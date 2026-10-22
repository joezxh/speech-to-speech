# 方案③：本地 LLM Qwen3.5-9B + STT/TTS 同卡

## 概述
本地 llama.cpp 运行 **Qwen3.5-9B GGUF**，质量最高（优于 8B，接近 14B 档），但显存需求最大。适合对回答质量敏感、且需完全离线/数据不出域的场景。

## 显存分配（单盒，同卡）
| 组件 | 显存（Q4_K_M） | 显存（Q8_0） | 显存（FP16） |
|---|---|---|---|
| STT (Qwen3-ASR FP16) | ~1.8GB | ~1.8GB | ~1.8GB |
| TTS (Qwen3-TTS FP16) | ~3.4GB | ~3.4GB | ~3.4GB |
| LLM (Qwen3.5-9B) | ~5.7GB | ~9.8GB | ~18GB |
| KV 缓存（8k, q8） | ~0.7GB | ~0.7GB | ~0.7GB |
| **小计** | **~11.6GB** | **~15.7GB** | **~23.9GB** |
| **建议显卡显存** | **16GB（紧，需量化 STT/TTS）** | **24GB** | **32GB+** |

> 16GB 卡跑 9B-Q4 余量仅 ~4GB（占 73%），建议将 STT/TTS 量化到 INT8 以腾空间；追求稳定直接上 24GB（Q8）或 32GB（FP16）。

## 商品检索（条目与价格见采购清单）

| 档位 | 条目编号 | 显卡 | 显存 | 一句话理由 |
|---|---|---|---|---|
| 最低成本（24G） | `D-G06` | RTX 4090 24G | 24GB | 1008 GB/s，9B Q4 下 3 路同机，二手价已回落 |
| 舒适（32G） | `D-G07` | RTX 5090 32G | 32GB | 1792 GB/s，9B Q4 下 4 路同机 |
| **推荐（48G）** | `D-S01` | NVIDIA L20 48G | 48GB | 9B Q4 下 7 路同机，单路成本最低；275W |
| 备选（48G） | `D-S02` | RTX 5880 Ada 48G | 48GB | 同显存可上台式机箱，但贵 1–2 万 |
| 高密度（128G 统一） | `D-G08` | NVIDIA DGX Spark 128GB | 128GB 统一 / 273 GB/s | 槽位上限 20–22 路；带宽是真正瓶颈，**待验证** |

> 价格与商品条目详情见 [procurement-list.md](./procurement-list.md)（检索日期 2026-10-22，下单前复核）。

## 并发与性能估算

> 以下路数按 [performance-assumptions.md](./performance-assumptions.md) §4 公式推导（每路管线实测 ≈4.6GB），
> 含 LLM 同机时受槽位约束显著下降；原按吞吐给出的乐观值已标注为多盒模式上限。

```
可用显存 = 标称 − 5.7（9B Q4 权重） − 0.7（KV 8K / q8） − 0.8（余量）
槽位路数 = floor(可用显存 × 0.85 ÷ 4.6)
```

| 单盒显存 | 可用显存 | 槽位路数 |
|---|---|---|
| 12 GB | 4.8 GB | **0 路**（装不下：可用显存已低于单路 4.6GB 门槛） |
| 16 GB | 8.8 GB | **1 路** |
| 24 GB | 16.8 GB | **3 路** |
| 32 GB | 24.8 GB | **4 路** |
| 48 GB | 40.8 GB | **7 路** |

- **修订说明**：原估「24GB 10–18 路 / 32GB 12–20 路 / L20 48G 15–25 路」未计
  `num_pipelines` 的显存约束（每路独占一套 handler，≈4.6GB），已按公式改写。
  **9B 是本组最吃显存的档：12GB 卡直接装不下，16GB 只能 1 路。**
- **吞吐侧**：Qwen3.5-9B Q4 在 4090 上单流 ~55–70 tok/s——这是**单路内**的生成耗时，与路数无关。
- 端到端 TTFA：见假设表 §5（9B 生成略慢于 8B/4B，TTFT 项按可用档取值）。

## 多盒拆分（高并发推荐）
- **1× LLM 盒（`D-G07` 32G 或 `D-S01` 48G 跑 9B-Q4）+ N× 管线盒（`D-G04` 12G）**。
- 管线盒侧：单盒 2 路（12G 纯管线）。
- LLM 盒侧：9B 模型较重，单张 LLM 卡可服务的管线盒数量受**解码吞吐**约束而非显存；
  上限按 `acceptance-test-plan.md` T6 实测后回填。
- 详见 [deployment-multibox.md](./deployment-multibox.md)。

## 部署建议
- 单盒：`docker-compose.llm-box.yml` 的 `llama` 服务把 `-hf` 换成 `Qwen/Qwen3.5-9B-Instruct-GGUF`（或本地 GGUF 路径），管线盒 `LLM_MODEL` 同步。
- llama.cpp 需 **≥ b8001**（qwen35 架构 2026-05 合入，旧版报 `unknown architecture`）。
- 显存吃紧时优先量化 LLM（Q4/Q8）而非 STT/TTS，后者量化对音质影响更可见。
- L20 为数据中心卡，需机架/供电环境，个人或小规模优先 5090 整机。

## 到货验收

- 到货后按 [acceptance-test-plan.md](./acceptance-test-plan.md) 执行 T0~T9，判定线见 [performance-assumptions.md](./performance-assumptions.md)。
- 本方案重点看 **T4（显存偏差）/ T6（9B 单流 tok/s 与 -np 吞吐）/ T8（长跑热降频）**。
