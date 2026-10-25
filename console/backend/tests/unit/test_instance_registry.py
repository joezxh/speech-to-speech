from __future__ import annotations

import pytest

from app.services.instance_registry import InstanceRegistry
from app.services.pool import PoolState


def _pool(size=4, in_use=0, stuck=0):
    units = []
    for i in range(size):
        if i < stuck:
            units.append({"index": i, "state": "stuck", "session_id": None})
        elif i < in_use:
            units.append({"index": i, "state": "active", "session_id": f"s{i}"})
        else:
            units.append({"index": i, "state": "idle", "session_id": None})
    return PoolState(reachable=True, size=size, in_use=in_use, units=tuple(units))


@pytest.fixture
def reg():
    r = InstanceRegistry(fail_threshold=3, recover_threshold=2)
    r.sync([("pipe-a", "http://a:8765", 1, True, False)])
    return r


def test_starts_unknown_and_not_allocatable(reg):
    state = reg.get("pipe-a")
    assert state.status == "unknown"
    assert reg.allocatable() == []


def test_first_success_goes_online(reg):
    assert reg.observe_success("pipe-a", _pool(), 10).status == "online"


def test_two_failures_do_not_evict_three_do(reg):
    reg.observe_success("pipe-a", _pool(), 10)
    reg.observe_failure("pipe-a", "timeout")
    reg.observe_failure("pipe-a", "timeout")
    assert reg.get("pipe-a").status == "online"  # 2 次不摘（spec §15 P1.1）
    assert reg.observe_failure("pipe-a", "timeout").status == "offline"  # 第 3 次摘


def test_recovery_needs_two_successes(reg):
    for _ in range(3):
        reg.observe_failure("pipe-a", "x")
    assert reg.get("pipe-a").status == "offline"
    reg.observe_success("pipe-a", _pool(), 5)
    assert reg.get("pipe-a").status == "offline"  # 1 次不恢复
    assert reg.observe_success("pipe-a", _pool(), 5).status == "online"  # 2 次恢复


def test_stuck_makes_degraded_then_clearing_returns_online(reg):
    reg.observe_success("pipe-a", _pool(stuck=1), 5)
    assert reg.get("pipe-a").status == "degraded"
    assert reg.observe_success("pipe-a", _pool(), 5).status == "online"


def test_drain_wins_over_probe_results_and_undrain_restores(reg):
    reg.observe_success("pipe-a", _pool(), 5)
    assert reg.set_drain("pipe-a", True).status == "draining"
    reg.observe_success("pipe-a", _pool(stuck=2), 5)  # 探测不改变 draining
    assert reg.get("pipe-a").status == "draining"
    assert reg.set_drain("pipe-a", False).status == "online"  # 已有健康探测结果，直接回 online


def test_undrain_from_draining_without_any_probe_goes_unknown(reg):
    r = InstanceRegistry(fail_threshold=3, recover_threshold=2)
    r.sync([("pipe-b", "http://b:8765", 1, True, True)])  # 重启后 drain_requested 保持
    assert r.get("pipe-b").status == "draining"
    assert r.set_drain("pipe-b", False).status == "unknown"  # 从未探过，等首轮巡检


def test_effective_free_subtracts_in_use_and_stuck(reg):
    reg.observe_success("pipe-a", _pool(size=4, in_use=2, stuck=1), 5)
    state = reg.get("pipe-a")
    assert state.effective_free == 1  # max(0, 4-2-1-0)，pending 由 allocator 再扣（spec §6.2）


def test_probe_history_keeps_rolling_20_for_percentiles(reg):
    for i in range(25):
        reg.observe_success("pipe-a", _pool(), i)
    assert len(reg.get("pipe-a").probe_history) == 20
    assert reg.get("pipe-a").p95_probe_ms is not None
