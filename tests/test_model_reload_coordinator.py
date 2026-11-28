"""模型重载协调器：工作线程、单飞锁与进度回执（TDD RED → GREEN）。"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from speech_to_speech.api.openai_realtime.model_reload import (
    ModelReloadCoordinator,
    ReloadBusyError,
)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.lock = threading.Lock()

    def callback(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)


def _coordinator(executor, **kwargs):
    return ModelReloadCoordinator(executor=executor, **kwargs)


def test_submit_returns_immediately_and_executes_work_off_thread():
    started = threading.Event()
    release = threading.Event()
    recorder = _Recorder()

    def executor(request, on_progress):
        started.set()
        release.wait(2)
        on_progress({"stage": "rebuild_asr", "module": "asr"})
        return {"ready": True}

    coordinator = _coordinator(executor)
    task_id = coordinator.submit(
        {"modules": ["asr"], "scope": "all"}, recorder.callback
    )

    assert started.wait(1), "executor must run on the worker thread"
    assert task_id
    # 主线程未被 executor 阻塞；此时工作线程仍在等待 release。
    assert recorder.events == []

    release.set()
    coordinator.wait_for(task_id, timeout=2)
    assert recorder.events[-1]["stage"] == "rebuild_asr"
    coordinator.close()


def test_second_submit_is_rejected_while_first_is_running():
    release = threading.Event()
    started = threading.Event()

    def executor(request, on_progress):
        started.set()
        release.wait(2)
        return {"ready": True}

    coordinator = _coordinator(executor)
    first = coordinator.submit({"modules": ["tts"], "scope": "all"}, lambda _: None)
    assert started.wait(1)
    with pytest.raises(ReloadBusyError):
        coordinator.submit({"modules": ["asr"], "scope": "all"}, lambda _: None)

    release.set()
    coordinator.wait_for(first, timeout=2)
    coordinator.close()


def test_progress_errors_do_not_fail_the_reload():
    def executor(request, on_progress):
        on_progress({"stage": "cleanup"})
        return {"ready": True}

    def broken_progress(_event):
        raise RuntimeError("console unreachable")

    coordinator = _coordinator(executor)
    task_id = coordinator.submit({"modules": ["asr"], "scope": "all"}, broken_progress)
    outcome = coordinator.wait_for(task_id, timeout=2)

    assert outcome["status"] == "succeeded"
    coordinator.close()


def test_executor_failure_is_reported_without_crashing_worker():
    def executor(request, on_progress):
        raise RuntimeError("model load failed")

    coordinator = _coordinator(executor)
    task_id = coordinator.submit({"modules": ["tts"], "scope": "all"}, lambda _: None)
    outcome = coordinator.wait_for(task_id, timeout=2)

    assert outcome["status"] == "failed"
    assert "model load failed" in outcome["error"]
    # 工作线程仍可用：下一次提交应被接受。
    coordinator.executor = lambda request, on_progress: {"ready": True}
    next_id = coordinator.submit({"modules": ["asr"], "scope": "all"}, lambda _: None)
    assert coordinator.wait_for(next_id, timeout=2)["status"] == "succeeded"
    coordinator.close()
