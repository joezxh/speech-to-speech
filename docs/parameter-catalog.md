# S2S 部署参数清单（speech-to-speech-src）

> 本文件是「S2S 部署参数配置平台」的参数单一事实来源的人读版；机器可读镜像见
> [`parameter-catalog.yaml`](./parameter-catalog.yaml)，平台设计见
> [`superpowers/specs/2026-10-23-s2s-deployment-parameter-platform-design.md`](./superpowers/specs/2026-10-23-s2s-deployment-parameter-platform-design.md)。
> YAML 语法与校验语义以 [`configuration.md`](./configuration.md) 为准，本文不复制其内容。

- 版本：`s2s-parameter-catalog-v1`
- 覆盖范围：`speech-to-speech-src` 启动参数通道 + 会话运行时通道 + 容器编排 + 客户端
- 参数计数：A 层 125 条（13 个方向）、B 层 9 个深挖后端 78 条、目录化后端 20 个；机器版 196 条（含 5 条 `session.*` 热更新字段）；逐章明细见附录 C
- 默认值均标注 `文件:符号` 溯源；标注 `固定` 的表示源码常量或编排文件写死，平台不可配置

## 0. 阅读指南

### 0.1 条目字段（13 项）

配置面（表 A）：参数名称、作用、所属模块/文件、默认值、允许范围/格式、是否必填、配置来源与优先级。
运行面（表 B）：生效方式、建议暴露、暴露级别、影响面、变更代价、风险提示/副作用。

### 0.2 暴露分级判定

| 级别 | 判定条件 | 含义 |
|---|---|---|
| `basic` | 无安全风险、改坏不影响启动与安全、面向业务语义 | 普通用户在默认页直接可改 |
| `advanced` | 影响延迟/资源/并发，需要理解系统 | 高级页可见，带数值建议 |
| `expert` | 设备/精度/后端选择，配错会 OOM 或启动失败 | 折叠展示 + 警告 |
| `ops` | 安全敏感或环境绑定，暴露给用户会引发事故 | 仅运维可见，必须写明风险类别 |

`ops` 级风险类别固定三选一（或组合）：**安全**（未鉴权暴露、密钥）、**隐私**（对话内容留存）、**环境绑定**（端口/GPU/镜像/路径）。

### 0.3 来源优先级（全表统一）

1. 显式 YAML / CLI 字段值（最高）
2. `{env: NAME}` 环境变量引用（缺失即报错，不回退默认）
3. dataclass 默认值（最低）
4. 覆盖型开关：`device` 覆盖组件 `*_device`；`mac_optimal_settings` 提供预设，显式字段再覆盖预设
5. 运行时会话：`session.update` 覆盖已解析的会话字段。**真正生效的只有 4 类**：`instructions`、`turn_detection`（`create_response` / `interrupt_response`）、转录语言、`extensions`；`model` / `voice` 仅被接受并回显，不改变实际模型与音色（详见附录 A.2）

### 0.4 生效方式取值

`启动` = 进程启动时 argparse/dataclass 固化，只能重启；`热更新` = `RuntimeConfig` 会话内可改；`启动+热更新` = 两者皆可；`容器` = 需重建容器。

---

## A 层：部署通用参数

### A1. 服务监听与端口（2）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `host` | Realtime 服务监听地址 | `realtime_server_arguments.py` | `127.0.0.1` | IPv4/IPv6 字符串 | 否 | YAML `runtime.server.host` > `{env}` > 默认 |
| `port` | HTTP/WebSocket 监听端口 | `realtime_server_arguments.py` | `8765` | 1–65535 整数 | 否 | YAML `runtime.server.port` > `{env}` > 默认 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `host` | 启动 | 否 | ops | 进程级 | 重启 | **安全**：默认仅回环；`0.0.0.0` 会把**无鉴权**的 Realtime API 暴露到网络 |
| `port` | 启动 | 否 | ops | 进程级 | 重启 | **环境绑定**：须与 compose 端口映射 `PIPELINE_PORT:8765` 一致，改错则外部不可达 |

### A2. 并发与队列（3）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `num_pipelines` | 管线池实例数，等于最大并发 WebSocket 会话数 | `module_arguments.py:num_pipelines`；YAML `pipelines.<name>.num_pipelines` | `1` | 正整数 `>=1`；硬约束 `<= floor(可用显存×0.85 / 4.6GB)` | 否 | YAML `num_pipelines` > `{env}` > 默认 1 |
| `-np`（llama 并行槽） | 端侧 llama.cpp 的并发请求槽数 | `docker-compose.yml`（llama 服务 command） | `1` | 正整数；与 llama 上下文 `-c` 共同决定单槽上下文 | 否 | compose 文件字面值（无 env 化） |
| pool 满拒绝 | 池内实例全部占用时新连接被拒绝（无排队） | `api/openai_realtime/websocket_router.py` | 固定行为 | 无 | 固定 | 固定行为：容量 = `num_pipelines`，无等待队列 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `num_pipelines` | 启动 | 是 | advanced | 管线级 | 分钟级 | 每路独占整套 handler，实测约 4.6GB 显存；超配直接 OOM，降配中断现有会话 |
| `-np` | 容器 | 否 | ops | 容器级 | 分钟级 | **环境绑定**：与 GPU 显存、`-c` 上下文耦合；调大易 OOM |
| pool 满拒绝 | 固定 | 否 | ops | 管线级 | 无 | 无排队意味着高峰期直接失败；扩容只能加 `num_pipelines` 或加实例 |

### A3. 超时与重试（6）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `llm_proxy_connect_timeout_s` | LLM 代理到上游的连接超时 | `module_arguments.py:llm_proxy_connect_timeout_s` | `10.0` | 正浮点（秒）；读无超时 | 否 | YAML `pipelines.<n>.options` > `{env}` > 默认 |
| `openai_stt_timeout` | OpenAI 兼容 STT 的 HTTP 超时 | `openai_stt_arguments.py:openai_stt_timeout` | `60.0` | 正浮点（秒），构造时校验 `>0` | 否 | 块 settings > `{env}` > 默认 |
| `openai_tts_timeout` | OpenAI 兼容 TTS 的 HTTP 超时 | `openai_tts_arguments.py:openai_tts_timeout` | `300.0` | 正浮点（秒） | 否 | 块 settings > `{env}` > 默认 |
| `connection_retry_timeout_s` | 本地音频客户端重连窗口 | `api/openai_realtime/audio_client.py:connection_retry_timeout_s` | `30.0` | 正浮点（秒） | 否 | YAML `runtime.client` > `{env}` > 默认 |
| `request_timeout_s`（LLM） | OpenAI 兼容 LLM 的读取超时，超时即结束本轮回复 | `LLM/base_openai_compatible_language_model.py:196` | `20.0` | 浮点（秒），`connect=min(10.0, x)` | 不可配置 | 构造参数写死，无 CLI/YAML 入口 |
| 自动重试策略 | LLM/STT/TTS 的 HTTP 请求均为单次尝试 | `base_openai_compatible_language_model.py`、`STT/openai_compatible_handler.py` | 固定（无重试） | 无 | 固定 | 固定行为：无指数退避；失败即错误事件，由客户端重连兜底 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `llm_proxy_connect_timeout_s` | 启动 | 是 | expert | 进程级 | 重启 | 仅约束连接；流式读无超时，上游卡住会长时间占用实例 |
| `openai_stt_timeout` | 启动 | 是 | expert | 管线级 | 重启 | 过小会截断长语音；过大在远端故障时拖住整路会话 |
| `openai_tts_timeout` | 启动 | 是 | expert | 管线级 | 重启 | 合成超时表现为该句静音；过小会频繁丢句 |
| `connection_retry_timeout_s` | 启动 | 是 | advanced | 会话级 | 重启 | 过短会让弱网客户端频繁放弃重连 |
| `request_timeout_s`（LLM） | 固定 | 否 | expert | 管线级 | 无 | 不可配置；20s 后强制结束回复，长回答可能被截断 |
| 自动重试策略 | 固定 | 否 | ops | 管线级 | 无 | 无重试意味着瞬时网络抖动直接失败，平台侧需提供健康检查与重启 |

### A4. 音频采样/通道与格式（8）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `sample_rate` | VAD 与管线音频采样率 | `vad_arguments.py:sample_rate` | `16000` | 正整数（Hz）；与模型要求一致 | 否 | 块 settings > `{env}` > 默认 |
| `PIPELINE_SAMPLE_RATE` | 管线内部固定采样率 | `api/openai_realtime/service.py:110` | `16000` | 固定常量 | 固定 | 不可配置 |
| `send_rate` | 客户端上行采样率 | `audio_client.py:send_rate` | `16000` | 正整数（Hz） | 否 | `runtime.client` > `{env}` > 默认 |
| `recv_rate` | 客户端下行采样率 | `audio_client.py:recv_rate` | `16000` | 正整数（Hz） | 否 | 同上 |
| `chunk_size` | 客户端收发块大小 | `audio_client.py:chunk_size` | `1024` | 正整数（采样点） | 否 | 同上 |
| `playback_buffer_ms` | 播放前缓冲时长 | `audio_client.py:playback_buffer_ms` | `0.0` | 有限非负数（毫秒） | 否 | 同上 |
| `openai_tts_sample_rate` | 远端 TTS 返回裸 PCM 的采样率 | `openai_tts_arguments.py:openai_tts_sample_rate` | `24000` | 正整数（Hz）；Qwen3-TTS 为 24000 | 否 | 块 settings > `{env}` > 默认 |
| `CHUNK_SAMPLES` | 服务端音频分块常量 | `api/openai_realtime/service.py:111` | `512` | 固定常量 | 固定 | 不可配置 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `sample_rate` | 启动 | 是 | advanced | 管线级 | 重启 | 与 STT/TTS 模型采样率不匹配会变调或识别率骤降；16k 为全链路约定 |
| `PIPELINE_SAMPLE_RATE` | 固定 | 否 | ops | 管线级 | 无 | 固定 16kHz；改它需改源码与全部后端适配 |
| `send_rate` | 启动 | 是 | advanced | 会话级 | 重启 | 与设备实际能力不符会导致重采样开销与延迟 |
| `recv_rate` | 启动 | 是 | advanced | 会话级 | 重启 | 同上 |
| `chunk_size` | 启动 | 是 | advanced | 会话级 | 重启 | 过小抬高回调频率与 CPU；过大抬高端到端延迟 |
| `playback_buffer_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 过小易 underrun 爆音；过大增加首音延迟 |
| `openai_tts_sample_rate` | 启动 | 是 | expert | 管线级 | 重启 | 配错会变调/变速；仅对返回裸 PCM 的兼容服务生效 |
| `CHUNK_SAMPLES` | 固定 | 否 | ops | 管线级 | 无 | 固定 512；改动影响全部下游分块假设 |

### A5. 模型与语音（全局）（11）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `stt` | STT 后端选择器 | `module_arguments.py:stt` | `parakeet-tdt` | `STT_BACKENDS` 枚举（含 `none`，需音频输入 LLM） | 否 | 块 `backend`（CLI `--stt`）> 默认 |
| `llm_backend` | LLM 后端选择器 | `module_arguments.py:llm_backend` | macOS `mlx-lm`，其他 `transformers` | `LLM_BACKENDS` 枚举 | 否 | 块 `backend` > 默认 |
| `tts` | TTS 后端选择器 | `module_arguments.py:tts` | `qwen3` | `TTS_BACKENDS` 枚举 | 否 | 块 `backend` > 默认 |
| `model_name` | LLM 模型 ID 或本地路径 | `language_model_base_arguments.py:model_name` | `Qwen/Qwen3.5-4B`（OpenAI 兼容后端覆写为 `gpt-5.6-terra`） | 字符串；Hub ID 或绝对路径 | 否 | 块 settings > `{env}` > 默认 |
| `user_role` | 用户消息在上下文中的角色名 | `language_model_base_arguments.py:user_role` | `user` | 字符串 | 否 | 同上 |
| `init_chat_role` | 会话初始系统消息角色 | `language_model_base_arguments.py:init_chat_role` | `system` | 字符串 | 否 | 同上 |
| `init_chat_prompt` | 系统提示词（助手人设） | `language_model_base_arguments.py:init_chat_prompt` | `"You are a helpful and friendly AI assistant. …less than 20 words."` | 字符串，建议 ≤2k 字符 | 否 | 同上；会话 `session.update.instructions` 可覆盖 |
| `chat_size` | 保留的历史交互轮数 | `language_model_base_arguments.py:chat_size` | `30` | 正整数 | 否 | 同上 |
| `stream_batch_sentences` | 流式输出每批累计句数 | `language_model_base_arguments.py:stream_batch_sentences` | `3` | 正整数；`1` = 逐句流式 | 否 | 同上 |
| `enable_lang_prompt` | 是否在系统提示中追加本轮语言指令 | `language_model_base_arguments.py:enable_lang_prompt` | `false` | 布尔 | 否 | 同上 |
| `compact_history` | 超 `chat_size` 时后台摘要旧轮次 | `language_model_base_arguments.py:compact_history` | `true` | 布尔 | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `stt` | 启动 | 是 | expert | 管线级 | 分钟级 | 切换后端会改变模型显存与语言支持；`none` 需音频输入 LLM，否则校验失败 |
| `llm_backend` | 启动 | 是 | expert | 管线级 | 分钟级 | 后端能力差异（音频输入/代理/思考）由 `backend_registry` 校验；配错启动失败 |
| `tts` | 启动 | 是 | expert | 管线级 | 分钟级 | 不同后端音色体系与采样率不同；切换需同步权重与缓存 |
| `model_name` | 启动 | 是 | expert | 管线级 | 分钟级 | 模型越大显存越高；远端模型名须与 provider 完全一致 |
| `user_role` | 启动 | 是 | advanced | 管线级 | 重启 | 与模型 chat template 不匹配会降低指令遵循 |
| `init_chat_role` | 启动 | 是 | advanced | 管线级 | 重启 | 非 `system` 可能被部分 chat template 忽略 |
| `init_chat_prompt` | 启动+热更新 | 是 | basic | 会话级 | 秒级 | 过长抬高首 token 延迟与 KV 显存；须脱敏后入库 |
| `chat_size` | 启动 | 是 | basic | 会话级 | 重启 | 过大抬上下文显存；过小丢失多轮记忆 |
| `stream_batch_sentences` | 启动 | 是 | basic | 会话级 | 重启 | 越大首音越慢（默认 3 句）；`1` 为低延迟推荐 |
| `enable_lang_prompt` | 启动 | 是 | basic | 会话级 | 重启 | 每轮追加指令会略增 token 与延迟 |
| `compact_history` | 启动 | 是 | advanced | 会话级 | 重启 | 开启后每轮可能多一次 LLM 调用（摘要） |

### A6. VAD 与判停（22）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `vad` | VAD 后端选择器 | `vad_arguments.py:vad` | `silero` | `silero` / `firered` | 否 | 块 `backend` > 默认 |
| `vad_firered_model_dir` | FireRed Stream-VAD 权重目录 | `vad_arguments.py:vad_firered_model_dir` | `None` | 路径（`~` 展开、相对 YAML 目录） | 条件必填（`vad=firered`） | 块 settings > `{env}` > 默认 |
| `vad_firered_use_gpu` | FireRedVAD 是否用 GPU | `vad_arguments.py:vad_firered_use_gpu` | `false` | 布尔 | 否 | 同上 |
| `thresh` | 语音活动判定阈值 | `vad_arguments.py:thresh` | `0.6` | 0–1 浮点 | 否 | 同上 |
| `sample_rate` | VAD 采样率 | `vad_arguments.py:sample_rate` | `16000` | 正整数（Hz） | 否 | 同上 |
| `min_silence_ms` | 判定句末的最短静音 | `vad_arguments.py:min_silence_ms` | `64` | 非负整数（毫秒） | 否 | 同上 |
| `min_speech_ms` | 有效语音段最短长度 | `vad_arguments.py:min_speech_ms` | `384` | 非负整数（毫秒） | 否 | 同上 |
| `min_speech_continuation_ms` | 软结束轮重开所需语音时长（滞回） | `vad_arguments.py:min_speech_continuation_ms` | `192` | 整数，钳制到 `[100, min_speech_ms]`；`0` 关闭 | 否 | 同上 |
| `max_speech_ms` | 连续语音强制切分上限 | `vad_arguments.py:max_speech_ms` | `inf`（YAML `null` 等价） | 正数（毫秒）或 `inf`/`null` | 否 | 同上 |
| `speech_pad_ms` | VAD 触发前保留的音频回补 | `vad_arguments.py:speech_pad_ms` | `500` | 非负整数（毫秒） | 否 | 同上 |
| `audio_enhancement` | 是否启用降噪/均衡 | `vad_arguments.py:audio_enhancement` | `false` | 布尔 | 否 | 同上 |
| `enable_realtime_transcription` | 说话中渐进释放音频做实时转写 | `vad_arguments.py:enable_realtime_transcription` | `false` | 布尔 | 否 | 同上 |
| `realtime_processing_pause` | 渐进音频分块间隔 | `vad_arguments.py:realtime_processing_pause` | `0.5` | 正浮点（秒） | 否 | 同上 |
| `speculative_reopen_ms` | 软结束轮保留可重开窗口 | `vad_arguments.py:speculative_reopen_ms` | `800` | 非负整数（毫秒）；`0` 关闭 | 否 | 同上 |
| `unanswered_reopen_ms` | 未被回答的软结束轮重开上限 | `vad_arguments.py:unanswered_reopen_ms` | `7000` | 非负整数（毫秒）；受 Smart Turn 上限钳制 | 否 | 同上 |
| `short_segment_merge_ms` | 过短片段的拼接保留时长 | `vad_arguments.py:short_segment_merge_ms` | `0` | 非负整数（毫秒）；`0` 关闭 | 否 | 同上 |
| `smart_turn` | 是否用 Smart Turn v3.2 判停 | `vad_arguments.py:smart_turn` | `true` | 布尔 | 否 | 同上 |
| `smart_turn_model_path` | Smart Turn v3.x CPU ONNX 路径 | `vad_arguments.py:smart_turn_model_path` | `None`（缺省自动下载 v3.2） | 路径（`~` 展开、相对 YAML 目录） | 否 | 同上 |
| `smart_turn_threshold` | Smart Turn 完成概率阈值 | `vad_arguments.py:smart_turn_threshold` | `0.5` | 0–1 浮点 | 否 | 同上 |
| `smart_turn_max_wait_ms` | 不完整轮的推测重开宽限 | `vad_arguments.py:smart_turn_max_wait_ms` | `2000` | 非负整数（毫秒） | 否 | 同上 |
| `smart_turn_incomplete_delay_ms` | 判定不完整后延迟 STT/LLM 的时长 | `vad_arguments.py:smart_turn_incomplete_delay_ms` | `600` | 非负整数（毫秒） | 否 | 同上 |
| `smart_turn_cpu_count` | Smart Turn ONNX 线程数 | `vad_arguments.py:smart_turn_cpu_count` | `1` | 正整数 | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `vad` | 启动 | 是 | expert | 管线级 | 重启 | `firered` 需额外可选依赖与权重目录，缺省会启动失败 |
| `vad_firered_model_dir` | 启动 | 否 | ops | 管线级 | 重启 | **环境绑定**：容器内路径；相对路径按 YAML 目录解析，错路径启动失败 |
| `vad_firered_use_gpu` | 启动 | 否 | expert | 管线级 | 重启 | 占用 GPU 显存，与 STT/TTS 争抢 |
| `thresh` | 启动 | 是 | advanced | 管线级 | 重启 | 过高漏检开头、过低误触噪音，直接影响断句 |
| `sample_rate` | 启动 | 是 | advanced | 管线级 | 重启 | 与模型/音频流不匹配会判停失准 |
| `min_silence_ms` | 启动 | 是 | basic | 会话级 | 重启 | 过小频繁断句、过大迟钝；生产常用 700ms |
| `min_speech_ms` | 启动 | 是 | basic | 会话级 | 重启 | 过大会吞掉短应答（"嗯""好"） |
| `min_speech_continuation_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 与 `min_speech_ms` 配合；过大导致续说被当新轮 |
| `max_speech_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 过小长段落被强制切分；默认无限 |
| `speech_pad_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 过小切掉首字、过大引入静音延迟 |
| `audio_enhancement` | 启动 | 是 | advanced | 管线级 | 重启 | 降噪可能损伤语音细节，增加 CPU |
| `enable_realtime_transcription` | 启动 | 是 | advanced | 管线级 | 重启 | 渐进转写会增加 partial 事件与重复风险 |
| `realtime_processing_pause` | 启动 | 是 | advanced | 管线级 | 重启 | 间隔过小抬高算力占用 |
| `speculative_reopen_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 过大导致重复转写与重复气泡（本项目已设 0 规避） |
| `unanswered_reopen_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 与 Smart Turn 上限钳制；过大拖慢提交 |
| `short_segment_merge_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 开启会增加起播延迟以等待拼接 |
| `smart_turn` | 启动 | 是 | basic | 会话级 | 重启 | 关闭后退回纯静音判停，交互更"硬"但更可预测 |
| `smart_turn_model_path` | 启动 | 否 | ops | 管线级 | 重启 | **环境绑定**：容器内 ONNX 路径；缺省会联网下载 |
| `smart_turn_threshold` | 启动 | 是 | expert | 会话级 | 重启 | 越高越倾向等待，容易显得迟钝 |
| `smart_turn_max_wait_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 过大拖慢回答提交 |
| `smart_turn_incomplete_delay_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 在宽限窗口内运行；过大浪费窗口 |
| `smart_turn_cpu_count` | 启动 | 是 | advanced | 管线级 | 重启 | 线程过多与 Silero、CPU STT 争抢 |

### A7. 全局覆盖、设备与说话人分离（11）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `device` | 全局设备覆盖，强制所有 handler 使用同一设备 | `module_arguments.py:device` | `None` | `auto` / `cuda` / `mps` / `cpu` / `npu` | 否 | YAML `pipelines.<n>.options.device` > `{env}` > 默认 |
| `mac_optimal_settings` | macOS 预设包：Parakeet TDT + MLX LM + Qwen3-TTS + MPS | `module_arguments.py:mac_optimal_settings` | `false` | 布尔；显式字段优先于预设 | 否 | 同上 |
| `torch_num_threads` | 进程级 PyTorch intra-op 线程数 | `module_arguments.py:torch_num_threads` | `None`（由 Silero 加载时设为 1） | 正整数 | 否 | 同上 |
| `diarization` | 启用说话人分离（Nemotron 3 Diarization） | `module_arguments.py:diarization` | `false` | 布尔 | 否 | 同上 |
| `diarization_model_name` | 流式说话人分离 checkpoint | `module_arguments.py:diarization_model_name` | `None` | Hub ID 或本地路径 | 条件必填（`diarization=true`） | 同上 |
| `diarization_revision` | 分离模型 revision | `module_arguments.py:diarization_revision` | `None` | 字符串 | 否 | 同上 |
| `diarization_device` | 分离模型设备（受 `device` 覆盖） | `module_arguments.py:diarization_device` | `auto` | `auto` / `cuda` / `mps` / `cpu` | 否 | 同上 |
| `diarization_dtype` | 分离模型数值精度 | `module_arguments.py:diarization_dtype` | `float32` | `float32` / `float16` / `bfloat16` | 否 | 同上 |
| `diarization_streaming_mode` | 分离模型流式模式 | `module_arguments.py:diarization_streaming_mode` | `low_latency` | `low_latency` / `very_low_latency` / `ultra_low_latency` | 否 | 同上 |
| `diarization_threshold` | 说话人活动概率判定阈值 | `module_arguments.py:diarization_threshold` | `0.5` | 0–1 浮点 | 否 | 同上 |
| `detect_llm_output_language` | 逐块检测助手输出语言并传给 TTS | `module_arguments.py:detect_llm_output_language` | `false` | 布尔；检测器启动时预热 | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `device` | 启动 | 否 | ops | 进程级 | 重启 | **环境绑定**：强制单设备会击穿各组件的 `*_device` 意图，可能 OOM 或落到 CPU 使延迟翻倍 |
| `mac_optimal_settings` | 启动 | 否 | expert | 进程级 | 重启 | 仅在 macOS 成立；在 Linux 打开会尝试加载 MLX 而失败 |
| `torch_num_threads` | 启动 | 否 | advanced | 进程级 | 重启 | Silero 与 CPU STT 共用该值，调大加速 STT 但拖慢 Silero；不影响 ONNX/MLX |
| `diarization` | 启动 | 是 | advanced | 管线级 | 分钟级 | 额外模型显存；分离出错会把同一人拆成多说话人 |
| `diarization_model_name` | 启动 | 否 | expert | 管线级 | 分钟级 | 未设而开启 `diarization` 会启动失败 |
| `diarization_revision` | 启动 | 否 | expert | 管线级 | 分钟级 | 固定 revision 避免上游更新导致行为漂移 |
| `diarization_device` | 启动 | 否 | expert | 管线级 | 重启 | 与 STT/TTS 争抢显存 |
| `diarization_dtype` | 启动 | 否 | expert | 管线级 | 重启 | `float16` 在部分算子下精度下降，可能误判说话人 |
| `diarization_streaming_mode` | 启动 | 否 | expert | 管线级 | 重启 | 越低延迟越易把一句话切成多段 |
| `diarization_threshold` | 启动 | 否 | expert | 管线级 | 重启 | 过低把噪声当说话人、过高漏掉轻声轮次 |
| `detect_llm_output_language` | 启动 | 是 | advanced | 管线级 | 重启 | 首块过短时不下发语言码；多一次本地推理开销 |

### A8. 鉴权与安全（9）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `enable_llm_proxy` | 在 Realtime 服务上暴露 OpenAI 兼容 LLM 代理端点 | `module_arguments.py:enable_llm_proxy` | `false` | 布尔；仅 `supports_llm_proxy` 后端可用 | 否 | YAML `options.enable_llm_proxy` > 默认 |
| `responses_api_api_key` | OpenAI 兼容 LLM 的 bearer token | `responses_api_language_model_arguments.py` | `None` | 字符串（密钥） | 否 | 块 settings > `{env}` > 默认 |
| `openai_stt_api_key` | OpenAI 兼容 STT 的 bearer token | `openai_stt_arguments.py` | `None` | 字符串；未设时回退 `OPENAI_API_KEY` | 否 | 同上 |
| `openai_tts_api_key` | OpenAI 兼容 TTS 的 bearer token | `openai_tts_arguments.py` | `None` | 字符串；未设时回退 `OPENAI_API_KEY` | 否 | 同上 |
| `USAGE_HASH_SECRET` | 用量库中用户标识的 HMAC 密钥 | `demo/limiter.py:50` | 进程启动随机生成 | 非空字符串 | 否 | 环境变量（无 YAML 入口） |
| `UNLIMITED_ORGS` | 不计配额的 HF 组织白名单（逗号分隔） | `demo/auth.py:47` | `cerebras,huggingfacem4,smolagents,pollen-robotics` | 逗号分隔组织名 | 否 | 环境变量 |
| `AUTH_DEBUG` | 打开鉴权调试日志 | `demo/auth.py:89` | `false` | 任意非空值即开启 | 否 | 环境变量 |
| CORS 策略 | 演示服务未安装 `CORSMiddleware`，浏览器跨域默认被拒 | `demo/server.py` | 固定（无 CORS 头） | 无 | 固定 | 不可配置 |
| Realtime API 鉴权 | `/v1/realtime` 与 `/v1/pool`、`/v1/usage` 均不校验凭据 | `api/openai_realtime/websocket_router.py` | 固定（无鉴权） | 无 | 固定 | 不可配置 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `enable_llm_proxy` | 启动 | 否 | ops | 进程级 | 重启 | **安全**：源码明确「服务自身不做任何鉴权」，开启即把 LLM 额度暴露给任何可达客户端，只能在可信网络或网关后启用 |
| `responses_api_api_key` | 启动 | 否 | ops | 管线级 | 重启 | **安全**：平台只写不读，回显 `***`；泄漏等于泄漏上游额度 |
| `openai_stt_api_key` | 启动 | 否 | ops | 管线级 | 重启 | **安全**：同上；并注意隐式回退 `OPENAI_API_KEY` 会让「未配置」看起来像「已配置」 |
| `openai_tts_api_key` | 启动 | 否 | ops | 管线级 | 重启 | **安全**：同上 |
| `USAGE_HASH_SECRET` | 启动 | 否 | ops | 进程级 | 重启 | **安全**：不显式设置则每次重启换密钥，历史 `user_key` 全部失配、配额记录失效 |
| `UNLIMITED_ORGS` | 启动 | 否 | ops | 进程级 | 重启 | **安全**：白名单组织绕开全部配额，误加等于开放无限用量 |
| `AUTH_DEBUG` | 启动 | 否 | ops | 进程级 | 重启 | **隐私**：调试日志可能落盘用户身份信息 |
| CORS 策略 | 固定 | 否 | ops | 进程级 | 无 | 固定行为：跨域前端需与 API 同源或由反代补 CORS 头 |
| Realtime API 鉴权 | 固定 | 否 | ops | 进程级 | 无 | **安全**：无鉴权意味着任何拿到 `host:port` 的人都能开会话、读 `/v1/pool`；平台必须在反代层加 token 与网络隔离 |

### A9. 日志与监控（8）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `log_level` | 应用日志级别 | `module_arguments.py:log_level` | `info` | `debug` / `info` / `warning` / `error` 等 logging 级别 | 否 | YAML `runtime.log_level` > `{env}` > 默认 |
| `log_transcripts` | 把用户与助手的完整转写文本写入应用日志 | `module_arguments.py:log_transcripts` | `false` | 布尔 | 否 | 同上 |
| `enable_live_transcription` | 用户说话过程中实时显示转写（配合 parakeet-tdt） | `module_arguments.py:enable_live_transcription` | `true` | 布尔 | 否 | 同上 |
| `live_transcription_update_interval` | 实时转写的刷新间隔 | `module_arguments.py:live_transcription_update_interval` | `0.5` | 正浮点（秒） | 否 | 同上 |
| `MODEL_METRICS_LOG` | 模型调用指标 JSONL 落盘路径 | `utils/model_monitor.py:50` | `model_metrics.log` | 路径字符串 | 否 | 环境变量（无 YAML 入口） |
| `MODEL_METRICS_LOG_MAX_BYTES` | 指标日志单文件上限 | `utils/model_monitor.py:51` | `20971520`（20 MiB） | 正整数（字节） | 否 | 环境变量 |
| `MODEL_METRICS_LOG_BACKUPS` | 指标日志滚动保留份数 | `utils/model_monitor.py:52` | `5` | 非负整数 | 否 | 环境变量 |
| 监控端点 | `GET /v1/pool` 返回 `{size, in_use, units}`；`GET /v1/usage` 返回用量累计 | `api/openai_realtime/websocket_router.py:615,639` | 固定可用 | 只读 JSON | 固定 | 不可配置 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `log_level` | 启动 | 是 | advanced | 进程级 | 重启 | `debug` 会显著抬高 I/O 与日志体积，生产建议 `info` |
| `log_transcripts` | 启动 | 否 | ops | 进程级 | 重启 | **隐私**：源码明确警告日志常被容器与聚合器长期保留，对话内容会比会话活得更久；默认关闭，开启前必须确认留存合规 |
| `enable_live_transcription` | 启动 | 是 | basic | 管线级 | 重启 | 开启会产生大量 partial 事件，弱网下抬高带宽 |
| `live_transcription_update_interval` | 启动 | 是 | advanced | 管线级 | 重启 | 间隔过小抬高 CPU 与事件量 |
| `MODEL_METRICS_LOG` | 启动 | 否 | ops | 进程级 | 重启 | **环境绑定**：容器内相对路径落在工作目录，未挂卷则随容器销毁丢失 |
| `MODEL_METRICS_LOG_MAX_BYTES` | 启动 | 否 | ops | 进程级 | 重启 | 过小导致高频滚动，过大占满磁盘 |
| `MODEL_METRICS_LOG_BACKUPS` | 启动 | 否 | ops | 进程级 | 重启 | 份数 × 单文件上限 = 磁盘占用上限，需与卷容量匹配 |
| 监控端点 | 固定 | 否 | advanced | 进程级 | 无 | 平台健康检查与回滚判定复用这两个端点；池状态含 `stuck` 单元可识别卡死管线 |

### A10. 环境变量（12）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `HF_HUB_OFFLINE` | 强制 HuggingFace Hub 完全离线 | `docker-compose.yml`（pipeline.environment） | `1`（本仓 compose 已设） | `0` / `1` | 否 | 环境变量 |
| `TRANSFORMERS_OFFLINE` | 强制 transformers 不联网 | `docker-compose.yml` | `1`（本仓 compose 已设） | `0` / `1` | 否 | 环境变量 |
| `TOKENIZERS_PARALLELISM` | 关闭 tokenizer 并行 fork 警告与开销 | `docker-compose.yml` | `false` | `true` / `false` | 否 | 环境变量 |
| `HF_ENDPOINT` | HuggingFace Hub 镜像源 | `docker-compose.gpustack.yml` | `https://hf-mirror.com` | URL | 否 | 环境变量 |
| `HF_HUB_ENABLE_PROGRESS_BARS` | 关闭下载进度条（避免日志噪声） | `docker-compose.gpustack.yml` | `false` | `true` / `false` | 否 | 环境变量 |
| `MODELSCOPE_ENDPOINT` | ModelScope 镜像源 | `docker-compose.gpustack.yml` | `https://modelscope.cn` | URL | 否 | 环境变量 |
| `GPUSTACK_BASE_URL` | GPUStack OpenAI 兼容网关地址 | `.env.gpustack.example` → compose `--responses_api_base_url` | `http://192.168.40.30/v1-openai` | URL（含 `/v1...`） | 否 | `.env` / shell 环境 |
| `GPUSTACK_MODEL` | GPUStack 上的模型名 | `.env.gpustack.example` → `--model_name` | `Qwen3-8B` | 字符串；须与网关注册名一致 | 否 | 同上 |
| `GPUSTACK_API_KEY` | GPUStack 网关密钥 | `.env.gpustack.example` → `--responses_api_api_key` | `not-needed` | 字符串（密钥） | 否 | 同上 |
| `SERPER_API_KEY` | 演示服务的 Web 搜索工具密钥 | `demo/server.py` | `None`（未设则工具不可用） | 字符串（密钥） | 否 | 环境变量 |
| `RTC_ICE_SERVERS` | 浏览器 WebRTC 的 ICE 服务器 JSON | `demo/server.py` | `None`（仅 STUN 默认） | JSON 数组字符串 | 否 | 环境变量 |
| `OPENAI_API_KEY` | OpenAI 兼容 STT/TTS 的隐式密钥回退 | `STT/openai_compatible_handler.py`、TTS 同构 | `None` | 字符串（密钥） | 否 | 环境变量（优先级低于显式 `*_api_key`） |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `HF_HUB_OFFLINE` | 启动 | 否 | ops | 容器级 | 分钟级 | **环境绑定**：置 1 后未缓存的权重直接失败；缓存不全时报 `LocalEntryNotFound` |
| `TRANSFORMERS_OFFLINE` | 启动 | 否 | ops | 容器级 | 分钟级 | 同上 |
| `TOKENIZERS_PARALLELISM` | 启动 | 否 | ops | 容器级 | 分钟级 | 仅影响警告与 fork 行为，无功能风险 |
| `HF_ENDPOINT` | 启动 | 否 | ops | 容器级 | 分钟级 | **环境绑定**：镜像站不可达时下载卡住；与离线变量互斥优先 |
| `HF_HUB_ENABLE_PROGRESS_BARS` | 启动 | 否 | ops | 容器级 | 分钟级 | 纯日志噪声控制 |
| `MODELSCOPE_ENDPOINT` | 启动 | 否 | ops | 容器级 | 分钟级 | 同上，仅影响 ModelScope 拉取 |
| `GPUSTACK_BASE_URL` | 启动 | 否 | ops | 管线级 | 重启 | **环境绑定**：错地址则首轮回复直接报错；平台应先用 `/v1/models` 探活 |
| `GPUSTACK_MODEL` | 启动 | 是 | expert | 管线级 | 重启 | 名称与网关注册名不匹配会 404 |
| `GPUSTACK_API_KEY` | 启动 | 否 | ops | 管线级 | 重启 | **安全**：写入 `.env` 后必须限制文件权限，不得入仓 |
| `SERPER_API_KEY` | 启动 | 否 | ops | 进程级 | 重启 | **安全**：泄漏等于泄漏搜索额度 |
| `RTC_ICE_SERVERS` | 启动 | 否 | ops | 进程级 | 重启 | **环境绑定**：NAT/防火墙下需自建 TURN，否则浏览器端连不通 |
| `OPENAI_API_KEY` | 启动 | 否 | ops | 管线级 | 重启 | **安全**：全局变量会隐式影响多个后端，平台应避免依赖它，改用显式 `*_api_key` |

### A11. 配置文件约束（6）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `schema_version` | YAML 配置版本号 | `config.py:375` | 必须为 `1` | 整数，仅接受 `1` | 是（使用 YAML 时） | 文件顶层字段 |
| 顶层结构 | 只允许 `schema_version` / `runtime` / `blocks` / `pipelines` 四个键 | `config.py:374` | — | 映射；未知键报错 | 是 | 文件结构 |
| `{env: NAME}` 引用 | 标量位置插入环境变量 | `config.py` | — | 仅标量；缺失即报错，**不回退默认** | 否 | 低于显式值、高于 dataclass 默认 |
| 路径字段解析 | `_PATH_FIELDS` 中的路径做 `~` 展开与「相对 YAML 目录」解析 | `config.py:_PATH_FIELDS` | — | 路径字符串 | 否 | 解析阶段 |
| 文件体积上限 | 单文件最大字节数 | `_config_yaml.py:13` | `1048576`（1 MiB） | 硬编码 | 固定 | 不可配置 |
| 嵌套深度上限 | 容器嵌套最大层数 | `_config_yaml.py:14` | `32` | 硬编码 | 固定 | 不可配置 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `schema_version` | 启动 | 否 | ops | 容器级 | 分钟级 | 写错直接拒启；平台模板应固定写入 `1` |
| 顶层结构 | 启动 | 否 | ops | 容器级 | 分钟级 | 多余键被拒（无向前兼容），平台模板需严格对齐 |
| `{env: NAME}` 引用 | 启动 | 是 | advanced | 容器级 | 重启 | 引用不存在的变量不会回退默认而是报错，这是「密钥不进仓」的主要手段 |
| 路径字段解析 | 启动 | 是 | advanced | 容器级 | 重启 | 容器内路径必须用绝对路径；相对路径按 YAML 所在目录解析易错 |
| 文件体积上限 | 固定 | 否 | ops | 容器级 | 无 | 超过 1 MiB 直接拒读；模板体积远低于此 |
| 嵌套深度上限 | 固定 | 否 | ops | 容器级 | 无 | 超 32 层拒绝；平台生成器不应生成深层嵌套 |

> anchors / aliases / merge keys / explicit tags 全部禁用，YAML 必须展开书写；详见 [`configuration.md`](./configuration.md)。

### A12. 容器化部署（9）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `DOCKERFILE`（build arg） | 选择镜像变体 | `docker-compose.yml:${DOCKERFILE:-Dockerfile}` | `Dockerfile` | `Dockerfile` / `Dockerfile.cu130` / `Dockerfile.baked` 等 | 否 | `.env` > 默认 |
| `BASE_IMAGE`（build arg） | 基础镜像 | `Dockerfile:ARG BASE_IMAGE` | `ccr.ccs.tencentyun.com/llm-basic/python-torch:cu128` | 镜像地址；cu128 需驱动 <13.0，cu130 需 >=580 | 否 | 构建参数 |
| `PIPELINE_PORT`（host 侧） | 宿主侧端口映射 | `docker-compose.gpustack.yml:${PIPELINE_PORT:-8765}:8765/tcp` | `8765` | 1–65535 | 否 | `.env` > 默认 |
| `PIPELINE_GPU_ID`（host 侧） | 绑定到哪张 GPU | `docker-compose.gpustack.yml:device_ids: ['${PIPELINE_GPU_ID:-1}']` | `1`（gpustack 变体；主 compose 写死 `'0'`） | GPU 序号字符串 | 否 | `.env` > 默认 |
| GPU 能力声明 | `deploy.resources.reservations.devices.capabilities: [gpu]` | `docker-compose.yml` | 固定声明 | — | 固定 | 不可配置 |
| 权重/缓存卷 | `./cache/` 挂到 `/root/.cache/` | `docker-compose.yml` | 固定挂载 | 宿主相对路径 | 固定 | 不可配置 |
| Silero VAD 卷 | `../.silero-dl2/silero-vad-master` 只读挂到 `/opt/silero-vad` | `docker-compose.yml` | 固定挂载（主 compose） | 宿主相对路径 | 固定 | 不可配置 |
| 重启策略 | 容器异常退出自动拉起 | `docker-compose.gpustack.yml:restart: unless-stopped` | `unless-stopped` | compose 重启策略枚举 | 否 | 编排文件 |
| 健康检查 | compose 未定义 `healthcheck`，探活靠 `GET /v1/pool` | `docker-compose*.yml`、`websocket_router.py:639` | 无 `healthcheck` | — | 固定 | 不可配置 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `DOCKERFILE` | 容器 | 否 | ops | 容器级 | 分钟级 | **环境绑定**：变体自带不同 CUDA 基线，选错则容器启动报驱动不匹配 |
| `BASE_IMAGE` | 容器 | 否 | ops | 容器级 | 分钟级 | **环境绑定**：与宿主驱动强耦合；镜像拉取需内网可达 |
| `PIPELINE_PORT` | 容器 | 否 | ops | 容器级 | 分钟级 | **环境绑定**：只改宿主侧，容器内仍固定 `8765`；必须与 `--port` 一致对 |
| `PIPELINE_GPU_ID` | 容器 | 否 | ops | 容器级 | 分钟级 | **环境绑定**：改错会用错卡或看不到 GPU；与 `num_pipelines` 的显存预算共同决定上限 |
| GPU 能力声明 | 固定 | 否 | ops | 容器级 | 无 | 无 GPU 预留时 pipeline 会退到 CPU，实时性不保 |
| 权重/缓存卷 | 固定 | 否 | ops | 容器级 | 无 | **环境绑定**：不挂卷则每次重建重下权重；卷权限需与容器 UID 匹配 |
| Silero VAD 卷 | 固定 | 否 | ops | 容器级 | 无 | **环境绑定**：缺该卷则回退联网下载，离线环境下启动挂掉 |
| 重启策略 | 容器 | 否 | ops | 容器级 | 分钟级 | 平台回滚与自动拉起存在竞争，建议平台接管后固定为 `no` |
| 健康检查 | 固定 | 否 | advanced | 容器级 | 无 | 无 `healthcheck` 意味着 compose 不知道服务是否真就绪，平台必须自己探 `/v1/pool` |

### A13. 客户端（18）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `url` | Realtime WebSocket 地址 | `audio_client.py:RealtimeAudioClientConfig.url` | `ws://127.0.0.1:8765/v1/realtime` | `ws://` 或 `wss://` URL | 是 | `runtime.client` > `{env}` > 默认 |
| `model` | 会话模型名（`session.update` 字段） | 同上 `.model` | `local` | 字符串；可被后端忽略 | 否 | 同上 |
| `api_key` | 连接凭据 | 同上 `.api_key` | `None` | 字符串（密钥） | 否 | 同上 |
| `send_rate` | 上行采样率 | 同上 `.send_rate` | `16000` | 正整数（Hz） | 否 | 同上 |
| `recv_rate` | 下行采样率 | 同上 `.recv_rate` | `16000` | 正整数（Hz） | 否 | 同上 |
| `playback_buffer_ms` | 播放前启动缓冲 | 同上 `.playback_buffer_ms`（`_PLAYBACK_START_BUFFER_MS`） | `0.0` | 有限非负数（毫秒）；构造时校验 | 否 | 同上 |
| `chunk_size` | 收发块大小（采样点） | 同上 `.chunk_size` | `1024` | 正整数 | 否 | 同上 |
| `input_device` | 声卡输入设备索引 | 同上 `.input_device` | `None`（系统默认） | 整数设备索引 | 否 | 同上 |
| `output_device` | 声卡输出设备索引 | 同上 `.output_device` | `None`（系统默认） | 整数设备索引 | 否 | 同上 |
| `instructions` | 会话首帧系统提示词 | 同上 `.instructions` | `None`（使用服务端默认） | 字符串 | 否 | 同上 |
| `voice` | 会话音色（`session.update`） | 同上 `.voice` | `None`（使用服务端默认） | 字符串；枚举由后端决定 | 否 | 同上 |
| `print_json` | 打印收到的原始 Realtime 事件 | 同上 `.print_json` | `false` | 布尔 | 否 | 同上 |
| `block_mic_during_playback` | 播放时暂停麦克风（关闭可保 barge-in） | 同上 `.block_mic_during_playback` | `false` | 布尔 | 否 | 同上 |
| `log_transcripts` | 客户端侧转写日志 | 同上 `.log_transcripts` | `false` | 布尔 | 否 | 同上 |
| `connection_retry_timeout_s` | 断线重连窗口 | 同上 `.connection_retry_timeout_s` | `30.0` | 正浮点（秒） | 否 | 同上 |
| `tools` | 可调用工具声明列表 | 同上 `.tools` | `[]` | JSON Schema 数组 | 否 | 代码传入 |
| `tool_executor` | 工具执行回调 | 同上 `.tool_executor` | `None` | Python 可调用对象 | 否 | 代码传入（不可 YAML 化） |
| `tool_response_create` | 工具结果是否触发新一轮回复 | 同上 `.tool_response_create` | `true` | 布尔 | 否 | 代码传入 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `url` | 启动 | 是 | advanced | 会话级 | 重启 | 地址与 `host`/端口映射不匹配会一直连不上；公网需 `wss://` |
| `model` | 启动+热更新 | 是 | basic | 会话级 | 秒级 | 本地后端可能忽略该值，改它无效果 |
| `api_key` | 启动 | 否 | ops | 会话级 | 重启 | **安全**：明文存于配置/命令行进程表 |
| `send_rate` | 启动 | 是 | advanced | 会话级 | 重启 | 与声卡能力不符会多次重采样 |
| `recv_rate` | 启动 | 是 | advanced | 会话级 | 重启 | 与服务端输出采样率不符会变调 |
| `playback_buffer_ms` | 启动 | 是 | advanced | 会话级 | 重启 | 过大首音迟、过小 underrun 爆音 |
| `chunk_size` | 启动 | 是 | advanced | 会话级 | 重启 | 过小抬高回调频率，过大抬高延迟 |
| `input_device` | 启动 | 是 | advanced | 会话级 | 重启 | **环境绑定**：设备索引在不同主机不同，容器内通常不可用 |
| `output_device` | 启动 | 是 | advanced | 会话级 | 重启 | 同上 |
| `instructions` | 热更新 | 是 | basic | 会话级 | 秒级 | 覆盖服务端 `init_chat_prompt`；过长抬高首 token 延迟 |
| `voice` | 热更新 | 是 | basic | 会话级 | 秒级 | 音色名由 TTS 后端决定，错名会导致合成失败或回退 |
| `print_json` | 启动 | 否 | expert | 会话级 | 重启 | 大量事件打印会拖慢终端 |
| `block_mic_during_playback` | 启动 | 是 | advanced | 会话级 | 重启 | 打开会失去 barge-in（打断）能力 |
| `log_transcripts` | 启动 | 否 | ops | 会话级 | 重启 | **隐私**：客户端也会留存对话文本 |
| `connection_retry_timeout_s` | 启动 | 是 | advanced | 会话级 | 重启 | 过短在弱网下直接放弃 |
| `tools` | 启动 | 是 | expert | 会话级 | 重启 | 工具描述错误会导致模型乱调或拒调 |
| `tool_executor` | 启动 | 否 | ops | 会话级 | 重启 | 执行任意本地逻辑，平台不应接受用户提交可执行回调 |
| `tool_response_create` | 启动 | 是 | advanced | 会话级 | 重启 | 关掉后工具结果不回灌，模型看不到执行结果 |

---

## B 层：后端专属参数

B 层不重复 A 层的通用字段（`device` / `num_pipelines` / `log_level` 等），只列各后端自己的 `settings` 字段。
参数名前缀就是 YAML 中的字段名，例如 `qwen3_asr_model_name` 属于 `blocks.stt.settings`。

### B0. 后端总览

| stage | 后端名 | arguments 文件 | 字段数 | 本文章节 |
|---|---|---|---|---|
| stt | `parakeet-tdt` | `parakeet_tdt_arguments.py` | 3 | 深挖 B1.1 |
| stt | `qwen3-asr` | `qwen3_asr_stt_arguments.py` | 6 | 深挖 B1.2 |
| stt | `openai_compatible` | `openai_stt_arguments.py` | 7 | 深挖 B1.3 |
| llm | `transformers` | `language_model_arguments.py` | 9 | 深挖 B2.1 |
| llm | `responses-api` | `responses_api_language_model_arguments.py` | 10 | 深挖 B2.2 |
| llm | `chat-completions` | `chat_completions_language_model_arguments.py` | 1（+ 继承 10） | 深挖 B2.3 |
| tts | `qwen3` | `qwen3_tts_arguments.py` | 23 | 深挖 B3.1 |
| tts | `openai_compatible` | `openai_tts_arguments.py` | 13 | 深挖 B3.2 |
| tts | `kokoro` | `kokoro_tts_arguments.py` | 6 | 深挖 B3.3 |
| 其余 | 19 个后端 | 见 B4 表 | — | 目录化 B4 |

> 可用枚举以 `backend_registry.py` 的 `STT_BACKENDS` / `LLM_BACKENDS` / `TTS_BACKENDS` 为准；YAML `backend:` 取值不在枚举内会直接报错。

### B1. STT 深挖

#### B1.1 `parakeet-tdt`（NVIDIA Parakeet TDT，默认 STT）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `parakeet_tdt_model_name` | 模型 ID 或本地路径 | `parakeet_tdt_arguments.py:15` | `None`（由 handler 内置默认） | 字符串 | 否 | `settings` > `{env}` > 默认 |
| `parakeet_tdt_device` | 运行设备 | `parakeet_tdt_arguments.py:22` | `auto` | `auto` / `cuda` / `cpu` 等 | 否 | 同上 |
| `parakeet_tdt_language` | 识别语言提示 | `parakeet_tdt_arguments.py:29` | `None` | 语言码字符串 | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `parakeet_tdt_model_name` | 启动 | 是 | expert | 管线级 | 分钟级 | 换模型需重下权重；本地路径写错启动失败 |
| `parakeet_tdt_device` | 启动 | 否 | expert | 管线级 | 重启 | 与 TTS 争抢显存 |
| `parakeet_tdt_language` | 启动 | 是 | advanced | 管线级 | 重启 | 语言提示与音频不符会降低准确率 |

> 本后端是 `enable_live_transcription` 的推荐搭配；它无独立采样率参数，固定跟随 `PIPELINE_SAMPLE_RATE=16000`。

#### B1.2 `qwen3-asr`（本地 Qwen3-ASR，本仓 compose 在用）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `qwen3_asr_model_name` | 模型 ID 或本地目录 | `qwen3_asr_stt_arguments.py:7` | `Qwen/Qwen3-ASR-0.6B-hf` | 字符串 | 否 | `settings` > `{env}` > 默认 |
| `qwen3_asr_device` | 运行设备 | `qwen3_asr_stt_arguments.py:17` | `auto` | `auto` / `cuda` / `cpu` | 否 | 同上 |
| `qwen3_asr_torch_dtype` | 推理精度 | `qwen3_asr_stt_arguments.py:23` | `auto` | `auto` / `float16` / `bfloat16` / `float32` | 否 | 同上 |
| `qwen3_asr_language` | 识别语言 | `qwen3_asr_stt_arguments.py:32` | `auto` | 语言码或 `auto` | 否 | 同上 |
| `qwen3_asr_prompt` | 识别提示词（热词/标点） | `qwen3_asr_stt_arguments.py:42` | `None` | 字符串 | 否 | 同上 |
| `qwen3_asr_gen_max_new_tokens` | 单段最大生成 token | `qwen3_asr_stt_arguments.py:51` | `256` | 正整数 | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `qwen3_asr_model_name` | 启动 | 是 | expert | 管线级 | 分钟级 | 容器内建议用绝对路径（如 `/root/.cache/qwen3-asr-model-hf`） |
| `qwen3_asr_device` | 启动 | 否 | expert | 管线级 | 重启 | `auto` 在无 GPU 环境下会落到 CPU，RTF 大幅上升 |
| `qwen3_asr_torch_dtype` | 启动 | 否 | expert | 管线级 | 重启 | `float32` 显存翻倍 |
| `qwen3_asr_language` | 启动 | 是 | basic | 会话级 | 重启 | `auto` 在短句上可能误判；可被 `session.update` 的转录语言约束 |
| `qwen3_asr_prompt` | 启动 | 是 | advanced | 管线级 | 重启 | 提示词过长抬高每段延迟 |
| `qwen3_asr_gen_max_new_tokens` | 启动 | 是 | advanced | 管线级 | 重启 | 过小截断长句转写 |

#### B1.3 `openai_compatible`（远端 OpenAI 兼容 STT）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `openai_stt_base_url` | 服务地址（含 `/v1`） | `openai_stt_arguments.py:9` | `http://localhost:8000/v1` | URL | 是 | `settings` > `{env}` > 默认 |
| `openai_stt_api_key` | Bearer token | `openai_stt_arguments.py:13` | `None`（回退 `OPENAI_API_KEY`） | 字符串（密钥） | 否 | 同上 |
| `openai_stt_model` | 请求中的 model 名 | `openai_stt_arguments.py:20` | `nvidia/parakeet-tdt-0.6b-v3` | 字符串 | 否 | 同上 |
| `openai_stt_language` | 识别语言 | `openai_stt_arguments.py:27` | `None` | 语言码 | 否 | 同上 |
| `openai_stt_response_format` | 响应格式 | `openai_stt_arguments.py:31` | `json` | 服务支持的格式（如 `json` / `text`） | 否 | 同上 |
| `openai_stt_timeout` | HTTP 超时 | `openai_stt_arguments.py:35` | `60.0` | 正浮点（秒） | 否 | 同上 |
| `openai_stt_max_window_s` | 单次请求最长音频窗口 | `openai_stt_arguments.py:39` | `None`（不切窗） | 正浮点（秒） | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `openai_stt_base_url` | 启动 | 是 | advanced | 管线级 | 重启 | **环境绑定**：错地址每轮都报错；建议平台先探 `/v1/models` |
| `openai_stt_api_key` | 启动 | 否 | ops | 管线级 | 重启 | **安全**：隐式回退 `OPENAI_API_KEY` 会让未配置看似已配置 |
| `openai_stt_model` | 启动 | 是 | expert | 管线级 | 重启 | 名称须与远端注册名完全一致 |
| `openai_stt_language` | 启动 | 是 | basic | 会话级 | 重启 | 与音频不符会降低准确率 |
| `openai_stt_response_format` | 启动 | 否 | expert | 管线级 | 重启 | 不支持的格式会解析失败 |
| `openai_stt_timeout` | 启动 | 是 | expert | 管线级 | 重启 | 过小截断长语音，过大在远端故障时拖住会话 |
| `openai_stt_max_window_s` | 启动 | 是 | advanced | 管线级 | 重启 | 设置后长段会被切窗请求，增加请求数与拼接复杂度 |

### B2. LLM 深挖

#### B2.1 `transformers`（本地 transformers，非 macOS 默认）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `llm_device` | 推理设备 | `language_model_arguments.py:10` | `auto`（MLX 后端为 `mps`） | `auto` / `cuda` / `cpu` / `mps` | 否 | `settings` > `{env}` > 默认 |
| `llm_torch_dtype` | 模型与张量精度 | `language_model_arguments.py:14` | `float16` | `float32` / `float16` / `bfloat16` | 否 | 同上 |
| `llm_load_in_8bit` | bitsandbytes 8bit 量化加载 | `language_model_arguments.py:20` | `false` | 布尔 | 否 | 同上 |
| `llm_load_in_4bit` | bitsandbytes 4bit（NF4）量化，覆盖 8bit | `language_model_arguments.py:27` | `false` | 布尔 | 否 | 同上 |
| `llm_gen_max_new_tokens` | 单次生成最大 token | `language_model_arguments.py:34` | `1024` | 正整数 | 否 | 同上 |
| `llm_gen_min_new_tokens` | 单次生成最小 token | `language_model_arguments.py:38` | `0` | 非负整数 | 否 | 同上 |
| `llm_gen_temperature` | 采样温度 | `language_model_arguments.py:42` | `0.0` | 浮点；`0.0` 为确定性 | 否 | 同上 |
| `llm_gen_do_sample` | 是否启用采样 | `language_model_arguments.py:48` | `false` | 布尔 | 否 | 同上 |
| `llm_is_vlm` | 按视觉语言模型加载（AutoProcessor） | `language_model_arguments.py:52` | `false` | 布尔 | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `llm_device` | 启动 | 否 | expert | 管线级 | 重启 | 落 CPU 时首 token 延迟可达秒级 |
| `llm_torch_dtype` | 启动 | 否 | expert | 管线级 | 重启 | `float32` 显存翻倍，容易 OOM |
| `llm_load_in_8bit` | 启动 | 是 | expert | 管线级 | 分钟级 | 需 bitsandbytes 与 CUDA 兼容；4B 模型显存 ~8GB → ~4GB |
| `llm_load_in_4bit` | 启动 | 是 | expert | 管线级 | 分钟级 | 显存降至 ~2.1GB，有小幅质量损失；优先级高于 8bit |
| `llm_gen_max_new_tokens` | 启动 | 是 | advanced | 会话级 | 重启 | 过大使长回答占满实例并抬高 KV 显存 |
| `llm_gen_min_new_tokens` | 启动 | 是 | advanced | 会话级 | 重启 | 非 0 会强制模型不说短句 |
| `llm_gen_temperature` | 启动 | 是 | basic | 会话级 | 重启 | 与 `llm_gen_do_sample` 联动；采样关闭时温度无效 |
| `llm_gen_do_sample` | 启动 | 是 | basic | 会话级 | 重启 | 开采样后同一输入不再稳定复现 |
| `llm_is_vlm` | 启动 | 否 | expert | 管线级 | 分钟级 | 用文本模型打开会加载失败 |

#### B2.2 `responses-api`（OpenAI Responses API 兼容）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `model_name` | 模型名（覆写基类默认） | `responses_api_language_model_arguments.py:9` | `gpt-5.6-terra`（基类为 `Qwen/Qwen3.5-4B`） | 字符串 | 否 | `settings` > `{env}` > 默认 |
| `responses_api_api_key` | bearer token | 同文件`:16` | `None` | 字符串（密钥） | 否 | 同上 |
| `responses_api_base_url` | 服务地址 | 同文件`:20` | `None`（回退官方 OpenAI） | URL | 否 | 同上 |
| `responses_api_stream` | 流式返回 | 同文件`:24` | `true` | 布尔 | 否 | 同上 |
| `responses_api_disable_thinking` | 禁用服务端推理 | 同文件`:31` | `true` | 布尔；对兼容后端发 `chat_template_kwargs.enable_thinking=false` | 否 | 同上 |
| `responses_api_reasoning_effort` | 推理强度 | 同文件`:38` | `none` | `none` / `low` / `medium` / `high` 等 | 否 | 同上 |
| `responses_api_audio_max_tokens` | 音频输入请求的最大 token | 同文件`:46` | `256` | 正整数 | 否 | 同上 |
| `responses_api_audio_temperature` | 音频输入请求的温度 | 同文件`:50` | `0.0` | 浮点 | 否 | 同上 |
| `responses_api_audio_content_type` | 音频内容编码方式 | 同文件`:54` | `input_audio` | `input_audio`（WAV base64）/ `audio_url`（data URL） | 否 | 同上 |
| `responses_api_audio_history_turns` | 历史中保留的音频轮数 | 同文件`:61` | `1` | 非负整数；`0` = 全部替换为占位 | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `model_name` | 启动 | 是 | expert | 管线级 | 分钟级 | 默认 `gpt-5.6-terra` **不支持音频输入**；`stt=none` 时必须显式换成支持音频的模型 |
| `responses_api_api_key` | 启动 | 否 | ops | 管线级 | 重启 | **安全**：只写不读，平台回显 `***` |
| `responses_api_base_url` | 启动 | 是 | advanced | 管线级 | 重启 | **环境绑定**：留空会打向公网官方 API，内网部署必须显式配置 |
| `responses_api_stream` | 启动 | 是 | advanced | 会话级 | 重启 | 关闭后首音延迟显著变长 |
| `responses_api_disable_thinking` | 启动 | 是 | advanced | 管线级 | 重启 | 部分提供商忽略该参数（需配合 `reasoning_effort`） |
| `responses_api_reasoning_effort` | 启动 | 是 | advanced | 管线级 | 重启 | 非 `none` 会明显抬高首 token 延迟 |
| `responses_api_audio_max_tokens` | 启动 | 是 | advanced | 会话级 | 重启 | 仅音频输入 LLM（`stt=none`）生效 |
| `responses_api_audio_temperature` | 启动 | 是 | advanced | 会话级 | 重启 | 同上 |
| `responses_api_audio_content_type` | 启动 | 否 | expert | 管线级 | 重启 | 提供商只接其中一种，选错报 400 |
| `responses_api_audio_history_turns` | 启动 | 是 | advanced | 会话级 | 重启 | 保留越多音频，上下文 token 越高 |

#### B2.3 `chat-completions`（Chat Completions 兼容，本仓 compose 在用）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `responses_api_reasoning_effort` | 推理强度（覆写默认，改为不发送） | `chat_completions_language_model_arguments.py:21` | `None` | 字符串或 `None`；作为 `extra_body.reasoning_effort` 下发 | 否 | `settings` > `{env}` > 默认 |
| 其余 10 个字段 | 完全继承 B2.2 | `responses_api_language_model_arguments.py` | 同 B2.2（`model_name` 同） | — | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `responses_api_reasoning_effort` | 启动 | 是 | advanced | 管线级 | 重启 | 为 `None` 时回退到 `disable_thinking` 行为（`enable_thinking=false`） |
| 其余 10 个字段 | — | — | — | — | — | 语义与风险同 B2.2；本后端下 `responses_api_stream` 控制 chat completions 的流式 |

> 本仓 `docker-compose.yml` 通过 `--responses_api_base_url` / `--responses_api_api_key` / `--responses_api_stream` / `--responses_api_reasoning_effort ""` 驱动 chat-completions 后端，字段名沿用 `responses_api_*` 前缀是预期行为，不是配置错误。

### B3. TTS 深挖

#### B3.1 `qwen3`（Qwen3-TTS，默认 TTS，本仓 compose 在用）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `qwen3_tts_model_name` | 模型 ID 或本地路径 | `qwen3_tts_arguments.py:7` | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | 字符串；Apple Silicon 自动映射 MLX 变体 | 否 | `settings` > `{env}` > 默认 |
| `qwen3_tts_device` | torch 后端设备 | `:13` | `cuda` | `cuda` / `auto` | 否 | 同上 |
| `qwen3_tts_dtype` | 推理精度 | `:19` | `auto` | `auto` / `float16` / `bfloat16` / `float32` | 否 | 同上 |
| `qwen3_tts_attn_implementation` | 注意力实现 | `:25` | `eager` | `eager` / `flash_attention_2` / `sdpa` | 否 | 同上 |
| `qwen3_tts_backend` | faster-qwen3-tts 后端 | `:31` | `ggml` | `ggml` / `torch`（Apple Silicon 忽略，走 mlx-audio） | 否 | 同上 |
| `qwen3_tts_ggml_quantization` | GGUF 量化级别 | `:37` | `BF16` | `BF16` / `Q8_0` / `Q4_K_M` / `F32` | 否 | 同上 |
| `qwen3_tts_gguf_talker_path` | 本地 talker GGUF 路径 | `:43` | `None` | 路径；需与 `codec` 同时提供且 `backend=ggml` | 否 | 同上 |
| `qwen3_tts_gguf_codec_path` | 本地 codec GGUF 路径 | `:49` | `None` | 同上 | 否 | 同上 |
| `qwen3_tts_ref_cache_dir` | 自动缓存的音色参考目录 | `:55` | `None`（用后端默认缓存） | 路径 | 否 | 同上 |
| `qwen3_tts_ref_audio` | 音色克隆参考音频 | `:61` | `None` | 路径；CustomVoice 模型留空 | 否 | 同上 |
| `qwen3_tts_ref_spk` | 预计算 `.spk` 说话人向量 | `:67` | `None` | 路径；与 `ref_audio` 互斥 | 否 | 同上 |
| `qwen3_tts_ref_rvq` | 预计算 `.rvq` 声学码 | `:73` | `None` | 路径；需 `ref_spk` + `ref_text` | 否 | 同上 |
| `qwen3_tts_ref_text` | 参考音频的转写文本 | `:79` | 内置一段英文示例文本 | 字符串 | 否 | 同上 |
| `qwen3_tts_speaker` | CustomVoice 音色名 | `:83` | `Aiden` | 后端支持的音色名 | 否 | 同上 |
| `qwen3_tts_instruct` | VoiceDesign 指令文本 | `:89` | `None` | 字符串（VoiceDesign 模型必填） | 否 | 同上 |
| `qwen3_tts_xvec_only` | 仅用 x-vector 克隆（起步更干净） | `:93` | `false` | 布尔 | 否 | 同上 |
| `qwen3_tts_parity_mode` | 关闭 CUDA graph 流式路径 | `:99` | `false` | 布尔 | 否 | 同上 |
| `qwen3_tts_non_streaming_mode` | 解码前预填完整文本 | `:103` | `true`（本仓 compose 显式 `False`） | 布尔；Apple Silicon 忽略 | 否 | 同上 |
| `qwen3_tts_mlx_quantization` | Apple Silicon MLX 量化 | `:109` | `6bit` | `bf16` / `4bit` / `6bit` / `8bit` | 否 | 同上 |
| `qwen3_tts_language` | 合成目标语言 | `:115` | `auto` | 语言码或 `auto` | 否 | 同上 |
| `qwen3_tts_streaming_chunk_size` | 每流式块 codec 步数 | `:119` | `None`（faster-qwen3-tts 为 8，mlx-audio 为 4） | 正整数 | 否 | 同上 |
| `qwen3_tts_max_new_tokens` | codec token 上限 | `:125` | `1536` | 正整数；约每秒音频 12 token | 否 | 同上 |
| `qwen3_tts_blocksize` | 流式输出块大小 | `:131` | `512` | 正整数（采样点） | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `qwen3_tts_model_name` | 启动 | 是 | expert | 管线级 | 分钟级 | CustomVoice / VoiceDesign / Base 三类模型可选字段不同，选错会启动失败 |
| `qwen3_tts_device` | 启动 | 否 | expert | 管线级 | 重启 | `auto` 在无 CUDA 时会落到 CPU，延迟不可接受 |
| `qwen3_tts_dtype` | 启动 | 否 | expert | 管线级 | 重启 | `float32` 显存与带宽开销翻倍 |
| `qwen3_tts_attn_implementation` | 启动 | 否 | expert | 管线级 | 重启 | `flash_attention_2` 需额外依赖；Jetson 必须用 `eager` |
| `qwen3_tts_backend` | 启动 | 是 | expert | 管线级 | 分钟级 | `ggml` 与 `torch` 权重格式不同，切换需重下 |
| `qwen3_tts_ggml_quantization` | 启动 | 是 | expert | 管线级 | 分钟级 | `Q4_K_M` 显存最低但音质下降 |
| `qwen3_tts_gguf_talker_path` | 启动 | 否 | ops | 管线级 | 重启 | **环境绑定**：本地路径；必须与 codec 成对且 `backend=ggml` |
| `qwen3_tts_gguf_codec_path` | 启动 | 否 | ops | 管线级 | 重启 | 同上 |
| `qwen3_tts_ref_cache_dir` | 启动 | 否 | ops | 管线级 | 重启 | **环境绑定**：容器内不挂卷会导致每次重建重算音色向量 |
| `qwen3_tts_ref_audio` | 启动 | 否 | expert | 管线级 | 分钟级 | **隐私**：参考音频是生物特征，入库需授权；与 `ref_spk` 互斥 |
| `qwen3_tts_ref_spk` | 启动 | 否 | expert | 管线级 | 重启 | 与 `ref_audio` 互斥，同时给会报错 |
| `qwen3_tts_ref_rvq` | 启动 | 否 | expert | 管线级 | 重启 | 依赖 `ref_spk` + `ref_text`，缺一会报错 |
| `qwen3_tts_ref_text` | 启动 | 是 | advanced | 管线级 | 重启 | 必须是参考音频的逐字转写，否则克隆失真 |
| `qwen3_tts_speaker` | 启动+热更新 | 是 | basic | 会话级 | 秒级 | 音色名不存在时后端会退到第一个可用音色 |
| `qwen3_tts_instruct` | 启动 | 是 | basic | 管线级 | 重启 | 仅 VoiceDesign 模型生效 |
| `qwen3_tts_xvec_only` | 启动 | 是 | advanced | 管线级 | 重启 | 开启后音色更稳定但相似度略降 |
| `qwen3_tts_parity_mode` | 启动 | 否 | expert | 管线级 | 重启 | 关闭 CUDA graph 后吞吐下降，但可规避部分卡型的流式异常 |
| `qwen3_tts_non_streaming_mode` | 启动 | 是 | advanced | 管线级 | 重启 | 关掉（=句内流式）可降首音延迟；本仓 compose 即为 `False` |
| `qwen3_tts_mlx_quantization` | 启动 | 否 | expert | 管线级 | 分钟级 | 仅 Apple Silicon 生效 |
| `qwen3_tts_language` | 启动 | 是 | basic | 会话级 | 重启 | `auto` 在混合语种下会串音；可被 `session.update` 覆盖 |
| `qwen3_tts_streaming_chunk_size` | 启动 | 是 | advanced | 管线级 | 重启 | 过小抬高调度开销，过大抬高首音延迟 |
| `qwen3_tts_max_new_tokens` | 启动 | 是 | advanced | 管线级 | 重启 | 过小长句被截断（约 12 token/秒音频） |
| `qwen3_tts_blocksize` | 启动 | 否 | expert | 管线级 | 重启 | 与下游 `CHUNK_SAMPLES=512` 对齐最佳 |

#### B3.2 `openai_compatible`（远端 OpenAI 兼容 TTS）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `openai_tts_base_url` | 服务地址（含 `/v1`） | `openai_tts_arguments.py:9` | `http://localhost:8091/v1` | URL | 是 | `settings` > `{env}` > 默认 |
| `openai_tts_api_key` | Bearer token | `:13` | `None`（回退 `OPENAI_API_KEY`） | 字符串（密钥） | 否 | 同上 |
| `openai_tts_model` | 请求 model | `:17` | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | 字符串 | 否 | 同上 |
| `openai_tts_voice` | 音色名 | `:21` | `aiden` | 服务支持的音色名 | 否 | 同上 |
| `openai_tts_language` | 固定语言参数 | `:25` | `None` | 语言码；原样透传 | 否 | 同上 |
| `openai_tts_task_type` | vLLM-Omni 任务类型 | `:29` | `None` | `CustomVoice` / `VoiceDesign` / `Base` | 否 | 同上 |
| `openai_tts_instructions` | 风格指令 | `:33` | `None` | 字符串 | 否 | 同上 |
| `openai_tts_response_format` | 音频响应格式 | `:37` | `pcm` | `pcm` / `wav` | 否 | 同上 |
| `openai_tts_sample_rate` | 裸 PCM 采样率 | `:41` | `24000` | 正整数（Hz） | 否 | 同上 |
| `openai_tts_speed` | 语速 | `:45` | `1.0` | 正浮点 | 否 | 同上 |
| `openai_tts_stream` | 启用 vLLM-Omni 流式扩展 | `:49` | `false` | 布尔 | 否 | 同上 |
| `openai_tts_timeout` | HTTP 超时 | `:53` | `300.0` | 正浮点（秒） | 否 | 同上 |
| `openai_tts_blocksize` | 管线输出块大小（16 kHz 采样点） | `:57` | `512` | 正整数 | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `openai_tts_base_url` | 启动 | 是 | advanced | 管线级 | 重启 | **环境绑定**：错地址每句都失败，表现为全程静音 |
| `openai_tts_api_key` | 启动 | 否 | ops | 管线级 | 重启 | **安全**：隐式回退 `OPENAI_API_KEY` |
| `openai_tts_model` | 启动 | 是 | expert | 管线级 | 重启 | 名称须与远端一致 |
| `openai_tts_voice` | 启动+热更新 | 是 | basic | 会话级 | 秒级 | 不存在时远端报 400 或回退默认 |
| `openai_tts_language` | 启动 | 是 | basic | 会话级 | 重启 | 固定语言会覆盖自动识别 |
| `openai_tts_task_type` | 启动 | 否 | expert | 管线级 | 重启 | 仅 vLLM-Omni 需要 |
| `openai_tts_instructions` | 启动 | 是 | basic | 管线级 | 重启 | 仅在支持风格指令的服务上生效 |
| `openai_tts_response_format` | 启动 | 否 | expert | 管线级 | 重启 | 只支持 `pcm` / `wav`；`mp3` 会报错 |
| `openai_tts_sample_rate` | 启动 | 是 | expert | 管线级 | 重启 | **配错会变调/变速**；Qwen3-TTS 固定 24000 |
| `openai_tts_speed` | 启动 | 是 | basic | 会话级 | 重启 | 仅非流式端点生效 |
| `openai_tts_stream` | 启动 | 是 | advanced | 会话级 | 重启 | 非 vLLM-Omni 服务打开会报错 |
| `openai_tts_timeout` | 启动 | 是 | expert | 管线级 | 重启 | 过小丢句，过大拖住会话 |
| `openai_tts_blocksize` | 启动 | 否 | expert | 管线级 | 重启 | 与 `CHUNK_SAMPLES` 对齐最佳 |

#### B3.3 `kokoro`（轻量本地 TTS）

**表 A**

| 参数 | 作用 | 模块/文件 | 默认值 | 范围/格式 | 必填 | 来源优先级 |
|---|---|---|---|---|---|---|
| `kokoro_model_name` | 模型 ID 或路径 | `kokoro_tts_arguments.py:7` | `None`（用后端内置） | 字符串 | 否 | `settings` > `{env}` > 默认 |
| `kokoro_device` | 运行设备 | `:13` | `auto` | `auto` / `cuda` / `cpu` / `mps` | 否 | 同上 |
| `kokoro_voice` | 音色 | `:19` | `bm_fable` | Kokoro 音色表 | 否 | 同上 |
| `kokoro_lang_code` | 语言分组码 | `:25` | `b` | `a`（美英）/ `b`（英）等 | 否 | 同上 |
| `kokoro_speed` | 语速 | `:31` | `1.0` | 正浮点 | 否 | 同上 |
| `kokoro_blocksize` | 流式输出块大小 | `:35` | `512` | 正整数（采样点） | 否 | 同上 |

**表 B**

| 参数 | 生效方式 | 建议暴露 | 暴露级别 | 影响面 | 变更代价 | 风险/副作用 |
|---|---|---|---|---|---|---|
| `kokoro_model_name` | 启动 | 是 | expert | 管线级 | 分钟级 | 留空依赖后端默认下载，离线环境需显式路径 |
| `kokoro_device` | 启动 | 否 | expert | 管线级 | 重启 | CPU 可接受但并发受限 |
| `kokoro_voice` | 启动+热更新 | 是 | basic | 会话级 | 秒级 | 与 `lang_code` 不匹配会读错音 |
| `kokoro_lang_code` | 启动 | 是 | advanced | 管线级 | 重启 | 决定可用音色集合 |
| `kokoro_speed` | 启动 | 是 | basic | 会话级 | 重启 | 过快影响可懂度 |
| `kokoro_blocksize` | 启动 | 否 | expert | 管线级 | 重启 | 与 `CHUNK_SAMPLES` 对齐最佳 |

### B4. 目录化后端（19 个）

后续按需深挖时，只需把对应行展开成 B1–B3 的表格式。字段名 = 文件内字段名，全部位于 `blocks.<stage>.settings`。

| stage | 后端名 | arguments 文件 | 字段数 | 必填/关键字段 | 与深挖后端的差异要点 |
|---|---|---|---|---|---|
| stt | `paraformer` | `paraformer_stt_arguments.py` | 2 | `paraformer_model_name` | 中文专用；无语言参数 |
| stt | `sensevoice` | `sensevoice_stt_arguments.py` | 4 | `sensevoice_model_name`、`sensevoice_device` | 内置情感/事件标签；字段名与 `sense_voice`（下划线版）不同，两者并存易混 |
| stt | `sense_voice` | `sense_voice_stt_arguments.py` | 3 | `sense_voice_model_name` | 与 `sensevoice` 是**两个不同后端**，不要混用字段前缀 |
| stt | `whisper` | `whisper_stt_arguments.py` | 9 | `whisper_model_name`、`whisper_device`、`whisper_language` | 字段最多（含 beam / VAD 参数）；延迟高于 parakeet |
| stt | `faster-whisper` | `faster_whisper_stt_arguments.py` | 8 | `faster_whisper_model_name`、`faster_whisper_device`、`faster_whisper_compute_type` | CTranslate2 实现，多 `compute_type`；CPU 友好 |
| stt | `mlx-audio-whisper` | `mlx_audio_whisper_arguments.py` | 3 | `mlx_audio_whisper_model_name` | 仅 Apple Silicon |
| stt | `nemotron-streaming` | `nemotron_streaming_stt_arguments.py` | 3 | `nemotron_streaming_model_name` | 真流式；与 `diarization` 同源家族 |
| stt | `orukeet` | `orukeet_stt_arguments.py` | 5 | `orukeet_model_name`、`orukeet_checkpoint_filename`、`orukeet_checkpoint_revision` | NeMo checkpoint 三件套 + `orukeet_device` / `orukeet_language` |
| stt | `parakeet-unified` | `parakeet_unified_stt_arguments.py` | 3 | `parakeet_unified_model_name` | 与 `parakeet-tdt` 不同 checkpoint，字段前缀不同 |
| stt | `openai-realtime` | `openai_realtime_stt_arguments.py` | 7 | `openai_realtime_base_url`、`openai_realtime_model` | 走 Realtime 协议而非 `/audio/transcriptions` |
| stt | `vllm-realtime` | `vllm_realtime_stt_arguments.py` | 6 | `vllm_realtime_base_url`、`vllm_realtime_model` | 同上，面向 vLLM Realtime 服务 |
| tts | `cosyvoice` | `cosyvoice_tts_arguments.py` | 9 | `cosyvoice_model_name`、`cosyvoice_device` | 支持零样本克隆，参考音频/文本字段与 qwen3 命名不同 |
| tts | `minimax` | `minimax_tts_arguments.py` | 9 | `minimax_api_key`、`minimax_model` | 云端 API，需密钥；有独立 `group_id` 类字段 |
| tts | `pocket` | `pocket_tts_arguments.py` | 9 | `pocket_model_name` | 轻量本地方案，含音色/设备字段 |
| tts | `facebookmms` | `facebookmms_tts_arguments.py` | 4 | `facebookmms_model_name`、`facebookmms_language` | 多语种 MMS，语言码驱动音色 |
| tts | `supertonic` | `supertonic_tts_arguments.py` | 4 | `supertonic_model_name` | 少参；设备与步数为主 |
| tts | `omnivoice` | `omnivoice_tts_arguments.py` | 12 | `omnivoice_model_name`、`omnivoice_ref_audio`、`omnivoice_ref_text` | 参考音频路径属 `_PATH_FIELDS`，会做 `~` 展开与相对解析 |
| tts | `drama3` | `drama3_tts_arguments.py` | 10 | `drama3_api_key`、`drama3_model` | 云端 API；需密钥 |
| tts | `kitten` | `kitten_tts_arguments.py` | 3 | `kitten_model_name` | 少参轻量 |
| tts | `chat-tts` | `chat_tts_arguments.py` | 3 | `chat_tts_model_name` | 对话式 TTS，参数极少 |

> VAD 侧另有两个后端：`silero`（无独立 arguments 文件，复用 `vad_arguments.py` 公共字段）与 `firered`（`vad_firered_model_dir` / `vad_firered_use_gpu`，已在 A6 列出）。

---

## 附录 A：三条端到端样例

三份片段都可直接交给平台 `renderer` 落盘。A.1 与 A.3 中的 YAML 已用 `speech_to_speech.config.load_config` 验证可解析（见 T7）。

### A.1 重启链路（调并发 + 判停 + 系统提示）

场景：把并发从 1 改到 2，换回纯静音判停（700ms），并把回复限短。全部参数 `effect=startup`，必须重建。

```yaml
# config/prod.yaml —— 重启链路样例
schema_version: 1

runtime:
  log_level: info
  log_transcripts: false          # 隐私开关：保持关闭
  server:
    host: 0.0.0.0                 # 容器内必须 0.0.0.0
    port: 8765                    # 需与端口映射 8765:8765 一致

blocks:
  vad:
    kind: vad
    backend: silero
    settings:
      thresh: 0.6
      min_silence_ms: 700         # 纯静音判停，与 compose 一致
      min_speech_ms: 384
      speech_pad_ms: 500
      speculative_reopen_ms: 0    # 本仓规避重复转写的做法
      unanswered_reopen_ms: 0
      smart_turn: false
  stt:
    kind: stt
    backend: qwen3-asr
    settings:
      qwen3_asr_model_name: /root/.cache/qwen3-asr-model-hf
      qwen3_asr_device: auto
      qwen3_asr_language: auto
  llm:
    kind: llm
    backend: chat-completions
    settings:
      model_name: Qwen3-8B
      responses_api_base_url: http://192.168.40.30/v1-openai
      responses_api_api_key: {env: GPUSTACK_API_KEY}   # 密钥不进库；{env:} 是 YAML 映射，不能加引号
      responses_api_stream: true
      stream_batch_sentences: 1   # 逐句流式，降首音延迟
      init_chat_role: system
      init_chat_prompt: "You are a helpful voice assistant. Keep every reply very short."
  tts:
    kind: tts
    backend: qwen3
    settings:
      qwen3_tts_model_name: /root/.cache/qwen3-tts-model
      qwen3_tts_backend: torch
      qwen3_tts_device: cuda
      qwen3_tts_non_streaming_mode: false   # 句内流式
      qwen3_tts_streaming_chunk_size: 4

pipelines:
  prod:
    num_pipelines: 2              # 需 <= floor(可用显存×0.85 / 4.6GB)
    stages: {vad: vad, stt: stt, llm: llm, tts: tts}
```

对应的发布流程（平台侧）：

| 步骤 | 动作 | 失败处理 |
|---|---|---|
| 1 | `validator` 调 `load_config` + `validate_config` | 字段错误直接退回 draft，标出 `file:symbol` 与期望类型 |
| 2 | `renderer` 写 `config/prod.yaml`，旧版备份为 `config/prod.yaml.bak.<version>` | 写失败保留旧文件并告警 |
| 3 | `renderer` 同步写 `.env`（只含 `GPUSTACK_API_KEY` 等 `ops` 字段），供 `docker compose` 做 `${GPUSTACK_API_KEY}` 变量替换（不是 `env_file:`）；配置加载器本身不读 `.env` | `.env` 权限固定 0600 |
| 4 | `compose_runner` 执行 `docker compose up -d --force-recreate pipeline` | 启动失败读 `docker logs --tail 200`，进步骤 7 |
| 5 | 轮询 `GET /v1/pool`，直到 HTTP 200 且 `size == 2` | 超时 180s 视为失败，进步骤 7 |
| 6 | 发一次真实 WebSocket 会话探活（可选） | 失败进步骤 7 |
| 7 | 回滚：恢复 `prod.yaml.bak.<version>` + 重建容器 + 再探 `/v1/pool` | 回滚也失败 → 告警人工介入 |

> `num_pipelines` 从 1 改到 2 会同时把显存占用翻倍。发布前 `validator` 必须先做显存预算校验，否则 OOM 会连带抖动现有会话。
>
> **YAML 如何进容器**：文件模式只接受 `-f/--file` 与 `--name`，其余参数必须写进 YAML（`cli.py:_run_file_command`）。因此 compose 服务的 `command` 需改成 `speech-to-speech serve -f /app/config/prod.yaml --name prod`，并把 `config/` 以只读卷挂到 `/app/config`。`serve` 要求恰好选中一个 definition，故 `--name` 不可省。

### A.2 热更新链路（不动容器改会话行为）

场景：运营把当前默认人设改成更简短，并调整打断行为。这两个字段在 `RuntimeConfig` 内，可以走 `session.update`。

> 不要用 `voice` / `model` 做热更新示例——取证显示它们只被接受并回显，不改变 TTS 音色与 LLM 模型（`handlers/response.py:519-525`、`handlers/session.py:66-68`）。换音色必须改 `qwen3_tts_speaker` 并重启。

**请求**（平台管理路由 → 服务端内部 fanout 到各 pipeline 的当前会话）：

```http
POST /admin/sessions/update
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "session": {
    "instructions": "你是简洁的语音助手，每次回复不超过两句话，跟随用户语言。",
    "audio": { "input": { "turn_detection": { "interrupt_response": true } } }
  },
  "scope": "all"
}
```

**响应**：

```json
{
  "updated": 2,
  "failed": [],
  "applied_fields": ["instructions", "audio.input.turn_detection.interrupt_response"]
}
```

**可热更新字段白名单**（超出此集合返回 `400 unsupported_field`）：

| 字段 | 真实生效 | 说明 / 证据 |
|---|---|---|
| `instructions` | 是 | `response.instructions or runtime_config.session.instructions`（`base_openai_compatible_language_model.py:972-974`）|
| `audio.input.turn_detection.create_response` | 是 | `runtime_config.py:59-68` |
| `audio.input.turn_detection.interrupt_response` | 是 | `runtime_config.py:70-88`，缺省 `true` |
| `audio.input.transcription.language` | 是 | `handlers/session.py:42-64` 做后端能力校验；`auto` 需 `stt_auto_reset_supported` |
| `extensions` | 是 | `runtime_config.py:90-100`，目前只识别 `speech_to_speech.input_audio_transcription.snapshot` |
| `voice` / `model` | **否** | 只回显到响应对象 / 只记日志；不进热更新面板 |

**行为约束**：

| 场景 | 结果 |
|---|---|
| 已连接会话 | 立刻写入 `RuntimeConfig`，下一次 LLM/TTS 调用即读到新值（`runtime_config.py:102-105`） |
| 新连接 | 仍读 `init_chat_prompt` 种子（`service.py:416`）；要同步改默认必须走 A.1 |
| `scope: all` | 向所有 pipeline 的所有活跃连接 fanout |
| `scope: pipeline` + `target: <index>` | 只 fanout 该 unit |
| `scope: session` + `target: <session_id>` | 只 fanout 单条连接 |
| 源码未改（无 `/admin/sessions/update`） | 端点返回 `501`；只能重启改 `init_chat_prompt`，且仅对新会话生效 |
| 字段不在白名单 | `400 unsupported_field`，不静默丢弃 |
| `transcription.language` 不被当前 STT/TTS 支持 | `400 unsupported_language`（复用 `handlers/session.py:24-77` 的校验） |

> **关键前提**：要让热更新影响**已建立**的会话，必须在 `api/openai_realtime/websocket_router.py` 的 FastAPI app 上新增一个受 token 保护的路由，复用 `SessionHandler.handle_session_update` 的合并语义；否则平台只能改「平台侧默认值」，仅对新会话生效。这是本方案唯一需要修改 S2S 源码的地方。

### A.3 回滚链路（健康检查失败自动回退）

场景：A.1 发布后 `num_pipelines=2` 导致 OOM，容器反复重启，`/v1/pool` 起不来。

```yaml
# config/prod.yaml —— 回滚后的目标内容（= 上一版本 v7）
```

沿用 A.1 的 YAML，只把 `num_pipelines` 改回 `1`。其余字段与 v7 完全一致。

**回滚流程**：

| 步骤 | 动作 | 证据 |
|---|---|---|
| 1 | 发布 v8（`num_pipelines: 2`） | `store` 记录 v8 内容哈希与操作人 |
| 2 | 轮询 `GET /v1/pool`，180s 内未返回 200 | 记录每次尝试的状态码与耗时 |
| 3 | `docker logs --tail 200 pipeline` 抓取 OOM/启动失败堆栈 | 写入 v8 审计附言 |
| 4 | 恢复 `config/prod.yaml.bak.v7` | 文件 SHA-256 与 v7 记录一致 |
| 5 | `docker compose up -d --force-recreate pipeline` | compose 返回码为 0 |
| 6 | 再探 `GET /v1/pool`，要求 `size == 1` 且 `in_use == 0` | 通过则标记 v8 回滚完成 |
| 7 | 若步骤 6 仍失败 → `POST /admin/profiles/prod/rollback` 回 v6，同时告警 | 连续两次失败视为需要人工介入 |

**回滚边界**：

- 只回滚文件与容器；**已建立连接全部断开**，这是重启链路的固有代价（变更代价 = `minutes`）。
- `ops` 字段（密钥、GPU ID、端口映射）不回滚——它们不归平台版本管，回滚只恢复 `renderer` 生成的那两个文件。
- 版本不可变：回滚产生新版本号 v9（内容等于 v7），历史 v7/v8 都不删除。

---

## 附录 B：与 `docs/configuration.md` 的分工

| 主题 | 本文 | `configuration.md` |
|---|---|---|
| YAML 语法、`{env:}` 展开规则、路径解析细节 | 只给结论 | **权威来源** |
| 每个参数字段值与风险 | **权威来源** | 不重复 |
| 校验命令与错误信息 | 不重复 | **权威来源** |
| 平台 API 契约 | 见 spec 附录 A | 无 |

---

## 附录 C：计数核对

### C.1 人读版章节计数

| 层级 | 章节 | 条数 |
|---|---|---|
| A 层 | A1 服务监听 2 / A2 并发队列 3 / A3 超时重试 6 / A4 音频 8 / A5 模型语音 11 / A6 VAD 22 / A7 设备与分离 11 / A8 鉴权安全 9 / A9 日志监控 8 / A10 环境变量 12 / A11 配置文件 6 / A12 容器化 9 / A13 客户端 18 | **125** |
| B 层深挖 | parakeet-tdt 3 / qwen3-asr 6 / openai STT 7 / transformers 9 / responses-api 10 / chat-completions 1 / qwen3 TTS 23 / openai TTS 13 / kokoro 6 | **78** |
| B 层目录化 | STT 11 个 + TTS 9 个后端 | **20 个后端** |
| 小计 | A + B 深挖 | **203** |

### C.2 机器可读目录计数

`parameter-catalog.yaml` 共 **196 条**，按 `stage` 分布：

| stage | client | deploy | env | llm | runtime | server | stt | tts | vad | 合计 |
|---|---|---|---|---|---|---|---|---|---|
| 条数 | 18 | 16 | 18 | 30 | 33 | 2 | 16 | 42 | 21 | **196** |

`runtime` 的 33 条中，有 5 条 `session.*` 是 **A.2 热更新链路的服务端会话字段**（`session.instructions`、两个 `turn_detection` 开关、转录语言、`extensions`），对应 `effect=hot`、`impact=session`。

### C.3 为何 203 ≠ 196

两个口径的差异全部来自**交叉引用的重复登记**——人读版按章节自包含允许重复，机器版按 `(stage, backend, name)` 唯一必须去重；此外人读版不重复登记 A.2 的 `session.*` 服务端字段（它们只在附录 A.2 表格出现，不在 A 层主表）。不是漏项：

| 差异原因 | 条数 |
|---|---|
| 密钥字段在 A8 与 B1.3 / B2.2 / B3.2 各登一次（`responses_api_api_key`、`openai_stt_api_key`、`openai_tts_api_key`） | -3 |
| 超时/采样字段在 A3 / A4 与 B1.3 / B3.2 各登一次（`openai_stt_timeout`、`openai_tts_timeout`、`openai_tts_sample_rate`） | -3 |
| `connection_retry_timeout_s` 在 A3（超时）与 A13（客户端）各登一次 | -1 |
| `sample_rate` 在 A4（音频）与 A6（VAD）各登一次 | -1 |
| 同一个 `model_name` 在 `llm/null`（基类）与 `llm/responses-api`（覆写）是两条独立条目，两侧均计 | 0 |
| 人读版仅在附录 A.2 表格出现、未进 A 层主表的 `session.*` 服务端字段 | +5 |
| 其余重复登记 | -4 |
| **合计** | **-7**（203 - 196） |

> 平台以 YAML 为唯一数据源；md 的重复登记是为了让每个章节自包含（读到 A3 就知道超时字段叫什么），阅读时以「参数名」为准，计数时才去重。

### C.4 YAML 标识符 ↔ md 写法对照

YAML 中部分条目用 snake_case 标识符，md 中用大写环境变量名或中文描述：

| YAML `name` | md 写法 | 所在章节 |
|---|---|---|
| `llama_parallel_slots` | `-np`（llama 并行槽） | A2 |
| `pipeline_sample_rate` | `PIPELINE_SAMPLE_RATE` | A4 |
| `chunk_samples` | `CHUNK_SAMPLES` | A4 |
| `request_timeout_s` | `request_timeout_s`（LLM） | A3 |
| `http_retry_policy` | 自动重试策略 | A3 |
| `pool_reject_when_full` | pool 满拒绝 | A2 |
| `cors_policy` | CORS 策略 | A8 |
| `realtime_api_auth` | Realtime API 鉴权 | A8 |
| `monitoring_endpoints` | 监控端点 | A9 |
| `top_level_keys` | 顶层结构 | A11 |
| `env_reference` | `{env: NAME}` 引用 | A11 |
| `path_field_resolution` | 路径字段解析 | A11 |
| `max_config_bytes` | 文件体积上限 | A11 |
| `max_config_depth` | 嵌套深度上限 | A11 |
| `dockerfile` | `DOCKERFILE`（build arg） | A12 |
| `base_image` | `BASE_IMAGE`（build arg） | A12 |
| `pipeline_port` | `PIPELINE_PORT`（host 侧） | A12 |
| `pipeline_gpu_id` | `PIPELINE_GPU_ID`（host 侧） | A12 |
| `gpu_reservation` | GPU 能力声明 | A12 |
| `cache_volume` | 权重/缓存卷 | A12 |
| `silero_vad_volume` | Silero VAD 卷 | A12 |
| `restart_policy` | 重启策略 | A12 |
| `healthcheck` | 健康检查 | A12 |
| `session.instructions` | `session.update.instructions` | A.2 |
| `session.audio.input.turn_detection.create_response` | `create_response` | A.2 |
| `session.audio.input.turn_detection.interrupt_response` | `interrupt_response` | A.2 |
| `session.audio.input.transcription.language` | `transcription.language` | A.2 |
| `session.extensions` | `extensions` | A.2 |
