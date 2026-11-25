"""回调目标服务层：校验（java 协议事件约束）、脱敏、测试投递。"""
from __future__ import annotations

import time

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.callbacks import CallbackTarget
from app.repositories.callback_repository import CallbackRepository
from app.schemas.callbacks import CallbackTargetCreate, CallbackTargetUpdate

JAVA_ONLY_EVENTS = ("transcript",)


def mask_token(token: str) -> str:
    if len(token) < 10:
        return "***"
    return f"{token[:4]}***{token[-4:]}"


class CallbackServiceError(ValueError):
    """业务校验失败（HTTP 400）。"""


def _validate_protocol(payload: CallbackTargetCreate | CallbackTargetUpdate) -> None:
    if payload.targetType == "java":
        bad = [e for e in payload.events if e not in JAVA_ONLY_EVENTS]
        if bad:
            raise CallbackServiceError(f"java 目标仅支持 {JAVA_ONLY_EVENTS} 事件: {bad}")
        if payload.authType != "header_token":
            raise CallbackServiceError("java 目标鉴权固定为 header_token")
    if payload.authType == "header_token" and not payload.authHeaderName:
        payload.authHeaderName = "X-Callback-Token"


def _fields(payload) -> dict:
    return {
        "name": payload.name, "target_type": payload.targetType, "base_url": payload.baseUrl,
        "auth_type": payload.authType, "auth_header_name": payload.authHeaderName,
        "auth_token": payload.authToken, "extra_headers": payload.extraHeaders,
        "timeout_ms": payload.timeoutMs, "retry_max_attempts": payload.retryMaxAttempts,
        "retry_backoff_ms": payload.retryBackoffMs, "events": payload.events,
        "filters": payload.filters, "enabled": payload.enabled,
    }


def _to_out(row) -> dict:
    return {
        "id": row.id, "name": row.name, "targetType": row.target_type,
        "baseUrl": row.base_url, "authType": row.auth_type,
        "authHeaderName": row.auth_header_name,
        "authToken": mask_token(row.auth_token) if row.auth_token else "",
        "extraHeaders": row.extra_headers or {}, "timeoutMs": row.timeout_ms,
        "retryMaxAttempts": row.retry_max_attempts, "retryBackoffMs": row.retry_backoff_ms,
        "events": row.events or [], "filters": row.filters, "enabled": bool(row.enabled),
    }


def list_targets(db: Session, page: int, page_size: int) -> dict:
    rows, total = CallbackRepository(db).list(page, page_size)
    return {"list": [_to_out(r) for r in rows], "total": total, "page": page, "pageSize": page_size}


def get_target(db: Session, target_id: int) -> dict | None:
    row = CallbackRepository(db).get(target_id)
    return _to_out(row) if row else None


def create_target(db: Session, payload: CallbackTargetCreate, actor: str) -> dict:
    _validate_protocol(payload)
    existing = db.execute(
        select(CallbackTarget).where(CallbackTarget.name == payload.name)
    ).scalar_one_or_none()
    if existing is not None:
        raise CallbackServiceError(f"目标名 {payload.name!r} 已存在")
    row = CallbackRepository(db).create(**_fields(payload), updated_by=actor)
    return _to_out(row)


def update_target(db: Session, target_id: int, payload: CallbackTargetUpdate, actor: str) -> dict | None:
    _validate_protocol(payload)
    row = CallbackRepository(db).update(target_id, **_fields(payload), updated_by=actor)
    return _to_out(row) if row else None


def delete_target(db: Session, target_id: int) -> bool:
    return CallbackRepository(db).delete(target_id)


def batch_targets(db: Session, ids: list[int], action: str) -> dict:
    repo = CallbackRepository(db)
    if action == "enable":
        return {"updated": repo.batch_set_enabled(ids, True)}
    if action == "disable":
        return {"updated": repo.batch_set_enabled(ids, False)}
    if action == "delete":
        return {"deleted": repo.batch_delete(ids)}
    raise CallbackServiceError(f"未知批量操作: {action!r}")


def send_test_event(db: Session, target_id: int) -> dict:
    """发送一条测试 transcript 事件，同步返回投递结果（spec §8.4）。

    连接探测不是正式投递：重试固定 1 次，不写 callback_delivery_log。
    请求构造复用 dispatcher 的协议适配，保证与真实投递同形状。
    """
    from speech_to_speech.callback.dispatcher import CallbackTargetConfig, _build_request

    row = CallbackRepository(db).get(target_id)
    if row is None:
        raise CallbackServiceError("target not found")
    config = CallbackTargetConfig(
        id=row.id, name=row.name, target_type=row.target_type, base_url=row.base_url,
        auth_type=row.auth_type, auth_header_name=row.auth_header_name,
        auth_token=row.auth_token, extra_headers=row.extra_headers or {},
        timeout_ms=row.timeout_ms, retry_max_attempts=1, retry_backoff_ms=0,
        events=tuple(row.events or ()), filters=row.filters, enabled=True,
    )

    class _FakeEvent:
        event_type = "transcript"
        room_sid = "console-test"
        identity = "console"
        text = "这是一条 console 回调连接测试事件"
        start_ts = 0
        end_ts = 0
        audio_level = None
        extra = {"test": True}

        def to_payload(self) -> dict:
            return {
                "eventType": "transcript", "roomSid": "console-test",
                "identity": "console", "text": self.text, "startTs": 0, "endTs": 0,
                "timestamp": int(time.time() * 1000), "test": True,
            }

    url, payload, headers = _build_request(_FakeEvent(), config)
    started = time.monotonic()
    try:
        resp = requests.post(url, json=payload, headers=headers,
                             timeout=config.timeout_ms / 1000,
                             params=({"roomSid": "console-test"} if config.target_type == "java" else None))
        ok = 200 <= int(resp.status_code) < 300
        return {"ok": ok, "httpStatus": int(resp.status_code),
                "durationMs": int((time.monotonic() - started) * 1000),
                "error": "" if ok else resp.text[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "httpStatus": None,
                "durationMs": int((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}"[:200]}


def list_logs(db: Session, *, target_id: int | None, status: str | None,
              page: int, page_size: int) -> dict:
    from app.schemas.common import iso_utc

    rows, total = CallbackRepository(db).list_logs(
        target_id=target_id, status=status, page=page, page_size=page_size)
    return {
        "list": [{
            "id": r.id, "targetId": r.target_id, "eventType": r.event_type,
            "triggeredAt": iso_utc(r.triggered_at), "requestUrl": r.request_url,
            "requestPayload": r.request_payload, "attempt": r.attempt,
            "httpStatus": r.http_status, "responseSnippet": r.response_snippet,
            "durationMs": r.duration_ms, "status": r.status, "error": r.error,
        } for r in rows],
        "total": total, "page": page, "pageSize": page_size,
    }
