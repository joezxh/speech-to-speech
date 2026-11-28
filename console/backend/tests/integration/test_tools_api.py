"""tools 管理面 HTTP 契约：CRUD、内置可见性、权限边界（Task 3 RED）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
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


def _seed_builtins(db_session):
    from app.models.tool import ConsoleTool

    for tool_id, name, kind, scope, enabled in [
        ("tool-search", "Web search", "web_search", "global", True),
        ("tool-calendar", "Calendar", "calendar", "global", False),
        ("tool-weather", "Weather", "weather", "global", True),
        ("tool-kb", "Knowledge base", "kb", "tenant", False),
    ]:
        db_session.add(
            ConsoleTool(
                id=tool_id, name=name, type=kind, scope=scope, enabled=enabled,
                builtin=True, owner="", params=[], config={},
            )
        )
    db_session.commit()


def _body(**overrides) -> dict:
    payload = {
        "name": "My hook",
        "type": "http",
        "description": "custom",
        "endpoint": "https://example.com/hook",
        "method": "POST",
        "scope": "tenant",
        "params": [{"k": "q", "t": "string", "req": True}],
    }
    payload.update(overrides)
    return payload


def test_list_shows_4_builtins_to_operator(client, db_session):
    _seed_builtins(db_session)
    response = client.get("/api/v1/tools", headers=_auth(client, "op"))
    assert response.status_code == 200
    assert len(response.json()["data"]["tools"]) == 4


def test_admin_crud_roundtrip(client, db_session):
    _seed_builtins(db_session)
    headers = _auth(client)
    created = client.post("/api/v1/tools", json=_body(), headers=headers)
    assert created.status_code == 200
    tool_id = created.json()["data"]["id"]

    assert client.get(f"/api/v1/tools/{tool_id}", headers=headers).json()["data"]["name"] == "My hook"
    updated = client.put(f"/api/v1/tools/{tool_id}", json={"description": "changed"}, headers=headers)
    assert updated.json()["data"]["description"] == "changed"
    copied = client.post(f"/api/v1/tools/{tool_id}/copy", headers=headers)
    assert copied.status_code == 200
    assert copied.json()["data"]["name"] == "My hook Copy"
    assert client.delete(f"/api/v1/tools/{tool_id}", headers=headers).status_code == 204


def test_duplicate_name_is_409(client, db_session):
    _seed_builtins(db_session)
    headers = _auth(client)
    assert client.post("/api/v1/tools", json=_body(), headers=headers).status_code == 200
    assert client.post("/api/v1/tools", json=_body(), headers=headers).status_code == 409


def test_operator_can_toggle_builtin(client, db_session):
    _seed_builtins(db_session)
    response = client.put(
        "/api/v1/tools/tool-search/enabled", json={"enabled": False}, headers=_auth(client, "op")
    )
    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False


def test_operator_can_create_own_tenant_tool(client, db_session):
    _seed_builtins(db_session)
    response = client.post("/api/v1/tools", json=_body(scope="tenant"), headers=_auth(client, "op"))
    assert response.status_code == 200
    assert response.json()["data"]["owner"] == "op"


def test_operator_cannot_create_global_tool(client, db_session):
    _seed_builtins(db_session)
    response = client.post("/api/v1/tools", json=_body(scope="global"), headers=_auth(client, "op"))
    assert response.status_code == 403


def test_operator_cannot_delete_builtin(client, db_session):
    _seed_builtins(db_session)
    assert client.delete("/api/v1/tools/tool-search", headers=_auth(client, "op")).status_code == 403


def test_invoke_returns_envelope(client, db_session):
    _seed_builtins(db_session)
    response = client.post(
        "/api/v1/tools/tool-search/invoke",
        json={"arguments": {"query": "hello"}},
        headers=_auth(client, "op"),
    )
    assert response.status_code == 200
    assert response.json()["data"]["mode"] in ("live", "demo")
