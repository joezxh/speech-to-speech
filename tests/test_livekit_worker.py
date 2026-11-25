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
