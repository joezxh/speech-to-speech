"""机器命令通道端到端：用户下发 → agent 拉取 → 回执 → 前端回显。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.models.param_instance import ParamInstance
from app.repositories.user_repository import UserRepository
from app.services import machine_service
from app.services.machine_service import MachineCreate
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


def _machine_and_token(client, db_session, machine_id="node-a01"):
    _, code = machine_service.create_machine(
        db_session, MachineCreate(machineId=machine_id, addr="10.0.0.9"), actor="alice"
    )
    response = client.post(
        "/api/v1/agent/register",
        json={
            "register_code": code,
            "machine": {"machine_id": machine_id, "addr": "10.0.0.9"},
            "workloads": [],
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["machine_token"]


def _issue(client, headers, kind="drain", **payload):
    return client.post(
        "/api/v1/machines/node-a01/commands",
        json={"kind": kind, **payload},
        headers=headers,
    )


def test_config_restart_is_supported_command(client, db_session):
    _machine_and_token(client, db_session)
    created = _issue(client, _auth(client), kind="config_restart")
    assert created.status_code == 200
    assert created.json()["data"]["kind"] == "config_restart"


def test_model_reload_payload_survives_issue_pull_and_report(client, db_session):
    token = _machine_and_token(client, db_session)
    auth = _auth(client)
    payload = {
        "modules": ["asr", "tts"],
        "scope": "unit",
        "unitIndex": 0,
        "drain": True,
        "drainTimeoutMs": 6000,
    }

    created = _issue(client, auth, kind="model_reload", payload=payload)
    assert created.status_code == 200

    pulled = client.get("/api/v1/agent/commands", headers={"Authorization": f"Bearer {token}"})
    assert pulled.status_code == 200
    command = pulled.json()["data"][0]
    assert command["kind"] == "model_reload"
    assert command["payload"] == payload

    result = {
        "status": "accepted",
        "stage": "queued",
        "progress": [{"stage": "maintenance_set", "unitIndex": 0}],
    }
    reported = client.post(
        f"/api/v1/agent/commands/{command['command_id']}/report",
        json={"ok": True, "result": result},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reported.status_code == 200
    row = client.get("/api/v1/machines/node-a01/commands", headers=auth).json()["data"][0]
    assert row["status"] == "succeeded"
    assert row["result"] == result


def test_admin_can_issue_and_list_commands(client, db_session):
    _machine_and_token(client, db_session)
    auth = _auth(client)

    created = _issue(client, auth)
    assert created.status_code == 200
    assert created.json()["data"]["status"] == "pending"

    listed = client.get("/api/v1/machines/node-a01/commands", headers=auth)
    assert listed.status_code == 200
    assert [row["kind"] for row in listed.json()["data"]] == ["drain"]


def test_operator_cannot_issue_commands(client, db_session):
    _machine_and_token(client, db_session)
    assert _issue(client, _auth(client, "op")).status_code == 403


def test_issue_rejects_unknown_machine_kind_and_duplicate(client, db_session):
    _machine_and_token(client, db_session)
    auth = _auth(client)
    assert client.post(
        "/api/v1/machines/missing/commands", json={"kind": "drain"}, headers=auth
    ).status_code == 404
    assert _issue(client, auth, kind="rm -rf").status_code == 400
    assert _issue(client, auth).status_code == 200
    assert _issue(client, auth).status_code == 409


def test_agent_pull_and_report_roundtrip(client, db_session):
    token = _machine_and_token(client, db_session)
    auth = _auth(client)
    command_id = _issue(client, auth, kind="health_check", serviceId="asr").json()["data"]["commandId"]
    agent_auth = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/agent/commands").status_code == 401
    pulled = client.get("/api/v1/agent/commands", headers=agent_auth)
    assert pulled.status_code == 200
    command = pulled.json()["data"][0]
    assert command["command_id"] == command_id
    assert command["payload"] == {"service_id": "asr"}
    assert client.get("/api/v1/agent/commands", headers=agent_auth).json()["data"] == []

    reported = client.post(
        f"/api/v1/agent/commands/{command_id}/report",
        json={"ok": True, "result": {"reachable": True}},
        headers=agent_auth,
    )
    assert reported.status_code == 200
    row = client.get("/api/v1/machines/node-a01/commands", headers=auth).json()["data"][0]
    assert row["status"] == "succeeded"
    assert row["result"] == {"reachable": True}


def test_agent_can_apply_drain_to_its_bound_instances(client, db_session):
    token = _machine_and_token(client, db_session)
    db_session.add(
        ParamInstance(
            instance_id="pipe-a", base_url="http://10.0.0.9:8765",
            machine_id="node-a01", labels_json={},
        )
    )
    db_session.commit()
    agent_auth = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/agent/instances/drain", json={"drain": True}, headers=agent_auth
    )
    assert response.status_code == 200
    assert response.json()["data"]["instanceIds"] == ["pipe-a"]
    row = db_session.query(ParamInstance).filter_by(instance_id="pipe-a").one()
    assert row.drain_requested is True
    assert client.get("/api/v1/machines/node-a01/commands", headers=_auth(client)).status_code == 200

