from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.errors import ApiError
from app.core.exposure import if_match, refuse_protected, validate_profile_name
from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.draft import DraftPatchRequest
from app.services import draft_service, publish_flow_service

router = APIRouter(prefix="/api/v1", tags=["drafts"])


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


@router.get("/profiles/{profile}/draft")
def get_draft(profile: str, db: DbSession, user: CurrentUser = Depends(require_user)):
    """A.2: a patch, not a document; secrets come back as `***`."""
    return ok(draft_service.read_draft(db, validate_profile_name(profile)))


@router.post("/profiles/{profile}/draft")
def post_draft(
    profile: str,
    payload: DraftPatchRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    """A.3: `null` falls back to the default, `***` leaves the field alone."""
    name = validate_profile_name(profile)
    refuse_protected(user.role, payload.patch, publish_flow_service.entries())
    claimed = payload.baseVersion
    if claimed is None:
        claimed = if_match(request.headers.get("if-match", ""))
    return ok(
        draft_service.save_draft(
            db,
            name,
            payload.patch,
            base_version=claimed,
            actor=user.username,
            role=user.role,
            request_id=_request_id(request),
        )
    )


@router.delete("/profiles/{profile}/draft")
def delete_draft(profile: str, request: Request, db: DbSession, user: CurrentUser = Depends(require_user)):
    """A.4: destructive, so admin only."""
    name = validate_profile_name(profile)
    if user.role != "admin":
        raise ApiError("forbidden", "only an admin may discard a draft", 403)
    return ok(
        draft_service.discard_draft(db, name, actor=user.username, role=user.role, request_id=_request_id(request))
    )
