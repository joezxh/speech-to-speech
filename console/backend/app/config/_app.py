from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Process-wide settings. One env file, one container (spec §13.5)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    log_level: str = "info"
    cors_origins: str = ""
    max_body_bytes: int = 2 * 1024 * 1024


settings = AppSettings()
