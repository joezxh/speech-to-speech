from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from app.core.errors import ApiError
from app.core.exposure import if_match, refuse_protected, validate_profile_name
from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.repositories.audit_repository import AuditRepository
from app.repositories.version_repository import VersionRepository
from app.schemas.common import iso_utc, ok
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


def _since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError("invalid_parameter", f"not an ISO 8601 time: {value!r}", 400) from exc


@router.get("/profiles/{profile}/versions")
def get_versions(
    profile: str,
    db: DbSession,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
):
    """A.7: append-only history without the renderings.

    `yaml_text` is the whole file; fifty of them would be megabytes the history
    table never shows. It stays in the row for the rollback that needs the
    exact bytes.
    """
    name = validate_profile_name(profile)
    publish_flow_service.require_profile(name)
    rows, total = VersionRepository(db).list(name, page=page, page_size=pageSize)
    return ok({
        "list": [
            {
                "version": row.version,
                "status": row.status,
                "author": row.author,
                "note": row.note,
                "createdAt": iso_utc(row.created_at),
                "durationS": row.duration_s,
                "rolledBackTo": row.rolled_back_to,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    })


@router.get("/profiles/{profile}/audit")
def get_audit(
    profile: str,
    db: DbSession,
    actor: str = "",
    action: str = "",
    result: str = "",
    field: str = "",
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
):
    """A.8: field names, never values (§10.1)."""
    name = validate_profile_name(profile)
    publish_flow_service.require_profile(name)
    rows, total = AuditRepository(db).list(
        profile=name, actor=actor, action=action, result=result, field=field,
        since=_since(from_), until=_since(to), page=page, page_size=pageSize,
    )
    return ok({
        "list": [
            {
                "auditId": str(row.id),
                "at": iso_utc(row.at),
                "actor": row.actor,
                "role": row.role,
                "action": row.action,
                "version": row.version,
                "fields": list(row.fields or []),
                "result": row.result,
                "errorCode": row.error_code,
                "durationS": row.duration_s,
                "requestId": row.request_id,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    })
