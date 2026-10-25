"""A.15 / A.16 over HTTP: the four failure shapes an operator will actually hit.

The pass-through cases (a page of lines, filters applied) are covered by the
unit tests over `log_service`; what only shows up through the router is the
mapping from exception to status code, and that is what is pinned here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services import log_analysis_service
from app.services.auth_service import hash_password


@pytest.fixture(autouse=True)
def _fresh_limiter():
    """The limiter is process-wide by design; one test must not 429 the next."""
    log_analysis_service._limiter.reset()
    yield
    log_analysis_service._limiter.reset()


@pytest.fixture
def log_dir(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "pipeline-stdout.log").write_text("alpha\nbeta\n", encoding="utf-8")
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


def test_requires_auth(client):
    assert client.get("/api/v1/logs").status_code == 401


def test_limit_over_2000_is_invalid_parameter(client):
    response = client.get("/api/v1/logs?limit=5000", headers=_auth(client))
    # 400, not 422: the panel translates `code`, and FastAPI's 422 has none.
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"


def test_missing_log_dir_is_503_not_500(client, monkeypatch, tmp_path):
    monkeypatch.setattr(console_settings, "log_dir", str(tmp_path / "absent"))
    response = client.get("/api/v1/logs", headers=_auth(client))
    assert response.status_code == 503
    assert response.json()["code"] == "logs_unavailable"


def test_the_keyword_filter_reaches_the_reader(client):
    data = client.get("/api/v1/logs?q=beta", headers=_auth(client)).json()["data"]
    assert [line["text"] for line in data["lines"]] == ["beta"]
    assert data["sources"][0]["file"] == "console-stdout.log"


def test_analyze_refuses_a_window_over_24h(client):
    response = client.post(
        "/api/v1/logs/analyze",
        headers=_auth(client),
        json={"from": "2026-10-22T00:00:00Z", "to": "2026-10-24T01:00:00Z"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "log_window_too_large"


def test_analyze_without_the_loopback_llm_is_502(client, monkeypatch):
    def _boom(prompt, model):
        raise log_analysis_service.AnalysisUnavailable("loopback is off")

    monkeypatch.setattr(log_analysis_service, "_call_loopback", _boom)
    response = client.post(
        "/api/v1/logs/analyze",
        headers=_auth(client),
        json={"from": "2026-10-24T09:00:00Z", "to": "2026-10-24T10:00:00Z", "process": ["pipeline"]},
    )
    assert response.status_code == 502
    assert response.json()["code"] == "log_analysis_unavailable"
