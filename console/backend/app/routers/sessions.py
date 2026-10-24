from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.session import SessionUpdateRequest
from app.services import hot_update_service

router = APIRouter(prefix="/api/v1", tags=["sessions"])


@router.post("/sessions/update")
def post_session_update(
    payload: SessionUpdateRequest,
    request: Request,
    db: DbSession,
    profile: str = "prod",
    user: CurrentUser = Depends(require_user),
):
    """A.9: chain B. admin and operator alike (A.0.2) — nothing is written to disk."""
    return ok(
        hot_update_service.update(
            db,
            profile,
            scope=payload.scope,
            target=payload.target,
            session=payload.session,
            actor=user.username,
            role=user.role,
            request_id=getattr(request.state, "request_id", ""),
        )
    )
