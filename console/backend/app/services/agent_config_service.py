"""agent 目标配置渲染与版本内核（A2 的后端，spec 2026-11-17 §7.2.3）。

复用 renderer_service.render_yaml 与 publish_flow_service 的 profile/目录加载，
不新写渲染器。落地载体是 `param_agent_config_version`（0010 迁移并入的表，
主键 (machine_id, config_version)，按机保留最近 N=5 版由调用方环形覆盖）。

profile 回落顺序（§7.2.3 D1）：机器 profile → 集群 baseline_profile → prod。
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.base import utcnow
from app.models.machine import ParamMachine
from app.models.machine_config import ParamAgentConfigVersion, ParamMachineDraft
from app.models.param_cluster import ParamCluster
from app.repositories.machine_config_repository import MachineConfigRepository
from app.repositories.machine_repository import MachineRepository
from app.schemas.common import iso_utc
from app.services import layout_service as layout
from app.services import publish_flow_service, renderer_service

DEFAULT_PROFILE = "prod"
# 快照环形保留版数（Task 6 的 A4 ack 也写这张表；超出即删最旧）。
RETAINED_VERSIONS = 5

# 密钥类键不下发（11-17 设计 §5.2 的密钥边界；param_config 登记表不含密钥，
# 这里兜底过滤机器级 values 里形似凭据的键）。
_SECRET_PATTERN = re.compile(r"(secret|token|password|passwd|api[_-]?key)", re.IGNORECASE)


def secret_keys_filtered(values: dict) -> dict:
    return {key: value for key, value in values.items() if not _SECRET_PATTERN.search(key)}


def _etag(text: str) -> str:
    """内容寻址：版本号递增但内容不变时 etag 保持稳定（If-None-Match 才能命中 304）。"""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f'W/"cfg-{digest}"'


def _baseline_profile(db: Session, cluster_id: str) -> str:
    if cluster_id:
        row = db.scalar(select(ParamCluster).where(ParamCluster.name == cluster_id))
        if row is not None and row.baseline_profile:
            return row.baseline_profile
    return DEFAULT_PROFILE


def _resolve_profile(db: Session, machine: ParamMachine) -> str:
    return machine.profile or _baseline_profile(db, machine.cluster_id)


def _machine_row(db: Session, machine_id: str) -> ParamMachine:
    row = MachineRepository(db).get(machine_id)
    if row is None:
        raise KeyError(machine_id)
    return row


def _coerce_draft(value: str, entry) -> object:
    """draft 列按字符串存；渲染前按目录 entry.type 转回原生类型。

    转型失败时保留原字符串——错误的值交给 refused/校验去拒绝，不静默吞掉。
    """
    if entry is None or not isinstance(value, str):
        return value
    kind = entry.type
    try:
        if kind in ("int", "integer"):
            return int(value)
        if kind in ("float", "number"):
            return float(value)
    except ValueError:
        return value
    if kind in ("bool", "boolean"):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value


def peek_version(db: Session, machine_id: str) -> int:
    """当前最大下发版本；从未渲染过 → 0。"""
    current = db.scalar(
        select(func.max(ParamAgentConfigVersion.config_version)).where(
            ParamAgentConfigVersion.machine_id == machine_id
        )
    )
    return int(current or 0)


def render_target(db: Session, machine_id: str) -> tuple[int, str, str]:
    """渲染机器目标配置并落版本快照；返回 (config_version, etag, yaml_text)。"""
    machine = _machine_row(db, machine_id)
    profile = _resolve_profile(db, machine)

    path = publish_flow_service.require_profile(profile)
    known = publish_flow_service.entries()
    base = renderer_service.load_base(path)
    # live = profile 文件现状；机器级草稿按键覆盖（draft 为空 = 纯 live 渲染）。
    draft_rows = db.scalars(
        select(ParamMachineDraft).where(ParamMachineDraft.machine_id == machine_id)
    ).all()
    patches = {
        row.param_key: _coerce_draft(row.value, known.get(row.param_key))
        for row in draft_rows
    }

    text, _applied, refused = renderer_service.render_yaml(base, profile, patches, known)
    if refused:
        raise ApiError(
            "invalid_parameter",
            "some machine draft keys have no place in this profile's YAML",
            400,
            detail=refused,
        )

    version = peek_version(db, machine_id) + 1
    db.add(
        ParamAgentConfigVersion(
            machine_id=machine_id,
            config_version=version,
            yaml_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            yaml_text=text,
        )
    )
    _prune_old_versions(db, machine_id)
    db.commit()
    return version, _etag(text), text


def _prune_old_versions(db: Session, machine_id: str) -> None:
    """按机保留最近 RETAINED_VERSIONS 版（环形覆盖）。"""
    rows = db.scalars(
        select(ParamAgentConfigVersion)
        .where(ParamAgentConfigVersion.machine_id == machine_id)
        .order_by(ParamAgentConfigVersion.config_version.desc())
        .offset(RETAINED_VERSIONS)
    ).all()
    for stale in rows:
        db.delete(stale)


# ---- A2：拉取（If-None-Match → 304） --------------------------------------


def latest_snapshot(db: Session, machine_id: str) -> ParamAgentConfigVersion | None:
    return db.scalar(
        select(ParamAgentConfigVersion)
        .where(ParamAgentConfigVersion.machine_id == machine_id)
        .order_by(ParamAgentConfigVersion.config_version.desc())
    )


def pull(db: Session, machine_id: str, if_none_match: str) -> tuple[dict | None, int, str]:
    """返回 (data, status, etag)。命中当前 etag → (None, 304, 当前 etag)，不渲染不递增。

    版本号只在内容变化时递增：agent 每轮都带 If-None-Match，未变更的轮询
    不会把快照环形滚掉。
    """
    snapshot = latest_snapshot(db, machine_id)
    if snapshot is not None and if_none_match:
        current = _etag(snapshot.yaml_text)
        if if_none_match.strip() == current:
            return None, 304, current
    version, etag, text = render_target(db, machine_id)
    fresh = latest_snapshot(db, machine_id)
    rendered_at = iso_utc(fresh.rendered_at) if fresh is not None else ""
    data = {
        "config_version": version,
        "etag": etag,
        "yaml_text": text,
        "rendered_at": rendered_at,
    }
    return data, 200, etag


# ---- A3：回报（漂移源） ----------------------------------------------------


def _expected_values(db: Session, machine: ParamMachine, keys: list[str]) -> dict:
    """live 期望值：profile 文件现状中各键当前所在位置的值。"""
    profile = _resolve_profile(db, machine)
    path = publish_flow_service.require_profile(profile)
    base = renderer_service.load_base(path)
    known = publish_flow_service.entries()
    expected: dict[str, object] = {}
    for key in keys:
        entry = known.get(key)
        if entry is None:
            continue
        located, _reason = layout.locate(base, profile, entry)
        if located is None:
            continue
        node: object = base
        try:
            for part in located:
                node = node[part]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            continue
        expected[key] = node
    return expected


def _values_equal(expected: object, actual: object) -> bool:
    try:
        return float(expected) == float(actual)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass
    lhs, rhs = str(expected).strip().lower(), str(actual).strip().lower()
    if lhs in ("true", "false") or rhs in ("true", "false"):
        return lhs == rhs
    return lhs == rhs


def report_values(db: Session, machine_id: str, config_version: int, values: dict) -> dict:
    """A3：values 逐键 upsert 进 param_machine_config，返回 {accepted, drift_count}。"""
    machine = _machine_row(db, machine_id)
    filtered = secret_keys_filtered(values)
    expected = _expected_values(db, machine, list(filtered))
    drift_count = sum(
        1 for key, value in filtered.items() if key in expected and not _values_equal(expected[key], value)
    )
    MachineConfigRepository(db).upsert_report(machine_id, filtered, config_version)
    return {"accepted": True, "drift_count": drift_count}


# ---- A4：确认（ack） -------------------------------------------------------


def ack(db: Session, machine_id: str, config_version: int, ok: bool, error: str | None) -> dict:
    """A4：ok=false 的版本不留快照（从环形中剔除）；ok=true 的保留。

    快照本身在 render_target 时已落行——ack 只决定它去留。
    """
    if not ok:
        stale = db.get(ParamAgentConfigVersion, (machine_id, config_version))
        if stale is not None:
            db.delete(stale)
            db.commit()
    return {"accepted": True}
