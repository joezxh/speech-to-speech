# 上游差异清单与本地部署配置表

> 生成时间：2026-10-24
> 对比对象：`https://github.com/huggingface/speech-to-speech.git`
> 取证方式：`git` 命令 + 逐文件读取源码/配置，**不依据 commit message 或 README 推断**
> 标注约定：**[已验证]** = 有文件或命令直接证据；**[推断]** = 由证据合理推导但无直接验证；**[未验证]** = 未实际执行

---

## 0. 结论摘要

| 结论 | 要点 |
|---|---|
| 分叉状态 | 本地 `main` 领先分叉点 **27** 个提交，落后上游 **35** 个提交（含 `v1.1.0`） |
| 改动规模 | 相对分叉点：**215 个文件**，新增 176 / 修改 39，`+40190 / −143` 行 |
| 改动性质 | 约 **74%** 为新增文档与部署资产（`docs/`、`.qoder/`、compose、Dockerfile）；**核心代码改动集中在 LLM 容错、量化、TTS/STT 新后端、模型监控、参数平台** |
| 最重要优化 | ① LLM 上游失败分类与专用兜底话术 ② bitsandbytes 4/8bit 量化 + SDPA ③ Qwen3-TTS 句内流式 ④ `/admin/sessions/update` 会话热更新 ⑤ `model_monitor` 统一延迟/资源观测 ⑥ 参数平台 `param_platform` + `prod.yaml` 文件配置模式 |
| 重要发现 | 新增的 `sensevoice_handler.py` / `cosyvoice_handler.py` **未接入 `backend_registry`**，当前无法通过 CLI 选中（详见 §5.1） |
| 网络关键 | 本机（Windows/Docker Desktop）必须经 `llm-proxy.py` 中转，否则 WSL2 NAT 到 GPUStack 返回 502；Linux 直连无需代理 |
| 配置不一致 | `docker-compose.cu130.yml` 与本机 `docker-compose.local.yml` 参数已分叉；`docs/deployment.md` 描述的默认模型与实际 compose 不符（详见 §6） |

---

## 1. 对比基准

### 1.1 精确提交信息 **[已验证]**

```bash
git rev-parse --abbrev-ref HEAD          # main
git log -1 --format='%H %ci %s'          # 648752fb9725619dd805c2194c63d4b19ac0c698 2026-10-24 19:08:52 +0800
git remote -v                            # origin  https://github.com/huggingface/speech-to-speech.git
git fetch origin --prune                 # 已执行
git log -1 --format='%H %ci %s' origin/main
# 0835002ad1c73cf1cc408ac10ebd2a19f777ae12 2026-10-22 23:21:27 +0200
git merge-base HEAD origin/main          # 0ed1bb95bd335aa89bb7c172b6a347b6dae596f8
git rev-list --left-right --count HEAD...origin/main   # 27   35
```

| 项 | 值 |
|---|---|
| 本地分支 | `main` |
| 本地提交 | `648752f`（2026-10-24 19:08:52 +0800）`chore(config): 新增 speech-to-speech 生产环境配置模板与 prod.yaml` |
| 上游仓库 | `https://github.com/huggingface/speech-to-speech.git`（`origin` 已指向该地址，无需临时获取） |
| 上游参考点 | `origin/main` = `0835002`（2026-10-22，PR #752 `claude/serper-api-auth-demo`） |
| 分叉点 | `0ed1bb9`（PR #726 合并提交） |
| 本地版本号 | `pyproject.toml:7 → version = "1.0.0"`；`src/speech_to_speech/__init__.py:3 → __version__ = "1.0.0"` |
| 上游版本号 | 上游 `v1.1.0` tag = `8ebde04`，**不在**本地历史中（本地分叉早于该 release） |

### 1.2 差异范围口径 **[已验证]**

**本项目"自己的改动" = `git diff 0ed1bb9 HEAD`。**

不使用 `git diff origin/main HEAD` 的原因：本地落后上游 35 个提交，直接对 `origin/main` 做 diff 会把**上游新增**的 `TTS/phonon_tts_handler.py`、`api/openai_realtime/voice_controls.py`、`pipeline/console.py`、`demo/server.py` 的大段实现全部显示为"本地删除"——那是失真的。实测两条命令的差异：

| 命令 | 文件数 | 新增行 | 删除行 | 说明 |
|---|---|---|---|---|
| `git diff --stat 0ed1bb9 HEAD` | 215 | 40190 | 143 | ✅ 本项目净改动 |
| `git diff --stat origin/main HEAD` | 263 | 40308 | 3129 | ❌ 混入上游新增，勿用 |

`git diff --name-status 0ed1bb9 HEAD` 汇总：**A（新增）176 个，M（修改）39 个，无 D（删除）**。

### 1.3 本地 27 个提交（`git log --oneline origin/main..HEAD`）

```
648752f chore(config): 新增 speech-to-speech 生产环境配置模板与 prod.yaml
f2267d8 refactor(docker): 重构部署镜像与编排配置并更新硬件选型文档
13ef03d docs(hardware): 假设表 HT1/HT2 补充可点击来源链接
aa76e1a docs(hardware): 选型文档一致性终检与检索来源可追溯化
c9a99bf docs(hardware): 多盒部署清单补充小模型档位并统一引用假设表
19037a8 docs(hardware): plan1-6 商品数据迁移至采购清单并对齐并发推导口径
b93c945 docs(hardware): README 扩展为6方案总入口并接入新专题文档索引
129ac7d docs(hardware): 新增到货算力盒实测验收方案（T0~T9 与三档判定）
eb4a77a docs(hardware): 新增方案⑥ Qwen3.5-0.8B 本地部署选型
f448758 docs(hardware): 新增方案⑤ Qwen3.5-2B 本地部署选型
b1eecfe docs(hardware): 回填 HT3 边缘盒一致性假设状态（转为待验证）
7f126d3 docs(hardware): 新增边缘与国产算力盒可行性评估
99fe602 docs(hardware): 新增可采购算力盒子商品清单
963753e docs(hardware): 依据检索结论解除小模型权重与llama.cpp支持假设
b1261a9 docs(hardware): 新增语音链路并发与延迟性能假设条件表
0ed78e5 docs(hardware): 将2026-10版四方案选型文档纳入版本控制
3d2060d docs(plans): 新增算力盒子选型文档实施计划
f1dd6cf docs: spec 增补到货实测验收方案
ecde095 docs: 算力盒子选型增量完善设计 spec
1fe12f4 Merge branch 'main' of https://github.com/huggingface/speech-to-speech
50ba233 chore(speech-to-speech): 新增 GPUStack 环境变量模板与中英双语 ADR 文档
d670f76 feat(core): 发布 1.0.0 版本，新增多个核心模块
4f1ecb1 fix(responses-api): 对非 OpenAI 提供商显式关闭思考以兼容 assistant prefill
fb7e9f7 feat(backend): 新增 SenseVoice STT 与 CosyVoice TTS 后端并支持离线容错
6d45e59 feat(pipeline): 集成云端百炼模型并优化语音转语音性能
f88ce2c feat(monitor): 添加模型监控功能以跟踪延迟、资源使用情况和输入输出负载
f1225ba feat(llm): 添加模型量化支持并优化 VAD 加载方式
```

> 其中 15 个是 `docs/hardware` 纯文档提交，1 个是 merge。**真正改代码/配置的只有 11 个提交**，且集中在 `f1225ba` ~ `648752f` 区间。

---

## 2. 优化改动清单

分类标签：`[功能]` 功能性改动 · `[性能]` 性能优化 · `[兼容]` 配置/协议兼容性 · `[部署]` 部署改动 · `[修复]` 缺陷修复 · `[可观测]` 观测能力 · `[文档]` 仅文档

### 2.1 STT 模块

| # | 改动 | 类型 | 文件 | 上游原有行为 | 当前实现 | 目的 / 影响 |
|---|---|---|---|---|---|---|
| S1 | Qwen3-ASR 属性访问加固 | `[修复][兼容]` | `STT/qwen3_asr_handler.py:148-186` | 直接 `vad_audio.runtime_config.selected_language`、`vad_audio.speech_end_at_s`、`self._record_final_stt(...)` | 全部改为 `getattr(...)` 兜底（`runtime_config`、`speech_end_at_s`、`_record_final_stt` 可调用性检查） | 部署树（137）的 `RuntimeConfig`/`VADAudio` 缺字段时不再抛 `AttributeError` 导致**每句转写失败**；源码注释明确写"部署树(137)" |
| S2 | 新增 SenseVoice STT handler | `[功能]`（**未接线**） | `STT/sensevoice_handler.py`（新增 108 行）<br>`arguments_classes/sensevoice_stt_arguments.py`（新增 27 行） | 上游仅有 `STT/sense_voice_handler.py`（snake_case 文件），注册名 `sense-voice` | 新增驼峰命名 `sensevoice_handler.py`：FunASR `AutoModel` + `disable_update=True`（不连 FunASR 模型仓）+ 正则 `_TAG_PATTERN` 剥离 `<\|zh\|><\|HAPPY\|><\|BGM\|>` 控制标签 + progressive/最终两态输出 | 面向中文/方言场景；但见 §5.1——**未注册进 `backend_registry`，不可通过 `--stt sensevoice` 选中** |
| S3 | Paraformer 接入模型监控 | `[可观测]` | `STT/paraformer_handler.py:37-84` | `process()` 只做 `perf_counter` 计时，无结构化记录 | warmup 与 `process()` 包进 `self.monitor.trace("STT", ...)`，记录 `mode / language / audio_summary(audio)` 输入与 `text / text_length` 输出 | 与 TTS/LLM 统一延迟口径；`audio_summary()` 只记录采样率/时长/幅度等摘要，不落原始音频 |

> ⚠️ 实际部署走的是 `qwen3-asr`，而 **`qwen3_asr_handler.py` 没有接入 `monitor.trace`**，`model_metrics.log` 中不会有 STT 段（见 §4.3）。

### 2.2 LLM 模块

| # | 改动 | 类型 | 文件 | 上游原有行为 | 当前实现 | 目的 / 影响 |
|---|---|---|---|---|---|---|
| L1 | bitsandbytes 8bit/4bit 量化 | `[性能]` | `LLM/language_model.py`（3 处 `_load_model` 签名扩展）<br>`arguments_classes/language_model_arguments.py:20-33` | `AutoModelForCausalLM.from_pretrained(..., torch_dtype).to(device)`，无量化路径 | 新增 `--llm_load_in_8bit` / `--llm_load_in_4bit`（4bit 优先，NF4）；`quant_kwargs` 命中时**不再 `.to(device)`**（bitsandbytes 自行管理设备） | 按注释：4B 模型显存 fp16 ~8GB → 8bit ~4GB → 4bit ~2.1GB。这是为 12GB 消费卡（RTX 5070 Ti Laptop）留出 STT/TTS 显存空间的关键手段 |
| L2 | 注意力后端切 SDPA + TF32 | `[性能]` | `LLM/language_model.py`（`_load_model` 内） | `from_pretrained` 未指定 `attn_implementation`（走 eager） | `load_kwargs["attn_implementation"] = "sdpa"`；`torch.backends.cuda.enable_cudnn_sdp(True)`；`matmul/cudnn.allow_tf32 = True`（均 `try/except` 包裹） | 降低 attention 显存 + 加速 prefill/decode；对 bnb 反量化路径友好。`try/except` 保证 CPU/Mac 上不炸 |
| L3 | Streamer 超时 1.0s → 60.0s | `[修复]` | `LLM/language_model.py`（`TextIteratorStreamer(timeout=...)`，2 处）<br>同改 `VisionLanguageModelHandler` | `timeout=1.0` | `timeout=60.0` | 1.0s 对 4bit 量化 / 小显存卡的首 token 明显偏紧，会抛 `queue.Empty` 导致整轮失败 |
| L4 | NLTK 断句离线兜底 | `[修复][兼容]` | `LLM/utils.py:101-151`<br>`LLM/language_model.py:26,75`<br>`s2s_pipeline.py:61-74` | `from nltk import sent_tokenize` 硬依赖；`nltk.download("punkt_tab")` 失败即启动失败 | ① `safe_sent_tokenize()`：`nltk.sent_tokenize` 失败时回落正则 `_SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？])\s*")`<br>② `sent_tokenize_preserving_markdown_code` 内部再包一层 `try/except`<br>③ `s2s_pipeline` 把 `nltk.data.find` 与 `nltk.download` 双层 `try/except` 吞掉，并补 `punkt`（不止 `punkt_tab`） | 容器出口被 SSRF 网关拦截时（`punkt_tab.zip` 卡 2.1MB、每次重建必现），流水线仍能运行，不再退化成 "I'm having trouble responding right now" |
| L5 | 上游失败分类与专用兜底话术 | `[功能][修复]` | `LLM/provider_errors.py`（新增 84 行）<br>`LLM/base_openai_compatible_language_model.py`<br>`arguments_classes/responses_api_language_model_arguments.py` | SDK 吞掉上游 body，GPUStack 500 只表现为 `Error code: 500 - None`；失败一律播通用兜底 | 新增 `classify_provider_error()` 返回 `(kind, detail)`，kind ∈ `upstream_unavailable / timeout / provider_error`；`detail` 拼上 `upstream_status=<code>` 与 `upstream_body=<前400字符单行>`（用竖线分隔）；新增 `--responses_api_provider_unavailable_message`，仅当 kind=`upstream_unavailable` 时播该专用话术 | 运维能从日志直接看到 "Failed to parse tools: Missing tool function" 这类真实原因；终端用户听到"服务暂时不可用"而非"助手答不出" |
| L6 | tool_calls 补 `type` 字段 | `[修复][兼容]` | `LLM/chat_completions_language_model.py:148-152` | 直接透传历史里的 `tool_calls` | `tool_call.setdefault("type", "function")` | GPUStack 等严格的 OpenAI 兼容服务会因缺 discriminator 返回 500，导致**一旦用过工具，后续每一轮都失败** |
| L7 | 非 OpenAI 提供商显式关思考 | `[兼容]` | `LLM/responses_api_language_model.py`（提交 `4f1ecb1`） | 仅发送 `reasoning_effort` | 配合 `--responses_api_reasoning_effort ""`（空串）→ 改发 `enable_thinking=false`；同时兼容 assistant prefill | Qwen3 默认开思考链，语音场景首字被拖 2~5s；空串 vs `none` 是刻意区分（GPUStack 不认 `reasoning_effort=none`） |
| L8 | VLM 加载支持量化 | `[功能]` | `LLM/language_model.py`（`VisionLanguageModelHandler._load_model`） | 纯 `torch_dtype` 加载 | 同步支持 `load_in_4bit/8bit` + `timeout=60` | 与文本 LLM 对齐；当前部署未启用 VLM |
| L9 | `chat_completions` 后端测试 | `[测试]` | `tests/test_chat_completions_backend.py`（+119） | — | 覆盖 tool_calls type 补齐等行为 | — |

### 2.3 TTS 模块

| # | 改动 | 类型 | 文件 | 说明 |
|---|---|---|---|---|
| T1 | Qwen3-TTS 接入监控 + 句内流式统计 | `[性能][可观测]` | `TTS/qwen3_tts_handler.py:576, 864` | `process()` 整体包进 `monitor.trace("TTS", ...)`；流式产出计数 `audio_bytes`、按 `PIPELINE_SR*2` 反算 `audio_duration_s`；异常写 `rec.error`；`--qwen3_tts_streaming_chunk_size 4`（约 320ms/块）为实测首包 ~0.5s 的关键参数（见 `docker-compose.gpustack.yml:69-73` 注释） |
| T2 | 新增 CosyVoice2 TTS handler | `[功能]`（**未接线**） | `TTS/cosyvoice_handler.py`（新增 204 行）<br>`arguments_classes/cosyvoice_tts_arguments.py`（新增 48 行） | 24kHz→16kHz `librosa.resample`；按 `chunk_size` 重组 int16 PCM 块并 `np.pad` 补齐尾块；`inference_instruct2` 支持方言/情绪 `instruct`；零样本音色克隆 `prompt_wav`（默认 `/opt/cosyvoice-src/asset/zero_shot_prompt.wav`）；ModelScope 兜底下载。**未注册进 `backend_registry`，不可选中**（见 §5.1） |
| T3 | TTS README 中文版 | `[文档]` | `TTS/README-CN.md`（+290） | — |

### 2.4 VAD 模块

| # | 改动 | 类型 | 文件:行 | 上游原有行为 | 当前实现 | 目的 |
|---|---|---|---|---|---|---|
| V1 | Silero VAD 本地加载 | `[部署][修复]` | `VAD/vad_handler.py:151-159` | `torch.hub.load("snakers4/silero-vad:master", "silero_vad", trust_repo=True)` —— 运行期去 GitHub 拉 zipball | `torch.hub.load("/opt/silero-vad", "silero_vad", source="local", ...)` | 运行时容器无法直连 `github.com`（被拦截/代理死链），`torch.hub` 会 `Connection refused` 导致启动失败。改为构建期把仓库预置到 `/opt/silero-vad`（`docker-compose.*.yml` 挂载 `./silero-vad:/opt/silero-vad:ro` 或 `Dockerfile.baked` 内 `git clone`） |
| V2 | 判停参数整定 | `[性能]` | 各 compose `command` | 上游默认 `min_silence_ms` 等 | 本机：`min_silence_ms=500`、`min_speech_ms=250`、`short_segment_merge_ms=800`；137：`700`；llm-bundled：`64`；统一 `--no_smart_turn --speculative_reopen_ms 0 --unanswered_reopen_ms 0` | 见 §2.6 延迟优化 |

### 2.5 实时管线与 OpenAI Realtime 接口

| # | 改动 | 类型 | 文件 | 上游原有行为 | 当前实现 | 目的 |
|---|---|---|---|---|---|---|
| R1 | **新增 `/admin/sessions/update` 热更新端点** | `[功能]` | `api/openai_realtime/websocket_router.py: +118 行` | 会话参数只能在建连时确定，改配置必须重启流水线（断话） | 新增 `POST /admin/sessions/update`：<br>· 鉴权 `S2S_ADMIN_TOKEN` Bearer，`hmac.compare_digest` 常量时间比较；**未配置 token 返回 503 而非放行**（fail-closed）<br>· `scope` ∈ `all / pipeline / session`，`target` 分别为空 / 整数 pipeline index / session_id<br>· payload 经 `SessionUpdateEvent` Pydantic 校验后交给 `SessionHandler.handle_session_update`（不在此处复制合并逻辑）<br>· 逐会话回报 `updated[] / failed[]`，成功者向客户端推 `session.updated` | 参数平台"链路 B"：不重启即可改运行中会话的语言/提示词等；错误体统一 `{"error":{"code","message","details"}}` 且 **`message` 不回显入参**（防提示词进日志） |
| R2 | `BaseHandler` 注入 monitor | `[可观测]` | `baseHandler.py:24,54-56` | 无 | `self.monitor = get_model_monitor()` | 所有 handler 子类自动获得监控句柄，无需各自初始化 |
| R3 | OpenAI Realtime 中文文档 | `[文档]` | `api/openai_realtime/README-CN.md`（+346） | — | — | — |
| R4 | 路由测试 | `[测试]` | `tests/openai_realtime/test_websocket_router.py`（+107） | — | 覆盖 scope/target/鉴权/失败回报 | — |

### 2.6 延迟与并发优化（跨模块，配置驱动）

这部分不是代码改动，而是**编排参数整定**，是当前部署延迟表现的主要来源。逐项有出处：

| 优化项 | 参数 | 取值演变 | 依据 |
|---|---|---|---|
| 首句即送 TTS | `--stream_batch_sentences 1` | 上游默认 3 句 → 1 句 | `docker-compose.gpustack.yml:50-53` 注释："默认要凑够 3 句才把文本喂给 TTS（首音被拖慢 ~4-5s）；改成 1 = 句-by-句流式 ★TTFA 关键★" |
| 关思考链 | `--responses_api_reasoning_effort ""` | 未设置 → 空串 | 同上 `:46-49`："非空时 `_build_extra_body` 只会发 `reasoning_effort=none`（GPUStack 不认），Qwen3 默认思考→答案前几秒 reasoning" |
| TTS 换芯 | `--tts qwen3` + `backend=torch` + `non_streaming_mode=False` + `chunk_size=4` | CosyVoice2（流式 ~4s 大块，首包 1.7–3.6s）→ Qwen3-TTS（~320ms/块，首包 ~0.5s） | `docker-compose.gpustack.yml:69-73`："CosyVoice2 流式按 ~4s 大块产出，首包 1.7-3.6s（占首音 ~75%）" |
| 缩短上下文 | `--chat_size 40`（本机）/ `20`（llm-bundled） | 上游默认（未显式设置） | `docker-compose.local.yml:42-44`："数值越小延迟越低、记忆越短" |
| 关 Smart Turn | `--no_smart_turn` + `speculative_reopen_ms=0` + `unanswered_reopen_ms=0` | 上游默认 Smart Turn + 800ms speculative grace | `docker-compose.gpustack.yml:88-98`："每轮省 ~0.55s，并消除 speculative 反复重开导致的重复 STT/LLM 取消" |
| 判停收紧 | `min_silence_ms 700→500` | — | `docker-compose.local.yml:68-72`："700 时实测捕获 75%、首音 3.9~6.7s；500 少等 0.2s 判停" |
| 短句保护 | `min_speech_ms 384→250`、`short_segment_merge_ms 0→800` | — | 同上 `:73-80`："首段有效语音不足 384ms 的整段会被丢弃，导致'嗯/好的/你好'完全捕捉不到"；注意 `short_segment_merge_ms >= min_silence_ms` 的硬约束 |
| 实时字幕 | `--enable_live_transcription --live_transcription_update_interval 0.5` | 上游默认关 | `docker-compose.local.yml:93-96` |
| 并发热更新 | `pipelines.prod.num_pipelines: 1` | — | `config/prod.yaml:63`；多路并发可调高，代价是显存线性增长 |
| LLM 预热 | warmup 包进 monitor | 上游已 warmup | `LLM/language_model.py:985` |

### 2.7 可观测性：`model_monitor`

| 项 | 内容 |
|---|---|
| 文件 | `src/speech_to_speech/utils/model_monitor.py`（新增 **471 行**） |
| 结构 | `CallRecord`（单次调用）/ `_Aggregator`（按间隔聚合并 flush）/ `_ResourceSampler`（0.1s 采样 CPU/GPU/显存，GPU 侧解析 `nvidia-smi` utilization）/ `ModelMonitor`（单例，含 `trace()` 上下文管理器与滚动文件日志） |
| 环境变量 | `MODEL_METRICS_LOG`（默认 `model_metrics.log`）、`MODEL_METRICS_LOG_MAX_BYTES`（默认 20MB）、`MODEL_METRICS_LOG_BACKUPS`（默认 5） |
| API | `get_model_monitor()`（单例）、`configure_model_monitor()`、`_truncate(value, max_len=512)`、`audio_summary(audio)` |
| 已接入点 **[已验证]** | `LLM/language_model.py:645,985`（transformers 后端 LLM 调用 + warmup）、`STT/paraformer_handler.py:57,66`、`TTS/qwen3_tts_handler.py:576,864` |
| 未接入点 | `STT/qwen3_asr_handler.py`（**当前实际部署的 STT**）、`LLM/base_openai_compatible_language_model.py`（chat-completions 路径，**当前实际部署的 LLM**）、`web`/`realtime` 传输层 |
| 结论 | 监控框架已具备，但**主链路（qwen3-asr + chat-completions）尚未覆盖**；根目录 `model_metrics.log` 现为 0 字节 **[已验证]**，说明尚未产生有效指标 |

### 2.8 配置系统：参数平台 + 文件模式

| 项 | 内容 |
|---|---|
| 新增模块 | `demo/param_platform/` 共 10 个文件：`catalog.py`(255) / `compose_runner.py`(329) / `drafts.py`(108) / `hot_update.py`(210) / `layout.py`(248) / `publish_flow.py`(569) / `renderer.py`(200) / `store.py`(336) / `validator.py`(431) / `__init__.py` |
| API 层 | `demo/param_api.py`（新增 519 行，`APIRouter(prefix='/admin')`） |
| 前端 | `demo/console.html`(200) + `demo/console.css`(749) + `demo/ui/console/*.js`（`api/app/audit/html/instances/params/sessions/versions`，合计 ~1400 行） |
| 存储 | `demo/s2s-params.sqlite3`（已 gitignore） |
| 核心能力 | YAML 渲染 → schema 校验 → Compose 重建 → 版本审计 → 热更新；`publish_flow.py` 负责发布事务与回滚 |
| 与 CLI 的关系 | `config/prod.yaml` 顶层注释明确：**文件模式只接受 `-f/--name`**（`cli.py:_run_file_command`），因此 40+ 个 CLI 开关必须写进 YAML |
| 密钥解析 | `responses_api_api_key: {env: GPUSTACK_API_KEY}` —— **映射式写法，变量缺失即 resolve 期硬失败，无默认值回落**（`config/prod.yaml:38-40`） |
| 文档 | `docs/parameter-catalog.yaml`（新增 **2994 行**）、`docs/parameter-catalog.md`（1037 行）、`docs/model-pipeline.md`（1011 行）、`demo/DESIGN-CN.md`、`demo/CONTEXT-CN.md` |
| 测试 | `tests/test_param_platform.py`（新增 **594 行**） |

### 2.9 依赖与构建

| # | 改动 | 类型 | 文件 | 要点 |
|---|---|---|---|---|
| B1 | 主 `Dockerfile` 重写（+128 行） | `[部署]` | `Dockerfile` | 构建期用内联 Python 脚本**删除 `pyproject.toml` 的全部 `optional-dependencies`**——注释解释：uv 通用解析会把 darwin-only 的 kokoro/mlx 拉进来导致 tqdm 冲突；并 `sed` 修补 `qwen_tts/_transformers_compat.py` 的 `rope_theta` 兼容问题 |
| B2 | 新增 6 个 Dockerfile 变体 | `[部署]` | `Dockerfile.cu130`(101) / `Dockerfile.cu128`(35) / `Dockerfile.baked`(49) / `Dockerfile.baked.cu130`(42) / `Dockerfile.local`(26) / `Dockerfile.sox`(20) / `Dockerfile.torch-base`(29) | 见 §3.2 镜像矩阵 |
| B3 | 新增 optional extra | `[兼容]` | `pyproject.toml:102-104` | `sensevoice = ["funasr>=1.1.6"]`（已有 `paraformer = ["funasr>=1.2.7","modelscope>=1.17.1"]`） |
| B4 | `uv` 索引策略 | `[部署]` | 各 Dockerfile | `Dockerfile.cu130`：`UV_INDEX="PyTorch cu130 → tuna → 阿里云"` + `UV_INDEX_STRATEGY=first-index` + `UV_BUILD_ISOLATION=false`；注释明确"刻意不用 pypi.org（构建容器内连接抖动/超时）" |
| B5 | cu130 驱动门槛 | `[部署][文档]` | `Dockerfile.cu130:12-16` | 宿主驱动 **>= 580**（CUDA 13.0+）；低于 580 会 "driver too old"，表现为 **TTS/STT 静默回退 CPU（RTF ≈ 3.7x）**。文档明确指出"本机（驱动 572.84 / CUDA 12.8）请用 `Dockerfile`（cu128 变体）" |
| B6 | `python3.12-dev` | `[部署]` | `Dockerfile.cu130:38-43` | triton JIT（CUDA graphs / `torch.compile`）需要 `Python.h`，缺失会导致 TTS warmup 报 `fatal error: Python.h: No such file or directory` |
| B7 | nltk 数据固化 | `[部署][修复]` | `Dockerfile.local` / `Dockerfile.sox` | `COPY cache/nltk_data /root/nltk_data` + `chmod -R 755` + `chown root:root`。原因：Windows bind mount 权限 777，nltk 判定 "world- or group-writable" 拒绝使用 → 转联网重下 → 启动卡死。**因此这两份 compose 明确禁止挂载 `nltk_data`**（`docker-compose.local.yml:108-109`） |
| B8 | `silero-vad` 变 gitlink | `[部署]` | `git ls-files -s silero-vad` → `160000 77d26db` | 作为子模块引用（**无 `.gitmodules`**），本地已 checkout 且含 `hubconf.py` **[已验证]**；`docker-compose.yml` 挂载的是仓库外的 `../.silero-dl2/silero-vad-master`（已确认存在） |

### 2.10 部署与编排

| # | 改动 | 类型 | 文件 | 要点 |
|---|---|---|---|---|
| D1 | 新增 6 份 compose | `[部署]` | `docker-compose.baked.yml`(80) / `.cu130.yml`(90) / `.gpustack.yml`(148) / `.llm-bundled.yml`(138) / `.local.yml`(120) / `.vn.ms.llm-bundled.yml`(110) | 见 §3 场景矩阵 |
| D2 | 根 `docker-compose.yml` 改写（+51） | `[部署][兼容]` | `docker-compose.yml` | 从 40+ CLI 参数缩到 **6 项**：`serve -f /app/config/prod.yaml --name prod`；`env_file: ./config/prod.env`；`./config:/app/config:ro`（配置只有一个写入方）；注释警告"任何一项若同时写在 `environment` 下会以更高优先级覆盖 env_file，平台就再也改不动那个值" |
| D3 | 新增 4 份 env 模板 | `[部署]` | `.env.cu130` / `.env.gpustack` / `.env.gpustack.example` / `.env.local` / `config/prod.env.example` | 见 §3.3 |
| D4 | 辅助脚本 | `[部署]` | `diag_import.py`(22) / `latency_test.py`(165) | 导入诊断与端到端延迟压测 |
| D5 | `llm-proxy.py` | `[部署]`（**未纳入版本控制**） | 根目录 128 行，`git check-ignore` 未命中但 `git ls-files` 无此项 | Windows 宿主上的流式反向代理，解决 WSL2→GPUStack 502 |
| D6 | 硬件选型文档 | `[文档]` | `docs/hardware/` 14 个文件（README/acceptance-test-plan/deployment-multibox/edge-box-feasibility/performance-assumptions/plan-1..6/procurement-list + 2 份 compose 样例） | 6 方案 × 4 维度；含 T0~T9 到货实测验收方案 |
| D7 | 构建日志入库 | `[文档]`（建议清理） | `build-cu130*.log` / `build.s2s.A.log` / `llama-server*.err/.out/.log` | 见 §6.6 |

### 2.11 测试

| 文件 | 变化 | 覆盖 |
|---|---|---|
| `tests/test_param_platform.py` | 新增 594 行 | 参数平台渲染/校验/发布/回滚/审计 |
| `tests/openai_realtime/test_websocket_router.py` | +107 | `/admin/sessions/update` |
| `tests/test_chat_completions_backend.py` | +119 | tool_calls type、后端行为 |
| `tests/test_qwen3_tts_handler_backend.py` | +34 | Qwen3-TTS 后端 |
| `tests/test_responses_api_language_model.py` | +12 | reasoning 关闭 |
| **缺失** | — | `sensevoice_handler.py` / `cosyvoice_handler.py` / `model_monitor.py` / `provider_errors.py` **均无对应测试** |

### 2.12 文档

新增：`README-CN.md`(+698)、`AGENTS-CN.md`(+30)、`demo/README-CN.md`(+245)、`demo/DESIGN-CN.md`(+157)、`demo/CONTEXT-CN.md`(+80)、`docs/deployment.md`(+147)、`docs/model-pipeline.md`(+1011)、`docs/parameter-catalog.md`(+1037)、`docs/openai-compatible-{stt,tts}-CN.md`、`LLM/README-CN.md`(+142)、`STT/README-CN.md`(+175)、`TTS/README-CN.md`(+290)、`api/openai_realtime/README-CN.md`(+346)、`.qoder/repowiki/` 全量知识库（~50 文件）。

### 2.13 工作区未提交改动 **[已验证]**

`git status --porcelain` 共 **112 项**：

- `.env.local`（M）：`GPUSTACK_BASE_URL` 由 `http://192.168.40.30/v1-openai` 改为 `http://host.docker.internal:8891/v1-openai`，并加 4 行注释说明 WSL2 NAT 502 问题。**这是本机部署能否连通 LLM 的关键改动，尚未提交。**
- `.qoder/repowiki/**`（D 约 100 项 + 未跟踪 ~40 项）：知识库文件被删除后由工具重新生成，属噪声。
- 其余为 `.gitignore` 已覆盖的运行时产物（`cache/`、`model_metrics.log`、`.pytest-tmp/`）。

---

## 3. 本地实际部署清单（主口径：docker-compose 编排）

### 3.1 场景 ↔ 编排 ↔ env 对照 **[已验证]**

| 场景 | compose 文件 | env 文件 | 镜像 | 目标环境 |
|---|---|---|---|---|
| **P1 生产（文件模式）** | `docker-compose.yml` | `config/prod.env`（+ `-f /app/config/prod.yaml --name prod`） | `build: Dockerfile`（`DOCKERFILE` 可覆盖） | Linux + NVIDIA，137 |
| **P2 本机 GPU 开发** | `docker-compose.local.yml` | `.env.local` | `speech-to-speech-local:cu130-1.1-sox`（`Dockerfile.local`） | Windows + Docker Desktop(WSL2) |
| **P3 137 GPUStack 版** | `docker-compose.gpustack.yml` | `.env.gpustack` | `build: ${DOCKERFILE:-Dockerfile}` | Linux 192.168.1.137 |
| **P4 137 cu130 版** | `docker-compose.cu130.yml` | `.env.cu130` | `ccr.ccs.tencentyun.com/llm-basic/speech-to-speech:cu130-1.0` | Linux 137，GPU1 |
| **P5 自带 LLM（本机验证）** | `docker-compose.llm-bundled.yml` | 无（值硬编码） | `speech-to-speech:cu130-1.0` | Windows + 宿主 llama-server:8080 |
| **P6 自带 LLM（越南/马来）** | `docker-compose.vn.ms.llm-bundled.yml` | 无 | `build: ${DOCKERFILE:-Dockerfile}` | Linux + llama.cpp 容器 |
| **P7 自包含 baked** | `docker-compose.baked.yml` | `.env.local` | `speech-to-speech-baked:cu128-1.0` | 无外部卷 |

> 默认加载行为：`docker compose -f X.yml` **不会**自动读 `.env.cu130` / `.env.gpustack`（只有 `.env` 会自动读）。P3/P4 必须显式 `--env-file`。P7 用 `.env.local` 是因为其中只有 `GPUSTACK_*` / `PIPELINE_*`，与 `.env` 里的 `DASHSCOPE_API_KEY` 无关。

### 3.2 镜像矩阵

| Dockerfile | 基础镜像 | 行数 | 是否内置模型 | sox | nltk 固化 | 热修 chat_completions | 产出的 tag |
|---|---|---|---|---|---|---|---|
| `Dockerfile` | `ccr.ccs.tencentyun.com/llm-basic/python-torch:cu128`（默认） | 128 | ✗ | ✗ | ✗（构建期 best-effort 下载） | ✗（源码已是新版） | `speech-to-speech:cu128-*` |
| `Dockerfile.cu128` | 同上（显式） | 35 | ✗ | ✗ | ✗ | ✗ | 同上 |
| `Dockerfile.cu130` | `python-torch:cu130`（torch 2.14.1+cu130） | 101 | ✗ | ✗ | ✗ | ✗ | `speech-to-speech:cu130-1.0` |
| `Dockerfile.baked` | `python-torch:cu128` | 49 | ✓ `qwen3-asr-model-hf` + `qwen3-tts-model` + `silero-vad` | ✗ | ✓ | ✗ | `speech-to-speech-baked:cu128-1.0` |
| `Dockerfile.baked.cu130` | `python-torch:cu130` | 42 | ✓ 同上 | ✗ | ✓ | ✗ | `speech-to-speech-baked:cu130-1.0` |
| `Dockerfile.sox` | `speech-to-speech:cu130-1.0`（**预构建镜像**） | 20 | 继承 | ✓ | ✓ | ✓ **COPY 覆盖 `chat_completions_language_model.py`** | `*-sox` |
| `Dockerfile.local` | `speech-to-speech:cu130-1.1`（预构建） | 26 | 继承 | ✓ | ✓ | 继承（1.1 已含） | `speech-to-speech-local:cu130-1.1-sox` |
| `Dockerfile.torch-base` | `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04` | 29 | ✗ | ✗ | ✗ | ✗ | 基座重建用 |

> `Dockerfile.sox` 的 COPY 覆盖是**重要证据**：`cu130-1.0` 镜像内的源码早于 tool_calls 修复，因此用 COPY 把修好的单文件塞进运行镜像。

### 3.3 env 文件职责

| 文件 | 是否入库 | 内容 | 被谁消费 |
|---|---|---|---|
| `.env` | ✗（`.gitignore:151`） | `DASHSCOPE_API_KEY=sk-...`、`GPUSTACK_API_KEY=gpustack_...`（**真实密钥**） | 无 compose 引用；`DASHSCOPE_API_KEY` 对应"百炼"后端（提交 `6d45e59`） |
| `.env.local` | ✓（已提交，**当前有未提交修改**） | `GPUSTACK_BASE_URL=http://host.docker.internal:8891/v1-openai`、`GPUSTACK_MODEL=Qwen3-8B`、`GPUSTACK_API_KEY`、`PIPELINE_PORT=8765`、`PIPELINE_GPU_ID=0` | P2、P7 |
| `.env.cu130` | ✓ | `GPUSTACK_BASE_URL=http://192.168.40.30/v1-openai`、`PIPELINE_GPU_ID=1` | P4（需 `--env-file`） |
| `.env.gpustack` | ✓ | 同 cu130 + 注释 | P3（需 `--env-file`） |
| `.env.gpustack.example` | ✓ | 模板 | — |
| `config/prod.env` | ✗（`.gitignore:config/*.env`） | `GPUSTACK_API_KEY=not-needed`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`TOKENIZERS_PARALLELISM=false` | P1（`env_file:`） |
| `config/prod.env.example` | ✓ | 模板 + `S2S_ADMIN_TOKEN=`（空） | — |

---

## 4. 本地实际模型清单

### 4.1 权重实体（`cache/`，已 `git check-ignore` 确认不入库）**[已验证]**

| 角色 | 目录（宿主） | 容器内路径 | 关键文件 | 体积 | 精度/量化 | 模型标识（来自 `config.json`） |
|---|---|---|---|---|---|---|
| **STT（实际使用）** | `cache/qwen3-asr-model-hf/` | `/root/.cache/qwen3-asr-model-hf` | `model.safetensors` + `chat_template.jinja` + `tokenizer.json` | 3887.4 MB | `dtype: bfloat16` | `model_type: qwen3_asr`，`architectures: [Qwen3ASRForConditionalGeneration]`，`text_config.hidden_size: 2048` → **Qwen3-ASR-1.7B（HF 格式）** **[推断：由 hidden_size + 3.87GB bf16 反推]** |
| STT（备用，**未使用**） | `cache/qwen3-asr-0.6b-hf/` | — | `model.safetensors` + `chat_template.jinja` | 1492.4 MB | bfloat16 | `model_type: qwen3_asr` → **Qwen3-ASR-0.6B（HF）**；**任何 compose / config / env 均未引用** |
| **TTS（实际使用）** | `cache/qwen3-tts-model/` | `/root/.cache/qwen3-tts-model` | `model.safetensors` + `vocab.json` + `merges.txt` | 3655.8 MB | 权重 bf16（`dtype: null` 未声明外部精度） | `model_type: qwen3_tts`，`tts_model_size: "1b7"`，`tts_model_type: "custom_voice"`，`tokenizer_type: qwen3_tts_tokenizer_12hz` → **Qwen3-TTS-12Hz-1.7B-CustomVoice** |
| **LLM（本机自包含时）** | `cache/qwen35-4b/` | `/root/.cache/qwen35-4b` | `Qwen3.5-4B-Q4_K_M.gguf` | 2614.0 MB | **GGUF Q4_K_M** | 由 `docker-compose.yml:8` 与 `docker-compose.llm-bundled.yml:12` 显式指向 |
| **VAD** | `cache/smart-turn-v3.2-cpu.onnx` | `/root/.cache/smart-turn-v3.2-cpu.onnx` | ONNX | — | CPU | Smart Turn v3.2；**即使 `smart_turn: false` 也必须给路径**（`config/prod.yaml:18-20`：缺路径会触发启动期下载，离线容器卡死） |
| **VAD（Silero）** | `silero-vad/`（gitlink `160000 77d26db`）或 `../.silero-dl2/silero-vad-master` | `/opt/silero-vad` | `hubconf.py` + 权重随仓库 | — | TorchScript | `torch.hub.load(..., source="local")` |
| nltk 数据 | `cache/nltk_data/` | `/root/nltk_data`（烤进镜像） | `index.xml` 等 | — | — | `punkt` / `punkt_tab` / `averaged_perceptron_tagger_eng` |

### 4.2 LLM 端点（三种互斥形态）

| 形态 | 端点 | 模型名 | 证据 |
|---|---|---|---|
| **A. 局域网 GPUStack 直连** | `http://192.168.40.30/v1-openai` | `Qwen3-8B` | `config/prod.yaml:36-37`、`.env.gpustack`、`.env.cu130` |
| **B. 局域网 GPUStack 经宿主代理** | `http://host.docker.internal:8891/v1-openai` → 宿主 `llm-proxy.py:8891` → `192.168.40.30:80` | `Qwen3-8B` | `.env.local`（未提交修改）+ `llm-proxy.py` docstring |
| **C. 本机 llama.cpp** | `http://host.docker.internal:8080/v1`（宿主 `llama-server.exe`）或 `http://llama:8080/v1`（容器） | `Qwen3.5-4B-Instruct-GGUF` / `Qwen/Qwen3-8B-Instruct-GGUF` | `docker-compose.llm-bundled.yml:11-13,69-70`、`docker-compose.yml:4-33`、`docker-compose.vn.ms.llm-bundled.yml` |

> `chat_size`：`prod.yaml` **未设置**（走 CLI 默认）；`docker-compose.local.yml` 设 `40`；`docker-compose.llm-bundled.yml` 设 `20`。

### 4.3 精度与设备汇总

| 组件 | 设备设置 | 各场景实际值 | 精度 |
|---|---|---|---|
| STT | `--qwen3_asr_device` | P1/P3/P4/P7=`auto`；P2=`cuda` | bf16 权重（`config.json: dtype=bfloat16`） |
| TTS | `--qwen3_tts_device` | 全部=`cuda` | 权重 bf16 |
| TTS 流式 | `--qwen3_tts_non_streaming_mode` / `--qwen3_tts_streaming_chunk_size` | 全部 `false` / `4` | — |
| LLM | 无本地设备参数（远端） | — | 远端由 GPUStack 决定；本机 llama.cpp 为 Q4_K_M |
| LLM 量化（可选） | `--llm_load_in_8bit` / `--llm_load_in_4bit` | **所有 compose 均未启用**（仅本地 transformers 后端可用） | 默认 fp16/bf16 |
| GPU 编号 | `PIPELINE_GPU_ID` | P1=`0`（硬编码 `device_ids: ['0']`）；P2=`0`；P3=`1`；P4=`1`；P5=`0`；P7=`0` | — |

---

## 5. 冲突与不一致清单

### 5.1 【高】新增的 SenseVoice / CosyVoice 未接入后端注册表 **[已验证]**

```bash
git diff --stat 0ed1bb9 HEAD -- src/speech_to_speech/backend_registry.py   # 输出为空 = 未修改
```

- `backend_registry.py:458` 的 `sense-voice` 指向 `speech_to_speech.STT.sense_voice_handler`（上游已有的小写下划线文件），**不是**新增的 `sensevoice_handler.py`。
- 全仓库检索 `cosyvoice` 只命中两个新增文件自身（`arguments_classes/cosyvoice_tts_arguments.py`、`TTS/cosyvoice_handler.py`），**registry 中无任何 cosyvoice 条目**。
- 后果：`--stt sensevoice`、`--tts cosyvoice` 均无法选中；`docs/`、`compose` 中也确实**没有任何场景使用它们**。这两个 handler + 两个 arguments 类当前是**死代码**。
- 建议：要么补 `BackendSpec` 注册 + 测试，要么从仓库移除以免误导。

### 5.2 【高】WSL2 场景的代理口径分裂 **[已验证]**

| 来源 | LLM base URL | 结果 |
|---|---|---|
| `config/prod.yaml:37` | `http://192.168.40.30/v1-openai`（**直连，无代理**） | 在 Windows/WSL2 容器内会 502 |
| `.env.local`（已修改未提交） | `http://host.docker.internal:8891/v1-openai`（**经宿主代理**） | 走通 |
| `.env.gpustack` / `.env.cu130` | `http://192.168.40.30/v1-openai` | 137（Linux）直连正常 |

→ **Windows 上必须用 P2/P5（`.env.local` 系），不能用 P1（`prod.yaml` 直连）。** 若把 `docker-compose.yml` 搬到 Windows 又保留 `prod.yaml` 的直连地址，会直接复现 502。

### 5.3 【中】`llm-proxy.py` 监听 127.0.0.1 而容器经 `host.docker.internal` 访问 **[未验证]**

`llm-proxy.py:32` 硬编码 `LISTEN_HOST = "127.0.0.1"`，`.env.local` 让容器连 `host.docker.internal:8891`。
- Docker Desktop（Win/Mac）的后端转发通常能把 `host.docker.internal` 落到宿主 loopback，**可能可用**；
- 原生 WSL2 + 自建 dockerd 时 `host.docker.internal` 指向 WSL 的宿主 IP，**大概率连不上 127.0.0.1 绑定的端口**。
- 该路径**尚未在本会话中实际验证**。若出现 `Connection refused`，把 `LISTEN_HOST` 改为 `0.0.0.0`（并注意此时端口对局域网暴露）。

### 5.4 【中】`docker-compose.cu130.yml` 与本机 `local.yml` 参数已分叉 **[已验证]**

| 参数 | `.cu130.yml`（P4） | `.local.yml`（P2） |
|---|---|---|
| `qwen3_asr_device` | `auto` | `cuda` |
| `--responses_api_reasoning_effort` | `""` | 未设（改用 `--responses_api_disable_thinking`） |
| `--min_silence_ms` | `700` | `500` |
| `--min_speech_ms` / `--short_segment_merge_ms` | 未设（默认 384 / 0） | `250` / `800` |
| `--thresh` | 未设 | `0.6` |
| live transcription | `--no_enable_live_transcription` | `--enable_live_transcription` + `0.5` |
| `init_chat_prompt` | "one or two spoken sentences…" | "ONE short sentence (under 30 words)…" |
| `--chat_size` | 未设 | `40` |
| 镜像 | 预构建 `cu130-1.0`（**不含** tool_calls 修复） | `local:cu130-1.1-sox`（含） |
| nltk 挂载 | `./nltk_data:/root/nltk_data/` | **禁止挂载**（已烤进镜像） |

> 两个文件头部都写着"参数与本地…完全一致"，实际已不一致。

### 5.5 【中】`docs/deployment.md` 与实际配置不符 **[已验证]**

| 文档描述 | 实际 |
|---|---|
| STT 默认 `NVIDIA Parakeet TDT 0.6B v3` | 所有 compose/config 都是 `qwen3-asr` |
| TTS 默认 `Qwen3-TTS 1.7B（GGML）` | 实际是 `torch` 后端（`--qwen3_tts_backend torch`），非 GGML |
| §4.2 "STT 默认 parakeet-tdt、TTS 默认 qwen3" | 同上 |
| §5 方案二默认拉 `Qwen/Qwen3-8B-Instruct-GGUF` | `llm-bundled.yml` 实际指向宿主已缓存的 `Qwen3.5-4B-Instruct-GGUF`（Q4_K_M），llama 服务被注释掉 |
| §5.1 `docker compose -f docker-compose.llm-bundled.yml up -d --build` | 该文件无 `build:`，只有 `image:`，`--build` 无效 |

### 5.6 【低】`config/prod.env` 缺 `S2S_ADMIN_TOKEN` **[已验证]**

`config/prod.env.example:22` 定义了 `S2S_ADMIN_TOKEN=`（空），但 `config/prod.env`（实际生效文件）**没有这一项**。后果：`/admin/sessions/update` 返回 `503 admin_disabled`（fail-closed 设计，不会静默放行）。P1 场景下参数平台的"链路 B 热更新"当前不可用，只有 `505` 之外的重启路径。

### 5.7 【低】`temp`/构建产物入库

`llama-server-2048.err`(67 行)、`llama-server.err`(165 行)、`llama-server-2048.out`(0 字节) 已提交进版本库（`git diff` 显示为 A）。`build-cu130*.log`、`build.s2s.A.log`、`model_metrics.log`、`llm-proxy.py`、`diag_import.py` 之外的部分未入库。建议清理。

### 5.8 【低】`LLM/utils.py` 重复定义 `_regex_sent_tokenize` **[已验证]**

```
LLM/utils.py:101  def _regex_sent_tokenize(...)   # 第一份（含中英文标点，按 \s+ 切）
LLM/utils.py:139  def _regex_sent_tokenize(...)   # 第二份（_SENTENCE_END_RE 版本）
```

第二份覆盖第一份。行为差异：第 101 行版 `re.split(r"(?<=[.!?。！？…])\s+", text)`，第 139 行版 `_SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？])\s*")`（少了 `…`，且 `\s*` 允许零宽切分 → 连续标点会产生空串后被 `if piece.strip()` 过滤，功能上等价但更易误切）。属可清理的重复代码，不影响运行。

### 5.9 【低】`docker-compose.yml` 依赖工作区外路径 **[已验证]**

```yaml
volumes:
  - ../.silero-dl2/silero-vad-master:/opt/silero-vad:ro
```

`Test-Path ../.silero-dl2/silero-vad-master` → `True`（本机存在）。但这意味着该 compose **只能在 `d:\work\qwen-audio-agent\` 这一层布局下运行**，单独 clone 仓库会挂载到空目录 → Silero VAD 加载失败。建议改用仓库内 `./silero-vad`（P2/P3 均如此）。

---

## 6. 未同步的上游变更（`0ed1bb9..origin/main`，35 个提交）

> 这部分**不属于本项目的改动**，列出是为了避免把上游行为误当成本地实现，也便于评估后续 rebase 成本。

| 簇 | 提交 | 影响 |
|---|---|---|
| **Phonon TTS 新后端** | `3978eba` `51a76e6` `8069376` `37ebeba` `f5c7b00` `d52ab33` `1c1572b` `d8fe610` `ccb05bb` `e4ec5e0` `c057ba6` `8ebde04` `f351d2a` `c2d801c` `c19c446` | 新增 `TTS/phonon_tts_handler.py`；默认语音/线程数/语言多次调整。**与本地无冲突但未纳入** |
| **终端会话 UI** | `3046bb8` `771db75` `b363c83` `fa28e2b` `45873ba` `6870015` `fca7621` | `pipeline/console.py`、conversation-only 模式、quiet startup |
| **文案/控件** | `0bc33c5` `c57...` | `api/openai_realtime/voice_controls.py` 方向键选音色 |
| **Demo 安全** | `1bab877` `b51e95a` `5229f2b` `0835002` | Serper key 门禁、sweep 恢复 |
| **Demo local VAD** | `496759e` | 浏览器端本地 VAD，加快打断 |
| **DGX Spark 文档** | `612a56a` `863a153` `c67e9da` | 部署文档 |

**rebase 风险提示**：本地把 `demo/server.py` 的 40 个 CLI 参数搬到了 `config/prod.yaml`，而上游同期在改 `demo/server.py`（Demo 安全 + local VAD），`demo/` 目录冲突概率高；`api/openai_realtime/` 文件名层面互斥（本地上游各增一个文件），需人工合并。

---

## 7. 完整配置表

### 7.1 公共配置项（三场景共享，改一处全局生效）

| 项 | 值 | 来源 | 说明 |
|---|---|---|---|
| 服务进程 | `speech-to-speech serve` | `pyproject.toml:124` | entry point `speech_to_speech.cli:main` |
| 对外协议 | OpenAI Realtime（WS/WebRTC） | 代码 | 路径 `/v1/realtime` |
| 容器内端口 | `8765` | 各 compose | `--port 8765` / `runtime.server.port: 8765` |
| 容器内 host | `0.0.0.0` | 各 compose | `prod.yaml:73` 注释：catalog 默认 `127.0.0.1` 容器外不可达 |
| VAD 后端 | `silero` | `config/prod.yaml:13` | 无 `--vad` 时即 CLI 默认 |
| Smart Turn 权重 | `/root/.cache/smart-turn-v3.2-cpu.onnx` | 各 compose + `prod.yaml:20` | **必须给**，否则触发联网下载 |
| Smart Turn 开关 | 关 | 各 `--no_smart_turn` / `smart_turn: false` | — |
| speculative/unanswered reopen | `0` / `0` | 各 compose | 消除重复转写 |
| STT 后端 | `qwen3-asr` | 全部 | `--stt qwen3-asr` |
| STT 权重 | `/root/.cache/qwen3-asr-model-hf` | 全部 | 必须 `-hf` 版（需 `chat_template.jinja`） |
| STT 语种 | `auto` | 全部 | — |
| TTS 后端 | `qwen3` | 全部 | `--tts qwen3` |
| TTS 权重 | `/root/.cache/qwen3-tts-model` | 全部 | CustomVoice 1.7B |
| TTS backend | `torch` | 全部 | 非 GGML |
| TTS 设备 | `cuda` | 全部 | — |
| TTS 流式 | `non_streaming=false`、`chunk=4` | 全部 | 句内流式 |
| 首句送 TTS | `--stream_batch_sentences 1` | 全部 | TTFA 关键 |
| LLM 后端 | `chat-completions` | 全部 | OpenAI 兼容 |
| LLM 流式 | `--responses_api_stream` | 全部 | — |
| LLM 模型名 | `Qwen3-8B` | P1/P2/P3/P4/P7 | P5/P6 为 GGUF 别名 |
| 离线开关 | `HF_HUB_OFFLINE=1` | P1/P2/P3/P4/P5 | 权重已缓存，防止 HEAD 重试卡死 |
| HF 镜像 | `HF_ENDPOINT=https://hf-mirror.com` | P2/P3/P4/P5 | P1 未设（用 `TRANSFORMERS_OFFLINE=1`） |
| ModelScope | `MODELSCOPE_ENDPOINT=https://modelscope.cn` | P2/P3/P4 | 137 上 CosyVoice 走此源 |
| 进度条 | `HF_HUB_ENABLE_PROGRESS_BARS=false` | P2/P3/P4 | 日志干净 |
| tokenizer 并发 | `TOKENIZERS_PARALLELISM=false` | P1/P7 | 消除 fork 警告 |
| 重启策略 | `restart: unless-stopped` | 全部有 | — |
| GPU 能力 | `capabilities: [gpu]` | P1/P2/P3/P4/P5/P6/P7 | 需 NVIDIA Container Toolkit |
| 主机映射 | `host.docker.internal:host-gateway` | P1/P2/P3/P4/P5/P7 | llama-server / llm-proxy 回连 |
| 缓存卷 | `./cache/:/root/.cache/` | P1/P2/P3/P4/P5/P6 | P7 无（模型已烤入） |
| Silero 卷 | `./silero-vad:/opt/silero-vad:ro` | P2/P3/P5/P6 | P1 用 `../.silero-dl2/...`；P7 烤入 |
| 管理端点鉴权 | `S2S_ADMIN_TOKEN` | `prod.env.example:22` | **`prod.env` 实际未设 → 503**（§5.6） |

### 7.2 主配置表

| 字段 | **场景 A：Windows + Docker Desktop(WSL2) 本机 GPU** | **场景 B：WSL2 内直接运行（无 Docker）** | **场景 C：Linux 直连（不走代理）** |
|---|---|---|---|
| **部署场景** | 本机开发/验证，LLM 走局域网 GPUStack 经宿主代理 | 未验证（无证据） | 137 生产 / GPU 服务器 |
| **OS / 运行方式** | Windows 11 + Docker Desktop（WSL2 后端）+ 宿主 PowerShell 跑辅助进程 | WSL2 Ubuntu + `uv run`（**本仓库无此配置，属假设**） | Linux + docker + nvidia-container-toolkit |
| **编排 / 启动文件** | `docker-compose.local.yml`（P2）<br>或 `docker-compose.baked.yml`（P7）<br>或 `docker-compose.llm-bundled.yml`（P5） | — | `docker-compose.yml`+`config/prod.yaml`（P1）<br>或 `docker-compose.gpustack.yml`（P3）<br>或 `docker-compose.cu130.yml`（P4） |
| **STT 后端** | `qwen3-asr` | 同 | `qwen3-asr` |
| **STT 模型 / 路径** | Qwen3-ASR-1.7B-HF<br>`/root/.cache/qwen3-asr-model-hf` | 同 | 同 |
| **STT 设备 / 精度** | `cuda`（P2）/ `auto`（P1/P3/P4/P7）；bf16 | 同 | `auto`；bf16 |
| **LLM 后端** | `chat-completions` | 同 | `chat-completions` |
| **LLM 模型** | `Qwen3-8B`（GPUStack）<br>或 `Qwen3.5-4B-Instruct-GGUF`（P5 本机 llama） | 同 | `Qwen3-8B` |
| **LLM 端点** | `http://host.docker.internal:8891/v1-openai`（GPUStack 经代理）<br>`http://host.docker.internal:8080/v1`（本机 llama） | — | `http://192.168.40.30/v1-openai` |
| **LLM 设备/精度** | 远端（GPUStack 决定）<br>本机 llama：GPU0 / GGUF Q4_K_M / `-c 8192 -np 1` | — | 远端 GPUStack |
| **TTS 后端** | `qwen3`（`backend=torch`） | 同 | 同 |
| **TTS 模型 / 路径** | Qwen3-TTS-12Hz-1.7B-CustomVoice<br>`/root/.cache/qwen3-tts-model` | 同 | 同 |
| **TTS 设备 / 精度** | `cuda`；bf16；`chunk_size=4`，非流式关闭 | 同 | 同 |
| **VAD 后端** | `silero` + `--no_smart_turn` | 同 | 同 |
| **VAD 关键参数** | P2：`min_silence=500 / min_speech=250 / short_segment_merge=800 / thresh=0.6`<br>P5：`min_silence=64 / thresh=0.6`<br>P1/P7：`min_silence=700` | — | P1/P3/P4：`min_silence=700`（P1 在 `prod.yaml:15`） |
| **关键环境变量** | `GPUSTACK_BASE_URL`、`GPUSTACK_MODEL`、`GPUSTACK_API_KEY`、`PIPELINE_PORT`、`PIPELINE_GPU_ID`（`.env.local`） | — | P1：`GPUSTACK_API_KEY` + `HF_HUB_OFFLINE` + `TRANSFORMERS_OFFLINE` + `TOKENIZERS_PARALLELISM`（`config/prod.env`）<br>P3/P4：`GPUSTACK_*` + `PIPELINE_GPU_ID=1` |
| **代理设置** | **启用**：宿主 `python llm-proxy.py 8891` 常驻；容器经 `host.docker.internal:8891` 访问 GPUStack。可选 `http_proxy` 不需要（代理是应用层反向代理，不是 HTTP_PROXY） | — | **禁用/直连**：`--network` 默认 bridge，直连 `192.168.40.30:80`；不设 `HTTP_PROXY`/`HTTPS_PROXY` |
| **服务地址与端口** | 宿主 `http://127.0.0.1:8765` → 容器 `0.0.0.0:8765`（`${PIPELINE_PORT:-8765}:8765/tcp`）<br>代理端口 `127.0.0.1:8891`（宿主）<br>llama `:8080`（宿主，P5） | — | `http://192.168.1.137:8765`（P1/P3/P4）<br>`expose: 8765` + `ports: 8765:8765` |
| **API Key 配置方式** | `.env.local` 明文 `GPUSTACK_API_KEY=gpustack_...`；容器内 `--responses_api_api_key "${GPUSTACK_API_KEY:-not-needed}"` | — | P1：`config/prod.env` 的 `GPUSTACK_API_KEY=not-needed`，YAML 用 `{env: GPUSTACK_API_KEY}` 映射注入<br>P3/P4：`.env.gpustack`/`.env.cu130` 明文；`--responses_api_api_key "${GPUSTACK_API_KEY:-not-needed}"` |
| **启动命令** | ①（仅 P2 需首次构建）`docker build -f Dockerfile.local -t speech-to-speech-local:cu130-1.1-sox .`<br>②（宿主）`python llm-proxy.py 8891`<br>③ `docker compose -f docker-compose.local.yml --env-file .env.local up -d` | — | P1：`docker compose up -d`（自动读 `config/prod.env` + `prod.yaml`）<br>P3：`docker compose -f docker-compose.gpustack.yml --env-file .env.gpustack up -d`<br>P4：`docker compose -f docker-compose.cu130.yml --env-file .env.cu130 up -d` |
| **依赖的配置文件** | `docker-compose.local.yml` + `.env.local` + `Dockerfile.local` + `cache/` + `silero-vad/` | — | P1：`docker-compose.yml` + `config/prod.yaml` + `config/prod.env` + `cache/` + `../.silero-dl2/silero-vad-master`<br>P3/P4：对应 compose + env + `cache/` + `silero-vad/`（P4 另需 `nltk_data/`） |
| **前置条件** | Docker Desktop 已启用 WSL2 后端 + NVIDIA GPU 支持；宿主驱动 572.84 → **必须用 cu128 镜像**（P2 是 cu130 → 见注意事项） | WSL2 内需 nvidia 驱动透传 | 驱动 **>=580** 才能用 cu130 镜像；否则 "driver too old"→ 静默回退 CPU（RTF≈3.7x） |
| **注意事项** | ① P2 镜像 `cu130-1.1-sox` 而宿主驱动 572.84/CUDA12.8 → `Dockerfile.cu130` 注释明确"本机请用 cu128 变体"，**此处存在版本风险，需实测确认是否真在 GPU 上跑**<br>② **禁止**挂载 `nltk_data`（Windows 挂载权限 777 → nltk 拒用 → 联网重下 → 启动卡死）<br>③ `.env.local` 的代理改动**尚未提交**<br>④ `llm-proxy.py` 绑 `127.0.0.1`，见 §5.3 | 未验证，不建议作为正式路径 | ① P1 的 `prod.yaml` 无 `chat_size`/`thresh`/`min_speech_ms`，走 CLI 默认<br>② P4 用 `cu130-1.0` 预构建镜像，**缺 tool_calls 修复** → 一旦用工具后续全轮失败；须改用 `Dockerfile.sox` 覆盖或重建<br>③ P4 需 `./nltk_data/` 挂载（137 无外网到 nltk.org） |

### 7.3 场景专用配置项（仅该场景生效，不可跨场景复用）

| 场景 | 专用项 | 值 | 为什么专用 |
|---|---|---|---|
| A（Windows） | `GPUSTACK_BASE_URL` | `http://host.docker.internal:8891/v1-openai` | WSL2 NAT 到 `192.168.40.30` 返回 502 |
| A | 宿主进程 `llm-proxy.py` | `python llm-proxy.py 8891` | 只有 Windows 宿主直连 GPUStack 正常 |
| A | `PIPELINE_GPU_ID` | `0` | 本机仅 1 张 RTX 5070 Ti Laptop 12GB |
| A | `--min_silence_ms 500` / `--min_speech_ms 250` / `--short_segment_merge_ms 800` | — | 本机实测调参（注释记录了 700ms 时捕获 75%、首音 3.9~6.7s） |
| A | `--chat_size 40` | — | 降 LLM 计算量 |
| A | `--enable_live_transcription` + `0.5` | — | 本机开字幕 |
| A（P5） | 宿主 `llama-server.exe --port 8080 --reasoning-budget 0` | LM Studio 自带 CUDA 版 | ghcr.io 拉取被限速，复用宿主已装二进制 |
| A（P5） | `--min_silence_ms 64` | — | 本机验证时最激进断句 |
| C（P1） | `-f /app/config/prod.yaml --name prod` | 文件模式 | 40+ 开关集中在 YAML |
| C（P1） | env 继承优先级 | `environment` > `env_file` | compose 注释：一旦写进 `environment`，参数平台就改不动 |
| C（P1） | `./config:/app/config:ro` | 只读挂载 | 保证配置只有一个写入方 |
| C（P3/P4） | `PIPELINE_GPU_ID=1` | — | 137 的 GPU0 被 GPUStack vLLM 占满 |
| C（P4） | `./nltk_data/:/root/nltk_data/` | — | 137 容器无外网到 nltk.org |
| C（P4） | 镜像 `ccr.ccs.tencentyun.com/llm-basic/speech-to-speech:cu130-1.0` | 预构建 | 无 `build:`，不重建 |
| P6（vi/ms） | `--stt whisper --stt_model_name distil-whisper/distil-large-v3`<br>`--tts facebookmms --tts_language vi` | — | 唯一覆盖越南语/马来语的组合 |
| P7 | 无卷挂载 | 模型烤入 `/root/.cache/*` | 完全自包含 |

### 7.4 可直接复制的部署脚本

**场景 A（Windows，本机 GPU + GPUStack 经代理）**

```powershell
# 0) 前置：Docker Desktop 已启用 WSL2 后端；宿主能 curl 通 GPUStack
curl.exe http://192.168.40.30/v1-openai/models -H "Authorization: Bearer not-needed"

# 1) 首次构建本机镜像（Dockerfile.local 基于预构建 cu130-1.1）
docker build -f Dockerfile.local -t speech-to-speech-local:cu130-1.1-sox .

# 2) 宿主启动 LLM 反向代理（新窗口，常驻）
cd d:\work\qwen-audio-agent\speech-to-speech-src
python llm-proxy.py 8891
# 预期输出：llm-proxy listening on 127.0.0.1:8891 -> http://192.168.40.30:80

# 3) 起 pipeline
docker compose -f docker-compose.local.yml --env-file .env.local up -d

# 4) 验证
docker compose -f docker-compose.local.yml logs -f pipeline
# 期望出现：Qwen3-ASR 加载完成 / Qwen3-TTS warmed up / LLM 连通
```

**场景 C（Linux 137，GPUStack 直连）**

```bash
cd /home/jiangwei/nvme/speech-to-speech

# 方式 1：文件模式（推荐，对应 docker-compose.yml）
docker compose up -d
docker compose logs -f pipeline

# 方式 2：GPUStack 参数式（GPU1，不再重建镜像）
docker compose -f docker-compose.gpustack.yml --env-file .env.gpustack up -d

# 方式 3：预构建 cu130 镜像（注意 §7.2 注意事项②，缺 tool_calls 修复）
docker compose -f docker-compose.cu130.yml --env-file .env.cu130 up -d
```

**验证连通性（三场景通用）**

```bash
# LLM 端点
curl -s http://<llm-host>/v1-openai/models -H "Authorization: Bearer <key>"
# Realtime 服务
curl -sI http://<pipeline-host>:8765/v1/realtime
# 会话热更新（需 S2S_ADMIN_TOKEN，prod.env 当前未设 → 503）
curl -sX POST http://<pipeline-host>:8765/admin/sessions/update \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scope":"all","session":{"instructions":"Keep replies under 20 words."}}'
```

---

## 8. 未验证项与假设

| 项 | 状态 | 原因 / 如何验证 |
|---|---|---|
| 场景 B（WSL2 内直接 `uv run`，无 Docker） | **未验证，且仓库内无对应配置** | 无 compose/env/Dockerfile 支持；仅 `docker-compose.llm-bundled.yml:3` 提到"Windows 部署"实为 Docker Desktop。若需支持，需补 `PYTHONPATH`/`HF_HOME` 与 `sox` 安装说明 |
| `llm-proxy.py` 绑 `127.0.0.1` 能否被 `host.docker.internal` 命中 | **未验证** | 见 §5.3；用 `docker compose exec pipeline curl -v http://host.docker.internal:8891/v1-openai/models` 验证 |
| 本机 cu130 镜像在驱动 572.84 上是否真在 GPU 跑 | **未验证（有明确风险）** | `Dockerfile.cu130:12-16` 说"驱动低于 580 → 静默回退 CPU（RTF≈3.7x）"；用 `nvidia-smi` + 日志中 RTF 判断 |
| `qwen3-asr-model-hf` 具体参数量（1.7B） | **推断** | 由 `hidden_size=2048` + 3887MB bf16 反推；未读 `README.md` 的模型卡标题 |
| `Qwen3.5-4B-Q4_K_M.gguf` 的 llama-server 实际吞吐 | **未验证** | `llama-server*.log` 有日志但未在本会话分析 |
| `model_monitor` 在生产链路的实际覆盖 | **已验证为不覆盖** | 见 §2.7；`model_metrics.log` 为 0 字节 |
| 上游 35 提交 rebase 后的兼容性 | **未验证** | 见 §6 风险提示 |
| `docs/hardware/plan-*.md` 中的并发/显存数字 | **文档声明，未实测** | 文档自身已标 `performance-assumptions.md` 为"假设条件表" |
| `demo/param_platform` 端到端发布链路 | **未验证** | 有 594 行测试，但未运行；`s2s-params.sqlite3` 存在说明跑过 |

---

## 9. 复现本文档的命令清单

```bash
# —— 基准 ——
git rev-parse --abbrev-ref HEAD
git log -1 --format='%H %ci %s'
git remote -v
git fetch origin --prune
git log -1 --format='%H %ci %s' origin/main
git merge-base HEAD origin/main
git rev-list --left-right --count HEAD...origin/main

# —— 差异范围 ——
git diff --stat 0ed1bb9 HEAD
git diff --name-status 0ed1bb9 HEAD
git log --oneline 0ed1bb9..HEAD            # 本项目 27 提交
git log --oneline 0ed1bb9..origin/main     # 上游 35 提交（未同步）

# —— 逐模块代码差异 ——
git diff 0ed1bb9 HEAD -- src/speech_to_speech/LLM
git diff 0ed1bb9 HEAD -- src/speech_to_speech/STT src/speech_to_speech/TTS
git diff 0ed1bb9 HEAD -- src/speech_to_speech/VAD src/speech_to_speech/baseHandler.py
git diff 0ed1bb9 HEAD -- src/speech_to_speech/api src/speech_to_speech/s2s_pipeline.py
git diff --stat 0ed1bb9 HEAD -- src/speech_to_speech/backend_registry.py   # 空 = 未改

# —— 配置与模型核对 ——
git check-ignore -v .env .env.local config/prod.env cache model_metrics.log
git ls-files -s silero-vad
Get-ChildItem cache -Directory
Get-Content cache/qwen3-asr-model-hf/config.json
Get-Content cache/qwen3-tts-model/config.json

# —— 运行态 ——
docker compose -f docker-compose.local.yml config     # 解析后的最终配置
docker compose -f docker-compose.local.yml logs -f pipeline
```

---

## 10. 建议的后续动作（按优先级）

1. **P0** — 提交 `.env.local` 的代理改动，或在 `.env.local.example` 中固化"Windows 必须走 8891"的口径（§2.13、§5.2）。
2. **P0** — 决定 `sensevoice_handler.py` / `cosyvoice_handler.py` 的归属：补 `backend_registry` 注册 + 测试，或删除（§5.1）。
3. **P1** — 统一 `docker-compose.cu130.yml` 与 `docker-compose.local.yml` 的参数口径（两者头部都声称"完全一致"）（§5.4）。
4. **P1** — `config/prod.env` 补 `S2S_ADMIN_TOKEN`，否则参数平台热更新链路在 P1 永远 503（§5.6）。
5. **P1** — `docker-compose.yml` 的 `../.silero-dl2/` 改为仓库内 `./silero-vad`（§5.9）。
6. **P2** — 修正 `docs/deployment.md` 的模型描述（Parakeet → qwen3-asr，GGML → torch）（§5.5）。
7. **P2** — 清理 `LLM/utils.py` 重复的 `_regex_sent_tokenize`（§5.8）；`git rm` 已入库的 `llama-server*.err/.out`（§5.7）。
8. **P2** — 把 `model_monitor.trace` 补到 `qwen3_asr_handler` 与 `base_openai_compatible_language_model`，否则主链路无延迟数据（§2.7）。
