from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsoleSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

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

    # Session archive (spec 2026-10-26 session-archive). `session_record_enabled`
    # is the server-side gate: false means every write answers 403
    # `recording_disabled` no matter what the browser checkbox says. Off by
    # default, so an unconfigured deployment records nothing.
    session_record_enabled: bool = False
    # Same class as `data_dir`: the /app default resolves to <cwd drive>:\app on
    # Windows, so a local checkout has to set an absolute path.
    session_data_dir: str = "/app/data/sessions"
    # The page's retention copy and the sweep both read these, so neither number
    # is a constant baked into the bundle. The max is the ceiling an operator
    # cannot exceed; the two audio limits are what the API enforces with a 413.
    session_retention_days: int = 30
    session_retention_max_days: int = 180
    session_audio_max_bytes: int = 10 * 1024 * 1024
    session_audio_max_seconds: float = 120.0

    # ── S2S 数据面负载均衡（spec 2026-11-16）────────────────────────────
    # off   = 现状：console 不代理 S2S 端点，浏览器仍直连 8765。
    # proxy = console 成为唯一数据面入口：/v1/realtime 与 /v1/audio/* 由
    #         console 按注册表选台后转发，8765 收敛为容器内/内网端口。
    # 默认 off，保证不配置时行为与改造前逐字一致。
    lb_mode: Literal["off", "proxy"] = Field(default="off", validation_alias="CONSOLE_LB_MODE")
    # 上游满员或拒连时换到另一台实例的次数（不含首次尝试）。
    lb_failover_attempts: int = 2
    # 等上游第一帧（session.created）的上限：超时就换台。
    lb_upstream_ready_timeout_s: float = 5.0
    # 分端点的上游超时。不用 pipeline_timeout_s：那个是给 /v1/pool 探针的 180s。
    lb_asr_timeout_s: float = 120.0
    lb_tts_timeout_s: float = 120.0
    lb_voiceprint_timeout_s: float = 30.0
    lb_emotion_timeout_s: float = 30.0
    # 音频上传上限：11 MiB = 声纹 10 MiB + 1 MiB multipart 余量。
    lb_audio_max_bytes: int = 11 * 1024 * 1024
    # 能力指纹的探测轮间隔（与容量巡检分开一轮，避免拖慢容量巡检）。
    lb_capability_interval_s: int = 30
    # 单实例能力探测超时。必须大于 SER_TIMEOUT_MS/1000（5s）：情感的 /health
    # 是同步转发 SER 的，探针比它还短就会把"慢"误判成"没有这个能力"。
    lb_capability_probe_timeout_s: float = 6.0
    # 单实例无状态请求（ASR/TTS/声纹/情感）的在途上限，0 = 不限。
    lb_stateless_max_inflight: int = 0
