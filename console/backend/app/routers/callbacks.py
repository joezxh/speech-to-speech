"""回调配置 CRUD/batch/test/logs（spec 2026-11-25 §8.4）。"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Query, Request, Response

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.callbacks import CallbackBatchRequest, CallbackTargetCreate, CallbackTargetUpdate
from app.schemas.common import ok
from app.services import callback_service
from app.services.callback_service import CallbackServiceError

router = APIRouter(prefix="/api/v1/callbacks", tags=["callbacks"])


@router.get("/targets")
def list_targets(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:callback:query")),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
):
    return ok(callback_service.list_targets(db, page, pageSize))


@router.get("/targets/dispatch-config")
def dispatch_config(db: DbSession, request: Request):
    """内部端点：s2s-agent CallbackDispatcher 轮询拉取（非 JWT，共享令牌 fail-closed）。

    - 令牌复用 S2S_ADMIN_TOKEN（与实例管理同源，console/pipeline 共用 env_file）；
      未配置 → 503（console 侧配置缺失），不匹配 → 401。
    - 响应含**明文 authToken**（投递硬需求，与 send_test_event 的明文消费一致）；
      只允许内部网络访问，不得接入 JWT 管理面或对外网关。
    - 声明在 `/targets/{target_id}` 之前：FastAPI 按声明顺序匹配，避免被路径参数吞掉。
    - 客户端（dispatcher）语义：成功响应（含空 targets）优先于 env 兜底；
      拉取失败保留最近一次成功配置（stale-while-error，见 dispatcher.py）。
    """
    expected = os.environ.get("S2S_ADMIN_TOKEN", "").strip()
    if not expected:
        raise ApiError("internal_disabled", "S2S_ADMIN_TOKEN is not configured on this console", 503)
    if not hmac.compare_digest(request.headers.get("X-Internal-Token", ""), expected):
        raise ApiError("unauthorized", "invalid internal token", 401)
    return ok(callback_service.dispatch_configs(db))


@router.post("/targets")
def create_target(
    payload: CallbackTargetCreate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    try:
        return ok(callback_service.create_target(db, payload, actor=user.username))
    except CallbackServiceError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc


@router.get("/targets/{target_id}")
def get_target(
    target_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:callback:query")),
):
    data = callback_service.get_target(db, target_id)
    if data is None:
        raise ApiError("not_found", f"callback target {target_id} not found", 404)
    return ok(data)


@router.put("/targets/{target_id}")
def update_target(
    target_id: int,
    payload: CallbackTargetUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    try:
        data = callback_service.update_target(db, target_id, payload, actor=user.username)
    except CallbackServiceError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc
    if data is None:
        raise ApiError("not_found", f"callback target {target_id} not found", 404)
    return ok(data)


@router.delete("/targets/{target_id}", status_code=204)
def delete_target(
    target_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    if not callback_service.delete_target(db, target_id):
        raise ApiError("not_found", f"callback target {target_id} not found", 404)
    return Response(status_code=204)


@router.post("/targets/batch")
def batch_targets(
    payload: CallbackBatchRequest,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    try:
        return ok(callback_service.batch_targets(db, payload.ids, payload.action))
    except CallbackServiceError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc


@router.post("/targets/{target_id}/test")
def test_target(
    target_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    try:
        return ok(callback_service.send_test_event(db, target_id))
    except CallbackServiceError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc


@router.get("/logs")
def list_logs(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:callback:query")),
    targetId: int | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
):
    return ok(callback_service.list_logs(
        db, target_id=targetId, status=status, page=page, page_size=pageSize))
