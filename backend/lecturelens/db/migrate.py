"""Tiny migration runner: applies backend/migrations/*.sql in order, once each.

Usage: python -m lecturelens.db.migrate
"""

from pathlib import Path

import psycopg

from ..config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def migrate(database_url: str | None = None) -> list[str]:
    url = database_url or get_settings().database_url
    applied: list[str] = []
    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        # serialize concurrent runs (api + worker starting together)
        conn.execute("SELECT pg_advisory_xact_lock(4242)")
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
        conn.commit()
    return applied


if __name__ == "__main__":
    names = migrate()
    print("applied:", ", ".join(names) if names else "nothing (up to date)")
