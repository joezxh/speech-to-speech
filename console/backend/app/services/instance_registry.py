"""实例级状态机（spec §6.2）：console 巡检推导，驻留内存。

两层状态绝不混用：unit 级（idle/active/draining/stuck）原样来自 /v1/pool；
这里只管机器级 unknown/online/degraded/offline/draining。摘除只停新分配，
本模块不触碰任何活跃会话（spec §9）。draining 是期望态：drain 优先于一切
探测结果，undrain 后按"是否已有一次成功探测"决定回 online 还是 unknown。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.pool import PoolState

UNKNOWN, ONLINE, DEGRADED, OFFLINE, DRAINING = "unknown", "online", "degraded", "offline", "draining"
PROBE_HISTORY = 20
# 巡检据此记 evict_count / recover_count（spec §10）
EVICTED, RECOVERED = "evicted", "recovered"


@dataclass
class RuntimeState:
    instance_id: str
    base_url: str
    weight: int = 1
    enabled: bool = True
    status: str = UNKNOWN
    pool: PoolState | None = None
    probe_ms: int | None = None
    usage: dict | None = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_error: str = ""
    probe_history: list[int] = field(default_factory=list)
    # 能力指纹（spec §5.1）：派生状态，不进 seed、不混进指标表。
    # 探测要花一次 HTTP 往返，且各实例的端点集合可能不同（声纹/情感是条件注册的），
    # 所以选台时要按能力过滤，否则会把请求发给没有该路由的机器。
    # 2026-11-17 起落 `param_instance_runtime`：多副本共享 + 控制台重启不丢状态。
    capabilities: frozenset[str] = frozenset()
    capability_issues: dict[str, str] = field(default_factory=dict)

    @property
    def effective_free(self) -> int:
        # pending_local 由 allocator 在选台时再扣（spec §6.2 容量建模）。
        if self.pool is None or self.status not in (ONLINE, DEGRADED):
            return 0
        return max(0, self.pool.size - self.pool.in_use - self.pool.stuck)

    @property
    def p95_probe_ms(self) -> int | None:
        return self._percentile(0.95)

    @property
    def p50_probe_ms(self) -> int | None:
        return self._percentile(0.5)

    def _percentile(self, q: float) -> int | None:
        if not self.probe_history:
            return None
        ordered = sorted(self.probe_history)
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


class InstanceRegistry:
    def __init__(self, fail_threshold: int = 3, recover_threshold: int = 2) -> None:
        self._fail_threshold = max(1, fail_threshold)
        self._recover_threshold = max(1, recover_threshold)
        self._states: dict[str, RuntimeState] = {}

    def sync(
        self,
        specs: list[tuple[str, str, int, bool, bool]],
        runtime: dict[str, dict] | None = None,
    ) -> None:
        """与注册表对齐：新增补 unknown，删除消失的，enabled/weight/drain 同步。
        specs = [(instance_id, base_url, weight, enabled, drain_requested)]。

        runtime 是从 `param_instance_runtime` 读回来的运行时状态（按 instance_id），
        用来在控制台重启后直接恢复到上次的健康状态与能力指纹，而不必等首轮探测
        （spec 2026-11-17 §2.1）。读不到就当没有——退化成"从 unknown 开始"。"""
        seen = set()
        for instance_id, base_url, weight, enabled, drain in specs:
            seen.add(instance_id)
            state = self._states.get(instance_id)
            if state is None:
                state = RuntimeState(instance_id=instance_id, base_url=base_url)
                self._states[instance_id] = state
            state.base_url, state.weight, state.enabled = base_url, weight, enabled
            payload = (runtime or {}).get(instance_id)
            if payload:
                self._restore_runtime(state, payload)
            if not enabled:
                state.status = OFFLINE if state.pool is None else state.status
            if drain and state.status != OFFLINE:
                state.status = DRAINING
            elif not drain and state.status == DRAINING:
                state.status = ONLINE if state.pool is not None else UNKNOWN
        for gone in [k for k in self._states if k not in seen]:
            del self._states[gone]

    @staticmethod
    def _restore_runtime(state: RuntimeState, payload: dict) -> None:
        """把库里的运行时状态灌回内存态。

        库里只有聚合值（size/in_use/stuck），没有 unit 明细，所以恢复出来的
        PoolState 不带 units；stuck 用库里记的个数（pool.PoolState.stuck_count）。
        """
        status = payload.get("status")
        if status:
            state.status = status
        size = payload.get("pool_size")
        if size is None:
            state.pool = None
        else:
            state.pool = PoolState(
                reachable=True,
                size=int(size),
                in_use=int(payload.get("in_use") or 0),
                units=(),
                stuck_count=int(payload.get("stuck") or 0),
            )
        if payload.get("probe_ms") is not None:
            state.probe_ms = int(payload["probe_ms"])
        state.capabilities = frozenset(payload.get("capabilities") or ())
        state.capability_issues = dict(payload.get("capability_issues") or {})
        state.consecutive_failures = int(payload.get("consecutive_failures") or 0)
        state.consecutive_successes = int(payload.get("consecutive_successes") or 0)
        state.last_error = str(payload.get("last_error") or "")
        state.probe_history = list(payload.get("probe_history") or ())

    def get(self, instance_id: str) -> RuntimeState | None:
        return self._states.get(instance_id)

    def snapshot(self) -> dict[str, RuntimeState]:
        return dict(self._states)

    def allocatable(self) -> list[RuntimeState]:
        # spec §8.2 过滤条件：enabled、weight>0、online/degraded、有余量。
        return [
            s
            for s in self._states.values()
            if s.enabled and s.weight > 0 and s.status in (ONLINE, DEGRADED) and s.effective_free > 0
        ]

    def observe_success(self, instance_id: str, pool_state: PoolState, probe_ms: int) -> RuntimeState:
        state = self._states[instance_id]
        state.pool, state.probe_ms, state.last_error = pool_state, probe_ms, ""
        state.probe_history = (state.probe_history + [probe_ms])[-PROBE_HISTORY:]
        state.consecutive_failures, state.consecutive_successes = 0, state.consecutive_successes + 1
        if state.status == DRAINING:  # 期望态压过探测
            return state
        if state.status == OFFLINE:
            if state.consecutive_successes >= self._recover_threshold:
                state.status = ONLINE
            return state
        state.status = DEGRADED if pool_state.stuck else ONLINE
        return state

    def observe_failure(self, instance_id: str, error: str) -> RuntimeState:
        state = self._states[instance_id]
        state.last_error, state.pool, state.usage = error, None, None
        state.consecutive_successes, state.consecutive_failures = 0, state.consecutive_failures + 1
        if state.status == DRAINING:
            return state
        if state.consecutive_failures >= self._fail_threshold:
            # offline 期间保持摘除，直到恢复阈值（抖动抑制，spec §9）。
            state.status = OFFLINE
        return state

    def set_drain(self, instance_id: str, drain: bool) -> RuntimeState:
        state = self._states[instance_id]
        if drain:
            state.status = DRAINING
        else:
            state.status = ONLINE if state.pool is not None else UNKNOWN
        return state
