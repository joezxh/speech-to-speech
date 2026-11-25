# src/speech_to_speech/livekit_worker/asr_provider.py（完整替换）
"""可插拔 ASR Provider，双模式（spec §6）：

- ``gateway``（默认）：OpenAI 兼容 HTTP 转写（``POST {base}/v1/audio/transcriptions``），
  与源工程 QwenAsrProvider 行为一致。
- ``local``：复用 pipeline 已解析的本地 STT handler（不重复加载模型）。
  handler 契约为 ``transcribe_chunk(pcm16_bytes, sample_rate) -> str``；
  实现期核对所选后端是否支持被 worker 线程并发调用，不支持时在文档标注限制。
"""
from __future__ import annotations

import io
import os
import wave

import requests


class AsrProvider:
    """ASR Provider 抽象基类。"""

    def transcribe(self, pcm16_bytes: bytes, sample_rate: int, language: str = "auto") -> str:
        raise NotImplementedError


def _to_wav(pcm16_bytes: bytes, sample_rate: int) -> bytes:
    """把裸 PCM16 单声道数据包成 WAV 容器（16bit、单声道、指定采样率）。纯函数。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16_bytes)
    return buf.getvalue()


class GatewayAsrProvider(AsrProvider):
    """OpenAI 兼容 ASR；base 取 ASR_BASE_URL（可选覆盖），默认 VOICE_GATEWAY_BASE_URL。"""

    def __init__(self) -> None:
        base = os.environ.get("ASR_BASE_URL") or os.environ.get("VOICE_GATEWAY_BASE_URL", "")
        if not base.strip():
            raise ValueError("VOICE_GATEWAY_BASE_URL（或 ASR_BASE_URL 覆盖）未配置（gateway 模式必需）")
        self.base = base.rstrip("/")
        self.model = os.environ.get("VOICE_ASR_MODEL", "qwen3-asr")

    def transcribe(self, pcm16_bytes: bytes, sample_rate: int, language: str = "auto") -> str:
        wav = _to_wav(pcm16_bytes, sample_rate)
        data = {"model": self.model}
        if language and language != "auto":
            data["language"] = language
        r = requests.post(
            f"{self.base}/v1/audio/transcriptions",
            files={"file": ("seg.wav", wav, "audio/wav")},
            data=data,
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("text", "")


class LocalSttAsrProvider(AsrProvider):
    """复用 pipeline 已解析的本地 STT handler。只依赖 transcribe_chunk 契约。"""

    def __init__(self, stt_handler: object) -> None:
        if stt_handler is None:
            raise ValueError("local ASR mode 需要 stt_handler（pipeline STT 后端实例）")
        self._handler = stt_handler

    def transcribe(self, pcm16_bytes: bytes, sample_rate: int, language: str = "auto") -> str:
        result = self._handler.transcribe_chunk(pcm16_bytes, sample_rate)
        return str(result or "")


def create_asr_provider(mode: str, stt_handler: object | None = None) -> AsrProvider:
    """按模式构造 provider；非法模式显式报错，不静默降级。"""
    normalized = (mode or "gateway").strip().lower()
    if normalized == "gateway":
        return GatewayAsrProvider()
    if normalized == "local":
        return LocalSttAsrProvider(stt_handler)
    raise ValueError(f"ASR mode 必须是 gateway|local；got {mode!r}")
