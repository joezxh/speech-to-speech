"""Shared, dependency-light PCM helpers for the TTS output contract.

TTS handlers emit audio at 24 kHz, but the pipeline consumes 16 kHz int16
little-endian PCM delivered in 512-sample chunks. These helpers are free of
any model / torch / GPU imports so they can be reused by the Breeze (Task 4)
and CosyVoice2 (Task 5) handlers.
"""

from typing import Iterator

import librosa
import numpy as np

_INPUT_SR = 24000
_OUTPUT_SR = 16000
_INT16_SCALE = 32767.0
_INT16 = np.iinfo(np.int16)


def resample_pcm_24k_to_16k(pcm: np.ndarray, *, input_dtype: str) -> np.ndarray:
    """Resample 24 kHz PCM to 16 kHz int16 PCM.

    Args:
        pcm: 1-D samples whose type is declared by ``input_dtype``.
        input_dtype: ``"int16"`` (normalized by 32768 before resampling) or
            ``"float32"`` (resampled directly).

    Returns:
        ``np.int16`` samples at 16 kHz. Out-of-range floats are clipped to the
        int16 bounds rather than silently wrapping around on the cast.
    """
    if input_dtype == "int16":
        audio = pcm.astype(np.float32) / 32768.0
    elif input_dtype == "float32":
        audio = np.asarray(pcm, dtype=np.float32)
    else:
        raise ValueError(f"unsupported input_dtype: {input_dtype!r} (expected 'int16' or 'float32')")

    resampled = librosa.resample(audio, orig_sr=_INPUT_SR, target_sr=_OUTPUT_SR)
    scaled = resampled * _INT16_SCALE
    return np.clip(scaled, _INT16.min, _INT16.max).astype(np.int16)


def iter_pcm_chunks(pcm_i16: np.ndarray, chunk_size: int = 512) -> Iterator[np.ndarray]:
    """Yield fixed-size int16 PCM chunks, zero-padding the final partial block.

    Every yielded array has exactly ``chunk_size`` samples. When the input
    length is an exact multiple of ``chunk_size``, no extra padded block is
    emitted.
    """
    n = len(pcm_i16)
    n_full = n // chunk_size
    remainder = n % chunk_size

    full = pcm_i16[: n_full * chunk_size].reshape(n_full, chunk_size)
    for i in range(n_full):
        yield full[i]

    if remainder:
        tail = pcm_i16[n_full * chunk_size :]
        yield np.pad(tail, (0, chunk_size - remainder))
