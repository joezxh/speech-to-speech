"""A.9 over HTTP: whitelist in this process, one hop to the pipeline, one audit row."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository
from app.services import hot_update_service
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    UserRepository(db_session).create("bob", hash_password("correct-horse"), "operator")
    return TestClient(app)


def _auth(client, username="alice"):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


class _Recorder:
    """Stands in for `httpx.post` so no test needs a running pipeline."""

    def __init__(self, status: int = 200, body=None) -> None:
        self.status = status
        self.body = {"updated": [], "failed": []} if body is None else body
        self.calls: list[dict] = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return httpx.Response(self.status, json=self.body)


def test_operator_trim_then_forward_and_audit(client, db_session, monkeypatch):
    recorder = _Recorder(body={"updated": ["s1"], "failed": []})
    monkeypatch.setattr(hot_update_service.httpx, "post", recorder)
    headers = _auth(client, "bob")

    refused = client.post(
        "/api/v1/sessions/update",
        json={"scope": "session", "target": "s1", "session": {"instructions": "be brief", "model": "x"}},
        headers=headers,
    )
    # A.9: `model` is a protocol echo (§2.2); reject it here, before any network hop.
    assert refused.status_code == 400
    assert refused.json()["code"] == "unsupported_field"
    assert refused.json()["detail"] == [{"field": "model"}]
    assert recorder.calls == []

    accepted = client.post(
        "/api/v1/sessions/update",
        json={"scope": "session", "target": "s1", "session": {"instructions": "be brief"}},
        headers=headers,
    )
    assert accepted.status_code == 200
    data = accepted.json()["data"]
    assert data["updated"] == ["s1"]
    assert data["failed"] == []
    assert data["auditId"]
    assert "只影响当前活跃连接" in data["hint"]

    call = recorder.calls[0]
    assert call["url"].endswith("/internal/sessions/update")
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["json"] == {"scope": "session", "target": "s1", "session": {"instructions": "be brief"}}

    rows, total = AuditRepository(db_session).list(profile="prod")
    assert total == 1
    row = rows[0]
    assert (row.actor, row.role, row.action, row.result) == ("bob", "operator", "session.update", "ok")
    assert row.fields == ["instructions"]


def test_empty_patch_is_400_invalid_parameter(client, monkeypatch):
    monkeypatch.setattr(hot_update_service.httpx, "post", _Recorder())
    response = client.post(
        "/api/v1/sessions/update", json={"scope": "all", "session": {}}, headers=_auth(client)
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"


def test_scope_pipeline_without_index_is_400(client, monkeypatch):
    monkeypatch.setattr(hot_update_service.httpx, "post", _Recorder())
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "pipeline", "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"


def test_missing_console_token_is_502_internal_token_missing(client, monkeypatch):
    monkeypatch.delenv("S2S_INTERNAL_TOKEN", raising=False)
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 502
    assert response.json()["code"] == "internal_token_missing"


def test_pipeline_rejecting_the_token_becomes_pipeline_token_missing(client, monkeypatch):
    monkeypatch.setattr(
        hot_update_service.httpx,
        "post",
        _Recorder(status=503, body={"error": {"code": "internal_token_missing"}}),
    )
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 502
    assert response.json()["code"] == "pipeline_token_missing"


def test_a_pipeline_without_the_route_is_501_not_implemented(client, monkeypatch):
    monkeypatch.setattr(hot_update_service.httpx, "post", _Recorder(status=404, body={}))
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 501
    assert response.json()["code"] == "not_implemented"


def test_pipeline_semantic_rejections_pass_through(client, monkeypatch):
    monkeypatch.setattr(
        hot_update_service.httpx,
        "post",
        _Recorder(
            status=422,
            body={"error": {"code": "invalid_session_type", "message": "transcription is not live"}},
        ),
    )
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "pipeline", "target": 0, "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_session_type"
    assert "transcription" in body["message"]
