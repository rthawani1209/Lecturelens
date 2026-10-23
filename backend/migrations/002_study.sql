-- Things a student makes while studying: highlights, notes, flashcards, quizzes.
CREATE TABLE highlights (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lecture_id  uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    start_s     double precision NOT NULL,
    end_s       double precision NOT NULL,
    note        text NOT NULL DEFAULT '',
    shared      boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (end_s >= start_s)
);
CREATE INDEX highlights_user_idx ON highlights (user_id, lecture_id);

CREATE TABLE decks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id   uuid NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title       text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Each card keeps its spaced-repetition state inline (SM-2 style).
CREATE TABLE cards (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deck_id     uuid NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    front       text NOT NULL,
    back        text NOT NULL,
    segment_id  bigint REFERENCES segments(id) ON DELETE SET NULL,
    ease        real NOT NULL DEFAULT 2.5,
    interval_d  int NOT NULL DEFAULT 0,
    reps        int NOT NULL DEFAULT 0,
    due_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cards_due_idx ON cards (deck_id, due_at);

CREATE TABLE reviews (
    id          bigserial PRIMARY KEY,
    card_id     uuid NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    grade       smallint NOT NULL CHECK (grade BETWEEN 0 AND 5),
    reviewed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quiz_attempts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id   uuid NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    questions   jsonb NOT NULL,
    answers     jsonb NOT NULL DEFAULT '[]',
    score       real,
    created_at  timestamptz NOT NULL DEFAULT now()
);
