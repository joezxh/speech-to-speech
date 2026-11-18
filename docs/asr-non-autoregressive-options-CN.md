# 替换 Qwen3-ASR 的非自回归开源语音模型选型

> 背景：当前全双工链路的 STT 用 Qwen3-ASR-0.6B（自回归 `model.generate`），实测中文 RTF 0.47~0.90（p50 2.69s），是端到端延迟的最大头。本文盘点可替换的**非自回归（一次前向出全文）**开源模型，附官方/公开基准的效果数据、本仓替换成本，并给出推荐。
> 整理日期：2026-11-18。硬件基线：本机 RTX 5070 Ti Laptop 12GB。

## 1. 为什么非自回归能提速

- **自回归**（Qwen3-ASR、Whisper）：逐 token 生成，解码步数 ∝ 文本长度，音频越长越慢（当前 RTF 随音频时长 0.47→0.90 递增）。
- **非自回归**（NAR）：encoder 一次前向 + CTC/transducer 头一次性输出整句，解码步数基本恒定，RTF 与音频长度弱相关，通常能降一个数量级。

代价：NAR 一般在超长音频、极复杂重叠语音上略逊于大模型 LLM-ASR，但语音助手的短句场景（1~6s）影响很小。

## 2. 候选模型效果对比

### 2.1 权威基准（FunASR 官方，单张 H100，184 条长中文音频/192 分钟）

来源：FunASR 官方博客 `https://www.funasr.com/en/blog/funasr-vs-whisper-benchmark.html`，CER 去标点后计算，RTFx 越高越快。

| 模型 | 架构 | 设备 | RTFx（越高越快） | CER（越低越好） |
|---|---|---|---:|---:|
| **SenseVoice-Small** | NAR encoder+CTC | GPU | **169.6x** | **7.81%** |
| SenseVoice-Small | NAR encoder+CTC | CPU | 17.2x | 7.81% |
| Paraformer-Large | NAR | GPU | 119.6x | 10.18% |
| Fun-ASR-Nano | LLM-ASR（SenseVoice enc + Qwen3-0.6B） | GPU(vLLM) | 340x | 8.20% |
| Whisper-large-v3-turbo | 自回归 | GPU | 46.1x | 21.71% |
| Whisper-large-v3 | 自回归 | GPU | 13.4x | 20.02% |

结论：**中文场景下 SenseVoice-Small 比 Whisper-large-v3 快约 12 倍、CER 低约 2.5 倍**。注意这是 H100 数字，本机 5070 Ti 会整体慢几倍，但相对优势保持（NAR vs AR 的架构差是主要的）。

### 2.2 模型参数与能力（FunASR 官方模型页 + 公开资料）

| 模型 | 出品方 | 参数量 | 语言 | 是否非自回归 | 显存/部署 | 特点 |
|---|---|---:|---|---|---|---|
| **SenseVoice-Small** | 阿里通义 | 234M | 中/粤/英/日/韩（自动检测） | ✅ NAR encoder+单 CTC 头 | 约 1GB；FunASR / ONNX / GGUF(llama.cpp) 全支持 | 极快，附带情感+音频事件标签，ITN 数字/标点归一化 |
| **Paraformer-zh** | 阿里达摩院 | 220M | 中文、粤语 | ✅ NAR | 约 1GB；FunASR | 中文标点/精度强，工业级稳定 |
| Fun-ASR-Nano | 阿里通义 | 800M | 中/英/日+方言 | ❌ LLM-ASR（但 vLLM 加速极快） | 需 vLLM | 难例最强，精度/速度旗舰 |
| **FireRedASR-AED-L** | 小红书 | 约 1.1B | 普通话+20 方言+英语 | AED（encoder-decoder，部分变体 NAR） | 较大 | 中文公开榜 SOTA，支持歌唱歌词；非纯 NAR，速度优势不如 SenseVoice |
| Parakeet-TDT (nvidia) | NVIDIA | 600M | 25 种欧洲语言（**无中文**） | ✅ TDT transducer | NeMo | 英文强，中文不可用 |
| NeMo / Nemotron / Orukeet | NVIDIA | 600M~2.5B | 4~40 种 | ✅ transducer/CTC | NeMo | 企业级流式，中文需具体模型 |

> FireRedASR 的 "CER 0.57%" 是特定榜单/子集的最优值，不是通用测试集成绩，勿直接横向比较；其 AED 变体严格说不是纯 NAR，提速不如 SenseVoice 明显。

### 2.3 精度口径提醒

不同来源的 CER 不可直接比较——测试集差异巨大（AISHELL-1 近场朗读 vs WenetSpeech 会议远场/重叠/口音，同一模型可差数倍）。上表 2.1 的 FunASR 官方数据是同一测试集横评，可信度最高。项目内部验收线见 `docs/private-deployment-manual-CN.md:936`：**中文 CER ≤ 10%**。

## 3. 本仓替换成本（关键：部分已接线）

仓库 `src/speech_to_speech/STT/` 已内置多个非自回归后端，通过 `backend_registry.py:360-530` 的 `STT_BACKENDS` 映射，`s2s_pipeline.py:510` 按 `stt backend` 名实例化。

| 后端名 | 对应模型 | 非自回归 | 已接线 | 依赖 | 替换成本 |
|---|---|---|---|---|---|
| `sense-voice` | SenseVoiceSmall（FunASR AutoModel） | ✅ | ✅ 已注册（`sense_voice_handler.py:18`） | `funasr>=1.1.6` + modelscope | **低**：装 funasr + 下模型 + 改 3 个参数 |
| `paraformer` | paraformer-zh | ✅ | ✅ 已注册（`paraformer_handler.py:20`） | `funasr>=1.2.7` | **低**：同上，改 2 个参数 |
| `parakeet-tdt` | nvidia parakeet | ✅ | ✅ 已注册 | `nano-parakeet` | 低，但**不支持中文**，排除 |
| `parakeet-unified` / `nemotron-streaming` / `orukeet` | NeMo 系列 | ✅ | ✅ 已注册 | `nemo` | 中，中文支持有限 |
| `sensevoice`（另一份） | SenseVoiceSmall | ✅ | ❌ **死代码，未注册**（`upstream-diff-and-deployment-config.md:18,327-336`） | funasr | 不可用 |
| FireRedASR | — | 部分 | ❌ 需新写 handler | 自建 | 高 |
| Fun-ASR-Nano | — | ❌ LLM-ASR | ❌ 需新写 handler | vLLM | 高 |

当前 `.venv` 实测：**funasr / nemo / sensevoice 均未安装**（`transformers 5.18.0`、`torch 2.11.0+cu128` 已有）。因此最省事的两条路是先装 `funasr` 再用已接线的 `sense-voice` 或 `paraformer`。

配置示例（改 `config/prod.yaml` 的 stt 段，需重启 8765）：

```yaml
  stt:
    kind: stt
    backend: sense-voice          # 或 paraformer
    settings:
      sense_voice_stt_model_name: iic/SenseVoiceSmall
      sense_voice_stt_device: cuda
      sense_voice_stt_language: zh
```

依赖安装（`sense-voice` extra 见 `pyproject.toml` / `docs/upstream-diff-and-deployment-config.md:199`）：需联网装 `funasr`+`modelscope`，并下载 `iic/SenseVoiceSmall` 权重（约 1GB）到本地 `cache/`。当前离线环境需先打通网络。

## 4. 推荐

| 场景 | 推荐 | 理由 |
|---|---|---|
| **本语音助手（中文短句、要低延迟）** | **SenseVoice-Small**（`sense-voice` 后端） | NAR 极快（官方 H100 169.6x）、CER 7.81% 优于当前、已接线、附带 ITN 标点，234M 显存友好 |
| 中文精度优先、可容忍稍慢 | Paraformer-Large / paraformer-zh | 中文标点强、工业稳定，已接线 |
| 难例/方言、有 vLLM | Fun-ASR-Nano | 精度旗舰（CER 8.20%、340x），但需 vLLM + 新 handler，成本高 |
| 中文 SOTA 精度、不追求 NAR 速度 | FireRedASR-AED-L | 方言/歌唱强，但非纯 NAR、需新 handler |

**首选 SenseVoice-Small**：它在"速度（NAR）+ 中文精度（优于 Whisper）+ 本仓已接线 + 部署简单（FunASR/ONNX/GGUF 全支持）"四项上最均衡。落地前按 `docs/private-deployment-manual-CN.md` §8 用真实业务音频跑一次 CER + RTF 评测（仓库 `scripts/benchmark_stt.py` 不含 sense-voice，需补充或手工计时）。

## 5. 数据来源

- FunASR 官方基准：https://www.funasr.com/en/blog/funasr-vs-whisper-benchmark.html
- FunASR 官方模型页：https://www.funasr.com/models.html
- SenseVoice：https://github.com/FunAudioLLM/SenseVoice
- FireRedASR：https://huggingface.co/FireRedTeam/FireRedASR-AED-L
- 本仓后端盘点：`backend_registry.py:360-530`、`docs/model-combination-matrix-CN.md:103-122`、`docs/full-duplex-voice-pipeline-CN.md`
