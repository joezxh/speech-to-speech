# 方案①：LLM 走远程（与本地部署一致，仅本机跑 VAD+STT+TTS）

## 概述
本机只运行 **VAD（Silero）+ STT（Qwen3-ASR）+ TTS（Qwen3-TTS）** 三级流水线，LLM 使用远程 OpenAI 兼容端点（如本地 GPUStack 的 Qwen3-8B）。这是与当前 `docker-compose.yml` 完全一致的部署方式，也是成本最低、上线最快的方案。文本出域、音频与模型权重全程留在本机。

## 显存分配（单盒）
| 组件 | 显存 |
|---|---|
| VAD (Silero) | ~0.03GB（CPU） |
| STT (Qwen3-ASR FP16) | ~1.8GB |
| TTS (Qwen3-TTS FP16) | ~3.4GB |
| **管线小计** | **~5.2GB** |
| LLM（远程，不出本机显存） | 0 |
| **建议显卡显存** | **≥8GB，推荐 12–16GB** |

> 若把 STT/TTS 转为 INT8 量化，管线可压到 ~4GB，8GB 卡也能跑；但为保障 RTF<1 与流式稳定，优先 12GB+。
>
> **两个数字要分清**：上表 5.2 GB 是 FP16 权重的理论合计；实测整套 handler（含 tokenizer、vocoder、
> CUDA context）为 **4.6 GB（4633 MiB）**。本文所有路数推导用 4.6 GB，见 `performance-assumptions.md` §3.1。

## 商品检索（条目与价格见采购清单）

| 档位 | 条目编号 | 显卡 | 显存 | 一句话理由 |
|---|---|---|---|---|
| 入门 | `D-G01` | RTX 3060 12G | 12GB | 二手最低价，纯管线 2 路；适合先跑通再扩容 |
| 入门 | `D-G02` | RTX 4060 Ti 16G | 16GB | 最便宜的 16G；纯管线 2 路，但 288 GB/s 是本档短板 |
| 主流 | `D-G03` | RTX 5060 Ti 16G | 16GB | 448 GB/s，介于 `D-G02` 与 `D-G05` 之间；溢价期，仅作缺货替代 |
| **主流（推荐）** | `D-G04` | RTX 5070 12G | 12GB | 672 GB/s，纯管线 2 路，本方案最低延迟档 |
| 舒适 | `D-G05` | RTX 5070 Ti 16G | 16GB | 896 GB/s，纯管线 2 路且单路余量最富余 |
| 高密度 | `D-G06` | RTX 4090 24G | 24GB | 1008 GB/s，纯管线 4 路 |
| 高密度 | `D-S01` | NVIDIA L20 48G | 48GB | 纯管线 8 路，275W 数据中心卡 |
| 边缘（待验证） | `D-E01` | Jetson Orin NX 16G | 16GB 统一 | 15–40W，纯管线 2 路"槽位"；能否跑一致性 ASR/TTS 见 `edge-box-feasibility.md` |

> 价格与商品条目详情见 [procurement-list.md](./procurement-list.md)（检索日期 2026-10-22，下单前复核）。

> 本地参考机即属此档（RTX 5070 / 5070 Ti）。**优先推荐 `D-G04` 或 `D-G05`**：本方案不放 LLM，
> 12–16 GB 已足够开 2 路；预算应留给管线盒的**台数**而不是单卡规格。

## 并发与性能估算

> 以下路数按 [performance-assumptions.md](./performance-assumptions.md) §4 公式推导
> （每路管线实测 ≈4.6GB）。本方案 LLM 走远程，属于**纯管线盒**模式，不受 LLM 权重挤占。

| 单盒显存 | 可用显存 | 槽位路数 | 吞吐上限 | 实际路数 |
|---|---|---|---|---|
| 12 GB（`D-G01`/`D-G04`） | 12 GB | `floor(12×0.85÷4.6)` = **2** | 20–40 路 | **2 路** |
| 16 GB（`D-G02`/`D-G03`/`D-G05`） | 16 GB | `floor(16×0.85÷4.6)` = **2** | 20–40 路 | **2 路** |
| 24 GB（`D-G06`） | 24 GB | `floor(24×0.85÷4.6)` = **4** | 20–40 路 | **4 路** |
| 48 GB（`D-S01`/`D-S02`） | 48 GB | `floor(48×0.85÷4.6)` = **8** | 20–40 路 | **8 路** |

- **修订说明**：原估"本机并发 20–40 路"未计 `num_pipelines` 的显存约束——每路独占一套
  VAD/STT/LM/TTS handler（≈4.6GB），GPU 显存先于计算吞吐成为瓶颈。
  真正的 20–40 路需要 **10–20 台** 12 GB 纯管线盒堆叠。
- **LLM 并发**：由远程 GPUStack 配额决定，本机不受限，可独立横向扩容。
- **多盒总路数**：N 台纯管线盒 → `N × 单盒槽位路数`，瓶颈转移到远程 GPUStack 的并发配额。
- 端到端 TTFA：见假设表 §5 的预算分解（700 ms 判停 + STT 150–300 + LLM TTFT 150–300
  + TTS 100–200 + 杂项 50–100 ms）；**700 ms 判停占了预算的大头**。

## 部署建议
- 直接用项目自带 `docker-compose.yml`（远程 LLM 版）即可，无需本地 llama.cpp。
- 先用本方案把整条管线跑通验证，再决定是否本地化 LLM（见方案②③④⑤⑥）。
- 边缘场景可用 Jetson Orin NX，但 Qwen3-TTS(torch)/Qwen3-ASR 在 ARM 上需验证 wheel 与性能，仅建议轻量 PoC。
- **边缘盒（ARM）在本方案下同样受约束**：见 [edge-box-feasibility.md](./edge-box-feasibility.md)。
  该文档 §1.2 的 G1 门槛要求「必须能跑 PyTorch + transformers **原样权重**」——
  需转 RKNN / RKLLM / OM / OpenVINO IR / TensorRT engine 的盒子一律不合格（本项目不允许改 `src/`）。
  当前 10 款候选**无一具备「1.7B + FP16 + transformers」的实测**（HT3 待验证）。
  **若 ARM 盒跑不通一致的 Qwen3-ASR / Qwen3-TTS，则方案①在边缘也不成立**——
  不是「LLM 远程就没事」，因为 STT/TTS 仍然在本地加速卡上跑。

## 到货验收

- 到货后按 [acceptance-test-plan.md](./acceptance-test-plan.md) 执行 T0~T9，判定线见 [performance-assumptions.md](./performance-assumptions.md)。
- 本方案重点看 **T1（指纹一致）/ T2（RTF < 1.0）/ T3（单路 TTFA）/ T7（远程 LLM 网络侧）**；
  T6 本地 LLM 专项可跳过。

## 备注
- 远程 LLM 端点建议走内网（如本机同网段 GPUStack），避免公网抖动。
- 若远程 LLM 偶发超时，pipeline 会走兜底文案，可参考项目记忆中的 S2S 慢/报错修复章节排查。
