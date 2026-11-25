"""CallbackDispatcher 离线测试：sqlite 内存库 + requests mock。"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from speech_to_speech.callback.dispatcher import CallbackDispatcher, mask_token

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1] / "console" / "backend")


@pytest.fixture()
def db_session(monkeypatch: pytest.MonkeyPatch):
    # console 后端在本仓内，测试直接用它的 Base/models（console/backend 进 sys.path，
    # 由 monkeypatch 在用例结束后还原，避免污染其它根仓库测试）。
    monkeypatch.syspath_prepend(_BACKEND_ROOT)
    from app.db.base import Base
    from app.models.callbacks import CallbackTarget

    # dispatcher 在线程池里写投递日志：sqlite 内存库必须全线程共享一个连接
    # （StaticPool），否则 worker 线程拿到的是空库。
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session, CallbackTarget


def _target(CallbackTarget, **overrides) -> object:
    fields = dict(
        name="webhook", target_type="python", base_url="http://hook", auth_type="none",
        auth_token="", extra_headers={}, timeout_ms=100, retry_max_attempts=2,
        retry_backoff_ms=0, events=["transcript"], filters=None, enabled=True,
    )
    fields.update(overrides)
    return CallbackTarget(**fields)


def _event(event_type: str = "transcript", text: str = "你好会议", identity: str = "u1"):
    from speech_to_speech.livekit_worker.events import TranscriptEvent

    return TranscriptEvent(
        event_type=event_type, room_sid="room-1", identity=identity, text=text,
        start_ts=1000, end_ts=2000, audio_level=-10, extra={}, timestamp_ms=12345,
    )


class _Resp:
    def __init__(self, status_code: int, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(self.status_code)


def test_dispatch_hits_python_target(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget))
    session.commit()

    posted: dict = {}

    def fake_post(url, **kwargs):  # noqa: ANN001
        posted.update({"url": url, **kwargs})
        return _Resp(200)

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert posted["url"] == "http://hook"
    assert posted["json"]["eventType"] == "transcript"
    assert posted["json"]["text"] == "你好会议"


def test_log_rows_written(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget))
    session.commit()
    monkeypatch.setattr(
        "speech_to_speech.callback.dispatcher.requests.post",
        lambda url, **kwargs: _Resp(200))
    from app.models.callbacks import CallbackDeliveryLog

    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    rows = list(session.query(CallbackDeliveryLog).all())
    assert len(rows) == 1
    assert rows[0].status == "success" and rows[0].http_status == 200


def test_java_protocol_adapter(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, name="ai", target_type="java",
                        base_url="http://ai", auth_type="header_token",
                        auth_header_name="X-Internal-Token", auth_token="tok",
                        extra_headers={"tenant-id": "7"}))
    session.commit()
    posted: dict = {}

    def fake_post(url, **kwargs):  # noqa: ANN001
        posted.update({"url": url, **kwargs})
        return _Resp(200)

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert posted["url"] == "http://ai/admin-api/ai/meeting/internal/transcript"
    assert posted["params"] == {"roomSid": "room-1"}
    assert posted["headers"]["X-Internal-Token"] == "tok"
    assert posted["headers"]["tenant-id"] == "7"
    assert isinstance(posted["json"], list)  # TranscriptSegmentVO 数组形状


def test_python_bearer_auth(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, auth_type="bearer", auth_token="btok"))
    session.commit()
    captured: dict = {}

    def fake_post(url, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return _Resp(200)

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert captured["headers"]["Authorization"] == "Bearer btok"


def test_retry_then_give_up(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, retry_max_attempts=2, retry_backoff_ms=0))
    session.commit()
    attempts = []

    def fake_post(url, **kwargs):  # noqa: ANN001
        attempts.append(1)
        raise ConnectionError("down")

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    from app.models.callbacks import CallbackDeliveryLog

    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert len(attempts) == 2
    rows = list(session.query(CallbackDeliveryLog).all())
    assert [r.status for r in rows] == ["retrying", "failed"]


def test_filters_event_type_and_speaker(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, events=["session_end"], filters={"speakers": ["u2"]}))
    session.commit()
    posted = []

    monkeypatch.setattr(
        "speech_to_speech.callback.dispatcher.requests.post",
        lambda url, **kwargs: posted.append(kwargs) or _Resp(200))
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event(event_type="transcript", identity="u1"))  # 事件不符
    dispatcher.dispatch(_event(event_type="session_end"))               # speakers 过滤仅作用于 transcript
    dispatcher.flush_pending()
    # transcript 被事件订阅过滤；session_end 无 identity，speakers 过滤只作用于 transcript
    assert len(posted) == 1


def test_min_text_len_filter(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, filters={"min_text_len": 5}))
    session.commit()
    posted = []
    monkeypatch.setattr(
        "speech_to_speech.callback.dispatcher.requests.post",
        lambda url, **kwargs: posted.append(kwargs) or _Resp(200))
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event(text="短"))
    dispatcher.dispatch(_event(text="足够长的文本"))
    dispatcher.flush_pending()
    assert len(posted) == 1


def test_ttl_cache_refresh(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, enabled=False))
    session.commit()
    posted: list = []

    def fake_post(url, **kwargs):  # noqa: ANN001
        posted.append({"url": url, **kwargs})
        return _Resp(200)

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=5)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert dispatcher.pending_count() == 0  # disabled 目标不投递
    # 动态启用（无需重启）：改库 + 缓存失效
    from app.models.callbacks import CallbackTarget as T

    session.query(T).update({"enabled": True})
    session.commit()
    dispatcher.invalidate_cache()
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert len(posted) == 1


def test_env_fallback_java_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JAVA_CALLBACK_BASE", "http://ai")
    monkeypatch.setenv("MEETING_INTERNAL_TOKEN", "tok")
    monkeypatch.delenv("CONSOLE_DATABASE_URL", raising=False)
    dispatcher = CallbackDispatcher(session_factory=None, ttl_seconds=0)
    targets = dispatcher._effective_targets()
    assert len(targets) == 1
    assert targets[0].target_type == "java"
    assert targets[0].base_url == "http://ai"
    assert targets[0].auth_header_name == "X-Internal-Token"


def test_mask_token() -> None:
    assert mask_token("secret-token-value") == "secr***alue"
    assert mask_token("") == "***"
