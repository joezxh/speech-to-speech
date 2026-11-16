"""Task 9（2026-11-17 原型对齐计划）——M8 注册测试三步流 + M9 自动注册。

三步语义（§7.2.2）：步1 console 自有注册表建档+注册码；步2 等 agent 换 token；
步3 等首个心跳。simulate=fail 时步2 必败（演练"agent 不来"）。
M9 只做受理（生成注册码挂"待接入"），不代 agent 完成注册。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.errors import ApiError
from app.db.base import Base
from app.models.machine import ParamMachine
from app.schemas.agent import AgentRegisterIn, HeartbeatIn
from app.services import agent_registry_service as svc
from app.services import machine_service
from app.services.machine_service import AutoRegisterIn, MachineCreate, RegisterTestIn


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


def _steps(result: dict) -> dict[str, dict]:
    return {step["key"]: step for step in result["steps"]}


def test_register_test_creates_row_and_returns_code(db_session):
    result = machine_service.register_test(
        db_session,
        RegisterTestIn(machineId="node-x", addr="10.0.0.9", clusterId="default"),
        actor="alice",
    )
    steps = _steps(result)
    assert steps["step1"]["state"] == "pass"
    assert steps["step2"]["state"] == "pending", "agent 还没来"
    assert steps["step3"]["state"] == "pending"
    assert result["ok"] is False
    assert result["register_code"], "一次性注册码明文仅此一次"

    row = db_session.scalar(select(ParamMachine).where(ParamMachine.machine_id == "node-x"))
    assert row.state == "pending_register"


def test_register_test_simulate_fail_forces_step2_fail(db_session):
    result = machine_service.register_test(
        db_session,
        RegisterTestIn(machineId="node-x", simulate=True),
        actor="alice",
    )
    steps = _steps(result)
    assert steps["step1"]["state"] == "pass", "步1 是 console 自己的写库，不会失败"
    assert steps["step2"]["state"] == "fail"
    assert steps["step3"]["state"] == "fail"
    assert result["ok"] is False


def test_register_test_reports_full_flow_after_agent_arrives(db_session):
    # 第一次：建档拿码
    first = machine_service.register_test(
        db_session, RegisterTestIn(machineId="node-x"), actor="alice"
    )
    assert _steps(first)["step2"]["state"] == "pending"

    # agent 走真实路径：注册 + 首心跳
    token = svc.register(
        db_session,
        AgentRegisterIn(
            register_code=first["register_code"],
            machine={"machine_id": "node-x"},
            workloads=[{"kind": "pipeline", "port": 8765}],
        ),
    )["machine_token"]
    svc.heartbeat(
        db_session,
        "node-x",
        HeartbeatIn(protocol_version=1, agent_version="1.0.0", machine={"machine_id": "node-x"}),
    )

    # 第二次调用（已存在机器 → 重新发码）应报三步全过
    second = machine_service.register_test(
        db_session, RegisterTestIn(machineId="node-x"), actor="alice"
    )
    steps = _steps(second)
    assert steps["step1"]["state"] == "pass"
    assert steps["step2"]["state"] == "pass", "agent 已注册（token 已签发）"
    assert steps["step3"]["state"] == "pass"
    assert steps["step3"]["detail"].get("agentVersion") == "1.0.0"
    assert second["ok"] is True
    assert second["register_code"], "重新发码（旧码明文已不可得）"


def test_auto_register_accepts_and_pends(db_session):
    result = machine_service.auto_register(
        db_session, AutoRegisterIn(clusterId="default", addr="10.0.0.10"), actor="alice"
    )
    assert result["machineId"].startswith("auto-")
    assert result["state"] == "pending_register"
    assert result["registerCode"]

    row = db_session.scalar(
        select(ParamMachine).where(ParamMachine.machine_id == result["machineId"])
    )
    assert row.registry_mode == "auto"
    assert row.cluster_id == "default"

    # 受理的注册码走真实 agent 注册路径可用
    token = svc.register(
        db_session,
        AgentRegisterIn(register_code=result["registerCode"], machine={"machine_id": result["machineId"]}),
    )["machine_token"]
    assert token


def test_auto_register_conflicts_on_existing_id(db_session):
    machine_service.auto_register(
        db_session, AutoRegisterIn(machineId="node-y", clusterId="default"), actor="alice"
    )
    with pytest.raises(ValueError):
        machine_service.auto_register(
            db_session, AutoRegisterIn(machineId="node-y", clusterId="default"), actor="alice"
        )


def test_create_machine_manual_mode_by_default(db_session):
    machine, _code = machine_service.create_machine(
        db_session, MachineCreate(machineId="m-1"), actor="alice"
    )
    assert machine.registryMode == "manual"
