"""重载执行器：维护态 → 排空 → 逐模块重建 → 就绪检查。

由 ModelReloadCoordinator 的工作线程调用；所有阶段通过 on_progress 上报，
失败时 fail-closed（目标实例保持维护态），不杀会话。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from loguru import logger


class ReloadExecutor:
    """执行一次 model_reload 请求；返回终态 dict。"""

    def __init__(
        self,
        pool: list[Any],
        *,
        rebuild: Callable[[Any, str], dict],
        on_progress: Callable[[dict], None] | None = None,
        drain_timeout_s: float = 5.0,
    ) -> None:
        self.pool = pool
        self.rebuild = rebuild
        self.on_progress = on_progress or (lambda event: None)
        self.drain_timeout_s = drain_timeout_s

    def __call__(self, request: dict, progress: Callable[[dict], None]) -> dict:
        started = time.monotonic()
        modules = request.get("modules") or []
        scope = request.get("scope", "all")
        unit_index = request.get("unit_index")
        drain = bool(request.get("drain", True))

        def emit(stage: str, **extra: Any) -> None:
            event = {
                "stage": stage,
                "elapsedMs": round((time.monotonic() - started) * 1000, 1),
                **extra,
            }
            try:
                progress(event)
                self.on_progress(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("model reload progress failed: {}", exc)

        units = self._targets(scope, unit_index)
        if not units:
            return {"status": "failed", "failedStage": "target", "error": "no target unit"}

        current_stage = "maintenance_set"
        current_module = ""
        try:
            emit(current_stage, units=[u.index for u in units])
            for unit in units:
                unit.maintenance = True
                if not drain and unit.session is not None:
                    current_stage = "drain"
                    raise RuntimeError(f"unit {unit.index} has an active session")
                if drain and unit.session is not None:
                    current_stage = "drain"
                    self._wait_drain(unit, request)

            for module in modules:
                emit(f"cleanup_{module}", module=module)
            for module in modules:
                current_module = module
                current_stage = f"rebuild_{module}"
                emit(current_stage, module=module)
                for unit in units:
                    self.rebuild(unit, module)

            current_stage = "ready"
            emit(current_stage, units=[u.index for u in units])
            for unit in units:
                unit.maintenance = False
            return {
                "status": "succeeded",
                "reloadedModules": list(modules),
                "targetUnits": [u.index for u in units],
                "ready": True,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("model reload failed at {}: {}", current_stage, exc)
            # drain 阶段失败（未动 handler）解除维护态恢复可用；
            # rebuild 阶段失败 fail-closed 保持维护态，不允许半重建实例接会话。
            if current_stage == "drain":
                for unit in units:
                    unit.maintenance = False
            emit("failed", failed_stage=current_stage, error=str(exc))
            return {
                "status": "failed",
                "failedStage": current_stage,
                "failedModule": current_module,
                "error": str(exc),
                "ready": False,
            }

    def _targets(self, scope: str, unit_index: int | None) -> list[Any]:
        if scope == "unit":
            return [u for u in self.pool if getattr(u, "index", None) == unit_index]
        return list(self.pool)

    def _wait_drain(self, unit: Any, request: dict) -> None:
        timeout = float(request.get("drain_timeout_ms", self.drain_timeout_s * 1000)) / 1000
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and unit.session is not None:
            time.sleep(0.05)
        if unit.session is not None:
            raise RuntimeError(f"unit {unit.index} drain timeout")
