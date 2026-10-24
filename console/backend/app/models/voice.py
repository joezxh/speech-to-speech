from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Voice(Base):
    """One row per upload (spec §3.11.3).

    Paths are stored relative to the voice volume so the same row works whether
    the volume is mounted at `/app/data` or at a temp dir in tests. `name` is
    unique here, but SQLite compares case-sensitively, so the service also
    refuses a case-insensitive duplicate instead of relying on the constraint.
    """

    __tablename__ = "voices"
    __table_args__ = (UniqueConstraint("name", name="uq_voices_name"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    backend: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    audio_relpath: Mapped[str | None] = mapped_column(String(255), nullable=True)
    audio_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trim_start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trim_end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ref_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    instruct: Mapped[str | None] = mapped_column(Text, nullable=True)
    spk_relpath: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rvq_relpath: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    consent_ack_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
