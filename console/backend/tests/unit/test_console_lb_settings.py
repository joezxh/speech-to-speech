from __future__ import annotations

import pytest

from app.config import ConsoleSettings

_LB_ENV_VARS = (
    "CONSOLE_LB_MODE",
    "LB_MODE",
    "LB_FAILOVER_ATTEMPTS",
    "LB_UPSTREAM_READY_TIMEOUT_S",
    "LB_ASR_TIMEOUT_S",
    "LB_TTS_TIMEOUT_S",
    "LB_VOICEPRINT_TIMEOUT_S",
    "LB_EMOTION_TIMEOUT_S",
    "LB_AUDIO_MAX_BYTES",
    "LB_CAPABILITY_INTERVAL_S",
    "LB_CAPABILITY_PROBE_TIMEOUT_S",
    "LB_STATELESS_MAX_INFLIGHT",
)


@pytest.fixture(autouse=True)
def _clean_lb_env(monkeypatch):
    """宿主机上可能已经导出了这些变量，测试不能被环境污染。"""
    for name in _LB_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_keep_the_lb_off():
    s = ConsoleSettings(_env_file=None)
    assert s.lb_mode == "off"
    assert s.lb_failover_attempts == 2
    assert s.lb_upstream_ready_timeout_s == 5.0
    assert s.lb_asr_timeout_s == 120.0
    assert s.lb_tts_timeout_s == 120.0
    assert s.lb_voiceprint_timeout_s == 30.0
    assert s.lb_emotion_timeout_s == 30.0
    assert s.lb_audio_max_bytes == 11534336
    assert s.lb_capability_interval_s == 30
    assert s.lb_capability_probe_timeout_s == 6.0
    assert s.lb_stateless_max_inflight == 0


def test_the_mode_is_read_from_console_lb_mode_not_lb_mode(monkeypatch):
    # 字段名大写的默认规则只会给出 LB_MODE；env 名必须显式绑定。
    monkeypatch.setenv("CONSOLE_LB_MODE", "proxy")
    monkeypatch.setenv("LB_MODE", "off")  # 干扰项：不该被读到
    s = ConsoleSettings(_env_file=None)
    assert s.lb_mode == "proxy"


def test_the_other_switches_read_from_their_own_env_names(monkeypatch):
    monkeypatch.setenv("LB_FAILOVER_ATTEMPTS", "4")
    monkeypatch.setenv("LB_AUDIO_MAX_BYTES", "1024")
    monkeypatch.setenv("LB_CAPABILITY_PROBE_TIMEOUT_S", "7.5")
    s = ConsoleSettings(_env_file=None)
    assert s.lb_failover_attempts == 4
    assert s.lb_audio_max_bytes == 1024
    assert s.lb_capability_probe_timeout_s == 7.5


def test_an_unknown_mode_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ConsoleSettings(_env_file=None, lb_mode="nonsense")
