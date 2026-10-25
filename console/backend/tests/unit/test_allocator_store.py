from __future__ import annotations

import time

import pytest

from app.services import instance_monitor
from app.services.allocator_store import InMemoryAllocatorStore
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


@pytest.fixture
def store(monkeypatch):
    instance_monitor.reset_for_tests()
    state = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry._states["pipe-a"] = state
    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=2, units=()), 5)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    return InMemoryAllocatorStore()


def test_reserve_is_capped_by_effective_free(store):
    assert store.reserve("pipe-a", "s1", 60) is True
    assert store.reserve("pipe-a", "s2", 60) is True
    # size=2，两个 pending 已占满，第三个拒绝（乐观修正，spec §6.2）
    assert store.reserve("pipe-a", "s3", 60) is False
    assert store.pending_count("pipe-a") == 2


def test_release_frees_the_slot(store):
    store.reserve("pipe-a", "s1", 60)
    store.release("s1")
    assert store.pending_count("pipe-a") == 0


def test_expire_pending_uses_monotonic_not_wallclock(store, monkeypatch):
    store.reserve("pipe-a", "s1", 60)
    monkeypatch.setattr(time, "monotonic", lambda: 1061.0)  # +61s
    assert store.expire_pending() == ["s1"]
    assert store.pending_count("pipe-a") == 0


def test_begin_once_dedupes_within_the_window(store, monkeypatch):
    assert store.begin_once("req-1", 10) is None
    assert store.begin_once("req-1", 10) == "deduped"
    monkeypatch.setattr(time, "monotonic", lambda: 1011.0)  # 窗口外
    assert store.begin_once("req-1", 10) is None


def test_bump_accumulates_and_drain_resets(store):
    store.bump("alloc_ok:pipe-a")
    store.bump("alloc_ok:pipe-a")
    store.bump("alloc_fail_no_instance")
    assert store.drain_counters() == {"alloc_ok:pipe-a": 2, "alloc_fail_no_instance": 1}
    assert store.drain_counters() == {}


def test_queue_methods_exist_but_stay_unused_in_p1(store):
    # spec §3：本地队列本期关闭，契约保留即可；不抛异常 = Protocol 完整。
    assert store.enqueue("t1", {}) == 1
    assert store.peek_queue()[0].ticket_id == "t1"
    assert store.pop_queue().ticket_id == "t1"
    assert store.pop_queue() is None
