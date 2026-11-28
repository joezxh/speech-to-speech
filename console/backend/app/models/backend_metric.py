from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ParamBackendMetric(Base):
    """Per-backend（STT/LLM/TTS）调用增量时序（agent 心跳 tokens.backends 落点）。

    计数是窗口增量而非累计值；latency_ms_sum 是调用时延总和（avg_ms=ms_sum/calls
    由查询端推导，不在库里存派生值）。engine/model 是上报时的后端标识快照，
    可为空（旧版 agent 不带）。不建 FK：与 param_token_metric 同约定。
    """

    __tablename__ = "param_backend_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reported_by: Mapped[str] = mapped_column(String(64), nullable=False, default="agent")
