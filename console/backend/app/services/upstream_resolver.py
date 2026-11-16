"""选台：两套策略（spec §5.2）。

为什么有两套：只有占 unit 槽位的端点才受"会话占满"影响——`/v1/realtime`（WS）
和 `/v1/realtime/calls`（WebRTC）会 claim unit，而 ASR / TTS / 声纹 / 情感直接
复用 pool 里的 handler，**不占槽位**（audio_services 的 `find_handlers` 不
claim unit）。用同一套 "free/capacity" 判据给所有端点选台，会让 ASR 被"会话
占满"的机器误杀。

- `rank_session`：容量感知。过滤 → free/capacity 降序 → 同分按 weight 加权随机
  → reserve 乐观占位。与 allocator 的既有语义一致（spec §8.2）。
- `rank_stateless`：在途感知。不看 free/capacity，按 console 侧记录的在途请求数
  升序 —— 这才是 least-conn 的近似。（不用 probe_ms：它来自 /v1/pool 的探测耗时，
  与负载无关，且首次探测成功前为 None，排序会炸。）

能力过滤：声纹/情感是条件注册的，不同实例的端点集合可能不同，所以选台要按能力
过滤（spec §5.1）。`RuntimeState.capabilities` 为空表示"还没探测过"，此时放行，
避免冷启动把候选全灭。
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.services import instance_monitor
from app.services.allocator_store import AllocatorStore

SESSION_PATH = "/v1/realtime"

# 在途计数（console 侧自己知道）：REST 请求进入 +1、结束 -1；WS 会话在
# accept 成功后 +1、断开后 -1。与 AllocatorStore 同生命周期（单 worker）。
_inflight: dict[str, int] = {}
_inflight_lock = threading.Lock()

_rng = random.Random()  # 测试里 monkeypatch allocator._rng = random.Random(42) 保证确定性


@dataclass(frozen=True)
class Allocation:
    """一次选台的结果。connect_url 对 session 策略是 ws:// 地址，对 stateless 是 http 基址。"""

    instance_id: str
    base_url: str
    connect_url: str
    weight: int
    free: int


def grant_connect_url(base_url: str) -> str:
    """http→ws、https→wss（calls_service.handshake_url 的反向，复用其映射表思路）。"""
    parts = urlsplit(base_url.strip())
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme or "ws")
    path = parts.path.rstrip("/") or SESSION_PATH
    if path == "/":
        path = SESSION_PATH
    return urlunsplit((scheme, parts.netloc, path, parts.query, ""))


def inflight_enter(instance_id: str) -> None:
    with _inflight_lock:
        _inflight[instance_id] = _inflight.get(instance_id, 0) + 1


def inflight_exit(instance_id: str) -> None:
    with _inflight_lock:
        current = _inflight.get(instance_id, 0)
        if current <= 1:
            _inflight.pop(instance_id, None)
        else:
            _inflight[instance_id] = current - 1


def inflight_count(instance_id: str) -> int:
    with _inflight_lock:
        return _inflight.get(instance_id, 0)


def reset_inflight() -> None:
    with _inflight_lock:
        _inflight.clear()


def _has_capability(instance_id: str, capability: str) -> bool:
    if not capability:
        return True
    state = instance_monitor.registry.get(instance_id)
    if state is None:
        return False
    if not state.capabilities:
        # 还没探测过能力：先放行。冷启动时不该把候选全灭，等能力轮跑完就严格了。
        return True
    return capability in state.capabilities


def _healthy(spec) -> bool:
    return bool(spec.enabled and spec.weight > 0 and spec.status in ("online", "degraded"))


def _pick(tied: list[Allocation], rng) -> Allocation:
    """同分按 weight 加权随机（spec §8.2 第 3 步）。"""
    chooser = rng if rng is not None else _rng
    return chooser.choices(tied, weights=[a.weight for a in tied], k=1)[0]


def rank_session(
    *,
    store: AllocatorStore,
    capability: str = "",
    exclude: frozenset[str] = frozenset(),
    rng=None,
) -> list[Allocation]:
    """按空闲槽位选台。返回完整候选序（胜者第一），供数据面逐台换。"""
    rows: list[tuple[Allocation, float]] = []
    for spec in store.list_instances():
        if not _healthy(spec):
            continue
        if spec.instance_id in exclude:
            continue
        if not _has_capability(spec.instance_id, capability):
            continue
        free = max(0, spec.effective_free - store.pending_count(spec.instance_id))
        if free <= 0:
            continue
        ratio = free / spec.capacity if spec.capacity else float(free)
        rows.append(
            (
                Allocation(
                    instance_id=spec.instance_id,
                    base_url=spec.base_url,
                    connect_url=grant_connect_url(spec.base_url),
                    weight=spec.weight,
                    free=free,
                ),
                ratio,
            )
        )
    if not rows:
        return []
    best = max(ratio for _, ratio in rows)
    tied = [alloc for alloc, ratio in rows if ratio == best]
    winner = tied[0] if len(tied) == 1 else _pick(tied, rng)
    rest = sorted((row for row in rows if row[0] is not winner), key=lambda row: -row[1])
    return [winner] + [alloc for alloc, _ in rest]


def rank_stateless(
    *,
    store: AllocatorStore,
    capability: str,
    exclude: frozenset[str] = frozenset(),
    rng=None,
    max_inflight: int | None = None,
) -> list[Allocation]:
    """按在途请求数选台（ASR/TTS/声纹/情感：不占 unit 槽位）。"""
    from app.config import console  # noqa: PLC0415 - 避免 import 环

    limit = console.lb_stateless_max_inflight if max_inflight is None else max_inflight
    rows: list[Allocation] = []
    for spec in store.list_instances():
        if not _healthy(spec):
            continue
        if spec.instance_id in exclude:
            continue
        if not _has_capability(spec.instance_id, capability):
            continue
        if limit and inflight_count(spec.instance_id) >= limit:
            continue
        rows.append(
            Allocation(
                instance_id=spec.instance_id,
                base_url=spec.base_url,
                connect_url=spec.base_url,
                weight=spec.weight,
                free=spec.effective_free,
            )
        )
    if not rows:
        return []
    best = min(inflight_count(a.instance_id) for a in rows)
    tied = [a for a in rows if inflight_count(a.instance_id) == best]
    winner = tied[0] if len(tied) == 1 else _pick(tied, rng)
    rest = [a for a in rows if a is not winner]
    return [winner] + rest
