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


def _config_restart(settings, client, token: str) -> tuple[bool, dict, str]:
    """先落地配置再重启；任一步失败都带阶段名回执，不假装成功。"""
    try:
        config = config_sync.sync_config(client, token, settings)
    except Exception as exc:  # noqa: BLE001 - 失败阶段必须显式回执
        return False, {"stage": "config"}, f"config stage failed: {type(exc).__name__}: {exc}"
    try:
        config_sync.restart_pipeline(settings)
    except Exception as exc:  # noqa: BLE001
        return False, {"stage": "restart", "config": config}, f"restart stage failed: {type(exc).__name__}: {exc}"
    return True, {"config": config, "restart": {"restarted": True}}, ""


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


def execute(
    command: dict,
    settings,
    client,
    token: str,
    *,
    allow_restart: bool = True,
) -> tuple[bool, dict, str]:
    """返回 (ok, result, error)；未知类型按失败回执，绝不静默成功。

    ``allow_restart=False`` 用于内嵌形态：此时 pipeline 就是当前进程，
    从进程内部通过 supervisor 重启自己不可行，重启类命令一律明确失败。
    """
    kind = str(command.get("kind") or "")
    payload = command.get("payload") or {}
    if kind == "drain":
        return _drain(client, token, True)
    if kind == "resume":
        return _drain(client, token, False)
    if kind == "reboot":
        if not allow_restart:
            return False, {"reason": "not_supported_in_embedded_mode"}, (
                "restarting the pipeline is not supported while the agent runs "
                "inside the pipeline process"
            )
        return _reboot(settings)
    if kind == "config_restart":
        if not allow_restart:
            return False, {"reason": "not_supported_in_embedded_mode"}, (
                "restarting the pipeline is not supported while the agent runs "
                "inside the pipeline process"
            )
        return _config_restart(settings, client, token)
    if kind == "recover":
        return _recover(client, token)
    if kind == "health_check":
        return _health_check(settings, str(payload.get("service_id") or ""))
    return False, {"reason": "unsupported_kind"}, f"unsupported command kind: {kind}"


def execute_command(
    command: dict,
    settings,
    client,
    token: str,
    allow_restart: bool = True,
) -> tuple[bool, dict, str]:
    """Call :func:`execute` with the restart switch only when it matters.

    The default path keeps the historical four-argument call shape, so an
    existing override of ``execute`` (a stub, a wrapper) keeps working.
    """

    if allow_restart:
        return execute(command, settings, client, token)
    return execute(command, settings, client, token, allow_restart=False)


def poll_and_run_detailed(
    client,
    token: str,
    settings,
    *,
    limit: int = 10,
    allow_restart: bool = True,
) -> list[dict]:
    """每 tick 的独立步骤：任何单条命令失败都照常回执，绝不影响主循环。

    返回逐条回执，供控制接口展示；:func:`poll_and_run` 只关心条数。
    """
    commands = client.pull_commands(token, limit=limit)
    receipts: list[dict] = []
    for command in commands:
        command_id = str(command.get("command_id") or "")
        try:
            ok, result, error = execute_command(command, settings, client, token, allow_restart)
        except Exception as exc:  # noqa: BLE001 - 命令失败要回执给 console，不是吞掉
            ok, result, error = False, {}, f"{type(exc).__name__}: {exc}"
            logger.warning("machine command {} failed: {}", command_id, exc)
        client.report_command(
            token, command_id, ok=ok, result=result, error=error[:512]
        )
        receipts.append(
            {
                "command_id": command_id,
                "kind": str(command.get("kind") or ""),
                "ok": ok,
                "result": result,
                "error": error,
            }
        )
    return receipts


def poll_and_run(
    client,
    token: str,
    settings,
    *,
    limit: int = 10,
    allow_restart: bool = True,
) -> int:
    """拉取并执行本机待办命令，返回执行条数。"""
    return len(
        poll_and_run_detailed(
            client, token, settings, limit=limit, allow_restart=allow_restart
        )
    )
