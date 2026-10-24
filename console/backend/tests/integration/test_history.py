from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository
from app.repositories.version_repository import VersionRepository
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "prod.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(config))

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


def _seed_versions(db_session):
    repo = VersionRepository(db_session)
    first = repo.create(
        "prod", status="publishing", yaml_text="a: 1\n", env_sha256="x", note="first", author="alice"
    )
    repo.set_status(first, "live", duration_s=41.2)
    second = repo.create(
        "prod", status="publishing", yaml_text="a: 2\n", env_sha256="x", note="second", author="alice"
    )
    repo.set_status(second, "rolled_back", error_code="healthcheck_timeout", rolled_back_to=first.version)
    return first, second


def test_versions_are_newest_first_and_carry_no_yaml(client, db_session):
    first, second = _seed_versions(db_session)
    data = client.get("/api/v1/profiles/prod/versions", headers=_auth(client)).json()["data"]
    assert data["total"] == 2
    assert [row["version"] for row in data["list"]] == [second.version, first.version]
    newest = data["list"][0]
    assert newest["status"] == "rolled_back"
    assert newest["rolledBackTo"] == first.version
    assert newest["durationS"] is None
    # A.7 lists what the history table renders; the YAML is megabytes of nothing.
    assert "yamlText" not in newest and "yaml_text" not in newest
    assert isinstance(newest["createdAt"], str) and newest["createdAt"].endswith("Z")


def test_versions_paginate(client, db_session):
    _seed_versions(db_session)
    data = client.get(
        "/api/v1/profiles/prod/versions?page=2&pageSize=1", headers=_auth(client)
    ).json()["data"]
    assert (data["page"], data["pageSize"], data["total"], len(data["list"])) == (2, 1, 2, 1)


def test_versions_of_an_unknown_profile_is_404(client):
    response = client.get("/api/v1/profiles/nope/versions", headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_profile"


def test_audit_records_field_names_but_never_values(client, db_session):
    AuditRepository(db_session).record(
        actor="alice", role="admin", action="publish", profile="prod",
        fields=["vad.min_silence_ms", "llm.api_key"], version=1, duration_s=41.2, request_id="req-1",
    )
    entry = client.get("/api/v1/profiles/prod/audit", headers=_auth(client)).json()["data"]["list"][0]
    assert entry["fields"] == ["vad.min_silence_ms", "llm.api_key"]
    assert entry["role"] == "admin" and entry["requestId"] == "req-1"
    assert "values" not in entry and "detail" not in entry


def test_audit_field_filter_narrows_the_result(client, db_session):
    repo = AuditRepository(db_session)
    repo.record(actor="alice", role="admin", action="draft.patch", profile="prod", fields=["vad.min_silence_ms"])
    repo.record(actor="alice", role="admin", action="draft.patch", profile="prod", fields=["stt.language"])
    data = client.get(
        "/api/v1/profiles/prod/audit?field=vad.min_silence_ms", headers=_auth(client)
    ).json()["data"]
    assert data["total"] == 1
    assert data["list"][0]["fields"] == ["vad.min_silence_ms"]
