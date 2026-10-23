import os

import psycopg
import pytest

from lecturelens.db.migrate import migrate

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://lecturelens:lecturelens@localhost:5432/lecturelens_test"
)


def _db_available() -> bool:
    try:
        psycopg.connect(TEST_DB, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def database_url():
    if not _db_available():
        pytest.skip("Postgres not available (set TEST_DATABASE_URL)")
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    migrate(TEST_DB)
    os.environ["DATABASE_URL"] = TEST_DB
    from lecturelens.config import get_settings

    get_settings.cache_clear()
    return TEST_DB


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn
        conn.execute("TRUNCATE users, groups, courses CASCADE")
