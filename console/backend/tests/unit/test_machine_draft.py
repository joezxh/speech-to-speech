"""Task 21（D3–D5）——机器级草稿：复用 config_service 校验 + 乐观锁。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.config import console as console_settings
from app.core.errors import ApiError
from app.db.base import Base
from app.models.param_audit import ParamAudit
from app.models.machine_config import ParamMachineDraft
from app.services import machine_config_service
from app.services.machine_service import MachineCreate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"
PROFILE = "schema_version: 1\nruntime:\n  log_level: info\n"


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


def test_put_then_get_draft(db_session):
    result = machine_config_service.put_draft(
        db_session, "node-a01", {"vad.min_silence_ms": "800"}, base_version=0, actor="alice"
    )
    assert result["vad.min_silence_ms"] == "800"
    draft = machine_config_service.get_draft(db_session, "node-a01")
    assert draft["values"]["vad.min_silence_ms"] == "800"
    assert draft["updated_by"] == "alice"
    assert draft["updated_at"]


def test_invalid_value_rejected_without_persisting(db_session):
    with pytest.raises(ApiError) as denied:
        machine_config_service.put_draft(
            db_session, "node-a01", {"vad.min_silence_ms": "not-an-int"}, base_version=0, actor="alice"
        )
    assert denied.value.status == 400
    assert db_session.scalars(select(ParamMachineDraft)).all() == []


def test_stale_base_version_returns_conflict(db_session):
    machine_config_service.put_draft(
        db_session, "node-a01", {"vad.min_silence_ms": "800"}, base_version=0, actor="alice"
    )
    with pytest.raises(ApiError) as conflict:
        machine_config_service.put_draft(
            db_session, "node-a01", {"vad.min_silence_ms": "900"}, base_version=0, actor="alice"
        )
    assert conflict.value.status == 409


def test_clear_draft(db_session):
    machine_config_service.put_draft(
        db_session, "node-a01", {"vad.min_silence_ms": "800"}, base_version=0, actor="alice"
    )
    machine_config_service.clear_draft(db_session, "node-a01", actor="alice")
    assert db_session.scalars(select(ParamMachineDraft)).all() == []


def test_draft_set_is_audited(db_session):
    machine_config_service.put_draft(
        db_session, "node-a01", {"vad.min_silence_ms": "800"}, base_version=0, actor="alice"
    )
    actions = db_session.scalars(select(ParamAudit.action)).all()
    assert "machine.draft.set" in actions
