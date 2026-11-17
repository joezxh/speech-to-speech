"""Task 17 数据面接线：WS 票据身份 → SessionContext → RoutingEngine → rank_session。

- 票据一次性消费后 username 进亲和键（JWT 不上查询串）；
- 粘性目标满员/不可达 → 删亲和行、回落重选、记理由 sticky_target_unavailable；
- 选台成功后亲和写不阻塞数据面（后台线程执行）。
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.lb import ParamLbAffinity
from app.repositories.lb_repository import put_affinity
from app.services import realtime_ticket, routing_service, upstream_resolver
from app.services.routing_service import (
    RoutingEngine,
    SessionContext,
    context_from_ticket,
    drop_sticky,
    sticky_key,
)


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    session = factory()
    try:
        yield session, factory
    finally:
        session.close()


class FakeSpec:
    def __init__(self, instance_id, free=4, capacity=4):
        self.instance_id = instance_id
        self.base_url = f"http://10.0.0.{instance_id[-1]}:8765"
        self.weight = 1
        self.enabled = True
        self.status = "online"
        self.effective_free = free
        self.capacity = capacity


class FakeStore:
    def list_instances(self):
        return [FakeSpec("pipe-a"), FakeSpec("pipe-b")]

    def pending_count(self, _):
        return 0


def test_ticket_identity_feeds_session_context():
    ticket = realtime_ticket.issue("alice", "admin")
    ctx = context_from_ticket(ticket, session_key="s-1", tenant_tag="x")
    assert ctx.username == "alice"
    assert ctx.tenant_tag == "x"
    assert sticky_key(ctx) == "alice:s-1"
    # 一次性：二次消费无身份（匿名），仍可路由（规则空 → 改前行为）
    assert context_from_ticket(ticket, session_key="s-1").username == ""


def test_sticky_target_unavailable_drops_affinity(db_session):
    session, _ = db_session
    key = "alice:s-1"
    put_affinity(session, key, machine_id=None, instance_id="pipe-a", rule_id=None, ttl_s=60)
    assert session.scalar(select(ParamLbAffinity).where(ParamLbAffinity.affinity_key == key)) is not None

    drop_sticky(session, key)
    assert session.scalar(select(ParamLbAffinity).where(ParamLbAffinity.affinity_key == key)) is None

    # 亲和行删后重新评估 → 不再 sticky，回落可选其它机器
    ctx = SessionContext(session_key="s-1", username="alice")
    decision = RoutingEngine(session).resolve(ctx)
    assert decision.sticky_hit is False
    ranked = upstream_resolver.rank_session(store=FakeStore(), rng=random.Random(1), routing=decision)
    assert len(ranked) == 2


def test_remember_sticky_async_does_not_block_caller(db_session):
    session, factory = db_session
    key = "alice:s-2"
    handle = routing_service.remember_sticky_async(
        factory, key, requested_by="alice", instance_id="pipe-b", ttl_s=60
    )
    handle.join(timeout=3)
    assert session.scalar(select(ParamLbAffinity).where(ParamLbAffinity.affinity_key == key)).instance_id == "pipe-b"


def test_ws_routing_helper_consumes_ticket(db_session):
    from app.routers.realtime import routing_for_websocket
    from app.services.lb_policy_service import create_rule

    session, _ = db_session
    create_rule(
        session, name="vip", priority=100, match_type="user_signed", match_value="alice",
        target_kind="instance", target_value="pipe-b", actor="alice",
    )

    class FakeWebSocket:
        def __init__(self, params: dict):
            self.query_params = params

    ticket = realtime_ticket.issue("alice", "admin")
    decision = routing_for_websocket(
        session, FakeWebSocket({"ticket": ticket, "session_key": "s-9", "tenant_tag": "x"})
    )
    assert decision.affinity_key == "alice:s-9"
    assert decision.candidates.instance_id == "pipe-b"
    # 票据已消费：同一票据二次握手 → 匿名 → 规则不命中 → default
    anonymous = routing_for_websocket(session, FakeWebSocket({"ticket": ticket, "session_key": "s-9"}))
    assert anonymous.candidates.kind == "default"
