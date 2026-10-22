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

## 商品检索（1688 / 淘宝 / 京东，2026-10）
| 推荐盒子 | 显卡 | 显存 | 参考价 | 检索/商品 |
|---|---|---|---|---|
| 最低成本单盒（9B-Q4） | RTX 4090 24G（涡轮） | 24GB | 涡轮卡 ¥30,681；工作站整机 ¥22,000–28,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%204090%2024G%20整机) / [京东 涡轮卡](https://union-click.jd.com/jdc?e=&p=JF8BARQJK1olXDYCVV9eDksVAG4LGV8lGVlaCgFtUQ5SQi0DBUVNGFJeSwUIFxlJX3EIGloWWwYAV19eCk8IWipURmsLKnJlUBddYytNX2kIfj9UI112FyItBEcnB2kLHV8UXAcBZF5cCUoWCmcBE1klWQBsVTBdAU55A2YAEghHXAdVVVZZDU1HC18IGmteMwcyVW5dDkMUBGkLHVgXWQYFZF5VDHvAqsHel_3B5KzV5txtOHsUM184G2sWbVhsVVlbCUwSBjxmRxxOBgZKUAMzAEMfC2wOEmsXXAcAVm5tOAt_ChsLHx1HFARhNloafUpBamdQeV9GDlpWBCguASUVX2Z1cDMdCWV7PVojfxtOAC04G2slXDY) |
| 舒适单盒（9B-Q8/FP16，推荐） | RTX 5090 32G | 32GB | 卡 ~¥20,000（5090D 24G）；整机 ¥28,000–35,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205090%2032G%20整机) |
| 数据中心/长上下文/多并发 | NVIDIA L20 48G（单/双卡服务器） | 48GB | 双卡服务器 ¥103,999–137,999；单卡整机 ¥40,000–120,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=L20%2048G%20推理服务器) / [京东 双卡](https://union-click.jd.com/jdc?e=&p=JF8BASoJK1olXwUHUF9YDUgfAF8IGlsVXQUDUFtdDU4RAF9MRANLAjZbERscSkAJHTdNTwcKBlMdBgABFksWA28IGFoRWAYHUVheFxJSXzI4RRpUW1lUHRk_VDl3fBsLS1hPJXRYJFJROE8RAGkMGloUXjYCVV9cCUIfCmcKK18TMwdsVFdYZkMQU2daSwtCXgIGBF5bW00nA244WjUVXgECU1hfDXsWM28OE1gSWwUEV1tYC0wnA2cMK4y889CO8orkopylgV84K1glbTYCZF1tViUWBGkKGF0QDWheEwUGCANTRgEAElIRXQYDZFxcCUkVM184Wx5POl1DFl8tfgwRAxlwcltcJAJXXTogCS5lWWZmGVIROl9WCwQoYzRiWW59fhJjbQYyU1hcOEon) |

## 并发与性能估算
- **24GB 卡（9B-Q4）**：约 **10–18 路**。Qwen3.5-9B Q4 在 4090 上单流 ~55–70 tok/s。
- **32GB 卡（9B-Q8/FP16）**：约 **12–20 路**，长上下文（32k）与多轮并发更稳。
- **L20 48G**：单卡可同卡跑 9B(FP16)+管线+长 KV，约 **15–25 路**；双卡服务器可再翻倍或做张量并行。
- 端到端 TTFA：~0.6–1.2s（9B 生成略慢于 8B/4B）。

## 多盒拆分（高并发推荐）
- **1× LLM 盒（5090 32G 或 L20 48G 跑 9B-Q8/FP16）+ N× 管线盒（4060 Ti 16G）**。
- 9B 模型较重，单张 LLM 卡建议服务 15–25 个管线盒（受 LLM 吞吐上限约束，而非管线盒数量）。
- 详见 [deployment-multibox.md](./deployment-multibox.md)。

## 部署建议
- 单盒：`docker-compose.llm-box.yml` 的 `llama` 服务把 `-hf` 换成 `Qwen/Qwen3.5-9B-Instruct-GGUF`（或本地 GGUF 路径），管线盒 `LLM_MODEL` 同步。
- 显存吃紧时优先量化 LLM（Q4/Q8）而非 STT/TTS，后者量化对音质影响更可见。
- L20 为数据中心卡，需机架/供电环境，个人或小规模优先 5090 整机。
