"""Task 16（2026-11-17 原型对齐计划）——realtime 一次性短票据（60s TTL，一次性）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services import realtime_ticket
from app.services.auth_service import hash_password


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    return TestClient(app)


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_issue_requires_jwt(client):
    assert client.post("/api/v1/realtime/ticket").status_code == 401


def test_consume_once_then_gone(client):
    response = client.post("/api/v1/realtime/ticket", headers=_auth(client))
    assert response.status_code == 200
    ticket = response.json()["data"]["ticket"]

    identity = realtime_ticket.consume(ticket)
    assert identity is not None
    assert identity.username == "alice"
    assert identity.role == "admin"

    assert realtime_ticket.consume(ticket) is None, "一次性：消费即焚"


def test_expired_ticket_is_none(monkeypatch):
    ticket = realtime_ticket.issue("alice", "admin")
    # TTL 60s：把整张表的时间戳拨回过去，等效时间旅行。
    for key, (username, role, issued_at) in list(realtime_ticket._TICKETS.items()):
        realtime_ticket._TICKETS[key] = (username, role, issued_at - 61)
    assert realtime_ticket.consume(ticket) is None


def test_issue_returns_urlsafe_token(client):
    response = client.post("/api/v1/realtime/ticket", headers=_auth(client))
    ticket = response.json()["data"]["ticket"]
    assert len(ticket) >= 22, "128bit urlsafe → ≥22 字符"
    assert realtime_ticket.consume(ticket) is not None
