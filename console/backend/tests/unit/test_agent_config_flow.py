"""Task 6（2026-11-17 原型对齐计划）——agent 配置面 A2/A3/A4。

- A2 GET /api/v1/agent/config：If-None-Match 命中当前 etag → 304；
- A3 POST /api/v1/agent/config/report：values 逐键 upsert 进 param_machine_config，
  drift_count 与 profile live 期望值比对；密钥类键不落库；
- A4 POST /api/v1/agent/config/ack：ok=false 的版本不留快照（从环形中剔除）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.config import console as console_settings
from app.db.base import Base
from app.db.database import get_db
from app.main import create_app
from app.models.machine_config import ParamAgentConfigVersion, ParamMachineConfig
from app.schemas.agent import AgentRegisterIn, HeartbeatIn
from app.services import agent_registry_service as svc
from app.services.machine_service import MachineCreate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"

PROFILE_YAML = """\
schema_version: 1
runtime:
  log_level: info
blocks:
  vad-main: {kind: vad, backend: silero, settings: {min_silence_ms: 700}}
"""


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "prod.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(directory))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)


@pytest.fixture
def token(db_session) -> str:
    """建档 → 注册 → 首次心跳，返回可用 machine token。"""
    machine_service_create(db_session)
    code = _register_code
    registered = svc.register(
        db_session,
        AgentRegisterIn(
            register_code=code,
            machine={"machine_id": "node-a01"},
            workloads=[{"kind": "pipeline", "port": 8765}],
        ),
    )
    svc.heartbeat(
        db_session,
        "node-a01",
        HeartbeatIn(protocol_version=1, machine={"machine_id": "node-a01"}),
    )
    return registered["machine_token"]


_register_code = ""


def machine_service_create(db_session) -> None:
    from app.services import machine_service

    global _register_code
    _, _register_code = machine_service.create_machine(
        db_session, MachineCreate(machineId="node-a01", addr="10.12.0.31"), actor="alice"
    )


def _pull(client, token: str, headers: dict | None = None):
    return client.get(
        "/api/v1/agent/config",
        params={"machine_id": "node-a01"},
        headers={"Authorization": f"Bearer {token}", **(headers or {})},
    )


def test_pull_returns_yaml_version_and_etag(client, token):
    response = _pull(client, token)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["config_version"] == 1
    assert data["etag"]
    assert "min_silence_ms: 700" in data["yaml_text"]
    assert data["rendered_at"]


def test_pull_with_matching_if_none_match_returns_304(client, token):
    first = _pull(client, token).json()["data"]
    again = _pull(client, token, headers={"If-None-Match": first["etag"]})
    assert again.status_code == 304

    changed = _pull(client, token, headers={"If-None-Match": 'W/"cfg-deadbeef0000"'})
    assert changed.status_code == 200


def test_pull_with_mismatched_machine_id_is_forbidden(client, token):
    response = client.get(
        "/api/v1/agent/config",
        params={"machine_id": "node-other"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_report_upserts_values_and_counts_drift(client, token, db_session):
    response = client.post(
        "/api/v1/agent/config/report",
        json={
            "config_version": 1,
            "applied_at": "2026-11-17T10:00:00Z",
            "values": {"vad.min_silence_ms": "900", "llm.api_key": "sk-x"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["accepted"] is True
    assert data["drift_count"] == 1, "live 期望 700，上报 900 记 1 漂移；密钥键不下库"

    rows = db_session.scalars(
        select(ParamMachineConfig).where(ParamMachineConfig.machine_id == "node-a01")
    ).all()
    assert len(rows) == 1, "密钥键被过滤，不落库"
    assert rows[0].param_key == "vad.min_silence_ms"
    assert rows[0].actual_value == "900"
    assert rows[0].reported_by == "agent"

    # 二次上报同键 → upsert 而非新行；回到期望值 → drift 0
    second = client.post(
        "/api/v1/agent/config/report",
        json={
            "config_version": 1,
            "applied_at": "2026-11-17T10:01:00Z",
            "values": {"vad.min_silence_ms": "700"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.json()["data"]["drift_count"] == 0
    assert (
        len(
            db_session.scalars(
                select(ParamMachineConfig).where(ParamMachineConfig.machine_id == "node-a01")
            ).all()
        )
        == 1
    )
    assert (
        db_session.scalar(
            select(ParamMachineConfig).where(ParamMachineConfig.machine_id == "node-a01")
        ).actual_value
        == "700"
    )


def test_ack_success_keeps_snapshot_and_failure_drops_it(client, token, db_session):
    data = _pull(client, token).json()["data"]

    ack_ok = client.post(
        "/api/v1/agent/config/ack",
        json={"config_version": data["config_version"], "ok": True, "error": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ack_ok.status_code == 200
    snapshots = db_session.scalars(
        select(ParamAgentConfigVersion).where(ParamAgentConfigVersion.machine_id == "node-a01")
    ).all()
    assert [s.config_version for s in snapshots] == [1]
    assert snapshots[0].yaml_text == data["yaml_text"]

    # 再拉一版 → v2；ack 失败 → 该版本不留快照
    _pull(client, token)
    ack_fail = client.post(
        "/api/v1/agent/config/ack",
        json={"config_version": 2, "ok": False, "error": "supervisor restart failed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ack_fail.status_code == 200
    versions = [
        s.config_version
        for s in db_session.scalars(
            select(ParamAgentConfigVersion).where(ParamAgentConfigVersion.machine_id == "node-a01")
        ).all()
    ]
    assert versions == [1], "ack 失败的版本从快照环形中剔除"


def test_ack_ring_keeps_at_most_five_versions(client, token, db_session):
    for _ in range(7):
        _pull(client, token)
    versions = sorted(
        s.config_version
        for s in db_session.scalars(
            select(ParamAgentConfigVersion).where(ParamAgentConfigVersion.machine_id == "node-a01")
        ).all()
    )
    assert versions == [3, 4, 5, 6, 7], "按机保留最近 5 版"


def test_ack_writes_full_69_char_marker_without_truncation(client, token, db_session):
    """回归：yaml_hash 列曾为 varchar(64)，ack 打 "ack:" 前缀（4 + 64 = 68 字符）触发
    StringDataRightTruncation → agent 的 config/ack 永久 500（40.30 部署实测，
    迁移 0016 已扩到 80）。"""
    data = _pull(client, token).json()["data"]
    response = client.post(
        "/api/v1/agent/config/ack",
        json={"config_version": data["config_version"], "ok": True, "error": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    row = db_session.scalar(
        select(ParamAgentConfigVersion).where(ParamAgentConfigVersion.machine_id == "node-a01")
    )
    assert row is not None
    assert row.yaml_hash.startswith("ack:")
    assert len(row.yaml_hash) == 68, "ack 前缀标记必须完整落库（4 + 64 位摘要）"
    assert len(row.yaml_hash.removeprefix("ack:")) == 64
