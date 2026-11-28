"""session-records 路由的请求模型（camelCase 契约）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SessionMessageIn(BaseModel):
    """保存会话时的消息行：role/type/content 按 TranscriptEntry 归一。"""

    role: str = Field(default="user", max_length=16)
    type: str = Field(default="text", max_length=16)
    content: str = Field(default="", max_length=8_000)
    interrupted: bool = False
    # ok | fail —— 用户行=STT 结果，助手行=TTS 结果（前端 stop() 时推导）。
    status: str = Field(default="ok", max_length=16)
    durationMs: int = Field(default=0, ge=0)


class SessionRecordSave(BaseModel):
    """通话结束保存：一次通话一条记录 + 逐行消息。"""

    title: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=500)
    pipelineSessionId: str = Field(default="", max_length=128)
    instanceId: str = Field(default="", max_length=100)
    node: str = Field(default="", max_length=100)
    state: str = Field(default="done", max_length=16)
    turns: int = Field(default=0, ge=0)
    durationMs: int = Field(default=0, ge=0)
    ttfaMs: int | None = Field(default=None, ge=0)
    messages: list[SessionMessageIn] = Field(default_factory=list)


class SessionRecordUpdate(BaseModel):
    """标题/备注部分更新（exclude_unset）。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class SessionMessageUpdate(BaseModel):
    """单条消息文本编辑。"""

    content: str = Field(min_length=1, max_length=8_000)


class SessionBatchDelete(BaseModel):
    ids: list[int] = Field(min_length=1)
