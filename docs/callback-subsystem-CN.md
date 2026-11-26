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
