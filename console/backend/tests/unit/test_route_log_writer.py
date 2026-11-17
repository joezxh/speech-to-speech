"""Task 18（2026-11-17 原型对齐计划）——路由记账异步落库 + L6 统计接真值。

submit 绝不阻塞选台（内存队列）；flush 批量入库；队列满丢弃并计数；
sticky_hit_rate = sticky/(sticky+新建)；未归因 token 计入"未匹配"。
"""

from __future__ import annotations

import queue
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.lb import ParamLbRouteLog
from app.repositories.lb_repository import append_route_log
from app.services import lb_policy_service, route_log_writer
from app.services.route_log_writer import RouteLogEntry


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


def test_submit_then_flush_writes_rows(db_session):
    route_log_writer.reset_for_test()
    route_log_writer.submit(RouteLogEntry(session_key="s1", rule_id=3, matched=True, input_tokens=10, output_tokens=5))
    route_log_writer.submit(RouteLogEntry(session_key="s2", rule_id=None, matched=False, sticky_hit=True, input_tokens=20))
    assert db_session.scalar(select(func.count()).select_from(ParamLbRouteLog)) == 0

    written = route_log_writer.flush(db_session)
    assert written == 2
    assert db_session.scalar(select(func.count()).select_from(ParamLbRouteLog)) == 2


def test_queue_full_drops_and_counts(db_session, monkeypatch):
    route_log_writer.reset_for_test()
    monkeypatch.setattr(route_log_writer, "_QUEUE", queue.Queue(maxsize=2))
    for index in range(5):
        route_log_writer.submit(RouteLogEntry(session_key=f"s{index}"))
    stats = route_log_writer.queue_stats()
    assert stats["queued"] == 2
    assert stats["dropped"] == 3, "队列满丢弃并计数（绝不阻塞选台）"


def test_sticky_hit_rate_denominator_excludes_unattributed(db_session):
    now = datetime.now(UTC)
    append_route_log(db_session, session_key="a", rule_id=3, matched=True, sticky_hit=True, input_tokens=10, at=now)
    append_route_log(db_session, session_key="b", rule_id=3, matched=True, sticky_hit=False, input_tokens=20, at=now)
    append_route_log(db_session, session_key="c", rule_id=None, matched=False, input_tokens=999, at=now)

    stats = lb_policy_service.route_stats(db_session, window_s=3600, now=now)
    assert stats["sticky_hit_rate"] == 0.5, "sticky/(sticky+新建)，未归因行不进分母"
    # 未归因的 token 计入"未匹配"桶
    assert any(row["rule_id"] is None and row["tokens"] == 999 for row in stats["rules"])


def test_flush_is_idempotent(db_session):
    route_log_writer.reset_for_test()
    route_log_writer.submit(RouteLogEntry(session_key="s1", input_tokens=5))
    assert route_log_writer.flush(db_session) == 1
    assert route_log_writer.flush(db_session) == 0
    assert db_session.scalar(select(func.count()).select_from(ParamLbRouteLog)) == 1
