"""Embedded SenseVoiceSmall SER runtime（内嵌情感服务）.

内置情感端点（``api/openai_realtime/emotion_local_service.py``）从 pipeline 池里
找一个 ``SenseVoiceSTTHandler`` 来出情感标签。只有 STT backend 是 ``sense-voice``
时池里才会有这个 handler；换成任何别的 STT（qwen3-asr / whisper / …）池里就没有
情感来源，端点只能回 503 "SER handler unavailable"。

本模块补上这个缺口：当**内置情感服务被要求**（``SER_PROVIDER=local``）但池里没有
SenseVoice handler 时，用独立线程加载 SenseVoiceSmall，把 handler 交给同一套路由，
于是 ``/v1/audio/emotion``、``/recognize``、``/v1/audio/emotion/health`` 在任何 STT
后端下都保持可用。

契约：
* 权重目录来自 ``S2S_SENSEVOICE_MODEL_DIR``（本地目录，**绝不下载**）；未设置则本模块
  保持关闭（不猜路径、不触网）。
* ``EMBEDDED_SER_AUTOSTART=false`` 显式关闭。
* ``EMBEDDED_SER_DEVICE``（默认 ``cuda``）、``EMBEDDED_SER_LANGUAGE``（默认 ``auto``）
  调整加载参数。
* 崩溃隔离：加载失败只记一条告警，``ready`` 保持 False，转写链路完全不受影响。
* 池里已有 SenseVoice handler 时本模块不启动（零额外模型、零额外显存）。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any, Iterable

logger = logging.getLogger(__name__)

SER_PROVIDER_ENV = "SER_PROVIDER"
EMBEDDED_SER_AUTOSTART_ENV = "EMBEDDED_SER_AUTOSTART"
EMBEDDED_SER_MODEL_DIR_ENV = "S2S_SENSEVOICE_MODEL_DIR"
EMBEDDED_SER_DEVICE_ENV = "EMBEDDED_SER_DEVICE"
EMBEDDED_SER_LANGUAGE_ENV = "EMBEDDED_SER_LANGUAGE"

DEFAULT_DEVICE = "cuda"
DEFAULT_LANGUAGE = "auto"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


class EmbeddedSerError(RuntimeError):
    """An embedded SER switch cannot be applied as requested."""


@dataclass(frozen=True)
class EmbeddedSerOptions:
    """Resolved switch state for the embedded SER runtime."""

    enabled: bool
    model_dir: str = ""
    device: str = DEFAULT_DEVICE
    language: str = DEFAULT_LANGUAGE
    reason: str = ""


def _read_bool(name: str, env: dict[str, str], default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise EmbeddedSerError(
        f"{name} must be a boolean (1/true/yes/on or 0/false/no/off); got {raw!r}."
    )


def resolve_embedded_ser_options(env: dict[str, str] | None = None) -> EmbeddedSerOptions:
    """Resolve the embedded SER switch from the environment (no side effects).

    关闭的三个原因（都记在 ``reason`` 里，便于日志排查）：
    * ``SER_PROVIDER`` 不是 ``local`` —— 内置情感端点压根没挂载；
    * ``EMBEDDED_SER_AUTOSTART=false`` —— 显式关闭；
    * ``S2S_SENSEVOICE_MODEL_DIR`` 未设置 —— 没有本地权重，绝不隐式下载。
    """
    environ = os.environ if env is None else env
    provider = environ.get(SER_PROVIDER_ENV, "proxy").strip().lower()
    if provider != "local":
        return EmbeddedSerOptions(enabled=False, reason=f"{SER_PROVIDER_ENV} is not local")
    if not _read_bool(EMBEDDED_SER_AUTOSTART_ENV, environ, True):
        return EmbeddedSerOptions(enabled=False, reason=f"{EMBEDDED_SER_AUTOSTART_ENV} is disabled")
    model_dir = environ.get(EMBEDDED_SER_MODEL_DIR_ENV, "").strip()
    if not model_dir:
        return EmbeddedSerOptions(
            enabled=False, reason=f"{EMBEDDED_SER_MODEL_DIR_ENV} is not set (no local weights)"
        )
    device = environ.get(EMBEDDED_SER_DEVICE_ENV, "").strip() or DEFAULT_DEVICE
    language = environ.get(EMBEDDED_SER_LANGUAGE_ENV, "").strip() or DEFAULT_LANGUAGE
    return EmbeddedSerOptions(enabled=True, model_dir=model_dir, device=device, language=language)


def build_sensevoice_handler(model_dir: str, device: str, language: str) -> Any:
    """Load a standalone SenseVoice handler (not part of the pipeline chain).

    独立于 pipeline 的 handler 链：它没有前驱/后继队列，只用 ``recognize()`` 做情感
    推理，因此不会参与转写，也不会打乱 handlers 链的索引。
    """
    from speech_to_speech.STT.sense_voice_handler import SenseVoiceSTTHandler

    return SenseVoiceSTTHandler(Event(), Queue(), Queue(), (model_dir, device, language))


class EmbeddedSerRuntime:
    """Loads SenseVoiceSmall on its own thread and exposes the handler."""

    def __init__(self, options: EmbeddedSerOptions) -> None:
        self._options = options
        self._handler: Any = None
        self._error: str | None = None
        self._stopped = False
        self._lock = Lock()
        self._thread: Thread | None = None

    @property
    def options(self) -> EmbeddedSerOptions:
        return self._options

    @property
    def ready(self) -> bool:
        return self._handler is not None

    @property
    def error(self) -> str | None:
        return self._error

    def handler(self) -> Any:
        return self._handler

    def start(self) -> None:
        """Kick off the loader thread (returns immediately; the model loads async)."""
        with self._lock:
            if self._thread is not None:
                return
            thread = Thread(target=self._load, name="embedded-ser", daemon=True)
            self._thread = thread
        thread.start()

    def _load(self) -> None:
        options = self._options
        try:
            handler = build_sensevoice_handler(options.model_dir, options.device, options.language)
        except BaseException as exc:  # noqa: BLE001 - crash isolation is the point
            self._error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Embedded SER model load failed (%s); emotion endpoints stay unavailable",
                self._error,
            )
            return
        with self._lock:
            if self._stopped:
                return
            self._handler = handler
        logger.info(
            "Embedded SER ready: SenseVoiceSmall from %s on %s",
            options.model_dir,
            options.device,
        )

    def stop(self) -> None:
        with self._lock:
            self._stopped = True


_runtime: EmbeddedSerRuntime | None = None
_runtime_lock = Lock()


def _pool_sensevoice_handler(pool: Iterable[Any] | None) -> Any:
    for unit in pool or []:
        for handler in getattr(unit, "handlers", None) or []:
            if type(handler).__name__ == "SenseVoiceSTTHandler":
                return handler
    return None


def get_embedded_ser_runtime() -> EmbeddedSerRuntime | None:
    """Return the process-wide runtime, if one was started."""
    return _runtime


def current_ser_handler() -> Any:
    """Return the embedded handler once it finished loading (None otherwise)."""
    runtime = _runtime
    return runtime.handler() if runtime is not None else None


def start_embedded_ser(pool: Iterable[Any] | None = None) -> EmbeddedSerRuntime | None:
    """Start the embedded runtime when the built-in SER needs it.

    Returns the runtime when one is (or already was) started, else None.  Safe to call
    from every entry point: the runtime is a process-wide singleton, so repeated calls
    never load the model twice.
    """
    options = resolve_embedded_ser_options()
    if not options.enabled:
        logger.info("Embedded SER not started: %s", options.reason)
        return None
    if _pool_sensevoice_handler(pool) is not None:
        logger.info("Embedded SER not started: the pipeline pool already serves SenseVoice")
        return None
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            return _runtime
        runtime = EmbeddedSerRuntime(options)
        _runtime = runtime
    runtime.start()
    return runtime


__all__ = [
    "DEFAULT_DEVICE",
    "DEFAULT_LANGUAGE",
    "EMBEDDED_SER_AUTOSTART_ENV",
    "EMBEDDED_SER_DEVICE_ENV",
    "EMBEDDED_SER_LANGUAGE_ENV",
    "EMBEDDED_SER_MODEL_DIR_ENV",
    "SER_PROVIDER_ENV",
    "EmbeddedSerError",
    "EmbeddedSerOptions",
    "EmbeddedSerRuntime",
    "build_sensevoice_handler",
    "current_ser_handler",
    "get_embedded_ser_runtime",
    "resolve_embedded_ser_options",
    "start_embedded_ser",
]
