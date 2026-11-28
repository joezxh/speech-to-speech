"""会话记录数据的读写（对话页「会话记录」面板 + 历史页）。

列表分页在 SQL 层做（单会话消息可能数百行）；详情一次取全并交前端本地搜索。
消息行的编辑/单删/清空只动 param_session_message；删除会话由 ORM 级联清理。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.lb import ParamLbRouteLog
from app.models.session_record import ParamSessionMessage, ParamSessionRecord


class SessionRecordRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(
        self,
        *,
        user_id: str = "",
        state: str = "",
        inst: str = "",
        q: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ParamSessionRecord], int]:
        base = select(ParamSessionRecord)
        if user_id:
            base = base.where(ParamSessionRecord.user_id == user_id)
        if state:
            base = base.where(ParamSessionRecord.state == state)
        if inst:
            base = base.where(
                or_(ParamSessionRecord.instance_id == inst, ParamSessionRecord.node == inst)
            )
        if since is not None:
            base = base.where(ParamSessionRecord.created_at >= since)
        if until is not None:
            base = base.where(ParamSessionRecord.created_at <= until)
        if q:
            like = f"%{q}%"
            base = base.where(
                or_(
                    ParamSessionRecord.title.like(like),
                    ParamSessionRecord.note.like(like),
                    ParamSessionRecord.pipeline_session_id.like(like),
                    ParamSessionRecord.instance_id.like(like),
                    ParamSessionRecord.node.like(like),
                    exists().where(
                        ParamSessionMessage.session_id == ParamSessionRecord.id,
                        ParamSessionMessage.content.like(like),
                    ),
                )
            )
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = list(
            self.session.scalars(
                base.order_by(ParamSessionRecord.created_at.desc(), ParamSessionRecord.id.desc())
                .offset(max(0, (page - 1) * page_size))
                .limit(page_size)
            )
        )
        return rows, int(total)

    def instances(self) -> list[dict]:
        """实例下拉数据源：非空 (instance_id, node) 对去重排序（两列投影，不拖全实体）。"""
        rows = self.session.execute(
            select(ParamSessionRecord.instance_id, ParamSessionRecord.node).distinct()
        ).all()
        pairs = {
            (instance_id or "", node or "")
            for instance_id, node in rows
            if instance_id or node
        }
        return [{"instanceId": a, "node": b} for a, b in sorted(pairs)]

    def get(self, record_id: int) -> ParamSessionRecord | None:
        return self.session.get(ParamSessionRecord, record_id)

    def get_messages(self, record_id: int) -> list[ParamSessionMessage]:
        stmt = (
            select(ParamSessionMessage)
            .where(ParamSessionMessage.session_id == record_id)
            .order_by(ParamSessionMessage.ordinal, ParamSessionMessage.id)
        )
        return list(self.session.scalars(stmt))

    def get_message(self, record_id: int, message_id: int) -> ParamSessionMessage | None:
        stmt = select(ParamSessionMessage).where(
            ParamSessionMessage.session_id == record_id,
            ParamSessionMessage.id == message_id,
        )
        return self.session.scalar(stmt)

    def create(
        self,
        *,
        record: ParamSessionRecord,
        messages: list[dict] | None = None,
    ) -> ParamSessionRecord:
        self.session.add(record)
        self.session.flush()
        for index, item in enumerate(messages or []):
            self.session.add(
                ParamSessionMessage(
                    session_id=record.id,
                    ordinal=item.get("ordinal", index),
                    role=item.get("role", "user"),
                    type=item.get("type", "text"),
                    content=item.get("content", ""),
                    interrupted=bool(item.get("interrupted", False)),
                    status=item.get("status", "ok"),
                    duration_ms=item.get("duration_ms", 0),
                )
            )
        self.session.commit()
        self.session.refresh(record)
        return record

    def delete(self, record_id: int) -> bool:
        row = self.get(record_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True

    def delete_many(self, record_ids: list[int]) -> int:
        rows = list(
            self.session.scalars(
                select(ParamSessionRecord).where(ParamSessionRecord.id.in_(record_ids))
            )
        )
        for row in rows:
            self.session.delete(row)
        self.session.commit()
        return len(rows)

    def clear_messages(self, record_id: int) -> int:
        rows = self.get_messages(record_id)
        for row in rows:
            self.session.delete(row)
        self.session.commit()
        return len(rows)

    def route_logs(self, *, limit: int = 50) -> list[ParamLbRouteLog]:
        """最近的 LB 路由决策（对话页「访问路由」tab 只读展示）。"""
        stmt = (
            select(ParamLbRouteLog)
            .order_by(ParamLbRouteLog.at.desc(), ParamLbRouteLog.id.desc())
            .limit(max(1, min(200, limit)))
        )
        return list(self.session.scalars(stmt))

    def stats(self, *, user_id: str = "") -> dict:
        base = select(ParamSessionRecord)
        if user_id:
            base = base.where(ParamSessionRecord.user_id == user_id)
        rows = list(self.session.scalars(base))
        done = sum(1 for row in rows if row.state == "done")
        failed = len(rows) - done
        durations = [row.duration_ms for row in rows if row.duration_ms > 0]
        avg_duration_ms = round(sum(durations) / len(durations)) if durations else 0
        ttfas = [row.ttfa_ms for row in rows if row.ttfa_ms]
        return {
            "total": len(rows),
            "done": done,
            "failed": failed,
            "turns": sum(row.turns for row in rows),
            "avgDurationMs": avg_duration_ms,
            "avgTtfaMs": round(sum(ttfas) / len(ttfas)) if ttfas else 0,
        }
