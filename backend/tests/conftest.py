"""Shared test fixtures.

The database URL is switched to in-memory SQLite *before* any app module is
imported, so tests never touch backend/data/loanops.db.
"""

import os

os.environ["LOANOPS_DATABASE_URL"] = "sqlite://"

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import SessionLocal, reset_db  # noqa: E402
from app.main import app  # noqa: E402
from app.scripts.seed import SeedReport, run_seed  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db() -> Iterator[None]:
    reset_db()
    yield


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seed_report(db: Session) -> SeedReport:
    return run_seed(db, get_settings().seed_data_dir, trigger="test")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
