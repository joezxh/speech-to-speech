# S2S 部署参数配置平台设计文档

> 日期：2026-10-23 ｜ 状态：待评审
> 工作目录：`speech-to-speech-src/`
> 配套交付：`docs/parameter-catalog.md`（人读清单）、`docs/parameter-catalog.yaml`（机器可读目录，schema `s2s-parameter-catalog-v1`）
> 边界：**只做设计**。不写平台代码，不改 `speech-to-speech-src` 源码；下文所有"源码改动点"均为设计标注，实施阶段才落地。

## 1. 背景与目标

### 1.1 要解决的问题

当前 S2S 服务的全部业务参数都以两种方式硬编码在部署物里：

1. `docker-compose.yml` 的 `command:` 数组里散落 40+ 个 CLI 开关（`--min_silence_ms 700`、`--qwen3_tts_streaming_chunk_size 4` …）；
2. 少量环境变量（`HF_HUB_OFFLINE`、`GPUSTACK_API_KEY`）靠 `${VAR:-default}` 替换。

带来四个具体痛点：

| 痛点 | 现状证据 | 后果 |
|---|---|---|
| 改参必须手工编辑 compose | `docker-compose.yml:44-101` 全是字面量 | 无审计、无回滚、误改靠 git diff 兜底 |
| 参数含义无单一来源 | 196 个可配字段分散在 40+ 个 `arguments_classes/*.py` | 新人靠读源码猜默认值与合法范围 |
| 热更新能力不可见 | 仅 4 类字段真正可热更（见 §2.2） | 运营以为改 YAML 就能换人设，实际要重启 |
| 危险参数无分级 | `enable_llm_proxy`、`host`、`log_transcripts` 与 `thresh` 平铺在同一命令行 | 误开代理或明文落转写无人拦 |

### 1.2 目标

1. **单一参数目录**：196 条参数带 13 字段元数据与 `file:symbol` 溯源，人和机器可读（`parameter-catalog.{md,yaml}`）。
2. **分层覆盖**：`basic / advanced / expert / ops` 四级暴露，UI 按级别渲染，越界字段不可见。
3. **两条生效链路显式化**：重启链路（容器重建）与热更新链路（会话级 `session.update`），每条都有健康检查与回滚。
4. **配置版本不可变**：每次发布留版本快照与审计记录，回滚 = 指向上一个版本。

### 1.3 非目标

- 不做多实例编排、K8s、灰度发布、跨机调度（单机 compose 是当前唯一部署形态）。
- 不做参数值的自动调优（A/B、自动寻参）。
- 不重写 `arguments_classes`，不改 `config.py` 的 YAML 语义。
- 不实现前端页面、数据库表结构；本文只到 API 契约层。
- 不引入新的鉴权体系；复用 `demo/auth.py` 的 tier 概念与 `demo/limiter.py` 的 sqlite 存储范式。

## 2. 源码配置模型结论

### 2.1 两条独立通道

| 维度 | 通道 A：启动参数 | 通道 B：会话运行时 |
|---|---|---|
| 入口 | `cli.py`（`serve`/`talk`/`local`）+ `arguments_classes/*.py` 的 dataclass；文件模式 `-f/--file` + `--name` | `api/openai_realtime/runtime_config.py:RuntimeConfig` + WebSocket `session.update` 事件 |
| 载体 | CLI 参数，或 YAML（`schema_version: 1`） | OpenAI Realtime 协议 JSON |
| 解析/校验 | `config.py:load_config` → `validate_config` → `resolve_config` | `handlers/session.py:24-77 handle_session_update` → `RuntimeConfig.apply_session_update`（`runtime_config.py:102-105`） |
| 作用域 | 进程 / 容器 | 单条连接（`conn_id`） |
| 生效代价 | 重建容器（秒级到分钟级） | 毫秒级，下一次 LLM/TTS 调用即读到新值 |
| 覆盖面 | 所有 pipeline、所有新老会话 | 仅被点名的连接 |

两条通道**互不知道对方存在**：`RuntimeConfig` 在 `service.py:407-422 register()` 里新建，只从 `self._default_instructions` 取一个字符串种子；启动参数里的 `init_chat_prompt` 通过 `s2s_pipeline.py:635 → 643` 传成 `default_instructions`。这是"改了 YAML 但当前通话没变"的根因。

YAML 模型的关键事实（`config.py:373-445`、`docs/configuration.md:99-134`）：

- 顶层只允许 `schema_version` / `runtime` / `blocks` / `pipelines` 四键，未知键报错；
- `schema_version` 必须是整数 `1`；
- `pipelines.<name>` 只允许 `stages` / `num_pipelines` / `options`，`device` 等进程级覆盖放 `options`；
- `{env: NAME}` 是**流式映射**而非字符串，只能放在标量位置；缺失变量**在 resolve 期报错**，不回退默认值；
- 单文件上限 1 MiB、容器层级上限 32，禁用 anchors/aliases/merge keys/explicit tags。

### 2.2 可热更新字段清单（附证据）

计划初判"7 类字段可热更新"。逐条取证后需要修正——真正改变行为的只有 4 类，另有 2 类是**协议兼容字段**：

| 字段路径 | 真实生效 | 证据 | 平台归类 |
|---|---|---|---|
| `instructions` | 是 | `base_openai_compatible_language_model.py:972-974`、`language_model.py:617-619`：`response.instructions or runtime_config.session.instructions` | 热更新 |
| `audio.input.turn_detection.create_response` | 是 | `runtime_config.py:59-68 create_response_enabled` | 热更新 |
| `audio.input.turn_detection.interrupt_response` | 是 | `runtime_config.py:70-88 interrupt_response_enabled`（缺省 `True`） | 热更新 |
| `audio.input.transcription.language` | 是，带校验 | `handlers/session.py:42-64`：`auto` 需 `stt_auto_reset_supported`，具体值须在 `stt_supported_languages` / `tts_supported_languages` 内；`runtime_config.py:107-115 selected_language` | 热更新 |
| `extensions` | 是 | `runtime_config.py:90-100`，目前只识别 `speech_to_speech.input_audio_transcription.snapshot` | 热更新（仅此一个取值） |
| `audio.output.voice` | **否，仅协议回显** | `handlers/response.py:519-525` 把 voice 回填进 `RealtimeResponse.audio.output.voice` 后返回给客户端；TTS 实际音色来自 `qwen3_tts_speaker` 启动参数 | 协议兼容，不进热更新面板 |
| `model` | **否，仅记日志** | `handlers/session.py:66-68` 只 `logger.info`，不触碰已加载的 LLM 后端 | 协议兼容，同上 |

合并语义（`runtime_config.py:10-24 _apply_update`）：只遍历 `update.model_fields_set`，即**只合并客户端真正发过的字段**，未发字段保持原值；嵌套 BaseModel 递归合并。因此部分更新安全，但"发 `null` 清空"和"不发"是两种语义，平台侧必须区分。

### 2.3 只能重启生效的边界

除上表 4 类字段外，其余全部需要重建容器，包括常被误认为可热更的：

- `init_chat_prompt`（`s2s_pipeline.py:635`）：只作为**新连接**的 `instructions` 种子（`service.py:416`）。改它 = 重启 + 只影响后续新连接，老连接仍持旧人设。这是"半热"状态，平台必须把"改默认人设"拆成两个动作：热更新存量连接 + 重启改未来连接（见 §5.4）。
- `qwen3_tts_speaker`、`qwen3_tts_model_name`：TTS 引擎在启动时加载模型，会话层无法换。
- `num_pipelines`、`device`、`host`、`port`：属进程/容器拓扑。

## 3. 平台架构

### 3.1 五个组件

| 组件 | 职责 | 输入 | 输出 | 明确不做 |
|---|---|---|---|---|
| `catalog_service` | 加载 `parameter-catalog.yaml`，按 `exposure` 过滤字段；提供字段元数据与默认值 | catalog 文件 | 字段列表 JSON | 不校验用户值、不持久化 |
| `store` | 配置版本存储：`profile → 不可变 version 快照`、`draft`、`audit` | draft/publish 请求 | 版本号、快照 | 不解析字段语义 |
| `validator` | 调 `speech_to_speech.config.load_config/validate_config/resolve_config` 做结构校验；再做显存预算与跨字段约束 | YAML 文本 | 错误列表 / `ResolvedConfig` | 不写盘、不调 docker |
| `renderer` | 由 draft 生成 `config/<profile>.yaml` 与 `.env`，旧版备份 | 已校验 draft | 两个文件 + 备份 | 不做健康检查 |
| `compose_runner` | `docker compose` 子进程、`/v1/pool` 探活、失败回滚 | 新版本 | 实例状态 | 不做字段校验 |

### 3.2 组件图

```
                        ┌──────────────────────────────┐
   浏览器 / 运维 CLI ──▶│  catalog_service（只读、无状态）│
                        │  parameter-catalog.yaml       │
                        └───────────────┬──────────────┘
                                        │ 字段元数据 + 暴露级别
                                        ▼
   ┌────────────┐   ① 存 draft   ┌──────────────┐  ② 校验   ┌──────────────────────┐
   │   store    │◀──────────────▶│  validator   │◀─────────▶│ speech_to_speech.    │
   │ 版本 / 审计 │                │  纯函数       │           │ config（load/        │
   └─────┬──────┘                └──────────────┘           │ validate/resolve）    │
         │ ③ publish（版本快照）                              └──────────────────────┘
         ▼
   ┌────────────┐  ④ config/prod.yaml + .env（旧版 .bak）  ┌──────────────────────┐
   │  renderer  │────────────────────────────────────────▶│   compose_runner     │
   └────────────┘                                          └──────────┬───────────┘
                                                                      │ ⑤ docker compose up -d
                                                                      │   --force-recreate pipeline
                                                                      ▼
                                                          ┌──────────────────────┐
                                                          │  pipeline 容器        │
                                                          │  serve -f … --name   │
                                                          │  ⑥ GET /v1/pool 探活  │
                                                          └──────────┬───────────┘
                                                                     │ ⑦ 失败 → 回滚
                                                                     ▼
                                                               store 上一版本
```

### 3.3 依赖方向

`catalog_service` ← `store` ← `validator` ← `renderer` ← `compose_runner`，单向无环。`validator` 是唯一依赖 `speech_to_speech` 包的组件，其余组件只依赖 catalog 文件与文件系统，便于单测。

### 3.4 明确不做的事

- 不管理多台机器、不做容器编排替代品。
- 不在平台侧重新实现参数默认值——默认值一律从 catalog 读，catalog 与源码不一致属 catalog 缺陷。
- 不做"改一个字段就重启一次"，发布是整份 profile 的原子动作。

## 4. 生效链路 A（重启）

适用：除 §2.2 四类字段外的全部参数（约 90%）。

### 4.1 流程

| 步骤 | 动作 | 失败处理 |
|---|---|---|
| 1 | UI 提交 draft（字段 + 值），`store` 记录 `draft` 与 `base_version` | 版本冲突返回 409 |
| 2 | `validator` 用 `load_config` 解析渲染后的 YAML 文本，`validate_config` 做结构校验 | 422，错误带 `file:symbol` 与期望类型 |
| 3 | `validator` 调 `resolve_config`，检查 `{env:}` 引用的变量是否齐备 | 422，指出缺失的变量名（不回退默认） |
| 4 | `validator` 做显存预算：`num_pipelines <= floor(可用显存GB × 0.85 / 4.6)` | 422，给出当前卡型号与允许上限 |
| 5 | publish：`store` 落不可变版本，`renderer` 写 `config/<profile>.yaml` + `.env`，旧文件备份为 `.bak.<version>` | 写失败保留旧文件并告警，版本标 `aborted` |
| 6 | `compose_runner` 执行 `docker compose up -d --force-recreate pipeline` | 读 `docker logs --tail 200`，进步骤 8 |
| 7 | 轮询 `GET /v1/pool` 直到 `size == <num_pipelines>` 且 `in_use` 在下降；超时 180s | 视为失败，进步骤 8 |
| 8 | 回滚：恢复 `.bak.<version>` + 重建容器 + 再探 `/v1/pool` | 回滚也失败 → 告警人工介入，容器保留最近一次日志 |

### 4.2 YAML 如何进容器

文件模式只接受 `-f/--file` 与 `--name`，其余参数必须写进 YAML（`cli.py:_run_file_command`：`File mode accepts only --file and --name`）。因此 compose 服务的 `command` 需要从当前 40+ 个 CLI 开关改为：

```yaml
command: [speech-to-speech, serve, -f, /app/config/prod.yaml, --name, prod]
volumes:
  - ./config:/app/config:ro
```

`serve` 要求恰好选中一个 definition（`cli.py`：`serve and local require exactly one selected definition; use --name`），故 `--name` 不可省。这一改动意味着 **compose 的 command 由平台固定模板生成**，不再手改。

### 4.3 版本状态机

```
draft ──validate──▶ validated ──publish──▶ publishing ──healthcheck ok──▶ live
  │                    │                       │
  └──abandon           └──reject               └──healthcheck fail──▶ rolled_back
                                                                         │
                                                          ──rollback fail──▶ failed(需人工)
```

只有 `live` 与 `rolled_back` 可被 `rollback` 指向；`draft` 不入版本历史。

## 5. 生效链路 B（热更新）

适用：§2.2 表中 4 类字段。

### 5.1 源码最小改动点

| # | 文件 | 改动 | 性质 |
|---|---|---|---|
| 1 | `api/openai_realtime/websocket_router.py` | 在 `create_app()`（当前 `510-514` 行，与 `/v1/pool`、`/v1/usage` 同级）新增 `POST /admin/sessions/update` 路由 | 新增路由，不触碰既有路由 |
| 2 | `api/openai_realtime/service.py` | 新增只读访问器（如 `active_connection_ids()`）暴露 `_conns` 的键集合，供 fanout 枚举；`_conns` 当前仅私有（`service.py:384`） | 新增方法，不改既有逻辑 |
| 3 | （可选）`service.py:register()` | 把单值 `_default_instructions` 换成"平台默认值对象"，让新连接读到最新默认人设 | 后续阶段，非本期必需 |

路由内部：构造 `SessionUpdateEvent` 并逐目标调用 `SessionHandler.handle_session_update`，复用其合并、语言校验、`invalid_session_type` 拒绝逻辑——**不复制一份校验代码**。

### 5.2 鉴权

`S2S_ADMIN_TOKEN` 环境变量提供 token，缺失时路由**一律 503 拒绝**（fail closed，不回退为无鉴权）。请求头 `Authorization: Bearer <token>`，比较用 `hmac.compare_digest`。

### 5.3 请求语义

```http
POST /admin/sessions/update
Authorization: Bearer <S2S_ADMIN_TOKEN>
Content-Type: application/json

{
  "scope": "all",
  "session": {
    "instructions": "你是简洁的语音助手，每次回复不超过两句话，跟随用户语言。",
    "audio": { "input": { "turn_detection": { "interrupt_response": true } } }
  }
}
```

- `scope=all`：向所有 pipeline 的所有活跃连接 fanout；
- `scope=pipeline` + `target=<index>`：只 fanout 该 unit；
- `scope=session` + `target=<session_id>`：只 fanout 单条连接。

响应返回 `{"updated": [...], "failed": [{"session_id": ..., "error": ...}]}`。部分失败不整体回滚——热更新是幂等覆盖写。

### 5.4 行为约束（必须写进 UI 文案）

| 约束 | 原因 | 后果 |
|---|---|---|
| 只影响**当前活跃**连接 | fanout 基于 `_conns` | 新连接读 `init_chat_prompt`，与热更新值可能不一致 |
| 空闲 unit 无连接可 fanout | `unit.session is None` | "改默认人设"必须同时改 YAML 并重启，否则重启后又回到旧默认 |
| 不支持 `transcription` 类型会话 | `handlers/session.py:36-40` 返回 `invalid_session_type` | 必须用 `realtime` 类型会话 |
| `language` 必须被活跃后端支持 | `handlers/session.py:52-63` | `auto` 需 `stt_auto_reset_supported`，否则 400 |
| `model` / `voice` 不生效 | §2.2 取证 | UI 不得把这两个字段放进热更新面板 |

## 6. 参数条目规范

每个参数一条记录，13 字段（10 基础 + 3 平台扩展）。YAML 目录用同名 14 字段（多一个 `stage` 分组键）。

| # | 字段 | 含义 | 取值/约束 | 示例 |
|---|---|---|---|---|
| 1 | 参数名称 | 源码字段名或 YAML 路径 | 与源码逐字一致 | `min_silence_ms` |
| 2 | 作用 | 一句话说明对人可感知的影响 | 不写实现细节 | 「判定用户说完话所需的静音时长」 |
| 3 | 模块/文件 | 字段定义位置 | 文件名 + 符号 | `arguments_classes/vad_arguments.py:min_silence_ms` |
| 4 | 默认值 | 源码默认值 | 必须带 `file:symbol` 溯源 | `700` |
| 5 | 范围/格式 | 类型与合法区间 | 枚举需列全 | `int, 0..2000` |
| 6 | 必填 | 是否必须显式给出 | `是` / `否` | `否` |
| 7 | 来源优先级 | 取值链 | 见 §8 | `yaml > env > default` |
| 8 | 生效方式 | 何时生效 | `启动` / `热更新` / `启动+热更新` / `固定` | `启动` |
| 9 | 建议暴露 | 默认暴露级别 | `basic` / `advanced` / `expert` / `ops` | `advanced` |
| 10 | 风险 | 配错的表现 | 一句话，可操作 | 「过高→开头被截，过低→误触噪首」 |
| 11 | 暴露级别 | 最终分级（可被 profile 覆盖） | 同字段 9 | `advanced` |
| 12 | 影响面 | 改动波及范围 | `process` / `pipeline` / `session` / `container` | `pipeline` |
| 13 | 变更代价 | 生效所需时间 | `seconds` / `restart` / `minutes` | `restart` |

`stage` 枚举固定为 `vad|stt|llm|tts|runtime|server|client|deploy|env`，通用层参数 `backend: null`。

## 7. 暴露分级策略

### 7.1 判定条件

按"谁能改、改错的后果有多重"四级判定，**取最严格的那一级**：

| 级别 | 判定条件（满足任一即归入） | 典型字段 |
|---|---|---|
| `basic` | 语义对非工程人员直观；配错最坏结果是体验差，不会不可用 | `instructions`、`voice`（展示用）、`min_silence_ms` |
| `advanced` | 需要懂音频/模型基础；配错会导致断句异常或音质劣化，但服务仍可用 | `thresh`、`qwen3_tts_streaming_chunk_size`、`stream_batch_sentences` |
| `expert` | 需要懂推理栈与硬件；配错可能 OOM、崩进程或显著变慢 | `num_pipelines`、`device`、`qwen3_tts_max_new_tokens`、`smart_turn` 相关阈值 |
| `ops` | 触碰安全边界、隐私数据或环境绑定；**改错会泄露、越权或换环境失效** | `host`、`enable_llm_proxy`、`*_api_key`、`log_transcripts`、`HF_HUB_OFFLINE` |

### 7.2 `ops` 必须标注风险类别

`exposure=ops` 的条目在 catalog 中 `risk` 字段必填，且必须能归入以下三类之一：

| 类别 | 判据 | 代表字段 | 平台动作 |
|---|---|---|---|
| **安全** | 扩大攻击面或绕过鉴权 | `host=0.0.0.0`（`/v1/*` 无鉴权）、`enable_llm_proxy`（自带代理无鉴权）、`responses_api_api_key` | 只允许管理员改；改 `host` 需二次确认；密钥只写不读 |
| **隐私** | 会落盘或外泄用户语音/文本 | `log_transcripts`（落转写全文）、`log_level=debug`（含内容） | 默认关闭；开启需审计记录操作人 |
| **环境绑定** | 换机器/换镜像后取值失效 | `HF_HUB_OFFLINE`、`TRANSFORMERS_OFFLINE`、GPU `device_ids`、端口映射、`qwen3_*_model_name` 路径 | 标记"随环境变化"；回滚时不跨环境复用 |

目录中 `ops` 条目共 52 条，全部带风险描述。

## 8. 来源优先级

### 8.1 主链路

```
显式 YAML 字段 / CLI 参数（最高）
  > {env: NAME} 引用（缺失即报错，不回退默认值）
    > dataclass 字段默认值（最低）
```

注意 `{env: NAME}` 不是"更低的优先级"，而是**延后取值的显式值**：写它就等于声明"这个值必须来自环境"，因此环境缺失是硬错误而非回退到默认（`docs/configuration.md:112`：`Missing explicit environment values fail even when a backend has a credential fallback`）。

### 8.2 覆盖型规则

| 规则 | 出处 | 说明 |
|---|---|---|
| `device` 覆盖 `*_device` | `module_arguments.py:device` | 进程级 `device` 一旦显式给出，覆盖各组件自己的 `*_device` |
| `mac_optimal_settings` 提供预设 | `module_arguments.py:mac_optimal_settings` | 预设先铺底，同名字段的显式值再覆盖预设 |
| `pipelines.<name>.options` 覆盖 `runtime` | `config.py` 三层结构 | pipeline 级选项优先于进程级 runtime |
| `session.update` 覆盖已解析会话字段 | `runtime_config.py:10-24` | 只合并 `model_fields_set` 中的字段 |
| `response.instructions` 覆盖会话 `instructions` | `base_openai_compatible_language_model.py:972-974` | 单次响应可临时覆盖人设 |
| `init_chat_prompt` 仅作新连接种子 | `s2s_pipeline.py:635-643` → `service.py:416` | 不改已有连接 |

### 8.3 平台侧落地

`validator` 必须按此顺序复算，**不允许**在平台侧再定义一套默认值：默认值一律读 catalog（其 `default` 与 `source_ref` 同源）。

## 9. 与既有能力复用

| 既有能力 | 出处 | 复用方式 | 不复用/不复制的部分 |
|---|---|---|---|
| `/v1/pool` | `websocket_router.py:639-674` | 健康检查数据源：`{size, in_use, units[{index, state, session_id, draining_for_s, stuck_for_s}]}`，`state ∈ idle/active/draining/stuck` | 不新增探活端点；`stuck` 单独告警 |
| `/v1/usage` | `websocket_router.py:615-637` | 监控源：逐 unit 汇总 + `llm_proxy` 段 | 不重算指标 |
| `demo/auth.py` | `attach(app)`（`:62`）、`resolve_identity`（`:263`）、`resolve_tier`（`:216`）、`set_anon_cookie`（`:288`） | 管理端沿用 tier 概念区分管理员/运营 | 管理 API 用独立 token，不复用匿名 cookie 路径 |
| `demo/limiter.py` | `begin/heartbeat/end/sweep`（`:179/:200/:235/:251`）、`budget_for`（`:56`）、`sign_cookie`/`verify_cookie` | 平台 `store` 沿用其 sqlite3 + 每日份额 + 签名 cookie 范式 | 不把配置版本混进 usage 库 |
| `utils/model_monitor.py` | `METRICS_LOG_PATH`（`:50`）、`MAX_BYTES`（`:51`）、`BACKUPS`（`:52`） | 作为"模型调用耗时"监控字段的数据源 | 不改造其轮转逻辑 |
| `docs/configuration.md` | `99-134`（值/路径/校验语义） | 作为 YAML 语义的**唯一权威引用** | catalog 不复制其语法说明，只给结论并链接 |

## 10. 安全与回滚

### 10.1 安全

| 项 | 要求 |
|---|---|
| 管理 API 鉴权 | 独立 `ADMIN_TOKEN`（Bearer），与匿名/免费 tier 完全隔离；token 只从环境读，不入库、不回显 |
| 角色 | `admin`（可发布/回滚/改 `ops` 字段）、`operator`（只能改 `basic/advanced` 并发起 draft） |
| 密钥字段 | 只写不读：读接口一律返回 `***`，长度与字符集不外泄 |
| 明文配置 | `config/*.yaml` 只放 `{env: NAME}`，真实密钥只进 `.env`（`0600`） |
| 审计 | 每次 draft/publish/rollback 记录：操作人、版本号、字段 diff、结果、耗时 |
| 网络暴露 | 平台默认只监听 `127.0.0.1`；`/v1/*` 无内建鉴权（`realtime_server_arguments.py:6-12` 的 `host` 默认即 `127.0.0.1`），不得因为平台上线而把 `host` 改成 `0.0.0.0` 却仍暴露公网 |

### 10.2 回滚

- 配置版本**不可变**：publish 产生新版本，旧版本永不改写；回滚 = 指向上一个 `live` 版本并重新执行链路 A 的步骤 5-7。
- 回滚粒度是整份 profile，不是单字段（单字段回滚 = 编辑新 draft 后发布）。
- 回滚触发条件：步骤 6 容器退出、步骤 7 探活超时、`/v1/pool` 出现 `stuck`。
- 连续两次回滚失败 → 停止自动重试，保留现场（容器与日志），转人工。

## 11. 测试策略

### 11.1 已完成（本次交付）

| 测试 | 方法 | 结果 |
|---|---|---|
| catalog 结构约束 | 脚本读 `parameter-catalog.yaml`：schema 固定、14 字段齐全、枚举合法、`ops` 必有 `risk`、`effect=hot` 必为 `impact=session`、`(stage,backend,name)` 唯一且升序 | 通过（196 条，0 错误） |
| catalog 默认值 ↔ 源码（131 条全量） | 逐条 import `arguments_classes` 的 dataclass，比对字段默认值与 catalog `default` | 通过（131 条一致，0 处不符） |
| `ops` 风险类别覆盖 | 52 条 `ops` 条目的 `risk` 必须含「安全/隐私/环境绑定」之一 | 通过（安全 14 / 隐私 3 / 环境绑定 35） |
| 样例可解析 | `docs/parameter-catalog.md` 附录 A.1 的 YAML 片段落盘后调 `load_config` + `validate_config` + `resolve_config` | 通过（`pipelines=['prod']`） |
| `{env:}` 语义 | 移除 `GPUSTACK_API_KEY` 后 `resolve_config` 应报错 | 通过（`ConfigurationError`） |
| 未知字段拒绝 | 把 `min_silence_ms` 改成 `min_silence_ms_typo` | 通过（`ConfigurationError`） |

### 11.2 实施阶段已补

实现在 `tests/test_param_platform.py`（40 项）与
`tests/openai_realtime/test_websocket_router.py::TestAdminHotUpdate`（6 项），
均不需要 docker、GPU 或外部数据库。回滚用例只替换 `compose_runner.recreate` /
`wait_healthy` / `read_pool` 三个出网/出进程调用，文件写入、`.bak.<version>` 备份与
还原走真实实现；真实 `compose up`、真崩的容器与显存实测仍需在部署机上验证。

| 测试 | 断言 |
|---|---|
| catalog ↔ 源码一致性 | 遍历 `arguments_classes/*.py` 的 dataclass 字段，与 catalog 的 `name` 集合比对，缺一即失败（防止源码加字段后 catalog 漂移） |
| `validator` 黄金用例 | `example_configs/mac.yaml` 必须通过；故意改坏 `schema_version`、顶层多键、`num_pipelines: "2"`（字符串）三种必须失败 |
| `renderer` 幂等 | 同一 draft 渲染两次输出字节完全一致（便于 diff 与审计） |
| 回滚测试 | 发布一个 `num_pipelines` 超显存上限的版本 → 必须被步骤 4 拦下；发布会崩的版本（如错误模型路径）→ 必须自动回滚到上一 `live` |
| 热更新隔离 | 两个并发连接，`scope=session` 只改一条，另一条 `session.updated` 不出现 |
| 密钥不泄露 | 读 draft/publish 响应与审计日志，全文搜索密钥字面量必须 0 次命中 |

### 11.3 与 `docs/configuration.md` 的一致性

catalog 与本文不得重新定义 YAML 语义。核对点：`{env:}` 是映射且缺失即错、路径字段按 YAML 目录解析、1 MiB/32 层限制、未知键拒绝——四项均为引用而非改写。

## 12. 风险清单

| # | 风险 | 触发条件 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | `num_pipelines` 撞显存 | 每路 ≈4.6GB（`nvidia-smi` 实测），12GB 卡上限 2 路 | OOM，连带现有会话抖动 | `validator` 强制显存预算；发布前必须过步骤 4 |
| R2 | `enable_llm_proxy` 无自带鉴权 | 开启后代理端点对 `host` 暴露 | 任意人可消耗 LLM 额度 | 归 `ops`-安全；开启需管理员 + 二次确认；`host` 保持 `127.0.0.1` |
| R3 | `log_transcripts` 隐私 | 开启后转写全文落盘 | 用户语音内容泄露 | 归 `ops`-隐私；默认关闭；开启写审计 |
| R4 | `host=0.0.0.0` 暴露未鉴权 API | `/v1/realtime`、`/v1/pool`、`/v1/usage` 均无鉴权 | 任意人可占用会话、读用量 | 归 `ops`-安全；默认 `127.0.0.1`；容器内需 `0.0.0.0` 但只映射到回环或前置反代 |
| R5 | 热更新与新连接默认值不一致 | 只做热更新不改 YAML | 重启后回退旧人设，运营误判 | §5.4 写入 UI；"改默认"必须同时走链路 A |
| R6 | catalog 与源码漂移 | 源码新增字段但未更新 catalog | 平台看不到新参数，或被误认为已覆盖 | §11.2 一致性测试；catalog 记录 `generated_from` commit |
| R7 | YAML 与 CLI 双写冲突 | compose 同时留 CLI 开关与 `-f` 文件 | 文件模式拒绝 CLI 参数，容器直接退出 | §4.2 固定模板；发布前 grep 校验 compose 不含业务 CLI 开关 |
| R8 | 回滚跨环境复用 | 换机器后回滚到旧版本 | 旧路径/旧设备号在新机不存在 | §7.2 环境绑定类不进回滚候选；回滚前重跑 `validator` |
| R9 | `{env:}` 写成字符串 | 手写 `"{env: NAME}"`（带引号） | 被当作字面量密钥，服务报鉴权失败或静默用错 key | catalog 与本文均标注"是映射，不能加引号"；`validator` 检测字符串形如 `{env:` 时告警 |
| R10 | 部分 fanout 失败被忽略 | 热更新多连接时个别失败 | 部分用户仍是旧人设，状态不一致 | 响应返回 `failed[]`；UI 提示重试 |

## 13. 附录 A：管理 API 契约

### A.0 通用约定

| 项 | 约定 |
|---|---|
| Base | `http://127.0.0.1:<admin_port>/admin`，与 `/v1/*` 不同端口或不同前缀 |
| 鉴权 | `Authorization: Bearer <ADMIN_TOKEN>`；缺失/错误 → `401 unauthorized`；token 未配置 → `503 admin_disabled` |
| 并发控制 | 写操作带 `If-Match: <version>`；不匹配 → `409 version_conflict` |
| 内容类型 | `application/json; charset=utf-8` |
| 密钥字段 | 响应中一律 `***` |
| 审计 | 所有写操作产生 `audit_id`，随响应返回 |
| 错误体 | `{"error": {"code": "...", "message": "...", "details": [...]}}`（`message` 不含输入值，避免泄露密钥） |

### A.1 `GET /admin/catalog`

返回字段目录（可按级别过滤）。

| 项 | 内容 |
|---|---|
| Query | `exposure=basic,advanced`（可选，逗号分隔）；`stage=vad`（可选）；`backend=silero`（可选） |
| 200 响应 | `{"schema": "s2s-parameter-catalog-v1", "generated_from": "speech-to-speech-src@<commit>", "parameters": [{stage, backend, name, type, default, choices, required, source_priority, effect, exposure, impact, change_cost, risk, source_ref}]}` |
| 错误 | `401`、`503` |

### A.2 `GET /admin/profiles/{id}/draft`

| 项 | 内容 |
|---|---|
| 200 响应 | `{"profile": "prod", "base_version": 7, "draft": {"<field_path>": <value>}, "updated_at": "...", "updated_by": "..."}` |
| 错误 | `401`、`404 unknown_profile` |

### A.3 `POST /admin/profiles/{id}/draft`

| 项 | 内容 |
|---|---|
| 请求体 | `{"patch": {"vad.min_silence_ms": 700, "llm.responses_api_api_key": "<secret>"}, "base_version": 7}` |
| 200 响应 | `{"draft": {...}, "validation": {"ok": true, "resolved_pipelines": ["prod"]}, "audit_id": "..."}` |
| 语义 | 局部覆盖（patch 语义），`null` 表示"回退到 catalog 默认值"；密钥字段落库加密、读取返回 `***` |
| 错误 | `400 invalid_parameter`（未知字段/级别越权）、`409 version_conflict`、`422 validation_failed`（附 `details[{field, expected, got, source_ref}]`）、`401`、`403 forbidden`（operator 改 `ops` 字段） |

### A.4 `POST /admin/profiles/{id}/publish`

| 项 | 内容 |
|---|---|
| 请求体 | `{"base_version": 7, "note": "把判停从 700 调到 900"}` |
| 200 响应 | `{"version": 8, "status": "live", "healthcheck": {"pool_size": 2, "in_use": 0}, "duration_s": 41.2, "audit_id": "..."}` |
| 流程 | 即 §4.1 步骤 2-7；返回 `status` 为 `live` 或 `rolled_back` |
| 错误 | `409 publish_in_progress`、`422 validation_failed`、`422 vram_budget_exceeded`（`details` 含 `max_allowed`）、`500 render_failed`、`502 compose_failed`、`504 healthcheck_timeout`（已自动回滚，`status=rolled_back`） |

### A.5 `POST /admin/profiles/{id}/rollback`

| 项 | 内容 |
|---|---|
| 请求体 | `{"target_version": 7, "note": "v8 探活超时"}` |
| 200 响应 | `{"version": 9, "rolled_back_to": 7, "status": "live", "audit_id": "..."}` |
| 语义 | 回滚产生**新版本号**（9），不删除 v8；`rolled_back_to` 指向被恢复的内容版本 |
| 错误 | `404 unknown_version`、`409 version_not_rollbackable`（目标非 `live`/`rolled_back`）、`422 validation_failed`（重跑校验失败，如换机后路径失效）、`502`、`504` |

### A.6 `POST /admin/sessions/update`

热更新，需 §5.1 的源码改动生效后才可用；未改动时该端点返回 `501 not_implemented`（平台提示"走链路 A"）。

| 项 | 内容 |
|---|---|
| 请求体 | `{"scope": "all"|"pipeline"|"session", "target": <index|session_id>|null, "session": {<OpenAI Realtime session 部分字段>}}` |
| 允许字段 | `instructions`、`audio.input.turn_detection`、`audio.input.transcription.language`、`extensions`（§2.2） |
| 200 响应 | `{"updated": ["<session_id>", ...], "failed": [{"session_id": "...", "error": "invalid_request_error"}], "audit_id": "..."}` |
| 语义 | 逐连接调用 `SessionHandler.handle_session_update`；部分失败不回滚 |
| 错误 | `400 unsupported_field`（如提交 `model`/`voice`）、`400 invalid_request_error`（语言不被后端支持、`auto` 不可重置）、`422 invalid_session_type`（transcription 会话）、`401`、`503` |

### A.7 `GET /admin/instances`

| 项 | 内容 |
|---|---|
| 200 响应 | `{"profile": "prod", "version": 8, "container": {"name": "…-pipeline-1", "status": "running", "started_at": "…", "image": "…"}, "pool": {"size": 2, "in_use": 1, "units": [{"index": 0, "state": "active", "session_id": "…"}, {"index": 1, "state": "idle", "session_id": null}]}, "usage": {...}}` |
| 数据来源 | `docker inspect` + `GET /v1/pool`（`websocket_router.py:639`）+ `GET /v1/usage`（`:615`） |
| 语义 | 只读聚合视图；`state=stuck` 时响应附 `alerts: ["unit stuck"]` |
| 错误 | `502 pool_unreachable`（容器在但 `/v1/pool` 不可达，通常意味着容器内服务崩溃）、`401` |
