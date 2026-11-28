"""控制台工具数据的读写（原型「会话工具」页）。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.tool import CalendarEvent, ConsoleTool


class ToolRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, *, q: str = "") -> list[ConsoleTool]:
        stmt = select(ConsoleTool).order_by(ConsoleTool.updated_at.desc())
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(ConsoleTool.name.like(like), ConsoleTool.description.like(like), ConsoleTool.id.like(like))
            )
        return list(self.session.scalars(stmt))

    def get(self, tool_id: str) -> ConsoleTool | None:
        return self.session.get(ConsoleTool, tool_id)

    def get_by_name(self, name: str) -> ConsoleTool | None:
        return self.session.scalar(select(ConsoleTool).where(ConsoleTool.name == name))

    def create(self, *, row: ConsoleTool) -> ConsoleTool:
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete(self, tool_id: str) -> bool:
        row = self.get(tool_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True

    def list_events(self, *, owner: str) -> list[CalendarEvent]:
        stmt = select(CalendarEvent).where(CalendarEvent.owner == owner).order_by(CalendarEvent.start_at)
        return list(self.session.scalars(stmt))

    def get_event(self, event_id: int, *, owner: str) -> CalendarEvent | None:
        row = self.session.get(CalendarEvent, event_id)
        return row if row is not None and row.owner == owner else None

    def create_event(self, *, row: CalendarEvent) -> CalendarEvent:
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete_event(self, event_id: int, *, owner: str) -> bool:
        row = self.get_event(event_id, owner=owner)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True
