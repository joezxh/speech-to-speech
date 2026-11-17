"""Task 22（D6，含 Review Focus #6）——机器配置下发与 ack 快照回滚。

- push：期望值+草稿叠加 → config_version 递增，agent 视角 GET config 取到新 YAML；
- rollback：取最近 ack 成功版本的快照（不是 agent 最近上报的实际值）；无 ack → 409；
- 风控：非 canary 机器需 confirm_word == machine_id，否则 403。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.config import console as console_settings
from app.core.errors import ApiError
from app.db.base import Base
from app.models.machine import ParamMachine
from app.models.machine_config import ParamAgentConfigVersion
from app.services import agent_config_service, machine_config_service
from app.services.machine_service import MachineCreate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"
PROFILE = "schema_version: 1\nruntime:\n  log_level: info\nblocks:\n  vad-main: {kind: vad, backend: silero, settings: {min_silence_ms: 700}}\n"


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    session = factory()
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "prod.yaml").write_text(PROFILE, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(directory))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    from app.services import machine_service

    machine_service.create_machine(session, MachineCreate(machineId="node-a01"), actor="alice")
    try:
        yield session
    finally:
        session.close()


def test_push_bumps_version_and_agent_sees_yaml(db_session):
    before = agent_config_service.peek_version(db_session, "node-a01")
    machine_config_service.put_draft(
        db_session, "node-a01", {"vad.min_silence_ms": "800"}, base_version=0, actor="alice"
    )
    result = machine_config_service.deploy(db_session, "node-a01", rows=None, mode="push", actor="alice", confirm_word="node-a01")
    assert result["config_version"] == before + 1
    snapshot = agent_config_service.latest_snapshot(db_session, "node-a01")
    assert snapshot.config_version == result["config_version"]
    assert "min_silence_ms: 800" in snapshot.yaml_text


def test_row_level_push_only_touches_selected_keys(db_session):
    machine_config_service.put_draft(
        db_session,
        "node-a01",
        {"vad.min_silence_ms": "800", "vad.speech_pad_ms": "300"},
        base_version=0,
        actor="alice",
    )
    machine_config_service.deploy(db_session, "node-a01", rows=["vad.min_silence_ms"], mode="push", actor="alice", confirm_word="node-a01")
    # agent 视角 = 最新一条目标配置快照（D6 落的那条）。
    snapshot = agent_config_service.latest_snapshot(db_session, "node-a01")
    assert "min_silence_ms: 800" in snapshot.yaml_text
    assert "speech_pad_ms: 300" not in snapshot.yaml_text


def test_rollback_uses_ack_snapshot_not_reported_actual(db_session):
    # v1：渲染快照（模拟 agent ack 成功）；v2：推新草稿 + agent 上报 900
    agent_config_service.render_target(db_session, "node-a01")  # v1 快照
    agent_config_service.ack(db_session, "node-a01", 1, True, None)
    machine_config_service.put_draft(
        db_session, "node-a01", {"vad.min_silence_ms": "1200"}, base_version=0, actor="alice"
    )
    machine_config_service.deploy(db_session, "node-a01", rows=None, mode="push", actor="alice", confirm_word="node-a01")  # v2

    from app.repositories.machine_config_repository import MachineConfigRepository

    MachineConfigRepository(db_session).upsert_report("node-a01", {"vad.min_silence_ms": "900"}, 2)

    result = machine_config_service.deploy(db_session, "node-a01", rows=None, mode="rollback", actor="alice")
    assert result["config_version"] == 3
    snapshot = agent_config_service.latest_snapshot(db_session, "node-a01")
    # 落回 ack 成功的 v1 快照（700），不是最近上报的 900。
    assert "min_silence_ms: 700" in snapshot.yaml_text


def test_rollback_without_ack_snapshot_is_conflict(db_session):
    with pytest.raises(ApiError) as conflict:
        machine_config_service.deploy(db_session, "node-a01", rows=None, mode="rollback", actor="alice")
    assert conflict.value.status == 409


def test_non_canary_requires_confirm_word(db_session):
    with pytest.raises(ApiError) as forbidden:
        machine_config_service.deploy(
            db_session, "node-a01", rows=None, mode="push", actor="alice", confirm_word=""
        )
    assert forbidden.value.status == 403

    machine_config_service.deploy(
        db_session, "node-a01", rows=None, mode="push", actor="alice", confirm_word="node-a01"
    )
    row = db_session.scalar(select(ParamMachine).where(ParamMachine.machine_id == "node-a01"))
    assert row.role != "canary"

    canary = db_session.scalar(select(ParamMachine).where(ParamMachine.machine_id == "node-a01"))
    canary.role = "canary"
    db_session.commit()
    machine_config_service.deploy(db_session, "node-a01", rows=None, mode="push", actor="alice", confirm_word="node-a01")
