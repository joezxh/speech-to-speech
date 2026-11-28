"""会话记录管理面（console:session:* 权限码）。

保存（POST ""）与查询/管理共用前缀 /api/v1/session-records；审计在
session_record_service 落（session-record.* / message.*），路由层不重复记。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.session_record import (
    SessionBatchDelete,
    SessionMessageUpdate,
    SessionRecordSave,
    SessionRecordUpdate,
)
from app.services import session_record_service

router = APIRouter(prefix="/api/v1/session-records", tags=["session-records"])


@router.get("")
def list_records(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:query")),
    q: str = "",
    state: str = "",
    inst: str = "",
    from_date: str = "",
    to_date: str = "",
    range: str = "",
    page: int = 1,
    pageSize: int = 20,
):
    """会话记录列表（关键词/状态/实例/时间范围筛选 + 分页）。"""
    return ok(
        session_record_service.list_records(
            db,
            state=state,
            inst=inst,
            q=q,
            from_date=from_date,
            to_date=to_date,
            date_range=range,
            page=page,
            page_size=pageSize,
        )
    )


@router.get("/stats")
def stats(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:query")),
):
    """KPI 汇总（总数/正常/失败/总轮数/平均时长）。"""
    return ok(session_record_service.stats(db))


@router.get("/route-logs")
def route_logs(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:query")),
    limit: int = 50,
):
    """最近的 LB 路由决策（对话页「访问路由」tab，只读）。"""
    return ok(session_record_service.list_route_logs(db, limit=limit))


@router.get("/instances")
def instances(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:query")),
):
    """实例下拉数据源（历史页筛选卡，非空 (instance_id, node) 对去重）。"""
    return ok(session_record_service.instances(db))


@router.get("/{record_id}")
def get_record(
    record_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:query")),
):
    try:
        return ok(session_record_service.get_record(db, record_id))
    except KeyError:
        raise ApiError("not_found", f"session record {record_id} does not exist", 404) from None


@router.post("")
def save_record(
    payload: SessionRecordSave,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:write")),
):
    """通话结束保存（前端 stop() 调用）。"""
    return ok(session_record_service.save_record(db, payload, actor=user.username))


@router.patch("/{record_id}")
def update_record(
    record_id: int,
    payload: SessionRecordUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:write")),
):
    """改标题/备注。"""
    try:
        return ok(session_record_service.update_record(db, record_id, payload, actor=user.username))
    except KeyError:
        raise ApiError("not_found", f"session record {record_id} does not exist", 404) from None


@router.delete("/{record_id}", status_code=204)
def delete_record(
    record_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:write")),
):
    try:
        session_record_service.delete_record(db, record_id, actor=user.username)
    except KeyError:
        raise ApiError("not_found", f"session record {record_id} does not exist", 404) from None


@router.post("/batch-delete")
def delete_records(
    payload: SessionBatchDelete,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:write")),
):
    deleted = session_record_service.delete_records(db, payload.ids, actor=user.username)
    return ok({"deleted": deleted})


@router.patch("/{record_id}/messages/{message_id}")
def update_message(
    record_id: int,
    message_id: int,
    payload: SessionMessageUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:write")),
):
    """编辑单条消息文本。"""
    try:
        return ok(
            session_record_service.update_message(db, record_id, message_id, payload, actor=user.username)
        )
    except KeyError:
        raise ApiError("not_found", f"message {message_id} does not exist", 404) from None


@router.delete("/{record_id}/messages/{message_id}", status_code=204)
def delete_message(
    record_id: int,
    message_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:write")),
):
    try:
        session_record_service.delete_message(db, record_id, message_id, actor=user.username)
    except KeyError:
        raise ApiError("not_found", f"message {message_id} does not exist", 404) from None


@router.post("/{record_id}/messages/clear")
def clear_messages(
    record_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:write")),
):
    try:
        cleared = session_record_service.clear_messages(db, record_id, actor=user.username)
    except KeyError:
        raise ApiError("not_found", f"session record {record_id} does not exist", 404) from None
    return ok({"cleared": cleared})


@router.post("/{record_id}/clips")
def upload_clip(
    record_id: int,
    db: DbSession,
    file: UploadFile = File(...),
    message_ordinal: int = Form(0),
    role: str = Form("user"),
    item_ref: str = Form(""),
    sample_rate: int = Form(24000),
    duration_ms: int = Form(0),
    user_write: CurrentUser = Depends(require_permission("console:session:write")),
):
    """上传一段会话音频（multipart）。失败不影响已保存记录。"""
    try:
        data = file.file.read()
    finally:
        file.file.close()
    try:
        clip = session_record_service.save_clip(
            db,
            record_id,
            message_ordinal=message_ordinal,
            role=role,
            item_ref=item_ref,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            data=data,
            actor=user_write.username,
        )
    except KeyError:
        raise ApiError("not_found", f"session record {record_id} does not exist", 404) from None
    return ok(clip)


@router.get("/{record_id}/clips/{clip_id}")
def download_clip(
    record_id: int,
    clip_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:session:query")),
):
    """回放片段字节（Content-Type 为片段 mime，浏览器可直接播放）。"""
    try:
        mime, data = session_record_service.clip_bytes(db, record_id, clip_id, actor=user.username)
    except KeyError:
        raise ApiError("not_found", f"clip {clip_id} does not exist", 404) from None
    return Response(content=data, media_type=mime)
