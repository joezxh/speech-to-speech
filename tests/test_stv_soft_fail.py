"""TDD: STV handler soft-fails when the phoneme model is unavailable."""
from __future__ import annotations

from speech_to_speech.STV.w2v_stv_handler import Wav2Vec2STVHandler


def test_setup_soft_fails_when_model_download_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("model download failed")

    import speech_to_speech.STV.w2v_stv_handler as mod
    monkeypatch.setattr(mod, "resolve_device", lambda *a, **k: "cpu")

    class _FakePipeline:
        @staticmethod
        def pipeline(*args, **kwargs):
            return boom(*args, **kwargs)

    monkeypatch.setattr("transformers.pipeline", boom, raising=False)
    h = object.__new__(Wav2Vec2STVHandler)
    # setup imports `from transformers import pipeline` internally; patch module attr.
    import transformers

    monkeypatch.setattr(transformers, "pipeline", boom)
    h.setup(model_name="nonexistent/model", device="cpu")
    # Instead of raising, it degrades to skip with a log and no pipeline.
    assert h.skip is True
    assert h.asr_pipeline is None
