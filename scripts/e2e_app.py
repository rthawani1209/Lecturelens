"""The API for browser tests, with a stand-in for Claude so decks work offline.

The stand-in turns the first few transcript lines into cards. Anything else it's
asked (Ask's answers) fails, so Ask quotes the lecture as it does with no model.
"""

import re

from lecturelens import ai
from lecturelens.api.main import app

_LINE = re.compile(r"^\[(\d+):(\d\d)\] (.+)$", re.M)


class StandIn:
    def json(self, system: str, user: str, schema: dict, max_tokens: int) -> tuple[dict, int]:
        if "cards" not in schema["properties"]:
            raise ai.AIUnavailable("the stand-in only writes cards")
        cards = [
            {
                "front": f"What does the lecture explain at {m}:{s}?",
                "back": text,
                "t_s": int(m) * 60 + int(s),
            }
            for m, s, text in _LINE.findall(user)[:4]
        ]
        return {"cards": cards}, 100


ai.set_llm(StandIn())
__all__ = ["app"]
