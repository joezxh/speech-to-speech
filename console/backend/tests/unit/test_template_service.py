"""template_service 单元测试：字段归一化、枚举/场景校验、CRUD 与审计前缀。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import console as console_settings
from app.core.errors import ApiError
from app.models.param_audit import ParamAudit
from app.schemas.template import TemplateCreate, TemplateFieldIn, TemplateUpdate
from app.services import template_service
from app.services.machine_service import infer_platform

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"


def _create(db_session: Session, **overrides) -> dict:
    payload = TemplateCreate(
        name=overrides.pop("name", "GPU 24G baseline"),
        effect=overrides.pop("effect", "restart"),
        platform=overrides.pop("platform", "gpu"),
        status=overrides.pop("status", "draft"),
        scene=overrides.pop("scene", "edge"),
        minVramGb=overrides.pop("minVramGb", 24),
        fields=overrides.pop("fields", [TemplateFieldIn(key="llm.model_name", value="qwen3-8b")]),
        desc=overrides.pop("desc", "restart only"),
    )
    return template_service.create_template(db_session, payload, actor="alice")


def test_hot_field_gets_patch_path_and_hot_flag(db_session):
    fields = template_service.normalize_fields([TemplateFieldIn(key="thresh", value="0.7")])
    assert fields == [
        {"key": "thresh", "value": "0.7", "patch": "audio.input.turn_detection.threshold", "source": "", "hot": True}
    ]


def test_unknown_key_is_refused_only_when_catalog_is_mounted(db_session, monkeypatch):
    # 目录已挂载：未知 key 拒绝。
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    with pytest.raises(ApiError) as exc:
        template_service.normalize_fields([TemplateFieldIn(key="nope.nope")])
    assert exc.value.code == "invalid_request"
    # 目录未挂载（真实部署可能没带目录）：降级为只存不校验。
    monkeypatch.setattr(console_settings, "param_catalog_path", "missing.yaml")
    fields = template_service.normalize_fields([TemplateFieldIn(key="nope.nope", value="1")])
    assert fields[0]["patch"] == "nope.nope"
    assert fields[0]["hot"] is False


def test_catalog_key_passes_through_with_entry_metadata(db_session, monkeypatch):
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    # fixture 条目无 source_ref、effect 非 hot → 只透传 key 作为 patch、hot=False。
    fields = template_service.normalize_fields([TemplateFieldIn(key="vad.min_silence_ms", value="400")])
    assert fields[0]["patch"] == "vad.min_silence_ms"
    assert fields[0]["source"] == ""
    assert fields[0]["hot"] is False


def test_create_list_update_delete_roundtrip(db_session):
    created = _create(db_session)
    assert created["effect"] == "restart"
    assert created["scene"] == "edge"
    assert created["fields"][0]["patch"] == "llm.model_name"

    listed = template_service.list_templates(db_session, effect="restart", q="baseline")
    assert listed["total"] == 1
    assert template_service.list_templates(db_session, effect="runtime")["total"] == 0

    updated = template_service.update_template(
        db_session,
        created["id"],
        TemplateUpdate(status="published", scene="latency"),
        actor="bob",
    )
    assert updated["status"] == "published"
    assert updated["updatedBy"] == "bob"

    template_service.delete_template(db_session, created["id"], actor="alice")
    with pytest.raises(KeyError):
        template_service.get_row(db_session, created["id"])


def test_name_conflict_raises_value_error(db_session):
    _create(db_session)
    with pytest.raises(ValueError):
        _create(db_session, name="GPU 24G baseline")


def test_bad_enum_and_scene_are_refused(db_session):
    with pytest.raises(ApiError):
        _create(db_session, name="bad-effect", effect="hot")
    with pytest.raises(ApiError):
        _create(db_session, name="bad-platform", platform="cuda")
    with pytest.raises(ApiError):
        _create(db_session, name="bad-scene", scene="latency-low")


def test_audit_uses_template_prefix(db_session):
    row = _create(db_session)
    template_service.update_template(db_session, row["id"], TemplateUpdate(desc="x"), actor="alice")
    template_service.delete_template(db_session, row["id"], actor="alice")
    actions = [a.action for a in db_session.query(ParamAudit).all()]
    assert "template.create" in actions
    assert "template.update" in actions
    assert "template.delete" in actions


def test_infer_platform_from_gpu_description():
    assert infer_platform("NVIDIA GeForce RTX 4090") == "gpu"
    assert infer_platform("Ascend 910B") == "npu"
    assert infer_platform("AMD Radeon Pro W7900") == "amd"
    assert infer_platform("") == "cpu"
    assert infer_platform("Intel iGPU") == "cpu"
