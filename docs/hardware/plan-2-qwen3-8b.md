# 方案②：本地 LLM Qwen3-8B + STT/TTS 同卡

## 概述
在方案①的管线基础上，把 LLM 从远程改为**本机 llama.cpp 运行 Qwen3-8B GGUF**（`docker-compose.llm-bundled.yml` 同款），完全自包含、断网可用、数据零出域。质量与本地体验优于远程，成本适中。

## 显存分配（单盒，同卡）
| 组件 | 显存（Q4_K_M） | 显存（Q8_0） |
|---|---|---|
| STT (Qwen3-ASR FP16) | ~1.8GB | ~1.8GB |
| TTS (Qwen3-TTS FP16) | ~3.4GB | ~3.4GB |
| VAD (Silero, CPU) | ~0.03GB | ~0.03GB |
| LLM (Qwen3-8B Q4_K_M) | ~5.0GB | — |
| LLM (Qwen3-8B Q8_0) | — | ~8.5GB |
| KV 缓存（8k 上下文, q8） | ~0.6GB | ~0.6GB |
| **小计** | **~11GB** | **~14.3GB** |
| **建议显卡显存** | **16GB（Q4 紧）/ 24GB（Q8 舒适）** | **24GB** |

> 16GB 卡跑 Q4 余量约 5GB（占 70%），可接受；若开启长上下文或多轮并发建议直接上 24GB。Q8 在 16GB 卡上会打满，必须 24GB。

## 商品检索（条目与价格见采购清单）

| 档位 | 条目编号 | 显卡 | 显存 | 一句话理由 |
|---|---|---|---|---|
| 最低成本（16G） | `D-G05` | RTX 5070 Ti 16G | 16GB | 896 GB/s，16G 档带宽最高；8B Q4 + 1 路管线刚好放下 |
| 备选（16G） | `D-G02` | RTX 4060 Ti 16G | 16GB | 最便宜的 16G，但 288 GB/s 拖慢 8B 解码 |
| 备选（16G） | `D-G03` | RTX 5060 Ti 16G | 16GB | 448 GB/s；溢价期，仅作缺货替代 |
| **推荐（24G）** | `D-G06` | RTX 4090 24G | 24GB | 1008 GB/s，8B Q4 下 3 路同机 |
| 高并发（32G） | `D-G07` | RTX 5090 32G | 32GB | 1792 GB/s，8B Q4 下 4 路同机 |
| 高密度（48G） | `D-S01` | NVIDIA L20 48G | 48GB | 8B Q4 下 7 路同机 |

> 价格与商品条目详情见 [procurement-list.md](./procurement-list.md)（检索日期 2026-10-22，下单前复核）。

## 并发与性能估算

> 以下路数按 [performance-assumptions.md](./performance-assumptions.md) §4 公式推导（每路管线实测 ≈4.6GB），
> 含 LLM 同机时受槽位约束显著下降；原按吞吐给出的乐观值已标注为多盒模式上限。

```
可用显存 = 标称 − 5.0（8B Q4 权重） − 0.6（KV 8K / q8） − 0.8（余量）
槽位路数 = floor(可用显存 × 0.85 ÷ 4.6)
```

| 单盒显存 | 可用显存 | 槽位路数 |
|---|---|---|
| 12 GB | 5.6 GB | **1 路**（本机实测 4B Q4 已占 11.6/12GB，8B 实际会超；不推荐） |
| 16 GB | 9.6 GB | **1 路** |
| 24 GB | 17.6 GB | **3 路** |
| 32 GB | 25.6 GB | **4 路** |
| 48 GB | 41.6 GB | **7 路** |

- **修订说明**：原估「16GB 10–18 路 / 24GB 12–20 路」未计 `num_pipelines` 的显存约束
  （每路独占一套 VAD/STT/LM/TTS handler，≈4.6GB），已按公式改写。
  **同机跑 8B 时单盒最多 3 路**（24GB 档）。
- **吞吐侧**：Qwen3-8B Q4 在 5070 Ti 上单流 ~70–90 tok/s，短回复（60 token）~0.7–0.9s——
  这是**单路内**的生成耗时，与路数无关。
- 端到端 TTFA：见假设表 §5。同机 LLM 省去网络往返（HA2 的 10–80 ms），但 700 ms 判停仍占预算大头。

## 多盒拆分（高并发推荐）
- **1× LLM 盒（`D-G06` 24G 跑 Qwen3-8B Q4）+ N× 管线盒（`D-G04` 12G 跑 VAD/STT/TTS）**。
- 管线盒侧：单盒 2 路（12G 纯管线），10 台 = 20 路。
- LLM 盒侧：受 8B 解码吞吐约束，上限按 `acceptance-test-plan.md` T6 实测后回填；
  系统总路数取两者较小值。要突破 LLM 侧，换 `D-G07` / `D-S01`，或加第二台 LLM 盒。
- 详见 [deployment-multibox.md](./deployment-multibox.md)。

## 部署建议
- 单盒：用 `docker-compose.llm-bundled.yml`（已含 Qwen3-8B GGUF + 同机 pipeline）。
- 多盒：用 `docker-compose.llm-box.yml` + `docker-compose.pipeline-box.yml`（把 `LLM_BASE_URL` 指向 LLM 盒 IP）。
- 关闭 Qwen3 思考链（`--reasoning-budget 0` + `enable_thinking=false`）以降低语音延迟。

## 到货验收

- 到货后按 [acceptance-test-plan.md](./acceptance-test-plan.md) 执行 T0~T9，判定线见 [performance-assumptions.md](./performance-assumptions.md)。
- 本方案重点看 **T4（显存偏差 ≤1.15）/ T5（并发阶梯与饱和点）/ T6（本地 LLM 吞吐）**。
