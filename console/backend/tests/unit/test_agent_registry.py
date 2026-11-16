"""Task 4（2026-11-17 原型对齐计划）——agent 注册与心跳（A0/A1）服务层用例。

口径（spec §5.2/§5.4）：注册码用过即焚；machine token 只存哈希；
body 的 machine_id 与 token 不一致 → 403；protocol_version 高于支持值 → 400；
token 差分先暂存内存（Task 14 接 param_token_metric）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.errors import ApiError
from app.db.base import Base
from app.models.machine import ParamMachine
from app.services import agent_registry_service as svc
from app.services import machine_service
from app.schemas.agent import AgentRegisterIn, HeartbeatIn
from app.services.machine_service import MachineCreate, WorkloadIn


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


def _enrolled(db_session) -> tuple[str, str]:
    """建档并签发注册码；返回 (machine_id, 注册码明文)。"""
    _, code = machine_service.create_machine(
        db_session, MachineCreate(machineId="node-a01", addr="10.12.0.31"), actor="alice"
    )
    return "node-a01", code


def _register_body(machine_id: str = "node-a01", **overrides) -> AgentRegisterIn:
    fields = {
        "register_code": "code",
        "machine": {"machine_id": machine_id, "addr": "10.12.0.31"},
        "workloads": [
            {"kind": "pipeline", "port": 8765, "listen": "127.0.0.1:8765",
             "public_addr": "10.12.0.31:8765"}
        ],
    }
    fields.update(overrides)
    return AgentRegisterIn(**fields)


def _heartbeat_body(machine_id: str = "node-a01", **overrides) -> HeartbeatIn:
    fields = {
        "protocol_version": 1,
        "agent_version": "1.0.0",
        "machine": {"machine_id": machine_id, "addr": "10.12.0.31"},
        "capabilities": ["heartbeat", "workloads", "token"],
        "workloads": [
            {"kind": "pipeline", "port": 8765, "listen": "127.0.0.1:8765",
             "public_addr": "10.12.0.31:8765"}
        ],
        "tokens": {"input_tokens": 100, "output_tokens": 40, "responses": 2, "window_s": 30},
    }
    fields.update(overrides)
    return HeartbeatIn(**fields)


def test_register_exchanges_code_for_token_and_burns_it(db_session):
    _, code = _enrolled(db_session)
    out = svc.register(db_session, _register_body(register_code=code))

    assert out["machine_token"]
    assert out["machine_id"] == "node-a01"
    assert out["heartbeat_after_s"] > 0

    row = db_session.scalar(select(ParamMachine).where(ParamMachine.machine_id == "node-a01"))
    assert row.token_hash == machine_service.hash_secret(out["machine_token"])
    assert row.register_code_hash is None, "注册码用过即焚"
    assert out["machine_token"] not in (row.token_hash,)


def test_register_reuses_or_unknown_code_is_unauthorized(db_session):
    _, code = _enrolled(db_session)
    svc.register(db_session, _register_body(register_code=code))
    with pytest.raises(ApiError) as exc:
        svc.register(db_session, _register_body(register_code=code))
    assert exc.value.status == 401

    with pytest.raises(ApiError) as exc:
        svc.register(db_session, _register_body(register_code="wrong-code"))
    assert exc.value.status == 401


def test_heartbeat_first_contact_flips_state_to_ok(db_session):
    _, code = _enrolled(db_session)
    token = svc.register(db_session, _register_body(register_code=code))["machine_token"]
    machine_id = svc.authenticate(db_session, f"Bearer {token}")

    out = svc.heartbeat(db_session, machine_id, _heartbeat_body())
    assert out["accepted"] is True
    assert out["machine_id"] == "node-a01"
    assert out["config_version"] == 0 and out["config_etag"] == ""  # Task 7 接配置服务

    row = db_session.scalar(select(ParamMachine).where(ParamMachine.machine_id == machine_id))
    assert row.state == "ok"
    assert row.last_seen_at is not None
    assert row.agent_version == "1.0.0"
    assert row.agent_caps == ["heartbeat", "workloads", "token"]


def test_heartbeat_replaces_workload_set_and_updates_last_seen(db_session):
    _, code = _enrolled(db_session)
    token = svc.register(db_session, _register_body(register_code=code))["machine_token"]
    machine_id = svc.authenticate(db_session, f"Bearer {token}")

    svc.heartbeat(db_session, machine_id, _heartbeat_body())
    first_seen = db_session.scalar(
        select(ParamMachine).where(ParamMachine.machine_id == machine_id)
    ).last_seen_at

    out = svc.heartbeat(
        db_session,
        machine_id,
        _heartbeat_body(
            workloads=[
                {"kind": "llm", "port": 8000, "listen": "127.0.0.1:8000",
                 "public_addr": "10.12.0.31:8000"}
            ]
        ),
    )
    assert out["accepted"] is True
    row = db_session.scalar(select(ParamMachine).where(ParamMachine.machine_id == machine_id))
    assert row.last_seen_at > first_seen
    kinds = {w.kind for w in machine_service.list_machines(db_session)[0].workloads}
    assert kinds == {"llm"}, "心跳清单全量覆盖"


def test_heartbeat_stores_token_diff_in_memory_only(db_session):
    _, code = _enrolled(db_session)
    token = svc.register(db_session, _register_body(register_code=code))["machine_token"]
    machine_id = svc.authenticate(db_session, f"Bearer {token}")

    svc.heartbeat(db_session, machine_id, _heartbeat_body())
    svc.heartbeat(
        db_session,
        machine_id,
        _heartbeat_body(tokens={"input_tokens": 250, "output_tokens": 90, "responses": 5, "window_s": 30}),
    )
    diff = svc.get_token_diff(machine_id)
    assert diff["input_tokens"] == 250  # 暂存内存，Task 14 接表
    assert db_session.scalars(
        select(ParamMachine).where(ParamMachine.machine_id == machine_id)
    ).all()  # 行仍在；token 数值不落库（本任务）


def test_heartbeat_with_mismatched_machine_id_is_forbidden(db_session):
    _, code = _enrolled(db_session)
    token = svc.register(db_session, _register_body(register_code=code))["machine_token"]
    machine_id = svc.authenticate(db_session, f"Bearer {token}")
    with pytest.raises(ApiError) as exc:
        svc.heartbeat(db_session, machine_id, _heartbeat_body(machine_id="node-other"))
    assert exc.value.status == 403


def test_heartbeat_with_newer_protocol_is_rejected(db_session):
    _, code = _enrolled(db_session)
    token = svc.register(db_session, _register_body(register_code=code))["machine_token"]
    machine_id = svc.authenticate(db_session, f"Bearer {token}")
    with pytest.raises(ApiError) as exc:
        svc.heartbeat(db_session, machine_id, _heartbeat_body(protocol_version=svc.SUPPORTED_PROTOCOL_VERSION + 1))
    assert exc.value.status == 400


def test_authenticate_rejects_bad_bearer(db_session):
    _enrolled(db_session)
    with pytest.raises(ApiError):
        svc.authenticate(db_session, "")
    with pytest.raises(ApiError):
        svc.authenticate(db_session, "Bearer no-such-token")


def test_caps_intersection_downgrades_panels(db_session):
    assert svc.caps_for(["heartbeat", "token"]) == ["heartbeat", "token"]
    assert svc.caps_for(["heartbeat", "magic_future"]) == ["heartbeat"]
    assert svc.caps_for([]) == []
