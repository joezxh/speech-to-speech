# 方案④：本地 LLM Qwen3.5-4B + STT/TTS 同卡

## 概述
本地 llama.cpp 运行 **Qwen3.5-4B GGUF**。模型最小、推理最快、并发最高、延迟最低，但回答质量弱于 8B/9B。适合**量大、容错高**的客服/导览/问答场景，或预算极有限的边缘部署。

## 显存分配（单盒，同卡）
| 组件 | 显存（Q4_K_M） | 显存（Q8_0） | 显存（FP16） |
|---|---|---|---|
| STT (Qwen3-ASR FP16) | ~1.8GB | ~1.8GB | ~1.8GB |
| TTS (Qwen3-TTS FP16) | ~3.4GB | ~3.4GB | ~3.4GB |
| LLM (Qwen3.5-4B) | ~2.6GB | ~4.5GB | ~8GB |
| KV 缓存（8k, q8） | ~0.4GB | ~0.4GB | ~0.4GB |
| **小计** | **~8.2GB** | ~10.1GB | ~13.6GB |
| **建议显卡显存** | **12GB（够用）** | **16GB（舒适）** | **16GB** |

> 12GB 卡（如 RTX 5070）跑 4B-Q4 仅占 ~68%，余量充足，是本组**性价比最高**的选择。16GB 卡可上 Q8/FP16 或开更多并发。
> 本机实测：S2S + 4B Q4 同卡 = 11878 / 12227 MiB，余量仅 67 MiB——**"够用"是指单路跑得起来，不是能开多路**。

## 商品检索（条目与价格见采购清单）

| 档位 | 条目编号 | 显卡 | 显存 | 一句话理由 |
|---|---|---|---|---|
| 最低成本（12G） | `D-G04` | RTX 5070 12G | 12GB | 672 GB/s，4B Q4 下 1 路，12G 档延迟最低 |
| **推荐（16G）** | `D-G05` | RTX 5070 Ti 16G | 16GB | 896 GB/s，4B Q4 下 2 路，16G 档唯一能同机 2 路的高带宽组合 |
| 备选（16G） | `D-G02` | RTX 4060 Ti 16G | 16GB | 最便宜的 16G，4B Q4 下同样 2 路，但 288 GB/s 拖慢解码 |
| 高并发（24G） | `D-G06` | RTX 4090 24G | 24GB | 4B Q4 下 3 路同机 |
| 高并发（32G） | `D-G07` | RTX 5090 32G | 32GB | 1792 GB/s，4B Q4 下 5 路同机 |
| 边缘（待验证） | `D-E01` | Jetson Orin NX 16G | 16GB 统一 | 15–40W；能否跑一致性 ASR/TTS 见 `edge-box-feasibility.md` |

> 价格与商品条目详情见 [procurement-list.md](./procurement-list.md)（检索日期 2026-10-22，下单前复核）。

## 并发与性能估算

> 以下路数按 [performance-assumptions.md](./performance-assumptions.md) §4 公式推导（每路管线实测 ≈4.6GB），
> 含 LLM 同机时受槽位约束显著下降；原按吞吐给出的乐观值已标注为多盒模式上限。

```
可用显存 = 标称 − 2.6（4B Q4 权重） − 0.4（KV 8K / q8） − 0.8（余量）
槽位路数 = floor(可用显存 × 0.85 ÷ 4.6)
```

| 单盒显存 | 可用显存 | 槽位路数 |
|---|---|---|
| 12 GB | 8.2 GB | **1 路**（`floor(8.2×0.85÷4.6)` = 1.51 → 1，与假设表 §4 的 worked example 同一档） |
| 16 GB | 12.2 GB | **2 路** |
| 24 GB | 20.2 GB | **3 路** |
| 32 GB | 28.2 GB | **5 路** |
| 48 GB | 44.2 GB | **8 路** |

- **修订说明**：原估「12GB 15–25 路 / 16GB 20–30 路」未计 `num_pipelines` 的显存约束
  （每路独占一套 VAD/STT/LM/TTS handler，≈4.6GB），已按公式改写。
  **4B 是本组同机路数最高的档，但 12GB 卡仍然只有 1 路**——本机实测已证实（余量 67 MiB）。
- **吞吐侧**：4B 单流 ~120–150 tok/s，短回复仅 ~0.4–0.6s——这是**单路内**的生成耗时，与路数无关。
- 端到端 TTFA：见假设表 §5。4B 的 TTFT 最短，但 **700 ms 判停仍是预算中的最大单项**。

## 多盒拆分（高并发推荐）
- 架构同方案②：1× LLM 盒（`D-G05` / `D-G06` 跑 4B）+ N× 管线盒（`D-G04` 12G）。
- 管线盒侧：单盒 2 路（12G 纯管线），10 台 = 20 路。
- LLM 盒侧：4B 解码吞吐最高，单张 LLM 卡可服务的管线盒数明显多于 8B/9B；
  具体上限按 `acceptance-test-plan.md` T6 实测后回填。
- 详见 [deployment-multibox.md](./deployment-multibox.md)。

## 部署建议
- 单盒：`docker-compose.llm-bundled.yml`（本机已验证跑通）或 `docker-compose.llm-box.yml`；
  `llama` 服务 `-hf` 指向 `unsloth/Qwen3.5-4B-GGUF`，或本地已缓存的 `cache/qwen35-4b/Qwen3.5-4B-Q4_K_M.gguf`。
- llama.cpp 需 **≥ b8001**（qwen35 架构 2026-05 合入，旧版报 `unknown architecture`）。
- 4B 质量有限：可在 system prompt 限制回答长度、用 few-shot 提升稳定性；对质量敏感请选方案②/③。
- 边缘 Jetson 需先验证 ARM wheel 与 RTF（见 `edge-box-feasibility.md` §5.2 的 PoC 判定线）后再量产。

## 到货验收

- 到货后按 [acceptance-test-plan.md](./acceptance-test-plan.md) 执行 T0~T9，判定线见 [performance-assumptions.md](./performance-assumptions.md)。
- 本方案重点看 **T4（显存偏差）/ T6（4B 单流 tok/s 与 -np 吞吐）/ T5（并发阶梯）**。
