from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsoleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    param_config_dir: str = "/app/config"
    param_catalog_path: str = "/app/catalog/parameter-catalog.yaml"
    static_dir: str = "/app/console/static"
    pipeline_base_url: str = "http://127.0.0.1:8765"
    pipeline_timeout_s: float = 180.0
    supervisor_socket: str = "/run/s2s-console/supervisor.sock"
    supervisor_program: str = "pipeline"
    restart_mode: str = "supervisor"
    verifier_mode: str = "reject"
