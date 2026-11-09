"""Study: flashcard decks per lecture with spaced repetition, and Ask."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ... import access, ai
from ...db import connection
from ...study import ask as asking
from ...study import cards as making
from ...study.retrieve import retrieve
from ...study.srs import GRADES, State, preview, schedule
from ..deps import require_user
from .media import media_url

router = APIRouter(tags=["study"])


class DeckLecture(BaseModel):
    id: UUID
    title: str
    week: int | None
    position: int
    cards: int
    due: int
    started: bool


class StudyWeek(BaseModel):
    week: int | None
    lectures: list[DeckLecture]


class CardOut(BaseModel):
    id: UUID
    front: str
    back: str
    t_s: float | None
    thumb_url: str | None
    due_at: datetime
    reps: int
    preview: dict[str, str]


class DeckOut(BaseModel):
    lecture_id: UUID
    course_id: UUID
    lecture_title: str
    course_code: str
    mode: str  # always "claude"; old decks said "cloze"
    total: int
    due: int
    cards: list[CardOut]  # due ones first, then the rest by due date


class ReviewIn(BaseModel):
    grade: str = Field(pattern="^(again|hard|good|easy)$")


class AskIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # "   " is empty

    question: str = Field(min_length=2, max_length=500)


class Source(BaseModel):
    n: int
    start_s: float
    text: str


class AskOut(BaseModel):
    covered: bool
    mode: str
    sentences: list[dict]
    sources: list[Source]


def _readable_lecture(conn, user: dict, lecture_id: UUID) -> dict:
    lec = access.lecture(conn, user["id"], lecture_id)
    if lec is None:
        raise HTTPException(404)
    return lec


def _ready(lec: dict) -> None:
    if lec["status"] == "failed":
        raise HTTPException(409, "This lecture didn't finish processing.")
    if lec["status"] != "ready":
        raise HTTPException(409, "This lecture is still processing.")


@router.get("/study/courses/{course_id}", response_model=list[StudyWeek])
def course_decks(course_id: UUID, user: dict = Depends(require_user)) -> list[dict]:
    """The sidebar: a course's ready lectures by week, with this user's card counts."""
    with connection() as conn:
        if access.course(conn, user["id"], course_id) is None:
            raise HTTPException(404)
        rows = conn.execute(
            """
            SELECT l.id, l.title, l.week, l.position, d.id IS NOT NULL AS started,
                   count(c.id) AS cards, count(c.id) FILTER (WHERE c.due_at <= now()) AS due
              FROM lectures l
              LEFT JOIN decks d ON d.lecture_id = l.id AND d.user_id = %(u)s
              LEFT JOIN cards c ON c.deck_id = d.id
             WHERE l.course_id = %(c)s AND l.status = 'ready'
             GROUP BY l.id, d.id
             ORDER BY l.week NULLS LAST, l.position
            """,
            {"u": user["id"], "c": course_id},
        ).fetchall()
    weeks: dict[int | None, list[dict]] = {}
    for r in rows:
        weeks.setdefault(r["week"], []).append(dict(r))
    return [{"week": w, "lectures": lecs} for w, lecs in weeks.items()]


def _deck(conn, user: dict, lec: dict) -> dict:
    deck = conn.execute(
        "SELECT * FROM decks WHERE user_id = %s AND lecture_id = %s", (user["id"], lec["id"])
    ).fetchone()
    if deck is not None:
        return deck

    lines = conn.execute(
        "SELECT start_s, end_s, text FROM transcript_lines WHERE lecture_id = %s ORDER BY start_s",
        (lec["id"],),
    ).fetchall()
    if not lines:
        raise HTTPException(409, "This lecture has no transcript yet.")
    llm = ai.get_llm()
    if llm is None:
        # cards cut from the transcript without a model were mostly small talk
        raise HTTPException(503, "Study cards need the AI model, and it isn't switched on here.")
    ai.guard(conn, user["id"])
    # guard() queues this user's calls; if a second open waited there, the first
    # one has written the deck by now, so don't pay the model twice
    deck = conn.execute(
        "SELECT * FROM decks WHERE user_id = %s AND lecture_id = %s", (user["id"], lec["id"])
    ).fetchone()
    if deck is not None:
        return deck
    try:
        made, tokens = making.write(llm, lec["title"], lines, lec["duration_s"])
    except ai.AIUnavailable:
        made, tokens = [], 0
    ai.record(conn, user["id"], "cards", tokens)
    if not made:
        conn.commit()  # keep the usage record; nothing is saved, so opening again retries
        raise HTTPException(503, "Couldn't write cards for this lecture just now. Try again.")

    with conn.transaction():
        deck = conn.execute(
            """
            INSERT INTO decks (user_id, course_id, lecture_id, title, mode)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, lecture_id) DO NOTHING RETURNING *
            """,
            (user["id"], lec["course_id"], lec["id"], lec["title"], "claude"),
        ).fetchone()
        if deck is None:  # a second request got there first
            return conn.execute(
                "SELECT * FROM decks WHERE user_id = %s AND lecture_id = %s",
                (user["id"], lec["id"]),
            ).fetchone()
        for i, c in enumerate(made):
            conn.execute(
                """
                INSERT INTO cards (deck_id, front, back, t_s, position, segment_id)
                VALUES (%s, %s, %s, %s, %s, (SELECT id FROM segments WHERE lecture_id = %s
                        AND start_s <= %s ORDER BY start_s DESC LIMIT 1))
                """,
                (deck["id"], c["front"], c["back"], c["t_s"], i, lec["id"], c["t_s"]),
            )
    return deck


def _deck_out(conn, lec: dict, deck: dict) -> dict:
    course = conn.execute(
        "SELECT code, title FROM courses WHERE id = %s", (lec["course_id"],)
    ).fetchone()
    rows = conn.execute(
        """
        SELECT c.*, (SELECT thumb_key FROM frames f WHERE f.lecture_id = %(l)s
                      AND f.t_s <= coalesce(c.t_s, 0) + 2 ORDER BY f.t_s DESC LIMIT 1) AS thumb_key
          FROM cards c WHERE c.deck_id = %(d)s
         ORDER BY c.due_at > now(), CASE WHEN c.due_at <= now() THEN c.position END, c.due_at
        """,
        {"l": lec["id"], "d": deck["id"]},
    ).fetchall()
    now = datetime.now(UTC)
    cards = [
        {
            **r,
            "thumb_url": media_url(r["thumb_key"]) if r["thumb_key"] else None,
            "preview": preview(State(r["ease"], r["interval_d"], r["reps"])),
        }
        for r in rows
    ]
    return {
        "lecture_id": lec["id"],
        "course_id": lec["course_id"],
        "lecture_title": lec["title"],
        "course_code": course["code"] or course["title"],
        "mode": deck["mode"],
        "total": len(cards),
        "due": sum(c["due_at"] <= now for c in cards),
        "cards": cards,
    }


@router.post("/lectures/{lecture_id}/deck", response_model=DeckOut)
def open_deck(lecture_id: UUID, user: dict = Depends(require_user)) -> dict:
    """The user's deck for a lecture, written the first time it's opened."""
    with connection() as conn:
        lec = _readable_lecture(conn, user, lecture_id)
        _ready(lec)
        deck = _deck(conn, user, lec)
        return _deck_out(conn, lec, deck)


@router.post("/cards/{card_id}/review", response_model=CardOut)
def review(card_id: UUID, body: ReviewIn, user: dict = Depends(require_user)) -> dict:
    with connection() as conn, conn.transaction():
        card = conn.execute(
            """
            SELECT c.* FROM cards c JOIN decks d ON d.id = c.deck_id
             WHERE c.id = %s AND d.user_id = %s FOR UPDATE OF c
            """,
            (card_id, user["id"]),
        ).fetchone()
        if card is None:
            raise HTTPException(404)
        state, wait = schedule(State(card["ease"], card["interval_d"], card["reps"]), body.grade)
        row = conn.execute(
            """
            UPDATE cards SET ease = %s, interval_d = %s, reps = %s, due_at = now() + %s
             WHERE id = %s RETURNING *
            """,
            (state.ease, state.interval_d, state.reps, wait, card_id),
        ).fetchone()
        conn.execute(
            "INSERT INTO reviews (card_id, user_id, grade) VALUES (%s, %s, %s)",
            (card_id, user["id"], GRADES[body.grade]),
        )
    return {**row, "thumb_url": None, "preview": preview(state)}


@router.post("/lectures/{lecture_id}/ask", response_model=AskOut)
def ask(lecture_id: UUID, body: AskIn, user: dict = Depends(require_user)) -> dict:
    with connection() as conn:
        _ready(_readable_lecture(conn, user, lecture_id))
        llm = ai.get_llm()
        if llm is not None:  # quoting the lecture back costs nothing, so it isn't limited
            ai.guard(conn, user["id"])
        excerpts = retrieve(conn, lecture_id, body.question)
        answer = None
        if llm is not None and excerpts:
            try:
                answer = asking.with_claude(llm, body.question, excerpts)
            except ai.AIUnavailable:
                answer = None
        if answer is None:
            answer = asking.extractive(body.question, excerpts)
        if answer.mode != "extractive" or answer.tokens:
            ai.record(conn, user["id"], "ask", answer.tokens)
    cited = {c for s in answer.sentences for c in s["cites"]}
    return {
        "covered": answer.covered,
        "mode": answer.mode,
        "sentences": answer.sentences,
        "sources": [
            {"n": e.n, "start_s": e.start_s, "text": e.text} for e in excerpts if e.n in cited
        ],
    }
