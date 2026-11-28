"""阶段上下文存储：重建 handler 所需的纯数据结构（TDD RED → GREEN）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from speech_to_speech.stage_context import StageContext, StageContextStore


def _selection(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, config={"model": name})


def test_store_normalizes_and_keeps_stage_selections():
    store = StageContextStore(
        stt=_selection("qwen3-asr"),
        llm=_selection("chat-completions"),
        tts=_selection("qwen3-tts"),
        vad_kwargs=SimpleNamespace(sample_rate=16000),
        module_kwargs=SimpleNamespace(enable_visemes=False),
    )

    assert store.selections("asr").name == "qwen3-asr"
    assert store.selections("llm").name == "chat-completions"
    assert store.selections("tts").name == "qwen3-tts"
    assert store.snapshot()["modules"] == ["asr", "llm", "tts"]


def test_store_rejects_unknown_stage():
    store = StageContextStore(
        stt=_selection("qwen3-asr"),
        llm=_selection("chat-completions"),
        tts=_selection("qwen3-tts"),
    )
    with pytest.raises(ValueError, match="unknown stage"):
        store.selections("gpu")


def test_stage_context_holds_rebuild_inputs():
    context = StageContext(
        queue_in=object(),
        queue_out=object(),
        sample_rate=24000,
        pipeline_index=2,
    )
    assert context.queue_in is not None
    assert context.pipeline_index == 2
