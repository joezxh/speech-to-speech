"""smart_settings_service 单元测试：拉取、规则兜底、LLM 结果校验。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.schemas.smart_settings import SmartAnalyzeIn
from app.services import machine_service, smart_settings_service
from app.services.log_analysis_service import AnalysisUnavailable


@pytest.fixture
def machine(db_session: Session):
    machine_service.create_machine(db_session, machine_service.MachineCreate(machineId="node-a01"), actor="alice")


def test_fetch_returns_params_and_empty_logs_when_log_dir_missing(db_session, machine, tmp_path):
    db_session.commit()
    data = smart_settings_service.fetch(db_session, "node-a01")
    assert data["machine"]["machineId"] == "node-a01"
    assert isinstance(data["params"], list) and data["params"]
    assert all("key" in row and "actual" in row for row in data["params"])
    assert data["logs"] == []


def test_fetch_unknown_machine_raises_key_error(db_session):
    with pytest.raises(KeyError):
        smart_settings_service.fetch(db_session, "ghost")


def test_analyze_requires_fault(db_session, machine):
    with pytest.raises(ApiError) as exc:
        smart_settings_service.analyze(db_session, SmartAnalyzeIn(machineId="node-a01", fault="  "), actor="alice")
    assert exc.value.code == "invalid_parameter"


def test_analyze_falls_back_to_rules_when_llm_unreachable(db_session, machine, monkeypatch):
    def unreachable(prompt: str):
        raise AnalysisUnavailable("loopback LLM unreachable")

    monkeypatch.setattr(smart_settings_service, "_call_llm", unreachable)
    result = smart_settings_service.analyze(
        db_session,
        SmartAnalyzeIn(machineId="node-a01", fault="用户说话总是被截断", params={"min_silence_ms": "450"}),
        actor="alice",
    )
    assert result["source"] == "rules"
    assert result["recommendations"][0]["key"] == "min_silence_ms"
    assert result["recommendations"][0]["from"] == "450"
    # 审计按 smart.* 前缀落地（fallback 也留痕）。
    from app.models.param_audit import ParamAudit

    actions = [row.action for row in db_session.query(ParamAudit).all()]
    assert "smart.analyze" in actions


def test_analyze_uses_llm_result_when_available(db_session, machine, monkeypatch):
    def fake_call(prompt: str):
        return (
            {"summary": "句末静音偏短导致误切", "recommendations": [{"key": "min_silence_ms", "from": "450", "to": "700", "reason": "被切句变多"}]},
            "test-model",
        )

    monkeypatch.setattr(smart_settings_service, "_call_llm", fake_call)
    result = smart_settings_service.analyze(
        db_session, SmartAnalyzeIn(machineId="node-a01", fault="总是把一句话切成两轮"), actor="alice"
    )
    assert result["source"] == "llm"
    assert result["model"] == "test-model"
    assert result["recommendations"][0]["to"] == "700"


def test_validate_result_rejects_schema_drift():
    good = {"summary": "s", "recommendations": [{"key": "k", "from": "1", "to": "2", "reason": "r"}]}
    assert smart_settings_service._validate_result(good)["summary"] == "s"
    with pytest.raises(AnalysisUnavailable):
        smart_settings_service._validate_result({"summary": "s", "recommendations": [{"key": "k"}]})
    with pytest.raises(AnalysisUnavailable):
        smart_settings_service._validate_result({"summary": "", "recommendations": []})
