from datetime import timedelta

import pytest

from lecturelens.study.srs import MIN_EASE, State, label, preview, schedule


def _days(s, *grades):
    out = []
    for g in grades:
        s, wait = schedule(s, g)
        out.append(wait)
    return s, out


def test_good_answers_space_out():
    s, waits = _days(State(), "good", "good", "good", "good")
    assert [w.days for w in waits] == [1, 3, 8, 20]  # 3 * 2.5 = 7.5 -> 8, 8 * 2.5 = 20
    assert s.reps == 4 and s.ease == 2.5


def test_again_brings_it_back_in_a_minute_and_makes_it_harder():
    s, _ = _days(State(), "good", "good")
    s, wait = schedule(s, "again")
    assert wait == timedelta(minutes=1)
    assert s.reps == 0 and s.ease == pytest.approx(2.3)
    _, wait = schedule(s, "good")  # starts over
    assert wait.days == 1


def test_easy_beats_good_beats_hard():
    s, _ = _days(State(), "good", "good")
    hard, good, easy = (schedule(s, g)[1] for g in ("hard", "good", "easy"))
    assert hard < good < easy


def test_ease_has_a_floor():
    s = State()
    for _ in range(20):
        s, _ = schedule(s, "again")
    assert s.ease == MIN_EASE


def test_button_labels():
    assert preview(State()) == {"again": "1m", "hard": "1d", "good": "1d", "easy": "2d"}
    assert label(timedelta(days=45)) == "2mo"
    assert label(timedelta(days=400)) == "1.1y"
