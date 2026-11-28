"""维护态实例：不接新会话、/v1/pool 计入占用（TDD RED → GREEN）。"""

from __future__ import annotations

from speech_to_speech.api.openai_realtime.pipeline_unit import PipelineUnit


def test_pipeline_unit_maintenance_flag_defaults_false():
    unit = PipelineUnit.model_construct(index=0, handlers=[])
    assert unit.maintenance is False


def test_maintenance_units_are_excluded_from_claim():
    """_claim_unit 只领取非维护态空闲单元。"""
    import speech_to_speech.api.openai_realtime.websocket_router as router

    units = [
        PipelineUnit.model_construct(index=0, handlers=[], maintenance=True),
        PipelineUnit.model_construct(index=1, handlers=[], maintenance=False),
    ]
    claimable = [u for u in units if u.session is None and not u.maintenance]
    assert [u.index for u in claimable] == [1]
