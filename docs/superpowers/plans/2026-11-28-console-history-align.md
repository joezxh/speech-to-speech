# console 会话历史页对齐原型 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 console `/history` 页对齐原型 `console-refactor-demo.html#/history`：消息级 STT/TTS 状态+时长落库、列表筛选扩面（实例/时间范围/转写全文）、列表行带消息数与摘录、页内展开消息面板、删 `/history/:id` 深链。

**Architecture:** 后端三件套（迁移 0020 → service/repository 契约扩展 → 路由参数），前端三件套（API/store 类型扩展与失败行保留 → HistoryView 按原型重写 → 删深链路由）。保留后端分页与既有审计约定。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic（SQLite/Postgres 双方言）；Vue 3 `<script setup>` + Pinia + vue-i18n + vitest。

**Spec:** `docs/superpowers/specs/2026-11-28-console-history-align-design.md`

## Global Constraints

- 消息枚举：`status ∈ {ok, fail}`；`role ∈ {user, assistant, tool}`；`state ∈ {done, failed}`（沿用 `session_record_service.STATES`）。
- 不做 live 状态：KPI = 总数/正常/失败/平均TTFT 四卡。
- 保留后端分页（SQL 层 offset/limit），不引入前端全量分页。
- 权限码沿用：查询 `console:session:query`，写 `console:session:write`；审计 action 点分前缀。
- 后端测试 cwd=`console/backend`（`python -m pytest tests/... -v`，fixture 走 `create_all` 不跑迁移）；前端测试 cwd=`console/frontend`（`npx vitest run <file>`）。
- i18n：en-US 与 zh-CN 的 `sessions.ts` 必须键集一致（`i18n.spec.ts` 强制）。
- init SQL 是生成物：改迁移后必须跑 `python scripts/dump_schema_sql.py` 重出 `alembic/sql/init-*.sql`，不得手改。

## Review Focus

1. **STT/TTS 失败行必须能落库**（本计划的核心动机）：有 audio 无文本的用户行、有 latency 无文本的助手行不再被 `toSavePayload` 丢弃 → Task 4 测试 `keeps stt/tts failure rows`。
2. **存量数据兼容**：迁移前保存的消息 status 默认 'ok'、durationMs 0，前端 durationMs<=0 显示 `—` → Task 1 迁移测试 + Task 5 组件测试。
3. **删助手消息联动 turns**：turns 必须重算而不是保持旧值 → Task 2 测试 `test_delete_message_recomputes_turns`。
4. **range 与 from/to 并存**：两者都传时 from/to 优先（range 只在 from/to 全空时生效）→ Task 3 测试。
5. **摘录/消息数为 0 或无实例**：空会话行 excerpt 为空串、messageCount=0、instanceId/node 空时显示 `—` → Task 5 组件测试 `renders empty excerpt as dash`。

---

### Task 1: 迁移 0020 + 模型列 + init SQL 重生成

**Files:**
- Create: `console/backend/alembic/versions/0020_session_message_fields.py`
- Modify: `console/backend/app/models/session_record.py`（`ParamSessionMessage` 加两列）
- Create: `console/backend/tests/unit/test_migration_0020_session_message_fields.py`
- Regenerate: `console/backend/alembic/sql/init-sqlite.sql`、`init-postgresql.sql`（跑脚本）

**Interfaces:**
- Produces: `ParamSessionMessage.status: Mapped[str]`（String(16), NOT NULL, default "ok"）、`ParamSessionMessage.duration_ms: Mapped[int]`（Integer, NOT NULL, default 0）。Task 2 的 service/repository、Task 4 的前端契约都依赖这两个出参键 `status` / `durationMs`。

- [ ] **Step 1: 写迁移文件**

`0020_session_message_fields.py`，风格对齐 `0019_session_records.py`（`revision = "0020_session_message_fields"`、`down_revision = "0019_session_records"`、模块 docstring 说明用途）：

```python
def upgrade() -> None:
    op.add_column(
        "param_session_message",
        sa.Column("status", sa.String(16), server_default="ok", nullable=False),
    )
    op.add_column(
        "param_session_message",
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("param_session_message", "duration_ms")
    op.drop_column("param_session_message", "status")
```

- [ ] **Step 2: 写迁移测试（先失败）**

新建 `tests/unit/test_migration_0020_session_message_fields.py`，程序化升级写法照抄 `tests/unit/test_migration_0006_clusters.py` 的结构（同一套 alembic config/cfg 获取方式），断言升级到 head 后 `param_session_message` 存在列 `status`（server_default 'ok'）与 `duration_ms`（server_default '0'），downgrade 后不存在。

- [ ] **Step 3: 跑迁移测试**

Run: `cd console/backend && python -m pytest tests/unit/test_migration_0020_session_message_fields.py -v`
Expected: FAIL（列不存在 / 模型无属性导致断言失败或升级断言通过但后续 schema 校验失败——以 Step 4 模型补列后全绿为准）

- [ ] **Step 4: 模型补列**

`app/models/session_record.py` 的 `ParamSessionMessage`，在 `interrupted` 之后加：

```python
    # ok | fail —— 用户行=STT 结果，助手行=TTS 结果。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    # 该条语音时长（毫秒）；用户行来自 TranscriptAudio，助手行来自 latency.e2e_s。
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

- [ ] **Step 5: 重生成 init SQL 并跑 drift guard**

Run: `cd console/backend && python scripts/dump_schema_sql.py && python -m pytest tests/unit/test_schema_sql.py -v`
Expected: PASS（git diff 里 init-sqlite.sql 的 CREATE TABLE 内出现 status/duration_ms 两列）

- [ ] **Step 6: 全量迁移测试回归**

Run: `cd console/backend && python -m pytest tests/unit/ -k migration -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add console/backend/alembic console/backend/app/models/session_record.py console/backend/tests/unit/test_migration_0020_session_message_fields.py
git commit -m "feat(console): migration 0020 adds status/duration_ms to session messages"
```

### Task 2: 后端消息契约 —— status/durationMs 落库与出参、删消息联动 turns

**Files:**
- Modify: `console/backend/app/schemas/session_record.py`
- Modify: `console/backend/app/services/session_record_service.py`（`_out`、`save_record`、`update_message`、`delete_message`、`clear_messages`）
- Modify: `console/backend/app/repositories/session_record_repository.py`（`create` 透传两字段）
- Test: `console/backend/tests/integration/test_session_records_api.py`

**Interfaces:**
- Consumes: `ParamSessionMessage.status/.duration_ms`（Task 1）。
- Produces（HTTP 契约，Task 4/5 依赖）:
  - `SessionMessageIn` 加 `status: str = "ok"`（枚举校验 ok|fail）、`durationMs: int = 0`（ge=0）。
  - `_out` 消息行 dict 加 `"status": msg.status, "durationMs": msg.duration_ms`（含 `update_message` 返回体）。
  - `_out` 行 dict 加 `"messageCount": int, "excerpt": str`（**始终返回**，列表与详情一致；本任务先在 with_messages 分支实现，Task 3 的批量摘录查询接入列表分支）。
  - `delete_message` 后重算 `record.turns = count(role=='assistant')`；`clear_messages` 后 `record.turns = 0`；`update_message` 不改 status（`min_length=1` 使 fail 分支不可达）。

- [ ] **Step 1: 写失败测试**

`tests/integration/test_session_records_api.py` 追加（`_save_payload` 沿用，messages 行加 `"status"`/`"durationMs"` 键）：

```python
def test_save_persists_message_status_and_duration(client):
    headers = _auth(client)
    payload = _save_payload(messages=[
        {"role": "user", "type": "audio", "content": "你好", "status": "ok", "durationMs": 4200},
        {"role": "assistant", "type": "text", "content": "", "status": "fail", "durationMs": 0},
    ])
    data = client.post("/api/v1/session-records", json=payload, headers=headers).json()["data"]
    assert data["messageCount"] == 2
    assert data["messages"][0]["status"] == "ok" and data["messages"][0]["durationMs"] == 4200
    assert data["messages"][1]["status"] == "fail"


def test_save_rejects_bad_message_status(client):
    payload = _save_payload(messages=[{"role": "user", "content": "x", "status": "weird"}])
    assert client.post("/api/v1/session-records", json=payload, headers=_auth(client)).status_code == 400


def test_delete_message_recomputes_turns(client):
    headers = _auth(client)
    record = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]
    # _save_payload 默认 3 条消息，assistant 只有 1 条（index 1），turns=2 是前端传入值。
    mid = record["messages"][1]["id"]
    assert client.delete(f"/api/v1/session-records/{record['id']}/messages/{mid}", headers=headers).status_code == 204
    got = client.get(f"/api/v1/session-records/{record['id']}", headers=headers).json()["data"]
    assert got["turns"] == 0  # 唯一 assistant 消息被删
    assert got["messageCount"] == 2


def test_clear_messages_zeros_turns(client):
    headers = _auth(client)
    record = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]
    client.post(f"/api/v1/session-records/{record['id']}/messages/clear", headers=headers)
    got = client.get(f"/api/v1/session-records/{record['id']}", headers=headers).json()["data"]
    assert got["turns"] == 0 and got["messageCount"] == 0 and got["excerpt"] == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/integration/test_session_records_api.py::test_save_persists_message_status_and_duration tests/integration/test_session_records_api.py::test_delete_message_recomputes_turns -v`
Expected: FAIL（KeyError 'status' / 'messageCount' / turns 未重算）

- [ ] **Step 3: 实现**

- `SessionMessageIn` 加字段（校验用 service 里现成 `_check_enum`，`STATUS_VALUES = ("ok", "fail")` 定义在 service 顶部）。
- `save_record`：消息 dict 加 `"status": item.status, "duration_ms": item.durationMs`，并 `_check_enum(item.status, STATUS_VALUES, "status")`；repository `create` 的 `ParamSessionMessage(...)` 加 `status=item.get("status", "ok"), duration_ms=item.get("duration_ms", 0)`。
- `_out`：行 dict 加 `messageCount`/`excerpt`——with_messages=True 时从 `row.messages` 现算（`len(row.messages)`；`" · ".join(m.content for m in row.messages)[:90]`）；with_messages=False 时本任务先置 `"messageCount": 0, "excerpt": ""` 占位，Task 3 接真值。消息行 dict 加 `"status": msg.status, "durationMs": msg.duration_ms`。
- `delete_message`：`db.delete(msg); db.commit()` 后重算 `row.turns = sum(1 for m in repo.get_messages(record_id) if m.role == "assistant")`，commit；审计不变。
- `clear_messages`：清空后 `row.turns = 0`，commit。
- `update_message`：返回体加 status/durationMs 两键，其余不动。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/integration/test_session_records_api.py -v`
Expected: PASS（含既有用例不回归）

- [ ] **Step 5: Commit**

```bash
git add console/backend/app/schemas/session_record.py console/backend/app/services/session_record_service.py console/backend/app/repositories/session_record_repository.py console/backend/tests/integration/test_session_records_api.py
git commit -m "feat(console): persist message status/durationMs and recompute turns on delete"
```

### Task 3: 列表筛选 inst/range/q 扩面 + instances 端点 + stats.avgTtfaMs

**Files:**
- Modify: `console/backend/app/repositories/session_record_repository.py`（`list` 筛选、`stats`）
- Modify: `console/backend/app/services/session_record_service.py`（`list_records`、`instances`、`stats`、`_parse_range`）
- Modify: `console/backend/app/routers/sessions_records.py`
- Test: `console/backend/tests/integration/test_session_records_api.py`

**Interfaces:**
- Consumes: `_out` 的 `messageCount`/`excerpt` 占位（Task 2）。
- Produces（HTTP 契约，Task 4 依赖）:
  - `GET /api/v1/session-records?inst=&range=&q=&state=&from_date=&to_date=&page=&pageSize=`。`inst` 匹配 `instance_id == inst OR node == inst`；`range ∈ {all, today, 24h, 7d}` 折算 `since`（UTC now - 24h/7d；today = UTC 当日 00:00），**仅在 from_date 与 to_date 均为空时生效**；`q` 扩为 or_(title, note, pipeline_session_id, instance_id, node, EXISTS 消息 content LIKE)。
  - `GET /api/v1/session-records/instances` → `ok([{"instanceId": str, "node": str}, ...])`，全表去重非空对，按 (instanceId, node) 排序，权限 `console:session:query`。
  - `stats()` 返回体加 `"avgTtfaMs": int`（非空 ttfa_ms 均值，无则 0）；既有键不变。

- [ ] **Step 1: 写失败测试**

```python
def test_list_inst_range_and_excerpt(client):
    headers = _auth(client)
    client.post("/api/v1/session-records", json=_save_payload(instanceId="pipe-a", node="n1"), headers=headers)
    client.post("/api/v1/session-records", json=_save_payload(instanceId="pipe-b", node="n2"), headers=headers)

    data = client.get("/api/v1/session-records", params={"inst": "pipe-a"}, headers=headers).json()["data"]
    assert data["total"] == 1

    data = client.get("/api/v1/session-records", params={"range": "today"}, headers=headers).json()["data"]
    assert data["total"] == 2
    # from/to 与 range 并存：from/to 优先（非法 range 不生效也不报错）。
    data = client.get(
        "/api/v1/session-records", params={"range": "7d", "from_date": "2030-01-01"}, headers=headers
    ).json()["data"]
    assert data["total"] == 0

    row = client.get("/api/v1/session-records", headers=headers).json()["data"]["list"][0]
    assert row["messageCount"] == 3
    assert "你好" in row["excerpt"] and "search(...)" in row["excerpt"]

    # q 搜转写原文
    data = client.get("/api/v1/session-records", params={"q": "有什么可以帮你"}, headers=headers).json()["data"]
    assert data["total"] == 2


def test_instances_endpoint(client):
    headers = _auth(client)
    client.post("/api/v1/session-records", json=_save_payload(instanceId="pipe-a", node="n1"), headers=headers)
    data = client.get("/api/v1/session-records/instances", headers=headers).json()["data"]
    assert {"instanceId": "pipe-a", "node": "n1"} in data


def test_stats_avg_ttfa(client):
    headers = _auth(client)
    client.post("/api/v1/session-records", json=_save_payload(), headers=headers)
    stats = client.get("/api/v1/session-records/stats", headers=headers).json()["data"]
    assert stats["avgTtfaMs"] == 660
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/integration/test_session_records_api.py::test_list_inst_range_and_excerpt tests/integration/test_session_records_api.py::test_instances_endpoint tests/integration/test_session_records_api.py::test_stats_avg_ttfa -v`
Expected: FAIL（inst/range 参数被忽略、instances 404、messageCount==0、avgTtfaMs KeyError）

- [ ] **Step 3: 实现**

- `repository.list` 加 `inst: str = ""` 形参：`base = base.where(or_(ParamSessionRecord.instance_id == inst, ParamSessionRecord.node == inst))`；`q` 分支的 `or_` 加 `instance_id`/`node` 的 like 与 `exists().where(ParamSessionMessage.session_id == ParamSessionRecord.id, ParamSessionMessage.content.like(like))`（select 语句需要 `select(ParamSessionRecord).where(...)` 上挂，注意 EXISTS 子查询写法用 `sqlalchemy.exists`）。
- repository 新方法 `instances()`：`select(ParamSessionRecord.instance_id, ParamSessionRecord.node)` 全表，Python 侧收集非空 (instance_id, node) 对去重排序，返回 `list[dict]`。
- repository `stats` 加 `ttfas = [row.ttfa_ms for row in rows if row.ttfa_ms]`；`avgTtfaMs = round(sum(ttfas)/len(ttfas)) if ttfas else 0`。
- service：`list_records` 加 `inst: str = ""`、`range: str = ""` 形参；新 `_parse_range(value)` 返回 `datetime | None`（`today`=UTC 当日零点，`24h`=now-24h，`7d`=now-7d，`all`/空=None，未知值 `ApiError("invalid_request", ..., 400)`）；`since = _parse_date(from_date) or _parse_range(range)`（from_date 优先）；把当页 rows 的消息批量查出填 `messageCount`/`excerpt`（一次 `select(ParamSessionMessage).where(ParamSessionMessage.session_id.in_(ids))`，按 session_id 分组后写入 `_out` 结果 dict）。
- service 新 `instances(db) -> list[dict]` 直通 repository。
- router：`list_records` 加 `inst: str = ""`、`range: str = ""` 参数并透传；新 `@router.get("/instances")`（放在 `/{record_id}` 之前，权限 query）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/integration/test_session_records_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add console/backend/app/repositories/session_record_repository.py console/backend/app/services/session_record_service.py console/backend/app/routers/sessions_records.py console/backend/tests/integration/test_session_records_api.py
git commit -m "feat(console): history list filters (inst/range/q-content), instances endpoint, avgTtfaMs"
```

### Task 4: 前端 API/store —— 类型扩展、失败行保留、行摘要同步

**Files:**
- Modify: `console/frontend/src/api/sessionRecords.ts`
- Modify: `console/frontend/src/stores/sessionRecords.ts`
- Test: `console/frontend/src/stores/sessionRecords.spec.ts`

**Interfaces:**
- Consumes: Task 2/3 的 HTTP 契约。
- Produces（Task 5 依赖）:
  - `SessionMessageRow` 加 `status: 'ok' | 'fail'`、`durationMs: number`。
  - `SessionRecordRow` 加 `messageCount: number`、`excerpt: string`。
  - `SessionRecordStats` 加 `avgTtfaMs: number`。
  - `SessionRecordQuery` 加 `inst?: string`、`range?: string`。
  - `SessionSavePayload.messages` 行加 `status?: 'ok' | 'fail'`、`durationMs?: number`。
  - 新 API 函数 `listSessionRecordInstances(): Promise<Array<{ instanceId: string; node: string }>>`（GET `/session-records/instances`）。
  - store filters 变为 `{ q: string; state: '' | 'done' | 'failed'; inst: string; range: '' | 'all' | 'today' | '24h' | '7d'; from: string; to: string }`；新 `instances` ref + `loadInstances()`；`removeMessage`/`clearMessages` 后同步对应 rows 行的 `messageCount`（excerpt 交由调用方 `load()` 刷新）。
  - `toSavePayload` 保留失败行：入选规则 `text.trim() !== '' || (role === 'user' && entry.audio) || (role === 'assistant' && entry.latency)`；用户行 `status = text 非空 ? 'ok' : 'fail'`、`durationMs = entry.audio?.durationMs ?? 0`；助手行 `status = text 非空 && !interrupted ? 'ok' : 'fail'`、`durationMs = latency?.e2e_s ? Math.round(e2e_s * 1000) : 0`；tool 行 `status: 'ok', durationMs: 0`。turns 仍数 assistant 行数（含失败行）。

- [ ] **Step 1: 写失败测试**

`sessionRecords.spec.ts` 改写/追加：
- `row()` fixture 加 `messageCount: 3, excerpt: '你好 · 你好，有什么可以帮你？ · search(...)'`；消息 fixture 加 `status: 'ok', durationMs: 4200`；stats mock 加 `avgTtfaMs: 660`。
- 原 `drops empty lines...` 用例改为 `keeps stt/tts failure rows and derives status/durationMs`：

```ts
const payload = toSavePayload([
  entry({ key: 'u:1', role: 'user', text: '', audio: { url: 'blob:x', durationMs: 3800, truncated: false } }),
  entry({ key: 'a:1', role: 'assistant', text: '好', latency: { version: 1, turn_id: null, turn_revision: 1, response_key: 'r1', status: 'ok', stt_s: 0.4, llm_s: 0.6, tts_ttfa_s: 0.66, e2e_s: 1.8 } }),
  entry({ key: 'a:2', role: 'assistant', text: '', interrupted: true, latency: { version: 1, turn_id: null, turn_revision: 1, response_key: 'r2', status: 'ok', stt_s: 0.2, llm_s: 0.1, tts_ttfa_s: 0.3, e2e_s: 0.5 } }),
  entry({ key: 't:1', role: 'tool', text: 'search()' })
], {})
expect(payload.messages).toHaveLength(4)
expect(payload.messages[0]).toMatchObject({ role: 'user', status: 'fail', durationMs: 3800 })
expect(payload.messages[1]).toMatchObject({ role: 'assistant', status: 'ok', durationMs: 1800 })
expect(payload.messages[2]).toMatchObject({ role: 'assistant', status: 'fail', durationMs: 500 })
expect(payload.messages[3]).toMatchObject({ role: 'tool', status: 'ok', durationMs: 0 })
expect(payload.turns).toBe(2)
```

- 追加 `loads instances list` 用例（mock `listSessionRecordInstances` → store.loadInstances() → `store.instances` 长度断言）。
- 追加 `removeMessage updates row messageCount` 用例（rows 里 messageCount 3 → 删后 2）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/frontend && npx vitest run src/stores/sessionRecords.spec.ts`
Expected: FAIL（类型缺属性 / 函数不存在）

- [ ] **Step 3: 实现**

- `api/sessionRecords.ts`：四处 interface 加字段（见 Produces），加 `listSessionRecordInstances`。
- `stores/sessionRecords.ts`：filters 加 `inst: ''`、`range: ''`（`hasFilters` 同步加两键判断）；`load()` 传 `inst: f.inst || undefined, range: f.range || undefined`；加 `instances = ref<InstanceRow[]>([])` 与 `loadInstances()`（失败静默置 []）；`removeMessage` 删消息后若 `rows` 里有对应行，`row.messageCount = Math.max(0, row.messageCount - 1)`；`clearMessages` 后 `row.messageCount = 0`。
- `toSavePayload` 按 Produces 规则改写（入选 filter 与 status/durationMs 计算）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd console/frontend && npx vitest run src/stores/sessionRecords.spec.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add console/frontend/src/api/sessionRecords.ts console/frontend/src/stores/sessionRecords.ts console/frontend/src/stores/sessionRecords.spec.ts
git commit -m "feat(console-web): history store gains inst/range filters, instances, failure-row persistence"
```

### Task 5: i18n hist 键组 + HistoryView 按原型重写 + 组件测试

**Files:**
- Modify: `console/frontend/src/i18n/locales/en-US/sessions.ts`、`zh-CN/sessions.ts`
- Modify: `console/frontend/src/views/HistoryView.vue`（整文件重写，样式沿用既有 `.hv` BEM 少量增补）
- Create: `console/frontend/src/views/HistoryView.spec.ts`

**Interfaces:**
- Consumes: Task 4 的 store 字段与方法；既有 `PBadge`（kind: 'ok'|'bad'）、`useConfirm().ask`。

- [ ] **Step 1: i18n 键组（en/zh 同步，落 `sessions.ts` 的 `hist:` 子对象）**

en（zh 按右侧）：

```
hist.title: 'Session History' / '会话历史'
hist.kpi.total: 'Total sessions' / '总会话'
hist.kpi.done: 'Finished' / '正常结束'
hist.kpi.failed: 'Failed' / '失败'
hist.kpi.avgTtfa: 'Avg TTFT' / '平均 TTFT'
hist.filter.title: 'Session query' / '会话查询'
hist.kw: 'Keyword' / '关键词'
hist.kw.ph: 'ID / instance / node / transcript' / 'ID / 实例 / 节点 / 转写'
hist.filter.state: 'State' / '状态'
hist.filter.all: 'All' / '全部'
hist.filter.inst: 'Instance' / '实例'
hist.filter.range: 'Range' / '时间范围'
hist.range.today: 'Today' / '今天'
hist.range.24h: 'Last 24h' / '近 24 小时'
hist.range.7d: 'Last 7 days' / '近 7 天'
hist.query: 'Query' / '查询'
hist.reset: 'Reset' / '重置'
hist.count: '{n} sessions' / '{n} 条会话'
hist.sel.count: '{n} selected' / '已选 {n} 条'
hist.delete.selected: 'Delete selected' / '删除所选'
hist.col.id: 'Session ID' / '会话 ID'
hist.col.start: 'Started' / '开始时间'
hist.col.route: 'Instance · node' / '实例 · 节点'
hist.col.excerpt: 'Transcript' / '转写摘录'
hist.col.turns: 'Turns' / '轮数'
hist.col.msgs: 'Messages' / '消息数'
hist.col.dur: 'Voice' / '语音时长'
hist.col.ttft: 'TTFT' / 'TTFT'
hist.col.actions: 'Actions' / '操作'
hist.view.messages: 'Messages' / '查看消息'
hist.empty: 'No session matches the query.' / '没有符合条件的会话。'
hist.prev: 'Previous' / '上一页'
hist.next: 'Next' / '下一页'
hist.page.of: 'Page {n} of {m}' / '第 {n} / {m} 页'
hist.msg.title: 'Session messages' / '会话消息'
hist.msg.count: '{n} messages' / '{n} 条消息'
hist.msg.kw: 'Search in the messages' / '消息内搜索'
hist.msg.clear: 'Clear all messages' / '清空全部消息'
hist.msg.no.match: 'No message matches.' / '没有匹配的消息。'
hist.col.mid: 'Message ID' / '消息 ID'
hist.col.role: 'Role' / '角色'
hist.col.type: 'Type' / '类型'
hist.col.content: 'Content' / '内容'
hist.col.at: 'At' / '时间'
hist.col.status: 'Status' / '状态'
hist.role.caller: 'Caller' / '调用者'
hist.role.bot: 'Bot' / '助手'
hist.type.asr: 'ASR' / '转写'
hist.type.reply: 'Reply' / '回复'
hist.flag.ok: 'ok' / '正常'
hist.flag.fail: 'fail' / '失败'
```

删除确认复用既有 `sessions.deleteTitle/deleteBody/clearMessages/clearTitle/clearBody/deleteMsgTitle/deleteMsgBody` 与 `common.search/common.refresh`；`sessions.filterAllStates` 继续用于状态下拉。

- [ ] **Step 2: 写失败组件测试**

`views/HistoryView.spec.ts`，jsdom + `createApp` 手挂（照抄 `proto.spec.ts` 的 mount/unmount 模式），app 需 `use(createPinia())` + `use(i18n)`（`@/i18n` 默认导出）+ mock `@/api/sessionRecords`（同 store spec 的 vi.mock 手法）。store 的 api mock 返回 2 行（一行 excerpt 非空、一行 `messageCount: 0, excerpt: ''`）。断言：

1. KPI 四卡渲染 `stats.avgTtfaMs`（如 `660ms`）。
2. 提交筛选表单（填 inst/range 后 submit）→ `listSessionRecords` 收到 `{ inst: 'pipe-a', range: '7d' }`。
3. 点行 → 消息面板出现（`.hv__panel` 存在，标题含会话 ID），同行高亮 class `sel`；再点收起。
4. 面板内点删除消息按钮（confirm 桩返回 true）→ `deleteSessionMessage` 被调用。
5. `excerpt: ''` 行显示 `—`；`durationMs <= 0` 显示 `—`。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd console/frontend && npx vitest run src/views/HistoryView.spec.ts`
Expected: FAIL（旧模板无 `.hv__panel`/KPI 无 avgTtfa）

- [ ] **Step 4: 重写 HistoryView.vue**

结构对齐原型 `renderHistory`（模板顺序：header → `.hv__kpis` 四卡 → `.hv__filters` 筛选卡 → 表格 → 分页 → 消息面板）：

- KPI：`store.stats` 的 `total/done/failed/avgTtfaMs`（`avgTtfaMs` 渲染 `${avgTtfaMs}ms`，stats 为 null 显示 `—`）。
- 筛选：kw(input type=search)、state(select: ''/done/failed)、inst(select: '' + store.instances，选项文本 `${instanceId} · ${node}`)、range(select: ''/today/24h/7d)、Query(submit)/Reset(type=button，清空 filters 后 `store.resetAndLoad()`)；右侧 `t('sessions.hist.count', { n: store.total })` + 选中条（`selected.size > 0` 时显示 `t('sessions.hist.sel.count', {n})` + 删除所选按钮，走既有 `batchDelete`）。
- 表 11 列：checkbox（`toggleAll`/`toggle` 沿用）、`#{{ row.id }}`（mono）、createdAt、`row.instanceId || row.node || '—'`（有 instanceId 且有 node 时显示 `instanceId · node`）、excerpt（`row.excerpt || '—'`，`.cell-clip` 截断+title）、turns、messageCount、`fmtDurationMs(row.durationMs)`（<=0 显示 `—`；秒显示保留原型口径 `<1s 显示 '0s'`）、`row.ttfaMs != null ? row.ttfaMs + 'ms' : '—'`、PBadge（done→ok / failed→bad）、操作列（查看消息 + 删除，删除走 `store.remove(row.id)` 前过 `useConfirm`）。
- 行 class `:class="{ sel: openId === row.id }"`；行点击 `togglePanel(row.id)`。
- 消息面板：`v-if="store.detail && openId != null"`；标题 `t('sessions.hist.msg.title')` + `store.detail.id` + `t('sessions.hist.msg.count', { n: msgs.length })` + 清空按钮（confirm 复用 `sessions.clearTitle/clearBody`，成功后 `store.clearMessages(id)` → `store.load()`）；面板内 `panelKw` 本地过滤（匹配 `m.id/content/type/role` 的小写包含）；消息表列：`m{ordinal+1}` mono、role（user→caller / assistant→bot / tool→tool 名原样）、type（user→asr / assistant→reply / tool 原样）、content、createdAt、PBadge（status fail→bad / ok→ok）、删除按钮（confirm `sessions.deleteMsgTitle/deleteMsgBody`，成功 `store.removeMessage` → `store.load()`）。
- 分页：`‹ / t('sessions.hist.page.of', { n: store.page, m: totalPages }) / ›`，沿用 store.page/pageSize/total。
- `watch(openId)` → `store.openDetail(id)`；关面板时 `store.closeDetail()`。
- i18n 引用全部走 `sessions.hist.*`；样式在既有 `.hv` 内补 `&__panel`、`.sel` 行高亮、`.cell-clip`。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd console/frontend && npx vitest run src/views/HistoryView.spec.ts && npx vitest run src/i18n/i18n.spec.ts`
Expected: PASS（键组两语言一致）

- [ ] **Step 6: Commit**

```bash
git add console/frontend/src/i18n/locales/en-US/sessions.ts console/frontend/src/i18n/locales/zh-CN/sessions.ts console/frontend/src/views/HistoryView.vue console/frontend/src/views/HistoryView.spec.ts
git commit -m "feat(console-web): rewrite history view to prototype (KPI/filters/columns/inline message panel)"
```

### Task 6: 删深链路由 + 全量回归

**Files:**
- Modify: `console/frontend/src/router/index.ts`（删 `history/:id` 记录，约 33-39 行）
- Delete: `console/frontend/src/views/HistoryDetailView.vue`

- [ ] **Step 1: 删路由与视图文件**

`router/index.ts` 删除 `path: 'history/:id'` 的记录（含注释）；`delete_file` 删 `views/HistoryDetailView.vue`。全仓确认无其他引用（`grep HistoryDetailView`，`router.spec.ts` 未引用它）。

- [ ] **Step 2: 类型检查 + 全量前端测试 + lint**

Run: `cd console/frontend && npx vue-tsc --noEmit && npx vitest run && npm run lint`
Expected: 全部 PASS（`SessionLogPanel`/`SessionRecordDetail` 不受影响——它们用 store 的 detail/openDetail/closeDetail/load，均保留）

- [ ] **Step 3: 后端全量回归**

Run: `cd console/backend && python -m pytest tests/ -v`
Expected: PASS（含 test_schema_sql drift guard）

- [ ] **Step 4: Commit**

```bash
git add -A console/frontend/src/router console/frontend/src/views
git commit -m "refactor(console-web): drop /history/:id deep link in favor of inline message panel"
```
