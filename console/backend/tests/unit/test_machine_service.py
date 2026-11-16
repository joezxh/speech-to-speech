"""Task 3（2026-11-17 原型对齐计划）——机器仓储与机器服务（M1–M7）。

口径：machine_id 重复 → ValueError（路由层映射 409）；不存在 → KeyError（映射 404）。
注册码 = secrets.token_urlsafe(24)，库中只存 sha256，明文仅 create 返回一次。
审计沿用 instances.py 约定：action 点分、fields 只含字段名不存值。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - 在 Base.metadata 上注册全部表
from app.db.base import Base
from app.models.machine import ParamMachine
from app.models.machine_config import ParamMachineConfig, ParamMachineDraft
from app.models.param_audit import ParamAudit
from app.models.token_metric import ParamTokenMetric  # noqa: F401
from app.services import machine_service
from app.services.machine_service import (
    MachineCreate,
    MachineUpdate,
    WorkloadIn,
)
from sqlalchemy import create_engine, select


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


def _audits(session, action: str) -> list[ParamAudit]:
    return list(
        session.scalars(select(ParamAudit).where(ParamAudit.action == action).order_by(ParamAudit.id))
    )


def _create_payload(machine_id: str = "m-01", **overrides) -> MachineCreate:
    fields = {
        "machineId": machine_id,
        "addr": "10.12.0.31",
        "role": "agent",
        "gpu": "RTX 4090",
        "gpuTotalGb": 24,
        "clusterId": "default",
        "profile": None,
    }
    fields.update(overrides)
    return MachineCreate(**fields)


def test_create_returns_register_code_once_and_stores_only_hash(db_session):
    machine, register_code = machine_service.create_machine(db_session, _create_payload(), actor="alice")

    assert register_code
    row = db_session.scalar(select(ParamMachine).where(ParamMachine.machine_id == "m-01"))
    assert row is not None
    assert row.state == "pending_register"
    assert row.register_code_hash
    assert register_code not in (row.register_code_hash,)
    # 明文不可得：库里任何列都不含明文
    for column in ParamMachine.__table__.columns:
        value = getattr(row, column.name)
        assert not (isinstance(value, str) and register_code in value), column.name


def test_create_duplicate_machine_id_raises_value_error(db_session):
    machine_service.create_machine(db_session, _create_payload(), actor="alice")
    with pytest.raises(ValueError):
        machine_service.create_machine(db_session, _create_payload(), actor="alice")


def test_update_applies_partial_fields_and_audits_field_names(db_session):
    machine_service.create_machine(db_session, _create_payload(), actor="alice")
    updated = machine_service.update_machine(
        db_session,
        "m-01",
        MachineUpdate(addr="10.12.0.32", gpuTotalGb=48),
        actor="bob",
    )
    assert updated.addr == "10.12.0.32"
    assert updated.gpuTotalGb == 48
    assert updated.role == "agent"  # 未提及的字段保持不变

    rows = _audits(db_session, "machine.update")
    assert rows, "update 必须落审计"
    assert rows[0].actor == "bob"
    assert set(rows[0].fields) == {"addr", "gpu_total_gb"}


def test_update_missing_machine_raises_key_error(db_session):
    with pytest.raises(KeyError):
        machine_service.update_machine(db_session, "ghost", MachineUpdate(), actor="bob")


def test_delete_cascades_to_workload_draft_config(db_session):
    machine_service.create_machine(db_session, _create_payload(), actor="alice")
    machine_service.upsert_workloads(
        db_session,
        "m-01",
        [WorkloadIn(kind="pipeline", port=8765, publicAddr="10.12.0.31:8765")],
        actor="alice",
    )
    db_session.add(
        ParamMachineDraft(machine_id="m-01", param_key="vad.min_silence_ms", value="700")
    )
    db_session.add(
        ParamMachineConfig(machine_id="m-01", param_key="vad.min_silence_ms", actual_value="700")
    )
    db_session.commit()

    machine_service.delete_machine(db_session, "m-01", actor="alice")

    assert db_session.scalar(select(ParamMachine).where(ParamMachine.machine_id == "m-01")) is None
    assert db_session.scalars(
        select(ParamMachineConfig).where(ParamMachineConfig.machine_id == "m-01")
    ).all() == []
    assert db_session.scalars(
        select(ParamMachineDraft).where(ParamMachineDraft.machine_id == "m-01")
    ).all() == []
    assert db_session.scalars(
        select(ParamMachineConfig).where(ParamMachineConfig.machine_id == "m-01")
    ).all() == []


def test_delete_missing_machine_raises_key_error(db_session):
    with pytest.raises(KeyError):
        machine_service.delete_machine(db_session, "ghost", actor="alice")


def test_upsert_workloads_replaces_full_set(db_session):
    machine_service.create_machine(db_session, _create_payload(), actor="alice")
    first = machine_service.upsert_workloads(
        db_session,
        "m-01",
        [
            WorkloadIn(kind="pipeline", port=8765, publicAddr="10.12.0.31:8765"),
            WorkloadIn(kind="llm", port=8080),
        ],
        actor="alice",
    )
    assert {w.kind for w in first} == {"pipeline", "llm"}

    second = machine_service.upsert_workloads(
        db_session,
        "m-01",
        [WorkloadIn(kind="pipeline", port=8766, publicAddr="10.12.0.31:8766")],
        actor="bob",
    )
    kinds = [w.kind for w in second]
    assert kinds == ["pipeline"], "全量覆盖：上一轮的 llm 行必须消失"
    assert second[0].port == 8766
    assert second[0].publicAddr == "10.12.0.31:8766"


def test_list_machines_filters_by_cluster(db_session):
    machine_service.create_machine(db_session, _create_payload("m-01", clusterId="alpha"), actor="a")
    machine_service.create_machine(db_session, _create_payload("m-02", clusterId="beta"), actor="a")

    ids = [m.machineId for m in machine_service.list_machines(db_session, cluster="alpha")]
    assert ids == ["m-01"]
    assert len(machine_service.list_machines(db_session)) == 2


def test_get_machine_returns_workloads_and_state(db_session):
    machine_service.create_machine(db_session, _create_payload(), actor="alice")
    machine_service.upsert_workloads(
        db_session, "m-01", [WorkloadIn(kind="pipeline", port=8765)], actor="alice"
    )
    detail = machine_service.get_machine(db_session, "m-01")
    assert detail.machineId == "m-01"
    assert [w.kind for w in detail.workloads] == ["pipeline"]
    with pytest.raises(KeyError):
        machine_service.get_machine(db_session, "ghost")


def test_machine_actions_are_audited_with_field_names_only(db_session):
    machine_service.create_machine(db_session, _create_payload(), actor="alice")
    machine_service.update_machine(db_session, "m-01", MachineUpdate(addr="x"), actor="bob")
    machine_service.delete_machine(db_session, "m-01", actor="carol")

    creates = _audits(db_session, "machine.create")
    updates = _audits(db_session, "machine.update")
    deletes = _audits(db_session, "machine.delete")
    assert len(creates) == 1 and creates[0].actor == "alice"
    assert creates[0].profile == "m-01"
    assert len(deletes) == 1 and deletes[0].actor == "carol"
    for row in (*creates, *updates, *deletes):
        for field in row.fields:
            assert isinstance(field, str) and field and "=" not in field and ":" not in field
