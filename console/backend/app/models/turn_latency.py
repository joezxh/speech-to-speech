from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class TurnLatencyRow(Base):
    """A rebuildable index over `TURN_LATENCY` log lines, not a ledger.

    Dropping this table and replaying `pipeline-stdout.log` restores it exactly
    (§3.9.4), which is why it stores milliseconds and nothing derived: rates and
    percentiles are computed per request, so a change of definition never needs
    a migration.
    """

    __tablename__ = "turn_latency"

    response_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    turn_revision: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)
    turn_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    smart_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    e2e_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tts_ttfa_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vad_decision_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hold_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
