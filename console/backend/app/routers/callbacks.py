"""回调配置 CRUD/batch/test/logs（spec 2026-11-25 §8.4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

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
