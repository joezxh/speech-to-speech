"""机器参数面 D1/D2（Task 20，spec 2026-11-17 §7.2.4）。

期望值唯一真源 = profile live 渲染值；未覆盖回落 catalog 默认；未回报的键
actual=None、drift=False（"未知"不是漂移，Review Focus #5）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.base import utcnow
from app.models.param_audit import ParamAudit

from app.models.machine_config import ParamMachineConfig, ParamMachineDraft
from app.repositories.machine_repository import MachineRepository
from app.services import agent_config_service, layout_service as layout
from app.services import publish_flow_service, renderer_service

SOURCE_PROFILE = "profile"
SOURCE_DEFAULT = "期望默认"


def _catalog_entry(key: str):
    return publish_flow_service.entries().get(key)


def _machine_profile(db: Session, machine_id: str) -> str:
    machine = MachineRepository(db).get(machine_id)
    if machine is None:
        raise KeyError(machine_id)
    return machine.profile or "prod"


def _locate_live(profile: str, key: str) -> str | None:
    entry = _catalog_entry(key)
    if entry is None:
        return None
    base = renderer_service.load_base(publish_flow_service.require_profile(profile))
    located, _reason = layout.locate(base, profile, entry)
    if located is None:
        return None
    node: object = base
    try:
        for part in located:
            node = node[part]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None
    return str(node)


def expected_value(db: Session, machine_id: str, key: str) -> tuple[str | None, str]:
    """(期望值, 基线来源)：profile live 渲染值优先，回落 catalog 默认。"""
    entry = _catalog_entry(key)
    profile = _machine_profile(db, machine_id)
    live = _locate_live(profile, key)
    if live is not None:
        return live, SOURCE_PROFILE
    default = entry.default if entry is not None else None
    return (None if default is None else str(default)), SOURCE_DEFAULT


def config_view(db: Session, machine_id: str) -> list[dict]:
    """每目录行：expected/actual/drift/source/effect/exposure/risk/anchor。"""
    reported = {
        row.param_key: row.actual_value
        for row in db.scalars(
            select(ParamMachineConfig).where(ParamMachineConfig.machine_id == machine_id)
        ).all()
    }
    rows: list[dict] = []
    for entry in publish_flow_service.entries().values():
        expected, source = expected_value(db, machine_id, entry.key)
        actual = reported.get(entry.key)
        rows.append(
            {
                "key": entry.key,
                "expected": expected,
                "actual": actual,
                "drift": actual is not None and str(actual) != str(expected),
                "source": source,
                "effect": entry.effect,
                "exposure": entry.exposure,
                "risk": entry.risk,
                "anchor": entry.anchor,
            }
        )
    return sorted(rows, key=lambda row: row["key"])


def drift(db: Session, machine_id: str) -> dict:
    rows = config_view(db, machine_id)
    return {
        "drift_count": sum(1 for row in rows if row["drift"]),
        "rows": rows,
    }


# ---- D3–D5：机器级草稿（校验走 catalog 条目的 type/choices） ----------------


def _validate_patch(patch: dict[str, str]) -> None:
    entries = publish_flow_service.entries()
    for key, raw in patch.items():
        entry = entries.get(key)
        if entry is None:
            raise ApiError("invalid_request", f"unknown parameter {key}", 400)
        text = str(raw)
        if entry.type in ("int", "integer"):
            try:
                int(text)
            except ValueError:
                raise ApiError("invalid_request", f"{key} must be an integer", 400) from None
        elif entry.type in ("float", "number"):
            try:
                float(text)
            except ValueError:
                raise ApiError("invalid_request", f"{key} must be a number", 400) from None
        elif entry.type in ("bool", "boolean"):
            if text.lower() not in ("true", "false", "1", "0"):
                raise ApiError("invalid_request", f"{key} must be a boolean", 400)
        if entry.choices and text not in entry.choices:
            raise ApiError("invalid_request", f"{key}={text} not in choices", 400)


def _draft_version(db: Session, machine_id: str) -> int:
    return int(
        db.query(ParamMachineDraft)
        .filter(ParamMachineDraft.machine_id == machine_id)
        .count()
    )


def put_draft(db: Session, machine_id: str, patch: dict[str, str], *, base_version: int, actor: str) -> dict:
    """保存草稿：校验不合法 → 400 不落库；base_version 过期 → 409（乐观锁）。"""
    _machine_profile(db, machine_id)  # 机器存在性
    _validate_patch(patch)
    current = _draft_version(db, machine_id)
    if base_version != current:
        raise ApiError("conflict", f"draft version changed: expected {base_version}, got {current}", 409)
    for key, raw in patch.items():
        row = db.scalar(
            select(ParamMachineDraft).where(
                ParamMachineDraft.machine_id == machine_id, ParamMachineDraft.param_key == key
            )
        )
        if row is None:
            row = ParamMachineDraft(machine_id=machine_id, param_key=key)
            db.add(row)
        row.value = str(raw)
        row.updated_by = actor
        row.updated_at = utcnow()
    db.add(ParamAudit(actor=actor, action="machine.draft.set", profile=machine_id, fields=sorted(patch), at=utcnow()))
    db.commit()
    return dict(patch)


def get_draft(db: Session, machine_id: str) -> dict:
    rows = db.scalars(
        select(ParamMachineDraft).where(ParamMachineDraft.machine_id == machine_id)
    ).all()
    return {
        "version": len(rows),
        "values": {row.param_key: row.value for row in rows},
        "updated_by": rows[-1].updated_by if rows else "",
        "updated_at": rows[-1].updated_at.isoformat() if rows else None,
    }


def clear_draft(db: Session, machine_id: str, *, actor: str) -> None:
    for row in db.scalars(
        select(ParamMachineDraft).where(ParamMachineDraft.machine_id == machine_id)
    ).all():
        db.delete(row)
    db.add(ParamAudit(actor=actor, action="machine.draft.clear", profile=machine_id, fields=[], at=utcnow()))
    db.commit()
