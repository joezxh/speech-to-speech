from __future__ import annotations

import socket
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AllocatorSettings(BaseSettings):
    """实例注册/巡检/本地分配的全部开关（spec §12）。每一项都有默认值，
    默认组合（mode=off + 空 seed）= 本期之前的行为完全不变。

    字段名是代码内的短名，env 名一律走 `validation_alias` 对齐 spec §12 的
    `ALLOCATOR_*` / `INSTANCE_*` / `CONSOLE_ID` / `INSTANCES_SEED_PATH`——前缀不
    统一，所以没法用 `env_prefix`，也不能靠"字段名大写"这条默认规则。
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

    mode: Literal["off", "local"] = Field(default="off", validation_alias="ALLOCATOR_MODE")
    # 指标 observed_by：多 console 无共享多活时区分采样来源（spec §5.2）。
    console_id: str = Field(default="", validation_alias="CONSOLE_ID")
    # 空则跳过 seed，DB 为唯一来源（spec §7）。
    seed_path: str = Field(default="", validation_alias="INSTANCES_SEED_PATH")
    probe_interval_s: int = Field(default=5, validation_alias="INSTANCE_PROBE_INTERVAL_S")
    probe_timeout_s: int = Field(default=2, validation_alias="INSTANCE_PROBE_TIMEOUT_S")
    fail_threshold: int = Field(default=3, validation_alias="INSTANCE_FAIL_THRESHOLD")
    recover_threshold: int = Field(default=2, validation_alias="INSTANCE_RECOVER_THRESHOLD")
    grant_ttl_s: int = Field(default=60, validation_alias="INSTANCE_GRANT_TTL_S")
    usage_interval_s: int = Field(default=30, validation_alias="INSTANCE_USAGE_INTERVAL_S")
    metric_retention_days: int = Field(default=7, validation_alias="INSTANCE_METRIC_RETENTION_DAYS")
    # 本地队列本期关闭：满则 503 at_capacity（spec §3）。
    queue_enabled: bool = Field(default=False, validation_alias="INSTANCE_QUEUE_ENABLED")
    webrtc_hangup_enabled: bool = Field(default=False, validation_alias="INSTANCE_WEBRTC_HANGUP_ENABLED")

    @property
    def resolved_console_id(self) -> str:
        return self.console_id.strip() or socket.gethostname()
