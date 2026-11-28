"""统一 handler 生命周期端口：flag 模式与 file 模式共用同一接口。

协调器只依赖 :class:`HandlerLifecycle`，不直接操作 ThreadManager 或
ConfiguredRuntime 内部；每个 handler 有独立线程记录，退役单个 handler
不会 stop 其他 handler 的共享 stop_event。
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from speech_to_speech.utils.thread_manager import ThreadManager


class HandlerLifecycle(Protocol):
    def register(self, handler: Any) -> None: ...

    def start_all(self) -> None: ...

    def start(self, handler: Any) -> None: ...

    def retire(self, handler: Any) -> None: ...

    def join(self, handler: Any, timeout: float | None = None) -> None: ...

    def alive(self, handler: Any) -> bool: ...

    def stop_all(self) -> None: ...


class ThreadManagerLifecycle:
    """基于 ThreadManager 的实现；按 handler 记录线程，支持单点替换。"""

    def __init__(self, manager: ThreadManager) -> None:
        self.manager = manager
        self._threads: dict[int, threading.Thread] = {}
        self._stopped: set[int] = set()

    def register(self, handler: Any) -> None:
        if handler not in self.manager.handlers:
            self.manager.handlers.append(handler)

    def start_all(self) -> None:
        for handler in list(self.manager.handlers):
            self.start(handler)

    def start(self, handler: Any) -> None:
        key = id(handler)
        thread = threading.Thread(target=handler.run, daemon=False)
        self._threads[key] = thread
        self._stopped.discard(key)
        thread.start()

    def retire(self, handler: Any) -> None:
        key = id(handler)
        self._stopped.add(key)
        retire = getattr(handler, "retire", None)
        if retire is not None:
            retire()
        else:
            handler.stop_event.set()

    def join(self, handler: Any, timeout: float | None = None) -> None:
        thread = self._threads.get(id(handler))
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def alive(self, handler: Any) -> bool:
        thread = self._threads.get(id(handler))
        return bool(thread is not None and thread.is_alive())

    def stop_all(self) -> None:
        for handler in list(self.manager.handlers):
            if id(handler) not in self._stopped:
                handler.stop_event.set()
        for thread in list(self._threads.values()):
            if thread.is_alive():
                thread.join(timeout=5.0)


__all__ = ["HandlerLifecycle", "ThreadManagerLifecycle"]
