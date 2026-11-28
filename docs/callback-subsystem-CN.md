# 可配置回调子系统说明

回调子系统（spec 2026-11-25 §8）由三部分组成：console 后端的配置面（两张表 + REST API + 「回调管理」页）、serve 进程内的分发器 `speech_to_speech/callback/dispatcher.py`（TTL 热加载目标 → 协议适配 → 线程池异步投递 → 投递日志落库）、以及 LiveKit worker 的双路输出口（`emit_segments`）。本文所有字段名、路由、默认值均对照本仓实际代码（`console/backend/app/models/callbacks.py`、`alembic/versions/0015_callback_subsystem.py`、`app/routers/callbacks.py`、`app/services/callback_service.py`、`app/schemas/callbacks.py`、`src/speech_to_speech/callback/dispatcher.py`、`src/speech_to_speech/livekit_worker/events.py`）。

## 1. 数据模型

### 1.1 `callback_target`（回调目标配置）

唯一约束：`name`（`uq_callback_target_name`）。

| 列 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `id` | Integer | PK | |
| `name` | String(128) | NOT NULL，UNIQUE | 目标名，console 内唯一，重名报 400 |
| `target_type` | String(16) | NOT NULL | `java` \| `python`，决定协议适配分支 |
| `base_url` | String(512) | NOT NULL | java：服务基址（投递时拼接固定内部端点）；python：完整 webhook URL |
| `auth_type` | String(16) | NOT NULL，server_default `"none"` | `none` \| `bearer` \| `header_token`；java 目标被 service 强制为 `header_token` |
| `auth_header_name` | String(128) | NULL | `header_token` 的头名；service 校验时缺省补 `X-Callback-Token`（java 目标实际固定用 `X-Internal-Token`） |
| `auth_token` | String(512) | NOT NULL，server_default `""` | 令牌明文入库；**API 输出恒为脱敏串**（见 §6 mask_token） |
| `extra_headers` | JSON | NOT NULL，server_default `"{}"` | 附加请求头（如 java 的 `tenant-id`） |
| `timeout_ms` | Integer | NOT NULL，server_default `"3000"` | 单次投递超时，schema 限制 100–60000 |
| `retry_max_attempts` | Integer | NOT NULL，server_default `"3"` | 最大尝试次数，schema 限制 1–10 |
| `retry_backoff_ms` | Integer | NOT NULL，server_default `"500"` | 首次退避毫秒，schema 限制 0–60000 |
| `events` | JSON | NOT NULL，server_default `"[]"` | 订阅事件类型数组，取值见 `EVENT_TYPES`；不能为空数组 |
| `filters` | JSON | NULL | 事件过滤：`{"speakers": ["user-a", ...], "min_text_len": 4}`，仅支持这两个键；只作用于 `transcript` 事件 |
| `enabled` | Boolean | NOT NULL，server_default `"1"` | 启用位；dispatcher 只加载 enabled=true 的目标 |
| `updated_by` | String(64) | NOT NULL，server_default `""` | 最后操作人（console 用户名） |
| `created_at` / `updated_at` | DateTime(timezone=True) | NOT NULL，`utcnow` / onupdate `utcnow` | |

### 1.2 `callback_delivery_log`（投递日志，每次尝试一行）

索引：`ix_cdl_target_id`、`ix_cdl_triggered_at`、`ix_cdl_status`。

| 列 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `id` | Integer | PK | |
| `target_id` | Integer | NULL，FK `callback_target.id` ON DELETE `SET NULL` | 软关联：目标删除后日志保留（审计口径） |
| `event_type` | String(32) | NOT NULL | 本行对应的投递事件类型 |
| `triggered_at` | DateTime(timezone=True) | NOT NULL | 写日志时**不显式传值**，由 ORM `default=utcnow` 在 flush 时填充（显式传 None 会违例） |
| `request_url` | String(1024) | NOT NULL | 本行尝试的完整 URL |
| `request_payload` | Text | NOT NULL，default `""` | 截断后的请求体 JSON（2000 字符上限，超出追加 `...(truncated)`） |
| `attempt` | Integer | NOT NULL，default `1` | 第几次尝试（1 起计） |
| `http_status` | Integer | NULL | HTTP 状态码；网络异常（未拿到响应）为 NULL |
| `response_snippet` | Text | NOT NULL，default `""` | 响应体片段，截断 200 字符 |
| `duration_ms` | Integer | NOT NULL，default `0` | 本行尝试耗时 |
| `status` | String(16) | NOT NULL | `success` \| `retrying` \| `failed` |
| `error` | String(1024) | NOT NULL，default `""` | 失败原因（网络异常为 `类型: 消息`，截 500 字符入库） |

迁移：`0015_callback_subsystem`（revises `0014_comments_backfill`），PostgreSQL 下对两张表补挂中文注释，SQLite 方言跳过。

## 2. API 清单

路由前缀 `/api/v1/callbacks`（`app/routers/callbacks.py`），统一成功信封 `{"code": 200, "message": "success", "data": ...}`。鉴权：JWT Bearer；查询类需权限码 `console:callback:query`，写操作需 `console:callback:manage`。

### 2.1 列表：`GET /api/v1/callbacks/targets?page=1&pageSize=50`

```bash
curl "http://127.0.0.1:8765/api/v1/callbacks/targets?page=1&pageSize=50" \
  -H "Authorization: Bearer <JWT>"
```

```json
{
  "code": 200, "message": "success",
  "data": {
    "list": [{
      "id": 1, "name": "meeting-java", "targetType": "java",
      "baseUrl": "http://ai-server:8086", "authType": "header_token",
      "authHeaderName": "X-Internal-Token", "authToken": "real***oken",
      "extraHeaders": {"tenant-id": "1"}, "timeoutMs": 3000,
      "retryMaxAttempts": 3, "retryBackoffMs": 500,
      "events": ["transcript"], "filters": null, "enabled": true
    }],
    "total": 1, "page": 1, "pageSize": 50
  }
}
```

### 2.2 创建：`POST /api/v1/callbacks/targets`

请求体（camelCase，`CallbackTargetCreate` 校验：`targetType ∈ {java, python}`、`authType ∈ {none, bearer, header_token}`、`events` 非空且取值合法、`filters` 仅允许 `speakers`/`min_text_len`、java 目标仅支持 `["transcript"]` 且鉴权固定 `header_token`、`name` 全局唯一）：

```bash
curl -X POST http://127.0.0.1:8765/api/v1/callbacks/targets \
  -H "Authorization: Bearer <JWT>" -H "Content-Type: application/json" \
  -d '{
    "name": "meeting-java",
    "targetType": "java",
    "baseUrl": "http://ai-server:8086",
    "authType": "header_token",
    "authHeaderName": "X-Internal-Token",
    "authToken": "real-token-value",
    "extraHeaders": {"tenant-id": "1"},
    "timeoutMs": 3000,
    "retryMaxAttempts": 3,
    "retryBackoffMs": 500,
    "events": ["transcript"],
    "filters": null,
    "enabled": true
  }'
```

响应：`data` 即 2.1 中单目标形状（`authToken` 已脱敏）。校验失败返回 `{"code": 400, "message": "<CallbackServiceError 文案>", ...}`（`invalid_request`）。

### 2.3 更新：`PUT /api/v1/callbacks/targets/{target_id}`

请求体与创建相同（全字段回传）；目标不存在 → 404。前端从详情整行回传时 `authToken` 是脱敏串（含 `***`）：service 检测到 `***` 就保留 DB 中已存旧 token，避免脱敏串覆盖真实凭据。

### 2.4 删除：`DELETE /api/v1/callbacks/targets/{target_id}`

成功返回 HTTP 204 无响应体；不存在 → 404。日志表中该目标的 `target_id` 置 NULL，日志保留。

### 2.5 批量：`POST /api/v1/callbacks/targets/batch`

```bash
curl -X POST http://127.0.0.1:8765/api/v1/callbacks/targets/batch \
  -H "Authorization: Bearer <JWT>" -H "Content-Type: application/json" \
  -d '{"ids": [1, 2], "action": "disable"}'
```

```json
{"code": 200, "message": "success", "data": {"updated": 2}}
```

`action ∈ {enable, disable, delete}`：enable/disable 返回 `{"updated": N}`，delete 返回 `{"deleted": N}`；其它值 400。

### 2.6 连接测试：`POST /api/v1/callbacks/targets/{target_id}/test`

发送一条固定内容的测试 transcript 事件（`roomSid="console-test"`、`identity="console"`），**同步**返回结果；固定 1 次尝试、不写 `callback_delivery_log`，请求构造与真实投递复用同一 `build_request`/`deliver_once`，保证形状一致。

```json
{"code": 200, "message": "success",
 "data": {"ok": true, "httpStatus": 200, "durationMs": 12, "error": ""}}
```

失败时 `ok=false`，`httpStatus` 为 null（网络异常）或实际状态码，`error` 为响应片段/异常摘要（截 200 字符）。

### 2.7 投递日志：`GET /api/v1/callbacks/logs?targetId=&status=&page=&pageSize=`

```bash
curl "http://127.0.0.1:8765/api/v1/callbacks/logs?targetId=1&status=failed&page=1&pageSize=50" \
  -H "Authorization: Bearer <JWT>"
```

```json
{
  "code": 200, "message": "success",
  "data": {
    "list": [{
      "id": 3, "targetId": 1, "eventType": "transcript",
      "triggeredAt": "2026-11-25T07:30:12.345000Z",
      "requestUrl": "http://ai-server:8086/admin-api/ai/meeting/internal/transcript?roomSid=room-1",
      "requestPayload": "[{\"speakerIdentity\": \"user-a\", \"text\": \"大家好\", \"startTs\": 1732500000123, \"endTs\": 1732500003456, \"audioLevel\": -12}]",
      "attempt": 1, "httpStatus": 502,
      "responseSnippet": "<html>Bad Gateway</html>",
      "durationMs": 18, "status": "retrying",
      "error": "HTTP 502"
    }],
    "total": 1, "page": 1, "pageSize": 50
  }
}
```

`triggeredAt` 经 `iso_utc` 输出 UTC ISO 8601（`Z` 后缀）。相关端点：console 前端「回调管理」页的实时字幕页签消费 `GET /api/v1/live-transcripts/stream`（SSE，订阅进程内 `TranscriptEventBus`，需 `console:callback:query`），见 [livekit-worker-integration-CN.md](./livekit-worker-integration-CN.md)。

## 3. 事件 payload

### 3.1 统一事件 JSON（`TranscriptEvent.to_payload()`，python 目标投递体）

固定字段：`eventType`、`roomSid`、`identity`、`text`、`startTs`、`endTs`、`timestamp`；`audioLevel` 仅非 None 时出现；`extra`（SER/声纹等扩展字段）平铺合并进顶层。

`transcript`（worker 转写分段，带 SER 标注）：

```json
{
  "eventType": "transcript",
  "roomSid": "room-1",
  "identity": "user-a",
  "text": "大家好，我们开始今天的会议",
  "startTs": 1732500000123,
  "endTs": 1732500003456,
  "timestamp": 1732500003500,
  "audioLevel": -12,
  "serEmotion": "calm",
  "serConfidence": 0.87,
  "serModel": "sensevoice"
}
```

`session_end`（房间断开时由 `worker._emit_session_end` 产出；`audio_level=None`、`extra={}`）：

```json
{
  "eventType": "session_end",
  "roomSid": "room-1",
  "identity": "",
  "text": "",
  "startTs": 0,
  "endTs": 1732503600000,
  "timestamp": 1732503600000
}
```

事件类型全集 `EVENT_TYPES = ("transcript", "segment_attributed", "session_end")`；当前 worker 实际产出 `transcript` 与 `session_end` 两种。

### 3.2 java 目标投递体（TranscriptSegmentVO 数组）

java 分支把统一事件降维成源工程 Java 侧 `TranscriptSegmentVO` 兼容形状，**数组**为请求体；`audioLevel` 仅非 None 时出现，`extra` 同样平铺合并：

```json
[
  {
    "speakerIdentity": "user-a",
    "text": "大家好，我们开始今天的会议",
    "startTs": 1732500000123,
    "endTs": 1732500003456,
    "audioLevel": -12,
    "serEmotion": "calm",
    "serConfidence": 0.87
  }
]
```

## 4. 协议适配矩阵

`dispatcher.build_request(event, config)` 按 `target_type` 分支（spec §8.2）：

| 维度 | java 目标 | python 目标 |
|---|---|---|
| URL | `{base_url}` + 固定路径 `/admin-api/ai/meeting/internal/transcript`（`JAVA_TRANSCRIPT_PATH`） | `{base_url}` 即完整 webhook URL，原样投递 |
| query 参数 | `roomSid={event.room_sid}`（`deliver_once` 附加） | 无 |
| 请求体 | `TranscriptSegmentVO` 数组（§3.2） | 统一事件 JSON（§3.1） |
| 事件类型 | 仅 `transcript`（console 创建/更新时 service 强制，其它值 400） | `transcript`/`segment_attributed`/`session_end` 任意组合 |
| 鉴权头 | 固定 `X-Internal-Token: {auth_token}`（忽略 `auth_type` 字段；console 侧强制 java 目标 `authType=header_token`） | 按 `auth_type`：`none` 不加头；`bearer` 加 `Authorization: Bearer {auth_token}`；`header_token` 加 `{auth_header_name}: {auth_token}`，头名缺省 `X-Callback-Token` |
| `tenant-id` 头 | `setdefault("tenant-id", MEETING_TENANT_ID 环境变量，默认 "1")`：`extra_headers` 显式配置了 `tenant-id` 时以配置优先 | 不自动添加，需要时经 `extra_headers` 自行配置 |
| 头合并顺序 | `extra_headers` → `X-Internal-Token`（同名覆盖）→ `tenant-id`（setdefault 不覆盖已有） | `extra_headers` → 鉴权头（同名覆盖） |

`MEETING_INTERNAL_TOKEN` / `X-Internal-Token` 细节：分发器本身不读 `MEETING_INTERNAL_TOKEN`——该变量只服务两处：① worker 拉取 SER 开关快照（`ser_provider.fetch_switch_snapshot`，同样带 `X-Internal-Token` + `tenant-id` 头）；② dispatcher 的 **env 兜底 java 目标**（§5），其 `auth_token` 取自 `MEETING_INTERNAL_TOKEN`。在 DB 配置的 java 目标中，令牌是 `callback_target.auth_token` 列本身。Java 侧校验失败返回 `MEETING_INTERNAL_TOKEN_INVALID`（快照端点密钥无效另用错误码 `1_040_064_003`）。

## 5. 热加载与 env 兜底语义

- **TTL 缓存**：`CallbackDispatcher._load_targets` 以 `time.monotonic()` 维护 5 秒 TTL（`DEFAULT_TTL_SECONDS = 5.0`）缓存已启用目标列表；构造参数 `ttl_seconds` 可覆盖（测试用 0）。
- **`invalidate_cache()`**：清空缓存（`_cache=None`、`_cache_at=0`），下一次 `_load_targets` 立即重读 DB。console 的写 API（创建/更新/删除/批量）当前**不**主动调用它——配置变更经下一轮 TTL（最长 5s）自然生效，**无需重启 worker 或 serve**；该方法保留给测试与需要立即生效的调用方（并发竞态下最多延后一个 TTL，语义不变）。
- **DB 可用时 env 兜底失效**：DB 查询成功即返回 DB 配置（**包括空列表**——此时没有任何目标、env 也不兜底）。也就是说 `JAVA_CALLBACK_BASE`/`MEETING_INTERNAL_TOKEN` 只在 DB 不可达时才产生投递目标。
- **DB 查询失败**：`logger.warning("callback targets DB query failed; falling back to env target")` 后回落 env 兜底目标（不写入 TTL 缓存，下次投递重试 DB）。env 兜底目标：`name="env-java-fallback"`、`target_type="java"`、`base_url=JAVA_CALLBACK_BASE`、`X-Internal-Token: MEETING_INTERNAL_TOKEN`、`extra_headers={"tenant-id": MEETING_TENANT_ID（默认 "1"）}`、超时 3000ms、重试 3 次、退避 500ms、仅订阅 `transcript`——与源工程 `worker.py push()` 行为一致，保持零 DB 部署可用。
- **console 后端不可导入**（`get_dispatcher()` 拿不到 `app.db.database.SessionLocal`，如不带 `--with-console` 的独立 serve）：`session_factory=None` 进入 env 兜底模式——仅当 `JAVA_CALLBACK_BASE` 与 `MEETING_INTERNAL_TOKEN` **同时非空**时生成上述内存 java 目标；此模式下投递日志不落库，改由 `logger.info("callback(env) %s attempt=%d status=%s")` 记录。

## 6. 投递语义

- **异步与隔离**：`dispatch(event)` → 过滤（订阅事件类型 + `filters.speakers`/`min_text_len`，过滤器只作用于 transcript）→ 每个目标一个线程池任务（`ThreadPoolExecutor(max_workers=8)`，线程名前缀 `callback`）；单目标失败只记日志，不影响其它目标与转写主流程。worker 侧入口 `publish_transcript(room_sid, segments)` 逐段产出 transcript 事件。
- **指数退避重试**：尝试次数 `retry_max_attempts`（默认 3）；两次尝试间 sleep `retry_backoff_ms × 2^(attempt-1)`（默认 500ms → 第 1 次失败后 500ms、第 2 次失败后 1000ms）；仅当「还有下一次尝试」时退避。2xx 即成功返回；非 2xx 与网络异常都计入重试。
- **每次尝试一行日志**：`success` / `retrying` / `failed` 三种状态（见 §1.2）；日志落库失败仅 `logger.exception`，不中断投递。
- **最终失败不重投**：所有尝试耗尽后写一行 `failed` 日志并 `logger.warning("callback %s -> %s 最终失败: %s")`，没有死信队列、不会重投；补投手段是目标端拉取或人工重放。
- **顺序语义**：异步投递按段并发，同房间 transcript 的到达顺序为 best-effort；需要严格保序的场景由目标端按 `startTs` 排序。
- **退出/测试冲刷**：`flush_pending(timeout=10)` 等待在途投递完成，`timeout` 是总预算（多个在途任务按剩余时间分配，耗尽抛 `TimeoutError`）；`pending_count()` 查询在途数。
- **token 脱敏 `mask_token`**（dispatcher 与 console service 同规则）：长度 ≥ 10 时输出 `前4位***后4位`（如 `real***oken`），长度 < 10 或空输出 `***`。作用点在 **API 输出侧**：所有读接口返回的 `authToken` 恒为脱敏串；投递日志只存截断后的请求体 JSON 与响应片段，**不含鉴权头**，天然不落 token 明文。

## 7. 部署配置手册（2026-11-27 实测）

### 7.0 前置：迁移

回调子系统依赖 `0015_callback_subsystem`（两张表）与 `0016_agent_config_hash_len`。
**console 容器启动命令自带 `alembic upgrade head`**（`docker-compose.split.yml` console 服务），
新库/升级库随 console 重启自动完成；手动执行：

```bash
cd console/backend && PYTHONPATH=. python -m alembic upgrade head
# 验证
psql ... -c "SELECT version_num FROM alembic_version"   # → 0016_agent_config_hash_len
psql ... -c "SELECT to_regclass('public.callback_target'), to_regclass('public.callback_delivery_log')"
```

### 7.1 本地调试（已全链路实测 ✅）

**① 起本地 webhook 接收器**（模拟业务方，`scripts/callback_receiver.py`）：

```bash
python scripts/callback_receiver.py --port 9101 --token local-dev-callback-token
# 可选 --fail-first 2：前 2 次返回 500，验证 dispatcher 重试与日志三态
curl http://127.0.0.1:9101/health   # {"ok":true,"received":{},"attempts":0}
```

**② console 配置 python 目标**（页面「回调管理」或 API）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/callbacks/targets \
  -H "Authorization: Bearer <JWT>" -H "Content-Type: application/json" -d '{
    "name": "local-receiver", "targetType": "python",
    "baseUrl": "http://127.0.0.1:9101/hook",
    "authType": "header_token", "authHeaderName": "X-Callback-Token",
    "authToken": "local-dev-callback-token",
    "timeoutMs": 3000, "retryMaxAttempts": 3, "retryBackoffMs": 500,
    "events": ["transcript"], "filters": {"min_text_len": 1}, "enabled": true }'
```

> `filters.min_text_len` 建议设 1：否则短句（"嗯"、"好"）被过滤，容易误判为"回调不工作"。

**③ 连接测试**：`POST /api/v1/callbacks/targets/{id}/test` → `{"ok":true,"httpStatus":200,"durationMs":10}`。
实测 token 脱敏正确（`loca***oken`）。

**④ 分发器级端到端**（真实 `CallbackDispatcher` + DB 目标 + 日志落库，实测输出）：

```python
from app.db.database import SessionLocal                      # console/backend 在 sys.path
from speech_to_speech.callback.dispatcher import get_dispatcher
from speech_to_speech.livekit_worker.events import TranscriptEvent

d = get_dispatcher()
assert d._session_factory is not None     # None = env 兜底模式，不落库
d.dispatch(TranscriptEvent(event_type="transcript", room_sid="e2e-local-test",
    identity="user-a", text="...", start_ts=..., end_ts=..., audio_level=-12,
    timestamp_ms=...))
d.flush_pending(timeout=15)
```

接收器 `--fail-first 2` 时的实测 `callback_delivery_log`（三态完整）：

| attempt | http | status | 耗时 | 说明 |
|---|---|---|---|---|
| 1 | 500 | `retrying` | 25ms | 第一次失败 |
| 2 | 500 | `retrying` | 5ms | 退避 500ms 后重试 |
| 3 | 200 | `success` | 6ms | 退避 1000ms 后成功 |

日志查询：

```sql
SELECT attempt, http_status, status, duration_ms, error, response_snippet
FROM callback_delivery_log WHERE request_url LIKE '%9101%' ORDER BY id;
```

### 7.2 容器发布（40.30 分裂部署）

**镜像包含性（无需重建）**：`Dockerfile.agent` 全量 `COPY src`（含 `speech_to_speech/callback/`）、
`Dockerfile.console` 全量 `COPY console/backend`（含 `routers/callbacks.py`）。
40.30 现役镜像的增量层构建于 2026-11-26 17:33，晚于 callback 代码入库（09:43）→ 已包含。

**关键约束：pipeline 容器内 dispatcher 的两条路径**（`dispatcher.py get_dispatcher`）：

| 路径 | 前提 | 投递日志 |
|---|---|---|
| **DB 配置** | `app.db.database.SessionLocal` 可导入 → 需要 `--with-console` 且 `CONSOLE_HOME` 存在。**`s2s-agent` 镜像不含 `console/backend`**，直接 `--with-console` 会因 `CONSOLE_HOME` 缺省路径不存在而失败 | 落 `callback_delivery_log`，console 页面可查 |
| **env 兜底** | `JAVA_CALLBACK_BASE` + `MEETING_INTERNAL_TOKEN` 同时非空（`session_factory=None` 时） | 仅 stdout（`callback(env) ...`），不落库 |

**模式 A：env 兜底（零镜像改动，推荐先打通）**：

> **worker 启用方式（file 模式）**：`serve -f` 拒绝 `--with-livekitworker` flag
> （`cli.py:355-359`），正确做法是 YAML `runtime.livekit_worker.enabled: true`
> （40.30 的 `config.split.2/prod.yaml:153-154` **已配置**）。仅 agent 模式才用 flag。

```yaml
# config.split.0.6b.2/prod.yaml
runtime:
  livekit_worker:
    enabled: true
```

```bash
# prod.env 追加（config.split.0.6b.2/prod.env，与 java 会议侧约定一致；值惰性读取，改后重建容器）：
JAVA_CALLBACK_BASE=http://ai-server:8086     # java ai-server 基址
MEETING_INTERNAL_TOKEN=<与 java 侧 meeting.internal-transcript-token 严格一致>
MEETING_TENANT_ID=1                          # 缺省即 1，可省
```

env 兜底目标与源工程 `worker.py push()` 行为一致（java 协议、仅 transcript、
固定路径 `/admin-api/ai/meeting/internal/transcript?roomSid=…`、重试 3 次/退避 500ms）。

**模式 B：DB 配置（完整管理面）**——增量层补 console 目录（hotfix，秒级）：

```dockerfile
FROM s2s-agent:4030-3
COPY console/backend /app/console
```

compose 追加：

```yaml
s2s-pipeline:
  command: serve ... --with-livekitworker --with-console
  environment:
    CONSOLE_HOME: /app/console          # console 后端代码目录
    CONSOLE_STATIC_DIR: /app/console-static   # 无前端产物时可指向空目录
```

> 内嵌 console 与独立 `s2s-console`（8010）**同库并存**：回调目标由 8010 的「回调管理」页配置，
> pipeline 进程内 dispatcher 经 5s TTL 读同一张表——改配置零重启。内嵌实例只在 8765 端口内可见，
> 不对外映射即可。
>
> 注意共享库迁移状态：40.30 console（`s2s-console:4030-1`）启动自动 `upgrade head`，
> 但该镜像构建早于 `0016`，共享库可能停在 0015（回调表已具备，0016 是 agent config 列宽，不影响回调）。

**验证（40.30 侧）**：

```bash
# 1. 容器内有 callback 模块
docker exec s2s-split-s2s-pipeline-1 ls /usr/src/app/src/speech_to_speech/callback/
# 2. worker 起来了（日志有 livekit worker 连接 ws://…:7880）
docker logs s2s-split-s2s-pipeline-1 2>&1 | grep -i "livekit\|callback"
# 3. 有真实转写后：模式 A 看 stdout 的 callback(env) 行；模式 B 查共享库 delivery_log
docker exec <console-db容器> psql -U <user> -d s2s_db -c \
  "SELECT attempt,http_status,status,duration_ms FROM callback_delivery_log ORDER BY id DESC LIMIT 10;"
# 4. 页面连接测试（console:8010 → 回调管理 → 测试）
```

**回滚**：compose command 去掉 `--with-livekitworker`（或 env `LIVEKIT_WORKER_AUTOSTART=false`）
+ 移除 env 兜底键，`up -d --force-recreate`；DB 目标行删除即回滚（日志保留，`target_id` 置 NULL）。

### 7.3 排查口径

| 现象 | 先看什么 |
|---|---|
| 完全没有投递 | worker 是否启动（`--with-livekitworker` / `LIVEKIT_WORKER_AUTOSTART`）；`emit_segments` 是否被调用 |
| 有投递但目标没收到 | `callback_delivery_log`（模式 A 只有 stdout）：`http_status` 与 `response_snippet`；401/403 → 鉴权头与 token；502 → 目标服务 |
| DB 配置不生效 | pipeline 进程是否真拿到 `SessionLocal`（模式 B 的 `CONSOLE_HOME`）；DB 查询失败会退 env 兜底并打 warning |
| 改了配置没反应 | TTL 5s；等一个 TTL 再试，无需重启 |
| 日志三态含义 | `retrying`=还有下次尝试；`failed`=尝试耗尽（无死信、不重投）；`http_status` NULL=网络异常 |

## 8. HTTP 配置源（2026-11-27，40.30 生产落地）

> **解决什么问题**：§7.2 的模式 A/B 都要求 pipeline 能直连 DB 或内嵌 console，
> 而 40.30 的 `s2s-agent` 镜像缺 console 依赖且禁止联网装包 → **console 页面配置原先不生效**。
> 本节方案由 console 暴露内部下发接口，pipeline 侧 dispatcher 轮询该接口取目标：
> **页面改配置 ≤5s 自动生效、零重启**，无需数据库迁移、无需给 agent 补依赖。

### 8.1 目标来源三级优先（`dispatcher.py`）

| 优先级 | 来源 | 条件 | 特征 |
|---|---|---|---|
| 1 | 进程内 `SessionLocal` 直连 DB | console 后端可导入（`--with-console`） | 投递日志落 `callback_delivery_log` |
| 2 | **console HTTP 下发接口** | `CONSOLE_CALLBACK_CONFIG_URL` 或 `S2S_AGENT_CONSOLE_URL` + `S2S_ADMIN_TOKEN` | 日志走 stdout；**成功（含空列表）即压制 env 兜底** |
| 3 | env 兜底 | 前两者不可用；`JAVA_CALLBACK_BASE` + `MEETING_INTERNAL_TOKEN` 齐备 | 源工程零配置行为；日志 stdout |

**stale-while-error**：HTTP 拉取失败 → 保留最近一次成功配置继续投递（每 TTL 最多重试一次）；
从未成功过才回落 env 兜底。HTTP 拉取在锁外执行（2s 超时不阻塞其它 dispatch 线程），
并发后来者用旧缓存（stale-while-revalidate）。

### 8.2 内部端点契约

`GET /api/v1/callbacks/targets/dispatch-config`，头 `X-Internal-Token: <S2S_ADMIN_TOKEN>`：

- **fail-closed**：console 未配置 `S2S_ADMIN_TOKEN` → 503 `internal_disabled`；令牌不匹配 → 401（常量时间比较 `hmac.compare_digest`）
- **仅 enabled 目标**；`authToken` **明文**下发（投递硬需求，与管理面 `_to_out` 的脱敏隔离），只允许内网访问
- `revision` = `max(updated_at)` + 行数派生（观测用， dispatcher 暂不消费，为条件缓存留口）
- 字段与 `CallbackTargetConfig` 一一对应（camelCase），java/python 协议适配不变

### 8.3 部署与验证（40.30 实测）

镜像：`s2s-console:4030-3`（FROM 4030-2 + `COPY app`）、`s2s-agent:4030-4`
（FROM 4030-3 + `COPY callback`，仅 dispatcher.py 改动）；两端均在 40.30 离线 hotfix 构建，秒级。
env 复用 `S2S_AGENT_CONSOLE_URL=http://s2s-console:8000`（纯基址，自动派生下发路径）
与 `S2S_ADMIN_TOKEN`（两容器共用 env_file）；compose 备份 `docker-compose.split.yml.bak-20261127-httpcfg`。

验证记录：

| 阶段 | 结果 |
|---|---|
| 本地端到端 | HTTP 拉取→投递 ✓；console 禁用→≤5s 停投 ✓；恢复→投递 ✓；停 console→stale 继续投 ✓ |
| 单测 | dispatcher **19 passed**、callbacks API **11 passed**、console 全量 **647 passed**；task-reviewer Approved |
| 40.30 生产 | pipeline 日志 `HTTP_FETCHER True SESSION_FACTORY False`；页面建目标后按配置地址发起投递 ✓；页面禁用后 7s 内零投递尝试 ✓ |

### 8.4 运维与回滚

- **日常运维**：回调目标**全部在 console（8010）「回调管理」页维护**，页面改完 ≤5s 生效，无需重建/重启容器。
- **投递日志**：生产 pipeline 无 DB 会话 → 日志仅在容器 stdout（`docker logs --since ... s2s-split-s2s-pipeline-1 | grep callback`）；
  "日志上报 console" 属二期增强（需新增上报接口），不在本期。
- **安全**：明文 token 仅在内网 HTTP 下发，端点由 `S2S_ADMIN_TOKEN` 保护且不写访问日志；
  不要把下发端点暴露到公网/网关。
- **回滚**：compose image tag 回退到 `s2s-console:4030-2` / `s2s-agent:4030-3` 并
  `up -d --force-recreate`；回滚后页面配置不生效，由 `JAVA_CALLBACK_BASE` + `MEETING_INTERNAL_TOKEN`
  env 兜底继续工作（两键已在 `config.split.2/prod.env`）。
- **java 侧 token 与投递闭环（2026-11-27 已闭环）**：token = `meeting.internal-transcript-token`
  （`application.yaml:505`，java 侧 `.env` 未覆盖 → 默认值 `change-me-internal-token`）。
  console 目标已配为 `meeting-java` / java 协议 / `baseUrl=http://192.168.110.167:8086` /
  `X-Internal-Token` / `tenant-id=1`，生产 dispatch 实测 2xx 到达 java 业务层。
  注意：直接用编造 roomSid 探测会得到业务 `code:500`——`MeetingTranscriptServiceImpl.ingest:90-93`
  要求 `meeting_room` 表存在该 `roomSid`，真实会议由 java 创建房间后回推必然命中。

