# Console Tools Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the console `/tools` page to match the prototype exactly, back it with a persisted tool registry + hybrid provider execution (real API with key, demo data without), and make enabled tools callable from the voice conversation demo.

**Architecture:** Backend FastAPI/SQLAlchemy adds a `tools` vertical slice (migration → model → repo → service → router) plus a provider layer under `services/tool_providers/` and one `/invoke` endpoint that all tool calls funnel through. Frontend replaces `ToolsView.vue` with the prototype's three-row layout fed by a new Pinia `tools` store, and `VoiceView.vue` derives its RealtimeAgent `ToolDef[]` from that store instead of hard-coded web/camera flags.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy sync / Alembic / httpx / pytest；Vue 3 / Pinia / vue-i18n / axios / vitest.

**Spec:** `docs/superpowers/specs/2026-11-28-console-tools-module-design.md`

## Global Constraints

- All `/api/v1/*` responses use `ok(data)` envelope `{code:200,message:"success",data:...}`; errors use `ApiError` (`{code,message,detail,requestId}`). No custom `RequestValidationError` handler exists — do not put `Literal`/range constraints in Pydantic that would trigger FastAPI's default 422; validate in service layer.
- Permission codes registered in **both** `console/backend/app/core/permissions.py` and `console/frontend/src/utils/permissions.ts` (mirror is asserted by `utils/permissions.spec.ts`).
- No API key ever leaves the server. No raw hex in `src/styles/**`, `ConsoleLayout.vue`, `components/proto/**` (`styles/hex-ban.spec.ts` enforces).
- Console content padding `22px 26px 60px` is supplied by `ConsoleLayout`; `/tools` page must not add outer padding.
- Chinese env, respond in 简体中文. Commit message prefix `feat:` / `test:` in English; no `codex` in branch names.

## Review Focus

- **Built-in `tool-kb` has `scope=tenant` and empty owner**: must still be visible to every logged-in user, or KPI count/table row/voice tool all disappear. → Task 2 test `test_builtin_tools_visible_to_all`.
- **Operator role toggling enabled**: `PUT /enabled` must work for operator (not just admin), else the voice demo's switches are dead. → Task 3 test `test_operator_can_toggle_builtin`.
- **`scope=session` enabled state**: must be included in `enabledTools` and therefore in the agent's tool declarations, else the switch is a no-op. → Task 8 test `test_session_scope_tool_reaches_agent`.
- **No-key path for every provider**: search/weather must return demo data with `mode="demo"` rather than raising, or the voice demo stalls without keys. → Task 4 test `test_search_no_key_returns_demo`, `test_weather_no_key_returns_demo`.
- **`/invoke` output shape**: SDK requires `{output: string}`; a structured object returned from `executeTool` breaks tool-call rendering. → Task 8 test `test_invoke_output_is_serialized_string`.

---

### Task 1: Migration + models for tools and calendar events

**Files:**
- Create: `console/backend/alembic/versions/0022_tools.py`
- Create: `console/backend/app/models/tool.py`
- Modify: `console/backend/app/models/__init__.py` (register new models on `Base.metadata`)

**Interfaces:**
- Produces: `ConsoleTool` ORM class (`__tablename__="ai_console_tool"`), `CalendarEvent` ORM class (`__tablename__="ai_console_calendar_event"`) with columns from spec §5.1; migration `0022_tools` with `down_revision="0021_session_clips"`.

- [ ] **Step 1: Write the failing migration test**

```python
# console/backend/tests/unit/test_tools_migration.py
def test_0022_tools_creates_tables_and_seeds_builtins():
    # use alembic Config pointed at a temp sqlite URL; command.upgrade("0022_tools")
    # assert tables ai_console_tool, ai_console_calendar_event exist
    # assert 4 rows with ids tool-search/tool-calendar/tool-weather/tool-kb
    # assert tool-search enabled=True, tool-calendar enabled=False, tool-kb scope="tenant" and owner=""
    # command.downgrade("0021_session_clips") then assert both tables gone
```

- [ ] **Step 2: Run it to verify it fails** — `pytest tests/unit/test_tools_migration.py -v`, expect FAIL (module/migration not found).

- [ ] **Step 3: Implement the migration and models** — `op.create_table` for both tables with columns exactly per spec §5.1 (`id VARCHAR(64) PK`, `name/type/description/endpoint/method/scope VARCHAR`, `enabled/builtin BOOLEAN`, `owner VARCHAR(64)`, `params/config JSON`, audit columns; calendar event `id INTEGER PK autoincrement`, `owner/title/start_at/end_at/description VARCHAR`, `created_at`). Seed via `op.bulk_insert` with the 4 built-in rows from prototype `TOOLS`. Add `UniqueConstraint("name")` on `ai_console_tool`. Register models in `app/models/__init__.py`.

- [ ] **Step 4: Run test to verify pass** — `pytest tests/unit/test_tools_migration.py -v`, expect PASS.

- [ ] **Step 5: Commit** — `git add` the four files, `git commit -m "feat: add tools and calendar event schema"`.

---

### Task 2: Tool repository and service (CRUD, visibility, effectiveEnabled)

**Files:**
- Create: `console/backend/app/repositories/tool_repository.py`
- Create: `console/backend/app/services/tool_service.py`
- Create: `console/backend/app/schemas/tool.py`
- Test: `console/backend/tests/unit/test_tool_service.py`

**Interfaces:**
- Consumes: `ConsoleTool`, `CalendarEvent` (Task 1).
- Produces: `ToolRepository(session)` with `list()`, `get(tool_id)`, `get_by_name(name)`, `create(row)`, `update(row)`, `delete(tool_id)`. `tool_service.list_tools(db, username) -> list[dict]` returning tool rows with `effectiveEnabled`; `create_tool(db, payload, actor, username)`, `update_tool`, `delete_tool`, `copy_tool`, `toggle_tool(db, tool_id, enabled, actor)`; raises `ApiError`/`ValueError`/`KeyError` as the router expects. `ToolCreate`, `ToolUpdate`, `ToolInvoke` Pydantic models.

- [ ] **Step 1: Write the failing service tests**

```python
# tests/unit/test_tool_service.py
def test_builtin_tools_visible_to_all(db_session):
    # seed builtins via helper; list_tools(db, "bob") contains all 4
    # tool-kb has effectiveEnabled False, tool-search True

def test_custom_tool_owner_isolation(db_session):
    # create custom tool owned by alice; list_tools(db,"bob") excludes it

def test_duplicate_name_raises(db_session):
    with pytest.raises(ValueError): ...

def test_toggle_changes_effective_enabled(db_session):
    ...
```

- [ ] **Step 2: Run to verify fails.**

- [ ] **Step 3: Implement repository/service/schemas** — mirror `template_repository.py`/`template_service.py` and `schemas/template.py`; `builtin=true` bypasses owner filter; `scope=global` custom tools visible to all but writable only by admin (router concern); `effectiveEnabled = row.enabled` for global/tenant, `None` for session. Domain validation (`type`/`scope`/`method` enums, endpoint required for `http`, duplicate name) in service. Audit via `AuditRepository(db).record(...)` with actions `tool.create/update/delete/copy/toggle`.

- [ ] **Step 4: Run tests to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add tool CRUD service"`.

---

### Task 3: Tools router + permissions + registration

**Files:**
- Create: `console/backend/app/routers/tools.py`
- Modify: `console/backend/app/core/permissions.py:17-59`
- Modify: `console/backend/app/core/router_registry.py:12-40,43-98`
- Test: `console/backend/tests/integration/test_tools_api.py`

**Interfaces:**
- Consumes: `tool_service` functions, `ToolCreate/ToolUpdate/ToolInvoke` (Task 2).
- Produces: `GET/POST /api/v1/tools`, `GET/PUT/DELETE /api/v1/tools/{id}`, `POST /api/v1/tools/{id}/copy`, `PUT /api/v1/tools/{id}/enabled`, `POST /api/v1/tools/{id}/invoke` (handler delegates to `tool_execution_service.execute` in Task 5 — stub returning `{"mode":"demo","data":{}}` until then).

- [ ] **Step 1: Write the failing integration tests** (mirror `test_templates_api.py` fixture exactly: tmp dist dir, `dependency_overrides[get_db]`, create alice/admin + op/operator):

```python
def test_admin_crud_roundtrip(client): ...
def test_duplicate_name_is_409(client): ...
def test_operator_can_toggle_builtin(client):
    resp = client.put("/api/v1/tools/tool-search/enabled", json={"enabled": False}, headers=_auth(client,"op"))
    assert resp.status_code == 200
def test_operator_can_create_own_tenant_tool(client):
    resp = client.post("/api/v1/tools", json=_body(scope="tenant"), headers=_auth(client,"op"))
    assert resp.status_code == 200
def test_operator_cannot_create_global_tool(client):
    assert client.post("/api/v1/tools", json=_body(scope="global"), headers=_auth(client,"op")).status_code == 403
def test_operator_cannot_delete_builtin(client):
    assert client.delete("/api/v1/tools/tool-search", headers=_auth(client,"op")).status_code == 403
def test_list_shows_4_builtins_to_operator(client): ...
```

- [ ] **Step 2: Run to verify fails.**

- [ ] **Step 3: Implement router + permission codes** — codes in `permissions.py` **and the frontend mirror**: all four `console:tool:query/create/update/delete` = `{admin, operator}`. Service/router enforces boundaries: `scope=global` create/update and builtin delete require `user.role == "admin"`; all other writes require `owner == username`. `PUT /enabled` uses `Depends(require_user)`. Register `tools.router` in `router_registry.py` before demo routers. `/invoke` temporarily returns stubbed envelope.

- [ ] **Step 4: Run tests to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add tools CRUD API"`.

---

### Task 4: Provider layer — search / weather / calendar / knowledge base

**Files:**
- Create: `console/backend/app/config/_tools.py`
- Create: `console/backend/app/services/tool_providers/__init__.py`
- Create: `console/backend/app/services/tool_providers/search.py`
- Create: `console/backend/app/services/tool_providers/weather.py`
- Create: `console/backend/app/services/tool_providers/calendar.py`
- Create: `console/backend/app/services/tool_providers/kb.py`
- Modify: `console/backend/app/config/__init__.py` (export `tools` settings), `console/backend/.env.example`
- Test: `console/backend/tests/unit/test_tool_providers.py`

**Interfaces:**
- Consumes: `CalendarEvent` (Task 1), `demo.serper_api_key` (existing).
- Produces: `search(query: str, top_k: int = 5, config: dict | None = None) -> dict` returning `{"mode","provider","results","answer?"}`; `weather(city: str) -> dict` returning `{"mode","city","temperature","condition","humidity","wind"}`; `calendar_list(owner)`, `calendar_create(owner, payload)`, `calendar_delete(owner, event_id)`; `kb_search(query: str, top_k: int = 5) -> dict` returning `{"mode":"local","items":[{"path","heading","snippet","score"}]}`. `ToolSettings` with `anspire_api_key/bocha_api_key/youtube...` — exact: `anspire_api_key`, `bocha_api_key`, `you_api_key`, `tavily_api_key`, `openweather_api_key`, `kb_docs_dir`, `http_allow_private`.

- [ ] **Step 1: Write the failing provider tests**

```python
def test_search_no_key_returns_demo(monkeypatch):
    monkeypatch.setattr("app.services.tool_providers.search._keys", lambda: {})
    out = search("天气")
    assert out["mode"] == "demo" and out["results"]

def test_search_anspire_live(monkeypatch):
    # monkeypatch httpx.AsyncClient.post to return fixture-shaped JSON
    # assert out["provider"] == "anspire" and out["mode"] == "live"

def test_bocha_live_and_fallback(monkeypatch): ...
def test_weather_no_key_returns_demo(monkeypatch): ...
def test_weather_live(monkeypatch): ...
def test_calendar_create_list_delete(db_session): ...
def test_kb_search_finds_spec_heading(): ...
```

- [ ] **Step 2: Run to verify fails.**

- [ ] **Step 3: Implement providers** — search tries providers in `config["providers"]` default `["anspire","bocha","serper","you","tavily"]`; each with key → `httpx.AsyncClient` POST/GET per spec §5.3, normalize to `{title,url,snippet}`; on failure fall through, all fail → demo fixture. weather uses OpenWeatherMap or city fixture. calendar writes `CalendarEvent` rows (service receives db session). kb walks `tools.kb_docs_dir` (`docs/**/*.md`), paragraph chunks, substring+heading-weight score, mtime cache. Add all env keys to `.env.example` with empty defaults and comments (never real keys).

- [ ] **Step 4: Run tests to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add tool providers with demo fallback"`.

---

### Task 5: `/invoke` execution service + HTTP tool SSRF guard

**Files:**
- Create: `console/backend/app/services/tool_execution_service.py`
- Modify: `console/backend/app/routers/tools.py` (replace stub `/invoke`)
- Test: `console/backend/tests/unit/test_tool_execution.py`

**Interfaces:**
- Consumes: provider functions (Task 4), `ToolRepository` (Task 2).
- Produces: `execute(db, tool: ConsoleTool, arguments: dict, username: str) -> dict` returning `{"mode","provider","data","error?"}`.

- [ ] **Step 1: Write failing tests**

```python
def test_invoke_dispatches_web_search(monkeypatch, db_session): ...
def test_invoke_http_tool_rejects_private_url(monkeypatch, db_session):
    # endpoint http://127.0.0.1/secret -> raises ApiError 400
def test_invoke_http_tool_allows_public_url(monkeypatch, db_session): ...
def test_invoke_disabled_tool_raises(db_session): ...
```

- [ ] **Step 2: Run to verify fails.**

- [ ] **Step 3: Implement execution service** — dispatch on `tool.type`: `web_search`/`weather`/`kb`/`calendar`/`http`. For `http`, validate URL scheme + `ipaddress.ip_address(host).is_private` (unless `tools.http_allow_private`), 8s timeout, truncate response to 64KB, never forward browser headers. Wrap provider exceptions into `{"mode":"demo","data":...,"error":...}` for search/weather (fail-open), but HTTP errors → `ApiError` 502.

- [ ] **Step 4: Run tests to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add tool invoke execution"`.

---

### Task 6: Frontend i18n + API client + store

**Files:**
- Create: `console/frontend/src/i18n/locales/en-US/tools.ts`, `console/frontend/src/i18n/locales/zh-CN/tools.ts`
- Modify: both `i18n/locales/*/index.ts`
- Create: `console/frontend/src/api/tools.ts`
- Create: `console/frontend/src/stores/tools.ts`
- Modify: `console/frontend/src/utils/permissions.ts` (add 4 codes)
- Test: `console/frontend/src/stores/tools.spec.ts`, `console/frontend/src/i18n/i18n.spec.ts` (extend)

**Interfaces:**
- Consumes: backend routes (Task 3).
- Produces: `ToolRow`, `ToolPayload`, `ToolFilter`, `ToolInvokeResult` types; `toolsApi.{list,create,update,remove,copy,toggle,invoke}`; `useToolsStore()` with `rows/loading/saving/error/kpi/filtered(rows)/enabledTools/load/create/update/remove/copy/toggle/invoke(id,args)`.

- [ ] **Step 1: Write failing tests**

```ts
// stores/tools.spec.ts — mock toolsApi, assert:
// load() populates rows and kpi counts
// applyFilter matches keyword/type/scope/on
// toggle() updates effectiveEnabled and enabledTools
// enabledTools includes a session-scope tool with localStorage enabled
```

- [ ] **Step 2: Run to verify fails** — `npx vitest run src/stores/tools.spec.ts`.

- [ ] **Step 3: Implement i18n/API/store** — i18n keys from prototype (`tools.page.desc`, `tools.kpi.*`, `tools.filter.*`, `tools.col.*`, `tool.type.*`, `tool.scope.*`, `tool.form.*`, `tools.new/edit/copy/count/empty`, `tool.builtin/custom`, `tool.toggle`); every key used by `ToolsView` must exist in both locales. API client uses `api.get/post/put/delete` from `./client` at `/tools` paths. Store mirrors `templates.ts` Pinia shape; `enabledTools` computed from `rows.filter(r => r.effectiveEnabled ?? sessionEnabled[r.id])`.

- [ ] **Step 4: Run tests + `npx vitest run src/i18n/i18n.spec.ts` to verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add tools API client and store"`.

---

### Task 7: ToolsView page aligned to prototype

**Files:**
- Modify: `console/frontend/src/views/ToolsView.vue` (full rewrite)
- Test: `console/frontend/src/views/toolsView.viewmodel.spec.ts`

**Interfaces:**
- Consumes: `useToolsStore`, i18n `tools.*` keys, `useConfirm`/`useToast`, `useAuthStore`.
- Produces: view with the three rows and a `toolForm` modal; exposes a pure helper module `src/views/tools.viewmodel.ts` with `applyToolFilter(rows, filter)`, `toolKpis(rows)`, `toolParamText(row)`.

- [ ] **Step 1: Write failing viewmodel tests**

```ts
expect(applyToolFilter(rows, { q: '天气', type: 'all', scope: 'all', on: 'all' })).toHaveLength(1)
expect(toolKpis(rows)).toEqual({ total: 4, on: 2, builtin: 4, custom: 0 })
expect(toolParamText({params:[{k:'city',t:'string',req:true}]})).toBe('city:string!')
```

- [ ] **Step 2: Run to verify fails.**

- [ ] **Step 3: Implement the viewmodel + rewrite the view** — `ToolsView.vue` template: `.page-head` (h1 + desc), `.grid.g4` four KPI cards, filter card with keyword `<input>`/scope `<select>`/on `<select>`/type chips, table card with 8 columns (`name/type/desc/params/scope/on/updated/actions`) and switch buttons. Use prototype-identical CSS token values; no outer padding. CRUD modal with fields name/type/desc/endpoint/method/scope/params rows; builtin edit/delete warnings via `useConfirm`. All copy from `t('tools.*')` — no hard-coded strings. UI buttons gated by `auth.hasPermission('console:tool:*')`.

- [ ] **Step 4: Run tests to verify pass** — `npx vitest run src/views/toolsView.viewmodel.spec.ts`.

- [ ] **Step 5: Commit** — `git commit -m "feat: align tools page with prototype"`.

---

### Task 8: Voice demo wiring — enabled tools callable

**Files:**
- Modify: `console/frontend/src/views/VoiceView.vue:181-200,237-264,281-300,549-565`
- Modify: `console/frontend/src/features/voice/components/ToolsDialog.vue`
- Modify: `console/frontend/src/stores/voice.ts` (session-enabled helper)
- Test: `console/frontend/src/views/voiceTools.viewmodel.spec.ts`, `console/frontend/src/features/voice/transport/s2s-client.spec.ts` (extend if needed)

**Interfaces:**
- Consumes: `useToolsStore().enabledTools`, `toolsApi.invoke`, `ToolDef`, `ToolCall`, `ToolResult` (existing types).
- Produces: pure helper `src/views/voiceTools.viewmodel.ts` with `buildVoiceToolDefs(enabledRows, cameraEnabled) -> ToolDef[]`, `serializeToolResult(envelope) -> string`, `describeToolCall(name, argsSummary) -> string`.

- [ ] **Step 1: Write failing tests**

```ts
const rows = [ {id:'tool-search',...}, {id:'tool-custom',scope:'session',effectiveEnabled:null} ]
expect(buildVoiceToolDefs(rows,false).map(t=>t.name)).toEqual(['tool-search','tool-custom'])
expect(serializeToolResult({mode:'demo',provider:'anspire',data:{results:[...]}})).toContain('"mode":"demo"')
test_session_scope_tool_reaches_agent() // localStorage enabled → included
test_camera_tool_still_present_when_enabled()
```

- [ ] **Step 2: Run to verify fails.**

- [ ] **Step 3: Wire the voice page** — `VoiceView` imports `useToolsStore`, loads tools on mount, `tools` computed uses `buildVoiceToolDefs(toolsStore.enabledTools, store.settings.tools.camera)`; `runTool` checks `camera_snapshot` first, else looks up row by name and calls `toolsApi.invoke(id, args)`, returning `{output: serializeToolResult(envelope)}`; `describeTool` uses row name/desc. `onToolsChange` already calls `client.setTools()` — keep. `ToolsDialog` rewritten to list `toolsStore.rows` with switches calling `toolsStore.toggle()`, no hard-coded English.

- [ ] **Step 4: Run tests — `npx vitest run src/views/voiceTools.viewmodel.spec.ts` and full `npx vitest run` — verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat: make enabled tools callable from voice demo"`.

---

### Task 9: Full verification and visual alignment

**Files:** none (verification task)

**Interfaces:** consumes all previous tasks.

- [ ] **Step 1: Backend full test suite** — `cd console/backend && pytest -q`. Expected: 0 failures (existing known-failing suites excluded if pre-existing — report honestly).

- [ ] **Step 2: Frontend tests** — `cd console/frontend && npx vitest run`. Expected: 0 failures.

- [ ] **Step 3: TypeScript check** — `npx vue-tsc --noEmit 2>&1 | Select-String 'src/(views/ToolsView|stores/tools|api/tools|views/VoiceView|features/voice/components/ToolsDialog)'`. Expected: no new errors in touched paths (existing `MeetingList.vue`-style errors elsewhere are out of scope).

- [ ] **Step 4: Visual comparison** — start frontend (`npm run dev` on :3000) and backend; navigate to `http://localhost:3000/tools`, compare with prototype `#/tools`: top/left padding, 4 KPI cards, filter card, 8-column table, switch/copy/edit/delete buttons. Screenshot both and save under `console/qa-artifacts/` if needed.

- [ ] **Step 5: Voice smoke test** — start the S2S pipeline; open voice demo; enable `tool-weather` (no key → demo mode) and ask "北京今天天气怎么样"; confirm the tool-call bubble appears with `tool-weather`, the result text contains demo data, and the assistant answers. Repeat with `tool-search` enabled and an Anspire/博查 key set in backend `.env` if available.

- [ ] **Step 6: Report** — summarize passing/failed checks and any known deviations.
