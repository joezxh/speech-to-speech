from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.repositories.version_repository import VersionRepository
from app.schemas.common import ok
from app.services import instances_service

router = APIRouter(prefix="/api/v1", tags=["instances"])


@router.get("/instances")
def get_instances(
    db: DbSession, profile: str = "prod", user: CurrentUser = Depends(require_user)
):
    """A.10: a degraded read is still a 200."""
    latest = VersionRepository(db).latest_live(profile)
    return ok(instances_service.collect(profile, int(latest.version) if latest else None))
