"""Offline tests for the VoxCPM TTS backend (weights are never downloaded)."""

from __future__ import annotations

import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from speech_to_speech.model_registry import ModelWeightsMissingError
from speech_to_speech.pipeline.handler_types import TTSInput
from speech_to_speech.pipeline.messages import AUDIO_RESPONSE_DONE, EndOfResponse
from speech_to_speech.TTS.voxcpm_tts_handler import (
    BLOCKSIZE,
    PIPELINE_SAMPLE_RATE,
    VOXCPM_LANGUAGE_CODES,
    VoxCPMTTSHandler,
)


class FakeModel:
    def __init__(self, chunks: list[np.ndarray], sample_rate: int = 48000) -> None:
        self.chunks = chunks
        self.sample_rate = sample_rate
        self.calls: list[dict[str, object]] = []
        self.streaming_calls = 0
        self.blocking_calls = 0

    def generate_streaming(self, text: str, **kwargs: object):
        self.calls.append(dict(kwargs))
        self.streaming_calls += 1
        yield from self.chunks

    def generate(self, text: str, **kwargs: object):
        self.calls.append(dict(kwargs))
        self.blocking_calls += 1
        if not self.chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate([np.asarray(chunk, dtype=np.float32).reshape(-1) for chunk in self.chunks])


class StrictModel:
    """Mimics a voxcpm release whose generate path rejects unknown kwargs."""

    sample_rate = 48000

    def __init__(self) -> None:
        self.calls = 0

    def generate_streaming(self, text: str):
        self.calls += 1
        yield np.zeros(1600, dtype=np.float32)


def _install_fake_module(monkeypatch: pytest.MonkeyPatch, model: object) -> type:
    class FakeVoxCPM:
        loaded: list[tuple[str, bool]] = []

        @classmethod
        def from_pretrained(cls, model_name: str, load_denoiser: bool = False):
            cls.loaded = [(model_name, load_denoiser)]
            return model

    module = types.ModuleType("voxcpm")
    module.VoxCPM = FakeVoxCPM  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "voxcpm", module)
    return FakeVoxCPM


def _make_handler(monkeypatch: pytest.MonkeyPatch, model: object, **kwargs: object) -> VoxCPMTTSHandler:
    _install_fake_module(monkeypatch, model)
    setup_kwargs = {"device": "cpu"}
    setup_kwargs.update(kwargs)
    handler = VoxCPMTTSHandler.__new__(VoxCPMTTSHandler)
    handler.setup(Event(), **setup_kwargs)
    return handler


def _blocks(handler: VoxCPMTTSHandler, text: str = "hello") -> list[np.ndarray]:
    return list(handler.process(TTSInput(text=text, language_code=None, tts_language_code=None)))


def test_setup_detects_native_sample_rate_and_logs(monkeypatch, caplog):
    model = FakeModel([np.zeros(1600, dtype=np.float32)], sample_rate=48000)
    with caplog.at_level(logging.INFO, logger="speech_to_speech.TTS.voxcpm_tts_handler"):
        handler = _make_handler(monkeypatch, model, streaming=True)

    assert handler.sample_rate == 48000
    assert handler.resolved_device == "cpu"
    assert "sample_rate=48000" in caplog.text
    assert "openbmb/VoxCPM2" in caplog.text


@dataclass
class _Nested:
    sample_rate: int


def test_setup_falls_back_across_sample_rate_sources(monkeypatch):
    nested = types.SimpleNamespace(tts_model=_Nested(sample_rate=44100))
    handler = _make_handler(monkeypatch, nested)
    assert handler.sample_rate == 44100

    bare = types.SimpleNamespace()
    handler = _make_handler(monkeypatch, bare)
    assert handler.sample_rate == 48000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cfg_value": 0.0},
        {"cfg_value": float("nan")},
        {"inference_timesteps": 0},
        {"inference_timesteps": 101},
        {"dtype": "int8"},
        {"device": "tpu"},
        {"ref_audio": "C:/definitely/not/a/file.wav"},
        {"prompt_text": "reference transcript without audio"},
    ],
)
def test_setup_rejects_invalid_configuration(monkeypatch, kwargs):
    _install_fake_module(monkeypatch, FakeModel([]))
    handler = VoxCPMTTSHandler.__new__(VoxCPMTTSHandler)
    with pytest.raises(ValueError):
        handler.setup(Event(), **kwargs)


def test_setup_reports_missing_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "voxcpm", None)
    handler = VoxCPMTTSHandler.__new__(VoxCPMTTSHandler)
    with pytest.raises(ImportError) as excinfo:
        handler.setup(Event(), device="cpu")
    message = str(excinfo.value)
    assert "speech-to-speech[voxcpm]" in message
    assert "3.10-3.12" in message


def test_setup_reports_missing_local_weights(monkeypatch):
    _install_fake_module(monkeypatch, FakeModel([]))
    handler = VoxCPMTTSHandler.__new__(VoxCPMTTSHandler)
    missing = str(Path.cwd() / "missing-voxcpm-checkpoint")
    with pytest.raises(ModelWeightsMissingError) as excinfo:
        handler.setup(Event(), device="cpu", model_name=missing)
    assert "huggingface-cli download" in str(excinfo.value)


@pytest.mark.parametrize(("sample_rate", "source_samples"), [(48000, 4800), (44100, 4410), (16000, 1600)])
def test_output_is_16k_int16_padded_blocks(monkeypatch, sample_rate, source_samples):
    model = FakeModel([np.zeros(source_samples, dtype=np.float32)], sample_rate=sample_rate)
    handler = _make_handler(monkeypatch, model)

    blocks = _blocks(handler)

    assert blocks
    assert handler.sample_rate == sample_rate
    assert all(block.dtype == np.int16 and block.size == BLOCKSIZE for block in blocks)
    expected = round(source_samples * PIPELINE_SAMPLE_RATE / sample_rate)
    assert abs(sum(block.size for block in blocks) - expected) <= 2 * BLOCKSIZE


def test_streaming_and_blocking_outputs_match(monkeypatch):
    chunks = [np.zeros(2400, dtype=np.float32), np.zeros(1600, dtype=np.float32)]
    streaming = _make_handler(monkeypatch, FakeModel(chunks), streaming=True)
    blocking = _make_handler(monkeypatch, FakeModel(chunks), streaming=False)

    assert [b.tobytes() for b in _blocks(streaming)] == [b.tobytes() for b in _blocks(blocking)]
    assert streaming.model.streaming_calls == 1
    assert blocking.model.blocking_calls == 1


def test_generation_params_are_forwarded(monkeypatch):
    model = FakeModel([np.zeros(1600, dtype=np.float32)])
    handler = _make_handler(
        monkeypatch,
        model,
        cfg_value=2.5,
        inference_timesteps=12,
        normalize=False,
        denoise=True,
        seed=7,
    )

    _blocks(handler)

    assert model.calls[0] == {
        "cfg_value": 2.5,
        "inference_timesteps": 12,
        "normalize": False,
        "denoise": True,
        "seed": 7,
    }


def test_kwargs_type_error_falls_back_to_text_only(monkeypatch):
    model = StrictModel()
    _install_fake_module(monkeypatch, model)
    handler = VoxCPMTTSHandler.__new__(VoxCPMTTSHandler)
    handler.setup(Event(), device="cpu")

    blocks = _blocks(handler)

    assert blocks
    assert model.calls == 1
    assert handler._kwargs_fallback_used is True


def test_inference_error_propagates(monkeypatch):
    class BrokenModel(FakeModel):
        def generate_streaming(self, text: str, **kwargs: object):
            raise RuntimeError("voxcpm exploded")
            yield  # pragma: no cover

    handler = _make_handler(monkeypatch, BrokenModel([]))
    with pytest.raises(RuntimeError, match="voxcpm exploded"):
        _blocks(handler)


def test_empty_text_and_empty_audio(monkeypatch):
    handler = _make_handler(monkeypatch, FakeModel([np.zeros(1600, dtype=np.float32)]))
    assert _blocks(handler, text="   ") == []

    silent = _make_handler(monkeypatch, FakeModel([]))
    with pytest.raises(RuntimeError, match="no audio"):
        _blocks(silent)


def test_cancellation_stops_output(monkeypatch):
    from speech_to_speech.pipeline.cancel_scope import CancelScope

    scope = CancelScope()

    class CancellingModel(FakeModel):
        def generate_streaming(self, text: str, **kwargs: object):
            yield np.zeros(24000, dtype=np.float32)
            scope.cancel()
            yield np.zeros(24000, dtype=np.float32)

    model = CancellingModel([])
    _install_fake_module(monkeypatch, model)
    handler = VoxCPMTTSHandler.__new__(VoxCPMTTSHandler)
    handler.setup(Event(), device="cpu", cancel_scope=scope)

    blocks = _blocks(handler)

    assert 0 < len(blocks) < 20


def test_end_of_response_emits_done(monkeypatch):
    handler = _make_handler(monkeypatch, FakeModel([]))
    assert list(handler.process(EndOfResponse())) == [AUDIO_RESPONSE_DONE]


def test_language_codes_are_two_letter_lowercase():
    assert len(VOXCPM_LANGUAGE_CODES) == 30
    assert all(len(code) == 2 and code.islower() and code.isalpha() for code in VOXCPM_LANGUAGE_CODES)
    assert {"zh", "en", "ja", "ko"} <= VOXCPM_LANGUAGE_CODES
