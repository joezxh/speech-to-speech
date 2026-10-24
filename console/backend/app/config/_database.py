from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////app/data/console.sqlite3"
    usage_db_path: str = "/app/data/usage.sqlite3"

    @field_validator("database_url")
    @classmethod
    def _absolute_sqlite(cls, value: str) -> str:
        # sqlite:///./dev.db is relative to CWD; sqlite:////app/... is absolute.
        return value
