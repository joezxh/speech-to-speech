from __future__ import annotations

import pytest

from app.config import allocator as allocator_settings
from app.services import allocator, instance_monitor
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


class _StubRng:
    """同分加权随机的可观测替身（spec §8.2 第 3 步）。真实 `random.Random` 即使
    固定 seed 也无法在写计划时预测选中哪一个，所以这里按 id 指定胜者并记录入参。"""

    def __init__(self, winner_id: str) -> None:
        self.winner_id = winner_id
        self.calls: list[tuple[list[str], list[int], int]] = []

    def choices(self, population, *, weights, k):
        self.calls.append(([spec.instance_id for spec in population], list(weights), k))
        return [spec for spec in population if spec.instance_id == self.winner_id]


@pytest.fixture
def two_online(monkeypatch):
    """pipe-a 空载 4/0（free ratio 1.0）、pipe-b 5/3（2/5 = 0.4）。
    取 0.4 是为了避开 pipe-a 随 pending 递减的 ratio 列 1.0/0.75/0.5/0.25，
    让主排序直接分出胜负（同分分支由下面的专用用例覆盖）。"""
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._counters.clear()
    for iid, size, in_use in (("pipe-a", 4, 0), ("pipe-b", 5, 3)):
        instance_monitor.registry._states[iid] = RuntimeState(
            instance_id=iid, base_url=f"http://{iid}:8765"
        )
        instance_monitor.registry.observe_success(
            iid, PoolState(reachable=True, size=size, in_use=in_use, units=()), 5
        )
    monkeypatch.setattr(allocator_settings, "grant_ttl_s", 60)
    return instance_monitor.registry


async def test_grant_shape_matches_the_demo_contract(two_online):
    grant = await allocator.allocate("s-1")
    assert grant["state"] == "granted" and grant["session_id"] == "s-1"
    assert grant["connect_url"] == "ws://pipe-a:8765/v1/realtime"  # free ratio 1.0 > 0.4
    assert grant["expires_in"] == 60


async def test_least_loaded_switches_when_the_richer_instance_fills_up(two_online):
    for i in range(3):  # pipe-a 的 free ratio 逐次 1.0 → 0.75 → 0.5，均高于 pipe-b 的 0.4
        assert (await allocator.allocate(f"s-{i}"))["connect_url"].startswith("ws://pipe-a")
    # 第 4 次 pipe-a 降到 0.25 < 0.4 → 自然切到次空闲的一台（spec §6.2/§8.2）
    assert (await allocator.allocate("s-x"))["connect_url"].startswith("ws://pipe-b")


async def test_tied_ratio_uses_weighted_random_by_weight(two_online, monkeypatch):
    two_online.get("pipe-a").weight = 3
    two_online.observe_success(
        "pipe-b", PoolState(reachable=True, size=5, in_use=0, units=()), 5
    )
    # 两台都空载 → free ratio 同为 1.0 → 走同分分支，由注入的 RNG 决定
    stub = _StubRng("pipe-b")
    monkeypatch.setattr(allocator, "_rng", stub)
    assert (await allocator.allocate("s-1"))["connect_url"].startswith("ws://pipe-b")
    assert stub.calls == [(["pipe-a", "pipe-b"], [3, 1], 1)]  # weight 透传，k=1


async def test_503_from_the_first_instance_retries_the_second_once(two_online):
    calls: list[str] = []

    async def claim(spec):
        calls.append(spec.instance_id)
        return "session_limit_reached" if len(calls) == 1 else ""

    grant = await allocator.allocate("s-9", claim=claim)
    assert grant["connect_url"].startswith("ws://pipe-b")
    assert calls == ["pipe-a", "pipe-b"]  # 首台被拒 → 只换台重试一次（spec §8.4）
    assert allocator.drain_counters() == {
        "alloc_fail_instance_503:pipe-a": 1,
        "alloc_ok:pipe-b": 1,
    }


async def test_expired_pending_frees_the_slot(two_online):
    # 不 monkeypatch time.monotonic：异步测试里冻结单调会干扰事件循环。直接植入已过期 pending。
    for i in range(4):
        allocator.store._pending[f"old-{i}"] = ("pipe-a", -1.0)
    # pipe-a 的 4 个槽位被过期 pending 扣光 → 只能选 pipe-b
    assert (await allocator.allocate("s-1"))["connect_url"].startswith("ws://pipe-b")
    assert allocator.store.expire_pending() == [f"old-{i}" for i in range(4)]
    # 回收后 pipe-a 回到 free ratio 1.0，又成了首选（spec §8.3）
    assert (await allocator.allocate("s-2"))["connect_url"].startswith("ws://pipe-a")


async def test_empty_registry_returns_none_and_counts_failure(two_online):
    instance_monitor.reset_for_tests()
    assert await allocator.allocate("s-1") is None
    assert allocator.drain_counters() == {"alloc_fail_no_instance": 1}


async def test_draining_instance_is_never_selected(two_online):
    two_online.set_drain("pipe-a", True)
    two_online.set_drain("pipe-b", True)
    assert await allocator.allocate("s-1") is None
    assert allocator.drain_counters() == {"alloc_fail_no_instance": 1}
