# Speech-To-Speech 服务器部署文档

低延迟、模块化语音智能体流水线 **VAD → STT → LLM → TTS**，通过 WebSocket / WebRTC 上的
OpenAI Realtime 兼容协议对外提供服务。本文档包含：组件说明、各环节延迟与优化、两种部署方案
（LLM 走 GPUStack / LLM 一并自部署）。

---

## 1. 流水线组件说明

| 环节 | 含义 | 本项目默认模型 | 作用 |
|---|---|---|---|
| **VAD** | Voice Activity Detection，语音活动检测 | Silero VAD v5 | 从麦克风音频流中判断"人何时说话、何时停"，负责端点检测与轮流对话（turn-taking），切出人声片段 |
| **STT** | Speech-To-Text，语音转文字 | NVIDIA Parakeet TDT 0.6B v3 | 把人声片段转成文本，作为 LLM 输入；可输出实时中间字幕 |
| **LLM** | Large Language Model，大语言模型 | 官方 OpenAI（默认）；本文档改为 Qwen3-8B | 流水线的"大脑"，生成回复文本并支持流式输出与工具调用；计算量最大、延迟最敏感 |
| **TTS** | Text-To-Speech，文字转语音 | Qwen3-TTS 1.7B（GGML） | 把 LLM 回复文本合成语音流，流式回传给客户端播放 |

数据流：

```
麦克风音频 ──▶ [VAD] ──▶ [STT] ──▶ [LLM] ──▶ [TTS] ──▶ 扬声器音频
   原始波形      切出人声片段   转成文字   生成回复文本   合成语音流
```

> 只有 **LLM** 槽位讲 OpenAI 兼容协议，因此可指向任意托管 / 自建服务（GPUStack、vLLM、
> llama.cpp、OpenAI 等）。其余三者在本地离线运行（首跑需联网下载权重，之后可离线）。

---

## 2. 各环节延迟占比与优化建议

> 以下为**参考量级**（短句、GPU 环境），实际取决于模型、量化、GPU 性能与网络。端到端
> 感知延迟 = 各段延迟之和；LLM 的"首字延迟(TTFT)"通常是主导项。

| 环节 | 典型延迟（参考） | 说明 | 优化建议 |
|---|---|---|---|
| **VAD** | 50–300 ms（含断句等待） | 含 `--min_silence_ms` 静音判定与 Smart Turn 二次确认；`speculative_reopen_ms` 默认 800ms 仅影响软结束的兜底，不计入硬延迟 | 降低 `--min_silence_ms`（如 64→48ms）加快断句；调高/调低 `--thresh` 适配环境噪声；如误判少，可 `--no_smart_turn` 去掉二次确认以减少等待 |
| **STT** | 200–600 ms（GPU）+ 说话时长 | Parakeet 解码很快，主要时间随说话长度线性增长 | 保持 GPU 推理；开启 `--enable_live_transcription` 让字幕早出；如资源紧张可换更小模型或 Faster-Whisper |
| **LLM** | TTFT 200–1000 ms；再按 token 流式 | **端到端延迟的主因**；Qwen3 思考链会显著拖慢首字 | 关闭思考链（`--responses_api_reasoning_effort none`，本项目默认已关 `enable_thinking`）；用流式输出；缩短上下文（`--chat_size`）；离 pipeline 近、网络 RTT 低；必要时换更小/更快模型或更强 GPU |
| **TTS** | 首包 200–600 ms（非流式）→ 流式更低 | Qwen3-TTS 默认非流式会等整句合成完才出声 | 改用流式合成（`--qwen3_tts_non_streaming_mode False`）让首包更早；选更轻量发音人或后端（Kokoro 等） |

**整体优化要点：**

- **LLM 是瓶颈**：优先优化 TTFT（关思考链、就近部署、流式）。
- **网络**：pipeline 与 LLM 服务之间的 RTT 直接叠加进延迟，尽量同机或同局域网。
- **并发**：默认单流水线，高峰可用 `--num_pipelines N` 提升并发（需更多显存/算力）。
- **预热**：服务启动会 warmup 一次 LLM，避免首个请求偏慢。

---

## 3. 部署方案总览

| 方案 | LLM 来源 | 是否需要 GPUStack | 适用场景 | 文件 |
|---|---|---|---|---|
| **方案一** | GPUStack 上**现有** Qwen3-8B | 需要 | 已有 GPUStack 集群、想集中管理模型与扩缩容 | `docker-compose.gpustack.yml` + `.env.gpustack.example` |
| **方案二** | 随容器**自带** llama.cpp 服务 Qwen3-8B | 不需要 | 完全自包含、单节点一键部署、离线运行、不依赖外部平台 | `docker-compose.llm-bundled.yml` |

两种方案都只让 pipeline 容器负责 VAD/STT/TTS；区别仅在于 LLM 由外部 GPUStack 提供，还是
由同 compose 内的 llama.cpp 提供。

---

## 4. 方案一：LLM 使用 GPUStack 现有 Qwen3-8B

### 4.1 前置信息（从 GPUStack 获取）

- **API 基址**：`http://<gpustack-host>/v1-openai`（注意是 `/v1-openai`，不是 `/v1`）
- **模型名** `GPUSTACK_MODEL`：GPUStack 控制台 Models 中注册的模型名（如 `Qwen3-8B`）
- **API Key**：控制台 → API Keys 生成

### 4.2 部署

```bash
cd <项目根目录>
cp .env.gpustack.example .env.gpustack     # 填好三项
docker compose -f docker-compose.gpustack.yml --env-file .env.gpustack up -d --build
```

关键参数（已内置在 compose）：

- `--llm_backend chat-completions`：兼容性最好的 OpenAI 兼容后端（GPUStack 的 Responses 接口未必代理得到）
- `--responses_api_reasoning_effort none`：关闭 Qwen3 思考链，降低语音延迟
- STT 默认 `parakeet-tdt`、TTS 默认 `qwen3`（容器内 GPU 运行）

### 4.3 拓扑

- **与 GPUStack 同机、分卡（推荐）**：`PIPELINE_GPU_ID` 指定 STT/TTS 用的卡，与 GPUStack 的 LLM 卡分开，避免显存争抢。
- **跨机 / CPU**：`GPUSTACK_BASE_URL` 填 GPUStack 可达地址；若 pipeline 放无 GPU 机器，去掉 GPU 预留并改 STT/TTS 为 CPU 实现（见 README CUDA 说明，TTS 需 cpu wheel）。

---

## 5. 方案二：LLM 也一并部署（自包含，不依赖 GPUStack）

自带 llama.cpp 容器在 GPU 上服务 Qwen3-8B-Instruct GGUF，pipeline 直接指向它。完全离线友好。

### 5.1 部署

```bash
cd <项目根目录>
docker compose -f docker-compose.llm-bundled.yml up -d --build
```

### 5.2 说明

- 默认拉取 `Qwen/Qwen3-8B-Instruct-GGUF`（多文件仓库，llama.cpp 取默认量化）。
  如需指定量化（如 `Q4_K_M` / `Q8_0`），把 `-hf` 换成具体 `.gguf` 文件，且 `--model_name` 需与之保持一致。
- 关闭思考链：llama.cpp 较新版本支持 `--reasoning-budget 0`；pipeline 侧仍发送
  `chat_template_kwargs.enable_thinking=false`（vLLM 生效）。
- `llama` 与 `pipeline` 都占用 GPU 0，请确保显存足够（Qwen3-8B q8 ≈ 8.5GB + STT/TTS）。

> 若你的 GPUStack 本身基于 vLLM 且你也想在本方案体验一致行为，可把 `llama` 镜像换成
> vLLM 镜像（如 `vllm/vllm-openai`），命令改为 `--model Qwen/Qwen3-8B-Instruct --enable-reasoning false`，
> 其余 `--responses_api_base_url http://llama:8000/v1` 不变。

---

## 6. 验证

```bash
# 查看日志，确认 LLM 已连上（warmup 成功）、各模型加载完成
docker compose -f <所用compose文件> logs -f pipeline

# 用自带客户端对讲测试（另开终端）
docker compose -f <所用compose文件> exec pipeline \
  speech-to-speech talk --url ws://127.0.0.1:8765/v1/realtime
```

也可从外部用 OpenAI Realtime SDK 连接 `ws://<server>:8765/v1/realtime`。

---

## 7. 注意事项

- **首次启动需联网**：Parakeet、Qwen3-TTS、Silero VAD、Smart Turn 等权重会从 HuggingFace
  下载并缓存到 `./cache/`，之后可设 `HF_HUB_OFFLINE=1` 离线运行。
- **无内置鉴权**：`serve` 本身不做认证。生产环境务必放在反向代理 / 网关后，或仅对内网开放
  `8765`；如需把 LLM 暴露给旁路任务，再加 `--enable_llm_proxy`（同样无鉴权，仅可信网络开启）。
- **HTTPS**：GPUStack 走 TLS 时把 `GPUSTACK_BASE_URL` 改成 `https://.../v1-openai` 即可。
- **多并发**：默认单流水线，可用 `--num_pipelines N` 提升并发（需更多显存/算力）。
- **镜像构建**：`Dockerfile` 基于 `nvidia/cuda:12.8.1`；需先安装
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/) 才能使用 GPU。
