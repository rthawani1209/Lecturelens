"""Spaced repetition, SM-2 style (the algorithm behind SuperMemo and Anki).

Each card keeps an ease factor and an interval. Remembering a card pushes it
further out; forgetting it brings it back in a minute and makes it a bit harder.
"""

from dataclasses import dataclass
from datetime import timedelta

GRADES = {"again": 0, "hard": 3, "good": 4, "easy": 5}
MIN_EASE = 1.3


@dataclass(frozen=True)
class State:
    ease: float = 2.5
    interval_d: int = 0
    reps: int = 0


def schedule(s: State, grade: str) -> tuple[State, timedelta]:
    """The card's new state and how long until it's due again."""
    g = GRADES[grade]
    if g == 0:
        return State(max(MIN_EASE, s.ease - 0.2), 0, 0), timedelta(minutes=1)

    if s.reps == 0:
        good = 1
    elif s.reps == 1:
        good = 3
    else:
        good = max(s.interval_d + 1, round(s.interval_d * s.ease))

    if g == 3:
        days = max(1, round(max(s.interval_d, 1) * 1.2))
        ease = s.ease - 0.15
    elif g == 4:
        days = good
        ease = s.ease
    else:
        days = max(good + 1, round(good * 1.3))
        ease = s.ease + 0.15
    return State(max(MIN_EASE, ease), days, s.reps + 1), timedelta(days=days)


def label(delta: timedelta) -> str:
    """Short text for the grade buttons: 1m, 3d, 2mo."""
    mins = delta.total_seconds() / 60
    if mins < 60:
        return f"{round(mins)}m"
    days = delta.days
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{round(days / 30)}mo"
    return f"{round(days / 365, 1):g}y"


def preview(s: State) -> dict[str, str]:
    return {g: label(schedule(s, g)[1]) for g in GRADES}
