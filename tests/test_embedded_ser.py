"""内嵌情感服务（embedded SER）离线契约测试。

不装 funasr：模型加载一律用替身，只验证开关解析、绑定判定、崩溃隔离与路由回落。
"""
from __future__ import annotations

import pytest

from speech_to_speech import embedded_ser
from speech_to_speech.embedded_ser import (
    EMBEDDED_SER_AUTOSTART_ENV,
    EMBEDDED_SER_DEVICE_ENV,
    EMBEDDED_SER_LANGUAGE_ENV,
    EMBEDDED_SER_MODEL_DIR_ENV,
    SER_PROVIDER_ENV,
    EmbeddedSerError,
    EmbeddedSerOptions,
    EmbeddedSerRuntime,
    resolve_embedded_ser_options,
    start_embedded_ser,
)


class _FakeHandler:
    """Mimics the SenseVoice handler surface the SER endpoint uses."""

    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, audio):  # pragma: no cover - not exercised here
        self.calls += 1
        return {"raw": "HAPPY", "laughter": False, "confidence": 0.9, "margin": 0.4}


class _Unit:
    def __init__(self, handlers) -> None:
        self.handlers = handlers


def _sensevoice_named_handler():
    """A handler whose class name matches the pool scan in find_ser_handler."""

    class SenseVoiceSTTHandler:  # noqa: N801 - the scan matches on this exact name
        pass

    return SenseVoiceSTTHandler()


@pytest.fixture(autouse=True)
def _reset_runtime():
    """每个用例都从“没有内嵌运行时”的干净状态开始。"""
    embedded_ser._runtime = None
    yield
    runtime = embedded_ser._runtime
    if runtime is not None:
        runtime.stop()
    embedded_ser._runtime = None


def _env(**overrides) -> dict[str, str]:
    base = {
        SER_PROVIDER_ENV: "local",
        EMBEDDED_SER_MODEL_DIR_ENV: "/models/sensevoice-small",
    }
    base.update(overrides)
    return base


def _wait_for_load(runtime: EmbeddedSerRuntime, timeout_s: float = 5.0) -> None:
    """Wait for the loader thread to finish (success or failure)."""
    thread = runtime._thread
    if thread is not None:
        thread.join(timeout_s)
        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# 开关解析
# ---------------------------------------------------------------------------


def test_disabled_when_provider_is_not_local() -> None:
    options = resolve_embedded_ser_options(_env(**{SER_PROVIDER_ENV: "proxy"}))
    assert options.enabled is False
    assert SER_PROVIDER_ENV in options.reason


def test_disabled_when_autostart_is_false() -> None:
    options = resolve_embedded_ser_options(_env(**{EMBEDDED_SER_AUTOSTART_ENV: "false"}))
    assert options.enabled is False
    assert EMBEDDED_SER_AUTOSTART_ENV in options.reason


def test_disabled_without_local_weights() -> None:
    """没有本地权重就保持关闭：绝不隐式下载。"""
    options = resolve_embedded_ser_options({SER_PROVIDER_ENV: "local"})
    assert options.enabled is False
    assert EMBEDDED_SER_MODEL_DIR_ENV in options.reason


def test_enabled_with_defaults() -> None:
    options = resolve_embedded_ser_options(_env())
    assert options.enabled is True
    assert options.model_dir == "/models/sensevoice-small"
    assert options.device == "cuda"
    assert options.language == "auto"


def test_device_and_language_overrides() -> None:
    options = resolve_embedded_ser_options(
        _env(**{EMBEDDED_SER_DEVICE_ENV: "cpu", EMBEDDED_SER_LANGUAGE_ENV: "zh"})
    )
    assert options.device == "cpu"
    assert options.language == "zh"


def test_invalid_autostart_value_raises() -> None:
    with pytest.raises(EmbeddedSerError, match="must be a boolean"):
        resolve_embedded_ser_options(_env(**{EMBEDDED_SER_AUTOSTART_ENV: "maybe"}))


# ---------------------------------------------------------------------------
# 绑定判定：池里已有 SenseVoice 就不启动内嵌运行时
# ---------------------------------------------------------------------------


def test_pool_sensevoice_handler_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SER_PROVIDER_ENV, "local")
    monkeypatch.setenv(EMBEDDED_SER_MODEL_DIR_ENV, "/models/sensevoice-small")
    started: list[tuple] = []
    monkeypatch.setattr(embedded_ser, "build_sensevoice_handler", lambda *a, **k: started.append(a))

    assert start_embedded_ser([_Unit([_sensevoice_named_handler()])]) is None
    assert embedded_ser.get_embedded_ser_runtime() is None
    assert started == []


def test_runtime_started_when_pool_has_no_sensevoice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SER_PROVIDER_ENV, "local")
    monkeypatch.setenv(EMBEDDED_SER_MODEL_DIR_ENV, "/models/sensevoice-small")
    monkeypatch.setattr(embedded_ser, "build_sensevoice_handler", lambda *a, **k: _FakeHandler())

    runtime = start_embedded_ser([_Unit([_FakeHandler()])])
    assert runtime is not None
    # 单例：重复调用不会重复加载模型。
    assert start_embedded_ser([]) is runtime
    _wait_for_load(runtime)
    assert runtime.ready is True
    assert runtime.handler() is not None


def test_not_started_when_provider_is_not_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SER_PROVIDER_ENV, "proxy")
    monkeypatch.setenv(EMBEDDED_SER_MODEL_DIR_ENV, "/models/sensevoice-small")
    assert start_embedded_ser([]) is None
    assert embedded_ser.get_embedded_ser_runtime() is None


# ---------------------------------------------------------------------------
# 运行时：加载成功 / 崩溃隔离
# ---------------------------------------------------------------------------


def test_runtime_load_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("no weights")

    monkeypatch.setattr(embedded_ser, "build_sensevoice_handler", _boom)
    runtime = EmbeddedSerRuntime(EmbeddedSerOptions(enabled=True, model_dir="/models/x"))
    runtime.start()
    _wait_for_load(runtime)
    assert runtime.ready is False
    assert "no weights" in (runtime.error or "")


def test_runtime_handler_available_after_load(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _FakeHandler()
    monkeypatch.setattr(embedded_ser, "build_sensevoice_handler", lambda *a, **k: handler)
    runtime = EmbeddedSerRuntime(EmbeddedSerOptions(enabled=True, model_dir="/models/x"))
    runtime.start()
    _wait_for_load(runtime)
    assert runtime.ready is True
    assert runtime.handler() is handler


def test_current_ser_handler_follows_the_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _FakeHandler()
    monkeypatch.setattr(embedded_ser, "build_sensevoice_handler", lambda *a, **k: handler)
    monkeypatch.setenv(SER_PROVIDER_ENV, "local")
    monkeypatch.setenv(EMBEDDED_SER_MODEL_DIR_ENV, "/models/sensevoice-small")
    runtime = start_embedded_ser([])
    assert runtime is not None
    _wait_for_load(runtime)
    assert embedded_ser.current_ser_handler() is handler


# ---------------------------------------------------------------------------
# 路由回落：池里没有 SenseVoice 时用内嵌 handler
# ---------------------------------------------------------------------------


def test_find_ser_handler_falls_back_to_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.api.openai_realtime import emotion_local_service

    handler = _FakeHandler()
    monkeypatch.setattr(embedded_ser, "current_ser_handler", lambda: handler)
    assert emotion_local_service.find_ser_handler([_Unit([_FakeHandler()])]) is handler


def test_find_ser_handler_prefers_pool_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.api.openai_realtime import emotion_local_service

    pooled = _sensevoice_named_handler()
    monkeypatch.setattr(embedded_ser, "current_ser_handler", lambda: _FakeHandler())
    assert emotion_local_service.find_ser_handler([_Unit([pooled])]) is pooled
