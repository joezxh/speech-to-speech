# src/speech_to_speech/livekit_worker/events.py
"""转写事件构造与进程内事件总线。

worker 每产出一个转写分段/会话结束，构造一个 :class:`TranscriptEvent`：
- bus.publish 交给进程内订阅者（本地转写 sink、日志 sink）；
- callback 子系统的 CallbackDispatcher.publish(event) 按 DB 配置投递。

payload 字段名沿用源工程 Java 侧 TranscriptSegmentVO 的 camelCase，保证
java 目标的向后兼容；python 目标收到同一份 JSON。
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

EVENT_TYPES = ("transcript", "segment_attributed", "session_end")


@dataclass(frozen=True)
class TranscriptEvent:
    """一条转写事件的统一形状（各协议适配器共享）。"""

    event_type: str
    room_sid: str
    identity: str
    text: str
    start_ts: int
    end_ts: int
    audio_level: int | None
    extra: dict[str, object] = field(default_factory=dict)
    timestamp_ms: int = 0

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"event_type must be one of {'|'.join(EVENT_TYPES)}; got {self.event_type!r}")

    def to_payload(self) -> dict[str, object]:
        """统一事件 JSON（python 目标的投递体）。"""
        payload: dict[str, object] = {
            "eventType": self.event_type,
            "roomSid": self.room_sid,
            "identity": self.identity,
            "text": self.text,
            "startTs": self.start_ts,
            "endTs": self.end_ts,
            "timestamp": self.timestamp_ms,
        }
        if self.audio_level is not None:
            payload["audioLevel"] = self.audio_level
        payload.update(self.extra)
        return payload


class TranscriptEventBus:
    """线程安全的最小发布/订阅总线（worker 线程发布，任意线程订阅）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[TranscriptEvent], None]] = []

    def subscribe(self, callback: Callable[[TranscriptEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, event: TranscriptEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - 坏订阅者不拖垮 worker
                logger.exception("transcript event subscriber failed")


_bus: TranscriptEventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> TranscriptEventBus:
    """进程级单例总线；serve 内 worker 与其它模块共享。"""
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = TranscriptEventBus()
        return _bus
