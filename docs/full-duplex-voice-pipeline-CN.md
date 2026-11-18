# 全双工语音对话：前端→后端→pipeline 全链路梳理与慢响应诊断

> 适用范围：本机 PyCharm 运行配置 `s2s-pipeline-prod`（源码 `serve -f config/prod.yaml --name prod`，监听 `0.0.0.0:8765`）、console 后端 `:8000`、console 前端 Vite `:3000`。
> 诊断日期：2026-11-18。本文同时是「页面 / 代码 / 方法」三级链路索引与本次慢响应根因记录。

---

## 0. 当前运行态（诊断时实测）

| 组件 | 进程 / 端口 | 说明 |
|---|---|---|
| S2S pipeline | PyCharm `speech_to_speech.cli serve -f config/prod.yaml --name prod`，PID 48828，`0.0.0.0:8765` | 真正的「s2s-pipeline-prod」，源码启动，非 Docker 容器 |
| console 后端 | `uvicorn app.main:app --host 127.0.0.1 --port 8000`，PID 34216 | 反代 + 负载均衡 + 配置/实例管理 |
| console 前端 | Vite `:3000` | 全双工语音对话页面 |
| GPU | RTX 5070 Ti Laptop 12GB | 诊断时显存被 LM Studio / llama.cpp 挤占（见 §3） |

> 注意：Docker 里那个 `speech-to-speech-voiceprint-pipeline-1` 容器已 `Exited (137)` 三天，**与当前对话链路无关**。

`/v1/pool` 实测 `size=1 / in_use=1`，pipeline 配置为单 unit（`num_pipelines: 1`），一次只服务一个会话。

---

## 1. 全链路总览

```
浏览器 (:3000)
  │  VoiceView.vue  →  S2sClient (OpenAI Realtime SDK)
  │  采集: getUserMedia + mic-capture AudioWorklet(40ms/24k)
  │  播放: audio-playback AudioWorklet
  │  事件: session.update / input_audio_buffer.append / response.create …
  │  WS 同源 /v1/realtime（或 WebRTC /v1/realtime/calls）
  ▼
console 后端 (:8000)  app.routers.realtime.realtime()
  │  短票据 issue_realtime_ticket()
  │  LB(proxy): 选台 reserve→hold→release；逐帧双向转发，无缓冲，compression=None
  ▼
pipeline (:8765)  websocket_router.realtime_endpoint()
  │  RealtimeService.register() → 事件分派 → pipeline unit
  ▼
pipeline 编排  s2s_pipeline.py  _build_handlers()
  VAD(silero) → STT(qwen3-asr-0.6b, cuda/bf16) → LLM(chat-completions, GPUStack Qwen3-8B) → TTS(qwen3 torch/cuda, chunk=4)
  │
  └─ 首音音频 + response.done metadata(TURN_LATENCY) 原路回传 → 浏览器播放
```

可选旁路：情感代理 `POST /v1/audio/emotion` → SER 服务 `8023`；声纹 `POST /v1/audio/embeddings` → CPU speaker encoder。二者不参与全双工主链路。
STV 口型阶段（`src/speech_to_speech/STV`）默认关闭（`enable_visemes=False`），不在主链路。

---

## 2. 页面 / 代码 / 方法 三级索引

### 2.1 前端（console/frontend）

| 层 | 文件（相对仓库根） | 关键方法 / 符号 | 作用 |
|---|---|---|---|
| 路由 | `console/frontend/src/router/index.ts` | `/` → `name:'voice'` → `VoiceView.vue` | 应用首页即语音对话页 |
| 页面 | `console/frontend/src/views/VoiceView.vue` | `connect()` :237、`stop()`、`teardown()` :388、`restart()` :414；`<OrbStage @activate="connect">` :532 | 按钮入口、通话生命周期、历史与延迟展示 |
| 传输客户端 | `console/frontend/src/features/voice/transport/s2s-client.ts` | `S2sClient.connect()` :268、`openSession()` :301、`onAudio()` :434、`handleCaptureMessage()` :525、`updateSession()` :568 | 建连、RealtimeSession 配置、音频收发、打断 |
| 地址决策 | 同上 | `directSocketUrl()` :261、`buildDirectWsUrl()` :64 | `s2sUrl=''` → 走同源 `/v1/realtime`（console 反代选台）；填钉死地址才直连 |
| 票据 | `console/frontend/src/composables/useRealtimeTicket.ts` | `appendRealtimeTicket()` :18 | WS 短票据（来自 `POST /api/v1/realtime/ticket`） |
| 音频采集 | `console/frontend/src/features/voice/audio/capture.ts` | `acquireMic()` :8 | `getUserMedia`，EC/NS/AGC 开 |
| 上行 worklet | `console/frontend/public/worklets/mic-capture.js` | 40ms/960 样本，降采样到 24k，噪声门 | PCM16 分块送 `input_audio_buffer.append` |
| 下行 worklet | `console/frontend/public/worklets/audio-playback.js` | 播放缓冲阈值 | 默认 `playbackBufferMs:0`（见 `stores/voice.ts` :31） |
| 本地 VAD | `console/frontend/src/features/voice/audio/vad.ts` | `startLocalVad()` :15 | 默认开，仅 UI 提示，不阻断上行；服务端 VAD 才是真提交者 |
| 延迟展示 | `console/frontend/src/features/voice/transport/turn-latency.ts`、`features/voice/useTurnLatency.ts`、`components/TurnLatencyPanel.vue` | `readTurnLatency()` | 解析 `response.done` metadata 的分阶段延迟 |
| 状态 | `console/frontend/src/stores/voice.ts` | `allowDirect`、`s2sUrl`、`playbackBufferMs`、`localVad` | 连接/播放参数 |
| 开发代理 | `console/frontend/vite.config.ts` | `/v1` `ws:true` → `VITE_DEV_BACKEND`（默认 `:8000`） | 开发态把同源 WS 转到 console |

**关键事件序列（浏览器侧）**

```
connect() → acquireMic() → appendRealtimeTicket() → setupAudio()（两个 AudioWorklet）
  → openSession():  new RealtimeSession({ turnDetection:{type:'server_vad',interruptResponse:true},
                                          outputModalities:['audio'], input rate 24000 })
  → session.connect({apiKey:'s2s-local', url}) → 开场问候 sendMessage()
上行: mic-capture worklet → handleCaptureMessage() → session.sendAudio() → input_audio_buffer.append
打断: conversation.item.truncate
提交/作答: 由服务端 VAD 自动 commit 并建 response；浏览器不主动 commit
```

### 2.2 console 后端（console/backend）

| 文件 | 关键方法 / 符号 | 作用 |
|---|---|---|
| `app/config/_console.py` | `pipeline_base_url='http://127.0.0.1:8765'` :17；`lb_mode` :71（默认 off，env `CONSOLE_LB_MODE`）；首帧超时 5s :73 | 后端连 pipeline 的配置 |
| `app/core/router_registry.py` | `app.include_router(realtime.router)` :80-83 | 注册实时路由 |
| `app/routers/realtime.py` | `realtime()` WS `/v1/realtime` :186；`_proxy_with_failover()` :219（proxy 模式）；`_proxy_to_loopback()` :198（off 模式）；`_pump()` :170、`_client_to_upstream()` :151、`_upstream_to_client()` :162；`issue_realtime_ticket()` :33 | 反代：`proxy` 模式选台 + 预留 + 逐帧转发，`compression=None` 关闭压缩避免首字节凑块延迟 |
| `app/services/upstream_resolver.py` | `rank_session()` :117、`inflight_enter/exit()` :61 | 上游选台与在途计数 |
| `app/services/allocator_store.py`（及 DB 版 `db_allocator_store.py`） | `reserve()` :115、`hold()` :135、`release()` :130 | 实例槽位预留/占用/释放 |
| `app/routers/instances.py` | `register_instance()` :96 | pipeline 实例注册 |
| `app/services/calls_service.py` | `forward_selected()` :90 | WebRTC SDP 反代到选中实例 |

> proxy 模式（`CONSOLE_LB_MODE=proxy`）在 accept 浏览器前先连上游等第一帧 `session.created`（最长 5s），这是一次性建连开销，不按轮次产生。

### 2.3 pipeline（src/speech_to_speech，:8765）

| 文件 | 关键方法 / 符号 | 作用 |
|---|---|---|
| `api/openai_realtime/websocket_router.py` | `realtime_endpoint()` WS `/v1/realtime` :690；`_claim_unit()` :677；`_dispatch_client_event()` :408；`handle_audio_append()` :452、`handle_audio_commit()` :457、`handle_session_update()` :490、`handle_response_create()` :517；`GET /v1/usage` :758、`GET /v1/pool` :782 | WS 入口、事件分派、观测端点 |
| `api/openai_realtime/webrtc_session.py` | `WebRTCSession.negotiate()` :354、`_consume_inbound_audio()` :542 | WebRTC 媒体/数据通道 |
| `api/openai_realtime/service.py` | `RealtimeService.register()` :477、`handle_session_update()` :593、`handle_audio_append()` :601、`handle_audio_commit()` :607、`dispatch_pipeline_event()` :714 | 会话状态机、管线驱动 |
| `s2s_pipeline.py` | `_build_handlers()` :408（doc :430 `VAD → STT/AudioInput → LM → TTS`）；VAD :433、STT :510、LM :549、`LMOutputProcessor` :558、TTS :572；`build_pipeline()` :777、`build_local_pipeline()` :819 | handler 编排 |
| `STT/qwen3_asr_handler.py` | `setup()` :67、`_transcribe()` :109、`process()` :147、`warmup()` :103 | Qwen3-ASR 转写，`model.generate` 自回归解码 |
| `LLM/chat_completions_language_model.py`、`LLM/base_openai_compatible_language_model.py` | `_build_extra_body()` :337、`_build_chat_optional_kwargs()` :96 | 关思考链、攒句、tools |
| `TTS/qwen3_tts_handler.py` | 首音日志 `_log_first_audio_latency()` :882 | TTS 流式出音频 |
| `VAD/vad_handler.py` | `_apply_runtime_turn_detection()` :225、决策打点 :858 | 静音检测与轮的收尾 |
| `pipeline/turn_latency.py` | `TurnLatencyTracker` :107、`format_log_line()` :288 | 分阶段延迟记录，写 `TURN_LATENCY ` 日志行 |
| `api/openai_realtime/handlers/response.py` | `response.done` metadata 写入 :580-594 | 把延迟带到前端 |
| `agent/collectors.py` | `tail_turn_latency()` :225 | agent 采集日志行入库（生产环境；本机 PyCharm 无此日志落点） |

---

## 3. 慢响应根因诊断（2026-11-18 实测）

### 证据

1. **GPU 显存被外部进程挤占（主因）**
   - `nvidia-smi`：RTX 5070 Ti 12GB 已用 **10.1GB**，剩 ~2GB；占用方除 pipeline（PID 48828）外，还有用户手动启动的 **LM Studio（PID 9184，11:03 起，Qwen3.5-0.8B + mmproj）** 与 llama.cpp server（PID 15392）。
   - `model_metrics.log` 中 STT 采样：`gpu_util_avg_percent` 仅 **5–14%**、峰值虽偶到 62% 但均值低；`ram_percent_avg` 高达 **88–93%**。
   - STT 耗时：1.4s 音频 → 1.37s、1.6s → 2.0s、2.6s → 3.26s（**RTF ≈ 1，即转一句要等一句那么久**）；5–7s 长句达 13–21s。
   - **用户已终止 LM Studio**，显存降至 8.4GB，仅剩 pipeline 进程——这是最直接的提速项。

2. **LLM 配置漂移（次因，已修）**
   - `config/prod.yaml` 原写 `model_name: qwen3.8-27b` + 百炼 maas 域名，与 `config/prod.env` 注释「当前 LLM 走 GPUStack」矛盾；`qwen3.8-27b` 并非有效模型名。
   - `/v1/usage`（累计）显示 3 次完成响应产生 **18084 output tokens（约 6k/次）**，对语音助手异常——长回复直接拉长按句送 TTS 的总时间。
   - 修复：LLM 段改用 `{env: GPUSTACK_MODEL}`（Qwen3-8B）、`GPUSTACK_BASE_URL`、`GPUSTACK_API_KEY`；关思考链。实测 GPUStack 关思考链后短回复 **1.26s / 43 tokens**，且走内网无公网抖动。

3. **结构性延迟（设计固有，可接受）**
   - VAD `min_silence_ms: 450`：每轮结束固定等 0.45s 静音才提交 STT（已从 700ms 优化到此，iterator 默认 300ms，再降有误切风险）。
   - STT 自回归 `generate` + `gen_max_new_tokens: 128`：长音频解码本身耗时。
   - `stream_batch_sentences: 1`、`qwen3_tts_streaming_chunk_size: 4`：已是偏低的首包友好配置，保持不变。
   - console proxy 模式：建连时一次性选台/等首帧，不按轮产生。

### 第二轮复查（14:5x，用户反馈「还是太慢」后）

关键发现：**上一轮的 `prod.yaml` 修改从未生效**。

| 时间 | 事件 |
|---|---|
| 11:40:43 | pipeline 进程 PID 48828 启动，加载的是当时的旧 `prod.yaml`（百炼 qwen3.8-27b） |
| 14:50:50 | `prod.yaml` 被修改为 GPUStack Qwen3-8B |
| 14:53 之后 | `/v1/usage` 涨到 11 次响应 / 41416 output tokens（新增 8 次约 2916 tokens/次）并出现 5 次 `response_failed` —— 说明仍跑旧配置（无效模型名是 `response_failed` 的疑似来源） |

源码启动进程**不热加载 YAML**，改文件不会自动生效。因此「还是太慢」的直接原因是配置改动未被加载，而非新瓶颈。

其他复查数据：
- GPU 已释放：`nvidia-smi` 显存从 10.1GB 降到 8.4GB，仅剩 pipeline 进程（用户已终止 LM Studio / llama-server）。
- STT 空转写率仅 5.4%（646 次 final 调用中 35 次空文本），**不是主因**。
- 真实连接存在（console `:8000` ↔ pipeline `:8765`），pool `in_use=1` 是前端挂着的会话。

### 已落地的修改

- `config/prod.yaml` 的 LLM 段：百炼 `qwen3.8-27b` → GPUStack `Qwen3-8B`（env 引用），关闭思考链，注释说明原因。修改已通过 `load_config()` 校验。
- （由用户操作）终止 LM Studio / llama-server，释放 GPU 显存。

> **必须在 PyCharm 里 stop 再 run `s2s-pipeline-prod` 重启 8765**，新的 LLM 配置才会生效。用户选择自行重启。

### 重启后验证（用户执行）

```powershell
# 1) 等待 pipeline 起稳（约 10-20s，模型预热），确认端口
netstat -ano | Select-String ':8765' | Select-String 'LISTENING'

# 2) 跑一次端到端复现（用中文音频；脚本自动转 16k）
D:\work\qwen-audio-agent\speech-to-speech-src\.venv\Scripts\python.exe `
  D:\work\qwen-audio-agent\speech-to-speech-src\scripts\e2e_realtime_test.py `
  --url ws://127.0.0.1:8765/v1/realtime `
  --audio D:\work\qwen-audio-agent\state\prompt.wav `
  --out-dir D:\work\qwen-audio-agent\state\e2e-verify `
  --timeout 60

# 3) 确认生效：日志里 LLM 的 model_name 应为 Qwen3-8B（而非 qwen3.8-27b）
Get-Content D:\work\qwen-audio-agent\speech-to-speech-src\model_metrics.log -Tail 200 |
  Select-String '"category": "LLM"' | Select-Object -Last 2

# 4) 累计错误不再增长：response_failed 应保持为 0（或不再新增）
curl.exe -s http://127.0.0.1:8765/v1/usage
```

预期：LLM 段 model_name 变为 `Qwen3-8B`、每次响应 output tokens 从约 3k 降到百级、`response_failed` 不再新增、端到端 TTFA 明显下降。

### 第三轮复查（用户反馈「好了很多但还不理想」）

重启生效后实测：
- **LLM thinking 已确认关闭**：`/v1/usage` 4 次响应仅 **75 output tokens**（此前 3 次就 18084），LLM 不再是瓶颈。代码层确认 `extra_body={"chat_template_kwargs":{"enable_thinking":false}}` 正确合并（`chat_completions_language_model.py:203`），仅当客户端显式选 reasoning_effort 才覆盖。
- **剩余唯一大头是 STT**：重启后 7 次调用 p50 **2.69s**、RTF 0.47~0.90，本质是 Qwen3-ASR 自回归 decode（音频越长越慢，架构决定）。
- 排除项：STT 空转写率 5.4%、GPU 已释放、progressive（live transcription）仅支持 parakeet 后端不适用、无 funasr/nemo 无法换非自回归后端。

第三轮优化（已落地，均需重启生效）：

| 参数 | 旧值 | 新值 | 收益 / 代价 |
|---|---|---|---|
| `vad.min_silence_ms` | 450 | **300** | 每轮省约 150ms 纯等待；300 是 silero iterator 下限，再低有误切风险 |
| `stt.qwen3_asr_language` | auto | **zh** | 省掉每轮语言标记的 decode + 解析；代价是不再自动识别英文（当前业务全程中文） |

已通过 `load_config()` 校验：`min_silence_ms=300`、`language=zh`、LLM 仍为 GPUStack env 引用。强制 zh 时 `_final_language_code` 直接返回 `zh` 给下游 TTS，链路正常。

> 用户选择自行在 PyCharm 重启。重启后按上面 4 条命令验证；若仍慢，下一步只能换非自回归 STT 后端（SenseVoice/FunASR，需联网装依赖+下模型）。

### 第四轮：STT 替换为 SenseVoiceSmall（已落地，需重启生效）

按 `docs/asr-non-autoregressive-options-CN.md` 的选型，把 STT 从自回归 Qwen3-ASR 换成非自回归 SenseVoiceSmall。

**本仓落地内容**

| 变更 | 文件 | 说明 |
|---|---|---|
| 装依赖 | `.venv` | `uv pip install --no-config --index-url https://mirrors.aliyun.com/pypi/simple/ "funasr>=1.1.6" "modelscope>=1.17.1"`（funasr 1.4.27 + modelscope 1.40.3）。`.venv` 无 pip、HuggingFace/hf-mirror 不通，故用 uv + 阿里云源 + ModelScope |
| 下模型 | `cache/sensevoice-small/` | ModelScope `iic/SenseVoiceSmall`（model.pt 936MB + tokens/config/bpe），约 1 分钟 |
| handler 修 emoji | `src/speech_to_speech/STT/sense_voice_handler.py` | 新增 `_strip_emotion_symbols()`：SenseVoice 会把情感/事件作为 emoji（😊/🎼）附在文本后，`rich_transcription_postprocess` 不清掉；下游 TTS 会读成怪音，故在 `_generate()` 返回前剥离 |
| 配置 | `config/prod.env`、`config/prod.yaml` | 新增 `S2S_SENSEVOICE_MODEL_DIR` 指向本地模型；STT backend `qwen3-asr` → `sense-voice`，参数前缀 `sense_voice_stt_*`（model_name=本地路径、device=cuda、language=zh） |

**本机实测（插件级，重启前独立验证）**

- 稳态 RTF **0.061~0.065**，2.64s 中文音频仅 **0.16s**——相比 Qwen3-ASR 的 0.47~0.90 **快约 7~14 倍**（FunASR 官方 H100 基准 169.6x，本机 5070 Ti 低得多但架构优势保持）。
- 文本正确（"你好，请用一句话介绍你自己。"），emoji 过滤生效。
- 加载 5.12s、首推理 5.89s（一次性 CUDA 初始化，handler `warmup()` 在 setup 期已覆盖）；稳态第 2 句起 0.16s。
- 配置通过 `load_config()` 校验，`create_backend_handler` 工厂接线为既有代码、不受影响。

**重启后验证**：PyCharm stop 再 run `s2s-pipeline-prod`，跑 §第三轮 的 e2e 命令；`model_metrics.log` 里 STT 的 `model_name` 应为本地 SenseVoice 路径、duration 明显下降。若报错 `requires optional 'sensevoice' extra`，说明依赖没进当前 venv（本项目已在 `.venv` 装好）。

### 第五轮：三类服务扩展（2026-11-18，已落地，需重启生效）

| 能力 | 改动 | 说明 |
|---|---|---|
| 内嵌 SenseVoice 情感 | `emotion_local_service.py`[NEW] `mount_emotion_local()`；`STT/sense_voice_emotion.py`[NEW] | `SER_PROVIDER=local` 注册 `/recognize` + `/v1/audio/emotion` + `/v1/audio/emotion/health`，复用 pool 内 SenseVoice handler；hook `ctc.ctc_lo` 抓情感位 logits → 7 类 softmax 算 confidence/margin；6 类映射（新增 happy）、AED 笑声事件、结构化 409、短截止并发门 |
| 情感注入 LLM | `messages.py`/`events.py`/`transcription_notifier.py` 加 `emotion` 字段；`service.py::with_emotion_text()` | STT 富标签转 `[情绪：xxx]`，客户端转录事件先发（干净）再注入 user message；ASR REST 同步支持 SenseVoice handler（修 503） |
| 口型服务 | `visemes_routes.py`[NEW]；`w2v_stv_handler.py` setup soft-fail；`prod.yaml` 打开 `enable_visemes` | `/v1/audio/visemes` + capability，复用 STV handler；默认英语音素模型本机不可达 → setup soft-fail 为 skip（capability ready=false，不阻断音频）；前端已内建 viseme 事件透传 |
| LLM | `prod.env` `GPUSTACK_MODEL=qwen3.5-2b` | 实测关思考链 0.37s/4 tokens |

链路新增：`STT(SenseVoice) → emotion 文字 → service.py 注入 user message → LLM(qwen3.5-2b)`，以及 `TTS 音频 → STV stage(可选) → speech_to_speech.output_audio.visemes 事件 → 前端`。

验证：本轮相关测试 48 + 20 项全绿；`create_app` 实测挂载 7 个新端点全部 OK；A/B 方案见 `docs/sensevoice-ser-a-b-CN.md`。所有配置改动需用户重启 8765 生效。

---

## 4. 延迟观测方法

| 手段 | 位置 | 说明 |
|---|---|---|
| 前端延迟面板 | `TurnLatencyPanel.vue`，数据来自 `response.done` metadata | 每轮 `stt/llm/tts_ttfa/e2e` |
| console API | `GET /api/v1/turn-latency`（需 Bearer）→ `s2s_db.turn_latency` | 生产 agent 采集落库；本机 PyCharm 无日志落点，表为空 |
| pipeline 日志 | `TURN_LATENCY ` 行（`pipeline/turn_latency.py:288`） | 需把 pipeline stdout 落盘供 agent 采集 |
| 模型指标 | `model_metrics.log`（`MODEL_CALL_METRICS` / `_AGGREGATE`） | 本次诊断主要依据，含 STT 耗时与 GPU/内存采样 |
| 端到端复现 | `scripts/e2e_realtime_test.py` | 送 16k PCM → STT→LLM→TTS，报 STT 出字延迟 / TTFA / 总耗时 |
| 运行态 | `GET /v1/pool`、`GET /v1/usage` | 会话占用与累计 token |

---

## 5. 优化建议（按收益排序）

1. **保持 GPU 独占**：跑 S2S 时不要同时开 LM Studio / 本地推理服务；12GB 卡放 Qwen3-ASR-0.6B + Qwen3-TTS 已接近上限。
2. **重启 8765 让新 LLM 配置生效**，然后跑 `scripts/e2e_realtime_test.py` 对比 TTFA / e2e。
3. **若仍慢**：把 STT 换成更快后端（如 CPU 侧的 FunASR / parakeet）或降低 `gen_max_new_tokens`；`min_silence_ms` 可在 350–450 间微调（低于 300 有误切风险）。
4. **公网→内网 LLM**：本次已切 GPUStack，避免百炼 maas 的公网往返与限流。
5. **如需 STV 口型**：注意 `Wav2Vec2STVHandler` 会引入最多 0.5s 累积缓冲；仅 `--enable_visemes` 时生效，语音对话默认不受影响。
