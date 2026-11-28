"""会话记录业务（对话页「会话记录」面板 + 历史页共用）。

设计约束：
* 保存入口只有一个：POST /session-records（前端 stop() 调用，带 JWT）。
  轮数/时长/TTFA 由前端计算好传入，后端只做枚举与长度校验。
* 权限查询面（console:session:query）看全量；保存人记 user_id。
* 审计沿用既有约定：action 点分前缀（session-record.* / message.*），
  fields 只存字段名不存值。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.session_record import ParamSessionClip, ParamSessionMessage, ParamSessionRecord
from app.repositories.audit_repository import AuditRepository
from app.repositories.session_record_repository import SessionRecordRepository
from app.schemas.common import iso_utc
from app.schemas.session_record import (
    SessionMessageUpdate,
    SessionRecordSave,
    SessionRecordUpdate,
)

STATES = ("done", "failed")
STATUS_VALUES = ("ok", "fail")
ROLES = ("user", "assistant", "tool")
TYPES = ("text", "audio")
CLIP_ROLES = ("user", "assistant")
CLIP_MIME = "audio/wav"
CLIP_MAX_BYTES = 8 * 1024 * 1024


def _check_enum(value: str, allowed: tuple[str, ...], label: str) -> None:
    if value not in allowed:
        raise ApiError("invalid_request", f"{label} must be one of {', '.join(allowed)}", 400)


def _audit(db: Session, *, actor: str, action: str, name: str, fields: list[str]) -> None:
    AuditRepository(db).record(
        actor=actor,
        role="",
        action=action,
        profile=name,
        fields=list(fields),
    )


def _out(row: ParamSessionRecord, *, with_messages: bool = False) -> dict:
    out = {
        "id": row.id,
        "userId": row.user_id,
        "title": row.title,
        "note": row.note,
        "pipelineSessionId": row.pipeline_session_id,
        "instanceId": row.instance_id,
        "node": row.node,
        "state": row.state,
        "turns": row.turns,
        "durationMs": row.duration_ms,
        "ttfaMs": row.ttfa_ms,
        "createdAt": iso_utc(row.created_at),
        "updatedAt": iso_utc(row.updated_at),
    }
    if with_messages:
        messages = list(row.messages)
        out["messages"] = [
            {
                "id": msg.id,
                "ordinal": msg.ordinal,
                "role": msg.role,
                "type": msg.type,
                "content": msg.content,
                "interrupted": msg.interrupted,
                "status": msg.status,
                "durationMs": msg.duration_ms,
                "createdAt": iso_utc(msg.created_at),
            }
            for msg in messages
        ]
        out["messageCount"] = len(messages)
        out["excerpt"] = " · ".join(msg.content for msg in messages)[:90]
        # 片段概要（不含字节）：前端按 message_ordinal 对齐消息行接线回放。
        out["clips"] = [_clip_out(clip) for clip in row.clips]
    else:
        # 列表分支占位（Task 3 批量查询真值替换，避免逐行 lazy load）。
        out["messageCount"] = 0
        out["excerpt"] = ""
    return out


def _clip_out(clip: ParamSessionClip) -> dict:
    return {
        "id": clip.id,
        "role": clip.role,
        "itemRef": clip.item_ref,
        "messageOrdinal": clip.message_ordinal,
        "durationMs": clip.duration_ms,
        "sizeBytes": clip.size_bytes,
    }


def get_row(db: Session, record_id: int) -> ParamSessionRecord:
    row = SessionRecordRepository(db).get(record_id)
    if row is None:
        raise KeyError(record_id)
    return row


def list_records(
    db: Session,
    *,
    state: str = "",
    inst: str = "",
    q: str = "",
    from_date: str = "",
    to_date: str = "",
    date_range: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    if state:
        _check_enum(state, STATES, "state")
    repo = SessionRecordRepository(db)
    rows, total = repo.list(
        state=state,
        inst=inst,
        q=q,
        since=_parse_date(from_date) or _parse_range(date_range),
        until=_parse_date(to_date, end_of_day=True),
        page=max(1, page),
        page_size=max(1, min(200, page_size)),
    )
    list_out = []
    if rows:
        # 当页消息批量查出，填 messageCount/excerpt（避免逐行 lazy load）。
        grouped: dict[int, list[str]] = {}
        stmt = select(ParamSessionMessage).where(
            ParamSessionMessage.session_id.in_([row.id for row in rows])
        )
        for msg in db.scalars(stmt):
            grouped.setdefault(msg.session_id, []).append(msg.content)
        for row in rows:
            contents = grouped.get(row.id, [])
            out = _out(row)
            out["messageCount"] = len(contents)
            # 完整转写（不截断）：历史页摘录列整段展示。
            out["excerpt"] = " · ".join(contents)
            list_out.append(out)
    return {
        "list": list_out,
        "total": total,
        "page": page,
        "pageSize": page_size,
    }


def instances(db: Session) -> list[dict]:
    """实例下拉数据源（历史页筛选卡）。"""
    return SessionRecordRepository(db).instances()


def stats(db: Session) -> dict:
    return SessionRecordRepository(db).stats()


def list_route_logs(db: Session, *, limit: int = 50) -> list[dict]:
    """最近的 LB 路由决策（对话页「访问路由」tab）。"""
    return [
        {
            "at": iso_utc(row.at),
            "sessionKey": row.session_key,
            "ruleId": row.rule_id,
            "matched": row.matched,
            "instanceId": row.instance_id,
            "stickyHit": row.sticky_hit,
            "isCanary": row.is_canary,
            "inputTokens": row.input_tokens,
            "outputTokens": row.output_tokens,
        }
        for row in SessionRecordRepository(db).route_logs(limit=limit)
    ]


def get_record(db: Session, record_id: int) -> dict:
    return _out(get_row(db, record_id), with_messages=True)


def save_record(db: Session, payload: SessionRecordSave, *, actor: str) -> dict:
    _check_enum(payload.state, STATES, "state")
    messages = []
    for item in payload.messages:
        _check_enum(item.role, ROLES, "role")
        _check_enum(item.type, TYPES, "type")
        _check_enum(item.status, STATUS_VALUES, "status")
        messages.append(
            {
                "role": item.role,
                "type": item.type,
                "content": item.content,
                "interrupted": item.interrupted,
                "status": item.status,
                "duration_ms": item.durationMs,
            }
        )
    row = ParamSessionRecord(
        user_id=actor,
        title=payload.title or "未命名会话",
        note=payload.note,
        pipeline_session_id=payload.pipelineSessionId,
        instance_id=payload.instanceId,
        node=payload.node,
        state=payload.state,
        turns=payload.turns,
        duration_ms=payload.durationMs,
        ttfa_ms=payload.ttfaMs,
    )
    row = SessionRecordRepository(db).create(record=row, messages=messages)
    _audit(
        db,
        actor=actor,
        action="session-record.save",
        name=row.title,
        fields=["state", "turns", "durationMs", "messages"],
    )
    return _out(row, with_messages=True)


def update_record(db: Session, record_id: int, payload: SessionRecordUpdate, *, actor: str) -> dict:
    row = get_row(db, record_id)
    changed = payload.model_dump(exclude_unset=True)
    for attr, value in changed.items():
        setattr(row, attr, value)
    db.commit()
    db.refresh(row)
    _audit(db, actor=actor, action="session-record.update", name=row.title, fields=sorted(changed))
    return _out(row)


def delete_record(db: Session, record_id: int, *, actor: str) -> None:
    row = get_row(db, record_id)
    title = row.title
    if not SessionRecordRepository(db).delete(record_id):
        raise KeyError(record_id)
    _audit(db, actor=actor, action="session-record.delete", name=title, fields=[])


def delete_records(db: Session, ids: list[int], *, actor: str) -> int:
    deleted = SessionRecordRepository(db).delete_many(ids)
    if deleted == 0:
        raise ApiError("not_found", "no matching session records", 404)
    _audit(
        db,
        actor=actor,
        action="session-record.batch-delete",
        name="",
        fields=[],
    )
    return deleted


def update_message(
    db: Session, record_id: int, message_id: int, payload: SessionMessageUpdate, *, actor: str
) -> dict:
    row = get_row(db, record_id)
    repo = SessionRecordRepository(db)
    msg = repo.get_message(record_id, message_id)
    if msg is None:
        raise KeyError(message_id)
    msg.content = payload.content
    db.commit()
    db.refresh(msg)
    _audit(db, actor=actor, action="message.update", name=row.title, fields=["content"])
    return {
        "id": msg.id,
        "ordinal": msg.ordinal,
        "role": msg.role,
        "type": msg.type,
        "content": msg.content,
        "interrupted": msg.interrupted,
        "status": msg.status,
        "durationMs": msg.duration_ms,
        "createdAt": iso_utc(msg.created_at),
    }


def delete_message(db: Session, record_id: int, message_id: int, *, actor: str) -> None:
    row = get_row(db, record_id)
    repo = SessionRecordRepository(db)
    msg = repo.get_message(record_id, message_id)
    if msg is None:
        raise KeyError(message_id)
    db.delete(msg)
    db.commit()
    # 对齐原型删消息联动：turns 重算（只数 assistant 行）；duration_ms 是墙钟差不改。
    row.turns = sum(1 for m in repo.get_messages(record_id) if m.role == "assistant")
    db.commit()
    _audit(db, actor=actor, action="message.delete", name=row.title, fields=[])


def clear_messages(db: Session, record_id: int, *, actor: str) -> int:
    row = get_row(db, record_id)
    cleared = SessionRecordRepository(db).clear_messages(record_id)
    row.turns = 0
    db.commit()
    _audit(db, actor=actor, action="message.clear", name=row.title, fields=[])
    return cleared


def save_clip(
    db: Session,
    record_id: int,
    *,
    message_ordinal: int,
    role: str,
    item_ref: str = "",
    sample_rate: int = 24000,
    duration_ms: int = 0,
    data: bytes,
    actor: str,
) -> dict:
    """保存一段会话音频（multipart 上传；失败不影响已保存记录）。"""
    _check_enum(role, CLIP_ROLES, "role")
    if len(data) > CLIP_MAX_BYTES:
        raise ApiError("invalid_request", f"clip too large ({len(data)} bytes, max {CLIP_MAX_BYTES})", 400)
    row = get_row(db, record_id)
    clip = SessionRecordRepository(db).add_session_clip(
        row.id,
        message_ordinal=max(0, message_ordinal),
        role=role,
        item_ref=item_ref[:128],
        mime=CLIP_MIME,
        sample_rate=max(1, sample_rate),
        duration_ms=max(0, duration_ms),
        data=data,
    )
    _audit(
        db,
        actor=actor,
        action="session-clip.upload",
        name=row.title,
        fields=["role", "messageOrdinal", "sizeBytes"],
    )
    return _clip_out(clip)


def clip_bytes(db: Session, record_id: int, clip_id: int, *, actor: str) -> tuple[str, bytes]:
    """回放：返回 (mime, 字节)。找不到记录或片段都是 404。"""
    row = get_row(db, record_id)
    clip = SessionRecordRepository(db).get_session_clip(row.id, clip_id)
    if clip is None:
        raise KeyError(clip_id)
    _audit(db, actor=actor, action="session-clip.download", name=row.title, fields=[])
    return clip.mime, clip.data


def _parse_range(value: str):
    """today/24h/7d → UTC since；all/空 → None（不限）；未知值 400。"""
    from datetime import datetime, timedelta, timezone

    raw = (value or "").strip()
    if not raw or raw == "all":
        return None
    now = datetime.now(timezone.utc)
    if raw == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if raw == "24h":
        return now - timedelta(hours=24)
    if raw == "7d":
        return now - timedelta(days=7)
    raise ApiError("invalid_request", f"bad range {value}, expect all|today|24h|7d", 400)


def _parse_date(value: str, *, end_of_day: bool = False):
    """YYYY-MM-DD → UTC datetime；end_of_day 把范围推到当天最后一微秒。"""
    from datetime import datetime, timedelta, timezone

    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ApiError("invalid_request", f"bad date {value}, expect YYYY-MM-DD", 400) from None
    if end_of_day:
        parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed
