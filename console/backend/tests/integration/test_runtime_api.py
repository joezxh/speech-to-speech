"""A.14 over HTTP: 401, 404 for a profile that is not on disk, and 200 whenever
the pipeline is down or the driver is missing.

The last two are the point of the endpoint: a runtime panel that 500s exactly
when the runtime is broken has no reason to exist.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services import runtime_service
from app.services.auth_service import hash_password

PROFILE_YAML = "schema_version: 1\nblocks: {}\npipelines: {}\n"


@pytest.fixture(autouse=True)
def _clean_cache():
    runtime_service.invalidate()
    yield
    runtime_service.invalidate()


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "prod.yaml").write_text(PROFILE_YAML, encoding="utf-8")

    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr(console_settings, "param_config_dir", str(config_dir))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "missing.yaml"))
    monkeypatch.setattr(console_settings, "model_metrics_log", str(tmp_path / "model_metrics.log"))

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
    assert client.get("/api/v1/runtime/models").status_code == 401


def test_unknown_profile_is_404(client):
    response = client.get("/api/v1/runtime/models?profile=nope", headers=_auth(client))
    assert response.status_code == 404
    # Flat envelope: `code` carries the machine code (app.core.errors).
    assert response.json()["code"] == "unknown_profile"


def test_stopped_pipeline_still_answers_200(client, monkeypatch):
    monkeypatch.setattr(runtime_service, "_pipeline_running", lambda: False)
    response = client.get("/api/v1/runtime/models?profile=prod", headers=_auth(client))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stages"][0]["reasons"]["loaded"] == "pipeline_stopped"
    assert "pipeline_stopped" in data["alerts"]


def test_missing_nvidia_smi_does_not_500(client, monkeypatch):
    monkeypatch.setattr(
        runtime_service, "_gpu", lambda: {"available": False, "reason": "nvidia_smi_missing"}
    )
    response = client.get("/api/v1/runtime/models?profile=prod", headers=_auth(client))
    assert response.status_code == 200
    assert len(response.json()["data"]["stages"]) == 4


def test_window_is_bounded(client):
    headers = _auth(client)
    assert client.get("/api/v1/runtime/models?windowS=30", headers=headers).status_code == 422
    assert client.get("/api/v1/runtime/models?windowS=7200", headers=headers).status_code == 422
