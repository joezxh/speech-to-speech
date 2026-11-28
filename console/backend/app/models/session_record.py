"""会话记录实体（对话页「会话记录」面板与历史页的数据落库）。

一次语音通话 = 一条 `param_session_record`；通话结束由前端保存当前转写
（逐行 → `param_session_message`，ordinal 保持通话顺序）。标题/备注可改、
消息可编辑/单删/清空，删除会话级联清理消息。

这里只存数据：轮数/时长/TTFA 由前端在 stop() 时计算好传入，后端不做二次
统计；user_id 记录保存人（列表按人过滤，operator 看得到全量）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow


class ParamSessionRecord(Base):
    __tablename__ = "param_session_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # pipeline 侧会话 ID（WS grant 的 sessionId），深链 /?session= 回跳用。
    pipeline_session_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    instance_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    node: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # done = 正常结束；failed = 异常中断。
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ttfa_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    messages: Mapped[list["ParamSessionMessage"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="ParamSessionMessage.ordinal",
        passive_deletes=True,
    )

    clips: Mapped[list["ParamSessionClip"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="ParamSessionClip.message_ordinal",
        passive_deletes=True,
    )


class ParamSessionMessage(Base):
    __tablename__ = "param_session_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("param_session_record.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # user | assistant | tool
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # text | audio
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    interrupted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # ok | fail —— 用户行=STT 结果，助手行=TTS 结果。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    # 该条语音时长（毫秒）；用户行来自 TranscriptAudio，助手行来自 latency.e2e_s。
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    record: Mapped[ParamSessionRecord] = relationship(back_populates="messages")


class ParamSessionClip(Base):
    """会话音频片段：按全局行序挂在消息行上，随会话级联删除。"""

    __tablename__ = "param_session_clip"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("param_session_record.id", ondelete="CASCADE"), nullable=False
    )
    # 与 param_session_message.ordinal 同一语义：全局行序。
    message_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # user | assistant（tool 行没有音频）。
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # 前端 turn 标识（itemId / responseId），仅作对账展示，不参与对齐。
    item_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    mime: Mapped[str] = mapped_column(String(64), nullable=False, default="audio/wav")
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=24000)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    record: Mapped[ParamSessionRecord] = relationship(back_populates="clips")
