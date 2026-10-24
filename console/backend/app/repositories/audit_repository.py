from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.param_audit import ParamAudit


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        actor: str,
        role: str,
        action: str,
        profile: str,
        fields: list[str],
        result: str = "ok",
        version: int | None = None,
        error_code: str | None = None,
        duration_s: float | None = None,
        request_id: str = "",
    ) -> ParamAudit:
        row = ParamAudit(
            actor=actor,
            role=role,
            action=action,
            profile=profile,
            fields=list(fields),
            result=result,
            version=version,
            error_code=error_code,
            duration_s=duration_s,
            request_id=request_id,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def list(
        self,
        *,
        profile: str = "",
        actor: str = "",
        action: str = "",
        result: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ParamAudit], int]:
        stmt = select(ParamAudit)
        if profile:
            stmt = stmt.where(ParamAudit.profile == profile)
        if actor:
            stmt = stmt.where(ParamAudit.actor == actor)
        if action:
            stmt = stmt.where(ParamAudit.action == action)
        if result:
            stmt = stmt.where(ParamAudit.result == result)
        if since is not None:
            stmt = stmt.where(ParamAudit.at >= since)
        if until is not None:
            stmt = stmt.where(ParamAudit.at <= until)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.order_by(ParamAudit.at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)
