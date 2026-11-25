"""--with-diarization / --with-livekitworker 开关解析测试（mirror agent_integration）。"""
from __future__ import annotations

import pytest

from speech_to_speech.worker_integration import (
    DIARIZATION_AUTOSTART_ENV,
    LIVEKIT_WORKER_AUTOSTART_ENV,
    WorkerIntegrationError,
    parse_worker_arguments,
)


def test_defaults_off() -> None:
    diar, worker, rest = parse_worker_arguments(["serve", "--port", "9000"])
    assert diar.autostart is False
    assert diar.explicit is False
    assert worker.autostart is False
    assert worker.explicit is False
    assert rest == ["serve", "--port", "9000"]


def test_explicit_flags_stripped() -> None:
    diar, worker, rest = parse_worker_arguments(["--with-diarization", "--with-livekitworker", "serve"])
    assert diar.autostart and diar.explicit
    assert worker.autostart and worker.explicit
    assert rest == ["serve"]


def test_no_flags_conflict() -> None:
    with pytest.raises(WorkerIntegrationError, match="conflicts"):
        parse_worker_arguments(["--with-diarization", "--no-with-diarization", "serve"])
    with pytest.raises(WorkerIntegrationError, match="conflicts"):
        parse_worker_arguments(["--with-livekitworker", "--no-with-livekitworker", "serve"])


def test_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DIARIZATION_AUTOSTART_ENV, "true")
    monkeypatch.setenv(LIVEKIT_WORKER_AUTOSTART_ENV, "1")
    diar, worker, _ = parse_worker_arguments(["serve"])
    assert diar.autostart is True
    assert worker.autostart is True


def test_env_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LIVEKIT_WORKER_AUTOSTART_ENV, "maybe")
    with pytest.raises(WorkerIntegrationError, match="must be a boolean"):
        parse_worker_arguments(["serve"])


def test_explicit_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DIARIZATION_AUTOSTART_ENV, "true")
    diar, _, _ = parse_worker_arguments(["--no-with-diarization", "serve"])
    assert diar.autostart is False
    assert diar.explicit is True
