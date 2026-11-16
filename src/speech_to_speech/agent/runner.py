"""s2s-agent 主循环（spec 2026-11-17 §5.2/§5.3）。

纪律：任一环节失败不抛出、不阻塞语音链路——语音在 pipeline，agent 只是它的
秘书。心跳失败指数退避 1s→60s 封顶；无 token 且有注册码先注册。
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from speech_to_speech.agent import config_sync
from speech_to_speech.agent.client import AgentClient
from speech_to_speech.agent.collectors import Usage, tail_turn_latency, usage_diff
from speech_to_speech.agent.settings import AgentSettings

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 60.0

# turn-latency 断点游标（内存态；进程重启从 0 重读，重复 upsert 无害）。
_TURN_OFFSET = 0


def _load_token(settings: AgentSettings) -> str:
    path = Path(settings.token_file)
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def _save_token(settings: AgentSettings, token: str) -> None:
    """0600 落盘（§5.2 两段式第 2 步）。"""
    path = Path(settings.token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _register(client: AgentClient, settings: AgentSettings) -> str | None:
    """一次性注册码换 token；失败返回 None（下一轮再试）。"""
    if not settings.register_code:
        return None
    try:
        data = client.register(
            {
                "register_code": settings.register_code,
                "machine": {"machine_id": settings.machine_id},
                "workloads": [],
            }
        )
    except Exception as exc:  # noqa: BLE001 - 网络失败下一轮再试
        logger.warning("agent register failed: {}", exc)
        return None
    token = data["machine_token"]
    _save_token(settings, token)
    return token


def _heartbeat_body(settings: AgentSettings, usage: Usage, uptime_s: int) -> dict:
    from speech_to_speech.agent.collectors import collect_workloads  # noqa: PLC0415

    return {
        "protocol_version": 1,
        "agent_version": "1.0.0",
        "machine": {"machine_id": settings.machine_id, "uptime_s": uptime_s},
        "capabilities": ["heartbeat", "workloads", "token", "config_pull", "config_report"],
        "workloads": collect_workloads(settings),
        "runtime": {},
        "tokens": usage.__dict__,
    }


def run_forever(settings: AgentSettings | None = None) -> None:  # pragma: no cover - 常驻进程
    settings = settings or AgentSettings.from_env()
    client = AgentClient(settings.console_url)
    backoff = BACKOFF_START_S
    prev_usage: Usage | None = None

    while True:
        token = _load_token(settings) or _register(client, settings)
        if not token:
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)
            continue

        try:
            # 1) 心跳 + token 差分（console 侧 Task 14 接表前只展示）。
            from speech_to_speech.agent.collectors import read_usage  # noqa: PLC0415

            cur_usage = read_usage(settings)
            delta = usage_diff(prev_usage, cur_usage)
            prev_usage = cur_usage
            client.heartbeat(
                token, _heartbeat_body(settings, delta, int(time.monotonic()))
            )
            backoff = BACKOFF_START_S

            # 2) 配置同步（拉取/落地/回报/确认）。
            config_sync.sync_config(client, token, settings)

            # 3) turn-latency 断点续读（Task 8 接 A5 端点后上报；先只推进游标）。
            global _TURN_OFFSET  # noqa: PLW0603
            _, _ = tail_turn_latency(settings.pipeline_log, _TURN_OFFSET)
        except Exception as exc:  # noqa: BLE001 - 语音链路优先，agent 失败只退避
            logger.warning("agent tick failed: {}", exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)
            continue

        time.sleep(settings.heartbeat_s)


def main() -> None:  # pragma: no cover - 常驻进程
    settings = AgentSettings.from_env()
    if not settings.console_url or not settings.machine_id:
        logger.error(
            "s2s-agent needs S2S_AGENT_CONSOLE_URL and S2S_AGENT_MACHINE_ID; exiting"
        )
        raise SystemExit(2)
    run_forever(settings)
