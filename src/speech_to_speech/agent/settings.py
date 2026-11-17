"""agent 进程设置：全部走 env（§5.2；本机声明文件 agent.yaml 由 collectors 读取）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HEARTBEAT_DEFAULT_S = 15
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _local_config(name: str, default: str = "") -> str:
    path = _REPO_ROOT / "config" / name
    return str(path) if path.is_file() else default


@dataclass
class AgentSettings:
    console_url: str
    register_code: str
    token_file: str
    machine_id: str
    heartbeat_s: int = HEARTBEAT_DEFAULT_S
    # 本机 pipeline 日志与目标配置的落点（pipeline-node 形态；workload-node 无日志）。
    pipeline_log: str = "/var/log/supervisor/pipeline-stdout.log"
    target_yaml: str = ""
    # supervisor 的 unix socket（start 类参数重启 pipeline 用）。
    supervisor_socket: str = "/run/s2s-console/supervisor.sock"
    supervisor_program: str = "pipeline"
    # 本机声明文件：负载清单与 effects 映射的来源（§5.3.3）。
    declaration_file: str = "/app/config/agent.yaml"
    # 构建期生成的 compose 声明清单（容器内读不到 compose 文件本身）。
    deployment_manifest: str = "/app/config/deployment-manifest.json"
    container_log_max_lines: int = 500

    @classmethod
    def from_env(cls) -> "AgentSettings":
        return cls(
            console_url=os.environ.get("S2S_AGENT_CONSOLE_URL", "").rstrip("/"),
            register_code=os.environ.get("S2S_AGENT_REGISTER_CODE", ""),
            token_file=os.environ.get("S2S_AGENT_TOKEN_FILE", "/run/s2s-agent/token"),
            machine_id=os.environ.get("S2S_AGENT_MACHINE_ID", ""),
            heartbeat_s=int(os.environ.get("S2S_AGENT_HEARTBEAT_S", str(HEARTBEAT_DEFAULT_S))),
            pipeline_log=os.environ.get("S2S_AGENT_PIPELINE_LOG", cls.pipeline_log),
            target_yaml=os.environ.get("S2S_AGENT_TARGET_YAML") or _local_config("prod.yaml"),
            supervisor_socket=os.environ.get(
                "S2S_AGENT_SUPERVISOR_SOCKET", cls.supervisor_socket
            ),
            supervisor_program=os.environ.get("S2S_AGENT_SUPERVISOR_PROGRAM", "pipeline"),
            declaration_file=os.environ.get("S2S_AGENT_DECLARATION") or (
                str(_REPO_ROOT / ".run" / "agent.yaml")
                if (_REPO_ROOT / ".run" / "agent.yaml").is_file()
                else cls.declaration_file
            ),
            deployment_manifest=os.environ.get("S2S_AGENT_DEPLOYMENT_MANIFEST")
            or _local_config("deployment-manifest.json", cls.deployment_manifest),
            container_log_max_lines=int(
                os.environ.get(
                    "S2S_AGENT_LOG_MAX_LINES", str(cls.container_log_max_lines)
                )
            ),
        )
