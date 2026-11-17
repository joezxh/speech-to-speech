"""集群总览「最近事件」卡扩为 cluster.* ∪ machine.*（用户反馈：添加机器后事件区空）。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.repositories.audit_repository import AuditRepository


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


def test_list_any_prefix_merges_and_orders_by_recency(db_session):
    repo = AuditRepository(db_session)
    repo.record(actor="alice", role="admin", action="cluster.create", profile="default", fields=["name"])
    repo.record(actor="alice", role="admin", action="machine.create", profile="node-a01", fields=["addr"])
    repo.record(actor="alice", role="admin", action="voice.create", profile="v1", fields=[])

    rows = repo.list_any_prefix(["cluster.", "machine."], limit=10)
    actions = [row.action for row in rows]
    assert actions == ["machine.create", "cluster.create"], "按 id 倒序，voice.* 不在内"

    limited = repo.list_any_prefix(["cluster.", "machine."], limit=1)
    assert [row.action for row in limited] == ["machine.create"], "limit 截取最新的"
