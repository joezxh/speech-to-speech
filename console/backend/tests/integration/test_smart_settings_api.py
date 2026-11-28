"""智能设置 HTTP 契约：fetch/analyze、权限码与 404/400/429 映射。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services import machine_service
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
    machine_service.create_machine(db_session, machine_service.MachineCreate(machineId="node-a01"), actor="alice")
    yield TestClient(app)


def _auth(client: TestClient, username: str = "alice") -> dict:
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_fetch_returns_machine_params(client):
    data = client.post("/api/v1/smart-settings/fetch", json={"machineId": "node-a01"}, headers=_auth(client)).json()["data"]
    assert data["machine"]["machineId"] == "node-a01"
    assert data["machine"]["platform"] == "cpu"  # 未填 gpu 描述 → 推断 cpu
    assert data["params"]
    assert data["logs"] == []


def test_fetch_unknown_machine_is_404(client):
    resp = client.post("/api/v1/smart-settings/fetch", json={"machineId": "ghost"}, headers=_auth(client))
    assert resp.status_code == 404


def test_analyze_without_fault_is_422(client):
    # pydantic min_length=1 在入口即拒绝空 fault（422），服务层的 400 兜纯空白由单测覆盖。
    resp = client.post("/api/v1/smart-settings/analyze", json={"fault": ""}, headers=_auth(client))
    assert resp.status_code == 422


def test_analyze_falls_back_to_rules(client, monkeypatch):
    from app.services import smart_settings_service

    def unreachable(prompt: str):
        from app.services.log_analysis_service import AnalysisUnavailable

        raise AnalysisUnavailable("down")

    monkeypatch.setattr(smart_settings_service, "_call_llm", unreachable)
    resp = client.post(
        "/api/v1/smart-settings/analyze",
        json={"machineId": "node-a01", "fault": "用户说话总是被截断", "params": {"min_silence_ms": "450"}},
        headers=_auth(client),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["source"] == "rules"
    assert data["recommendations"]
