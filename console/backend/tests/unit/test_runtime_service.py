"""A.14's single invariant: a `null` / `false` field must say *why*.

The panel exists to separate "zero" from "unknown", so every hole carries a
reason code and every real value carries none. The four sources are patched one
at a time: a unit test that depended on the machine's `nvidia-smi`, its loopback
pool or its supervisor socket would pass on one box and fail on the next.
"""

from __future__ import annotations

import json
import time

import pytest

from app.services import pool, runtime_service

MARKER = "MODEL_CALL_METRICS"


def pkg_metrics_line(
    category: str,
    *,
    duration_s: float,
    first_byte_s: float | None = None,
    vram_mb: float | None = None,
    model_name: str | None = None,
) -> str:
    """One `MODEL_CALL_METRICS` line, stamped now so it lands inside the window."""
    record = {
        "category": category,
        "model_name": model_name or f"{category.lower()}-model",
        "start_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "duration_s": duration_s,
        "error": None,
        "input": {"backend": "torch"},
        "output": {} if first_byte_s is None else {"first_byte_s": first_byte_s},
        "resources": {"vram_used_mb_peak": vram_mb},
    }
    return json.dumps({MARKER: record})


@pytest.fixture(autouse=True)
def _clean_cache():
    # `collect()` caches for 3 s; without this a patched source would be
    # shadowed by the previous test's frame.
    runtime_service.invalidate()
    yield
    runtime_service.invalidate()


@pytest.fixture
def healthy(monkeypatch):
    """Every source that is not under test answers something usable."""
    monkeypatch.setattr(
        runtime_service,
        "_gpu",
        lambda: {"available": True, "name": "GPU", "totalMb": 8192, "usedMb": 1024, "percent": 12.5},
    )
    monkeypatch.setattr(runtime_service, "_pool", lambda: pool.PoolState(reachable=True, size=1, in_use=0))
    monkeypatch.setattr(runtime_service, "_pipeline_running", lambda: True)
    monkeypatch.setattr(runtime_service, "_metrics_tail", lambda **kw: [])


def test_null_vram_always_carries_a_reason(healthy, monkeypatch):
    monkeypatch.setattr(runtime_service, "_gpu", lambda: {"available": False, "reason": "nvidia_smi_missing"})
    data = runtime_service.collect("prod")
    for stage in data["stages"]:
        assert stage["vram"]["usedMb"] is None
        assert stage["reasons"]["vram"] == "nvidia_smi_missing"


def test_stopped_pipeline_marks_loaded_false_with_reason(healthy, monkeypatch):
    monkeypatch.setattr(runtime_service, "_pipeline_running", lambda: False)
    data = runtime_service.collect("prod")
    for stage in data["stages"]:
        assert stage["loaded"] is False
        assert stage["reasons"]["loaded"] == "pipeline_stopped"


def test_running_pipeline_is_loaded_even_without_metrics(healthy):
    # `healthy` leaves `_metrics_tail` empty. The deployed STT (qwen3-asr) and
    # LLM (chat-completions) emit no MODEL_CALL_METRICS at all, so "no metrics"
    # must not become a red "not loaded": a running pipeline is the evidence.
    data = runtime_service.collect("prod")
    for stage in data["stages"]:
        assert stage["loaded"] is True
        assert "loaded" not in stage["reasons"]


def test_queue_depth_is_null_and_not_zero(healthy):
    data = runtime_service.collect("prod")
    for stage in data["stages"]:
        assert stage["busy"]["queueDepth"] is None
        assert stage["reasons"]["queueDepth"] == "queue_depth_not_exposed"


def test_vad_has_no_first_byte(healthy):
    data = runtime_service.collect("prod")
    vad = next(s for s in data["stages"] if s["stage"] == "vad")
    assert vad["latency"]["firstByteMs"] is None
    assert vad["reasons"]["firstByte"] == "not_applicable"


def test_valid_values_carry_no_reason(healthy, monkeypatch):
    line = pkg_metrics_line("TTS", duration_s=0.42, first_byte_s=0.11, vram_mb=2048.0)
    monkeypatch.setattr(runtime_service, "_metrics_tail", lambda **kw: [line])
    tts = next(s for s in runtime_service.collect("prod")["stages"] if s["stage"] == "tts")
    # Queue depth is the one field the pipeline never exposes (A.14's
    # `queue_depth_not_exposed` is unconditional), so it is the only reason a
    # fully-measured stage may carry. Everything else has a value, hence no code.
    assert tts["reasons"] == {"queueDepth": "queue_depth_not_exposed"}
    assert tts["latency"]["firstByteMs"] == 110
    assert tts["vram"]["usedMb"] == 2048
    assert tts["loaded"] is True


def test_missing_gpu_still_returns_four_stages(healthy, monkeypatch):
    monkeypatch.setattr(runtime_service, "_gpu", lambda: {"available": False, "reason": "nvidia_smi_missing"})
    data = runtime_service.collect("prod")
    assert [s["stage"] for s in data["stages"]] == ["vad", "stt", "llm", "tts"]
    assert data["gpu"]["available"] is False
