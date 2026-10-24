from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamAudit(Base):
    """Append-only. `fields` holds names only — never values (spec §10.1)."""

    __tablename__ = "param_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    profile: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[str] = mapped_column(String(8), nullable=False, default="ok")
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
