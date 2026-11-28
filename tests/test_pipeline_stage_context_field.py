"""PipelineUnit 保存阶段上下文：重建时无需重新解析配置。"""

from __future__ import annotations

from speech_to_speech.api.openai_realtime.pipeline_unit import PipelineUnit
from speech_to_speech.stage_context import StageContextStore


def test_pipeline_unit_accepts_stage_context_store():
    unit = PipelineUnit.model_construct(
        index=0,
        handlers=[],
        stage_context=StageContextStore(stt=object(), llm=object(), tts=object()),
    )
    assert unit.stage_context is not None
