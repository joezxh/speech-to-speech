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

## 商品检索（1688 / 淘宝 / 京东，2026-10）
| 推荐盒子 | 显卡 | 显存 | 参考价 | 检索/商品 |
|---|---|---|---|---|
| 入门整机 | RTX 4060 Ti 16G | 16GB | 整机 ¥7,000–10,000（涡轮卡 ¥4,849） | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%204060Ti%2016G%20整机) / [什么值得买 涡轮卡](https://www.smzdm.com/p/184237068) |
| 主流整机 | RTX 5060 Ti 16G | 16GB | 卡 ¥4,599 / 整机 ~¥8,877 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205060Ti%2016G%20整机) / [aixplore 配置](https://aixplore.cc/posts/local-llm-hardware-requirements) |
| 主流整机 | RTX 5070 12G | 12GB | 整机 ¥6,000–8,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205070%2012G%20整机) |
| 边缘可选 | Jetson Orin NX 16G 盒子 | 16GB 统一 | ¥5,000–8,000 | [1688 检索](https://s.1688.com/selloffer/offer_search.htm?keywords=Jetson%20Orin%20NX%20边缘计算盒子) |

> 本地参考机即属此档（RTX 5070 / 5070 Ti）。**优先推荐 RTX 5060 Ti 16G 或 5070 12G 整机**：价格低、显存够、功耗小（150–250W）。

## 并发与性能估算
- **本机并发**：20–40 路实时语音会话（瓶颈在 STT/TTS 吞吐与回传带宽，不在 LLM）。
- **LLM 并发**：由远程 GPUStack 配额决定，本机不受限，可独立横向扩容。
- 端到端首响（TTFA）：受远程 LLM 网络 RT + 生成延迟影响，约 0.6–1.4s（局域网内远程 LLM 通常 +20–80ms）。

## 部署建议
- 直接用项目自带 `docker-compose.yml`（远程 LLM 版）即可，无需本地 llama.cpp。
- 先用本方案把整条管线跑通验证，再决定是否本地化 LLM（见方案②③④）。
- 边缘场景可用 Jetson Orin NX，但 Qwen3-TTS(torch)/Qwen3-ASR 在 ARM 上需验证 wheel 与性能，仅建议轻量 PoC。

## 备注
- 远程 LLM 端点建议走内网（如本机同网段 GPUStack），避免公网抖动。
- 若远程 LLM 偶发超时，pipeline 会走兜底文案，可参考项目记忆中的 S2S 慢/报错修复章节排查。
