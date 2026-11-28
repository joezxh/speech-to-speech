"""重载执行器：维护态→排空→退役重建→进度回执（TDD RED → GREEN）。"""

from __future__ import annotations

import threading
from queue import Queue
from types import SimpleNamespace

import pytest

from speech_to_speech.api.openai_realtime.model_reload_executor import ReloadExecutor
from speech_to_speech.api.openai_realtime.pipeline_unit import PipelineUnit
from speech_to_speech.stage_context import StageContextStore


class _STTHandler:
    def retire(self) -> None:
        self.retired = True


class _TTSHandler:
    def retire(self) -> None:
        self.retired = True


def _unit(index=0):
    return PipelineUnit.model_construct(
        index=index,
        handlers=[_STTHandler(), _TTSHandler()],
        session=None,
        maintenance=False,
        output_queue=Queue(),
        text_prompt_queue=Queue(),
        text_output_queue=Queue(),
        stage_context=StageContextStore(
            stt=SimpleNamespace(name="qwen3-asr"),
            llm=SimpleNamespace(name="chat-completions"),
            tts=SimpleNamespace(name="qwen3-tts"),
        ),
    )


def test_executor_marks_maintenance_and_emits_progress(monkeypatch):
    unit = _unit()
    events = []
    rebuilt = []

    executor = ReloadExecutor(
        pool=[unit],
        rebuild=lambda u, stage: rebuilt.append((u.index, stage)) or {"stage": stage},
        on_progress=events.append,
    )
    outcome = executor(
        {"modules": ["asr"], "scope": "unit", "unit_index": 0, "drain": False},
        events.append,
    )

    assert outcome["status"] == "succeeded"
    assert rebuilt == [(0, "asr")]
    assert unit.maintenance is False
    stages = [event.get("stage") for event in events]
    assert "maintenance_set" in stages
    assert "rebuild_asr" in stages
    assert "ready" in stages


def test_executor_rejects_drained_false_with_active_session():
    unit = _unit()
    unit.session = SimpleNamespace()

    executor = ReloadExecutor(pool=[unit], rebuild=lambda u, s: {}, on_progress=lambda e: None)
    outcome = executor(
        {"modules": ["tts"], "scope": "unit", "unit_index": 0, "drain": False},
        lambda e: None,
    )

    assert outcome["status"] == "failed"
    assert outcome["failedStage"] == "drain"
    assert unit.maintenance is False


def test_executor_fails_closed_on_rebuild_error(monkeypatch):
    unit = _unit()

    def broken(u, s):
        raise RuntimeError("model load failed")

    executor = ReloadExecutor(pool=[unit], rebuild=broken, on_progress=lambda e: None)
    outcome = executor(
        {"modules": ["tts"], "scope": "unit", "unit_index": 0, "drain": False},
        lambda e: None,
    )

    assert outcome["status"] == "failed"
    assert outcome["failedStage"] == "rebuild_tts"
    assert unit.maintenance is True  # fail-closed：保持维护态
