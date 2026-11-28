from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolSettings(BaseSettings):
    """工具 provider 的密钥与边界配置。密钥只走 env，永不进浏览器。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anspire_api_key: str = ""
    bocha_api_key: str = ""
    you_api_key: str = ""
    tavily_api_key: str = ""
    openweather_api_key: str = ""
    kb_docs_dir: str = ""
    http_allow_private: bool = False

    @property
    def docs_path(self) -> Path:
        if self.kb_docs_dir.strip():
            return Path(self.kb_docs_dir).resolve()
        return Path(__file__).resolve().parents[4] / "docs"
