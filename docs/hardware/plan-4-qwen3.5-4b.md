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

> 12GB 卡（如 RTX 5070）跑 4B-Q4 仅占 ~68%，余量充足，是本组**性价比与并发上限最高**的选择。16GB 卡可上 Q8/FP16 或开更多并发。

## 商品检索（1688 / 淘宝 / 京东，2026-10）
| 推荐盒子 | 显卡 | 显存 | 参考价 | 检索/商品 |
|---|---|---|---|---|
| 最低成本单盒（推荐） | RTX 5070 12G | 12GB | 整机 ¥6,000–8,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205070%2012G%20整机) |
| 舒适单盒（Q8/FP16，多并发） | RTX 5070 Ti 16G | 16GB | 卡 ¥13,398–13,949；整机 ~¥16,000–20,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205070Ti%2016G%20整机) |
| 备选入门 | RTX 4060 Ti 16G | 16GB | 整机 ¥7,000–10,000（涡轮卡 ¥4,849） | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%204060Ti%2016G%20整机) / [什么值得买](https://www.smzdm.com/p/184237068) |
| 边缘可选 | Jetson Orin NX 16G 盒子 | 16GB 统一 | ¥5,000–8,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=Jetson%20Orin%20NX%20边缘计算盒子) |

## 并发与性能估算
- **12GB 卡（4B-Q4）**：约 **15–25 路**实时会话。4B 单流 ~120–150 tok/s，短回复仅 ~0.4–0.6s 生成。
- **16GB 卡（4B-Q8/FP16）**：约 **20–30 路**，余量富余，可叠加 RAG/向量库。
- 端到端 TTFA：~0.4–0.9s（本组最低延迟）。

## 多盒拆分（高并发推荐）
- 架构同方案②：1× LLM 盒（5070 Ti / 4090 跑 4B）+ N× 管线盒（4060 Ti 16G）。
- 4B 吞吐极高，单张 LLM 卡可服务 **30+ 管线盒**，是规模化最省钱的配置。
- 详见 [deployment-multibox.md](./deployment-multibox.md)。

## 部署建议
- 单盒：`docker-compose.llm-box.yml` 的 `llama` 服务 `-hf` 换 `Qwen/Qwen3.5-4B-Instruct-GGUF`，或本地已缓存的 `Qwen3.5-4B-Q4_K_M.gguf`（项目原 compose 即此路径）。
- 4B 质量有限：可在 system prompt 限制回答长度、用 few-shot 提升稳定性；对质量敏感请选方案②/③。
- 边缘 Jetson 验证 ARM wheel 后再量产。
