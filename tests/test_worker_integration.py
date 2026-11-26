"""--with-diarization / --with-livekitworker 开关解析测试（mirror agent_integration）。"""
from __future__ import annotations

import sys

import pytest

from speech_to_speech.worker_integration import (
    DIARIZATION_AUTOSTART_ENV,
    DIARIZATION_WITH_FLAG,
    LIVEKIT_WITH_FLAG,
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


@pytest.mark.parametrize("flag", [DIARIZATION_WITH_FLAG, LIVEKIT_WITH_FLAG])
def test_talk_rejects_explicit_switches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    """真实触发 cli.main() 的 talk 分支：显式 worker 开关必须以 exit 2 拒绝。"""
    from speech_to_speech import cli

    # talk 分支先检查 console/agent 开关，这里清掉相关 env 确保到达 worker 检查。
    monkeypatch.delenv("CONSOLE_AUTOSTART", raising=False)
    monkeypatch.delenv("S2S_AGENT_AUTOSTART", raising=False)
    monkeypatch.delenv(DIARIZATION_AUTOSTART_ENV, raising=False)
    monkeypatch.delenv(LIVEKIT_WORKER_AUTOSTART_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "talk", flag])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2
    # 错误消息必须来自 worker 开关拒绝路径，而非 console/agent 的同类拒绝。
    assert f"talk does not accept {flag}" in capsys.readouterr().err


def test_validate_worker_options_requires_livekit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.worker_integration import SwitchOptions, validate_worker_options

    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    with pytest.raises(WorkerIntegrationError) as exc_info:
        validate_worker_options(SwitchOptions(autostart=True))
    message = str(exc_info.value)
    assert "LIVEKIT_URL" in message and "LIVEKIT_API_KEY" in message and "LIVEKIT_API_SECRET" in message


def test_validate_worker_options_asr_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.worker_integration import SwitchOptions, validate_worker_options

    # 先满足凭证要求，确保断言落在 ASR 模式校验上，不随宿主环境波动。
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret")

    monkeypatch.delenv("LIVEKIT_WORKER_ASR_MODE", raising=False)
    monkeypatch.setenv("LIVEKIT_WORKER_ASR_MODE", "bogus")
    with pytest.raises(WorkerIntegrationError, match="LIVEKIT_WORKER_ASR_MODE"):
        validate_worker_options(SwitchOptions(autostart=True))

    monkeypatch.setenv("LIVEKIT_WORKER_ASR_MODE", "gateway")
    monkeypatch.delenv("VOICE_GATEWAY_BASE_URL", raising=False)
    with pytest.raises(WorkerIntegrationError, match="VOICE_GATEWAY_BASE_URL"):
        validate_worker_options(SwitchOptions(autostart=True))

    # local 模式下 STT 定义在 pipeline 解析后校验；validate 只查非法模式与 gateway 依赖。
    monkeypatch.setenv("LIVEKIT_WORKER_ASR_MODE", "local")
    validate_worker_options(SwitchOptions(autostart=True))  # 不抛


def test_validate_worker_options_off_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.worker_integration import SwitchOptions, validate_worker_options

    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    validate_worker_options(SwitchOptions(autostart=False))  # 不抛


def test_no_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LIVEKIT_WORKER_AUTOSTART_ENV, "true")
    diar, worker, rest = parse_worker_arguments(["--no-with-livekitworker", "serve"])
    assert worker.autostart is False
    assert worker.explicit is True
    assert worker.explicit_flag == "--no-with-livekitworker"
    assert diar.autostart is False
    assert rest == ["serve"]


def test_file_mode_switches_stripped_before_f() -> None:
    """-f 文件模式：worker 开关在 parse_command 之前剥离，剩余 argv 顺序保持不变。"""
    diar, worker, rest = parse_worker_arguments(["-f", "run.yaml", "--with-livekitworker"])
    assert rest == ["-f", "run.yaml"]
    assert worker.autostart is True
    assert worker.explicit is True
    assert worker.explicit_flag == "--with-livekitworker"
    assert diar.autostart is False
    assert diar.explicit is False


# ---------------------------------------------------------------------------
# s2s_pipeline 接线：开关真正生效（Task 10）
# ---------------------------------------------------------------------------


def test_diarization_switch_maps_to_module_kwargs() -> None:
    from types import SimpleNamespace

    from speech_to_speech.s2s_pipeline import apply_diarization_switch

    kwargs = SimpleNamespace(diarization=False)
    apply_diarization_switch(kwargs, True)
    assert kwargs.diarization is True
    apply_diarization_switch(kwargs, False)
    assert kwargs.diarization is False


def test_local_asr_mode_requires_stt_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.s2s_pipeline import validate_local_asr_mode
    from speech_to_speech.worker_integration import WorkerIntegrationError

    monkeypatch.setenv("LIVEKIT_WORKER_ASR_MODE", "local")
    with pytest.raises(WorkerIntegrationError, match="local"):
        validate_local_asr_mode(stt_backend_name=None)
    validate_local_asr_mode(stt_backend_name="parakeet-tdt")
    monkeypatch.setenv("LIVEKIT_WORKER_ASR_MODE", "gateway")
    validate_local_asr_mode(stt_backend_name=None)  # gateway 无 STT 也可
