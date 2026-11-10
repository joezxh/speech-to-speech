# 本地部署语音到语音（Speech-to-Speech）系统 · LLM 走第三方服务

> 🌐 Language / 语言：**中文版** · [English](./local-thirdparty-deployment.md)

本文档描述在本机（Windows + Docker Desktop + NVIDIA GPU）部署一套完整的语音到语音系统：
**LLM 使用第三方 OpenAI 兼容服务**，其余组件（ASR / TTS / VAD / 判停 / 编排）配置与
**现有 192.168.40.30 环境**（生产部署 `docker-compose.gpustack.yml`）保持一致；
同时把 **ASR 与 TTS 模型作为独立接口对外提供**，可脱离 S2S 会话单独调用。

---

## 1. 架构与组件清单

```text
                       ┌──────────────────────────────────────────┐
 客户端 ──WS /v1/realtime──▶  speech-to-speech pipeline (:8765)   │
                       │                                          │
 客户端 ──POST /v1/audio/transcriptions ──▶ ASR 独立接口          │
 客户端 ──POST /v1/audio/speech          ──▶ TTS 独立接口          │
                       │                                          │
       ┌───────────────┼───────────────┬──────────────┐        │
       ▼               ▼               ▼              ▼        │
  Qwen3-ASR-1.7B-hf  Qwen3-TTS      silero-vad    第三方 LLM    │
  (本地 ./cache)   (本地 ./cache)   (本地 ./silero-vad)  ▲      │
       GPU              GPU              CPU         │  外部 API │
                                                      └──────────┘
                                          (百炼 DashScope / DeepSeek / OpenAI …)
```

| 组件 | 本地实现 | 与 192.168.40.30 环境的关系 |
|---|---|---|
| ASR | Qwen3-ASR-1.7B-hf（`./cache/qwen3-asr-model-hf`） | **完全一致**（`--stt qwen3-asr` / `language=auto` / `device=auto`） |
| TTS | Qwen3-TTS CustomVoice（`./cache/qwen3-tts-model`） | **完全一致**（torch 后端 / cuda / 句内流式 chunk=4） |
| VAD | silero-vad（`./silero-vad` → `/opt/silero-vad`） | **完全一致**（`min_silence_ms=700`、`thresh=0.6`） |
| 判停 | 关闭 Smart Turn + speculative reopen | **完全一致**（避免重复气泡与首音延迟） |
| 转写输出 | 关闭 live transcription | **完全一致**（一句一气泡） |
| 编排 | `stream_batch_sentences=1` | **完全一致**（LLM 出首句即送 TTS） |
| 初始化 | system 角色 + 简短口语化 prompt | **完全一致** |
| **LLM** | **第三方 OpenAI 兼容服务（百炼 DashScope）** | **唯一差异项**（生产走局域网 GPUStack） |
| 镜像基座 | `speech-to-speech-local:cu130-1.2-rest` | 生产为 `Dockerfile.ttsfix`（同样已固化 ASR/TTS REST 端点） |

### 为什么 ASR/TTS 独立接口是"同一进程的多端点"

后端注册表里 `LLM_BACKENDS` / `TTS_BACKENDS` **没有 `none` 后端**（只有 `STT_BACKENDS` 有），
因此无法启动"只加载 ASR、不加载 LLM/TTS"的独立进程。与其为一个进程重复加载一份模型
（本机单卡 12GB 显存承受不起），正确做法是**在同一个 pipeline 进程内把已加载的模型
以独立 HTTP 端点暴露出来**——这也正是生产环境（192.168.40.30 基准）已在使用的暴露方式，
额外调用不产生任何额外显存开销。

---

## 2. 前置条件

| 项 | 要求 | 检查 |
|---|---|---|
| Docker Desktop | 支持 `nvidia` runtime | `docker info \| Select-String "Runtimes"` |
| NVIDIA 驱动 | ≥ 12.8（匹配镜像内 cu128 torch wheel） | `nvidia-smi` |
| 显存 | ≥ 8GB 可用（ASR 1.7B + TTS 1.7B） | `nvidia-smi --query-gpu=memory.total` |
| 模型权重 | `cache/qwen3-asr-model-hf`、`cache/qwen3-tts-model` | 见下 |
| VAD 权重 | `silero-vad/`（含 `src/silero_vad/data/silero_vad.jit`） | 见下 |
| 第三方 Key | OpenAI 兼容服务的 API Key | 填入 `.env.thirdparty` |

模型权重需已存在于 `speech-to-speech-src/` 目录下：

```text
speech-to-speech-src/
├── cache/
│   ├── qwen3-asr-model-hf/     # Qwen3-ASR-1.7B-hf（必须是 -hf 版）
│   ├── qwen3-tts-model/        # Qwen3-TTS-12Hz-1.7B-CustomVoice
│   └── nltk_data/              # nltk 资源（构建镜像时会烤进去）
├── silero-vad/                 # snakers4/silero-vad 仓库
```

> ⚠️ **必须用 `-hf` 版 ASR 权重**：handler 走 transformers 的
> `processor.apply_transcription_request()`，它需要 `-hf` 权重自带的 `chat_template.jinja`；
> 非 `-hf` 版会在 warmup 时抛 `ValueError: continue_final_message ...` 导致容器崩溃重启。

---

## 3. 部署步骤

### 3.1 构建镜像（含 ASR/TTS 独立端点补丁）

```powershell
cd d:\work\qwen-audio-agent\speech-to-speech-src
docker build -f Dockerfile.local.rest -t speech-to-speech-local:cu130-1.2-rest .
```

构建日志末尾应出现 `ASR/TTS REST endpoints baked OK`（自检行，缺失即说明补丁未生效）。

> 为什么要这一步：ASR/TTS 的 REST 端点由 `scripts/patch_pipeline_rest.py` 注入到
> `api/openai_realtime/websocket_router.py`。生产基座 `Dockerfile.ttsfix`（cu130-1.0）
> 已在构建期固化该补丁，但**本地基座 `Dockerfile.local`（cu130-1.1）原本缺失**，
> 导致本地镜像只有 WS 接口、ASR/TTS 无法单独调用。`Dockerfile.local.rest` 就是补这一层。

### 3.2 配置第三方 LLM

编辑 `.env.thirdparty`（已在 `.gitignore` 中，**不会入库**）：

```ini
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
```

切换服务商只需替换这三项：

| 服务商 | `LLM_BASE_URL` | `LLM_MODEL` |
|---|---|---|
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` / `qwen-max` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI 官方 | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 其它 OpenAI 兼容网关 | 各自的 `/v1` 地址 | 对应模型 id |

> **思考开关**：compose 传了 `--responses_api_disable_thinking`，服务会附带
> `chat_template_kwargs.enable_thinking=false`。已实测百炼接受该参数（返回 200）；
> 若某服务商报参数错误，把 compose 里该行换成 `--responses_api_reasoning_effort` + `"none"`。

### 3.3 启动

```powershell
docker compose -f docker-compose.thirdparty.yml --env-file .env.thirdparty up -d
docker compose -f docker-compose.thirdparty.yml --env-file .env.thirdparty logs -f pipeline
```

**首次启动约需 3~4 分钟**（加载 ASR 权重 → ASR warmup → LLM warmup → TTS 权重 + CUDA graph 捕获）。
就绪标志（日志末尾）：

```text
speech_to_speech.api.openai_realtime.server - INFO - OpenAI Realtime API starting on ws://0.0.0.0:8765/v1/realtime (pool size 1)
INFO:     Uvicorn running on http://0.0.0.0:8765
```

其中 LLM 打通的关键日志：

```text
speech_to_speech.LLM.chat_completions_language_model - INFO - ChatCompletionsApiModelHandler: warmed up! time: 2.872 s
```

停止 / 重启 / 查看状态：

```powershell
docker compose -f docker-compose.thirdparty.yml --env-file .env.thirdparty stop
docker compose -f docker-compose.thirdparty.yml --env-file .env.thirdparty restart pipeline
docker compose -f docker-compose.thirdparty.yml --env-file .env.thirdparty ps
```

---

## 4. 对外接口

服务统一监听 **`http://127.0.0.1:8765`**（`PIPELINE_PORT` 可改），共三个入口：

| 方法 | 路径 | 用途 | 模型 |
|---|---|---|---|
| `WS` | `/v1/realtime` | 完整 S2S 会话（OpenAI Realtime 协议） | STT + LLM + TTS |
| `POST` | `/v1/audio/transcriptions` | **ASR 独立接口**（OpenAI 兼容） | Qwen3-ASR-1.7B-hf |
| `POST` | `/v1/audio/speech` | **TTS 独立接口**（OpenAI 兼容） | Qwen3-TTS CustomVoice |

> 三个端点共用同一份已加载的模型：**额外调用不增加显存占用**，也不影响正在进行的 S2S 会话。
> 本地部署默认无鉴权；如需暴露到局域网，请在宿主机/网关层加反向代理与鉴权。

---

## 5. ASR 独立接口调用方式

`POST /v1/audio/transcriptions` —— 兼容 OpenAI `audio.transcriptions` 协议。

### 5.1 curl（multipart 表单，推荐）

```bash
curl -X POST http://127.0.0.1:8765/v1/audio/transcriptions \
  -F "file=@sample.wav" \
  -F "language=auto"
```

### 5.2 curl（裸二进制 body）

```bash
curl -X POST http://127.0.0.1:8765/v1/audio/transcriptions \
  -H "Content-Type: audio/wav" \
  --data-binary "@sample.wav"
```

### 5.3 Python + OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="not-needed")

with open("sample.wav", "rb") as f:
    result = client.audio.transcriptions.create(model="qwen3-asr", file=f)

print(result.text)
```

### 5.4 纯 Python（不依赖 SDK）

```python
import requests

with open("sample.wav", "rb") as f:
    resp = requests.post(
        "http://127.0.0.1:8765/v1/audio/transcriptions",
        files={"file": ("sample.wav", f, "audio/wav")},
        data={"language": "auto"},
        timeout=120,
    )
resp.raise_for_status()
print(resp.json()["text"], resp.json()["language"])
```

### 5.5 参数与响应

| 项 | 说明 |
|---|---|
| `file` | 音频文件；任意采样率/声道，服务端内部重采样到 16k 单声道 |
| `language` | `auto`（自动语种识别，默认）或具体语种码如 `zh` / `en` |
| `model` | 表单字段，默认 `qwen3-asr`（仅作标识，不影响推理） |

响应：

```json
{"text": "今天天气怎么样？", "language": "Chinese"}
```

| 状态码 | 含义 |
|---|---|
| `200` | 成功 |
| `400` | 未提供音频 / 解码失败（`detail` 给出原因） |
| `500` | 推理失败（`detail` 为 `asr failed: ...`） |
| `503` | STT handler 不可用（模型未加载完成） |

---

## 6. TTS 独立接口调用方式

`POST /v1/audio/speech` —— 兼容 OpenAI `audio.speech` 协议。

### 6.1 curl（JSON）

```bash
curl -X POST http://127.0.0.1:8765/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"今天天气怎么样","voice":"Aiden","response_format":"wav"}' \
  --output speech.wav
```

也支持表单形式：

```bash
curl -X POST http://127.0.0.1:8765/v1/audio/speech \
  -F "input=今天天气怎么样" \
  -F "voice=Aiden" \
  --output speech.wav
```

### 6.2 Python + OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="not-needed")

with client.audio.speech.create(
    model="qwen3-tts",
    voice="Aiden",
    input="今天天气怎么样",
    response_format="wav",   # 本服务只产出 WAV，务必显式指定 wav
) as resp:
    resp.stream_to_file("speech.wav")
```

> ⚠️ `response_format` 只支持 `wav`。OpenAI SDK 的默认值是 `mp3`，若不显式传 `wav`，
> 拿到的仍是 WAV 字节但文件后缀是 `.mp3`，部分播放器会因此报错。

### 6.3 纯 Python（不依赖 SDK）

```python
import requests

resp = requests.post(
    "http://127.0.0.1:8765/v1/audio/speech",
    json={"input": "今天天气怎么样", "voice": "Aiden", "response_format": "wav"},
    timeout=300,
)
resp.raise_for_status()
open("speech.wav", "wb").write(resp.content)
```

### 6.4 参数与响应

| 项 | 默认 | 说明 |
|---|---|---|
| `input` / `text` | 必填 | 待合成文本（`input` 优先） |
| `voice` / `speaker` | `Aiden` | CustomVoice 说话人（如 `Aiden` / `Ryan`） |
| `language` | `Auto` | `Auto` 或具体语种（如 `Chinese` / `English`） |
| `response_format` | `wav` | 仅 `wav` 有效 |

响应：`200`，`Content-Type: audio/wav`，body 为 WAV 字节流（24kHz 单声道）。

| 状态码 | 含义 |
|---|---|
| `200` | 成功 |
| `400` | `input` 为空 |
| `500` | 合成失败（`detail` 为 `tts failed: ...`） |
| `503` | TTS handler 不可用（模型未加载完成） |

---

## 7. S2S 主链路（WS /v1/realtime）

### 7.1 事件序列

```text
input_audio_buffer.append  x N   送入 16k PCM16 音频（base64）
input_audio_buffer.append 静音  尾部补静音，让服务端 VAD 收尾
（服务端 VAD 判定静音 → 自动提交 → STT 转写 → LLM → TTS）
response.audio.delta             助手音频（PCM16 base64）
response.audio_transcript.delta   助手文本增量
response.done                    本轮结束
```

> **不要额外发 `input_audio_buffer.commit`**：服务端 VAD 已在静音时自动提交，
> 显式 commit 会造成双重提交，进而在已有 response 进行中时收到
> `conversation_already_has_active_response` 错误（该错误为良性，不影响本轮对话结果）。

### 7.2 内置验证脚本

仓库已内置端到端验证脚本 `scripts/e2e_realtime_test.py`：

```powershell
# 在容器内跑（容器已装 websockets / soundfile / numpy）
docker cp scripts/e2e_realtime_test.py speech-to-speech-thirdparty-pipeline-1:/tmp/
docker cp prompt.wav speech-to-speech-thirdparty-pipeline-1:/tmp/
docker exec speech-to-speech-thirdparty-pipeline-1 \
  python3 /tmp/e2e_realtime_test.py --url ws://127.0.0.1:8765/v1/realtime \
  --audio /tmp/prompt.wav --out-dir /tmp/e2e
```

实测输出（百炼 `qwen-plus` + 本地 STT/TTS）：

```text
  用户转写 (STT)   : 你好，请用一句话介绍你自己。
  助手回复 (LLM)   : 你好！我是你的语音助手，随时帮你解答问题或完成任务。
  助手音频 (TTS)   : 5.25s / 167936 bytes
  STT 出字延迟     : 5.70s
  TTFA (首音)      : 6.13s
  端到端总耗时     : 9.93s
结论: ✅ 全链路成功
```

常用参数：`--chunk-delay`（模拟实时推送节奏）、`--silence-ms`（尾部静音）、
`--commit always`（显式提交）、`--timeout`。

---

## 8. 参数调优

`.env.thirdparty` 中可调（默认值已与生产环境一致）：

| 变量 | 默认 | 作用 |
|---|---|---|
| `MIN_SILENCE_MS` | `700` | 静音判停阈值。调小→首音更快但更容易抢话；调大→更稳但更慢 |
| `VAD_THRESH` | `0.6` | VAD 置信阈值。调高抗噪/降误触发；调低提灵敏度 |
| `PIPELINE_PORT` | `8765` | 对外端口 |
| `PIPELINE_GPU_ID` | `0` | 预留给 STT+TTS 的 GPU 编号 |

需要更多参数（如 `--qwen3_tts_speaker`、`--qwen3_asr_language`）时，直接改
`docker-compose.thirdparty.yml` 的 `command` 段即可，编排文件头部有逐项对照说明。

---

## 9. 常见问题

| 现象 | 原因与处理 |
|---|---|
| 启动很慢（3~4 分钟） | 正常：加载 ASR 权重 + ASR warmup + LLM warmup + TTS CUDA graph 捕获 |
| 容器反复重启，日志有 `ValueError: continue_final_message` | ASR 权重不是 `-hf` 版，换成 `cache/qwen3-asr-model-hf` |
| 启动卡死在 nltk 下载 | 镜像已烤入 nltk 资源；**不要**挂载 `nltk_data` 到容器（Windows 挂载点权限 777，nltk 会拒绝并转去联网下载） |
| 日志 `sox: not found` | 非致命警告（音频后处理），镜像已装 sox 可忽略 |
| ASR/TTS 端点返回 503 | 模型尚未加载完成，等日志出现 `Uvicorn running on ...` 再调用 |
| ASR 首次调用 20~30s | lazy warmup（首次推理含图捕获），第二次起 <1s |
| 第三方 LLM 报参数错误 | 把 `--responses_api_disable_thinking` 换成 `--responses_api_reasoning_effort` + `"none"` |
| 容器访问不到第三方 API | 检查宿主是否需要代理；本机 `docker` 容器可直连公网（百炼已实测 200） |

---

## 10. 安全提示

- `.env.thirdparty` 已加入 `.gitignore`，**不会入库**；但 `.env.local` / `.env.gpustack`
  历史上已被 git 跟踪且内含 GPUStack API Key，**建议尽快轮换该 Key 并将这些文件改为
  `git rm --cached` + 只保留 `.example` 模板**。
- 本地部署默认**无鉴权**，三个端点均可被本机任意进程调用；仅监听回环地址是默认保护。
  若需对外提供，请在反向代理层加鉴权与限流。
- 容器以 `restart: unless-stopped` 运行，宿主重启后会自动拉起。

---

## 11. 相关文件

| 文件 | 作用 |
|---|---|
| `docker-compose.thirdparty.yml` | 本部署的编排（LLM 走第三方，其余对齐 192.168.40.30 环境） |
| `.env.thirdparty` | 第三方 LLM / 端口 / VAD 参数（不入库） |
| `Dockerfile.local.rest` | 在本地基座镜像上固化 ASR/TTS 独立端点补丁 |
| `scripts/patch_pipeline_rest.py` | ASR/TTS REST 端点的注入补丁（构建期执行） |
| `scripts/e2e_realtime_test.py` | S2S 端到端验证脚本 |
| `docker-compose.gpustack.yml` | 生产基准编排（LLM 走局域网 GPUStack 192.168.40.30） |
