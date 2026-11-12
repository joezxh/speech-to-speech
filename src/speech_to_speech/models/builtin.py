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
            status="planned",
            notes=(
                "MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型；"
                "同时承担 spec §6.4 路径 L 的 Breeze 替代位。"
                "官方代码仓库 LICENSE 为 Apache-2.0；权重许可已获取。"
                "项目定位为演示开源项目，商用部署所需的相关许可由实际应用方自行申请。"
                "status=planned 仅因适配层尚未实现（Spec B），不再是许可 gate。"
                "本仓 TTS/cosyvoice_handler.py 存在但未注册。"
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
    )
