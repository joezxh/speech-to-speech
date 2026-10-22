# Speech-to-Speech 算力盒子选型与部署手册

> 适用对象：`speech-to-speech-src` 的 VAD→STT→LLM→TTS 实时语音流水线
> 定价日期：**2026-10**（来自 1688 / 淘宝 / 京东检索，价格随行情波动，下单前请复核）
> 本地基线参考机：**RTX 5070 / 5070 Ti（12–16GB 档）**，仅跑 VAD+STT+TTS，LLM 走远程

本目录给出 4 种 LLM 部署方案的完整选型结果，并附「多盒 + 内网 LLM 端点」部署清单。

## 组件与显存基线（与本地部署一致）

| 组件 | 模型 | 部署方式 | GPU 显存占用 |
|---|---|---|---|
| VAD | Silero VAD v5 | ONNX / CPU | 可忽略（~30MB） |
| STT | **Qwen3-ASR**（`qwen3-asr-model-hf`，FP16） | transformers / CUDA | ~1.8GB（FP16），量化 0.6–1.0GB |
| TTS | **Qwen3-TTS**（torch backend / cuda，1.7B） | transformers / CUDA | ~3.4GB（FP16），INT8 ~2GB |
| LLM | 远程 GPUStack（Qwen3-8B）/ 或本地 GGUF | 网络 / llama.cpp | 见各方案 |

**管线常驻（STT+TTS+VAD）≈ 6–9GB（FP16）/ 4–5GB（量化）**。下文均按「FP16 管线 + 量化 LLM」估算，留 15–20% 余量防降频。

### 本机实测（RTX 5070 Ti Laptop 12GB，2026-10-22）

> 实测环境：`docker-compose.local.yml`（VAD+STT+TTS 全 GPU，LLM 走远程）与
> `docker-compose.llm-bundled.yml`（VAD+STT+TTS 全 GPU + 本机 llama.cpp 服务 Qwen3.5-4B Q4）。
> `nvidia-smi` 实测，非理论估算。

| 项 | 数值 |
|---|---|
| GPU | RTX 5070 Ti Laptop GPU |
| 总显存 | 12227 MiB（≈12GB） |
| S2S 单独（VAD+STT+TTS 全 GPU） | ≈ 4633 MiB（≈4.6GB） |
| **S2S + 本地 4B Q4 LLM 同卡** | **≈ 11878 MiB（≈11.6GB），仅余 ~67 MiB** |

> 实测结论：12GB 卡上 S2S 与本地 LLM 共存时，**Qwen3.5-4B Q4 已把显存吃到 ~11.6GB（临界）**。
> 即 4B Q4 是 12GB 卡上"还能放下"的最大现实选择；8B/9B 即使走 Q4 也会超 12GB。
> 本机另开 LM Studio 时若加载模型，会与上述两者争抢同一张 12GB 卡。

**同卡本地 LLM 容量（实测修正）**：

| 方案 | 与 S2S 共存是否可行 | 说明 |
|---|---|---|
| Qwen3.5-4B Q4（实测） | ✅ 勉强（~11.6/12GB，余量≈0） | 已验证可跑通（见下） |
| Qwen3-8B Q4（比 4B 多 ~1.8GB 权重+KV） | ❌ 超 12GB | 需 ≥24GB 或把 S2S 拆到别的盒子/CPU |
| Qwen3.5-9B Q4（比 4B 多 ~2.5GB） | ❌ 超 12GB | 同上 |
| 任意 Q8 / FP16 | ❌ 更超 | 8B Q8 本身 ~8.8GB，加 S2S 远超 12GB |

**结论**：本机 12GB 卡上，本地 LLM 只能选 **Qwen3.5-4B Q4**，且**无并发余量**（`--num_pipelines>1` 不可行，每路再吃 ≈4.6GB）。
要本地跑 8B/9B（哪怕 Q4）或开多并发，必须上 ≥24GB 卡（如 RTX 4090）或按 `deployment-multibox.md` 把 S2S 与 LLM 拆到不同盒子。

**验证记录（2026-10-22）**：`docker-compose.llm-bundled.yml` 改造为用主机 LM Studio 自带的 CUDA `llama-server.exe` 服务本地已缓存的
`./cache/qwen35-4b/Qwen3.5-4B-Q4_K_M.gguf`，pipeline 经 `host.docker.internal:8080` 访问。
启动后：llama-server `GET /v1/models` 返回 `Qwen3.5-4B-Instruct-GGUF`（Q4_K_M，4.2B）；
pipeline `ChatCompletionsApiModelHandler` warmup 收到 `HTTP 200`；`Application startup complete`、
`Uvicorn running on :8765`、`OpenAI Realtime API starting on ws://0.0.0.0:8765/v1/realtime`。**全链路跑通。**
（注：ghcr.io 的 `llama.cpp:server-cuda` 镜像在本机网络被限速，故改用主机 llama-server；compose 内已保留容器化 LLM 的注释方案。）

## 四种方案索引

| 方案 | LLM 来源 | 最低成本单盒 | 推荐单盒 | 多盒拆分 | 并发(单盒) | 详情 |
|---|---|---|---|---|---|---|
| [① 远程 LLM](./plan-1-remote-llm.md) | GPUStack 远程 | 4060 Ti 16G / 5070 12G（¥6k–10k） | 5070 12G | 管线盒可无限堆叠 | 20–40 路 | 最省、数据本机 |
| [② Qwen3-8B 本地](./plan-2-qwen3-8b.md) | 本地 GGUF | 5070 Ti 16G（¥16k+） | 4090 24G | 4090(LLM)+4060Ti×N | 10–20 路 | 质量/成本均衡 |
| [③ Qwen3.5-9B 本地](./plan-3-qwen3.5-9b.md) | 本地 GGUF | 4090 24G（¥22k+） | 5090 32G / L20 48G | 5090×N / L20 集群 | 10–20 路 | 质量最高、最吃显存 |
| [④ Qwen3.5-4B 本地](./plan-4-qwen3.5-4b.md) | 本地 GGUF | 5070 12G（¥6k–8k） | 5070 Ti 16G | 同② | 15–30 路 | 并发最高、延迟最低 |

## 多盒部署（必读）

- [多盒 + 内网 LLM 端点部署清单](./deployment-multibox.md)
- [docker-compose.llm-box.yml](./docker-compose.llm-box.yml)（LLM 盒：llama.cpp 服务）
- [docker-compose.pipeline-box.yml](./docker-compose.pipeline-box.yml)（管线盒：VAD/STT/TTS + 内网 LLM）

## 电商平台检索入口（1688）

> 点击即跳转 1688 搜索结果页，可筛选「整机 / 涡轮卡 / 工控机」。

- RTX 4060 Ti 16G 整机：<https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%204060Ti%2016G%20整机>
- RTX 5060 Ti 16G 整机：<https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205060Ti%2016G%20整机>
- RTX 5070 12G 整机：<https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205070%2012G%20整机>
- RTX 5070 Ti 16G 整机：<https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205070Ti%2016G%20整机>
- RTX 4090 24G 整机：<https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%204090%2024G%20整机>
- RTX 5090 32G 整机：<https://s.1688.com/selloffer/offer_search.htm?keywords=RTX%205090%2032G%20整机>
- L20 48G 推理服务器：<https://s.1688.com/selloffer/offer_search.htm?keywords=L20%2048G%20推理服务器>
- Jetson Orin 边缘盒子：<https://s.1688.com/selloffer/offer_search.htm?keywords=Jetson%20Orin%20NX%20边缘计算盒子>

> 价格参考与具体商品链接见各方案文档内「商品检索」小节。
