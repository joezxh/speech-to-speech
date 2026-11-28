# s2s-agent 内嵌模式与 `/v1/agent/*` 接口

`speech-to-speech serve --with-agent` 把运维代理（s2s-agent）拉进**主服务同一个进程**，
并把它的能力以 REST 接口发布到主服务端口（默认 `8765`）——与既有的 `/v1/pool`、
`/v1/usage`、`/v1/audio/*` 同一套风格、同一份 Swagger 文档。

- [1. 两种部署形态](#1-两种部署形态)
- [2. 启用方式](#2-启用方式)
- [3. 环境变量清单](#3-环境变量清单)
- [4. 通用约定](#4-通用约定)
- [5. 只读观测接口](#5-只读观测接口)
- [6. 触发与管控接口](#6-触发与管控接口)
- [7. 状态机与失败语义](#7-状态机与失败语义)
- [8. 与 console 侧接口的方向关系](#8-与-console-侧接口的方向关系)
- [9. Swagger UI](#9-swagger-ui)
- [10. 自检清单](#10-自检清单)

---

## 1. 两种部署形态

| 形态 | 启动方式 | agent 与 pipeline 的关系 | 重启类命令 |
|---|---|---|---|
| 独立进程（既有） | `python -m speech_to_speech.agent`（supervisor 的 `[program:s2s-agent]`） | 两个进程 | `reboot` / `config_restart` 可用 |
| 内嵌（本次新增） | `speech-to-speech serve --with-agent` | 同一进程、同一个停止事件 | `reboot` / `config_restart` **不可用**（见 §7.4） |

两种形态共用同一份实现（`src/speech_to_speech/agent/embedded.py`），
因此心跳协议、配置同步流程、命令白名单、退避策略完全一致，不存在「两份实现漂移」。

内嵌形态下 agent 不是语音链路的前置条件：它的任何失败都只记录到
`/v1/agent/status` 的 `last_error` 并退避重试，**不会中断通话**。

---

## 2. 启用方式

### 2.1 命令行开关

```bash
# 显式开启：serve 启动时一并拉起 agent
speech-to-speech serve -f config/prod.yaml --name prod --with-agent

# 显式关闭：覆盖环境变量 S2S_AGENT_AUTOSTART=true
speech-to-speech serve -f config/prod.yaml --name prod --no-with-agent
```

- 开关只对 **`serve`** 生效。`talk` / `local` 传入 `--with-agent` 会直接报错退出；
  仅由环境变量打开时打印一条警告并忽略，不会让这些命令启动失败。
- 开关在 `parse_command` **之前**被剥离，因此 `-f` 配置文件模式不会把它当成未知参数报错。
- `speech-to-speech --help` 会打印 agent 开关说明。

### 2.2 环境变量

```bash
S2S_AGENT_AUTOSTART=true    # 等价于 --with-agent；命令行开关优先级更高
```

取值同布尔开关：`1/true/yes/on` 为真，`0/false/no/off`（含空串）为假，
其它值视为配置错误并以退出码 2 结束（错误信息里点名该变量）。

### 2.3 必需配置

内嵌形态下 agent 要向 console 上报状态，因此这两个变量必须配置：

| 变量 | 含义 |
|---|---|
| `S2S_AGENT_CONSOLE_URL` | console 控制面基址，例如 `http://console:8000` |
| `S2S_AGENT_MACHINE_ID` | 本机标识，例如 `node-a` |

### 2.4 快速失败

缺配置时**在加载任何模型之前**就报错退出（退出码 2），避免「模型都加载完了才发现
agent 起不来」：

```text
Configuration error: the embedded agent needs S2S_AGENT_CONSOLE_URL and S2S_AGENT_MACHINE_ID; set them (or drop --with-agent) before starting the server.
```

---

## 3. 环境变量清单

| 变量 | 默认值 | 作用 |
|---|---|---|
| `S2S_AGENT_AUTOSTART` | `false` | 是否随 `serve` 启动 agent |
| `S2S_AGENT_CONSOLE_URL` | 空 | console 控制面基址（必填） |
| `S2S_AGENT_MACHINE_ID` | 空 | 本机标识（必填） |
| `S2S_AGENT_REGISTER_CODE` | 空 | 一次性注册码；没有令牌时用它换令牌 |
| `S2S_AGENT_TOKEN_FILE` | `/run/s2s-agent/token` | 机器令牌落盘路径（0600） |
| `S2S_AGENT_HEARTBEAT_S` | `15` | 心跳间隔（秒） |
| `S2S_AGENT_PIPELINE_LOG` | `/var/log/supervisor/pipeline-stdout.log` | 时延采集的日志来源 |
| `S2S_AGENT_TARGET_YAML` | 空 | 配置同步落地目标 YAML |
| `S2S_AGENT_DECLARATION` | `/app/config/agent.yaml` | 负载声明文件（含 `effects` 分流表） |
| `S2S_AGENT_DEPLOYMENT_MANIFEST` | `/app/config/deployment-manifest.json` | 声明式部署参数来源 |
| `S2S_AGENT_SUPERVISOR_SOCKET` | `/run/s2s-console/supervisor.sock` | supervisor XML-RPC socket |
| `S2S_AGENT_SUPERVISOR_PROGRAM` | `pipeline` | supervisor 里的程序名 |
| `S2S_AGENT_LOG_MAX_LINES` | `500` | 容器日志单次最大行数 |
| `S2S_AGENT_PIPELINE_HOST` | `127.0.0.1` | 热更新目标主机（配置同步用） |
| `S2S_AGENT_PIPELINE_PORT` | 取声明文件 / `8765` | 热更新目标端口（配置同步用） |
| `S2S_ADMIN_TOKEN` | 空 | `/v1/agent/*` 触发类接口的 Bearer 令牌（fail-closed） |
| `S2S_INTERNAL_TOKEN` | 空 | 热更新会话时访问 `/internal/sessions/update` 的令牌 |

---

## 4. 通用约定

### 4.1 路径与分组

- 路径前缀 `/v1/agent/`，与 `/v1/audio/*`（能力）、`/v1/pool`、`/v1/usage`（观测）同层。
- Swagger UI 中归入 **「运维代理」** 分组，与「实时对话」「音频能力」「LLM 代理」「观测与运维」并列。

### 4.2 鉴权：读写分离

| 类别 | 端点 | 鉴权 |
|---|---|---|
| 只读观测 | `status` / `capability` / `workloads` / `metrics` / `deployment` / `usage` | 无（与 `/v1/pool`、`/v1/usage` 一致） |
| 触发与管控 | `heartbeat` / `config/sync` / `commands/poll` / `commands` / `register` / `drain` / `logs` | `Authorization: Bearer <S2S_ADMIN_TOKEN>` |

触发类接口 **fail-closed**：

- `S2S_ADMIN_TOKEN` 未配置 → `503 admin_disabled`（**绝不**等于「不鉴权」）；
- 令牌不匹配 → `401 unauthorized`；
- 比对使用 `hmac.compare_digest`，不做前缀比较。

### 4.3 错误信封与错误码

所有错误统一为：

```json
{"error": {"code": "agent_busy", "message": "another agent action is already running", "details": []}}
```

| `code` | HTTP | 含义 | 处理建议 |
|---|---|---|---|
| `agent_disabled` | 503 | 服务未以 `--with-agent` 启动 | 用 `--with-agent` 重启 |
| `admin_disabled` | 503 | 未配置 `S2S_ADMIN_TOKEN` | 配置令牌（fail-closed，不可绕过） |
| `unauthorized` | 401 | 令牌缺失或不匹配 | 带上正确的 Bearer 头 |
| `invalid_request_error` | 400 | 请求体非法 / 命令类型不在白名单 | 修正请求 |
| `agent_busy` | 409 | 另一个 agent 动作正在执行 | 稍后重试 |
| `agent_not_registered` | 409 | 没有机器令牌且无法注册 | 配置注册码或手工放置令牌 |
| `console_unreachable` | 502 | console 不可达 | 检查 console 与网络 |
| `agent_error` | 500 | 其它执行失败 | 看 `details` / 服务端日志 |

> 语义要点：**503 优先于 400/401**。请求体再离谱，只要 agent 没开，先回
> `503 agent_disabled`——调用方据此判断「这个能力有没有部署」，而不是去猜参数错误。

### 4.4 阻塞与并发

- 所有会阻塞的动作（console 往返、`nvidia-smi` 子进程、文件读）都在工作线程里执行，
  事件循环不被占用，语音链路的实时性不受影响。
- **single-flight**：任一时刻只允许一个 agent 动作在跑。并发触发返回 `409 agent_busy`，
  而不是排队——命令「领到即被 console 标记 dispatched」，重复执行有副作用（重启、排空）。
- 只读采集器有短 TTL 缓存：`workloads` 2 秒、`metrics` 2 秒、`deployment` 5 秒；
  日志不缓存（必须是最新的）。

---

## 5. 只读观测接口

### 5.1 `GET /v1/agent/status` — agent 运行态快照

免鉴权。

**响应字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | agent 已随本进程启动（恒为 `true`；未启用时接口直接 503） |
| `running` | bool | 常驻循环是否在跑 |
| `embedded` | bool | 是否内嵌形态（内嵌为 `true`） |
| `registered` | bool | 本机是否已有机器令牌 |
| `machine_id` | string | 本机标识 |
| `console_url` | string | console 基址 |
| `heartbeat_interval_s` | int | 心跳间隔（秒） |
| `agent_version` | string | agent 版本（随包版本） |
| `uptime_s` | number | agent 存活秒数 |
| `ticks` | int | 已完成轮次 |
| `last_tick_at` | string/null | 最近一轮完成时间（UTC ISO-8601） |
| `last_heartbeat_at` | string/null | 最近一次心跳成功时间 |
| `last_heartbeat_ok` | bool | 最近一次心跳是否成功 |
| `last_config_sync_at` | string/null | 最近一次配置同步时间 |
| `last_command_at` | string/null | 最近一次命令执行时间 |
| `last_error` | string | 最近一次失败（`TypeName: message`），无失败为空串 |
| `last_error_at` | string/null | 最近失败时间 |
| `backoff_s` | number | 当前退避时长（秒） |
| `next_action_in_s` | number | 距下一次动作的秒数 |

```bash
curl http://localhost:8765/v1/agent/status
```

```json
{
  "enabled": true, "running": true, "embedded": true, "registered": true,
  "machine_id": "node-a", "console_url": "http://console:8000",
  "heartbeat_interval_s": 15, "agent_version": "0.4.0",
  "uptime_s": 312.4, "ticks": 20,
  "last_tick_at": "2026-11-18T09:00:12Z", "last_heartbeat_at": "2026-11-18T09:00:11Z",
  "last_heartbeat_ok": true, "last_error": "", "backoff_s": 1.0, "next_action_in_s": 12.5
}
```

### 5.2 `GET /v1/agent/capability` — 能力与就绪自检

免鉴权。

**响应字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `agent_version` | string | agent 版本 |
| `protocol_version` | int | 上报协议版本（当前 `1`） |
| `capabilities` | string[] | 上报给 console 的能力声明 |
| `actions` | string[] | 本实例可执行的管控动作 |
| `embedded` | bool | 是否内嵌形态 |
| `restart_supported` | bool | 是否支持重启类命令（内嵌形态为 `false`） |
| `console_url` | string | console 基址 |
| `console_configured` | bool | 是否配置了 console 地址 |
| `machine_id` | string | 本机标识 |
| `machine_configured` | bool | 是否配置了机器标识 |
| `register_code_configured` | bool | 是否配置了注册码 |
| `token_ready` | bool | 令牌是否就绪 |
| `pipeline_reachable` | bool | 本机 pipeline 观测端点是否可达 |

```bash
curl http://localhost:8765/v1/agent/capability
```

### 5.3 `GET /v1/agent/workloads` — 本机负载清单

免鉴权。返回 `{"workloads": [...]}`。

**每项字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `kind` | string | 负载类型（如 `pipeline`） |
| `engine` | string | 引擎名 |
| `model` | string | 模型名 |
| `port` | int | 监听端口 |
| `vram_gb` | number/null | 实测显存占用 |
| `health_path` | string | 健康探测路径 |
| `listen` / `public_addr` | string | 监听地址 / 对外地址 |
| `params` | object | 对应 block 的参数（密钥类已掩码为 `***`） |

```bash
curl http://localhost:8765/v1/agent/workloads
```

### 5.4 `GET /v1/agent/metrics` — 节点资源指标

免鉴权。

| 字段 | 类型 | 说明 |
|---|---|---|
| `cpu_pct` | number/null | CPU 使用率 |
| `load_avg` | number[] | 1/5/15 分钟负载 |
| `mem_total_gb` / `mem_used_gb` / `mem_pct` | number/null | 内存总量 / 用量 / 使用率 |
| `gpu_name` | string/null | GPU 型号 |
| `gpu_util_pct` | int/null | GPU 利用率 |
| `gpu_mem_total_gb` / `gpu_mem_used_gb` | number/null | GPU 显存总量 / 用量 |
| `pipeline_vram_gb` | number/null | pipeline 进程显存 |
| `collected_at` | string | 采集时间 |

拿不到的字段一律 `null`，不猜。

```bash
curl http://localhost:8765/v1/agent/metrics
```

### 5.5 `GET /v1/agent/deployment` — 部署参数

免鉴权。

| 字段 | 类型 | 说明 |
|---|---|---|
| `runtime` | object | 运行时**生效**的配置值 |
| `declared` | object | 仓库**声明**的部署参数 |

密钥类参数（键名含 `key` / `token` / `secret` / `password` / `credential`）一律掩码为 `***`。

```bash
curl http://localhost:8765/v1/agent/deployment
```

### 5.6 `GET /v1/agent/usage` — pipeline 累计用量

免鉴权。与 `GET /v1/usage` **同源同值**（同一个聚合函数，读的是进程内的 pipeline pool，
不是 HTTP 自调用），字段包括 `input_tokens`、`output_tokens`、`responses_completed`、
`responses_cancelled`、`turns`、`audio_duration_s`、`total_tokens`、`total_errors`、
`errors_by_type`。

```bash
curl http://localhost:8765/v1/agent/usage
```

---

## 6. 触发与管控接口

以下接口全部要求 `Authorization: Bearer <S2S_ADMIN_TOKEN>`。

### 6.1 `POST /v1/agent/heartbeat` — 立即执行一次心跳

不等下一个心跳周期，立刻向 console 上报一次机器状态。

**请求参数**：无。

**响应字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `sent` | bool | 心跳是否已发出 |
| `heartbeat` | object | 本次心跳体（`protocol_version` / `agent_version` / `machine` / `capabilities` / `workloads` / `runtime` / `tokens`） |
| `console` | object | console 的响应 |

```bash
curl -X POST http://localhost:8765/v1/agent/heartbeat \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```

### 6.2 `POST /v1/agent/config/sync` — 立即执行一轮配置同步

完整跑一遍：拉取 console 渲染好的配置 → 原子替换本机 YAML → 按 `effects` 分流
（`hot` 热更新会话 / `start` 重启 / `container` 仅登记）→ 回报实际生效值 → 确认。

**请求参数**：无。

**响应字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `changed` | bool | 是否有新版本落地（`false` 表示 console 侧返回 304） |
| `ack` | object/null | 确认回执 |

> 内嵌形态下 `start` 类参数**不会**重启宿主进程（从进程内部重启自己不可行），
> 会明确失败而不是假装生效；`hot` 类参数只下发明确是会话字段的键
> （`instructions` / `voice` / `modalities` / `temperature` / `turn_detection` 等），
> 其余键会记录一条告警。

```bash
curl -X POST http://localhost:8765/v1/agent/config/sync \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```

### 6.3 `POST /v1/agent/commands/poll` — 拉取并执行待办命令

**请求参数（query）**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `limit` | int | `10` | 单次拉取条数，服务端裁剪到 `1..50` |

**响应字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `count` | int | 本次执行条数 |
| `receipts[].command_id` | string | 命令 ID |
| `receipts[].kind` | string | 命令类型 |
| `receipts[].ok` | bool | 是否成功 |
| `receipts[].result` | object | 执行结果 |
| `receipts[].error` | string | 失败原因（成功时为空串） |

```bash
curl -X POST "http://localhost:8765/v1/agent/commands/poll?limit=10" \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```

### 6.4 `POST /v1/agent/commands` — 执行一条指定命令

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `kind` | string | 是 | 命令类型，见下表；不在白名单 → `400 invalid_request_error` |
| `payload` | object | 否 | 命令参数，默认 `{}` |

| `kind` | 作用 | `payload` |
|---|---|---|
| `drain` | 排空本机实例 | 无 |
| `resume` | 恢复本机实例 | 无 |
| `reboot` | 经 supervisor 重启 pipeline | 无（内嵌形态不支持） |
| `config_restart` | 先同步配置再重启 pipeline | 无（内嵌形态不支持） |
| `recover` | 恢复调度并巡检实例 | 无 |
| `health_check` | 真探测某服务的健康端点 | `service_id`（必填） |

**响应字段**：`ok`（bool）、`result`（object）、`error`（string）。

```bash
curl -X POST http://localhost:8765/v1/agent/commands \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"health_check","payload":{"service_id":"pipeline"}}'
```

### 6.5 `POST /v1/agent/register` — 用注册码换取机器令牌

**请求参数**：无。

**响应字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `registered` | bool | 是否注册成功 |
| `machine_id` | string | 本机标识 |
| `token_file` | string | 令牌落盘路径 |

响应**不含令牌本身**。未配置注册码或 console 未返回令牌 → `409 agent_not_registered`。

```bash
curl -X POST http://localhost:8765/v1/agent/register \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```

### 6.6 `POST /v1/agent/drain` — 排空 / 恢复本机实例

**请求体**

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `drain` | bool | `true` | `true` 排空（新会话不再进入本机），`false` 恢复 |

**响应字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `drain` | bool | 本次写入的期望态 |
| `console` | object | console 的响应 |

```bash
curl -X POST http://localhost:8765/v1/agent/drain \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"drain": true}'
```

### 6.7 `GET /v1/agent/logs` — 读取容器日志

返回 `{"logs": [...]}`，每项含 `source`（`stdout` / `stderr`）与 `lines`（字符串数组）。
已做有界截断（默认 500 行 / 200 KiB，`S2S_AGENT_LOG_MAX_LINES` 可调）与脱敏
（`api_key`、`token`、`secret`、`password` 与 `sk-` 开头的密钥替换为 `***`）。

日志属运维敏感数据，因此需要鉴权。

```bash
curl http://localhost:8765/v1/agent/logs \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```

### 6.6 模型重载命令 `model_reload`

console 向机器下发 `model_reload`，agent 收到后在 **pipeline 进程内**重建
ASR / LLM / TTS 中的单模块或任意组合，不重启进程、不阻塞心跳。
首期严格复用**当前内存配置**（用途：恢复卡死/损坏模型、换权重文件后不重启），
不应用新配置；若需变更模型参数或后端类型，仍走 `config_restart`。

#### 6.6.1 命令与参数

```json
{
  "kind": "model_reload",
  "payload": {
    "modules": ["asr", "llm"],
    "scope": "all",
    "unitIndex": null,
    "drain": true,
    "drainTimeoutMs": 5000,
    "configVersion": "v12",
    "reason": "console"
  }
}
```

- `modules`：白名单 `asr`/`llm`/`tts`；非空、去重、按 `asr→llm→tts` 规范化。
- `scope`：`all`（全部实例）或 `unit`（`unitIndex` 必填）。
- `drain`：默认 `true`，标记维护态并等待在途会话排空；超时即失败，不杀会话。
- `drainTimeoutMs`：排空超时，默认 5000ms。
- `configVersion`：仅信息性标注；`reason`：审计标注。

console API 用 camelCase（与现有 `serviceId` 一致），agent 内部统一 snake_case；
命令队列表的 `payload` JSON 列原样持久化，本期无需新迁移。
该命令使用独立长 TTL（600s，可通过 `TTL_BY_KIND` 配置），避免重建耗时被 120s 默认 TTL 误判 expired。

#### 6.6.2 回执语义（accepted + progress + 终态）

`execute` 同步返回 accepted，重建在独立工作线程进行，进度与终态持续 `report_command`：

```json
{"status": "accepted", "stage": "queued"}
{"status": "progress", "progress": {"stage": "rebuild_asr", "elapsedMs": 1840}}
{"status": "succeeded", "reloadedModules": ["asr", "llm"], "targetUnits": [0], "ready": true}
{"status": "failed", "failedStage": "rebuild_tts", "failedModule": "tts", "ready": false}
```

阶段序列：`maintenance_set` → `drain` → `cleanup_*` → `rebuild_*` → `ready`。
`drain` 阶段失败（会话未排空）解除维护态恢复可用；`rebuild` 阶段失败 **fail-closed**，
目标实例保持维护态，不允许半重建实例继续接会话。
全局单飞锁保证同一时刻仅一个重载任务；单实例重建时目标实例置维护态，
`/v1/pool` 以 `state=maintenance` 展示并计入 `in_use`，分配器不会再派会话。

#### 6.6.3 单模块与组合逻辑

- `asr`：退役旧 STT（**不发 `PIPELINE_END` 哨兵**，避免级联停链），复用内存 `BackendSelection` 重建，
  并重接 `vad.streaming_stt_sink`、`window_partials_enabled`、LiveKit `SttHandlerAdapter`、内嵌 SenseVoice 引用。
- `llm`：远程 OpenAI 兼容后端受锁 `reconfigure()`，替换 client / `_async_client` / `_async_runner` /
  `_extra_body` / compactor 并关闭旧客户端，保留对话历史；本地后端走 handler 重建。
- `tts`：原位替换 TTS handler（列表索引不变），保持下游处理链。
- 组合与 `scope=all`：统一排空 → 统一清理 → 按 `asr→llm→tts` 逐个重建；
  任一阶段失败即停止后续模块并按上述 fail-closed 规则处理。

独立进程 agent（无 pool，能力未声明 `model_reload`）收到该命令降级为 `config_restart`；
内嵌 agent 但协调器缺失时明确失败，不静默成功。

#### 6.6.4 自检

```bash
# 1) 能力声明（内嵌 agent 且协调器就绪时应含 model_reload）
curl http://localhost:8765/v1/agent/capability -H "Authorization: Bearer $S2S_ADMIN_TOKEN"

# 2) 触发单模块重载
curl -X POST http://localhost:8765/v1/agent/commands \
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"kind":"model_reload","payload":{"modules":["asr"],"scope":"all"}}'

# 3) 观察目标实例状态与回执
curl http://localhost:8765/v1/pool
```

---

## 7. 状态机与失败语义

### 7.1 一轮 tick 的动作顺序

agent 的常驻循环与手动触发共用同一份实现，一轮的顺序固定：

```text
取机器令牌（没有就用注册码换一个）
  → 读本机累计用量，算出窗口增量
  → 组心跳体（版本 / GPU / 负载清单 / 运行时参数 / token 增量）并上报 console
  → 配置同步：拉取 → 原子落地 YAML → 按 effects 分流 → 回报 → 确认
  → 命令轮询：拉取本机待办命令 → 逐条执行 → 逐条回执
  → 日志上传（每 4 轮一次）
  → 时延采集（读 pipeline 日志里的时延行，只推进游标）
```

任何一步失败都**不会**中断这一轮后续步骤里除该步以外的部分，也不会抛出到语音链路。

### 7.2 退避

一轮失败后按指数退避重试：`1s → 2s → 4s → … → 60s`（封顶），成功后立刻复位到 `1s`。
当前退避时长在 `/v1/agent/status` 的 `backoff_s` 里可见。

### 7.3 忙碌与并发

- 后台 tick 与手动触发共用一把 single-flight 锁。
- 后台 tick 在跑时手动触发 → `409 agent_busy`。
- 手动触发在跑时后台 tick 到来 → 后台这一轮退避后重试，不打断手动动作。

### 7.4 内嵌形态的限制

内嵌形态下 **pipeline 就是当前进程**，因此：

| 能力 | 内嵌形态 | 说明 |
|---|---|---|
| `drain` / `resume` / `recover` / `health_check` | 可用 | 只影响 console 侧的期望态或做只读探测 |
| `reboot` / `config_restart` | **不可用** | 返回 `ok=false`、`result.reason="not_supported_in_embedded_mode"`；需要重启请走部署侧的 supervisor |

`GET /v1/agent/capability` 的 `restart_supported` 字段即表示这一点。

---

## 8. 与 console 侧接口的方向关系

两套接口方向相反，不要混淆：

```text
console（控制面）  ──调用──▶  agent ──上报/拉取──▶  console（控制面）
console ──HTTP──▶ pipeline 的 /v1/agent/*  （本次新增：运维直接观察与触发）
```

- console 侧 `/api/v1/agent/*`（`register` / `heartbeat` / `config` / `commands` / `logs`）
  是 **agent 调 console** 用的协议，方向是「agent → console」；
- 本文的 `/v1/agent/*` 是 **运维/平台调 pipeline** 用的接口，方向是「调用方 → pipeline」。

两者共用同一个 agent 实例：pipeline 侧的触发动作最终仍落到 console 上，
因此 console 侧看到的实例状态与 pipeline 侧一致。

---

## 9. Swagger UI

服务启动后，13 个新接口全部出现在运行时 Swagger UI 的 **「运维代理」** 分组里，
可展开查看中文摘要、Markdown 说明、参数表、响应示例与错误码说明：

```text
http://localhost:8765/docs
```

- OpenAPI 原文：`http://localhost:8765/openapi.json`
- 接口是否启用与 Swagger 无关：未开 `--with-agent` 时接口仍会出现，只是调用返回
  `503 agent_disabled`。这样「这个能力存不存在」和「这个能力有没有开」是两个可分辨的事实。

---

## 10. 自检清单

```bash
# 1) agent 已启用且在跑
curl -s http://localhost:8765/v1/agent/status | jq '{enabled, running, registered, ticks}'

# 2) 控制台与令牌就绪
curl -s http://localhost:8765/v1/agent/capability | jq '{console_configured, machine_configured, token_ready, pipeline_reachable}'

# 3) 触发类接口需要令牌（未配置 S2S_ADMIN_TOKEN 时应回 503 admin_disabled）
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8765/v1/agent/heartbeat

# 4) 带令牌触发一次心跳
curl -s -X POST http://localhost:8765/v1/agent/heartbeat -H "Authorization: Bearer $S2S_ADMIN_TOKEN" | jq '{sent}'

# 5) 未启用 agent 的实例应回 503 agent_disabled
curl -s http://localhost:8765/v1/agent/status | jq '.error.code'
```
