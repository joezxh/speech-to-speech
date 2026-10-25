from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsoleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    param_config_dir: str = "/app/config"
    param_catalog_path: str = "/app/catalog/parameter-catalog.yaml"
    static_dir: str = "/app/console/static"
    pipeline_base_url: str = "http://127.0.0.1:8765"
    # Display-only label for the container behind `pipeline_base_url`. The console
    # never talks to docker; the label exists so the voice page can say *which*
    # pipeline it is bound to instead of showing a bare host:port.
    pipeline_container: str = "speech-to-speech-local-pipeline-1"
    pipeline_timeout_s: float = 180.0
    supervisor_socket: str = "/run/s2s-console/supervisor.sock"
    supervisor_program: str = "pipeline"
    restart_mode: str = "supervisor"
    verifier_mode: str = "reject"

    # A.14 reads the tail of this file. The pipeline chooses its own path via
    # `MODEL_METRICS_LOG` (default `model_metrics.log`, relative to /app), so the
    # console follows the same env var and defaults to the same place: one
    # container, one filesystem, no mount to configure.
    model_metrics_log: str = "/app/model_metrics.log"

    # A.15/A.16 read the four supervisor files read-only; A.17's indexer keeps
    # its cursor on the writable volume. Both live in this container, so neither
    # needs a mount — and the console still never touches the docker socket.
    log_dir: str = "/var/log/supervisor"
    data_dir: str = "/app/data"

    # Voice library (A.18). The audio never leaves this volume, and nothing here
    # is on the publish path: a voice is picked, then written as a draft value.
    voice_data_dir: str = "/app/data/voices"
    voice_max_bytes: int = 10 * 1024 * 1024
    voice_max_seconds: float = 30.0
    voice_min_seconds: float = 1.0
    voice_retention_max_days: int = 180
    voice_precompute_concurrency: int = 1
    voice_precompute_timeout_s: float = 300.0
