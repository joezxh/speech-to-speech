"""TDD: SenseVoiceSTTHandler reports the spoken language as `language_code`.

Without it the pipeline cannot tell the LLM which language the user spoke, so
`enable_lang_prompt` stays silent and the assistant is free to answer in
English even though the user spoke Chinese.
"""
from __future__ import annotations

import numpy as np

from speech_to_speech.pipeline.messages import VADAudio
from speech_to_speech.STT.sense_voice_handler import SenseVoiceSTTHandler


class _FakeAutoModel:
    def __init__(self, text):
        self._text = text
        self.model = type("Inner", (), {})()

    def generate(self, audio, **kwargs):
        return [{"text": self._text}]


def _handler(text="<|zh|><|NEUTRAL|><|Speech|>你好", language="zh"):
    handler = object.__new__(SenseVoiceSTTHandler)
    handler.model = _FakeAutoModel(text)
    handler._postprocess = lambda t: t
    handler.language = language
    handler.gen_kwargs = {}
    handler.device = "cpu"
    return handler


def test_language_code_uses_the_tag_sensevoice_emitted():
    handler = _handler()
    assert handler._resolved_language_code("<|zh|><|NEUTRAL|>你好") == "zh"


def test_language_code_follows_the_spoken_language_not_the_configured_one():
    # SenseVoice tags the audio with the language it heard, whatever
    # sense_voice_stt_language was configured to.
    handler = _handler(language="zh")
    assert handler._resolved_language_code("<|en|><|NEUTRAL|>Hello") == "en"


def test_language_code_falls_back_to_the_configured_language():
    handler = _handler(language="zh")
    assert handler._resolved_language_code("") == "zh"
    assert handler._resolved_language_code("<|NEUTRAL|>你好") == "zh"


def test_language_code_is_unset_when_configured_to_auto_and_untagged():
    handler = _handler(language="auto")
    assert handler._resolved_language_code("") is None


def test_process_reports_the_detected_language_on_the_transcription():
    handler = _handler(text="<|zh|><|NEUTRAL|><|Speech|>你好")
    audio = VADAudio(audio=np.zeros(1600, dtype=np.float32), mode="final")

    outputs = list(handler.process(audio))

    assert len(outputs) == 1
    assert outputs[0].text == "你好"
    assert outputs[0].language_code == "zh"