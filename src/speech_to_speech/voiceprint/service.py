"""声纹嵌入服务（网关侧）：一次音频 → 一次说话人向量。

契约与边界见 docs/voiceprint-embedding-service-design-CN.md：
  · 网关**只做特征提取**，不做注册/验证/底库/比对，也不出任何身份结论
  · 音频只在请求期内存中存在，不落盘、不入库、不进日志
  · 失败一律返回机器可读错误码，**绝不**返回 200 + 空/零向量
  · 鉴权 fail-closed：未配置凭据时端点关闭（503），不匿名放行
  · 拒收策略只拒"全静音"；"有声但非语音"必须放过（G0 探测音频是 440Hz 纯音）
"""

from __future__ import annotations

import logging
import queue
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

import numpy as np

from speech_to_speech.voiceprint.embedder import (
    SpeakerEmbedder,
    SpeakerEncoderUnavailable,
)
from speech_to_speech.voiceprint.errors import (
    VoiceprintErrorCode,
    error_body,
    http_status,
)
from speech_to_speech.voiceprint.preprocess import (
    AudioDecodeError,
    analyze,
    decode_audio,
    is_silent,
    resample_to_target,
)

logger = logging.getLogger(__name__)


class VoiceprintRequestError(Exception):
    """携带机器可读错误码的请求失败。"""

    def __init__(self, code: VoiceprintErrorCode) -> None:
        super().__init__(code.value)
        self.code = code

    @property
    def status_code(self) -> int:
        return http_status(self.code)

    @property
    def body(self) -> dict[str, object]:
        return error_body(self.code)


class VoiceprintService:
    """说话人嵌入提取服务。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        max_audio_ms: int = 30000,
        max_bytes: int = 10 * 1024 * 1024,
        min_speech_ms: int = 800,
        strict_reject: bool = False,
        queue_capacity: int = 16,
        max_concurrency: int = 4,
        infer_timeout_ms: int = 3000,
        device: str | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model_name = (model_name or "").strip() or None
        self.max_audio_ms = int(max_audio_ms)
        self.max_bytes = int(max_bytes)
        self.min_speech_ms = int(min_speech_ms)
        self.strict_reject = bool(strict_reject)
        self.infer_timeout_ms = int(infer_timeout_ms)

        self._embedder = SpeakerEmbedder(device=device)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_concurrency)),
            thread_name_prefix="voiceprint",
        )
        self._slots = queue.Queue(maxsize=max(1, int(queue_capacity)))
        self._lock = threading.Lock()

    # ── 绑定已加载的 TTS 模型（方案 A：零额外权重加载）────────────────────
    def attach_pool(self, pool: Any, encoder_dir: str | None = None) -> None:
        """绑定提取能力。

        两种来源（按优先级）：
          1. **方案 C**：给定 `encoder_dir`（切分出来的 speaker encoder）→ 独立加载，
             不依赖 TTS 模型，TTS 保持 CustomVoice 预设音色（首音 1.85s）。
          2. **方案 A**：从 handler 池里找到 Qwen3-TTS handler 并复用其模型对象
             （Base 权重自带 encoder；但 TTS 必须走克隆路径，首音 37s，生产不可用）。

        绑定完成后立即做一次**预热**（见 `warmup`），把首请求的惰性成本前置到启动期。
        """
        handler = None
        for unit in pool or []:
            for candidate in getattr(unit, "handlers", None) or []:
                if type(candidate).__name__ == "Qwen3TTSHandler":
                    handler = candidate
                    break
            if handler is not None:
                break

        if handler is not None:
            self._embedder._tts_handler = handler

        if encoder_dir:
            from speech_to_speech.voiceprint.standalone import (
                load_standalone_encoder,
                read_encoder_dim,
            )

            encoder = load_standalone_encoder(encoder_dir, self._embedder.device or "cpu")
            self._embedder.bind_standalone_encoder(
                encoder,
                model_id=f"standalone-speaker-encoder@{Path(encoder_dir).name}",
                dim=read_encoder_dim(encoder_dir),
            )
            logger.info(
                "voiceprint: loaded standalone speaker encoder from %s (dim=%s)",
                encoder_dir,
                self._embedder.dim,
            )
            self.warmup()
            return

        if handler is not None:
            logger.info("voiceprint: bound to the loaded Qwen3-TTS model object")
            self.warmup()
        else:
            logger.warning("voiceprint: no Qwen3TTSHandler found in the pipeline pool")

    def warmup(self, *, seconds: float = 1.0, sample_rate: int = 16000) -> bool:
        """预热一次完整链路（解码 → 重采样 → 推理），返回是否成功。

        **为什么必须预热**：解码与重采样走 librosa/numba，**首次调用会触发 JIT 编译**，
        实测冷启动后首个请求耗时 **26.4s**（第二次起 <2s）。而 3s 的推理超时只覆盖
        `future.result(...)`，覆盖不到这段预处理 —— 表现为"首请求极慢、后续正常"。
        调用端（网关）通常只有 3~5s 超时，因此预热必须发生在**启动期**。

        预热音频用 440Hz 纯音（F11：非语音必须放过，不能用静音去触发拒收分支）。
        失败只记录告警，不影响服务可用性。
        """
        import io
        import math
        import struct
        import wave

        frames = max(1, int(sample_rate * seconds))
        pcm = b"".join(
            struct.pack(
                "<h", int(math.sin(2 * math.pi * 440.0 * i / sample_rate) * 6000)
            )
            for i in range(frames)
        )
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm)

        try:
            self.embed(buf.getvalue())
        except VoiceprintRequestError as exc:
            logger.warning("voiceprint: warmup rejected (%s)", exc.code.value)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("voiceprint: warmup failed: %s", type(exc).__name__)
            return False
        logger.info("voiceprint: warmup done")
        return True

    # ── 鉴权 ────────────────────────────────────────────────────────────
    def authorize(self, authorization: str | None) -> None:
        """校验 Bearer 凭据；未配置时 fail-closed。"""
        if not self.api_key:
            raise VoiceprintRequestError(VoiceprintErrorCode.AUTH_NOT_CONFIGURED)
        header = (authorization or "").strip()
        if not header.lower().startswith("bearer "):
            raise VoiceprintRequestError(VoiceprintErrorCode.UNAUTHORIZED)
        token = header[len("bearer ") :].strip()
        if not token or not secrets.compare_digest(token, self.api_key):
            raise VoiceprintRequestError(VoiceprintErrorCode.FORBIDDEN)

    # ── 探活 ────────────────────────────────────────────────────────────
    def capability(self) -> dict[str, object]:
        """能力信息：维度、模型标识、就绪状态。"""
        dim = 0
        model_id = self.model_name or ""
        ready = False
        try:
            self._embedder.ensure_ready()
            ready = self._embedder.ready
            dim = int(self._embedder.dim or 0)
            model_id = self._embedder.model_id or model_id
        except SpeakerEncoderUnavailable as exc:
            logger.warning("voiceprint: speaker encoder unavailable: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("voiceprint: capability probe failed: %s", type(exc).__name__)
        return {
            "dim": dim,
            "embedding_dim": dim,
            "model": model_id,
            "ready": ready,
            "device": getattr(self._embedder, "device", None) or "inherit",
            "maxAudioMs": self.max_audio_ms,
            "maxBytes": self.max_bytes,
        }

    # ── 主流程 ──────────────────────────────────────────────────────────
    def embed(
        self,
        data: bytes,
        *,
        model: str | None = None,
        purpose: str | None = None,
    ) -> dict[str, object]:
        """一次音频 → 一次向量。"""
        if self.model_name and model and model.strip() != self.model_name:
            raise VoiceprintRequestError(VoiceprintErrorCode.MODEL_MISMATCH)
        if not data:
            raise VoiceprintRequestError(VoiceprintErrorCode.INVALID_REQUEST)
        if len(data) > self.max_bytes:
            raise VoiceprintRequestError(VoiceprintErrorCode.AUDIO_TOO_LARGE)

        try:
            audio, sr = decode_audio(data)
        except AudioDecodeError as exc:
            raise VoiceprintRequestError(VoiceprintErrorCode.AUDIO_UNDECODABLE) from exc

        audio = resample_to_target(audio, sr)
        if len(audio) and len(audio) / 24000.0 * 1000.0 > self.max_audio_ms:
            raise VoiceprintRequestError(VoiceprintErrorCode.AUDIO_TOO_LONG)
        if is_silent(audio):
            raise VoiceprintRequestError(VoiceprintErrorCode.AUDIO_SILENT)

        stats = analyze(audio)
        if self.strict_reject:
            if stats.speech_duration_ms == 0:
                raise VoiceprintRequestError(VoiceprintErrorCode.SPEECH_NOT_DETECTED)
            if stats.speech_duration_ms < self.min_speech_ms:
                raise VoiceprintRequestError(VoiceprintErrorCode.AUDIO_TOO_SHORT)

        vector = self._infer(audio)

        return {
            "embedding": vector,
            "dim": len(vector),
            "model": self._embedder.model_id or self.model_name or "",
            "quality": round(float(stats.quality), 4),
            "speechDurationMs": int(stats.speech_duration_ms),
        }

    def _infer(self, audio: np.ndarray) -> list[float]:
        """在有界队列与并发上限内做推理。"""
        try:
            self._slots.put_nowait(1)
        except queue.Full:
            raise VoiceprintRequestError(VoiceprintErrorCode.QUEUE_FULL) from None

        try:
            future = self._executor.submit(self._embedder.embed, audio)
            try:
                return future.result(timeout=self.infer_timeout_ms / 1000.0)
            except FutureTimeoutError as exc:
                future.cancel()
                raise VoiceprintRequestError(VoiceprintErrorCode.INFERENCE_TIMEOUT) from exc
            except VoiceprintRequestError:
                raise
            except SpeakerEncoderUnavailable as exc:
                raise VoiceprintRequestError(VoiceprintErrorCode.MODEL_UNAVAILABLE) from exc
            except RuntimeError as exc:
                message = str(exc)
                if "维度漂移" in message:
                    raise VoiceprintRequestError(VoiceprintErrorCode.DIM_DRIFT) from exc
                logger.warning(
                    "voiceprint: inference failed (%s): %s",
                    type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                    message,
                )
                raise VoiceprintRequestError(VoiceprintErrorCode.INFERENCE_FAILED) from exc
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "voiceprint: inference failed (%s)", type(exc).__name__
                )
                raise VoiceprintRequestError(VoiceprintErrorCode.INFERENCE_FAILED) from exc
        finally:
            try:
                self._slots.get_nowait()
            except queue.Empty:  # pragma: no cover - 防御性
                pass

    # ── 生命周期 ────────────────────────────────────────────────────────
    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)


__all__ = [
    "VoiceprintRequestError",
    "VoiceprintService",
]
