"""agent 注册与心跳（A0/A1，spec 2026-11-17 §5.2/§5.4）。

- 注册：一次性注册码换正式 machine token；码与 token 都只存 sha256，码用过即焚。
- 心跳：按 token 映射 machine_id；body 的 machine_id 只做一致性校验，不符 403。
- token 差分：暂存内存（Task 14 接 param_token_metric）。
- capabilities 缺项 → caps 交集（面板据此降级，§5.3.7）。
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories.token_metric_repository import TokenDelta, append_delta
from app.db.base import utcnow
from app.models.machine import ParamMachine
from app.repositories.machine_repository import MachineRepository
from app.schemas.agent import HeartbeatIn
from app.schemas.common import iso_utc
from app.services.machine_service import hash_secret

SUPPORTED_PROTOCOL_VERSION = 1
SUPPORTED_CAPS = ("heartbeat", "workloads", "token", "config_pull", "config_report", "commands")
HEARTBEAT_AFTER_S = 15

# token 窗口增量的暂存处（键 = machine_id）。console 重启即失——Task 14 接表后废弃。
_TOKEN_DIFFS: dict[str, dict] = {}


def caps_for(capabilities: list[str]) -> list[str]:
    """机器上报能力与协议支持能力的交集，保持协议声明顺序。"""
    return [cap for cap in SUPPORTED_CAPS if cap in capabilities]


def _host_port_of_public_addr(public_addr: str) -> tuple[str, int] | None:
    """`host:port` → (host, port)；缺端口或解析失败 → None。"""
    text = public_addr.strip()
    if not text or "://" in text:
        return None
    host, _sep, port_text = text.rpartition(":")
    if not host or not port_text.isdigit():
        return None
    return host.strip("[]"), int(port_text)


def _host_port_of_base_url(base_url: str) -> tuple[str, int] | None:
    from urllib.parse import urlparse  # noqa: PLC0415

    try:
        parsed = urlparse(base_url)
    except ValueError:
        return None
    if not parsed.hostname or parsed.port is None:
        return None
    return parsed.hostname, parsed.port


def bind_instances_by_public_addr(db, machine_id: str, workloads) -> int:
    """心跳回填绑定（§7.1）：public_addr 的 host:port 反查 param_instance.base_url。

    不按 listen 匹配（容器内地址与 console 侧 base_url 不可比）；未命中的
    实例保持 machine_id=NULL，由 machines 页手工绑定。返回绑定实例数。
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.param_instance import ParamInstance  # noqa: PLC0415

    wanted = {
        pair
        for item in workloads
        if (pair := _host_port_of_public_addr(item.public_addr)) is not None
    }
    if not wanted:
        return 0
    bound = 0
    for row in db.scalars(
        select(ParamInstance).where(ParamInstance.machine_id.is_(None))
    ).all():
        location = _host_port_of_base_url(row.base_url)
        if location is not None and location in wanted:
            row.machine_id = machine_id
            bound += 1
    if bound:
        db.commit()
    return bound


def get_token_diff(machine_id: str) -> dict:
    return dict(_TOKEN_DIFFS.get(machine_id, {}))


def authenticate(db: Session, authorization_header: str) -> str:
    """Bearer machine token → machine_id；缺失/未知 → 401。"""
    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        raise ApiError("unauthorized", "machine token required", 401)
    row = db.scalar(select(ParamMachine).where(ParamMachine.token_hash == hash_secret(token)))
    if row is None:
        raise ApiError("unauthorized", "unknown machine token", 401)
    return row.machine_id


def register(db: Session, body) -> dict:
    """一次性注册码 → machine token；绑档（或按注册码找到预建档）。"""
    row = db.scalar(
        select(ParamMachine).where(ParamMachine.register_code_hash == hash_secret(body.register_code))
    )
    if row is None:
        raise ApiError("unauthorized", "invalid or used register code", 401)

    machine_token = secrets.token_urlsafe(24)
    row.token_hash = hash_secret(machine_token)
    row.register_code_hash = None  # 用过即焚
    # agent 自报身份绑档（纯负载机的建档路径也走这里——M9 已预建档）。
    row.addr = body.machine.addr or row.addr
    row.gpu = body.machine.gpu or row.gpu
    row.gpu_total_gb = body.machine.gpu_total_gb or row.gpu_total_gb
    row.role = body.machine.role or row.role
    db.commit()
    return {
        "machine_token": machine_token,
        "machine_id": row.machine_id,
        "heartbeat_after_s": HEARTBEAT_AFTER_S,
    }


def heartbeat(db: Session, token_machine_id: str, body: HeartbeatIn) -> dict:
    """心跳：身份一致性校验 → 刷新机器行 → 全量覆盖负载清单 → 暂存 token 差分。"""
    if body.protocol_version > SUPPORTED_PROTOCOL_VERSION:
        raise ApiError(
            "invalid_request",
            f"protocol_version {body.protocol_version} not supported (max {SUPPORTED_PROTOCOL_VERSION})",
            400,
        )
    if body.machine.machine_id != token_machine_id:
        raise ApiError("forbidden", "machine_id does not match token", 403)
    row = MachineRepository(db).get(token_machine_id)
    if row is None:
        raise ApiError("unauthorized", "machine no longer registered", 401)

    row.addr = body.machine.addr or row.addr
    row.gpu = body.machine.gpu or row.gpu
    row.gpu_total_gb = body.machine.gpu_total_gb or row.gpu_total_gb
    row.role = body.machine.role or row.role
    row.agent_version = body.agent_version
    row.protocol_version = body.protocol_version
    row.agent_caps = list(body.capabilities)
    row.last_seen_at = utcnow()
    # 首次心跳 = 注册成功落地（§7.1 状态表）；warn/bad/draining 由 monitor 后续覆盖。
    if row.state == "pending_register":
        row.state = "ok"
    row.updated_at = row.last_seen_at
    db.commit()

    MachineRepository(db).replace_workloads(
        token_machine_id,
        [
            {
                "kind": item.kind,
                "engine": item.engine,
                "model": item.model,
                "port": item.port,
                "listen_addr": item.listen,
                "public_addr": item.public_addr,
                "vram_gb": item.vram_gb,
                "health_path": item.health_path,
                "health_interval_s": item.health_interval_s,
                "note": item.note,
                "params_json": item.params,
            }
            for item in body.workloads
        ],
    )
    bind_instances_by_public_addr(db, token_machine_id, body.workloads)
    _TOKEN_DIFFS[token_machine_id] = dict(body.tokens)
    # Task 13：tokens{} 落库（单通道真值；instance_probe 的 /v1/usage 轮询不落库）。
    if body.tokens:
        append_delta(
            db,
            token_machine_id,
            TokenDelta(
                input_tokens=int(body.tokens.get("input_tokens") or 0),
                output_tokens=int(body.tokens.get("output_tokens") or 0),
                responses=int(body.tokens.get("responses") or 0),
                audio_duration_s=(
                    float(body.tokens["audio_duration_s"])
                    if body.tokens.get("audio_duration_s") is not None
                    else None
                ),
                window_s=int(body.tokens.get("window_s") or 0),
            ),
        )

    return {
        "accepted": True,
        "machine_id": token_machine_id,
        "server_time": iso_utc(row.last_seen_at),
        "config_version": 0,  # Task 7 接 agent_config_service
        "config_etag": "",
        "poll_after_s": HEARTBEAT_AFTER_S,
        "caps": caps_for(body.capabilities),
    }
