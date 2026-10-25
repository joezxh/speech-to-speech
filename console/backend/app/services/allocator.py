"""本地分配：选实例→签发 grant→兜底降级（spec §8）。

只依赖 AllocatorStore 与 instance_registry，不直接碰 ORM（spec §4 依赖方向）。
"""

from __future__ import annotations

import asyncio
import random
from urllib.parse import urlsplit, urlunsplit

from loguru import logger

from app.config import allocator as settings
from app.services.allocator_store import InMemoryAllocatorStore, InstanceSpec

SESSION_PATH = "/v1/realtime"
store = InMemoryAllocatorStore()
_rng = random.Random()  # 测试里 monkeypatch allocator._rng = random.Random(42) 保证确定性


def grant_connect_url(base_url: str) -> str:
    """http→ws、https→wss（calls_service.handshake_url 的反向，复用其映射表思路）。"""
    parts = urlsplit(base_url.strip())
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme or "ws")
    path = parts.path.rstrip("/") or SESSION_PATH
    if path == "/":
        path = SESSION_PATH
    return urlunsplit((scheme, parts.netloc, path, parts.query, ""))


def _candidates(target: InMemoryAllocatorStore, exclude: set[str]) -> list[InstanceSpec]:
    # spec §8.2 四步：过滤 → free/capacity 降序主排序 → 同分按 weight 加权随机。
    # §6.2 的 pending_local 在这里扣（RuntimeState.effective_free 不包含它）。
    rows: list[tuple[InstanceSpec, float]] = []
    for spec in target.list_instances():
        if not (spec.enabled and spec.weight > 0 and spec.status in ("online", "degraded")):
            continue
        if spec.instance_id in exclude:
            continue
        free = max(0, spec.effective_free - target.pending_count(spec.instance_id))
        if free <= 0:
            continue
        rows.append((spec, free / spec.capacity if spec.capacity else float(free)))
    if not rows:
        return []
    best = max(ratio for _, ratio in rows)
    tied = [spec for spec, ratio in rows if ratio == best]
    if len(tied) == 1:
        return tied
    first = _rng.choices(tied, weights=[spec.weight for spec in tied], k=1)[0]
    return [first] + [spec for spec in tied if spec is not first]


async def allocate(
    session_id: str, *, store: InMemoryAllocatorStore | None = None, claim=None
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
    return len(store._pending)


async def expire_task() -> None:
    """单调时钟回收过期 grant（spec §8.3）；随 lifespan 启停。"""
    while True:
        await asyncio.sleep(max(1, settings.grant_ttl_s // 4))
        for session_id in store.expire_pending():
            logger.debug("expired pending grant {}", session_id)
