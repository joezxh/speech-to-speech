"""数据面代理的窗口计数器（纯内存，无 app 依赖）。

代理每来一个请求就 bump 一次，真正落库由巡检的采样 tick 统一做：每请求写一次
DB 太重，而 30s 窗口增量正好和 `param_proxy_metric` 的语义一致（同
`param_instance_metric` 的 alloc 计数器）。

**刻意不 import 任何 app 模块**：本模块同时被 `audio_proxy_service`（请求侧）
和 `instance_monitor`（落库侧）引用，而后者与前者之间已经有 import 环的雷
（instance_monitor → allocator → allocator_store → instance_monitor）。
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_counters: dict[tuple[str, str], dict] = {}


def bump(
    instance_id: str,
    service: str,
    *,
    ok: bool,
    fail_reason: str = "",
    duration_ms: int = 0,
) -> None:
    with _lock:
        entry = _counters.setdefault(
            (instance_id, service),
            {"ok": 0, "fail": 0, "fail_reason": "", "duration_ms": 0, "count": 0},
        )
        entry["count"] += 1
        entry["duration_ms"] += duration_ms
        if ok:
            entry["ok"] += 1
        else:
            entry["fail"] += 1
            if fail_reason:
                entry["fail_reason"] = fail_reason


def drain() -> list[dict]:
    """取走并清空当前窗口的计数。落库侧调用。"""
    with _lock:
        rows = []
        for (instance_id, service), entry in _counters.items():
            rows.append(
                {
                    "instance_id": instance_id,
                    "service": service,
                    "ok": entry["ok"],
                    "fail_count": entry["fail"],
                    "fail_reason": entry["fail_reason"],
                    "duration_ms": entry["duration_ms"] // max(1, entry["count"]),
                }
            )
        _counters.clear()
        return rows


def reset() -> None:
    with _lock:
        _counters.clear()
