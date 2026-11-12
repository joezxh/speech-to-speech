"""Shared PCM utilities: 24 kHz -> 16 kHz resampling and 512-sample chunking.

The TTS output contract is 16 kHz int16 little-endian PCM delivered in
512-sample chunks. These tests pin the two helpers consumed by Task 4
(Breeze) and Task 5 (CosyVoice2).
"""

import numpy as np

from speech_to_speech.audio_utils import iter_pcm_chunks, resample_pcm_24k_to_16k


def test_int16_24k_to_16k_sample_count_converges_by_two_thirds() -> None:
    t = np.arange(24000, dtype=np.float64) / 24000.0
    pcm = (np.sin(2.0 * np.pi * 440.0 * t) * 16000).astype(np.int16)
    out = resample_pcm_24k_to_16k(pcm, input_dtype="int16")
    assert out.shape == (16000,)
    assert out.dtype == np.int16


def test_float32_input_is_normalized_and_clipped() -> None:
    pcm = np.array([-2.0, 0.0, 2.0], dtype=np.float32)
    out = resample_pcm_24k_to_16k(pcm, input_dtype="float32")
    info = np.iinfo(np.int16)
    assert out.dtype == np.int16
    assert np.isfinite(out).all()  # no nan / inf
    assert out.min() >= info.min  # all within int16 range
    assert out.max() <= info.max
    # No silent wrap: peaks beyond [-1, 1] must be clamped to the int16
    # bounds. A bare .astype(np.int16) would wrap the overshoot into an
    # opposite-sign interior value and never reach either bound.
    assert np.any(out == info.min) or np.any(out == info.max)


def test_iter_pcm_chunks_pads_tail() -> None:
    pcm = np.arange(600, dtype=np.int16)
    chunks = list(iter_pcm_chunks(pcm, chunk_size=512))
    assert [len(c) for c in chunks] == [512, 512]
    np.testing.assert_array_equal(chunks[0], np.arange(512, dtype=np.int16))
    np.testing.assert_array_equal(chunks[1][:88], np.arange(512, 600, dtype=np.int16))
    np.testing.assert_array_equal(chunks[1][88:], np.zeros(424, dtype=np.int16))


def test_iter_pcm_chunks_exact_multiple_has_no_extra_block() -> None:
    pcm = np.arange(1024, dtype=np.int16)
    chunks = list(iter_pcm_chunks(pcm))  # default chunk_size = 512
    assert len(chunks) == 2
    assert [len(c) for c in chunks] == [512, 512]
