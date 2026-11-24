"""Static model cards shipped with speech-to-speech.

These are metadata only. None of these cards loads weights or imports handlers.
"""

from __future__ import annotations

from speech_to_speech.model_registry import ModelCard


def builtin_model_cards() -> tuple[ModelCard, ...]:
    return (
        ModelCard(
            id="qwen3-asr-1.7b-hf",
            name="Qwen3-ASR-1.7B",
            kind="stt",
            version="1.7b-hf",
            provider="Alibaba Qwen",
            weight_format="safetensors",
            backend_name="qwen3-asr",
            repo_id="Qwen/Qwen3-ASR-1.7B-hf",
            min_vram_gb=1.8,
            status="available",
            notes="docs/hardware/performance-assumptions.md 实测口径；代码 help 另标约 4 GB。",
        ),
        ModelCard(
            id="qwen3-tts-1.7b-customvoice",
            name="Qwen3-TTS-12Hz-1.7B-CustomVoice",
            kind="tts",
            version="12hz-1.7b",
            provider="Alibaba Qwen",
            weight_format="safetensors",
            backend_name="qwen3",
            repo_id="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            min_vram_gb=3.4,
            status="available",
            notes="许可未核实，license=None。",
        ),
        ModelCard(
            id="qwen3.5-4b-transformers",
            name="Qwen3.5-4B (transformers)",
            kind="llm",
            version="3.5-4b",
            provider="Alibaba Qwen",
            weight_format="safetensors",
            backend_name="transformers",
            repo_id="Qwen/Qwen3.5-4B",
            min_vram_gb=8.0,
            status="available",
            notes="默认 FP16 约 8 GB；4bit NF4 约 2.1 GB。",
        ),
        ModelCard(
            id="breeze-tts-2",
            name="Breeze TTS 2",
            kind="tts",
            version="2",
            provider="BreezeBlue",
            weight_format="safetensors",
            backend_name="breeze-tts-2",
            repo_id="BreezeBlue/Breeze-TTS-2",
            min_vram_gb=7.7,
            license="BreezeBlue Research and Non-Commercial License",
            status="planned",
            notes=(
                "项目已取得 BreezeBlue 商业授权（2026-11-12 用户确认），可商用自托管 Breeze TTS 2 权重；"
                "官方权重许可证名仍为 BreezeBlue Research and Non-Commercial License，商用权来自单独商业授权。"
                "status=planned 仅因 Spec B 适配层尚未实现，不再是许可 gate。"
                "本列为官方 eager 显存 7.7 GiB；--fast-all 快路径 14.4 GiB 需 24 GB 卡，"
                "叠加 4.6 GB 管线后约 12.3 GB / 19 GB，可作商用部署预算参考。"
                "官方输出 24 kHz mono s16le PCM；本地流式 API 单并发、忙时 409；"
                "checkpoint 自带 audio_tokenizer；--revision 固定权重版本。"
                "路径 L（CosyVoice2）/ 路径 R（付费托管 API）为可选替代，不再是合规必需。"
            ),
        ),
        ModelCard(
            id="whisper-medium",
            name="Whisper-medium",
            kind="stt",
            version="medium",
            provider="OpenAI / MiniCPM-o 同源",
            weight_format="safetensors",
            backend_name="whisper",
            repo_id="openai/whisper-medium",
            status="planned",
            notes="MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型。",
        ),
        ModelCard(
            id="cosyvoice2",
            name="CosyVoice2",
            kind="tts",
            version="2",
            provider="Alibaba / MiniCPM-o 同源",
            weight_format="safetensors",
            backend_name="cosyvoice2",
            repo_id="FunAudioLLM/CosyVoice2-0.5B",
            status="available",
            notes=(
                "MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型；"
                "同时承担 spec §6.4 路径 L 的 Breeze 替代位。"
                "官方代码仓库 LICENSE 为 Apache-2.0；权重许可已获取。"
                "项目定位为演示开源项目，商用部署所需的相关许可由实际应用方自行申请。"
                "backend_registry.py 已注册 cosyvoice2 后端，handler 位于 TTS/cosyvoice_handler.py。"
            ),
        ),
        ModelCard(
            id="minicpm-homologous-qwen3-8b",
            name="Qwen3-8B（MiniCPM-o 同源 LLM）",
            kind="llm",
            version="3-8b",
            provider="Alibaba Qwen / MiniCPM-o 同源",
            weight_format="safetensors",
            backend_name="transformers",
            repo_id="Qwen/Qwen3-8B",
            min_vram_gb=16.0,
            status="planned",
            notes="MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型；Q8 约 8.5 GB / Q4 约 5.0 GB。",
        ),
        ModelCard(
            id="minicpm-2b",
            name="MiniCPM-2B",
            kind="llm",
            version="2b",
            provider="OpenBMB",
            weight_format="safetensors",
            backend_name="transformers",
            min_vram_gb=1.2,
            status="planned",
            notes="可选；docs/models.md 的 2B Q4 估值。repo_id 待 Spec B 核实后补。",
        ),
        ModelCard(
            id="minicpm-4b",
            name="MiniCPM-4B",
            kind="llm",
            version="4b",
            provider="OpenBMB",
            weight_format="safetensors",
            backend_name="transformers",
            status="planned",
            notes="可选；repo_id 与显存待 Spec B 核实后补。",
        ),
        ModelCard(
            id="voxcpm2-2b",
            name="VoxCPM2 2B",
            kind="tts",
            version="2b",
            provider="OpenBMB",
            weight_format="safetensors",
            backend_name="voxcpm",
            repo_id="openbmb/VoxCPM2",
            default_load_params={"voxcpm_tts_model_name": "openbmb/VoxCPM2"},
            min_vram_gb=8.0,
            license="Apache-2.0",
            status="available",
            notes=(
                "原生 48 kHz 输出，由 handler 重采样到管线 16 kHz；支持 30 种语言与 9 种中文方言；"
                "voxcpm 库要求 Python < 3.13。官方推荐显存 8 GB，叠加约 4.6 GB 管线建议 ≥ 16 GB。"
            ),
        ),
        ModelCard(
            id="voxcpm1.5-0.8b",
            name="VoxCPM1.5 0.8B",
            kind="tts",
            version="0.8b",
            provider="OpenBMB",
            weight_format="safetensors",
            backend_name="voxcpm",
            repo_id="openbmb/VoxCPM1.5",
            default_load_params={"voxcpm_tts_model_name": "openbmb/VoxCPM1.5"},
            license="Apache-2.0",
            status="available",
            notes=(
                "需求中的 VoxCPM2 0.8B 实际为 VoxCPM1.5，约 0.8B；原生 44.1 kHz 输出经 handler 重采样到 16 kHz；"
                "显存官方未给出；voxcpm 库要求 Python < 3.13。"
            ),
        ),
        ModelCard(
            id="voxcpm-0.5b",
            name="VoxCPM 0.5B",
            kind="tts",
            version="0.5b",
            provider="OpenBMB",
            weight_format="safetensors",
            backend_name="voxcpm",
            repo_id="openbmb/VoxCPM-0.5B",
            default_load_params={"voxcpm_tts_model_name": "openbmb/VoxCPM-0.5B"},
            license="Apache-2.0",
            status="available",
            notes=(
                "需求中的 VoxCPM2 0.5B 实际为 VoxCPM-0.5B，约 0.5B；原生 16 kHz 输出与管线一致；"
                "显存官方未给出；voxcpm 库要求 Python < 3.13。"
            ),
        ),
        ModelCard(
            id="minicpm-o-2-6",
            name="MiniCPM-o 2.6",
            kind="llm",
            version="2.6",
            provider="OpenBMB",
            weight_format="safetensors",
            backend_name="minicpm-o",
            repo_id="openbmb/MiniCPM-o-2_6",
            license="MiniCPM Model License",
            status="planned",
            notes=(
                "8B 全模态模型（SigLIP-400M + Whisper-medium-300M + ChatTTS-200M + Qwen2.5-7B），"
                "不是独立 TTS/STT/LLM 后端，需要 trust_remote_code；本仓仅登记元信息，不提供运行适配。"
            ),
        ),
    )
