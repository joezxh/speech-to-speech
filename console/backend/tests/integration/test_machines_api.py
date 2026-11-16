"""machines 路由 M1–M9（用户 JWT + console:machine:* 权限码）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.repositories.machine_repository import MachineRepository
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


def _auth(client, username="alice"):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _create(client, machine_id="node-a01", **overrides):
    payload = {"machineId": machine_id, "addr": "10.12.0.31", "role": "agent", "gpu": "L40S"}
    payload.update(overrides)
    return client.post("/api/v1/machines", json=payload, headers=_auth(client))


def test_m3_create_returns_register_code_once(client, db_session):
    response = _create(client)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["machine"]["machineId"] == "node-a01"
    assert data["machine"]["state"] == "pending_register"
    assert data["registerCode"]
    row = MachineRepository(db_session).get("node-a01")
    assert row.register_code_hash
    assert data["registerCode"] != row.register_code_hash


def test_m3_duplicate_is_conflict(client):
    assert _create(client).status_code == 200
    assert _create(client).status_code == 409


def test_m1_list_and_m2_detail(client):
    _create(client)
    listed = client.get("/api/v1/machines", headers=_auth(client)).json()["data"]["machines"]
    assert [m["machineId"] for m in listed] == ["node-a01"]
    detail = client.get("/api/v1/machines/node-a01", headers=_auth(client))
    assert detail.status_code == 200
    assert detail.json()["data"]["machineId"] == "node-a01"
    assert client.get("/api/v1/machines/ghost", headers=_auth(client)).status_code == 404


def test_m4_partial_update_and_m5_delete(client, db_session):
    _create(client)
    updated = client.put(
        "/api/v1/machines/node-a01",
        json={"addr": "10.12.0.32", "gpuTotalGb": 48},
        headers=_auth(client),
    )
    assert updated.json()["data"]["addr"] == "10.12.0.32"
    assert updated.json()["data"]["gpuTotalGb"] == 48

    assert (
        client.delete("/api/v1/machines/node-a01", headers=_auth(client)).status_code == 204
    )
    assert MachineRepository(db_session).get("node-a01") is None
    assert client.delete("/api/v1/machines/node-a01", headers=_auth(client)).status_code == 404


def test_m6_m7_workloads_roundtrip(client):
    _create(client)
    replaced = client.put(
        "/api/v1/machines/node-a01/workloads",
        json={"workloads": [{"kind": "pipeline", "port": 8765, "publicAddr": "10.12.0.31:8765"}]},
        headers=_auth(client),
    )
    assert replaced.status_code == 200
    listed = client.get("/api/v1/machines/node-a01/workloads", headers=_auth(client))
    assert [w["kind"] for w in listed.json()["data"]["workloads"]] == ["pipeline"]


def test_m8_register_test_endpoint(client):
    response = client.post(
        "/api/v1/machines/register-test",
        json={"machineId": "node-x", "addr": "10.0.0.9", "simulate": True},
        headers=_auth(client),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    steps = {step["key"]: step["state"] for step in data["steps"]}
    assert steps == {"step1": "pass", "step2": "fail", "step3": "fail"}
    assert data["ok"] is False


def test_m9_auto_register_endpoint(client, db_session):
    response = client.post(
        "/api/v1/machines/auto-register",
        json={"clusterId": "default", "addr": "10.0.0.10"},
        headers=_auth(client),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"] == "pending_register"
    assert MachineRepository(db_session).get(data["machineId"]).registry_mode == "auto"


def test_operator_cannot_create_or_delete(client):
    response = client.post(
        "/api/v1/machines",
        json={"machineId": "op-test-2"},
        headers=_auth(client, "op"),
    )
    assert response.status_code == 403
    assert (
        client.delete("/api/v1/machines/node-a01", headers=_auth(client, "op")).status_code
        == 403
    )
    # 查询允许
    assert client.get("/api/v1/machines", headers=_auth(client, "op")).status_code == 200
