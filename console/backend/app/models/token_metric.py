from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ParamTokenMetric(Base):
    """Token 增量时序（agent 按窗口上报，§5.2 心跳体的 tokens{} 落点）。

    计数是窗口增量而非累计值；audio_duration_s 是 RTF 的分子，缺键时为空。
    不建 FK：workload 删除后历史仍可读，与 param_instance_metric 既有做法一致。
    """

    __tablename__ = "param_token_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workload_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    responses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    window_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reported_by: Mapped[str] = mapped_column(String(64), nullable=False, default="agent")
