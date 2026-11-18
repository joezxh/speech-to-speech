"""TDD: emotion text flows STT -> event -> LLM user message, client stays clean."""
from __future__ import annotations

import threading

import numpy as np

from speech_to_speech.api.openai_realtime import service as svc
from speech_to_speech.pipeline.events import TranscriptionCompletedEvent
from speech_to_speech.pipeline.messages import Transcription
from speech_to_speech.STT.transcription_notifier import TranscriptionNotifier


def test_transcription_carries_emotion_field():
    t = Transcription(text="你好", emotion="[情绪：开心]")
    assert t.emotion == "[情绪：开心]"


def test_completed_event_carries_emotion_field():
    e = TranscriptionCompletedEvent(transcript="你好", emotion="[情绪：愤怒]")
    assert e.emotion == "[情绪：愤怒]"


def test_notifier_preserves_emotion_from_transcription():
    class _Queue:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

    queue = _Queue()
    notifier = object.__new__(TranscriptionNotifier)
    notifier.setup(text_output_queue=queue, should_listen=threading.Event())
    t = Transcription(text="你好", emotion="[情绪：开心]")
    # Drive process() with a minimal final transcription; inspect the emitted event.
    list(notifier.process(t))
    assert queue.items and queue.items[-1].emotion == "[情绪：开心]"


def test_llm_user_message_gets_emotion_appended():
    # Pure helper: client transcript unchanged, LLM text annotated.
    llm_text = svc.with_emotion_text("你好", "[情绪：开心]")
    assert llm_text == "你好 [情绪：开心]"


def test_llm_user_message_unchanged_when_no_emotion():
    assert svc.with_emotion_text("你好", None) == "你好"


def test_asr_rest_finds_sensevoice_handler():
    from speech_to_speech.api.openai_realtime import audio_services

    class _U:
        class _H:
            pass

        handlers = [_H()]

    _H = type("SenseVoiceSTTHandler", (), {})
    unit = _U()
    unit.handlers = [_H()]
    assert audio_services.find_stt_handler([unit]) is not None
