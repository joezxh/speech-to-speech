"""Task 10（2026-11-17 原型对齐计划）——实例按 public_addr 绑定机器。

绑定规则（spec §7.1）：用 public_addr 的 host:port 反查 param_instance.base_url；
不按 listen 匹配（容器内地址与 console 侧 base_url 不可比）；未命中保持 NULL。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.database import get_db
from app.main import create_app
from app.models.param_instance import ParamInstance
from app.repositories.instance_repository import InstanceRepository
from app.repositories.user_repository import UserRepository
from app.schemas.agent import AgentRegisterIn, HeartbeatIn
from app.services import agent_registry_service as svc
from app.services.auth_service import hash_password
from app.services.machine_service import MachineCreate


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
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    yield TestClient(app)


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _enroll_and_heartbeat(db_session, workloads: list[dict]) -> str:
    _, code = machine_service_create(db_session)
    svc.register(
        db_session,
        AgentRegisterIn(register_code=code, machine={"machine_id": "node-a01"}),
    )
    svc.heartbeat(
        db_session,
        "node-a01",
        HeartbeatIn(protocol_version=1, machine={"machine_id": "node-a01"}, workloads=workloads),
    )
    return "node-a01"


def machine_service_create(db_session):
    from app.services import machine_service

    return machine_service.create_machine(
        db_session, MachineCreate(machineId="node-a01"), actor="alice"
    )


def _instance(db_session, instance_id: str, base_url: str) -> None:
    InstanceRepository(db_session).create(instance_id=instance_id, base_url=base_url)


def _machine_id_of(db_session, instance_id: str) -> str | None:
    return db_session.scalar(
        select(ParamInstance.machine_id).where(ParamInstance.instance_id == instance_id)
    )


def test_public_addr_hit_binds_machine(db_session):
    _instance(db_session, "pipe-a", "http://10.12.0.31:8765")
    _enroll_and_heartbeat(
        db_session,
        [{"kind": "pipeline", "port": 8765, "listen": "127.0.0.1:8765", "public_addr": "10.12.0.31:8765"}],
    )
    assert _machine_id_of(db_session, "pipe-a") == "node-a01"


def test_listen_never_binds(db_session):
    _instance(db_session, "pipe-a", "http://127.0.0.1:8765")
    _enroll_and_heartbeat(
        db_session,
        [{"kind": "pipeline", "port": 8765, "listen": "127.0.0.1:8765", "public_addr": "10.12.0.31:8765"}],
    )
    assert _machine_id_of(db_session, "pipe-a") is None, "listen 是容器内地址，不参与匹配"


def test_unmatched_stays_null(db_session):
    _instance(db_session, "pipe-a", "http://10.12.0.99:8765")
    _enroll_and_heartbeat(
        db_session,
        [{"kind": "pipeline", "port": 8765, "listen": "127.0.0.1:8765", "public_addr": "10.12.0.31:8765"}],
    )
    assert _machine_id_of(db_session, "pipe-a") is None


def test_manual_binding_via_endpoint(client, db_session):
    _instance(db_session, "pipe-a", "http://10.12.0.99:8765")
    machine_service_create(db_session)
    headers = _auth(client)

    response = client.put(
        "/api/v1/instances/pipe-a/machine",
        json={"machine_id": "node-a01"},
        headers=headers,
    )
    assert response.status_code == 200
    assert _machine_id_of(db_session, "pipe-a") == "node-a01"

    unbind = client.put(
        "/api/v1/instances/pipe-a/machine", json={"machine_id": ""}, headers=headers
    )
    assert unbind.status_code == 200
    assert _machine_id_of(db_session, "pipe-a") is None


def test_binding_to_unknown_machine_is_404(client, db_session):
    _instance(db_session, "pipe-a", "http://10.12.0.99:8765")
    response = client.put(
        "/api/v1/instances/pipe-a/machine",
        json={"machine_id": "ghost"},
        headers=_auth(client),
    )
    assert response.status_code == 404


def test_instances_aggregate_carries_machine_id(db_session):
    _instance(db_session, "pipe-a", "http://10.12.0.31:8765")
    _enroll_and_heartbeat(
        db_session,
        [{"kind": "pipeline", "port": 8765, "listen": "127.0.0.1:8765", "public_addr": "10.12.0.31:8765"}],
    )
    # 聚合读直接走 service（路由层另有集成覆盖），机器维度须随行。
    from app.services import instances_service

    payload = instances_service.collect("prod", None, db=db_session, cluster=None)
    instances = payload.get("instances") or []
    assert instances, "聚合读里有实例"
    assert instances[0]["machine_id"] == "node-a01"
