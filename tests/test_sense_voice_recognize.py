"""TDD: SenseVoiceSTTHandler.recognize() and _generate_with_emotion()."""
from __future__ import annotations

import numpy as np
import pytest

from speech_to_speech.STT.sense_voice_handler import SenseVoiceSTTHandler


class _FakeLo:
    def __init__(self):
        self._hook = None

    def register_forward_hook(self, fn):
        self._hook = fn
        return type("H", (), {"remove": lambda self: None})()

    def __call__(self, x):
        return x


class _FakeInner:
    def __init__(self):
        self.ctc = type("CTC", (), {"ctc_lo": _FakeLo()})()


class _FakeAutoModel:
    def __init__(self, text, logits=None):
        self._text = text
        self._logits = logits
        self.model = _FakeInner()

    def generate(self, audio, **kwargs):
        # Simulate the hooked layer firing during generate.
        if self._logits is not None:
            self.model.ctc.ctc_lo._hook(None, None, self._logits)
        return [{"text": self._text}]


def _handler(text="<|zh|><|HAPPY|><|Laughter|>你好😊", logits=None):
    h = object.__new__(SenseVoiceSTTHandler)
    fake = _FakeAutoModel(text, logits)
    h.model = fake
    h._postprocess = lambda t: t
    h.language = "zh"
    h.gen_kwargs = {}
    h.device = "cpu"
    return h, fake


def test_recognize_returns_raw_label_laughter_confidence_margin():
    h, fake = _handler(text="<|zh|><|HAPPY|><|Laughter|>你好")
    # Provide real-shaped logits at emotion position with HAPPY dominant.
    from speech_to_speech.STT.sense_voice_emotion import emotion_token_ids

    ids = emotion_token_ids()
    vocab = max(ids.values()) + 1
    logits = np.full((1, 4, vocab), -20.0, dtype=np.float32)
    logits[0, 1, ids["HAPPY"]] = 8.0
    logits[0, 1, ids["NEUTRAL"]] = 2.0
    h._install_emotion_hook()
    fake._logits = logits
    result = h.recognize(np.zeros(1600, dtype=np.float32))
    assert result["raw"] == "HAPPY"
    assert result["laughter"] is True
    assert result["confidence"] > 0.9
    assert result["margin"] > 0.8


def test_generate_with_emotion_returns_clean_text_and_emotion_string():
    h, _ = _handler(text="<|zh|><|ANGRY|>我很生气😡")
    clean, emotion = h._generate_with_emotion(np.zeros(1600, dtype=np.float32))
    assert "生气" in clean
    assert "😡" not in clean
    assert "anger" in emotion or "愤怒" in emotion


def test_generate_keeps_clean_text_backward_compatible():
    h, _ = _handler(text="<|zh|><|HAPPY|>你好😊")
    assert h._generate(np.zeros(1600, dtype=np.float32)) == "你好"
