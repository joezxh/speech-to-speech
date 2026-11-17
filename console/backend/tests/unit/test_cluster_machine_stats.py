"""集群统计把 param_machine 计入机器数（用户反馈：机器注册到集群后总览页数目为 0）。

口径（spec §4.2 的自然延伸）：集群成员 = 实例 host 去重 ∪ 该集群的 param_machine 行；
在线 = 有 online 实例的 host ∪ state==online 且其绑定实例（若有）不提供 online 的机器。
instance.host 与 machine 按 public_addr 匹配去重——同一台机器既有实例又有 param_machine
行时只算一台。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.machine import ParamMachine
from app.models.param_instance import ParamInstance
from app.services import cluster_service
from app.services.machine_service import MachineCreate
from app.services import machine_service


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


def _machine(db_session, machine_id: str, cluster: str, state: str = "online") -> None:
    db_session.add(
        ParamMachine(
            machine_id=machine_id,
            cluster_id=cluster,
            state=state,
            addr="10.0.0.1",
        )
    )
    db_session.commit()


def _instance(db_session, instance_id: str, cluster: str, base_url: str, status: str = "online") -> None:
    db_session.add(
        ParamInstance(
            instance_id=instance_id,
            cluster_id=cluster,
            base_url=base_url,
        )
    )
    db_session.commit()


def test_machine_registered_in_cluster_counts_even_without_instances(db_session):
    _machine(db_session, "node-a01", "default", state="online")
    stats = cluster_service.instance_host_stats(db_session, "default")
    assert stats["machines_total"] == 1, "集群里注册了机器但还没实例 → 机器数应为 1 而非 0"
    assert stats["machines_online"] == 1


def test_machine_and_instance_same_host_dedup(db_session):
    # 同一集群：实例（host=10.0.0.1）+ 机器行（public_addr 命中同 host）→ 只算一台。
    _machine(db_session, "node-a01", "default", state="online")
    _instance(db_session, "pipe-a", "default", "http://10.0.0.1:8765")
    stats = cluster_service.instance_host_stats(db_session, "default")
    assert stats["machines_total"] == 1
    assert stats["instances_total"] == 1


def test_offline_machine_counts_total_but_not_online(db_session):
    _machine(db_session, "node-a01", "default", state="pending_register")
    stats = cluster_service.instance_host_stats(db_session, "default")
    assert stats["machines_total"] == 1
    assert stats["machines_online"] == 0


def test_other_cluster_machines_do_not_leak(db_session):
    _machine(db_session, "node-a01", "edge", state="online")
    stats = cluster_service.instance_host_stats(db_session, "default")
    assert stats["machines_total"] == 0
