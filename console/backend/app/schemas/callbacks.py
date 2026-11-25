"""回调配置的请求/响应契约（spec 2026-11-25 §8.4）。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

EVENT_TYPES = ("transcript", "segment_attributed", "session_end")
TARGET_TYPES = ("java", "python")
AUTH_TYPES = ("none", "bearer", "header_token")


class CallbackTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    targetType: str
    baseUrl: str = Field(min_length=1, max_length=512)
    authType: str = "none"
    authHeaderName: str | None = None
    authToken: str = ""
    extraHeaders: dict[str, str] = Field(default_factory=dict)
    timeoutMs: int = Field(default=3000, ge=100, le=60000)
    retryMaxAttempts: int = Field(default=3, ge=1, le=10)
    retryBackoffMs: int = Field(default=500, ge=0, le=60000)
    events: list[str] = Field(default_factory=lambda: ["transcript"])
    filters: dict | None = None
    enabled: bool = True

    @field_validator("targetType")
    @classmethod
    def _check_type(cls, value: str) -> str:
        if value not in TARGET_TYPES:
            raise ValueError(f"targetType must be one of {'|'.join(TARGET_TYPES)}")
        return value

    @field_validator("authType")
    @classmethod
    def _check_auth(cls, value: str) -> str:
        if value not in AUTH_TYPES:
            raise ValueError(f"authType must be one of {'|'.join(AUTH_TYPES)}")
        return value

    @field_validator("events")
    @classmethod
    def _check_events(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("events 不能为空")
        unknown = [e for e in value if e not in EVENT_TYPES]
        if unknown:
            raise ValueError(f"未知事件类型: {unknown}")
        return value

    @field_validator("filters")
    @classmethod
    def _check_filters(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        allowed = {"speakers", "min_text_len"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"filters 仅支持 {sorted(allowed)}")
        return value


class CallbackTargetUpdate(CallbackTargetCreate):
    pass


class CallbackTargetOut(BaseModel):
    id: int
    name: str
    targetType: str
    baseUrl: str
    authType: str
    authHeaderName: str | None
    authToken: str  # service 层保证脱敏
    extraHeaders: dict[str, str]
    timeoutMs: int
    retryMaxAttempts: int
    retryBackoffMs: int
    events: list[str]
    filters: dict | None
    enabled: bool
    updatedAt: str | None = None


class CallbackBatchRequest(BaseModel):
    ids: list[int] = Field(min_length=1)
    action: str  # enable | disable | delete


class TestDeliveryResult(BaseModel):
    ok: bool
    httpStatus: int | None = None
    durationMs: int = 0
    error: str = ""


class DeliveryLogOut(BaseModel):
    id: int
    targetId: int | None
    eventType: str
    triggeredAt: str | None
    requestUrl: str
    requestPayload: str
    attempt: int
    httpStatus: int | None
    responseSnippet: str
    durationMs: int
    status: str
    error: str
