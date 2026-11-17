"""发布台账端点 R1–R4（Task 24；console:release:query|write）。

build/staging 由外部 CI 执行，console 只记账——CI 用服务凭据回填 stage_result。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.release import ReleaseCreate, ReleaseOut, StageResultIn
from app.services import release_service

router = APIRouter(prefix="/api/v1/releases", tags=["releases"])


@router.post("")
def create_release(
    payload: ReleaseCreate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:release:write")),
):
    release = release_service.create_release(db, payload, actor=user.username)
    return ok(release.model_dump())


@router.post("/{release_id}/advance")
def advance(
    release_id: str,
    payload: StageResultIn,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:release:write")),
):
    try:
        release = release_service.advance(
            db, release_id, payload.stage, payload.result, payload.note, user.username
        )
    except ApiError:
        raise
    return ok(release.model_dump())


@router.post("/{release_id}/stage-result")
def stage_result(
    release_id: str,
    payload: StageResultIn,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:release:write")),
):
    """R3b：CI 回填阶段结论（signature 可空=内网受信，审计记 signature_absent）。"""
    try:
        release = release_service.stage_result(db, release_id, payload, actor=user.username)
    except ApiError:
        raise
    return ok(release.model_dump())


@router.post("/{release_id}/rollback")
def rollback(
    release_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:release:write")),
):
    try:
        release = release_service.rollback(db, release_id, actor=user.username)
    except ApiError:
        raise
    return ok(release.model_dump())


@router.get("")
def list_releases(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:release:query")),
):
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.release import ParamRelease  # noqa: PLC0415

    rows = db.scalars(select(ParamRelease).order_by(ParamRelease.created_at.desc())).all()
    return ok({"releases": [release_service._out(row).model_dump() for row in rows]})


@router.get("/summary")
def summary(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:release:query")),
):
    return ok(release_service.summary(db))
