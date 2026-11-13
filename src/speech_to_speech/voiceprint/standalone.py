"""独立加载切分出来的 speaker encoder（方案 C）。

背景（docs/voiceprint-embedding-service-design-CN.md §3.5）：
  方案 A 用一份 Base 权重同时做 TTS 与声纹，功能成立、声纹性能达标（P95 258ms），
  但 **Base 没有预设音色**，TTS 必须走参考音频克隆路径，而实测该路径首音 37s、
  RTF 0.03（CustomVoice 预设音色是 1.85s / 0.41）→ 语音合成不可接受。
  方案 C 因此改为：TTS 继续用 CustomVoice，声纹只加载切出来的 22.9 MiB encoder
  （不加载 talker，不占显存，不改变 TTS 行为）。

本模块提供：
  · load_standalone_encoder(dir, device)  —— 加载切分权重 + 构造模型
  · embed_with_encoder(encoder, audio)   —— 24kHz 波形 → L2 归一化向量
    其 mel 参数与官方 `extract_speaker_embedding` 完全一致
    (n_fft=1024, num_mels=128, hop=256, win=1024, fmin=0, fmax=12000)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

#: 官方 `extract_speaker_embedding` 的 mel 参数（勿随意改动）
MEL_N_FFT = 1024
MEL_NUM_MELS = 128
MEL_HOP_SIZE = 256
MEL_WIN_SIZE = 1024
MEL_FMIN = 0
MEL_FMAX = 12000


def load_standalone_encoder(directory: str | Path, device: str = "cpu") -> Any:
    """加载切分出来的 speaker encoder（返回已 eval 的模块）。"""
    import torch
    from safetensors.torch import load_file
    from qwen_tts.core.models.configuration_qwen3_tts import Qwen3TTSSpeakerEncoderConfig
    from qwen_tts.core.models.modeling_qwen3_tts import Qwen3TTSSpeakerEncoder

    path = Path(directory)
    cfg_path = path / "config.json"
    weights_path = path / "speaker_encoder.safetensors"
    if not cfg_path.is_file() or not weights_path.is_file():
        raise FileNotFoundError(
            f"缺少切分权重: {cfg_path} / {weights_path}；"
            "请先运行 scripts/extract_speaker_encoder.py"
        )

    cfg = Qwen3TTSSpeakerEncoderConfig(**json.loads(cfg_path.read_text(encoding="utf-8")))
    model = Qwen3TTSSpeakerEncoder(cfg)
    state = load_file(str(weights_path))
    model.load_state_dict(state, strict=True)
    model.eval()
    model.to(torch.device(device))
    return model


def read_encoder_dim(directory: str | Path) -> int | None:
    """从切分目录的 `config.json` 读出向量维度 `enc_dim`（读不到返回 None）。

    用途：**启动期定维**。`Qwen3TTSSpeakerEncoder` 并不保留 `config` 属性，
    而 `SpeakerEmbedder.dim` 原本只在首次推理后才有值 —— 冷启动时首个
    capability 请求会拿到 `dim=0`。切分目录里的 `config.json` 是启动期
    唯一的可靠来源。
    """
    path = Path(directory) / "config.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    dim = cfg.get("enc_dim")
    return int(dim) if isinstance(dim, int) and dim > 0 else None


def embed_with_encoder(encoder: Any, audio_24k: np.ndarray) -> np.ndarray:
    """24kHz 单声道波形 → 说话人向量（未归一化）。"""
    import torch
    from qwen_tts.core.models.modeling_qwen3_tts import mel_spectrogram

    audio = np.asarray(audio_24k, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        raise ValueError("空音频")

    device = next(encoder.parameters()).device
    dtype = next(encoder.parameters()).dtype
    mels = mel_spectrogram(
        torch.from_numpy(audio).unsqueeze(0),
        n_fft=MEL_N_FFT,
        num_mels=MEL_NUM_MELS,
        sampling_rate=24000,
        hop_size=MEL_HOP_SIZE,
        win_size=MEL_WIN_SIZE,
        fmin=MEL_FMIN,
        fmax=MEL_FMAX,
    ).transpose(1, 2)
    with torch.inference_mode():
        vector = encoder(mels.to(device).to(dtype))[0]
    return vector.detach().float().cpu().numpy().reshape(-1)


__all__ = [
    "MEL_FMAX",
    "MEL_FMIN",
    "MEL_HOP_SIZE",
    "MEL_N_FFT",
    "MEL_NUM_MELS",
    "MEL_WIN_SIZE",
    "embed_with_encoder",
    "load_standalone_encoder",
    "read_encoder_dim",
]
