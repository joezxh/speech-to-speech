# tests/test_livekit_worker.py
"""LiveKit worker 移植测试。全部离线：不 import livekit（mock），不发网络请求。"""
from __future__ import annotations

import pytest

from speech_to_speech.livekit_worker.events import (
    EVENT_TYPES,
    TranscriptEvent,
    TranscriptEventBus,
)


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
