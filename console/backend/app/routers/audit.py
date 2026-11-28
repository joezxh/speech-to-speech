"""全局审计端点 R5/R6（Task 25；console:audit:query|export）。

category 由 action 前缀推导（machine./lb./deploy./release./voice./cluster.）；
CSV 导出带 Content-Disposition: attachment，行数 = 筛选总数 + 表头。
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.security import CurrentUser
from app.core.permissions import require_permission
from app.deps import DbSession
from app.schemas.common import ok
from app.repositories.audit_repository import AuditRepository

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

CATEGORY_PREFIXES = (
    "machine.",
    "lb.",
    "deploy.",
    "release.",
    "voice.",
    "cluster.",
    "template.",
    "smart.",
)


def _category(action: str) -> str:
    for prefix in CATEGORY_PREFIXES:
        if action.startswith(prefix):
            return prefix.rstrip(".")
    return "other"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@router.get("")
def query_audit(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:audit:query")),
    actor: str = "",
    action: str = "",
    result: str = "",
    field: str = "",
    category: str = "",
    profile: str = "",
    from_date: str | None = None,
    to_date: str | None = None,
    page: int = 1,
    pageSize: int = 50,
):
    rows, total = AuditRepository(db).list(
        profile=profile,
        actor=actor,
        action=action,
        action_prefix=f"{category}." if category else "",
        result=result,
        field=field,
        since=_parse_date(from_date),
        until=_parse_date(to_date),
        page=max(1, page),
        page_size=max(1, min(pageSize, 200)),
    )
    items = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "at": row.at.isoformat(),
                "actor": row.actor,
                "role": row.role,
                "action": row.action,
                "category": _category(row.action),
                "profile": row.profile,
                "fields": row.fields,
                "result": row.result,
                "error_code": row.error_code,
            }
        )
    return ok({"items": items, "total": total, "page": page, "pageSize": pageSize})


@router.get("/export")
def export_audit(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:audit:export")),
    actor: str = "",
    action: str = "",
    result: str = "",
    field: str = "",
    category: str = "",
    profile: str = "",
    from_date: str | None = None,
    to_date: str | None = None,
):
    rows, _total = AuditRepository(db).list(
        profile=profile,
        actor=actor,
        action=action,
        action_prefix=f"{category}." if category else "",
        result=result,
        field=field,
        since=_parse_date(from_date),
        until=_parse_date(to_date),
        page=1,
        page_size=100_000,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "at", "actor", "role", "action", "category", "profile", "fields", "result", "error_code"])
    for row in rows:
        writer.writerow(
            [row.id, row.at.isoformat(), row.actor, row.role, row.action, _category(row.action), row.profile, ",".join(row.fields), row.result, row.error_code or ""]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"},
    )
