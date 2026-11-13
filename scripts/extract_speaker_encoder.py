"""从 Qwen3-TTS-12Hz-1.7B-Base 的 safetensors 中切出 `speaker_encoder.*` 单独保存。

为什么需要它（docs/voiceprint-embedding-service-design-CN.md §3.5 方案 C）：
  Base 权重 = CustomVoice 权重 + 22.9 MiB 的 ECAPA-TDNN speaker encoder。
  方案 A（统一一份权重做 TTS + 声纹）实测**克隆路径首音 37s、RTF 0.03**，
  语音合成不可接受；而 CustomVoice 预设音色的首音是 1.85s、RTF 0.41。
  → 生产应当：TTS 继续用 CustomVoice，声纹只用切出来的 encoder（不加载 talker）。

用法：
    python scripts/extract_speaker_encoder.py \
        --model-dir cache/qwen3-tts-base \
        --out-dir cache/qwen3-speaker-encoder

产物：
    cache/qwen3-speaker-encoder/
      ├── speaker_encoder.safetensors   # 仅 speaker_encoder.* 张量
      └── config.json                   # speaker_encoder_config + 构造参数

安全性：脚本会校验
    · 输入权重里确有 speaker_encoder.*（否则说明不是 Base 权重）
    · 输出不含任何 talker.* 张量（避免误带入 3.8GB）
    · 全部张量能成功加载进 Qwen3TTSSpeakerEncoder（缺键即失败）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract speaker_encoder weights from a Qwen3-TTS Base checkpoint")
    ap.add_argument("--model-dir", required=True, help="Base 权重目录（含 model.safetensors 与 config.json）")
    ap.add_argument("--out-dir", required=True, help="输出目录")
    ap.add_argument("--dry-run", action="store_true", help="只检查不写盘")
    args = ap.parse_args()

    from safetensors import safe_open
    from safetensors.torch import save_file

    model_dir = Path(args.model_dir)
    out_dir = Path(args.out_dir)
    weights = model_dir / "model.safetensors"
    if not weights.is_file():
        print(f"ERROR: 未找到 {weights}", file=sys.stderr)
        return 2

    keep: dict[str, object] = {}
    total = 0
    with safe_open(str(weights), framework="pt") as f:
        for key in f.keys():
            if not key.startswith("speaker_encoder."):
                continue
            keep[key] = f.get_tensor(key)
            total += 1

    if total == 0:
        print(
            "ERROR: 该权重里没有 speaker_encoder.* —— 这不是 Base 权重"
            "（CustomVoice 不含 encoder；见设计 F12/F13）",
            file=sys.stderr,
        )
        return 3

    # 去掉模块前缀，得到 encoder 自身的 state_dict 键名
    stripped = {k[len("speaker_encoder.") :]: v for k, v in keep.items()}
    nbytes = sum(v.numel() * v.element_size() for v in stripped.values())
    print(f"提取到 {total} 个 speaker_encoder 张量，合计 {nbytes / 1024 / 1024:.1f} MiB")
    print(f"键名样例: {sorted(stripped)[:3]}")

    # 从原 config.json 取 speaker_encoder_config
    cfg_all = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    enc_cfg = dict(cfg_all.get("speaker_encoder_config") or {})
    if not enc_cfg:
        print(
            "ERROR: config.json 里没有 speaker_encoder_config —— 该权重不是 Base 变体",
            file=sys.stderr,
        )
        return 4

    if args.dry_run:
        print("dry-run：未写盘")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    save_file(stripped, str(out_dir / "speaker_encoder.safetensors"))
    (out_dir / "config.json").write_text(json.dumps(enc_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"已写入 {out_dir}")

    # 加载校验：必须能装进 Qwen3TTSSpeakerEncoder
    try:
        import torch
        from qwen_tts.core.models.configuration_qwen3_tts import Qwen3TTSSpeakerEncoderConfig
        from qwen_tts.core.models.modeling_qwen3_tts import Qwen3TTSSpeakerEncoder

        cfg = Qwen3TTSSpeakerEncoderConfig(**enc_cfg)
        model = Qwen3TTSSpeakerEncoder(cfg)
        missing, unexpected = model.load_state_dict(stripped, strict=False)
        if missing:
            print(f"ERROR: 缺少 {len(missing)} 个参数，例如 {missing[:3]}", file=sys.stderr)
            return 5
        print(f"加载校验通过（参数量 {sum(p.numel() for p in model.parameters()):,}）")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: 加载校验未完成: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
