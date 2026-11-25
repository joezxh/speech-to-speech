# src/speech_to_speech/livekit_worker/asr_provider.py（Task 6 临时骨架，Task 8 扩全）
"""可插拔 ASR Provider：把 PCM16 单声道音频段转成文本。"""
from __future__ import annotations

import io
import wave


class AsrProvider:
    """ASR Provider 抽象基类。"""

    def transcribe(self, pcm16_bytes: bytes, sample_rate: int, language: str = "auto") -> str:
        raise NotImplementedError


def _to_wav(pcm16_bytes: bytes, sample_rate: int) -> bytes:
    """把裸 PCM16 单声道数据包成 WAV 容器（16bit、单声道、指定采样率）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16_bytes)
    return buf.getvalue()
