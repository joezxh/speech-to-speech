"""s2s-agent 主循环（spec 2026-11-17 §5.2/§5.3）。

纪律：任一环节失败不抛出、不阻塞语音链路——语音在 pipeline，agent 只是它的
秘书。心跳失败指数退避 1s→60s 封顶；无 token 且有注册码先注册。

实现说明：真正的循环体在 :mod:`speech_to_speech.agent.embedded` 的
``EmbeddedAgent`` 里——独立进程形态与内嵌形态（``serve --with-agent``）
共用同一份实现，因此这里只是一层薄包装。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from speech_to_speech.agent.embedded import EmbeddedAgent
from speech_to_speech.agent.settings import AgentSettings

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 60.0


def run_forever(settings: AgentSettings | None = None) -> None:  # pragma: no cover - 常驻进程
    """独立进程形态的常驻循环。

    ``embedded=False``：此时 pipeline 在别的进程里，重启类命令（reboot /
    config_restart）仍然可用。
    """

    settings = settings or AgentSettings.from_env()
    agent = EmbeddedAgent(settings, embedded=False)
    agent.run()


def main() -> None:  # pragma: no cover - 常驻进程
    settings = AgentSettings.from_env()
    if not settings.console_url or not settings.machine_id:
        logger.error(
            "s2s-agent needs S2S_AGENT_CONSOLE_URL and S2S_AGENT_MACHINE_ID; exiting"
        )
        raise SystemExit(2)
    run_forever(settings)


def __getattr__(name: str) -> Any:
    """兼容旧入口：``runner._load_token`` 等私有函数已迁到 EmbeddedAgent。"""

    if name in {"load_token", "save_token", "_register", "_heartbeat_body"}:
        return getattr(EmbeddedAgent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["BACKOFF_MAX_S", "BACKOFF_START_S", "main", "run_forever"]
