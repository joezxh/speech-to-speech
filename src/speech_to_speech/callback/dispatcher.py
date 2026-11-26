"""可配置回调子系统（spec 2026-11-25 §8）。

serve 进程内单例：dispatch(event) → 读取启用目标（TTL 缓存热加载）→ 过滤
→ 按目标协议适配投递（java/python）→ 重试 → callback_delivery_log 落库。

- DB 不可用时 env 兜底（JAVA_CALLBACK_BASE + MEETING_INTERNAL_TOKEN → 内存
  java 目标），保持源工程零改动部署可用（spec §8.3）；DB 查询失败期同样回落。
- 投递在线程池执行，不阻塞转写主流程；每目标独立，单点失败不影响其它目标。
- 段序说明：异步投递按段并发，同房间 transcript 的到达顺序为 best-effort；
  需要严格保序的场景由目标端按 startTs 排序。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

JAVA_TRANSCRIPT_PATH = "/admin-api/ai/meeting/internal/transcript"
DEFAULT_TTL_SECONDS = 5.0
PAYLOAD_SNIPPET_MAX = 2000
RESPONSE_SNIPPET_MAX = 200


@dataclass(frozen=True)
class CallbackTargetConfig:
    """dispatcher 视角的平铺目标配置（ORM 行 → 此结构）。"""

    id: int | None
    name: str
    target_type: str  # java | python
    base_url: str
    auth_type: str  # none | bearer | header_token
    auth_header_name: str | None
    auth_token: str
    extra_headers: dict = field(default_factory=dict)
    timeout_ms: int = 3000
    retry_max_attempts: int = 3
    retry_backoff_ms: int = 500
    events: tuple[str, ...] = ()
    filters: dict | None = None
    enabled: bool = True


def mask_token(token: str) -> str:
    """token 脱敏：前 4 位 + *** + 后 4 位；过短或为空全遮。"""
    if len(token) < 10:
        return "***"
    return f"{token[:4]}***{token[-4:]}"


def _row_to_config(row) -> CallbackTargetConfig:
    return CallbackTargetConfig(
        id=row.id, name=row.name, target_type=row.target_type, base_url=row.base_url,
        auth_type=row.auth_type, auth_header_name=row.auth_header_name,
        auth_token=row.auth_token, extra_headers=dict(row.extra_headers or {}),
        timeout_ms=int(row.timeout_ms), retry_max_attempts=int(row.retry_max_attempts),
        retry_backoff_ms=int(row.retry_backoff_ms),
        events=tuple(row.events or []), filters=row.filters, enabled=bool(row.enabled),
    )


def _env_fallback_target() -> CallbackTargetConfig:
    """旧 env 兜底：与源工程 worker.py push() 行为完全一致。"""
    return CallbackTargetConfig(
        id=None, name="env-java-fallback", target_type="java",
        base_url=os.environ.get("JAVA_CALLBACK_BASE", "").rstrip("/"),
        auth_type="header_token", auth_header_name="X-Internal-Token",
        auth_token=os.environ.get("MEETING_INTERNAL_TOKEN", ""),
        extra_headers={"tenant-id": os.environ.get("MEETING_TENANT_ID", "1")},
        timeout_ms=3000, retry_max_attempts=3, retry_backoff_ms=500,
        events=("transcript",), filters=None, enabled=True,
    )


def _env_fallback_targets() -> list[CallbackTargetConfig]:
    """env 兜底目标：JAVA_CALLBACK_BASE + MEETING_INTERNAL_TOKEN 齐备才启用。"""
    base = os.environ.get("JAVA_CALLBACK_BASE", "").strip()
    token = os.environ.get("MEETING_INTERNAL_TOKEN", "").strip()
    if base and token:
        return [_env_fallback_target()]
    return []


def _passes_filters(event, config: CallbackTargetConfig) -> bool:
    """事件订阅 + 过滤器（speakers / min_text_len）。"""
    if event.event_type not in (config.events or ()):
        return False
    filters = config.filters or {}
    if event.event_type == "transcript":
        speakers = filters.get("speakers")
        if speakers and event.identity not in speakers:
            return False
        min_len = filters.get("min_text_len")
        if min_len is not None and len(event.text or "") < int(min_len):
            return False
    return True


def build_request(event, config: CallbackTargetConfig) -> tuple[str, object, dict]:
    """按 target_type 协议适配（spec §8.2 矩阵）。返回 (url, payload, headers)。"""
    headers: dict = dict(config.extra_headers or {})
    if config.target_type == "java":
        # java：固定内部端点 + header_token；body 为 TranscriptSegmentVO 数组
        segment: dict = {
            "speakerIdentity": event.identity,
            "text": event.text,
            "startTs": event.start_ts,
            "endTs": event.end_ts,
        }
        if event.audio_level is not None:
            segment["audioLevel"] = event.audio_level
        segment.update(event.extra)
        headers["X-Internal-Token"] = config.auth_token
        headers.setdefault("tenant-id", os.environ.get("MEETING_TENANT_ID", "1"))
        url = f"{config.base_url}{JAVA_TRANSCRIPT_PATH}"
        return url, [segment], headers
    # python：base_url 即完整 webhook；body 为统一事件 JSON
    payload = event.to_payload()
    if config.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {config.auth_token}"
    elif config.auth_type == "header_token":
        headers[config.auth_header_name or "X-Callback-Token"] = config.auth_token
    return config.base_url, payload, headers


# 兼容别名：保留 _ 前缀引用（既有测试投递与文档调用点）。
_build_request = build_request


def deliver_once(event, config: CallbackTargetConfig, url: str, payload: object,
                 headers: dict) -> tuple[int | None, str]:
    """单次投递，返回 (http_status, response_snippet)；网络异常向上抛。"""
    resp = requests.post(url, json=payload, headers=headers,
                         timeout=config.timeout_ms / 1000, params=(
                             {"roomSid": event.room_sid} if config.target_type == "java" else None))
    status = int(resp.status_code)
    snippet = (getattr(resp, "text", "") or "")[:RESPONSE_SNIPPET_MAX]
    return status, snippet


# 兼容别名：保留 _ 前缀引用。
_deliver_once = deliver_once


def _sanitize_payload(payload: object) -> str:
    """payload 截断后入库（仅截断，不含 token 脱敏）。"""
    import json

    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > PAYLOAD_SNIPPET_MAX:
        text = text[:PAYLOAD_SNIPPET_MAX] + "...(truncated)"
    return text


class CallbackDispatcher:
    """单例分发器。session_factory 为 None 时进入 env 兜底模式（不写 DB 日志）。"""

    def __init__(self, session_factory, ttl_seconds: float = DEFAULT_TTL_SECONDS,
                 max_workers: int = 8) -> None:
        self._session_factory = session_factory
        self._ttl_seconds = ttl_seconds
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="callback")
        self._cache: list[CallbackTargetConfig] | None = None
        self._cache_at = 0.0
        self._lock = threading.Lock()
        self._pending_futures: set = set()

    # ---- 目标解析（TTL 缓存热加载，spec §8.3）----
    def invalidate_cache(self) -> None:
        """清空目标缓存；并发竞态不改——最长 TTL（默认 5s）后自然重载兜底。"""
        with self._lock:
            self._cache = None
            self._cache_at = 0.0

    def _load_targets(self) -> list[CallbackTargetConfig]:
        if self._session_factory is None:
            return _env_fallback_targets()
        now = time.monotonic()
        with self._lock:
            if self._cache is not None and now - self._cache_at < self._ttl_seconds:
                return self._cache
        session = None
        try:
            session = self._session_factory()
            from app.models.callbacks import CallbackTarget

            rows = session.query(CallbackTarget).filter(CallbackTarget.enabled.is_(True)).all()
            configs = [_row_to_config(row) for row in rows]
        except Exception:  # noqa: BLE001 DB 故障期回落 env 兜底（spec §8.3）
            logger.warning("callback targets DB query failed; falling back to env target",
                           exc_info=True)
            return _env_fallback_targets()
        finally:
            if session is not None:
                session.close()
        with self._lock:
            self._cache = configs
            self._cache_at = now
        return configs

    def _effective_targets(self) -> list[CallbackTargetConfig]:
        return [t for t in self._load_targets() if t.enabled]

    # ---- 入口 ----
    def dispatch(self, event) -> None:
        """异步投递：每目标一个线程任务；单目标失败只记日志。"""
        for config in self._effective_targets():
            if not _passes_filters(event, config):
                continue
            future = self._pool.submit(self._deliver_with_retry, event, config)
            self._pending_futures.add(future)
            future.add_done_callback(self._pending_futures.discard)

    def publish_transcript(self, room_sid: str, segments: list[dict]) -> None:
        """worker emit_segments 的 java 兼容入口：逐段产出 transcript 事件。"""
        from speech_to_speech.livekit_worker.events import TranscriptEvent

        for segment in segments:
            extra = {k: v for k, v in segment.items()
                     if k not in ("speakerIdentity", "text", "startTs", "endTs", "audioLevel")}
            self.dispatch(TranscriptEvent(
                event_type="transcript", room_sid=room_sid,
                identity=str(segment.get("speakerIdentity", "")),
                text=str(segment.get("text", "")),
                start_ts=int(segment.get("startTs", 0)), end_ts=int(segment.get("endTs", 0)),
                audio_level=segment.get("audioLevel"), extra=extra,
                timestamp_ms=int(time.time() * 1000),
            ))

    def pending_count(self) -> int:
        return sum(1 for f in list(self._pending_futures) if not f.done())

    def flush_pending(self, timeout: float = 10.0) -> None:
        """测试/退出用：等待在途投递完成（spec §9 flush 语义）。

        timeout 为总等待预算：多个在途任务按累计剩余时间分配，预算耗尽抛
        TimeoutError（而非每个 future 各自等待完整 timeout）。
        """
        futures = list(self._pending_futures)
        self._pending_futures = set()
        deadline = time.monotonic() + timeout
        for future in futures:
            future.result(timeout=deadline - time.monotonic())

    # ---- 投递 + 重试 + 日志 ----
    def _deliver_with_retry(self, event, config: CallbackTargetConfig) -> None:
        url, payload, headers = build_request(event, config)
        body_text = _sanitize_payload(payload)
        attempts = max(1, config.retry_max_attempts)
        last_error = ""
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            status: int | None = None
            snippet = ""
            error = ""
            ok = False
            try:
                status, snippet = deliver_once(event, config, url, payload, headers)
                ok = 200 <= status < 300
                if not ok:
                    error = f"HTTP {status}"
            except Exception as exc:  # noqa: BLE001 网络异常按重试计
                error = f"{type(exc).__name__}: {exc}"[:500]
            duration_ms = int((time.monotonic() - started) * 1000)
            if ok:
                self._write_log(event, config, url, body_text, attempt, status, snippet,
                                duration_ms, "success", "")
                return
            if attempt < attempts:
                self._write_log(event, config, url, body_text, attempt, status, snippet,
                                duration_ms, "retrying", error)
                backoff = config.retry_backoff_ms * (2 ** (attempt - 1)) / 1000
                if backoff > 0:
                    time.sleep(backoff)
            else:
                last_error = error
                self._write_log(event, config, url, body_text, attempt, status, snippet,
                                duration_ms, "failed", last_error)
        logger.warning("callback %s -> %s 最终失败: %s", config.name, url, last_error)

    def _write_log(self, event, config: CallbackTargetConfig, url: str, payload_text: str,
                   attempt: int, status: int | None, snippet: str, duration_ms: int,
                   log_status: str, error: str) -> None:
        if self._session_factory is None:
            logger.info("callback(env) %s attempt=%d status=%s", url, attempt, log_status)
            return
        session = self._session_factory()
        try:
            from app.models.callbacks import CallbackDeliveryLog

            # triggered_at 不显式传：显式 None 会覆盖 ORM default，NOT NULL 违例；
            # 留空让 default=utcnow 在 flush 时填充。
            session.add(CallbackDeliveryLog(
                target_id=config.id, event_type=event.event_type,
                request_url=url, request_payload=payload_text, attempt=attempt,
                http_status=status, response_snippet=snippet[:RESPONSE_SNIPPET_MAX],
                duration_ms=duration_ms, status=log_status,
                error=error[:1024],
            ))
            session.commit()
        except Exception:  # noqa: BLE001 日志落库失败不投递中断
            logger.exception("callback delivery log write failed")
        finally:
            session.close()


_dispatcher: CallbackDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_dispatcher() -> CallbackDispatcher:
    """进程级单例；优先复用 console 后端的 SessionLocal，失败退 env 兜底。"""
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is None:
            session_factory = None
            try:
                from app.db.database import SessionLocal

                session_factory = SessionLocal
            except Exception:  # noqa: BLE001 console 后端不可导入 → env 兜底
                session_factory = None
            _dispatcher = CallbackDispatcher(session_factory)
        return _dispatcher


def reset_dispatcher() -> None:
    """测试隔离用。"""
    global _dispatcher
    with _dispatcher_lock:
        _dispatcher = None
