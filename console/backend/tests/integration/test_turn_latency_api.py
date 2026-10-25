"""A.17 over HTTP: the reason codes, and the two 400s that keep the panel honest.

The panel's whole value is that "no turns" and "index is behind" and "the log is
gone" are three different sentences. Each one is pinned here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories import turn_latency_repository as repo
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password


@pytest.fixture
def log_dir(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    # `sources` is what separates `log_missing` from every other reason, so the
    # file has to exist for the other four cases to be reachable.
    (directory / "pipeline-stdout.log").write_text("boot\n", encoding="utf-8")
    return directory


@pytest.fixture
def client(db_session, monkeypatch, tmp_path, log_dir):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr(console_settings, "log_dir", str(log_dir))
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    return TestClient(app)


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _row(*, key: str = "k1", logged_at: datetime | None = None, ingested_at: datetime | None = None):
    moment = datetime.now(UTC)
    return {
        "response_key": key,
        "turn_revision": 0,
        "turn_id": "t1",
        "source": "realtime",
        "status": "completed",
        "smart_status": "hold",
        "e2e_ms": 6260,
        "stt_ms": 120,
        "llm_ms": 800,
        "tts_ttfa_ms": 300,
        "vad_decision_ms": 40,
        "hold_ms": None,
        "logged_at": logged_at or moment,
        "raw_offset": 0,
        "ingested_at": ingested_at or moment,
    }


def test_requires_auth(client):
    assert client.get("/api/v1/turn-latency").status_code == 401


def test_unknown_status_is_refused(client):
    response = client.get("/api/v1/turn-latency?status=bogus", headers=_auth(client))
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"


def test_an_empty_window_is_not_an_error(client, db_session):
    # One row outside the window keeps `lagS` fresh, so the reason really is
    # "this window has nothing" rather than "the indexer never ran".
    repo.upsert_many(db_session, [_row(logged_at=datetime.now(UTC) - timedelta(hours=3))])
    response = client.get("/api/v1/turn-latency", headers=_auth(client))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["count"] == 0
    assert data["summary"]["e2e"] == {"p50Ms": None, "p95Ms": None, "maxMs": None}
    assert data["reasons"]["summary"] == "no_turn_rows"
    assert data["rows"] == []


def test_a_stale_index_is_labelled_but_not_hidden(client, db_session):
    # `ingested_at` is the indexer's high-water mark: five minutes old here.
    stale = datetime.now(UTC) - timedelta(minutes=5)
    repo.upsert_many(db_session, [_row(logged_at=stale, ingested_at=stale)])
    data = client.get("/api/v1/turn-latency", headers=_auth(client)).json()["data"]
    assert data["reasons"]["summary"] == "index_lag"
    assert data["index"]["lagS"] >= 300
    # Labelled, not hidden: the row is still returned.
    assert [row["responseKey"] for row in data["rows"]] == ["k1"]


def test_limit_over_500_is_invalid_parameter(client):
    response = client.get("/api/v1/turn-latency?limit=501", headers=_auth(client))
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"
