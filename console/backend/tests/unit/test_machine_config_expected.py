"""Task 20（D1/D2）——机器参数期望值（profile live 渲染真源）与漂移判定。

Review Focus #5：agent 未回报的键 actual=None 且 drift=False（"未知"不算漂移）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.config import console as console_settings
from app.db.base import Base
from app.repositories.machine_config_repository import MachineConfigRepository
from app.services import machine_config_service
from app.services.machine_service import MachineCreate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"
PROFILE = """\
schema_version: 1
runtime:
  log_level: info
blocks:
  vad-main: {kind: vad, backend: silero, settings: {min_silence_ms: 700}}
"""


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


def test_expected_value_uses_profile_live_when_covered(db_session):
    value, source = machine_config_service.expected_value(db_session, "node-a01", "vad.min_silence_ms")
    assert value == "700"
    assert source == "profile"


def test_expected_value_falls_back_to_catalog_default(db_session):
    # vad.max_speech_ms 在 min 目录里存在，但测试 profile 未配置该键 → 回落 catalog 默认。
    entry = machine_config_service._catalog_entry("stt.language")
    value, source = machine_config_service.expected_value(db_session, "node-a01", "stt.language")
    assert entry is not None
    assert source == "期望默认"
    assert value == str(entry.default)


def test_config_view_marks_unreported_as_unknown_not_drift(db_session):
    rows = machine_config_service.config_view(db_session, "node-a01")
    assert rows, "目录有行"
    for row in rows:
        assert row["actual"] is None
        assert row["drift"] is False, "agent 未回报 → 未知，不算漂移"


def test_drift_counts_only_reported_and_different(db_session):
    MachineConfigRepository(db_session).upsert_report(
        "node-a01", {"vad.min_silence_ms": "900"}, config_version=1
    )
    summary = machine_config_service.drift(db_session, "node-a01")
    assert summary["drift_count"] == 1
    assert any(row["key"] == "vad.min_silence_ms" and row["drift"] for row in summary["rows"])

    # 上报匹配期望 → 漂移归零
    MachineConfigRepository(db_session).upsert_report(
        "node-a01", {"vad.min_silence_ms": "700"}, config_version=1
    )
    assert machine_config_service.drift(db_session, "node-a01")["drift_count"] == 0
