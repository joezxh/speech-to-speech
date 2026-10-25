"""对**指定**实例地址读 pool/usage 并归一化（spec §4 表）。

替换点在 `pool.read_pool/read_usage` 这一层：与 `lb_service._http` 的
"单独一层测试替换点" 惯例一致（spec §17）。探测不新增实例侧端点。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.services import pool


@dataclass(frozen=True)
class PoolProbe:
    ok: bool
    state: pool.PoolState | None
    probe_ms: int
    error: str = ""


def probe_pool(base_url: str, timeout: float = 2.0) -> PoolProbe:
    started = time.monotonic()
    state = pool.read_pool(timeout=timeout, base_url=base_url)
    elapsed = int((time.monotonic() - started) * 1000)
    if not state.reachable:
        return PoolProbe(ok=False, state=None, probe_ms=elapsed, error=state.error)
    return PoolProbe(ok=True, state=state, probe_ms=elapsed)


def probe_usage(base_url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    # usage 失败不参与健康判定，只产生 usage_unavailable 告警（spec §9）。
    return pool.read_usage(timeout=timeout, base_url=base_url)
