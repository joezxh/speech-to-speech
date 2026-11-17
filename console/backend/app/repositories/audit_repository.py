from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, cast, func, select
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
        field: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
        action_prefix: str = "",
    ) -> tuple[list[ParamAudit], int]:
        stmt = select(ParamAudit)
        if profile:
            stmt = stmt.where(ParamAudit.profile == profile)
        if actor:
            stmt = stmt.where(ParamAudit.actor == actor)
        if action:
            stmt = stmt.where(ParamAudit.action == action)
        if action_prefix:
            stmt = stmt.where(ParamAudit.action.like(f"{action_prefix}%"))
        if result:
            stmt = stmt.where(ParamAudit.result == result)
        if field:
            # `fields` is a JSON array of names. A LIKE on its text form works on
            # both SQLite and Postgres without a JSON path operator, and the
            # quotes keep `stt.language` from matching `stt.language_variant`.
            stmt = stmt.where(cast(ParamAudit.fields, String).like(f'%"{field}"%'))
        if since is not None:
            stmt = stmt.where(ParamAudit.at >= since)
        if until is not None:
            stmt = stmt.where(ParamAudit.at <= until)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.order_by(ParamAudit.at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)

    def list_prefix(self, action_prefix: str, *, limit: int = 4) -> list[ParamAudit]:
        """按 action 前缀取最新行（集群总览「最近事件」卡，spec §5.2-5）。
        LIKE 前缀匹配 + 参数绑定，转义交驱动。"""
        stmt = (
            select(ParamAudit)
            .where(ParamAudit.action.like(f"{action_prefix}%"))
            .order_by(ParamAudit.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_any_prefix(self, action_prefixes: list[str], *, limit: int = 4) -> list[ParamAudit]:
        """多个 action 前缀合并取最新 N 行（总览事件卡：cluster.* ∪ machine.*）。
        机器增删改记 machine.*——只看 cluster.* 时添加机器不产生事件（用户反馈）。"""
        from sqlalchemy import or_  # noqa: PLC0415

        if not action_prefixes:
            return []
        stmt = (
            select(ParamAudit)
            .where(or_(*[ParamAudit.action.like(f"{prefix}%") for prefix in action_prefixes]))
            .order_by(ParamAudit.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
