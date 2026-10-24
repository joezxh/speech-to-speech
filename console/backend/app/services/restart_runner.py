"""链路 A 的步骤 7：先把 pipeline 停干净，再起来，再等回 RUNNING。

与旧实现（`compose_runner.recreate()` → `docker compose up --force-recreate`）
的区别只有一个：不再重建容器，只重启容器内的子进程。因此 `.env` 类字段无法
生效（→ `409 env_requires_recreate`，Task 15）。
"""

from __future__ import annotations

import time

from app.config import console
from app.core.errors import ApiError
from app.services import process_probe, supervisor_client


def restart() -> float:
    """重启 pipeline 并等它回到 RUNNING；返回耗时秒。"""
    started = time.monotonic()

    if console.restart_mode != "noop":
        usable, detail = supervisor_client.available()
        if not usable:
            raise ApiError(
                code="restart_unavailable",
                message="the supervisor socket is not reachable",
                status=502,
                detail=[{"reason": detail}],
            )
        try:
            supervisor_client.restart(supervisor_client.program())
        except supervisor_client.SupervisorError as exc:
            raise ApiError(
                code="restart_unavailable",
                message=str(exc),
                status=502,
            ) from exc

    wait_running()
    return round(time.monotonic() - started, 1)


def wait_running(timeout: float = 60.0, interval: float = 1.0) -> process_probe.ProcessInfo:
    """等回 RUNNING。超时仍不是 RUNNING 就是重启失败，没有「先当它成功了」。"""
    deadline = time.monotonic() + timeout
    info = process_probe.get_probe().state(supervisor_client.program())
    while not info.running:
        if time.monotonic() + interval > deadline:
            raise ApiError(
                code="restart_unavailable",
                message=f"pipeline did not reach RUNNING within {timeout:.0f}s",
                status=502,
                detail=[{"state": info.state, "detail": info.detail}],
            )
        time.sleep(interval)
        info = process_probe.get_probe().state(supervisor_client.program())
    return info
