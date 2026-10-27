# S2S 部署调参场景手册（按环境与现象给参数组合）

面向"已经知道要部署在哪台机器、给谁用"的运维与交付同学：**先判断环境档位与现象，再照组合改，改完照验证项复核**。

本手册**不重复**下列内容，只引用：

| 你要的东西 | 去哪看 |
|---|---|
| 单个旋钮怎么改（CLI/YAML 写法） | [`model-pipeline.md`](./model-pipeline.md) §6 |
| 每个参数的默认值、范围、暴露级别、风险 | [`parameter-catalog.md`](./parameter-catalog.md) §2–§6 |
| 显存基线、并发公式、延迟档位、假设编号 | [`hardware/performance-assumptions.md`](./hardware/performance-assumptions.md) §3–§5 |
| 机型/盒子选型与采购编号 `D-xx` | [`hardware/README.md`](./hardware/README.md)、[`hardware/procurement-list.md`](./hardware/procurement-list.md) |
| 延迟日志字段语义 | [`response-latency.md`](./response-latency.md) |
| 部署形态与 compose 矩阵 | [`deployment.md`](./deployment.md)、[`upstream-diff-and-deployment-config.md`](./upstream-diff-and-deployment-config.md) §3 |

> 本手册中所有路数/显存数字均为**引用** [`hardware/performance-assumptions.md`](./hardware/performance-assumptions.md) §4 的口径（单路 ≈4.6 GB、余量 ×0.85）。测出新值只改假设表，不要改这里。

---

## 0. 三条纪律

1. **一次只动一组**。同一场景内的参数是耦合的（如 `min_silence_ms` ↔ `short_segment_merge_ms`），跨场景的不要混在一轮里改。
2. **改前先抓指纹**：`nvidia-smi` 显存占用、`GET /v1/pool`、一轮真实对话的 latency 日志行。没有基线就无法判断改善还是退化。
3. **先算预算再动 `num_pipelines`**：`槽位上限 = floor(可用显存 × 0.85 ÷ 4.6)`（假设表 §4）。同机含 LLM 时先扣权重与 KV。池满**直接拒绝新连接、不排队**（catalog §6.1），所以宁小勿大。

### 0.1 诊断入口：先看日志属于哪一段

服务每轮结束打一条 INFO（[`response-latency.md`](./response-latency.md)）：

```text
Turn turn_3 rev=0 latency: stt=0.18s llm=1.24s tts_ttfa=0.12s e2e=2.01s vad_settle=0.61s vad_decision=0.36s hold=0.24s smart_status=complete
```

| 偏大的字段 | 归因 | 去哪个场景 |
|---|---|---|
| `vad_decision` / `vad_settle` | 判停等待 | S10–S14 |
| `stt` | 转写耗时（整段非流式） | S1、S3、S12、S17 |
| `llm` | 上游生成 / 网络 / 排队 | S9、S2、S17 |
| `tts_ttfa` | 合成首包 | S1、S4、S11、S19 |
| `e2e` 大但各分段都不大 | 排队与抢占、hold | S2、S12、S18 |
| `mlx_lock_wait` / `mlx_lock_hold` | macOS 全局 Metal 锁竞争 | S3、S2 |
| `hold` | 处理门控等待（含软结束宽限） | S12、S14 |
| 反复出现 `smart_status=incomplete` | 语义判停在拖时间 | S12、S11 |

> `e2e` 从**估计的说话结束**起算，不 inclusive 判停等待；比较档位时统一用 `e2e + min_silence_ms/1000`（口径见 [`hardware/deployment-multibox.md`](./hardware/deployment-multibox.md) §并发压测）。

---

# 第一部分 · 服务端：GPU、镜像与接入

## S1 · 显存临界 / OOM / 启动即被杀

**触发**：`docker logs` 出现 CUDA OOM；`nvidia-smi` 占用逼近标称显存；容器被反复拉起。本仓实测：**12 GB 卡同机放 4B Q4 LLM 时已到 ≈11.6 GB，仅剩 ~67 MiB**（`hardware/README.md` 本机实测）。

**先动（按性价比排序）**

1. `num_pipelines` 降到预算内（这是唯一硬约束，见 §0 纪律 3）。
2. TTS 换 GGML 后端并降量化：`qwen3_tts_backend: ggml` + `qwen3_tts_ggml_quantization: Q8_0`（保守）或 `Q4_K_M`（显存最低，**音质下降**）。
3. 精度收一档：`qwen3_asr_torch_dtype: bfloat16`、`qwen3_tts_dtype: float16`，别用 `float32`。
4. 把 LLM 搬出去（S9 / 多盒），管线盒只留 VAD+STT+TTS。

```yaml
blocks:
  tts:
    kind: tts
    backend: qwen3
    settings:
      qwen3_tts_backend: ggml
      qwen3_tts_ggml_quantization: Q8_0
      qwen3_tts_dtype: float16
  stt:
    kind: stt
    backend: qwen3-asr
    settings:
      qwen3_asr_torch_dtype: bfloat16
pipelines:
  prod: {num_pipelines: 1, stages: {vad: vad, stt: stt, llm: llm, tts: tts}}
```

**验证**：`nvidia-smi` 稳定占用 ≤ 标称 ×0.85；`GET /v1/pool` 的 `size` 等于 `num_pipelines`；跑一轮对话后 `llm`/`tts_ttfa` 未劣化。

**代价 / 回退**：GGML 与 torch 的权重形态不同，切换要重新准备权重（分钟级）；`Q4_K_M` 听感劣化明显，交付前需业务确认。STT/TTS 的 INT8 只在假设表 §3.1 给了区间，**仓库未提供 INT8 配置项**，需自行量化，别在配置里臆造字段。

## S2 · 并发从 1 路扩到 N 路

**触发**：高峰期新会话直接被拒（池满无排队），或单路对话被另一路的推理抢占导致 `e2e` 抖动。

**先动**

1. 按公式算上限：12 GB→2、16 GB→2、24 GB→4、48 GB→8（纯管线盒，假设表 §4）。
2. `num_pipelines` 设到上限**减 1**，先留缓冲，压测通过再顶格。
3. 同机 CPU 侧跟上：`torch_num_threads`、`smart_turn_cpu_count`（Silero 加载时会把线程设为 1，调大是加速 CPU STT，代价是拖慢 Silero）。
4. 更多路只有两条路：**加管线盒**（LLM 集中）或换 ≥24 GB 卡。同卡塞 LLM 时 12 GB 做不出多路（假设表 §4 结论 1）。

```yaml
pipelines:
  prod:
    num_pipelines: 3            # 24GB 卡上限 4，先给 3
    options:
      enable_live_transcription: false   # 字幕事件量随路数线性增长，压测期先关
```

**验证**：按 1→3→5→10→20 递增并发（`latency_test.py`，口径见 `hardware/deployment-multibox.md`）；**饱和点**=P95 TTFA 超档 / 出现 `SERVER ERROR` / GPU 温度触顶降频，任一命中即减一档作为交付路数。

**代价 / 回退**：每加一路 ≈ 一份 4.6 GB；降配会中断现有会话。多路复测出的实际每路显存要**回填假设表 §3.1/§7 HA4**，不要在本手册里改数。

## S3 · 没有 GPU 的机器 / CPU-only 演示

**触发**：目标机只有集显或 NPU；或只是要给销售/测试演示一场，不追求并发。

**先动**

1. STT 换 CPU 友好的 `faster-whisper` 并设 `faster_whisper_stt_compute_type`（`int8`/`float16`）。
2. TTS 换轻量后端：`kokoro`（需 `[kokoro]` extra，CPU 可跑）、`supertonic`（只有 4 个字段）、`kitten`/`pocket`；或干脆走远端 `openai` TTS 把算力推出去。
3. LLM 走远端（`chat-completions`），本地不留权重。
4. 关掉 Smart Turn 之外的 CPU 负载：`smart_turn_cpu_count` 保持 1；`enable_live_transcription: false`。
5. 需要 Qwen3-TTS 的 GGML 轮子时，装 `qwentts-cpp-python==+cpu`（根 [`README.md`](../README.md) §CUDA Note）。

```yaml
blocks:
  vad: {kind: vad, backend: silero, settings: {smart_turn: false}}
  stt:
    kind: stt
    backend: faster-whisper
    settings:
      faster_whisper_stt_model_name: <model>
      faster_whisper_stt_compute_type: int8
  llm:
    kind: llm
    backend: chat-completions
    settings:
      responses_api_base_url: http://<内网网关>/v1-openai
      responses_api_api_key: {env: GPUSTACK_API_KEY}
      stream_batch_sentences: 1
      chat_size: 12
  tts: {kind: tts, backend: kokoro, settings: {kokoro_device: cpu}}
```

**验证**：一轮对话的 `stt`/`tts_ttfa` 是否落在可用档（P95 ≤2.0 s，假设表 §5）；`vad_decision` 是否因 CPU 抢核变大。

**代价**：RTF 可能 >1（比实时还慢），此时判停再快也没用——**换模型，不要靠调阈值掩盖**。macOS / Apple Silicon 另见第三部分矩阵的“macOS 本机”行（`mac_optimal_settings: true` + `example_configs/mac.yaml`）。

## S4 · 驱动 / CUDA 版本不匹配：**静默**回退 CPU

**触发**：服务正常启动、能对话，但响应极慢，日志里没有 OOM 也没有报错。

**根因模式**（`Dockerfile.cu130:12-16` 原文）：宿主驱动 **< 580**（`nvidia-smi` 的 CUDA 列 <13.0）时，torch 的 cu130 轮子在 CUDA 初始化阶段报 `driver too old`，表现为 **TTS/STT 静默回退 CPU，RTF ≈ 3.7× 实时**。

**先动**

1. 先核对驱动：`nvidia-smi` 看 CUDA Version；<580 驱动就用 `Dockerfile`（cu128 变体），**不要**升 `DOCKERFILE=Dockerfile.cu130`。
2. 驱动 ≥580 且要新架构卡（RTX 50 系）：`.env` 里设 `DOCKERFILE=Dockerfile.cu130`——它是 compose 透传的变量（`dockerfile: ${DOCKERFILE:-Dockerfile}`，`docker-compose.yml:47`）。但 **`BASE_IMAGE` 不是**：它只是 Dockerfile 里的 `ARG`，仓内 7 个 compose 没有一个写 `build.args`，想换基镜像得自己 `docker build --build-arg BASE_IMAGE=…` 或给 compose 补 `args:`（catalog §6.9）。
3. 确认 GPU 真的进了容器：compose 的 `deploy.resources.reservations.devices.capabilities: [gpu]` 缺失时同样退 CPU，且**不报错**。
4. 若用 GGML TTS，轮子要匹配 CUDA：`+cu130` / `+cu128` / `+cu124` / `+cpu`（根 [`README.md`](../README.md)）。

**验证**：`nvidia-smi` 在对话进行中能看到 pipeline 进程占卡；`tts_ttfa` 回到 100–200 ms 量级（假设表 §5 舒适档）。

**代价**：换镜像变体是**分钟级重建**，属于"容器"生效面，不能热改。

## S5 · ARM 边缘盒（Jetson Orin NX / DGX Spark）

**触发**：15–40 W 功耗预算、统一内存、aarch64。

**前提**：假设表 §7 **HT3 仍未解除**——10 款候选盒子里没有一个有"1.7B + FP16 + transformers"的实测证据；到货必须先跑 [`hardware/acceptance-test-plan.md`](./hardware/acceptance-test-plan.md) 的 T1/T2/T3，**RTF>1 则整体否决**。

**先动**

1. STT 用 0.6B 而不是 1.7B（`qwen3_asr_model_name` 指向 0.6B 本地目录）。
2. TTS：`qwen3_tts_attn_implementation: eager`（Jetson 必须 eager，catalog §5.2）；`qwen3_tts_parity_mode: true` 规避 CUDA graph 流式路径在 ARM 上的异常。
3. DGX Spark（CUDA 13 + ARM64）：装 cu130 的 **aarch64** 轮子并用 `uv run --no-sync` 启动，否则默认 cu12 轮子缺 `libcudart.so.12`（根 [`README.md`](../README.md)）。
4. Orin 的 llama.cpp 需 aarch64+CUDA 构建（**≥ b8001**，旧版报 `unknown architecture`，假设表 HT2）。
5. `num_pipelines: 1`——统一内存下别让两路抢带宽。

**验证**：T3 的 RTF 实测；`vad_settle` 是否因 CPU 侧争抢变大；`MODEL_METRICS_LOG` 里各段耗时。

**代价**：0.6B ASR 与 int4 TTS 的质量下限要业务确认；社区方案（Seeed，假设表 HT3）是**方案级证据**，不等于本机可用。

## S6 · 多卡机器：谁用哪张卡

**触发**：GPUStack/vLLM 与 pipeline 同机不同卡；或 pipeline 与分离/降噪模型争卡。

**先动**

1. 编排侧指定卡号：`.env` 的 `PIPELINE_GPU_ID`（compose 里 `device_ids: ['${PIPELINE_GPU_ID:-0}']`）。
2. **不要**用全局 `device` 图省事——它会击穿各组件的 `*_device` 意图（catalog §6.4）。
3. 逐组件写：`qwen3_asr_device` / `qwen3_tts_device` / `llm_device` / `diarization_device`。
4. 分离模型（S16）与 TTS 抢同一张卡时，把 `diarization_dtype` 收到 `float16` 并降低 `num_pipelines`。

**验证**：`nvidia-smi` 逐卡核对进程归属；跨卡不会自动变快——每路 handler 是整套独占。

## S7 · 镜像与配置加载的既有坑

| 症状 | 原因（已在仓内注释确认） | 处置 |
|---|---|---|
| 平台改了 `prod.env` 但值纹丝不动 | compose 中 `environment:` **优先级高于** `env_file:`，同名项会盖掉文件值（`docker-compose.yml:51-53`） | 环境变量只留在 `env_file`，`environment:` 里不要再写同名项 |
| 启动卡住并联网重下 nltk 数据 | bind mount 后 `nltk_data` 权限 777，nltk 判定 world-writable 拒用（`Dockerfile.local/sox` 已固化进镜像） | 用 `Dockerfile.local`/`.sox` 变体时**不要**再挂 `nltk_data`（`docker-compose.local.yml:108-109`） |
| TTS warmup 报 `fatal error: Python.h: No such file` | 基础镜像缺 `python3.12-dev`，triton JIT 编不了 CUDA graph | 镜像里装上（`Dockerfile.cu130:38-43`）；或 `qwen3_tts_parity_mode: true` 绕过 CUDA graph 路径 |
| `up -d` 后 `.env.cu130` / `.env.gpustack` 里的值没生效 | `docker compose -f X.yml` **只自动读 `.env`** | 显式 `--env-file .env.cu130`（`upstream-diff…` §3.1 注） |
| clone 后 Silero 目录是空的 | `silero-vad` 是 gitlink 且**无 `.gitmodules`**；compose 挂的是仓外 `../.silero-dl2/silero-vad-master` | 自备权重目录并设 `SILERO_VAD_REPO_PATH`（catalog §6.7） |

## S8 · 离线内网：首启就卡在下载

**触发**：无外网环境首次拉起，日志停在权重下载 / HEAD 重试。

**先动**

1. `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`（`config/prod.env.example` 明确建议保持开启——权重已在 `./cache`，离线模式可阻止加载器对不存在的可选文件反复 HEAD 重试）。
2. 权重目录整卷挂载：`./cache/ → /root/.cache/`（catalog §6.9）。
3. Smart Turn 用本地 ONNX：`smart_turn_model_path: cache/smart-turn-v3.2-cpu.onnx`——留空会**联网下载 v3.2**（catalog §2.4）。
4. Silero 用本地仓库：`SILERO_VAD_REPO_PATH` → `/opt/silero-vad` → 仓库内 `silero-vad/`。
5. 有镜像源时设 `HF_ENDPOINT`（如 hf-mirror）；ModelScope 系（`paraformer`/`sense-voice`）另设 `MODELSCOPE_ENDPOINT`。
6. 缓存不全时报的是 `LocalEntryNotFound`——**这是缺文件，不是网络问题**，别去调代理。

**验证**：拔网重启一次，服务能在 `docker compose up` 后直接 `GET /v1/pool` 就绪。

**代价**：`--force-recreate` 会重下权重（若没挂卷），生产环境这是分钟级停机。

## S9 · 远端 LLM 慢、超时、404、502

**触发**：`llm` 字段占掉 `e2e` 的大头；或首轮就报错；日志有 `upstream_status` / `upstream_body`。

**先动（按归因）**

| 现象 | 动什么 |
|---|---|
| 首 token 慢（TTFT 大） | `responses_api_reasoning_effort`：本仓现网用 `""`——**这只在 `chat-completions` 上等于不下发**（`base_openai_compatible_language_model.py:297` 是 falsy 判断，回落 `chat_template_kwargs.enable_thinking=false`）；若 LLM 后端是 `responses`，空串**仍会**发出 `reasoning:{effort:""}`（`responses_api_language_model.py:95` 只判 `is None`），要不发必须留空。通用安全取值是 `none`（`deployment.md` §4.2 即用它）。其余：`responses_api_disable_thinking: true`、确认 `responses_api_stream: true`；`chat_size` 收紧（本仓 local 用 40、现网 20，见假设表 §2）；`compact_history` 决定是否多一次摘要调用 |
| 回答偏长导致出声晚 | `init_chat_prompt` 限定"一两句"；`stream_batch_sentences: 1` 逐句下吐 |
| 上游 5xx / 连不上，用户听到尴尬沉默 | `responses_api_provider_unavailable_message: "语言模型服务暂时不可用，请稍后再试。"`（`docker-compose.local.yml:36-39`） |
| `model_name` 404 | 名称必须与网关注册名**完全一致**（`GPUSTACK_MODEL`）；`responses_api_base_url` 用 `/v1-openai` 而不是 `/v1`（`deployment.md` §4.1） |
| Windows/Docker Desktop 打不通内网 GPUStack | WSL2 → 宿主服务需中转，本仓用 `llm-proxy.py` 解决 502（`upstream-diff…` 重要发现） |
| 长回答被截断 | LLM 读取超时是**只读常量 20 s**（catalog §6.2），不可配；只能缩短回答或换吞吐 |
| 跨机延迟 | 管线与 LLM 同网段（假设 HA2 内网 RTT 10–80 ms），1 GbE 起步，建议同二层/10 GbE |

**验证**：`llm` 字段回到假设表 §5 预算（舒适 150–300 ms）；`GET /v1/models`（LLM 盒）与一轮真实会话同时通过。

**代价**：`reasoning_effort` 的**空串语义按后端不对称**（见上表），照搬另一后端的写法会让上游按默认强度推理或收到非法值；非 `none` 的首 token 延迟直接进 `e2e`（catalog §4.3）。

---

# 第二部分 · 使用环境与交互手感

> 这一部分的判停类参数里，`thresh` 与 `min_silence_ms` **支持会话级热更新**（catalog §2.8），其余要重启。
> 热更新走 `POST /admin/sessions/update`（需 `S2S_ADMIN_TOKEN`，未配置直接 `503`，catalog A.2）。

## S10 · 噪声环境（开放办公、门店、车载、空调/风扇）

**现象**：没人说话时也起气泡；呼吸、键盘声被判成语音；`vad_decision` 频繁触发。

**先动**

1. `thresh` 调大：0.6 → 0.65–0.7（catalog §2.7）。
2. `min_speech_ms` 调大：384 → 500+，过滤短促脉冲。
3. `audio_enhancement: true`（DeepFilterNet，需装 `df`；未装则只记错误日志并自动关闭）——噪声大时这一项收益最明显，代价是 CPU。
4. 换 VAD 后端：`vad: firered` + `vad_firered_model_dir`（误警率显著低于 Silero，见 catalog §1.2 横向指标）。
5. `speculative_reopen_ms: 0`、`unanswered_reopen_ms: 0`——噪声引起的软结束轮重开会造成重复转写与重复气泡。

**验证**：静默 60 s 不应出现任何 partial/转写事件；`thresh` 热更新可在已连会话上即时试。

**代价**：`thresh` 过高会漏掉轻声句尾；`audio_enhancement` 与 CPU STT 抢核。

## S11 · 安静环境追求极致首音

**现象**：演示/评测要压 P95 TTFA，允许偶尔切错句。

**先动（本仓实测过的组合）**

1. `min_silence_ms`：700 → 500。本仓记录：**700 ms 档实测捕获率 75%、首音 3.9–6.7 s；500 ms 少等 0.2 s，捕获率略降但首音更快**（`docker-compose.local.yml:68-69`）。评测下限可再试 64 ms（假设表 §1 的"本机调优"档，**不作验收基线**）。
2. `smart_turn: false`（去掉二次确认等待）。
3. `stream_batch_sentences: 1` + `qwen3_tts_non_streaming_mode: false` + `qwen3_tts_streaming_chunk_size: 4`（逐句 + 句内流式）。
4. `enable_live_transcription: true` + `live_transcription_update_interval: 0.5`：字幕早出，用户感知更快（不改变显存口径）。
5. 客户端 `playback_buffer_ms: 0`（有爆音风险，见 S18）。

**验证**：`e2e + min_silence_ms/1000` 对比改前；`tts_ttfa` 应 <200 ms。

**代价**：判停越短，误切句越多；这是体验取舍，不是纯优化。

## S12 · 慢语速 / 长句 / 中英混说被切碎

**现象**：用户一句话被拆成两轮；或句中思考停顿后就开始回答。

**先动**

1. `min_silence_ms` 调大（450 → 600–800），每轮响应延迟 +0.15–0.35 s（catalog §2.7）。
2. 打开语义判停：`smart_turn: true` + `smart_turn_threshold: 0.55–0.6` + 配 `smart_turn_model_path`（离线必须给本地 ONNX）。
3. `smart_turn_max_wait_ms`（默认 2000）与 `smart_turn_incomplete_delay_ms`（默认 600）控制"判为没说完"后的重开宽限与延迟；注意 `unanswered_reopen_ms` 实际取三者最大值。
4. 碎片拼接：`short_segment_merge_ms` **必须 ≥ `min_silence_ms`**（catalog §2.3），本仓取值 800/`min_silence_ms` 500。
5. 长独白保护：`max_speech_ms: 15000–30000`（默认 `inf` 不切）。

**验证**：`smart_status` 应多为 `complete`；`hold` 不应长期顶满宽限；重开导致的重复气泡归零。

**代价**：每轮判停延迟直接进 TTFA；FireRedVAD/Silero 之外的误检问题不在这里解决。

## S13 · 首字被吞 / 句尾被截

**现象**：句首爆破音（"八""怕"）丢失；或句尾语气词被吃掉。

**先动**

1. `speech_pad_ms` 调大：500 → 700（本项目语义是"触发前回补窗口"，与官方 30 ms 语义不同，catalog §2.6）。
2. 句尾被截属于判停太急 → 回 S12 第 1 项，或开 `smart_turn`。
3. 客户端确认 `send_rate`/`chunk_size` 与服务端 16 kHz / 512 点分块不冲突（catalog §6.3）。

**代价**：段首多带静音会略增 STT 输入长度；`speech_pad_ms` 过大引入额外静音延迟。

## S14 · 「嗯」「好的」这类短应答无响应

**现象**：用户小声附和，服务完全不理。

**先动**

1. `min_speech_ms` 调小：384 → **250**（本仓实测：384 ms 时"嗯/好的/你好"这类整段会被直接丢弃，`docker-compose.local.yml:73-74`）。
2. `min_speech_continuation_ms`（钳制到 `[100, min_speech_ms]`，`0` 关闭）配合调整续说判定。
3. 配 `short_segment_merge_ms` 把碎片先 hold 再拼，而不是丢弃（约束见 S12 第 4 项）。

**代价**：噪声脉冲更容易触发 barge-in——噪声环境做这项调整前先看 S10。

## S15 · 打断（barge-in）与自打断、回声

**现象**：AI 说话时用户插话不生效；或 AI 被自己的外放打断。

**先动**

1. 确认会话侧允许打断：`turn_detection.interrupt_response`（默认 `true`）、`turn_detection.create_response`（默认 `true`），二者**可热更新**（catalog §0.4 第 5 条）。
2. 客户端 `block_mic_during_playback: true` 是最粗暴的止血（代价：失去 barge-in，catalog §6.10）。
3. 真正的问题是声学回路的：优先**耳机**；外放场景检查浏览器 AEC 是否启用。
4. 误打断导致的重复合成看日志 `tts=cut`（表示取消发生在已出声之后）。

**验证**：热更新对**已连会话**立刻生效（`/admin/sessions/update` 返回 `{updated, failed}`）；新连接仍读 YAML。

## S16 · 多说话人 / 会议分离

**现象**：需要标记"谁说的"。

**先动**

1. `diarization: true` + `diarization_model_name`（+ `diarization_revision` 固定，避免上游漂移）——开了不配模型会**启动失败**。
2. `diarization_streaming_mode`：`low_latency` / `very_low_latency` / `ultra_low_latency`，越低越易把一句切成多段。
3. `diarization_threshold`（默认 0.5）：过低把噪声当人，过高漏轻声轮次。
4. `diarization_device` / `diarization_dtype` 与 STT/TTS 显存一起进预算（catalog §6.4）。
5. 分离与 `nemotron-streaming` STT 同源，真流式场景优先考虑该组合（catalog §1.3）。

**代价**：额外显存 + 分离出错会把同一人拆成多个说话人；多路并发下先降 `num_pipelines`。

## S17 · 语种与切换

**现象**：中英混说识别飘、回答语言乱、TTS 串音。

**先动**

1. 固定 STT 语言：`qwen3_asr_language: zh`——`auto` 会多花 token 做语言识别并多跑一轮解析（catalog §3.1/§3.4）。
2. 会话内改语言：`session.update` 的 `audio.input.transcription.language`，**必须通过当前 STT/TTS 语言能力校验**，否则 `invalid_request_error`；`auto` 能否复位后端语言取决于 `stt_auto_reset_supported`（部分后端为 `false`）。
3. 让 LLM 跟随用户语言：`enable_lang_prompt: true`（每轮多几条 token）；或让 TTS 跟随助手输出语言：`detect_llm_output_language: true`（启动时预热检测器，首块过短时不下发语言码）。
4. TTS 侧：`qwen3_tts_language` 固定目标语言，`auto` 在混合语种下会串音；`facebookMMS`/`phonon`/`supertonic` 的语言在**加载时或按语言码**决定音色，会话改语言会被拒。
5. 热词/专名：`qwen3_asr_prompt`（过长会抬高每段延迟）。

**验证**：`GET /v1/pool` 正常 + 连续 10 轮混说无语言飘移；TTS 支持语言集见 `s2s_pipeline.py:700-716`（catalog §5.1）。

## S18 · 公网 / 弱网客户端

**现象**：卡顿、爆音、频繁掉线；上行音频被重采样。

**先动**

1. 传输：公网必须 `wss://`；`host`/端口映射与反代一致（catalog §6.1/§6.9）。**Realtime API 本身不做鉴权**，token 与网络隔离在反代层加。
2. 缓冲：客户端 `playback_buffer_ms` 调大（代价：首音更迟）；`chunk_size` 与 `send_rate`/`recv_rate` 对齐 16 kHz。
3. 断线：`connection_retry_timeout_s` 调大（默认 30 s），弱网下不要让它轻易放弃。
4. 事件量：关掉 `enable_live_transcription`（partial 事件在弱网最费带宽）。
5. 远端 STT/TTS 时：`openai_stt_timeout`（默认 60 s）、`openai_stt_max_window_s`、`openai_tts_timeout`（默认 300 s）按链路重设；注意这些超时**过小会丢句、过大在故障时拖住会话**。

**代价**：客户端侧参数是"会话级·重启"，改了要重连；缓冲换来的稳定直接计进用户感知的TTFA。

## S19 · 音色、克隆与品牌声音

**先动**

1. 预置音色：`qwen3_tts_speaker`（CustomVoice，默认 `Aiden`）；会话级 `voice` **只有 `qwen3`（命中支持列表）和 `kitten` 真生效**，其余后端只回显（catalog §5.4）——平台的选择器要按后端置灰。
2. 风格指令：`qwen3_tts_instruct`（VoiceDesign 模型必需）。
3. 克隆：`qwen3_tts_ref_audio` + `qwen3_tts_ref_text`（文本要**逐字**匹配参考音频）；`qwen3_tts_xvec_only: true` 起步更干净、切语言更稳，代价是相似度略降。GGML 路线改用预计算的 `ref_spk` / `ref_rvq`（与 `ref_audio` 互斥/依赖关系见 catalog §5.2）。
4. `qwen3_tts_ref_cache_dir` 要给到持久卷，否则每次重建重算音色向量。
5. 远端音色：`openai` TTS 用 `openai_tts_voice`；裸 `pcm` 必须配对 `openai_tts_sample_rate`（Qwen3-TTS 为 24000）。

**风险**：参考音频是**生物特征**（catalog §5.2 标隐私）——入库需授权，日志与缓存目录同样受约；见 S20。

## S20 · 隐私与合规收尾

**必查清单**

| 项 | 目标取值 | 依据 |
|---|---|---|
| `log_transcripts` | `false` | 日志常被容器与聚合器长期保留，对话会比会话活得更久（catalog §6.6） |
| `USAGE_HASH_SECRET` | 显式固定 | 不设则每次启动换钥，历史 `user_key` 全部失配（§6.5） |
| `MODEL_METRICS_LOG*` | 指到受控卷 + 设滚动上限 | 相对路径未挂卷会随容器销毁丢失 |
| `S2S_ADMIN_TOKEN` / `S2S_INTERNAL_TOKEN` | 必配（fail-closed） | 未配则热更新路由 `503`；配上后泄漏即可改所有在线会话 |
| `enable_llm_proxy` | 默认 `false` | 服务自身不鉴权，开启等于把 LLM 额度交给任意可达客户端 |
| `UNLIMITED_ORGS` / `AUTH_DEBUG` | 生产清空 | 白名单绕配额；调试日志可能落盘身份 |
| `log_transcripts`（客户端） | `false` | 客户端侧也会留文本 |

---

# 第三部分 · 环境档位 × 参数组合速查

> 只列**与库默认不同**的取值，其余保持默认。显存/路数一律回查假设表 §4。

| 档位 | VAD | STT | LLM | TTS | 并发 | 关键取舍 |
|---|---|---|---|---|---|---|
| 12 GB 纯管线盒 + 远程 LLM | `min_silence_ms 450–500`、`min_speech_ms 250`、`short_segment_merge_ms 800`、`speculative/unanswered_reopen_ms 0`、`smart_turn false` | `qwen3-asr` 0.6B / `cuda` / `bfloat16` / `language zh` / `gen_max_new_tokens 128` | `chat-completions` + `reasoning_effort ""` + `stream_batch_sentences 1` | `qwen3` / `torch` / `non_streaming_mode false` / `chunk 4` | **2 路** | 判停优先，量化不动 |
| 12 GB 同机塞 LLM | 同上 | 同上 | `transformers` + `llm_load_in_4bit`（4B 才现实） | 同上，必要时 `ggml` + `Q8_0` | **1 路**（已到 ≈11.6 GB） | 8B/9B 直接放弃同机 |
| 24 GB 单盒 | 同上 | 同上 | 远程或 8B Q4 | 同上 | **4 路**（同机含 8B 时按公式重算，先扣权重与 KV；自包含方案见 `deployment.md` §5） | 压测后再顶格 |
| 多盒（1 LLM 盒 + N 管线盒） | 同上 | 同上 | `-np` 按档设（4B 8–16、8B/9B 4–8，见 `hardware/deployment-multibox.md` §调优） | 同上 | 每盒 2–4 路 | 瓶颈转为 LLM 吞吐与内网 RTT |
| 无 GPU / CPU 演示 | `smart_turn false` | `faster-whisper` + `compute_type int8` | 远程 `chat-completions` | `kokoro`（cpu）或远端 `openai` | 1 路 | 只保证"可用档"P95 ≤2.0 s |
| macOS 本机 | `silero` | `parakeet-tdt` / `whisper-mlx` | `mlx-lm` | `qwen3`（自动 mlx-audio） | 1 路 | `mac_optimal_settings: true` + `example_configs/mac.yaml`；关注 `mlx_lock_*` |
| ARM 边缘（Orin NX 16G） | `silero` | 0.6B `cuda` | 远程 | `attn_implementation eager`、`parity_mode true` | 1 路 | **HT3 未解除**，先测 RTF |
| 噪声门店 | `thresh 0.65–0.7`、`audio_enhancement true`、`min_speech_ms 500`、可换 `vad: firered` | `language zh` 固定 | 同基线 | 同基线 | 减一档 | 误警优先于漏检 |
| 公网弱网 | `min_silence_ms` 偏大更稳 | 远端则调 `openai_stt_*` 超时 | 同基线 | 同基线 | — | 关 `enable_live_transcription`，客户端加 `playback_buffer_ms` |

---

# 第四部分 · 每轮改动后的固定验证动作

1. **配置能被解析**：`speech-to-speech serve -f <profile>.yaml --name <profile>` 起得来；`{env: NAME}` 缺失是**硬报错**，不会回退默认。
2. **服务就绪**：`GET /v1/pool` 返回 `size == num_pipelines` 且 `in_use == 0`。注意主 `docker-compose.yml:67` 的 `healthcheck` **只探 console**（`:8000/api/v1/health`，`start_period` 120 s 留给权重加载），**探不到 pipeline**；其余 6 个 compose 变体连 console 都不探，平台必须自己探 `/v1/pool`（catalog §6.9）。
3. **真在 GPU 上**：对话进行中 `nvidia-smi` 能看到该进程占卡（防 S4 的静默回退）。
4. **一轮真实对话**：`speech-to-speech talk --url ws://127.0.0.1:8765/v1/realtime`，记下 latency 行的四个归因时间戳（假设表 §5）。
5. **并发阶梯**：1→3→5→10→20，按 `hardware/deployment-multibox.md` 的饱和点定义收尾。
6. **判停回归**：静默 60 s 无误触发；短句（"嗯"）能被接住；慢语速整句不被切。
7. **回滚可用**：改动前留 `prod.yaml.bak.<version>`；镜像回退换 `S2S_IMAGE_TAG=<旧>` + `--no-build`（`deployment.md` §8）。

---

# 第五部分 · 反模式（本仓踩过或注释明确禁止的）

| 不要做 | 为什么 |
|---|---|
| 用全局 `device` 代替各组件 `*_device` | 会击穿组件意图，可能 OOM 或直接落 CPU（catalog §6.4） |
| 把环境变量写进 compose 的 `environment:` 又想用平台改 | `environment` 覆盖 `env_file`，平台再也改不动那个值 |
| 调 `min_silence_ms` 来"修"识别错字 | 判停只决定何时结束一句话，正确率属于 STT 模型与 `qwen3_asr_language`/`prompt` |
| `short_segment_merge_ms < min_silence_ms` | hold 先于相邻片段到期，拼接静默失效 |
| 为压延迟把 `qwen3_asr_gen_max_new_tokens` 调到极小 | 长句转写被截断；默认 256 曾出现 47 s/53 s 长尾，生产取 **128** 是有记录的取舍 |
| 把 `voice` 当通用热更新音色开关 | 只有 `qwen3`/`kitten` 真生效，其余后端只回显 |
| 在 12 GB 卡上把 `num_pipelines` 调到 3 | 超出 `floor(×0.85÷4.6)`，池满**不排队**，直接拒绝新会话 |
| 驱动 <580 却换 `Dockerfile.cu130` | TTS/STT **静默**退 CPU，RTF ≈3.7×，且没有任何报错提示 |
| 未配 `S2S_ADMIN_TOKEN` 就依赖 `/admin/sessions/update` | fail-closed，返回 `503 admin_disabled`，看起来像"接口坏了" |
| 打开 `log_transcripts` 做长期排障 | 对话文本进聚合日志，比会话活得更久（隐私） |
