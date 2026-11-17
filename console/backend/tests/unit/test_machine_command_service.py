"""机器命令队列服务：下发/抢占/回执/过期状态机（TDD RED → GREEN）。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - 注册全部表
from app.db.base import Base, utcnow
from app.models.machine import ParamMachine
from app.models.param_audit import ParamAudit
from app.services import machine_command_service as svc


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def machines(db_session):
    db_session.add_all([ParamMachine(machine_id="m-01"), ParamMachine(machine_id="m-02")])
    db_session.commit()


def test_issue_persists_pending_command_with_audit_and_expiry(db_session, machines):
    row = svc.issue(db_session, "m-01", "drain", actor="alice")

    assert row["status"] == "pending"
    assert row["machine_id"] == "m-01"
    assert row["kind"] == "drain"
    assert row["expires_at"] > utcnow()
    assert db_session.scalar(
        select(ParamAudit).where(ParamAudit.action == "machine.command.issue")
    ).actor == "alice"


def test_issue_rejects_unknown_kind(db_session, machines):
    with pytest.raises(ValueError, match="unsupported"):
        svc.issue(db_session, "m-01", "rm -rf", actor="alice")


def test_issue_rejects_unknown_machine(db_session, machines):
    with pytest.raises(KeyError):
        svc.issue(db_session, "missing", "reboot", actor="alice")


def test_issue_rejects_duplicate_active_command(db_session, machines):
    svc.issue(db_session, "m-01", "drain", actor="alice")
    with pytest.raises(ValueError, match="in_flight"):
        svc.issue(db_session, "m-01", "drain", actor="alice")


def test_poll_claims_only_pending_commands_for_its_machine(db_session, machines):
    svc.issue(db_session, "m-01", "drain", actor="alice")
    svc.issue(db_session, "m-01", "reboot", actor="alice")
    svc.issue(db_session, "m-02", "drain", actor="alice")

    claimed = svc.poll(db_session, "m-01", limit=1)

    assert len(claimed) == 1
    assert claimed[0]["kind"] in {"drain", "reboot"}
    assert svc.poll(db_session, "m-01")[0]["kind"] != claimed[0]["kind"]
    assert [c["kind"] for c in svc.poll(db_session, "m-02")] == ["drain"]


def test_report_moves_dispatched_command_to_succeeded_with_result(db_session, machines):
    svc.issue(db_session, "m-01", "health_check", actor="alice")
    claimed = svc.poll(db_session, "m-01")[0]
    row = svc.report(
        db_session,
        "m-01",
        claimed["command_id"],
        ok=True,
        result={"service": "asr", "reachable": True},
    )

    assert row["status"] == "succeeded"
    assert row["result"] == {"service": "asr", "reachable": True}
    assert svc.poll(db_session, "m-01") == []


def test_report_rejects_wrong_machine(db_session, machines):
    svc.issue(db_session, "m-01", "reboot", actor="alice")
    claimed = svc.poll(db_session, "m-01")[0]
    with pytest.raises(PermissionError):
        svc.report(db_session, "m-02", claimed["command_id"], ok=True, result={})


def test_expire_stale_marks_old_commands_and_poll_skips_them(db_session, machines):
    svc.issue(db_session, "m-01", "drain", actor="alice")
    row = db_session.scalars(select(svc.ParamMachineCommand)).one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()

    assert svc.expire_stale(db_session) == 1
    assert svc.poll(db_session, "m-01") == []
    assert svc.list_for_machine(db_session, "m-01")[0]["status"] == "expired"
