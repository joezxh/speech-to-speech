# src/speech_to_speech/livekit_worker/asr_provider.py（完整替换）
"""可插拔 ASR Provider，双模式（spec §6）：

- ``gateway``（默认）：OpenAI 兼容 HTTP 转写（``POST {base}/v1/audio/transcriptions``），
  与源工程 QwenAsrProvider 行为一致。
- ``local``：复用 pipeline 已解析的本地 STT handler（不重复加载模型）。
  pipeline handler 的真实接口是 ``process(VADAudio) -> Iterator[STTOut]``（float32
  numpy 音频，16k），与 worker 的 ``transcribe_chunk(pcm16_bytes, sample_rate) -> str``
  契约不同，由 :class:`SttHandlerAdapter` 在注入点（``build_pipeline``）完成转换；
  ``LocalSttAsrProvider`` 只依赖 ``transcribe_chunk`` 契约，保持不变。
  实现期核对所选后端是否支持被 worker 线程并发调用，不支持时在文档标注限制。
"""
from __future__ import annotations

import io
import os
import wave

import numpy as np
import requests

from speech_to_speech.pipeline.messages import VADAudio


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


class SttHandlerAdapter:
    """把 pipeline STT handler 的真实接口适配成 worker 的 ``transcribe_chunk`` 契约。

    pipeline 侧契约（``BaseSTTHandler`` 子类，src/speech_to_speech/STT/*）：
    - ``process(vad_audio: VADAudio) -> Iterator[STTOut]``：整段音频进、生成器出
      ``Transcription``/``PartialTranscription``；空音频不产出。
    - ``vad_audio.audio`` 为 **float32** numpy 数组（16bit int8 幅度归一到 [-1, 1]），
      采样率取 pipeline VAD 的 ``vad_handler_kwargs.sample_rate``（默认 16000）。
    - ``turn_id``/``turn_revision`` 留 None：``BaseSTTHandler`` 的 speculative-turn
      门对 None 键恒放行，``turn_latency_store`` 缺失也安全（getattr None）。

    worker 侧契约：``transcribe_chunk(pcm16_bytes, sample_rate) -> str``（PCM16 单声道）。
    适配做三件事：PCM16 → float32 归一；worker 16k → handler 采样率线性重采样（纯
    numpy，不引入 scipy/torchaudio）；构造 ``mode="final"`` 的 ``VADAudio`` 并同步消费
    process 生成器，拼接全部产出文本。

    已知限制（spec §6 允许文档标注）：
    - 流式后端（``StatefulStreamingSTTHandler`` 等）的流式状态机以 turn_id/revision
      维护跨段上下文；worker 每段独立调用（键恒 None），不与 pipeline 会话共享流式
      上下文，逐段转写语义等于「final 整段」路径。
    - handler 同时被 pipeline ``run()`` 线程与 worker 线程调用时存在模型并发风险，
      取决于所选后端（契约说明见模块 docstring）。
    """

    def __init__(self, handler: object, sample_rate: int = 16000) -> None:
        self._handler = handler
        self._sample_rate = int(sample_rate)

    def _resample_to_handler_rate(self, audio: np.ndarray, source_rate: int) -> np.ndarray:
        """线性插值重采样（纯 numpy）；同采样率恒等返回。"""
        if source_rate == self._sample_rate or len(audio) == 0:
            return audio
        duration = len(audio) / source_rate
        target_len = max(1, int(duration * self._sample_rate))
        source_idx = np.linspace(0.0, len(audio) - 1, num=target_len)
        return np.interp(source_idx, np.arange(len(audio)), audio).astype(np.float32)

    def transcribe_chunk(self, pcm16_bytes: bytes, sample_rate: int) -> str:
        audio = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        audio = self._resample_to_handler_rate(audio, int(sample_rate))
        if len(audio) == 0:
            return ""
        vad_audio = VADAudio(audio=audio, mode="final")
        parts: list[str] = []
        for output in self._handler.process(vad_audio):
            # Transcription / PartialTranscription 均携带 text；其它产出类型忽略
            text = getattr(output, "text", None)
            if text:
                parts.append(str(text).strip())
        return "".join(parts)


def create_asr_provider(mode: str, stt_handler: object | None = None) -> AsrProvider:
    """按模式构造 provider；非法模式显式报错，不静默降级。"""
    normalized = (mode or "gateway").strip().lower()
    if normalized == "gateway":
        return GatewayAsrProvider()
    if normalized == "local":
        return LocalSttAsrProvider(stt_handler)
    raise ValueError(f"ASR mode 必须是 gateway|local；got {mode!r}")
