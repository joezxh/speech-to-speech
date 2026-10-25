from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.exposure import validate_profile_name
from app.core.security import CurrentUser, require_user
from app.schemas.common import ok
from app.services import publish_flow_service, runtime_service

router = APIRouter(prefix="/api/v1", tags=["runtime"])


@router.get("/runtime/models")
def runtime_models(
    profile: str = "prod",
    windowS: int = Query(300, ge=60, le=3600),
    user: CurrentUser = Depends(require_user),
):
    """A.14: four stage cards and one GPU header; degraded reads are 200.

    Same default profile as `/status` and `/instances`: the console serves one
    deployment and its name is a query parameter, not server state.
    """
    target = validate_profile_name(profile)
    publish_flow_service.require_profile(target)
    return ok(runtime_service.collect(target, windowS))
