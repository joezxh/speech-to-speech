"""DbAllocatorStore 的行为（spec 2026-11-17 §3.2）。

守住这几条不变量：
- 占位不超发：条件 UPDATE + rowcount，两个副本共享同一份余量；
- hold 之后不再靠 TTL 回收，但仍然占着槽位；
- release / expire 把 `reserved` 还回去；
- DB 不可用时预留失败（宁可少派不超发），不抛异常。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.repositories.instance_runtime_repository import InstanceRuntimeRepository
from app.services import instance_monitor
from app.services.allocator_store import AllocatorStore, InMemoryAllocatorStore
from app.services.db_allocator_store import DbAllocatorStore


@pytest.fixture
def factory(db_session):
    return sessionmaker(bind=db_session.get_bind(), future=True)


@pytest.fixture
def runtime_row(db_session):
    """一台容量为 2 的在线实例（探测结果已落库）。"""
    return InstanceRuntimeRepository(db_session).upsert(
        instance_id="pipe-a",
        observed_by="test",
        status="online",
        pool_size=2,
        in_use=0,
        stuck=0,
        probe_ms=5,
        capabilities=["realtime"],
        capability_issues={},
        consecutive_failures=0,
        consecutive_successes=1,
        last_error="",
        probe_history=[5],
    )


@pytest.fixture
def store(factory, runtime_row):
    instance_monitor.reset_for_tests()
    return DbAllocatorStore(factory, console_id="console-1")


def test_reserve_is_capped_by_the_shared_free_slots(store, runtime_row):
    assert store.reserve("pipe-a", "s1", 60) is True
    assert store.reserve("pipe-a", "s2", 60) is True
    # 容量 2，两个预留占满，第三个被条件 UPDATE 挡住（spec §3.2）。
    assert store.reserve("pipe-a", "s3", 60) is False
    assert store.pending_count("pipe-a") == 2


def test_release_frees_the_slot(store, runtime_row):
    store.reserve("pipe-a", "s1", 60)
    store.release("s1")
    assert store.pending_count("pipe-a") == 0
    # 释放之后还能再占。
    assert store.reserve("pipe-a", "s2", 60) is True


def test_hold_keeps_the_slot_but_drops_the_ttl(store, runtime_row, db_session):
    store.reserve("pipe-a", "s1", 60)
    store.hold("s1", "pipe-a")
    from app.repositories.allocator_lease_repository import AllocatorLeaseRepository

    lease = AllocatorLeaseRepository(db_session).get("s1")
    assert lease is not None
    assert lease.state == "held"
    assert lease.expires_at is None
    # held 仍然占着槽位。
    assert store.pending_count("pipe-a") == 1


def test_expire_pending_reclaims_by_wallclock(store, runtime_row):
    store.reserve("pipe-a", "s1", 0)
    assert store.expire_pending() == ["s1"]
    assert store.pending_count("pipe-a") == 0


def test_two_replicas_cannot_overcommit(factory, runtime_row):
    """两个控制台副本共享同一份余量：先占满的那个赢，后来的拿不到。"""
    one = DbAllocatorStore(factory, console_id="console-1")
    two = DbAllocatorStore(factory, console_id="console-2")
    assert one.reserve("pipe-a", "s1", 60) is True
    assert one.reserve("pipe-a", "s2", 60) is True
    assert two.reserve("pipe-a", "s3", 60) is False
    assert two.pending_count("pipe-a") == 2


def test_pending_total_counts_only_this_console(factory, runtime_row):
    one = DbAllocatorStore(factory, console_id="console-1")
    two = DbAllocatorStore(factory, console_id="console-2")
    one.reserve("pipe-a", "s1", 60)
    two.reserve("pipe-a", "s2", 60)
    assert one.pending_total() == 1
    assert two.pending_total() == 1


def test_a_broken_database_fails_the_reserve_without_raising(runtime_row):
    class _Boom:
        def __call__(self):
            raise RuntimeError("db is down")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    broken = DbAllocatorStore(_Boom(), console_id="console-1")
    assert broken.reserve("pipe-a", "s1", 60) is False


def test_both_stores_cover_the_frozen_protocol():
    methods = {name for name in dir(AllocatorStore) if not name.startswith("_")}
    for implementation in (InMemoryAllocatorStore(), DbAllocatorStore()):
        missing = [name for name in methods if not hasattr(implementation, name)]
        assert missing == [], f"{type(implementation).__name__} misses {missing}"  
