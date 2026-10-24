"""Shared HTTP client for the console API.

Every API test needs the same three things: a mounted dist for the SPA fallback,
the temp database instead of the real one, and one seeded account. Putting it
here keeps each test file about its own endpoint.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password, throttle


@pytest.fixture(autouse=True)
def _fresh_throttle():
    """The login throttle is process-wide by design (one worker); without a
    reset, one test's failures would 429 the next test's login."""
    throttle._hits.clear()
    yield
    throttle._hits.clear()


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    app = create_app()
    # Same function object as `app.deps.get_db`, so the override really applies.
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    return TestClient(app)
