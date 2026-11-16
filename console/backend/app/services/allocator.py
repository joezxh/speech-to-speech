"""本地分配：选实例→签发 grant→兜底降级（spec §8）。

只依赖 AllocatorStore 与 instance_registry，不直接碰 ORM（spec §4 依赖方向）。

store 的实现按运行模式选（spec 2026-11-17 §3.2）：
- `local` + 数据面 `proxy` → `DbAllocatorStore`：占位落库，多个控制台副本共享余量，
  不会各自看到"还有空位"而同时派发到同一台；
- 其余 → `InMemoryAllocatorStore`：单副本直连，行为与今天完全一致。
两种实现都满足 `AllocatorStore` Protocol（签名冻结）。
"""

from __future__ import annotations

import asyncio
import random

from loguru import logger

from app.config import allocator as settings
from app.config import console
from app.services import upstream_resolver
from app.services.allocator_store import AllocatorStore, InMemoryAllocatorStore
from app.services.upstream_resolver import Allocation, grant_connect_url

SESSION_PATH = "/v1/realtime"


def _build_store() -> AllocatorStore:
    """按运行模式选 store（spec 2026-11-17 §3.2）。

    这两个开关是启动期语义（`restart_required`）：改了要重启控制台才换实现。
    """
    if settings.mode == "local" and console.lb_mode == "proxy":
        from app.services.db_allocator_store import DbAllocatorStore  # noqa: PLC0415 - 避免 import 环

        return DbAllocatorStore(console_id=settings.resolved_console_id)
    return InMemoryAllocatorStore()


store: AllocatorStore = _build_store()
_rng = random.Random()  # 测试里 monkeypatch allocator._rng = random.Random(42) 保证确定性

__all__ = ["Allocation", "allocate", "drain_counters", "expire_task", "grant_connect_url", "pending_count", "store"]


def _candidates(target: AllocatorStore, exclude: set[str]) -> list[Allocation]:
    # spec §8.2 四步在 upstream_resolver.rank_session 里：过滤 → free/capacity
    # 降序主排序 → 同分按 weight 加权随机。§6.2 的 pending_local 在那里扣
    # （RuntimeState.effective_free 不包含它）。
    return upstream_resolver.rank_session(store=target, exclude=frozenset(exclude), rng=_rng)


async def allocate(
    session_id: str, *, store: AllocatorStore | None = None, claim=None
) -> dict | None:
    target = store if store is not None else globals()["store"]
    tried: set[str] = set()
    for _attempt in range(2):  # 首次 + 换台重试一次（spec §8.4）
        ranked = _candidates(target, tried)
        if not ranked:
            # 首轮就没候选 = 真的无可用实例；换台后被拒的情况已由 503 计数说明原因。
            if not tried:
                target.bump("alloc_fail_no_instance")
            return None
        spec = ranked[0]
        if not target.reserve(spec.instance_id, session_id, settings.grant_ttl_s):
            tried.add(spec.instance_id)
            continue
        refusal = await claim(spec) if claim is not None else ""
        if refusal == "session_limit_reached":
            # 实例 503：释放本机占位、换一台重试一次（spec §8.4）。
            target.release(session_id)
            target.bump(f"alloc_fail_instance_503:{spec.instance_id}")
            tried.add(spec.instance_id)
            continue
        target.bump(f"alloc_ok:{spec.instance_id}")
        return {
            "state": "granted",
            "session_id": session_id,
            "connect_url": grant_connect_url(spec.base_url),
            "expires_in": settings.grant_ttl_s,
        }
    # 走到这里：连续两台 `reserve` 都被乐观修正拦下 → 本机视图无余量。
    target.bump("alloc_fail_no_instance")
    return None


def drain_counters() -> dict[str, int]:
    return store.drain_counters()


def pending_count() -> int:
    """本机已签发未领取的 grant 数。

    DB 版按本副本的 pending 租约统计（共享 store 的口径就是"本机"）；
    内存版直接数自己的 pending 字典。
    """
    shared = getattr(store, "pending_total", None)
    if callable(shared):
        return shared()
    return len(store._pending)


async def expire_task() -> None:
    """单调时钟回收过期 grant（spec §8.3）；随 lifespan 启停。"""
    while True:
        await asyncio.sleep(max(1, settings.grant_ttl_s // 4))
        for session_id in store.expire_pending():
            logger.debug("expired pending grant {}", session_id)
