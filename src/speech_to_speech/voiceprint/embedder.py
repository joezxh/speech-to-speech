"""说话人嵌入提取器：从 pipeline 已加载的模型中提取说话人向量。

两条提取路径（docs/voiceprint-embedding-service-design-CN.md §3.5）：

  · 方案 A：复用 pipeline 已加载的 Qwen3-TTS 模型对象
    （Base 权重目录同时含 talker 与 `speaker_encoder.*`，**零额外权重加载、零额外显存**；
    但 Base 没有预设音色，TTS 必须走克隆路径 → 首音 37s，生产不可用）

  · 方案 C（**当前生产部署形态**）：独立加载从 Base 切出的 22.9 MiB encoder
    （`standalone.py`），TTS 继续用 CustomVoice 预设音色（首音 1.85s），
    不加载 talker、不占显存、不改变 TTS 行为

两条路径的调用契约**完全一致**（24kHz 波形 → 2048 维 L2 归一化向量）。

调用契约（读 qwen_tts 源码实测确认，勿凭猜）：
  `Qwen3TTSForConditionalGeneration.extract_speaker_embedding(audio, sr)`
    · audio：numpy float32 **一维**波形
    · sr   ：必须是 **24000**（内部 assert "Only support 24kHz audio"）
    · 内部：mel 频谱(n_fft=1024, num_mels=128, hop=256) → ECAPA-TDNN → 取 batch 0
    · 返回：形状 (enc_dim,) 的向量（Base 配置 enc_dim=2048；官方默认值是 192）

注意：**不能**直接调 `speaker_encoder.forward(...)` —— 它吃的是 mel 频谱
`(B, T, mel_dim)`，直接喂波形会抛
`IndexError: Dimension out of range (expected to be in range of [-1, 0], but got 1)`。
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import numpy as np

#: speaker encoder 的输入采样率（Base config: speaker_encoder_config.sample_rate）
TARGET_SR = 24000


class SpeakerEncoderUnavailable(RuntimeError):
    """模型对象里找不到可用的 speaker embedding 提取能力。"""


def _candidate_holders(model: Any) -> list[Any]:
    """按可能的封装层次展开候选对象（去重、保持顺序）。"""
    holders: list[Any] = []
    seen: set[int] = set()

    def push(obj: Any) -> None:
        if obj is None:
            return
        if id(obj) in seen:
            return
        seen.add(id(obj))
        holders.append(obj)

    push(model)
    for attr in ("model", "module", "net"):
        push(getattr(model, attr, None))
    for holder in list(holders):
        for attr in ("model", "module", "net"):
            push(getattr(holder, attr, None))
    return holders


def find_speaker_extractor(model: Any) -> Callable[..., Any] | None:
    """定位官方封装的 `extract_speaker_embedding(audio, sr)`。"""
    for holder in _candidate_holders(model):
        fn = getattr(holder, "extract_speaker_embedding", None)
        if callable(fn):
            return fn
    return None


def find_speaker_encoder(model: Any) -> Any:
    """定位底层 speaker encoder 模块（仅用于诊断：确认权重里带没带 encoder）。"""
    for holder in _candidate_holders(model):
        for attr in ("speaker_encoder", "spk_encoder", "speaker_encoder_model"):
            encoder = getattr(holder, attr, None)
            if encoder is not None and hasattr(encoder, "forward"):
                return encoder
    raise SpeakerEncoderUnavailable(
        "当前加载的 Qwen3-TTS 模型不含 speaker_encoder；"
        "请使用 Qwen3-TTS-12Hz-1.7B-Base 权重（CustomVoice 不含 encoder，见设计 F12/F13）"
    )


class SpeakerEmbedder:
    """把 24kHz 单声道音频转成 L2 归一化的说话人向量。

    线程安全：推理在调用方的锁内串行执行（与 ASR/TTS 共享 GPU，避免并发挤占）。
    """

    def __init__(self, tts_handler: Any | None = None, device: str | None = None) -> None:
        self._tts_handler = tts_handler
        self._device = device
        self._extractor: Callable[..., Any] | None = None
        self._encoder: Any | None = None
        self._dim: int | None = None
        self._model_id: str | None = None
        self._lock = threading.Lock()

    # ── 就绪与元信息 ────────────────────────────────────────────────────
    @property
    def ready(self) -> bool:
        """是否具备提取能力。

        方案 A（复用 TTS 模型对象的官方封装）与方案 C（独立加载的 encoder）
        **任一**可用即视为就绪 —— 早期版本只判 `_extractor`，导致方案 C 部署下
        capability 恒报 `ready=false`，而推理其实完全正常（会误伤调用端的门禁判断）。
        """
        return self._extractor is not None or self._encoder is not None

    @property
    def dim(self) -> int | None:
        """向量维度。

        启动期能读到配置则启动期给（避免冷启动首个 capability 请求返回 0）；
        否则在首次成功推理后确定。
        """
        return self._dim

    @property
    def model_id(self) -> str | None:
        return self._model_id

    @property
    def device(self) -> str | None:
        """推理设备（None 表示跟随 TTS 模型自身的设备）。"""
        return self._device

    def ensure_ready(self) -> None:
        """定位并缓存提取能力（幂等）。"""
        if self._extractor is not None or self._encoder is not None:
            return

        if self._tts_handler is None:
            raise SpeakerEncoderUnavailable("未绑定 TTS handler，无法复用模型对象")
        model = getattr(self._tts_handler, "model", None)
        if model is None:
            raise SpeakerEncoderUnavailable("TTS handler 尚未加载模型")

        extractor = find_speaker_extractor(model)
        if extractor is None:
            try:
                self._encoder = find_speaker_encoder(model)
                detail = "模型含 speaker_encoder 但缺少 extract_speaker_embedding 封装"
            except SpeakerEncoderUnavailable:
                detail = "模型既无 extract_speaker_embedding 也无 speaker_encoder"
            raise SpeakerEncoderUnavailable(
                f"{detail}；请使用 Qwen3-TTS-12Hz-1.7B-Base 权重（见设计 F12/F13）"
            )
        self._extractor = extractor
        self._model_id = self._describe_model(model)
        dim = self._model_dim(model)
        if dim:
            self._dim = dim

    @staticmethod
    def _model_dim(model: Any) -> int | None:
        """从模型配置里读出 speaker encoder 的输出维度（读不到返回 None）。

        方案 A 下 `SpeakerEmbedder.dim` 若只在首次推理后确定，冷启动时
        capability 会返回 `dim=0`；模型配置里带 `enc_dim`，用它做启动期定维。
        """
        cfg = getattr(model, "config", None)
        candidates = [cfg, getattr(cfg, "speaker_encoder_config", None)]
        for candidate in candidates:
            dim = getattr(candidate, "enc_dim", None)
            if isinstance(dim, int) and dim > 0:
                return dim
        return None

    @staticmethod
    def _describe_model(model: Any) -> str:
        """拼一个含版本信息的模型标识（供平台侧做漂移检查）。"""
        name = type(model).__name__
        revision = getattr(model, "_voiceprint_revision", None) or getattr(model, "revision", None)
        return f"{name}@{revision}" if revision else name

    def bind_standalone_encoder(
        self,
        encoder: Any,
        model_id: str | None = None,
        dim: int | None = None,
    ) -> None:
        """绑定独立加载的 speaker encoder（方案 C：不依赖 TTS 模型对象）。

        适用于：从 Base 权重切出的 22.9 MiB encoder 单独加载，
        TTS 继续用 CustomVoice（预设音色，首音 1.85s），两边互不影响。

        `dim` 为**启动期已知维度**（从切分目录的 `config.json` 读出），
        使 capability 在首次推理前也能给出真实维度；读不到则留 None，
        由首次推理确定。
        """
        self._encoder = encoder
        self._extractor = None
        self._model_id = model_id or self._model_id or "standalone-speaker-encoder"
        if dim:
            self._dim = int(dim)

    # ── 推理 ────────────────────────────────────────────────────────────
    def embed(self, audio_24k: np.ndarray) -> list[float]:
        """24kHz 单声道 float32 → L2 归一化向量。"""
        self.ensure_ready()
        import torch

        audio = np.asarray(audio_24k, dtype=np.float32).reshape(-1)

        with self._lock:
            if self._extractor is not None:
                with torch.inference_mode():
                    try:
                        output = self._extractor(audio=audio, sr=TARGET_SR)
                    except TypeError:
                        # 兼容位置参数签名 extract_speaker_embedding(audio, sr)
                        output = self._extractor(audio, TARGET_SR)
                vector = self._to_vector(output)
            else:
                # 方案 C：独立 encoder 路径（mel 频谱参数与官方实现一致）
                from speech_to_speech.voiceprint.standalone import embed_with_encoder

                vector = embed_with_encoder(self._encoder, audio)

        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 1e-12:
            raise RuntimeError("声纹向量无效（NaN 或零范数）")
        vector = vector / norm

        if self._dim is None:
            self._dim = int(vector.shape[0])
        elif int(vector.shape[0]) != self._dim:
            raise RuntimeError(
                f"声纹维度漂移：实测 {int(vector.shape[0])} != 启动期 {self._dim}"
            )
        return [float(x) for x in vector]

    @staticmethod
    def _to_vector(output: Any) -> np.ndarray:
        """把模型输出规整成一维向量。"""
        import torch

        if isinstance(output, (tuple, list)):
            output = output[0]
        if isinstance(output, dict):
            for key in ("embedding", "embeddings", "speaker_embedding", "x"):
                if key in output:
                    output = output[key]
                    break
            else:
                raise RuntimeError("speaker embedding 输出中找不到向量字段")
        if isinstance(output, torch.Tensor):
            output = output.detach().float().cpu().numpy()
        array = np.asarray(output, dtype=np.float32).reshape(-1)
        if array.size == 0:
            raise RuntimeError("speaker embedding 输出为空")
        return array


__all__ = [
    "TARGET_SR",
    "SpeakerEmbedder",
    "SpeakerEncoderUnavailable",
    "find_speaker_encoder",
    "find_speaker_extractor",
]
