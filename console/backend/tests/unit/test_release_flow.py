"""Task 24（R1–R4 + R3b）——发布台账：阶段机、CI 回填、回滚联动。

console 只记账：build/staging 由外部 CI 执行；签名缺省放行但必须审计。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.errors import ApiError
from app.db.base import Base
from app.models.param_audit import ParamAudit
from app.models.release import ParamRelease
from app.schemas.release import ReleaseCreate, StageResultIn
from app.services import release_service


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


def _created(db_session) -> str:
    return release_service.create_release(
        db_session,
        ReleaseCreate(name="v2026.11.17", profile="prod", artifactRef="oci://build/1"),
        actor="alice",
    ).release_id


def test_create_release_starts_building(db_session):
    release = release_service.create_release(
        db_session,
        ReleaseCreate(name="v1", profile="prod"),
        actor="alice",
    )
    assert release.status == "building"
    assert release.created_by == "alice"
    assert db_session.scalars(select(ParamRelease)).all()


def test_legal_transition_chain(db_session):
    release_id = _created(db_session)
    for stage in ("staging", "canary", "rolling", "current"):
        result = release_service.advance(db_session, release_id, stage, "ok", None, "alice")
        assert result.status == stage
    assert db_session.scalar(select(ParamRelease).where(ParamRelease.version == release_id)).status == "current"


def test_illegal_transition_is_conflict(db_session):
    release_id = _created(db_session)
    with pytest.raises(ApiError) as conflict:
        release_service.advance(db_session, release_id, "current", "ok", None, "alice")
    assert conflict.value.status == 409
    with pytest.raises(ApiError):
        release_service.advance(db_session, release_id, "building", "ok", None, "alice")


def test_stage_result_records_artifact_ref_and_absent_signature(db_session):
    release_id = _created(db_session)
    result = release_service.stage_result(
        db_session,
        release_id,
        StageResultIn(stage="staging", result="ok", artifactRef="oci://staging/2", note="CI #42"),
        actor="ci-runner",
    )
    assert result.status == "staging"
    row = db_session.scalar(select(ParamRelease).where(ParamRelease.version == "v2026.11.17"))
    stages = {item["stage"]: item for item in row.changes}
    assert stages["staging"]["artifact_ref"] == "oci://staging/2"
    assert stages["staging"]["result"] == "ok"

    actions = db_session.scalars(select(ParamAudit.action)).all()
    assert "release.stage_result" in actions
    fields = [row.fields for row in db_session.scalars(select(ParamAudit)).all()]
    assert any("signature_absent" in value for value in fields)


def test_rollback_triggers_profile_rollback_once(db_session, monkeypatch):
    release_id = _created(db_session)
    release_service.advance(db_session, release_id, "staging", "ok", None, "alice")
    release_service.advance(db_session, release_id, "canary", "ok", None, "alice")
    calls: list[str] = []

    def fake_rollback(profile: str) -> None:
        calls.append(profile)

    monkeypatch.setattr(release_service, "profile_rollback", fake_rollback)
    result = release_service.rollback(db_session, release_id, actor="alice")
    assert result.status == "rolled_back"
    assert calls == ["prod"], "profile rollback 只触发一次"


def test_rollback_from_current_is_rejected(db_session):
    release_id = _created(db_session)
    for stage in ("staging", "canary", "rolling", "current"):
        release_service.advance(db_session, release_id, stage, "ok", None, "alice")
    with pytest.raises(ApiError) as conflict:
        release_service.rollback(db_session, release_id, actor="alice")
    assert conflict.value.status == 409


def test_stale_stage_marks_pending_backfill(db_session, monkeypatch):
    release_id = _created(db_session)
    release_service.advance(db_session, release_id, "staging", "ok", None, "alice")
    row = db_session.scalar(select(ParamRelease).where(ParamRelease.version == "v2026.11.17"))
    stage_at = datetime.fromisoformat([item for item in row.changes if item["stage"] == "staging"][0]["at"])
    fake_now = stage_at + timedelta(minutes=31)
    summary = release_service.summary(db_session, now=fake_now)
    assert summary["pending_backfill"] >= 1
