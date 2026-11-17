"""agent 注册与心跳端点（A0/A1，spec §5.2/§7.2.1）。

register 匿名（凭据是一次性注册码，放请求体）；heartbeat 走 machine token。
响应带 {code, message, data} 信封，与设计草案一致。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.repositories.machine_repository import MachineRepository
from app.services import machine_service
from app.services.machine_service import MachineCreate


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)


def _enroll(db_session) -> str:
    """建档并返回一次性注册码明文。"""
    _, code = machine_service.create_machine(
        db_session, MachineCreate(machineId="node-a01", addr="10.12.0.31"), actor="alice"
    )
    return code


def _register(client, code: str, machine_id: str = "node-a01"):
    return client.post(
        "/api/v1/agent/register",
        json={
            "register_code": code,
            "machine": {"machine_id": machine_id, "addr": "10.12.0.31", "role": "agent"},
            "workloads": [
                {"kind": "pipeline", "port": 8765, "listen": "127.0.0.1:8765",
                 "public_addr": "10.12.0.31:8765"}
            ],
        },
    )


def _heartbeat(client, token: str, machine_id: str = "node-a01", **overrides):
    body = {
        "protocol_version": 1,
        "agent_version": "1.0.0",
        "machine": {"machine_id": machine_id, "addr": "10.12.0.31"},
        "capabilities": ["heartbeat", "workloads", "token"],
        "workloads": [
            {"kind": "pipeline", "port": 8765, "listen": "127.0.0.1:8765",
             "public_addr": "10.12.0.31:8765"}
        ],
        "runtime": {"pipeline_units": 4},
        "tokens": {"input_tokens": 100, "output_tokens": 40, "responses": 2, "window_s": 30},
    }
    body.update(overrides)
    return client.post(
        "/api/v1/agent/heartbeat",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_register_exchange_then_heartbeat_roundtrip(client, db_session):
    code = _enroll(db_session)
    response = _register(client, code)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["machine_id"] == "node-a01"
    assert data["machine_token"]
    assert data["heartbeat_after_s"] > 0

    heartbeat = _heartbeat(client, data["machine_token"])
    assert heartbeat.status_code == 200
    payload = heartbeat.json()["data"]
    assert payload["accepted"] is True
    assert payload["machine_id"] == "node-a01"
    assert payload["config_version"] == 0  # Task 7 接配置服务
    assert payload["poll_after_s"] > 0
    assert MachineRepository(db_session).get("node-a01").state == "ok"


def test_register_code_is_single_use(client, db_session):
    code = _enroll(db_session)
    assert _register(client, code).status_code == 200
    assert _register(client, code).status_code == 401
    assert _register(client, "totally-wrong").status_code == 401


def test_heartbeat_requires_machine_token(client, db_session):
    # FastAPI 先做 body 校验（坏 body → 422），鉴权守卫用合法 body 验证：
    # 缺 token / 未知 token 一律 401，绝不进入业务逻辑。
    body = {
        "protocol_version": 1,
        "machine": {"machine_id": "node-a01"},
    }
    assert client.post("/api/v1/agent/heartbeat", json=body).status_code == 401
    assert (
        client.post(
            "/api/v1/agent/heartbeat", json=body, headers={"Authorization": "Bearer bogus"}
        ).status_code
        == 401
    )


def test_heartbeat_machine_id_mismatch_is_forbidden(client, db_session):
    code = _enroll(db_session)
    token = _register(client, code).json()["data"]["machine_token"]
    assert _heartbeat(client, token, machine_id="node-other").status_code == 403


def test_heartbeat_with_unsupported_protocol_is_rejected(client, db_session):
    code = _enroll(db_session)
    token = _register(client, code).json()["data"]["machine_token"]
    response = _heartbeat(client, token, protocol_version=999)
    assert response.status_code == 400


def test_heartbeat_persists_real_pipeline_models_params_and_vram(client, db_session):
    # 机器页展开区需要 agent 采集的真源（模型/全部参数/实测显存）。
    code = _enroll(db_session)
    token = _register(client, code).json()["data"]["machine_token"]
    params = {
        "models": {"stt": "/models/asr-1.7b", "llm": "qwen3.8-27b", "tts": "/models/qwen3-tts"},
        "llm.responses_api_api_key": "***",
        "stt.qwen3_asr_device": "cuda",
    }
    response = _heartbeat(
        client,
        token,
        workloads=[
            {
                "kind": "pipeline", "port": 8765, "model": "asr · llm · tts",
                "public_addr": "10.12.0.31:8765", "vram_gb": 4.75, "params": params,
            }
        ],
    )
    assert response.status_code == 200
    rows = MachineRepository(db_session).list_workloads("node-a01")
    assert len(rows) == 1
    assert rows[0].params_json == params
    assert rows[0].vram_gb == 4.75
    out = machine_service._workload_out(rows[0])
    assert out.params == params
