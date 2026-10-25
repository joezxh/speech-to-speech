import pytest

from app.services import instance_monitor
from app.services.allocator import allocate
from app.services.allocator_store import InMemoryAllocatorStore
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


@pytest.mark.asyncio
async def test_two_stores_overcommit_only_yield_at_capacity():
    """两台 console 各持内存 store，但共享同一个实例视图：实例只有 1 个槽位。

    本机的乐观修正只防同机重复派发，看不见对端的 pending（spec §6.2），所以
    两台都会先拿到本地 grant；实例是槽位的最终仲裁者（spec §8.4），第二个
    连接一定吃 503 → 换台无可换 → allocate 返 None → 调用方回 503 at_capacity。"""
    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry.observe_success(
        "pipe-a", PoolState(reachable=True, size=1, in_use=0, units=()), 5)
    a, b = InMemoryAllocatorStore(), InMemoryAllocatorStore()
    remaining = [1]  # 实例侧只有 1 个真槽位

    async def instance_arbiter(spec):
        if remaining[0] > 0:
            remaining[0] -= 1
            return ""
        return "session_limit_reached"

    g1 = await allocate("s-a", store=a, claim=instance_arbiter)
    g2 = await allocate("s-b", store=b, claim=instance_arbiter)
    assert g1 is not None and g1["session_id"] == "s-a"
    assert g2 is None  # 超发的唯一下场：503 at_capacity，无异常态
    assert a.drain_counters() == {"alloc_ok:pipe-a": 1}
    assert b.drain_counters() == {"alloc_fail_instance_503:pipe-a": 1}
    # B 被拒后释放了自己的乐观占位，不会泄漏 pending_local
    assert b.pending_count("pipe-a") == 0
