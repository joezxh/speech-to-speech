"""SSE 实时转写流：订阅 TranscriptEventBus，逐事件 data: 行输出，15s 心跳。"""
from __future__ import annotations

import json
import threading
import time

import pytest
import speech_to_speech.livekit_worker.events as worker_events


@pytest.fixture()
def auth_headers(client) -> dict:
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _publish_transcript(text: str = "实时字幕测试") -> None:
    worker_events.get_event_bus().publish(
        worker_events.TranscriptEvent(
            event_type="transcript", room_sid="room-sse", identity="speaker-1",
            text=text, start_ts=1, end_ts=2, audio_level=-8,
            extra={}, timestamp_ms=12345,
        )
    )


def test_sse_requires_auth(client) -> None:
    assert client.get("/api/v1/live-transcripts/stream").status_code == 401


def test_sse_stream_emits_events(client, auth_headers: dict) -> None:
    """打开流 → 向进程内总线发布事件 → 读到 data 行；随后关闭。"""
    # 客户端读取期间由后台线程发布事件：TestClient 流式读取为同步迭代，
    # 先打开流（路由内已订阅总线），0.5s 后再 publish。
    def publish_later() -> None:
        time.sleep(0.5)
        _publish_transcript("实时字幕A")
        _publish_transcript("实时字幕B")

    threading.Thread(target=publish_later, daemon=True).start()
    received: list[dict] = []
    with client.stream("GET", "/api/v1/live-transcripts/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                received.append(json.loads(line[len("data: "):]))
                if len(received) >= 2:
                    break
    assert received[0]["text"] == "实时字幕A"
    assert received[1]["eventType"] == "transcript"


def test_sse_worker_absent_reports_error(client, auth_headers: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """livekit_worker 不可用（standalone console 部署）→ 首帧 error 事件。

    路由内 `from ... import get_event_bus` 后调用 `get_event_bus()`，from-import
    每次都从模块取属性，monkeypatch 模块属性即可生效。
    """
    def _boom() -> None:
        raise ImportError("livekit extra not installed")

    monkeypatch.setattr(worker_events, "get_event_bus", _boom)
    with client.stream("GET", "/api/v1/live-transcripts/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        lines = list(resp.iter_lines())
    assert any(line.startswith("event: error") for line in lines)
