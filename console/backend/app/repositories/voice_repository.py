from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.voice import Voice


class VoiceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, voice_id: str) -> Voice | None:
        return self.session.get(Voice, voice_id)

    def by_name(self, name: str) -> Voice | None:
        """Case-insensitive: SQLite's UNIQUE compares bytes, so `Jiajia` and
        `jiajia` would both be accepted by the constraint alone (§11.2)."""
        return self.session.scalar(select(Voice).where(func.lower(Voice.name) == name.lower()))

    def list(
        self,
        *,
        backend: str = "",
        source: str = "",
        status: str = "",
        q: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Voice], int]:
        stmt = select(Voice)
        if backend:
            stmt = stmt.where(Voice.backend == backend)
        if source:
            stmt = stmt.where(Voice.source == source)
        if status:
            stmt = stmt.where(Voice.status == status)
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(Voice.name).like(pattern), func.lower(Voice.id).like(pattern)))
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.order_by(Voice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)

    def add(self, row: Voice) -> Voice:
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def save(self, row: Voice) -> Voice:
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def remove(self, row: Voice) -> None:
        self.session.delete(row)
        self.session.commit()
