from __future__ import annotations

import io
import wave

import pytest

from app.core.errors import ApiError
from app.services import voice_service


def _wav(seconds: float = 8.0, *, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(width)
            handle.setframerate(rate)
            handle.writeframes(b"\x00\x00" * int(seconds * rate) * channels)
        return buffer.getvalue()


def test_bindings_covers_the_three_sources_for_qwen3():
    assert voice_service.bindings("builtin", "qwen3") == {"speaker": "qwen3_tts_speaker"}
    assert set(voice_service.bindings("clone", "qwen3")) == {"refAudio", "refText", "refSpk", "refRvq"}
    assert voice_service.bindings("design", "qwen3") == {"instruct": "qwen3_tts_instruct"}


def test_kokoro_and_openai_only_accept_builtin():
    assert voice_service.bindings("clone", "kokoro") is None
    assert voice_service.bindings("clone", "openai_compatible") is None
    assert voice_service.bindings("design", "kokoro") is None
    assert voice_service.bindings("design", "openai_compatible") is not None


def test_ref_audio_and_ref_spk_are_mutually_exclusive():
    errors = voice_service.conflicts(
        {"qwen3_tts_ref_audio": "/a.wav", "qwen3_tts_ref_spk": "/a.npy"}
    )
    assert errors == [{"field": "qwen3_tts_ref_spk", "conflictWith": "qwen3_tts_ref_audio"}]


def test_rvq_requires_spk_and_text():
    assert voice_service.conflicts({"qwen3_tts_ref_rvq": "/a.npy"}) == [
        {"field": "qwen3_tts_ref_rvq", "reason": "requires_spk_and_text"}
    ]
    assert voice_service.conflicts(
        {"qwen3_tts_ref_rvq": "/a.npy", "qwen3_tts_ref_spk": "/s.npy", "qwen3_tts_ref_text": "hi"}
    ) == []


def test_reference_count_includes_draft_and_versions():
    """Drafts count too, or deleting a voice silently breaks that draft (§3.11.4)."""
    voice_id = "01JABC"
    refs = voice_service.count_references(
        voice_id,
        drafts={"prod": {"qwen3_tts_ref_spk": f"/app/data/voices/{voice_id}/spk.npy"}},
        versions=[("prod", 11, "unrelated: true\n"), ("prod", 12, f"spk: /app/data/voices/{voice_id}/spk.npy")],
    )
    assert refs == {"profiles": ["prod"], "versions": [12]}


def test_validate_wav_accepts_sixteen_k_mono_pcm16():
    assert voice_service.validate_wav(_wav(8.0)) == 8.0


@pytest.mark.parametrize(
    "kwargs",
    [{"rate": 44100}, {"channels": 2}, {"width": 1}],
)
def test_validate_wav_rejects_anything_but_16k_mono_pcm16(kwargs):
    with pytest.raises(ApiError) as caught:
        voice_service.validate_wav(_wav(2.0, **kwargs))
    assert caught.value.code == "voice_audio_invalid"


def test_validate_wav_rejects_over_thirty_seconds():
    with pytest.raises(ApiError) as caught:
        voice_service.validate_wav(_wav(31.0))
    assert caught.value.code == "voice_audio_invalid"


def test_backends_lists_the_three_catalogued_ones_and_the_b4_gap():
    rows = {row["backend"]: row for row in voice_service.backends()["list"]}
    assert rows["qwen3"]["catalogued"] is True
    assert rows["qwen3"]["sources"] == ["builtin", "clone", "design"]
    assert rows["kokoro"]["sources"] == ["builtin"]
    # Not in the machine catalog: listed with no sources and no fields.
    assert rows["cosyvoice"]["catalogued"] is False
    assert rows["cosyvoice"]["sources"] == []
    assert rows["cosyvoice"]["fields"] == {}
    assert rows["cosyvoice"]["notes"] == "字段未进机器目录"


def test_voice_ids_in_reads_only_the_voices_segment():
    assert voice_service.voice_ids_in(
        ["/app/data/voices/01J1/spk.npy", "plain", "/app/data/voices/01J2/rvq.npy"]
    ) == ["01J1", "01J2"]
