"""A.5/A.6 over HTTP: the envelope, the role gate, and the two refusals."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.draft_repository import DraftRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"
BASE_YAML = "schema_version: 1\npipelines:\n  prod:\n    num_pipelines: 1\n"


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    from app.services import pool, publish_flow_service, restart_runner

    config = tmp_path / "config"
    config.mkdir()
    (config / "prod.yaml").write_text(BASE_YAML, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(config))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    monkeypatch.setattr(restart_runner, "restart", lambda: 1.0)
    monkeypatch.setattr(
        pool,
        "wait_healthy",
        lambda expected, timeout=180.0, interval=2.0: pool.HealthResult(
            ok=True,
            reason="ok",
            elapsed_s=1.0,
            attempts=1,
            pool=pool.PoolState(reachable=True, size=1),
        ),
    )
    monkeypatch.setattr(
        publish_flow_service,
        "render",
        lambda profile, values, environ=None: publish_flow_service.Rendered(
            text=BASE_YAML.replace("1\n", "1\n    seed: 2\n", 1),
            values=values,
            applied=sorted(values),
            expected_size=1,
            resolved={"pipelines": [profile]},
        ),
    )

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

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


def test_publish_returns_the_a5_shape(client, db_session):
    DraftRepository(db_session).put(
        "prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice"
    )
    headers = _auth(client)
    body = client.post("/api/v1/profiles/prod/publish", json={"note": "tune"}, headers=headers).json()
    assert body["data"]["status"] == "live"
    assert body["data"]["version"] == 1
    assert body["data"]["healthcheck"]["poolSize"] == 1
    assert body["data"]["auditId"]


def test_operator_cannot_publish(client, db_session):
    headers = _auth(client, username="bob")
    response = client.post("/api/v1/profiles/prod/publish", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_publishing_nothing_is_404_no_draft(client):
    response = client.post("/api/v1/profiles/prod/publish", json={}, headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "no_draft"


def test_an_env_field_is_409(client, db_session):
    DraftRepository(db_session).put(
        "prod", base_version=0, patch={"env.GPUSTACK_API_KEY": "gsk-x"}, actor="alice"
    )
    response = client.post("/api/v1/profiles/prod/publish", json={}, headers=_auth(client))
    assert response.status_code == 409
    assert response.json()["code"] == "env_requires_recreate"
    assert response.json()["detail"] == [{"var": "GPUSTACK_API_KEY"}]


def test_rolling_back_to_an_unknown_version_is_404(client):
    response = client.post(
        "/api/v1/profiles/prod/rollback", json={"targetVersion": 99}, headers=_auth(client)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_version"
