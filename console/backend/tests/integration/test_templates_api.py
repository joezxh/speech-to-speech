"""模板管理面 HTTP 契约：CRUD、筛选、权限码与审计分类（template.*）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.models.param_audit import ParamAudit
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    UserRepository(db_session).create("op", hash_password("correct-horse"), "operator")
    yield TestClient(app)


def _auth(client: TestClient, username: str = "alice") -> dict:
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _body(**overrides) -> dict:
    payload = {
        "name": "GPU 24G pipeline baseline",
        "effect": "restart",
        "platform": "gpu",
        "status": "draft",
        "scene": "edge",
        "minVramGb": 24,
        "fields": [{"key": "llm.model_name", "value": "qwen3-8b"}],
        "desc": "publish + restart",
    }
    payload.update(overrides)
    return payload


def test_crud_roundtrip(client):
    headers = _auth(client)
    created = client.post("/api/v1/templates", json=_body(), headers=headers)
    assert created.status_code == 200
    data = created.json()["data"]
    assert data["fields"][0]["patch"] == "llm.model_name"
    assert data["scene"] == "edge"

    got = client.get(f"/api/v1/templates/{data['id']}", headers=headers).json()["data"]
    assert got["name"] == "GPU 24G pipeline baseline"

    listed = client.get("/api/v1/templates", params={"q": "baseline"}, headers=headers).json()["data"]
    assert listed["total"] == 1
    assert client.get("/api/v1/templates", params={"effect": "runtime"}, headers=headers).json()["data"]["total"] == 0

    updated = client.put(f"/api/v1/templates/{data['id']}", json={"status": "published"}, headers=headers)
    assert updated.json()["data"]["status"] == "published"

    deleted = client.delete(f"/api/v1/templates/{data['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/templates/{data['id']}", headers=headers).status_code == 404


def test_duplicate_name_is_409(client):
    headers = _auth(client)
    assert client.post("/api/v1/templates", json=_body(), headers=headers).status_code == 200
    conflict = client.post("/api/v1/templates", json=_body(), headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "conflict"


def test_unknown_field_key_is_400_when_catalog_mounted(client, monkeypatch):
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"
    monkeypatch.setattr("app.config.console.param_catalog_path", str(fixture))
    headers = _auth(client)
    bad = client.post(
        "/api/v1/templates", json=_body(fields=[{"key": "nope.nope"}]), headers=headers
    )
    assert bad.status_code == 400


def test_operator_can_read_but_not_write(client):
    read = client.get("/api/v1/templates", headers=_auth(client, "op"))
    assert read.status_code == 200
    write = client.post("/api/v1/templates", json=_body(), headers=_auth(client, "op"))
    assert write.status_code == 403


def test_audit_rows_carry_template_category(client, db_session):
    headers = _auth(client)
    data = client.post("/api/v1/templates", json=_body(), headers=headers).json()["data"]
    client.delete(f"/api/v1/templates/{data['id']}", headers=headers)
    actions = {row.action for row in db_session.query(ParamAudit).all()}
    assert {"template.create", "template.delete"} <= actions
    categories = client.get("/api/v1/audit", params={"category": "template"}, headers=headers).json()["data"]
    assert categories["total"] >= 2
    assert {row["category"] for row in categories["items"]} == {"template"}
