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

## 商品检索（1688 / 淘宝 / 京东，2026-10）
| 推荐盒子 | 显卡 | 显存 | 参考价 | 检索/商品 |
|---|---|---|---|---|
| 最低成本单盒 | RTX 5070 Ti 16G | 16GB | 卡 ¥13,398–13,949（七彩虹/技嘉）；整机 ~¥16,000–20,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205070Ti%2016G%20整机) / [京东 技嘉](https://union-click.jd.com/jdc?e=&p=JF8BASsJK1olXwELUldaAUweBV8IGlsSXwYCXVZeC0kQC19MRANLAjZbERscSkAJHTdNTwcKBlMdBgABFksWA2gKG1scVQUBVllVFxJSXzI4S1hTA3VGNRs4cDFOURh7UDllA0ZeElJROE8RAGkMGloUXjYCVV9cCUIfCmcKK18TMwdsVFdYZktFUW8MS1oTWgMLUgpaC08nA244WjUVWw8GUl9fD3sWM28OE1gSWwUEV1tcCk4nA2cMK4y889CO8orkopylgV84K1glbTYCZF1tViUWBGkKGF0QDWheEwUGCANNAgEAElIRXAACZFxcCUkVM184WAF1H0ZANT8lUz5cQRdNbgF-IFBJFiY8bx5fVjdodVkXWmJhDB8gSypgcRpqX1tIAzYCZFlbCXsWMw) |
| 舒适单盒（推荐 Q8 / 长上下文） | RTX 4090 24G（涡轮） | 24GB | 涡轮卡 ¥30,681；单卡工作站整机 ¥22,000–28,000；服务器级整机 ¥45,000–55,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%204090%2024G%20整机) / [京东 涡轮卡](https://union-click.jd.com/jdc?e=&p=JF8BARQJK1olXDYCVV9eDksVAG4LGV8lGVlaCgFtUQ5SQi0DBUVNGFJeSwUIFxlJX3EIGloWWwYAV19eCk8IWipURmsLKnJlUBddYytNX2kIfj9UI112FyItBEcnB2kLHV8UXAcBZF5cCUoWCmcBE1klWQBsVTBdAU55A2YAEghHXAdVVVZZDU1HC18IGmteMwcyVW5dDkMUBGkLHVgXWQYFZF5VDHvAqsHel_3B5KzV5txtOHsUM184G2sWbVhsVVlbCUwSBjxmRxxOBgZKUAMzAEMfC2wOEmsXXAcAVm5tOAt_ChsLHx1HFARhNloafUpBamdQeV9GDlpWBCguASUVX2Z1cDMdCWV7PVojfxtOAC04G2slXDY) |
| 备选 | RTX 5080 16G | 16GB | 卡 ¥10,000–11,000；整机 ¥18,000–24,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205080%2016G%20整机) |

## 并发与性能估算
- **16GB 卡（Q4）**：约 **10–18 路**实时会话。Qwen3-8B Q4 在 5070 Ti 上单流 ~70–90 tok/s，短回复（60 token）~0.7–0.9s。
- **24GB 卡（Q8 / 长上下文）**：约 **12–20 路**，生成更稳定、长上下文不降频。
- 端到端 TTFA：~0.5–1.0s（同机 LLM，省去网络 RT）。

## 多盒拆分（高并发推荐）
- **1× LLM 盒（4090 24G 跑 Qwen3-8B Q8）+ N× 管线盒（4060 Ti 16G 跑 VAD/STT/TTS）**。
- LLM 盒经内网 `chat-completions` 供多管线盒，线性扩展到 **50+ 路**，比堆单卡更省钱。
- 详见 [deployment-multibox.md](./deployment-multibox.md)。

## 部署建议
- 单盒：用 `docker-compose.llm-bundled.yml`（已含 Qwen3-8B GGUF + 同机 pipeline）。
- 多盒：用 `docker-compose.llm-box.yml` + `docker-compose.pipeline-box.yml`（把 `LLM_BASE_URL` 指向 LLM 盒 IP）。
- 关闭 Qwen3 思考链（`--reasoning-budget 0` + `enable_thinking=false`）以降低语音延迟。
