# 本机启用 speech-to-speech 独立服务（ASR / TTS / 声纹 / 情感）

> 适用：PyCharm 里以源码启动的 `s2s-pipeline-prod`（`127.0.0.1:8765`），console 后端独立在 `127.0.0.1:8000`，前端 `:3000`。
> 参照部署：`docker-compose.voiceprint.yml` + `.env.thirdparty`（声纹），以及 `D:/work/mediation_platform/mediation-deploy/ser`（情感识别）。
> 本阶段不改动 console 业务逻辑与前端；服务级负载均衡设计见本文末「后续阶段」。

## 1. 能力盘点（以本机 8765 的 `/openapi.json` 实测为准）

| 能力 | 启用前 | 实现链路 / 端点 |
|---|---|---|
| 全双工语音 | ✅ 已具备 | `config/prod.yaml` 的 `pipelines.prod`（`num_pipelines: 1`）：VAD `silero`（`min_silence_ms: 450`、`smart_turn: false`）→ STT `qwen3-asr-0.6b-hf`（cuda/bfloat16/zh）→ LLM `chat-completions` Qwen3-8B @ `192.168.40.30/v1` → TTS `qwen3`（torch/cuda/chunk 4）。入口 WS `/v1/realtime`、WebRTC `/v1/realtime/calls`；`GET /v1/pool` 返回 `size=1` |
| ASR 独立服务 | ❌ 无 REST 入口 | 新增 `POST /v1/audio/transcriptions`，复用同进程 `Qwen3ASRSTTHandler`（16k 解码 → `asyncio.to_thread(_transcribe)`） |
| TTS 独立服务 | ❌ 无 REST 入口 | 新增 `POST /v1/audio/speech`，复用同进程 `Qwen3TTSHandler`（克隆/预设音色分流，wav 输出） |
| 声纹识别 | ❌ 无 REST 入口 | 新增 `POST /v1/audio/embeddings`、`GET /v1/audio/embeddings/capability`；`VoiceprintService` 方案 C（CPU 独立 speaker encoder，2048 维，对称 Bearer） |
| 情感识别 | ❌ 全仓未实现 | 新增 `POST /v1/audio/emotion`、`GET /v1/audio/emotion/health`；代理到现成 `emotion2vec_plus_large` SER 服务 |

启用前 8765 的 OpenAPI 只有 7 条路径（`/v1/pool`、`/v1/usage`、`/v1/realtime/calls` POST/DELETE、`/v1/responses`、`/v1/chat/completions`、`/admin/sessions/update`）；WebSocket 路由不进 OpenAPI。

## 2. 根因：端点原本只在容器镜像里

`scripts/patch_pipeline_rest.py` 与 `scripts/patch_voiceprint_embeddings.py` 把路由作为**字符串**注入容器内 `/usr/src/app/src/speech_to_speech/api/openai_realtime/websocket_router.py`，由 `Dockerfile.voiceprint` 在构建期固化。PyCharm 跑的是仓库源码，因此：

- 只改 `config/prod.env` / `config/prod.yaml` **不会**让端点出现；
- 本轮把注入体抽成三个源码模块，由 `create_app()` 直接挂载，源码与容器共用一套语义：

| 模块 | 挂载函数 | 开关 |
|---|---|---|
| `api/openai_realtime/audio_services.py` | `mount_audio_services(app, pool)` | 总是注册（复用 pipeline 内已加载 handler） |
| `api/openai_realtime/voiceprint_routes.py` | `mount_voiceprint(app, pool)` | `VOICEPRINT_ENABLED=true` |
| `api/openai_realtime/emotion_routes.py` | `mount_emotion(app)` | `SER_ENABLED=true` 且 `SER_BASE_URL` / `SER_API_KEY` 均非空 |

三个模块都有路由存在性检查，重复挂载不会注册第二份；两个补丁脚本降级为旧基座镜像的兼容层（检测到源码模块存在即跳过注入），`Dockerfile.voiceprint` / `Dockerfile.local.rest` 的自检同时接受「源码模块」与「旧补丁」两种形态，容器对外端点清单不变。

## 3. 配置：为什么是 env 驱动

`src/speech_to_speech/config.py:429` 的顶层键白名单只允许 `schema_version / runtime / blocks / pipelines / models`，`:154-161` 的 `_mapping()` 遇未知字段直接报 `Unknown field; use only documented fields.`。因此**没有**在 `config/prod.yaml` 新增 `services:` 段（方案 B：需同步改 `config.py`、`ResolvedConfig`、参数平台 catalog/renderer，影响面大，留作后续升级路径）。

采用方案 A：

- `config/prod.env` 承载全部开关（PyCharm 的 EnvFile 就是该文件）；
- `config/prod.yaml` 只在允许的 `blocks.*.settings` 内把权重路径改为 `{env: NAME}` 联动，并补充服务清单与映射注释；
- `validate_config()` 与 `resolve_config()` 均已实测通过。

### 3.1 变量映射表

| 变量 | 取值来源 | 本机值 |
|---|---|---|
| `S2S_ASR_MODEL_DIR` / `S2S_TTS_MODEL_DIR` | 本机 `cache/` 相对路径 | `cache/qwen3-asr-0.6b-hf` / `cache/qwen3-tts-model` |
| `VOICEPRINT_ENABLED` / `_API_KEY` / `_MODEL` | `.env.thirdparty` | `true` / `vp_local_dev_key_change_me` / `qwen3-tts-base-speaker` |
| `VOICEPRINT_MAX_AUDIO_MS` / `_MAX_BYTES` / `_MIN_SPEECH_MS` | 同上 | `30000` / `10485760` / `800` |
| `VOICEPRINT_STRICT_REJECT` | 同上 | `false`（探测音频是 440Hz 纯音，只拒全静音） |
| `VOICEPRINT_QUEUE_CAPACITY` / `_MAX_CONCURRENCY` / `_INFER_TIMEOUT_MS` | 同上 | `16` / `4` / `3000` |
| `VOICEPRINT_ENCODER_DIR` | **本机新增**（容器用 `/root/.cache/qwen3-speaker-encoder`） | `cache/qwen3-speaker-encoder` |
| `SER_ENABLED` / `SER_BASE_URL` / `SER_TIMEOUT_MS` | 本机新增（已切 GPU 编排） | `true` / `http://127.0.0.1:8023/ser` / `5000` |
| `SER_API_KEY` | mediation `ser/.env` 的 `API_KEY` | **留空，需手工填写**；空值时 8765 不注册情感路由、不转发任何请求（fail-closed） |

> `config/prod.env` 由参数平台 `renderer_service.py` 渲染，但 `render_env` 保留未知键，且 publish 对任何 `stage: env` 的 patch 直接返回 409 `env_requires_recreate`，因此新增变量不会被下次 publish 清掉；换机器部署仍需手工同步该清单。

> **版本控制状态**：`config/prod.env` 与 `.idea/runConfigurations/` 均被 `.gitignore` 忽略
> （`git ls-files config/prod.env` 为空、`git status --short` 不列出它们）。上述 env 改动与
> 新增的 `s2s_pipeline_prod.xml` 只作用于本机，不会随提交带走；换机器需按 §3.1 手工回填，
> 或另建一份非忽略的模板文件。

## 4. 声纹：方案 C 权重准备

TTS 保持 CustomVoice 预设音色（首音 1.85s），声纹只用从 Base 权重切出的 CPU speaker encoder（+22.9 MiB，不占显存）：

```powershell
cd D:\work\qwen-audio-agent\speech-to-speech-src
.venv\Scripts\python.exe scripts/extract_speaker_encoder.py `
  --model-dir cache/qwen3-tts-base `
  --out-dir cache/qwen3-speaker-encoder
```

产物 `speaker_encoder.safetensors` + `config.json`（校验 `speaker_encoder.*` 存在、不含 `talker.*`），二进制不入库。`VoiceprintService.attach_pool(pool, encoder_dir)` 已在启动期从 `config.json` 的 `enc_dim` 定维并 `warmup()` 预热，避免 librosa/numba 首次 JIT 造成首请求超时。

## 5. 情感：复用现成模型与 SER 服务

`D:/work/mediation_platform/mediation-deploy/ser` 已就位：

- 权重 `models/model.pt`（1855.7 MB，`iic/emotion2vec_plus_large`）+ `config.yaml` / `tokens.txt` / `example/test.wav`，**无需下载或训练**；
- 服务 `emotion2vec/app.py`（FastAPI，`POST /v1/audio/emotion` multipart、`GET /health`）、`funasr.AutoModel`、9→5 标签映射、静音 409、`unk` 拒分类、并发门 429；
- nginx `X-API-Key` 网关（CPU `8020/8021`、GPU `ser-gpu` `8022/8023`），权重只读挂载 `./models:/models:ro`；
- 离线 wheel 9 个（Linux cp310）、`.env` 里 `API_KEY` 已配置。

**采用代理而非同进程加载**，理由：离线 wheel 是 Linux/CPython 3.10 版，无法装进 Windows 的 s2s `.venv`（torch 2.11.0+cu128，缺 `funasr`/`modelscope`）；8765 同机已有 ASR+TTS 占 GPU，SER GPU 版 2 并发显存峰值约 4796 MB、GPU util 100%，README 明确警示同机算力争抢。代理方案零依赖冲突、零显存冲突，且 8765 仍是统一入口。

8765 侧 `mount_emotion()` 用 `httpx.AsyncClient` 原样转发 multipart body，服务端注入 `X-API-Key`，**不透传浏览器自带的 `Authorization`**；透传 400/409/429/500/502，`TimeoutException` → 504 `SER_TIMEOUT`，`RequestError` → 503 `SER_UNREACHABLE`；音频只在内存，不落盘、不进日志。

本机部署 GPU 编排（已替换 CPU 编排）：

```powershell
cd D:\work\mediation_platform\mediation-deploy\ser
docker compose --env-file .env -f docker-compose.gpu.yml up -d --build   # project ser-gpu，8022/8023
curl.exe http://127.0.0.1:8023/ser-nginx-health                          # 免鉴权探针
docker exec emotion2vec-gpu python -c "import torch; a=torch.randn(1024,1024,device='cuda'); print(float((a@a).sum().item())!=0)"  # CUDA kernel
curl.exe -s -F "file=@models\example\test.wav" -F "sample_rate=16000" -F "language=zh" http://127.0.0.1:8022/v1/audio/emotion   # 预热
```

首次真实推理会加载 1.81GB 权重并做 CUDA warmup（本机实测约 17s），**必须预热**，首请求不计入业务流量。回退 CPU 编排：`docker compose --env-file .env -f docker-compose.yml up -d`（镜像 `emotion2vec:1.0` 保留）。

### 5.1 本机 CPU / GPU 实测对比（2026-11-16）

同一脚本、同一合成音频（16k 单声道）、直连推理端口（CPU 8021 / GPU 8022），预热后稳态；CPU 每档 1–4 轮、GPU 每档 10 轮：

| 音频 | CPU P50 / P95 | GPU P50 / P95 | 提效（P50） |
|---|---|---|---|
| 1s | 535 / 553 ms | 89 / 169 ms | 6.0× |
| 3s | 877 / 881 ms | 83 / 109 ms | 10.6× |
| 10s | 3633 / 3894 ms | 121 / 151 ms | 30.1× |
| 30s | 16516 / 17146 ms | 327 / 354 ms | 50.5× |
| 60s | 50407 ms | 757 / 779 ms | 66.6× |

- 吞吐：3s 音频 1.14 → 12.08 rps（10.6×）；2 并发 8 次 3s 1.565 → 16.44 rps（10.5×，8/8 200）。
- 资源：容器 CPU 峰值 728% → 194%（约 3.8× 降低）；GPU 版 `gpu_available=true`、`device=cuda:0`、torch 2.7.1+cu128 / CUDA 12.8 / RTX 5070 Ti Laptop，真实 matmul 通过。
- 长音频 RTF：CPU 0.55–0.84 → GPU 0.011–0.013；60s 音频从 1.19× 实时提升到 79× 实时。
- 结论：**实测提效 6–67×，音频越长收益越大，10s 以上约 30–67×**。此前按 README 历史数据估的 50–90× 偏高，以本表为准。

**性能与门禁（务必知悉）**：GPU 预热后 60s P95 779ms，满足 1500ms 门禁；`SER_TIMEOUT_MS=5000` 给共存抖动留余量。mediation 侧 `MEETING_SER_ENABLED=false` 且 U5 人检待测，本项目只复用模型与实现，**该能力按「能力可用 / 影子模式」使用，不接入业务链路**。GPU 编排与本机 8765 的 ASR+TTS 共存需复测算力争抢（README：2 并发显存峰值约 4796 MB / 12227 MB、GPU util 100%）。

> 同进程加载（备选）代价：Windows 侧另装 funasr/modelscope 并验证与 torch 2.11+cu128 的兼容性、承担 GPU 争抢与约 60s 冷启动预热。仅在明确要求「情感必须与 ASR/TTS 同进程」时采用。

## 6. 启动顺序

1. 准备声纹权重（§4）与 `config/prod.env`（§3.1，含手填 `SER_API_KEY`）。
2. 启动并预热 GPU 版 SER 服务（§5），确认 `8023/ser-nginx-health` 与 `8022/health` 的 `ready=true`。
3. PyCharm 选 **`s2s-pipeline-prod`**（`.idea/runConfigurations/s2s_pipeline_prod.xml`：`serve -f config/prod.yaml --name prod`，EnvFile `config/prod.env`，不带 `--with-console`）→ 8765。
4. console 后端保持 `s2s-console-backend` 在 8000 独立运行，前端 `:3000`。

不要选 `s2s-pipeline-prod-with-console`：它带 `--with-console`，会让 console 在 8765 同进程再起一份，与 8000 并存。`CONSOLE_AUTOSTART=true` 是 s2s CLI 的开关，对独立 `uvicorn app.main:app` 无效。

> 改动源码后必须**重启** 8765 进程才会出现新端点；`/openapi.json` 是最快的核对方式。

## 7. 冒烟清单

| 检查 | 命令 / 期望 |
|---|---|
| 端点清单 | `curl.exe http://127.0.0.1:8765/openapi.json` 出现 6 条新路径（transcriptions / speech / embeddings / capability / emotion / emotion/health） |
| ASR | `POST /v1/audio/transcriptions` multipart wav → `{"text":...,"language":...}`；缺 handler 503 |
| TTS | `POST /v1/audio/speech` `{"input":"你好"}` → `Content-Type: audio/wav`，RIFF 头；缺 handler 503 |
| 声纹 capability | `GET /v1/audio/embeddings/capability` + `Authorization: Bearer <VOICEPRINT_API_KEY>` → `200`，`dim=2048` |
| 声纹鉴权 | 无 Bearer → `401 UNAUTHORIZED`；`model=rr` → `400 MODEL_MISMATCH` |
| 声纹嵌入 | `POST /v1/audio/embeddings` 带 Bearer → 200 且 `len(embedding)==dim`；不得返回全零或默认向量 |
| 情感 | `POST /v1/audio/emotion` multipart `models/example/test.wav` + `sample_rate=16000` → 200；静音 → 409；下游超时 → 504；下游不可达 → 503 |
| 回归 | WS `/v1/realtime` 可用；`GET /v1/pool` 200；console `:8000` 集群总览不再有 `pool_unreachable`；`ALLOCATOR_MODE=off` 语义不变 |

契约测试：`pytest tests/test_audio_service_routes.py tests/test_emotion_proxy.py`（挂载幂等、开关、handler 缺失、Bearer/model 错误码、代理透传与超时、prod.yaml 白名单）。

## 8. 后续阶段（本轮不实施）

- 统一 `GET /v1/capabilities`：一次请求聚合五类服务的 `enabled/ready/endpoint/model/dim/capacity/inUse`，避免 console 为每类服务各打一次探测。
- ~~console 服务级负载均衡~~ **已实现**（spec 2026-11-16，见
  `docs/superpowers/specs/2026-11-16-console-s2s-load-balancing-design.md`）：
  `CONSOLE_LB_MODE=proxy` 下 console 按实例注册表选台，能力指纹按能力维度过滤，
  故障摘除用 `drain`，ASR/TTS/声纹/情感由 `/v1/audio/*` 反代。**未覆盖**的部分：
  `POST /api/v1/services/{service}/dispatch` 这个统一 dispatch 端点、可选流式反代、
  前端能力筛选与分组 KPI 仍未做。
- 情感服务的异构实例注册（SER 作为独立能力实例，而非 8765 同进程能力）。
- 兼容性前提：`ALLOCATOR_MODE=off`、`_collect_legacy()`、`/v1/audio/embeddings/capability` 别名、现有集成测试语义不破坏。

> **入口变了**：交付形态（`docker-compose.yml`）不再 publish 8765，外部调用方统一
> 走 console 的 `/v1/audio/*`（`http://host:8000/v1/audio/transcriptions` 等），浏览器
> 走同源 `/v1/realtime`。本文里的 `curl http://127.0.0.1:8765/...` 仍适用于本机源码
> 调试与 `docker-compose.local.yml`（它保留 publish）。

