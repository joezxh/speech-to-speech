"""机器命令执行器：console 下达 → 本机真动作 → 回执（不阻塞语音链路）。

只做能落到真源的动作：排空/恢复写 console 实例期望态，重启走 supervisor
XML-RPC，拉起=恢复调度+巡检，健康检查读 agent.yaml 声明的 health_path 真探测。
"""

from __future__ import annotations

import httpx
from loguru import logger

from speech_to_speech.agent import config_sync
from speech_to_speech.agent.collectors import collect_workloads

PROBE_TIMEOUT_S = 2.0


def _drain(client, token: str, drain: bool) -> tuple[bool, dict, str]:
    result = client.set_instance_drain(token, drain)
    return True, result, ""


def _reboot(settings) -> tuple[bool, dict, str]:
    config_sync.restart_pipeline(settings)
    return True, {"restarted": True}, ""


def _recover(client, token: str) -> tuple[bool, dict, str]:
    drained = client.set_instance_drain(token, False)
    probed = client.probe_instances(token)
    return True, {**drained, **probed}, ""


def _service_matches(workload: dict, service_id: str) -> bool:
    kind = str(workload.get("kind") or "")
    port = workload.get("port")
    keys = {kind, f"{kind}:{port}"} if port is not None else {kind}
    return service_id in keys


def _health_check(settings, service_id: str) -> tuple[bool, dict, str]:
    if not service_id:
        return False, {"reachable": None, "reason": "service_id_missing"}, "service id missing"
    workload = next(
        (w for w in collect_workloads(settings) if _service_matches(w, service_id)), None
    )
    if workload is None:
        return False, {"reachable": None, "reason": "service_not_found"}, "service not found"
    path = str(workload.get("health_path") or "")
    address = str(workload.get("listen") or workload.get("public_addr") or "")
    if not path or not address:
        return False, {"reachable": None, "reason": "no_probe_target"}, "no health path or address"
    response = httpx.get(f"http://{address.rstrip('/')}{path}", timeout=PROBE_TIMEOUT_S)
    reachable = response.status_code < 400
    return (
        reachable,
        {
            "reachable": reachable,
            "status_code": response.status_code,
            "url": f"http://{address.rstrip('/')}{path}",
        },
        "" if reachable else f"http {response.status_code}",
    )


def execute(command: dict, settings, client, token: str) -> tuple[bool, dict, str]:
    """返回 (ok, result, error)；未知类型按失败回执，绝不静默成功。"""
    kind = str(command.get("kind") or "")
    payload = command.get("payload") or {}
    if kind == "drain":
        return _drain(client, token, True)
    if kind == "resume":
        return _drain(client, token, False)
    if kind == "reboot":
        return _reboot(settings)
    if kind == "recover":
        return _recover(client, token)
    if kind == "health_check":
        return _health_check(settings, str(payload.get("service_id") or ""))
    return False, {"reason": "unsupported_kind"}, f"unsupported command kind: {kind}"


def poll_and_run(client, token: str, settings, *, limit: int = 10) -> int:
    """每 tick 的独立步骤：任何单条命令失败都照常回执，绝不影响主循环。"""
    commands = client.pull_commands(token, limit=limit)
    for command in commands:
        command_id = str(command.get("command_id") or "")
        try:
            ok, result, error = execute(command, settings, client, token)
        except Exception as exc:  # noqa: BLE001 - 命令失败要回执给 console，不是吞掉
            ok, result, error = False, {}, f"{type(exc).__name__}: {exc}"
            logger.warning("machine command {} failed: {}", command_id, exc)
        client.report_command(
            token, command_id, ok=ok, result=result, error=error[:512]
        )
    return len(commands)
