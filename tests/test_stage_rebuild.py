"""阶段重建器：原位替换 handler、重接外部引用（TDD RED → GREEN）。"""

from __future__ import annotations

from queue import Queue
from types import SimpleNamespace

import pytest

from speech_to_speech.api.openai_realtime.pipeline_unit import PipelineUnit
from speech_to_speech.stage_context import StageContext, StageContextStore
from speech_to_speech.stage_rebuild import StageRebuilder


class _Handler:
    def __init__(self, name: str) -> None:
        self.name = name
        self.retired = False

    def retire(self) -> None:
        self.retired = True


class _STTHandler(_Handler):
    pass


class _TTSHandler(_Handler):
    pass


class _ChatCompletionsLanguageModel(_Handler):
    pass


@pytest.fixture
def unit():
    stt = _STTHandler("old-stt")
    notifier = _Handler("notifier")
    lm = _ChatCompletionsLanguageModel("lm")
    tts = _TTSHandler("old-tts")
    vad = SimpleNamespace(streaming_stt_sink=stt, window_partials_enabled=False)
    return PipelineUnit.model_construct(
        index=0,
        handlers=[vad, stt, notifier, lm, tts],
        output_queue=Queue(),
        text_prompt_queue=Queue(),
        text_output_queue=Queue(),
        stage_context=StageContextStore(
            stt=SimpleNamespace(name="qwen3-asr"),
            llm=SimpleNamespace(name="chat-completions"),
            tts=SimpleNamespace(name="qwen3-tts"),
        ),
    )


def test_rebuild_asr_replaces_stt_in_place_and_rewires_vad(unit, monkeypatch):
    created = []

    def fake_create(selection, context):
        handler = _Handler("new-stt")
        created.append(handler)
        return handler

    monkeypatch.setattr(
        "speech_to_speech.stage_rebuild.create_backend_handler", fake_create
    )
    monkeypatch.setattr(
        "speech_to_speech.stage_rebuild.build_stt_handlers",
        lambda stt, ctx: [stt],
    )

    rebuilder = StageRebuilder()
    result = rebuilder.rebuild(unit, "asr")

    assert result["stage"] == "asr"
    assert unit.handlers[1] is created[0]
    assert unit.handlers[1].name == "new-stt"
    assert unit.handlers[0].streaming_stt_sink is created[0]
    assert unit.handlers[2].name == "notifier"


def test_rebuild_tts_replaces_tts_in_place(unit, monkeypatch):
    monkeypatch.setattr(
        "speech_to_speech.stage_rebuild.create_backend_handler",
        lambda selection, context: _Handler("new-tts"),
    )

    rebuilder = StageRebuilder()
    result = rebuilder.rebuild(unit, "tts")

    assert result["stage"] == "tts"
    assert unit.handlers[4].name == "new-tts"
    assert len(unit.handlers) == 5


def test_rebuild_llm_reconfigures_remote_client_in_place(unit):
    lm = unit.handlers[3]
    calls = []
    lm.reconfigure = lambda: calls.append("reconfigure")

    result = StageRebuilder().rebuild(unit, "llm")

    assert result["mode"] == "client_reconfigure"
    assert calls == ["reconfigure"]
    assert unit.handlers[3] is lm


def test_rebuild_unknown_stage_fails(unit):
    with pytest.raises(ValueError, match="stage"):
        StageRebuilder().rebuild(unit, "gpu")
