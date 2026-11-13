"""声纹音频预处理：解码归一、有效语音检测与技术质量分。

设计依据（docs/voiceprint-embedding-service-design-CN.md §5.3 / §5.4）：
  · 输入任意采样率/声道 → 单声道 float32 → **24 kHz**（speaker_encoder_config.sample_rate）
  · **只拒全静音**；"有声但非语音"必须放过（g0-probe 的探测音频是 440Hz 纯音，
    若此处拒收，G0-a/G0-c 将恒定 4xx，永远无法取证 —— 见设计 §5.3 约束）
  · 有效语音时长只参与质量分计算，**不作拒收**（除非显式开启严格模式）
  · 音频只在请求期内存中存在，不落盘
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np

#: speaker encoder 的输入采样率（Base config: speaker_encoder_config.sample_rate）
TARGET_SR = 24000

#: 帧长与步长（毫秒）——能量法 VAD 的分析粒度
_FRAME_MS = 30.0
_HOP_MS = 10.0

#: 全静音判定的绝对能量下限（帧均方根）
_SILENCE_RMS = 1e-4

#: 语音帧相对噪声底的能量倍数门限
_SPEECH_OVER_NOISE = 3.0

#: 削波判定阈值（|x| >= 该值视为削波）
_CLIP_LEVEL = 0.99


@dataclass(frozen=True)
class AudioStats:
    """一段音频的技术统计量（不含任何可还原内容的信息）。"""

    duration_ms: int
    speech_duration_ms: int
    rms: float
    peak: float
    clipping_ratio: float
    snr_db: float
    quality: float

    @property
    def speech_ratio(self) -> float:
        if self.duration_ms <= 0:
            return 0.0
        return self.speech_duration_ms / self.duration_ms


class AudioDecodeError(Exception):
    """音频无法解码（对应 AUDIO_UNDECODABLE）。"""


def decode_audio(data: bytes) -> tuple[np.ndarray, int]:
    """解码任意音频 → (单声道 float32 数组, 原始采样率)。"""
    import soundfile as sf

    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    except Exception as exc:  # noqa: BLE001 - 统一转成解码失败
        raise AudioDecodeError(str(exc)) from exc
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return np.asarray(audio, dtype=np.float32), int(sr)


def resample_to_target(audio: np.ndarray, sr: int, target_sr: int = TARGET_SR) -> np.ndarray:
    """重采样到目标采样率（单声道 float32）。"""
    if sr == target_sr:
        return audio
    import librosa

    return librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=target_sr)


def _frame_rms(audio: np.ndarray, frame_len: int, hop_len: int) -> np.ndarray:
    """按帧计算均方根，返回每帧 rms。"""
    if audio.size < frame_len:
        return np.asarray([float(np.sqrt(np.mean(audio**2)))] if audio.size else [0.0], dtype=np.float32)
    n_frames = 1 + (audio.size - frame_len) // hop_len
    idx = np.arange(frame_len)[None, :] + hop_len * np.arange(n_frames)[:, None]
    frames = audio[idx]
    return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))


def analyze(audio: np.ndarray, sr: int = TARGET_SR) -> AudioStats:
    """计算时长、有效语音、削波率、信噪与复合质量分。

    质量分口径（设计 §5.4）：
        quality = clip(0.5·speechRatio + 0.3·snrConfidence + 0.2·(1-clippingRatio), 0, 1)
    """
    duration_ms = int(round(audio.size / sr * 1000)) if sr else 0
    if audio.size == 0:
        return AudioStats(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.abs(audio).max())
    clipping_ratio = float(np.mean(np.abs(audio) >= _CLIP_LEVEL))

    frame_len = max(1, int(sr * _FRAME_MS / 1000))
    hop_len = max(1, int(sr * _HOP_MS / 1000))
    frame_rms = _frame_rms(audio, frame_len, hop_len)

    if frame_rms.size == 0:
        speech_duration_ms = 0
        snr_db = 0.0
    else:
        # 噪声底取能量较低的分位数，避免整段静音把门限拉到 0
        noise_floor = float(np.percentile(frame_rms, 20.0))
        threshold = max(noise_floor * _SPEECH_OVER_NOISE, _SILENCE_RMS)
        speech_frames = frame_rms >= threshold
        speech_duration_ms = int(round(speech_frames.sum() * _HOP_MS))
        if speech_frames.any():
            speech_energy = float(np.mean(frame_rms[speech_frames]))
            noise_energy = float(np.mean(frame_rms[~speech_frames])) if (~speech_frames).any() else 0.0
            snr_db = 20.0 * float(np.log10(max(speech_energy, 1e-12) / max(noise_energy, 1e-12)))
        else:
            snr_db = 0.0
        snr_db = max(0.0, min(snr_db, 60.0))

    speech_ratio = speech_duration_ms / duration_ms if duration_ms else 0.0
    snr_confidence = min(1.0, snr_db / 30.0)
    quality = float(
        np.clip(0.5 * speech_ratio + 0.3 * snr_confidence + 0.2 * (1.0 - clipping_ratio), 0.0, 1.0)
    )

    return AudioStats(
        duration_ms=duration_ms,
        speech_duration_ms=speech_duration_ms,
        rms=rms,
        peak=peak,
        clipping_ratio=clipping_ratio,
        snr_db=snr_db,
        quality=quality,
    )


def is_silent(audio: np.ndarray, sr: int = TARGET_SR) -> bool:
    """全静音判定（唯一允许的音频级拒收理由）。"""
    if audio.size == 0:
        return True
    frame_len = max(1, int(sr * _FRAME_MS / 1000))
    hop_len = max(1, int(sr * _HOP_MS / 1000))
    frame_rms = _frame_rms(audio, frame_len, hop_len)
    if frame_rms.size == 0:
        return True
    return bool(np.max(frame_rms) < _SILENCE_RMS)


__all__ = [
    "TARGET_SR",
    "AudioDecodeError",
    "AudioStats",
    "analyze",
    "decode_audio",
    "is_silent",
    "resample_to_target",
]
