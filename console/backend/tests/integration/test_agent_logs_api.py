"""agent 容器日志上报：脱敏后按现有四日志格式落盘，供 /logs/analyze 复用。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.services import machine_service
from app.services.machine_service import MachineCreate


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr("app.routers.agent.console_settings.log_dir", str(tmp_path / "logs"))
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)


def _enroll_and_register(client, db_session):
    _, code = machine_service.create_machine(
        db_session, MachineCreate(machineId="node-a01", addr="10.0.0.9"), actor="alice"
    )
    return client.post(
        "/api/v1/agent/register",
        json={
            "register_code": code,
            "machine": {"machine_id": "node-a01", "addr": "10.0.0.9"},
            "workloads": [],
        },
    ).json()["data"]["machine_token"]


def test_agent_uploads_redacted_container_logs(client, db_session, tmp_path):
    token = _enroll_and_register(client, db_session)
    response = client.post(
        "/api/v1/agent/logs",
        json={"logs": [
            {"source": "stdout", "lines": ["INFO ready", "ERROR api_key=sk-secret-abcdef"]},
            {"source": "stderr", "lines": ["WARN retry"]},
        ]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    stdout = (tmp_path / "logs" / "pipeline-stdout.log").read_text(encoding="utf-8")
    stderr = (tmp_path / "logs" / "pipeline-stderr.log").read_text(encoding="utf-8")
    assert "[machine:node-a01] INFO ready" in stdout
    assert "sk-secret-abcdef" not in stdout
    assert "api_key=***" in stdout
    assert "[machine:node-a01] WARN retry" in stderr
