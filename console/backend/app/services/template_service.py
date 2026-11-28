"""模板业务（原型「模板管理」页 + 「保存为模板」共用）。

设计约束：
* 字段 schema 以 parameter-catalog 为单一事实源：字段 key 必须是目录参数键
  （`<stage>.<name>`）或热更参数别名（HOT_FIELDS）；目录未挂载时降级为只存不校验
  （模板 CRUD 不应因目录缺失而 503）。
* runtime 模板的热更参数给出 session.update patch 路径（与 hot_update_service
  白名单同源维护，但不扩大白名单——白名单裁剪仍由热更下发链路执行）。
* 审计沿用既有约定：action 点分前缀（template.*），fields 只存字段名不存值。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.template import ParamTemplate
from app.repositories.audit_repository import AuditRepository
from app.repositories.template_repository import TemplateRepository
from app.schemas.common import iso_utc
from app.schemas.template import TemplateCreate, TemplateUpdate

EFFECTS = ("runtime", "restart")
PLATFORMS = ("gpu", "npu", "amd", "cpu")
STATUSES = ("draft", "review", "published", "archived")
# 绑定场景 key（推荐配置方案的固定组成部分）；方案内容在目录/前端侧维护。
SCENE_KEYS = ("latency", "slow", "noisy", "edge", "mix", "remote", "meeting")

# 热更参数别名 → session.update 路径（原型 PARAM_TEMPLATES 的 patch 列）。
# 注意：白名单裁剪仍以 hot_update_service.WHITELIST 为准；audio.output.* 与
# model 目前会被白名单拒绝，模板照存路径，由前端灰显该类字段的"应用"按钮。
HOT_FIELDS: dict[str, str] = {
    "thresh": "audio.input.turn_detection.threshold",
    "min_silence_ms": "audio.input.turn_detection.silence_duration_ms",
    "qwen3_asr_language": "audio.input.transcription.language",
    "init_chat_prompt": "instructions",
    "instructions": "instructions",
    "qwen3_tts_speaker": "audio.output.voice",
    "voice": "audio.output.voice",
    "model": "model",
}


def _catalog_entries() -> dict:
    """目录条目（key → entry）；目录未挂载时返回空表并跳过 key 校验。"""
    try:
        from app.services import publish_flow_service  # noqa: PLC0415 - 延迟导入避免环

        return publish_flow_service.entries()
    except ApiError:
        return {}


def normalize_fields(raw_fields) -> list[dict]:
    """补 patch / hot / source 派生列；key 不合法（目录已挂载时）→ 400。"""
    entries = _catalog_entries()
    out: list[dict] = []
    for item in raw_fields or []:
        key = str(item.key).strip()
        if not key:
            raise ApiError("invalid_request", "template field key must not be empty", 400)
        hot = key in HOT_FIELDS
        if key not in HOT_FIELDS and entries and key not in entries:
            raise ApiError("invalid_request", f"unknown parameter {key}", 400)
        patch = str(item.patch or "").strip() or HOT_FIELDS.get(key, key)
        entry = entries.get(key)
        source = str(item.source or "").strip() or (entry.source_ref if entry else "")
        if entry and not hot and entry.effect in ("hot", "start+hot"):
            hot = True
        out.append({"key": key, "value": str(item.value or ""), "patch": patch, "source": source, "hot": hot})
    return out


def _check_enum(value: str, allowed: tuple[str, ...], label: str) -> None:
    if value not in allowed:
        raise ApiError("invalid_request", f"{label} must be one of {', '.join(allowed)}", 400)


def _check_scene(scene: str) -> None:
    if scene and scene not in SCENE_KEYS:
        raise ApiError("invalid_request", f"unknown scene {scene}", 400)


def _audit(db: Session, *, actor: str, action: str, name: str, fields: list[str]) -> None:
    AuditRepository(db).record(
        actor=actor,
        role="",
        action=action,
        profile=name,
        fields=list(fields),
    )


def _out(row: ParamTemplate) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "effect": row.effect,
        "platform": row.platform,
        "status": row.status,
        "scene": row.scene,
        "minVramGb": row.min_vram_gb,
        "fields": list(row.fields_json or []),
        "desc": row.description,
        "createdAt": iso_utc(row.created_at),
        "updatedAt": iso_utc(row.updated_at),
        "createdBy": row.created_by,
        "updatedBy": row.updated_by,
    }


def get_row(db: Session, template_id: int) -> ParamTemplate:
    row = TemplateRepository(db).get(template_id)
    if row is None:
        raise KeyError(template_id)
    return row


def list_templates(db: Session, *, effect: str = "", platform: str = "", status: str = "", q: str = "") -> dict:
    rows = TemplateRepository(db).list(effect=effect, platform=platform, status=status, q=q)
    templates = [_out(row) for row in rows]
    return {"templates": templates, "total": len(templates)}


def get_template(db: Session, template_id: int) -> dict:
    return _out(get_row(db, template_id))


def create_template(db: Session, payload: TemplateCreate, *, actor: str) -> dict:
    _check_enum(payload.effect, EFFECTS, "effect")
    _check_enum(payload.platform, PLATFORMS, "platform")
    _check_enum(payload.status, STATUSES, "status")
    _check_scene(payload.scene)
    if TemplateRepository(db).get_by_name(payload.name) is not None:
        raise ValueError(payload.name)
    row = ParamTemplate(
        name=payload.name,
        effect=payload.effect,
        platform=payload.platform,
        status=payload.status,
        scene=payload.scene,
        min_vram_gb=payload.minVramGb,
        fields_json=normalize_fields(payload.fields),
        description=payload.desc,
        created_by=actor,
        updated_by=actor,
    )
    row = TemplateRepository(db).create(row=row)
    _audit(db, actor=actor, action="template.create", name=row.name, fields=[f.key for f in payload.fields])
    return _out(row)


def update_template(db: Session, template_id: int, payload: TemplateUpdate, *, actor: str) -> dict:
    row = get_row(db, template_id)
    changed = payload.model_dump(exclude_unset=True)
    if "effect" in changed:
        _check_enum(changed["effect"], EFFECTS, "effect")
    if "platform" in changed:
        _check_enum(changed["platform"], PLATFORMS, "platform")
    if "status" in changed:
        _check_enum(changed["status"], STATUSES, "status")
    if "scene" in changed:
        _check_scene(changed["scene"] or "")
    if "name" in changed and changed["name"] != row.name:
        existing = TemplateRepository(db).get_by_name(changed["name"])
        if existing is not None and existing.id != row.id:
            raise ValueError(changed["name"])
    if "fields" in changed and changed["fields"] is not None:
        row.fields_json = normalize_fields(changed["fields"])
        changed.pop("fields")
    for attr, value in changed.items():
        column = {"minVramGb": "min_vram_gb", "desc": "description"}.get(attr, attr)
        setattr(row, column, value)
    row.updated_by = actor
    db.commit()
    db.refresh(row)
    _audit(db, actor=actor, action="template.update", name=row.name, fields=sorted(changed))
    return _out(row)


def delete_template(db: Session, template_id: int, *, actor: str) -> None:
    row = get_row(db, template_id)
    name = row.name
    if not TemplateRepository(db).delete(template_id):
        raise KeyError(template_id)
    _audit(db, actor=actor, action="template.delete", name=name, fields=[])
