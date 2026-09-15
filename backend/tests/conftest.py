"""Shared test fixtures.

Tests run against a dedicated ``app_test`` database (derived from ``DATABASE_URL``)
so they never touch development data. The database is created and migrated on
first use; every table is truncated at the end of the session.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings

# --- redirect the whole app at the test database BEFORE the engine is created ---
_dev_url = str(settings.DATABASE_URL)
_base, _dev_db = _dev_url.rsplit("/", 1)
TEST_DB_NAME = f"{_dev_db.split('?')[0]}_test"
settings.DATABASE_URL = f"{_base}/{TEST_DB_NAME}"  # type: ignore[assignment]


def _ensure_test_database() -> None:
    from sqlalchemy import create_engine

    admin = create_engine(f"{_base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}
        ).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


_ensure_test_database()

from app.core.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.storage import InMemoryStorage  # noqa: E402
from app.services.vectors import InMemoryVectorStore  # noqa: E402
from tests.utils.user import authentication_token_from_email  # noqa: E402
from tests.utils.utils import get_superuser_token_headers  # noqa: E402

# Signing in costs an emailed code, and the product allows only a handful per
# quarter hour. A test run signs in far more often than any person would, so the
# allowance is lifted here; the limit itself is covered in test_login.py, which
# sets it back for the duration of that test.
settings.AUTH_CODE_MAX_SENDS = 10_000

TABLES_TO_TRUNCATE = [
    "askmessage",
    "askconversation",
    "cleanuptask",
    "workerheartbeat",
    "importjob",
    "embeddingjob",
    "documentchunk",
    "documentshare",
    "attachment",
    "document",
    "folder",
    "namespacemember",
    "namespace",
    "apikey",
    "user",
    # Emptied with the rest; `init_db` puts the default group back at the start
    # of every session, which is what makes limit resolution work on run two.
    "usergroup",
]


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    with Session(engine) as session:
        init_db(session)
        yield session
        session.execute(
            text(
                "TRUNCATE "
                + ", ".join(f'"{t}"' for t in TABLES_TO_TRUNCATE)
                + " CASCADE"
            )
        )
        session.commit()


@pytest.fixture(scope="session", autouse=True)
def fake_services() -> Generator[tuple[InMemoryStorage, InMemoryVectorStore]]:
    storage = InMemoryStorage()
    vectors = InMemoryVectorStore()
    app.state.storage = storage
    app.state.vectors = vectors
    yield storage, vectors


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    """One administrator session per module.

    Shared deliberately: signing in now costs an emailed code, and the product
    only allows a handful of those per quarter hour. A test that needs to change
    a password must therefore do it to an account of its own, not this one.
    """
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email="test@example.com", db=db
    )
