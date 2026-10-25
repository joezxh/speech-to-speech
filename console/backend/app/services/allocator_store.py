"""AllocatorStore：Phase 2 的替换点（spec §13，签名冻结）。

本期唯一实现 InMemoryAllocatorStore：单把 threading.Lock，与 console 单
worker 约束一致（spec §16）。时间一律 time.monotonic，避免多实例机器间
时钟偏差抖动租约（spec §8.3）。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.services import instance_monitor
from app.services.instance_registry import RuntimeState

# 注册表一律晚绑定（`instance_monitor.registry`）：`reset_for_tests()` 会重新
# 绑定那个对象，`from ... import registry` 的早绑定会让测试看见旧注册表。


class AllocatorStore(Protocol):
    def list_instances(self) -> list[InstanceSpec]: ...
    def snapshot_runtime(self) -> dict[str, RuntimeState]: ...
    def upsert_runtime(self, state: RuntimeState) -> None: ...
    def reserve(self, instance_id: str, session_id: str, ttl_s: int) -> bool: ...
    def release(self, session_id: str) -> None: ...
    def expire_pending(self) -> list[str]: ...
    def pending_count(self, instance_id: str) -> int: ...
    def begin_once(self, dedupe_key: str, window_s: int) -> str | None: ...
    def remember_grant(self, dedupe_key: str, grant: dict) -> None: ...
    def grant_for(self, dedupe_key: str) -> dict | None: ...
    def enqueue(self, ticket_id: str, meta: dict) -> int: ...
    def peek_queue(self) -> list[QueueTicket]: ...
    def pop_queue(self) -> QueueTicket | None: ...
    def bump(self, counter: str, delta: int = 1) -> int: ...
    def drain_counters(self) -> dict[str, int]: ...


@dataclass(frozen=True)
class InstanceSpec:
    instance_id: str
    base_url: str
    weight: int
    enabled: bool
    effective_free: int
    capacity: int
    status: str


@dataclass
class QueueTicket:
    ticket_id: str
    meta: dict = field(default_factory=dict)


class InMemoryAllocatorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # session_id -> (instance_id, 单调过期时刻)
        self._pending: dict[str, tuple[str, float]] = {}
        # dedupe_key -> 首次看到的单调时刻（spec §8.5：缺省 cookie+10s 时间桶）
        self._begun: dict[str, float] = {}
        self._grants: dict[str, dict] = {}
        self._queue: list[QueueTicket] = []
        self._counters: dict[str, int] = {}

    def list_instances(self) -> list[InstanceSpec]:
        out = []
        for state in instance_monitor.registry.snapshot().values():
            capacity = state.pool.size if state.pool else 0
            out.append(
                InstanceSpec(
                    instance_id=state.instance_id,
                    base_url=state.base_url,
                    weight=state.weight,
                    enabled=state.enabled,
                    effective_free=state.effective_free,
                    capacity=capacity,
                    status=state.status,
                )
            )
        return out

    def snapshot_runtime(self) -> dict[str, RuntimeState]:
        return instance_monitor.registry.snapshot()

    def upsert_runtime(self, state: RuntimeState) -> None:
        instance_monitor.registry._states[state.instance_id] = state

    def pending_count(self, instance_id: str) -> int:
        with self._lock:
            return sum(1 for iid, _ in self._pending.values() if iid == instance_id)

    def reserve(self, instance_id: str, session_id: str, ttl_s: int) -> bool:
        state = instance_monitor.registry.get(instance_id)
        if state is None:
            return False
        with self._lock:
            pending = sum(1 for iid, _ in self._pending.values() if iid == instance_id)
            # 占用 = 实例报的 in_use + 本机未反映的 pending；effective_free 已扣
            # stuck，这里只剩 pending 需要再扣（spec §6.2）。
            if state.pool is None or pending >= max(0, state.pool.size - state.pool.in_use - state.pool.stuck):
                return False
            self._pending[session_id] = (instance_id, time.monotonic() + ttl_s)
            return True

    def release(self, session_id: str) -> None:
        with self._lock:
            self._pending.pop(session_id, None)

    def expire_pending(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            gone = [sid for sid, (_, deadline) in self._pending.items() if now >= deadline]
            for sid in gone:
                del self._pending[sid]
            return gone

    def begin_once(self, dedupe_key: str, window_s: int) -> str | None:
        now = time.monotonic()
        with self._lock:
            first = self._begun.get(dedupe_key)
            if first is None:
                self._begun[dedupe_key] = now
                return None
            if now - first <= window_s:
                return "deduped"
            self._begun[dedupe_key] = now
            return None

    def remember_grant(self, dedupe_key: str, grant: dict) -> None:
        with self._lock:
            self._grants[dedupe_key] = dict(grant)

    def grant_for(self, dedupe_key: str) -> dict | None:
        with self._lock:
            grant = self._grants.get(dedupe_key)
            return dict(grant) if grant else None

    def enqueue(self, ticket_id: str, meta: dict) -> int:
        with self._lock:
            self._queue.append(QueueTicket(ticket_id=ticket_id, meta=dict(meta)))
            return len(self._queue)

    def peek_queue(self) -> list[QueueTicket]:
        with self._lock:
            return list(self._queue)

    def pop_queue(self) -> QueueTicket | None:
        with self._lock:
            return self._queue.pop(0) if self._queue else None

    def bump(self, counter: str, delta: int = 1) -> int:
        with self._lock:
            self._counters[counter] = self._counters.get(counter, 0) + delta
            return self._counters[counter]

    def drain_counters(self) -> dict[str, int]:
        with self._lock:
            out = dict(self._counters)
            self._counters.clear()
            return out
