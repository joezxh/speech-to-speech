"""模型重载协调器：在独立工作线程执行重建，进度经回调上报。

设计纪律（D6）：
- `submit()` 只投递任务并立即返回，不阻塞 agent 心跳线程；
- 全局单飞锁 + per-unit 锁避免并发重载与会话串音；
- 进度回调失败只记日志，不影响任务本身；
- 执行器异常转 failed 结果，工作线程继续可用。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

ProgressCallback = Callable[[dict], None]
ReloadExecutor = Callable[[dict, ProgressCallback], Any]


class ReloadBusyError(RuntimeError):
    """另一个重载任务正在执行；调用方应稍后重试。"""


@dataclass
class _Task:
    task_id: str
    request: dict
    on_progress: ProgressCallback
    done: threading.Event = field(default_factory=threading.Event)
    outcome: dict = field(default_factory=dict)


class ModelReloadCoordinator:
    """把重载任务投递到单个工作线程，并报告进度与终态。"""

    def __init__(
        self,
        executor: ReloadExecutor,
        *,
        on_terminal: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.executor = executor
        self.on_terminal = on_terminal
        self._queue: list[_Task] = []
        self._condition = threading.Condition()
        self._flight = threading.Lock()
        self._unit_locks: dict[int, threading.Lock] = {}
        self._tasks: dict[str, _Task] = {}
        self._closed = False
        self._worker = threading.Thread(
            target=self._run, name="model-reload-worker", daemon=True
        )
        self._worker.start()

    def submit(self, request: dict, on_progress: ProgressCallback) -> str:
        """投递一个重载任务；同一时刻只允许一个任务在跑。"""
        if not self._flight.acquire(blocking=False):
            raise ReloadBusyError("another model reload is in progress")
        task = _Task(
            task_id=uuid.uuid4().hex,
            request=dict(request),
            on_progress=on_progress,
        )
        with self._condition:
            if self._closed:
                self._flight.release()
                raise RuntimeError("model reload coordinator is closed")
            self._tasks[task.task_id] = task
            self._queue.append(task)
            self._condition.notify()
        # 单飞锁在任务终态（_execute finally）释放：执行中拒绝后续提交。
        return task.task_id

    def wait_for(self, task_id: str, *, timeout: float | None = None) -> dict:
        """等待任务终态；超时返回 status=running。"""
        with self._condition:
            task = self._tasks.get(task_id)
        if task is None:
            return {"status": "unknown", "taskId": task_id}
        task.done.wait(timeout)
        return dict(task.outcome) if task.outcome else {"status": "running", "taskId": task_id}

    def close(self) -> None:
        """停止工作线程；不等待在途任务完成（进程退出路径）。"""
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait(0.5)
                if self._closed and not self._queue:
                    return
                task = self._queue.pop(0)
            self._execute(task)

    def _execute(self, task: _Task) -> None:
        started = time.monotonic()
        request = task.request
        unit_index = request.get("unit_index")
        unit_lock = None
        if unit_index is not None:
            with self._condition:
                unit_lock = self._unit_locks.setdefault(int(unit_index), threading.Lock())
            unit_lock.acquire()

        def progress(event: dict) -> None:
            payload = {**event, "taskId": task.task_id}
            try:
                task.on_progress(payload)
            except Exception as exc:  # noqa: BLE001 - 进度上报失败不影响重建
                logger.warning("model reload progress callback failed: {}", exc)

        try:
            result = self.executor(request, progress)
            outcome = {
                "status": "succeeded",
                "taskId": task.task_id,
                "result": result,
            }
        except Exception as exc:  # noqa: BLE001 - 执行失败转终态，不杀工作线程
            logger.warning("model reload task {} failed: {}", task.task_id, exc)
            outcome = {
                "status": "failed",
                "taskId": task.task_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            if unit_lock is not None:
                unit_lock.release()
            outcome["elapsedMs"] = round((time.monotonic() - started) * 1000, 1)
            task.outcome = outcome
            task.done.set()
            self._flight.release()
            if self.on_terminal is not None:
                try:
                    self.on_terminal(task.task_id, outcome)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("model reload terminal callback failed: {}", exc)
