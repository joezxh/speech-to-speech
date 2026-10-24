from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ok
from app.services import status_service

router = APIRouter(prefix="/api/v1", tags=["status"])


@router.get("/status")
def get_status(
    db: DbSession, profile: str = "prod", user: CurrentUser = Depends(require_user)
):
    """A.11: the top bar and the publish gate read this."""
    return ok(status_service.snapshot(db, profile))
