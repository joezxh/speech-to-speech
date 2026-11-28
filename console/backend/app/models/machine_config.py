from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamMachineConfig(Base):
    """机器实际生效配置（漂移源）：与 profile 期望值逐键比对得出 drift_count。

    每机每键一行（upsert 落点）；值统一按字符串存，与 param_config 同口径。
    """

    __tablename__ = "param_machine_config"
    __table_args__ = (
        UniqueConstraint("machine_id", "param_key", name="uq_param_machine_config_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    param_key: Mapped[str] = mapped_column(String(128), nullable=False)
    actual_value: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    reported_by: Mapped[str] = mapped_column(String(64), nullable=False, default="agent")


class ParamMachineDraft(Base):
    """机器级待下发草稿：live 渲染后按本表覆盖对应键（§7.2.3）。"""

    __tablename__ = "param_machine_draft"
    __table_args__ = (
        UniqueConstraint("machine_id", "param_key", name="uq_param_machine_draft_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    param_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ParamAgentConfigVersion(Base):
    """agent 目标配置下发快照（Task 5/6 的实现载体，命名遵循 param_* 惯例）。

    主键是 (machine_id, config_version)：ack 成功时保存下发全文，按机保留
    最近 N=5 版（环形覆盖）；render_target 每次递增版本号并写一行。
    """

    __tablename__ = "param_agent_config_version"

    machine_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    config_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 80 而非 64：ack 成功时会在 64 位摘要前打 "ack:" 标记（4 + 64 = 68 字符），见
    # agent_config_service.ack；64 列会触发 StringDataRightTruncation（2026-11-27 实测）。
    yaml_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    yaml_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rendered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
