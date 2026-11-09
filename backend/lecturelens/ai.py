"""The one place that talks to Claude.

Routes ask for `get_llm()`, which is None when no API key is set; callers then use
their extractive fallback. Tests swap in a fake with `set_llm`. Every call goes
through `guard()` first, which enforces a per-user rate limit, a per-user daily
token budget and a site-wide monthly cap.
"""

import json
from typing import Protocol
from uuid import UUID

import anthropic
from fastapi import HTTPException

from .config import get_settings


class LLM(Protocol):
    def json(self, system: str, user: str, schema: dict, max_tokens: int) -> tuple[dict, int]:
        """Returns (data matching schema, tokens used)."""
        ...


class AIUnavailable(RuntimeError):
    pass


class Claude:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=60)
        self.model = model

    def json(self, system: str, user: str, schema: dict, max_tokens: int) -> tuple[dict, int]:
        try:
            res = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.APIError as e:
            raise AIUnavailable(str(e)) from e
        if res.stop_reason in ("refusal", "max_tokens"):
            raise AIUnavailable(f"model stopped: {res.stop_reason}")
        text = next((b.text for b in res.content if b.type == "text"), "")
        tokens = res.usage.input_tokens + res.usage.output_tokens
        return json.loads(text), tokens


_llm: LLM | None = None
_set = False


def set_llm(llm: LLM | None) -> None:
    """For tests: force a client (or None for the extractive path)."""
    global _llm, _set
    _llm, _set = llm, llm is not None


def get_llm() -> LLM | None:
    if _set:
        return _llm
    s = get_settings()
    return Claude(s.anthropic_api_key, s.ai_model) if s.anthropic_api_key else None


def guard(conn, user_id: UUID) -> None:
    """Raise 429 if this user (or the whole site) has used its allowance."""
    s = get_settings()
    # one call at a time per user, until the caller's transaction (and its record())
    # commits; otherwise a burst all reads the same "under the limit"
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('ai:' || %s))", (str(user_id),))
    row = conn.execute(
        """
        SELECT
          count(*) FILTER (WHERE user_id = %(u)s AND at > now() - interval '1 minute') AS minute,
          coalesce(sum(tokens) FILTER (WHERE user_id = %(u)s AND at > now() - interval '1 day'), 0)
            AS day,
          coalesce(sum(tokens) FILTER (WHERE at >= date_trunc('month', now())), 0) AS month
          FROM ai_calls WHERE at > now() - interval '32 days'
        """,
        {"u": user_id},
    ).fetchone()
    if row["month"] >= s.ai_monthly_tokens:
        raise HTTPException(429, "The AI budget for this month is used up. Search still works.")
    if row["day"] >= s.ai_daily_tokens:
        raise HTTPException(429, "You've hit today's AI limit. It resets in 24 hours.")
    if row["minute"] >= s.ai_per_minute:
        raise HTTPException(429, "That's a lot of questions at once. Try again in a minute.")


def record(conn, user_id: UUID, kind: str, tokens: int) -> None:
    conn.execute(
        "INSERT INTO ai_calls (user_id, kind, tokens) VALUES (%s, %s, %s)",
        (user_id, kind, tokens),
    )
