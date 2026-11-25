# tests/test_livekit_worker.py
"""LiveKit worker 移植测试。全部离线：不 import livekit（mock），不发网络请求。"""
from __future__ import annotations

import pytest

from speech_to_speech.livekit_worker.audio_level import SILENCE_DBFS, compute_audio_level_dbfs
from speech_to_speech.livekit_worker.events import (
    EVENT_TYPES,
    TranscriptEvent,
    TranscriptEventBus,
)
from speech_to_speech.livekit_worker.segment_dedupe import DuplicateGuard, normalize_text


def test_event_types() -> None:
    assert EVENT_TYPES == ("transcript", "segment_attributed", "session_end")


def test_transcript_event_to_payload() -> None:
    event = TranscriptEvent(
        event_type="transcript",
        room_sid="room-1",
        identity="user-a",
        text="大家好",
        start_ts=1000,
        end_ts=2000,
        audio_level=-12,
        extra={"speakerName": "张三"},
        timestamp_ms=1700000000000,
    )
    payload = event.to_payload()
    assert payload == {
        "eventType": "transcript",
        "roomSid": "room-1",
        "identity": "user-a",
        "text": "大家好",
        "startTs": 1000,
        "endTs": 2000,
        "audioLevel": -12,
        "speakerName": "张三",
        "timestamp": 1700000000000,
    }


def test_transcript_event_extra_flattens() -> None:
    event = TranscriptEvent(
        event_type="transcript", room_sid="r", identity="i", text="t",
        start_ts=0, end_ts=1, audio_level=None, extra={"serEmotion": "calm"}, timestamp_ms=0,
    )
    assert event.to_payload()["serEmotion"] == "calm"


def test_bus_publish_subscribe() -> None:
    bus = TranscriptEventBus()
    seen: list[TranscriptEvent] = []
    unsubscribe = bus.subscribe(seen.append)
    event = TranscriptEvent(
        event_type="session_end", room_sid="r", identity="i", text="",
        start_ts=0, end_ts=0, audio_level=None, extra={}, timestamp_ms=0,
    )
    bus.publish(event)
    unsubscribe()
    bus.publish(event)
    assert len(seen) == 1
    assert seen[0].event_type == "session_end"


def test_bus_subscriber_exception_isolated() -> None:
    bus = TranscriptEventBus()
    seen: list[TranscriptEvent] = []

    def bad(_: TranscriptEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(bad)
    bus.subscribe(seen.append)
    bus.publish(TranscriptEvent(
        event_type="transcript", room_sid="r", identity="i", text="t",
        start_ts=0, end_ts=0, audio_level=None, extra={}, timestamp_ms=0,
    ))
    assert len(seen) == 1  # 坏订阅者不影响其它订阅者


def test_event_type_validation() -> None:
    with pytest.raises(ValueError, match="event_type"):
        TranscriptEvent(
            event_type="bogus", room_sid="r", identity="i", text="t",
            start_ts=0, end_ts=0, audio_level=None, extra={}, timestamp_ms=0,
        )


def test_dedupe_normalize_strips_punctuation() -> None:
    assert normalize_text("之前，没一次性写出来！") == "之前没一次性写出来"


def test_dedupe_short_text_passes() -> None:
    guard = DuplicateGuard()
    assert guard.should_skip("u1", "嗯", 1000) is False


def test_dedupe_exact_duplicate_within_window() -> None:
    guard = DuplicateGuard()
    assert guard.should_skip("u1", "之前没一次性写出来", 1000) is False
    assert guard.should_skip("u1", "之前没一次性写出来", 2000) is True


def test_dedupe_variant_with_tail() -> None:
    guard = DuplicateGuard()
    assert guard.should_skip("u1", "之前没一次性写出来", 1000) is False
    assert guard.should_skip("u1", "之前没一次性写出来了", 2000) is True


def test_dedupe_window_expiry() -> None:
    guard = DuplicateGuard()
    guard.should_skip("u1", "之前没一次性写出来", 1000)
    assert guard.should_skip("u1", "之前没一次性写出来", 1000 + 4001) is False


def test_dedupe_identity_scoped() -> None:
    guard = DuplicateGuard()
    guard.should_skip("u1", "之前没一次性写出来", 1000)
    assert guard.should_skip("u2", "之前没一次性写出来", 2000) is False


def test_audio_level_silence_and_full_scale() -> None:
    assert compute_audio_level_dbfs(b"") == SILENCE_DBFS
    full_scale = (32767).to_bytes(2, "little", signed=True) * 100
    assert compute_audio_level_dbfs(full_scale) == 0
    assert compute_audio_level_dbfs(b"\x00\x00" * 100) == SILENCE_DBFS


def test_audio_level_odd_length_bytes_tolerated() -> None:
    assert compute_audio_level_dbfs(b"\x01") == SILENCE_DBFS


# ---------------------------------------------------------------------------
# ser_provider：SP-4 声学情感 Provider（fail-closed 门）
# ---------------------------------------------------------------------------
from speech_to_speech.livekit_worker import ser_provider
from speech_to_speech.livekit_worker.ser_provider import (
    DEFAULT_SER_POLICY,
    SerCircuitBreaker,
    SerConcurrencyGate,
    SerRejectedException,
    SerResult,
    get_ser_provider,
    in_segment_window,
    parse_switch_snapshot,
)


class _FakeResponse:
    """requests.Response 最小替身（Task 6/7 共用）。"""

    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, str):
            import json as _json
            return _json.loads(self._payload)
        return self._payload


def test_ser_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SER_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="SER_PROVIDER"):
        get_ser_provider()


def test_ser_result_validates_labels() -> None:
    assert SerResult.from_response({"emotion": "calm", "confidence": 0.9, "model": "m"}).emotion == "calm"
    assert SerResult.from_response({"emotion": "happy", "confidence": 0.9, "model": "m"}).emotion == "calm"
    with pytest.raises(ValueError, match="emotion"):
        SerResult.from_response({"emotion": "unknown", "confidence": 0.9, "model": "m"})
    with pytest.raises(ValueError, match="confidence"):
        SerResult.from_response({"emotion": "calm", "confidence": 1.5, "model": "m"})
    with pytest.raises(ValueError, match="缺少字段"):
        SerResult.from_response({"emotion": "calm"})


def test_parse_switch_snapshot_fail_closed() -> None:
    closed = parse_switch_snapshot({})
    assert closed["ser"] is False and closed["policyComplete"] is False
    complete = parse_switch_snapshot({
        "voice": True, "ser": True, "video": False,
        "serPolicy": {"minSegSec": 1.0, "maxSegSec": 30.0, "maxConcurrency": 2,
                      "failThreshold": 3, "cooldownSec": 60},
    })
    assert complete["ser"] is True and complete["policyComplete"] is True


def test_segment_window() -> None:
    policy = dict(DEFAULT_SER_POLICY)
    assert in_segment_window(2 * 16000 * 5, 16000, policy)  # 5s
    assert not in_segment_window(2 * 16000 * 0.5, 16000, policy)  # 0.5s < min
    assert not in_segment_window(2 * 16000 * 40, 16000, policy)  # 40s > max


def test_concurrency_gate() -> None:
    gate = SerConcurrencyGate(1)
    assert gate.try_enter() is True
    assert gate.try_enter() is False
    gate.exit()
    assert gate.inflight == 0


def test_circuit_breaker_opens_and_recovers() -> None:
    clock = {"now": 0.0}
    breaker = SerCircuitBreaker(fail_threshold=2, cooldown_sec=10, clock=lambda: clock["now"])
    breaker.record_failure()
    assert breaker.is_open is False
    breaker.record_failure()
    assert breaker.is_open is True
    assert breaker.allow() is False
    clock["now"] += 11
    assert breaker.allow() is True  # 半开放行
    breaker.record_success()
    assert breaker.is_open is False


def test_ser_rejected_is_distinct_exception() -> None:
    assert issubclass(SerRejectedException, RuntimeError)


def test_ser_http_409_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """409 → SerRejectedException（fail-closed，不降级为无 SER 结果）。

    源工程 ser_provider 中发起 /v1/audio/emotion 请求、409 抛
    SerRejectedException 的路径是 ``HttpSerProvider.predict``（无模块级
    ``post_segment``），按移植对齐规则以源码真实名称调用。
    """
    from speech_to_speech.livekit_worker import ser_provider as sp

    provider = sp.HttpSerProvider(base_url="http://ser")

    def fake_post(url, **kwargs):  # noqa: ANN001
        return _FakeResponse(409, '{"error":"concurrency"}')

    monkeypatch.setattr(sp.requests, "post", fake_post)
    with pytest.raises(SerRejectedException):
        provider.predict(b"\x01\x00" * 16000, 16000)
