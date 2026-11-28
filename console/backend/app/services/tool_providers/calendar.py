"""日历工具：本地事件库（无真实账号授权时的可操作日历）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.tool import CalendarEvent
from app.repositories.tool_repository import ToolRepository


def _out(row: CalendarEvent) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "start_at": row.start_at,
        "end_at": row.end_at,
        "description": row.description,
    }


def calendar_list(db: Session, owner: str) -> dict:
    return {"mode": "local", "events": [_out(row) for row in ToolRepository(db).list_events(owner=owner)]}


def calendar_create(db: Session, owner: str, payload: dict) -> dict:
    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValueError("title is required")
    row = ToolRepository(db).create_event(
        row=CalendarEvent(
            owner=owner,
            title=title,
            start_at=str(payload.get("start_at", "")),
            end_at=str(payload.get("end_at", "")),
            description=str(payload.get("description", "")),
        )
    )
    return {"mode": "local", **_out(row)}


def calendar_delete(db: Session, owner: str, event_id: int) -> bool:
    return ToolRepository(db).delete_event(event_id, owner=owner)
