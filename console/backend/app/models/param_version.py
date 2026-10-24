from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamVersion(Base):
    """Immutable snapshot. `yaml_text` is what makes byte-comparison on boot
    possible (spec §4.1 启动自检); never updated after creation except status."""

    __tablename__ = "param_version"
    __table_args__ = (UniqueConstraint("profile", "version", name="uq_param_version_profile_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="publishing")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    author: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    yaml_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    yaml_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    env_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolled_back_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
