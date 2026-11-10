# 私有化部署手册（Docker 环境）

> 🌐 Language / 语言：**中文版**

**适用对象**：在客户现场 / 内网数据中心，以 Docker 方式交付 `speech-to-speech`（S2S）语音智能体系统。

**本手册覆盖三件事**：
1. **部署**——从环境准备到服务可用的完整步骤，含**离线内网**（无外网）交付路径；
2. **模型变换**——VAD / STT / LLM / TTS 四个槽位如何换模型、权重如何离线导入、如何回滚；
3. **模型效果评估**——精度、性能、稳定性、端到端体感四层评估方法与验收基线。

### 与其他文档的关系

| 文档 | 定位 | 何时看 |
|---|---|---|
| **本手册** | 私有化交付总纲（部署 + 换模型 + 评估） | 交付现场 |
| [`deployment.md`](./deployment.md) | 上游通用部署文档（部署形态原理） | 想了解 compose 变体由来 |
| [`deployment-tuning-playbook.md`](./deployment-tuning-playbook.md) | 调参手册（现象 → 参数组） | 上线后延迟/打断手感不达标 |
| [`parameter-catalog.md`](./parameter-catalog.md) | 全量参数目录（含各后端字段前缀） | 需要查某个参数的完整语义 |
| [`model-pipeline.md`](./model-pipeline.md) | 流水线内部实现 | 需要改代码 |
| [`local-thirdparty-deployment-CN.md`](./local-thirdparty-deployment-CN.md) | LLM 走第三方 API 的专题部署 | LLM 不在内网 GPUStack |
| [`hardware/acceptance-test-plan.md`](./hardware/acceptance-test-plan.md) | 到货算力盒 T0~T9 验收流程 | 需要完整验收报告模板 |

---

## 目录

- [1. 系统构成](#1-系统构成)
- [2. 部署形态选型](#2-部署形态选型)
- [3. 环境准备](#3-环境准备)
- [4. 离线交付（内网无外网）](#4-离线交付内网无外网)
- [5. 镜像](#5-镜像)
- [6. 部署实施](#6-部署实施)
- [7. 模型变换](#7-模型变换)
- [8. 模型效果评估](#8-模型效果评估)
- [9. 运维与故障排查](#9-运维与故障排查)
- [10. 附录](#10-附录)

---

## 1. 系统构成

### 1.1 流水线

```text
麦克风 ──▶ [VAD] ──▶ [STT] ──▶ [LLM] ──▶ [TTS] ──▶ 扬声器
 原始波形   切出人声    转成文字   生成回复    合成语音流
```

| 槽位 | 作用 | 当前默认 | 是否可换 | 可换范围 |
|---|---|---|---|---|
| **VAD** | 判断人何时说话、何时停；负责端点检测与轮流对话 | Silero VAD v5 | ✅ | `silero` / `firered`（需额外依赖与权重） |
| **STT** | 人声片段 → 文本 | Qwen3-ASR-1.7B-hf | ✅ | 15 个后端（§7.3） |
| **LLM** | 生成回复（支持流式与工具调用） | 内网 GPUStack `Qwen3-8B` | ✅ | 4 个后端 + 任意 OpenAI 兼容端点（§7.4） |
| **TTS** | 文本 → 语音流 | Qwen3-TTS CustomVoice | ✅ | 12 个后端（§7.5） |

> 只有 **LLM** 槽位讲 OpenAI 兼容协议，因此可直接指向任意托管 / 自建服务；
> VAD / STT / TTS 在本地离线运行（首跑需联网下载权重，之后可离线）。

### 1.2 对外接口

服务统一监听 `0.0.0.0:8765`（端口可改）：

| 方法 | 路径 | 用途 |
|---|---|---|
| `WS` | `/v1/realtime` | S2S 主链路（OpenAI Realtime 兼容协议） |
| `POST` | `/v1/audio/transcriptions` | **ASR 独立接口**（OpenAI 兼容，可脱离会话单独调用） |
| `POST` | `/v1/audio/speech` | **TTS 独立接口**（OpenAI 兼容，可脱离会话单独调用） |
| `GET` | `/v1/pool` | 流水线池状态（**健康检查用此端点**） |
| `GET` | `/v1/usage` | 用量统计 |

> **无 `/health` 端点**（返回 404）。健康检查请用 `/v1/pool`，或对 `/v1/realtime` 做
> WebSocket 升级握手（期望 `101`）。

---

## 2. 部署形态选型

三个维度独立组合：**LLM 放哪** × **LLM 是几路** × **STT/TTS 在哪台机**。

### 2.1 按 LLM 来源选 compose

| 形态 | LLM 来源 | 编排文件 | env 文件 | 适用场景 |
|---|---|---|---|---|
| **A. 内网 GPUStack** | 局域网 GPUStack（vLLM 等） | `docker-compose.gpustack.yml` | `.env.gpustack` | 已有 GPUStack 集群，集中管理模型与扩缩容 |
| **B. 自带 llama.cpp** | 同 compose 内 `llama` 容器 | `docker-compose.llm-bundled.yml` | 根目录 `.env`（compose 默认读取） | 完全自包含、单节点一键、离线运行 |
| **C. 第三方 API** | 公网 OpenAI 兼容服务 | `docker-compose.thirdparty.yml` | `.env.thirdparty` | LLM 用云端服务（详见专题文档） |
| **D. 混合多盒** | 独立算力盒 + pipeline 盒 | `docs/hardware/docker-compose.llm-box.yml` + `...-pipeline-box.yml` | — | LLM 单独部署在另一台高算力机 |

> 形态 A/B/C 的 pipeline 容器职责相同：只跑 VAD/STT/TTS，LLM 由外部提供。

### 2.2 拓扑图（形态 A / B 通用）

```text
┌──────────── pipeline 容器（GPU 卡 X）─────────────┐
│  VAD(silero, CPU) → STT → [HTTP/WS] → LLM → TTS   │
└───────────────┬──────────────────────────────────┘
                │ OpenAI 兼容
        ┌───────┴────────┐
        │                │
  GPUStack/llama     第三方 API
  (同机 GPU 卡 Y 或  (公网 / 专线)
   另一台算力盒)
```

### 2.3 选型决策要点

| 约束 | 建议 |
|---|---|
| 客户内网、**无外网** | 形态 B（自带 llama.cpp）+ 离线权重；或形态 A 但 GPUStack 也在内网 |
| 现场只有一张卡，LLM 也要跑 | 形态 B，注意显存：llama(Qwen3-8B q8≈8.5GB) + STT/TTS(≈9GB) 需 ≥24GB |
| 客户要求数据不出内网 | 形态 A / B（**不要**用形态 C） |
| LLM 要独立扩缩容 | 形态 A（GPUStack）或 D（多盒） |
| 显存紧张、只要 STT/TTS 能力 | 形态 A + 把 STT/TTS 拆到独立盒（见 `docs/hardware/`） |

---

## 3. 环境准备

### 3.1 硬件与驱动

| 项 | 最低 | 推荐 | 检查 |
|---|---|---|---|
| GPU | 1 张，支持 CUDA 12.8 | 2 张（LLM 与 STT/TTS 分卡） | `nvidia-smi` |
| 显存 | 12GB（仅 STT/TTS） | 24GB+（含本地 8B LLM） | `nvidia-smi --query-gpu=memory.total` |
| 内存 | 16GB | 32GB | `free -g` |
| 磁盘 | 40GB（镜像 12GB + 权重 8GB + 日志） | 100GB | `df -h` |
| 驱动 | ≥ 525（CUDA 12.x） | ≥ 550 | `nvidia-smi` 顶部版本号 |

> ⚠️ **torch wheel 与驱动版本必须匹配**。镜像内 torch 默认装 cu130 wheel，
> 若宿主驱动为 12.8，`torch.cuda.is_available()` 会返回 False → TTS/STT **静默回退 CPU**，
> 表现为"能跑但极慢"（RTF 从 0.4 飙到 3.7）。
> 处置：把 Dockerfile 里 torch/torchaudio 锁到 cu128 wheel（见 `Dockerfile.cu128`）。

### 3.2 Docker 与 NVIDIA Container Toolkit

```bash
# Docker 版本 ≥ 24
docker --version
docker compose version

# NVIDIA runtime 需可见
docker info | grep -A2 Runtimes
# 期望输出里含 io.containerd.runc.nvidia 或 nvidia
```

若 `docker info` 中没有 nvidia runtime：

```bash
# Ubuntu/Debian
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 3.3 目录结构

```text
<部署根目录>/
├── docker-compose.<形态>.yml     # 编排
├── .env.<形态>                   # 该形态的变量（**不要提交到 git**）
├── cache/                        # 模型权重（挂载到 /root/.cache）
│   ├── qwen3-asr-model-hf/       # STT：Qwen3-ASR-1.7B-hf
│   ├── qwen3-tts-model/          # TTS：Qwen3-TTS CustomVoice
│   ├── nltk_data/                # nltk 资源（构建期烤入镜像更稳）
│   └── huggingface/              # 其它 HF 缓存
├── silero-vad/                   # VAD 权重（挂载到 /opt/silero-vad）
└── scripts/                      # 评测与压测脚本
```

权限与大小写：

- Linux 下目录名**区分大小写**，`silero-vad` 与 `silero_vad` 不可互换；
- `cache/` 与 `silero-vad/` 需容器内 root 可读写（`chmod -R 777` 或保持默认 755）；
- Windows 绑定挂载点权限恒为 777，**nltk 会拒绝使用** → 不要挂载 `nltk_data`（见 §4.3）。

---

## 4. 离线交付（内网无外网）

内网环境最常见的三个卡点：**镜像拉不到、权重下不来、nltk 联网卡死**。本节给出逐项解法。

### 4.1 镜像离线导入

```bash
# —— 有外网的机器（与客户同架构）——
docker pull <镜像仓库>/speech-to-speech:<tag>
docker save  speech-to-speech:<tag> -o speech-to-speech-<tag>.tar
# 大文件可压缩传输
gzip -k speech-to-speech-<tag>.tar

# —— 客户内网机器 ——
docker load -i speech-to-speech-<tag>.tar
docker images | grep speech-to-speech
```

若需基于官方镜像派生（补 sox / nltk / ASR-TTS 端点补丁），构建时也要离线：

```bash
# 预先把基础镜像拉下来并导出
docker pull ccr.ccs.tencentyun.com/llm-basic/speech-to-speech:cu130-1.1
docker save ccr.ccs.tencentyun.com/llm-basic/speech-to-speech:cu130-1.1 -o base.tar
# 内网加载后直接构建（不再联网）
docker load -i base.tar
docker build -f Dockerfile.local.rest -t speech-to-speech-local:cu130-1.2-rest .
```

### 4.2 模型权重离线导入

**方式一：外网机器下载 → 打包 → 内网解包**（推荐）

```bash
# 外网机器（用 modelscope，境内可达性好）
pip install modelscope
modelscope download --model Qwen/Qwen3-ASR-1.7B --local_dir ./qwen3-asr-model-hf
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice --local_dir ./qwen3-tts-model
tar czf models.tar.gz qwen3-asr-model-hf qwen3-tts-model nltk_data
# 内网解包到部署根目录的 cache/ 下
tar xzf models.tar.gz -C cache/
```

> ⚠️ **ASR 必须用 `-hf` 版**（`Qwen3-ASR-1.7B` 的 HF 权重目录）。handler 走 transformers 的
> `processor.apply_transcription_request()`，它依赖 `-hf` 权重自带的 `chat_template.jinja`；
> 非 `-hf` 版会在 warmup 阶段抛 `ValueError: continue_final_message ...` → 容器崩溃重启循环。

**方式二：HuggingFace 直连**（需能访问 huggingface.co）

```bash
huggingface-cli download Qwen/Qwen3-ASR-1.7B --local-dir ./cache/qwen3-asr-model-hf
```

**方式三：镜像内预置**——把权重目录直接 COPY 进镜像（镜像会变大，但彻底免挂载）。

### 4.3 nltk 资源（启动卡死的头号原因）

镜像内 `s2s_pipeline.py` 的引导逻辑会查 `punkt` / `punkt_tab` / `averaged_perceptron_tagger_eng`。
若资源缺失，它会调用 `nltk.download()`——**该下载没有超时**，在内网会永久阻塞，导致容器
永远起不来。

处置（二选一，**推荐 A**）：

- **A. 烤进镜像**（见 `Dockerfile.local`）：
  ```dockerfile
  COPY cache/nltk_data /root/nltk_data
  RUN chmod -R 755 /root/nltk_data && chown -R root:root /root/nltk_data
  ```
  烤进去后是 `root:root 755`，nltk 合法使用本地副本，**启动零网络依赖**。
- **B. 打补丁**（见 `Dockerfile.ttsfix`）：修正 tagger 资源路径（实际在 `taggers/` 而非
  `tokenizers/`），并把下载改为 30s 超时的守护线程，失败不阻塞启动。

> ❌ **不要**把 `cache/nltk_data` 绑定挂载到容器：Windows 挂载点权限恒为 777，
> nltk 会以 "world- or group-writable" 拒绝授权，转去联网重下 → 同样卡死。

### 4.4 内网连通性自检清单

```bash
# 1) 镜像内能否解析并访问 LLM 网关
docker exec <pipeline> python3 -c "import httpx;print(httpx.get('http://<llm>/v1/models',timeout=10).status_code)"

# 2) 确认 HF 离线模式已生效（compose 已设 HF_HUB_OFFLINE=1）
docker exec <pipeline> env | grep HF_HUB_OFFLINE

# 3) 确认 nltk 资源在镜像内
docker exec <pipeline> ls /root/nltk_data

# 4) VAD 权重在位
docker exec <pipeline> ls /opt/silero-vad/src/silero_vad/data/
```

---

## 5. 镜像

### 5.1 仓库内 Dockerfile 家族

| 文件 | 基座 | 用途 |
|---|---|---|
| `Dockerfile` | `nvidia/cuda:12.8.1` | 上游基础镜像（源码完整构建） |
| `Dockerfile.cu128` | — | torch/torchaudio 锁 **cu128** wheel（驱动 12.8 必用，见 §3.1） |
| `Dockerfile.cu130` | — | cu130 基座 |
| `Dockerfile.local` | `…:cu130-1.1` | 本地基座：装 sox + 烤入 nltk 资源 |
| **`Dockerfile.local.rest`** | `speech-to-speech-local:cu130-1.1-sox` | **在本地基座上固化 ASR/TTS 独立 REST 端点** |
| `Dockerfile.ttsfix` | `…:cu130-1.0` | 生产基座：补 `python3.12-dev`（triton JIT）、sox、nltk 补丁、ASR/TTS 端点补丁 |
| `Dockerfile.baked` / `.baked.cu130` | — | 预烘焙权重（免首跑下载） |
| `Dockerfile.sox` | — | 仅补 sox |
| `Dockerfile.arm64` | — | ARM 架构 |

### 5.2 ASR/TTS 独立端点补丁（重要）

`/v1/audio/transcriptions` 与 `/v1/audio/speech` 两个 REST 端点**不是上游原生功能**，
而是由 `scripts/patch_pipeline_rest.py` 在**构建期**注入到
`src/speech_to_speech/api/openai_realtime/websocket_router.py`。

| 基座 | 是否自带该补丁 |
|---|---|
| `Dockerfile.ttsfix`（cu130-1.0，生产） | ✅ 构建期已固化 |
| `Dockerfile.local`（cu130-1.1，本地） | ❌ **缺失** → 需用 `Dockerfile.local.rest` |

构建与自检：

```bash
docker build -f Dockerfile.local.rest -t speech-to-speech-local:cu130-1.2-rest .
# 日志末尾应出现：ASR/TTS REST endpoints baked OK
```

> 该补丁**复用进程内已加载的模型**，因此 ASR/TTS 独立调用**不占额外显存**，
> 也**不需要**额外的容器。这也是本项目的既定设计：后端注册表中 `LLM_BACKENDS` /
> `TTS_BACKENDS` 均**无 `none` 后端**，无法只启动单一组件进程。

---

## 6. 部署实施

### 6.1 标准流程（以形态 A 为例）

```bash
cd <部署根目录>

# 1) 准备变量
cp .env.gpustack.example .env.gpustack
vi .env.gpustack      # 填 GPUSTACK_BASE_URL / GPUSTACK_MODEL / GPUSTACK_API_KEY

# 2) 确认权重与 VAD 就位
ls cache/qwen3-asr-model-hf/config.json cache/qwen3-tts-model/config.json
ls silero-vad/src/silero_vad/data/silero_vad.jit

# 3) 启动
docker compose -f docker-compose.gpustack.yml --env-file .env.gpustack up -d

# 4) 观察日志直到就绪
docker compose -f docker-compose.gpustack.yml --env-file .env.gpustack logs -f pipeline
```

### 6.2 就绪判据

启动全过程约 **3~4 分钟**（加载 STT 权重 → STT warmup → LLM warmup → TTS 权重 + CUDA graph 捕获）。
必须看到这三类日志才算成功：

```text
# ① LLM 打通（关键：第三方/内网 LLM 是否可用）
…LLM.chat_completions_language_model - INFO - ChatCompletionsApiModelHandler: warmed up! time: 2.872 s

# ② TTS 就绪
…TTS.qwen3_tts_handler - INFO - Qwen3-TTS TTFA: 1.85s (custom_voice)
…TTS.qwen3_tts_handler - INFO - Qwen3-TTS generated 1.56s audio in 3.78s (RTF: 0.41, custom_voice)

# ③ 服务监听
…openai_realtime.server - INFO - OpenAI Realtime API starting on ws://0.0.0.0:8765/v1/realtime (pool size 1)
INFO:     Uvicorn running on http://0.0.0.0:8765
```

### 6.3 冒烟验证

```bash
# 健康检查（注意：没有 /health）
curl -s http://127.0.0.1:8765/v1/pool

# ASR 独立接口
curl -s -X POST http://127.0.0.1:8765/v1/audio/transcriptions \
  -F "file=@sample.wav" -F "language=auto"
# → {"text":"今天天气怎么样？","language":"Chinese"}

# TTS 独立接口
curl -s -X POST http://127.0.0.1:8765/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"今天天气怎么样","voice":"Aiden","response_format":"wav"}' -o out.wav

# S2S 主链路（仓库自带脚本）
docker cp scripts/e2e_realtime_test.py <pipeline容器>:/tmp/
docker cp prompt.wav <pipeline容器>:/tmp/
docker exec <pipeline容器> python3 /tmp/e2e_realtime_test.py \
  --url ws://127.0.0.1:8765/v1/realtime --audio /tmp/prompt.wav --out-dir /tmp/e2e
```

### 6.4 GPU 分配

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          device_ids: ['${PIPELINE_GPU_ID:-0}']
          capabilities: [gpu]
```

> ⚠️ **`docker compose` 只读 `.env`，不会读 `.env.cu130` / `.env.gpustack`**（除非用
> `--env-file` 显式指定）。若 `PIPELINE_GPU_ID` 回退为 0，而 GPU0 被 LLM 服务占满，
> pipeline 会 CUDA OOM 崩溃循环。**部署时务必用 `--env-file` 指定**，
> 或在部署根目录放一份 `.env` 兜底。

---

## 7. 模型变换

### 7.1 通用五步法

```text
① 选后端（--stt / --tts / --llm_backend / --vad）
      ↓
② 备权重（离线下载 → 放到 cache/ 对应目录，或改用远端后端免权重）
      ↓
③ 改参数（compose 的 command 段 / .env 变量）
      ↓
④ 重建容器并验证（up -d --force-recreate + 冒烟三件套）
      ↓
⑤ 评估（§8）+ 记录归档（§8.7 报告模板）
```

> 后端选择、字段前缀、必填项的权威依据是
> [`parameter-catalog.md` §1.2–§1.5 / §3.3 / §5.3](./parameter-catalog.md)。
> **字段前缀必须与后端匹配**，混用会导致配置校验报"未知字段"。

### 7.2 VAD

| 后端 | 命令行 | 前置条件 | 备注 |
|---|---|---|---|
| `silero`（默认） | `--vad silero` | 权重在 `/opt/silero-vad` | 通用、离线、CPU 每帧 <1ms |
| `firered` | `--vad firered` | ① `fireredvad` 包 ② `Stream-VAD/` 下 `cmvn.ark` + `model.pth.tar` ③ `--vad_firered_model_dir` | 三件套缺一即启动失败 |

换 VAD 会改变**判停手感与延迟构成**（FireRedVAD 多语种与音乐场景误警率 2.69%，
Silero 9.41%），上线前必须重跑 §8.5 的端到端评估。

```yaml
# compose 中切换
- --vad
- firered
- --vad_firered_model_dir
- /root/.cache/Stream-VAD
```

### 7.3 STT（15 个后端）

| 后端名 | 关键字段 | 必填 | 选型要点 |
|---|---|---|---|
| `qwen3-asr`（默认） | `qwen3_asr_model_name` / `_device` / `_language` | — | 多语种、低延迟；**权重必须是 `-hf` 版** |
| `parakeet-tdt` | `parakeet_tdt_model_name` / `_device` / `_language` | — | 快；配 `enable_live_transcription` 出实时字幕 |
| `parakeet-unified` | `parakeet_unified_model_name` … | — | 与 tdt 是**不同 checkpoint** |
| `nemotron-streaming` | `nemotron_streaming_*` | — | 真流式，天然低延迟 |
| `orukeet` | `orukeet_model_name` + `_checkpoint_filename` + `_checkpoint_revision` | **三件套** | 固定 revision 防上游漂移 |
| `whisper` | `stt_model_name` / `stt_device` / `stt_torch_dtype` / `stt_gen_num_beams` | 模型名 | ⚠️ 前缀是 `stt_` 不是 `whisper_` |
| `whisper-mlx` | 同 `stt_*` | — | 仅 Apple Silicon |
| `mlx-audio-whisper` | `mlx_audio_whisper_model_name` / `_gen_kwargs` | 模型名 | `gen_kwargs` 是**字典**不是标量 |
| `faster-whisper` | `faster_whisper_stt_model_name` / `_device` / `_compute_type` | 模型名、compute_type | CPU 友好；`compute_type` 直接决定显存与速度 |
| `paraformer` | `paraformer_stt_model_name` / `_device` | 模型名 | 中文专用，**无语言参数** |
| `sense-voice` | `sense_voice_stt_model_name` / `_device` / `_language` | 模型名 | 多语种 + 情感/事件标签 |
| `openai` | `openai_stt_base_url` / `_api_key` / `_model` / `_response_format` | base_url | 远端托管；密钥隐式回退 `OPENAI_API_KEY` |
| `openai-realtime` | `openai_realtime_stt_base_url` / `_model` / `_audio_sample_rate` | base_url、model | 流式音频块 |
| `vllm-realtime` | `vllm_realtime_stt_base_url` / `_model` … | base_url、model | 面向自建 vLLM Realtime |
| `none` | — | — | 跳过转写，音频直送支持音频输入的 LLM |

**换 STT 示例 ①**：换成 `faster-whisper`（CPU 友好）

```yaml
- --stt
- faster-whisper
- --faster_whisper_stt_model_name
- /root/.cache/faster-whisper-large-v3
- --faster_whisper_stt_device
- cuda
- --faster_whisper_stt_compute_type
- float16
```

**换 STT 示例 ②**：换成远端 OpenAI 兼容转写服务（免本地权重）

```yaml
- --stt
- openai
- --openai_stt_base_url
- http://asr-gateway.internal/v1
- --openai_stt_api_key
- ${ASR_API_KEY}
- --openai_stt_model
- Qwen/Qwen3-ASR-1.7B
```

> 注意远端 STT 后端在初始化阶段会**转写一秒合成静音**做探测，
> 因此该端点不可达会直接**阻止 Realtime 服务接受会话**（不是运行期才报错）。

### 7.4 LLM（4 个后端 + 任意兼容端点）

| 后端名 | 接口 | 额外依赖 | 说明 |
|---|---|---|---|
| `chat-completions`（默认） | OpenAI Chat Completions | 内置 | 兼容性最好；GPUStack / vLLM / llama.cpp / 云服务都用它 |
| `responses-api` | OpenAI Responses | 内置 | 官方 Responses 语义 |
| `transformers` | 本地 HF 权重 | 内置 | 可 8bit/4bit 量化，显存可控 |
| `mlx-lm` | 本地 MLX | `mlx-lm` | **仅 macOS**，Linux 上加载失败 |

字段前缀沿用 `responses_api_*`（这是**预期行为**，不是 bug）。

**换 LLM 三种典型做法**：

```yaml
# ① 内网 GPUStack
- --llm_backend
- chat-completions
- --model_name
- "${LLM_MODEL}"                 # 必须与 GPUStack 控制台注册名完全一致
- --responses_api_base_url
- http://192.168.40.30/v1-openai
- --responses_api_api_key
- "${LLM_API_KEY}"

# ② 本地 transformers 权重（完全离线）
- --llm_backend
- transformers
- --model_name
- /root/.cache/Qwen3-8B
- --llm_device
- cuda
- --llm_torch_dtype
- bfloat16

# ③ 第三方云服务
- --llm_backend
- chat-completions
- --model_name
- qwen-plus
- --responses_api_base_url
- https://dashscope.aliyuncs.com/compatible-mode/v1
- --responses_api_api_key
- "${LLM_API_KEY}"
```

**关思考链**（语音场景必须，否则首字延迟被思考链吃掉）：

先理解两个参数的**优先级**（见
`src/speech_to_speech/LLM/base_openai_compatible_language_model.py:_build_extra_body`）：

| 条件 | 实际发给上游的 extra_body |
|---|---|
| `reasoning_effort` **非空**（**默认值就是 `"none"`**） | `{"reasoning_effort": "<值>"}` ← **优先，短路下面的分支** |
| `reasoning_effort` 为空 + 基址是官方 `api.openai.com` | 不发任何 extra_body |
| `reasoning_effort` 为空 + `disable_thinking=True` + 非官方基址 | `{"chat_template_kwargs": {"enable_thinking": false}}` |

因此按目标服务商二选一：

```yaml
# ① 服务商认 reasoning_effort（GLM / 部分 vLLM 网关 / OpenAI 兼容代理）——默认值即可
- --responses_api_reasoning_effort
- "none"

# ② 服务商只认 vLLM 风格的 chat_template_kwargs（GPUStack / vLLM 直连）
#    ★ 必须把 reasoning_effort **显式置空**，否则它会短路、永远发不出 chat_template_kwargs
- --responses_api_reasoning_effort
- ""
- --responses_api_disable_thinking
```

> ⚠️ 常见误区：只写 `--responses_api_disable_thinking` 而**不**把 `reasoning_effort` 置空，
> 上游收到的仍是 `{"reasoning_effort": "none"}`，而不是你以为的 `enable_thinking=false`。
> 生产编排 `docker-compose.gpustack.yml` 正是显式传空（`""`）来走 chat_template_kwargs 分支。
> 换服务商后请用抓包或上游日志确认实际发出的字段。

### 7.5 TTS（12 个后端）

| 后端名 | 关键字段 | 必填 | 选型要点 |
|---|---|---|---|
| `qwen3`（默认） | `qwen3_tts_model_name` / `_backend` / `_device` / `_speaker` / `_language` / `_non_streaming_mode` / `_streaming_chunk_size` | — | 三类权重：CustomVoice / VoiceDesign / Base |
| `openai` | `openai_tts_base_url` / `_model` / `_voice` / `_sample_rate` / `_stream` | base_url | `pcm` 裸流必须配对 `sample_rate` |
| `kokoro` | `kokoro_model_name` / `_device` / `_voice` / `_lang_code` / `_speed` / `_blocksize` | 音色 + lang_code | 音色多、CPU 可跑；`lang_code` 决定可用音色集合 |
| `kitten` | `kitten_model_name` / `_device` / `_voice` | 音色 | 参数极少，**支持会话改音色** |
| `pocket` | `pocket_tts_model_name` / `_voice` / `_device` / `_temperature` / `_eos_threshold` | 模型名 | 有随机性，语音更"活" |
| `supertonic` | `supertonic_tts_voice` / `_lang` / `_speed` / `_blocksize` | 语言码 | 仅 4 个字段 |
| `phonon` | `phonon_tts_model_name` / `_revision` / `_voice` / `_language` / `_quant` / `_num_threads` | 模型名 | 语言加载时固化，**会话改语言会被拒** |
| `chatTTS` | `chat_tts_model_name` / `_device` / `_stream` / `_chunk_size` | 模型名 | 不支持会话改语言 |
| `facebookMMS` | `facebook_mms_model_name` + `tts_language` / `_device` | 语言码 | ⚠️ 字段名是 `tts_language`，不是 `facebook_mms_language` |
| `omnivoice` | `omnivoice_model_name` / `_ref_audio` / `_ref_text` / `_voice_clone_prompt` | 参考音频 | 零样本克隆 |
| `drama3` | `drama3_base_url` / `_api_key` / `_model` / `_ref_audio` | API 密钥 | 云端 API |
| `minimax` | `minimax_tts_api_key` / `_base_url` / `_model` / `_voice` / `_speed` / `_vol` / `_pitch` | API 密钥 | 云端 API，含音量/音高 |

**Qwen3-TTS 后端与权重组合**（同一仓库存三类权重，靠模型名区分）：

| 权重 | 能力 | 所需参数 |
|---|---|---|
| `Qwen3-TTS-12Hz-1.7B-CustomVoice` | 预设音色（`Aiden` 等），**无需参考音频** | `--qwen3_tts_speaker Aiden` |
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | 用文字描述设计音色 | `--qwen3_tts_instruct "..."` |
| `Qwen3-TTS-12Hz-1.7B-Base` | 音色克隆 | `--qwen3_tts_ref_audio <path>` + `--qwen3_tts_ref_text "..."` |

**TTS 后端选择（torch）**：

```yaml
- --tts
- qwen3
- --qwen3_tts_model_name
- /root/.cache/qwen3-tts-model
- --qwen3_tts_backend
- torch          # torch | ggml | mlx；CUDA 场景首选 torch
- --qwen3_tts_device
- cuda
- --qwen3_tts_non_streaming_mode
- "False"        # False = 句内流式，首包更早
- --qwen3_tts_streaming_chunk_size
- "4"            # ~320ms 音频/块
```

> ⚠️ `transformers >= 5.15.1` 下 `torch` 后端加载 `MimiConfig` 会因缺 `rope_theta`
> 抛 `AttributeError`。镜像内已固化补丁（`base = getattr(config, "rope_theta", 10000.0)`）。

### 7.6 音色（speaker）更换

| 场景 | 结果 |
|---|---|
| `session.update` 的 `voice` 命中 CustomVoice 支持列表 | 改写 `handler.speaker`，**下一句即生效**（热更新） |
| `voice` 不是支持的名字 | 只记 warning 并忽略，音色不变 |
| `voice` 是音频文件路径 | 作为 `ref_audio` 使用（克隆模式） |
| **非 `qwen3` 后端** | 除 `kitten` 外，`voice` **只回显不改变合成** |

> 音色选择器应按后端能力置灰：把 `voice` 当"热更新音色"只在 `qwen3`（及 `kitten`）成立。

### 7.7 权重离线导入校验

导入后逐项自检：

```bash
# STT 权重结构（必须有 config.json / chat_template.jinja / *.safetensors）
ls cache/qwen3-asr-model-hf/ | head
test -f cache/qwen3-asr-model-hf/chat_template.jinja && echo "chat_template OK（-hf 版）"

# TTS 权重结构
ls cache/qwen3-tts-model/ | head

# 容器内实际加载路径（compose 里写的是容器内路径）
docker exec <pipeline> ls /root/.cache/qwen3-asr-model-hf
docker exec <pipeline> ls /root/.cache/qwen3-tts-model

# VAD 权重
docker exec <pipeline> ls /opt/silero-vad/src/silero_vad/data/silero_vad.jit
```

### 7.8 切换与回滚

```bash
# 切换：改完 compose/.env 后强制重建容器（参数在 command 段，必须 recreate）
docker compose -f <compose> --env-file <env> up -d --force-recreate pipeline

# 回滚：把配置改回旧值再重建；镜像侧建议提前打 tag
docker tag speech-to-speech-local:cu130-1.2-rest speech-to-speech-local:backup-20261110
# 回滚时
#   S2S_IMAGE_TAG=backup-20261110 docker compose up -d --no-build
```

> 回滚必须带 `--no-build`：不带它，compose 会按当前工作区重新构建，你以为在回滚，
> 实际是重新部署了 HEAD。

---

## 8. 模型效果评估

评估分四层，**缺一层都会漏判**：

```text
┌─ 精度层：模型说得对不对？（CER / MOS）        ← 换模型后必做
├─ 性能层：说得快不快？（RTF、TTFA、显存）      ← 换模型后必做
├─ 稳定层：长时间跑会不会坏？（soak、错误率）   ← 上线前必做
└─ 体感层：整体对话顺不顺？（端到端 TTFA）      ← 验收必做
```

### 8.1 精度层：STT 识别准确率

#### 8.1.1 构造测试集

准备 **≥ 50 条**真实场景语音 + 逐字标注文本，覆盖：口音、中英混说、噪声、远场、
短句（"嗯""好的"）、长句、专有名词、数字与单位。

```text
evalset/
├── audio/
│   ├── 001.wav   # 16k 单声道（可用 sox 统一转码）
│   └── ...
└── reference.txt # 每行: 文件名<TAB>标注文本
```

#### 8.1.2 批量跑 ASR 独立接口

```bash
# 单条
curl -s -X POST http://127.0.0.1:8765/v1/audio/transcriptions \
  -F "file=@evalset/audio/001.wav" -F "language=auto"
```

批量（bash）：

```bash
#!/usr/bin/env bash
# run_asr_eval.sh —— 批量转写并落地结果
BASE=http://127.0.0.1:8765
OUT=evalset/hypothesis.tsv
: > "$OUT"
for wav in evalset/audio/*.wav; do
  name=$(basename "$wav")
  text=$(curl -s -X POST "$BASE/v1/audio/transcriptions" \
      -F "file=@$wav" -F "language=auto" | python3 -c "import sys,json;print(json.load(sys.stdin).get('text',''))")
  printf '%s\t%s\n' "$name" "$text" >> "$OUT"
done
echo "done -> $OUT"
```

#### 8.1.3 计算 CER / WER

> 下列脚本为 Linux shell 写法（`python3 - <<'PY'` heredoc），在部署机的 bash / WSL /
> Git Bash 下执行；Windows PowerShell 请改为把代码块存成 `.py` 文件再 `python xxx.py`。
> 脚本仅用标准库，无需额外依赖。

```bash
python3 - <<'PY'
import re, unicodedata

def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s,，。！？、,.!?;:'\"“”‘’()（）\-—…]", "", s)

def edit_distance(ref, hyp):
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (r != h)))
        prev = cur
    return prev[-1]

def load(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        if "\t" in line:
            k, v = line.rstrip("\n").split("\t", 1)
            out[k] = v
    return out

ref = load("evalset/reference.txt")
hyp = load("evalset/hypothesis.tsv")
tot_ref = tot_err = 0
for k, r in ref.items():
    r, h = norm(r), norm(hyp.get(k, ""))
    tot_ref += len(r); tot_err += edit_distance(r, h)
print(f"样本 {len(ref)} 条 / 参考字数 {tot_ref}")
print(f"CER(全局) = {tot_err / max(tot_ref,1):.2%}")
PY
```

**判定参考**（中文普通话、安静环境）：

| CER | 评价 |
|---|---|
| < 5% | 优秀，可直接上线 |
| 5% ~ 10% | 可用，需抽查高频词（专名 / 数字） |
| 10% ~ 20% | 需换模型或加领域热词 |
| > 20% | 不可用 |

> 仓库自带的 `scripts/benchmark_stt.py` **只做性能基准**（推理耗时、warmup、显存），
> **不做准确率评测**，且其可选 handler 列表**不包含 `qwen3-asr`**
> （仅 `whisper` / `whisper-mlx` / `mlx-audio-whisper` / `faster-whisper` /
> `parakeet-tdt` / `parakeet-tdt-progressive` / `moonshine`）。
> 因此**生产 STT（Qwen3-ASR）的准确率评测请走 §8.1.2 的独立接口路径**。

### 8.2 精度层：TTS 合成质量

#### 8.2.1 客观检查

```bash
# 生成样音并检查基础属性（时长 / 采样率 / 响度 / 是否静音）
curl -s -X POST http://127.0.0.1:8765/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"今天天气怎么样","voice":"Aiden","response_format":"wav"}' -o tts.wav

python3 - <<'PY'
import soundfile as sf, numpy as np
d, sr = sf.read("tts.wav")
d = np.asarray(d, dtype="float32")
rms = float(np.sqrt((d**2).mean()))
peak = float(np.abs(d).max())
dbfs = 20 * np.log10(rms) if rms > 0 else -99.0
print(f"采样率 {sr} Hz | 时长 {len(d)/sr:.2f}s | RMS {rms:.4f} ({dbfs:.1f} dBFS) | 峰值 {peak:.3f}")
print("判定：RMS < 0.005（约 -46 dBFS）视为静音输出；峰值 >= 1.0 视为削波；语音 RMS 典型 0.05~0.3")
PY
```

> ⚠️ **量纲提醒**：`soundfile` 读 WAV 得到的是 **float32** 域（幅度 0~1），
> RMS 阈值必须按 float32 判定。若你的工具链在 **int16** 域统计，同样的语音会显示
> RMS ≈ 3400（= 0.104 × 32768），切勿混用两套阈值。
> 脚本运行环境需 `soundfile` + `numpy`（容器内已自带；宿主可用 `pip install soundfile numpy`）。

> 参考实测（Qwen3-TTS torch/cuda，float32 域）：采样率 24000 Hz、时长 4.16 s、
> RMS 0.14（约 -17 dBFS）、峰值 0.656 —— 属正常语音电平。

#### 8.2.2 主观 MOS 评测（A/B 对比）

换 TTS 模型后**必须**做主观评测，客观指标测不出"听着像不像人"。

评测流程：

1. 准备 **20~30 条**覆盖不同语种、语速、情绪的固定文本（与换型前**完全相同**）；
2. 每个模型各合成一遍，文件名按 `模型名_序号.wav` 编排，**去掉模型标识**做盲测；
3. 3~5 名评测者按 **MOS 1~5 分**打分（1=不可用，3=可接受，5=优秀）；
4. 记录：MOS 均值、方差、评语里出现最多的负面标签（机械感、吞字、尾音、语调平）；
5. 与换型前基线对比，**MOS 降幅 > 0.5 分则不接受该模型**。

参考辅助指标（可选）：

| 指标 | 含义 | 工具 |
|---|---|---|
| 回读 WER | 合成语音的可懂度（最省事） | 把 TTS 产物喂回 ASR 独立接口，与原文本比对，WER 应 < 3% |
| 说话人相似度 | 与目标音色的接近度 | `speechbrain/spkrec-ecapa` |
| 语速 | 字符/秒 | 中文自然语速约 4~6 字/秒 |

### 8.3 性能层：基准测试

#### 8.3.1 TTS 基准（仓库自带）

```bash
# 在容器内跑（依赖已装齐）
docker exec -w /usr/src/app <pipeline容器> python3 scripts/benchmark_tts.py \
  --text "这是一段用于性能基准测试的中文语音样本" \
  --language_code zh \
  --handlers qwen3 \
  --iterations 5 \
  --output /tmp/tts_bench.json
```

支持的 handler：`kokoro` / `kitten` / `pocket_tts` / `qwen3` / `chatTTS` /
`facebookMMS` / `supertonic`（注意脚本里叫 `pocket_tts`，而注册表后端名是 `pocket`）。

输出字段与解读：

| 字段 | 含义 | 判定 |
|---|---|---|
| `warmup_time` | 加载 + 首次预热耗时 | 越大启动越慢 |
| `avg_inference_time` | 平均合成耗时 | 与音频时长相除得 RTF |
| `time_to_first_chunk` | **首块延迟（TTFC）** | 语音体感的第一因 |
| `avg_audio_duration` | 生成音频时长 | — |
| `status` / `errors` | 失败原因 | 有 error 必须先解决 |

**RTF（Real-Time Factor）** = 合成耗时 ÷ 音频时长。**RTF < 1 表示快于实时**。

参考实测（Qwen3-TTS torch/cuda，RTX 5070 Ti 12GB）：

| 指标 | 实测 | 含义 |
|---|---|---|
| TTFA（首包） | 1.85 s | 语音首包延迟 |
| 生成 1.56 s 音频 | 3.78 s | 合成耗时 |
| **RTF** | **0.41** | 优于实时 ~2.4 倍 |

| RTF 区间 | 评价 |
|---|---|
| < 0.5 | 优秀 |
| 0.5 ~ 1.0 | 可用 |
| > 1.0 | 慢，需换轻量后端或开流式 |
| > 3.0 | 不可用（多半是 CPU 回退，见 §9.2） |

#### 8.3.2 STT 基准（仓库自带）

```bash
docker exec -w /usr/src/app <pipeline容器> python3 scripts/benchmark_stt.py \
  --audio_file /tmp/sample.wav \
  --handlers faster-whisper parakeet-tdt \
  --iterations 10 \
  --output /tmp/stt_bench.json
```

输出字段：`warmup_time` / `avg_inference_time` / `min` / `max` /
`time_to_first_token`（出字延迟）/ `transcriptions`（可直接人工核对）/ `errors`。

> 同 §8.1.3 的限制：该脚本不支持 `qwen3-asr`。要评 Qwen3-ASR 的性能，
> 请用独立接口做多次调用取中位数，或直接看容器日志里的 STT 耗时。

#### 8.3.3 显存

```bash
# 常驻（启动后空闲 3 分钟）
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv -l 60 > mem_idle.log
# 压测中另开一个终端
docker exec <pipeline容器> python3 /tmp/e2e_realtime_test.py --audio /tmp/prompt.wav --out-dir /tmp/e2e
```

参考实测（Qwen3-ASR-1.7B + Qwen3-TTS-1.7B 同卡）：**9.4 GB / 12.2 GB**。
换更大的 STT/TTS 前，先按"参数量 × 2 bytes"估算并核对余量。

### 8.4 稳定层

```bash
# 2 小时 soak：每 60s 一轮，共 120 轮
for i in $(seq 1 120); do
  docker exec <pipeline容器> python3 /tmp/e2e_realtime_test.py \
    --audio /tmp/prompt.wav --out-dir /tmp/soak/$i --timeout 60 \
    >> /tmp/soak.log 2>&1
  sleep 60
done
grep -c "全链路成功" /tmp/soak.log
```

判定：

| 指标 | 通过线 |
|---|---|
| 成功率 | ≥ 99%（120 轮允许失败 ≤ 1 轮） |
| 内存增长 | 2 小时内增长 < 200MB（无泄漏） |
| 容器重启次数 | 0 |

### 8.5 体感层：端到端

```bash
docker exec <pipeline容器> python3 /tmp/e2e_realtime_test.py \
  --url ws://127.0.0.1:8765/v1/realtime \
  --audio /tmp/prompt.wav --out-dir /tmp/e2e
```

输出关键指标：`STT 出字延迟` / `TTFA（首音）` / `端到端总耗时` / 助手音频时长。

> 客户端**不要**额外发 `input_audio_buffer.commit`：服务端 VAD 已在静音时自动提交，
> 双提交会产生 `conversation_already_has_active_response`（良性错误，不影响本轮结果）。

参考实测（百炼 `qwen-plus` + 本地 Qwen3-ASR/Qwen3-TTS，RTX 5070 Ti）：

| 场景 | STT 出字 | TTFA | 端到端 |
|---|---|---|---|
| 实时节奏推送（chunk 间隔 50ms） | 5.70 s | 6.13 s | 9.93 s |
| 快速推送（chunk 间隔 5ms） | 4.12 s | 4.64 s | 8.12 s |
| 稳态复测 | — | 5.06 s | 8.44 s |

> 端到端耗时里**包含了客户端推音频的时长**（真实场景下用户说话时长本就计入感知延迟）。
> 横向对比模型时务必**固定 `--chunk-delay`**，否则数字不可比。

### 8.6 验收基线表（交付时填写）

| # | 项目 | 指标 | 基线 | 实测 | 判定 |
|---|---|---|---|---|---|
| 1 | 容器就绪 | 启动时长 | ≤ 5 min | | □ |
| 2 | LLM 打通 | warmup 成功 | 是 | | □ |
| 3 | STT 精度 | 中文 CER | ≤ 10% | | □ |
| 4 | STT 性能 | 出字延迟 | ≤ 1.5 s | | □ |
| 5 | TTS 性能 | RTF | ≤ 1.0 | | □ |
| 6 | TTS 首包 | TTFA | ≤ 2.0 s | | □ |
| 7 | TTS 质量 | MOS | ≥ 3.5 | | □ |
| 8 | 端到端 | TTFA | ≤ 6 s | | □ |
| 9 | 显存 | 峰值占用 | ≤ 80% 总量 | | □ |
| 10 | 稳定性 | 2h soak 成功率 | ≥ 99% | | □ |
| 11 | 并发 | 目标路数无 OOM | 按合同 | | □ |

### 8.7 评估报告模板

```markdown
# 模型变更评估报告

- 变更内容：STT 由 <旧> 换为 <新>；TTS 由 <旧> 换为 <新>
- 变更原因：
- 评估环境：GPU <型号> / 驱动 <版本> / 镜像 <tag> / 权重 <来源与校验值>
- 评估数据集：<条数> 条，含 <覆盖维度>

## 1. 精度
| 指标 | 变更前 | 变更后 | 结论 |
|---|---|---|---|
| STT CER | | | |
| TTS MOS | | | |
| TTS 回读 WER | | | |

## 2. 性能
| 指标 | 变更前 | 变更后 | 结论 |
|---|---|---|---|
| STT 出字延迟 | | | |
| TTS RTF | | | |
| TTS TTFC | | | |
| 端到端 TTFA | | | |
| 显存占用 | | | |

## 3. 稳定性
（soak 时长、成功轮次、内存增长、容器重启次数）

## 4. 结论与放行意见
（接受 / 回退 / 有条件接受 + 整改项）
```

---

## 9. 运维与故障排查

### 9.1 常用命令

```bash
docker compose -f <compose> --env-file <env> ps          # 状态
docker compose -f <compose> --env-file <env> logs -f pipeline
docker compose -f <compose> --env-file <env> restart pipeline
docker compose -f <compose> --env-file <env> stop
docker compose -f <compose> --env-file <env> up -d --force-recreate pipeline

docker exec <pipeline> nvidia-smi                        # 容器内看 GPU
curl -s http://127.0.0.1:8765/v1/pool                    # 健康检查
```

### 9.2 故障速查表

| 现象 | 根因 | 处置 |
|---|---|---|
| 容器反复重启，日志 `ValueError: continue_final_message` | ASR 权重不是 `-hf` 版 | 换成 `Qwen3-ASR-1.7B` 的 HF 权重目录 |
| 启动卡死，日志停在 nltk | nltk 资源缺失且下载无超时 | 把 `nltk_data` 烤进镜像（§4.3），并打 tagger 路径补丁 |
| 容器 OOM 崩溃循环 | GPU 选错卡（`PIPELINE_GPU_ID` 回退 0，而 GPU0 被 LLM 占满） | 用 `--env-file` 显式指定 env；或在部署根放 `.env` 兜底 |
| TTS 每次生成 `CalledProcessError` | 镜像缺 `python3-dev` → triton JIT 缺 `Python.h` | 用 `Dockerfile.ttsfix` 派生镜像 |
| 启动卡在 `Loading weights` 后 `AttributeError: rope_theta` | transformers ≥5.15.1 与 torch 后端不兼容 | 用已固化补丁的镜像（`base = getattr(config,"rope_theta",10000.0)`） |
| **能跑但极慢**（RTF 3.7） | torch cu130 wheel 与驱动 12.8 不匹配 → 静默回退 CPU | 锁 cu128 wheel（`Dockerfile.cu128`）；`torch.cuda.is_available()` 应为 True |
| 容器访问内网 LLM 全部 502 | Docker/WSL2 NAT 到局域网返回 502（宿主正常） | 在宿主起反向代理中转（见 `llm-proxy.py`），LLM 基址指向 `host.docker.internal:<port>` |
| 有转写无音频 | TTS 后端/权重不匹配 | 看日志 `tts_ttfa=n/a`；确认 `--qwen3_tts_backend torch` 与权重目录 |
| 同一句出现多个气泡 | 渐进转写 + speculative 重开导致多次提交 | `--no_enable_live_transcription` + `--speculative_reopen_ms 0` |
| 首音很慢 | LLM 思考链未关 / TTS 非流式 / `stream_batch_sentences` 过大 | 关思考链、`--qwen3_tts_non_streaming_mode False`、`--stream_batch_sentences 1` |
| ASR/TTS 端点 503 | 模型尚未加载完 | 等 `Uvicorn running on ...` 再调 |
| ASR 首次调用 20~30s | lazy warmup（含图捕获） | 第二次起 <1s，属正常 |
| 重建容器后 ASR/TTS 端点 404 | 端点补丁未固化进镜像 | 用 `Dockerfile.local.rest` 重建镜像 |
| 服务起来但 `/v1/realtime` 连不上 | 无鉴权但端口被占 / 防火墙 | 确认 `docker ps` 端口映射与 `ss -lntp \| grep 8765` |

### 9.3 已知"良性"日志

| 日志 | 含义 | 是否处理 |
|---|---|---|
| `sox: not found` | 音频后处理缺 sox | 可忽略（镜像已装则不会出现） |
| `conversation_already_has_active_response` | 客户端显式 commit 与服务端 VAD 自动提交形成双提交 | 良性；客户端去掉 `input_audio_buffer.commit` |
| openai SDK 发出的 `session.update` 被判 invalid | 服务端按 openai 类型模型严格校验 | 不影响对话 |

### 9.4 安全基线

- 服务**默认无鉴权**，务必仅对内网开放 8765，或置于带鉴权的反向代理之后；
- 密钥只放在 `.env.*`（**确保被 git 忽略**），不要写进 compose 或代码；
- 若历史提交中已含密钥，**先轮换密钥**再谈清理历史；
- 客户现场交付前，确认 `.env.*` 与 `cache/` 未被打包进镜像层。

---

## 10. 附录

### 10.1 关键参数速查

| 类别 | 参数 | 默认 | 作用 |
|---|---|---|---|
| 判停 | `--min_silence_ms` | 700 | 静音判停；调小首音快但易抢话 |
| 判停 | `--thresh` | 0.6 | VAD 置信阈值 |
| 判停 | `--no_smart_turn` | 关 | 去掉语义二次确认（省 ~0.55s/轮） |
| 判停 | `--speculative_reopen_ms` | 800 | 软结束兜底；置 0 消除重复 |
| 编排 | `--stream_batch_sentences` | 3 | 凑够几句才送 TTS；设 1 压 TTFA |
| 编排 | `--chat_size` | — | 上下文长度，越小延迟越低 |
| 编排 | `--num_pipelines` | 1 | 并发路数（显存随之增长） |
| LLM | `--responses_api_reasoning_effort` | `none` | **非空即优先**发 `reasoning_effort`；置空才走下面的 disable_thinking |
| LLM | `--responses_api_disable_thinking` | True | 需与上一项**同时置空**才生效（发 `chat_template_kwargs.enable_thinking=false`） |
| LLM | `--llm_device` / `--llm_torch_dtype` | — | 本地 `transformers` 后端的设备与精度 |
| LLM | `--responses_api_request_timeout_s` | 20 | 上游超时 |
| TTS | `--qwen3_tts_non_streaming_mode` | True | 设 False 开句内流式 |
| TTS | `--qwen3_tts_streaming_chunk_size` | 8 | 块大小（越小首包越早、开销越大） |
| STT | `--qwen3_asr_language` | auto | 设具体语种可减少解码开销 |
| 字幕 | `--no_enable_live_transcription` | — | 关闭渐进转写，避免重复气泡 |

> 全量参数见 [`parameter-catalog.md`](./parameter-catalog.md)；
> 按"现象 → 参数组"组织的调参见 [`deployment-tuning-playbook.md`](./deployment-tuning-playbook.md)。

### 10.2 端口与路径

| 项 | 值 |
|---|---|
| pipeline 服务端口 | `8765`（`PIPELINE_PORT`） |
| 容器内权重路径 | `/root/.cache/`（宿主机 `./cache/` 挂载） |
| 容器内 VAD 路径 | `/opt/silero-vad`（宿主机 `./silero-vad` 挂载，只读） |
| 容器内 nltk 路径 | `/root/nltk_data`（建议烤进镜像，勿挂载） |

### 10.3 交付检查清单

**部署前**

- [ ] GPU 驱动版本与镜像 torch wheel 匹配（`torch.cuda.is_available() == True`）
- [ ] `docker info` 中 nvidia runtime 可见
- [ ] 权重目录齐全，ASR 为 `-hf` 版且含 `chat_template.jinja`
- [ ] `silero-vad` 权重在位
- [ ] nltk 资源已烤进镜像
- [ ] `.env.*` 已填写且被 git 忽略
- [ ] `PIPELINE_GPU_ID` 指向空闲卡

**上线前**

- [ ] 日志出现 LLM warmup 成功
- [ ] 日志出现 `Uvicorn running on http://0.0.0.0:8765`
- [ ] `/v1/pool` 返回正常
- [ ] ASR 独立接口返回正确转写
- [ ] TTS 独立接口返回有效非静音 WAV
- [ ] S2S 端到端脚本 `✅ 全链路成功`
- [ ] 显存占用在预算内
- [ ] 8765 未暴露到公网（或已有鉴权代理）

**评估与归档**

- [ ] 精度：CER / MOS / 回读 WER 达标
- [ ] 性能：RTF / TTFA / 出字延迟达标
- [ ] 稳定：2h soak 成功率 ≥ 99%
- [ ] 评估报告已填写并归档
- [ ] 回滚镜像 tag 已打好（`backup-<日期>`）


