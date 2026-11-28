"""Task 14（2026-11-17 原型对齐计划）——token 观测分析（T1–T4）与 LB 策略（L1–L6）。

公式只在后端算（§9.2.4）；无路由日志时 sticky_hit_rate=None（不可得，不是 0）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.errors import ApiError
from app.db.base import Base
from app.repositories.lb_repository import append_route_log
from app.repositories.token_metric_repository import TokenDelta, append_delta
from app.services import lb_policy_service, token_analytics_service

NOW = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)


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


def _seed(db_session):
    from app.models.machine import ParamMachine, ParamMachineWorkload  # noqa: PLC0415

    db_session.add(ParamMachine(machine_id="node-a01", gpu_total_gb=48))
    db_session.add(ParamMachine(machine_id="node-b02", gpu_total_gb=48))
    db_session.add(ParamMachineWorkload(machine_id="node-a01", kind="pipeline", health_path="/v1/pool", health_interval_s=5))
    db_session.add(ParamMachineWorkload(machine_id="node-a01", kind="llm", health_path="/health", health_interval_s=30))
    db_session.add(ParamMachineWorkload(machine_id="node-b02", kind="llm", health_path="/health", health_interval_s=30))
    db_session.commit()

    base = NOW - timedelta(minutes=10)
    append_delta(db_session, "node-a01", TokenDelta(input_tokens=600, output_tokens=400, responses=5, audio_duration_s=60.0, window_s=600), observed_at=base)
    append_delta(db_session, "node-a01", TokenDelta(input_tokens=100, output_tokens=100, responses=1, audio_duration_s=10.0, window_s=60), observed_at=NOW - timedelta(minutes=2))
    append_delta(db_session, "node-b02", TokenDelta(input_tokens=300, output_tokens=500, responses=4, audio_duration_s=30.0, window_s=300), observed_at=NOW - timedelta(minutes=3))


def test_window_boundaries_are_aligned(db_session):
    _seed(db_session)
    # 5m 窗只含最近 5 分钟的行（node-a01 的第二窗与 node-b02 的窗）。
    summary = token_analytics_service.summary(db_session, None, "5m", now=NOW)
    assert summary["total"] == (100 + 100) + (300 + 500)
    # 1h 窗含全部。
    hour = token_analytics_service.summary(db_session, None, "1h", now=NOW)
    assert hour["total"] == (600 + 400) + (100 + 100) + (300 + 500)


def test_prompt_completion_split_and_per_minute(db_session):
    _seed(db_session)
    summary = token_analytics_service.summary(db_session, None, "1h", now=NOW)
    assert summary["input"] == 1000 and summary["output"] == 1000
    assert summary["total"] == 2000
    assert summary["per_minute"] == round(2000 / 3600 * 60, 1)


def test_cost_formula_uses_configured_prices(db_session, monkeypatch):
    _seed(db_session)
    monkeypatch.setenv("S2S_TOKEN_PRICE_IN", "2.0")   # $/Mtok
    monkeypatch.setenv("S2S_TOKEN_PRICE_OUT", "8.0")
    summary = token_analytics_service.summary(db_session, None, "1h", now=NOW)
    # (1000/1e6)*2.0 + (1000/1e6)*8.0 = 0.01
    assert summary["cost_usd"] == pytest.approx(0.01)


def test_distribution_share_pct_normalized(db_session):
    _seed(db_session)
    dist = token_analytics_service.distribution(db_session, None, "1h", now=NOW)
    by_machine = {row["machine_id"]: row for row in dist}
    assert by_machine["node-a01"]["tokens"] == 1200
    assert by_machine["node-b02"]["tokens"] == 800
    assert sum(row["share_pct"] for row in dist) == pytest.approx(100, abs=0.5)


def test_egress_groups_by_kind_and_route(db_session):
    _seed(db_session)
    rows = token_analytics_service.egress(db_session, None, "1h", now=NOW)
    by_kind = {row["kind"]: row for row in rows}
    assert by_kind["pipeline"]["route"] == "lb", "kind==pipeline → route=lb"
    assert by_kind["llm"]["route"] == "direct"
    assert sum(row["tokens"] for row in rows) == 2000


def test_egress_carries_engine_hosts_load_and_vram(db_session):
    """出口卡 7 列：kind/engine/hosts/load/tokens/vram/route。"""
    from app.models.param_instance import ParamInstance  # noqa: PLC0415

    _seed(db_session)
    db_session.add(
        ParamInstance(
            instance_id="pipe-a", machine_id="node-a01", base_url="http://node-a01:8765",
        )
    )
    db_session.commit()

    rows = token_analytics_service.egress(db_session, None, "1h", now=NOW)
    by_kind = {row["kind"]: row for row in rows}
    pipeline = by_kind["pipeline"]
    assert pipeline["hosts"] == ["node-a01"]
    assert pipeline["load"] == "1 · instances"
    llm = by_kind["llm"]
    assert set(llm["hosts"]) == {"node-a01", "node-b02"}
    assert llm["load"] == "2 machines"
    assert "vram_gb" in pipeline and "engine" in pipeline


def test_route_stats_without_logs_has_none_sticky_rate(db_session):
    result = lb_policy_service.route_stats(db_session, window_s=3600)
    assert result["rules"] == []
    assert result["sticky_hit_rate"] is None, "不可得是 None，不是 0"


def test_route_stats_counts_matches_and_sticky(db_session):
    base = NOW - timedelta(minutes=5)
    append_route_log(db_session, session_key="s1", rule_id=7, matched=True, sticky_hit=False, input_tokens=10, output_tokens=0, at=base)
    append_route_log(db_session, session_key="s2", rule_id=7, matched=True, sticky_hit=True, input_tokens=30, output_tokens=0, at=base)
    append_route_log(db_session, session_key="s3", rule_id=None, matched=False, sticky_hit=False, input_tokens=10, output_tokens=0, at=base)

    result = lb_policy_service.route_stats(db_session, window_s=3600, now=NOW)
    rules = {row["rule_id"]: row for row in result["rules"]}
    assert rules[7]["matched"] == 2
    assert rules[7]["tokens"] == 40
    # Task 18 口径：sticky/(sticky+新建)=1/2，未匹配行不进分母。
    assert result["sticky_hit_rate"] == 0.5


def test_rule_crud_priority_unique_and_match_value_required(db_session):
    created = lb_policy_service.create_rule(
        db_session, name="canary-a", priority=100, match_type="session_prefix",
        match_value="vip-", target_kind="instance", target_value="pipe-a", actor="alice",
    )
    assert created["name"] == "canary-a"

    # 优先级唯一：撞 100 → 409
    with pytest.raises(ApiError) as conflict:
        lb_policy_service.create_rule(
            db_session, name="canary-b", priority=100, match_type="default",
            match_value="", target_kind="instance", target_value="", actor="alice",
        )
    assert conflict.value.status == 409

    # 非默认规则缺 match_value → 400
    with pytest.raises(ApiError) as missing:
        lb_policy_service.create_rule(
            db_session, name="canary-c", priority=110, match_type="session_prefix",
            match_value="", target_kind="instance", target_value="x", actor="alice",
        )
    assert missing.value.status == 400

    updated = lb_policy_service.update_rule(db_session, created["id"], priority=90, actor="alice")
    assert updated["priority"] == 90

    lb_policy_service.delete_rule(db_session, created["id"])
    assert lb_policy_service.rules(db_session) == []


def test_policy_snapshot_reports_source_and_effect(db_session, monkeypatch):
    monkeypatch.delenv("S2S_TOKEN_PRICE_IN", raising=False)
    policy = token_analytics_service.policy(db_session)
    assert len(policy["items"]) == 4
    for item in policy["items"]:
        assert item["source"] in ("env", "default")
        assert "effective" in item
