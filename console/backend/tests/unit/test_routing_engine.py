"""Task 17（2026-11-17 原型对齐计划）——RoutingEngine：规则/粘性/金丝雀/越权。

硬规则（设计 §7.4）：规则空/无票据 → 与改前逐字一致；粘性命中且 reserve 成功 →
直连；粘性过期 → 视为新路由；亲和 key 派生自票据 username（A 写不了 B 的 key）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.errors import ApiError
from app.db.base import Base
from app.repositories.lb_repository import put_affinity
from app.services.lb_policy_service import create_rule
from app.services.routing_service import RoutingEngine, SessionContext, sticky_key


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


def ctx(**over):
    base = {"session_key": "sess-20261117-0001", "username": "alice"}
    base.update(over)
    return SessionContext(**base)


def test_no_rules_and_no_ticket_is_default(db_session):
    decision = RoutingEngine(db_session).resolve(ctx(username=""))
    assert decision.rule_id is None
    assert decision.sticky_hit is False
    assert decision.is_canary is False
    assert decision.candidates.kind == "default"


def test_first_enabled_rule_by_priority_wins(db_session):
    create_rule(db_session, name="lowp", priority=200, match_type="default", match_value="",
                target_kind="instance", target_value="pipe-b", actor="alice")
    create_rule(db_session, name="hip", priority=50, match_type="user_signed", match_value="alice",
                target_kind="instance", target_value="pipe-a", actor="alice")

    decision = RoutingEngine(db_session).resolve(ctx())
    assert decision.rule_id == 2  # priority 50 的先命中
    assert decision.candidates.kind == "pinned_instance"


def test_user_signed_rule_requires_ticket_username(db_session):
    create_rule(db_session, name="vip", priority=100, match_type="user_signed", match_value="bob",
                target_kind="instance", target_value="pipe-b", actor="alice")
    hit = RoutingEngine(db_session).resolve(ctx(username="bob"))
    assert hit.rule_id is not None
    miss = RoutingEngine(db_session).resolve(ctx(username="alice"))
    assert miss.rule_id is None


def test_sticky_hit_pins_and_expired_reroutes(db_session):
    key = sticky_key(ctx())
    put_affinity(db_session, key, machine_id=None, instance_id="pipe-a", rule_id=None, ttl_s=60)
    decision = RoutingEngine(db_session).resolve(ctx())
    assert decision.sticky_hit is True
    assert decision.candidates.kind == "pinned_instance"

    # 过期：expires_at 已过 → 视为新路由（不 sticky）。
    from app.models.lb import ParamLbAffinity
    row = db_session.get(ParamLbAffinity, key)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    rerouted = RoutingEngine(db_session).resolve(ctx())
    assert rerouted.sticky_hit is False


def test_canary_share_pct_approx_split(db_session):
    create_rule(db_session, name="canary", priority=100, match_type="default", match_value="",
                target_kind="instance", target_value="pipe-canary", actor="alice",
                share_pct=20)
    engine = RoutingEngine(db_session)
    hits = sum(
        1 for index in range(1000)
        if engine.resolve(ctx(session_key=f"s-{index}")).is_canary
    )
    assert 120 <= hits <= 280, f"20% 分流在 1000 次模拟中应落 [12%,28%]，实际 {hits/10}%"


def test_affinity_key_cross_user_is_rejected(db_session):
    key = sticky_key(ctx(username="alice"))
    with pytest.raises(ApiError) as denied:
        RoutingEngine(db_session).remember_sticky(key, requested_by="bob", instance_id="pipe-a", ttl_s=60)
    assert denied.value.status == 403


def test_machine_filter_resolves_to_instance_set(db_session):
    from app.models.machine import ParamMachine, ParamMachineWorkload
    from app.models.param_instance import ParamInstance

    db_session.add(ParamMachine(machine_id="node-x"))
    db_session.add(ParamMachineWorkload(machine_id="node-x", kind="pipeline", health_path="/v1/pool", health_interval_s=5))
    db_session.add(ParamInstance(instance_id="pipe-x", base_url="http://10.0.0.5:8765", machine_id="node-x"))
    db_session.add(ParamInstance(instance_id="pipe-y", base_url="http://10.0.0.6:8765", machine_id=None))
    db_session.commit()

    create_rule(db_session, name="to-node-x", priority=100, match_type="tenant_tag", match_value="x",
                target_kind="machine", target_value="node-x", actor="alice")
    decision = RoutingEngine(db_session).resolve(ctx(tenant_tag="x"))
    assert decision.candidates.kind == "machine_filter"
    assert decision.candidates.instance_ids == frozenset({"pipe-x"})
