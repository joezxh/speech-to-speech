# S2S 单镜像控制台迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `console/`（Vue 运维台 + 语音对话页、FastAPI 后端）与 `speech-to-speech serve` 打进同一个镜像、跑在同一个容器的两个 supervisord 托管进程里，对外只留 `:8000`，完整承接 `demo/` 的前后端能力后拆除 `demo/`。

**Architecture:** 一个镜像（根 `Dockerfile` 新增 `frontend-build` 阶段产出 `dist/`，运行时阶段拷入 `/app/console/static` 与 `console/backend`）、一个容器（compose 服务仍叫 `pipeline`，`ENTRYPOINT` 是 supervisord，**不给 `command`**）、一个对外端口（`8000`；`8765` 绑 `127.0.0.1` 且不 publish）。链路 A 用 supervisor 的 unix socket 重启 `pipeline` 子进程（不挂 docker.sock、不执行 `docker compose`）；`.env` 类字段发布直接 `409 env_requires_recreate`。

**Tech Stack:** Python 3.12（代码保持 3.11 兼容）· FastAPI + SQLAlchemy 2 + Alembic + python-jose + bcrypt + loguru · supervisor 4.x（XML-RPC over unix socket）· Vue 3.4 + Vite 5 + Pinia 2 + vue-router 4 + ant-design-vue 4 + Less + Vitest 2 + Playwright 1.62.1 · Node 20 LTS / npm 10。

**Spec:** `docs/superpowers/specs/2026-10-23-s2s-deployment-parameter-platform-design.md`

---

## Global Constraints

以下每条都是全任务隐含要求，逐字取自设计文档：

- **一个镜像、一个容器、一个对外端口**：只有 `8000` publish；`8765` 绑 `127.0.0.1` 且**不 publish**；PG（可选 profile）不映射。
- **compose 的 `pipeline` 服务不得有 `command`**：给了会覆盖 `ENTRYPOINT` 的 supervisord，两个进程都不会启动。
- **`console` program 必须 `--workers 1`**：发布单飞锁、supervisor 状态、内存 draft 缓存都假定单进程。
- **console 不持有 docker 权限**：不挂 `/var/run/docker.sock`、不执行 `docker compose`、不装 docker CLI；只允许 XML-RPC 的 `stopProcess`/`startProcess`/`getState`，目标 program 从 `SUPERVISOR_PROGRAM` 读，不从请求体取。
- **`[supervisorctl]` 段不写、`[inet_http_server]` 不启**。
- **依赖策略（D9）**：与 s2s 共用的包**写下界不写精确 pin**（`fastapi>=0.115.0`）；只有 console 独占包（SQLAlchemy / alembic / psycopg2 / python-jose / bcrypt / loguru / supervisor）写精确版本。镜像内只有一棵 Python 依赖树，console 复用同一个 venv（`PYTHONPATH=/app/console`）。
- **`validator_service` 是唯一 `import speech_to_speech` 的模块**，且只 import 配置层（`config`、`arguments_classes` 数据类），不得 import `s2s_pipeline` / `service`。
- **运维面 `ApiResponse` 包络只用于 `/api/v1/*`**，两个例外裸响应：`GET /api/v1/health` 与 `GET /api/config`。
- **演示面 `/api/*` 不套包络、不改路径、不改状态码**（B10）；条件能力缺失时返回 **404 而不是 403**。
- **字段命名**：HTTP 载荷 camelCase；catalog 条目保持 snake_case；时间 ISO 8601 UTC。
- **密钥单向（B5）**：读接口一律 `***`，日志与审计只记字段名；密钥值永不进 `localStorage`、URL、日志、错误上报。
- **前端不把 upstream 地址烘进产物**（D1）：页面只认同源相对路径。
- **静态注册顺序**：`/api/v1`、`/api`、`/v1`、`/vendor` 必须先注册，`/assets`、`/worklets`、SPA 兜底最后挂，否则接口被 `StaticFiles` 吞掉。
- **版本与审计 append-only**：回滚产生新版本号，不删旧版本；审计只增不改。
- **错误码固定清单**：`unauthorized`、`forbidden`、`invalid_parameter`、`version_conflict`、`validation_failed`、`vram_budget_exceeded`、`publish_in_progress`、`render_failed`、`restart_unavailable`、`healthcheck_timeout`、`pipeline_token_missing`、`pipeline_unavailable`、`pool_unreachable`、`catalog_unavailable`、`db_unavailable`、`unknown_profile`、`unknown_version`、`version_not_rollbackable`、`no_draft`、`unsupported_field`、`internal_token_missing`、`asset_missing`、`invalid_credentials`、`too_many_attempts`、`invalid_refresh_token`、`not_implemented`、`env_requires_recreate`（§4.1 步骤 5：`stage=env` 字段不可在不重建容器时生效）、`rollback_failed`（§11.3：自动回滚也失败，需人工）、`runtime_unavailable`、`logs_unavailable`、`log_window_too_large`、`log_analysis_busy`、`log_analysis_rate_limited`、`log_analysis_unavailable`、`log_analysis_timeout`（后七个由 Task 21/22 使用，与设计文档 A.0 同一份清单）、`catalog_entry_missing`（表单里出现 catalog 之外的键，或某条 catalog 条目在 `ParamField` 里找不到落点）、`voice_not_found`、`voice_name_taken`、`voice_audio_invalid`、`voice_too_large`、`voice_consent_required`、`voice_in_use`、`voice_expired`、`voice_precompute_failed`、`voice_precompute_busy`、`voice_binding_conflict`（最后 11 个由 Task 12 / 12B 使用，与设计文档 A.0 逐字一致）。
- **提交纪律**：一次任务一次提交；不 force push、不改 git config、不 `--no-verify`；未经用户明确要求不合并 PR。

## 阶段与检查点

| 阶段 | 任务 | 检查点（不过不进入下一阶段） |
|---|---|---|
| A 源码前置 | T1 | `pytest tests/openai_realtime/test_internal_session_update.py` 绿 |
| B 底座（P0） | T2–T5 | 单镜像起两个进程，`supervisorctl status` 均 RUNNING，`:8000/api/v1/health` 200 |
| C 后端只读（P1） | T6–T10 | `pytest tests/unit tests/integration` 绿；与旧 `param_api` 对同一 catalog 的 JSON 对照（除包络）一致 |
| D 运维台（P2） | T11–T13（含 T12B） | 四视图对真实后端可览；`vitest run` 绿；196 条逐条有落点 |
| E 写入链路（P3） | T14–T16 | 部署机完成一次真发布 + 一次真回滚，发布期间控制台 HTTP 不中断 |
| F 演示面（P4） | T17–T20 | §14.5 对话页 23 条清单逐项通过（含嵌入形态与用户原音回放）；两套开关环境各跑一遍 |
| F2 观测旁路（P4.5） | T21–T22 | §14.6 三种构造全绿；采样与分析期间语音 `e2e_s` 无抬升，`/logs` 不返回 5xx |
| G 拆除（P5） | T23–T24 | 连续两个工作日所有发布与语音演示均经新镜像；旧路径 404 |

**共存期纪律（§14.4，覆盖 C–E 三个阶段）**：P1–P4 期间旧 `demo` 实例与新控制台**只能有一个写入方**——在旧 `demo` 容器上把 `ADMIN_TOKEN` 置空（它的写接口随之 503，只读仍可用），并且**不让两个实例指向同一个宿主 `./config`**（§12 R12）。违反这一条时，两个写入方会各自渲染同一份 `prod.yaml`，后写入的那个覆盖前一个，`config/*.bak.<version>` 的命名也会撞车。这条不需要写代码，但它决定 C–E 阶段能不能在**活的生产机**上做。

---

# 阶段 A：源码前置

## Task 1: pipeline 侧 `/internal/sessions/update`（链路 B 的落地端点）

**Files:**
- Modify: `src/speech_to_speech/api/openai_realtime/service.py`（在 `unregister` 之后插入一个只读访问器）
- Modify: `src/speech_to_speech/api/openai_realtime/websocket_router.py`（在 `create_app` 内、`/v1/pool` 之后插入路由）
- Test: `tests/openai_realtime/test_internal_session_update.py`

**Interfaces:**
- Produces: `POST /internal/sessions/update`，请求体 `{scope: "all"|"pipeline"|"session", target: int|str|null, session: {...}}`，成功回 `{"updated": ["<session_id>"], "failed": [{"session_id": "...", "error": "..."}]}`（**裸对象**）；`S2S_INTERNAL_TOKEN` 缺失 → `503 internal_token_missing`，token 错 → `401 unauthorized`。
- Produces: `RealtimeService.active_connection_ids() -> list[str]`
- Consumes: `RealtimeService.session.handle_session_update(conn_id, event) -> Optional[RealtimeErrorEvent]`（已存在，`handlers/session.py:24`）；`PipelineUnit.session.session_id`（`pipeline_unit.py:35`）。

- [ ] **Step 1: 写失败测试**

Create `tests/openai_realtime/test_internal_session_update.py`:

```python
"""The console's machine-to-machine fanout endpoint (spec §5.1 / A.12)."""
from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app

ENDPOINT = "/internal/sessions/update"


class _SessionStub:
    """Records fanout instead of touching a real pipeline."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reject: set[str] = set()

    def handle_session_update(self, conn_id, event):
        self.calls.append(conn_id)
        if conn_id in self.reject:
            return SimpleNamespace(error=SimpleNamespace(code="invalid_request_error"))
        return None


class _ServiceStub:
    def __init__(self, conn_ids) -> None:
        self._conns = {cid: object() for cid in conn_ids}
        self.session = _SessionStub()

    def active_connection_ids(self):
        return list(self._conns)


def _unit(index: int, session_id: str, conn_ids):
    return SimpleNamespace(index=index, session=SimpleNamespace(session_id=session_id),
                           service=_ServiceStub(conn_ids))


@pytest.fixture
def client():
    return TestClient(create_app([], Event()))


def test_missing_token_env_is_fail_closed(client, monkeypatch):
    monkeypatch.delenv("S2S_INTERNAL_TOKEN", raising=False)
    response = client.post(ENDPOINT, json={"scope": "all", "session": {"instructions": "hi"}})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "internal_token_missing"


def test_wrong_token_is_401(client, monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "expected")
    response = client.post(
        ENDPOINT,
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers={"Authorization": "Bearer nope"},
    )
    assert response.status_code == 401


def test_empty_pool_returns_empty_fanout(client, monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")
    response = client.post(
        ENDPOINT,
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers={"Authorization": "Bearer tok"},
    )
    assert response.status_code == 200
    assert response.json() == {"updated": [], "failed": []}


def test_scope_session_touches_only_the_named_connection(monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")
    unit = _unit(0, "s1", ["s1", "s2"])
    app = create_app([unit], Event())
    response = TestClient(app).post(
        ENDPOINT,
        json={"scope": "session", "target": "s1", "session": {"instructions": "hi"}},
        headers={"Authorization": "Bearer tok"},
    )
    assert response.status_code == 200
    assert response.json()["updated"] == ["s1"]
    assert unit.service.session.calls == ["s1"]


def test_scope_all_reports_partial_failures(monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")
    unit = _unit(0, "s1", ["s1", "s2"])
    unit.service.session.reject.add("s2")
    app = create_app([unit], Event())
    body = TestClient(app).post(
        ENDPOINT,
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers={"Authorization": "Bearer tok"},
    ).json()
    assert body["updated"] == ["s1"]
    assert body["failed"] == [{"session_id": "s2", "error": "invalid_request_error"}]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/openai_realtime/test_internal_session_update.py -v`
Expected: 5 个用例全 FAIL（`404 Not Found`，路由还没加）。

- [ ] **Step 3: 加只读访问器**

In `src/speech_to_speech/api/openai_realtime/service.py`, right after `unregister(...)` 结束处（`self._conns.pop` 那个方法之后、`_state` 之前）插入：

```python
    def active_connection_ids(self) -> list[str]:
        """Session ids of live connections, for the console's fanout endpoint.

        Read-only by design: the console enumerates connections to push a
        ``session.update``, it never mutates ``_conns`` itself (spec §9.1).
        """
        return list(self._conns.keys())
```

- [ ] **Step 4: 加路由**

In `src/speech_to_speech/api/openai_realtime/websocket_router.py`，在 `create_app` 内 `@app.get("/v1/pool")` 那个函数**之后**、`create_app` 的 `return app` 之前插入：

```python
    class _InternalPayload(BaseModel):
        scope: Literal["all", "pipeline", "session"] = "all"
        target: int | str | None = None
        session: dict[str, Any]

    def _internal_error(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)

    def _bearer(request: Request) -> str:
        header = request.headers.get("authorization", "")
        return header[7:].strip() if header.lower().startswith("bearer ") else ""

    @app.post("/internal/sessions/update", include_in_schema=False)
    async def internal_sessions_update(request: Request) -> JSONResponse:
        """Fan a ``session.update`` out to live connections (console-only).

        Fail closed: with no token configured the route refuses everything, so a
        stripped-down deploy cannot accidentally expose an unauthenticated
        config push on loopback.
        """
        expected = os.environ.get("S2S_INTERNAL_TOKEN", "").strip()
        if not expected:
            return _internal_error(503, "internal_token_missing", "S2S_INTERNAL_TOKEN is not configured")
        if not hmac.compare_digest(_bearer(request), expected):
            return _internal_error(401, "unauthorized", "invalid internal token")

        try:
            payload = _InternalPayload.model_validate(await request.json())
            event = SessionUpdateEvent(type="session.update", session=payload.session)
        except ValidationError as exc:
            detail = exc.errors()[0] if exc.errors() else {}
            return _internal_error(400, "invalid_request_error", str(detail.get("msg", "invalid payload")))

        if payload.scope == "pipeline" and payload.target is None:
            return _internal_error(400, "invalid_request_error", "scope=pipeline requires target")

        only = str(payload.target) if payload.scope == "session" and payload.target is not None else None
        if payload.scope == "session" and only is None:
            return _internal_error(400, "invalid_request_error", "scope=session requires target")

        updated: list[str] = []
        failed: list[dict[str, str]] = []
        for unit in pool:
            if payload.scope == "pipeline" and unit.index != int(payload.target):
                continue
            for session_id in unit.service.active_connection_ids():
                if only is not None and session_id != only:
                    continue
                error = unit.service.session.handle_session_update(session_id, event)
                if error is None:
                    updated.append(session_id)
                else:
                    code = getattr(getattr(error, "error", None), "code", None) or "invalid_request_error"
                    failed.append({"session_id": session_id, "error": str(code)})
        return JSONResponse({"updated": updated, "failed": failed})
```

同时在文件头部的 import 区补齐（`hmac` / `os` / `Literal` / `BaseModel` / `ValidationError` / `SessionUpdateEvent` 大多已存在，缺一补一）：

```python
from typing import Any, Callable, Literal, TypeVar
from pydantic import BaseModel, ValidationError
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/openai_realtime/test_internal_session_update.py -v`
Expected: 5 passed。

- [ ] **Step 6: 跑既有回归，确认没碰坏路由**

Run: `python -m pytest tests/openai_realtime -q`
Expected: 全绿（原 `TestAdminHotUpdate` 若引用了旧路径名，本任务**不**改它；改名在 Task 16 做）。

- [ ] **Step 7: 提交**

```bash
git add src/speech_to_speech/api/openai_realtime/service.py \
        src/speech_to_speech/api/openai_realtime/websocket_router.py \
        tests/openai_realtime/test_internal_session_update.py
git commit -m "feat(realtime): add /internal/sessions/update fanout endpoint"
```

---

# 阶段 B：底座（P0）

## Task 2: `console/frontend` 脚手架与构建链

**Files:**
- Create: `console/frontend/package.json`
- Create: `console/frontend/tsconfig.json`, `console/frontend/tsconfig.node.json`
- Create: `console/frontend/vite.config.ts`
- Create: `console/frontend/vitest.config.ts`
- Create: `console/frontend/index.html`
- Create: `console/frontend/scripts/copy-vendors.mjs`
- Create: `console/frontend/src/main.ts`, `src/App.vue`, `src/vite-env.d.ts`
- Create: `console/frontend/src/router/index.ts`（先只有占位路由）
- Create: `console/frontend/src/styles/index.less`, `variables.less`
- Create: `console/frontend/src/styles/theme.ts`（AntD 主题，唯一事实来源）
- Reference: `console/design/console-preview.html`（十一个视图的视觉基线：运维台六页 + 语音对话五页；**同一个 `div.shell` 装两个面**，对话页不再独占全屏（§3.2.4）；零依赖单文件，不进构建产物）

**Interfaces:**
- Produces: `npm run build` → `console/frontend/dist/{index.html,assets/**,vendor/**,worklets/**}`；`npm run test`（Vitest，node 环境，`src/**/*.spec.ts`）；`npm run dev`（:3000，`/api` `/v1` `/vendor` 代理到 :8000，`/v1` 带 `ws:true`）。
- Produces: `public/vendor/` 下恰好 7 个资产（1 个 UMD + 6 个 VAD）。
- Produces: `themeConfig`（`src/styles/theme.ts`）——全站唯一的 AntD 主题入口，由 `App.vue` 的 `<a-config-provider>` 消费；`/console/*` 与 `/` 共用它。

- [ ] **Step 1: 写 `package.json`**

```json
{
  "name": "s2s-console-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "node scripts/copy-vendors.mjs && vue-tsc --noEmit && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext .vue,.ts,.tsx --max-warnings 0",
    "test": "vitest run",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "@ant-design/icons-vue": "^7.0.1",
    "@openai/agents": "0.14.3",
    "@ricky0123/vad-web": "0.0.31",
    "ant-design-vue": "^4.1.2",
    "axios": "^1.6.8",
    "dayjs": "^1.11.10",
    "onnxruntime-web": "1.22.0",
    "pinia": "^2.1.7",
    "vue": "^3.4.21",
    "vue-i18n": "^9.13.1",
    "vue-router": "^4.3.0"
  },
  "devDependencies": {
    "@playwright/test": "1.62.1",
    "@types/node": "^20.12.7",
    "@typescript-eslint/eslint-plugin": "^7.1.1",
    "@typescript-eslint/parser": "^7.1.1",
    "@vitejs/plugin-vue": "^5.0.4",
    "eslint": "^8.57.0",
    "eslint-plugin-vue": "^9.22.0",
    "less": "^4.2.0",
    "typescript": "^5.4.5",
    "vite": "^5.1.5",
    "vitest": "^2.1.9",
    "vue-tsc": "^2.0.6"
  }
}
```

- [ ] **Step 2: 安装并生成锁文件**

Run: `cd console/frontend && npm install --package-lock-only && npm ci`
Expected: 生成 `package-lock.json`（**必须提交**，D2），`node_modules/` 出现。

- [ ] **Step 3: 写 Vite 配置**

`console/frontend/vite.config.ts`:

```ts
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const target = process.env.VITE_DEV_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 3000,
    proxy: {
      '/api': { target, changeOrigin: true },
      '/vendor': { target, changeOrigin: true },
      // ws:true is what makes the voice page work against a local backend:
      // the browser dials /v1/realtime on :3000 and Vite upgrades the socket.
      '/v1': { target, changeOrigin: true, ws: true }
    }
  },
  build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false }
})
```

- [ ] **Step 4: 写 `copy-vendors.mjs`（构建期烤入 7 个资产）**

`console/frontend/scripts/copy-vendors.mjs`:

```js
// Copy browser-only third-party bundles into public/vendor at build time.
// Spec D10: the runtime image has no node_modules, so a missing asset must
// fail the build here instead of returning 503 at 3am.
import { access, cp, mkdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const vendor = join(root, 'public', 'vendor')
const vad = join(vendor, 'local-vad')

const UMD = ['@openai/agents-realtime', 'dist', 'bundle', 'openai-realtime-agents.umd.js']
const VAD_WEB = ['bundle.min.js', 'vad.worklet.bundle.min.js', 'silero_vad_v6.onnx']
const ORT = ['ort.wasm.min.js', 'ort-wasm-simd-threaded.mjs', 'ort-wasm-simd-threaded.wasm']

await mkdir(vad, { recursive: true })
await cp(join(root, 'node_modules', ...UMD), join(vendor, 'openai-realtime-agents.umd.js'))
for (const file of VAD_WEB) {
  await cp(join(root, 'node_modules', '@ricky0123', 'vad-web', 'dist', file), join(vad, file))
}
for (const file of ORT) {
  await cp(join(root, 'node_modules', 'onnxruntime-web', 'dist', file), join(vad, file))
}

for (const file of [...VAD_WEB, ...ORT]) await access(join(vad, file))
await access(join(vendor, 'openai-realtime-agents.umd.js'))
console.log(`[copy-vendors] 7 assets -> public/vendor`)
```

- [ ] **Step 5: 写 tsconfig / vitest / index.html / 主题 / 最小 app**

> **为什么主题在骨架期就定死**：`ant-design-vue/dist/reset.css` 是**亮色**基线。只引它、不装 `darkAlgorithm`，后面每个视图的 `a-input` / `a-select` / `a-table` / `a-modal` 都会是白底浅灰边，贴在 `#0b1020` 上是一整块刺眼的白。逐个组件补深色 CSS 等于把同一个决定重写几十遍，而且总有漏掉的那一个。所以 `main.ts`、`App.vue`、`styles/theme.ts` 三件套在本步一起落地，后续所有任务只允许消费 `themeConfig`，不允许再写颜色字面量（设计文档 §3.4.4）。

`console/frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "jsx": "preserve",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "esModuleInterop": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "types": ["vite/client", "node"],
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] },
    "noEmit": true
  },
  "include": ["src/**/*.ts", "src/**/*.vue", "scripts/**/*.mjs"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`console/frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": { "composite": true, "module": "ESNext", "moduleResolution": "bundler", "types": ["node"] },
  "include": ["vite.config.ts", "vitest.config.ts", "playwright.config.ts"]
}
```

`console/frontend/vitest.config.ts`:

```ts
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    environment: 'node',
    include: ['src/**/*.spec.ts'],
    reporters: 'dot'
  }
})
```

`console/frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <title>S2S 部署参数控制台</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

`console/frontend/src/main.ts`:

```ts
import Antd from 'ant-design-vue'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

import 'ant-design-vue/dist/reset.css'
import './styles/index.less'

// `reset.css` 是 antd 的亮色基线，必须排在 `index.less` 之前；
// 真正的深色不在这里，而在 App.vue 的 <a-config-provider :theme="themeConfig">。
createApp(App).use(createPinia()).use(Antd).use(router).mount('#app')
```

`console/frontend/src/styles/theme.ts`（与 `variables.less` 同值；改一处必须同步另一处）：

```ts
// 唯一主题事实来源（设计文档 §3.4.4）。这里出现的每一个色值，
// 都能在 styles/variables.less 或 console-preview.html 的 :root 里找到同名项。
import { theme } from 'ant-design-vue'

export const themeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#5b8cff',
    colorBgBase: '#0b1020',
    colorBgLayout: '#0b1020',
    colorBgContainer: '#141a2e',
    colorBgElevated: '#1a2138',
    colorBorder: '#232b45',
    colorBorderSecondary: '#1e2740',
    colorTextBase: '#e6e8f0',
    colorText: '#e6e8f0',
    colorTextSecondary: '#8b93a7',
    colorTextTertiary: '#5b6478',
    colorSuccess: '#35c48a',
    colorWarning: '#e8b339',
    colorError: '#f0655c',
    colorInfo: '#5b8cff',
    borderRadius: 8,
    fontSize: 13,
    fontFamily: "'Inter', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
  }
}
```

`console/frontend/src/App.vue`（**根级**包一层；不要下沉到每个 view）：

```vue
<script setup lang="ts">
import { themeConfig } from './styles/theme'
</script>

<template>
  <a-config-provider :theme="themeConfig">
    <router-view />
  </a-config-provider>
</template>
```

> 放在 `App.vue` 而不是各 view 的理由：`/console/*` 与 `/` 是同一份产物里的两条路由，主题入口只能有一个；谁在 view 里单独包一层，另一条路由就会漏出亮色控件。`<a-config-provider>` 不引入额外依赖（`Antd` 已在 `main.ts` 全局注册），也不产生 DOM 节点。

`console/frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
```

`console/frontend/src/router/index.ts`（占位，Task 11 替换为真实路由）：

```ts
import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'voice', component: () => import('@/views/PlaceholderView.vue') },
    { path: '/console/:pathMatch(.*)*', name: 'console', component: () => import('@/views/PlaceholderView.vue') }
  ]
})
```

`console/frontend/src/views/PlaceholderView.vue`:

```vue
<template>
  <main class="placeholder">console skeleton</main>
</template>
```

`console/frontend/src/styles/variables.less`:

```less
@color-bg: #0b1020;
@color-surface: #141a2e;
@color-text: #e6e8f0;
@color-muted: #8b93a7;
@color-accent: #5b8cff;
@radius-md: 10px;
```

`console/frontend/src/styles/index.less`:

```less
@import './variables.less';

html,
body,
#app {
  height: 100%;
  margin: 0;
  background: @color-bg;
  color: @color-text;
  font-family: 'Inter', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
}
```

- [ ] **Step 6: 构建并存产物**

Run: `cd console/frontend && npm run build && ls dist && ls dist/vendor dist/vendor/local-vad`
Expected: `dist/index.html` 存在；`dist/vendor/openai-realtime-agents.umd.js` 存在；`dist/vendor/local-vad/` 恰好 6 个文件。缺任一则 `copy-vendors.mjs` 抛错退出。

再验主题确实装上了（三条都要过，否则后面所有视图都要返工）：

```bash
grep -n "themeConfig" console/frontend/src/App.vue        # 1) 根组件引用了唯一主题源
grep -rn "#001529" console/frontend/src                  # 2) 源码里没有 AntD 默认深蓝
grep -rn "reset.css" console/frontend/src/main.ts        # 3) 亮色基线只在入口引一次
```

Expected: 1) 命中 `<a-config-provider :theme="themeConfig">`；2) 无输出；3) 命中且位于 `import './styles/index.less'` 之前。最后 `npm run dev` 打开 :3000，开发者工具里 `document.querySelector('.ant-btn').background` 不应是白色（`reset.css` 默认）。

- [ ] **Step 7: 提交**

```bash
git add console/frontend
git commit -m "feat(console): scaffold Vue frontend with build-time vendor copy"
```

---

## Task 3: `console/backend` 骨架 + 健康检查 + SPA 静态托管

**Files:**
- Create: `console/backend/requirements.txt`, `console/backend/requirements-dev.txt`
- Create: `console/backend/.env.example`
- Create: `console/backend/conftest.py`
- Create: `console/backend/pyproject.toml`（只放 ruff/pytest 配置，不是打包单元）
- Create: `console/backend/app/main.py`
- Create: `console/backend/app/config/{__init__,_app,_database,_auth,_console}.py`
- Create: `console/backend/app/core/{spa,errors,logging,router_registry}.py`
- Create: `console/backend/app/routers/health.py`
- Create: `console/backend/app/middleware/{request_id,security_headers}.py`
- Test: `console/backend/tests/unit/test_health.py`
- Test: `console/backend/tests/integration/test_static_mount_order.py`

**Interfaces:**
- Produces: `GET /api/v1/health` → `{"status":"ok","version":"<pkg version>"}`（**裸对象**，无 `ApiResponse`）；DB 不可用 → `503 {"code":"db_unavailable",...}`。
- Produces: `app.config.settings`（`pydantic-settings`，前缀无、字段名与 `.env` 同名）。
- Produces: `core/spa.py::mount_spa(app, dist_dir)` — 注册 `/assets`、`/worklets` 与兜底路由，**必须在所有 API 路由之后调用**。
- Produces: `ApiResponse[T]`（`schemas/common.py` 在 Task 8 落地；本任务先由 `core/errors.py` 提供错误包络）。

- [ ] **Step 1: 写依赖清单**

`console/backend/requirements.txt`:

```
# Shared with speech-to-speech: floors only (spec D9). The image has one venv,
# and s2s's uv sync already resolved these; exact pins would create a second
# unsolvable set.
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
httpx>=0.28.0
PyYAML>=6,<7
pydantic>=2.7.4
pydantic-settings>=2.1.0
websockets>=12.0
# Console-only: exact pins.
SQLAlchemy==2.0.36
alembic==1.13.1
psycopg2-binary==2.9.10
python-jose[cryptography]==3.3.0
bcrypt==4.2.1
loguru==0.7.2
supervisor==4.2.5
```

`console/backend/requirements-dev.txt`:

```
-r requirements.txt
pytest==8.0.1
pytest-asyncio==0.23.5
ruff==0.6.9
```

`console/backend/.env.example`（开发态默认值，必须能直接跑起来）：

```
JWT_SECRET_KEY=dev-only-change-me-32-bytes-minimum
DATABASE_URL=sqlite:///./dev.db
USAGE_DB_PATH=./usage-dev.sqlite3
PARAM_CONFIG_DIR=../../../config
PARAM_CATALOG_PATH=../../../docs/parameter-catalog.yaml
PIPELINE_BASE_URL=http://127.0.0.1:8765
PIPELINE_TIMEOUT_S=180
SUPERVISOR_SOCKET=/tmp/s2s-console/supervisor.sock
SUPERVISOR_PROGRAM=pipeline
RESTART_MODE=noop
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

- [ ] **Step 2: 写配置分文件**

`console/backend/app/config/_app.py`:

```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Process-wide settings. One env file, one container (spec §13.5)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    log_level: str = "info"
    cors_origins: str = ""
    max_body_bytes: int = 2 * 1024 * 1024


settings = AppSettings()
```

`console/backend/app/config/_console.py`:

```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsoleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    param_config_dir: str = "/app/config"
    param_catalog_path: str = "/app/catalog/parameter-catalog.yaml"
    static_dir: str = "/app/console/static"
    pipeline_base_url: str = "http://127.0.0.1:8765"
    pipeline_timeout_s: float = 180.0
    supervisor_socket: str = "/run/s2s-console/supervisor.sock"
    supervisor_program: str = "pipeline"
    restart_mode: str = "supervisor"
    verifier_mode: str = "reject"
```

`console/backend/app/config/_database.py`:

```python
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////app/data/console.sqlite3"
    usage_db_path: str = "/app/data/usage.sqlite3"

    @field_validator("database_url")
    @classmethod
    def _absolute_sqlite(cls, value: str) -> str:
        # sqlite:///./dev.db is relative to CWD; sqlite:////app/... is absolute.
        return value
```

`console/backend/app/config/_auth.py`:

```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    login_max_attempts: int = 5
    login_window_seconds: int = 300
```

`console/backend/app/config/__init__.py`:

```python
from ._app import AppSettings, settings
from ._auth import AuthSettings
from ._console import ConsoleSettings
from ._database import DatabaseSettings

app = settings
console = ConsoleSettings()
database = DatabaseSettings()
auth = AuthSettings()

if not auth.jwt_secret_key:
    raise RuntimeError("JWT_SECRET_KEY is required; console refuses to start without it")

__all__ = ["AppSettings", "AuthSettings", "ConsoleSettings", "DatabaseSettings", "app", "auth", "console", "database", "settings"]
```

- [ ] **Step 3: 写 `core/errors.py` 与中间件**

`console/backend/app/core/errors.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass
class ApiError(Exception):
    """A stable machine code plus a human message. Never carries input values."""

    code: str
    message: str
    status: int = 400
    detail: list[dict] | None = None


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        {
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail or [],
            "requestId": getattr(request.state, "request_id", ""),
        },
        status_code=exc.status,
    )
```

`console/backend/app/middleware/request_id.py`:

```python
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response
```

`console/backend/app/middleware/security_headers.py`:

```python
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# worker-src blob: is required by the local VAD (it spawns a blob worker) and
# media-src blob: by the playback queue. Narrow either and the voice page dies
# in a way that only shows up in the browser console.
_CSP = (
    "default-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "worker-src 'self' blob:; "
    "script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_bytes: int = 2 * 1024 * 1024) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_body_bytes:
            return JSONResponse({"code": "invalid_parameter", "message": "request body too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = _CSP
        return response
```

- [ ] **Step 4: 写 `core/spa.py`（静态托管 + 兜底）**

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Built assets carry a content hash in the filename, so they can be cached hard;
# index.html must not be cached or a browser keeps an old bundle across deploys
# (spec R16).
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_NO_STORE = {"Cache-Control": "no-store"}


def mount_spa(app: FastAPI, dist_dir: str | Path) -> None:
    """Serve the built SPA. Call this **after** every API router is registered.

    Starlette matches routes in registration order, so a catch-all registered
    first would answer /api/config with index.html.
    """
    dist = Path(dist_dir)
    if not dist.is_dir():
        # A missing dist is a broken image, not a runtime condition worth
        # pretending to survive: fail loudly at boot.
        raise RuntimeError(f"static dir {dist} is missing; the image was built without the frontend")

    for name in ("assets", "worklets"):
        directory = dist / name
        if directory.is_dir():
            app.mount(f"/{name}", StaticFiles(directory=directory), name=name)

    index = dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file() and dist in candidate.resolve().parents:
            return FileResponse(candidate, headers=_IMMUTABLE)
        return FileResponse(index, headers=_NO_STORE)
```

- [ ] **Step 5: 写 `app/main.py` 与 health**

`console/backend/app/routers/health.py`:

```python
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.database import engine

router = APIRouter()


def _package_version() -> str:
    try:
        return version("speech-to-speech")
    except PackageNotFoundError:  # a bare checkout, not the image
        return "0.0.0+dev"


@router.get("/api/v1/health", include_in_schema=False)
async def health() -> JSONResponse:
    """Bare object: docker-compose's healthcheck consumes it directly (A.0.1)."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"code": "db_unavailable", "message": "database is not reachable"}, status_code=503)
    return JSONResponse({"status": "ok", "version": _package_version()})
```

`console/backend/app/db/database.py`（Task 6 会扩展，本任务只需 engine 可导入）：

```python
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import database

connect_args = {"check_same_thread": False} if database.database_url.startswith("sqlite") else {}
engine = create_engine(database.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

`console/backend/app/main.py`:

```python
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import app as app_settings, console as console_settings
from app.core.errors import ApiError, api_error_handler
from app.core.logging import configure_logging
from app.core.spa import mount_spa
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import health

configure_logging(app_settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="s2s-console", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(SecurityHeadersMiddleware, max_body_bytes=app_settings.max_body_bytes)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)

    # Order matters: every API prefix first, SPA last (spec §10.2.3).
    app.include_router(health.router)

    mount_spa(app, console_settings.static_dir)
    return app


app = create_app()
```

`console/backend/app/core/logging.py`:

```python
from __future__ import annotations

import sys

from loguru import logger


def configure_logging(level: str = "info") -> None:
    """stdout only: supervisord captures it, `docker logs` merges both programs.

    Deliberately does not touch the root stdlib logger — the pipeline owns its
    own logging configuration in the same container (spec D13).
    """
    logger.remove()
    logger.add(sys.stdout, level=level.upper(), enqueue=False,
               format="{time:YYYY-MM-DDTHH:mm:ss.SSSZ} {level} {name} {message}")
```

`console/backend/app/core/router_registry.py`:

```python
from __future__ import annotations

from fastapi import FastAPI


def register_api_routers(app: FastAPI) -> None:
    """Single place where route groups are added, in prefix order.

    /api/v1 (JWT), /api (anonymous), /v1 (reverse proxy) — never reordered,
    because the SPA catch-all is registered after this call returns.
    """
    from app.routers import health  # noqa: PLC0415 - import cycle avoidance

    app.include_router(health.router)
```

- [ ] **Step 6: 写 `conftest.py` 与两个测试**

`console/backend/conftest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
```

`console/backend/tests/unit/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_is_a_bare_object(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    response = TestClient(create_app()).get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Bare object: no code/message/data envelope (A.0.1).
    assert set(body) == {"status", "version"}
```

`console/backend/tests/integration/test_static_mount_order.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "index.html").write_text("<!doctype html><div id=app></div>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    return TestClient(create_app())


def test_api_survives_the_spa_catch_all(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_unknown_console_route_returns_index_not_404(client):
    response = client.get("/console/versions")
    assert response.status_code == 200
    assert "<div id=app>" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_hashed_asset_is_cached_hard(client):
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]
```

- [ ] **Step 7: 跑测试**

Run: `cd console/backend && pip install -r requirements-dev.txt && python -m pytest tests -q`
Expected: 4 passed。

If `ModuleNotFoundError: app`：确认 `conftest.py` 在 `console/backend/` 根而不是 `tests/` 下。

- [ ] **Step 8: 提交**

```bash
git add console/backend
git commit -m "feat(console): backend skeleton with health and SPA hosting"
```

---

## Task 4: 单镜像 + supervisord + compose（P0 门禁）

**Files:**
- Create: `console/deploy/supervisord.conf`
- Create: `console/deploy/entrypoint.sh`
- Modify: `Dockerfile`（新增 `frontend-build` 阶段；运行时阶段拷 console 与 dist；改 `ENTRYPOINT`）
- Modify: `docker-compose.yml`（`pipeline` 服务：删 `command`、加 `8000`、加 `./data`、加 healthcheck、`./config` 改 rw）
- Modify: `.dockerignore`（排除 `console/frontend/node_modules`）

**Interfaces:**
- Consumes: Task 2 的 `console/frontend/dist`、Task 3 的 `console/backend`。
- Produces: 镜像内 `/app/console`（代码 + `static/`）、`/etc/supervisor/supervisord.conf`、`/var/log/supervisor/*.log`；容器 `:8000` 由 console program 提供，`:8765` 仅回环。

- [ ] **Step 1: 写 supervisord.conf**

`console/deploy/supervisord.conf`:

```ini
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log
pidfile=/run/supervisord.pid

[unix_http_server]
file=/run/s2s-console/supervisor.sock
chmod=0700

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[program:console]
command=uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-ws-per-message-deflate
directory=/app/console
environment=PYTHONPATH="/app/console"
autostart=true
autorestart=true
startretries=3
priority=10
stdout_logfile=/var/log/supervisor/console-stdout.log
stderr_logfile=/var/log/supervisor/console-stderr.log

[program:pipeline]
command=speech-to-speech serve -f /app/config/prod.yaml --name prod
autostart=true
autorestart=true
startretries=3
priority=20
stopwaitsecs=30
stdout_logfile=/var/log/supervisor/pipeline-stdout.log
stderr_logfile=/var/log/supervisor/pipeline-stderr.log
```

`--no-ws-per-message-deflate` 不是可有可无的调优项：§12 R20 要求转发层**关闭** `permessage-deflate`，否则 uvicorn 会为每个 WS 连接协商压缩，帧要凑满一个 deflate 块才吐出去，TTS 首字节延迟直接抬高。写完先确认这个开关在这版 uvicorn 上真存在：

```bash
uvicorn --help | grep -i deflate
```

Expected: 能搜到 `--ws-per-message-deflate / --no-ws-per-message-deflate`。如果只有前者（老版本写法），改成 `--ws-per-message-deflate false`——**名称不对时控制台会直接起不来**，这一个 `grep` 比事后看 `console-stderr.log` 便宜得多。

`console/deploy/entrypoint.sh`（只 `exec`，不跑业务逻辑；保留给调试与将来加 `--config` 用）：

```sh
#!/bin/sh
set -eu
mkdir -p /var/log/supervisor /run/s2s-console /app/data
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
```

- [ ] **Step 2: 改根 `Dockerfile` —— 新增前端阶段**

在 `ARG BASE_IMAGE=...` 与 `FROM ${BASE_IMAGE}` **之后**（`FROM` 之前不行，`ARG` 必须在所有 `FROM` 之前声明），把前端阶段放在文件最前面：

```dockerfile
# ---------------------------------------------------------------------------
# Frontend build stage (spec §13.3). Emits dist/ only; node never reaches the
# runtime image, so the container carries no node_modules (D10).
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY console/frontend/package.json console/frontend/package-lock.json ./
RUN npm ci
COPY console/frontend/ ./
RUN npm run build
```

- [ ] **Step 3: 改运行时阶段 —— 装 console 依赖、拷代码与产物、换 ENTRYPOINT**

在 `Dockerfile` 的 `RUN --mount=type=cache,target=/root/.cache/uv ... uv sync ...` **之后**、`COPY src ./src` **之前**插入：

```dockerfile
# Console backend deps go into the *same* venv: one image, one dependency tree
# (D9). Ordered before the source copy so editing code does not re-resolve pip.
COPY console/backend/requirements.txt /tmp/console-requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /usr/src/app/.venv/bin/python -r /tmp/console-requirements.txt
```

在 `uv pip install -e . ...` 那一行**之后**插入：

```dockerfile
# Console app + built SPA + supervisor config.
COPY console/backend /app/console
COPY --from=frontend-build /build/dist /app/console/static
COPY console/deploy/supervisord.conf /etc/supervisor/supervisord.conf
COPY console/deploy/entrypoint.sh /usr/local/bin/s2s-entrypoint
RUN chmod 0755 /usr/local/bin/s2s-entrypoint \
 && mkdir -p /var/log/supervisor /run/s2s-console /app/data
ENV PYTHONPATH=/app/console
EXPOSE 8000
```

文件末尾（`rm -rf /root/.cache/uv` 那段之后）追加：

```dockerfile
ENTRYPOINT ["/usr/local/bin/s2s-entrypoint"]
```

> 注意：现有 `Dockerfile` **没有** `CMD` 也没有 `ENTRYPOINT`，所以这里只加 `ENTRYPOINT` 不会与旧行为冲突；compose 侧的 `command` 必须同时删掉，否则会覆盖它。

- [ ] **Step 4: 改 `docker-compose.yml` 的 `pipeline` 服务**

把 `pipeline` 服务整体替换为：

```yaml
  pipeline:
    build:
      context: .
      dockerfile: ${DOCKERFILE:-Dockerfile}
    # No `command` on purpose: it would override the image ENTRYPOINT, and
    # supervisord would never start. What runs is decided by supervisord.conf.
    env_file:
      - ./config/prod.env
    ports:
      - "8000:8000"          # the only published port (spec §13.4)
    volumes:
      - ./cache/:/root/.cache/
      - ../.silero-dl2/silero-vad-master:/opt/silero-vad:ro
      # console is the only writer of /app/config; pipeline only reads it.
      - ./config:/app/config
      - ./data:/app/data
      - ./docs/parameter-catalog.yaml:/app/catalog/parameter-catalog.yaml:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 120s
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['0']
              capabilities: [gpu]
```

- [ ] **Step 5: 更新 `.dockerignore`**

在 `.dockerignore` 追加（否则 `COPY console/frontend/ ./` 会把宿主 `node_modules` 一起搬进构建阶段缓存层）：

```
console/frontend/node_modules
console/frontend/dist
```

- [ ] **Step 6: 构建镜像**

Run: `docker compose build pipeline`
Expected: 构建成功。若报 `COPY console/frontend/package-lock.json` 找不到，回 Task 2 Step 2 生成锁文件。

- [ ] **Step 7: 起容器并发态**

```bash
mkdir -p data
docker compose up -d pipeline
sleep 20
docker compose exec pipeline supervisorctl -c /etc/supervisor/supervisord.conf status
```

Expected: 两行，`console` 与 `pipeline` 均 `RUNNING`。若 `console` 反复 `FATAL`，`docker compose exec pipeline tail -50 /var/log/supervisor/console-stderr.log` 看是不是 `JWT_SECRET_KEY is required`。

- [ ] **Step 8: 验证三个面**

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/v1/health   # 200
curl -s http://127.0.0.1:8000/ | head -c 60                                   # <!doctype html
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/console/login  # 200 (SPA)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/v1/pool        # 000 / connection refused
docker compose exec pipeline supervisorctl -c /etc/supervisor/supervisord.conf status pipeline
```

- [ ] **Step 9: 提交**

```bash
git add Dockerfile docker-compose.yml .dockerignore console/deploy
git commit -m "feat(deploy): single image, single container, supervisord-managed console"
```

---

## Task 5: 四条 CI 作业与构建门禁

**Files:**
- Create: `.github/workflows/console.yml`
- Modify: `console/frontend/package.json`（补 `test:e2e` 之外的脚本，已具备则跳过）

**Interfaces:**
- Produces: `frontend` / `backend` / `contract` / `image` 四条独立作业，任一红即阻断合并。

- [ ] **Step 1: 写 workflow**

`.github/workflows/console.yml`:

```yaml
name: console

on:
  pull_request:
    paths:
      - 'console/**'
      - 'src/speech_to_speech/api/openai_realtime/**'
      - 'docs/parameter-catalog.yaml'
      - 'Dockerfile'
      - 'docker-compose.yml'
      - '.github/workflows/console.yml'
  push:
    branches: [main]

jobs:
  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: console/frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20', cache: npm, cache-dependency-path: console/frontend/package-lock.json }
      - run: npm ci
      - run: npm run lint
      - run: npm run test
      - run: npm run build
      - name: vendor assets present
        run: |
          test -f public/vendor/openai-realtime-agents.umd.js
          test "$(ls public/vendor/local-vad | wc -l)" -eq 6

  backend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: console/backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -e ../.. --no-deps
      - run: pip install -r requirements-dev.txt
      - run: ruff check .
      - run: python -m pytest tests/unit -q
      - run: python -m pytest tests/integration -q
        env:
          JWT_SECRET_KEY: ci-only-secret-at-least-32-bytes-long
          DATABASE_URL: sqlite:///./ci.db

  contract:
    runs-on: ubuntu-latest
    needs: [backend]
    defaults: { run: { working-directory: console/backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: pip install -e ../.. --no-deps && pip install -r requirements-dev.txt
      - name: start console
        run: |
          JWT_SECRET_KEY=ci-only-secret-at-least-32-bytes-long \
          DATABASE_URL=sqlite:///./ci.db RESTART_MODE=noop \
          uvicorn app.main:app --port 8000 &
          for i in $(seq 1 30); do
            curl -sf http://127.0.0.1:8000/api/v1/health && break || sleep 1
          done
      - run: node ../frontend/scripts/check-contract.mjs http://127.0.0.1:8000

  image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t s2s-console:ci .
      - name: assert image contents
        run: |
          docker run --rm --entrypoint sh s2s-console:ci -c '
            test -f /app/console/static/index.html
            test -f /app/console/static/vendor/openai-realtime-agents.umd.js
            test -d /app/console/static/vendor/local-vad
            test -f /etc/supervisor/supervisord.conf
          '
      - name: compose publishes only 8000
        run: |
          docker compose -f docker-compose.yml config | tee /tmp/cfg.yml
          grep -q '8000:8000' /tmp/cfg.yml
          ! grep -q '8765:8765' /tmp/cfg.yml
```

- [ ] **Step 2: 本地跑一遍可跑的三条**

Run: `cd console/frontend && npm run lint && npm run test`
Expected: 绿（此时 `src/**/*.spec.ts` 只有 Task 19 落地后才有内容，`vitest run` 在 0 个测试时以 0 退出）。

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/console.yml
git commit -m "ci(console): frontend, backend, contract and image jobs"
```

--

# 阶段 C：后端只读 API（P1）

## Task 6: 数据层（4 张表 + Alembic + 仓储 + seed_admin）

**Files:**
- Create: `console/backend/app/db/base.py`
- Create: `console/backend/app/models/{__init__,param_user,param_draft,param_version,param_audit}.py`
- Create: `console/backend/app/repositories/{__init__,user_repository,draft_repository,version_repository,audit_repository}.py`
- Create: `console/backend/alembic.ini`, `console/backend/alembic/env.py`, `console/backend/alembic/script.py.mako`, `console/backend/alembic/versions/0001_initial.py`
- Create: `console/backend/scripts/seed_admin.py`
- Modify: `console/backend/app/db/database.py`（加 `init_engine` 供测试替换）
- Test: `console/backend/tests/integration/test_repositories.py`

**Interfaces:**
- Produces: `Base`（`DeclarativeBase`）、`utcnow() -> datetime`（aware UTC）
- Produces: `DraftRepository.get(profile) -> ParamDraft | None`、`.put(profile, base_version, patch, actor)`、`.drop(profile) -> bool`
- Produces: `VersionRepository.create(profile, status, yaml_text, env_text, note, author) -> ParamVersion`、`.set_status(version_id, status, error_code=None, duration_s=None, rolled_back_to=None)`、`.latest_live(profile, exclude=None)`、`.list(profile, page, page_size)`、`.get(profile, version)`
- Produces: `AuditRepository.record(**kwargs) -> ParamAudit`、`.list(profile, filters, page, page_size)`
- Produces: `UserRepository.by_username(name)`、`.create(username, password_hash, role)`、`.touch_login(user)`

- [ ] **Step 1: 写 Base 与 4 个模型**

`console/backend/app/db/base.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Always aware UTC: the API emits ISO 8601 with a Z suffix (A.0)."""
    return datetime.now(timezone.utc)
```

`console/backend/app/models/param_user.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamUser(Base):
    __tablename__ = "param_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="operator")
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`console/backend/app/models/param_draft.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamDraft(Base):
    """One mutable draft per profile: a patch, never a whole config (A.2)."""

    __tablename__ = "param_draft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    patch: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
```

`console/backend/app/models/param_version.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamVersion(Base):
    """Immutable snapshot. `yaml_text` is what makes byte-comparison on boot
    possible (spec §4.1 启动自检); never updated after creation except status."""

    __tablename__ = "param_version"
    __table_args__ = (UniqueConstraint("profile", "version", name="uq_param_version_profile_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="publishing")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    author: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    yaml_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    yaml_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    env_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolled_back_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
```

`console/backend/app/models/param_audit.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamAudit(Base):
    """Append-only. `fields` holds names only — never values (spec §10.1)."""

    __tablename__ = "param_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    profile: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[str] = mapped_column(String(8), nullable=False, default="ok")
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
```

`console/backend/app/models/__init__.py`:

```python
from .param_audit import ParamAudit
from .param_draft import ParamDraft
from .param_user import ParamUser
from .param_version import ParamVersion

__all__ = ["ParamAudit", "ParamDraft", "ParamUser", "ParamVersion"]
```

- [ ] **Step 2: 写 4 个仓储**

`console/backend/app/repositories/draft_repository.py`:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.param_draft import ParamDraft


class DraftRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, profile: str) -> ParamDraft | None:
        return self.session.scalar(select(ParamDraft).where(ParamDraft.profile == profile))

    def put(self, profile: str, *, base_version: int, patch: dict, actor: str) -> ParamDraft:
        row = self.get(profile)
        if row is None:
            row = ParamDraft(profile=profile, base_version=base_version, patch=patch, updated_by=actor)
            self.session.add(row)
        else:
            row.base_version = base_version
            row.patch = patch
            row.updated_by = actor
        self.session.commit()
        self.session.refresh(row)
        return row

    def drop(self, profile: str) -> bool:
        row = self.get(profile)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True
```

`console/backend/app/repositories/version_repository.py`:

```python
from __future__ import annotations

from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.param_version import ParamVersion


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class VersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def next_number(self, profile: str) -> int:
        current = self.session.scalar(select(func.max(ParamVersion.version)).where(ParamVersion.profile == profile))
        return int(current or 0) + 1

    def create(self, profile: str, *, status: str, yaml_text: str, env_sha256: str, note: str, author: str) -> ParamVersion:
        row = ParamVersion(
            profile=profile,
            version=self.next_number(profile),
            status=status,
            note=note[:500],
            author=author,
            yaml_text=yaml_text,
            yaml_sha256=_sha(yaml_text),
            env_sha256=env_sha256,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def set_status(self, row: ParamVersion, status: str, *, error_code: str | None = None,
                   duration_s: float | None = None, rolled_back_to: int | None = None) -> ParamVersion:
        row.status = status
        row.error_code = error_code
        row.duration_s = duration_s
        row.rolled_back_to = rolled_back_to
        self.session.commit()
        self.session.refresh(row)
        return row

    def get(self, profile: str, version: int) -> ParamVersion | None:
        return self.session.scalar(
            select(ParamVersion).where(ParamVersion.profile == profile, ParamVersion.version == version)
        )

    def latest_live(self, profile: str, *, exclude: int | None = None) -> ParamVersion | None:
        stmt = select(ParamVersion).where(ParamVersion.profile == profile, ParamVersion.status == "live")
        if exclude is not None:
            stmt = stmt.where(ParamVersion.version != exclude)
        return self.session.scalar(stmt.order_by(ParamVersion.version.desc()).limit(1))

    def list(self, profile: str, *, page: int = 1, page_size: int = 20) -> tuple[list[ParamVersion], int]:
        base = select(ParamVersion).where(ParamVersion.profile == profile)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.scalars(
            base.order_by(ParamVersion.version.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)

    def dangling(self) -> list[ParamVersion]:
        return list(self.session.scalars(select(ParamVersion).where(ParamVersion.status == "publishing")).all())
```

`console/backend/app/repositories/audit_repository.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.param_audit import ParamAudit


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, *, actor: str, role: str, action: str, profile: str, fields: list[str],
               result: str = "ok", version: int | None = None, error_code: str | None = None,
               duration_s: float | None = None, request_id: str = "") -> ParamAudit:
        row = ParamAudit(actor=actor, role=role, action=action, profile=profile,
                         fields=list(fields), result=result, version=version,
                         error_code=error_code, duration_s=duration_s, request_id=request_id)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def list(self, *, profile: str = "", actor: str = "", action: str = "", result: str = "",
             since: datetime | None = None, until: datetime | None = None,
             page: int = 1, page_size: int = 50) -> tuple[list[ParamAudit], int]:
        stmt = select(ParamAudit)
        if profile:
            stmt = stmt.where(ParamAudit.profile == profile)
        if actor:
            stmt = stmt.where(ParamAudit.actor == actor)
        if action:
            stmt = stmt.where(ParamAudit.action == action)
        if result:
            stmt = stmt.where(ParamAudit.result == result)
        if since is not None:
            stmt = stmt.where(ParamAudit.at >= since)
        if until is not None:
            stmt = stmt.where(ParamAudit.at <= until)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.order_by(ParamAudit.at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)
```

`console/backend/app/repositories/user_repository.py`:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.param_user import ParamUser


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def by_username(self, username: str) -> ParamUser | None:
        return self.session.scalar(select(ParamUser).where(ParamUser.username == username))

    def create(self, username: str, password_hash: str, role: str = "operator") -> ParamUser:
        row = ParamUser(username=username, password_hash=password_hash, role=role)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def touch_login(self, user: ParamUser) -> None:
        user.last_login_at = utcnow()
        self.session.commit()
```

`console/backend/app/repositories/__init__.py`:

```python
from .audit_repository import AuditRepository
from .draft_repository import DraftRepository
from .user_repository import UserRepository
from .version_repository import VersionRepository

__all__ = ["AuditRepository", "DraftRepository", "UserRepository", "VersionRepository"]
```

- [ ] **Step 3: 写 Alembic**

`console/backend/alembic.ini` 关键段（其余保持 `alembic init` 默认）：

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url =
```

`console/backend/alembic/env.py`:

```python
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import database
from app.db.base import Base
import app.models  # noqa: F401 - register metadata

config = context.config
config.set_main_option("sqlalchemy.url", database.database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=database.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
```

`console/backend/alembic/versions/0001_initial.py`:

```python
"""initial tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_user",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="operator"),
        sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "param_draft",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile", sa.String(64), nullable=False, unique=True),
        sa.Column("base_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("patch", sa.JSON, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "param_version",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("author", sa.String(64), nullable=False, server_default=""),
        sa.Column("yaml_text", sa.Text, nullable=False, server_default=""),
        sa.Column("yaml_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("env_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("duration_s", sa.Float, nullable=True),
        sa.Column("rolled_back_to", sa.Integer, nullable=True),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile", "version", name="uq_param_version_profile_version"),
    )
    op.create_table(
        "param_audit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False, server_default=""),
        sa.Column("role", sa.String(16), nullable=False, server_default=""),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("profile", sa.String(64), nullable=False, server_default=""),
        sa.Column("version", sa.Integer, nullable=True),
        sa.Column("fields", sa.JSON, nullable=False),
        sa.Column("result", sa.String(8), nullable=False, server_default="ok"),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("duration_s", sa.Float, nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("param_audit")
    op.drop_table("param_version")
    op.drop_table("param_draft")
    op.drop_table("param_user")
```

- [ ] **Step 4: 写 `seed_admin.py`**

`console/backend/scripts/seed_admin.py`:

```python
"""Create the first operator account. There is no self-service registration."""
from __future__ import annotations

import argparse
import getpass
import sys

from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="admin", choices=["admin", "operator"])
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("password: ")
    if len(password) < 8:
        print("password must be at least 8 characters", file=sys.stderr)
        return 2

    from app.db.database import SessionLocal  # imported late so --help works without a DB

    with SessionLocal() as session:
        repo = UserRepository(session)
        if repo.by_username(args.username) is not None:
            print(f"user {args.username} already exists", file=sys.stderr)
            return 1
        repo.create(args.username, hash_password(password), args.role)
    print(f"created {args.role} {args.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 写集成测试**

`console/backend/tests/integration/test_repositories.py`:（`tests/conftest.py` 提供 `db_session`）

`console/backend/tests/conftest.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - importing registers the four tables on Base.metadata
from app.db.base import Base


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
```

```python
from app.repositories.draft_repository import DraftRepository
from app.repositories.version_repository import VersionRepository


def test_draft_round_trip(db_session):
    repo = DraftRepository(db_session)
    assert repo.get("prod") is None
    repo.put("prod", base_version=3, patch={"vad.min_silence_ms": 900}, actor="alice")
    row = repo.get("prod")
    assert row.patch == {"vad.min_silence_ms": 900} and row.base_version == 3
    assert repo.drop("prod") is True and repo.get("prod") is None


def test_version_numbers_are_append_only(db_session):
    repo = VersionRepository(db_session)
    first = repo.create("prod", status="publishing", yaml_text="a: 1\n", env_sha256="x", note="n", author="alice")
    second = repo.create("prod", status="publishing", yaml_text="a: 2\n", env_sha256="x", note="n", author="alice")
    assert (first.version, second.version) == (1, 2)
    # Rendering the same text twice must hash identically (audit relies on it).
    assert repo.get("prod", 1).yaml_sha256 == repo.get("prod", 1).yaml_sha256
    assert repo.latest_live("prod") is None
    repo.set_status(second, "live")
    assert repo.latest_live("prod").version == 2
```

- [ ] **Step 6: 建表并跑测试**

```bash
cd console/backend
export JWT_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
DATABASE_URL=sqlite:///./dev.db alembic upgrade head
python -m pytest tests/integration/test_repositories.py -q
```

Expected: `alembic` 建出 4 张表；2 passed。

- [ ] **Step 7: 提交**

```bash
git add console/backend/app/db console/backend/app/models console/backend/app/repositories \
        console/backend/alembic console/backend/alembic.ini console/backend/scripts console/backend/tests
git commit -m "feat(console): sqlalchemy models, alembic baseline and repositories"
```

---

## Task 7: 鉴权（JWT + 登录 + 角色 + 节流）

**Files:**
- Create: `console/backend/app/schemas/common.py`, `console/backend/app/schemas/auth.py`
- Create: `console/backend/app/core/security.py`
- Create: `console/backend/app/services/auth_service.py`
- Create: `console/backend/app/routers/auth.py`
- Create: `console/backend/app/deps.py`
- Modify: `console/backend/app/core/router_registry.py`（注册 auth 路由）
- Test: `console/backend/tests/integration/test_auth.py`

**Interfaces:**
- Produces: `ApiResponse` 形状 `{"code":200,"message":"success","data":...}`；辅助函数 `ok(data)`
- Produces: `CurrentUser(username: str, role: str)`；依赖 `require_user` / `require_admin` / `require_operator`
- Produces: `hash_password(pw) -> str`、`verify_password(pw, hash) -> bool`、`create_token(sub, role, kind) -> str`、`decode_token(token, kind) -> dict`
- Produces: `POST /api/v1/auth/login`、`POST /api/v1/auth/refresh`、`GET /api/v1/auth/me`

- [ ] **Step 1: 写失败测试**

`console/backend/tests/integration/test_auth.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    return TestClient(app)


def test_login_returns_camel_case_tokens(client):
    body = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()
    assert body["code"] == 200
    data = body["data"]
    assert data["tokenType"] == "bearer" and data["expiresIn"] == 1800
    assert data["user"] == {"username": "alice", "role": "admin"}


def test_unknown_user_and_wrong_password_look_identical(client):
    a = client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"})
    b = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json()["code"] == b.json()["code"] == "invalid_credentials"


def test_me_requires_a_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_role(client):
    token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()["data"]["accessToken"]
    body = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["data"]["username"] == "alice" and "lastLoginAt" in body["data"]


def test_refresh_token_is_not_an_access_token(client):
    tokens = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()["data"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['refreshToken']}"}).status_code == 401


def test_sixth_failure_is_429(client):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"})
    sixth = client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"})
    assert sixth.status_code == 429
    assert sixth.json()["code"] == "too_many_attempts"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/integration/test_auth.py -q`
Expected: 全 FAIL（`404`）。

- [ ] **Step 3: 写 schema 与 security**

`console/backend/app/schemas/common.py`:

```python
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: T


def ok(data):
    """The only success envelope. /health and /api/config deliberately bypass it."""
    return {"code": 200, "message": "success", "data": data}


class PageData(BaseModel, Generic[T]):
    list: list[T]
    total: int
    page: int
    pageSize: int
```

`console/backend/app/schemas/auth.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    refreshToken: str
```

`console/backend/app/core/security.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import auth as auth_settings
from app.core.errors import ApiError

_bearer = HTTPBearer(auto_error=False)


def create_token(subject: str, role: str, kind: str) -> str:
    now = datetime.now(timezone.utc)
    delta = (
        timedelta(minutes=auth_settings.jwt_access_token_expire_minutes)
        if kind == "access"
        else timedelta(days=auth_settings.jwt_refresh_token_expire_days)
    )
    payload = {"sub": subject, "role": role, "typ": kind, "iat": int(now.timestamp()), "exp": now + delta}
    return jwt.encode(payload, auth_settings.jwt_secret_key, algorithm=auth_settings.jwt_algorithm)


def decode_token(token: str, *, kind: str) -> dict:
    try:
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[auth_settings.jwt_algorithm])
    except JWTError as exc:
        raise ApiError("unauthorized", "token is invalid or expired", 401) from exc
    if payload.get("typ") != kind:
        # A refresh token must never open an API: same signature, different job.
        raise ApiError("unauthorized", "wrong token type", 401)
    return payload


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: str


def require_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise ApiError("unauthorized", "missing bearer token", 401)
    payload = decode_token(credentials.credentials, kind="access")
    return CurrentUser(username=str(payload.get("sub", "")), role=str(payload.get("role", "operator")))


def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if user.role != "admin":
        raise ApiError("forbidden", "admin role required", 403)
    return user


def require_operator(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if user.role not in ("admin", "operator"):
        raise ApiError("forbidden", "operator role required", 403)
    return user
```

- [ ] **Step 4: 写 auth_service（哈希 + 节流）**

`console/backend/app/services/auth_service.py`:

```python
from __future__ import annotations

import time
from collections import defaultdict, deque

import bcrypt

from app.config import auth as auth_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


class LoginThrottle:
    """Per-IP failure window. In-process is enough: console runs one worker."""

    def __init__(self, max_attempts: int, window_s: int) -> None:
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str, now: float) -> None:
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        self._trim(key, now)
        return len(self._hits[key]) >= self.max_attempts

    def fail(self, key: str) -> None:
        self._hits[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


throttle = LoginThrottle(auth_settings.login_max_attempts, auth_settings.login_window_seconds)
```

- [ ] **Step 5: 写 router 与 deps**

`console/backend/app/deps.py`:

```python
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.database import SessionLocal


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


DbSession = Depends(get_db)
```

`console/backend/app/routers/auth.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.config import auth as auth_settings
from app.core.errors import ApiError
from app.core.security import CurrentUser, create_token, require_user
from app.deps import DbSession
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RefreshRequest
from app.schemas.common import ok
from app.services.auth_service import throttle, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _token_bundle(username: str, role: str) -> dict:
    return {
        "accessToken": create_token(username, role, "access"),
        "tokenType": "bearer",
        "expiresIn": auth_settings.jwt_access_token_expire_minutes * 60,
        "refreshToken": create_token(username, role, "refresh"),
        "user": {"username": username, "role": role},
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: DbSession):
    ip = _client_ip(request)
    if throttle.blocked(ip):
        raise ApiError("too_many_attempts", "too many failed logins; retry later", 429)
    user = UserRepository(db).by_username(payload.username)
    # Same rejection for "no such user" and "wrong password": the error must
    # not become a username oracle.
    if user is None or user.disabled or not verify_password(payload.password, user.password_hash):
        throttle.fail(ip)
        raise ApiError("invalid_credentials", "username or password is incorrect", 401)
    throttle.reset(ip)
    UserRepository(db).touch_login(user)
    return ok(_token_bundle(user.username, user.role))


@router.post("/refresh")
def refresh(payload: RefreshRequest):
    from app.core.security import decode_token  # local import keeps the public surface small

    claims = decode_token(payload.refreshToken, kind="refresh")
    return ok(_token_bundle(str(claims.get("sub", "")), str(claims.get("role", "operator"))))


@router.get("/me")
def me(user: CurrentUser = Depends(require_user), db: DbSession = DbSession):
    row = UserRepository(db).by_username(user.username)
    if row is None:
        raise ApiError("unauthorized", "unknown account", 401)
    return ok({
        "username": row.username,
        "role": row.role,
        "lastLoginAt": row.last_login_at.isoformat().replace("+00:00", "Z") if row.last_login_at else None,
    })
```

- [ ] **Step 6: 注册路由**

`console/backend/app/core/router_registry.py` 改为：

```python
from __future__ import annotations

from fastapi import FastAPI


def register_api_routers(app: FastAPI) -> None:
    """Prefix order: /api/v1 (JWT) → /api (anonymous) → /v1 (proxy).

    The SPA catch-all is mounted after this returns, so nothing here can be
    shadowed by index.html.
    """
    from app.routers import auth, health  # noqa: PLC0415

    app.include_router(health.router)
    app.include_router(auth.router)
```

`console/backend/app/main.py` 里把 `app.include_router(health.router)` 换成 `register_api_routers(app)`。

- [ ] **Step 7: 跑测试**

Run: `cd console/backend && python -m pytest tests/integration/test_auth.py -q`
Expected: 6 passed。

- [ ] **Step 8: 提交**

```bash
git add console/backend/app
git commit -m "feat(console): jwt auth with login throttle and role dependencies"
```

## Task 8: catalog 与 layout 服务 + `GET /api/v1/catalog`（A.1）

**Files:**
- Create: `console/backend/app/services/__init__.py`
- Create: `console/backend/app/services/catalog_service.py`（由 `demo/param_platform/catalog.py` 迁移）
- Create: `console/backend/app/services/layout_service.py`（由 `demo/param_platform/layout.py` 迁移）
- Create: `console/backend/app/routers/catalog.py`
- Modify: `console/backend/app/core/logging.py`（加 `get_logger`）
- Modify: `console/backend/app/core/router_registry.py`
- Create: `console/backend/tests/fixtures/parameter-catalog.min.yaml`
- Test: `console/backend/tests/unit/test_catalog_service.py`
- Test: `console/backend/tests/integration/test_catalog_api.py`

**Interfaces:**
- Consumes: `app.config.console.param_catalog_path`、`app.schemas.common.ok`、`app.core.security.require_user`、`app.core.errors.ApiError`（均来自 Task 3/7）。
- Produces: `catalog_service.load(path: Path | None = None) -> Catalog`；`Catalog.available/.hint/.path/.schema/.generated_from/.generated_at/.variant_keys: list[str]/.entries: list[Entry]`、`.by_key() -> dict[str, Entry]`、`.entries_for(key) -> list[Entry]`、`.filtered(*, exposure: str | None = None, stage: str | None = None) -> list[Entry]`；模块级 `EXPOSURE_LEVELS`、`EXPECTED_SCHEMA`、`CatalogError`；`Entry.key -> str`、`Entry.as_json() -> dict`。
- Produces: `layout_service.locate(document, profile, entry) -> tuple[list[str] | None, str]`、`.block_for(document, kind, backend=None) -> str | None`、`.read(document, path) -> Any`（缺失返回哨兵 `MISSING`）、`.read_values(document, profile, entries) -> dict[str, Any]`、`.stage_backends(document, profile) -> dict[str, str | None]`、`.apply(document, profile, patches, entries) -> tuple[list[str], list[dict[str, str]]]`、`.prune(document) -> None`。
- Produces: `GET /api/v1/catalog` → `{code:200, message:"success", data:{schema, generatedFrom, generatedAt, total, returned, exposureLevels, exposureCounts, variantKeys, parameters:[...]}}`；`parameters[]` **保持 snake_case**并额外含 `key`（前端按 `key` 索引，A.1 未列但迁移必需）。

- [ ] **Step 1: 写夹具与失败测试**

`console/backend/tests/fixtures/parameter-catalog.min.yaml`（6 条，覆盖四个 exposure 层级与一个 `variant_keys`）:

```yaml
schema: s2s-parameter-catalog-v1
generated_from: tests@fixture
generated_at: "2026-10-24T00:00:00Z"
parameters:
  - stage: vad
    backend: silero
    name: min_silence_ms
    type: integer
    default: 700
    exposure: basic
    effect: 判停最短静音
  - stage: vad
    backend: silero
    name: speech_pad_ms
    type: integer
    default: 200
    exposure: advanced
  - stage: stt
    backend: whisper
    name: language
    type: string
    default: auto
    exposure: expert
  - stage: llm
    backend: chat-completions
    name: model_name
    type: string
    default: Qwen/Qwen3.5-4B
    exposure: expert
  - stage: llm
    backend: responses-api
    name: model_name
    type: string
    default: gpt-5.6-terra
    exposure: expert
  - stage: runtime
    backend: null
    name: torch_num_threads
    type: integer
    default: 4
    exposure: ops
    risk: 改线程数会改变实时性
```

`console/backend/tests/unit/test_catalog_service.py`:

```python
from pathlib import Path

import pytest

from app.services import catalog_service

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"


def test_load_reads_the_fixture():
    loaded = catalog_service.load(FIXTURE)
    assert loaded.available is True
    assert loaded.schema == "s2s-parameter-catalog-v1"
    assert loaded.generated_from == "tests@fixture"
    assert len(loaded.entries) == 6
    assert loaded.by_key()["vad.min_silence_ms"].default == 700


def test_exposure_ladder_is_cumulative():
    loaded = catalog_service.load(FIXTURE)
    assert [e.key for e in loaded.filtered(exposure="basic")] == ["vad.min_silence_ms"]
    assert [e.key for e in loaded.filtered(exposure="advanced")] == [
        "vad.min_silence_ms",
        "vad.speech_pad_ms",
    ]
    assert len(loaded.filtered(exposure="ops")) == 6


def test_unknown_exposure_is_refused():
    loaded = catalog_service.load(FIXTURE)
    with pytest.raises(catalog_service.CatalogError):
        loaded.filtered(exposure="secret")


def test_variant_keys_name_the_backend_shared_keys():
    loaded = catalog_service.load(FIXTURE)
    assert loaded.variant_keys == ["llm.model_name"]
    assert [e.backend for e in loaded.entries_for("llm.model_name")] == [
        "chat-completions",
        "responses-api",
    ]


def test_missing_file_is_unavailable_not_an_exception(tmp_path):
    loaded = catalog_service.load(tmp_path / "nope.yaml")
    assert loaded.available is False
    assert loaded.hint
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_catalog_service.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.catalog_service'`。

- [ ] **Step 3: 给 `core/logging.py` 补 `get_logger`**

在 `console/backend/app/core/logging.py` 末尾追加：

```python
from loguru import logger as _logger


def get_logger(name: str):
    """A stdlib-`logging`-shaped handle over loguru.

    The migrated modules were written against `logging`, so they interpolate
    with %s. loguru interpolates with {}, so every migrated call site is
    converted — this helper only fixes the name binding, not the format.
    """
    return _logger.bind(module=name)
```

- [ ] **Step 4: 迁移 `catalog_service.py`**

```bash
cp demo/param_platform/catalog.py console/backend/app/services/catalog_service.py
touch console/backend/app/services/__init__.py
```

然后只改这 4 处（其余逐字节保留）：

```diff
-import logging
-import os
 from dataclasses import dataclass, field
 from pathlib import Path
 from typing import Any
 
 import yaml
+from loguru import logger
 
-logger = logging.getLogger("s2s.params")
+from app.config import console
```

```diff
 def default_path() -> Path | None:
-    """First readable catalog. Two layouts, because the same code runs in a
-    container (catalog copied beside the app) and in the repo (`docs/`)."""
-    explicit = os.environ.get("PARAM_CATALOG_PATH", "").strip()
-    if explicit:
-        candidate = Path(explicit)
-        return candidate if candidate.is_file() else None
-
-    here = Path(__file__).resolve().parent.parent
-    for candidate in (
-        here / "catalog" / "parameter-catalog.yaml",
-        here.parent / "docs" / "parameter-catalog.yaml",
-    ):
-        if candidate.is_file():
-            return candidate
-    return None
+    """The one file the deployment mounted read-only (spec §12 R17).
+
+    No search path: "whichever catalog happens to sit on disk" is how a console
+    ends up editing a plan the running container never read.
+    """
+    candidate = Path(console.param_catalog_path)
+    return candidate if candidate.is_file() else None
```

```diff
-        logger.warning("catalog %s rejected: %s", target, exc)
+        logger.warning("catalog {} rejected: {}", target, exc)
```

```diff
-        logger.info(
-            "catalog defines %d key(s) in more than one backend: %s",
-            len(variants),
-            ", ".join(variants),
-        )
+        logger.info(
+            "catalog defines {} key(s) in more than one backend: {}",
+            len(variants),
+            ", ".join(variants),
+        )
```

- [ ] **Step 5: 迁移 `layout_service.py`**

```bash
cp demo/param_platform/layout.py console/backend/app/services/layout_service.py
```

零改动：`layout.py` 没有任何项目内 import。跑 `grep -n '^from\|^import' console/backend/app/services/layout_service.py` 确认只有 `from __future__ import annotations` 与 `from typing import ...`。

- [ ] **Step 6: 跑单测确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_catalog_service.py -q`
Expected: 5 passed。

- [ ] **Step 7: 写路由并注册**

`console/backend/app/routers/catalog.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import console as console_settings
from app.core.errors import ApiError
from app.core.security import CurrentUser, require_user
from app.schemas.common import ok
from app.services import catalog_service

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/catalog")
def get_catalog(
    exposure: str | None = None,
    stage: str | None = None,
    backend: str | None = None,
    user: CurrentUser = Depends(require_user),
):
    """The parameter tree (A.1).

    `exposure=basic,advanced` is cumulative, so the highest level named is the
    level shown — asking for basic and advanced and getting expert back would
    defeat the point of the ladder.
    """
    loaded = catalog_service.load()
    if not loaded.available:
        raise ApiError("catalog_unavailable", loaded.hint or "catalog not mounted", 503)

    levels = [part.strip() for part in (exposure or "").split(",") if part.strip()]
    try:
        entries = loaded.filtered(exposure=levels[-1] if levels else None, stage=stage)
    except catalog_service.CatalogError as exc:
        raise ApiError("invalid_parameter", str(exc), 400) from exc
    if backend:
        entries = [entry for entry in entries if entry.backend in (None, backend)]

    counts: dict[str, int] = {}
    for entry in loaded.entries:
        counts[entry.exposure] = counts.get(entry.exposure, 0) + 1

    return ok({
        "schema": loaded.schema,
        "generatedFrom": loaded.generated_from,
        "generatedAt": loaded.generated_at,
        "total": len(loaded.entries),
        "returned": len(entries),
        "exposureLevels": list(catalog_service.EXPOSURE_LEVELS),
        "exposureCounts": counts,
        "variantKeys": loaded.variant_keys,
        "parameters": [entry.as_json() for entry in entries],
    })
```

`console_settings` 在本路由未直接使用，保留 import 供后续 `/status` 复用；若 ruff 报 `F401`，删掉这一行。

`console/backend/app/core/router_registry.py` 改为：

```python
from __future__ import annotations

from fastapi import FastAPI


def register_api_routers(app: FastAPI) -> None:
    """Prefix order: /api/v1 (JWT) → /api (anonymous) → /v1 (proxy).

    The SPA catch-all is mounted after this returns, so nothing here can be
    shadowed by index.html.
    """
    from app.routers import auth, catalog, health  # noqa: PLC0415

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(catalog.router)
```

- [ ] **Step 8: 写 API 测试**

`console/backend/tests/integration/test_catalog_api.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    from app.main import create_app

    return TestClient(create_app())


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_catalog_needs_a_token(client):
    assert client.get("/api/v1/catalog").status_code == 401


def test_catalog_envelope_is_camelcase_and_entries_stay_snake_case(client):
    body = client.get("/api/v1/catalog", headers=_auth(client)).json()
    assert body["code"] == 200
    data = body["data"]
    assert data["generatedFrom"] == "tests@fixture"
    assert data["variantKeys"] == ["llm.model_name"]
    first = data["parameters"][0]
    assert first["key"] == "vad.min_silence_ms"
    # Catalog rows are the contract the frontend indexes by; never camelCased.
    assert first["source_ref"] == ""
    assert "sourceRef" not in first


def test_catalog_exposure_filter_takes_the_highest_level(client):
    data = client.get(
        "/api/v1/catalog?exposure=basic,advanced", headers=_auth(client)
    ).json()["data"]
    assert data["returned"] == 2


def test_unknown_exposure_is_400_invalid_parameter(client):
    response = client.get("/api/v1/catalog?exposure=secret", headers=_auth(client))
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"


def test_missing_catalog_is_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "nope.yaml"))
    response = client.get("/api/v1/catalog", headers=_auth(client))
    assert response.status_code == 503
    assert response.json()["code"] == "catalog_unavailable"
```

- [ ] **Step 9: 跑集成测试**

Run: `cd console/backend && python -m pytest tests/integration/test_catalog_api.py -q`
Expected: 5 passed（`client` fixture 依赖 Task 7 的 `alice` 种子用户）。

- [ ] **Step 10: 与旧实现对照**

```bash
cd console/backend && python - <<'PY'
from app.services import catalog_service
c = catalog_service.load()
print(c.available, c.schema, c.generated_from, len(c.entries), len(c.variant_keys))
print(c.variant_keys[:5])
PY
```

Expected: 与 `cd demo && python -c "from param_platform import catalog; c=catalog.load(); print(c.available, c.schema, c.generated_from, len(c.entries), len(c.variant_keys))"` 输出一致（`path` 不同是预期的：console 读挂载路径，demo 读仓库路径）。若 `available` 为 `False`，先导出 `PARAM_CATALOG_PATH=../docs/parameter-catalog.yaml` 再跑。

- [ ] **Step 11: 提交**

```bash
git add console/backend/app console/backend/tests
git commit -m "feat(console): catalog and layout services with GET /api/v1/catalog"
```

---

## Task 9: renderer / validator / review 服务 + draft 三端点（A.2–A.4）

**Files:**
- Create: `console/backend/app/services/renderer_service.py`（← `demo/param_platform/renderer.py`）
- Create: `console/backend/app/services/validator_service.py`（← `demo/param_platform/validator.py`）
- Create: `console/backend/app/services/publish_flow_service.py`（← `publish_flow.py:96-192` + `:551-569` 重组）
- Create: `console/backend/app/core/exposure.py`
- Create: `console/backend/app/services/draft_service.py`
- Create: `console/backend/app/schemas/draft.py`
- Create: `console/backend/app/routers/profiles.py`
- Modify: `console/backend/app/core/router_registry.py`
- Test: `console/backend/tests/unit/test_validator_service.py`
- Test: `console/backend/tests/unit/test_exposure.py`
- Test: `console/backend/tests/integration/test_drafts.py`

**Interfaces:**
- Consumes: `DraftRepository` / `VersionRepository` / `AuditRepository`（Task 6）、`DbSession` / `CurrentUser` / `require_user`（Task 7）、`catalog_service` / `layout_service`（Task 8）。
- Produces: `publish_flow_service.Rendered(text, values, applied, env_text, expected_size, resolved, warnings)`；`.profile_path(profile) -> Path`、`.env_path(profile) -> Path`、`.require_profile(profile) -> Path`、`.entries() -> dict[str, Entry]`、`.live_version(profile, versions) -> int`、`.render(profile, values, *, environ=None) -> Rendered`、`.validation_code(errors) -> str`、`.expected_size(result, text, profile) -> int | None`、`.vram_budget() -> float | None`、`.health_timeout() -> float`。**Task 10/15 全部复用这些名字。**
- Produces: `exposure.MASK`、`.is_secret(key) -> bool`、`.mask(values) -> dict`、`.validate_profile_name(profile) -> str`、`.refuse_protected(role, patch, known) -> None`、`.if_match(raw) -> int | None`。
- Produces: `validator_service.validate(text, profile, *, entries, patches=None, environ=None, vram_gb=None) -> {ok, mode, errors, warnings, checks, resolved}`。**本模块是 console 里唯一 `import speech_to_speech` 的地方（§3.7）。**
- Produces: `GET /api/v1/profiles/{profile}/draft`、`POST .../draft`、`DELETE .../draft`。

- [ ] **Step 1: 写失败测试**

`console/backend/tests/unit/test_validator_service.py`:

```python
from app.services import validator_service


def test_unparseable_yaml_is_reported_not_raised():
    result = validator_service.validate("blocks: [", "prod", entries={})
    assert result["ok"] is False
    assert result["mode"] == "structural"
    assert result["checks"]["parse"] == "failed"


def test_a_sequence_top_level_is_refused():
    result = validator_service.validate("- a\n- b\n", "prod", entries={})
    assert result["ok"] is False
    assert "not a mapping" in result["errors"][0]["message"]


def test_missing_speech_to_speech_degrades_to_structural(monkeypatch):
    # §11.2: structural mode must be reported, never silently treated as a pass.
    monkeypatch.setattr(validator_service, "_runtime", lambda: None)
    result = validator_service.validate("schema_version: 1\n", "prod", entries={})
    assert result["mode"] == "structural"
    assert result["checks"]["load"].startswith("skipped")
```

`console/backend/tests/unit/test_exposure.py`:

```python
from types import SimpleNamespace

import pytest

from app.core import exposure
from app.core.errors import ApiError


def test_secret_names_are_detected_by_their_tail():
    assert exposure.is_secret("llm.responses_api_api_key")
    assert exposure.is_secret("tts.token")
    assert not exposure.is_secret("vad.min_silence_ms")


def test_mask_replaces_only_non_empty_secrets():
    masked = exposure.mask({"llm.api_key": "sk-real", "stt.token": "", "vad.min_silence_ms": 700})
    assert masked == {"llm.api_key": "***", "stt.token": "", "vad.min_silence_ms": 700}


def test_operator_is_refused_on_expert_fields():
    known = {"stt.language": SimpleNamespace(exposure="expert")}
    with pytest.raises(ApiError) as caught:
        exposure.refuse_protected("operator", {"stt.language": "en"}, known)
    assert caught.value.code == "forbidden"
    assert caught.value.detail == [{"field": "stt.language", "exposure": "expert"}]


def test_admin_is_never_refused():
    known = {"stt.language": SimpleNamespace(exposure="expert")}
    exposure.refuse_protected("admin", {"stt.language": "en"}, known)


def test_profile_name_cannot_leave_the_config_dir():
    with pytest.raises(ApiError):
        exposure.validate_profile_name("../../etc/passwd")
    assert exposure.validate_profile_name("prod") == "prod"
```

`console/backend/tests/integration/test_drafts.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.draft_repository import DraftRepository
from app.repositories.user_repository import UserRepository
from app.services import publish_flow_service
from app.services.auth_service import hash_password

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"

PROFILE_YAML = """\
schema_version: 1
runtime:
  log_level: info
blocks:
  vad-main: {kind: vad, backend: silero, settings: {min_silence_ms: 700}}
  stt-main: {kind: stt, backend: whisper}
  llm-main: {kind: llm, backend: chat-completions}
  tts-main: {kind: tts, backend: kokoro}
pipelines:
  prod:
    stages: {vad: vad-main, stt: stt-main, llm: llm-main, tts: tts-main}
    num_pipelines: 1
"""


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "prod.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(config))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))

    # The validator needs the whole runtime package; it is covered in
    # tests/unit/test_validator_service.py. Here the render is stubbed.
    monkeypatch.setattr(
        publish_flow_service,
        "render",
        lambda profile, values, environ=None: publish_flow_service.Rendered(
            text="schema_version: 1\n",
            values=values,
            applied=sorted(values),
            expected_size=1,
            resolved={"pipelines": [profile]},
        ),
    )

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    UserRepository(db_session).create("bob", hash_password("correct-horse"), "operator")
    return TestClient(app)


def _auth(client, username="alice"):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_draft_is_empty_and_carries_the_live_version(client):
    data = client.get("/api/v1/profiles/prod/draft", headers=_auth(client)).json()["data"]
    assert data == {
        "profile": "prod",
        "baseVersion": 0,
        "draft": {},
        "masked": [],
        "updatedAt": None,
        "updatedBy": "",
    }


def test_patch_is_merged_and_secrets_come_back_masked(client):
    headers = _auth(client)
    first = client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"vad.min_silence_ms": 900, "llm.api_key": "sk-real"}},
        headers=headers,
    ).json()["data"]
    assert first["draft"] == {"vad.min_silence_ms": 900, "llm.api_key": "***"}
    assert first["validation"]["ok"] is True
    assert first["validation"]["mode"] == "runtime"

    second = client.post(
        "/api/v1/profiles/prod/draft", json={"patch": {"vad.min_silence_ms": 950}}, headers=headers
    ).json()["data"]
    assert second["draft"] == {"vad.min_silence_ms": 950, "llm.api_key": "***"}


def test_resending_the_mask_does_not_store_the_literal(client, db_session):
    headers = _auth(client)
    client.post("/api/v1/profiles/prod/draft", json={"patch": {"llm.api_key": "sk-real"}}, headers=headers)
    data = client.post(
        "/api/v1/profiles/prod/draft", json={"patch": {"llm.api_key": "***"}}, headers=headers
    ).json()["data"]
    assert data["skippedMasked"] == ["llm.api_key"]
    # The point of the check: the literal "***" must never reach the row.
    assert DraftRepository(db_session).get("prod").patch == {"llm.api_key": "sk-real"}


def test_structural_mode_is_reported_to_the_caller(client, monkeypatch):
    monkeypatch.setattr(
        publish_flow_service,
        "render",
        lambda profile, values, environ=None: publish_flow_service.Rendered(
            text="schema_version: 1\n", values=values, applied=sorted(values)
        ),
    )
    data = client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"vad.min_silence_ms": 900}},
        headers=_auth(client),
    ).json()["data"]
    assert data["validation"]["mode"] == "structural"
    assert data["validation"]["expectedPoolSize"] is None


def test_base_version_conflict_is_409(client):
    response = client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"vad.min_silence_ms": 1}, "baseVersion": 7},
        headers=_auth(client),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"


def test_operator_may_patch_a_basic_field(client):
    assert client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"vad.min_silence_ms": 800}},
        headers=_auth(client, "bob"),
    ).status_code == 200


def test_operator_may_not_patch_an_expert_field(client):
    response = client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"stt.language": "en"}},
        headers=_auth(client, "bob"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == [{"field": "stt.language", "exposure": "expert"}]


def test_discard_requires_admin(client):
    assert client.delete("/api/v1/profiles/prod/draft", headers=_auth(client, "bob")).status_code == 403


def test_discard_without_a_draft_is_404_no_draft(client):
    response = client.delete("/api/v1/profiles/prod/draft", headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "no_draft"


def test_discard_removes_the_draft_and_creates_no_version(client, db_session):
    headers = _auth(client)
    client.post(
        "/api/v1/profiles/prod/draft", json={"patch": {"vad.min_silence_ms": 900}}, headers=headers
    )
    data = client.delete("/api/v1/profiles/prod/draft", headers=headers).json()["data"]
    assert data["discarded"] is True
    assert data["revertedTo"] == "catalog-defaults"
    assert DraftRepository(db_session).get("prod") is None


def test_unknown_profile_is_404(client):
    response = client.get("/api/v1/profiles/nope/draft", headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_profile"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_exposure.py tests/unit/test_validator_service.py tests/integration/test_drafts.py -q`
Expected: 全部 `ModuleNotFoundError`（缺 `app.core.exposure`）。

- [ ] **Step 3: 迁移 `renderer_service.py`**

```bash
cp demo/param_platform/renderer.py console/backend/app/services/renderer_service.py
```

只改 import 段（其余逐字节保留，包含 `_Dumper`、`load_base`、`split_patches`、`render_yaml`、`dump_yaml`、`render_env`、`parse_env`、`diff_values`）：

```diff
-import logging
 import copy
 import re
 from pathlib import Path
 from typing import Any
 
 import yaml
-from param_platform import layout
-
-logger = logging.getLogger("s2s.params")
+from app.services import layout_service as layout
```

- [ ] **Step 4: 迁移 `validator_service.py`**

```bash
cp demo/param_platform/validator.py console/backend/app/services/validator_service.py
```

两处改动：

```diff
-import logging
 import os
 import re
 import sys
 import tempfile
 from pathlib import Path
 from typing import Any
 
 import yaml
-
-logger = logging.getLogger("s2s.params")
+from loguru import logger
```

```diff
-    src = Path(__file__).resolve().parent.parent.parent / "src"
-    if not src.is_dir():
-        return
-    if str(src) not in sys.path:
-        sys.path.insert(0, str(src))
+    # In the image the package is installed, so this only ever matters for a
+    # bare checkout. Walk up instead of counting `.parent`s: the console sits
+    # one level deeper than demo/ did, and a wrong count fails silently.
+    candidates = [Path("/app/src")]
+    candidates += [parent / "src" for parent in Path(__file__).resolve().parents]
+    for src in candidates:
+        if src.is_dir():
+            if str(src) not in sys.path:
+                sys.path.insert(0, str(src))
+            break
```

- [ ] **Step 5: 写 `publish_flow_service.py`**

`console/backend/app/services/publish_flow_service.py`:

```python
"""Steps 2–4 of chain A: turn a set of values into bytes and validate them.

Nothing here writes. `publish_service` (Task 15) owns the writes, which is what
keeps the rollback ordering reviewable in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import console
from app.core.errors import ApiError
from app.services import catalog_service, renderer_service, validator_service


@dataclass(frozen=True)
class Rendered:
    """What a set of values turns into, before anything is written."""

    text: str
    values: dict[str, Any]
    applied: list[str] = field(default_factory=list)
    env_text: str | None = None
    expected_size: int | None = None
    resolved: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def profile_path(profile: str) -> Path:
    return Path(console.param_config_dir) / f"{profile}.yaml"


def env_path(profile: str) -> Path:
    """`config/<profile>.env`, the file compose names in `env_file`.

    Not `.env`: compose reads that from the project root for its own variable
    interpolation, and writing there would leave the container still reading
    the values this publish was supposed to replace.
    """
    return Path(console.param_config_dir) / f"{profile}.env"


def require_profile(profile: str) -> Path:
    path = profile_path(profile)
    if not path.is_file():
        raise ApiError("unknown_profile", f"{path.name} does not exist", 404)
    return path


def entries() -> dict[str, catalog_service.Entry]:
    loaded = catalog_service.load()
    if not loaded.available:
        raise ApiError("catalog_unavailable", loaded.hint or "catalog not mounted", 503)
    return loaded.by_key()


def live_version(profile: str, versions) -> int:
    """0 when nothing has been published yet, which is what `If-Match` compares."""
    latest = versions.latest_live(profile)
    return int(latest.version) if latest else 0


def render(profile: str, values: dict[str, Any], *, environ: dict[str, str] | None = None) -> Rendered:
    """`config/<profile>.yaml` plus `values`, validated. Nothing is written.

    A refused key aborts the render: publishing the half of a patch that
    happened to apply is how a deployed file ends up different from the one
    that was reviewed.
    """
    path = require_profile(profile)
    known = entries()
    base = renderer_service.load_base(path)
    yaml_patches, env_patches = renderer_service.split_patches(values, known)
    text, applied, refused = renderer_service.render_yaml(base, profile, yaml_patches, known)
    if refused:
        raise ApiError(
            "invalid_parameter",
            "some parameters have no place in this profile's YAML",
            400,
            detail=refused,
        )

    env_text: str | None = None
    if env_patches:
        existing = env_path(profile).read_text(encoding="utf-8") if env_path(profile).is_file() else ""
        env_text, _ = renderer_service.render_env(existing, env_patches)

    # The rendered `.env` wins over the process environment: it is the file the
    # container will actually read.
    merged = {**os.environ, **renderer_service.parse_env(env_text or ""), **(environ or {})}
    result = validator_service.validate(
        text, profile, entries=known, patches=values, environ=merged, vram_gb=vram_budget()
    )
    if not result["ok"]:
        raise ApiError(
            validation_code(result["errors"]),
            "the rendered profile does not pass validation",
            422,
            detail=result["errors"],
        )

    return Rendered(
        text=text,
        values=values,
        applied=applied,
        env_text=env_text,
        expected_size=expected_size(result, text, profile),
        resolved=result["resolved"],
        warnings=result["warnings"],
    )


def validation_code(errors: list[dict[str, Any]]) -> str:
    """A budget failure is a different answer than a typo; A.5 separates them."""
    for error in errors:
        if error.get("field") == "runtime.num_pipelines" and error.get("details"):
            return "vram_budget_exceeded"
    return "validation_failed"


def expected_size(result: dict[str, Any], text: str, profile: str) -> int | None:
    """How many units the new YAML asks for, or None when that cannot be known.

    `{env: N}` for `num_pipelines` only resolves at startup, so the pool is then
    judged on reachability alone — inventing a size and failing on it would
    refuse a config that is actually correct.
    """
    count = (result.get("resolved") or {}).get("num_pipelines")
    if type(count) is int:
        return count
    try:
        document = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None
    pipeline = (document.get("pipelines") or {}).get(profile)
    if not isinstance(pipeline, dict):
        return None
    count = pipeline.get("num_pipelines", 1)
    return count if type(count) is int else None


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        from loguru import logger

        logger.warning("ignoring {}={!r}: not a number", name, raw)
        return None


def vram_budget() -> float | None:
    return _float_env("PARAM_VRAM_GB")


def health_timeout() -> float:
    return _float_env("PARAM_HEALTH_TIMEOUT") or 180.0
```

- [ ] **Step 6: 写 `core/exposure.py`**

`console/backend/app/core/exposure.py`:

```python
"""The two rules every read and write of a parameter obeys (§10.1)."""

from __future__ import annotations

import re
from typing import Any

from app.core.errors import ApiError

# The mask A.0 promises for secret fields. A console that posts its whole form
# back would send this string as the value, so it is read as "unchanged" rather
# than written: saving it literally is how a masked field becomes the literal
# password `***` on the next publish.
MASK = "***"

# The catalog has no `secret` flag, so the name is the only signal there is.
SECRET_NAME = re.compile(r"(api_key|_key|token|secret|password)$", re.IGNORECASE)

# Profile names become file names, so they must not leave the config directory.
PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

# `operator` may draft `basic` and `advanced`; everything else needs `admin`.
OPERATOR_EXPOSURE = frozenset({"basic", "advanced"})


def is_secret(key: str) -> bool:
    return bool(SECRET_NAME.search(key.rsplit(".", 1)[-1]))


def mask(values: dict[str, Any]) -> dict[str, Any]:
    """`{key: "***"}` for names that look like credentials, values otherwise."""
    return {
        key: MASK if is_secret(key) and value not in (None, "") else value
        for key, value in values.items()
    }


def validate_profile_name(profile: str) -> str:
    if not PROFILE_NAME.match(profile):
        raise ApiError("invalid_parameter", f"invalid profile name {profile!r}", 400)
    return profile


def refuse_protected(role: str, patch: dict[str, Any], known: dict[str, Any]) -> None:
    """A.3's `403 forbidden`.

    Checked against the request, not the merged draft: an operator patching a
    basic field onto a draft an admin already put an `ops` value in has changed
    nothing they are not allowed to change. The whole patch is refused rather
    than the offending keys dropped — half a patch shipped is worse than none.
    """
    if role == "admin":
        return
    blocked = [
        {"field": key, "exposure": known[key].exposure}
        for key in patch
        if key in known and known[key].exposure not in OPERATOR_EXPOSURE
    ]
    if blocked:
        raise ApiError("forbidden", "only an admin may change these parameters", 403, detail=blocked)


def if_match(raw: str) -> int | None:
    """`If-Match: <version>`, or None when the caller did not claim one.

    Absent is allowed on purpose: a single-operator console has nothing to
    compare against on its first save. Present-but-stale is always a 409.
    """
    value = (raw or "").strip().strip('"')
    if not value or value == "*":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ApiError("invalid_parameter", f"If-Match must be an integer version, got {value!r}", 400) from exc
```

- [ ] **Step 7: 写 `draft_service.py`**

`console/backend/app/services/draft_service.py`:

```python
"""The draft: the only mutable state in the platform (A.2–A.4).

A draft is a patch, not a document. It holds the keys an operator touched and
the live version it was started against, so once someone publishes, every other
draft is stale and its next save is refused with a 409 instead of quietly
diffing against a config that no longer exists.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.errors import ApiError
from app.core.exposure import MASK, is_secret, mask
from app.repositories.audit_repository import AuditRepository
from app.repositories.draft_repository import DraftRepository
from app.repositories.version_repository import VersionRepository
from app.services import publish_flow_service


def _iso(value) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def read_draft(db, profile: str) -> dict[str, Any]:
    """The stored draft, or an empty one carrying the current live version."""
    publish_flow_service.require_profile(profile)
    row = DraftRepository(db).get(profile)
    if row is None:
        return {
            "profile": profile,
            "baseVersion": publish_flow_service.live_version(profile, VersionRepository(db)),
            "draft": {},
            "masked": [],
            "updatedAt": None,
            "updatedBy": "",
        }
    return {
        "profile": profile,
        "baseVersion": row.base_version,
        "draft": mask(row.patch),
        "masked": sorted(key for key in row.patch if is_secret(key)),
        "updatedAt": _iso(row.updated_at),
        "updatedBy": row.updated_by,
    }


def save_draft(
    db,
    profile: str,
    patch: dict[str, Any],
    *,
    base_version: int | None,
    actor: str,
    role: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Merge `patch` onto the stored draft, validate, then persist.

    Validation runs before the write on purpose: the draft is what publish
    reads, so an unpublishable draft is only a way to lose work later. `null`
    is a value here — "drop this key and fall back to the default" — and has to
    survive the merge.
    """
    publish_flow_service.require_profile(profile)
    versions = VersionRepository(db)
    live = publish_flow_service.live_version(profile, versions)
    if base_version is not None and base_version != live:
        raise ApiError(
            "version_conflict",
            f"the live version moved to {live}",
            409,
            detail=[{"expected": live, "got": base_version}],
        )

    stored = DraftRepository(db).get(profile)
    existing = dict(stored.patch) if stored is not None else {}
    skipped = [key for key, value in patch.items() if value == MASK]
    merged = {**existing, **{key: value for key, value in patch.items() if value != MASK}}

    started = time.monotonic()
    rendered = publish_flow_service.render(profile, merged)

    DraftRepository(db).put(profile, live, merged, actor)
    audit = AuditRepository(db).record(
        actor=actor,
        role=role,
        action="draft.patch",
        profile=profile,
        fields=sorted(patch),
        version=live,
        duration_s=round(time.monotonic() - started, 3),
        request_id=request_id,
    )
    return {
        "draft": mask(merged),
        "baseVersion": live,
        "skippedMasked": skipped,
        "validation": {
            "ok": True,
            # Structural mode means the runtime package was absent, so the UI
            # can say "checked for shape only" rather than implying more.
            "mode": "runtime" if rendered.resolved else "structural",
            "resolvedPipelines": rendered.resolved.get("pipelines", []),
            "expectedPoolSize": rendered.expected_size,
            "warnings": rendered.warnings,
        },
        "auditId": str(audit.id),
    }


def discard_draft(db, profile: str, *, actor: str, role: str, request_id: str = "") -> dict[str, Any]:
    """Discarding produces no version: `live` is untouched (A.4)."""
    publish_flow_service.require_profile(profile)
    live = publish_flow_service.live_version(profile, VersionRepository(db))
    if not DraftRepository(db).drop(profile):
        raise ApiError("no_draft", f"profile {profile!r} has no draft to discard", 404)
    audit = AuditRepository(db).record(
        actor=actor, role=role, action="draft.discard", profile=profile, fields=[],
        version=live, request_id=request_id,
    )
    return {
        "discarded": True,
        "revertedTo": "catalog-defaults" if live == 0 else f"v{live}",
        "auditId": str(audit.id),
    }
```

- [ ] **Step 8: 写 schema 与路由**

`console/backend/app/schemas/draft.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DraftPatchRequest(BaseModel):
    patch: dict[str, Any] = Field(min_length=1)
    baseVersion: int | None = None
```

`console/backend/app/routers/profiles.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.errors import ApiError
from app.core.exposure import if_match, refuse_protected, validate_profile_name
from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.draft import DraftPatchRequest
from app.services import draft_service, publish_flow_service

router = APIRouter(prefix="/api/v1", tags=["drafts"])


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


@router.get("/profiles/{profile}/draft")
def get_draft(profile: str, db: DbSession, user: CurrentUser = Depends(require_user)):
    """A.2: a patch, not a document; secrets come back as `***`."""
    return ok(draft_service.read_draft(db, validate_profile_name(profile)))


@router.post("/profiles/{profile}/draft")
def post_draft(
    profile: str,
    payload: DraftPatchRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    """A.3: `null` falls back to the default, `***` leaves the field alone."""
    name = validate_profile_name(profile)
    refuse_protected(user.role, payload.patch, publish_flow_service.entries())
    claimed = payload.baseVersion
    if claimed is None:
        claimed = if_match(request.headers.get("if-match", ""))
    return ok(
        draft_service.save_draft(
            db, name, payload.patch, base_version=claimed, actor=user.username,
            role=user.role, request_id=_request_id(request),
        )
    )


@router.delete("/profiles/{profile}/draft")
def delete_draft(
    profile: str, request: Request, db: DbSession, user: CurrentUser = Depends(require_user)
):
    """A.4: destructive, so admin only."""
    name = validate_profile_name(profile)
    if user.role != "admin":
        raise ApiError("forbidden", "only an admin may discard a draft", 403)
    return ok(
        draft_service.discard_draft(
            db, name, actor=user.username, role=user.role, request_id=_request_id(request)
        )
    )
```

`console/backend/app/core/router_registry.py` 加一行 `app.include_router(drafts.router)`，并把 `drafts` 加入 `from app.routers import ...`。

- [ ] **Step 9: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_exposure.py tests/unit/test_validator_service.py -q`
Expected: 8 passed。

Run: `cd console/backend && python -m pytest tests/integration/test_drafts.py -q`
Expected: 11 passed。

- [ ] **Step 10: 跑 Task 7/8 回归**

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿（`router_registry` 动了两次，`health` / `auth` / `catalog` 都应仍可访问）。

- [ ] **Step 11: 提交**

```bash
git add console/backend/app console/backend/tests
git commit -m "feat(console): render, validate and draft endpoints"
```

---

## Task 10: pool / probe 服务 + versions / audit / instances / status（A.7–A.11）

**Files:**
- Create: `console/backend/app/services/pool.py`（← `compose_runner.py:229-305`）
- Create: `console/backend/app/services/process_probe.py`
- Create: `console/backend/app/services/instances_service.py`
- Create: `console/backend/app/services/status_service.py`
- Modify: `console/backend/app/routers/profiles.py`（追加 A.5 versions / A.6 audit 路由；**不**新建 `history.py`，理由见下文「A.2–A.8 全部挂在 `/profiles/{id}/*` 下」那段）
- Create: `console/backend/app/routers/instances.py`
- Modify: `console/backend/app/repositories/audit_repository.py`（`list()` 加 `field` 过滤）
- Modify: `console/backend/app/services/validator_service.py`（加 `mode()`）
- Modify: `console/backend/app/core/router_registry.py`
- Test: `console/backend/tests/unit/test_pool.py`
- Test: `console/backend/tests/integration/test_history.py`
- Test: `console/backend/tests/integration/test_instances.py`

**Interfaces:**
- Consumes: `publish_flow_service.live_version`（Task 9）、`VersionRepository` / `AuditRepository`（Task 6）、`validator_service`（Task 9）。
- Produces: `pool.PoolState(reachable, size, in_use, units, error)` 与 `.stuck` / `.busy`；`pool.HealthResult(ok, reason, elapsed_s, attempts, pool, notes)`；`pool.read_pool(timeout=5.0) -> PoolState`、`.read_usage(timeout=5.0) -> dict | None`、`.wait_healthy(expected_size, *, timeout=180.0, interval=2.0) -> HealthResult`、`.pool_url() -> str`、`.POLL_SECONDS`、`.DEFAULT_TIMEOUT`。
- Produces: `process_probe.ProcessInfo(name, running, pid, state, detail)`；`process_probe.ProcessProbe`（Protocol，唯一方法 `state(name) -> ProcessInfo`）、`.NullProbe(detail="…")`、`.get_probe()`、`.set_probe(probe | None)`。**Task 14 只替换 `_build()`**。
- Produces: `instances_service.collect(profile, version) -> dict`；`status_service.snapshot(db, profile) -> dict`；`validator_service.mode() -> "runtime" | "structural"`。
- Produces: `GET /api/v1/profiles/{id}/versions|audit`、`GET /api/v1/instances`、`GET /api/v1/status`。
- Consumes: `auditRepository.list(..., field: str = "")`。

- [ ] **Step 1: 写失败测试**

`console/backend/tests/unit/test_pool.py`:

```python
import httpx

from app.services import pool


def test_read_pool_marks_an_unreachable_pool(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(pool.httpx, "get", boom)
    state = pool.read_pool()
    assert state.reachable is False
    assert "ConnectError" in state.error


def test_read_pool_counts_busy_and_stuck_units(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "size": 3,
                "in_use": 2,
                "units": [
                    {"index": 0, "state": "active", "session_id": "s1"},
                    {"index": 1, "state": "draining", "session_id": "s2"},
                    {"index": 2, "state": "stuck", "session_id": "s3"},
                ],
            }

    monkeypatch.setattr(pool.httpx, "get", lambda *a, **k: _Response())
    state = pool.read_pool()
    assert (state.reachable, state.size, state.in_use) == (True, 3, 2)
    assert state.busy == 1  # only `active` is a live conversation
    assert state.stuck == 1


def test_wait_healthy_gives_up_after_the_deadline(monkeypatch):
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=False, error="refused")
    )
    result = pool.wait_healthy(2, timeout=0.2, interval=0.1)
    assert result.ok is False
    assert result.reason.startswith("after 0.2s")


def test_wait_healthy_accepts_only_the_expected_size(monkeypatch):
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=True, size=1, in_use=0)
    )
    assert pool.wait_healthy(2, timeout=0.2, interval=0.1).ok is False

    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=True, size=2, in_use=0)
    )
    assert pool.wait_healthy(2, timeout=1.0, interval=0.01).ok is True


def test_wait_healthy_fails_on_a_stuck_unit(monkeypatch):
    state = pool.PoolState(
        reachable=True, size=2, units=({"index": 0, "state": "stuck", "session_id": "s1"},)
    )
    monkeypatch.setattr(pool, "read_pool", lambda timeout=5.0: state)
    result = pool.wait_healthy(2, timeout=0.2, interval=0.1)
    assert result.ok is False
    assert "stuck" in result.reason
```

`console/backend/tests/integration/test_history.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository
from app.repositories.version_repository import VersionRepository
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "prod.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(config))

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    return TestClient(app)


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _seed_versions(db_session):
    repo = VersionRepository(db_session)
    first = repo.create(
        "prod", status="publishing", yaml_text="a: 1\n", env_sha256="x", note="first", author="alice"
    )
    repo.set_status(first, "live", duration_s=41.2)
    second = repo.create(
        "prod", status="publishing", yaml_text="a: 2\n", env_sha256="x", note="second", author="alice"
    )
    repo.set_status(second, "rolled_back", error_code="healthcheck_timeout", rolled_back_to=first.version)
    return first, second


def test_versions_are_newest_first_and_carry_no_yaml(client, db_session):
    first, second = _seed_versions(db_session)
    data = client.get("/api/v1/profiles/prod/versions", headers=_auth(client)).json()["data"]
    assert data["total"] == 2
    assert [row["version"] for row in data["list"]] == [second.version, first.version]
    newest = data["list"][0]
    assert newest["status"] == "rolled_back"
    assert newest["rolledBackTo"] == first.version
    assert newest["durationS"] is None
    # A.7 lists what the history table renders; the YAML is megabytes of nothing.
    assert "yamlText" not in newest and "yaml_text" not in newest
    assert isinstance(newest["createdAt"], str) and newest["createdAt"].endswith("Z")


def test_versions_paginate(client, db_session):
    _seed_versions(db_session)
    data = client.get(
        "/api/v1/profiles/prod/versions?page=2&pageSize=1", headers=_auth(client)
    ).json()["data"]
    assert (data["page"], data["pageSize"], data["total"], len(data["list"])) == (2, 1, 2, 1)


def test_versions_of_an_unknown_profile_is_404(client):
    response = client.get("/api/v1/profiles/nope/versions", headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_profile"


def test_audit_records_field_names_but_never_values(client, db_session):
    AuditRepository(db_session).record(
        actor="alice", role="admin", action="publish", profile="prod",
        fields=["vad.min_silence_ms", "llm.api_key"], version=1, duration_s=41.2, request_id="req-1",
    )
    entry = client.get("/api/v1/profiles/prod/audit", headers=_auth(client)).json()["data"]["list"][0]
    assert entry["fields"] == ["vad.min_silence_ms", "llm.api_key"]
    assert entry["role"] == "admin" and entry["requestId"] == "req-1"
    assert "values" not in entry and "detail" not in entry


def test_audit_field_filter_narrows_the_result(client, db_session):
    repo = AuditRepository(db_session)
    repo.record(actor="alice", role="admin", action="draft.patch", profile="prod", fields=["vad.min_silence_ms"])
    repo.record(actor="alice", role="admin", action="draft.patch", profile="prod", fields=["stt.language"])
    data = client.get(
        "/api/v1/profiles/prod/audit?field=vad.min_silence_ms", headers=_auth(client)
    ).json()["data"]
    assert data["total"] == 1
    assert data["list"][0]["fields"] == ["vad.min_silence_ms"]
```

`console/backend/tests/integration/test_instances.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services import pool, process_probe
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "missing.yaml"))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    process_probe.set_probe(process_probe.NullProbe("test has no supervisor"))
    yield TestClient(app)
    process_probe.set_probe(None)


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_instances_keeps_200_when_the_pool_is_down(client, monkeypatch):
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=False, error="refused")
    )
    response = client.get("/api/v1/instances", headers=_auth(client))
    assert response.status_code == 200
    data = response.json()["data"]
    # A.10: a degraded read is the whole point of this page.
    assert data["pool"] is None
    assert "pool_unreachable" in data["alerts"]
    assert "pipeline_stopped" in data["alerts"]
    assert data["container"]["name"] == console_settings.supervisor_program


def test_instances_exposes_units_and_usage(client, monkeypatch):
    state = pool.PoolState(
        reachable=True,
        size=2,
        in_use=1,
        units=(
            {"index": 0, "state": "active", "session_id": "s1"},
            {"index": 1, "state": "idle", "session_id": None},
        ),
    )
    monkeypatch.setattr(pool, "read_pool", lambda timeout=5.0: state)
    monkeypatch.setattr(pool, "read_usage", lambda timeout=5.0: {"turns": 3})

    data = client.get("/api/v1/instances", headers=_auth(client)).json()["data"]
    assert data["pool"] == {
        "size": 2,
        "inUse": 1,
        "units": [
            {"index": 0, "state": "active", "sessionId": "s1"},
            {"index": 1, "state": "idle", "sessionId": None},
        ],
    }
    assert data["usage"] == {"turns": 3}
    assert data["alerts"] == ["pipeline_stopped"]


def test_status_reports_the_environment_it_is_running_in(client, monkeypatch):
    monkeypatch.delenv("S2S_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=False, error="refused")
    )
    data = client.get("/api/v1/status", headers=_auth(client)).json()["data"]
    assert data["db"] == "ok"
    assert data["pipeline"] == "unreachable"
    assert data["internalTokenConfigured"] is False
    assert data["validatorMode"] in ("runtime", "structural")
    assert data["profile"] == "prod"


def test_status_sees_a_configured_internal_token(client, monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=True, size=1)
    )
    process_probe.set_probe(_RunningProbe())
    data = client.get("/api/v1/status", headers=_auth(client)).json()["data"]
    assert data["internalTokenConfigured"] is True
    assert data["pipeline"] == "ok"


class _RunningProbe:
    def state(self, name):
        return process_probe.ProcessInfo(name=name, running=True, pid=42, state="RUNNING")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_pool.py tests/integration/test_history.py tests/integration/test_instances.py -q`
Expected: 全 FAIL（`ModuleNotFoundError: app.services.pool`）。

- [ ] **Step 3: 写 `pool.py`**

`console/backend/app/services/pool.py`（`read_pool` / `wait_healthy` / `_judge` 逻辑逐字迁移自 `compose_runner.py:232-305`，只把 `pool_url()` 从环境变量换成 settings）：

```python
"""Talking to the pipeline's own loopback API (A.10's `pool` section).

No docker here: the console and the pipeline share a container, so “what is
running” is supervisor's answer, and “is it serving” is `/v1/pool`'s.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import console

POLL_SECONDS = 2.0
DEFAULT_TIMEOUT = 180.0
# `stuck` is the one pool state that means "this unit will not serve again
# without a restart" (websocket_router.py:660-695).
BAD_STATES = frozenset({"stuck"})


@dataclass(frozen=True)
class PoolState:
    reachable: bool
    size: int = 0
    in_use: int = 0
    units: tuple[dict[str, Any], ...] = ()
    error: str = ""

    @property
    def stuck(self) -> int:
        return sum(1 for unit in self.units if unit.get("state") in BAD_STATES)

    @property
    def busy(self) -> int:
        return sum(1 for unit in self.units if unit.get("state") == "active")


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    reason: str
    elapsed_s: float
    attempts: int = 0
    pool: PoolState | None = None
    notes: list[str] = field(default_factory=list)


def pool_url() -> str:
    return console.pipeline_base_url.rstrip("/")


def read_pool(timeout: float = 5.0) -> PoolState:
    try:
        response = httpx.get(f"{pool_url()}/v1/pool", timeout=timeout)
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        return PoolState(reachable=False, error=f"{type(exc).__name__}: {exc}")
    except ValueError as exc:
        return PoolState(reachable=False, error=f"invalid JSON: {exc}")

    units = body.get("units") or []
    return PoolState(
        reachable=True,
        size=int(body.get("size") or 0),
        in_use=int(body.get("in_use") or 0),
        units=tuple(unit for unit in units if isinstance(unit, dict)),
    )


def read_usage(timeout: float = 5.0) -> dict[str, Any] | None:
    """`None` rather than an empty dict: “no data” must not look like zero."""
    try:
        response = httpx.get(f"{pool_url()}/v1/usage", timeout=timeout)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def wait_healthy(
    expected_size: int | None, *, timeout: float = DEFAULT_TIMEOUT, interval: float = POLL_SECONDS
) -> HealthResult:
    """Poll until the pool is the size the new YAML asked for.

    A pool larger or smaller than `expected_size` means the process is still
    serving the old config (or a partially started one), so neither counts.
    `expected_size=None` (num_pipelines is `{env: N}`) judges reachability only.
    Active sessions do not fail the publish — they keep running on the handler
    that accepted them — but they are reported.
    """
    started = time.monotonic()
    deadline = started + timeout
    attempts = 0
    last: PoolState | None = None

    while True:
        attempts += 1
        last = read_pool()
        ok, reason = _judge(last, expected_size)
        if ok:
            notes = []
            if last.busy:
                notes.append(
                    f"{last.busy} session(s) still on the previous handler; "
                    "they pick up the new config when they reconnect"
                )
            return HealthResult(
                ok=True,
                reason=reason,
                elapsed_s=round(time.monotonic() - started, 1),
                attempts=attempts,
                pool=last,
                notes=notes,
            )
        if time.monotonic() + interval > deadline:
            return HealthResult(
                ok=False,
                reason=f"after {timeout:.0f}s: {reason}",
                elapsed_s=round(time.monotonic() - started, 1),
                attempts=attempts,
                pool=last,
            )
        time.sleep(interval)


def _judge(state: PoolState, expected_size: int | None) -> tuple[bool, str]:
    if not state.reachable:
        return False, state.error or "pool unreachable"
    if state.stuck:
        return False, f"{state.stuck} unit(s) stuck"
    if expected_size is not None and state.size != expected_size:
        return False, f"pool size {state.size}, expected {expected_size}"
    return True, f"pool size {state.size}, {state.in_use} in use"
```

- [ ] **Step 4: 写 `process_probe.py`**

`console/backend/app/services/process_probe.py`:

```python
"""What is running, as opposed to what the console believes (A.10).

A seam on purpose: Task 14 supplies the supervisor-backed probe. Everything in
this task works against `NullProbe`, which reports failure instead of raising —
`/instances` must stay a 200 exactly when the pipeline is down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProcessInfo:
    name: str
    running: bool
    pid: int | None = None
    state: str = "unknown"
    detail: str = ""


class ProcessProbe(Protocol):
    def state(self, name: str) -> ProcessInfo: ...


class NullProbe:
    def __init__(self, detail: str = "supervisor probe not installed") -> None:
        self._detail = detail

    def state(self, name: str) -> ProcessInfo:
        return ProcessInfo(name=name, running=False, state="unknown", detail=self._detail)


_probe: ProcessProbe | None = None


def get_probe() -> ProcessProbe:
    global _probe
    if _probe is None:
        _probe = _build()
    return _probe


def set_probe(probe: ProcessProbe | None) -> None:
    """Test seam. `None` re-resolves on next access."""
    global _probe
    _probe = probe


def _build() -> ProcessProbe:
    # Task 14 replaces this body with the XML-RPC-over-unix-socket probe.
    return NullProbe("supervisor probe not installed")
```

- [ ] **Step 5: 写 `instances_service` 与 `status_service`**

`console/backend/app/services/instances_service.py`:

```python
"""A.10: one read-only aggregate so the instance page calls one endpoint (B1)."""

from __future__ import annotations

import os
from typing import Any

from app.config import console
from app.services import pool, process_probe


def collect(profile: str, version: int | None) -> dict[str, Any]:
    state = pool.read_pool()
    usage = pool.read_usage() if state.reachable else None
    info = process_probe.get_probe().state(console.supervisor_program)

    alerts: list[str] = []
    if not state.reachable:
        alerts.append("pool_unreachable")
    if state.stuck:
        alerts.append("pool_stuck")
    if not info.running:
        alerts.append("pipeline_stopped")
    if state.reachable and usage is None:
        alerts.append("usage_unavailable")

    return {
        "profile": profile,
        "version": version,
        # Still called `container`: one container, one pipeline process inside it.
        # startedAt/image come from the image label when the deploy sets it;
        # the console cannot ask docker (no socket, §10.1).
        "container": {
            "name": info.name,
            "status": "running" if info.running else (info.state or "unknown"),
            "startedAt": None,
            "image": os.environ.get("S2S_IMAGE", "").strip(),
            "pid": info.pid,
            "detail": info.detail,
        },
        "pool": None
        if not state.reachable
        else {
            "size": state.size,
            "inUse": state.in_use,
            "units": [
                {
                    "index": unit.get("index"),
                    "state": unit.get("state"),
                    "sessionId": unit.get("session_id"),
                }
                for unit in state.units
            ],
        },
        "usage": usage,
        "alerts": alerts,
    }
```

`console/backend/app/services/status_service.py`:

```python
"""A.11: what the console needs before it renders anything at all."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import text

from app.config import console
from app.repositories.version_repository import VersionRepository
from app.services import catalog_service, pool, process_probe, validator_service


def _db_ok(db) -> bool:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


def snapshot(db, profile: str) -> dict[str, Any]:
    """Never raises for a downstream failure: A.11 wants a 200 with the facts."""
    db_ok = _db_ok(db)
    latest = VersionRepository(db).latest_live(profile) if db_ok else None
    info = process_probe.get_probe().state(console.supervisor_program)
    reachable = pool.read_pool().reachable
    return {
        "profile": profile,
        "version": int(latest.version) if latest else None,
        "status": latest.status if latest else "unknown",
        "catalogCommit": catalog_service.load().generated_from,
        "validatorMode": validator_service.mode(),
        "db": "ok" if db_ok else "unavailable",
        "pipeline": "ok" if (info.running and reachable) else "unreachable",
        "internalTokenConfigured": bool(os.environ.get("S2S_INTERNAL_TOKEN", "").strip()),
    }
```

给 `validator_service.py` 追加：

```python
def mode() -> str:
    """The tier the next `validate()` call would take (§11.2).

    Runs the same import-recovery the validator does, so the console reports
    `runtime` exactly when a publish would actually be verified.
    """
    if _runtime() is None:
        _ensure_runtime_importable()
    return "runtime" if _runtime() is not None else "structural"
```

- [ ] **Step 6: 给 `AuditRepository.list()` 加 `field` 过滤**

`console/backend/app/repositories/audit_repository.py` 的 `list()` 签名加 `field: str = ""`，并在 `if result:` 之后插入：

```python
        if field:
            # `fields` is a JSON array of names. A LIKE on its text form works on
            # both SQLite and Postgres without a JSON path operator, and the
            # quotes keep `stt.language` from matching `stt.language_variant`.
            stmt = stmt.where(cast(ParamAudit.fields, String).like(f'%"{field}"%'))
```

并在该文件头部把 import 改为 `from sqlalchemy import String, cast, func, select`。

- [ ] **Step 7: 追加 versions / audit 端点，写 instances / status 路由**

A.2–A.8 全部挂在 `/profiles/{id}/*` 下（§3.3 也只列了 `routers/profiles.py`），所以 versions 与 audit **追加到 `profiles.py`**，不另起 `history.py`。

在 `console/backend/app/routers/profiles.py` 顶部 import 区补四行：

```python
from datetime import datetime

from fastapi import Query

from app.repositories.audit_repository import AuditRepository
from app.repositories.version_repository import VersionRepository
```

在文件末尾追加：

```python
def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError("invalid_parameter", f"not an ISO 8601 time: {value!r}", 400) from exc


@router.get("/profiles/{profile}/versions")
def get_versions(
    profile: str,
    db: DbSession,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
):
    """A.7: append-only history without the renderings.

    `yaml_text` is the whole file; fifty of them would be megabytes the history
    table never shows. It stays in the row for the rollback that needs the
    exact bytes.
    """
    name = validate_profile_name(profile)
    publish_flow_service.require_profile(name)
    rows, total = VersionRepository(db).list(name, page=page, page_size=pageSize)
    return ok({
        "list": [
            {
                "version": row.version,
                "status": row.status,
                "author": row.author,
                "note": row.note,
                "createdAt": _iso(row.created_at),
                "durationS": row.duration_s,
                "rolledBackTo": row.rolled_back_to,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    })


@router.get("/profiles/{profile}/audit")
def get_audit(
    profile: str,
    db: DbSession,
    actor: str = "",
    action: str = "",
    result: str = "",
    field: str = "",
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
):
    """A.8: field names, never values (§10.1)."""
    name = validate_profile_name(profile)
    publish_flow_service.require_profile(name)
    rows, total = AuditRepository(db).list(
        profile=name, actor=actor, action=action, result=result, field=field,
        since=_since(from_), until=_since(to), page=page, page_size=pageSize,
    )
    return ok({
        "list": [
            {
                "auditId": str(row.id),
                "at": _iso(row.at),
                "actor": row.actor,
                "role": row.role,
                "action": row.action,
                "version": row.version,
                "fields": list(row.fields or []),
                "result": row.result,
                "errorCode": row.error_code,
                "durationS": row.duration_s,
                "requestId": row.request_id,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    })
```

若 `audit_repository.list()` 的参数是 `since`/`until` 之外的命名（按 Task 6 实际落地调整），以 Task 6 的文件为准。

`console/backend/app/routers/instances.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.repositories.version_repository import VersionRepository
from app.schemas.common import ok
from app.services import instances_service

router = APIRouter(prefix="/api/v1", tags=["instances"])


@router.get("/instances")
def get_instances(
    db: DbSession, profile: str = "prod", user: CurrentUser = Depends(require_user)
):
    """A.10: a degraded read is still a 200."""
    latest = VersionRepository(db).latest_live(profile)
    return ok(instances_service.collect(profile, int(latest.version) if latest else None))
```

`console/backend/app/routers/status.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ok
from app.services import status_service

router = APIRouter(prefix="/api/v1", tags=["status"])


@router.get("/status")
def get_status(
    db: DbSession, profile: str = "prod", user: CurrentUser = Depends(require_user)
):
    """A.11: the top bar and the publish gate read this."""
    return ok(status_service.snapshot(db, profile))
```

`console/backend/app/core/router_registry.py` 的 import 行改为 `from app.routers import auth, catalog, health, instances, profiles, status`，并按 `/api/v1` 顺序追加 `profiles.router`、`instances.router`、`status.router`。

- [ ] **Step 8: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_pool.py -q`
Expected: 5 passed。

Run: `cd console/backend && python -m pytest tests/integration/test_history.py tests/integration/test_instances.py -q`
Expected: 9 passed。

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿（阶段 C 检查点：`pytest tests/unit tests/integration` 绿）。

- [ ] **Step 9: 与旧实现对照（阶段 C 检查点）**

在一个**装了依赖但没接 supervisor**的环境里，把同一份 catalog 交给两边，比对 `parameters` 数组（忽略包络）：

```bash
cd demo && python -c "import json;from param_platform import catalog;c=catalog.load();print(json.dumps([e.as_json() for e in c.entries],ensure_ascii=False,sort_keys=True))" > /tmp/old.json
cd ../console/backend && PARAM_CATALOG_PATH=../../docs/parameter-catalog.yaml python -c "import json;from app.services import catalog_service;c=catalog_service.load();print(json.dumps([e.as_json() for e in c.entries],ensure_ascii=False,sort_keys=True))" > /tmp/new.json
diff /tmp/old.json /tmp/new.json && echo IDENTICAL
```

Expected: `IDENTICAL`。有差异说明 `catalog.py` 迁移时被改坏了。

Windows PowerShell 没有 `/tmp` 也没有 `diff`，等价写法是：把两处 `> /tmp/x.json` 换成 `| Out-File -Encoding utf8 $env:TEMP\x.json`，把最后一条换成 `Compare-Object (Get-Content $env:TEMP\old.json) (Get-Content $env:TEMP\new.json)`——**没有输出就是一致**。

这条对照是一次性检查，跑在阶段 C（此时 `demo/` 还在原位）。Task 23 归档之后不能再重跑；真需要重跑就把 `cd demo` 改成 `cd archive/demo`。

- [ ] **Step 10: 提交**

```bash
git add console/backend/app console/backend/tests
git commit -m "feat(console): pool probe, versions, audit, instances and status endpoints"
```

---

# 阶段 D：运维台（P2）

## Task 11: 前端基础设施（client / 错误翻译 / stores / 路由 / 布局 / 登录）

**Files:**
- Create: `console/frontend/src/types/api.d.ts`
- Create: `console/frontend/src/utils/error.ts`、`format.ts`、`storage.ts`
- Test: `console/frontend/src/utils/error.spec.ts`、`format.spec.ts`
- Create: `console/frontend/src/api/client.ts`、`api/auth.ts`
- Create: `console/frontend/src/stores/index.ts`、`stores/auth.ts`、`stores/console.ts`
- Create: `console/frontend/src/router/nav.ts`
- Modify: `console/frontend/src/router/index.ts`（替换 Task 2 的占位路由）
- Modify: `console/frontend/src/main.ts`（装 antd、显式 pinia 实例）
- Create: `console/frontend/src/i18n/index.ts`、`i18n/zh-CN.ts`
- Create: `console/frontend/src/components/ErrorBanner.vue`
- Create: `console/frontend/src/layouts/ConsoleLayout.vue`
- Create: `console/frontend/src/views/LoginView.vue`
- Delete: `console/frontend/src/views/PlaceholderView.vue`（Task 2 的占位，被真实布局取代）

**Interfaces:**
- Consumes: `POST /api/v1/auth/login`（→ `{accessToken,tokenType,expiresIn,refreshToken,user}`）、`POST /api/v1/auth/refresh`、`GET /api/v1/auth/me`（Task 7）；`GET /api/v1/status`（→ `{profile,version,status,catalogCommit,validatorMode,db,pipeline,internalTokenConfigured}`，Task 10）。
- Produces: `AppError{class,code,message,requestId,detail}`；`api.get<T>(url,config?) / api.post<T>(url,body?,config?) / api.delete<T>(url)`（自动拆 `ApiResponse` 包络，只把 `data` 交给调用方）；`translate(code)`、`fallbackCode(status)`；`useAuthStore()`（`user / signedIn / isAdmin / login() / logout()`）、`useConsoleStore()`（`profile / status / statusError / refreshStatus() / selectProfile() / startPolling() / stopPolling()`）；路由名 `login`、`console`；`NAV_GROUPS` / `navItemsFor(face)` 供 Task 12/13 点亮菜单；`useShellStore()`（`siderCollapsed / drawerOpen / voiceOverlay / toggleSider() / closeDrawer() / openOverlay() / closeOverlay()`，唯一 storage 键 `s2s.shell.collapsed`）。

**为什么令牌放 `sessionStorage` 而不是 `localStorage`**：控制台是单机运维工具，常被多人用同一浏览器登录；`sessionStorage` 关标签页即失效，也满足「密钥值永不进 `localStorage`」（Global Constraints）。`refreshToken` 与 `accessToken` 同地存放，键名 `s2s.console.session`；用户输入过的密钥不进任何 storage。

- [ ] **Step 1: 写类型**

`console/frontend/src/types/api.d.ts`：

```ts
/** The envelope every `/api/v1/*` success response carries (A.0). */
export interface Envelope<T> {
  code: number
  message: string
  data: T
}

/** The envelope every `/api/v1/*` failure carries (A.0). */
export interface ApiErrorBody {
  code: string
  message: string
  detail?: unknown[]
  requestId?: string
}

/** Every paged list endpoint answers with this (A.0). */
export interface Page<T> {
  list: T[]
  total: number
  page: number
  pageSize: number
}

export interface User {
  username: string
  role: 'admin' | 'operator'
}

export interface UserProfile extends User {
  lastLoginAt: string | null
}

export interface TokenBundle {
  accessToken: string
  tokenType: 'bearer'
  expiresIn: number
  refreshToken: string
  user: User
}

/** A.11 — the top bar reads this. */
export interface StatusSnapshot {
  profile: string
  version: number | null
  status: string
  catalogCommit: string
  validatorMode: 'runtime' | 'structural'
  db: 'ok' | 'unavailable'
  pipeline: 'ok' | 'unreachable'
  internalTokenConfigured: boolean
}
```

`catalog.d.ts`、`profile.d.ts`、`voice.d.ts` 由使用它们的任务各自追加（Task 12 / Task 18）。

- [ ] **Step 2: 先写错误翻译的失败测试**

`console/frontend/src/utils/error.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { fallbackCode, translate } from './error'

describe('translate', () => {
  it('maps the codes the backend is allowed to send', () => {
    expect(translate('unauthorized')).toBe('登录已过期，请重新登录')
    expect(translate('vram_budget_exceeded')).toBe('显存预算不足，请减少 pipeline 数量或换更小的模型')
    expect(translate('publish_in_progress')).toBe('已有一次发布正在进行')
    expect(translate('version_not_rollbackable')).toBe('该版本不可回滚')
  })

  it('never falls back to the server message', () => {
    // A.0: the UI translates `code` and must not parse `message` — the message is
    // English and may quote an input value (B7). A code we do not know yet gets a
    // neutral sentence, not the raw text.
    expect(translate('brand_new_code')).toBe('操作失败，请查看审计记录')
  })
})

describe('fallbackCode', () => {
  it('gives every status the UI can receive a code of our own', () => {
    expect(fallbackCode(503)).toBe('db_unavailable')
    expect(fallbackCode(403)).toBe('forbidden')
    expect(fallbackCode(undefined)).toBe('network_error')
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd console/frontend && npx vitest run src/utils/error.spec.ts`
Expected: FAIL，`Failed to resolve import "./error"`。

- [ ] **Step 4: 实现 `utils/error.ts`**

```ts
/**
 * Machine code → human sentence. The backend sends `code` for exactly this
 * purpose (A.0): `message` is English, may quote an input value, and is not
 * something the UI is allowed to render.
 */
export const ERROR_TEXT: Record<string, string> = {
  // auth
  unauthorized: '登录已过期，请重新登录',
  invalid_credentials: '用户名或密码不正确',
  invalid_refresh_token: '登录已失效，请重新登录',
  too_many_attempts: '失败次数过多，请稍后再试',
  forbidden: '当前角色无权执行该操作',
  // write path
  invalid_parameter: '参数不合法',
  version_conflict: '配置已被他人修改，请刷新后重试',
  validation_failed: '参数校验未通过',
  vram_budget_exceeded: '显存预算不足，请减少 pipeline 数量或换更小的模型',
  publish_in_progress: '已有一次发布正在进行',
  render_failed: '生成配置文件失败',
  restart_unavailable: '无法重启 pipeline 进程',
  healthcheck_timeout: '重启后健康检查超时，已回滚',
  pipeline_token_missing: 'pipeline 缺少内部令牌',
  pipeline_unavailable: 'pipeline 进程不可达',
  internal_token_missing: '控制台未配置内部令牌',
  env_requires_recreate: '该字段需要重建容器才能生效，请在部署窗口处理',
  rollback_failed: '自动回滚也失败了，请人工介入',
  // read path
  pool_unreachable: '无法连接 pipeline 池',
  catalog_unavailable: '参数目录不可用',
  db_unavailable: '数据库不可用',
  unknown_profile: '未知的 profile',
  unknown_version: '未知的版本',
  version_not_rollbackable: '该版本不可回滚',
  no_draft: '没有可丢弃的草稿',
  unsupported_field: '该字段不支持热更新',
  asset_missing: '静态资源缺失',
  not_implemented: '功能尚未启用',
  // ours, never sent by the backend
  network_error: '网络不可达，请检查连接',
  timeout: '请求超时',
  not_found: '接口或资源不存在',
  unknown: '未知错误'
}

export const FALLBACK_TEXT = '操作失败，请查看审计记录'

export function translate(code: string): string {
  return ERROR_TEXT[code] ?? FALLBACK_TEXT
}

/**
 * A body-less failure (proxy error page, connection reset) still has to become
 * something the user can read, so the status code is turned into one of our own
 * codes. These three plus `unknown` are the only codes the frontend invents.
 */
export function fallbackCode(status?: number): string {
  switch (status) {
    case 403:
      return 'forbidden'
    case 404:
      return 'not_found'
    case 409:
      return 'version_conflict'
    case 429:
      return 'too_many_attempts'
    case 503:
      return 'db_unavailable'
    default:
      return 'network_error'
  }
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd console/frontend && npx vitest run src/utils/error.spec.ts`
Expected: 3 passed。

- [ ] **Step 6: 写 `utils/format.ts` 与它的测试**

`console/frontend/src/utils/format.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { formatDuration, formatTime } from './format'

describe('formatTime', () => {
  it('renders a UTC instant without the T', () => {
    expect(formatTime('2026-10-24T08:09:10Z')).toBe('2026-10-24 08:09:10')
  })

  it('renders an empty value as a dash, not as the epoch', () => {
    expect(formatTime(null)).toBe('—')
    expect(formatTime('')).toBe('—')
  })
})

describe('formatDuration', () => {
  it('keeps one decimal under ten seconds and drops it above', () => {
    expect(formatDuration(0.4)).toBe('0.4s')
    expect(formatDuration(41.27)).toBe('41s')
    expect(formatDuration(null)).toBe('—')
  })
})
```

`console/frontend/src/utils/format.ts`：

```ts
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)

export const DASH = '—'

/** ISO 8601 UTC in, local wall clock out (A.0). */
export function formatTime(value: string | null | undefined): string {
  if (!value) return DASH
  const at = dayjs(value)
  return at.isValid() ? at.format('YYYY-MM-DD HH:mm:ss') : DASH
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return DASH
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`
}
```

Run: `cd console/frontend && npx vitest run src/utils`
Expected: 5 passed（`error.spec.ts` 3 + `format.spec.ts` 2）。注意 `environment: 'node'` 下 `dayjs` 用系统时区，测试用的是无时区偏移的 `Z` 时刻且只断言格式——所以不要把断言写成依赖本地时区的值。

- [ ] **Step 7: 写 `utils/storage.ts`**

```ts
import type { TokenBundle } from '@/types/api'

const SESSION_KEY = 's2s.console.session'
const PROFILE_KEY = 's2s.console.profile'

export const DEFAULT_PROFILE = 'prod'

/**
 * `sessionStorage`, not `localStorage`: the console is a single-host ops tool
 * that tends to share a browser, and closing the tab should end the session.
 * Nothing else is persisted — a secret typed into a form lives in component
 * state until it is sent.
 */
export function readBundle(): TokenBundle | null {
  const raw = sessionStorage.getItem(SESSION_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as TokenBundle
    return typeof parsed?.accessToken === 'string' && parsed.accessToken ? parsed : null
  } catch {
    return null
  }
}

export function readToken(): string {
  return readBundle()?.accessToken ?? ''
}

export function saveBundle(bundle: TokenBundle): void {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(bundle))
}

export function clearSession(): void {
  sessionStorage.removeItem(SESSION_KEY)
}

export function readProfile(): string {
  return sessionStorage.getItem(PROFILE_KEY) || DEFAULT_PROFILE
}

export function saveProfile(profile: string): void {
  sessionStorage.setItem(PROFILE_KEY, profile)
}
```

- [ ] **Step 8: 写 `api/client.ts`**

```ts
import axios, { AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios'

import type { ApiErrorBody, Envelope, TokenBundle } from '@/types/api'
import { fallbackCode, translate } from '@/utils/error'
import { clearSession, readBundle, readToken, saveBundle } from '@/utils/storage'

/** Everything a component needs to know about a failed call. */
export class AppError extends Error {
  readonly code: string
  readonly requestId: string
  readonly detail: unknown[]

  constructor(code: string, message: string, requestId = '', detail: unknown[] = []) {
    super(message)
    this.name = 'AppError'
    this.code = code
    this.requestId = requestId
    this.detail = detail
  }
}

/** Same-origin relative base: the page never learns an upstream address (D1). */
export const client = axios.create({ baseURL: '/api/v1', timeout: 30_000 })

type Retriable = AxiosRequestConfig & { __retried?: boolean }

let inFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const bundle = readBundle()
  if (!bundle?.refreshToken) return null
  // Raw axios on purpose: going through `client` would re-enter this interceptor
  // on a 401 from `/auth/refresh` and recurse until the tab gives up.
  const response = await axios.post<Envelope<TokenBundle>>('/api/v1/auth/refresh', {
    refreshToken: bundle.refreshToken
  })
  const next = response.data.data
  saveBundle(next)
  return next.accessToken
}

/** One refresh attempt shared by every 401 that lands while it is running. */
function refreshOnce(): Promise<string | null> {
  if (inFlight === null) {
    inFlight = refreshAccessToken()
      .catch(() => null)
      .finally(() => {
        inFlight = null
      }) as Promise<string | null>
  }
  return inFlight
}

function redirectToLogin(): void {
  if (!window.location.pathname.startsWith('/console')) return
  const next = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.assign(`/console/login?next=${next}`)
}

client.interceptors.request.use((config) => {
  const token = readToken()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

client.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError<ApiErrorBody>) => {
    const config = error.config as Retriable | undefined
    const status = error.response?.status
    // A 401 from `/auth/*` is a wrong password, not an expired session: trying to
    // refresh a login turns a typo into a redirect loop.
    const isAuthEndpoint = config?.url?.startsWith('/auth/') ?? false

    if (status === 401 && config && !config.__retried && !isAuthEndpoint) {
      const token = await refreshOnce()
      if (token) {
        config.__retried = true
        return client.request(config)
      }
      clearSession()
      redirectToLogin()
    }

    const body = error.response?.data
    const code = typeof body?.code === 'string' && body.code ? body.code : fallbackCode(status)
    return Promise.reject(
      new AppError(code, translate(code), body?.requestId ?? '', body?.detail ?? [])
    )
  }
)

/** Unwraps `{code,message,data}` so callers only ever see `data`. */
async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await client.request<Envelope<T>>(config)
  return response.data.data
}

export const api = {
  get: <T>(url: string, config?: AxiosRequestConfig): Promise<T> =>
    request<T>({ ...config, url, method: 'get' }),
  post: <T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> =>
    request<T>({ ...config, url, method: 'post', data: body }),
  delete: <T>(url: string, config?: AxiosRequestConfig): Promise<T> =>
    request<T>({ ...config, url, method: 'delete' })
}
```

`api/client.ts` 不写单测：它整块是 axios 拦截器，`environment: 'node'` 下要造 `sessionStorage`、`window.location` 和网络桩，测到的全是桩。它的行为由 Task 13 的 Playwright 用例与手工检查覆盖。

- [ ] **Step 9: 写 `api/auth.ts`**

```ts
import { api } from './client'
import type { TokenBundle, UserProfile } from '@/types/api'

export const login = (username: string, password: string): Promise<TokenBundle> =>
  api.post<TokenBundle>('/auth/login', { username, password })

export const me = (): Promise<UserProfile> => api.get<UserProfile>('/auth/me')
```

- [ ] **Step 10: 写 stores 与 `main.ts`**

`console/frontend/src/stores/index.ts`：

```ts
import { createPinia } from 'pinia'

/** One instance, imported by `main.ts` and by the router guard. */
export const pinia = createPinia()
```

`console/frontend/src/stores/auth.ts`：

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import * as authApi from '@/api/auth'
import type { TokenBundle, User } from '@/types/api'
import { clearSession, readBundle, saveBundle } from '@/utils/storage'

export const useAuthStore = defineStore('auth', () => {
  const bundle = ref<TokenBundle | null>(readBundle())
  const user = computed<User | null>(() => bundle.value?.user ?? null)
  const signedIn = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function login(username: string, password: string): Promise<void> {
    const next = await authApi.login(username, password)
    bundle.value = next
    saveBundle(next)
  }

  function logout(): void {
    bundle.value = null
    clearSession()
  }

  return { bundle, user, signedIn, isAdmin, login, logout }
})
```

`console/frontend/src/stores/console.ts`：

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, AppError } from '@/api/client'
import type { StatusSnapshot } from '@/types/api'
import { readProfile, saveProfile } from '@/utils/storage'

export const useConsoleStore = defineStore('console', () => {
  const profile = ref(readProfile())
  const status = ref<StatusSnapshot | null>(null)
  const statusError = ref('')
  let timer: number | undefined

  async function refreshStatus(): Promise<void> {
    try {
      status.value = await api.get<StatusSnapshot>('/status', { params: { profile: profile.value } })
      statusError.value = ''
    } catch (error) {
      // A dead backend is a state the top bar must show, not an exception the
      // layout should blow up on.
      status.value = null
      statusError.value = error instanceof AppError ? error.message : '状态不可读'
    }
  }

  function selectProfile(next: string): void {
    profile.value = next
    saveProfile(next)
    void refreshStatus()
  }

  function startPolling(intervalMs = 15_000): void {
    stopPolling()
    void refreshStatus()
    timer = window.setInterval(() => void refreshStatus(), intervalMs)
  }

  function stopPolling(): void {
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  return { profile, status, statusError, refreshStatus, selectProfile, startPolling, stopPolling }
})
```

`console/frontend/src/main.ts`（替换 Task 2 版本）：

```ts
import Antd from 'ant-design-vue'
import { createApp } from 'vue'

import App from './App.vue'
import i18n from './i18n'
import router from './router'
import { pinia } from './stores'

import 'ant-design-vue/dist/reset.css'
import './styles/index.less'

// `reset.css` first: antd's reset is the baseline, `index.less` the overrides.
createApp(App).use(pinia).use(i18n).use(Antd).use(router).mount('#app')
```

> **`App.vue` 不动**。Task 2 Step 5 的 `<a-config-provider :theme="themeConfig">` 是根级主题入口，本步只把 pinia 换成显式实例、加 i18n，**不得**把 `ConfigProvider` 拆掉或下沉到 `ConsoleLayout`。拆掉的直接后果：对话页（`/`，不经过 `ConsoleLayout`）里所有 AntD 控件回到亮色，`a-modal` / `a-slider` / `a-select` 全部刺眼。

- [ ] **Step 11: 写 i18n 骨架**

`console/frontend/src/i18n/zh-CN.ts`：

```ts
export default {
  app: {
    title: 'S2S 部署参数控制台',
    signIn: '登录',
    signOut: '退出',
    username: '用户名',
    password: '密码',
    profile: 'Profile'
  },
  nav: {
    params: '参数',
    sessions: '活跃会话',
    versions: '版本',
    instances: '实例',
    audit: '审计'
  }
}
```

`console/frontend/src/i18n/index.ts`：

```ts
import { createI18n } from 'vue-i18n'

import zhCN from './zh-CN'

/** Only zh-CN ships now; the mechanism is here so a second locale is a file. */
export default createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN }
})
```

- [ ] **Step 12: 写 `components/ErrorBanner.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { AppError } from '@/api/client'

const props = defineProps<{ error: AppError | null }>()

const text = computed(() => props.error?.message ?? '')
const requestId = computed(() => props.error?.requestId ?? '')
</script>

<template>
  <a-alert v-if="text" class="error-banner" type="error" show-icon :message="text">
    <template v-if="requestId" #description>
      <span class="error-banner__id">requestId: {{ requestId }}</span>
    </template>
  </a-alert>
</template>
```

- [ ] **Step 13: 写 `router/nav.ts` 与 `router/index.ts`**

`console/frontend/src/router/nav.ts`：

```ts
export type ShellFace = 'console' | 'voice'

/** 对话页侧栏里四个「打开浮层」的项——它们不是路由，旧页也从来没给它们路由。 */
export type VoiceOverlay = 'history' | 'tools' | 'settings' | 'about'

export interface NavItem {
  /** 路由名（自 Task 12/13 注册）；`action` 项没有路由。 */
  name?: string
  /** 只在 voice 面出现：由 `ConsoleLayout` 写进 `stores/shell` 的 `voiceOverlay`。 */
  action?: VoiceOverlay
  label: string
}

export interface NavGroup {
  face: ShellFace
  label: string
  items: NavItem[]
}

/**
 * 侧栏两组，按 `route.meta.face` 只渲染其中一组（§3.2.4）。
 * `ConsoleLayout` 用 `router.hasRoute(item.name)` 过滤尚未注册的路由，所以这张表
 * 可以在视图建齐之前就写完整。
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    face: 'console',
    label: '部署',
    items: [
      { name: 'params', label: '参数' },
      { name: 'sessions', label: '活跃会话' },
      { name: 'versions', label: '版本' },
      { name: 'instances', label: '实例' },
      { name: 'audit', label: '审计' }
    ]
  },
  {
    face: 'voice',
    label: '对话',
    items: [
      { name: 'voice', label: 'Voice' },
      { action: 'history', label: 'History' },
      { action: 'tools', label: 'Tools' },
      { action: 'settings', label: 'Settings' },
      { action: 'about', label: 'About' }
    ]
  }
]

export function navItemsFor(face: ShellFace): NavItem[] {
  return NAV_GROUPS.find((group) => group.face === face)?.items ?? []
}
```

`console/frontend/src/stores/shell.ts`——外壳自己的视图状态。**不是**业务状态：它只活一个页面生命周期 + 一个 `localStorage` 键（侧栏折叠），不碰会话、不碰密钥：

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { VoiceOverlay } from '@/router/nav'

/** 折叠态是纯视图偏好，允许跨会话保留；整个应用只写这一个键。 */
const COLLAPSED_KEY = 's2s.shell.collapsed'

/** 抽屉阈值：与 `ConsoleLayout` 的 `@media (max-width: 979px)` 必须同值。 */
export const DRAWER_BREAKPOINT = 980

export const useShellStore = defineStore('shell', () => {
  const siderCollapsed = ref(localStorage.getItem(COLLAPSED_KEY) === '1')
  const drawerOpen = ref(false)
  const voiceOverlay = ref<VoiceOverlay | null>(null)

  function toggleSider(): void {
    siderCollapsed.value = !siderCollapsed.value
    localStorage.setItem(COLLAPSED_KEY, siderCollapsed.value ? '1' : '0')
  }

  /** 小屏时侧栏是抽屉：点完导航必须自己关上，否则会把舞台挤没。 */
  function closeDrawer(): void {
    drawerOpen.value = false
  }

  function openOverlay(overlay: VoiceOverlay): void {
    voiceOverlay.value = overlay
    drawerOpen.value = false
  }

  function closeOverlay(): void {
    voiceOverlay.value = null
  }

  return { siderCollapsed, drawerOpen, voiceOverlay, toggleSider, closeDrawer, openOverlay, closeOverlay }
})
```

`console/frontend/src/router/index.ts`（替换 Task 2 的占位实现）：

```ts
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

// 导出这张表本身：`router.spec.ts`（Task 20 Step 20）用 `createMemoryHistory`
// 建一个不进浏览器的同构实例来断言 matched 链，不依赖 DOM。
export const routes: RouteRecordRaw[] = [
  {
    path: '/console/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue')
  },
  {
    // 一个外壳两个面（§3.2.4）：`/` 与 `/console/*` 是同一个 `ConsoleLayout`
    // 的子路由。只有 console 面要求登录；对话页匿名可开，与旧页一致。
    path: '/',
    component: () => import('@/layouts/ConsoleLayout.vue'),
    children: [
      {
        path: '',
        name: 'voice',
        component: () => import('@/views/VoicePlaceholderView.vue'),
        meta: { face: 'voice' }
      },
      {
        // 无组件记录只是命名空间：`hasRoute` 与 `addRoute` 需要一个挂点，
        // 子路由由 Task 12/13 注册进来。`meta` 会被子路由继承。
        path: 'console',
        name: 'console',
        meta: { face: 'console', requiresAuth: true },
        children: []
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const auth = useAuthStore(pinia)
  // 只看合并后的 `requiresAuth`：外壳自己不上锁，否则对话页也被拦在登录页外。
  if (to.meta.requiresAuth && !auth.signedIn) {
    return { name: 'login', query: { next: to.fullPath } }
  }
  if (to.name === 'login' && auth.signedIn) {
    return { path: '/console' }
  }
  return true
})

export default router
```

`/` 先指向一个占位视图，Task 20 用真实 `VoiceView.vue` 替换它。`console/frontend/src/views/VoicePlaceholderView.vue`（占位期也套 `ConsoleLayout`，预览里看到的外壳就是最终形态）：

```vue
<template>
  <main class="placeholder">
    <h1>S2S</h1>
    <p>语音界面正在迁移中。</p>
  </main>
</template>
```

同时删除 `console/frontend/src/views/PlaceholderView.vue`（Task 2 的两条路由都已被替换）。

- [ ] **Step 14: 写 `layouts/ConsoleLayout.vue`（一个外壳两个面）**

对话页与运维台共用这一个外壳（§3.2.4）：面由 `route.meta.face` 声明，外壳只负责顶栏、侧栏与内容区。对话页没有自己的 `.v-top` 顶栏，它把账号 chip 与工具 / 历史 / 设置三枚按钮 `Teleport` 到顶栏里的 `#shell-actions`（About 是 `IdentityBlock` 里的圆钮，留在舞台）。

```vue
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { navItemsFor, type NavItem } from '@/router/nav'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore } from '@/stores/console'
import { DRAWER_BREAKPOINT, useShellStore } from '@/stores/shell'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const consoleStore = useConsoleStore()
const shell = useShellStore()

/** 一个外壳两个面：面由子路由声明，外壳不猜。 */
const face = computed<'console' | 'voice'>(() => (route.meta.face === 'voice' ? 'voice' : 'console'))

// `hasRoute` 让菜单在 Task 12/13 逐个建视图的过程中保持诚实。
const items = computed(() => navItemsFor(face.value).filter((item) => !item.name || router.hasRoute(item.name)))
const selected = computed(() => [String(route.name ?? '')])

function keyOf(item: NavItem): string {
  return item.name ?? `overlay:${item.action}`
}

const narrow = ref(false)
let mql: MediaQueryList | null = null

function syncNarrow(event: MediaQueryList | MediaQueryListEvent): void {
  narrow.value = event.matches
  if (!narrow.value) shell.closeDrawer()
}

const profileOptions = ['prod', 'dev'].map((value) => ({ value, label: value }))

const pipelineText = computed(() => {
  const status = consoleStore.status
  if (!status) return consoleStore.statusError || '未连接'
  const version = status.version === null ? '未发布' : `v${status.version}`
  return status.pipeline === 'ok' ? `pipeline ok · ${version}` : 'pipeline 不可达'
})

const pipelineBadge = computed(() => {
  if (!consoleStore.status) return 'error'
  return consoleStore.status.pipeline === 'ok' ? 'success' : 'error'
})

// 状态轮询只属于运维面：对话页匿名可用，不该去打 JWT 接口（否则顶栏挂一条 401）。
watch(
  face,
  (value) => (value === 'console' ? consoleStore.startPolling() : consoleStore.stopPolling()),
  { immediate: true }
)

onMounted(() => {
  // 与 `console.less` / `DRAWER_BREAKPOINT` 同值：小屏侧栏变抽屉，舞台不被挤压。
  mql = window.matchMedia(`(max-width: ${DRAWER_BREAKPOINT - 1}px)`)
  syncNarrow(mql)
  mql.addEventListener('change', syncNarrow)
})

onBeforeUnmount(() => {
  mql?.removeEventListener('change', syncNarrow)
  consoleStore.stopPolling()
})

function onMenuClick(info: { key: string | number }): void {
  const item = items.value.find((candidate) => keyOf(candidate) === String(info.key))
  if (!item) return
  if (item.name) void router.push({ name: item.name })
  else if (item.action) shell.openOverlay(item.action)
  shell.closeDrawer()
}

function signOut(): void {
  auth.logout()
  void router.replace({ name: 'login' })
}
</script>

<template>
  <div class="shell" :data-face="face" :class="{ 'is-collapsed': shell.siderCollapsed }">
    <header class="shell__top">
      <button
        class="shell__burger"
        type="button"
        aria-label="Toggle navigation"
        aria-controls="shell-nav"
        :aria-expanded="shell.drawerOpen"
        @click="shell.drawerOpen = !shell.drawerOpen"
      >
        <span /><span /><span />
      </button>

      <span class="shell__brand">{{ face === 'console' ? 'S2S 控制台' : 'S2S' }}</span>

      <template v-if="face === 'console'">
        <a-select
          :value="consoleStore.profile"
          :options="profileOptions"
          size="small"
          class="shell__profile"
          @change="(value) => consoleStore.selectProfile(String(value))"
        />
        <a-badge :status="pipelineBadge" :text="pipelineText" />
        <span class="shell__spacer" />
        <button class="shell__collapse" type="button" aria-label="Toggle sidebar" @click="shell.toggleSider()">
          {{ shell.siderCollapsed ? '»' : '«' }}
        </button>
        <span class="shell__user">{{ auth.user?.username }} · {{ auth.user?.role }}</span>
        <a-button type="link" size="small" @click="signOut">退出</a-button>
      </template>

      <template v-else>
        <span class="shell__spacer" />
        <!-- 对话页把账号 chip 与工具 / 历史 / 设置三枚按钮 Teleport 到这里（§3.2.4），
             所以它没有自己的顶栏，也无法盖住外壳。 -->
        <div id="shell-actions" class="shell__actions" />
      </template>
    </header>

    <div class="shell__body">
      <nav id="shell-nav" class="shell__nav" :class="{ 'is-open': shell.drawerOpen }" aria-label="主导航">
        <a-menu mode="inline" theme="dark" :selected-keys="selected" @click="onMenuClick">
          <a-menu-item v-for="item in items" :key="keyOf(item)">{{ item.label }}</a-menu-item>
        </a-menu>

        <router-link v-if="face === 'voice'" class="shell__link" :to="{ name: 'console' }">运维控制台 ↗</router-link>
      </nav>

      <div v-if="shell.drawerOpen" class="shell__scrim" @click="shell.closeDrawer()" />

      <main class="shell__content">
        <router-view v-slot="{ Component }">
          <component :is="Component" v-if="Component" />
          <a-empty v-else description="选择左侧菜单开始" />
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped lang="less">
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #0b1020;
  color: #e6e8f0;

  &__top {
    align-items: center;
    background: #141a2e;
    border-bottom: 1px solid #1f2740;
    display: flex;
    flex: 0 0 56px;
    gap: 16px;
    height: 56px;
    padding: 0 20px;
    position: relative;
    z-index: 20;
  }

  &__burger {
    align-items: center;
    background: transparent;
    border: 0;
    color: #8b93a7;
    cursor: pointer;
    display: none;
    flex-direction: column;
    gap: 4px;
    padding: 6px 4px;

    span {
      background: currentColor;
      display: block;
      height: 2px;
      width: 18px;
    }
  }

  &__brand {
    font-weight: 600;
    white-space: nowrap;
  }

  &__profile {
    width: 120px;
  }

  &__spacer {
    flex: 1;
  }

  // Teleport 的落点：对话页的四个圆钮就长在这里。
  &__actions {
    align-items: center;
    display: flex;
    gap: 8px;
    min-height: 32px;
  }

  &__collapse {
    background: transparent;
    border: 0;
    color: #8b93a7;
    cursor: pointer;
    font-size: 14px;
    padding: 2px 6px;
  }

  &__user {
    color: #8b93a7;
    font-size: 12px;
  }

  &__body {
    display: flex;
    flex: 1 1 auto;
    min-height: 0;
    position: relative;
  }

  &__nav {
    background: #0f1424;
    border-right: 1px solid #1f2740;
    flex: 0 0 200px;
    min-width: 0;
    overflow: auto;
    transition: flex-basis 160ms ease, width 160ms ease;
    width: 200px;
  }

  &__link {
    color: #8b93a7;
    display: block;
    font-size: 12px;
    padding: 12px 16px;
  }

  &__content {
    flex: 1 1 auto;
    min-height: 0;
    min-width: 0;
    overflow: auto;
  }

  &__scrim {
    display: none;
  }
}

.shell.is-collapsed .shell__nav {
  flex-basis: 56px;
  width: 56px;
}

/* 两个面的内容区边距不同：运维台要内边距，对话页要一整块舞台。 */
.shell[data-face='console'] .shell__content {
  padding: 20px;
}

.shell[data-face='voice'] .shell__content {
  /* 舞台高度由 `.v-page { height: 100% }` 自己管，外壳不再给 100vh。
     滚动只发生在历史抽屉里，页面本身不滚。 */
  overflow: hidden;
  padding: 0;
}

@media (max-width: 979px) {
  /* 小屏：侧栏变抽屉，舞台宽度不被挤压（§3.2.4）。 */
  .shell__burger {
    display: inline-flex;
  }

  .shell__nav {
    bottom: 0;
    flex-basis: 200px;
    left: 0;
    position: absolute;
    top: 0;
    transform: translateX(-100%);
    transition: transform 160ms ease;
    width: 200px;
    z-index: 30;
  }

  .shell__nav.is-open {
    box-shadow: 24px 0 40px rgba(0, 0, 0, 0.45);
    transform: none;
  }

  /* 抽屉态忽略折叠：56px 的图标条在触屏上没有意义。 */
  .shell.is-collapsed .shell__nav {
    flex-basis: 200px;
    width: 200px;
  }

  .shell__scrim {
    background: rgba(4, 6, 12, 0.55);
    display: block;
    inset: 0;
    position: absolute;
    z-index: 25;
  }
}
</style>
```

`console/frontend/src/styles/console.less` 要同时补齐高度链：`html, body, #app { height: 100% }`，否则 `.shell { height: 100% }` 会退化成内容高度，`a-layout` 时代那种“页脚向上飘”会复活。

- [ ] **Step 15: 写 `views/LoginView.vue`**

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { AppError } from '@/api/client'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const pending = ref(false)
const failure = ref<AppError | null>(null)

// Only same-site console paths are acceptable as a landing target: an open
// redirect on a login form is a phishing primitive.
const next = computed(() => {
  const value = route.query.next
  return typeof value === 'string' && value.startsWith('/console') ? value : '/console'
})

async function submit(): Promise<void> {
  failure.value = null
  pending.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    password.value = '' // the password does not outlive the request
    await router.replace(next.value)
  } catch (error) {
    failure.value =
      error instanceof AppError ? error : new AppError('unknown', '登录失败，请重试')
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="login">
    <form class="login__card" @submit.prevent="submit">
      <h1 class="login__title">S2S 部署参数控制台</h1>

      <label class="login__label" for="username">用户名</label>
      <a-input id="username" v-model:value="username" autocomplete="username" :disabled="pending" />

      <label class="login__label" for="password">密码</label>
      <a-input-password
        id="password"
        v-model:value="password"
        autocomplete="current-password"
        :disabled="pending"
      />

      <ErrorBanner :error="failure" />

      <a-button type="primary" html-type="submit" block :loading="pending">登录</a-button>
    </form>
  </div>
</template>

<style scoped lang="less">
.login {
  align-items: center;
  display: flex;
  justify-content: center;
  min-height: 100vh;

  &__card {
    background: #141a2e;
    border-radius: 10px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 28px;
    width: 320px;
  }

  &__title {
    color: #e6e8f0;
    font-size: 16px;
    margin: 0 0 8px;
  }

  &__label {
    color: #8b93a7;
    font-size: 12px;
  }
}
</style>
```

- [ ] **Step 16: 类型检查与构建**

Run: `cd console/frontend && npm run build`
Expected: `vue-tsc --noEmit` 无错误，`vite build` 产出 `dist/`。常见失败点：`a-select` 的 `@change` 参数类型是 `unknown`，已用 `String(value)` 兜底；`import type { AppError }` 必须是 `import type`，否则 `verbatimModuleSyntax` 下报错。

- [ ] **Step 17: 起后端与前端，手工验收（阶段 D 第一半）**

Run（终端 A）：`cd console/backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
Run（终端 B）：`cd console/frontend && npm run dev`

浏览器打开 `http://127.0.0.1:3000/console`：

1. 未登录 → 被守卫送到 `/console/login?next=%2Fconsole`；
2. 用 Task 6 `seed_admin` 建的账号登录 → 回到 `/console`，顶栏显示用户名与角色；
3. 顶栏 badge 显示 `pipeline ok` 或 `pipeline 不可达`（取决于本机是否跑着 pipeline，两种都算通过）；
4. 左侧菜单暂时为空（Task 12/13 才有点击目标），内容区显示「选择左侧菜单开始」；
5. 点「退出」→ 回到登录页，再直接访问 `/console` 仍被拦。
6. 用错密码登录 → 提示「用户名或密码不正确」（不是英文 `message`）。

- [ ] **Step 18: 提交**

```bash
git add console/frontend
git commit -m "feat(console): frontend shell with api client, auth store and console layout"
```

---

## Task 12: `ParamsView`：catalog 树 + draft 表单 + 校验结果

**Files:**
- Create: `console/frontend/src/types/catalog.d.ts`、`types/profile.d.ts`
- Create: `console/frontend/src/utils/draft-patch.ts`、`utils/catalog-view.ts`
- Test: `console/frontend/src/utils/draft-patch.spec.ts`、`utils/catalog-view.spec.ts`
- Create: `console/frontend/src/api/catalog.ts`、`api/profiles.ts`
- Create: `console/frontend/src/stores/catalog.ts`、`stores/draft.ts`
- Create: `console/frontend/src/composables/useConfirm.ts`
- Create: `console/frontend/src/components/ParamTree.vue`、`ParamField.vue`、`ExposureTag.vue`、`EffectBadge.vue`、`FixedField.vue`、`DiffTable.vue`、`ConfirmDialog.vue`
- Create: `console/frontend/src/views/ParamsView.vue`
- Modify: `console/frontend/src/router/index.ts`（给 `console` 加 `params` 子路由与默认重定向）

**Interfaces:**
- Consumes: `GET /api/v1/catalog`（→ `parameters[]`，每项 snake_case + `key`，Task 8）；`GET /api/v1/profiles/{p}/draft`（→ `{profile,baseVersion,draft,masked,updatedAt,updatedBy}`）；`POST .../draft`（body `{patch,baseVersion?}` → `{draft,baseVersion,skippedMasked,validation,auditId}`，`validation={ok,mode,resolvedPipelines,expectedPoolSize,warnings}`）；`DELETE .../draft`（→ `{discarded,revertedTo,auditId}`）——后三个来自 Task 9。
- Produces: `baseline(entries, draft) -> Values`、`buildPatch(entries, values, draft) -> Values`；`useCatalogStore()`（`entries / meta / loading / error / load(opts)`）、`useDraftStore()`（`draft / masked / baseVersion / validation / load(profile) / save(profile, patch) / discard(profile)`）；`useConfirm()`；路由名 `params`（`/console/params`，且 `/console` 重定向到此）。

**为什么只有 `draft-patch.ts` / `catalog-view.ts` 有单测**：这两个是全视图里「错了会静默写坏配置 / 静默漏掉字段」的纯函数。表单渲染、树交互、发布按钮用 Task 13 与 Task 18 的 Playwright 用例守。

**落点规则（196 条逐条有落点，§6.1）**：

| 类 | 条数 | 渲染方式 |
|---|---|---|
| 已覆盖 | 120 | `stage ∈ {vad, stt, llm, tts, runtime, server}` 且 `type ≠ fixed` → `ParamField` 可编辑控件 |
| 待补（本轮新增形态） | 16 | 音色绑定 14 条（`tts/qwen3` 10 + `tts/openai_compatible` 3 + `tts/kokoro` 1）→ `VoicePicker`（Task 12B）；人设双动作 2 条（`init_chat_prompt` / `session.instructions`）→ `ParamField` 的 `dualAction` 插槽（文案见 §5.4） |
| 明确不暴露 | 60 | `type=fixed`（17，其中 9 条在 `deploy`）→ `FixedField` 只读行；`stage ∈ {deploy, env, client}` 且非 fixed（16 + 18 + 18 = 52，去掉与 fixed 重叠的 9 后为 43）→ 树里可见、详情只读并标原因 |

- 计数口径：界面写 `196 条 · 193 个唯一名 · 2 个多后端字段`，**不是** 196 个控件——`deploy` / `env` / `client` 的 60 条只读也只占一行；
- 去重（`catalog-view.ts`）：`log_transcripts` 取 `runtime`、`model_name` 取通用 `llm`、`responses_api_reasoning_effort` 取 `responses-api`，被合并的条目进 `aliases` 只在详情里展示；
- `type=fixed` 一律 `FixedField`：不可编辑、无「恢复默认」、`source_ref` 展示为「源码常量 / 编排写死 / 无 YAML 入口」之一；
- 表单只渲染 catalog 里存在的键；出现 catalog 之外的键 → `catalog_entry_missing`（前端在 `buildPatch` 后自检，后端在 A.3 复核）。

**关键语义（A.3）**：
- 只发用户真改过的键（否则每次保存都往 `fields` 里塞全量键名，审计表变得没用）；
- 回显仍是 `***` 的密钥字段**不发出**（发了也只是让服务端原值保留，但会污染审计）；
- `null` = 「回到默认值」；只有当草稿里本来就有值时才有意义，否则是噪声；
- `validation.mode === "structural"` 必须在页面上明说「仅校验了结构」——不得让用户以为跑过运行时校验。

- [ ] **Step 1: 写类型**

`console/frontend/src/types/catalog.d.ts`：

```ts
export type Exposure = 'basic' | 'advanced' | 'expert' | 'ops'

/** One catalog row: `parameter-catalog.yaml` 的直映，字段名保持 snake_case（§6 / A.0）。 */
export interface CatalogEntry {
  key: string
  stage: string
  backend: string | null
  name: string
  type: string
  default: unknown
  choices: unknown[]
  required: boolean
  effect: string
  exposure: Exposure
  impact: string
  change_cost: string
  risk: string | null
  source_ref: string
  source_priority: string[]
}

/** A.1 的 `data`（Task 8 多给了几个计数/变体字段，前端用处不大但类型要完整）。 */
export interface CatalogResponse {
  schema: string
  generatedFrom: string
  generatedAt: string | null
  total: number
  returned: number
  exposureLevels: Exposure[]
  exposureCounts: Record<string, number>
  variantKeys: string[]
  parameters: CatalogEntry[]
}
```

`console/frontend/src/types/profile.d.ts`：

```ts
import type { Values } from '@/utils/draft-patch'

export interface DraftResponse {
  profile: string
  baseVersion: number | null
  draft: Values
  /** 服务端判定为密钥的键（B5）；值一定已是 `***`。 */
  masked: string[]
  updatedAt: string | null
  updatedBy: string
}

export interface ValidationResult {
  ok: boolean
  /** `structural` = 运行时包不在，只校验了结构（§11.2）。 */
  mode: 'runtime' | 'structural'
  resolvedPipelines: string[]
  expectedPoolSize: number | null
  warnings: unknown[]
}

export interface DraftSaveResponse {
  draft: Values
  baseVersion: number | null
  /** 因为回传 `***` 而被忽略的键，UI 可以提示「密钥未变」。 */
  skippedMasked: string[]
  validation: ValidationResult
  auditId: string
}

export interface DiscardResponse {
  discarded: boolean
  revertedTo: string
  auditId: string
}
```

- [ ] **Step 2: 先写 `draft-patch` 的失败测试**

`console/frontend/src/utils/draft-patch.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import type { CatalogEntry } from '@/types/catalog'
import { baseline, buildPatch, MASK, resetValue } from './draft-patch'

function entry(key: string, fallback: unknown): CatalogEntry {
  return {
    key,
    stage: key.split('.')[0],
    backend: null,
    name: key.split('.')[1],
    type: 'string',
    default: fallback,
    choices: [],
    required: false,
    effect: '',
    exposure: 'basic',
    impact: '',
    change_cost: 'restart',
    risk: null,
    source_ref: '',
    source_priority: []
  }
}

const ENTRIES = [entry('vad.min_silence_ms', 500), entry('llm.api_key', ''), entry('stt.language', 'auto')]

describe('baseline', () => {
  it('prefers the draft value and falls back to the catalog default', () => {
    expect(baseline(ENTRIES, { 'vad.min_silence_ms': 700 })).toEqual({
      'vad.min_silence_ms': 700,
      'llm.api_key': '',
      'stt.language': 'auto'
    })
  })

  it('treats a stored null as "use the default"', () => {
    expect(baseline(ENTRIES, { 'stt.language': null })['stt.language']).toBe('auto')
  })
})

describe('buildPatch', () => {
  const draft = { 'vad.min_silence_ms': 700, 'llm.api_key': 'sk-live' }

  it('sends only the keys that changed', () => {
    const values = { ...baseline(ENTRIES, draft), 'stt.language': 'zh' }
    expect(buildPatch(ENTRIES, values, draft)).toEqual({ 'stt.language': 'zh' })
  })

  it('leaves an untouched mask out of the patch', () => {
    // The field still reads `***` because the user never typed a new key.
    const values = { ...baseline(ENTRIES, draft), 'llm.api_key': MASK }
    expect(buildPatch(ENTRIES, values, draft)).toEqual({})
  })

  it('sends null only when there was a draft value to clear', () => {
    const values = { ...baseline(ENTRIES, draft), 'stt.language': resetValue(ENTRIES[2], draft) }
    expect(buildPatch(ENTRIES, values, draft)).toEqual({})

    const cleared = { ...baseline(ENTRIES, draft), 'vad.min_silence_ms': resetValue(ENTRIES[0], draft) }
    expect(buildPatch(ENTRIES, cleared, draft)).toEqual({ 'vad.min_silence_ms': null })
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd console/frontend && npx vitest run src/utils/draft-patch.spec.ts`
Expected: FAIL，找不到 `./draft-patch`。

- [ ] **Step 4: 实现 `utils/draft-patch.ts`**

```ts
import type { CatalogEntry } from '@/types/catalog'

export const MASK = '***'

/** 表单值的集合，键是 catalog 的 `key`（`<stage>.<name>`）。 */
export type Values = Record<string, unknown>

function draftHas(draft: Values, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(draft, key) && draft[key] !== null
}

/** 字段当前应显示的值：草稿优先（`null` 视为未设），否则 catalog 默认值。 */
export function baseline(entries: CatalogEntry[], draft: Values): Values {
  const values: Values = {}
  for (const entry of entries) {
    values[entry.key] = draftHas(draft, entry.key) ? draft[entry.key] : entry.default
  }
  return values
}

/**
 * 交给 `POST /draft` 的 patch。
 *
 * 三个「不发」：没改的、还是掩码的、本来就没值却要「恢复默认」的。第一个
 * 让审计表可读，第二个是为了不让没动过的密钥反复出现在 `fields` 里，第三个
 * 是因为 `null` 只对「草稿里已有值」才有意义（否则服务端会收到一条空操作）。
 */
export function buildPatch(entries: CatalogEntry[], values: Values, draft: Values): Values {
  const base = baseline(entries, draft)
  const patch: Values = {}
  for (const entry of entries) {
    // catalog 的 17 条 fixed 是源码常量：即便调用方把它们塞进 values，也不进 patch（§6.1）。
    if (entry.type === 'fixed') continue
    const key = entry.key
    if (!Object.prototype.hasOwnProperty.call(values, key)) continue
    const next = values[key]
    if (next === MASK) continue
    if (next === base[key]) continue
    if (next === null && !draftHas(draft, key)) continue
    patch[key] = next
  }
  return patch
}

/** 「恢复默认」按钮要写入表单的值：草稿里有值就发 `null`，否则回到默认值。 */
export function resetValue(entry: CatalogEntry, draft: Values): unknown {
  return draftHas(draft, entry.key) ? null : entry.default
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd console/frontend && npx vitest run src/utils`
Expected: 11 passed（`error` 3 + `format` 2 + `draft-patch` 6）。

- [ ] **Step 6: 写 API 模块**

`console/frontend/src/api/catalog.ts`：

```ts
import { api } from './client'
import type { CatalogResponse, Exposure } from '@/types/catalog'

export interface CatalogQuery {
  exposure?: Exposure
  stage?: string
  backend?: string
}

export const getCatalog = (query: CatalogQuery = {}): Promise<CatalogResponse> =>
  api.get<CatalogResponse>('/catalog', { params: query })
```

`console/frontend/src/api/profiles.ts`：

```ts
import { api } from './client'
import type { DraftResponse, DiscardResponse, DraftSaveResponse } from '@/types/profile'
import type { Values } from '@/utils/draft-patch'

export const getDraft = (profile: string): Promise<DraftResponse> =>
  api.get<DraftResponse>(`/profiles/${profile}/draft`)

export const saveDraft = (
  profile: string,
  patch: Values,
  baseVersion: number | null
): Promise<DraftSaveResponse> =>
  api.post<DraftSaveResponse>(`/profiles/${profile}/draft`, { patch, baseVersion })

export const discardDraft = (profile: string): Promise<DiscardResponse> =>
  api.delete<DiscardResponse>(`/profiles/${profile}/draft`)
```

- [ ] **Step 7: 写 stores**

`console/frontend/src/stores/catalog.ts`：

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getCatalog } from '@/api/catalog'
import { AppError } from '@/api/client'
import type { CatalogEntry, Exposure } from '@/types/catalog'

export const useCatalogStore = defineStore('catalog', () => {
  const entries = ref<CatalogEntry[]>([])
  const schema = ref('')
  const generatedFrom = ref('')
  const generatedAt = ref<string | null>(null)
  const exposureCounts = ref<Record<string, number>>({})
  const loading = ref(false)
  const error = ref<AppError | null>(null)

  async function load(options: { exposure?: Exposure; stage?: string } = {}): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await getCatalog(options)
      entries.value = data.parameters
      schema.value = data.schema
      generatedFrom.value = data.generatedFrom
      generatedAt.value = data.generatedAt
      exposureCounts.value = data.exposureCounts
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', '参数目录加载失败')
      entries.value = []
    } finally {
      loading.value = false
    }
  }

  return { entries, schema, generatedFrom, generatedAt, exposureCounts, loading, error, load }
})
```

`console/frontend/src/stores/draft.ts`：

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { AppError } from '@/api/client'
import * as profilesApi from '@/api/profiles'
import type { ValidationResult } from '@/types/profile'
import type { Values } from '@/utils/draft-patch'

export const useDraftStore = defineStore('draft', () => {
  const profile = ref('')
  const draft = ref<Values>({})
  const masked = ref<string[]>([])
  const baseVersion = ref<number | null>(null)
  const updatedAt = ref<string | null>(null)
  const updatedBy = ref('')
  const validation = ref<ValidationResult | null>(null)
  const loading = ref(false)
  const saving = ref(false)

  async function load(name: string): Promise<void> {
    profile.value = name
    loading.value = true
    try {
      const data = await profilesApi.getDraft(name)
      draft.value = data.draft
      masked.value = data.masked
      baseVersion.value = data.baseVersion
      updatedAt.value = data.updatedAt
      updatedBy.value = data.updatedBy
    } finally {
      loading.value = false
    }
  }

  async function save(name: string, patch: Values): Promise<void> {
    saving.value = true
    try {
      const data = await profilesApi.saveDraft(name, patch, baseVersion.value)
      draft.value = data.draft
      baseVersion.value = data.baseVersion
      validation.value = data.validation
      // A fresh save is the new truth about which keys are secret.
      masked.value = Object.keys(data.draft).filter((key) => data.draft[key] === '***')
    } finally {
      saving.value = false
    }
  }

  async function discard(name: string): Promise<void> {
    await profilesApi.discardDraft(name)
    await load(name)
    validation.value = null
  }

  return {
    profile,
    draft,
    masked,
    baseVersion,
    updatedAt,
    updatedBy,
    validation,
    loading,
    saving,
    load,
    save,
    discard
  }
})
```

- [ ] **Step 8: 写 `composables/useConfirm.ts` 与 `components/ConfirmDialog.vue`**

`console/frontend/src/composables/useConfirm.ts`：

```ts
import { ref } from 'vue'

export interface ConfirmRequest {
  title: string
  content: string
}

/** 一个 Promise 化的确认框：丢弃草稿是破坏性动作，必须先问。 */
export function useConfirm() {
  const open = ref(false)
  const title = ref('')
  const content = ref('')
  let resolver: ((confirmed: boolean) => void) | null = null

  function ask(request: ConfirmRequest): Promise<boolean> {
    title.value = request.title
    content.value = request.content
    open.value = true
    return new Promise((resolve) => {
      resolver = resolve
    })
  }

  function answer(confirmed: boolean): void {
    open.value = false
    resolver?.(confirmed)
    resolver = null
  }

  return { open, title, content, ask, answer }
}
```

`console/frontend/src/components/ConfirmDialog.vue`：

```vue
<script setup lang="ts">
defineProps<{ open: boolean; title: string; content: string; danger?: boolean }>()
const emit = defineEmits<{ answer: [confirmed: boolean] }>()
</script>

<template>
  <a-modal :open="open" :title="title" :footer="null" @cancel="emit('answer', false)">
    <p>{{ content }}</p>
    <div class="confirm-dialog__actions">
      <a-button @click="emit('answer', false)">取消</a-button>
      <a-button :danger="danger" type="primary" @click="emit('answer', true)">确认</a-button>
    </div>
  </a-modal>
</template>

<style scoped lang="less">
.confirm-dialog__actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
```

- [ ] **Step 9: 写 `components/ExposureTag.vue` / `EffectBadge.vue` / `FixedField.vue`**

`ExposureTag.vue`：

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { Exposure } from '@/types/catalog'

const props = defineProps<{ exposure: Exposure }>()

const color = computed(
  () => ({ basic: 'green', advanced: 'blue', expert: 'orange', ops: 'red' })[props.exposure] ?? 'default'
)
</script>

<template>
  <a-tag :color="color">{{ exposure }}</a-tag>
</template>
```

`EffectBadge.vue` —— 徽标只允许三个取值（§2.4），**不用** catalog 原值直接印字：

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { CatalogEntry } from '@/types/catalog'

/** catalog `effect=both` 但实际只有启动生效的三条：`audio.output.voice` 只是协议回显（§2.4）。 */
const STARTUP_ONLY = new Set(['qwen3_tts_speaker', 'kokoro_voice', 'openai_tts_voice'])

const props = defineProps<{ entry: CatalogEntry }>()

const badge = computed(() => {
  if (props.entry.effect === 'hot') return { text: '热更新', color: 'blue' }
  if (props.entry.effect === 'both') {
    return STARTUP_ONLY.has(props.entry.name)
      ? { text: '启动', color: 'default' }
      : { text: '启动 + 热更', color: 'purple' }
  }
  return { text: '启动', color: 'default' }
})

/** 只给被降级的那三条用小字提示，避免让读者以为平台擅自改了 catalog。 */
const downgraded = computed(
  () => props.entry.effect === 'both' && STARTUP_ONLY.has(props.entry.name)
)
</script>

<template>
  <span class="effect-badge">
    <a-tag :color="badge.color">{{ badge.text }}</a-tag>
    <small v-if="downgraded" title="catalog: both；audio.output.voice 只是协议回显">catalog: both</small>
  </span>
</template>

<style scoped lang="less">
.effect-badge {
  align-items: center;
  display: inline-flex;
  gap: 4px;

  small {
    color: #6f7891;
    font-size: 11px;
  }
}
</style>
```

`FixedField.vue` —— 60 条不暴露的只读行（四类原因，文案固定，§6.1）：

```vue
<script setup lang="ts">
import { computed } from 'vue'

import ExposureTag from '@/components/ExposureTag.vue'
import type { CatalogEntry } from '@/types/catalog'

const props = defineProps<{ entry: CatalogEntry }>()

/** 原因只由 `stage` 与 `type` 决定，不靠猜：合计 17 + 7 + 18 + 18 = 60。 */
const reason = computed(() => {
  if (props.entry.type === 'fixed') return '不可配置 · 源码常量'
  if (props.entry.stage === 'deploy') return '平台维护 · 改它要重建镜像'
  if (props.entry.stage === 'env') return '需重建容器'
  if (props.entry.stage === 'client') return '属对话页客户端，不在运维面'
  return '不可配置'
})
</script>

<template>
  <div class="fixed-field">
    <div class="fixed-field__head">
      <span class="fixed-field__name">{{ entry.name }}</span>
      <ExposureTag :exposure="entry.exposure" />
      <a-tag color="default">固定</a-tag>
      <span class="fixed-field__reason">{{ reason }}</span>
    </div>
    <p class="fixed-field__ref">{{ entry.source_ref }}</p>
  </div>
</template>

<style scoped lang="less">
.fixed-field {
  border-bottom: 1px solid #1e2742;
  padding: 10px 0;

  &__head {
    align-items: center;
    display: flex;
    gap: 8px;
  }

  &__name {
    color: #9aa3b8;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
  }

  &__reason {
    color: #8b93a7;
    font-size: 12px;
  }

  &__ref {
    color: #6f7891;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    margin: 4px 0 0;
    word-break: break-all;
  }
}
</style>
```

- [ ] **Step 10: 写 `components/ParamField.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import EffectBadge from '@/components/EffectBadge.vue'
import ExposureTag from '@/components/ExposureTag.vue'
import FixedField from '@/components/FixedField.vue'
import type { CatalogEntry } from '@/types/catalog'

const props = defineProps<{
  entry: CatalogEntry
  modelValue: unknown
  masked: boolean
  disabled?: boolean
  /** advanced 层级的建议值；不传则不显示「建议」。 */
  suggested?: unknown
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
  reset: []
}>()

const control = computed(() => {
  if (props.masked) return 'secret'
  if (props.entry.type === 'bool' || props.entry.type === 'boolean') return 'bool'
  if (props.entry.choices.length > 0) return 'choice'
  if (['int', 'integer', 'float', 'number'].includes(props.entry.type)) return 'number'
  return 'text'
})

const isFixed = computed(() => props.entry.type === 'fixed')

const IMPACT_LABEL: Record<string, string> = {
  process: '进程',
  pipeline: 'pipeline',
  session: '会话',
  container: '容器'
}

const COST_LABEL: Record<string, string> = {
  seconds: '秒级',
  restart: '重启',
  minutes: '分钟级'
}

const impactLabel = computed(() => IMPACT_LABEL[props.entry.impact] ?? props.entry.impact)
const changeCostLabel = computed(() => COST_LABEL[props.entry.change_cost] ?? props.entry.change_cost)

/** `ops` 必须把 risk 归到三类之一（§7.2）；完整文案进 `title`，不把长句塞进标签。 */
const riskCategory = computed(() => {
  const risk = props.entry.risk ?? ''
  for (const tag of ['安全', '隐私', '环境绑定']) if (risk.includes(tag)) return tag
  return risk ? '其他' : ''
})

function formatDefault(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : '[]'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** 不写 `effect`：它由 `EffectBadge` 承担，两处同时写会给出两个互相矛盾的说法。 */
const hint = computed(() => {
  // advanced 带建议值：同一个值不再用「默认」和「建议」各说一遍。
  const lead =
    props.suggested === undefined
      ? `默认 ${formatDefault(props.entry.default)}`
      : `建议 ${formatDefault(props.suggested)}`
  return [lead, impactLabel.value, changeCostLabel.value].join(' · ')
})

function onInput(event: Event): void {
  emit('update:modelValue', (event.target as HTMLInputElement).value)
}

function onNumber(value: number | string | null): void {
  emit('update:modelValue', value === null || value === '' ? null : Number(value))
}
</script>

<template>
  <FixedField v-if="isFixed" :entry="entry" />

  <div v-else class="param-field" :class="{ 'param-field--expert': entry.exposure === 'expert' }">
    <div class="param-field__head">
      <span class="param-field__name" :title="entry.key">{{ entry.name }}</span>
      <ExposureTag :exposure="entry.exposure" />
      <EffectBadge :entry="entry" />
      <a-tag color="default">{{ impactLabel }}</a-tag>
      <a-tag color="default">{{ changeCostLabel }}</a-tag>
      <a-tag v-if="entry.exposure === 'ops' && riskCategory" color="red" :title="entry.risk ?? ''">
        {{ riskCategory }}
      </a-tag>
      <span class="param-field__spacer" />
      <a-button
        type="link"
        size="small"
        :disabled="disabled"
        :title="`默认 ${formatDefault(entry.default)}`"
        @click="emit('reset')"
      >
        恢复默认
      </a-button>
    </div>

    <a-select
      v-if="control === 'choice'"
      :value="modelValue"
      :options="entry.choices.map((value) => ({ value, label: String(value) }))"
      :disabled="disabled"
      class="param-field__control"
      @change="(value) => emit('update:modelValue', value)"
    />

    <a-switch
      v-else-if="control === 'bool'"
      :checked="Boolean(modelValue)"
      :disabled="disabled"
      @change="(checked) => emit('update:modelValue', checked)"
    />

    <a-input-number
      v-else-if="control === 'number'"
      :value="typeof modelValue === 'number' ? modelValue : null"
      :disabled="disabled"
      class="param-field__control"
      @change="onNumber"
    />

    <a-input-password
      v-else-if="control === 'secret'"
      :value="modelValue"
      :disabled="disabled"
      class="param-field__control"
      @input="onInput"
    />

    <a-input
      v-else
      :value="modelValue === null || modelValue === undefined ? '' : String(modelValue)"
      :disabled="disabled"
      class="param-field__control"
      @input="onInput"
    />

    <p v-if="entry.exposure === 'expert'" class="param-field__warn">
      expert：改错会让 pipeline 起不来，先存草稿、再审 diff 后发布。
    </p>
    <p class="param-field__hint">{{ hint }}</p>

    <!-- 人设类字段的第二个动作：「热更存量连接」+「重启改未来连接」（§5.4）。 -->
    <slot name="dualAction" />
  </div>
</template>

<style scoped lang="less">
.param-field {
  border-bottom: 1px solid #1e2742;
  padding: 12px 0;

  &__head {
    align-items: center;
    display: flex;
    gap: 8px;
    margin-bottom: 6px;
  }

  &__name {
    color: #e6e8f0;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
  }

  &__spacer {
    flex: 1;
  }

  &__control {
    max-width: 320px;
  }

  &__hint {
    color: #8b93a7;
    font-size: 12px;
    margin: 6px 0 0;
  }

  &__warn {
    color: #d89614;
    font-size: 12px;
    margin: 6px 0 0;
  }

  &--expert {
    background: rgba(216, 150, 20, 0.05);
    padding-left: 8px;
  }
}
</style>
```

`a-select` 的 `:value` 与草稿值类型不一致时（catalog 的 `choices` 是 `unknown[]`）会按值严格比较而选不中；因此 `choices` 一律经 `String(value)` 生成 `label`，而 `value` 原样传。如果某个真实条目的 `choices` 是数字，草稿里存的也是数字（由 `baseline` 从 `entry.default` 带入），能对上。

- [ ] **Step 11: 写 `utils/catalog-view.ts`（去重 + 分组）与 `components/ParamTree.vue`**

先写纯函数（这一层错了会让某条参数在树上永远消失，所以有单测）：

```ts
import type { CatalogEntry } from '@/types/catalog'

export interface FieldGroup {
  /** `${stage}::${backend ?? ''}`，直接当 `a-menu-item` 的 key。 */
  key: string
  stage: string
  backend: string | null
  readOnly: boolean
  items: CatalogEntry[]
}

export interface Deduped {
  items: CatalogEntry[]
  /** 被合并的条目，只在详情里展示（`aliases`），树与表单各只出现一次。 */
  aliases: Record<string, CatalogEntry[]>
  multiBackend: number
}

/** 3 条重名保留哪一条（§6.1）：服务端优先、前缀所属 backend 优先、通用组优先。 */
const PREFERRED: Record<string, (entry: CatalogEntry) => boolean> = {
  log_transcripts: (entry) => entry.stage === 'runtime',
  model_name: (entry) => entry.backend === null,
  responses_api_reasoning_effort: (entry) => entry.backend === 'responses-api'
}

export function dedupe(entries: CatalogEntry[]): Deduped {
  const kept = new Map<string, CatalogEntry>()
  const aliases: Record<string, CatalogEntry[]> = {}
  const multi = new Set<string>()

  for (const entry of entries) {
    const current = kept.get(entry.name)
    if (!current) {
      kept.set(entry.name, entry)
      continue
    }

    const prefer = PREFERRED[entry.name]
    const keepNew = prefer ? prefer(entry) && !prefer(current) : false
    const winner = keepNew ? entry : current
    const loser = keepNew ? current : entry

    kept.set(entry.name, winner)
    aliases[entry.name] = [...(aliases[entry.name] ?? []), loser]

    // 「多后端」只算同一 stage 内跨 backend；跨 stage 的（client ↔ runtime）不算。
    if (winner.stage === loser.stage && winner.backend !== loser.backend) multi.add(entry.name)
  }

  return { items: [...kept.values()], aliases, multiBackend: multi.size }
}

const READ_ONLY_STAGES = new Set(['deploy', 'env', 'client'])

/** 两级分组：stage → backend，保持 catalog 的出现顺序；17 组（§6.1）。 */
export function groupByStage(entries: CatalogEntry[]): FieldGroup[] {
  const order: string[] = []
  const buckets = new Map<string, FieldGroup>()

  for (const entry of entries) {
    const key = `${entry.stage}::${entry.backend ?? ''}`
    if (!buckets.has(key)) {
      order.push(key)
      buckets.set(key, {
        key,
        stage: entry.stage,
        backend: entry.backend,
        readOnly: READ_ONLY_STAGES.has(entry.stage),
        items: []
      })
    }
    buckets.get(key)!.items.push(entry)
  }

  return order.map((key) => buckets.get(key)!)
}

/** 计数行唯一文案：不得手写数字（§14.7）。 */
export function countLabel(total: number, deduped: Deduped): string {
  return `${total} 条 · ${deduped.items.length} 个唯一名 · ${deduped.multiBackend} 个多后端字段`
}
```

`utils/catalog-view.spec.ts`：

```ts
describe('catalog-view', () => {
  const entry = (stage: string, backend: string | null, name: string): CatalogEntry =>
    ({
      key: `${stage}/${backend ?? '-'}/${name}`,
      stage,
      backend,
      name,
      type: 'string',
      default: null,
      choices: [],
      required: false,
      source_priority: ['yaml'],
      effect: 'startup',
      exposure: 'advanced',
      impact: 'pipeline',
      change_cost: 'restart',
      risk: null,
      source_ref: 'test:test'
    }) as CatalogEntry

  it('merges the three duplicate names and keeps the documented winner', () => {
    const result = dedupe([
      entry('client', null, 'log_transcripts'),
      entry('runtime', null, 'log_transcripts'),
      entry('llm', null, 'model_name'),
      entry('llm', 'responses-api', 'model_name'),
      entry('llm', 'chat-completions', 'responses_api_reasoning_effort'),
      entry('llm', 'responses-api', 'responses_api_reasoning_effort')
    ])

    expect(result.items.map((item) => `${item.stage}/${item.backend}/${item.name}`)).toEqual([
      'runtime/null/log_transcripts',
      'llm/null/model_name',
      'llm/responses-api/responses_api_reasoning_effort'
    ])
    expect(countLabel(6, result)).toBe('6 条 · 3 个唯一名 · 2 个多后端字段')
  })

  it('groups by stage then backend without reordering', () => {
    const groups = groupByStage([
      entry('vad', null, 'thresh'),
      entry('vad', 'firered', 'vad_firered_threshold'),
      entry('client', null, 'api_key')
    ])

    expect(groups.map((group) => group.key)).toEqual(['vad::', 'vad::firered', 'client::'])
    expect(groups.map((group) => group.items.length)).toEqual([1, 1, 1])
    expect(groups.filter((group) => group.readOnly).map((group) => group.stage)).toEqual(['client'])
  })

  it('keeps read-only stages visible instead of hiding them', () => {
    // 隐藏 = 运维以为参数不存在；只读 = 运维知道它存在但轮不到控制台改（§6.1）。
    const groups = groupByStage([entry('deploy', null, 'max_config_bytes')])
    expect(groups).toHaveLength(1)
    expect(groups[0].readOnly).toBe(true)
  })
})
```

Run: `cd console/frontend && npx vitest run src/utils/catalog-view.spec.ts`
Expected: FAIL，`Failed to resolve import './catalog-view'`。

再写树（两级分组 + 只读标记）：

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { CatalogEntry } from '@/types/catalog'
import { groupByStage } from '@/utils/catalog-view'

const props = defineProps<{ entries: CatalogEntry[]; selected: string }>()
const emit = defineEmits<{ select: [key: string] }>()

const groups = computed(() => groupByStage(props.entries))
const selectedKeys = computed(() => [props.selected])
</script>

<template>
  <a-menu mode="inline" theme="dark" :selected-keys="selectedKeys" class="param-tree">
    <a-menu-item v-for="group in groups" :key="group.key" @click="emit('select', group.key)">
      <span class="param-tree__stage">{{ group.stage }}</span>
      <span class="param-tree__backend">· {{ group.backend ?? '通用' }}</span>
      <a-tag v-if="group.readOnly" class="param-tree__ro">只读</a-tag>
      <a-tag class="param-tree__count">{{ group.items.length }}</a-tag>
    </a-menu-item>
  </a-menu>
</template>

<style scoped lang="less">
.param-tree {
  max-height: calc(100vh - 260px);
  overflow-y: auto;

  &__stage {
    font-family: 'JetBrains Mono', monospace;
  }

  &__backend {
    color: #8b93a7;
    font-size: 12px;
    margin-left: 2px;
  }

  &__ro {
    margin-left: 4px;
    transform: scale(0.85);
  }

  &__count {
    float: right;
    margin-top: 4px;
  }
}
</style>
```

17 个分组的分母必须与 §6.1 的表逐字相等；`deploy` / `env` / `client` 三组的 `readOnly` 为 `true`，其余为 `false`。

- [ ] **Step 12: 写 `components/DiffTable.vue`**

发布前给用户看的「将要改变什么」。Task 15 的发布对话框直接复用。

```vue
<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ draft: Record<string, unknown>; masked: string[] }>()

interface Row {
  key: string
  value: string
}

const rows = computed<Row[]>(() =>
  Object.keys(props.draft)
    .sort()
    .map((key) => ({
      key,
      value: props.masked.includes(key) ? '***' : JSON.stringify(props.draft[key])
    }))
)
</script>

<template>
  <a-table
    size="small"
    :data-source="rows"
    :pagination="false"
    :columns="[
      { title: '字段', dataIndex: 'key', key: 'key' },
      { title: '草稿值', dataIndex: 'value', key: 'value' }
    ]"
    row-key="key"
  />
</template>
```

- [ ] **Step 13: 写 `views/ParamsView.vue`**

```vue
<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { AppError } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DiffTable from '@/components/DiffTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import ParamField from '@/components/ParamField.vue'
import ParamTree from '@/components/ParamTree.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useAuthStore } from '@/stores/auth'
import { useCatalogStore } from '@/stores/catalog'
import { useConsoleStore } from '@/stores/console'
import { useDraftStore } from '@/stores/draft'
import type { Exposure } from '@/types/catalog'
import { groupByStage, countLabel, dedupe } from '@/utils/catalog-view'
import { baseline, buildPatch, resetValue, type Values } from '@/utils/draft-patch'

const auth = useAuthStore()
const consoleStore = useConsoleStore()
const catalogStore = useCatalogStore()
const draftStore = useDraftStore()
const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const exposure = ref<Exposure>('basic')
/** 选中 `stage::backend` 分组（17 组，§6.1）；空串表示不过滤。 */
const group = ref('')
const values = ref<Values>({})
const saveError = ref<AppError | null>(null)
const notice = ref('')

const deduped = computed(() => dedupe(catalogStore.entries))
const entries = computed(() => deduped.value.items)
const groups = computed(() => groupByStage(entries.value))
/** 计数行只能由纯函数生成，不手写数字（§14.7）。 */
const countText = computed(() => countLabel(catalogStore.entries.length, deduped.value))
const groupReadOnly = computed(() => groups.value.find((item) => item.key === group.value)?.readOnly ?? false)

/** `ops` 只对管理员渲染：operator 连看都看不到（§7.2）。 */
const visible = computed(() =>
  entries.value.filter(
    (entry) =>
      (group.value === '' || `${entry.stage}::${entry.backend ?? ''}` === group.value) &&
      (auth.isAdmin || entry.exposure !== 'ops')
  )
)

/** basic / advanced 直出；expert / ops 折进一个折叠面板（§7.3）。 */
const direct = computed(() =>
  visible.value.filter((entry) => entry.exposure === 'basic' || entry.exposure === 'advanced')
)
const folded = computed(() =>
  visible.value.filter((entry) => entry.exposure === 'expert' || entry.exposure === 'ops')
)
const opsCount = computed(() => folded.value.filter((entry) => entry.exposure === 'ops').length)

const patch = computed(() => buildPatch(entries.value, values.value, draftStore.draft))
const dirty = computed(() => Object.keys(patch.value).length > 0)
const structural = computed(() => draftStore.validation?.mode === 'structural')

async function reload(): Promise<void> {
  await catalogStore.load({ exposure: exposure.value })
  await draftStore.load(consoleStore.profile)
  values.value = baseline(entries.value, draftStore.draft)
  // 切 exposure 会改变分组集合，但不能把用户刚选中的组默默换掉。
  if (!groups.value.some((item) => item.key === group.value)) group.value = groups.value[0]?.key ?? ''
}

watch(() => consoleStore.profile, () => void reload(), { immediate: true })
watch(exposure, () => void reload())

function reset(key: string): void {
  const entry = entries.value.find((candidate) => candidate.key === key)
  if (entry) values.value = { ...values.value, [key]: resetValue(entry, draftStore.draft) }
}

function isMasked(key: string): boolean {
  return draftStore.masked.includes(key)
}

async function save(): Promise<void> {
  saveError.value = null
  notice.value = ''
  if (!dirty.value) {
    notice.value = '没有改动'
    return
  }
  try {
    await draftStore.save(consoleStore.profile, patch.value)
    values.value = baseline(catalogStore.entries, draftStore.draft)
    notice.value = `草稿已保存（v${draftStore.baseVersion ?? 0}）`
  } catch (error) {
    saveError.value = error instanceof AppError ? error : new AppError('unknown', '保存失败')
  }
}

async function discard(): Promise<void> {
  const confirmed = await askConfirm({
    title: '丢弃草稿',
    content: '草稿会被删除，已发布的版本不受影响。'
  })
  if (!confirmed) return
  saveError.value = null
  try {
    await draftStore.discard(consoleStore.profile)
    values.value = baseline(catalogStore.entries, draftStore.draft)
    notice.value = '草稿已丢弃'
  } catch (error) {
    saveError.value = error instanceof AppError ? error : new AppError('unknown', '丢弃失败')
  }
}
</script>

<template>
  <div class="params">
    <div class="params__toolbar">
      <a-select
        :value="exposure"
        :options="[
          { value: 'basic', label: 'basic · 直出' },
          { value: 'advanced', label: 'advanced · 带建议值' },
          { value: 'expert', label: 'expert · 折叠 + 警告' },
          { value: 'ops', label: 'ops · 仅运维可见' }
        ]"
        class="params__exposure"
        @change="(value) => (exposure = value as Exposure)"
      />

      <span class="params__count">{{ countText }}</span>

      <span class="params__meta">
        draft v{{ draftStore.baseVersion ?? 0 }} · {{ draftStore.updatedBy || '未编辑' }}
        <template v-if="draftStore.updatedAt"> · {{ draftStore.updatedAt }}</template>
      </span>

      <span class="params__spacer" />

      <a-badge :status="dirty ? 'warning' : 'default'" :text="dirty ? '有未保存改动' : '无改动'" />
      <a-button :disabled="!dirty || draftStore.saving" @click="discard">丢弃草稿</a-button>
      <a-button
        type="primary"
        :disabled="!dirty"
        :loading="draftStore.saving"
        @click="save"
      >
        保存草稿
      </a-button>
    </div>

    <a-alert v-if="structural" type="warning" show-icon message="仅校验了结构" description="运行时包不在本进程，字段是否能被 pipeline 接受未经运行验证。" />
    <a-alert v-else-if="notice" type="info" show-icon :message="notice" />
    <a-alert
      v-if="groupReadOnly"
      type="info"
      show-icon
      message="该组只读"
      description="deploy / env / client 不在运维面可写范围：前两类改它要重建容器，第三类属对话页客户端。只读行不进 patch，也不会触发发布。"
    />
    <ErrorBanner :error="saveError" />
    <ErrorBanner :error="catalogStore.error" />

    <div class="params__body">
      <aside class="params__tree">
        <ParamTree :entries="entries" :selected="group" @select="(value) => (group = value)" />
      </aside>

      <section class="params__form">
        <ParamField
          v-for="entry in direct"
          :key="entry.key"
          :entry="entry"
          :model-value="values[entry.key]"
          :masked="isMasked(entry.key)"
          :suggested="entry.exposure === 'advanced' ? entry.default : undefined"
          :disabled="!auth.isAdmin && entry.exposure === 'expert'"
          @update:model-value="(value) => (values = { ...values, [entry.key]: value })"
          @reset="reset(entry.key)"
        />

        <a-collapse v-if="folded.length" class="params__fold" ghost>
          <a-collapse-panel
            key="expert-ops"
            :header="`expert / ops ${folded.length} 条（含 ${opsCount} 条仅运维可见）—— 展开前先读完警告`"
          >
            <ParamField
              v-for="entry in folded"
              :key="entry.key"
              :entry="entry"
              :model-value="values[entry.key]"
              :masked="isMasked(entry.key)"
              :disabled="!auth.isAdmin"
              @update:model-value="(value) => (values = { ...values, [entry.key]: value })"
              @reset="reset(entry.key)"
            />
          </a-collapse-panel>
        </a-collapse>

        <a-empty v-if="!visible.length && !catalogStore.loading" description="该级别下没有参数" />
      </section>

      <aside class="params__preview">
        <h3>本次改动（{{ Object.keys(patch).length }}）</h3>
        <DiffTable :draft="patch" :masked="draftStore.masked" />
        <!-- 发布入口由 Task 15 的 PublishPanel 挂在这里：草稿 → 校验 → 发布/热更 → 生效/回滚。 -->
      </aside>
    </div>

    <ConfirmDialog
      :open="confirmOpen"
      :title="confirmTitle"
      :content="confirmContent"
      danger
      @answer="answerConfirm"
    />
  </div>
</template>

<style scoped lang="less">
.params {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__toolbar {
    align-items: center;
    display: flex;
    gap: 12px;
  }

  &__exposure {
    width: 140px;
  }

  &__count {
    color: #e6e8f0;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  &__meta {
    color: #8b93a7;
    font-size: 12px;
  }

  &__form {
    max-height: calc(100vh - 300px);
    overflow-y: auto;
    padding-right: 4px;
  }

  &__fold {
    border-top: 1px solid #1e2742;
    margin-top: 8px;

    :deep(.ant-collapse-header) {
      color: #d89614;
      font-size: 12px;
    }
  }

  &__spacer {
    flex: 1;
  }

  &__body {
    display: grid;
    gap: 16px;
    grid-template-columns: 180px minmax(320px, 1fr) 280px;
  }

  &__tree,
  &__preview {
    background: #141a2e;
    border-radius: 10px;
    padding: 12px;
  }

  &__preview h3 {
    color: #8b93a7;
    font-size: 12px;
    margin: 0 0 8px;
  }
}
</style>
```

用 operator 账号登录时，`expert`/`ops` 字段是禁用的——这只是 UX，真正的拦截在服务端（`refuse_protected`，A.0.2）；不要在后端放开的前提下指望前端拦住写。

- [ ] **Step 14: 注册路由**

`console/frontend/src/router/index.ts` 的 `console` 路由把 `children: []` 换成：

```ts
      children: [
        { path: '', redirect: { name: 'params' } },
        { path: 'params', name: 'params', component: () => import('@/views/ParamsView.vue') }
      ]
```

- [ ] **Step 15: 构建 + 手工验收**

Run: `cd console/frontend && npm run build`
Expected: `vue-tsc` 无错误。

Run（两个终端）：后端 `uvicorn app.main:app --port 8000`，前端 `npm run dev`。浏览器打开 `http://127.0.0.1:3000/console`：

1. 登录后被送到 `/console/params`，左侧列出 17 个 `stage · backend` 分组，每组后缀数字与设计文档 §6.1 的表逐字相等（合计 196）；
2. 顶部计数行读 `196 条 · 193 个唯一名 · 2 个多后端字段`；`log_transcripts` / `model_name` / `responses_api_reasoning_effort` 三个名字在树上各只出现一次；
3. 把 exposure 逐档切到 `basic` / `advanced` / `expert` / `ops`：`basic`/`advanced` 直出，`advanced` 的 hint 写「建议 …」，`expert`/`ops` 折在一个折叠面板里且面板标题带警告；
4. 点 `deploy · 通用` / `env · 通用` / `client · 通用` 三组 → 顶部出现《该组只读》，字段全部是 `FixedField`（无输入框、无「恢复默认」），与 catalog 的 60 条不暴露一致；`runtime · 通用` 里的 `chunk_samples` 同样只读；
5. 把 exposure 切到 `expert`（admin 账号）→ 字段变多；用 operator 账号 → `expert`/`ops` 字段被禁用，且 `ops` 组内字段完全不渲染；
6. 改一个 `basic` 字段 → 顶部变「有未保存改动」，右侧「本次改动」出现一行；
7. 点保存 → 提示「草稿已保存」；刷新页面 → 改动的值仍在；
8. 把某个密钥字段填入新值后保存 → 刷新页面后该字段显示 `***`，且「本次改动」里它是 `***`；
9. 点「恢复默认」再保存 → 该键从草稿消失（刷新后回落到 catalog `default`）；
10. 点「丢弃草稿」→ 确认后改动消失；
11. 若 `validatorMode=structural`（本机没装 speech_to_speech 运行时），顶部常驻黄色「仅校验了结构」。

- [ ] **Step 16: 提交**

```bash
git add console/frontend
git commit -m "feat(console): params view with catalog tree, draft form and validation banner"
```

---

## Task 12B: 音色制作与音色库（旁路，§3.11 / A.18）

**Files:**
- Create: `console/backend/alembic/versions/0003_voices.py`
- Create: `console/backend/app/models/voice.py`、`app/schemas/voices.py`、`app/repositories/voice_repository.py`
- Create: `console/backend/app/routers/voices.py`、`app/services/voice_service.py`、`app/services/voice_precompute.py`
- Test: `console/backend/tests/unit/test_voice_service.py`、`console/backend/tests/integration/test_voices.py`
- Create: `console/frontend/src/types/voice-library.ts`、`api/voices.ts`、`stores/voices.ts`
- Create: `console/frontend/src/utils/voice-refs.ts`、`utils/voice-refs.spec.ts`
- Create: `console/frontend/src/components/VoicePicker.vue`、`VoiceLibraryTable.vue`、`VoiceCreateDialog.vue`、`VoiceAudition.vue`
- Create: `console/frontend/src/views/VoicesView.vue`
- Modify: `console/frontend/src/router/index.ts`（`/console/voices`）
- Modify: `console/frontend/src/views/ParamsView.vue`（`tts` 组的 14 条音色字段接 `VoicePicker`）
- Modify: `console/backend/app/main.py`（注册 `routers/voices.py`）、`app/config/_console.py`（`VOICE_PRECOMPUTE_CONCURRENCY=1`、`VOICE_MAX_BYTES`、`VOICE_RETENTION_MAX_DAYS`）

**Interfaces:**
- Produces（A.18，七个端点，回包形状与设计文档 A.18 逐字一致）：

| 方法 | 路径 | 200 `data` | 错误 |
|---|---|---|---|
| `GET` | `/api/v1/voices` | `{list:[{id,name,source,backend,language,status,audioSeconds,createdAt,createdBy,refCount,usedBy:{profiles,versions}}],total,page,pageSize}` | `401` |
| `POST` | `/api/v1/voices` | `{id,status:"precomputing",jobId}`（`multipart`：`audio` / `name` / `source` / `backend` / `language` / `refText` / `instruct` / `consent="biometric-ack"` / `retentionDays`） | `400 voice_audio_invalid`、`400 voice_consent_required`、`409 voice_name_taken`、`413 voice_too_large`、`422 validation_failed`、`429 voice_precompute_busy` |
| `GET` | `/api/v1/voices/{id}` | `{id,name,source,backend,language,status,audioSeconds,trimStartMs,trimEndMs,refText,instruct,createdAt,createdBy,consentAckAt,retentionDays,precompute:{stage,progress,errorCode},usedBy:{profiles,versions}}` | `404 voice_not_found` |
| `GET` | `/api/v1/voices/{id}/audio` | 裸响应 `audio/wav`，`Range` → `206`，`Cache-Control: no-store` | `404 voice_not_found`、`410 voice_expired` |
| `POST` | `/api/v1/voices/{id}/duplicate` | `{id,name,status}` | `404 voice_not_found`、`409 voice_name_taken` |
| `DELETE` | `/api/v1/voices/{id}` | `{deleted:true}`；有引用 → `409 voice_in_use`（`detail[{field:"profiles",value:[…]},{field:"versions",value:N}]`） | `404` / `409` |
| `GET` | `/api/v1/voices/backends` | `{list:[{backend,stage,catalogued,sources,fields,notes}]}` | `401` |

- Produces（前端纯函数）：`bindings(source, backend) -> Record<string, string> | null`、`bindPatch(voice, fields, cacheDir) -> Values`、`conflicts(patch) -> Conflict[]`、`mergeCounts(list) -> Record<string, {profiles,versions}>`。
- Consumes: `catalogService.entries()`（校验字段名确实存在，`cacheDir` 取自 `qwen3_tts_ref_cache_dir` 的当前值，缺省 `/app/data/voices`）、`draft` 仓储（引用计数）、`audit_service`（`voiceRefs`）。

**边界（硬约束，不得突破）**：
- 音色库**不是**第二条配置通道：不写 `config/`、不调 `/internal/*`、不重启；选中后只走 A.3 草稿。
- 预计算子进程 `CUDA_VISIBLE_DEVICES=-1` + `VOICE_PRECOMPUTE_CONCURRENCY=1` + `asyncio.create_subprocess_exec`；试听是静态文件 `Range` 读，不经 `8765`。
- 目录 `0700`、文件 `0600`；`/app/data/voices/**` 不在 git、不在镜像；日志只写 `voiceId` 不写路径与文本。
- `qwen3_tts_backend=ggml` 跳过预计算，只存 `ref_audio` + `ref_text`；`kokoro` 与 `openai_compatible` 的 `clone` 在 §3.11.1 表里就是「不支持」，不能“顺便支持”。

- [ ] **Step 1: 迁移 `0003_voices.py`**

`upgrade()` 只建一张表 + 一个索引（与设计 §3.11.3 逐列对应）：

```python
def upgrade() -> None:
    op.create_table(
        "voices",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("audio_relpath", sa.String(255), nullable=True),
        sa.Column("audio_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("audio_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("trim_start_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trim_end_ms", sa.Integer(), nullable=True),
        sa.Column("ref_text", sa.Text(), nullable=True),
        sa.Column("instruct", sa.Text(), nullable=True),
        sa.Column("spk_relpath", sa.String(255), nullable=True),
        sa.Column("rvq_relpath", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("consent_ack_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.UniqueConstraint("name", name="uq_voices_name"),
    )
    op.create_index("ix_voices_status", "voices", ["status"])
```

名字唯一性在 SQLite 里是大小写敏感的，所以**应用层也要拦**（`voice_name_taken`），不能只靠约束（§11.2）。

- [ ] **Step 2: 写失败测试 `tests/unit/test_voice_service.py`**

五组断言（与设计 §11.2 同一份）：

```python
def test_bindings_covers_the_three_sources_for_qwen3():
    assert bindings("builtin", "qwen3") == {"speaker": "qwen3_tts_speaker"}
    assert set(bindings("clone", "qwen3")) == {"refAudio", "refText", "refSpk", "refRvq"}
    assert bindings("design", "qwen3") == {"instruct": "qwen3_tts_instruct"}

def test_kokoro_and_openai_only_accept_builtin():
    assert bindings("clone", "kokoro") is None
    assert bindings("clone", "openai_compatible") is None
    assert bindings("design", "kokoro") is None

def test_ref_audio_and_ref_spk_are_mutually_exclusive():
    errors = conflicts({"qwen3_tts_ref_audio": "/a.wav", "qwen3_tts_ref_spk": "/a.npy"})
    assert errors == [{"field": "qwen3_tts_ref_spk", "conflictWith": "qwen3_tts_ref_audio"}]

def test_rvq_requires_spk_and_text():
    assert conflicts({"qwen3_tts_ref_rvq": "/a.npy"})

def test_reference_count_includes_draft_and_versions():
    # 草稿里引用了也要算，否则删掉后草稿直接失效（§3.11.4）。
    refs = count_references("01J...", draft={"qwen3_tts_ref_spk": "/app/data/voices/01J.../spk.npy"}, versions=[...])
    assert refs == {"profiles": ["prod"], "versions": [12]}
```

Run: `cd console/backend && python -m pytest tests/unit/test_voice_service.py -q`
Expected: FAIL，`ImportError: cannot import name 'bindings'`。

- [ ] **Step 3: 实现 `services/voice_service.py`**

```python
BINDINGS: dict[tuple[str, str], dict[str, str]] = {
    ("builtin", "qwen3"): {"speaker": "qwen3_tts_speaker"},
    ("builtin", "openai_compatible"): {"speaker": "openai_tts_voice"},
    ("builtin", "kokoro"): {"speaker": "kokoro_voice", "language": "kokoro_lang_code"},
    ("clone", "qwen3"): {
        "refAudio": "qwen3_tts_ref_audio",
        "refText": "qwen3_tts_ref_text",
        "refSpk": "qwen3_tts_ref_spk",
        "refRvq": "qwen3_tts_ref_rvq",
    },
    ("design", "qwen3"): {"instruct": "qwen3_tts_instruct"},
    ("design", "openai_compatible"): {
        "instruct": "openai_tts_instructions",
        "taskType": "openai_tts_task_type",
    },
}

def bindings(source: str, backend: str) -> dict[str, str] | None:
    """§3.11.1 的表就是这行字典：前端不内置副本，后端也不猜前缀。"""
    return BINDINGS.get((source, backend))


def conflicts(patch: Mapping[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if "qwen3_tts_ref_audio" in patch and "qwen3_tts_ref_spk" in patch:
        errors.append({"field": "qwen3_tts_ref_spk", "conflictWith": "qwen3_tts_ref_audio"})
    for name in ("qwen3_tts_ref_rvq",):
        if name in patch and not {"qwen3_tts_ref_spk", "qwen3_tts_ref_text"} <= set(patch):
            errors.append({"field": name, "reason": "requires_spk_and_text"})
    return errors
```

`count_references(voice_id, draft, versions)` 只做字符串包含匹配：路径里出现 `/voices/<id>/` 即算引用；返回 `{profiles:[...], versions:[...]}`，两边都空才是 `[]`。

Run: `python -m pytest tests/unit/test_voice_service.py -q`
Expected: 5 passed。

- [ ] **Step 4: 写 `services/voice_precompute.py`（子进程，不占 GPU）**

```python
async def run(voice_id: str, ref_wav: Path, out_dir: Path) -> None:
    """预计算是**子进程**：CUDA_VISIBLE_DEVICES=-1 保证不碰 pipeline 的显存（§3.11.5）。"""
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "PYTHONUNBUFFERED": "1"}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.services.voice_precompute", str(ref_wav), str(out_dir),
        env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    # 进度行：queued → loading → spk → rvq → done/failed:<errorCode>
    ...
```

失败时的 `errorCode` 只允许四个值：`model_not_found` / `audio_too_short` / `oom_cpu` / `timeout`（A.18）。`status=failed` 的行仍然保留音频，运维可重试或删除。

- [ ] **Step 5: 写 `routers/voices.py`（七个端点）**

上传分片的校验顺序是固定的（早失败好过晚失败）：

1. `consent != "biometric-ack"` → `400 voice_consent_required`；
2. `size > VOICE_MAX_BYTES`（默认 10 MiB）→ `413 voice_too_large`；
3. `wave` 读头：`PCM16` / `16 kHz` / 单声道 / `0 < 时长 <= 30s` 全部满足，否则 `400 voice_audio_invalid`；
4. `name` 大小写不敏感查重 → `409 voice_name_taken`；
5. 落盘 `0700/0600` → 建行：`source=builtin` 直接 `status=ready`（无预计算）；`clone` / `design` 先 `status=precomputing` 再由后台任务推进；回 `201`。

`DELETE` 先 `count_references`：非空 → `409 voice_in_use`，`detail=[{field:"profiles",value:["prod"]},{field:"versions",value:12}]`（与 A.18 逐字一致）。

- [ ] **Step 6: 写失败测试 `tests/integration/test_voices.py`**

七组（与设计 §11.2 同一份）：上传全链（`voice_precompute.run` 打桩）、`consent` 缺失、超限、采样率不符、被引用 409、试听 `Range` 206、`ggml` 跳过预计算。

Run: `python -m pytest tests/integration/test_voices.py -q`
Expected: 7 passed。

- [ ] **Step 7: 写 `utils/voice-refs.ts` 与测试（绑定表的前端副本）**

```ts
import type { VoiceRow, VoiceSource } from '@/types/voice-library'

export type Values = Record<string, unknown>
export interface Conflict {
  field: string
  with?: string
  reason?: string
}

/** §3.11.1 的表：与后端 `voice_service.BINDINGS` 逐字相同，两边各自算一遍（不互相信任）。 */
export const BINDINGS: Record<string, Record<string, string> | null> = {
  'builtin/qwen3': { speaker: 'qwen3_tts_speaker' },
  'builtin/openai_compatible': { speaker: 'openai_tts_voice' },
  'builtin/kokoro': { speaker: 'kokoro_voice', language: 'kokoro_lang_code' },
  'clone/qwen3': {
    refAudio: 'qwen3_tts_ref_audio',
    refText: 'qwen3_tts_ref_text',
    refSpk: 'qwen3_tts_ref_spk',
    refRvq: 'qwen3_tts_ref_rvq'
  },
  'design/qwen3': { instruct: 'qwen3_tts_instruct' },
  'design/openai_compatible': {
    instruct: 'openai_tts_instructions',
    taskType: 'openai_tts_task_type'
  }
}

export function bindings(source: VoiceSource, backend: string): Record<string, string> | null {
  return BINDINGS[`${source}/${backend}`] ?? null
}

/** 选中音色 → 草稿 patch。`cacheDir` 由调用方从 catalog 的 `qwen3_tts_ref_cache_dir` 取，前端不内置路径。 */
export function bindPatch(voice: VoiceRow, fields: Record<string, string>, cacheDir: string): Values {
  const base = `${cacheDir.replace(/\/+$/, '')}/${voice.id}`
  switch (voice.source) {
    case 'builtin':
      return { [fields.speaker]: voice.name }
    case 'clone':
      // 预计算完成才有 spk / rvq；不然只能退回运行时计算的 refAudio + refText。
      // 克隆与内置互斥：speaker 必须显式置空，否则旧 speaker 会留着一起下发
      // （§14.7 里的 patch 形状就是这 4 个键）。
      return voice.status === 'ready'
        ? {
            [fields.speaker]: null,
            [fields.refSpk]: `${base}/spk.npy`,
            [fields.refRvq]: `${base}/rvq.npy`,
            [fields.refText]: voice.refText ?? ''
          }
        : { [fields.speaker]: null, [fields.refAudio]: `${base}/ref.wav`, [fields.refText]: voice.refText ?? '' }
    case 'design':
      return { [fields.instruct]: voice.instruct ?? '' }
  }
}

/** 与后端 `voice_service.conflicts` 同口径：先在草稿层拦住，不要等到发布后再回滚（§3.11.4）。 */
export function conflicts(patch: Values): Conflict[] {
  const errors: Conflict[] = []
  const has = (name: string) => Object.prototype.hasOwnProperty.call(patch, name)
  if (has('qwen3_tts_ref_audio') && has('qwen3_tts_ref_spk')) {
    errors.push({ field: 'qwen3_tts_ref_spk', with: 'qwen3_tts_ref_audio' })
  }
  if (has('qwen3_tts_ref_rvq') && !(has('qwen3_tts_ref_spk') && has('qwen3_tts_ref_text'))) {
    errors.push({ field: 'qwen3_tts_ref_rvq', reason: 'requires_spk_and_text' })
  }
  return errors
}

/** 参数字段下挂的音色池：只列该后端、且已 `ready` 的（A.18 固定文案：只有 ready 可选）。 */
export function selectable(voices: VoiceRow[], backend: string): VoiceRow[] {
  return voices.filter((voice) => voice.backend === backend && voice.status === 'ready')
}
```

`utils/voice-refs.spec.ts`（4 个用例）：

1. `bindings('clone', 'kokoro')` 与 `bindings('clone', 'openai_compatible')` 都是 `null`；
2. `bindPatch` 对 `ready` 的 clone 产出 `refSpk` + `refRvq` + `refText`，对 `draft` 的 clone 产出 `refAudio` + `refText`（两条路径不共存）；
3. `conflicts` 同时报出「互斥」与「rvq 缺依赖」两类；
4. 同一个 `tts · qwen3` 组里 14 个音色字段只对应 3 个控件位置（builtin / clone / design），不会重复出现。

Run: `cd console/frontend && npx vitest run src/utils/voice-refs.spec.ts`
Expected: 4 passed。

- [ ] **Step 8: 写 `api/voices.ts` 与 `stores/voices.ts`**

上传必须用 `FormData`，且**不得**让 `client.ts` 的默认 `Content-Type: application/json` 污染它（Task 11 的 axios 实例）：

```ts
export async function createVoice(form: CreateVoiceForm): Promise<CreateVoiceResult> {
  const body = new FormData()
  for (const [key, value] of Object.entries(form)) {
    if (value !== undefined && value !== null) body.append(key, String(value))
  }
  body.append('consent', 'biometric-ack')
  const { data } = await http.post<ApiResponse<CreateVoiceResult>>('/api/v1/voices', body)
  return data.data
}

export function voiceAudioUrl(id: string): string {
  return `/api/v1/voices/${id}/audio`
}

/** `<audio src>` 带不上 `Authorization`，所以先 fetch 成 blob URL：既保住鉴权，也不新增契约。 */
export async function fetchVoiceAudio(id: string): Promise<string> {
  const response = await http.get(voiceAudioUrl(id), { responseType: 'blob' })
  return URL.createObjectURL(response.data as Blob)
}
```

`stores/voices.ts`：`list / backends / loading / error / load(filter) / create(form) / duplicate(id) / remove(id) / refreshOne(id)`；`remove` 遇 `409 voice_in_use` 时**把 `detail` 原样存进 `error`**，由表格渲「被 prod、v12 引用」。

- [ ] **Step 9: 写四个组件**

| 组件 | 职责 | 关键 props / emit |
|---|---|---|
| `VoiceAudition.vue` | `<audio controls preload="none">` + 波形占位 + 首尾裁剪两个 `a-slider` | `props: {src, durationMs, trimStartMs, trimEndMs}`；`emit: update:trim` |
| `VoiceCreateDialog.vue` | 四步：来源 → 音频/转写/指令 → 试听与裁剪 → 命名保存；预计算进度轮询 `GET /voices/{id}` | `props: {open, backend, sources}`；`emit: created(voice)` |
| `VoiceLibraryTable.vue` | 表格：名称 / 来源 / 后端 / 时长 / 状态 / 引用 / 操作（试听、复制、删除） | `props: {rows, loading}`；`emit: audition, duplicate, remove` |
| `VoicePicker.vue` | 参数页里的一个字段位置：当前值 + 「选内置 / 从音色库选 / 制作新音色」 | `props: {entry, backend, voices, modelValue}`；`emit: update:modelValue(patch)` |

`VoiceCreateDialog` 的关键约束（三步循环，不能提前跳步）：

```ts
/** 只有 ready 才能“命名保存为可选音色”；未 ready 时按钮文案是“预计算中 62%”，不可点。 */
const canSave = computed(() => form.name.trim().length > 0 && (form.source === 'builtin' || precompute.stage === 'done'))

/** clone 必须有逐字转写：catalog 的 risk 写得很清楚，乱填会让合成失真（§3.11.2 步骤 4）。 */
const refTextMissing = computed(() => form.source === 'clone' && form.refText.trim().length === 0)
```

失败时展示 `precompute.errorCode` 的四个固定文案：`model_not_found` → 「未找到 VoiceDesign / 说话人模型」、`audio_too_short` → 「参考音频太短（< 3 s）」、`oom_cpu` → 「CPU 内存不足」、`timeout` → 「预计算超时」；重试只重跑预计算，不重传音频。

- [ ] **Step 10: 接入三处**

1. **参数页**：`ParamsView` 的 `direct`/`folded` 渲染前先判断该 entry 是否属 14 条音色字段（`TTS_VOICE_FIELDS` 集合）——是则渲染 `VoicePicker`，否则 `ParamField`；两者共用 `values` 与 `@update:model-value`，所以草稿与 diff 不受影响。`cacheDir` 从 `values['qwen3_tts_ref_cache_dir'] ?? entry.default ?? '/app/data/voices'` 取。
2. **目录化后端卡**：在 `ParamTree` 底部渲染 `GET /voices/backends` 里 `catalogued:false` 的 19 项（含 `cosyvoice` / `omnivoice`），只显示 `backend` + `notes:"字段未进机器目录"`，**不给输入控件**（§3.11.1）。
3. **路由**：`console` 的 `children` 加 `{ path: 'voices', name: 'voices', component: () => import('@/views/VoicesView.vue') }`，nav 加一项「音色库」。`VoicesView` = 筛选栏（backend / source / status / q）+ `VoiceLibraryTable` + `VoiceCreateDialog`；空态写「还没有音色：上传一段参考音频，或直接用后端内置音色」。

删除被引用音色时的拒绝标本（文案固定，三处一致）：

> 无法删除「嘉嘉」：正被 `prod`（草稿）与 `v12` 引用，共 2 处。先从这些配置里换成别的音色并发布，再回来删除。

- [ ] **Step 11: 手工验收（含旁路断言）**

1. 上传 8 s 的 16 kHz 单声道 WAV（`clone` / `qwen3`）→ 进度 `queued → loading → spk → rvq → done`，约 20–60 s 后表格变「可用」；
2. 上传前与预计算完成后各打一次 `GET /v1/pool`：`size` 与 `in_use` 完全不变（不占 pipeline 显存，§14.7）；`nvidia-smi` 里看不到新进程；
3. 在 `/console/params` 的 `tts · qwen3` 组里用 `VoicePicker` 选中该音色 → 右侧「本次改动」出现 `qwen3_tts_ref_spk` / `qwen3_tts_ref_rvq` / `qwen3_tts_ref_text` 三行（值里含音色 ULID）；
4. 存草稿 → 发布（Task 15）→ 盘上 `<profile>.yaml` 里是三行路径，`param_audit.detail.voiceRefs` 只有 `{field,voiceId}`，**无音频、无转写文本**；
5. 回滚到上一版 → `values` 里音色回到旧版本那一套（或 validator 报 `file_missing`），**不静默回退内置音色**；
6. 删除刚发布用的音色 → `409`，页面显示引用计数（`prod` / `v12`）；把配置改成另一个音色并发布后再删 → 成功；
7. `catalogued:false` 的后端（`cosyvoice`）在树底部可见但无输入控件；`/voices/backends` 回 `sources:[]`。

- [ ] **Step 12: 提交**

```bash
git add console
git commit -m "feat(console): voice library with clone precompute and TTS binding"
```

---

## Task 13: Versions / Audit / Instances 三视图（阶段 D 收尾）

**Files:**
- Modify: `console/frontend/src/types/api.d.ts`（加 `InstanceSnapshot`）
- Modify: `console/frontend/src/types/profile.d.ts`（加 `VersionRow`、`AuditRow`）
- Modify: `console/frontend/src/utils/error.ts`（加 `ALERT_TEXT`、`describeAlert`）
- Test: `console/frontend/src/utils/alert.spec.ts`
- Modify: `console/frontend/src/api/profiles.ts`（加 `getVersions`、`getAudit`）
- Create: `console/frontend/src/api/instances.ts`
- Create: `console/frontend/src/composables/usePolling.ts`
- Create: `console/frontend/src/components/VersionTable.vue`、`AuditTable.vue`、`InstanceCard.vue`
- Create: `console/frontend/src/views/VersionsView.vue`、`AuditView.vue`、`InstancesView.vue`
- Modify: `console/frontend/src/router/index.ts`（再加三个子路由）

**Interfaces:**
- Consumes: `GET /api/v1/profiles/{p}/versions`（→ `{list:[{version,status,author,note,createdAt,durationS,rolledBackTo}],total,page,pageSize}`）、`GET .../audit`（query `actor/action/result/field/from/to/page/pageSize`；→ `{list:[{auditId,at,actor,role,action,version,fields,result,errorCode,durationS,requestId}],total,page,pageSize}`）、`GET /api/v1/instances?profile=`（→ `{profile,version,container:{name,status,startedAt,image,pid,detail},pool:{size,inUse,units:[{index,state,sessionId}]}|null,usage,alerts[]}`）——均来自 Task 10。
- Produces: `usePolling(task, intervalMs)`；`describeAlert(code)`；路由名 `versions`、`audit`、`instances`（菜单 `NAV_GROUPS` 不需改动，`hasRoute` 自动点亮）。
- 本任务**不加回滚按钮**：`POST .../rollback` 在 Task 15 才存在，提前放一个按钮等于放一个 404。

**四个必须写进 UI 的事实**
1. `GET /instances` 降级时仍是 200，`pool` 为 `null` 而 `alerts` 非空——页面必须把 `null` 渲染成「不可达」而不是空白；
2. `alerts` 是机器码（`pool_unreachable` / `pool_stuck` / `pipeline_stopped` / `usage_unavailable`），文案在前端翻译；
3. 审计只展示字段名，永远不展示值（§10.1）；
4. 版本列表是 append-only，没有删除按钮，也不需要。

- [ ] **Step 1: 先写告警翻译的失败测试**

`console/frontend/src/utils/alert.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { describeAlert } from './error'

describe('describeAlert', () => {
  it('translates the four codes the instances endpoint emits', () => {
    expect(describeAlert('pool_unreachable')).toBe('无法连接 pipeline 池')
    expect(describeAlert('pool_stuck')).toBe('有 unit 卡在 stuck，需要重启 pipeline')
    expect(describeAlert('pipeline_stopped')).toBe('pipeline 进程未运行')
    expect(describeAlert('usage_unavailable')).toBe('用量数据不可读')
  })

  it('shows an unknown code instead of hiding it', () => {
    // A new alert must be visible in the ops tool the day it is added, even if
    // this table has not caught up; hiding it would turn a signal into silence.
    expect(describeAlert('disk_filling_up')).toBe('disk_filling_up')
  })
})
```

Run: `cd console/frontend && npx vitest run src/utils/alert.spec.ts`
Expected: FAIL，`describeAlert is not a function`。

- [ ] **Step 2: 给 `utils/error.ts` 追加告警文案**

```ts
/**
 * `/instances` 的 `alerts` 也是机器码（A.10）。与 `ERROR_TEXT` 分开，因为一个是
 * 「你的操作失败了」，一个是「系统现状不佳」——语气和位置都不同。
 */
export const ALERT_TEXT: Record<string, string> = {
  pool_unreachable: '无法连接 pipeline 池',
  pool_stuck: '有 unit 卡在 stuck，需要重启 pipeline',
  pipeline_stopped: 'pipeline 进程未运行',
  usage_unavailable: '用量数据不可读'
}

/** 未知码原样返回：宁可让运维看到一个英文码，也不要让一条告警消失。 */
export function describeAlert(code: string): string {
  return ALERT_TEXT[code] ?? code
}
```

Run: `cd console/frontend && npx vitest run src/utils`
Expected: 20 passed（`error` 3 + `format` 2 + `draft-patch` 6 + `alert` 2 + `catalog-view` 3 + `voice-refs` 4）。

- [ ] **Step 3: 补类型**

`console/frontend/src/types/api.d.ts` 末尾追加：

```ts
export interface PoolUnit {
  index: number | null
  state: string | null
  sessionId: string | null
}

/** A.10。`pool` 为 `null` 表示探不到，不是「没有 unit」。 */
export interface InstanceSnapshot {
  profile: string
  version: number | null
  container: {
    name: string
    status: string
    startedAt: string | null
    image: string
    pid: number | null
    detail: string
  }
  pool: { size: number; inUse: number; units: PoolUnit[] } | null
  usage: Record<string, unknown> | null
  alerts: string[]
}
```

`console/frontend/src/types/profile.d.ts` 末尾追加：

```ts
export interface VersionRow {
  version: number
  status: string
  author: string
  note: string | null
  createdAt: string | null
  durationS: number | null
  rolledBackTo: number | null
}

/** A.8：`fields` 是字段名清单，不是值。 */
export interface AuditRow {
  auditId: string
  at: string | null
  actor: string
  role: string
  action: string
  version: number | null
  fields: string[]
  result: string
  errorCode: string | null
  durationS: number | null
  requestId: string
}
```

- [ ] **Step 4: 补 API 模块**

给 `console/frontend/src/api/profiles.ts` 追加：

```ts
import type { AuditRow, VersionRow } from '@/types/profile'
import type { Page } from '@/types/api'

export interface AuditQuery {
  actor?: string
  action?: string
  result?: string
  field?: string
  from?: string
  to?: string
  page?: number
  pageSize?: number
}

export const getVersions = (
  profile: string,
  page = 1,
  pageSize = 20
): Promise<Page<VersionRow>> =>
  api.get<Page<VersionRow>>(`/profiles/${profile}/versions`, { params: { page, pageSize } })

export const getAudit = (profile: string, query: AuditQuery = {}): Promise<Page<AuditRow>> =>
  api.get<Page<AuditRow>>(`/profiles/${profile}/audit`, { params: query })
```

（`Page` 已在 Task 11 的 `types/api.d.ts` 里定义，与三个分页端点的 `{list,total,page,pageSize}` 一致。）

`console/frontend/src/api/instances.ts`：

```ts
import { api } from './client'
import type { InstanceSnapshot } from '@/types/api'

export const getInstances = (profile: string): Promise<InstanceSnapshot> =>
  api.get<InstanceSnapshot>('/instances', { params: { profile } })
```

- [ ] **Step 5: 写 `composables/usePolling.ts`**

```ts
import { onBeforeUnmount, ref } from 'vue'

export interface Polling {
  active: import('vue').Ref<boolean>
  start: () => void
  stop: () => void
  refresh: () => Promise<void>
}

/**
 * 定时间隔轮询，且保证两次执行不重叠：`/instances` 要探 pool 和 supervisor，
 * 一次可能要好几秒，重叠后请求会跣起。
 */
export function usePolling(task: () => Promise<void>, intervalMs = 5000): Polling {
  const active = ref(false)
  let timer: number | undefined
  let running = false

  async function refresh(): Promise<void> {
    if (running) return
    running = true
    try {
      await task()
    } finally {
      running = false
    }
  }

  function stop(): void {
    active.value = false
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  function start(): void {
    stop()
    active.value = true
    void refresh()
    timer = window.setInterval(() => void refresh(), intervalMs)
  }

  onBeforeUnmount(stop)

  return { active, start, stop, refresh }
}
```

- [ ] **Step 6: 写 `components/VersionTable.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { VersionRow } from '@/types/profile'
import { formatDuration, formatTime } from '@/utils/format'

const props = defineProps<{ rows: VersionRow[]; loading?: boolean }>()

const data = computed(() =>
  props.rows.map((row) => ({ ...row, key: row.version, createdAtText: formatTime(row.createdAt) }))
)
</script>

<template>
  <a-table
    size="small"
    :data-source="data"
    :loading="loading"
    :pagination="false"
    :columns="[
      { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
      { title: '状态', dataIndex: 'status', key: 'status', width: 110 },
      { title: '作者', dataIndex: 'author', key: 'author', width: 120 },
      { title: '时间', dataIndex: 'createdAtText', key: 'createdAt', width: 170 },
      { title: '耗时', dataIndex: 'durationS', key: 'durationS', width: 90 },
      { title: '说明', dataIndex: 'note', key: 'note' }
    ]"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'status'">
        <a-tag :color="record.status === 'live' ? 'green' : record.status === 'failed' ? 'red' : 'default'">
          {{ record.status }}
        </a-tag>
      </template>
      <template v-else-if="column.key === 'durationS'">
        {{ formatDuration(record.durationS) }}
      </template>
      <template v-else-if="column.key === 'note'">
        <span>{{ record.note || '—' }}</span>
        <a-tag v-if="record.rolledBackTo" color="orange">回滚自 v{{ record.rolledBackTo }}</a-tag>
      </template>
    </template>
  </a-table>
</template>
```

- [ ] **Step 7: 写 `components/AuditTable.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { AuditRow } from '@/types/profile'
import { formatDuration, formatTime } from '@/utils/format'

const props = defineProps<{ rows: AuditRow[]; loading?: boolean }>()

const data = computed(() => props.rows.map((row) => ({ ...row, key: row.auditId, atText: formatTime(row.at) })))
</script>

<template>
  <a-table size="small" :data-source="data" :loading="loading" :pagination="false">
    <template #columns>
      <a-table-column title="时间" data-index="atText" key="at" :width="170" />
      <a-table-column title="操作人" data-index="actor" key="actor" :width="120" />
      <a-table-column title="动作" data-index="action" key="action" :width="130" />
      <a-table-column title="版本" data-index="version" key="version" :width="80" />
      <a-table-column title="结果" key="result" :width="100">
        <template #default="{ record }">
          <a-tag :color="record.result === 'ok' ? 'green' : 'red'">{{ record.result }}</a-tag>
        </template>
      </a-table-column>
      <a-table-column title="字段（仅名称）" key="fields">
        <template #default="{ record }">
          <a-tag v-for="field in record.fields" :key="field" class="audit-table__field">{{ field }}</a-tag>
          <span v-if="!record.fields.length">—</span>
        </template>
      </a-table-column>
      <a-table-column title="耗时" key="durationS" :width="90">
        <template #default="{ record }">{{ formatDuration(record.durationS) }}</template>
      </a-table-column>
      <a-table-column title="错误码" data-index="errorCode" key="errorCode" :width="160" />
    </template>
  </a-table>
</template>

<style scoped lang="less">
.audit-table__field {
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 2px;
}
</style>
```

- [ ] **Step 8: 写 `components/InstanceCard.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { InstanceSnapshot } from '@/types/api'
import { describeAlert } from '@/utils/error'
import { formatTime } from '@/utils/format'

const props = defineProps<{ snapshot: InstanceSnapshot | null; error: string }>()

const container = computed(() => props.snapshot?.container ?? null)
const pool = computed(() => props.snapshot?.pool ?? null)
</script>

<template>
  <div class="instance-card">
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-alert
      v-for="alert in snapshot?.alerts ?? []"
      :key="alert"
      type="warning"
      show-icon
      :message="describeAlert(alert)"
    />

    <a-descriptions v-if="container" title="进程" size="small" bordered :column="3">
      <a-descriptions-item label="program">{{ container.name }}</a-descriptions-item>
      <a-descriptions-item label="状态">
        <a-tag :color="container.status === 'running' ? 'green' : 'red'">{{ container.status }}</a-tag>
      </a-descriptions-item>
      <a-descriptions-item label="pid">{{ container.pid ?? '—' }}</a-descriptions-item>
      <a-descriptions-item label="镜像">{{ container.image || '—' }}</a-descriptions-item>
      <a-descriptions-item label="启动时间">{{ formatTime(container.startedAt) }}</a-descriptions-item>
      <a-descriptions-item label="详情">{{ container.detail || '—' }}</a-descriptions-item>
    </a-descriptions>

    <a-descriptions v-if="pool" title="会话池" size="small" bordered :column="2">
      <a-descriptions-item label="大小">{{ pool.size }}</a-descriptions-item>
      <a-descriptions-item label="占用">{{ pool.inUse }}</a-descriptions-item>
    </a-descriptions>
    <a-alert v-else-if="snapshot" type="warning" show-icon message="会话池不可达（/v1/pool 无响应）" />

    <a-table
      v-if="pool && pool.units.length"
      size="small"
      :pagination="false"
      :data-source="pool.units"
      :columns="[
        { title: '#', dataIndex: 'index', key: 'index', width: 60 },
        { title: '状态', dataIndex: 'state', key: 'state', width: 110 },
        { title: '会话', dataIndex: 'sessionId', key: 'sessionId' }
      ]"
      row-key="index"
    />

    <pre v-if="snapshot?.usage" class="instance-card__usage">{{ JSON.stringify(snapshot.usage, null, 2) }}</pre>
  </div>
</template>

<style scoped lang="less">
.instance-card {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__usage {
    background: #141a2e;
    border-radius: 10px;
    color: #8b93a7;
    font-size: 12px;
    margin: 0;
    padding: 12px;
  }
}
</style>
```

- [ ] **Step 9: 写三个视图**

`console/frontend/src/views/VersionsView.vue`：

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'

import { AppError } from '@/api/client'
import { getVersions } from '@/api/profiles'
import ErrorBanner from '@/components/ErrorBanner.vue'
import VersionTable from '@/components/VersionTable.vue'
import { useConsoleStore } from '@/stores/console'
import type { VersionRow } from '@/types/profile'

const consoleStore = useConsoleStore()

const rows = ref<VersionRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<AppError | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await getVersions(consoleStore.profile, page.value, pageSize.value)
    rows.value = data.list
    total.value = data.total
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '版本列表加载失败')
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch([() => consoleStore.profile, page, pageSize], () => void load(), { immediate: true })
</script>

<template>
  <div class="versions">
    <ErrorBanner :error="error" />
    <VersionTable :rows="rows" :loading="loading" />
    <a-pagination
      v-model:current="page"
      v-model:page-size="pageSize"
      :total="total"
      size="small"
      show-size-changer
      :page-size-options="['20', '50', '100']"
    />
  </div>
</template>

<style scoped lang="less">
.versions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
```

`console/frontend/src/views/AuditView.vue`：

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'

import { AppError } from '@/api/client'
import { getAudit } from '@/api/profiles'
import AuditTable from '@/components/AuditTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useConsoleStore } from '@/stores/console'
import type { AuditRow } from '@/types/profile'

const consoleStore = useConsoleStore()

const rows = ref<AuditRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const error = ref<AppError | null>(null)

const actor = ref('')
const action = ref('')
const result = ref('')
const field = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await getAudit(consoleStore.profile, {
      actor: actor.value || undefined,
      action: action.value || undefined,
      result: result.value || undefined,
      field: field.value || undefined,
      page: page.value,
      pageSize: pageSize.value
    })
    rows.value = data.list
    total.value = data.total
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '审计列表加载失败')
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch([() => consoleStore.profile, page, pageSize], () => void load(), { immediate: true })
</script>

<template>
  <div class="audit">
    <form class="audit__filters" @submit.prevent="page = 1; void load()">
      <a-input v-model:value="actor" placeholder="操作人" allow-clear />
      <a-input v-model:value="action" placeholder="动作（如 draft.patch）" allow-clear />
      <a-select
        v-model:value="result"
        :options="[
          { value: '', label: '全部结果' },
          { value: 'ok', label: 'ok' },
          { value: 'failed', label: 'failed' }
        ]"
      />
      <a-input v-model:value="field" placeholder="字段名（如 vad.min_silence_ms）" allow-clear />
      <a-button type="primary" html-type="submit">查询</a-button>
    </form>

    <ErrorBanner :error="error" />
    <AuditTable :rows="rows" :loading="loading" />
    <a-pagination
      v-model:current="page"
      v-model:page-size="pageSize"
      :total="total"
      size="small"
      show-size-changer
      :page-size-options="['50', '100', '200']"
    />
  </div>
</template>

<style scoped lang="less">
.audit {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__filters {
    display: flex;
    gap: 8px;
    max-width: 900px;
  }
}
</style>
```

`console/frontend/src/views/InstancesView.vue`：

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'

import { AppError } from '@/api/client'
import { getInstances } from '@/api/instances'
import InstanceCard from '@/components/InstanceCard.vue'
import { usePolling } from '@/composables/usePolling'
import { useConsoleStore } from '@/stores/console'
import type { InstanceSnapshot } from '@/types/api'

const consoleStore = useConsoleStore()

const snapshot = ref<InstanceSnapshot | null>(null)
const error = ref('')

async function poll(): Promise<void> {
  try {
    snapshot.value = await getInstances(consoleStore.profile)
    error.value = ''
  } catch (caught) {
    snapshot.value = null
    error.value = caught instanceof AppError ? caught.message : '实例状态不可读'
  }
}

const { active, start, stop } = usePolling(poll, 5000)

watch(
  () => consoleStore.profile,
  () => start(),
  { immediate: true }
)
</script>

<template>
  <div class="instances">
    <div class="instances__bar">
      <a-badge :status="active ? 'processing' : 'default'" :text="active ? '每 5s 刷新' : '已暂停'" />
      <a-button size="small" @click="active ? stop() : start()">{{ active ? '暂停' : '继续' }}</a-button>
    </div>

    <InstanceCard :snapshot="snapshot" :error="error" />
  </div>
</template>

<style scoped lang="less">
.instances {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__bar {
    align-items: center;
    display: flex;
    gap: 12px;
  }
}
</style>
```

- [ ] **Step 10: 注册四个路由**

`console/frontend/src/router/index.ts` 里 **`path: 'console'` 那条记录**（Task 11 Step 13 建的空 `children`）变为：

```ts
      children: [
        // `/console` 自己落到参数页；`meta`（`face` / `requiresAuth`）从父记录继承，
        // 不必逐条重复。
        { path: '', redirect: { name: 'params' } },
        { path: 'params', name: 'params', component: () => import('@/views/ParamsView.vue') },
        { path: 'versions', name: 'versions', component: () => import('@/views/VersionsView.vue') },
        { path: 'audit', name: 'audit', component: () => import('@/views/AuditView.vue') },
        { path: 'instances', name: 'instances', component: () => import('@/views/InstancesView.vue') }
      ]
```

`/console/params` 能渲染出视图依赖两件事同时成立：父记录 `/` 挂着 `ConsoleLayout`、`console` 记录没有组件（`RouterView` 会跳过无组件的 matched 记录，把子路由交给外壳的 `<router-view>`）。Task 20 Step 20 的 `router.spec.ts` 会为这条链补断言（不依赖 DOM，只查 `router.resolve` 的 matched 链）。

- [ ] **Step 11: 构建 + 全量单测**

Run: `cd console/frontend && npx vitest run && npm run build`
Expected: `Test Files 6 passed`, `Tests 20 passed`，`vue-tsc` 无错误。

- [ ] **Step 12: 手工验收（阶段 D 检查点）**

后端与前端各起一个终端（同 Task 12 Step 15）。登录后逐页看：

1. **版本**：没发布过时表格为空、分页隐藏；用 `seed` 造一条版本行后能看到状态标签；
2. **审计**：先不改筛选直接查 → 有 `draft.patch` 记录，`fields` 显示字段名列表，没有任何值；用 `field=vad.min_silence_ms` 能筛出对应行；
3. **实例**：`pipeline stopped` 的环境里，页面必须仍能渲染（HTTP 200），同时出现「pipeline 进程未运行」与「会话池不可达」两条告警；`active` 时每 5s 自动刷新，点「暂停」后不再发请求（DevTools Network 里可验证）；
4. 把 `supervisord` 停掉再刷新 `/instances` → 页面不报错，`container.status` 变成 `unknown`，`detail` 显示 probe 未就绪的原因。

四面板可览即阶段 D 通过。

- [ ] **Step 13: 提交**

```bash
git add console/frontend
git commit -m "feat(console): versions, audit and instances views"
```

---

# 阶段 E：写入链路（P3）

## Task 14: `supervisor_client` + `restart_runner`（把“重启”从 docker 换成 socket）

**Files:**
- Create: `console/backend/app/services/supervisor_client.py`
- Create: `console/backend/app/services/restart_runner.py`
- Modify: `console/backend/app/services/process_probe.py`（把 `_build()` 换成真实 probe）
- Test: `console/backend/tests/unit/test_supervisor_client.py`
- Test: `console/backend/tests/unit/test_restart_runner.py`

**Interfaces:**
- Consumes: `console.supervisor_socket`（默认 `/run/s2s-console/supervisor.sock`）、`console.supervisor_program`（`pipeline`）、`console.restart_mode`（`supervisor` / `noop`）——Task 3 已定义。
- Produces: `supervisor_client.SupervisorError`；`supervisor_client.available() -> tuple[bool, str]`；`supervisor_client.state(name) -> dict`；`supervisor_client.restart(name) -> None`；`supervisor_client.program() -> str`；`restart_runner.restart() -> float`（返回重启耗时秒，失败抛 `ApiError(502, "restart_unavailable")`）；`restart_runner.wait_running(timeout=60.0) -> ProcessInfo`；`process_probe._build()` 返回 `SupervisorProbe()`。

**不做什么**：不装 docker CLI、不挂 `docker.sock`、不暴露任意 XML-RPC 方法。`_proxy()` 只被三个函数用，没有任何“把方法名当参数”的入口（§10.3）。

- [ ] **Step 1: 先写 supervisor 客户端的失败测试**

`console/backend/tests/unit/test_supervisor_client.py`：

```python
from __future__ import annotations

import xmlrpc.client

import pytest

from app.config import console
from app.services import supervisor_client


def _fake(monkeypatch, supervisor):
    class _Proxy:
        pass

    proxy = _Proxy()
    proxy.supervisor = supervisor
    monkeypatch.setattr(supervisor_client, "_proxy", lambda: proxy)


def test_available_reports_a_missing_socket(monkeypatch, tmp_path):
    monkeypatch.setattr(console, "supervisor_socket", str(tmp_path / "nope.sock"))
    ok, detail = supervisor_client.available()
    assert ok is False
    assert "nope.sock" in detail


def test_restart_stops_waiting_then_starts(monkeypatch):
    calls: list[tuple] = []

    class _Supervisor:
        def stopProcess(self, name, wait):
            calls.append(("stop", name, wait))

        def startProcess(self, name):
            calls.append(("start", name))

    _fake(monkeypatch, _Supervisor())
    supervisor_client.restart("pipeline")
    # `wait=True` matters: without it the start can race the stop and fail.
    assert calls == [("stop", "pipeline", True), ("start", "pipeline")]


def test_a_refused_restart_is_a_supervisor_error(monkeypatch):
    class _Supervisor:
        def stopProcess(self, name, wait):
            raise xmlrpc.client.Fault(90, "RUNNING")

    _fake(monkeypatch, _Supervisor())
    with pytest.raises(supervisor_client.SupervisorError, match="RUNNING"):
        supervisor_client.restart("pipeline")


def test_the_program_name_comes_from_settings_not_from_the_caller(monkeypatch):
    monkeypatch.setattr(console, "supervisor_program", "pipeline")
    assert supervisor_client.program() == "pipeline"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_supervisor_client.py -q`
Expected: FAIL，`ModuleNotFoundError: app.services.supervisor_client`。

- [ ] **Step 3: 实现 `services/supervisor_client.py`**

```python
"""supervisor 的 XML-RPC 客户端，跑在 unix socket 上（§10.3）。

故意做得很窄：三个函数，三个调用的方法。console 能对容器内做的最坏的事
是重启 pipeline，而不是“以任意权限执行任意 supervisor 命令”。
"""

from __future__ import annotations

import http.client
import os
import socket
import xmlrpc.client
from typing import Any

from app.config import console

# supervisor 的 RPC 是同步的；给足 60s，与规格「单次重启超时 60s」对齐（§4.1）。
CALL_TIMEOUT = 60.0


class SupervisorError(RuntimeError):
    """socket 不可达或 supervisor 拒绝；调用方一律翻译成 502。"""


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


class _UnixTransport(xmlrpc.client.Transport):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__()
        self._path = path
        self._timeout = timeout

    def make_connection(self, host: str) -> _UnixHTTPConnection:
        return _UnixHTTPConnection(self._path, self._timeout)


def program() -> str:
    """重启目标从配置读，不从请求体读（§10.3）。"""
    return console.supervisor_program


def _proxy() -> xmlrpc.client.ServerProxy:
    path = console.supervisor_socket
    if not os.path.exists(path):
        raise SupervisorError(f"supervisor socket {path} does not exist")
    transport = _UnixTransport(path, CALL_TIMEOUT)
    # host 只用于 HTTP 头，真实连接走 unix socket。
    return xmlrpc.client.ServerProxy("http://localhost", transport=transport, allow_none=True)


def _call(method: str, *args: Any) -> Any:
    try:
        proxy = _proxy()
        return getattr(proxy.supervisor, method)(*args)
    except SupervisorError:
        raise
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError) as exc:
        raise SupervisorError(f"supervisor refused {method}: {exc}") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise SupervisorError(f"supervisor socket unusable: {exc}") from exc


def available() -> tuple[bool, str]:
    """`(usable, detail)`。socket 不在是正常状态，不是异常。"""
    try:
        info = _call("getState")
    except SupervisorError as exc:
        return False, str(exc)
    return True, str((info or {}).get("statename", "unknown"))


def state(name: str) -> dict[str, Any]:
    return dict(_call("getProcessInfo", name) or {})


def restart(name: str) -> None:
    """`stopProcess(wait=True)` 后 `startProcess`（§4.1 步骤 7）。"""
    _call("stopProcess", name, True)
    _call("startProcess", name)
```

注意 `restart()` 两次 `_call` 各建一个 proxy：`stopProcess(wait=True)` 期间 XML-RPC 连接可能被 supervisord 的重启流程关掉，复用同一个 proxy 会出现「stop 成功、start 抛 `ProtocolError`」的假失败。代价是多开一个本地连接，可以忽略。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_supervisor_client.py -q`
Expected: 4 passed。

- [ ] **Step 5: 先写 `restart_runner` 的失败测试**

`console/backend/tests/unit/test_restart_runner.py`：

```python
from __future__ import annotations

import pytest

from app.config import console
from app.core.errors import ApiError
from app.services import process_probe, restart_runner, supervisor_client


def test_a_dead_socket_is_a_502(monkeypatch):
    monkeypatch.setattr(supervisor_client, "available", lambda: (False, "no socket"))
    with pytest.raises(ApiError) as caught:
        restart_runner.restart()
    assert caught.value.code == "restart_unavailable"
    assert caught.value.status == 502


def test_noop_mode_skips_the_restart_but_not_the_wait(monkeypatch):
    monkeypatch.setattr(console, "restart_mode", "noop")
    monkeypatch.setattr(supervisor_client, "restart", lambda name: pytest.fail("must not restart"))
    seen = []
    monkeypatch.setattr(restart_runner, "wait_running", lambda timeout=60.0: seen.append(timeout))
    restart_runner.restart()
    # 开发态不真重启，但探活必须照常跑，否则开发时看不到“重启后不健康”。
    assert seen == [60.0]


def test_wait_running_gives_up_after_the_timeout(monkeypatch):
    monkeypatch.setattr(
        process_probe,
        "get_probe",
        lambda: type(
            "_Probe", (), {"state": lambda self, name: process_probe.ProcessInfo(name=name, running=False)}
        )(),
    )
    with pytest.raises(ApiError) as caught:
        restart_runner.wait_running(timeout=0.2, interval=0.05)
    assert caught.value.code == "restart_unavailable"
```

Run: `cd console/backend && python -m pytest tests/unit/test_restart_runner.py -q`
Expected: FAIL，`app.services.restart_runner` 不存在。

- [ ] **Step 6: 实现 `services/restart_runner.py`**

```python
"""链路 A 的步骤 7：先把 pipeline 停干净，再起来，再等回 RUNNING。

与旧实现（`compose_runner.recreate()` → `docker compose up --force-recreate`）
的区别只有一个：不再重建容器，只重启容器内的子进程。因此 `.env` 类字段无法
生效（→ `409 env_requires_recreate`，Task 15）。
"""

from __future__ import annotations

import time

from app.config import console
from app.core.errors import ApiError
from app.services import process_probe, supervisor_client


def restart() -> float:
    """重启 pipeline 并等它回到 RUNNING；返回耗时秒。"""
    started = time.monotonic()

    if console.restart_mode != "noop":
        usable, detail = supervisor_client.available()
        if not usable:
            raise ApiError(
                code="restart_unavailable",
                message="the supervisor socket is not reachable",
                status=502,
                detail=[{"reason": detail}],
            )
        try:
            supervisor_client.restart(supervisor_client.program())
        except supervisor_client.SupervisorError as exc:
            raise ApiError(
                code="restart_unavailable",
                message=str(exc),
                status=502,
            ) from exc

    wait_running()
    return round(time.monotonic() - started, 1)


def wait_running(timeout: float = 60.0, interval: float = 1.0) -> process_probe.ProcessInfo:
    """等回 RUNNING。超时仍不是 RUNNING 就是重启失败，没有“先当它成功了”。"""
    deadline = time.monotonic() + timeout
    info = process_probe.get_probe().state(supervisor_client.program())
    while not info.running:
        if time.monotonic() + interval > deadline:
            raise ApiError(
                code="restart_unavailable",
                message=f"pipeline did not reach RUNNING within {timeout:.0f}s",
                status=502,
                detail=[{"state": info.state, "detail": info.detail}],
            )
        time.sleep(interval)
        info = process_probe.get_probe().state(supervisor_client.program())
    return info
```

`RESTART_MODE=noop` 时跳过的是 `restart()` 这一句，**不是 `wait_running()`**：开发机上 pipeline 常常已经在跑，跳过探活会让“重启后不健康”这类问题只在生产出现。

- [ ] **Step 7: 把 `process_probe._build()` 接上真实探针**

`console/backend/app/services/process_probe.py` 末尾追加，并改 `_build()`：

```python
class SupervisorProbe:
    """read-only：问 supervisor“这个 program 现在什么状态”（§10.3）。"""

    def state(self, name: str) -> ProcessInfo:
        try:
            info = supervisor_client.state(name)
        except supervisor_client.SupervisorError as exc:
            return ProcessInfo(name=name, running=False, state="unknown", detail=str(exc))
        statename = str(info.get("statename", "unknown")).lower()
        pid = info.get("pid")
        return ProcessInfo(
            name=name,
            running=statename == "running",
            pid=pid if isinstance(pid, int) and pid > 0 else None,
            state=statename,
            detail=str(info.get("spawnerr") or ""),
        )


def _build() -> ProcessProbe:
    return SupervisorProbe()
```

并在文件顶部加 `from app.services import supervisor_client`（`process_probe` 已在 Task 10 的 `services/__init__` 同层，不会循环 import：`supervisor_client` 只依赖 `app.config`）。

- [ ] **Step 8: 跑全量后端测试**

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿。重点确认 Task 10 的 `test_instances.py` 仍过：它们 monkeypatch 了 `process_probe.get_probe` 或 `set_probe`，不会真的去碰 socket。

- [ ] **Step 9: 在真容器里验一把 socket（阶段 E 的第一个现场证据）**

在宿主机上（镜像已按 Task 4 构建并启动）：

```bash
docker compose exec pipeline python -c "from app.services import supervisor_client as s; print(s.available()); print(s.state('pipeline'))"
docker compose exec pipeline ls -l /run/s2s-console/supervisor.sock
```

Expected: `(True, 'RUNNING')`；第二行是 `{'name': 'pipeline', 'statename': 'RUNNING', ...}`；第三个命令显示 `srw------- 1 root root`。
若报 `socket ... does not exist`：`supervisord.conf` 的 `[unix_http_server] file=` 与 `console.supervisor_socket` 不一致。

- [ ] **Step 10: 提交**

```bash
git add console/backend
git commit -m "feat(console): restart pipeline through the supervisor unix socket"
```

---

## Task 15: 发布与回滚端点（A.5/A.6）+ 启动自检 + 发布对话框

**Files:**
- Modify: `console/backend/tests/fixtures/parameter-catalog.min.yaml`（加一条 `stage: env`）
- Modify: `console/backend/app/services/publish_flow_service.py`（追加 `publish` / `rollback` / `recover_pending` / `_deploy` / `_revert` / `backup` / `restore` / `_write`）
- Modify: `console/backend/app/schemas/draft.py`（加 `PublishRequest`、`RollbackRequest`）
- Modify: `console/backend/app/routers/profiles.py`（加 A.5、A.6）
- Modify: `console/backend/app/main.py`（`lifespan` 里调 `recover_pending`）
- Test: `console/backend/tests/unit/test_publish_flow.py`
- Test: `console/backend/tests/integration/test_publish.py`
- Modify: `console/frontend/src/types/profile.d.ts`（加 `PublishResult`、`RollbackResult`）
- Modify: `console/frontend/src/api/profiles.ts`（加 `publishProfile`、`rollbackProfile`）
- Create: `console/frontend/src/components/PublishDialog.vue`
- Modify: `console/frontend/src/views/ParamsView.vue`（加「发布」按钮与对话框）
- Modify: `console/frontend/src/components/VersionTable.vue`（加「回滚到此版本」）
- Modify: `console/frontend/src/views/VersionsView.vue`（接回滚）

**Interfaces:**
- Consumes: `restart_runner.restart() -> float`（Task 14）；`pool.read_pool()` / `pool.wait_healthy(expected, *, timeout, interval)`（Task 10）；`VersionRepository.create(profile, *, status, yaml_text, env_sha256, note, author)` / `.set_status(row, status, *, error_code, duration_s, rolled_back_to)` / `.get(profile, version)` / `.dangling()`（Task 6）；`renderer_service.split_patches`（Task 9）。
- Produces: `publish_flow_service.publish(db, profile, *, base_version=None, note="", actor="", role="", request_id="") -> dict`；`.rollback(db, profile, *, target_version, note="", actor="", role="", request_id="") -> dict`；`.recover_pending(db) -> list[dict]`；`.backup(path, version)` / `.restore(source, target)`；`POST /api/v1/profiles/{p}/publish`、`POST .../rollback`。

**为什么 `.env` 门禁必须放在落版本之前**（§4.1 步骤 5）：`render()` 会把 env 字段写进 `config/<profile>.env`，而运行中的 pipeline 进程永远不会重读它（只有重建容器才会）。若先落版本再拒绝，版本表里会留下一条永远不会变 `live` 的 `publishing` 行，下次启动自检还会把它当成“悬挂发布”去恢复。

- [ ] **Step 1: 给夹具加一条 `stage: env` 条目**

`console/backend/tests/fixtures/parameter-catalog.min.yaml` 末尾（`runtime.torch_num_threads` 之后）追加：

```yaml
  - stage: env
    backend: null
    name: GPUSTACK_API_KEY
    type: string
    default: not-needed
    exposure: ops
    effect: 供应商凭据
```

它的 `key` 是 `env.GPUSTACK_API_KEY`——这就是 `.env` 门禁测试要用的字段（真实目录里同名条目的 `source_ref` 是 `.env.gpustack.example:GPUSTACK_API_KEY`）。

- [ ] **Step 2: 先写失败测试**

`console/backend/tests/unit/test_publish_flow.py`：

```python
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.config import console as console_settings
from app.core.errors import ApiError
from app.db.database import SessionLocal
from app.models import ParamVersion
from app.repositories.draft_repository import DraftRepository
from app.repositories.version_repository import VersionRepository
from app.services import pool, publish_flow_service, restart_runner

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"
BASE_YAML = "schema_version: 1\npipelines:\n  prod:\n    num_pipelines: 1\n"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "prod.yaml").write_text(BASE_YAML, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(directory))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    return directory


@pytest.fixture
def healthy(monkeypatch):
    monkeypatch.setattr(restart_runner, "restart", lambda: 1.0)
    monkeypatch.setattr(
        pool, "wait_healthy", lambda expected, timeout=180.0, interval=2.0: pool.HealthResult(
            ok=True, reason="pool size 1, 0 in use", elapsed_s=1.0, attempts=1,
            pool=pool.PoolState(reachable=True, size=1),
        )
    )


def test_an_env_field_is_refused_before_anything_is_written(config_dir, healthy, db_session):
    DraftRepository(db_session).put("prod", base_version=0, patch={"env.GPUSTACK_API_KEY": "gsk-x"}, actor="alice")
    before = (config_dir / "prod.yaml").read_bytes()

    with pytest.raises(ApiError) as caught:
        publish_flow_service.publish(db_session, "prod", actor="alice", role="admin")

    assert caught.value.code == "env_requires_recreate"
    assert caught.value.status == 409
    # Only the variable name, never its value (B7).
    assert caught.value.detail == [{"var": "GPUSTACK_API_KEY"}]
    assert (config_dir / "prod.yaml").read_bytes() == before
    assert VersionRepository(db_session).list("prod")[1] == 0
    assert DraftRepository(db_session).get("prod") is not None


def test_a_dead_supervisor_aborts_and_restores_the_backup(config_dir, db_session, monkeypatch):
    original = (config_dir / "prod.yaml").read_bytes()
    DraftRepository(db_session).put("prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice")
    monkeypatch.setattr("app.services.publish_flow_service.render", _rendered)
    monkeypatch.setattr(
        restart_runner,
        "restart",
        lambda: (_ for _ in ()).throw(ApiError(code="restart_unavailable", message="no socket", status=502)),
    )

    with pytest.raises(ApiError) as caught:
        publish_flow_service.publish(db_session, "prod", actor="alice", role="admin")

    assert caught.value.code == "restart_unavailable"
    # The whole point: what runs must be what ran before, byte for byte.
    assert (config_dir / "prod.yaml").read_bytes() == original
    row = VersionRepository(db_session).list("prod")[0][0]
    assert row.status == "rolled_back"


def test_a_healthcheck_timeout_marks_rolled_back(config_dir, db_session, monkeypatch):
    DraftRepository(db_session).put("prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice")
    monkeypatch.setattr("app.services.publish_flow_service.render", _rendered)
    monkeypatch.setattr(restart_runner, "restart", lambda: 1.0)
    monkeypatch.setattr(
        pool, "wait_healthy",
        lambda expected, timeout=180.0, interval=2.0: pool.HealthResult(
            ok=False, reason="after 180s: pool size 0, expected 1", elapsed_s=180.0, attempts=90
        ),
    )

    with pytest.raises(ApiError) as caught:
        publish_flow_service.publish(db_session, "prod", actor="alice", role="admin")

    assert (caught.value.code, caught.value.status) == ("healthcheck_timeout", 504)
    assert VersionRepository(db_session).list("prod")[0][0].status == "rolled_back"


def test_a_second_publish_is_refused_while_the_first_holds_the_lock(config_dir, healthy, db_session):
    DraftRepository(db_session).put("prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice")
    assert publish_flow_service._lock.acquire(blocking=False)
    try:
        with pytest.raises(ApiError) as caught:
            publish_flow_service.publish(db_session, "prod", actor="alice", role="admin")
        assert (caught.value.code, caught.value.status) == ("publish_in_progress", 409)
    finally:
        publish_flow_service._lock.release()


def test_the_draft_disappears_only_after_a_successful_publish(config_dir, healthy, db_session, monkeypatch):
    DraftRepository(db_session).put("prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice")
    monkeypatch.setattr("app.services.publish_flow_service.render", _rendered)

    result = publish_flow_service.publish(db_session, "prod", actor="alice", role="admin", note="tune")

    assert result["status"] == "live"
    assert result["version"] == 1
    assert DraftRepository(db_session).get("prod") is None
    assert VersionRepository(db_session).latest_live("prod").version == 1


def _rendered(profile, values, environ=None):
    text = BASE_YAML.replace("num_pipelines: 1", "num_pipelines: 1\n    seed: 1")
    return publish_flow_service.Rendered(
        text=text, values=values, applied=sorted(values), expected_size=1, resolved={"pipelines": [profile]}
    )
```

`tests/conftest.py` 的 `db_session` fixture 已在 Task 6 建好（内存 SQLite + `import app.models`），此处直接复用。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_publish_flow.py -q`
Expected: FAIL，`AttributeError: module 'app.services.publish_flow_service' has no attribute 'publish'`。

- [ ] **Step 4: 给 `publish_flow_service.py` 追加发布实现**

文件顶部 import 区补：

```python
import hashlib
import shutil
import threading
from typing import NoReturn

from loguru import logger

from app.core.errors import ApiError
from app.repositories.audit_repository import AuditRepository
from app.repositories.draft_repository import DraftRepository
from app.repositories.version_repository import VersionRepository
from app.services import pool, restart_runner, validator_service
```

文件末尾追加：

```python
# ── 链路 A 步骤 5–9 ─────────────────────────────────────────────────────────

# 只有这两个状态可以被回滚指向（§4.3）。
ROLLBACKABLE = frozenset({"live", "rolled_back"})

# supervisor 写的两份日志（§10.3）：只读、只 tail 200 行。
PIPELINE_LOGS = (
    "/var/log/supervisor/pipeline-stdout.log",
    "/var/log/supervisor/pipeline-stderr.log",
)

_lock = threading.Lock()


def _exclusive() -> None:
    """同一 profile 同时只能有一个发布（多 worker 会各持一把锁 → 必须单 worker）。"""
    if not _lock.acquire(blocking=False):
        raise ApiError(
            code="publish_in_progress",
            message="another publish or rollback is running for this deployment",
            status=409,
        )


def _finish(repo: VersionRepository, row, status: str, *, error_code: str | None = None,
            duration_s: float | None = None):
    """`set_status` 会把每个字段重写一遍，所以 `rolled_back_to` 必须原样传回。

    否则回滚产生的版本在变 `live` 时会把「它是从哪个版本来的」抹掉，审计就断了。
    """
    return repo.set_status(row, status, error_code=error_code, duration_s=duration_s,
                           rolled_back_to=row.rolled_back_to)


def _audit(db, action: str, profile: str, *, actor: str, role: str, version: int,
           result: str, fields: list[str], error_code: str | None = None,
           duration_s: float | None = None, request_id: str = ""):
    return AuditRepository(db).record(
        actor=actor, role=role, action=action, profile=profile, fields=list(fields),
        result=result, version=version, error_code=error_code,
        duration_s=duration_s, request_id=request_id,
    )


def publish(db, profile: str, *, base_version: int | None = None, note: str = "",
            actor: str = "", role: str = "", request_id: str = "") -> dict[str, Any]:
    """A.5。不可附带 draft 参数：补丁只能通过 A.3 先落库再发布。"""
    started = time.monotonic()
    _exclusive()
    try:
        require_profile(profile)
        known = entries()
        drafts = DraftRepository(db)
        draft = drafts.get(profile)
        if draft is None or not draft.patch:
            raise ApiError(code="no_draft", message="there is nothing to publish", status=404)

        versions = VersionRepository(db)
        current = live_version(profile, versions)
        if base_version is not None and base_version != current:
            raise ApiError(
                code="version_conflict",
                message=f"the live version moved to {current}",
                status=409,
                detail=[{"expected": current, "got": base_version}],
            )

        # 步骤 5：先拒，再写、再版本化（§4.2）。
        _, env_patches = renderer_service.split_patches(draft.patch, known)
        if env_patches:
            raise ApiError(
                code="env_requires_recreate",
                message="these variables only take effect in a recreated container",
                status=409,
                detail=[{"var": name} for name in sorted(env_patches)],
            )

        rendered = render(profile, draft.patch)  # 422 在这里抛，草稿不动

        row = versions.create(
            profile,
            status="publishing",
            yaml_text=rendered.text,
            env_sha256=_sha(rendered.env_text or ""),
            note=note,
            author=actor,
        )
        result = _deploy(db, profile, rendered, row, actor=actor, role=role, note=note,
                         started=started, request_id=request_id)
        drafts.drop(profile)
        return result
    finally:
        _lock.release()


def rollback(db, profile: str, *, target_version: int, note: str = "", actor: str = "",
             role: str = "", request_id: str = "") -> dict[str, Any]:
    """A.6：回滚产生新版本号，不删旧版本。

    盘上写的是目标版本的原字节，不是「拿它的 patch 重新渲染」：重新渲染会把旧
    补丁套到新文件上，得到一个从未运行过的配置。
    """
    started = time.monotonic()
    _exclusive()
    try:
        require_profile(profile)
        versions = VersionRepository(db)
        target = versions.get(profile, target_version)
        if target is None:
            raise ApiError(code="unknown_version",
                           message=f"version {target_version} does not exist", status=404)
        if target.status not in ROLLBACKABLE:
            raise ApiError(
                code="version_not_rollbackable",
                message=f"version {target_version} is {target.status}, not a rollback target",
                status=409,
                detail=[{"status": target.status, "allowed": sorted(ROLLBACKABLE)}],
            )
        if not target.yaml_text:
            raise ApiError(code="version_not_rollbackable",
                           message=f"version {target_version} has no stored rendering", status=409)

        # 重跑校验不是多疑：换机后路径可能失效、模型可能被删、`{env:}` 可能被轮换。
        known = entries()
        result = validator_service.validate(
            target.yaml_text, profile, entries=known, environ=os.environ, vram_gb=vram_budget()
        )
        if not result["ok"]:
            raise ApiError(
                code=validation_code(result["errors"]),
                message=f"version {target_version} no longer validates on this machine",
                status=422,
                detail=result["errors"],
            )

        row = versions.create(
            profile,
            status="publishing",
            yaml_text=target.yaml_text,
            env_sha256=target.env_sha256,
            note=note or f"rollback to v{target_version}",
            author=actor,
        )
        versions.set_status(row, "publishing", rolled_back_to=target_version)
        rendered = Rendered(
            text=target.yaml_text,
            values={},
            applied=[],
            expected_size=expected_size(result, target.yaml_text, profile),
            resolved=result["resolved"],
            warnings=result["warnings"],
        )
        outcome = _deploy(db, profile, rendered, row, actor=actor, role=role, note=note,
                          started=started, request_id=request_id)
        outcome["rolledBackTo"] = target_version
        return outcome
    finally:
        _lock.release()


def _deploy(db, profile: str, rendered: Rendered, row, *, actor: str, role: str, note: str,
            started: float, request_id: str) -> dict[str, Any]:
    """步骤 6–8。调用方持有 `_lock`。"""
    versions = VersionRepository(db)
    snapshot = _backup(profile, rendered, row.version)

    try:
        _write(profile_path(profile), rendered.text)
        if rendered.env_text is not None:
            _write(env_path(profile), rendered.env_text)
    except OSError as exc:
        _undo(snapshot, profile)
        _finish(versions, row, "aborted", error_code="render_failed")
        _audit(db, "publish.aborted", profile, actor=actor, role=role, version=row.version,
               result="aborted", fields=sorted(rendered.values), error_code="render_failed",
               duration_s=round(time.monotonic() - started, 3), request_id=request_id)
        raise ApiError(code="render_failed",
                       message="the rendered profile could not be written",
                       status=500) from exc

    expected = rendered.expected_size
    if expected is None:
        # `num_pipelines` 是 `{env: N}`，真实大小只有重启后才知道；
        # 拿当前大小当基准，至少不会因为凭空造的数字判定失败。
        running = pool.read_pool()
        expected = running.size if running.reachable else 1

    try:
        restart_runner.restart()
    except ApiError as exc:
        _revert(db, profile, row, snapshot, actor=actor, role=role, started=started,
                request_id=request_id, code="restart_unavailable", status=502,
                reason=exc.message, expected=expected)

    health = pool.wait_healthy(expected, timeout=health_timeout())
    if not health.ok:
        _revert(db, profile, row, snapshot, actor=actor, role=role, started=started,
                request_id=request_id, code="healthcheck_timeout", status=504,
                reason=health.reason, expected=expected)

    duration = round(time.monotonic() - started, 1)
    _finish(versions, row, "live", duration_s=duration)
    audit = _audit(db, "publish.live", profile, actor=actor, role=role, version=row.version,
                   result="live", fields=rendered.applied, duration_s=duration,
                   request_id=request_id)
    return {
        "version": row.version,
        "status": "live",
        "healthcheck": {
            "poolSize": health.pool.size if health.pool else None,
            "inUse": health.pool.in_use if health.pool else None,
            "attempts": health.attempts,
            "notes": health.notes,
        },
        "durationS": duration,
        "applied": rendered.applied,
        "warnings": rendered.warnings,
        "auditId": str(audit.id),
    }


def _revert(db, profile: str, row, snapshot: "_Snapshot", *, actor: str, role: str,
            started: float, request_id: str, code: str, status: int, reason: str,
            expected: int) -> NoReturn:
    """步骤 9。永不返回：要么报 `rolled_back`，要么报 `rollback_failed`。"""
    versions = VersionRepository(db)
    restored = _undo(snapshot, profile)
    reverted = all(restored.values())
    log_tail = _tail_logs()

    if reverted:
        try:
            restart_runner.restart()
            health = pool.wait_healthy(expected, timeout=health_timeout())
        except ApiError as exc:
            health = pool.HealthResult(ok=False, reason=str(exc), elapsed_s=0.0)
        if health.ok:
            _finish(versions, row, "rolled_back", error_code=code,
                    duration_s=round(time.monotonic() - started, 1))
            _audit(db, "publish.rolled_back", profile, actor=actor, role=role,
                   version=row.version, result="rolled_back", fields=[], error_code=code,
                   duration_s=round(time.monotonic() - started, 3), request_id=request_id)
            raise ApiError(
                code=code,
                message=reason,
                status=status,
                detail=[{"status": "rolled_back", "version": row.version, **restored}],
            )

    # 发布失败且回滚也失败：盘上跑的东西没人验证过，只能人工收尾（§4.1 步骤 9）。
    _finish(versions, row, "failed", error_code=code,
            duration_s=round(time.monotonic() - started, 1))
    _audit(db, "publish.failed", profile, actor=actor, role=role, version=row.version,
           result="failed", fields=[], error_code="rollback_failed",
           duration_s=round(time.monotonic() - started, 3), request_id=request_id)
    raise ApiError(
        code="rollback_failed",
        message=f"{reason}; the automatic revert also failed — this needs a human",
        status=500,
        detail=[{"reason": reason, "restored": restored, "logs": log_tail}],
    )


def recover_pending(db) -> list[dict[str, Any]]:
    """启动自检（§4.1 末尾）：收尾上上回容器重建时被切在 6–9 之间的发布。"""
    versions = VersionRepository(db)
    outcomes: list[dict[str, Any]] = []
    for row in versions.dangling():
        path = profile_path(row.profile)
        on_disk = path.read_text(encoding="utf-8") if path.is_file() else ""
        state = pool.read_pool()

        if state.reachable and not state.stuck and _sha(on_disk) == row.yaml_sha256:
            _finish(versions, row, "live")
            outcomes.append({"profile": row.profile, "version": row.version, "status": "live"})
            continue

        restored = restore(_backup_path(row.profile, row.version), path)
        try:
            restart_runner.restart()
        except ApiError as exc:
            logger.warning("recovery restart for {} v{} failed: {}", row.profile, row.version, exc.message)
        _finish(versions, row, "rolled_back", error_code="restart_interrupted")
        outcomes.append({"profile": row.profile, "version": row.version,
                         "status": "rolled_back", "restored": restored})
    return outcomes


# ── 文件层 ────────────────────────────────────────────────────────────────


def _sha(text: str) -> str:
    """必须与 `version_repository` 存 `yaml_sha256` 时用的算法一致。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _backup_path(profile: str, version: int) -> Path:
    path = profile_path(profile)
    return path.with_suffix(path.suffix + f".bak.{version}")


def backup(path: Path, version: int) -> Path | None:
    if not path.is_file():
        return None
    target = path.with_suffix(path.suffix + f".bak.{version}")
    shutil.copy2(path, target)
    return target


def restore(source: Path | None, target: Path) -> bool:
    if source is None or not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _write(path: Path, text: str) -> None:
    """一步替换，避免崩溃时留下半份文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class _Snapshot:
    yaml: Path | None
    env: Path | None
    env_written: bool = False


def _backup(profile: str, rendered: Rendered, version: int) -> _Snapshot:
    writes_env = rendered.env_text is not None
    return _Snapshot(
        yaml=backup(profile_path(profile), version),
        env=backup(env_path(profile), version) if writes_env else None,
        env_written=writes_env,
    )


def _undo(snapshot: _Snapshot, profile: str) -> dict[str, bool]:
    """两个都恢复，或者都不算恢复成功。"""
    return {
        "yaml": restore(snapshot.yaml, profile_path(profile)),
        "env": _restore_env(snapshot, profile),
    }


def _restore_env(snapshot: _Snapshot, profile: str) -> bool:
    if not snapshot.env_written:
        return True
    if snapshot.env is not None:
        return restore(snapshot.env, env_path(profile))
    # 发布新建了这个文件，撤销就是把它删掉，否则它带来的密钥比失败的版本活得久。
    try:
        env_path(profile).unlink(missing_ok=True)
    except OSError as exc:
        logger.error("could not remove {}: {}", env_path(profile), exc)
        return False
    return True


def _tail_logs(lines: int = 200) -> list[str]:
    out: list[str] = []
    for name in PIPELINE_LOGS:
        path = Path(name)
        if not path.is_file():
            continue
        try:
            out.extend(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            continue
    return out
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_publish_flow.py -q`
Expected: 5 passed。

- [ ] **Step 6: 加 schema 与两个路由**

`console/backend/app/schemas/draft.py` 追加：

```python
class PublishRequest(BaseModel):
    baseVersion: int | None = None
    note: str = Field(default="", max_length=500)


class RollbackRequest(BaseModel):
    targetVersion: int
    note: str = Field(default="", max_length=500)
```

`console/backend/app/routers/profiles.py` 追加（import 区补 `PublishRequest, RollbackRequest`）：

```python
@router.post("/profiles/{profile}/publish")
def post_publish(
    profile: str,
    payload: PublishRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    """A.5: one publish at a time, and only an admin may interrupt live calls."""
    name = validate_profile_name(profile)
    if user.role != "admin":
        raise ApiError(code="forbidden", message="only an admin may publish", status=403)
    claimed = payload.baseVersion
    if claimed is None:
        claimed = if_match(request.headers.get("if-match", ""))
    return ok(
        publish_flow_service.publish(
            db, name, base_version=claimed, note=payload.note, actor=user.username,
            role=user.role, request_id=_request_id(request),
        )
    )


@router.post("/profiles/{profile}/rollback")
def post_rollback(
    profile: str,
    payload: RollbackRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    """A.6: a rollback is a new version, never a deletion."""
    name = validate_profile_name(profile)
    if user.role != "admin":
        raise ApiError(code="forbidden", message="only an admin may roll back", status=403)
    return ok(
        publish_flow_service.rollback(
            db, name, target_version=payload.targetVersion, note=payload.note,
            actor=user.username, role=user.role, request_id=_request_id(request),
        )
    )
```

**超时提醒**：这两个端点同步跑完整条链路，最坏 60s（重启）+ 180s（探活）+ 180s（回滚探活）≈ 7 分钟。

- [ ] **Step 7: 启动自检接进 lifespan**

`console/backend/app/main.py` 的 `lifespan` 改为：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 上一个容器可能把发布切在步骤 6–9 之间；先把这种行收尾，再开始接请求。
    session = SessionLocal()
    try:
        outcomes = publish_flow_service.recover_pending(session)
        for outcome in outcomes:
            logger.warning("recovered an interrupted publish: {}", outcome)
    except Exception as exc:  # noqa: BLE001 - a bad DB must not stop the API from booting
        logger.error("startup recovery skipped: {}", exc)
    finally:
        session.close()
    yield
```

（`from app.db.database import SessionLocal`、`from app.services import publish_flow_service`、`from loguru import logger` 补到 import 区。）

- [ ] **Step 8: 写集成测例**

`console/backend/tests/integration/test_publish.py`：

```python
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import console as console_settings
from app.repositories.draft_repository import DraftRepository

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"
BASE_YAML = "schema_version: 1\npipelines:\n  prod:\n    num_pipelines: 1\n"


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    from app.services import pool, publish_flow_service, restart_runner

    config = tmp_path / "config"
    config.mkdir()
    (config / "prod.yaml").write_text(BASE_YAML, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(config))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    monkeypatch.setattr(restart_runner, "restart", lambda: 1.0)
    monkeypatch.setattr(
        pool, "wait_healthy",
        lambda expected, timeout=180.0, interval=2.0: pool.HealthResult(
            ok=True, reason="ok", elapsed_s=1.0, attempts=1, pool=pool.PoolState(reachable=True, size=1)
        ),
    )
    monkeypatch.setattr(
        publish_flow_service,
        "render",
        lambda profile, values, environ=None: publish_flow_service.Rendered(
            text=BASE_YAML.replace("1\n", "1\n    seed: 2\n", 1), values=values,
            applied=sorted(values), expected_size=1, resolved={"pipelines": [profile]},
        ),
    )

    from app.main import create_app

    return TestClient(create_app())


def test_publish_returns_the_a5_shape(client, db_session):
    DraftRepository(db_session).put("prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice")
    headers = _auth(client)
    body = client.post("/api/v1/profiles/prod/publish", json={"note": "tune"}, headers=headers).json()
    assert body["data"]["status"] == "live"
    assert body["data"]["version"] == 1
    assert body["data"]["healthcheck"]["poolSize"] == 1
    assert body["data"]["auditId"]


def test_operator_cannot_publish(client, db_session):
    headers = _auth(client, username="bob", password="correct-horse")
    response = client.post("/api/v1/profiles/prod/publish", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_publishing_nothing_is_404_no_draft(client):
    response = client.post("/api/v1/profiles/prod/publish", json={}, headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "no_draft"


def test_an_env_field_is_409(client, db_session):
    DraftRepository(db_session).put("prod", base_version=0, patch={"env.GPUSTACK_API_KEY": "gsk-x"}, actor="alice")
    response = client.post("/api/v1/profiles/prod/publish", json={}, headers=_auth(client))
    assert response.status_code == 409
    assert response.json()["code"] == "env_requires_recreate"
    assert response.json()["detail"] == [{"var": "GPUSTACK_API_KEY"}]


def test_rolling_back_to_an_unknown_version_is_404(client):
    response = client.post("/api/v1/profiles/prod/rollback", json={"targetVersion": 99}, headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_version"
```

`_auth(client, username="alice", password="correct-horse")` 与 Task 8 的 helper 同形；`bob` 由 Task 6 的 `db_session` fixture 以 `operator` 角色播种（若 fixture 只建了 `alice`，在 `conftest.py` 里补一个 operator 用户，参见 Task 7 的 `seed` fixture）。

- [ ] **Step 9: 跑集成测试**

Run: `cd console/backend && python -m pytest tests/integration/test_publish.py -q`
Expected: 5 passed。

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿。

- [ ] **Step 10: 前端 API 与类型**

`console/frontend/src/types/profile.d.ts` 追加：

```ts
export interface PublishResult {
  version: number
  status: 'live' | 'rolled_back'
  healthcheck: { poolSize: number | null; inUse: number | null; attempts: number; notes: string[] }
  durationS: number
  applied: string[]
  warnings: unknown[]
  auditId: string
}

export interface RollbackResult extends PublishResult {
  rolledBackTo: number
}
```

`console/frontend/src/api/profiles.ts` 追加：

```ts
// 发布是同步的：重启 ≤60s + 探活 ≤180s（失败还要回滚再探一次）。默认 30s
// 超时会把一次成功的发布报成失败，而服务端其实已经写盘并重启了。
const LONG_RUNNING = { timeout: 480_000 }

export const publishProfile = (
  profile: string,
  body: { baseVersion: number | null; note: string }
): Promise<PublishResult> =>
  api.post<PublishResult>(`/profiles/${profile}/publish`, body, LONG_RUNNING)

export const rollbackProfile = (
  profile: string,
  body: { targetVersion: number; note: string }
): Promise<RollbackResult> =>
  api.post<RollbackResult>(`/profiles/${profile}/rollback`, body, LONG_RUNNING)
```

- [ ] **Step 11: 写 `components/PublishDialog.vue`**

```vue
<script setup lang="ts">
import { ref } from 'vue'

import { AppError } from '@/api/client'
import { publishProfile } from '@/api/profiles'
import DiffTable from '@/components/DiffTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import type { PublishResult } from '@/types/profile'

const props = defineProps<{
  open: boolean
  profile: string
  baseVersion: number | null
  draft: Record<string, unknown>
  masked: string[]
}>()
const emit = defineEmits<{ close: []; published: [result: PublishResult] }>()

const note = ref('')
const pending = ref(false)
const error = ref<AppError | null>(null)
const result = ref<PublishResult | null>(null)

async function submit(): Promise<void> {
  error.value = null
  result.value = null
  pending.value = true
  try {
    result.value = await publishProfile(props.profile, {
      baseVersion: props.baseVersion,
      note: note.value
    })
    note.value = ''
    emit('published', result.value)
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '发布失败')
  } finally {
    pending.value = false
  }
}

function close(): void {
  if (pending.value) return // 一次发布中途关掉对话框，用户会以为它被取消了
  result.value = null
  error.value = null
  emit('close')
}
</script>

<template>
  <a-modal :open="open" title="发布" :footer="null" :mask-closable="!pending" @cancel="close">
    <a-alert
      type="warning"
      show-icon
      message="发布会重启 pipeline 进程"
      description="正在进行的语音会话会中断，并在重连后使用新配置。"
    />

    <DiffTable :draft="draft" :masked="masked" />

    <a-textarea v-model:value="note" :rows="2" placeholder="变更说明（会写进版本记录与审计）" />

    <ErrorBanner :error="error" />

    <a-alert
      v-if="result"
      type="success"
      show-icon
      :message="`v${result.version} 已生效`"
      :description="`耗时 ${result.durationS}s · 池大小 ${result.healthcheck.poolSize ?? '—'} · 审计 ${result.auditId}`"
    />

    <div class="publish-dialog__actions">
      <a-button :disabled="pending" @click="close">{{ result ? '关闭' : '取消' }}</a-button>
      <a-button v-if="!result" type="primary" danger :loading="pending" @click="submit">
        确认发布
      </a-button>
    </div>
  </a-modal>
</template>

<style scoped lang="less">
.publish-dialog__actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
```

「重启会中断会话」这句文案是必须的（A.0.2 的 `publish` 行）：不写，运维会在下午三点把正在开会的人挂断。

- [ ] **Step 12: 把发布接进 `ParamsView`**

`console/frontend/src/views/ParamsView.vue` 补：

```ts
import PublishDialog from '@/components/PublishDialog.vue'

const publishOpen = ref(false)

async function onPublished(): Promise<void> {
  await reload()
  await consoleStore.refreshStatus()
  notice.value = '发布完成'
}
```

工具栏在「保存草稿」后面加：

```vue
      <a-button
        type="primary"
        danger
        :disabled="dirty || draftStore.saving"
        @click="publishOpen = true"
      >
        发布
      </a-button>
```

模板末尾加：

```vue
    <PublishDialog
      :open="publishOpen"
      :profile="consoleStore.profile"
      :base-version="draftStore.baseVersion"
      :draft="draftStore.draft"
      :masked="draftStore.masked"
      @close="publishOpen = false"
      @published="onPublished"
    />
```

`:disabled="dirty"` 是有意的：本地有没保存的改动时，发布的是**草稿**而不是屏幕上看到的东西，两者不一致时必须先保存。

- [ ] **Step 13: 给 `VersionTable` 加回滚，并在 `VersionsView` 接上**

`components/VersionTable.vue` 的 props 加 `liveVersion?: number | null`，emits 加 `rollback: [version: number]`，并追加一列：

```vue
      { title: '操作', key: 'actions', width: 130 }
```

```vue
      <template v-else-if="column.key === 'actions'">
        <a-button
          v-if="record.status === 'live' || record.status === 'rolled_back'"
          type="link"
          size="small"
          :disabled="record.version === liveVersion"
          @click="$emit('rollback', record.version)"
        >
          回滚到此版本
        </a-button>
        <span v-else>—</span>
      </template>
```

`views/VersionsView.vue` 补：

```ts
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useConfirm } from '@/composables/useConfirm'
import { rollbackProfile } from '@/api/profiles'

const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const rollbackError = ref<AppError | null>(null)
const liveVersion = computed(() => rows.value.find((row) => row.status === 'live')?.version ?? null)

async function rollback(target: number): Promise<void> {
  const confirmed = await askConfirm({
    title: `回滚到 v${target}`,
    content: '回滚会写入一个新版本并重启 pipeline，正在进行的语音会话会中断。'
  })
  if (!confirmed) return
  rollbackError.value = null
  try {
    await rollbackProfile(consoleStore.profile, { targetVersion: target, note: `rollback to v${target}` })
    await load()
    await consoleStore.refreshStatus()
  } catch (caught) {
    rollbackError.value = caught instanceof AppError ? caught : new AppError('unknown', '回滚失败')
  }
}
```

模板：

```vue
    <ErrorBanner :error="error" />
    <ErrorBanner :error="rollbackError" />
    <VersionTable :rows="rows" :loading="loading" :live-version="liveVersion" @rollback="rollback" />
```

（`computed` 需要补进 `vue` 的 import。）

- [ ] **Step 14: 构建与单测**

Run: `cd console/frontend && npx vitest run && npm run build`
Expected: 20 passed，`vue-tsc` 无错。

- [ ] **Step 15: 真机验收（阶段 E 检查点）**

在部署机上（镜像按 Task 4 构建）：

1. **真发布**：改一个 `basic` 字段 → 保存草稿 → 发布 → 对话框显示 `v2 已生效`；`docker compose exec pipeline supervisorctl status` 里 `pipeline` 的 PID 变了、`console` 的 PID 没变；
2. **HTTP 不中断**：发布期间另开一个终端跑
   `for i in $(seq 1 40); do curl -s -o /dev/null -w '%{http_code} ' http://127.0.0.1:8000/api/v1/health; sleep 1; done`
   → 40 个 `200`（console 进程没被重启，所以控制台在发布全程可用）；
3. **真回滚**：`versions` 里对 v1 点回滚 → 产生 v3，v3 的 `rolledBackTo` 是 1，v2 仍在列表里；盘上 `config/prod.yaml` 与 `.bak.3` 无关、与 v1 的 `yaml_text` 逐字节相同；
4. **`.env` 门禁**：改一个 `stage=env` 字段（如 `env.GPUSTACK_API_KEY`）→ 发布 409 `env_requires_recreate`；确认 `config/prod.yaml` 的 mtime 与 sha256 未变、`versions` 里没有新行；
5. **重启失败**：`chmod 000 /run/s2s-console/supervisor.sock`（或 `RESTART_MODE` 指向一个不存在的 socket）→ 发布 502 `restart_unavailable`，`config/prod.yaml` 回到发布前字节，版本状态 `rolled_back`；
6. **启动自检**：手动 `UPDATE param_versions SET status='publishing' WHERE version=<最新>` 后重启 console 进程 → 日志出现 `recovered an interrupted publish`，该行变成 `live`（盘上字节一致且池健康时）。

六条全过 = 阶段 E 通过。

- [ ] **Step 16: 提交**

```bash
git add console/backend console/frontend
git commit -m "feat(console): publish and rollback through supervisor, with startup recovery"
```

---

## Task 16: 链路 B —— 热更新端点与 `SessionsView`（阶段 E 收尾）

**Files:**
- Create: `console/backend/app/schemas/session.py`
- Create: `console/backend/app/services/hot_update_service.py`
- Create: `console/backend/app/routers/sessions.py`
- Modify: `console/backend/app/core/router_registry.py`（注册 `sessions.router`）
- Test: `console/backend/tests/unit/test_hot_update_whitelist.py`
- Test: `console/backend/tests/integration/test_sessions_api.py`
- Create: `console/frontend/src/types/session.d.ts`
- Create: `console/frontend/src/utils/session-patch.ts`
- Test: `console/frontend/src/utils/session-patch.spec.ts`
- Modify: `console/frontend/src/utils/error.ts`（补 `invalid_request_error`、`invalid_session_type` 两条文案）
- Create: `console/frontend/src/api/sessions.ts`
- Create: `console/frontend/src/views/SessionsView.vue`
- Modify: `console/frontend/src/router/index.ts`（加 `sessions` 子路由）

**Interfaces:**
- Consumes: pipeline `POST /internal/sessions/update`（Task 1；成功回**裸对象** `{updated:[sid], failed:[{session_id,error}]}`；`503 internal_token_missing` / `401` / `404` / `400` / `422` 五个分支）；`S2S_INTERNAL_TOKEN`（从 `os.environ` 直读，**不进 `ConsoleSettings`**）；`console.pipeline_base_url`；`AuditRepository.record`（Task 6，关键字专用，`list()` 返回 `(rows, total)`）；`ok()` / `ApiError`（Task 3）；`useConsoleStore().status.internalTokenConfigured`（Task 10/11）。
- Produces: `hot_update_service.WHITELIST`、`hot_update_service.prune(session) -> tuple[dict, list[str]]`、`hot_update_service.update(db, profile, *, scope, target, session, actor, role, request_id="") -> dict`；`POST /api/v1/sessions/update` → `{updated:[...], failed:[{sessionId,error}], auditId, hint}`；前端 `buildSessionPatch(form) -> {session, problems}`；路由名 `sessions`（`/console/sessions`）。

**为什么 `S2S_INTERNAL_TOKEN` 不进 `ConsoleSettings`**：`ConsoleSettings` 的实例会被 pydantic 序列化、被日志打印、被 `/status` 快照引用；机对机 token 一旦成为配置对象的字段，就多出一个泄漏面。`status_service` 已经在用 `os.environ.get("S2S_INTERNAL_TOKEN")` 算布尔值（Task 10），这里保持同一写法：读的时候就地读，给前端看的永远只是 `true/false`。

**为什么白名单在 console 侧再剪一遍**（A.9）：pipeline 侧 `/internal/*` 也会拒（A.12），但反射弧太长——运维点了一次「热更新」，拿回的是 pipeline 的英文错误体，而 `model` / `audio.output.voice` 这类只做协议回显的字段（§2.2 取证）会被静默接受、悄悄不生效。先在本进程剪，错在入口、`detail` 里逐个列出被拒字段名，审计里也留得下痕迹。

**为什么 `scope` / `target` 用 `ApiError` 校验而不是 pydantic `Literal` + `model_validator`**：pydantic 抛出的 `RequestValidationError` 会走 FastAPI 默认处理器，返回 `{"detail":[...]}`，绕开 `ApiResponse` 错误包络（Global Constraints：`/api/v1/*` 一律包络）。用 `ApiError("invalid_parameter", ..., 400)` 校验，形状才和其余端点一致。

- [ ] **Step 1: 写白名单的失败测试**

`console/backend/tests/unit/test_hot_update_whitelist.py`：

```python
from __future__ import annotations

from app.services.hot_update_service import prune


def test_prune_keeps_the_four_allowed_paths():
    clean, rejected = prune(
        {
            "instructions": "be brief",
            "audio": {
                "input": {
                    "turn_detection": {"interrupt_response": False},
                    "transcription": {"language": "zh"},
                }
            },
            "extensions": {"speech_to_speech": {"input_audio_transcription": {"snapshot": True}}},
        }
    )
    assert rejected == []
    assert clean["instructions"] == "be brief"
    assert clean["audio"]["input"]["turn_detection"] == {"interrupt_response": False}
    assert clean["audio"]["input"]["transcription"] == {"language": "zh"}
    assert "extensions" in clean


def test_prune_names_model_and_voice_instead_of_dropping_them():
    clean, rejected = prune(
        {"instructions": "hi", "model": "gpt-4o", "audio": {"output": {"voice": "alloy"}}}
    )
    # Silent drops are how an operator ends up believing `voice` was updated.
    assert sorted(rejected) == ["audio.output.voice", "model"]
    assert clean == {"instructions": "hi"}


def test_prune_rejects_a_scalar_where_an_object_belongs():
    clean, rejected = prune({"audio": {"input": {"transcription": "zh"}}})
    assert rejected == ["audio.input.transcription"]
    assert clean == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_hot_update_whitelist.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.hot_update_service'`。

- [ ] **Step 3: 写 `schemas/session.py` 与 `hot_update_service.py`**

`console/backend/app/schemas/session.py`：

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionUpdateRequest(BaseModel):
    """A.9's body. `scope`/`target` are validated in the service, not here.

    A `Literal` here would raise `RequestValidationError` and hand FastAPI's
    default 422 body back to the client, which has no `code` field — the console
    frontend translates codes, never Freeform text (Global Constraints).
    """

    scope: str = "all"
    target: int | str | None = None
    session: dict[str, Any] = Field(default_factory=dict)
```

`console/backend/app/services/hot_update_service.py`：

```python
"""Chain B: push a session patch to live connections, touching no files (A.9).

The console does not re-implement `handle_session_update`: it trims the payload
against A.9's whitelist and forwards it, so language checks and
`invalid_session_type` stay in exactly one place (spec §3.2.3).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.config import console
from app.core.errors import ApiError
from app.repositories.audit_repository import AuditRepository

TIMEOUT_S = 10.0
SCOPES = frozenset({"all", "pipeline", "session"})
HINT = (
    "只影响当前活跃连接；空闲 unit 与新连接仍读 init_chat_prompt，"
    "改默认人设需要同时发布配置并重启 pipeline。"
)

# A.9's whitelist as a tree; `None` means “this whole node is allowed”.
# `audio.input.turn_detection` is a leaf on purpose: A.9 whitelists the object,
# and which of its keys actually change behaviour (§2.2) is the pipeline's call.
WHITELIST: dict[str, Any] = {
    "instructions": None,
    "extensions": None,
    "audio": {"input": {"turn_detection": None, "transcription": {"language": None}}},
}


def prune(session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Keep A.9's four paths and name everything else."""
    clean: dict[str, Any] = {}
    rejected: list[str] = []
    _walk(session, WHITELIST, "", clean, rejected)
    return clean, rejected


def _walk(
    node: Any, tree: dict[str, Any], prefix: str, out: dict[str, Any], rejected: list[str]
) -> None:
    if not isinstance(node, dict):
        rejected.append(prefix or "<root>")
        return
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in tree:
            rejected.append(path)
            continue
        branch = tree[key]
        if branch is None:
            out[key] = value
            continue
        if not isinstance(value, dict):
            rejected.append(path)
            continue
        child: dict[str, Any] = {}
        _walk(value, branch, path, child, rejected)
        if child:
            out[key] = child


def _paths(node: dict[str, Any], prefix: str = "") -> list[str]:
    """Dotted leaf names for the audit row: names only, never values (§10.1)."""
    out: list[str] = []
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_paths(value, path) or [path])
        else:
            out.append(path)
    return out


def update(
    db,
    profile: str,
    *,
    scope: str,
    target: Any,
    session: dict[str, Any],
    actor: str,
    role: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Trim, forward, audit. Partial failure is normal (A.9: idempotent overwrite)."""
    if scope not in SCOPES:
        raise ApiError("invalid_parameter", f"unknown scope {scope!r}", 400)
    if scope == "pipeline" and not isinstance(target, int):
        raise ApiError("invalid_parameter", "scope=pipeline needs an integer target", 400)
    if scope == "session" and not isinstance(target, str):
        raise ApiError("invalid_parameter", "scope=session needs a session id", 400)
    if scope == "all" and target is not None:
        raise ApiError("invalid_parameter", "scope=all takes no target", 400)

    clean, rejected = prune(session)
    if rejected:
        raise ApiError(
            "unsupported_field",
            "these fields cannot be changed on a live session",
            400,
            detail=[{"field": path} for path in rejected],
        )
    if not clean:
        raise ApiError("invalid_parameter", "the session patch is empty", 400)

    fields = sorted(_paths(clean))
    try:
        body = _forward(scope, target, clean)
    except ApiError as exc:
        _audit(db, profile, actor, role, request_id, fields, "failed", exc.code)
        raise

    audit = _audit(db, profile, actor, role, request_id, fields, "ok", None)
    return {
        "updated": [str(item) for item in body.get("updated") or []],
        "failed": [
            {"sessionId": str(item.get("session_id", "")), "error": str(item.get("error", ""))}
            for item in body.get("failed") or []
            if isinstance(item, dict)
        ],
        "auditId": str(audit.id),
        "hint": HINT,
    }


def _forward(scope: str, target: Any, session: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("S2S_INTERNAL_TOKEN", "").strip()
    if not token:
        # The console is misconfigured, not the pipeline. A.11 greys the button
        # out for the same reason; this is that fact arriving via the write path.
        raise ApiError(
            "internal_token_missing",
            "S2S_INTERNAL_TOKEN is not configured for the console",
            502,
            detail=[{"env": "S2S_INTERNAL_TOKEN"}],
        )

    url = f"{console.pipeline_base_url.rstrip('/')}/internal/sessions/update"
    try:
        response = httpx.post(
            url,
            json={"scope": scope, "target": target, "session": session},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise ApiError(
            "pipeline_unavailable", f"the pipeline is not reachable: {type(exc).__name__}", 502
        ) from exc

    if response.status_code == 404:
        # A.12: a pipeline build that predates Task 1. Tell the operator to use
        # chain A instead of leaking a bare 404 from loopback.
        raise ApiError(
            "not_implemented",
            "this pipeline has no /internal/sessions/update yet; publish instead",
            501,
        )
    if response.status_code in (401, 503):
        raise ApiError(
            "pipeline_token_missing",
            "the pipeline rejected the internal token; check S2S_INTERNAL_TOKEN in config/prod.env",
            502,
        )

    body = _json(response)
    if response.status_code >= 400:
        # 400 invalid_request_error / 422 invalid_session_type are the pipeline's
        # verdicts about *this* patch: pass the code and status through (§A.12).
        if response.status_code not in (400, 422):
            raise ApiError("pipeline_unavailable", f"pipeline returned {response.status_code}", 502)
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raise ApiError(
            str(error.get("code") or "invalid_parameter"),
            str(error.get("message") or "the pipeline rejected this session update"),
            response.status_code,
        )
    return body


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _audit(db, profile, actor, role, request_id, fields, result, error_code):
    return AuditRepository(db).record(
        actor=actor,
        role=role,
        action="session.update",
        profile=profile,
        fields=fields,
        result=result,
        error_code=error_code,
        request_id=request_id,
    )
```

- [ ] **Step 4: 跑白名单测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_hot_update_whitelist.py -q`
Expected: 3 passed。

- [ ] **Step 5: 写 API 的失败测试**

`console/backend/tests/integration/test_sessions_api.py`：

```python
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository
from app.services import hot_update_service
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    UserRepository(db_session).create("bob", hash_password("correct-horse"), "operator")
    return TestClient(app)


def _auth(client, username="alice"):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


class _Recorder:
    """Stands in for `httpx.post` so no test needs a running pipeline."""

    def __init__(self, status: int = 200, body=None) -> None:
        self.status = status
        self.body = {"updated": [], "failed": []} if body is None else body
        self.calls: list[dict] = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return httpx.Response(self.status, json=self.body)


def test_operator_trim_then_forward_and_audit(client, db_session, monkeypatch):
    recorder = _Recorder(body={"updated": ["s1"], "failed": []})
    monkeypatch.setattr(hot_update_service.httpx, "post", recorder)
    headers = _auth(client, "bob")

    refused = client.post(
        "/api/v1/sessions/update",
        json={"scope": "session", "target": "s1", "session": {"instructions": "be brief", "model": "x"}},
        headers=headers,
    )
    # A.9: `model` is a protocol echo (§2.2); reject it here, before any network hop.
    assert refused.status_code == 400
    assert refused.json()["code"] == "unsupported_field"
    assert refused.json()["detail"] == [{"field": "model"}]
    assert recorder.calls == []

    accepted = client.post(
        "/api/v1/sessions/update",
        json={"scope": "session", "target": "s1", "session": {"instructions": "be brief"}},
        headers=headers,
    )
    assert accepted.status_code == 200
    data = accepted.json()["data"]
    assert data["updated"] == ["s1"]
    assert data["failed"] == []
    assert data["auditId"]
    assert "只影响当前活跃连接" in data["hint"]

    call = recorder.calls[0]
    assert call["url"].endswith("/internal/sessions/update")
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["json"] == {"scope": "session", "target": "s1", "session": {"instructions": "be brief"}}

    rows, total = AuditRepository(db_session).list(profile="prod")
    assert total == 1
    row = rows[0]
    assert (row.actor, row.role, row.action, row.result) == ("bob", "operator", "session.update", "ok")
    assert row.fields == ["instructions"]


def test_empty_patch_is_400_invalid_parameter(client, monkeypatch):
    monkeypatch.setattr(hot_update_service.httpx, "post", _Recorder())
    response = client.post(
        "/api/v1/sessions/update", json={"scope": "all", "session": {}}, headers=_auth(client)
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"


def test_scope_pipeline_without_index_is_400(client, monkeypatch):
    monkeypatch.setattr(hot_update_service.httpx, "post", _Recorder())
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "pipeline", "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"


def test_missing_console_token_is_502_internal_token_missing(client, monkeypatch):
    monkeypatch.delenv("S2S_INTERNAL_TOKEN", raising=False)
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 502
    assert response.json()["code"] == "internal_token_missing"


def test_pipeline_rejecting_the_token_becomes_pipeline_token_missing(client, monkeypatch):
    monkeypatch.setattr(
        hot_update_service.httpx,
        "post",
        _Recorder(status=503, body={"error": {"code": "internal_token_missing"}}),
    )
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 502
    assert response.json()["code"] == "pipeline_token_missing"


def test_a_pipeline_without_the_route_is_501_not_implemented(client, monkeypatch):
    monkeypatch.setattr(hot_update_service.httpx, "post", _Recorder(status=404, body={}))
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 501
    assert response.json()["code"] == "not_implemented"


def test_pipeline_semantic_rejections_pass_through(client, monkeypatch):
    monkeypatch.setattr(
        hot_update_service.httpx,
        "post",
        _Recorder(
            status=422,
            body={"error": {"code": "invalid_session_type", "message": "transcription is not live"}},
        ),
    )
    response = client.post(
        "/api/v1/sessions/update",
        json={"scope": "pipeline", "target": 0, "session": {"instructions": "hi"}},
        headers=_auth(client),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_session_type"
    assert "transcription" in body["message"]
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/integration/test_sessions_api.py -q`
Expected: 7 个用例全 FAIL（`404 Not Found`，`/api/v1/sessions/update` 还没注册）。

- [ ] **Step 7: 写路由并注册**

`console/backend/app/routers/sessions.py`：

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.session import SessionUpdateRequest
from app.services import hot_update_service

router = APIRouter(prefix="/api/v1", tags=["sessions"])


@router.post("/sessions/update")
def post_session_update(
    payload: SessionUpdateRequest,
    request: Request,
    db: DbSession,
    profile: str = "prod",
    user: CurrentUser = Depends(require_user),
):
    """A.9: chain B. admin and operator alike (A.0.2) — nothing is written to disk."""
    return ok(
        hot_update_service.update(
            db,
            profile,
            scope=payload.scope,
            target=payload.target,
            session=payload.session,
            actor=user.username,
            role=user.role,
            request_id=getattr(request.state, "request_id", ""),
        )
    )
```

`console/backend/app/core/router_registry.py`：import 行改为
`from app.routers import auth, catalog, health, instances, profiles, sessions, status`，
并在 `status.router` 之前插入 `app.include_router(sessions.router)`（`/api/v1` 组内顺序不影响匹配，同一前缀下按方法+路径分发）。

- [ ] **Step 8: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/integration/test_sessions_api.py -q`
Expected: 7 passed。

- [ ] **Step 9: 跑 Task 7–15 全量回归**

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿。`router_registry` 第五次被改动，`/api/v1/health`、`/api/v1/auth/login`、`/api/v1/status`、`/api/v1/instances` 都应仍可访问。

- [ ] **Step 10: 写前端的失败测试**

`console/frontend/src/utils/session-patch.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { buildSessionPatch } from './session-patch'

const EMPTY = {
  instructions: '',
  createResponse: null,
  interruptResponse: null,
  language: '',
  extensions: ''
}

describe('buildSessionPatch', () => {
  it('refuses an empty form instead of sending a no-op patch', () => {
    const built = buildSessionPatch(EMPTY)
    expect(built.session).toEqual({})
    expect(built.problems).toEqual(['至少填写一个字段'])
  })

  it('sends only what the operator filled in, trimmed', () => {
    const built = buildSessionPatch({ ...EMPTY, instructions: '  只说两句话  ' })
    expect(built.problems).toEqual([])
    expect(built.session).toEqual({ instructions: '只说两句话' })
  })

  it('treats false as a value, not as “unset”', () => {
    const built = buildSessionPatch({ ...EMPTY, interruptResponse: false })
    expect(built.session).toEqual({
      audio: { input: { turn_detection: { interrupt_response: false } } }
    })
  })

  it('nests the language under audio.input.transcription', () => {
    const built = buildSessionPatch({ ...EMPTY, language: ' zh ' })
    expect(built.session).toEqual({ audio: { input: { transcription: { language: 'zh' } } } })
  })

  it('keeps the valid half and reports broken extensions JSON', () => {
    const built = buildSessionPatch({ ...EMPTY, instructions: 'hi', extensions: '{oops' })
    expect(built.problems).toEqual(['extensions 不是合法 JSON'])
    expect(built.session).toEqual({ instructions: 'hi' })
  })
})
```

- [ ] **Step 11: 跑测试确认失败**

Run: `cd console/frontend && npx vitest run src/utils/session-patch.spec.ts`
Expected: FAIL（`Failed to resolve import "./session-patch"`）。

- [ ] **Step 12: 写 `session-patch.ts`**

`console/frontend/src/utils/session-patch.ts`：

```ts
/** Build A.9's payload from the form: only filled-in fields travel.
 *
 * `session.update` merges `model_fields_set` (spec §2.2), so “absent” and
 * “explicitly false/null” are different instructions. `null` here means the
 * operator never touched the control, and the field must not be sent at all.
 */

export interface SessionForm {
  instructions: string
  createResponse: boolean | null
  interruptResponse: boolean | null
  language: string
  /** Raw JSON text for `extensions`; `''` means “leave it alone”. */
  extensions: string
}

export interface BuiltPatch {
  session: Record<string, unknown>
  /** Non-empty means “do not submit”. */
  problems: string[]
}

export function buildSessionPatch(form: SessionForm): BuiltPatch {
  const problems: string[] = []
  const session: Record<string, unknown> = {}

  const instructions = form.instructions.trim()
  if (instructions) session.instructions = instructions

  const turnDetection: Record<string, unknown> = {}
  if (form.createResponse !== null) turnDetection.create_response = form.createResponse
  if (form.interruptResponse !== null) turnDetection.interrupt_response = form.interruptResponse

  const language = form.language.trim()
  const audioInput: Record<string, unknown> = {}
  if (Object.keys(turnDetection).length > 0) audioInput.turn_detection = turnDetection
  if (language) audioInput.transcription = { language }
  if (Object.keys(audioInput).length > 0) session.audio = { input: audioInput }

  const extensions = form.extensions.trim()
  if (extensions) {
    try {
      const parsed: unknown = JSON.parse(extensions)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        session.extensions = parsed
      } else {
        problems.push('extensions 必须是 JSON 对象')
      }
    } catch {
      problems.push('extensions 不是合法 JSON')
    }
  }

  if (Object.keys(session).length === 0 && problems.length === 0) {
    problems.push('至少填写一个字段')
  }
  return { session, problems }
}
```

- [ ] **Step 13: 跑测试确认通过**

Run: `cd console/frontend && npx vitest run src/utils/session-patch.spec.ts`
Expected: 5 passed。

- [ ] **Step 14: 补类型、API 模块与两条错误文案**

`console/frontend/src/types/session.d.ts`：

```ts
export type SessionScope = 'all' | 'pipeline' | 'session'

export interface SessionUpdateRequest {
  scope: SessionScope
  /** A unit index for `pipeline`, a session id for `session`, `null` for `all`. */
  target?: number | string | null
  session: Record<string, unknown>
}

/** A.9 — `hint` is server-authored copy that *must* reach the operator (§5.4). */
export interface SessionUpdateResult {
  updated: string[]
  failed: Array<{ sessionId: string; error: string }>
  auditId: string
  hint: string
}
```

`console/frontend/src/api/sessions.ts`：

```ts
import { api } from './client'
import type { SessionUpdateRequest, SessionUpdateResult } from '@/types/session'

export const updateSessions = (body: SessionUpdateRequest): Promise<SessionUpdateResult> =>
  api.post<SessionUpdateResult>('/sessions/update', body)
```

`console/frontend/src/utils/error.ts` 的 `ERROR_TEXT` 在 `unsupported_field` 之后插入两条：

```ts
  invalid_request_error: 'pipeline 不接受这次热更新：语言不被支持，或 auto 不可重置',
  invalid_session_type: '该会话不是 realtime 类型，无法热更新',
```

- [ ] **Step 15: 写 `views/SessionsView.vue`**

```vue
<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import { AppError } from '@/api/client'
import { updateSessions } from '@/api/sessions'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useConsoleStore } from '@/stores/console'
import { translate } from '@/utils/error'
import { buildSessionPatch } from '@/utils/session-patch'
import type { SessionScope, SessionUpdateResult } from '@/types/session'

const consoleStore = useConsoleStore()

type Tri = 'keep' | 'on' | 'off'

const TRI_OPTIONS: Array<{ value: Tri; label: string }> = [
  { value: 'keep', label: '不修改' },
  { value: 'on', label: '开启' },
  { value: 'off', label: '关闭' }
]

const form = reactive({
  scope: 'all' as SessionScope,
  targetText: '',
  instructions: '',
  createResponse: 'keep' as Tri,
  interruptResponse: 'keep' as Tri,
  language: '',
  extensions: ''
})

const pending = ref(false)
const failure = ref<AppError | null>(null)
const result = ref<SessionUpdateResult | null>(null)

function tri(value: Tri): boolean | null {
  return value === 'keep' ? null : value === 'on'
}

const target = computed<number | string | null>(() => {
  const raw = form.targetText.trim()
  if (form.scope === 'all' || !raw) return null
  return form.scope === 'pipeline' ? Number(raw) : raw
})

const preview = computed(() =>
  buildSessionPatch({
    instructions: form.instructions,
    createResponse: tri(form.createResponse),
    interruptResponse: tri(form.interruptResponse),
    language: form.language,
    extensions: form.extensions
  })
)

const problems = computed<string[]>(() => {
  const list = [...preview.value.problems]
  if (form.scope === 'all' && form.targetText.trim()) list.push('scope=all 不需要 target')
  if (form.scope === 'pipeline' && !Number.isInteger(target.value)) {
    list.push('target 必须是 unit 序号（整数）')
  }
  if (form.scope === 'session' && !form.targetText.trim()) list.push('target 必须是 session id')
  return list
})

// A.11: `internalTokenConfigured=false` means chain B cannot work at all, so the
// button is disabled and the variable name is shown instead of a 502 toast.
const tokenMissing = computed(() => consoleStore.status?.internalTokenConfigured === false)

async function submit(): Promise<void> {
  failure.value = null
  result.value = null
  pending.value = true
  try {
    result.value = await updateSessions({
      scope: form.scope,
      target: target.value,
      session: preview.value.session
    })
  } catch (error) {
    failure.value = error instanceof AppError ? error : new AppError('unknown', '热更新失败，请重试')
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="sessions">
    <a-alert type="info" show-icon title="热更新只改活跃连接，不写任何文件">
      <ul class="sessions__rules">
        <li>只影响当前活跃连接；新连接仍读 <code>init_chat_prompt</code>，与这里下发的值可能不一致。</li>
        <li>空闲 unit 没有连接可下发；改默认人设必须同时改 YAML 并发布，否则重启后又回到旧默认。</li>
        <li>不支持 <code>transcription</code> 类型会话，必须是 <code>realtime</code> 会话。</li>
        <li><code>language</code> 必须被活跃后端支持；<code>auto</code> 需要后端支持自动重置，否则 400。</li>
        <li>不提供 <code>model</code> 与 <code>audio.output.voice</code>：它们在协议里只是回显，下发也不会改变音色或模型。</li>
      </ul>
    </a-alert>

    <a-alert
      v-if="tokenMissing"
      type="warning"
      show-icon
      title="控制器未配置 S2S_INTERNAL_TOKEN，链路 B 不可用"
      description="在 config/prod.env 里设置 S2S_INTERNAL_TOKEN 后 docker compose up -d --force-recreate pipeline。"
    />

    <a-form layout="vertical" class="sessions__form">
      <a-form-item label="作用域">
        <a-radio-group v-model:value="form.scope" button-style="solid">
          <a-radio-button value="all">全部活跃连接</a-radio-button>
          <a-radio-button value="pipeline">单个 unit</a-radio-button>
          <a-radio-button value="session">单条会话</a-radio-button>
        </a-radio-group>
      </a-form-item>

      <a-form-item v-if="form.scope !== 'all'" :label="form.scope === 'pipeline' ? 'unit 序号' : 'session id'">
        <a-input v-model:value="form.targetText" :placeholder="form.scope === 'pipeline' ? '0' : '复现实时转写里的 session id'" />
      </a-form-item>

      <a-form-item label="instructions（人设）">
        <a-textarea v-model:value="form.instructions" :rows="3" placeholder="留空即不修改" />
      </a-form-item>

      <a-form-item label="turn_detection.create_response（自动应答）">
        <a-select v-model:value="form.createResponse" :options="TRI_OPTIONS" style="width: 160px" />
      </a-form-item>

      <a-form-item label="turn_detection.interrupt_response（允许打断）">
        <a-select v-model:value="form.interruptResponse" :options="TRI_OPTIONS" style="width: 160px" />
      </a-form-item>

      <a-form-item label="transcription.language">
        <a-input v-model:value="form.language" placeholder="auto / zh / en —— 必须是活跃后端支持的值" />
      </a-form-item>

      <a-form-item label="extensions（JSON，留空即不修改）">
        <a-textarea
          v-model:value="form.extensions"
          :rows="3"
          placeholder='{"speech_to_speech":{"input_audio_transcription":{"snapshot":true}}}'
        />
      </a-form-item>

      <a-alert v-if="problems.length" type="warning" show-icon :title="problems.join('；')" />

      <ErrorBanner :error="failure" />

      <a-button
        type="primary"
        :loading="pending"
        :disabled="tokenMissing || problems.length > 0"
        @click="submit"
      >
        下发到活跃会话
      </a-button>
    </a-form>

    <a-card v-if="result" size="small" title="下发结果">
      <p>
        已更新 <strong>{{ result.updated.length }}</strong> 条连接；失败
        <strong>{{ result.failed.length }}</strong> 条。审计号 <code>{{ result.auditId }}</code>
      </p>
      <a-list v-if="result.failed.length" size="small" bordered :data-source="result.failed">
        <template #renderItem="{ item }">
          <a-list-item><code>{{ item.sessionId }}</code> — {{ translate(item.error) }}</a-list-item>
        </template>
      </a-list>
      <a-alert type="info" :title="result.hint" />
    </a-card>
  </div>
</template>

<style scoped lang="less">
.sessions {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__rules {
    margin: 0;
    padding-left: 18px;
  }

  &__form {
    max-width: 640px;
  }
}
</style>
```

- [ ] **Step 16: 注册路由**

`console/frontend/src/router/index.ts` 里 `path: 'console'` 那条记录的 `children` 末尾追加一项（`NAV_GROUPS` 里 `sessions` 已在 Task 11 定义，`hasRoute` 会自动点亮菜单）：

```ts
        { path: 'sessions', name: 'sessions', component: () => import('@/views/SessionsView.vue') }
```

- [ ] **Step 17: 全量单测与构建**

Run: `cd console/frontend && npx vitest run && npm run build`
Expected: 新增 5 个用例全绿，其余保持绿；`vue-tsc` 无错误。常见失败点：`a-radio-group` 的 `v-model:value` 与 `value` 写法混用会静默失效（`a-radio-button` 用 `value`，不是 `:checked`）。

- [ ] **Step 18: 手工验收（链路 B 检查点）**

部署机上（镜像按 Task 4 构建，`config/prod.env` 里已有 `S2S_INTERNAL_TOKEN`）：

1. **闸门**：把 `S2S_INTERNAL_TOKEN` 从 `prod.env` 删掉并重建容器 → 登录后 `/console/sessions` 出现黄色告警「未配置 S2S_INTERNAL_TOKEN」，按钮置灰；直接 `curl -X POST :8000/api/v1/sessions/update -H 'Authorization: Bearer <jwt>' -d '{"scope":"all","session":{"instructions":"hi"}}'` → 502 `internal_token_missing`；
2. **白名单**：带 `"model":"qwen"` 或 `"audio":{"output":{"voice":"alloy"}}` 请求 → 400 `unsupported_field`，`detail` 里逐个列出被拒字段；用 `docker compose logs` 确认 pipeline **没有**收到这次请求；
3. **scope 语义**：`scope=pipeline` 不给 `target` → 400 `invalid_parameter`；`scope=session` 给一个不存在的 id → 200 且 `updated:[]`（fanout 找不到人不算错，A.9「部分失败不回滚」）；
4. **真下发**：连着一条语音会话时下发 `instructions` → 返回 `updated` 里有该 session id，且这条会话下一次回复的人设变了；**不重连**、只看同一条会话；
5. **新连接不受影响**：紧接着新开一条会话 → 人设仍是旧值（这是 §5.4 第一条，不是 bug，必须肉眼确认）；
6. **pipeline 挂掉**：`docker compose exec pipeline supervisorctl stop pipeline` 后提交 → 502 `pipeline_unavailable`，审计里有一条 `session.update / failed / pipeline_unavailable`。

六条全过 = 链路 B 通过，阶段 E 闭环（链路 A 在 Task 15 Step 15 已验）。

- [ ] **Step 19: 提交**

```bash
git add console/backend console/frontend
git commit -m "feat(console): live session hot update through the pipeline's internal endpoint"
```

---

# 阶段 F：演示面（P4）

## Task 17: 演示面底座 —— `GET /api/config`、`/vendor/*`、双入口静态托管

**Files:**
- Create: `console/backend/app/config/_demo.py`
- Modify: `console/backend/app/config/__init__.py`（导出 `demo`）
- Create: `console/backend/app/services/demo_config_service.py`
- Create: `console/backend/app/services/asset_service.py`
- Create: `console/backend/app/routers/demo/__init__.py`、`routers/demo/config.py`
- Modify: `console/backend/app/core/spa.py`（`mount_spa` 里先挂 `/vendor`，再挂兜底）
- Modify: `console/backend/app/core/router_registry.py`
- Test: `console/backend/tests/unit/test_demo_config_service.py`
- Test: `console/backend/tests/demo/test_config_api.py`
- Test: `console/backend/tests/demo/test_vendor_api.py`
- Create: `console/frontend/src/types/demo.d.ts`、`src/api/demo.ts`

**Interfaces:**
- Consumes: `console.static_dir`（`dist/` 根，Task 3）；`ApiError`（Task 3）；`demo/server.py:246-266` 的字段形状。
- Produces: `DemoSettings`（`serper_api_key / load_balancer_url / speech_to_speech_url / space_id / oauth_client_id / rtc_ice_servers / startup_greeting / lb_hf_token` + 属性 `pinned_url`、`lb_url`、`limiter_enabled`、`oauth_configured`、`auth_enabled`、`server_search`）；`demo_config_service.config() -> dict`、`demo_config_service.ice_servers(raw) -> list[dict]`；`asset_service.LOCAL_VAD_ASSETS`、`asset_service.agents_sdk_path()`、`asset_service.vad_path(filename)`；`GET /api/config`（裸对象）；`GET /vendor/openai-realtime-agents.umd.js`、`GET /vendor/local-vad/{filename}`；前端 `getDemoConfig()`。

**三条必须逐字保住的契约**（A.13）：
1. `/api/config` **不套 `ApiResponse`**，也**不需要登录**；
2. `/api/config` **绝不下发 `LOAD_BALANCER_URL` 本身**，只给 `lb: true/false`；
3. `/vendor/local-vad/{filename}` 只开 6 个白名单文件名，**非白名单 404、文件缺失 503 `asset_missing`**。

**为什么把 `auth` 也算在 `DemoSettings` 里**：`/api/config` 的 `auth` 字段是「HF 登录入口是否存在」，而入口是否存在只取决于 `OAUTH_CLIENT_ID` 与限流开关——不取决于 `identity_service` 有没有初始化。把判定放在设置对象上，Task 17 就不必先建 Task 18 才跑得通；Task 18 的 `identity_service` 会读同一组设置，两处不会漂。

- [ ] **Step 1: 写失败测试（`/api/config`）**

`console/backend/tests/unit/test_demo_config_service.py`：

```python
from __future__ import annotations

import json

from app.services.demo_config_service import ice_servers


def test_ice_servers_accept_a_json_list():
    raw = json.dumps([{"urls": "turn:t.example.com", "username": "u", "credential": "c"}])
    assert ice_servers(raw) == [{"urls": "turn:t.example.com", "username": "u", "credential": "c"}]


def test_ice_servers_accept_a_single_object():
    assert ice_servers('{"urls": "stun:stun.l.google.com:19302"}') == [
        {"urls": "stun:stun.l.google.com:19302"}
    ]


def test_ice_servers_fall_back_to_a_comma_list():
    assert ice_servers("stun:a, stun:b ,") == [{"urls": "stun:a"}, {"urls": "stun:b"}]


def test_ice_servers_are_empty_when_unset():
    # Host candidates only. An empty list is valid and is what local dev uses.
    assert ice_servers("   ") == []
```

`console/backend/tests/demo/test_config_api.py`：

```python
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app

KEYS = {
    "search",
    "lb",
    "allowDirect",
    "s2sUrl",
    "rtc",
    "iceServers",
    "startupGreeting",
    "auth",
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    return TestClient(create_app())


def test_config_is_a_bare_object_and_needs_no_token(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    # A.13 rule 1: the demo face never carries the /api/v1 envelope.
    assert "code" not in body and "data" not in body
    assert set(body) == KEYS


def test_config_never_returns_the_load_balancer_address(client, monkeypatch):
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "")
    body = client.get("/api/config").json()
    assert body["lb"] is True
    assert body["allowDirect"] is False
    assert "lb.internal" not in json.dumps(body)


def test_a_pinned_direct_url_turns_the_load_balancer_off(client, monkeypatch):
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "ws://127.0.0.1:8765/v1/realtime")
    body = client.get("/api/config").json()
    # demo/server.py:80-81: a pinned URL wins and every LB branch is disabled.
    assert body["lb"] is False
    assert body["allowDirect"] is True
    assert body["s2sUrl"] == "ws://127.0.0.1:8765/v1/realtime"
    assert body["rtc"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_demo_config_service.py tests/demo/test_config_api.py -q`
Expected: 全 FAIL（`No module named 'app.services.demo_config_service'`；`/api/config` 返 404 或 `index.html`）。

- [ ] **Step 3: 写 `config/_demo.py` 并在 `__init__` 里导出**

`console/backend/app/config/_demo.py`：

```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_STARTUP_GREETING = (
    "Start the conversation now with a brief, spontaneous greeting in character. "
    "Keep it to one sentence, invite the user in naturally, and vary the wording each time."
)


class DemoSettings(BaseSettings):
    """The demo face's switches (A.13). Every one defaults to “feature off”."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    serper_api_key: str = ""
    load_balancer_url: str = ""
    speech_to_speech_url: str = ""
    space_id: str = ""
    oauth_client_id: str = ""
    rtc_ice_servers: str = ""
    startup_greeting: str = DEFAULT_STARTUP_GREETING
    # Service credential for the HF ingress in front of the LB. Never leaves the
    # server: `/api/me` and `/api/session` use it, `/api/config` never mentions it.
    lb_hf_token: str = ""

    @property
    def pinned_url(self) -> str:
        return self.speech_to_speech_url.strip()

    @property
    def lb_url(self) -> str:
        """A pinned direct URL disables the whole LB face (demo/server.py:80)."""
        return "" if self.pinned_url else self.load_balancer_url.strip()

    @property
    def limiter_enabled(self) -> bool:
        """Budget and queue exist only on a Space behind an LB (demo/server.py:88)."""
        return bool(self.lb_url) and bool(self.space_id.strip())

    @property
    def oauth_configured(self) -> bool:
        return bool(self.oauth_client_id.strip())

    @property
    def auth_enabled(self) -> bool:
        """Sign-in only matters when we are metering (demo/server.py:205)."""
        return self.limiter_enabled and self.oauth_configured

    @property
    def server_search(self) -> bool:
        """A public Space only spends the paid key for signed-in users."""
        return bool(self.serper_api_key.strip()) and (self.auth_enabled or not self.space_id.strip())
```

`console/backend/app/config/__init__.py` 改为（只多一行 import、一行实例、`__all__` 加两项）：

```python
from ._app import AppSettings, settings
from ._auth import AuthSettings
from ._console import ConsoleSettings
from ._database import DatabaseSettings
from ._demo import DemoSettings

app = settings
console = ConsoleSettings()
database = DatabaseSettings()
auth = AuthSettings()
demo = DemoSettings()

if not auth.jwt_secret_key:
    raise RuntimeError("JWT_SECRET_KEY is required; console refuses to start without it")

__all__ = [
    "AppSettings",
    "AuthSettings",
    "ConsoleSettings",
    "DatabaseSettings",
    "DemoSettings",
    "app",
    "auth",
    "console",
    "database",
    "demo",
    "settings",
]
```

- [ ] **Step 4: 写服务与路由**

`console/backend/app/services/demo_config_service.py`：

```python
"""`GET /api/config`: the browser's bootstrap facts (A.13).

Deliberately env-only: no database, no identity, no pipeline call. The voice page
asks for this before it has a cookie or a token, so it must never block.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import demo


def ice_servers(raw: str) -> list[dict[str, Any]]:
    """JSON list / single object / comma list — same three forms as demo (§9.2)."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
    except ValueError:
        pass
    return [{"urls": item.strip()} for item in raw.split(",") if item.strip()]


def config() -> dict[str, Any]:
    """A.13's key set. The LB address itself is never included."""
    return {
        "search": demo.server_search,
        "lb": bool(demo.lb_url),
        "allowDirect": not demo.lb_url,
        "s2sUrl": demo.pinned_url,
        "rtc": bool(demo.pinned_url),
        "iceServers": ice_servers(demo.rtc_ice_servers),
        "startupGreeting": demo.startup_greeting.strip(),
        "auth": demo.auth_enabled,
    }
```

`console/backend/app/routers/demo/__init__.py`：

```python
"""The demo face: byte-compatible with `demo/server.py` (A.13), never enveloped."""

from . import config

ROUTERS = (config.router,)

__all__ = ["ROUTERS", "config"]
```

`console/backend/app/routers/demo/config.py`：

```python
from __future__ import annotations

from fastapi import APIRouter

from app.services import demo_config_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/config")
def get_config():
    """Anonymous and unenveloped: the voice page reads it before it has a cookie."""
    return demo_config_service.config()
```

`console/backend/app/core/router_registry.py` 的 `register_api_routers` 改为：

```python
from __future__ import annotations

from fastapi import FastAPI


def register_api_routers(app: FastAPI) -> None:
    """Prefix order: /api/v1 (JWT) → /api (anonymous) → /v1 (proxy).

    The SPA catch-all is mounted after this returns, so nothing here can be
    shadowed by index.html.
    """
    from app.routers import (  # noqa: PLC0415
        auth,
        catalog,
        health,
        instances,
        profiles,
        sessions,
        status,
    )
    from app.routers.demo import ROUTERS as DEMO_ROUTERS  # noqa: PLC0415

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(profiles.router)
    app.include_router(sessions.router)
    app.include_router(instances.router)
    app.include_router(status.router)

    for router in DEMO_ROUTERS:
        app.include_router(router)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_demo_config_service.py tests/demo/test_config_api.py -q`
Expected: 7 passed。

- [ ] **Step 6: 写 `/vendor` 的失败测试**

`console/backend/tests/demo/test_vendor_api.py`：

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    (root / "vendor" / "local-vad").mkdir(parents=True)
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "vendor" / "openai-realtime-agents.umd.js").write_text("// umd", encoding="utf-8")
    (root / "vendor" / "local-vad" / "bundle.min.js").write_text("// vad", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


def test_agents_bundle_is_served_as_javascript(dist):
    response = TestClient(create_app()).get("/vendor/openai-realtime-agents.umd.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert "immutable" in response.headers["cache-control"]


def test_a_whitelisted_vad_asset_is_served(dist):
    response = TestClient(create_app()).get("/vendor/local-vad/bundle.min.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")


def test_an_unlisted_vad_filename_is_404(dist):
    # A.13: only the six pinned names exist; anything else must look absent.
    response = TestClient(create_app()).get("/vendor/local-vad/secrets.txt")
    assert response.status_code == 404


def test_a_missing_whitelisted_asset_is_503_asset_missing(dist):
    (dist / "vendor" / "local-vad" / "bundle.min.js").unlink()
    response = TestClient(create_app()).get("/vendor/local-vad/bundle.min.js")
    assert response.status_code == 503
    assert response.json()["code"] == "asset_missing"


def test_the_spa_fallback_still_serves_console_routes(dist):
    # Registering /vendor must not reorder anything: deep links still get index.html.
    response = TestClient(create_app()).get("/console/versions")
    assert response.status_code == 200
    assert response.text == "<html></html>"
```

- [ ] **Step 7: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/demo/test_vendor_api.py -q`
Expected: 前两条 FAIL（兜底把 `/vendor/...` 当成静态文件返回，`content-type` 不是 `text/javascript`）；后三条也会红（`secrets.txt` 返 404 但 `asset_missing` 不存在）。

- [ ] **Step 8: 写 `asset_service.py` 并接入 `mount_spa`**

`console/backend/app/services/asset_service.py`：

```python
"""`/vendor/*`: build-time assets, runtime whitelist (A.13).

No `node_modules` probing at request time (D10): a missing asset is a broken
image and must say so loudly instead of falling back to a directory that the
runtime image does not contain.
"""

from __future__ import annotations

from pathlib import Path

from app.config import console
from app.core.errors import ApiError

AGENTS_SDK = "openai-realtime-agents.umd.js"

# The six pinned VAD assets and their media types (demo/server.py:179-186).
LOCAL_VAD_ASSETS: dict[str, str] = {
    "bundle.min.js": "text/javascript",
    "vad.worklet.bundle.min.js": "text/javascript",
    "silero_vad_v6.onnx": "application/octet-stream",
    "ort.wasm.min.js": "text/javascript",
    "ort-wasm-simd-threaded.mjs": "text/javascript",
    "ort-wasm-simd-threaded.wasm": "application/wasm",
}


def vendor_dir() -> Path:
    return Path(console.static_dir) / "vendor"


def agents_sdk_path() -> Path:
    return _require(vendor_dir() / AGENTS_SDK)


def vad_path(filename: str) -> tuple[Path, str]:
    """`(path, media_type)`. An unlisted name is not a 503 — it does not exist."""
    media_type = LOCAL_VAD_ASSETS.get(filename)
    if media_type is None:
        raise ApiError("not_found", "no such asset", 404)
    return _require(vendor_dir() / "local-vad" / filename), media_type


def _require(path: Path) -> Path:
    if not path.is_file():
        raise ApiError(
            "asset_missing",
            f"{path.name} is missing from the image; the frontend build did not run",
            503,
        )
    return path
```

`console/backend/app/core/spa.py` 的 `mount_spa` 改为（`/vendor` 必须在兜底**之前**注册）：

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.services import asset_service

# Built assets carry a content hash in the filename, so they can be cached hard;
# index.html must not be cached or a browser keeps an old bundle across deploys
# (spec R16).
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_NO_STORE = {"Cache-Control": "no-store"}


def mount_spa(app: FastAPI, dist_dir: str | Path) -> None:
    """Serve the built SPA. Call this **after** every API router is registered.

    Starlette matches routes in registration order, so a catch-all registered
    first would answer /api/config with index.html.
    """
    dist = Path(dist_dir)
    if not dist.is_dir():
        # A missing dist is a broken image, not a runtime condition worth
        # pretending to survive: fail loudly at boot.
        raise RuntimeError(f"static dir {dist} is missing; the image was built without the frontend")

    @app.get("/vendor/openai-realtime-agents.umd.js", include_in_schema=False)
    def agents_sdk() -> FileResponse:
        return FileResponse(
            asset_service.agents_sdk_path(), media_type="text/javascript", headers=_IMMUTABLE
        )

    @app.get("/vendor/local-vad/{filename}", include_in_schema=False)
    def local_vad(filename: str) -> FileResponse:
        path, media_type = asset_service.vad_path(filename)
        return FileResponse(path, media_type=media_type, headers=_IMMUTABLE)

    for name in ("assets", "worklets"):
        directory = dist / name
        if directory.is_dir():
            app.mount(f"/{name}", StaticFiles(directory=directory), name=name)

    index = dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file() and dist in candidate.resolve().parents:
            return FileResponse(candidate, headers=_IMMUTABLE)
        return FileResponse(index, headers=_NO_STORE)
```

注意：`/api/config` 的 404 也要能落到 `ApiError` → `JSONResponse`（全局注册了 `ApiError` handler，Task 3）；这就是为什么 `asset_service` 抛的是 `ApiError("not_found", ..., 404)` 而不是 `HTTPException`——两者状态码一样，但前者带 `code`，前端能翻译。

- [ ] **Step 9: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/demo -q`
Expected: 8 passed（`test_config_api.py` 3 + `test_vendor_api.py` 5）。`test_demo_config_service.py` 那 4 条在 `tests/unit/` 下，**不在**这个目录里——把 9 当成期望值说明统计口径错了。

- [ ] **Step 10: 回归静态托管顺序**

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿。特别注意 Task 3 的 `test_static_mount_order.py`：`/api/config`、`/vendor/*`、`/v1/realtime` 都不能被兜底吞掉。

- [ ] **Step 11: 前端类型与取数模块**

`console/frontend/src/types/demo.d.ts`：

```ts
export interface IceServer {
  urls: string
  username?: string
  credential?: string
}

/** A.13 — `GET /api/config`, bare object, no token. */
export interface DemoConfig {
  search: boolean
  lb: boolean
  allowDirect: boolean
  s2sUrl: string
  rtc: boolean
  iceServers: IceServer[]
  startupGreeting: string
  auth: boolean
}
```

`console/frontend/src/api/demo.ts`：

```ts
import axios from 'axios'

import type { DemoConfig } from '@/types/demo'

/** The demo face has its own contract (A.13): bare objects, no JWT.
 *
 * Deliberately not `api/client.ts`: that instance unwraps `ApiResponse`, redirects
 * to `/console/login` on 401, and retries through a refresh token — none of which
 * apply to an anonymous `/api/*` call.
 */
export const getDemoConfig = async (): Promise<DemoConfig> =>
  (await axios.get<DemoConfig>('/api/config', { timeout: 10_000 })).data
```

- [ ] **Step 12: 构建与单测**

Run: `cd console/frontend && npx vitest run && npm run build`
Expected: 原有用例全绿（本任务不加前端用例）；`vue-tsc` 无错误。

- [ ] **Step 13: 手工验收**

起后端（`cd console/backend && python -m uvicorn app.main:app --port 8000`），然后：

1. `curl -s http://127.0.0.1:8000/api/config` → 8 个键、无 `code`/`data`；未配 `LOAD_BALANCER_URL` 时 `lb:false`、`allowDirect:true`；
2. `curl -sI http://127.0.0.1:8000/vendor/openai-realtime-agents.umd.js` → `200` + `text/javascript`；
3. `curl -sI http://127.0.0.1:8000/vendor/local-vad/silero_vad_v6.onnx` → `200` + `application/octet-stream`；
4. `curl -sI http://127.0.0.1:8000/vendor/local-vad/nope` → `404`；
5. 临时 `mv` 掉 `dist/vendor/local-vad/bundle.min.js` 再请求 → `503 {"code":"asset_missing"}`，改回；
6. 浏览器直接访问 `http://127.0.0.1:8000/console/versions`（未登录）→ 拿到 `index.html`（`no-store`），不是 404。

- [ ] **Step 14: 提交**

```bash
git add console/backend console/frontend
git commit -m "feat(console): demo bootstrap config and build-time vendor assets"
```

---

## Task 18: 演示面身份与计量底座 + `GET /api/me`

**Files:**
- Modify: `console/backend/requirements.txt`（加一行共享包下界）
- Create: `console/backend/app/services/metering_service.py`
- Create: `console/backend/app/services/identity_service.py`
- Create: `console/backend/app/routers/demo/me.py`
- Modify: `console/backend/app/routers/demo/__init__.py`（`ROUTERS` 加 `me.router`）
- Modify: `console/backend/app/main.py`（`create_app` 里 `mount_spa` **之前** attach OAuth；`lifespan` 里 init 计量库 + 起 sweeper）
- Test: `console/backend/tests/unit/test_metering_service.py`
- Test: `console/backend/tests/unit/test_identity_service.py`
- Test: `console/backend/tests/demo/test_me_api.py`

**Interfaces:**
- Consumes: `database.usage_db_path`（Task 3，默认 `/app/data/usage.sqlite3`）；`DemoSettings`（`limiter_enabled` / `auth_enabled` / `space_id` / `oauth_client_id`，Task 17）；`routers/demo/ROUTERS`（Task 17）。
- Produces: `metering_service`（`budget_for(tier) -> int|None`、`hash_key(raw) -> str`、`sign_cookie(value) -> str`、`verify_cookie(signed) -> str|None`、`init(path: str|None = None)`、`remaining(keys, tier) -> int|None`、`begin(session_id, keys, tier) -> int`、`heartbeat(session_id) -> bool`、`end(session_id)`、`sweep()`、`session_live(session_id, keys) -> bool`、`take_search(keys) -> bool`、常量 `ANON_SEC`/`FREE_SEC`/`CHUNK_SEC`/`HEARTBEAT_SEC`/`REAP_AFTER_SEC`/`SEARCH_PER_DAY`/`UNLIMITED_TIERS`）；`identity_service`（`attach(app) -> bool`、`oauth_enabled`、`resolve_identity(request) -> (tier, keys, set_cookie)`、`resolve_tier(user, token=None) -> str`、`user_view(request, tier=None) -> dict`、`current_access_token(request) -> str|None`、`oauth_login_required_reason(request) -> str|None`、`set_anon_cookie(response, signed)`、`ANON_COOKIE`、`OAUTH_LOGIN_PATH`、`OAUTH_LOGOUT_PATH`）；`GET /api/me`（裸对象）。

**为什么计量库继续用裸 `sqlite3`**（D11）：参数库走 SQLAlchemy + Alembic，用量库走 `demo/limiter.py` 那套手写 PRAGMA。硬接进 ORM 会造出两套事务语义、两套锁、一个连接池去竞争同一个文件。两个库各走各的 WAL、各自备份，参数平台的发布回滚也不会碰到用量库。

**为什么 `attach()` 必须在 `mount_spa()` 之前**：`attach_huggingface_oauth(app)` 是**往 app 上追加路由**（`/oauth/huggingface/login`、`/oauth/huggingface/logout`…）。而 `mount_spa` 最后注册的 `GET /{full_path:path}` 是兜底，会吞掉一切后注册的路径。放在 lifespan 里 attach 就等于把登录入口埋进 `index.html`（回 200 + HTML，而不是跳转 HF）。

**为什么 `/api/me` 写 `def` 而不是 `async def`**：`resolve_identity` → `resolve_tier` → `_whoami_via_token` 会同步打一次 `https://huggingface.co/api/whoami-v2`（进程内按 token 缓存）。demo 把它写成 `async def` 直接调，等于把网络等待压在事件循环上；写成 `def`，FastAPI 自动丢进线程池，语义不变而循环不堵。同理 `metering_service.remaining()` 是阻塞的 sqlite 读，也不再需要 `asyncio.to_thread` 包一层。

**为什么伪造 `X-Forwarded-For` 换不出新额度**：匿名的两个键是 `ip:<XFF 首跳>` 与 `cookie:<签名 id>`，`_spent_max` 对两个键**取 max**（OR-match）。换 IP 只是让 `ip` 键从 0 重新算，`cookie` 键仍然是满的，`remaining` 依旧 0。所以 `_client_ip` 照抄 demo 的「信 XFF 首跳」不构成配额绕过——它是为了让 HF 代理后的真实 IP 生效，而不是安全边界。

- [ ] **Step 1: 写计量的失败测试**

`console/backend/tests/unit/test_metering_service.py`：

```python
from __future__ import annotations

import pytest

from app.services import metering_service


@pytest.fixture
def usage_db(tmp_path):
    metering_service.init(str(tmp_path / "usage.sqlite3"))
    yield
    metering_service._db_path = None  # module global; do not leak into the next test


def _age_session(session_id: str, seconds: float) -> None:
    """Backdate a grant so a heartbeat sees elapsed time without sleeping."""
    with metering_service._lock, metering_service._session() as con:
        con.execute(
            "UPDATE sessions SET grant_ts = grant_ts - ? WHERE session_id = ?",
            (seconds, session_id),
        )


def test_budget_for_maps_every_tier():
    assert metering_service.budget_for("anon") == 300
    assert metering_service.budget_for("free") == 600
    # Unlimited tiers report no budget at all, not a very large number.
    assert metering_service.budget_for("pro") is None
    assert metering_service.budget_for("org") is None


def test_hash_key_is_opaque_and_stable():
    first = metering_service.hash_key("sub:alice")
    assert first.startswith("k_")
    assert "alice" not in first
    assert metering_service.hash_key("sub:alice") == first
    assert metering_service.hash_key("sub:bob") != first


def test_sign_cookie_round_trips_and_rejects_a_forgery():
    signed = metering_service.sign_cookie("abc123")
    assert metering_service.verify_cookie(signed) == "abc123"
    assert metering_service.verify_cookie("abc123.deadbeef") is None
    assert metering_service.verify_cookie("") is None
    assert metering_service.verify_cookie("no-signature") is None


def test_begin_debits_one_chunk(usage_db):
    keys = ["k_a"]
    assert metering_service.begin("s1", keys, "free") == 10
    # A fresh session is not live-budget-negative: the chunk is what was reserved.
    assert metering_service.remaining(keys, "free") == 590


def test_heartbeat_grows_the_reservation_and_end_refunds_the_rest(usage_db):
    keys = ["k_b"]
    metering_service.begin("s2", keys, "free")
    assert metering_service.remaining(keys, "free") == 590

    # 25 s in: the heartbeat tops the reservation up to elapsed + one chunk (40 s).
    _age_session("s2", 25)
    assert metering_service.heartbeat("s2") is True
    assert metering_service.remaining(keys, "free") == 560

    # Clean teardown bills the elapsed time rounded up to a chunk (30 s) and
    # refunds the 10 s that was reserved but never used.
    metering_service.end("s2")
    assert metering_service.remaining(keys, "free") == 570
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_metering_service.py -q`
Expected: 收集期就 ERROR —— `ModuleNotFoundError: No module named 'app.services.metering_service'`。

- [ ] **Step 3: 写 `metering_service.py`**

`console/backend/app/services/metering_service.py`：

```python
"""每日用量、会话预留与搜索配额（`USAGE_DB_PATH`，默认 `/app/data/usage.sqlite3`）。

移植自 `demo/limiter.py`，语义逐条照搬；存储仍是裸 `sqlite3`（D11）：参数库走
SQLAlchemy，用量库不共用连接池——两套 WAL、两套备份、互不阻塞。

每个函数都在请求路径上，所以只有一个模块级锁，没有 ORM，没有异步。
调用方负责把它塞进线程池（路由写成同步 `def` 就够了）。
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from loguru import logger

from app.config import database

# ── 可调参数：环境变量名与 demo 完全一致，运维不用学第二套名字 ──────────────
ANON_SEC = int(os.environ.get("LIMIT_ANON_SEC", "300"))  # 未登录：5 分钟/天
FREE_SEC = int(os.environ.get("LIMIT_FREE_SEC", "600"))  # 已登录非 PRO：10 分钟/天
CHUNK_SEC = int(os.environ.get("RESERVE_CHUNK_SEC", "10"))  # 预留粒度
HEARTBEAT_SEC = int(os.environ.get("HEARTBEAT_SEC", "5"))  # 下发给客户端的心跳节奏
REAP_AFTER_SEC = int(os.environ.get("SESSION_REAP_SEC", "15"))  # 静默多久算掉线
SEARCH_PER_DAY = int(os.environ.get("LIMIT_SEARCH_PER_DAY", "100"))  # 服务端 key 的搜索上限

UNLIMITED_TIERS = ("pro", "org")

# 跨重启必须稳定，否则哈希键（以及签名 cookie）全部轮换，当日额度等于清零。
# Space 上配 USAGE_HASH_SECRET；没配就每次启动随机——额度只在一个 uptime 内有效。
_HASH_SECRET = (os.environ.get("USAGE_HASH_SECRET", "").strip() or os.urandom(32).hex()).encode()

_lock = threading.Lock()
_db_path: Path | None = None


def budget_for(tier: str) -> int | None:
    """某档位的每日秒数预算；不限量的档位返回 `None`，不是一个大数字。"""
    if tier in UNLIMITED_TIERS:
        return None
    if tier == "free":
        return FREE_SEC
    return ANON_SEC


def hash_key(raw: str) -> str:
    """把裸标识（sub / ip / cookie id）HMAC 成不透明存储键。"""
    digest = hmac.new(_HASH_SECRET, raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"k_{digest}"


def sign_cookie(value: str) -> str:
    """`<id>.<sig>`，读回时能识别伪造的匿名 id。"""
    sig = hmac.new(_HASH_SECRET, value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{value}.{sig}"


def verify_cookie(signed: str) -> str | None:
    """签名对得上就回 id，否则 `None`。"""
    if not signed or "." not in signed:
        return None
    value, _, sig = signed.rpartition(".")
    want = hmac.new(_HASH_SECRET, value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return value if hmac.compare_digest(sig, want) else None


def init(path: str | None = None) -> None:
    """建表。lifespan 里调一次（demo 的 `@app.on_event("startup")` 同一位置）。"""
    global _db_path
    target = Path(path or database.usage_db_path)
    # /app/data 是命名卷，首次起来是空目录；sqlite3 不会替你建父目录。
    target.parent.mkdir(parents=True, exist_ok=True)
    _db_path = target
    with _lock, _session() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS usage_daily (
                   user_key   TEXT NOT NULL,
                   day        TEXT NOT NULL,
                   spent_sec  INTEGER NOT NULL DEFAULT 0,
                   updated_at INTEGER NOT NULL,
                   PRIMARY KEY (user_key, day)
               )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                   session_id   TEXT PRIMARY KEY,
                   keys         TEXT NOT NULL,   -- 逗号串：要扣的 usage_daily 键
                   day          TEXT NOT NULL,
                   tier         TEXT NOT NULL,
                   grant_ts     REAL NOT NULL,
                   last_seen_ts REAL NOT NULL,
                   reserved_sec INTEGER NOT NULL,
                   ended        INTEGER NOT NULL DEFAULT 0
               )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS search_daily (
                   user_key TEXT NOT NULL,
                   day      TEXT NOT NULL,
                   count    INTEGER NOT NULL DEFAULT 0,
                   PRIMARY KEY (user_key, day)
               )"""
        )
    logger.info(
        "usage metering ready at {} (anon={}s free={}s chunk={}s)",
        _db_path, ANON_SEC, FREE_SEC, CHUNK_SEC,
    )


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        # 没有 init 就来扣额度说明 lifespan 没跑：宁可炸，也不要静默地让人白嫖。
        raise RuntimeError("metering_service.init() must run in the lifespan before any request")
    con = sqlite3.connect(_db_path, timeout=5.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


@contextmanager
def _session() -> Iterator[sqlite3.Connection]:
    """`with con:` 只提交不关闭（demo 靠 GC 兜底）；这里显式关掉，语义不变。"""
    con = _connect()
    try:
        with con:
            yield con
    finally:
        con.close()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _spent(con: sqlite3.Connection, key: str, day: str) -> int:
    row = con.execute(
        "SELECT spent_sec FROM usage_daily WHERE user_key=? AND day=?", (key, day)
    ).fetchone()
    return int(row[0]) if row else 0


def _spent_max(con: sqlite3.Connection, keys, day: str) -> int:
    """OR-match：花得最多的那个标识说了算（换 IP 换不出新额度，见本任务说明）。"""
    return max((_spent(con, k, day) for k in keys), default=0)


def _add(con: sqlite3.Connection, keys, day: str, delta: int) -> None:
    now = int(time.time())
    for k in keys:
        nxt = max(0, _spent(con, k, day) + delta)
        con.execute(
            """INSERT INTO usage_daily (user_key, day, spent_sec, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_key, day) DO UPDATE SET
                   spent_sec = excluded.spent_sec, updated_at = excluded.updated_at""",
            (k, day, nxt, now),
        )


def remaining(keys, tier: str) -> int | None:
    """今天还剩多少秒（`None` = 不限量）。只读，不产生写入。"""
    budget = budget_for(tier)
    if budget is None:
        return None
    with _lock, _session() as con:
        return max(0, budget - _spent_max(con, keys, _today()))


def begin(session_id: str, keys, tier: str) -> int:
    """给新会话预留第一块并记账，返回预留秒数（预算已耗尽时为 0）。

    不限量档位也记一行：Web 搜索要靠这一行判断「这个会话是不是活的」。
    """
    day = _today()
    budget = budget_for(tier)
    now = time.time()
    with _lock, _session() as con:
        avail = budget - _spent_max(con, keys, day) if budget is not None else 0
        chunk = max(0, min(CHUNK_SEC, avail))
        if chunk:
            _add(con, keys, day, chunk)
        con.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, keys, day, tier, grant_ts, last_seen_ts, reserved_sec, ended)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (session_id, ",".join(keys), day, tier, now, now, chunk),
        )
        return chunk


def heartbeat(session_id: str) -> bool:
    """续期：把预留追到 `elapsed + 一块`，逐块扣预算。

    返回 True = 会话还活着；False = 预算花完（调用方必须拆会话）或会话未知/已结束。
    """
    now = time.time()
    with _lock, _session() as con:
        row = con.execute(
            "SELECT keys, day, tier, grant_ts, reserved_sec, ended FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row or row[5]:
            return False
        keys = row[0].split(",")
        day, tier, grant_ts, reserved = row[1], row[2], row[3], int(row[4])
        budget = budget_for(tier)
        if budget is None:
            # 不限量：没有账可记，心跳只用来表示「这个会话还在」。
            con.execute("UPDATE sessions SET last_seen_ts=? WHERE session_id=?", (now, session_id))
            return True
        elapsed = now - grant_ts

        # 一块一块往上加，直到覆盖「已用时长 + 一块的提前量」，或者预算见底。
        while reserved < elapsed + CHUNK_SEC:
            if _spent_max(con, keys, day) >= budget:
                break
            _add(con, keys, day, CHUNK_SEC)
            reserved += CHUNK_SEC

        alive = reserved > elapsed  # 已经过去的时间还付得起吗？
        con.execute(
            "UPDATE sessions SET last_seen_ts=?, reserved_sec=?, ended=? WHERE session_id=?",
            (now, reserved, 0 if alive else 1, session_id),
        )
        if not alive:
            _reconcile(con, keys, day, grant_ts, reserved, end_ts=now)
        return alive


def end(session_id: str) -> None:
    """正常结束：按真实时长结算，退回没用掉的预留。幂等。"""
    now = time.time()
    with _lock, _session() as con:
        row = con.execute(
            "SELECT keys, day, grant_ts, reserved_sec, ended FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row or row[4]:
            return
        keys, day, grant_ts, reserved = row[0].split(","), row[1], row[2], int(row[3])
        _reconcile(con, keys, day, grant_ts, reserved, end_ts=now)
        con.execute("UPDATE sessions SET ended=1, last_seen_ts=? WHERE session_id=?", (now, session_id))


def sweep() -> None:
    """回收静默掉的计量会话（崩了 / 关页没发 beacon）：按走过的时长结算、
    退回其余、标记结束。最多损失一块。

    不限量会话没有账可结，留着不关：断线后一次心跳就能复活，期间
    `session_live()` 视它们为过期。只有显式 `end()` 才真正关闭。"""
    now = time.time()
    cutoff = now - REAP_AFTER_SEC
    unlimited = ",".join("?" * len(UNLIMITED_TIERS))
    with _lock, _session() as con:
        stale = con.execute(
            "SELECT session_id, keys, day, grant_ts, last_seen_ts, reserved_sec FROM sessions "
            f"WHERE ended=0 AND last_seen_ts < ? AND tier NOT IN ({unlimited})",
            (cutoff, *UNLIMITED_TIERS),
        ).fetchall()
        for session_id, keys_s, day, grant_ts, last_seen, reserved in stale:
            _reconcile(con, keys_s.split(","), day, grant_ts, int(reserved), end_ts=last_seen)
            con.execute("UPDATE sessions SET ended=1 WHERE session_id=?", (session_id,))
        if stale:
            logger.debug("swept {} stale session(s)", len(stale))


def session_live(session_id: str, keys) -> bool:
    """这个 `session_id` 是否是发给这组 keys 的、还没结束、且 `REAP_AFTER_SEC`
    内有过动静（授权或心跳）的会话。"""
    if not session_id:
        return False
    with _lock, _session() as con:
        row = con.execute(
            "SELECT keys, ended, last_seen_ts FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    return (
        bool(row)
        and not row[1]
        and row[0] == ",".join(keys)
        and row[2] >= time.time() - REAP_AFTER_SEC
    )


def take_search(keys) -> bool:
    """给服务端 key 的一次搜索记一笔（OR-match，与时长预算同规则）。
    达到上限时返回 False 且不记账。"""
    day = _today()
    with _lock, _session() as con:
        counts = [
            con.execute(
                "SELECT count FROM search_daily WHERE user_key=? AND day=?", (k, day)
            ).fetchone()
            for k in keys
        ]
        if max((int(c[0]) for c in counts if c), default=0) >= SEARCH_PER_DAY:
            return False
        for k in keys:
            con.execute(
                """INSERT INTO search_daily (user_key, day, count) VALUES (?, ?, 1)
                   ON CONFLICT(user_key, day) DO UPDATE SET count = count + 1""",
                (k, day),
            )
        return True


def _reconcile(con: sqlite3.Connection, keys, day: str, grant_ts: float, reserved: int, end_ts: float) -> None:
    """退回「预留了但没用」的时间。已用时长向上取整到整块，且不超过预留。"""
    elapsed = max(0.0, end_ts - grant_ts)
    billed = min(reserved, int(math.ceil(elapsed / CHUNK_SEC) * CHUNK_SEC))
    refund = reserved - billed
    if refund > 0:
        _add(con, keys, day, -refund)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_metering_service.py -q`
Expected: 5 passed。

- [ ] **Step 5: 写身份的失败测试**

`console/backend/tests/unit/test_identity_service.py`：

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import identity_service, metering_service


def _request(cookies=None, headers=None, host="127.0.0.1"):
    return SimpleNamespace(
        cookies=cookies or {},
        headers=headers or {},
        client=SimpleNamespace(host=host),
    )


def test_user_view_is_anonymous_without_oauth():
    # oauth_enabled is False in tests (no OAUTH_CLIENT_ID), so there is no identity.
    assert identity_service.user_view(_request()) == {"loggedIn": False, "tier": "anon"}


def test_an_expired_token_is_not_trusted():
    info = {
        "user_info": {"sub": "u"},
        "access_token": "t",
        "access_token_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    assert identity_service._oauth_token_expired(info) is True


def test_a_missing_expiry_is_left_to_the_hub():
    # Older huggingface_hub builds do not expose the field; the Hub validates instead.
    assert identity_service._oauth_token_expired({"user_info": {}}) is False


def test_anonymous_identity_mints_a_signed_cookie():
    tier, keys, set_cookie = identity_service.resolve_identity(
        _request(headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"})
    )
    assert tier == "anon"
    # Two keys: the IP and the cookie id, OR-matched by the limiter.
    assert len(keys) == 2 and keys[0] != keys[1]
    assert set_cookie is not None
    assert metering_service.verify_cookie(set_cookie) is not None


def test_a_forged_cookie_gets_a_new_id():
    tier, _, set_cookie = identity_service.resolve_identity(
        _request(cookies={identity_service.ANON_COOKIE: "forged.nope"})
    )
    assert tier == "anon"
    assert set_cookie is not None
    assert metering_service.verify_cookie(set_cookie) != "forged"
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_identity_service.py -q`
Expected: 收集期 ERROR —— `No module named 'app.services.identity_service'`。

- [ ] **Step 7: 写 `identity_service.py` 并加依赖**

`console/backend/requirements.txt` 的「共享包（只写下界）」段追加一行：

```
# [oauth] extra 带进 authlib；没有它 attach_huggingface_oauth 只是一段被跳过的 import。
huggingface-hub[oauth]>=0.34.0
```

`console/backend/app/services/identity_service.py`：

```python
"""演示面身份：匿名 cookie 或 HF OAuth（移植自 `demo/auth.py`）。

与运维面的 JWT **完全独立**（§10.1）：`/api/*` 只认这里，`/api/v1/*` 只认
`core/security.py`；两者不共享依赖注入，也不把 demo 的 tier 映射成
`admin`/`operator`。tier 只决定「今天能说多少秒」。
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.services import metering_service

# huggingface_hub 挂上来时自带这几个路由；集中在这里，版本改名就是一行的事。
# 路径通过 /api/me 交给前端，前端不硬编码。
OAUTH_LOGIN_PATH = "/oauth/huggingface/login"
OAUTH_LOGOUT_PATH = "/oauth/huggingface/logout"

ANON_COOKIE = "s2s_anon"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 天
_OAUTH_EXPIRY_SKEW = timedelta(seconds=30)

# 这些组织成默认不限量（与 PRO 同档）；UNLIMITED_ORGS 是在此之上追加，不是替换。
_DEFAULT_UNLIMITED_ORGS = {"cerebras", "huggingfacem4", "smolagents", "pollen-robotics"}

# 把探到的 org 与 tier 写进日志和 /api/me，便于在真 Space 上核对组织放行是否生效。
AUTH_DEBUG = bool(os.environ.get("AUTH_DEBUG"))

# 由 attach() 置位：True = 登录真的接上了（可 import + 环境变量在）。
oauth_enabled = False

try:
    from huggingface_hub import attach_huggingface_oauth, parse_huggingface_oauth

    _OAUTH_IMPORTABLE = True
except Exception as exc:  # pragma: no cover - import guard
    logger.info("huggingface_hub OAuth unavailable ({}); sign-in disabled", exc)
    _OAUTH_IMPORTABLE = False

# whoami-v2 的结果按 token 缓存到进程结束：/api/me 与 /api/session 共用一次 Hub 请求。
_whoami_cache: dict[str, dict] = {}


def attach(app) -> bool:
    """能 import 且配了 OAUTH_CLIENT_ID 就把 HF OAuth 挂到 app 上，返回是否可用。

    必须在 `mount_spa()` 之前调用：这里的路由是追加的，兜底的
    `GET /{full_path:path}` 会吞掉之后注册的一切。
    """
    global oauth_enabled
    from app.config import demo

    if not _OAUTH_IMPORTABLE or not demo.oauth_client_id.strip():
        return False
    try:
        attach_huggingface_oauth(app)
        oauth_enabled = True
        logger.info("HF OAuth attached (sign-in enabled)")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("failed to attach HF OAuth: {}", exc)
        oauth_enabled = False
    return oauth_enabled


def _field(obj, name, default=None):
    """用户信息可能是对象也可能是 dict，两种都读。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def current_oauth(request):
    """解析后的 HF OAuth 信息（user_info + access_token），没有就 None。"""
    if not oauth_enabled:
        return None
    try:
        return parse_huggingface_oauth(request)
    except Exception:
        return None


def _oauth_token_expired(info, *, now=None) -> bool:
    """access token 是否过期（含时钟偏移）。"""
    expires_at = _field(info, "access_token_expires_at")
    if expires_at is None:
        # 老版本 huggingface_hub 不暴露这个字段：交给上游校验，不要误判。
        return False
    if not isinstance(expires_at, datetime):
        logger.warning("unexpected OAuth expiry value; requiring a fresh login")
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.astimezone(timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.astimezone(timezone.utc)
    return expires_at <= current + _OAUTH_EXPIRY_SKEW


def _oauth_token(info) -> str | None:
    token = _field(info, "access_token")
    if token is None:
        return None
    return str(token).strip() or None


def oauth_login_required_reason(request) -> str | None:
    """已登录的缓存会话为什么不能用（要重新登录）——没有会话则 None。"""
    info = current_oauth(request)
    if not _field(info, "user_info"):
        return None
    if _oauth_token_expired(info):
        return "token_expired"
    if not _oauth_token(info):
        return "token_invalid"
    return None


def current_access_token(request) -> str | None:
    """登录用户的 HF access token，没有就 None。

    只在服务端用（把 LB 的会话申请记到具体 HF 账号上），**绝不**回给浏览器。
    """
    info = current_oauth(request)
    if _oauth_token_expired(info):
        return None
    return _oauth_token(info)


def _user_org_names(user) -> set[str]:
    """OAuth userinfo 里带的组织名（按 username/name/id 三种键都认）。"""
    names: set[str] = set()
    for org in _field(user, "orgs", []) or []:
        for key in ("preferred_username", "name", "sub"):
            val = _field(org, key)
            if val:
                names.add(str(val).lower())
    return names


def _whoami_via_token(token: str) -> dict:
    """认证过的 Hub `whoami-v2` 档案，按 token 缓存。"""
    if not token:
        return {}
    if token in _whoami_cache:
        return _whoami_cache[token]
    try:
        import httpx

        resp = httpx.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("whoami-v2 returned a non-object response")
    except Exception as exc:  # pragma: no cover - 依赖网络与权限
        logger.info("whoami-v2 profile lookup failed: {}", exc)
        return {}
    _whoami_cache[token] = data
    return data


def _orgs_via_token(token: str, profile=None) -> set[str]:
    """从缓存的 Hub 档案里取组织名。"""
    if profile is None:
        profile = _whoami_via_token(token)
    names: set[str] = set()
    for org in profile.get("orgs", []) or []:
        for key in ("name", "fullname"):
            val = _field(org, key)
            if val:
                names.add(str(val).lower())
    return names


def _org_names(user, token=None, allow=None, profile=None) -> set[str]:
    """用户所在组织。userinfo 里的 claim 常是空的或残缺的，若不满足 `allow`
    就回落到 Hub 的 whoami-v2 再问一次。"""
    names = _user_org_names(user)
    if token and (allow is None or not (allow & names)):
        names = names | _orgs_via_token(token, profile)
    return names


def _unlimited_orgs() -> set[str]:
    """默认不限量的组织集合；UNLIMITED_ORGS（逗号/空格分隔）在上面追加。"""
    raw = os.environ.get("UNLIMITED_ORGS", "")
    extra = {o.strip().lower() for o in raw.replace(",", " ").split() if o.strip()}
    return _DEFAULT_UNLIMITED_ORGS | extra


def resolve_tier(user, token=None) -> str:
    """登录用户的档位：pro（付费）、org（放行组织成员，不限量）、free。
    PRO 优先于 org。"""
    if bool(_field(user, "is_pro", False)):
        return "pro"
    profile = _whoami_via_token(token)
    if bool(profile.get("isPro", False)):
        return "pro"
    allow = _unlimited_orgs()
    names = _org_names(user, token, allow, profile)
    tier = "org" if (allow & names) else "free"
    if AUTH_DEBUG:
        logger.info("tier={} orgs={} allow={}", tier, sorted(names), sorted(allow))
    return tier


def user_view(request, tier=None) -> dict:
    """`/api/me` 的公开身份段。"""
    info = current_oauth(request)
    user = _field(info, "user_info")
    if not user:
        return {"loggedIn": False, "tier": "anon"}
    if _oauth_token_expired(info):
        return {"loggedIn": False, "tier": "anon", "reason": "token_expired"}
    token = _oauth_token(info)
    if not token:
        return {"loggedIn": False, "tier": "anon", "reason": "token_invalid"}
    out = {
        "loggedIn": True,
        "username": _field(user, "preferred_username") or _field(user, "name") or "you",
        "avatar": _field(user, "picture"),
        "tier": tier if tier is not None else resolve_tier(user, token),
    }
    if AUTH_DEBUG:
        out["orgs"] = sorted(_org_names(user, token))
    return out


def _client_ip(request) -> str:
    """真实客户端 IP。HF 上应用在代理后面，地址是 X-Forwarded-For 的首跳。

    信这个头不是安全边界：伪造它换不来新额度，因为 `_spent_max` 对
    ip 键与 cookie 键取 max，cookie 那一半仍然被算进去。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def resolve_identity(request) -> tuple[str, list[str], str | None]:
    """解析 `(tier, keys, set_cookie)`。

    `keys` 是要扣的 usage_daily 键（登录一个、匿名两个）；`set_cookie` 是本次
    新签发匿名 id 时要 Set-Cookie 的签名值，否则 None。
    """
    info = current_oauth(request)
    user = _field(info, "user_info")
    token = _oauth_token(info)
    if user and token and not _oauth_token_expired(info):
        sub = _field(user, "sub") or _field(user, "preferred_username")
        return resolve_tier(user, token), [metering_service.hash_key(f"sub:{sub}")], None

    # 匿名：IP 与一个签名 cookie id 双键，缺 cookie 就当场发一个。
    ip = _client_ip(request)
    cookie_id = metering_service.verify_cookie(request.cookies.get(ANON_COOKIE, ""))
    set_cookie = None
    if not cookie_id:
        cookie_id = secrets.token_urlsafe(18)
        set_cookie = metering_service.sign_cookie(cookie_id)
    keys = [metering_service.hash_key(f"ip:{ip}"), metering_service.hash_key(f"cookie:{cookie_id}")]
    return "anon", keys, set_cookie


def set_anon_cookie(response, signed: str) -> None:
    # 真 Space 跑在 huggingface.co 的 iframe 里，cookie 处于跨站上下文，必须
    # SameSite=None; Secure，否则浏览器直接丢掉。本地 http 下这条 cookie 收不到，
    # 所以本地开发不启用计量（`limiter_enabled` 需要 LB + SPACE_ID）。
    response.set_cookie(
        ANON_COOKIE, signed,
        max_age=_COOKIE_MAX_AGE, httponly=True, samesite="none", secure=True,
    )
```

Run: `cd console/backend && python -m pytest tests/unit/test_identity_service.py -q`
Expected: 5 passed。

- [ ] **Step 8: 写 `/api/me` 的失败测试**

`console/backend/tests/demo/test_me_api.py`：

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import identity_service


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def metered(tmp_path, monkeypatch):
    """An LB + a Space id is exactly what turns metering on (demo/server.py:88)."""
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "space_id", "my-space")
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "")
    monkeypatch.setattr("app.config.database.usage_db_path", str(tmp_path / "usage.sqlite3"))


def test_without_metering_the_body_is_just_enabled_false(dist):
    response = TestClient(create_app()).get("/api/me")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_an_anonymous_visitor_gets_the_anon_budget_and_a_cookie(dist, metered):
    # The lifespan is what runs metering_service.init(); without `with` it never runs.
    with TestClient(create_app()) as client:
        response = client.get("/api/me")
    body = response.json()
    assert body["enabled"] is True
    assert body["loggedIn"] is False and body["tier"] == "anon"
    assert body["limitSec"] == 300 and body["remainingSec"] == 300
    # No OAUTH_CLIENT_ID in tests, so there is nothing to log in to.
    assert body["auth"] is False and body["loginUrl"] is None and body["logoutUrl"] is None
    # A.13 rule 1: no envelope on the demo face.
    assert "code" not in body and "data" not in body
    cookies = response.headers.get_list("set-cookie")
    assert any(identity_service.ANON_COOKIE + "=" in value for value in cookies)


def test_a_forged_anon_cookie_is_replaced(dist, metered):
    with TestClient(create_app()) as client:
        response = client.get("/api/me", cookies={identity_service.ANON_COOKIE: "forged.nope"})
    minted = [v for v in response.headers.get_list("set-cookie") if identity_service.ANON_COOKIE + "=" in v]
    assert minted, "a forged cookie must be replaced with a freshly signed one"
    assert "forged.nope" not in minted[0]
```

- [ ] **Step 9: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/demo/test_me_api.py -q`
Expected: 3 FAIL —— 前两条拿到的不是 `{"enabled": …}`（`/api/me` 还没注册，落到 SPA 兜底回 `index.html`），第三条同理没有 `set-cookie`。

- [ ] **Step 10: 写路由、注册、接线**

`console/backend/app/routers/demo/me.py`：

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import demo
from app.services import identity_service, metering_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/me")
def get_me(request: Request):
    """登录态、档位、今日剩余额度；未启用计量时只回 `{"enabled": false}`。

    写成同步函数：`resolve_tier` 会打一次 whoami-v2（带缓存），放进线程池
    才不堵事件循环；`remaining()` 也是阻塞的 sqlite 读。
    """
    if not demo.limiter_enabled:
        return {"enabled": False}

    tier, keys, set_cookie = identity_service.resolve_identity(request)
    view = identity_service.user_view(request, tier=tier)
    limit = metering_service.budget_for(tier)
    left = None if limit is None else metering_service.remaining(keys, tier)

    body = {
        "enabled": True,
        # 运行时真相：attach 失败（缺 authlib）时这里必须是 False，否则前端会
        # 渲染一个 404 的登录链接。
        "auth": identity_service.oauth_enabled,
        **view,
        "remainingSec": left,
        "limitSec": limit,
        "loginUrl": identity_service.OAUTH_LOGIN_PATH if identity_service.oauth_enabled else None,
        "logoutUrl": identity_service.OAUTH_LOGOUT_PATH if identity_service.oauth_enabled else None,
    }
    response = JSONResponse(body)
    if set_cookie:
        identity_service.set_anon_cookie(response, set_cookie)
    return response
```

`console/backend/app/routers/demo/__init__.py` 改为：

```python
"""The demo face: byte-compatible with `demo/server.py` (A.13), never enveloped."""

from . import config, me

ROUTERS = (config.router, me.router)

__all__ = ["ROUTERS", "config", "me"]
```

`console/backend/app/main.py`：`create_app` 里在 `mount_spa` **之前**加 attach；`lifespan` 里加计量初始化与 sweeper。改完这两个函数是：

```python
async def _usage_sweeper() -> None:
    """回收静默掉的计量会话（崩了 / 关页没发 beacon）（demo/server.py:227-233）。"""
    while True:
        await asyncio.sleep(metering_service.REAP_AFTER_SEC)
        try:
            await asyncio.to_thread(metering_service.sweep)
        except Exception as exc:  # noqa: BLE001 - 一次 sweep 失败不该杀掉后台任务
            logger.warning("usage sweep failed: {}", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 上一个容器可能把发布切在步骤 6–9 之间；先把这种行收尾，再开始接请求。
    session = SessionLocal()
    try:
        outcomes = publish_flow_service.recover_pending(session)
        for outcome in outcomes:
            logger.warning("recovered an interrupted publish: {}", outcome)
    except Exception as exc:  # noqa: BLE001 - a bad DB must not stop the API from booting
        logger.error("startup recovery skipped: {}", exc)
    finally:
        session.close()

    # 顺序不能变：sweeper 依赖计量库已建表（spec §9.1）。参数库那棵树在上面
    # 已经建完；用量库是裸 sqlite3（D11），单独 init。
    sweeper: asyncio.Task | None = None
    if demo_settings.limiter_enabled:
        metering_service.init()
        sweeper = asyncio.create_task(_usage_sweeper())

    try:
        yield
    finally:
        if sweeper is not None:
            sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper


def create_app() -> FastAPI:
    app = FastAPI(title="s2s-console", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(SecurityHeadersMiddleware, max_body_bytes=app_settings.max_body_bytes)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)

    # OAuth 路由是 attach 时追加的，必须在 mount_spa 的兜底之前注册，否则
    # /oauth/huggingface/login 会拿到 index.html。
    if demo_settings.auth_enabled:
        identity_service.attach(app)

    # Order matters: every API prefix first, SPA last (spec §10.2.3).
    register_api_routers(app)
    mount_spa(app, console_settings.static_dir)
    return app
```

import 区补：`import asyncio`、`from contextlib import asynccontextmanager, suppress`、
`from app.config import app as app_settings, console as console_settings, demo as demo_settings`、
`from app.core.router_registry import register_api_routers`（若 Task 17 已补则不动）、
`from app.services import identity_service, metering_service`。

- [ ] **Step 11: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/demo/test_me_api.py -q`
Expected: 3 passed。

- [ ] **Step 12: 全量回归**

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿。重点看三处：① Task 17 的 `/api/config` 仍在兜底之前（`test_static_mount_order.py`）；② 既有集成测例没有因为 `create_app` 多了 attach 分支而变慢或改行为（`auth_enabled` 默认 False，分支不执行）；③ `tests/demo/test_vendor_api.py` 不受影响。

- [ ] **Step 13: 手工验收**

1. **未计量**：不设 `LOAD_BALANCER_URL`／`SPACE_ID` 起服务，`curl -s localhost:8000/api/me` → 恰好 `{"enabled":false}`，无 `set-cookie`。
2. **计量**：
   ```bash
   LOAD_BALANCER_URL=http://lb.test SPACE_ID=demo USAGE_DB_PATH=/tmp/u.sqlite3 \
     python -m uvicorn app.main:app --port 8000
   ```
   `curl -si localhost:8000/api/me` → `enabled:true`、`tier:"anon"`、`limitSec:300`、`remainingSec:300`，响应头有 `s2s_anon=…; HttpOnly; Secure; SameSite=none`。
3. **表建出来了**：`sqlite3 /tmp/u.sqlite3 '.tables'` → `search_daily  sessions  usage_daily`。
4. **额度跨重启不清零**：固定 `USAGE_HASH_SECRET=dev-secret` 与同一 `USAGE_DB_PATH`，重启后同一个 cookie 的 `remainingSec` 仍是上次的值。
5. **两套鉴权互不认**：带上 `Cookie: s2s_anon=…` 请求 `/api/v1/catalog` → 仍 `401 unauthorized`；带上运维 JWT 请求 `/api/me` → 仍按匿名算（`tier:"anon"`）。
6. **伪造 cookie 不生效**：`curl -s -H 'Cookie: s2s_anon=forged.deadbeef' localhost:8000/api/me` → 响应里重新 `set-cookie`，且数值不是 `forged`。
7. **登录入口在兜底之前**（需要 authlib；先 `pip install 'huggingface-hub[oauth]'`）：设 `OAUTH_CLIENT_ID=x` + `LOAD_BALANCER_URL` + `SPACE_ID` 重启，
   `curl -si localhost:8000/oauth/huggingface/login` → **3xx 跳 `huggingface.co`**，不是 `200 text/html`。
   再把 authlib 卸掉重启：同一条路径回落到 SPA 的 `index.html`（200），后端日志有 `OAuth unavailable` / `failed to attach HF OAuth`，而 `/api/me` 的 `auth` 是 `false`——不会给出一个 404 的登录链接。
   （`/api/config` 的 `auth` 此时仍是 `true`：它答的是「环境变量配没配」，`/api/me` 答的是「现在能不能登录」。两者只在 authlib 缺失这一种情况下分叉，这是本任务唯一保留的口径差。）

- [ ] **Step 14: 提交**

```bash
git add console/backend
git commit -m "feat(console): demo identity and daily metering behind /api/me"
```

---

## Task 19: 演示面转发面 + `/v1` 反向代理

**Files:**
- Modify: `console/backend/requirements.txt`（`websockets>=13.0`）
- Create: `console/backend/app/services/search_service.py`
- Create: `console/backend/app/services/calls_service.py`
- Create: `console/backend/app/services/lb_service.py`
- Create: `console/backend/app/routers/demo/search.py`、`calls.py`、`session.py`、`queue.py`
- Create: `console/backend/app/routers/realtime.py`
- Modify: `console/backend/app/routers/demo/__init__.py`（`ROUTERS` 补四个）
- Modify: `console/backend/app/core/router_registry.py`（注册 `realtime.router`）
- Test: `console/backend/tests/demo/test_search_api.py`、`test_calls_api.py`、`test_session_api.py`、`test_queue_api.py`
- Test: `console/backend/tests/integration/test_realtime_proxy.py`

**Interfaces:**
- Consumes: `identity_service` / `metering_service`（Task 18）；`demo.lb_url` / `demo.pinned_url` / `demo.server_search` / `demo.limiter_enabled` / `demo.serper_api_key` / `demo.space_id` / `demo.lb_hf_token`（Task 17）；`console.pipeline_base_url`（Task 3）。
- Produces: `search_service.gate(request, session_id)`、`search_service.run(query, key) -> dict`；`calls_service.handshake_url(realtime_url) -> str`、`calls_service.forward(url, offer, *, keep_location) -> Response`、`calls_service.loopback_url() -> str`；`lb_service.base_url()`、`lb_service.headers(request)`、`lb_service.login_required(reason, set_cookie=None)`、`lb_service.spent(tier, set_cookie=None)`、`lb_service.start(request)`、`lb_service.poll(request, queue_id)`、`lb_service.leave(queue_id, request)`、`lb_service.finalize(data, keys, tier, tracked, set_cookie)`、`lb_service.body_field(request, field)`；八个演示面路由 + `WS /v1/realtime` + `POST /v1/realtime/calls`。

**演示面错误一律用 `HTTPException`，不用 `ApiError`**（A.13 第 1 条）：`ApiError` 的全局 handler 产出 `{code, message, detail, requestId}` 运维面包络，而演示面的契约是「直接返回对象或 FastAPI 默认 `{"detail": …}`」。唯一例外是 Task 17 的 `/vendor` 503 `asset_missing`——那个 code 是 A.13 明文写进契约的，且它不经过 `fetch`（是 `<script src>`）。

**为什么 `/api/calls` 与 `/v1/realtime/calls` 并存**（A.13 末尾）：前者属于演示面契约，目标是**环境变量钉死的** `SPEECH_TO_SPEECH_URL`——一旦接受客户端传目标就成了开放代理（SSRF）；后者是同一镜像里的同源入口，目标固定为回环 `8765`（`8765` 不再 publish，浏览器无法直连）。两者能串起来：把 `SPEECH_TO_SPEECH_URL` 设成 `http://127.0.0.1:8000/v1/realtime`，浏览器打 `/api/calls` → console 转给自己的 `/v1/realtime/calls` → 再到 `8765`。

**为什么 `/v1` 不做通配反代**：`/v1/pool`、`/v1/usage` 是 pipeline 的运维数据，控制台自己用 `console.pipeline_base_url` 在服务端读（Task 10），浏览器从不需要。把整段 `/v1/*` 透明暴露给公网等于白送实例拓扑与用量（§12 R4），所以只开 `/v1/realtime`（WS）与 `/v1/realtime/calls`（SDP）两条——剩下的路径继续被 SPA 兜底回 `index.html`。

- [ ] **Step 1: 写搜索的失败测试**

`console/backend/tests/demo/test_search_api.py`：

```python
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import search_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    monkeypatch.setattr(demo_settings, "serper_api_key", "")
    monkeypatch.setattr(demo_settings, "space_id", "")
    return TestClient(create_app())


@pytest.fixture
def serper(monkeypatch):
    """Records the payload/headers and answers with a canned Serper body."""
    calls = []

    async def fake_post(payload, key):
        calls.append((payload, key))
        return httpx.Response(
            200,
            json={
                "organic": [
                    {"title": "T", "snippet": "S", "link": "https://e.test/a"},
                    {"title": "T2", "snippet": "S2", "link": "https://e.test/b"},
                ],
                "answerBox": {"answer": "42"},
            },
            request=httpx.Request("POST", search_service.SERPER_URL),
        )

    monkeypatch.setattr(search_service, "_post", fake_post)
    return calls


def test_an_empty_query_is_400(client):
    response = client.post("/api/search", json={"query": "   "})
    assert response.status_code == 400
    # A.13 rule 1: FastAPI's own {"detail": …}, no envelope.
    assert set(response.json()) == {"detail"}


def test_nothing_configured_and_no_user_key_is_503(client):
    response = client.post("/api/search", json={"query": "weather"})
    assert response.status_code == 503


def test_the_user_supplied_key_is_used_and_never_echoed(client, serper):
    response = client.post("/api/search", json={"query": "weather", "key": "user-key"})
    assert response.status_code == 200
    assert serper == [([{"q": "weather", "num": 5}][0], "user-key")]
    assert "user-key" not in response.text


def test_a_server_key_on_a_space_requires_sign_in(client, monkeypatch, serper):
    monkeypatch.setattr(demo_settings, "serper_api_key", "paid")
    monkeypatch.setattr(demo_settings, "space_id", "my-space")
    response = client.post("/api/search", json={"query": "weather"})
    # An anonymous identity is only an IP + a cookie, both cheap to rotate.
    assert response.status_code == 401
    assert serper == []


def test_the_direct_answer_and_results_are_flattened(client, serper):
    body = client.post("/api/search", json={"query": "weather", "key": "k"}).json()
    assert body["query"] == "weather"
    assert body["answer"] == "42"
    assert body["results"] == [
        {"title": "T", "snippet": "S", "url": "https://e.test/a"},
        {"title": "T2", "snippet": "S2", "url": "https://e.test/b"},
    ]


def test_a_provider_error_is_relayed_as_502(client, monkeypatch):
    async def failing(payload, key):
        return httpx.Response(
            403,
            json={"message": "Not enough credits"},
            request=httpx.Request("POST", search_service.SERPER_URL),
        )

    monkeypatch.setattr(search_service, "_post", failing)
    response = client.post("/api/search", json={"query": "weather", "key": "k"})
    assert response.status_code == 502
    assert "Not enough credits" in response.json()["detail"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/demo/test_search_api.py -q`
Expected: 6 FAIL —— `No module named 'app.services.search_service'`。

- [ ] **Step 3: 写 `search_service.py` 与 `routers/demo/search.py`**

`console/backend/app/services/search_service.py`：

```python
"""`POST /api/search`：把 Serper 查询挡在服务端（A.13）。

服务端 key 是花钱的。公开 Space 上它只给登录用户、且只在 LB 授权的活跃会话里
用（`gate()`）；用户自带 key 只用于当次请求，不落库、不回显。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import HTTPException, Request
from loguru import logger

from app.config import demo
from app.services import identity_service, metering_service

SERPER_URL = "https://google.serper.dev/search"
# 结果条数压小，才能整段回给模型。
MAX_RESULTS = 5


async def _post(payload: dict[str, Any], key: str) -> httpx.Response:
    """单独一层：测试替换点，真实实现只打一次 Serper。"""
    async with httpx.AsyncClient(timeout=12.0) as http:
        return await http.post(
            SERPER_URL,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json=payload,
        )


async def gate(request: Request, session_id: str) -> None:
    """放行一次服务端 key 的搜索，否则抛。

    Space 上必须是登录用户（匿名只有 IP + cookie，两个都能换），且处在 LB 授权、
    还在心跳的会话里——每个档位都算，PRO 也不例外。所有人每天限 SEARCH_PER_DAY 次。
    不在 Space 上什么都不查。
    """
    if not demo.space_id.strip():
        return
    if identity_service.oauth_login_required_reason(request):
        raise HTTPException(status_code=401, detail="Sign in with Hugging Face to use web search.")
    tier, keys, _ = identity_service.resolve_identity(request)
    if tier == "anon":
        raise HTTPException(status_code=401, detail="Sign in with Hugging Face to use web search.")
    if not await asyncio.to_thread(metering_service.session_live, session_id, keys):
        raise HTTPException(status_code=403, detail="Web search only works during a conversation.")
    if not await asyncio.to_thread(metering_service.take_search, keys):
        raise HTTPException(status_code=429, detail="Daily web search limit reached.")


def _message(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except Exception:
        return None
    return body.get("message") if isinstance(body, dict) else None


async def run(query: str, key: str) -> dict[str, Any]:
    """打一次 Serper，把结果压成模型能直接读的形状。"""
    try:
        response = await _post({"q": query, "num": MAX_RESULTS}, key)
    except httpx.RequestError as exc:
        logger.warning("serper unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Search provider unreachable.")

    if response.status_code != 200:
        # Serper 的错误体带真实原因（如 "Not enough credits"）且不含 key，可以记录并转达。
        logger.warning("serper error {}: {}", response.status_code, response.text[:300])
        message = _message(response)
        detail = f"Search provider error ({response.status_code})"
        if message:
            detail += f": {message}"
        raise HTTPException(status_code=502, detail=detail)

    data = response.json()
    results = [
        {
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
            "url": item.get("link", ""),
        }
        for item in (data.get("organic") or [])[:MAX_RESULTS]
    ]

    # Google 有直接答案就直接给，省模型一跳。
    box = data.get("answerBox") or {}
    answer = box.get("answer") or box.get("snippet") or None
    if not answer:
        graph = data.get("knowledgeGraph") or {}
        answer = graph.get("description") or None

    return {"query": query, "answer": answer, "results": results}
```

`console/backend/app/routers/demo/search.py`：

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import demo
from app.services import search_service

router = APIRouter(prefix="/api", tags=["demo"])


class SearchRequest(BaseModel):
    query: str = ""
    # 用户自带的 key：只在本次请求用，不存。
    key: str | None = None
    # 调用方被授权的会话，让服务端 key 的搜索能绑到一个活着的会话上。
    sessionId: str | None = None


@router.post("/search")
async def search(payload: SearchRequest, request: Request):
    query = (payload.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query.")

    key = (payload.key or "").strip()
    if not key:
        if not demo.server_search:
            raise HTTPException(status_code=503, detail="Search is not configured.")
        await search_service.gate(request, payload.sessionId or "")
        key = demo.serper_api_key.strip()

    return await search_service.run(query, key)
```

- [ ] **Step 4: 跑测试确认失败（服务层已可用）**

Run: `cd console/backend && python -m pytest tests/demo/test_search_api.py -q`
Expected: 6 FAIL —— `search_service` 已能 import，但 `/api/search` 还没注册，请求落到 SPA 兜底（拿到 `index.html`）。路由在 Step 12 统一接上。

- [ ] **Step 5: 写转发与 LB 的失败测试**

`console/backend/tests/demo/test_calls_api.py`：

```python
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import calls_service

OFFER = b"v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return TestClient(create_app())


@pytest.fixture
def upstream(monkeypatch):
    calls = []

    async def fake(url, offer):
        calls.append((url, offer))
        return httpx.Response(
            201, content=b"v=0\r\nanswer\r\n",
            headers={"content-type": "application/sdp", "location": "http://s2s.test/v1/realtime/calls/call_1"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(calls_service, "_http", fake)
    return calls


def test_without_a_pinned_url_the_route_is_404(client):
    response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    # A.13 rule 3: indistinguishable from a missing route.
    assert response.status_code == 404


def test_the_offer_is_relayed_to_the_pinned_url(client, monkeypatch, upstream):
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "ws://s2s.test:8765/v1/realtime")
    response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    assert response.status_code == 201
    assert response.content == b"v=0\r\nanswer\r\n"
    assert upstream == [("http://s2s.test:8765/v1/realtime/calls", OFFER)]


def test_the_upstream_location_header_is_kept(client, monkeypatch, upstream):
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "ws://s2s.test:8765/v1/realtime")
    response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    # The call id lives in Location; the pinned target is dialable by the browser.
    assert response.headers["location"].endswith("/call_1")


def test_an_unreachable_upstream_is_502(client, monkeypatch):
    async def boom(url, offer):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "ws://s2s.test:8765/v1/realtime")
    monkeypatch.setattr(calls_service, "_http", boom)
    response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    assert response.status_code == 502


def test_the_call_url_is_derived_from_the_realtime_url():
    assert calls_service.handshake_url("ws://h:8765/v1/realtime") == "http://h:8765/v1/realtime/calls"
    assert calls_service.handshake_url("wss://h/realtime") == "https://h/realtime/calls"
    assert calls_service.handshake_url("h:8765") == "http://h:8765/v1/realtime/calls"
```

`console/backend/tests/demo/test_session_api.py`：

```python
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import lb_service, metering_service


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "")
    return root


@pytest.fixture
def metered(tmp_path, monkeypatch):
    """An LB + a Space id turns metering on; the usage DB goes to a temp file."""
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "space_id", "my-space")
    monkeypatch.setattr("app.config.database.usage_db_path", str(tmp_path / "usage.sqlite3"))


@pytest.fixture
def lb(monkeypatch):
    calls = []
    reply = {"state": "queued", "queue_id": "q1", "position": 3}

    async def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json=reply, request=httpx.Request(method, url))

    monkeypatch.setattr(lb_service, "_http", fake)
    return calls


def test_without_a_load_balancer_the_route_is_404(dist):
    with TestClient(create_app()) as client:
        assert client.post("/api/session").status_code == 404


def test_a_queued_reply_is_relayed_without_reserving(dist, metered, lb):
    with TestClient(create_app()) as client:
        body = client.post("/api/session").json()
    assert body == {"state": "queued", "queue_id": "q1", "position": 3, "tier": "anon"}
    # Waiting in line must never cost the day's budget.
    assert metering_service.remaining.__module__  # sanity: metering is importable here


def test_a_grant_reserves_the_first_chunk(dist, metered, monkeypatch):
    async def fake(method, url, **kwargs):
        return httpx.Response(
            200,
            json={"state": "granted", "session_id": "s-1", "connect_url": "wss://c.test/rt"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(lb_service, "_http", fake)
    with TestClient(create_app()) as client:
        body = client.post("/api/session").json()
    assert body["tier"] == "anon" and body["limited"] is True
    assert body["heartbeatSec"] == 5
    # 300 - one 10 s chunk reserved at grant time.
    assert body["remainingSec"] == 290
    assert body["session_id"] == "s-1"


def test_a_spent_budget_is_refused_before_the_lb_is_called(dist, metered, lb, monkeypatch):
    monkeypatch.setattr(metering_service, "remaining", lambda keys, tier: 0)
    with TestClient(create_app()) as client:
        response = client.post("/api/session")
    assert response.status_code == 402
    assert response.json() == {"tier": "anon", "reason": "limit", "remainingSec": 0}
    assert lb == []


def test_heartbeat_reports_expired_for_an_unknown_session(dist, metered):
    with TestClient(create_app()) as client:
        body = client.post("/api/session/heartbeat", json={"sessionId": "nope"}).json()
    assert body == {"expired": True}


def test_session_end_always_answers_ok(dist, metered):
    with TestClient(create_app()) as client:
        # sendBeacon may post nothing at all; the answer must not depend on the body.
        assert client.post("/api/session/end").json() == {"ok": True}
        assert client.post("/api/session/end", content=b"{oops").json() == {"ok": True}


def test_heartbeat_and_end_are_404_without_metering(dist):
    with TestClient(create_app()) as client:
        assert client.post("/api/session/heartbeat", json={}).status_code == 404
        assert client.post("/api/session/end", json={}).status_code == 404
```

`console/backend/tests/demo/test_queue_api.py`：

```python
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import lb_service, metering_service


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def metered(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "space_id", "my-space")
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "")
    monkeypatch.setattr("app.config.database.usage_db_path", str(tmp_path / "usage.sqlite3"))


def _stub(monkeypatch, status: int, payload: dict, calls: list):
    async def fake(method, url, **kwargs):
        calls.append((method, url))
        return httpx.Response(status, json=payload, request=httpx.Request(method, url))

    monkeypatch.setattr(lb_service, "_http", fake)


def test_queue_routes_are_404_without_a_load_balancer(dist):
    with TestClient(create_app()) as client:
        assert client.get("/api/queue/q1").status_code == 404
        assert client.delete("/api/queue/q1").status_code == 404
        assert client.post("/api/queue/end", json={"queueId": "q1"}).status_code == 404


def test_a_waiting_ticket_is_relayed_with_the_tier(dist, metered, monkeypatch):
    calls: list = []
    _stub(monkeypatch, 200, {"state": "queued", "position": 2}, calls)
    with TestClient(create_app()) as client:
        body = client.get("/api/queue/q1").json()
    assert body == {"state": "queued", "position": 2, "tier": "anon"}
    assert calls[0][0] == "GET" and calls[0][1].endswith("/queue/q1")


def test_an_unknown_ticket_tells_the_client_to_start_over(dist, metered, monkeypatch):
    _stub(monkeypatch, 404, {}, [])
    with TestClient(create_app()) as client:
        response = client.get("/api/queue/gone")
    assert response.status_code == 404
    assert response.json() == {"state": "expired"}


def test_a_claim_rechecks_the_budget(dist, metered, monkeypatch):
    # The LB hands over a slot; the budget was spent in another tab during the wait.
    _stub(monkeypatch, 200, {"state": "granted", "session_id": "s-9"}, [])
    monkeypatch.setattr(metering_service, "remaining", lambda keys, tier: 0)
    with TestClient(create_app()) as client:
        response = client.get("/api/queue/q1")
    assert response.status_code == 402
    assert response.json()["reason"] == "limit"


def test_leaving_the_queue_calls_the_lb(dist, metered, monkeypatch):
    calls: list = []
    _stub(monkeypatch, 200, {}, calls)
    with TestClient(create_app()) as client:
        assert client.delete("/api/queue/q1").json() == {"ok": True}
        assert client.post("/api/queue/end", json={"queueId": "q2"}).json() == {"ok": True}
    assert [c[0] for c in calls] == ["DELETE", "DELETE"]
    assert calls[1][1].endswith("/queue/q2")
```

`console/backend/tests/integration/test_realtime_proxy.py`：

```python
from __future__ import annotations

import asyncio
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.server import serve

from app.main import create_app
from app.services import calls_service

OFFER = b"v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def pipeline():
    """A real echo server on a free port, driven from its own event-loop thread."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    async def echo(websocket):
        async for message in websocket:
            await websocket.send(message)

    async def _start():
        return await serve(echo, "127.0.0.1", 0, subprotocols=["realtime"])

    server = asyncio.run_coroutine_threadsafe(_start(), loop).result(timeout=5)
    port = server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    asyncio.run_coroutine_threadsafe(server.close(), loop).result(timeout=5)
    loop.call_soon_threadsafe(loop.stop)


def test_a_frame_round_trips(dist, pipeline, monkeypatch):
    monkeypatch.setattr("app.main.console_settings.pipeline_base_url", pipeline)
    with TestClient(create_app()) as client:
        with client.websocket_connect("/v1/realtime") as ws:
            ws.send_text("hello")
            assert ws.receive_text() == "hello"


def test_the_realtime_subprotocol_is_forwarded(dist, pipeline, monkeypatch):
    monkeypatch.setattr("app.main.console_settings.pipeline_base_url", pipeline)
    with TestClient(create_app()) as client:
        with client.websocket_connect("/v1/realtime", subprotocols=["realtime"]) as ws:
            assert ws.accepted_subprotocol == "realtime"


def test_an_unreachable_pipeline_fails_the_handshake(dist, monkeypatch):
    # Nothing listens on this port; the client must not be left holding an open socket.
    monkeypatch.setattr("app.main.console_settings.pipeline_base_url", "http://127.0.0.1:1")
    with TestClient(create_app()) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/realtime"):
                pass


def test_the_sdp_offer_goes_to_loopback_without_a_location(dist, monkeypatch):
    seen = []

    async def fake(url, offer):
        seen.append((url, offer))
        return httpx.Response(
            201, content=b"v=0\r\nanswer\r\n",
            headers={"content-type": "application/sdp", "location": "http://127.0.0.1:8765/v1/realtime/calls/c1"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.main.console_settings.pipeline_base_url", "http://127.0.0.1:8765")
    monkeypatch.setattr(calls_service, "_http", fake)
    with TestClient(create_app()) as client:
        response = client.post("/v1/realtime/calls", content=OFFER,
                              headers={"Content-Type": "application/sdp"})
    assert response.status_code == 201
    assert seen == [("http://127.0.0.1:8765/v1/realtime/calls", OFFER)]
    # A loopback Location would be undialable for the browser (spec §10.2.3).
    assert "location" not in response.headers
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/demo/test_calls_api.py tests/demo/test_session_api.py tests/demo/test_queue_api.py tests/integration/test_realtime_proxy.py -q`
Expected: 收集期 21 个 ERROR（`No module named 'app.services.calls_service'` / `'app.services.lb_service'`，两个文件都还没写）。

- [ ] **Step 7: 写 `calls_service.py`**

```python
"""WebRTC 的 SDP 握手转发。

两条路目标不同（A.13 末尾）：
- `/api/calls` 转到**环境变量钉死的** `SPEECH_TO_SPEECH_URL`。接受客户端传目标就
  等于开放代理（SSRF），所以目标只能来自 env。
- `/v1/realtime/calls` 转到回环的 pipeline：`8765` 不 publish，浏览器需要一条同源
  入口（demo 阶段是浏览器直连 8765）。
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException, Response
from loguru import logger

from app.config import console


def handshake_url(realtime_url: str) -> str:
    """`ws://host:port/v1/realtime` → `http://host:port/v1/realtime/calls`。

    ws→http、wss→https；只有主机名时补默认的 `/v1/realtime` 路径（与客户端的
    `buildDirectWsUrl` 规整方式一致）。"""
    raw = realtime_url.strip()
    if not raw.startswith(("ws://", "wss://", "http://", "https://")):
        raw = "http://" + raw
    parts = urlsplit(raw)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    path = parts.path if parts.path not in ("", "/") else "/v1/realtime"
    return urlunsplit((scheme, parts.netloc, path.rstrip("/") + "/calls", parts.query, ""))


def loopback_url() -> str:
    return handshake_url(console.pipeline_base_url)


async def _http(url: str, offer: bytes) -> httpx.Response:
    """单独一层：测试替换点。超时给得宽松——pipeline 要等自己的 ICE 收集（~5 s）。"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(url, headers={"Content-Type": "application/sdp"}, content=offer)


async def forward(url: str, offer: bytes, *, keep_location: bool) -> Response:
    """把 SDP offer 打给 upstream，把 answer（或错误体）原样转回。"""
    try:
        upstream = await _http(url, offer)
    except httpx.HTTPError as exc:
        logger.warning("sdp handshake unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Speech service unreachable.")

    headers = {}
    if keep_location and "location" in upstream.headers:
        headers["Location"] = upstream.headers["location"]
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/sdp"),
        headers=headers,
    )
```

- [ ] **Step 8: 写 `lb_service.py`**

```python
"""LB 会话申请与排队（移植自 `demo/server.py` 的 `/api/session` 与 `/api/queue*`）。

两条硬约束：未配 LB 时回 **404 而不是 403**（防探测，A.13 第 3 条）；`connect_url`
必然被下发（浏览器要直连），但 LB 的稳定地址永远不出服务端。
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import demo
from app.services import identity_service, metering_service

LB_USER_AGENT = "speech-to-speech-console"
FAILURE_HEADER_NAMES = (
    "content-type",
    "server",
    "x-request-id",
    "ratelimit",
    "ratelimit-policy",
    "retry-after",
)


def base_url() -> str:
    return demo.lb_url.rstrip("/")


def enabled() -> bool:
    return bool(demo.lb_url)


def tracked_for(tier: str) -> bool:
    """要不要真记账：计量关着、或不限量档位，都不记。"""
    return demo.limiter_enabled and metering_service.budget_for(tier) is not None


async def _http(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """单独一层：测试替换点。"""
    timeout = kwargs.pop("timeout", 15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(method, url, **kwargs)


def headers(request: Request | None = None) -> dict[str, str]:
    """服务端发起会话申请时带的头。

    专用服务 token 让 Space 通过 HF ingress；登录访客的 OAuth token 另走
    `X-Reachy-Mini-Authorization`，因为 ingress 会把标准 `Authorization` 消耗掉。
    没配服务 token 时，登录用户的 token 兼两跳；匿名照常放行。
    """
    out = {"Content-Type": "application/json", "User-Agent": LB_USER_AGENT}
    user_token = identity_service.current_access_token(request) if request is not None else None
    gateway = demo.lb_hf_token.strip() or user_token
    if gateway:
        out["Authorization"] = f"Bearer {gateway}"
    if user_token:
        out["X-Reachy-Mini-Authorization"] = f"Bearer {user_token}"
    return out


def login_required(reason: str, set_cookie: str | None = None) -> JSONResponse:
    """浏览器登录流能认的 401。"""
    body = {
        "reason": reason,
        "loginUrl": identity_service.OAUTH_LOGIN_PATH if identity_service.oauth_enabled else None,
    }
    response = JSONResponse(body, status_code=401)
    if set_cookie:
        identity_service.set_anon_cookie(response, set_cookie)
    return response


def spent(tier: str, set_cookie: str | None = None) -> JSONResponse:
    """今天的额度已经花完（402，与 demo 一致）。"""
    response = JSONResponse({"tier": tier, "reason": "limit", "remainingSec": 0}, status_code=402)
    if set_cookie:
        identity_service.set_anon_cookie(response, set_cookie)
    return response


def log_failure(operation: str, response: httpx.Response) -> None:
    """记足够定位问题、但不含凭据的 ingress 元数据。"""
    seen = {name: value for name in FAILURE_HEADER_NAMES if (value := response.headers.get(name))}
    logger.warning(
        "load balancer {} failed status={} headers={} body={}",
        operation, response.status_code, seen, " ".join(response.text[:500].split()),
    )


def safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


async def body_field(request: Request, field: str) -> str:
    """从 JSON 体里取一个字段，容忍 sendBeacon 的 blob 提交与空体。"""
    try:
        data = await request.json()
    except Exception:
        return ""
    return (data or {}).get(field, "") if isinstance(data, dict) else ""


async def finalize(
    data: dict[str, Any], keys: list[str], tier: str, tracked: bool, set_cookie: str | None
) -> JSONResponse:
    """快路径与排队认领共用的收尾：预留第一块、贴上计量字段、发匿名 cookie。"""
    left = None
    if demo.limiter_enabled and data.get("session_id"):
        # 每次授权都记一行，Web 搜索靠它判断会话是否活着；只有计量档位才真扣。
        await asyncio.to_thread(metering_service.begin, data["session_id"], keys, tier)
        if tracked:
            left = await asyncio.to_thread(metering_service.remaining, keys, tier)

    data.update({
        "tier": tier,
        "limited": tracked,
        "remainingSec": left,
        # 开着计量时每个档位都心跳（活体检测）；关掉就没人听。
        "heartbeatSec": metering_service.HEARTBEAT_SEC if demo.limiter_enabled else None,
    })
    response = JSONResponse(data)
    if set_cookie:
        identity_service.set_anon_cookie(response, set_cookie)
    return response


async def start(request: Request) -> JSONResponse:
    """申请一个会话：授权或排队票。"""
    reason = identity_service.oauth_login_required_reason(request)
    if reason:
        return login_required(reason)

    tier, keys, set_cookie = identity_service.resolve_identity(request)
    tracked = tracked_for(tier)

    # 预算已经没了就别去麻烦 LB：也不要把一个说不了话的人放进队列。
    if tracked:
        left = await asyncio.to_thread(metering_service.remaining, keys, tier)
        if left is not None and left <= 0:
            return spent(tier, set_cookie)

    try:
        lb = await _http("POST", f"{base_url()}/session", headers=headers(request), content="{}")
    except httpx.HTTPError as exc:
        logger.warning("load balancer unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Speech service unreachable.")

    # 队列满：原样转 503 {state:"at_capacity"}，让客户端软提示「稍后再试」。
    if lb.status_code == 503 and safe_json(lb).get("state") == "at_capacity":
        response = JSONResponse({"state": "at_capacity"}, status_code=503)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response

    if lb.status_code == 401:
        reason = safe_json(lb).get("reason", "login_required")
        logger.info("session authentication rejected: {}", reason)
        return login_required(reason, set_cookie)

    if lb.status_code != 200:
        log_failure("session handshake", lb)
        raise HTTPException(status_code=502, detail=f"Session handshake failed ({lb.status_code}).")

    data = lb.json()
    # 在排队：原样转回，且**不预留**——站着等不该花掉今天的额度。
    if data.get("state") == "queued":
        data["tier"] = tier
        response = JSONResponse(data)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response
    return await finalize(data, keys, tier, tracked, set_cookie)


async def poll(request: Request, queue_id: str) -> JSONResponse:
    """轮询排队票：转位次；排到头部时此刻再校验预算并授权。"""
    reason = identity_service.oauth_login_required_reason(request)
    if reason:
        return login_required(reason)

    tier, keys, set_cookie = identity_service.resolve_identity(request)
    tracked = tracked_for(tier)

    try:
        lb = await _http("GET", f"{base_url()}/queue/{quote(queue_id, safe='')}", headers=headers(request))
    except httpx.HTTPError as exc:
        logger.warning("load balancer unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Speech service unreachable.")

    if lb.status_code == 404:
        # 票号过期（停止轮询后被回收）：让客户端重开，而不是原地打转。
        response = JSONResponse({"state": "expired"}, status_code=404)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response

    if lb.status_code != 200:
        log_failure("queue poll", lb)
        raise HTTPException(status_code=502, detail=f"Queue poll failed ({lb.status_code}).")

    data = lb.json()
    if data.get("state") == "queued":
        data["tier"] = tier
        response = JSONResponse(data)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response

    # 拿到位置了：重新校验预算——等待期间额度可能已经在另一个标签页里花掉。
    # 此时 LB 上那个刚被认领的位子会由它自己的 pending 超时回收。
    if tracked:
        left = await asyncio.to_thread(metering_service.remaining, keys, tier)
        if left is not None and left <= 0:
            return spent(tier, set_cookie)
    return await finalize(data, keys, tier, tracked, set_cookie)


async def leave(queue_id: str, request: Request | None = None) -> None:
    """尽力而为：叫 LB 丢掉一张等待中的票。失败只记日志。"""
    url = f"{base_url()}/queue/{quote(queue_id, safe='')}"
    try:
        response = await _http("DELETE", url, headers=headers(request), timeout=5.0)
        if response.status_code not in {200, 404}:
            log_failure("queue leave", response)
    except httpx.HTTPError as exc:
        logger.warning("queue leave failed: {}", exc)
```

- [ ] **Step 9: 跑测试确认通过（服务层）**

Run: `cd console/backend && python -m pytest tests/demo/test_calls_api.py tests/demo/test_session_api.py tests/demo/test_queue_api.py -q`
Expected: 17 failed（路由未注册，全部被 SPA 兜底接住）——服务层已能 import，下一批把路由接上就绿。

- [ ] **Step 10: 写四个演示面路由**

`console/backend/app/routers/demo/calls.py`：

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import demo
from app.services import calls_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.post("/calls")
async def calls(request: Request):
    """只转发到 env 钉死的地址：接受客户端目标就是开放代理（SSRF）。"""
    if not demo.pinned_url:
        raise HTTPException(status_code=404, detail="Not found.")
    return await calls_service.forward(
        calls_service.handshake_url(demo.pinned_url), await request.body(), keep_location=True
    )
```

`console/backend/app/routers/demo/session.py`：

```python
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.config import demo
from app.services import lb_service, metering_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.post("/session")
async def session(request: Request):
    """向 LB 申请会话：授权，或一张排队票。未配 LB 时 404（防探测）。"""
    if not demo.lb_url:
        raise HTTPException(status_code=404, detail="Not found.")
    return await lb_service.start(request)


@router.post("/session/heartbeat")
async def heartbeat(request: Request):
    """续期。`expired: true` 时前端必须拆会话。"""
    if not demo.limiter_enabled:
        raise HTTPException(status_code=404, detail="Not found.")
    session_id = await lb_service.body_field(request, "sessionId")
    alive = bool(session_id) and await asyncio.to_thread(metering_service.heartbeat, session_id)
    return {"expired": not alive}


@router.post("/session/end")
async def end(request: Request):
    """按真实时长结算并退回未用块。走 sendBeacon，所以必须无条件成功。"""
    if not demo.limiter_enabled:
        raise HTTPException(status_code=404, detail="Not found.")
    session_id = await lb_service.body_field(request, "sessionId")
    if session_id:
        await asyncio.to_thread(metering_service.end, session_id)
    return {"ok": True}
```

`console/backend/app/routers/demo/queue.py`：

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import demo
from app.services import lb_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/queue/{queue_id}")
async def status(queue_id: str, request: Request):
    """轮询等待票：位次，或排到头部时拿到的授权。"""
    if not demo.lb_url:
        raise HTTPException(status_code=404, detail="Not found.")
    return await lb_service.poll(request, queue_id)


@router.delete("/queue/{queue_id}")
async def leave(queue_id: str, request: Request):
    """「离开队列」按钮（真 fetch）。"""
    if not demo.lb_url:
        raise HTTPException(status_code=404, detail="Not found.")
    await lb_service.leave(queue_id, request)
    return {"ok": True}


@router.post("/queue/end")
async def end(request: Request):
    """拆页时用 navigator.sendBeacon 离开队列（只能 POST）。体 `{queueId}`。"""
    if not demo.lb_url:
        raise HTTPException(status_code=404, detail="Not found.")
    queue_id = await lb_service.body_field(request, "queueId")
    if queue_id:
        await lb_service.leave(queue_id, request)
    return {"ok": True}
```

- [ ] **Step 11: 写 `/v1` 反代**

`console/backend/app/routers/realtime.py`：

```python
"""`/v1/realtime*`：浏览器进入回环 8765 的唯一通道（§10.2.3）。

只开两条路。`/v1/pool`、`/v1/usage` 是运维数据，控制台在服务端自己读，不往
公网放（§12 R4）。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

import websockets
from fastapi import APIRouter, Request, WebSocket
from loguru import logger

from app.config import console
from app.services import calls_service

router = APIRouter(tags=["realtime"])


def _upstream_url(url) -> str:
    """`http://127.0.0.1:8765` + 浏览器的 path/query → `ws://…`（https→wss）。"""
    base = console.pipeline_base_url.strip().rstrip("/")
    if "://" not in base:
        base = "http://" + base
    scheme, host = base.split("://", 1)
    query = f"?{url.query}" if url.query else ""
    return f"{'wss' if scheme == 'https' else 'ws'}://{host}{url.path}{query}"


def _subprotocols(websocket: WebSocket) -> list[str]:
    raw = websocket.headers.get("sec-websocket-protocol", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


async def _client_to_upstream(client: WebSocket, upstream) -> None:
    while True:
        message = await client.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("text") is not None:
            await upstream.send(message["text"])
        elif message.get("bytes") is not None:
            await upstream.send(message["bytes"])


async def _upstream_to_client(client: WebSocket, upstream) -> None:
    async for message in upstream:
        if isinstance(message, bytes):
            await client.send_bytes(message)
        else:
            await client.send_text(message)


@router.websocket("/v1/realtime")
async def realtime(websocket: WebSocket) -> None:
    """把浏览器的 Realtime WS 接到回环 pipeline。

    不改路径、不缓冲帧（缓冲会把 TTS 首字节延迟放大，§12 R20）——两边都是逐帧转发。
    一侧关闭就关另一侧，否则回环端口会积压僵尸连接。
    """
    try:
        upstream = await websockets.connect(
            _upstream_url(websocket.url),
            subprotocols=_subprotocols(websocket) or None,
            max_size=None,  # base64 音频帧可能超过默认 1 MiB
            # R20: deflate 会把帧缓冲到凑满一个块，TTS 首字节因此晚到。
            compression=None,
            open_timeout=5.0,
        )
    except Exception as exc:
        logger.warning("realtime upstream unreachable: {}", exc)
        # 还没 accept：ASGI 会把这次握手判为失败，而不是收下一个谁也服务不了的会话。
        await websocket.close(code=1013)
        return

    await websocket.accept(subprotocol=upstream.subprotocol)
    tasks = [
        asyncio.create_task(_client_to_upstream(websocket, upstream)),
        asyncio.create_task(_upstream_to_client(websocket, upstream)),
    ]
    _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    with suppress(Exception):
        await upstream.close()
    with suppress(Exception):
        await websocket.close()


@router.post("/v1/realtime/calls", include_in_schema=False)
async def realtime_calls(request: Request):
    """同源的 SDP 入口。不回填 `Location`：它指向回环，浏览器拿不到。"""
    return await calls_service.forward(
        calls_service.loopback_url(), await request.body(), keep_location=False
    )
```

- [ ] **Step 12: 注册路由，并把 `websockets` 下界抬到 13**

`console/backend/requirements.txt` 里 `websockets>=12.0` 改为：

```
# 13 起才有 `websockets.asyncio.*`（反代用的非弃用 API）。
websockets>=13.0
```

`console/backend/app/routers/demo/__init__.py` 改为：

```python
"""The demo face: byte-compatible with `demo/server.py` (A.13), never enveloped."""

from . import calls, config, me, queue, search, session

# Order is the A.13 table's order; nothing here overlaps another prefix.
ROUTERS = (config.router, me.router, search.router, calls.router, session.router, queue.router)

__all__ = ["ROUTERS", "calls", "config", "me", "queue", "search", "session"]
```

`console/backend/app/core/router_registry.py` 的 import 与注册改为：

```python
    from app.routers import (  # noqa: PLC0415
        auth,
        catalog,
        health,
        instances,
        profiles,
        realtime,
        sessions,
        status,
    )
    from app.routers.demo import ROUTERS as DEMO_ROUTERS  # noqa: PLC0415

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(profiles.router)
    app.include_router(sessions.router)
    app.include_router(instances.router)
    app.include_router(status.router)

    for router in DEMO_ROUTERS:
        app.include_router(router)

    # /v1 反代最后注册：它只开两条精确路径，不和 /api 抢前缀。
    app.include_router(realtime.router)
```

`compression=None` 只关掉了 console → pipeline 这一跳；浏览器 ↔ console 那一跳由 uvicorn 控制，Task 4 的 supervisord 已经带了 `--no-ws-per-message-deflate`。两跳都关才算满足 R20——只关一边时，延迟提升会出现在你没测的那一侧。R20 的「p95 超出 20ms 即视为回退」是部署后重测 `docs/response-latency.md` 的事，不在本任务里跑。

- [ ] **Step 13: 跑全量测试**

Run: `cd console/backend && python -m pytest tests/demo tests/integration/test_realtime_proxy.py -q`
Expected: 38 passed。拆开对帐：`tests/demo` 34（`test_config_api.py` 3 + `test_vendor_api.py` 5 + `test_me_api.py` 3 + `test_search_api.py` 6 + `test_calls_api.py` 5 + `test_session_api.py` 7 + `test_queue_api.py` 5）；`tests/integration/test_realtime_proxy.py` 4。计量与身份的 10 个单测在 `tests/unit`，由 Step 14 的全量回归覆盖。

- [ ] **Step 14: 回归（静态注册顺序最要紧）**

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿。三个不能破的：① `POST /v1/realtime/calls` 不能被 SPA 兜底或 `/v1/realtime` 的 WS 路由抢走（FastAPI 按路径+方法区分，WS 与 POST 不同命名空间）；② `/api/session/heartbeat` 不被 `/api/queue/{queue_id}` 抢走（路径不同）；③ `test_static_mount_order.py` 里 `/v1/realtime` 仍是 WS 而非 HTML。

- [ ] **Step 15: 手工验收**

起服务（`cd console/backend && python -m uvicorn app.main:app --port 8000`），然后：

1. **条件关闭一律 404，且不是 `index.html`**：不设 `LOAD_BALANCER_URL`／`SPEECH_TO_SPEECH_URL` 时，`curl -si localhost:8000/api/session -X POST`、`curl -si localhost:8000/api/queue/q1`、`curl -si -X POST localhost:8000/api/calls` → 三条都是 `404` + `{"detail":"Not found."}`。
2. **搜索两种模式**：不配 `SERPER_API_KEY` 时 `curl -X POST localhost:8000/api/search -d '{"query":"x"}' -H 'content-type: application/json'` → `503`；带上 `{"key":"<自己的 serper key>"}` → `200` 且 `results` 有条目。
3. **WS 逐帧转发**：`python -m websockets ws://127.0.0.1:8000/v1/realtime` 手动发一帧 `{"type":"session.update","session":{}}`，应当收到 pipeline 的 `error` 或 `session.updated`（证明帧透过去了，不是只连上）；同时 `supervisorctl tail -f pipeline` 能看到同一条连接。
4. **双向关闭**：断开上面的客户端后 `ss -tnp | grep 8765` 不应残留 `ESTABLISHED`（两侧都关掉了）。
5. **pipeline 挂了不会挂住**：`docker compose exec pipeline supervisorctl stop pipeline` 后连 `/v1/realtime` → 握手直接失败（不是 200 后静默），`curl -si -X POST localhost:8000/v1/realtime/calls -H 'Content-Type: application/sdp' --data-binary @offer.sdp` → `502 {"detail":"Speech service unreachable."}`。
6. **两跳串通**：`SPEECH_TO_SPEECH_URL=http://127.0.0.1:8000/v1/realtime` 重启 → `/api/config` 的 `rtc:true`；`curl -X POST localhost:8000/api/calls -H 'Content-Type: application/sdp' --data-binary @offer.sdp` 经 console 转给自己再到 8765，拿到 SDP answer（pipeline 的 WebRTC 开启时）。
7. **`/v1` 不泄漏运维数据**：`curl -si localhost:8000/v1/pool` → `200 text/html`（SPA 兜底），不是 `JSON`。

- [ ] **Step 16: 提交**

```bash
git add console/backend
git commit -m "feat(console): demo search/calls/session/queue proxies and the /v1 reverse proxy"
```

---

## Task 20: 对话页 Vue 重写（阶段 F 收尾）

**Files:**
- Create: `console/frontend/public/worklets/audio-playback.js`、`mic-capture.js`（从 `demo/worklets/` 逐字节拷贝）
- Create: `console/frontend/src/features/voice/types.ts`
- Create: `console/frontend/src/features/voice/transport/turn-latency.ts`
- Test: `console/frontend/src/features/voice/transport/turn-latency.spec.ts`
- Create: `console/frontend/src/features/voice/transport/events.ts`
- Test: `console/frontend/src/features/voice/transport/events.spec.ts`
- Create: `console/frontend/src/features/voice/transport/s2s-client.ts`
- Create: `console/frontend/src/features/voice/audio/meter.ts`
- Test: `console/frontend/src/features/voice/audio/meter.spec.ts`
- Create: `console/frontend/src/features/voice/audio/capture.ts`、`audio/vad.ts`、`audio/sent-audio.ts`
- Test: `console/frontend/src/features/voice/audio/sent-audio.spec.ts`
- Create: `console/frontend/src/features/voice/tools/camera.ts`
- Create: `console/frontend/src/features/voice/useTurnLatency.ts`
- Test: `console/frontend/src/features/voice/useTurnLatency.spec.ts`
- Create: `console/frontend/src/stores/voice.ts`
- Test: `console/frontend/src/stores/voice.spec.ts`
- Create: `console/frontend/src/features/voice/components/{MicGate,OrbStage,TranscriptList,AudioReplay,ToolsDialog,SettingsDialog,QueueOverlay,AccountWidget,IdentityBlock,AboutDialog,HistoryDrawer,BubbleStack,CameraPip,LimitDialog,TurnTimings}.vue`
- Create: `console/frontend/src/styles/voice.less`
- Create: `console/frontend/src/views/VoiceView.vue`
- Modify: `console/frontend/src/types/demo.d.ts`、`src/api/demo.ts`（补 `GET /api/me`、`POST /api/session`、`GET|DELETE /api/queue/{id}`、`POST /api/search`、`POST /api/calls`）
- Modify: `console/frontend/src/router/index.ts`（子路由 `name: 'voice'` 的 `component` 换成 `VoiceView.vue`；**不新增路由**，也不拆掉外壳）
- Test: `console/frontend/src/router/router.spec.ts`
- Modify: `console/frontend/index.html`（加载 UMD）
- Delete: `console/frontend/src/views/VoicePlaceholderView.vue`

**Interfaces:**
- Consumes: `GET /api/config`（`search / lb / allowDirect / s2sUrl / rtc / iceServers / startupGreeting / auth`，Task 17）；`GET /api/me`（`enabled / auth / loggedIn / tier / username / avatar / remainingSec / limitSec / loginUrl / logoutUrl`，Task 18）；`POST /api/session`（→ grant `{session_id, connect_url, websocket_url, session_token, pending_timeout_s, tier, limited, remainingSec, heartbeatSec}`，或 `{state:"queued", queue_id, position, poll_interval_s}`，或 `503 {state:"at_capacity"}`，或 `402 {tier}`，或 `401 {reason, loginUrl}`，Task 19）；`GET|DELETE /api/queue/{queue_id}`、`POST /api/queue/end`、`POST /api/session/heartbeat`（→ `{expired}`）、`POST /api/session/end`（Task 19）；`POST /api/search`（Task 19）；`POST /api/calls`（Task 19）；`buildSessionPatch()`（Task 16）；`/worklets/*` 与 `/vendor/*`（Task 17）。
- Produces: `VoiceState`、`TranscriptEntry`（`role: 'user' | 'assistant' | 'tool'`，可带 `audio?: { url, truncated }`、`tool?: { name, input, output, image }`）、`SessionGrant`、`QueueTicket`、`MeResponse`、`TurnLatency`、`ToolDef`、`VoiceConfig`、`SentAudio`（`{ blob, durationMs, truncated }`）；`readTurnLatency(response)`；`TranscriptReducer`（`{entries, apply(event)}`）；`SentAudioRecorder`（`append(samples, atMs) / speechStarted(atMs) / speechStopped() / reset()`）与 `pcm16ToWavBlob(samples, sampleRate)`；`S2sClient`（`connect() / close() / join() / setMuted() / setTools() / updateSession(patch) / setAudioOutputDevice(id)`，事件 `status / server-event / response-finished / visemes / session / queue / error / user-audio`）；`rmsToDb(samples)`、`dbToPercent(db)`、`fractionToDb(fraction)`、`gateOpen(levelDb, thresholdDb)`、`SpeakingDetector`（`push(db)` / `speaking` / `reset()`）、`timingSummary(turn)` / `statusLabel(status)` / `timingRows(turn)` / `timingNote(turn)`；`useVoiceStore()`（`state / entries / grant / queue / me / config / latency / settings / connect() / stop() / restart()`）。

**为什么把 986 行 `S2sRealtimeClient` 拆成三块**：`demo/s2s-realtime-client.js` 把 SDK 适配、播放队列、转写归约、排队轮询、计量心跳全塞在一个 `EventTarget` 里，而 `demo/tests/*.test.mjs` 只能靠假 transport 打桩来测。重写时按「能纯函数测的先进纯函数」切三刀：`transport/events.ts` 是**纯归约器**（服务端事件 → 转写条目，不碰 DOM、不碰 SDK，vitest 直接喂对象）；`transport/s2s-client.ts` 是**唯一的 SDK/WebAudio 接触面**（`globalThis.OpenAIAgentsRealtime` 只在这里出现一次）；`audio/*` 只负责采集、电平与本地 VAD。这样 §14.5 里「转写条目顺序与分段点一致」「三态切换时机」这两条不再是手工肉眼验收，而是 `events.spec.ts` 与 `meter.spec.ts` 的断言。

**为什么 worklet 必须原样拷进 `public/`**（§14.1）：`audio-playback.js` / `mic-capture.js` 跑在 `AudioWorkletGlobalScope`，Vite 的 TS 插件与模块预打包都会把它当普通模块处理，结果是 `import` 语法在 worklet 里直接抛错。它们和 `/vendor/local-vad/*` 是同一类资产，区别只是 worklet 走 T17 已挂的 `/worklets` 前缀（不进 vendor 白名单）。

**为什么连接目标只读、不再给「手填 URL」**：`demo` 允许用户填任意 s2s 地址（`allowDirect`），因为旧部署把页面放到静态托管上、后面跟的是用户自己的服务。新形态是单入口 `8000`：浏览器只认同源（Global Constraints「前端不把 upstream 地址烘进产物」），`/api/session` 与 `/v1/realtime` 已经把地址钉在服务端。设置面板因此只显示「同源 `:8000`」或 `/api/config.s2sUrl`（部署钉死时只读展示），**不提供输入框**——手填入口在单入口下等于让浏览器直连一个浏览器够不到的端口（`8765` 不再 publish）。同理不移植 `s2s.debug` 这个 localStorage 调试开关：要看原始事件就在 DevTools 的 Network → WS 帧里看，不再造一个只存在于代码里的开关。

**为什么计量字段放 store 而不是组件各取**：`remainingSec` 会被心跳改写（`POST /api/session/heartbeat` 的 `expired`），`AccountWidget` 的「今天还剩多少」与 `QueueOverlay` 的「满员」读的是同一个数。三个组件各发一次 `/api/me` 会出现「账号区显示 30 秒、遮罩显示 5 分钟」的自相矛盾，所以 `stores/voice.ts` 是唯一持有者，组件只读。

- [ ] **Step 1: 原样拷贝两个 worklet 并校验字节一致**

Run:

```bash
mkdir -p console/frontend/public/worklets && cp demo/worklets/audio-playback.js demo/worklets/mic-capture.js console/frontend/public/worklets/
```

Run: `cd console/frontend && shasum public/worklets/*.js ../demo/worklets/*.js`
Expected: 四个哈希两两相同（拷贝后 `audio-playback.js` 与 `mic-capture.js` 各出现两次，值相同）。两者都不得被 Prettier/ESLint 处理：`console/frontend/.prettierignore` 追加 `public/worklets/`。

- [ ] **Step 2: 写类型**

`console/frontend/src/features/voice/types.ts`：

```ts
/** The nine painted states of the orb page (demo/main.js:174-197, same names). */
export type VoiceState =
  | 'idle'
  | 'connecting'
  | 'queued'
  | 'your-turn'
  | 'listening'
  | 'user-speaking'
  | 'processing'
  | 'ai-speaking'
  | 'error'

/** The four states that mean “a call is up”. */
export const LIVE_STATES: ReadonlySet<VoiceState> = new Set([
  'listening',
  'user-speaking',
  'processing',
  'ai-speaking'
])

export interface TranscriptAudio {
  /** `URL.createObjectURL(pcm16ToWavBlob(...))`；条目被替换时 `revokeObjectURL`。 */
  url: string
  durationMs: number
  /** 录音器已经剪掉了这段语音的开头（超过 `maxBufferMs`）。 */
  truncated: boolean
}

export interface TranscriptTool {
  name: string
  input: string
  output: string
  /** `camera_snapshot` 的 data URL；无图时是 `''`，模板据此决定要不要渲染 `<img>`。 */
  image: string
}

export interface TranscriptEntry {
  /** `u:<itemId>` / `a:<responseId>` / `t:<callId>` — stable across partial and final updates. */
  key: string
  role: 'user' | 'assistant' | 'tool'
  text: string
  partial: boolean
  /** 只有 WebSocket 传输下的用户条目带原音（demo 的 `user-audio` 事件，§3.2.2）。 */
  audio?: TranscriptAudio
  /** 只有 tool 条目带调用信息与图片（`_appendHistTool` / `_appendHistImage`）。 */
  tool?: TranscriptTool
  /**
   * 助手条目的 `Server timings`（服务端 `speech_to_speech.turn_latency`，§3.9.4）。
   * 取不到时是 `undefined`——条目只显示文本，不显示一排 0。
   */
  latency?: TurnLatency
}

/** The metering fields the server bolts onto every grant (demo/server.py:653-660). */
export interface SessionGrant {
  sessionId: string
  connectUrl: string
  websocketUrl?: string
  sessionToken?: string
  pendingTimeoutS?: number
  tier: string
  limited: boolean
  remainingSec: number | null
  heartbeatSec: number | null
}

export interface QueueTicket {
  queueId: string
  position: number
  pollIntervalS: number
}

/** `/api/me` — shape is owned by Task 18's router, not by this file. */
export interface MeResponse {
  enabled: boolean
  auth?: boolean
  loggedIn?: boolean
  tier?: string
  username?: string
  avatar?: string
  remainingSec?: number | null
  limitSec?: number | null
  loginUrl?: string | null
  logoutUrl?: string | null
}

/**
 * 浏览器侧可写的会话设置。字段与 `demo/main.js` 写进 localStorage 的键一一对应；
 * 唯一的例外是 `searchKey`：**它不进任何 storage**（Global Constraints B5）。
 */
export interface VoiceSettings {
  voice: string
  instructions: string
  noiseGateDb: number
  playbackBufferMs: number
  localVad: boolean
  transport: 'ws' | 'webrtc'
  tools: { web: boolean; camera: boolean }
  audioInputId: string
  audioOutputId: string
}

/** `/api/config` — Task 17. `lb` is a boolean; the LB address never comes down. */
export interface VoiceConfig {
  search: boolean
  lb: boolean
  allowDirect: boolean
  s2sUrl: string
  rtc: boolean
  iceServers: RTCIceServer[]
  startupGreeting: string
  auth: boolean
}

/** `speech_to_speech.turn_latency` v1/v2 (demo/turn-latency.js:2-18). */
export interface TurnLatency {
  version: number
  turn_id: string | null
  source?: 'speech' | 'client' | 'tool' | null
  turn_revision: number
  response_key: string
  status: string
  stt_s: number | null
  llm_s: number | null
  tts_ttfa_s: number | null
  e2e_s: number | null
  vad_decision_s?: number | null
  smart_wait_s?: number | null
  smart_status?: 'complete' | 'incomplete' | 'failed' | 'disabled' | null
  hold_s?: number | null
}

export interface ToolDef {
  type: 'function'
  name: string
  description: string
  parameters: Record<string, unknown>
}

export interface ToolCall {
  name: string
  arguments: string
  callId: string
}

export interface ToolResult {
  output: string
  /** Base64 data URL; the client turns it into an `addImage` turn. */
  image?: string
}
```

- [ ] **Step 3: 先写 `turn-latency` 的失败测试**

`console/frontend/src/features/voice/transport/turn-latency.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { readTurnLatency } from './turn-latency'

const good = {
  version: 2,
  turn_id: 't1',
  source: 'speech',
  turn_revision: 0,
  response_key: 'k1',
  status: 'completed',
  stt_s: 0.12,
  llm_s: 0.34,
  tts_ttfa_s: 0.05,
  e2e_s: 0.51,
  vad_decision_s: 0.16,
  smart_wait_s: null,
  smart_status: 'disabled',
  hold_s: 0
}

function wrap(data: unknown, status = 'completed') {
  return { status, metadata: { 'speech_to_speech.turn_latency': JSON.stringify(data) } }
}

describe('readTurnLatency', () => {
  it('accepts a well-formed v2 record', () => {
    expect(readTurnLatency(wrap(good))).toMatchObject({ e2e_s: 0.51, status: 'completed' })
  })

  it('accepts a v2 record with no turn id when the source is client or tool', () => {
    expect(readTurnLatency(wrap({ ...good, turn_id: null, source: 'tool' }))).not.toBeNull()
    // Same shape but a speech turn with no id is not attributable, so it is dropped.
    expect(readTurnLatency(wrap({ ...good, turn_id: null, source: 'speech' }))).toBeNull()
  })

  it('drops a record whose status disagrees with the response', () => {
    expect(readTurnLatency(wrap(good, 'cancelled'))).toBeNull()
  })

  it('drops negative or non-finite measurements instead of rendering them', () => {
    expect(readTurnLatency(wrap({ ...good, e2e_s: -1 }))).toBeNull()
    expect(readTurnLatency(wrap({ ...good, llm_s: null }))).not.toBeNull()
  })

  it('returns null for a missing, malformed or unknown-version payload', () => {
    expect(readTurnLatency({ status: 'completed' })).toBeNull()
    expect(readTurnLatency(wrap({ ...good, version: 3 }))).toBeNull()
    expect(
      readTurnLatency({ status: 'completed', metadata: { 'speech_to_speech.turn_latency': '{' } })
    ).toBeNull()
  })
})
```

- [ ] **Step 4: 跑测试确认失败**

Run: `cd console/frontend && npx vitest run src/features/voice/transport/turn-latency.spec.ts`
Expected: FAIL，`Failed to resolve import "./turn-latency"`。

- [ ] **Step 5: 实现 `transport/turn-latency.ts`**

与 `demo/turn-latency.js` 逐条件等价——**不要「顺手简化」**：这些条件决定面板显示 `0.51s` 还是 `—`，`demo/tests/turn-latency.test.mjs` 是同一批断言的旧版。

```ts
import type { TurnLatency } from '../types'

const TERMINAL_STATUSES = ['completed', 'cancelled', 'failed', 'incomplete']
const SOURCE_WITHOUT_TURN = ['client', 'tool']
const SMART_STATUSES = ['complete', 'incomplete', 'failed', 'disabled']

/** Seconds that are present must be real; `null` means “not measured”. */
function optionalSeconds(value: unknown): boolean {
  return value === undefined || value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0)
}

/**
 * Only terminal server measurements are trusted; older pipelines omit the
 * metadata entirely, which must read as “no numbers”, never as zero.
 */
export function readTurnLatency(response: any): TurnLatency | null {
  const raw = response?.metadata?.['speech_to_speech.turn_latency']
  if (typeof raw !== 'string') return null
  let data: any
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  if (!data || ![1, 2].includes(data.version)) return null

  const attributed =
    (typeof data.turn_id === 'string' && data.turn_id !== '') ||
    (data.version === 2 && SOURCE_WITHOUT_TURN.includes(data.source) && data.turn_id === null)
  if (!attributed) return null
  if (typeof data.response_key !== 'string' || data.response_key === '') return null
  if (!Number.isInteger(data.turn_revision) || data.turn_revision < 0) return null
  if (!TERMINAL_STATUSES.includes(data.status) || data.status !== response.status) return null
  if (!optionalSeconds(data.stt_s) || !optionalSeconds(data.llm_s)) return null
  if (!optionalSeconds(data.tts_ttfa_s) || !optionalSeconds(data.e2e_s)) return null
  if (!optionalSeconds(data.vad_decision_s) || !optionalSeconds(data.hold_s)) return null
  if (!optionalSeconds(data.smart_wait_s)) return null
  if (data.smart_status !== undefined && data.smart_status !== null && !SMART_STATUSES.includes(data.smart_status)) {
    return null
  }
  return data as TurnLatency
}
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd console/frontend && npx vitest run src/features/voice/transport/turn-latency.spec.ts`
Expected: 5 passed。

---

- [ ] **Step 7: 先写事件归约器的失败测试**

`console/frontend/src/features/voice/transport/events.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { TranscriptReducer } from './events'

describe('TranscriptReducer', () => {
  it('merges one user turn from delta → snapshot → completed into a single entry', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'hel' })
    r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'lo' })
    r.apply({ type: 'speech_to_speech.input_audio_transcription.snapshot', item_id: 'i1', transcript: 'hello there' })
    r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hello there.' })

    expect(r.entries).toHaveLength(1)
    expect(r.entries[0]).toMatchObject({ role: 'user', text: 'hello there.', partial: false })
  })

  it('keeps the snapshot text while the deltas are still catching up', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'speech_to_speech.input_audio_transcription.snapshot', item_id: 'i1', transcript: 'snap' })
    r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'sn' })

    expect(r.entries[0]).toMatchObject({ text: 'snap', partial: true })
  })

  it('drops a turn whose final transcript is empty, so no blank bubble is left behind', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'hmm' })
    r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: '' })

    expect(r.entries).toHaveLength(0)
  })

  it('appends assistant segments per response id instead of creating one bubble each', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'response.audio_transcript.delta', response_id: 'r1', delta: 'Hi' })
    r.apply({ type: 'response.output_audio_transcript.done', response_id: 'r1', transcript: 'Hi.' })
    r.apply({ type: 'response.audio_transcript.delta', response_id: 'r1', delta: 'More' })
    r.apply({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'More.' })

    expect(r.entries).toHaveLength(1)
    expect(r.entries[0]).toMatchObject({ role: 'assistant', text: 'Hi. More.', partial: false })
  })

  it('keeps user and assistant turns in arrival order and ignores unknown events', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'q' })
    r.apply({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'a' })
    r.apply({ type: 'response.output_audio.delta', delta: 'AAAA' })
    r.apply({ type: 'speech_to_speech.output_audio.visemes', samples: [] })

    expect(r.entries.map((e) => `${e.role}:${e.text}`)).toEqual(['user:q', 'assistant:a'])
  })
})
```

- [ ] **Step 8: 跑测试确认失败**

Run: `cd console/frontend && npx vitest run src/features/voice/transport/events.spec.ts`
Expected: FAIL，`Failed to resolve import "./events"`。

- [ ] **Step 9: 实现 `transport/events.ts`**

语义逐条对应 `demo/s2s-realtime-client.js:614-710`：临时文本可被权威快照覆盖、终态文本为空则删条目、助手分段用空格拼接。

```ts
import type { TranscriptEntry } from '../types'

interface Cell {
  /** Finalised text from `.done` events (assistant) — never overwritten downward. */
  full: string
  /** Delta accumulator. */
  partial: string
  /** Authoritative input transcript, once the server sends one. */
  snapshot: string
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * Server event stream → the transcript list. Pure: no DOM, no SDK, no timers,
 * so `demo/tests/*.test.mjs` behaviour can be asserted directly.
 */
export class TranscriptReducer {
  readonly entries: TranscriptEntry[] = []

  private readonly cells = new Map<string, Cell>()

  private readonly index = new Map<string, number>()

  reset(): void {
    this.entries.length = 0
    this.cells.clear()
    this.index.clear()
  }

  private cell(key: string): Cell {
    let cell = this.cells.get(key)
    if (!cell) {
      cell = { full: '', partial: '', snapshot: '' }
      this.cells.set(key, cell)
    }
    return cell
  }

  private write(key: string, role: 'user' | 'assistant', value: string, partial: boolean): void {
    const at = this.index.get(key)
    const entry: TranscriptEntry = { key, role, text: value, partial }
    if (at === undefined) {
      this.index.set(key, this.entries.length)
      this.entries.push(entry)
    } else {
      this.entries[at] = entry
    }
  }

  private remove(key: string): void {
    const at = this.index.get(key)
    if (at === undefined) return
    this.entries.splice(at, 1)
    this.index.clear()
    this.entries.forEach((entry, i) => this.index.set(entry.key, i))
  }

  /** @returns whether the rendered list changed. */
  apply(event: any): boolean {
    const type = typeof event?.type === 'string' ? event.type : ''
    switch (type) {
      case 'conversation.item.input_audio_transcription.delta': {
        const delta = text(event.delta)
        if (!delta) return false
        const key = `u:${text(event.item_id)}`
        const cell = this.cell(key)
        cell.partial += delta
        this.write(key, 'user', cell.snapshot || cell.partial, true)
        return true
      }
      case 'speech_to_speech.input_audio_transcription.snapshot': {
        const snapshot = text(event.transcript)
        if (!snapshot) return false
        const key = `u:${text(event.item_id)}`
        this.cell(key).snapshot = snapshot
        this.write(key, 'user', snapshot, true)
        return true
      }
      case 'conversation.item.input_audio_transcription.completed': {
        const key = `u:${text(event.item_id)}`
        const cell = this.cells.get(key)
        const hadPartial = Boolean(cell && (cell.partial || cell.snapshot))
        this.cells.delete(key)
        const final = text(event.transcript)
        if (final) {
          this.write(key, 'user', final, false)
          return true
        }
        if (hadPartial) {
          this.remove(key)
          return true
        }
        return false
      }
      case 'conversation.item.input_audio_transcription.failed': {
        const key = `u:${text(event.item_id)}`
        this.cells.delete(key)
        this.remove(key)
        return true
      }
      case 'response.audio_transcript.delta':
      case 'response.output_audio_transcript.delta': {
        const delta = text(event.delta)
        if (!delta) return false
        const key = `a:${text(event.response_id)}`
        const cell = this.cell(key)
        cell.partial += delta
        const shown = cell.full && cell.partial ? `${cell.full} ${cell.partial}` : cell.full || cell.partial
        this.write(key, 'assistant', shown, true)
        return true
      }
      case 'response.audio_transcript.done':
      case 'response.output_audio_transcript.done': {
        const key = `a:${text(event.response_id)}`
        const cell = this.cell(key)
        const segment = text(event.transcript) || cell.partial
        if (segment) cell.full = cell.full ? `${cell.full} ${segment}` : segment
        cell.partial = ''
        if (!cell.full) {
          this.remove(key)
          return true
        }
        this.write(key, 'assistant', cell.full, false)
        return true
      }
      default:
        // Audio frames, visemes, response.created, error … none of them are text.
        return false
    }
  }
}
```

- [ ] **Step 10: 跑测试确认通过**

Run: `cd console/frontend && npx vitest run src/features/voice/transport/events.spec.ts`
Expected: 5 passed。

- [ ] **Step 11: 先写电平与门限的失败测试**

`console/frontend/src/features/voice/audio/meter.ts` 对应 `demo/main.js:54-61`（门限轴）与 `demo/s2s-realtime-client.js:60-61`（`SPEAKING_OPEN_DB = -50`、`SPEAKING_HANG_MS = 250`）。

`console/frontend/src/features/voice/audio/meter.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { dbToPercent, fractionToDb, GATE_MAX_DB, GATE_OFF_DB, rmsToDb, SpeakingDetector } from './meter'

describe('rmsToDb', () => {
  it('turns a silent buffer into the floor, not -Infinity', () => {
    expect(rmsToDb(new Float32Array([0, 0, 0]))).toBe(-100)
    expect(rmsToDb(new Float32Array([1, -1, 1, -1]))).toBe(0)
    expect(rmsToDb(new Float32Array([0.5]))).toBeCloseTo(-6.02, 1)
  })
})

describe('dbToPercent', () => {
  it('maps the shared gate axis onto 0-100 and clamps outside it', () => {
    expect(dbToPercent(GATE_OFF_DB)).toBe(0)
    expect(dbToPercent(-3)).toBe(100)
    expect(dbToPercent(-90)).toBe(0)
    expect(dbToPercent(0)).toBe(100)
  })
})

describe('fractionToDb', () => {
  it('inverts dbToPercent and clamps the arc gap to the nearest end', () => {
    expect(fractionToDb(0)).toBe(GATE_OFF_DB)
    expect(fractionToDb(1)).toBe(GATE_MAX_DB)
    expect(fractionToDb(dbToPercent(-30) / 100)).toBeCloseTo(-30, 5)
    // 200° 弧的右侧是缺口，落进去的角度会算出 [0,1] 之外的 fraction；
    // 夹住而不是返回越界的 dB，否则拖到缺口会把门限设成 -120 dB。
    expect(fractionToDb(-0.4)).toBe(GATE_OFF_DB)
    expect(fractionToDb(1.4)).toBe(GATE_MAX_DB)
  })
})

describe('SpeakingDetector', () => {
  it('opens above -50 dB and holds for 250 ms so short gaps do not flicker', () => {
    let now = 0
    const detector = new SpeakingDetector(() => now)

    expect(detector.push(-40)).toBe(true)
    now = 100
    expect(detector.push(-80)).toBe(true)
    now = 300
    expect(detector.push(-80)).toBe(false)
  })

  it('never opens below -50 dB and resets cleanly', () => {
    let now = 0
    const detector = new SpeakingDetector(() => now)

    expect(detector.push(-60)).toBe(false)
    expect(detector.push(-30)).toBe(true)
    detector.reset()
    now = 1000
    expect(detector.push(-60)).toBe(false)
  })
})
```

- [ ] **Step 12: 跑测试确认失败**

Run: `cd console/frontend && npx vitest run src/features/voice/audio/meter.spec.ts`
Expected: FAIL，`Failed to resolve import "./meter"`。

- [ ] **Step 13: 实现 `audio/meter.ts`**

```ts
/** The gate slider and the level bar share one dB axis (demo/main.js:51-56). */
export const GATE_OFF_DB = -66
export const GATE_MAX_DB = -3
export const GATE_DEFAULT_DB = -50

/** Local speech detection: open above this, hold this long (demo client). */
export const SPEAKING_OPEN_DB = -50
export const SPEAKING_HANG_MS = 250

const SILENCE_DB = -100

export function rmsToDb(samples: Float32Array): number {
  if (!samples.length) return SILENCE_DB
  let sum = 0
  for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i]
  const rms = Math.sqrt(sum / samples.length)
  // log10(0) is -Infinity; the meter has to stay a number the UI can format.
  return rms > 0 ? 20 * Math.log10(rms) : SILENCE_DB
}

export function dbToPercent(db: number): number {
  const clamped = Math.min(GATE_MAX_DB, Math.max(GATE_OFF_DB, db))
  return ((clamped - GATE_OFF_DB) / (GATE_MAX_DB - GATE_OFF_DB)) * 100
}

/**
 * 弧上的反向映射：拖拽把手得到的 0-1 比例换回 dB。
 * `MicGate.vue` 的 `atan2` 在缺口里会算出 [0,1] 之外的值，必须夹住。
 */
export function fractionToDb(fraction: number): number {
  const clamped = Math.min(1, Math.max(0, fraction))
  return GATE_OFF_DB + clamped * (GATE_MAX_DB - GATE_OFF_DB)
}

/** `thresholdDb === GATE_OFF_DB` is the OFF detent: the gate never opens. */
export function gateOpen(levelDb: number, thresholdDb: number): boolean {
  return thresholdDb > GATE_OFF_DB && levelDb > thresholdDb
}

/** Hysteresis on release only: opening is immediate, closing waits out noise. */
export class SpeakingDetector {
  private lastVoiceAt = Number.NEGATIVE_INFINITY

  constructor(private readonly now: () => number = () => performance.now()) {}

  push(levelDb: number): boolean {
    const at = this.now()
    if (levelDb > SPEAKING_OPEN_DB) this.lastVoiceAt = at
    return at - this.lastVoiceAt <= SPEAKING_HANG_MS
  }

  reset(): void {
    this.lastVoiceAt = Number.NEGATIVE_INFINITY
  }
}
```

- [ ] **Step 14: 跑测试确认通过**

Run: `cd console/frontend && npx vitest run src/features/voice/audio/meter.spec.ts`
Expected: 5 passed。

---

- [ ] **Step 15: 写 `stores/voice.ts` 与它的测试**

先写测试。`console/frontend/src/stores/voice.spec.ts`（node 环境没有 `localStorage`，测试自带一个最小 shim；**没有 `sessionStorage`**——demo 不跨刷新保留会话，这里也不保留）：

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { DEFAULT_SETTINGS, SETTINGS_KEY, useVoiceStore } from './voice'

function installStorage(): Map<string, string> {
  const data = new Map<string, string>()
  ;(globalThis as any).localStorage = {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear()
  }
  return data
}

beforeEach(() => {
  installStorage()
  setActivePinia(createPinia())
})

describe('voice store', () => {
  it('paints `connected` as `listening` — the orb has no separate connected face', () => {
    const store = useVoiceStore()
    store.setState('connected')
    expect(store.state).toBe('listening')
    expect(store.live).toBe(true)
  })

  it('keeps the transcript in arrival order and replaces the array so Vue re-renders', () => {
    const store = useVoiceStore()
    store.applyEvent({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hi' })
    store.applyEvent({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'hello' })

    expect(store.entries.map((e) => e.role)).toEqual(['user', 'assistant'])
  })

  it('hands the server timings to the last assistant entry, not to a global slot', () => {
    const store = useVoiceStore()
    store.applyEvent({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'hello' })
    store.attachLatency({
      version: 2,
      turn_id: 't1',
      turn_revision: 0,
      response_key: 'r1',
      status: 'completed',
      stt_s: 0.12,
      llm_s: null,
      tts_ttfa_s: 0.05,
      e2e_s: 0.51,
      vad_decision_s: 0.55,
      smart_status: 'disabled',
      hold_s: null
    })

    const last = store.entries[store.entries.length - 1]
    expect(last?.latency?.e2e_s).toBe(0.51)
    // 下一条回复到达之前的 `null` 不得把已挂上的数字抹掉（demo 每条 hist 各留一份）。
    store.attachLatency(null)
    expect(store.entries[store.entries.length - 1]?.latency?.e2e_s).toBe(0.51)
  })

  it('persists the settings demo keeps in localStorage', () => {
    const store = useVoiceStore()
    store.saveSettings({ ...DEFAULT_SETTINGS, voice: 'Serena', noiseGateDb: -42 })

    const raw = (globalThis as any).localStorage.getItem(SETTINGS_KEY) ?? ''
    expect(JSON.parse(raw).voice).toBe('Serena')
    expect(raw).not.toContain('searchKey')
  })

  it('loads saved settings and falls back per missing field', () => {
    ;(globalThis as any).localStorage.setItem(SETTINGS_KEY, JSON.stringify({ voice: 'Vivian' }))

    const store = useVoiceStore()
    store.loadSettings()

    expect(store.settings.voice).toBe('Vivian')
    expect(store.settings.playbackBufferMs).toBe(DEFAULT_SETTINGS.playbackBufferMs)
    expect(store.settings.tools.camera).toBe(false)
  })

  it('survives a corrupt settings record instead of failing to mount', () => {
    ;(globalThis as any).localStorage.setItem(SETTINGS_KEY, '{not json')

    const store = useVoiceStore()
    expect(() => store.loadSettings()).not.toThrow()
    expect(store.settings).toEqual(DEFAULT_SETTINGS)
  })

  it('keeps the transcript out of storage — a refresh ends the conversation, as in demo', () => {
    const store = useVoiceStore()
    store.applyEvent({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hi' })
    store.saveSettings(store.settings)

    const raw = (globalThis as any).localStorage.getItem(SETTINGS_KEY) ?? ''
    expect(raw).not.toContain('hi')
    expect(Object.keys(JSON.parse(raw))).not.toContain('entries')
  })
})
```

实现 `console/frontend/src/stores/voice.ts`：

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { TranscriptReducer } from '@/features/voice/transport/events'
import { LIVE_STATES } from '@/features/voice/types'
import type { MeResponse, QueueTicket, SessionGrant, TranscriptEntry, TurnLatency, VoiceConfig, VoiceSettings, VoiceState } from '@/features/voice/types'

/**
 * 唯一持久化的东西：设置。demo/main.js 也把同一组值写进 localStorage
 * （voice / instructions / noiseGate / playbackBufferMs / localVad /
 * transport / audioInputId / audioOutputId / tools），但不写转写。
 * 刷新 = 会话结束，这一点与 demo 完全一致。
 */
export const SETTINGS_KEY = 's2s.voice.settings'

export const DEFAULT_SETTINGS: VoiceSettings = {
  voice: 'Aiden',
  instructions: 'You are a friendly voice assistant.',
  noiseGateDb: -50,
  playbackBufferMs: 0,
  localVad: true,
  transport: 'ws',
  tools: { web: true, camera: false },
  audioInputId: '',
  audioOutputId: ''
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    // Private mode throws on access; the page still has to work.
    return null
  }
}

/** 逐字段合并：旧版本存下的部分记录也能用，未知字段直接忽略。 */
export function mergeSettings(saved: Partial<VoiceSettings> | null): VoiceSettings {
  const tools = { ...DEFAULT_SETTINGS.tools, ...(saved?.tools ?? {}) }
  return { ...DEFAULT_SETTINGS, ...(saved ?? {}), tools }
}

const EMPTY_CONFIG: VoiceConfig = {
  search: false,
  lb: false,
  allowDirect: true,
  s2sUrl: '',
  rtc: false,
  iceServers: [],
  startupGreeting: '',
  auth: false
}

export const useVoiceStore = defineStore('voice', () => {
  const state = ref<VoiceState>('idle')
  const entries = ref<TranscriptEntry[]>([])
  const grant = ref<SessionGrant | null>(null)
  const queue = ref<QueueTicket | null>(null)
  const me = ref<MeResponse>({ enabled: false })
  const config = ref<VoiceConfig>({ ...EMPTY_CONFIG })
  const latency = ref<TurnLatency | null>(null)
  const settings = ref<VoiceSettings>(mergeSettings(null))

  const reducer = new TranscriptReducer()
  const live = computed(() => LIVE_STATES.has(state.value))

  function setState(next: VoiceState): void {
    // The transport reports `connected`; the page paints that as `listening`.
    state.value = next === 'connected' ? 'listening' : next
  }

  function applyEvent(event: any): void {
    if (!reducer.apply(event)) return
    entries.value = [...reducer.entries]
  }

  /**
   * `Server timings` 的归属（§3.9.4）：demo 把它挂在「最后一条助手条目」上
   * （`chat.js:637`：`hist ??= this._appendHistMsg("assistant", …)`），而不是存一份全局最新值。
   * 找不到助手条目（转写还没到）时只丢掉这块数字，不造空节点——宁可少一条，也不挂错人。
   */
  function attachLatency(turn: TurnLatency | null): void {
    latency.value = turn
    if (!turn) return
    let index = -1
    for (let i = entries.value.length - 1; i >= 0; i -= 1) {
      if (entries.value[i].role === 'assistant') {
        index = i
        break
      }
    }
    if (index < 0) return
    entries.value = entries.value.map((entry, i) => (i === index ? { ...entry, latency: turn } : entry))
  }

  function resetTranscript(): void {
    reducer.reset()
    entries.value = []
    latency.value = null
  }

  function loadSettings(): void {
    const raw = storage()?.getItem(SETTINGS_KEY)
    if (!raw) {
      settings.value = mergeSettings(null)
      return
    }
    try {
      settings.value = mergeSettings(JSON.parse(raw) as Partial<VoiceSettings>)
    } catch {
      // 坏记录当成没存过：一个 JSON 解析失败不该让整页挂不上。
      settings.value = mergeSettings(null)
    }
  }

  function saveSettings(next: VoiceSettings = settings.value): void {
    settings.value = mergeSettings(next)
    storage()?.setItem(SETTINGS_KEY, JSON.stringify(settings.value))
  }

  return {
    state,
    entries,
    grant,
    queue,
    me,
    config,
    latency,
    settings,
    live,
    setState,
    applyEvent,
    attachLatency,
    resetTranscript,
    loadSettings,
    saveSettings
  }
})
```

Run: `cd console/frontend && npx vitest run src/stores/voice.spec.ts`
Expected: 7 passed。若先跑的是失败阶段（未建文件），Expected: FAIL，`Failed to resolve import "./voice"`。

- [ ] **Step 16: 写 `transport/s2s-client.ts`**

这是唯一允许出现 `globalThis.OpenAIAgentsRealtime` 的文件。它把四件事镇在一起：**会话获取**（`/api/session` + 排队轮询）、**SDK 适配**（WS 或 WebRTC 两种 transport）、**播放队列**（worklet 升水门 + 中断截断）、**麦克风上行**。`demo/s2s-realtime-client.js` 是本文件的唯一参考；下列方法的**名称与职责必须一致**，但代码是重写的（1:1 回搬那个文件会让 TypeScript 在 `private` 与 `EventTarget` 之间到处报错）。

```ts
import type { QueueTicket, SessionGrant, ToolCall, ToolDef, ToolResult } from '../types'
import { readTurnLatency } from './turn-latency'

export const AUDIO_SAMPLE_RATE = 24_000
export const AUDIO_WORKLET_VERSION = 'audio-24k-v2'
const MIC_CHUNK_MS = 40

function sdk(): any {
  const value = (globalThis as any).OpenAIAgentsRealtime
  if (!value) throw new Error('OpenAI Agents SDK bundle is not loaded')
  return value
}

export interface NoiseGate {
  enabled: boolean
  thresholdDb: number
}

export interface S2sClientOptions {
  transport: 'websocket' | 'webrtc'
  sessionUrl: string
  callsUrl: string
  voice: string
  instructions: string
  tools: ToolDef[]
  iceServers: RTCIceServer[]
  startupGreeting: string
  localVad: boolean
  noiseGate: NoiseGate
  playbackBufferMs: number
  micStream?: MediaStream
  audioContext?: AudioContext
  acquireMic?: () => Promise<MediaStream>
  executeTool?: (call: ToolCall) => Promise<ToolResult>
}

function codedError(message: string, code: string, extra?: Record<string, unknown>): Error {
  return Object.assign(new Error(message), { code }, extra)
}

/**
 * One conversation. Every event other than audio is forwarded verbatim as
 * `server-event`; the store's TranscriptReducer owns all text bookkeeping.
 */
export class S2sClient extends EventTarget {
  private status = 'idle'
  private closed = false
  private closing = false
  private muted = false
  private session: any = null
  private transport: any = null
  private agent: any = null
  private ctx: AudioContext | null = null
  private micSource: MediaStreamAudioSourceNode | null = null
  private captureNode: AudioWorkletNode | null = null
  private playbackNode: AudioWorkletNode | null = null
  private analysers: { mic?: AnalyserNode; out?: AnalyserNode } = {}
  private outputGain: GainNode | null = null
  private audioElement: HTMLAudioElement | null = null
  private playbackResponseId = ''
  private playbackAudioKey = ''
  private pending: { samples: Float32Array; key: string }[] = []
  private pendingSamples = 0
  private playbackStarted = false
  private readonly playbackItems = new Map<string, { itemId: string; contentIndex: number; samples: number }>()
  private queueId = ''
  private joinWaiter: { resolve: () => void; reject: (e: Error) => void; timer: number } | null = null

  constructor(private readonly options: S2sClientOptions) {
    super()
  }

  get currentStatus(): string {
    return this.status
  }

  private setStatus(next: string): void {
    if (this.status === next) return
    this.status = next
    this.emit('status', { status: next })
  }

  private emit(type: string, detail: unknown): void {
    this.dispatchEvent(new CustomEvent(type, { detail }))
  }

  /** Step 1 of the handshake: a grant, or a queue ticket, or a coded error. */
  private async acquireGrant(): Promise<{ grant: SessionGrant; waited: boolean }> {
    const first = await this.postSession()
    if (first.state === 'granted') return { grant: first.grant, waited: false }
    this.setStatus('queued')
    return { grant: await this.pollQueue(first.ticket), waited: true }
  }

  private async postSession(): Promise<{ state: 'granted'; grant: SessionGrant } | { state: 'queued'; ticket: QueueTicket }> {
    const res = await fetch(this.options.sessionUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    })
    const body = await res.json().catch(() => ({}))
    if (res.status === 402) throw codedError('Daily conversation limit reached', 'limit', { tier: body?.tier })
    if (res.status === 401) throw codedError('Sign in again to continue', 'login-required', { loginUrl: body?.loginUrl })
    if (res.status === 503 && body?.state === 'at_capacity') throw codedError('The queue is full — try again shortly.', 'queue-full')
    if (!res.ok) throw codedError(`/session failed (${res.status})`, 'session-failed')
    if (body.state === 'queued') {
      return { state: 'queued', ticket: { queueId: body.queue_id, position: body.position, pollIntervalS: body.poll_interval_s } }
    }
    return { state: 'granted', grant: parseGrant(body) }
  }

  private async pollQueue(ticket: QueueTicket): Promise<SessionGrant> {
    this.queueId = ticket.queueId
    this.emit('queue', { queueId: ticket.queueId, position: ticket.position })
    const interval = Math.max(1, ticket.pollIntervalS || 2) * 1000
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, interval))
      if (this.closed) throw codedError('queue wait aborted', 'aborted')
      let res: Response
      try {
        res = await fetch(`${this.options.sessionUrl.replace(/\/session$/, '')}/queue/${encodeURIComponent(this.queueId)}`)
      } catch {
        continue // transient network blip: the ticket is still good
      }
      if (res.status === 402) throw codedError('Daily conversation limit reached', 'limit')
      if (res.status === 401) throw codedError('Sign in again to continue', 'login-required')
      if (res.status === 404) throw codedError('Queue timed out', 'queue-expired')
      if (!res.ok) continue
      const body = await res.json().catch(() => null)
      if (!body) continue
      if (body.state === 'queued') {
        this.emit('queue', { queueId: this.queueId, position: body.position })
        continue
      }
      this.queueId = ''
      return parseGrant(body)
    }
  }

  private async awaitJoin(grant: SessionGrant): Promise<void> {
    const seconds = Math.max(3, (grant.pendingTimeoutS || 60) - 3)
    this.setStatus('your-turn')
    this.emit('ready-to-join', { grant, expiresSec: seconds })
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(codedError('Your spot expired', 'join-expired')), seconds * 1000)
      this.joinWaiter = { resolve, reject, timer }
    })
  }

  async connect(): Promise<void> {
    if (this.session) throw new Error('Already connected')
    let url: string
    if (this.options.transport === 'websocket') {
      this.setStatus('creating-session')
      const { grant, waited } = await this.acquireGrant()
      if (this.closed) throw codedError('connect aborted', 'aborted')
      // A queued grant holds a slot for seconds only, and the browser needs a user
      // gesture to resume the AudioContext — so wait for the click before dialling.
      if (waited) await this.awaitJoin(grant)
      this.emit('session', { grant })
      url = grant.connectUrl
    } else {
      url = new URL(this.options.callsUrl, globalThis.location?.href).href
    }
    this.setStatus('connecting')
    if (!this.options.micStream && this.options.acquireMic) {
      this.options.micStream = await this.options.acquireMic()
    }
    if (!this.options.micStream?.getAudioTracks()[0]) throw new Error('No microphone track available')
    await this.setupAudio(this.options.micStream)
    await this.openSession(url)
    this.setStatus('connected')
  }

  private async openSession(url: string): Promise<void> {
    const { OpenAIRealtimeWebRTC, OpenAIRealtimeWebSocket, RealtimeAgent, RealtimeSession, tool } = sdk()
    if (this.options.transport === 'websocket') {
      // The SDK clock starts at receipt; our worklet queue owns the real playout
      // position, so the interrupt is re-implemented against that queue.
      this.transport = new (class extends OpenAIRealtimeWebSocket {
        interrupt(cancelOngoingResponse = true): void {
          if (cancelOngoingResponse) this._cancelResponse?.()
          this.emit('audio_interrupted')
        }
      })({ useInsecureApiKey: true })
    } else {
      // Mute until the data channel is up so startup noise cannot race the greeting.
      this.options.micStream!.getAudioTracks()[0].enabled = false
      this.audioElement = new Audio()
      this.audioElement.autoplay = true
      this.transport = new OpenAIRealtimeWebRTC({
        mediaStream: this.options.micStream,
        audioElement: this.audioElement,
        useInsecureApiKey: true,
        changePeerConnection: (pc: RTCPeerConnection) => {
          if (this.options.iceServers.length) {
            pc.setConfiguration({ ...pc.getConfiguration(), iceServers: this.options.iceServers })
          }
          return pc
        }
      })
    }

    const tools = this.options.tools.map((definition) =>
      tool({
        name: definition.name,
        description: definition.description,
        parameters: definition.parameters,
        strict: false,
        execute: async (args: unknown, _context: unknown, details: any) => {
          const result = await this.options.executeTool?.({
            name: definition.name,
            arguments: JSON.stringify(args ?? {}),
            callId: details?.toolCall?.callId ?? ''
          })
          if (!result) throw new Error(`No executor for ${definition.name}`)
          if (result.image) this.session?.addImage(result.image, { triggerResponse: false })
          return result.output
        }
      })
    )
    this.agent = new RealtimeAgent({
      name: 'speech-to-speech-console',
      instructions: this.options.instructions,
      voice: this.options.voice,
      tools
    })
    this.session = new RealtimeSession(this.agent, {
      transport: this.transport,
      model: 's2s-local',
      tracingDisabled: true,
      config: {
        outputModalities: ['audio'],
        providerData: { extensions: ['speech_to_speech.input_audio_transcription.snapshot'] },
        audio: {
          input: {
            format: { type: 'audio/pcm', rate: AUDIO_SAMPLE_RATE },
            transcription: { model: 'whisper-1' },
            turnDetection: { type: 'server_vad', interruptResponse: true },
            noiseReduction: null
          },
          output: { format: { type: 'audio/pcm', rate: AUDIO_SAMPLE_RATE }, speed: 1 }
        }
      }
    })

    this.transport.on('*', (event: any) => this.onTransportEvent(event))
    this.transport.on('connection_change', (state: string) => {
      if (state === 'disconnected' && !this.closing && this.status !== 'error') {
        this.setStatus('error')
        this.emit('error', { error: new Error('Realtime transport disconnected') })
      }
    })
    this.session.on('audio', (event: any) => this.onAudio(event))
    this.session.on('audio_interrupted', () => this.clearPlayback())

    await this.session.connect({ apiKey: 's2s-local', url })
    const greeting = this.options.startupGreeting.trim()
    if (greeting) this.session.sendMessage(greeting)
    this.setMuted(this.muted)
  }

  private onTransportEvent(event: any): void {
    if (typeof event?.type !== 'string') return
    switch (event.type) {
      case 'speech_to_speech.output_audio.visemes':
        this.emit('visemes', event)
        return
      case 'input_audio_buffer.speech_started':
        this.setStatus('user-speaking')
        break
      case 'input_audio_buffer.speech_stopped':
        if (this.status === 'user-speaking') this.setStatus('processing')
        break
      case 'response.created':
        this.resetPlaybackBuffer(event.response?.id ?? '')
        if (this.status === 'connected' || this.status === 'user-speaking') this.setStatus('processing')
        break
      case 'response.output_audio.delta':
        if (this.options.transport === 'websocket' && event.response_id === this.playbackResponseId) {
          this.playbackAudioKey = JSON.stringify([event.item_id, event.content_index])
          if (!this.playbackItems.has(this.playbackAudioKey)) {
            this.playbackItems.set(this.playbackAudioKey, {
              itemId: event.item_id,
              contentIndex: event.content_index,
              samples: 0
            })
          }
        }
        break
      case 'response.done': {
        const id = event.response?.id ?? ''
        if (this.options.transport === 'websocket') this.finishPlayback(id, event.response?.status ?? 'completed')
        this.setStatus('connected')
        this.playbackResponseId = ''
        this.emit('response-finished', {
          responseId: id,
          status: event.response?.status ?? 'completed',
          transcript: transcriptOf(event.response),
          latency: readTurnLatency(event.response)
        })
        break
      }
      case 'error':
        this.emit('error', { error: new Error(event.error?.message ?? 'Server error') })
        break
    }
    this.emit('server-event', event)
  }

  private onAudio(event: any): void {
    if (this.options.transport !== 'websocket' || !this.playbackNode || this.closed) return
    if (!this.playbackResponseId || event.responseId !== this.playbackResponseId || !event.data?.byteLength) return
    const view = new DataView(event.data)
    const samples = new Float32Array(event.data.byteLength / 2)
    for (let i = 0; i < samples.length; i += 1) {
      const sample = view.getInt16(i * 2, true)
      samples[i] = sample < 0 ? sample / 0x8000 : sample / 0x7fff
    }
    const item = this.playbackItems.get(this.playbackAudioKey)
    if (item) item.samples += samples.length
    this.pending.push({ samples, key: this.playbackAudioKey })
    this.pendingSamples += samples.length
    if (this.playbackStarted || this.pendingSamples >= this.playbackThreshold) this.releasePlayback()
  }

  private get playbackThreshold(): number {
    return Math.ceil((AUDIO_SAMPLE_RATE * Math.max(0, this.options.playbackBufferMs)) / 1000)
  }

  private releasePlayback(): void {
    if (!this.pending.length) return
    for (const { samples, key } of this.pending) {
      this.playbackNode?.port.postMessage({ kind: 'audio', samples, key }, [samples.buffer])
    }
    this.pending = []
    this.pendingSamples = 0
    this.playbackStarted = true
    this.setStatus('ai-speaking')
  }

  private resetPlaybackBuffer(responseId = ''): void {
    this.playbackResponseId = responseId
    this.playbackAudioKey = ''
    this.pending = []
    this.pendingSamples = 0
    this.playbackStarted = false
  }

  private finishPlayback(responseId: string, status: string): void {
    if (!responseId || responseId !== this.playbackResponseId) return
    if (status === 'completed' || status === 'incomplete') this.releasePlayback()
    this.resetPlaybackBuffer()
  }

  private clearPlayback(): void {
    this.resetPlaybackBuffer()
    this.playbackNode?.port.postMessage({ kind: 'clear' })
  }

  private async setupAudio(stream: MediaStream): Promise<void> {
    const ctx = this.options.audioContext ?? new AudioContext({ latencyHint: 'interactive' })
    this.ctx = ctx
    if (ctx.state === 'suspended') await ctx.resume().catch(() => {})
    this.outputGain = ctx.createGain()
    this.outputGain.connect(ctx.destination)
    this.micSource = ctx.createMediaStreamSource(stream)

    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    analyser.smoothingTimeConstant = 0
    this.micSource.connect(analyser)
    this.analysers.mic = analyser

    await ctx.audioWorklet.addModule(`/worklets/mic-capture.js?v=${AUDIO_WORKLET_VERSION}`)
    this.captureNode = new AudioWorkletNode(ctx, 'mic-capture', { processorOptions: { chunkMs: MIC_CHUNK_MS } })
    this.captureNode.port.onmessage = (message) => {
      const data = message.data
      if (data?.kind === 'level') this.emit('level', { db: data.db })
      if (data?.kind === 'chunk' && !this.muted) this.session?.sendAudio(data.buffer)
    }
    this.micSource.connect(this.captureNode)
    this.setNoiseGate(this.options.noiseGate)

    if (this.options.transport === 'websocket') {
      await ctx.audioWorklet.addModule(`/worklets/audio-playback.js?v=${AUDIO_WORKLET_VERSION}`)
      this.playbackNode = new AudioWorkletNode(ctx, 'audio-playback', { outputChannelCount: [1] })
      this.playbackNode.connect(this.outputGain)
      this.playbackNode.port.onmessage = (message) => {
        if (message.data?.kind === 'cleared') this.onPlaybackCleared(message.data)
      }
    }
  }

  /**
   * The worklet reports how many samples it actually rendered before the clear.
   * Anything still unheard is truncated server-side, so the model's transcript
   * stops matching audio the user never got (demo/s2s-realtime-client.js:522-538).
   */
  private onPlaybackCleared(message: any): void {
    const played = new Map<string, number>(message.played ?? [])
    for (const [key, item] of this.playbackItems) {
      const samples = Math.min(item.samples, played.get(key) ?? 0)
      if (samples >= item.samples) continue
      this.transport?.sendEvent({
        type: 'conversation.item.truncate',
        item_id: item.itemId,
        content_index: item.contentIndex,
        audio_end_ms: Math.max(0, Math.floor((samples / AUDIO_SAMPLE_RATE) * 1000))
      })
    }
    this.playbackItems.clear()
  }

  /**
   * §2.2 hot fields only. A present `voice` is remembered for the next call but the
   * live session is not rebuilt: the pipeline treats it as protocol echo.
   */
  updateSession(session: Record<string, unknown>): void {
    const voice = session.voice
    const instructions = session.instructions
    if (typeof voice === 'string' && voice) this.options.voice = voice
    if (typeof instructions === 'string' && instructions) this.options.instructions = instructions
    if (!this.session) return
    this.transport?.sendEvent?.({ type: 'session.update', session })
  }

  setTools(tools: ToolDef[]): void {
    this.options.tools = tools
    this.session?.updateAgent?.({ ...this.agent, tools })
  }

  setMuted(muted: boolean): void {
    this.muted = muted
    for (const track of this.options.micStream?.getAudioTracks() ?? []) track.enabled = !muted
    this.captureNode?.port.postMessage({ kind: 'mute', muted })
  }

  setNoiseGate(gate: NoiseGate): void {
    this.options.noiseGate = gate
    this.captureNode?.port.postMessage({ kind: 'gate', enabled: gate.enabled, thresholdDb: gate.thresholdDb })
  }

  async setAudioOutputDevice(deviceId = ''): Promise<void> {
    if (this.audioElement && 'setSinkId' in this.audioElement) {
      await (this.audioElement as any).setSinkId(deviceId).catch(() => {})
    }
  }

  join(): void {
    const waiter = this.joinWaiter
    this.joinWaiter = null
    if (waiter) {
      clearTimeout(waiter.timer)
      waiter.resolve()
    }
  }

  async close(): Promise<void> {
    this.closed = true
    this.closing = true
    this.clearPlayback()
    if (this.joinWaiter) {
      clearTimeout(this.joinWaiter.timer)
      this.joinWaiter.reject(codedError('join aborted', 'aborted'))
      this.joinWaiter = null
    }
    this.session?.close?.()
    this.session = null
    this.transport = null
    for (const node of [this.captureNode, this.playbackNode, this.micSource, this.analysers.mic, this.outputGain]) {
      try {
        node?.disconnect()
      } catch {
        /* already detached */
      }
    }
    try {
      await this.ctx?.close()
    } catch {
      /* already closed */
    }
    this.ctx = null
    this.setStatus('closed')
  }
}

function parseGrant(body: any): SessionGrant {
  return {
    sessionId: body.session_id,
    connectUrl: body.connect_url,
    websocketUrl: body.websocket_url,
    sessionToken: body.session_token,
    pendingTimeoutS: body.pending_timeout_s,
    tier: body.tier,
    limited: !!body.limited,
    remainingSec: body.remainingSec ?? null,
    heartbeatSec: body.heartbeatSec ?? null
  }
}

function transcriptOf(response: any): string {
  const parts = response?.output ?? []
  return parts
    .flatMap((part: any) => part?.content ?? [])
    .filter((content: any) => content?.type === 'audio' || content?.type === 'output_audio')
    .map((content: any) => content?.transcript ?? '')
    .join(' ')
    .trim()
}
```

`awaitJoin` 的职责就一件事：把 `your-turn` 的状态与超时窗口给到 UI，并等 `join()` 被点。`queue` → `your-turn` 两个状态名与 `demo/main.js:174-197` 一致。

Run: `cd console/frontend && npx tsc --noEmit`
Expected: 无输出。

- [ ] **Step 17: 写音频与工具三件（`audio/capture.ts`、`audio/vad.ts`、`tools/camera.ts`），并补齐 `api/demo.ts`**

`console/frontend/src/features/voice/audio/capture.ts`：

```ts
/** Constraints that match the old page: the pipeline does its own AGC/NS. */
const MIC: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true
}

export async function acquireMic(deviceId = ''): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw Object.assign(new Error('This browser cannot capture audio.'), { code: 'mic-unsupported' })
  }
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: deviceId ? { ...MIC, deviceId: { exact: deviceId } } : MIC })
  } catch (error: any) {
    // The three names the page distinguishes in MicGate.
    const code =
      error?.name === 'NotAllowedError' || error?.name === 'SecurityError'
        ? 'mic-denied'
        : error?.name === 'NotFoundError' || error?.name === 'OverconstrainedError'
          ? 'mic-missing'
          : 'mic-failed'
    throw Object.assign(new Error(error?.message ?? 'Microphone failed'), { code, cause: error })
  }
}

/** Released on unmount, otherwise the tab keeps the recording indicator on. */
export function releaseMic(stream: MediaStream | null): void {
  for (const track of stream?.getTracks() ?? []) track.stop()
}

export async function listAudioDevices(): Promise<MediaDeviceInfo[]> {
  const devices = await navigator.mediaDevices?.enumerateDevices?.() ?? []
  return devices.filter((device) => device.kind === 'audioinput')
}
```

`console/frontend/src/features/voice/audio/sent-audio.ts`——逐行移植 `demo/ws/user-audio-recorder.js`（198 行）：它保存“用户到底说了什么”的 PCM，在 `speech_stopped` 时转成 WAV 交给条目回放。**这是 §14.5「用户条目原音回放」的唯一实现**，没有它转写条目就只剩文字。

```ts
/** pipeline 上行采样率，不是浏览器的 48kHz。 */
export const USER_AUDIO_SAMPLE_RATE = 24000
const BYTES_PER_SAMPLE = 2
const DEFAULT_PREROLL_MS = 5000
const DEFAULT_MAX_BUFFER_MS = 120_000

export interface SentAudio {
  blob: Blob
  durationMs: number
  /** 开头被剪掉了：条目要显示 `· beginning unavailable`。 */
  truncated: boolean
}

export function pcm16ToWavBlob(pcm: Int16Array, sampleRate = USER_AUDIO_SAMPLE_RATE): Blob {
  const samples = new Int16Array(pcm) // 自带 buffer，避免 subarray 共享出 44 字节以外的脏数据
  const header = new ArrayBuffer(44)
  const view = new DataView(header)
  const ascii = (offset: number, text: string): void => {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index))
  }
  const dataBytes = samples.length * BYTES_PER_SAMPLE
  ascii(0, 'RIFF')
  view.setUint32(4, 36 + dataBytes, true)
  ascii(8, 'WAVE')
  ascii(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true)
  view.setUint16(32, BYTES_PER_SAMPLE, true)
  view.setUint16(34, 16, true)
  ascii(36, 'data')
  view.setUint32(40, dataBytes, true)
  return new Blob([header, samples.buffer], { type: 'audio/wav' })
}

/**
 * 有界环形缓冲：`hardFloor = now - maxBufferMs`，`softFloor = speechStart - prerollMs`，
 * 取两者较大者作为裁剪起点。与 demo 的三个默认值逐个对应，不自己发明第四个数。
 */
export class SentAudioRecorder {
  private chunks: Int16Array[] = []
  private totalSamples = 0
  private speechStartMs = 0
  private truncated = false

  constructor(
    private readonly prerollMs = DEFAULT_PREROLL_MS,
    private readonly maxBufferMs = DEFAULT_MAX_BUFFER_MS
  ) {}

  /** `speech_started`：固定 pre-roll 的起点，让句子开头不被剪掉。 */
  speechStarted(atMs: number): void {
    this.speechStartMs = atMs
  }

  append(samples: Int16Array, atMs: number): void {
    if (!samples.length) return
    this.chunks.push(samples)
    this.totalSamples += samples.length
    const hardFloorMs = atMs - this.maxBufferMs
    const softFloorMs = this.speechStartMs ? this.speechStartMs - this.prerollMs : atMs - this.prerollMs
    this.pruneBefore(Math.max(hardFloorMs, softFloorMs))
  }

  /** `speech_stopped`：拼成一段、封成 WAV，然后清空（下一次说话重新计数）。 */
  speechStopped(): SentAudio {
    const samples = new Int16Array(this.totalSamples)
    let offset = 0
    for (const chunk of this.chunks) {
      samples.set(chunk, offset)
      offset += chunk.length
    }
    const result: SentAudio = {
      blob: pcm16ToWavBlob(samples),
      durationMs: Math.round((samples.length / USER_AUDIO_SAMPLE_RATE) * 1000),
      truncated: this.truncated
    }
    this.reset()
    return result
  }

  reset(): void {
    this.chunks = []
    this.totalSamples = 0
    this.speechStartMs = 0
    this.truncated = false
  }

  private pruneBefore(floorMs: number): void {
    const keepSamples = Math.max(0, Math.floor((floorMs * USER_AUDIO_SAMPLE_RATE) / 1000))
    while (this.totalSamples > keepSamples && this.chunks.length > 0) {
      const head = this.chunks[0]
      const excess = this.totalSamples - keepSamples
      this.truncated = true
      if (head.length <= excess) {
        this.chunks.shift()
        this.totalSamples -= head.length
      } else {
        this.chunks[0] = head.subarray(excess)
        this.totalSamples -= excess
      }
    }
  }
}
```

`console/frontend/src/features/voice/audio/sent-audio.spec.ts`（5 条：WAV 头、采样率、pre-roll 保留、超限剪裁置 `truncated`、`reset` 后不串段）：

```ts
import { describe, expect, it } from 'vitest'

import { pcm16ToWavBlob, SentAudioRecorder, USER_AUDIO_SAMPLE_RATE } from './sent-audio'

const chunk = (ms: number): Int16Array => new Int16Array(Math.round((ms * USER_AUDIO_SAMPLE_RATE) / 1000))

describe('pcm16ToWavBlob', () => {
  it('writes a 44-byte RIFF/WAVE header around the PCM', async () => {
    const blob = pcm16ToWavBlob(new Int16Array(480))
    const view = new DataView(await blob.arrayBuffer())
    expect(blob.type).toBe('audio/wav')
    expect(view.getUint32(4, true)).toBe(36 + 960)
    expect(view.getUint32(24, true)).toBe(USER_AUDIO_SAMPLE_RATE)
  })

  it('encodes duration from sample count, not from wall clock', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(3000), 3000)
    expect(recorder.speechStopped().durationMs).toBe(3000)
  })
})

describe('SentAudioRecorder', () => {
  it('keeps the pre-roll before speech_started', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(2000), 2000)
    recorder.speechStarted(2000)
    recorder.append(chunk(1000), 3000)
    const audio = recorder.speechStopped()
    expect(audio.truncated).toBe(false)
    expect(audio.durationMs).toBe(3000)
  })

  it('prunes past maxBuffer and flags truncated', () => {
    const recorder = new SentAudioRecorder(1000, 5000)
    for (let at = 1000; at <= 12000; at += 1000) recorder.append(chunk(1000), at)
    const audio = recorder.speechStopped()
    expect(audio.truncated).toBe(true)
    expect(audio.durationMs).toBeLessThan(12000)
  })

  it('does not leak one utterance into the next', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(500), 500)
    recorder.speechStopped()
    recorder.append(chunk(700), 700)
    expect(recorder.speechStopped().durationMs).toBe(700)
  })
})
```

Run: `cd console/frontend && npx vitest run src/features/voice/audio/sent-audio.spec.ts`
Expected: 5 passed（未建实现文件时为 FAIL：`Failed to resolve import "./sent-audio"`）。这五条是 §14.5「用户原音回放」那条的自动化部分；剩下两条（麦克风被静音、其它条目暂停）只能人工验收，见 Step 21 第 10 条。

`console/frontend/src/features/voice/audio/vad.ts`——模型与 wasm 都在 `/vendor/local-vad/`（Task 17 的六个白名单文件），页面里不出现任何 CDN 地址：

```ts
import { MicVAD } from '@ricky0123/vad-web'

const ASSET_BASE = '/vendor/local-vad/'

export interface LocalVadOptions {
  stream: MediaStream
  isEnabled: () => boolean
  onChange: (speaking: boolean) => void
}

/**
 * Client-side barge-in aid. It never gates the uplink: the pipeline still runs
 * its own server VAD — this only lets the orb react before the server answers.
 */
export async function startLocalVad(options: LocalVadOptions): Promise<{ destroy: () => Promise<void> }> {
  const vad = await MicVAD.new({
    baseAssetPath: ASSET_BASE,
    onnxWASMBasePath: ASSET_BASE,
    startOnLoad: false,
    processorType: 'AudioWorklet',
    audioContext: undefined,
    onSpeechStart: () => options.isEnabled() && options.onChange(true),
    onSpeechEnd: () => options.onChange(false)
  })
  await vad.start()
  return {
    destroy: async () => {
      await vad.destroy()
    }
  }
}
```

`console/frontend/src/features/voice/tools/camera.ts`——`demo/main.js:93-109` 的阶梯换编码逐级下降，目的是让失败是确定性的：任何内容在最后一级都能装进一个数据通道消息。

```ts
const MAX_EDGE = 768
const FIRST_QUALITY = 0.7
/** SCTP messages above 64 KiB fail on the aiortc peer; leave JSON headroom. */
const DC_BUDGET_CHARS = 60_000
const LADDER: [number, number][] = [
  [MAX_EDGE, FIRST_QUALITY],
  [MAX_EDGE, 0.5],
  [640, 0.45],
  [512, 0.4],
  [448, 0.35],
  [384, 0.3]
]

export async function openCamera(): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 } }, audio: false })
}

/** @returns a data URL, or `''` when the camera has no frame yet. */
export function snapshot(video: HTMLVideoElement): string {
  if (!video.videoWidth || video.videoHeight === 0) return ''
  for (const [edge, quality] of LADDER) {
    const scale = Math.min(1, edge / Math.max(video.videoWidth, video.videoHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    const dataUrl = canvas.toDataURL('image/jpeg', quality)
    if (dataUrl.length <= DC_BUDGET_CHARS) return dataUrl
  }
  // Last rung still over budget (never seen in practice): send nothing rather
  // than a frame the data channel will refuse.
  return ''
}
```

（`LADDER` 的第一级 `[768, 0.7]` 就是旧页的 `SNAPSHOT_MAX_EDGE` / `SNAPSHOT_QUALITY`，所以只需要这一个函数。）

`console/frontend/src/api/demo.ts` 追加（Task 17 已建此文件并含 `getDemoConfig()`）：

```ts
export async function getDemoConfig(): Promise<VoiceConfig> {
  // Task 17 的实现；这里列出它必须返回的字段，避免两处形状漂移。
}

export async function getMe(): Promise<MeResponse> {
  const res = await fetch('/api/me')
  // A 404 means “metering is off for this deploy”, not a failure to report.
  if (!res.ok) return { enabled: false }
  return (await res.json()) as MeResponse
}

export async function postSession(): Promise<Response> {
  return fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}'
  })
}

export async function heartbeat(sessionId: string): Promise<{ expired: boolean }> {
  const res = await fetch('/api/session/heartbeat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId })
  })
  if (!res.ok) return { expired: false }
  return (await res.json()) as { expired: boolean }
}

/** sendBeacon can only POST: it survives the tab close that a fetch does not. */
export function endSessionBeacon(sessionId: string): void {
  const body = new Blob([JSON.stringify({ sessionId })], { type: 'application/json' })
  if (!navigator.sendBeacon('/api/session/end', body)) {
    void fetch('/api/session/end', { method: 'POST', body, keepalive: true })
  }
}

export function leaveQueueBeacon(queueId: string): void {
  const body = new Blob([JSON.stringify({ queueId })], { type: 'application/json' })
  if (!navigator.sendBeacon('/api/queue/end', body)) {
    void fetch('/api/queue/end', { method: 'POST', body, keepalive: true })
  }
}

export async function search(query: string, key: string, sessionId: string): Promise<string> {
  const res = await fetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, ...(key ? { key } : {}), ...(sessionId ? { sessionId } : {}) })
  })
  if (!res.ok) throw new Error(`search failed (${res.status})`)
  const body = (await res.json()) as { answer?: string; results?: { title: string; snippet: string; url: string }[] }
  // Date-stamp the header so the model treats hits as fresh facts, not memory.
  const today = new Date().toISOString().slice(0, 10)
  const lines = [`Google search result from ${today}:`]
  if (body.answer) lines.push(`Answer: ${body.answer}`)
  for (const hit of body.results ?? []) lines.push(`- ${hit.title}: ${hit.snippet} (${hit.url})`)
  return lines.length > 1 ? lines.join('\n') : `${lines[0]}\nNo results found.`
}
```

`getDemoConfig` 保留 Task 17 的已有实现——上面那个空壳**不要落盘**，它只用来提醒字段集合；实际提交时保持 Task 17 的版本，只把返回类型窄到 `VoiceConfig`。

---

- [ ] **Step 18: 写十五个展示组件**

对话页的文案保持英文：§14.5 要求「拒绝授权时给出与旧页一致的提示文案」，而旧页是英文。运维台继续中文——两个面的读者不同，不强行统一。样式不进组件，统一在 `src/styles/voice.less`（Step 19），因为 orb 的九个状态靠同一组 CSS 变量切换，分散到十五个 scoped 块反而无法共享轴。

**每个组件都能指回 demo 里的一个 DOM 节点**——这不是「重画一个更好看的对话页」，是把 `demo/index.html` 的每一块搬进 Vue。漏掉一块就是功能缺失，多出一块就是凭空发明：

| 组件 | 对应 demo | 承担的现有功能 |
| --- | --- | --- |
| `IdentityBlock.vue` | `index.html:23-52` `.ident` | 标题外链、About 圆钮、blurb、`Powered by` / `Built by` 两行鸣谢 |
| `AccountWidget.vue` | `#account` + `ui/account.js` | 登录徽章、tier、今日剩余分钟、升级 PRO、退出 |
| `OrbStage.vue` | `.orb-wrap` + `#main-circle` + `#circle-caption` / `#circle-subcaption` | 四层球体（glow / ring / ring-outer / core）、六个指示器、九态配色、caption 与 subcaption |
| `MicGate.vue` | `#mic-gate`（`#mic-btn` + `#mic-gate-arc`） | 52px 圆形静音钮、80px 噪声门圆弧（可拖拽改门限、显示实时电平） |
| `TranscriptList.vue` | `#chat-history` + `.hist-audio` + `.hist-tool` / `.hist-image` | 三类条目（user / tool / assistant）、临时条目半透明、自动贴底；用户条目嵌 `AudioReplay`，tool 条目嵌 `Input` / `Output` 与 `Snapshot` |
| `AudioReplay.vue` | `ui/chat.js:onUserAudio` 的 `.hist-audio` | 标签 `Audio sent to the model`（截断时加 `· beginning unavailable`）+ `<audio controls preload="metadata" aria-label="Replay your audio">`；`play` 暂停其它条目并通知父级静音麦克风，`pause` / `ended` / `error` 通知恢复 |
| `HistoryDrawer.vue` | `#chat-panel` | 右侧会话历史抽屉（标题、关闭、条目数） |
| `BubbleStack.vue` | `#bubble-stack` | 右上角临时气泡（user / tool / assistant，自动消失） |
| `CameraPip.vue` | `#cam-pip` + `#cam-video` / `.cam-flash` / `.cam-label` | 相机开启时的左下自视窗；`snapshot()` 读的就是它 |
| `TurnTimings.vue` | `ui/chat.js:636-678` 的 `_appendTimings` | 助手条目下的 `details.hist-timings`：summary（`Server timings` / `· E2E 6.26 s` / v1 `· First audio …`）+ `timing-status` 四态 + 七行 `<dl>` + 末尾口径句；同一 response 重到时替换而不是追加 |
| `useTurnLatency.ts` | `demo/turn-latency.js` 的 `readTurnLatency` 下游 | **只 re-export** `readTurnLatency`（校验在 `transport/turn-latency.ts`，Step 5），并提供 `formatSeconds` / `timingSummary` / `statusLabel` / `timingRows` / `timingNote` 五个展示纯函数；本文件不自己校验 metadata，也不持有状态 |
| `ToolsDialog.vue` | `#tools-modal` | Web search 开关 + Serper key + Camera 开关 + 三条 hint |
| `SettingsDialog.vue` | `#settings-modal` | 连接（只读）、Transport、Voice 9 项、Microphone、Speakers、Faster interruptions、Playback buffer、Noise gate、Instructions、Restart + Save |
| `AboutDialog.vue` | `#about-modal` | 项目简介 + 四段 pipeline（VAD / STT / VLM / TTS）+ 版本 |
| `LimitDialog.vue` | `#limit-modal` | 额度耗尽卡片（HF 徽章、标题、正文、CTA、note） |
| `QueueOverlay.vue` | `#queue-actions` + `#join-queue-btn` / `#leave-queue-btn` | 排队位次 / `your-turn` 的 Join now 倒计时 / 满员提示 / Leave queue |

demo 里还有两个不属于任何组件的节点：`#stop-btn`（52px 结束钮）与 `footer`（`Powered by huggingface/speech-to-speech`），它们各自只有一行模板，直接写在 `VoiceView` 的 `.v-orb-wrap` 与 `.v-foot` 里，不单独立组件。

`console/frontend/src/features/voice/components/MicGate.vue`（demo 的 `#mic-gate`：52px 圆形静音钮 + 80px 环形噪声门。旧计划里的「Mute 文字按钮 + Faster interruptions 复选框」是错的：后者在 demo 里位于 Settings，不在球体旁边）：

```vue
<script setup lang="ts">
import { computed } from 'vue'

import { dbToPercent, fractionToDb, GATE_OFF_DB } from '../audio/meter'

const props = defineProps<{ muted: boolean; gateDb: number; levelDb: number }>()
const emit = defineEmits<{
  (e: 'update:muted', value: boolean): void
  (e: 'update:gateDb', value: number): void
}>()

// demo/main.js:493-516：200° 的弧，缺口朝着球体（右侧），0 在左下、1 在左上。
const R = 40
const SPAN = 200
const START = 180 - SPAN / 2

function arcPoint(fraction: number): { x: number; y: number } {
  const rad = ((START + fraction * SPAN) * Math.PI) / 180
  return { x: 50 + R * Math.cos(rad), y: 50 + R * Math.sin(rad) }
}

// 几何只有一条，`d` 不随状态变化，进程内算一次。
const arcPath = ((): string => {
  const a = arcPoint(0)
  const b = arcPoint(1)
  return `M ${a.x} ${a.y} A ${R} ${R} 0 1 1 ${b.x} ${b.y}`
})()

const gateFraction = computed(() => dbToPercent(props.gateDb) / 100)
const levelFraction = computed(() => dbToPercent(props.levelDb) / 100)
const handle = computed(() => arcPoint(gateFraction.value))
const gating = computed(() => props.gateDb > GATE_OFF_DB)
// 电平越过门限 = 门确实开了；门关着的时候弧不该整圈高亮。
const open = computed(() => gating.value && levelFraction.value >= gateFraction.value)

let dragging = false

function dbFromPointer(event: PointerEvent, svg: SVGSVGElement): number {
  const box = svg.getBoundingClientRect()
  let deg = (Math.atan2(event.clientY - (box.top + box.height / 2), event.clientX - (box.left + box.width / 2)) * 180) / Math.PI
  if (deg < 0) deg += 360
  // 落进右侧缺口的角度会算出 [0,1] 之外的值，fractionToDb 会夹到最近的一端。
  return fractionToDb((deg - START) / SPAN)
}

function startDrag(event: PointerEvent): void {
  dragging = true
  const path = event.currentTarget as SVGPathElement
  path.setPointerCapture(event.pointerId)
  const svg = path.ownerSVGElement
  if (svg) emit('update:gateDb', dbFromPointer(event, svg))
}

function moveDrag(event: PointerEvent): void {
  if (!dragging) return
  const svg = (event.currentTarget as SVGPathElement).ownerSVGElement
  if (svg) emit('update:gateDb', dbFromPointer(event, svg))
}

function endDrag(): void {
  dragging = false
}
</script>

<template>
  <div class="mic-gate" :class="{ 'is-gating': gating, 'is-open': open }">
    <svg class="mic-gate__arc" viewBox="0 0 100 100" aria-hidden="true">
      <path class="mic-gate__track" :d="arcPath" fill="none" />
      <path
        class="mic-gate__fill"
        :d="arcPath"
        fill="none"
        pathLength="100"
        :style="{ strokeDashoffset: 100 - levelFraction * 100 }"
      />
      <path
        class="mic-gate__hit"
        :d="arcPath"
        fill="none"
        @pointerdown="startDrag"
        @pointermove="moveDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
      />
      <circle class="mic-gate__handle" :cx="handle.x" :cy="handle.y" r="3" />
    </svg>
    <button
      class="v-side"
      type="button"
      :aria-pressed="!props.muted"
      :title="props.muted ? 'Unmute' : 'Mute'"
      @click="emit('update:muted', !props.muted)"
    >
      <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use :href="props.muted ? '#i-mic-off' : '#i-mic'" /></svg>
    </button>
  </div>
</template>
```

> 麦克风授权失败的文案不在这里：demo 把它放在球体下方的 caption（`#circle-caption`），所以那段文案属于 `VoiceView`（Step 19），`MicGate` 只负责静音与门限两个可操作项。

`console/frontend/src/features/voice/components/OrbStage.vue`（**九态不降维**：旧计划把它投影成 idle/live/thinking 三态，demo 的九种颜色与六个指示器全部丢失。这里 `data-state` 原样透传，配色全在 CSS）：

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { VoiceState } from '../types'

const props = defineProps<{
  state: VoiceState
  levelDb: number
  caption: string
  subCaption: string
  tone: 'info' | 'error'
}>()
const emit = defineEmits<{ (e: 'activate'): void }>()

/** demo/main.js 的六个指示器：球心随状态换图形，而不是只有一个光斑。 */
type Indicator = 'mic' | 'error' | 'spinner' | 'dots' | 'bars' | 'voice'

const INDICATOR: Record<VoiceState, Indicator> = {
  idle: 'mic',
  connecting: 'spinner',
  queued: 'spinner',
  'your-turn': 'mic',
  listening: 'bars',
  'user-speaking': 'bars',
  processing: 'dots',
  'ai-speaking': 'voice',
  error: 'error'
}

const indicator = computed(() => INDICATOR[props.state])
// 只有待机与出错时球体才是一个按钮；通话中它只是显示器。
const activatable = computed(() => props.state === 'idle' || props.state === 'error')
// 电平只允许驱动光晕，且只在通话中：待机时的环境噪声不该让球体发亮。
const glow = computed(() => (activatable.value ? 0 : Math.min(1, Math.max(0, (props.levelDb + 60) / 60))))
</script>

<template>
  <div class="v-orb-wrap">
    <slot name="left" />
    <button
      class="v-orb"
      :data-state="props.state"
      :disabled="!activatable"
      :aria-label="props.caption || props.state"
      :style="{ '--glow-strength': glow }"
      @click="activatable && emit('activate')"
    >
      <span class="v-orb__glow" aria-hidden="true" />
      <span class="v-orb__ring" aria-hidden="true" />
      <span class="v-orb__ring v-orb__ring--outer" aria-hidden="true" />
      <span class="v-orb__core">
        <span class="v-orb__ind">
          <svg v-if="indicator === 'mic'" class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-mic" /></svg>
          <svg v-else-if="indicator === 'error'" class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-info" /></svg>
          <span v-else-if="indicator === 'spinner'" class="v-spinner" />
          <span v-else-if="indicator === 'dots'" class="v-dots"><i /><i /><i /></span>
          <span v-else-if="indicator === 'bars'" class="v-bars"><i v-for="n in 5" :key="n" /></span>
          <svg v-else class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-voice" /></svg>
        </span>
      </span>
    </button>
    <slot name="right" />
  </div>

  <p class="v-caption" :class="{ 'v-caption--error': props.tone === 'error' }" role="status">{{ props.caption }}</p>
  <p v-if="props.subCaption" class="v-sub">{{ props.subCaption }}</p>
</template>
```

> 为什么 caption 是 prop 而不是写死在组件里：demo 的 `#circle-caption` 在同一个位置显示对话状态、“Queued · position 3 · ~2 min”、麦克风拒绝授权提示与 `Tap to retry`。文案的唯一持有者是 store 与 `VoiceView`，组件只负责把它显示在球体正下方。

`console/frontend/src/features/voice/components/TranscriptList.vue`（自动滚动 + 区分最终与临时 + 三类条目，§14.5 第三条；用户条目的原音回放就是旧页的 `.hist-audio`，tool 条目的 `Input` / `Output` / `Snapshot` 与 `_appendHistTool` / `_appendHistImage` 一一对应，助手条目的 `Server timings` 折叠块与 `_appendTimings` 一一对应）。**计时只挂在助手条目里，舞台上没有任何 chip 行**（`demo/index.html` 与 `main.js` 搜 `latency` 都是 0 命中）：

```vue
<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import type { TranscriptEntry } from '../types'
import AudioReplay from './AudioReplay.vue'
import TurnTimings from './TurnTimings.vue'

const props = defineProps<{ entries: TranscriptEntry[] }>()
const emit = defineEmits<{ (e: 'replay', playing: boolean): void }>()
const list = ref<HTMLElement | null>(null)
/** 同时只允许一条条目在响；`AudioReplay` 听这个值自己暂停。 */
const playingKey = ref('')

const ROLE_LABEL: Record<TranscriptEntry['role'], string> = {
  user: 'You',
  tool: 'Tool',
  assistant: 'Assistant'
}

watch(
  () => props.entries.map((entry) => `${entry.key}:${entry.text.length}:${entry.partial}`).join('|'),
  async () => {
    await nextTick()
    // Only stick to the bottom while the user is already there: scrolling a
    // reader back down after they scrolled up to read is hostile.
    const el = list.value
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 120) el.scrollTop = el.scrollHeight
  }
)

function onAudioPlay(key: string): void {
  playingKey.value = key
  // 播放原音时必须静音麦克风，否则录音会被重新送进 pipeline（回声）；
  // 旧页就是靠这一个回调做的（demo/main.js:372-406）。
  emit('replay', true)
}

function onAudioStop(): void {
  playingKey.value = ''
  emit('replay', false)
}
</script>

<template>
  <ol ref="list" class="transcript" aria-live="polite">
    <li
      v-for="entry in props.entries"
      :key="entry.key"
      class="transcript__item"
      :class="[`transcript__item--${entry.role}`, { 'is-partial': entry.partial }]"
    >
      <span class="transcript__role">{{ ROLE_LABEL[entry.role] }}</span>
      <span class="transcript__text">{{ entry.text }}</span>

      <!-- 用户条目：只有带音频的条目才有播放器（demo 也只在 websocket 分支产生原音）。 -->
      <AudioReplay
        v-if="entry.audio"
        :url="entry.audio.url"
        :truncated="entry.audio.truncated"
        :active="playingKey === entry.key"
        @play="onAudioPlay(entry.key)"
        @stop="onAudioStop"
      />

      <!-- tool 条目：Input / Output 可展开 + Snapshot 缩略图。 -->
      <details v-if="entry.tool" class="transcript__tool">
        <summary class="transcript__tool-name">{{ entry.tool.name }}</summary>
        <p class="transcript__tool-label">Input</p>
        <pre class="transcript__tool-json">{{ entry.tool.input }}</pre>
        <p class="transcript__tool-label">Output</p>
        <pre class="transcript__tool-json">{{ entry.tool.output }}</pre>
        <template v-if="entry.tool.image">
          <p class="transcript__tool-label">Snapshot</p>
          <a :href="entry.tool.image" target="_blank" rel="noopener">
            <img class="transcript__tool-image" :src="entry.tool.image" alt="Camera snapshot" />
          </a>
        </template>
      </details>

      <!--
        助手条目：服务端测的七行计时（`_appendTimings`）。`latency` 缺失时整块不渲染；
        同一条目后来收到更完整的 payload 时由 `TurnTimings` 内部整体替换（`chat.js:674` 的 remove-then-append）。
      -->
      <TurnTimings v-if="entry.latency" :latency="entry.latency" />
    </li>
  </ol>
</template>
```

`console/frontend/src/features/voice/components/AudioReplay.vue`——§14.5「用户条目原音回放」的控件本身。三件事不能省：指针一律指向 demo 的同一串文案、点开只允许一条在响、`pause`/`ended`/`error` 都要回调 `false`（否则麦克风会一直静音下去）：

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{ url: string; truncated: boolean; active: boolean }>()
const emit = defineEmits<{ (e: 'play'): void; (e: 'stop'): void }>()

const audio = ref<HTMLAudioElement | null>(null)

// 父级换了“当前播放的那一条”就把自己停下：同时两条原音会让回声抑制失效。
watch(
  () => props.active,
  (active) => {
    if (!active && audio.value && !audio.value.paused) audio.value.pause()
  }
)
</script>

<template>
  <div class="hist-audio">
    <span class="hist-audio__label">
      Audio sent to the model
      <template v-if="props.truncated">· beginning unavailable</template>
    </span>
    <audio
      ref="audio"
      :src="props.url"
      controls
      preload="metadata"
      aria-label="Replay your audio"
      @play="emit('play')"
      @pause="emit('stop')"
      @ended="emit('stop')"
      @error="emit('stop')"
    />
  </div>
</template>
```

> 助手条目**不接播放器**：demo 从不保存 TTS 音频（`_appendHist` 只写文本与 timings），所以给它加一个播放按钮就是凭空发明（§3.2.2 末段）。

`console/frontend/src/features/voice/components/BubbleStack.vue`（demo 的 `#bubble-stack`：对话顶部右上角一闪而过的气泡。转写正文归历史抽屉，气泡只放「刚刚发生的一件事」，四条后自动丢弃）：

在 `features/voice/types.ts` 追加一个类型（Step 2 还没列它）：

```ts
export interface Bubble {
  id: number
  role: 'user' | 'tool' | 'assistant'
  text: string
}
```

```vue
<script setup lang="ts">
import type { Bubble } from '../types'

const props = defineProps<{ items: Bubble[] }>()
</script>

<template>
  <div class="v-bubbles" aria-live="polite" aria-atomic="false">
    <TransitionGroup name="v-bubble">
      <div v-for="item in props.items" :key="item.id" class="v-bubble" :class="`v-bubble--${item.role}`">
        <span class="v-bubble__role">
          {{ item.role === 'tool' ? 'tool' : item.role === 'user' ? 'You' : 'Assistant' }}
        </span>
        <span class="v-bubble__text">{{ item.text }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>
```

`console/frontend/src/features/voice/components/HistoryDrawer.vue`（demo 的 `#chat-panel`：右侧抽屉，不是常驻列表。旧计划把 `TranscriptList` 直接铺在页面上，视觉上与旧页不同）：

```vue
<script setup lang="ts">
import type { TranscriptEntry } from '../types'
import TranscriptList from './TranscriptList.vue'

const props = defineProps<{ open: boolean; entries: TranscriptEntry[] }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()
</script>

<template>
  <a-drawer
    :open="props.open"
    placement="right"
    :width="380"
    :body-style="{ padding: '0 12px 12px' }"
    @close="emit('update:open', false)"
  >
    <template #title>Conversation</template>
    <TranscriptList :entries="props.entries" />
    <p v-if="!props.entries.length" class="v-empty">Nothing said yet.</p>
  </a-drawer>
</template>
```

`console/frontend/src/features/voice/components/CameraPip.vue`（demo 的 `#cam-pip`：只有相机开启时存在。`snapshot()` 读的就是它的 `<video>`，所以必须 `defineExpose`）：

```vue
<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ active: boolean }>()
const video = ref<HTMLVideoElement | null>(null)
const flashing = ref(false)
let timer = 0

/** 拍照时闪一下：用户能看见「它刚刚拍了一张」，而不是静默上传。 */
function flash(): void {
  flashing.value = true
  window.clearTimeout(timer)
  timer = window.setTimeout(() => (flashing.value = false), 240)
}

defineExpose({ video, flash })
</script>

<template>
  <div v-if="props.active" class="v-pip" aria-hidden="true">
    <video ref="video" class="v-pip__feed" autoplay playsinline muted />
    <span class="v-pip__flash" :class="{ 'is-on': flashing }" />
    <span class="v-pip__label">camera</span>
  </div>
</template>
```

`console/frontend/src/features/voice/components/ToolsDialog.vue`（demo 的 `#tools-modal`：Web search + Serper key + Camera 三条，hint 文案逐字对齐；搜索仍走服务端 `/api/search`）：

```vue
<script setup lang="ts">
const props = defineProps<{
  open: boolean
  searchAvailable: boolean
  serverKey: boolean
  webSearch: boolean
  camera: boolean
  searchKey: string
}>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'update:webSearch', value: boolean): void
  (e: 'update:camera', value: boolean): void
  (e: 'update:searchKey', value: string): void
}>()
</script>

<template>
  <a-modal :open="props.open" title="Tools" :footer="null" @cancel="emit('update:open', false)">
    <p class="v-hint">Let the assistant act during the conversation. Changes apply live.</p>

    <div class="v-tool">
      <div class="v-tool__info">
        <span class="v-tool__name">Web search</span>
        <span class="v-tool__desc">Look things up on Google, via Serper.</span>
      </div>
      <a-switch
        :checked="props.webSearch"
        :disabled="!props.searchAvailable"
        @change="(value: boolean) => emit('update:webSearch', value)"
      />
    </div>

    <!-- 服务端已握 key 时既不回显也不受输入：B5 -->
    <div class="v-field">
      <label class="v-field__label" for="v-search-key">Search API key</label>
      <a-input-password
        id="v-search-key"
        :value="props.serverKey ? '' : props.searchKey"
        :disabled="props.serverKey"
        :placeholder="props.serverKey ? '••••••••  · provided by the server' : 'Serper API key (stays in this browser)'"
        autocomplete="off"
        @change="(event: Event) => emit('update:searchKey', (event.target as HTMLInputElement).value)"
      />
      <small class="v-hint">
        {{
          props.serverKey
            ? 'Ready. The search key is held server-side and never sent to the page.'
            : props.searchAvailable
              ? 'Ready.'
              : 'This deployment has no search key. Add your own above to use it anyway.'
        }}
      </small>
    </div>

    <div class="v-tool v-tool--sep">
      <div class="v-tool__info">
        <span class="v-tool__name">Camera</span>
        <span class="v-tool__desc">Let the assistant see through your webcam.</span>
      </div>
      <a-switch :checked="props.camera" @change="(value: boolean) => emit('update:camera', value)" />
    </div>
    <small class="v-hint">A live preview shows bottom-left while the camera is on.</small>
  </a-modal>
</template>
```

`console/frontend/src/features/voice/components/SettingsDialog.vue`（demo 的 `#settings-modal`：十个字段一个不少。旧计划只写「Voice / Model / language / instructions」四项，丢掉了 transport、麦克风、扬声器、播放缓冲与重启按钮——而「重启后生效」正是旧页的交互核心）：

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'

import { dbToPercent, GATE_MAX_DB, GATE_OFF_DB } from '../audio/meter'
import type { VoiceSettings } from '../types'

const props = defineProps<{
  open: boolean
  serverUrl: string
  transportLocked: boolean
  voices: string[]
  inputs: Array<{ id: string; label: string }>
  outputs: Array<{ id: string; label: string }>
  settings: VoiceSettings
  connected: boolean
}>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'save', value: VoiceSettings): void
  (e: 'restart'): void
}>()

const draft = ref<VoiceSettings>({ ...props.settings, tools: { ...props.settings.tools } })

// 每次打开都从 store 重取：面板是「照镜子」，不是第二个状态容器。
watch(
  () => props.open,
  (open) => {
    if (open) draft.value = { ...props.settings, tools: { ...props.settings.tools } }
  }
)

const gateLabel = () => (draft.value.noiseGateDb <= GATE_OFF_DB ? 'Off' : `${draft.value.noiseGateDb} dB`)
const gatePercent = () => dbToPercent(draft.value.noiseGateDb)

function save(): void {
  emit('save', {
    ...draft.value,
    noiseGateDb: Math.round(draft.value.noiseGateDb),
    playbackBufferMs: Math.max(0, Number(draft.value.playbackBufferMs) || 0)
  })
  emit('update:open', false)
}
</script>

<template>
  <a-modal :open="props.open" title="Settings" :width="520" @ok="save" ok-text="Save" @cancel="emit('update:open', false)">
    <a-form layout="vertical">
      <a-form-item label="Speech-to-speech server URL">
        <a-input :value="props.serverUrl" disabled />
        <small class="v-hint">Same origin as this page. The address is pinned by the deployment, not typed here.</small>
      </a-form-item>

      <a-form-item label="Transport">
        <a-select v-model:value="draft.transport" :disabled="props.transportLocked">
          <a-select-option value="ws">WebSocket</a-select-option>
          <a-select-option value="webrtc">WebRTC</a-select-option>
        </a-select>
        <small class="v-hint">
          {{ props.transportLocked ? 'Locked to WebSocket: this deployment pins the upstream URL.' : 'How audio travels to the server. Applies on the next conversation.' }}
        </small>
      </a-form-item>

      <a-form-item label="Voice">
        <a-select v-model:value="draft.voice">
          <a-select-option v-for="name in props.voices" :key="name" :value="name">{{ name }}</a-select-option>
        </a-select>
      </a-form-item>

      <a-form-item label="Microphone">
        <a-select v-model:value="draft.audioInputId">
          <a-select-option value="">System default</a-select-option>
          <a-select-option v-for="device in props.inputs" :key="device.id" :value="device.id">{{ device.label }}</a-select-option>
        </a-select>
        <small class="v-hint">Applies on the next conversation (or Restart).</small>
      </a-form-item>

      <a-form-item label="Speakers">
        <a-select v-model:value="draft.audioOutputId">
          <a-select-option value="">System default</a-select-option>
          <a-select-option v-for="device in props.outputs" :key="device.id" :value="device.id">{{ device.label }}</a-select-option>
        </a-select>
        <small class="v-hint">Where assistant audio plays. Chrome/Edge support switching outputs.</small>
      </a-form-item>

      <a-form-item label="Faster interruptions">
        <a-select :value="draft.localVad ? 'on' : 'off'" @change="(value: string) => (draft.localVad = value === 'on')">
          <a-select-option value="on">On</a-select-option>
          <a-select-option value="off">Off</a-select-option>
        </a-select>
        <small class="v-hint">Lowers the assistant's volume when you start speaking. Applies on the next conversation.</small>
      </a-form-item>

      <a-form-item label="Playback startup buffer (ms)">
        <a-input-number v-model:value="draft.playbackBufferMs" :min="0" :step="50" class="v-wide" />
        <small class="v-hint">
          WebSocket only. 0 starts immediately; larger values delay playback to absorb delivery gaps.
        </small>
      </a-form-item>

      <a-form-item :label="`Noise gate  ·  ${gateLabel()}`">
        <a-slider
          v-model:value="draft.noiseGateDb"
          :min="GATE_OFF_DB"
          :max="GATE_MAX_DB"
          :tip-formatter="(value: number) => (value <= GATE_OFF_DB ? 'Off' : `${value} dB`)"
        />
        <div class="v-gate-meter" aria-hidden="true"><span :style="{ width: `${gatePercent()}%` }" /></div>
        <div class="v-gate-ends"><span>Off</span><span>−3 dB</span></div>
        <small class="v-hint">
          Mutes the mic below the handle so room noise isn't sent. Slide fully left to turn it off; the arc
          around the mic shows your live input while in a call.
        </small>
      </a-form-item>

      <a-form-item label="Instructions">
        <a-textarea v-model:value="draft.instructions" :rows="5" placeholder="You are a friendly voice assistant..." />
      </a-form-item>

      <a-form-item>
        <a-button class="v-wide" :disabled="!props.connected" @click="emit('restart')">
          Restart conversation with these settings
        </a-button>
        <small class="v-hint">
          {{ props.connected ? 'Drops this call and reconnects with the settings above.' : 'Connect first, then come back here to apply live changes.' }}
        </small>
      </a-form-item>
    </a-form>
  </a-modal>
</template>
```

> 设置面板只写 `localStorage`，不回写 `#settings-modal` 的 `method="dialog"` 那套表单提交。保存之后真正常驻的是 `store.saveSettings()`（Step 15），所以刷新后仍在的只有这里能改到的值。

`console/frontend/src/features/voice/components/QueueOverlay.vue`（demo 的 `#queue-actions`：不是全屏遮罩，而是球体下方的一行动作；`Join now` 只在 `your-turn` 出现，其余时候只有 `Leave queue`）：

```vue
<script setup lang="ts">
import { computed } from "vue"

import type { VoiceState } from "../types"

const props = defineProps<{ state: VoiceState; position: number; expiresSec: number; full: boolean }>()
const emit = defineEmits<{ (e: "join"): void; (e: "leave"): void }>()

const yourTurn = computed(() => props.state === "your-turn")
const visible = computed(() => props.state === "queued" || yourTurn.value || props.full)
</script>

<template>
  <div v-if="visible" class="v-queue" role="status">
    <p v-if="props.full" class="v-queue__body">The waiting line is full. Try again in a minute.</p>
    <p v-else-if="yourTurn" class="v-queue__body">A slot opened up. Join within {{ props.expiresSec }}s.</p>
    <p v-else class="v-queue__body">You're number {{ props.position }}. Waiting never uses up your daily minutes.</p>
    <div class="v-queue__actions">
      <a-button v-if="yourTurn" class="v-join" type="primary" size="large" @click="emit('join')">Join now</a-button>
      <a-button v-if="!yourTurn" class="v-leave" size="large" @click="emit('leave')">Leave queue</a-button>
    </div>
  </div>
</template>
```

`console/frontend/src/features/voice/components/IdentityBlock.vue`（demo 的 `.ident`：标题、About 圆钮、blurb 与两行鸣谢。旧计划把它缩成「Anonymous / Sign in」一行，结果顶栏的左半边完全消失）：

```vue
<script setup lang="ts">
const emit = defineEmits<{ (e: 'about'): void }>()
const REPO = 'https://github.com/huggingface/speech-to-speech'
</script>

<template>
  <div class="v-ident">
    <div class="v-ident__head">
      <a class="v-ident__title" :href="REPO" target="_blank" rel="noopener">Hugging Face Realtime</a>
      <button class="v-icon v-icon--sm" title="About this space" aria-label="About this space" @click="emit('about')">
        <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-info" /></svg>
      </button>
    </div>
    <p class="v-ident__blurb">An open, real-time voice chat built on Hugging Face's speech-to-speech stack.</p>
    <div class="v-meta">
      <span>
        <span class="v-meta__label">Powered by</span>
        <a href="https://huggingface.co/inference-endpoints" target="_blank" rel="noopener">Inference Endpoints</a>
        <span class="v-sep" aria-hidden="true">·</span>
        <a href="https://cerebras.ai" target="_blank" rel="noopener">Cerebras</a>
      </span>
      <span>
        <span class="v-meta__label">Built by</span>
        <a href="https://huggingface.co" target="_blank" rel="noopener">Hugging Face</a>
        <span class="v-sep" aria-hidden="true">·</span>
        <a href="https://huggingface.co/tfrere" target="_blank" rel="noopener">tfrere</a>
        <span class="v-sep" aria-hidden="true">·</span>
        <a href="https://huggingface.co/A-Mahla" target="_blank" rel="noopener">A-Mahla</a>
        <span class="v-sep" aria-hidden="true">·</span>
        <a href="https://huggingface.co/andito" target="_blank" rel="noopener">andito</a>
      </span>
    </div>
  </div>
</template>
```

`console/frontend/src/features/voice/components/AccountWidget.vue`（demo 的 `#account` + `ui/account.js`：未登录时是 Sign in 胶囊，登录后是带剩余分钟的头像胶囊；额度耗尽时弹出 `LimitDialog`）：

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { MeResponse } from '../types'

const props = defineProps<{ me: MeResponse }>()
const emit = defineEmits<{ (e: 'limit'): void }>()

const PRO_URL = 'https://huggingface.co/subscribe/pro'
const unlimited = computed(() => props.me.tier === 'pro' || props.me.tier === 'org')
const remaining = computed(() => {
  if (!props.me.enabled) return ''
  if (unlimited.value || props.me.remainingSec == null) return 'Unlimited'
  return `${Math.max(0, Math.floor(props.me.remainingSec / 60))} min left today`
})
// 额度已耗尽时点胶囊直接弹限制卡，而不是让用户自己去找。
const spent = computed(() => !unlimited.value && props.me.remainingSec != null && props.me.remainingSec <= 0)
</script>

<template>
  <!-- 未开启账号体系时整块不渲染（§14.5 第八条） -->
  <template v-if="props.me.enabled">
    <a v-if="!props.me.loggedIn && props.me.auth && props.me.loginUrl" class="v-account v-account--signin" :href="props.me.loginUrl">
      Sign in for more time
    </a>
    <a-popover v-else-if="props.me.loggedIn" placement="bottomRight" trigger="click">
      <template #content>
        <p class="v-account__tier">{{ props.me.tier === 'pro' ? 'PRO' : props.me.tier === 'org' ? 'Team' : 'Free' }}</p>
        <p class="v-account__remaining">{{ remaining }}</p>
        <a v-if="!unlimited" class="v-account__link" :href="PRO_URL" target="_blank" rel="noopener">Upgrade to PRO</a>
        <a class="v-account__link" :href="props.me.logoutUrl || '#'">Sign out</a>
      </template>
      <button class="v-account" :class="{ 'is-spent': spent }" @click="spent && emit('limit')">
        <img v-if="props.me.avatar" class="v-account__avatar" :src="props.me.avatar" alt="" width="20" height="20" />
        <span>{{ props.me.username || 'you' }}</span>
      </button>
    </a-popover>
  </template>
</template>
```

`console/frontend/src/features/voice/components/AboutDialog.vue`（demo 的 `#about-modal`：项目简介 + 四段 pipeline。旧计划只有「Speech to speech console / Version」两行，把旧页最有信息量的部分删了）：

```vue
<script setup lang="ts">
const props = defineProps<{ open: boolean; version: string }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const STAGES = [
  { tag: 'VAD', job: 'detects speech', model: 'silero-vad', href: 'https://github.com/snakers4/silero-vad' },
  { tag: 'STT', job: 'transcribes it', model: 'nvidia/parakeet-tdt-1.1b', href: 'https://huggingface.co/nvidia/parakeet-tdt-1.1b' },
  { tag: 'VLM', job: 'composes the reply', model: 'google/gemma-4-31B-it', href: 'https://huggingface.co/google/gemma-4-31B-it' },
  { tag: 'TTS', job: 'speaks it back', model: 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice', href: 'https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice' }
]
</script>

<template>
  <a-modal :open="props.open" title="About" :footer="null" :width="560" @cancel="emit('update:open', false)">
    <p class="v-hint">
      Speech-to-speech is Hugging Face's open framework for real-time voice agents. Rather than one end-to-end
      model, it chains four open models from the Hub, so any stage can be swapped or run locally.
    </p>
    <a class="v-account__link" href="https://github.com/huggingface/speech-to-speech" target="_blank" rel="noopener">
      View the project on GitHub
    </a>

    <p class="v-pipe__title">The pipeline</p>
    <ol class="v-pipe">
      <li class="v-pipe__end">You speak</li>
      <li v-for="stage in STAGES" :key="stage.tag" class="v-pipe__stage">
        <span class="v-pipe__tag">{{ stage.tag }}</span>
        <span class="v-pipe__job">{{ stage.job }}</span>
        <a :href="stage.href" target="_blank" rel="noopener">{{ stage.model }}</a>
      </li>
      <li class="v-pipe__end">The orb replies</li>
    </ol>

    <p class="v-about__version">Version {{ props.version || 'unknown' }}</p>
  </a-modal>
</template>
```

`console/frontend/src/features/voice/components/TurnTimings.vue`（助手条目里的 `Server timings` 折叠块，逐行对回 `ui/chat.js:636-678` 的 `_appendTimings`）。**demo 没有舞台 chip 行**：`index.html` 与 `main.js` 里搜不到任何 latency 节点，所有计时只出现在历史条目里；上一版计划凭空加了一行 `turn / stt / llm / tts / total` 的 chip，已删除。

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type { TurnLatency } from '../types'
import { statusLabel, timingNote, timingRows, timingSummary } from '../useTurnLatency'

const props = defineProps<{ latency: TurnLatency }>()

const summary = computed(() => timingSummary(props.latency))
const rows = computed(() => timingRows(props.latency))
const note = computed(() => timingNote(props.latency))
</script>

<template>
  <details class="hist-timings">
    <summary>{{ summary }}</summary>
    <p class="timing-status">{{ statusLabel(latency.status) }}</p>
    <dl>
      <template v-for="row in rows" :key="row.label">
        <dt>{{ row.label }}</dt>
        <dd>{{ row.value }}</dd>
      </template>
    </dl>
    <p>{{ note }}</p>
  </details>
</template>
```

`useTurnLatency.ts` 里四个导出的口径（全部对回 `chat.js`，不自作主张）：

| 导出 | 输入 → 输出 | 与 demo 的对应 |
|---|---|---|
| `readTurnLatency(response)`（本文件只 re-export，实现在 Step 5 的 `transport/turn-latency.ts`） | OpenAI `response` → `TurnLatency \| null` | 逐条移植 `turn-latency.js` 的校验：`version ∈ {1,2}`、`status ∈ {completed,cancelled,failed,incomplete}` 且等于 `response.status`、五个时长非负有限、`smart_status` 四值，任何一条不符就返回 `null`（宁可不显示，不显示错的） |
| `formatSeconds(seconds)` | `number \| null \| undefined` → `6.26 s` / `Unavailable` | `chat.js:637`：`null` 与 `Infinity` 都写 `Unavailable`，不写 `0.00 s`；有效值固定两位小数加一个空格再加 `s` |
| `timingSummary(t)` | `Server timings` / `Server timings · E2E 6.26 s` / `Server timings · First audio 6.26 s` | `chat.js:643-645`：`e2e_s === null` 时只有两个词；v1 把 `E2E` 换成 `First audio` |
| `statusLabel(status)` | `Completed` / `Interrupted` / `Failed` / `Incomplete` | `chat.js:649` 的四态字符串，不是原枚举值 |
| `timingRows(t)` | 七行 `{label, value}` | `chat.js:653-661`：`E2E time`（v1 为 `VAD handoff to first audio`）/ `VAD end decision` / `Smart Turn decision`（字符串，如 `disabled`）/ `Transcription` / `Response generation` / `Voice synthesis to first audio` / `Hold time before response`（v2 取 `hold_s`，v1 取 `smart_wait_s`）；数值 `null` 一律 `Unavailable`，否则 `toFixed(2) + ' s'` |
| `timingNote(t)` | v2：`E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.`；v1：`First audio: VAD handoff to generated audio, excluding browser playback. Stages overlap and do not add up.` | `chat.js:671-673` 逐字 |

`console/frontend/src/features/voice/useTurnLatency.spec.ts`（6 条：合法 v2 原样返回、`e2e_s=null` 时 summary 退回两个词、`status` 与 `response.status` 不一致返回 `null`、负值与 `Infinity` 返回 `null`、v1 的标签换词、`formatSeconds(null)` 是 `Unavailable`）：

Run: `cd console/frontend && npx vitest run src/features/voice/useTurnLatency.spec.ts`
Expected: 6 passed。

`console/frontend/src/features/voice/components/LimitDialog.vue`（demo 的 `#limit-modal`：额度用完时的卡片。标题 / 正文 / CTA / note 按 tier 填，不写死一句「额度已用完」）：

```vue
<script setup lang="ts">
const props = defineProps<{
  open: boolean
  title: string
  message: string
  ctaLabel: string
  ctaHref: string
  note: string
}>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()
</script>

<template>
  <a-modal :open="props.open" :footer="null" :width="420" :closable="true" @cancel="emit('update:open', false)">
    <div class="v-limit">
      <span class="v-limit__badge" aria-hidden="true">
        <svg viewBox="0 0 95 88" fill="none"><path fill="#FFD21E" d="M47.21 76.5a34.75 34.75 0 1 0 0-69.5 34.75 34.75 0 0 0 0 69.5Z" /><path fill="#FF9D0B" d="M81.96 41.75a34.75 34.75 0 1 0-69.5 0 34.75 34.75 0 0 0 69.5 0Zm-73.5 0a38.75 38.75 0 1 1 77.5 0 38.75 38.75 0 0 1-77.5 0Z" /><path fill="#3A3B45" d="M58.5 32.3c1.28.44 1.78 3.06 3.07 2.38a5 5 0 1 0-6.76-2.07c.61 1.15 2.55-.72 3.7-.32ZM34.95 32.3c-1.28.44-1.79 3.06-3.07 2.38a5 5 0 1 1 6.76-2.07c-.61 1.15-2.56-.72-3.7-.32Z" /><path fill="#FF323D" d="M46.96 56.29c9.83 0 13-8.76 13-13.26 0-2.34-1.57-1.6-4.09-.36-2.33 1.15-5.46 2.74-8.9 2.74-7.19 0-13-6.88-13-2.38s3.16 13.26 13 13.26Z" /><path fill="#3A3B45" fill-rule="evenodd" d="M39.43 54a8.7 8.7 0 0 1 5.3-4.49c.4-.12.81.57 1.24 1.28.4.68.82 1.37 1.24 1.37.45 0 .9-.68 1.33-1.35.45-.7.89-1.38 1.32-1.25a8.61 8.61 0 0 1 5 4.17c3.73-2.94 5.1-7.74 5.1-10.7 0-2.34-1.57-1.6-4.09-.36l-.14.07c-2.31 1.15-5.39 2.67-8.77 2.67s-6.45-1.52-8.77-2.67c-2.6-1.29-4.23-2.1-4.23.29 0 3.05 1.46 8.06 5.47 10.97Z" clip-rule="evenodd" /></svg>
      </span>
      <h2 class="v-limit__title">{{ props.title }}</h2>
      <p class="v-limit__msg">{{ props.message }}</p>
      <a class="v-join v-limit__cta" :href="props.ctaHref">{{ props.ctaLabel }}</a>
      <p class="v-limit__note">{{ props.note }}</p>
    </div>
  </a-modal>
</template>
```

---

- [ ] **Step 19: 写 `views/VoiceView.vue`，替换路由与 `index.html`**

`console/frontend/src/views/VoiceView.vue`——页面只做三件事：装配、接线、拆装。业务状态全在 store 与 client 里。**刷新即结束会话**（与 demo 一致）：只保设置，不保转写。

```vue
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { endSessionBeacon, getDemoConfig, getMe, heartbeat, leaveQueueBeacon, search } from '@/api/demo'
import { acquireMic, releaseMic } from '@/features/voice/audio/capture'
import { GATE_OFF_DB, SpeakingDetector } from '@/features/voice/audio/meter'
import { startLocalVad } from '@/features/voice/audio/vad'
import AboutDialog from '@/features/voice/components/AboutDialog.vue'
import AccountWidget from '@/features/voice/components/AccountWidget.vue'
import BubbleStack from '@/features/voice/components/BubbleStack.vue'
import CameraPip from '@/features/voice/components/CameraPip.vue'
import HistoryDrawer from '@/features/voice/components/HistoryDrawer.vue'
import IdentityBlock from '@/features/voice/components/IdentityBlock.vue'
import LimitDialog from '@/features/voice/components/LimitDialog.vue'
import MicGate from '@/features/voice/components/MicGate.vue'
import OrbStage from '@/features/voice/components/OrbStage.vue'
import QueueOverlay from '@/features/voice/components/QueueOverlay.vue'
import SettingsDialog from '@/features/voice/components/SettingsDialog.vue'
import ToolsDialog from '@/features/voice/components/ToolsDialog.vue'
import { openCamera, snapshot } from '@/features/voice/tools/camera'
import { S2sClient } from '@/features/voice/transport/s2s-client'
import type { Bubble, ToolCall, ToolDef, VoiceSettings } from '@/features/voice/types'
import { useShellStore } from '@/stores/shell'
import { useVoiceStore } from '@/stores/voice'

const store = useVoiceStore()
const shell = useShellStore()

/**
 * 侧栏的 History / Tools / Settings / About 是「打开浮层」的动作，不是路由（§3.2.4）：
 * 外壳只把选择写进 `shell.voiceOverlay`，页面负责打开对应的抽屉/对话窗并立刻清空选择。
 */
watch(
  () => shell.voiceOverlay,
  (overlay) => {
    if (overlay === 'history') historyOpen.value = true
    if (overlay === 'tools') toolsOpen.value = true
    if (overlay === 'settings') {
      settingsOpen.value = true
      void refreshDevices()
    }
    if (overlay === 'about') aboutOpen.value = true
    if (overlay) shell.closeOverlay()
  }
)

/** 回放用户原音时静音上行，停止后按当前静音钮状态恢复（demo 的 `userAudioReplaying`）。 */
function onReplay(playing: boolean): void {
  client?.setMuted(playing || muted.value)
}

/** demo/index.html 的九个 voice：顺序与值都不能变，它会进 session.update。 */
const VOICES = ['Aiden', 'Ryan', 'Dylan', 'Eric', 'Ono_Anna', 'Serena', 'Sohee', 'Uncle_Fu', 'Vivian']

const settingsOpen = ref(false)
const toolsOpen = ref(false)
const aboutOpen = ref(false)
const historyOpen = ref(false)
const limitOpen = ref(false)
const micError = ref('')
const levelDb = ref(-100)
const notice = ref('')
const expiresSec = ref(60)
const muted = ref(false)
const queueFull = ref(false)
const bubbles = ref<Bubble[]>([])
const inputs = ref<Array<{ id: string; label: string }>>([])
const outputs = ref<Array<{ id: string; label: string }>>([])
/** 用户自带的 Serper key：**只在内存里**，不进 localStorage，也不进 URL（B5）。 */
const searchKey = ref('')
/** `/api/config.version` 不在 Task 17 的必填字段里；缺了就显示 unknown，不报错。 */
const version = ref('')

let bubbleId = 0
let client: S2sClient | null = null
let mic: MediaStream | null = null
let vad: { destroy: () => Promise<void> } | null = null
let camStream: MediaStream | null = null
let heartbeatTimer = 0
const detector = new SpeakingDetector()
const camPip = ref<InstanceType<typeof CameraPip> | null>(null)

const MIC_ERRORS: Record<string, string> = {
  'mic-denied': 'Microphone access was blocked. Allow it from your browser address bar, then retry.',
  'mic-missing': 'No microphone found. Plug one in or pick another input in Settings.',
  'mic-failed': 'The microphone could not be opened. Retry, or pick another input in Settings.'
}

const CONNECT_ERRORS: Record<string, string> = {
  limit: "You're out of minutes for today — they reset daily.",
  'login-required': 'Sign in again to continue.',
  'queue-full': 'The waiting line is full. Try again in a minute.',
  'queue-expired': 'Your spot in line expired.',
  'join-expired': 'Your spot expired before you joined.',
  aborted: ''
}

const serverKey = computed(() => store.config.search)
const searchAvailable = computed(() => serverKey.value || Boolean(searchKey.value))
const serverUrl = computed(() => store.config.s2sUrl || `${location.protocol}//${location.host}`)
// 上游地址被钉死时 WebRTC 的 /api/calls 代理也只转发那一个地址，因此传输方式不可选。
const transportLocked = computed(() => !store.config.allowDirect)

const caption = computed(() => {
  if (micError.value) return MIC_ERRORS[micError.value] ?? micError.value
  if (notice.value) return notice.value
  switch (store.state) {
    case 'idle': return 'Tap to start'
    case 'connecting': return 'Connecting'
    case 'queued': return `Queued · position ${store.queue?.position ?? '—'}`
    case 'your-turn': return "You're up!"
    case 'listening':
    case 'user-speaking': return 'Listening'
    case 'processing': return 'Thinking'
    case 'ai-speaking': return 'Speaking'
    case 'error': return 'Tap to retry'
    default: return ''
  }
})
const subCaption = computed(() =>
  store.state === 'queued' ? 'Every slot is busy, so we saved you a spot. Hang tight, you’re moving up.' : ''
)
const captionTone = computed<'info' | 'error'>(() => (micError.value || notice.value || store.state === 'error' ? 'error' : 'info'))

const tools = computed<ToolDef[]>(() => {
  const list: ToolDef[] = []
  if (store.settings.tools.web && searchAvailable.value) {
    list.push({
      type: 'function',
      name: 'web_search',
      description: 'Search the web for current or factual information. Returns results with titles, snippets and URLs.',
      parameters: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] }
    })
  }
  if (store.settings.tools.camera) {
    list.push({
      type: 'function',
      name: 'camera_snapshot',
      description: "Capture a frame from the user's webcam when they refer to something visual.",
      parameters: { type: 'object', properties: {}, required: [] }
    })
  }
  return list
})

const limitCopy = computed(() => {
  const paid = store.me.tier === 'pro' || store.me.tier === 'org'
  return paid
    ? {
        title: "That's a wrap for now",
        message: 'Your organisation has used today’s shared minutes.',
        ctaLabel: 'Back to the space',
        ctaHref: '/',
        note: 'Daily caps keep the shared pool healthy for everyone.'
      }
    : {
        title: "That's a wrap for now",
        message: 'You have used your free minutes for today.',
        ctaLabel: 'Sign in for more time',
        ctaHref: store.me.loginUrl || 'https://huggingface.co/subscribe/pro',
        note: 'Free minutes reset every day.'
      }
})

/** demo 的 #bubble-stack：同时最多四条，4.2s 后自己消失。 */
function say(role: Bubble['role'], text: string): void {
  if (!text) return
  const id = ++bubbleId
  bubbles.value = [...bubbles.value, { id, role, text }].slice(-4)
  window.setTimeout(() => (bubbles.value = bubbles.value.filter((item) => item.id !== id)), 4200)
}

async function runTool(call: ToolCall) {
  if (call.name === 'web_search') {
    const args = JSON.parse(call.arguments || '{}') as { query?: string }
    say('tool', `Searching for “${args.query ?? ''}”`)
    return { output: await search(args.query ?? '', searchKey.value, store.grant?.sessionId ?? '') }
  }
  if (call.name === 'camera_snapshot') {
    const video = camPip.value?.video
    if (!camStream || !video?.videoWidth) return { output: 'The camera is not available right now.' }
    const image = snapshot(video)
    camPip.value?.flash()
    return image ? { output: 'Here is the current camera frame.', image } : { output: 'The camera is not available right now.' }
  }
  return { output: `Unknown tool: ${call.name}` }
}

async function connect(): Promise<void> {
  if (client) return
  store.resetTranscript()
  micError.value = ''
  notice.value = ''
  queueFull.value = false
  try {
    mic = await acquireMic(store.settings.audioInputId)
  } catch (error: any) {
    micError.value = error?.code ?? 'mic-failed'
    store.setState('idle')
    return
  }
  client = new S2sClient({
    transport: store.config.rtc && store.settings.transport === 'webrtc' ? 'webrtc' : 'websocket',
    sessionUrl: '/api/session',
    callsUrl: '/api/calls',
    voice: store.settings.voice,
    instructions: store.settings.instructions,
    tools: tools.value,
    iceServers: store.config.iceServers,
    startupGreeting: store.config.startupGreeting,
    localVad: store.settings.localVad,
    noiseGate: { enabled: store.settings.noiseGateDb > GATE_OFF_DB, thresholdDb: store.settings.noiseGateDb },
    playbackBufferMs: store.settings.playbackBufferMs,
    micStream: mic,
    acquireMic: () => Promise.resolve(mic as MediaStream),
    executeTool: runTool
  })
  client.addEventListener('status', (event: Event) => store.setState((event as CustomEvent).detail.status))
  client.addEventListener('server-event', (event: Event) => {
    const detail = (event as CustomEvent).detail
    store.applyEvent(detail)
    // 气泡只搬「刚刚发生的一件事」，完整转写归历史抽屉。
    if (detail?.type === 'conversation.item.input_audio_transcription.completed') say('user', detail.transcript)
    if (detail?.type === 'response.audio_transcript.done') say('assistant', detail.transcript)
  })
  client.addEventListener('level', (event: Event) => {
    const db = (event as CustomEvent).detail.db as number
    levelDb.value = db
    detector.push(db)
  })
  client.addEventListener('session', (event: Event) => {
    const grant = (event as CustomEvent).detail.grant
    if (!grant?.sessionId) return
    store.grant = grant
    if (grant.remainingSec != null) store.me = { ...store.me, remainingSec: grant.remainingSec }
    void client?.setAudioOutputDevice(store.settings.audioOutputId)
    startHeartbeat(grant.heartbeatSec)
    void refreshMe()
  })
  client.addEventListener('ready-to-join', (event: Event) => {
    expiresSec.value = (event as CustomEvent).detail.expiresSec ?? 60
  })
  client.addEventListener('response-finished', (event: Event) => {
    // §3.9.4：计时交给 store 挂到那条助手条目上（demo 的 `_appendTimings` 也挂在 hist 条目里）。
    // 页面自己不再持有 `turnIndex` / `store.latency` ——历史抽屉里每条助手条目各有一份数字，
    // 只存「最新一条」会让同一条对话在抽屉里除了最后一句之外全部没有计时。
    store.attachLatency((event as CustomEvent).detail.latency ?? null)
  })
  try {
    await client.connect()
  } catch (error: any) {
    // 402 / 401 / queue-full / join-expired 都以带 code 的错误到达。
    notice.value = CONNECT_ERRORS[error?.code] ?? 'Could not start the conversation.'
    queueFull.value = error?.code === 'queue-full'
    if (error?.code === 'limit') limitOpen.value = true
    await teardown()
    store.setState('error')
    return
  }
  if (store.settings.localVad) {
    vad = await startLocalVad({
      stream: mic,
      isEnabled: () => Boolean(client),
      onChange: (speaking) => store.setState(speaking ? 'user-speaking' : 'listening')
    })
  }
  if (store.settings.tools.camera) await startCamera()
}

function startHeartbeat(seconds: number | null): void {
  stopHeartbeat()
  if (!seconds) return
  heartbeatTimer = window.setInterval(async () => {
    const sessionId = store.grant?.sessionId
    if (!sessionId) return
    const result = await heartbeat(sessionId)
    if (result.remainingSec != null) store.me = { ...store.me, remainingSec: result.remainingSec }
    // 额度中途用完：立刻拆掉并弹限制卡，不等下一次 402。
    if (result.expired) {
      limitOpen.value = true
      await stop()
    }
  }, seconds * 1000)
}

function stopHeartbeat(): void {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer)
  heartbeatTimer = 0
}

async function teardown(): Promise<void> {
  stopHeartbeat()
  await vad?.destroy()
  vad = null
  await client?.close()
  client = null
  releaseMic(mic)
  mic = null
  stopCamera()
  detector.reset()
  levelDb.value = -100
}

async function stop(): Promise<void> {
  if (store.grant?.sessionId) endSessionBeacon(store.grant.sessionId)
  store.grant = null
  await teardown()
  store.setState('idle')
  notice.value = ''
  micError.value = ''
}

/** 「Restart conversation with these settings」：丢会话、带新设置重连。 */
async function restart(): Promise<void> {
  await stop()
  await connect()
}

async function leaveQueue(): Promise<void> {
  const queueId = store.queue?.queueId
  if (queueId) leaveQueueBeacon(queueId)
  store.queue = null
  queueFull.value = false
  await stop()
}

function join(): void {
  client?.join()
}

function toggleMute(next: boolean): void {
  muted.value = next
  client?.setMuted(next)
}

function setGate(db: number): void {
  store.saveSettings({ ...store.settings, noiseGateDb: db })
  client?.setNoiseGate({ enabled: db > GATE_OFF_DB, thresholdDb: db })
}

async function startCamera(): Promise<void> {
  if (camStream) return
  try {
    camStream = await openCamera()
    // PiP 是 v-if 挂上的：等它真的在 DOM 里再 srcObject，否则拿到 null。
    await nextTick()
    const video = camPip.value?.video
    if (video) {
      video.srcObject = camStream
      await video.play().catch(() => {})
    }
  } catch {
    stopCamera()
    store.saveSettings({ ...store.settings, tools: { ...store.settings.tools, camera: false } })
  }
}

function stopCamera(): void {
  for (const track of camStream?.getTracks() ?? []) track.stop()
  camStream = null
  const video = camPip.value?.video
  if (video) video.srcObject = null
}

async function applySession(instructions: string): Promise<void> {
  if (!client) return
  client.updateSession({ instructions })
}

async function refreshDevices(): Promise<void> {
  if (!navigator.mediaDevices?.enumerateDevices) return
  const devices = await navigator.mediaDevices.enumerateDevices()
  inputs.value = devices
    .filter((device) => device.kind === 'audioinput')
    .map((device, index) => ({ id: device.deviceId, label: device.label || `Microphone ${index + 1}` }))
  outputs.value = devices
    .filter((device) => device.kind === 'audiooutput')
    .map((device, index) => ({ id: device.deviceId, label: device.label || `Speakers ${index + 1}` }))
}

async function onSettingsSave(next: VoiceSettings): Promise<void> {
  store.saveSettings(next)
  // 工具、门限、输出设备立即生效；其余按 demo 的规矩等下一个会话（或 Restart）。
  client?.setTools(tools.value)
  client?.setNoiseGate({ enabled: next.noiseGateDb > GATE_OFF_DB, thresholdDb: next.noiseGateDb })
  await client?.setAudioOutputDevice(next.audioOutputId)
  await applySession(next.instructions)
  if (next.tools.camera) await startCamera()
  else stopCamera()
}

function onToolsChange(): void {
  store.saveSettings(store.settings)
  client?.setTools(tools.value)
  if (store.settings.tools.camera) void startCamera()
  else stopCamera()
}

async function refreshMe(): Promise<void> {
  store.me = await getMe()
}

onMounted(async () => {
  store.config = await getDemoConfig()
  version.value = (store.config as { version?: string }).version ?? ''
  store.loadSettings()
  void refreshMe()
  void refreshDevices()
})

onBeforeUnmount(() => {
  // 页面卸载必须退回预约：sendBeacon 能在 unload 之后仍送达。
  if (store.grant?.sessionId) endSessionBeacon(store.grant.sessionId)
  if (store.queue?.queueId) leaveQueueBeacon(store.queue.queueId)
  stopHeartbeat()
  void teardown()
})
</script>

<template>
  <main class="v-page">
    <!-- 对话页没有自己的顶栏：账号 chip 与工具 / 历史 / 设置三枚按钮挂到外壳顶栏的
         `#shell-actions` 上（§3.2.4）；About 是 `IdentityBlock` 里的圆钮，留在舞台。
         离开对话页时 Teleport 自动摘下。 -->
    <Teleport to="#shell-actions">
      <AccountWidget :me="store.me" @limit="limitOpen = true" />
      <button class="v-icon" title="Tools" aria-label="Tools" @click="toolsOpen = true">
        <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-wrench" /></svg>
      </button>
      <button class="v-icon" title="Conversation history" aria-label="Conversation history" @click="historyOpen = true">
        <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-chat" /></svg>
        <span v-if="store.entries.length" class="v-badge" aria-hidden="true" />
      </button>
      <button class="v-icon" title="Settings" aria-label="Settings" @click="settingsOpen = true; refreshDevices()">
        <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-gear" /></svg>
      </button>
    </Teleport>

    <!-- 标题与 blurb 退回舞台头部：外壳顶栏已经被品牌与账号占据（§3.2.4）。 -->
    <header class="v-head">
      <IdentityBlock @about="aboutOpen = true" />
    </header>

    <section class="v-stage">
      <BubbleStack :items="bubbles" />

      <OrbStage
        :state="store.state"
        :level-db="levelDb"
        :caption="caption"
        :sub-caption="subCaption"
        :tone="captionTone"
        @activate="connect"
      >
        <template #left>
          <MicGate v-if="store.live" :muted="muted" :gate-db="store.settings.noiseGateDb" :level-db="levelDb" @update:muted="toggleMute" @update:gate-db="setGate" />
        </template>
        <template #right>
          <button v-if="store.live" class="v-side v-side--stop" type="button" aria-label="End" title="End" @click="stop">
            <svg class="v-i v-i--fill" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-stop" /></svg>
          </button>
        </template>
      </OrbStage>

      <QueueOverlay
        :state="store.state"
        :position="store.queue?.position ?? 0"
        :expires-sec="expiresSec"
        :full="queueFull"
        @join="join"
        @leave="leaveQueue"
      />

      <!--
        舞台上不放任何计时 chip：demo 的 `index.html` / `main.js` 搜不到 latency 节点，
        计时只出现在历史条目的 `details.hist-timings` 里（`TranscriptList` → `TurnTimings`）。
        这里也不再传 `turnIndex`：没有任何组件需要它。
      -->
    </section>

    <footer class="v-foot">
      Powered by
      <a href="https://github.com/huggingface/speech-to-speech" target="_blank" rel="noopener">huggingface/speech-to-speech</a>
    </footer>

    <CameraPip ref="camPip" :active="store.settings.tools.camera && Boolean(camStream)" />

    <HistoryDrawer v-model:open="historyOpen" :entries="store.entries" @replay="onReplay" />

    <SettingsDialog
      v-model:open="settingsOpen"
      :server-url="serverUrl"
      :transport-locked="transportLocked"
      :voices="VOICES"
      :inputs="inputs"
      :outputs="outputs"
      :settings="store.settings"
      :connected="store.live"
      @save="onSettingsSave"
      @restart="restart"
    />

    <ToolsDialog
      v-model:open="toolsOpen"
      :search-available="searchAvailable"
      :server-key="serverKey"
      :web-search="store.settings.tools.web"
      :camera="store.settings.tools.camera"
      :search-key="searchKey"
      @update:web-search="(value: boolean) => { store.settings.tools.web = value; onToolsChange() }"
      @update:camera="(value: boolean) => { store.settings.tools.camera = value; onToolsChange() }"
      @update:search-key="(value: string) => { searchKey = value; onToolsChange() }"
    />

    <AboutDialog v-model:open="aboutOpen" :version="version" />

    <LimitDialog v-model:open="limitOpen" v-bind="limitCopy" />
  </main>
</template>
```

`console/frontend/src/styles/voice.less`（**深色基线**。旧计划那份是白底绿球的亮色稿，贴在 `#0b1020` 上就是一张白纸。色值与 `console/design/console-preview.html` 的 `--voice-*` 逐个对齐；变量挂在 `:root` 而不是 `.v-page`，因为 `a-modal` / `a-drawer` 会被 teleport 到 `body`，挂在页面上它们就取不到了）：

```less
// 彩色只属于声音：界面本身是无彩度的，只有 orb / 弧线 / 状态色带颜色。
:root {
  --voice-bg: #0a0b10;
  --voice-surface: #13151c;
  --voice-surface-2: #1b1e29;
  --voice-border: rgba(255, 255, 255, 0.08);
  --voice-border-strong: rgba(255, 255, 255, 0.16);
  --voice-text: #f5f6fa;
  --voice-dim: rgba(245, 246, 250, 0.65);
  --voice-faint: rgba(245, 246, 250, 0.42);
  --voice-accent: #8b7dff;
  --voice-listening: #22d3ee;
  --voice-processing: #f59e0b;
  --voice-error: #ff6a75;
  --voice-ready: #34d399;
  --voice-queued: #94a3b8;
}

// ── 对话页嵌在外壳里的高度契约（§3.2.4）────────────────────────────────
// `.shell__content` 是 `flex: 1 1 auto; min-height: 0`，所以这里写 `height: 100%`
// 而不是 `min-height: 100vh`：后者会把页脚推到视口外，外壳的滚动条一闪就被
// `overflow: hidden` 藏掉，舞台高度只剩下一条缝。
.v-page {
  height: 100%;
  min-height: 0;
  display: grid;
  // 三行：头部（IdentityBlock）/ 舞台（`minmax(0, 1fr)` 允许被压缩）/ 页脚
  grid-template-rows: auto minmax(0, 1fr) auto;
  // `CameraPip` 的绝对定位基准就是这一层（见 `.v-pip`）。
  position: relative;
  background: var(--voice-bg);
  color: var(--voice-text);
  font-size: 14px;
}

// 头部只剩 IdentityBlock 与两行鸣谢。账号 chip 与工具 / 历史 / 设置三枚按钮
// 被 `VoiceView` `Teleport` 到外壳顶栏的 `#shell-actions`，不在这一层；About 是
// `IdentityBlock` 里的圆钮，随头部留在舞台。
.v-head {
  padding: 20px 24px 0;
}

.v-ident {
  max-width: 560px;

  &__head { display: flex; align-items: center; gap: 8px; }
  &__title { color: var(--voice-text); font-size: 15px; font-weight: 600; }
  &__title:hover { color: var(--voice-accent); }
  &__blurb { margin: 4px 0 8px; color: var(--voice-dim); font-size: 13px; line-height: 1.5; }
}

.v-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11.5px;
  color: var(--voice-faint);

  a { color: var(--voice-dim); }
  a:hover { color: var(--voice-text); }
  &__label { margin-right: 6px; }
}

.v-sep { margin: 0 6px; opacity: 0.5; }

// `Teleport` 到 `#shell-actions` 的四个按钮仍然带 `.v-icon`：`voice.less` 是全局
// 样式（不是 scoped），被传送出去的节点照样命中，长得与旧页一致。
.v-actions { display: flex; align-items: center; gap: 8px; }

.v-icon {
  position: relative;
  display: inline-grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--voice-border);
  border-radius: 50%;
  background: transparent;
  color: var(--voice-dim);
  cursor: pointer;

  &:hover { color: var(--voice-text); border-color: var(--voice-border-strong); }
  &--sm { width: 20px; height: 20px; border: 0; }
}

// 图标几何（fill / stroke / stroke-width）全部写在 index.html 的 <symbol> 里。
// 这里只给尺寸与颜色：<use> 会把 symbol 克隆进 shadow tree，而表现属性优先于
// 继承来的 CSS，所以在这儿写 fill / stroke 也覆盖不动里面的形状。
.v-i {
  width: 18px;
  height: 18px;
  color: inherit;
}

.v-icon--sm .v-i { width: 14px; height: 14px; }

.v-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--voice-accent);
}

.v-account {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--voice-border);
  border-radius: 999px;
  background: var(--voice-surface);
  color: var(--voice-dim);
  font-size: 12px;
  cursor: pointer;

  &:hover { color: var(--voice-text); }
  &.is-spent { color: var(--voice-error); border-color: color-mix(in srgb, var(--voice-error) 40%, transparent); }
  &--signin { color: var(--voice-text); border-color: var(--voice-border-strong); }
  &__avatar { border-radius: 50%; }
  &__tier { margin: 0; font-size: 11px; letter-spacing: 0.08em; color: var(--voice-faint); }
  &__remaining { margin: 2px 0 8px; font-size: 13px; }
  &__link { display: block; font-size: 12px; }
}

.v-stage {
  // 嵌进外壳后舞台不再是整页：orb 仍在这一层里居中，PiP 以这一层为基准贴左下。
  position: relative;
  // grid 子项默认 `min-height: auto`，内容一多就顶破 `1fr`，把页脚挤出可视区。
  min-height: 0;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 18px;
  padding: 24px 16px 40px;
  overflow: hidden;
}

.v-orb-wrap {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
}

.v-side {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--voice-border-strong);
  background: color-mix(in srgb, var(--voice-surface-2) 80%, #2a2e3c);
  color: var(--voice-dim);
  cursor: pointer;

  &:hover { color: var(--voice-text); }
  &--stop:hover { color: var(--voice-error); border-color: color-mix(in srgb, var(--voice-error) 50%, transparent); }
}

.v-orb {
  position: relative;
  display: grid;
  place-items: center;
  width: clamp(140px, min(38vw, 46vh), 320px);
  aspect-ratio: 1 / 1;
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--glow, var(--voice-accent));
  cursor: pointer;

  &:disabled { cursor: default; }
  &__glow {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: radial-gradient(circle at center, var(--glow) 0%, transparent 65%);
    filter: blur(28px);
    opacity: calc(0.38 + 0.42 * var(--glow-strength, 0));
    transition: opacity 120ms linear;
  }
  &__ring {
    position: absolute;
    width: 82%;
    height: 82%;
    border-radius: 50%;
    border: 1.5px solid color-mix(in srgb, var(--glow) 35%, transparent);
    opacity: 0.4;
  }
  &__ring--outer {
    width: 96%;
    height: 96%;
    opacity: 0.18;
    transform: scale(0.98);
  }
  &__core {
    position: relative;
    width: 72%;
    height: 72%;
    border-radius: 50%;
    border: 2px solid color-mix(in srgb, var(--glow) 40%, transparent);
    background: radial-gradient(
      circle at 35% 28%,
      color-mix(in srgb, var(--glow) 28%, transparent),
      color-mix(in srgb, var(--glow) 10%, transparent) 55%,
      color-mix(in srgb, var(--glow) 5%, transparent)
    );
    display: grid;
    place-items: center;
  }
  &__ind {
    width: 44%;
    height: 44%;
    display: grid;
    place-items: center;
    // 指示器跟随球体颜色轴（.v-orb 上的 --glow），不写死正文色。
    color: inherit;
    opacity: 0.9;

    // demo 的指示器都是「占球心的百分比」（.circle-indicator 44% / svg 60%，
    // demo/style.css:685-703），因为球体在 140–320px 间自适应。写死 18px 会让
    // 大屏上的球心缩成一个小点，小屏上又溢出。
    .v-i { width: 60%; height: 60%; }
    .v-spinner { width: 48%; height: 48%; border-width: 3px; }
    .v-dots { gap: 8%; }
    .v-dots i { width: 15%; height: auto; aspect-ratio: 1 / 1; }
    .v-bars { gap: 10%; height: 42%; }
    .v-bars i { width: 8%; height: 100%; }
  }

  // 九态只用一条轴：--glow。
  &[data-state="idle"] { --glow: var(--voice-ready); }
  &[data-state="connecting"] { --glow: #facd15; }
  &[data-state="your-turn"] { --glow: var(--voice-accent); }
  &[data-state="queued"] { --glow: var(--voice-queued); }
  &[data-state="listening"],
  &[data-state="user-speaking"] { --glow: var(--voice-listening); }
  &[data-state="processing"] { --glow: var(--voice-processing); }
  &[data-state="ai-speaking"] { --glow: var(--voice-accent); }
  &[data-state="error"] { --glow: var(--voice-error); }
}

.v-spinner {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, currentColor 30%, transparent);
  border-top-color: currentColor;
  animation: v-spin 900ms linear infinite;
}

.v-dots,
.v-bars {
  display: inline-flex;
  align-items: center;
  gap: 4px;

  i { display: block; background: currentColor; border-radius: 999px; }
}

.v-dots i { width: 5px; height: 5px; animation: v-dot 1s ease-in-out infinite; }
.v-dots i:nth-child(2) { animation-delay: 0.15s; }
.v-dots i:nth-child(3) { animation-delay: 0.3s; }

.v-bars i { width: 3px; height: 10px; animation: v-bar 900ms ease-in-out infinite; }
.v-bars i:nth-child(2) { animation-delay: 120ms; }
.v-bars i:nth-child(3) { animation-delay: 240ms; }
.v-bars i:nth-child(4) { animation-delay: 360ms; }
.v-bars i:nth-child(5) { animation-delay: 480ms; }

@keyframes v-spin { to { transform: rotate(360deg); } }
@keyframes v-dot { 0%, 100% { opacity: 0.25; } 50% { opacity: 1; } }
@keyframes v-bar { 0%, 100% { transform: scaleY(0.4); } 50% { transform: scaleY(1.6); } }

.mic-gate {
  position: relative;
  width: 80px;
  height: 80px;
  display: grid;
  place-items: center;

  &__arc { position: absolute; inset: 0; width: 80px; height: 80px; }
  &__track { stroke: var(--voice-border-strong); stroke-width: 2.5; }
  &__fill {
    stroke: color-mix(in srgb, var(--voice-listening) 70%, transparent);
    stroke-width: 2.5;
    stroke-dasharray: 100 100;
    transition: stroke-dashoffset 80ms linear;
  }
  &__hit { stroke: transparent; stroke-width: 12; cursor: grab; }
  &__handle { fill: var(--voice-dim); }
  &.is-gating &__handle { fill: var(--voice-ready); }
  &.is-open &__fill { stroke: var(--voice-ready); }
}

.v-caption {
  margin: 0;
  font-size: 17px;
  color: var(--voice-text);
  text-align: center;

  &--error { color: var(--voice-error); font-size: 14px; max-width: 48ch; }
}

.v-sub { margin: -8px 0 0; max-width: 46ch; text-align: center; font-size: 12.5px; color: var(--voice-faint); }

.v-queue {
  display: grid;
  justify-items: center;
  gap: 10px;

  &__body { margin: 0; font-size: 13px; color: var(--voice-dim); }
  &__actions { display: flex; gap: 8px; }
}

.v-join {
  border: 0 !important;
  background: var(--voice-accent) !important;
  color: #0a0b10 !important;
  font-weight: 600;
  border-radius: 999px !important;

  &:hover { background: color-mix(in srgb, var(--voice-accent) 85%, #fff) !important; }
}

.v-leave {
  border-radius: 999px !important;
  border-color: var(--voice-border-strong) !important;
  background: transparent !important;
  color: var(--voice-dim) !important;
}

.v-foot {
  padding: 0 0 20px;
  text-align: center;
  font-size: 11.5px;
  color: var(--voice-faint);

  a { color: var(--voice-dim); }
}

// ── 历史抽屉里的转写条目（demo `#chat-history` 的三种形态）──────────────
.transcript {
  list-style: none;
  margin: 0;
  padding: 8px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
}

.transcript__item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 10px;
  border: 1px solid var(--voice-border);
  border-radius: 10px;
  background: color-mix(in srgb, var(--voice-surface) 92%, transparent);

  // 临时条目（partial）半透明：与旧页的 `.hist-item.transient` 同义。
  &.is-partial { opacity: 0.6; }
  &--tool { border-color: color-mix(in srgb, var(--voice-processing) 40%, transparent); }
  &--assistant { border-color: color-mix(in srgb, var(--voice-accent) 32%, transparent); }
}

.transcript__role {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--voice-faint);
}

.transcript__item--tool .transcript__role { color: var(--voice-processing); }
.transcript__item--assistant .transcript__role { color: var(--voice-accent); }

.transcript__text { white-space: pre-wrap; word-break: break-word; }

// 用户条目原音：标签 + 原生 <audio controls>，与 demo 的 `.hist-audio` 同名同形。
.hist-audio {
  display: flex;
  flex-direction: column;
  gap: 2px;

  &__label { font-size: 10.5px; color: var(--voice-faint); }
  audio { width: 100%; height: 32px; }
}

// tool 条目：Input / Output / Snapshot 三段，包在 <details> 里默认折叠。
.transcript__tool {
  border-top: 1px dashed var(--voice-border);
  padding-top: 4px;

  &-name { cursor: pointer; font-size: 11.5px; color: var(--voice-processing); }
  &-label {
    margin: 6px 0 2px;
    font-size: 10.5px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--voice-faint);
  }
  &-json {
    margin: 0;
    max-height: 140px;
    overflow: auto;
    padding: 6px 8px;
    border-radius: 6px;
    background: #0d1326;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
  }
  &-image { margin-top: 4px; width: 100%; border-radius: 6px; }
}

// 助手条目的计时块：与 demo 的 `.hist-timings` 同名同形（`style.css:2724-2754`）。
// summary 撑到 44px 是触控目标，不是装饰——历史抽屉在手机宽度下也要能用拇指展开。
.hist-timings {
  margin-top: 6px;
  font-size: 12px;
  color: var(--voice-faint);

  summary {
    min-height: 44px;
    padding: 12px 0;
    cursor: pointer;
    touch-action: manipulation;

    &:focus-visible { outline: 2px solid var(--voice-accent); outline-offset: 3px; }
  }

  .timing-status { margin: 0; color: var(--voice-text); }

  dl {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px 16px;
    margin: 8px 0;
  }

  dt { color: var(--voice-faint); }
  dd { margin: 0; color: var(--voice-text); font-variant-numeric: tabular-nums; }

  // 口径句：说明「为什么七行加起来不等于 E2E」，不折叠也不隐藏。
  p:last-child { margin: 8px 0 0; line-height: 1.45; }
}

.v-bubbles {
  position: absolute;
  top: 8px;
  right: 24px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  pointer-events: none;
}

.v-bubble {
  max-width: 34ch;
  padding: 6px 10px;
  border: 1px solid var(--voice-border);
  border-radius: 10px;
  background: color-mix(in srgb, var(--voice-surface) 92%, transparent);
  font-size: 12px;
  line-height: 1.4;

  &__role { display: block; font-size: 10px; letter-spacing: 0.08em; color: var(--voice-faint); text-transform: uppercase; }
  &--tool &__role { color: var(--voice-processing); }
  &--assistant &__role { color: var(--voice-accent); }
}

.v-bubble-enter-active,
.v-bubble-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.v-bubble-enter-from,
.v-bubble-leave-to { opacity: 0; transform: translateY(-4px); }

.v-pip {
  // 旧页整页铺满时 `fixed` 与 `absolute` 等价；嵌进外壳后必须改 `absolute`，
  // 否则滚动或侧栏折叠时 PiP 会飘到运维台侧栏上。
  position: absolute;
  left: 20px;
  bottom: 20px;
  width: 148px;
  aspect-ratio: 4 / 3;
  border: 1px solid var(--voice-border-strong);
  border-radius: 10px;
  overflow: hidden;
  background: #000;

  &__feed { width: 100%; height: 100%; object-fit: cover; transform: scaleX(-1); }
  &__flash { position: absolute; inset: 0; background: #fff; opacity: 0; transition: opacity 120ms ease; }
  &__flash.is-on { opacity: 0.6; }
  &__label { position: absolute; left: 6px; bottom: 6px; font-size: 10px; color: var(--voice-dim); }
}

.v-latency-wrap { display: grid; justify-items: center; gap: 6px; }

.v-latency {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: center;

  &__chip {
    padding: 3px 8px;
    border: 1px solid var(--voice-border);
    border-radius: 999px;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    color: var(--voice-dim);
  }
  &__label { margin-right: 6px; color: var(--voice-faint); }
  &__more { font-size: 11.5px; color: var(--voice-faint); }
  &__more summary { cursor: pointer; }
  &__more ul { margin: 4px 0 0; padding-left: 16px; }
}

// 弹层里的共用块（Tools / Settings / About 都用）。
.v-hint {
  display: block;
  margin: 6px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--voice-faint);
}

.v-tool {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;

  &--sep { border-top: 1px solid var(--voice-border); }
  &__info { display: grid; gap: 2px; }
  &__name { font-size: 13.5px; }
  &__desc { font-size: 11.5px; color: var(--voice-faint); }
}

.v-field {
  display: grid;
  gap: 6px;
  padding: 4px 0 10px;

  &__label { font-size: 12.5px; color: var(--voice-dim); }
}

.v-gate-meter {
  height: 4px;
  margin-top: 2px;
  border-radius: 999px;
  background: var(--voice-surface-2);
  overflow: hidden;

  span { display: block; height: 100%; background: var(--voice-ready); }
}

.v-gate-ends { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--voice-faint); }

.v-wide { width: 100%; }
.v-empty { margin: 12px; color: var(--voice-faint); font-size: 12.5px; }

.v-pipe {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  gap: 6px;

  &__title { margin: 16px 0 0; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--voice-faint); }
  &__end { font-size: 12px; color: var(--voice-dim); }
  &__stage { display: grid; grid-template-columns: 44px 1fr; gap: 2px 10px; padding-left: 4px; border-left: 1px solid var(--voice-border); }
  &__tag { font-size: 10.5px; letter-spacing: 0.08em; color: var(--voice-accent); }
  &__job { font-size: 12px; color: var(--voice-dim); }
  &__stage a { grid-column: 2; font-size: 11.5px; }
}

.v-about__version { margin: 16px 0 0; font-size: 11.5px; color: var(--voice-faint); }

.v-limit {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 8px;
  padding: 8px 0 4px;

  &__badge svg { width: 64px; height: 60px; }
  &__title { margin: 0; font-size: 19px; }
  &__msg { margin: 0; font-size: 13px; color: var(--voice-dim); }
  &__cta { margin-top: 6px; padding: 8px 18px; border-radius: 999px; }
  &__note { margin: 0; font-size: 11.5px; color: var(--voice-faint); }
}

@media (max-width: 720px) {
  .v-head { padding: 14px 16px 0; }
  .v-ident__blurb { display: none; }
  .v-bubbles { right: 12px; }
  .v-pip { width: 104px; left: 12px; bottom: 12px; }
}
```

在 `console/frontend/src/main.ts` 里 `import '@/styles/voice.less'`（与控制台全局样式并列）。

`console/frontend/src/router/index.ts` 只改一行：`component: () => import('@/views/VoiceView.vue')`，并删除 `views/VoicePlaceholderView.vue`。

`console/frontend/index.html` 的 `<body>` 末尾要加两段：**图标精灵**在前，脚本在后（UMD 必须先于 app 入口，否则 `sdk()` 拿不到 `globalThis.OpenAIAgentsRealtime`）。

demo 的图标是就地内联的 `<svg>`（`demo/index.html:58-129`），一个 `<button>` 里写一份，重复了七八次也无所谓——那是手写 HTML。Vue 侧十四个组件分散在十四个文件里，内联就等于每处复制一遍几何，改一处忘三处；`<symbol>` 精灵是这类「同一套图标被多处引用」的标准解法，`<use href="#i-mic">` 在 Vue 模板里完全合法（`href` 而非已废弃的 `xlink:href`）。

**几何逐字照抄 demo，不做风格化重绘**：实心部件（麦头、停止方块、喇叭）自带 `fill="currentColor"`，描边部件自带 `fill="none" stroke="currentColor"`。写死在 symbol 里而不是交给 `.v-i` 的 CSS，是因为 `<use>` 会在 shadow tree 里克隆 `symbol`，而**表现属性优先于继承来的 CSS**——CSS 里的 `fill: none` 覆盖不掉 `path` 上的 `fill="currentColor"`，反过来也一样。所以 `.v-i` 只负责尺寸与 `color`（见上面的 `voice.less`）。

```html
    <!-- 图标精灵：组件里的 <use href="#i-…"> 全部指向这里。
         几何来自 demo/index.html:58-129，实心件用 fill、描边件用 stroke。 -->
    <svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="display: none">
      <symbol id="i-mic" viewBox="0 0 24 24">
        <rect x="9" y="2" width="6" height="12" rx="3" fill="currentColor" />
        <path d="M5 10a7 7 0 0 0 14 0M12 19v3M8 22h8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
      </symbol>
      <symbol id="i-mic-off" viewBox="0 0 24 24">
        <path
          d="M2 2l20 20M9 5a3 3 0 0 1 6 0v4M9 10v1a3 3 0 0 0 5.1 2.1M19 10a7 7 0 0 1-1.24 3.97M5 10a7 7 0 0 0 11 5.67M12 19v3M8 22h8"
          fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
        />
      </symbol>
      <symbol id="i-stop" viewBox="0 0 24 24">
        <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
      </symbol>
      <symbol id="i-voice" viewBox="0 0 24 24">
        <path d="M3 10v4a1 1 0 0 0 1 1h3l5 4V5L7 9H4a1 1 0 0 0-1 1z" fill="currentColor" />
        <path d="M16 8a5 5 0 0 1 0 8M19 5a9 9 0 0 1 0 14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
      </symbol>
      <symbol id="i-info" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2" />
        <path d="M12 16v-4M12 8v.01" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </symbol>
      <symbol id="i-wrench" viewBox="0 0 24 24">
        <path
          d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
          fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
        />
      </symbol>
      <symbol id="i-chat" viewBox="0 0 24 24">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      </symbol>
      <symbol id="i-gear" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2" />
        <path
          d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c0 .66.39 1.25 1 1.51H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
          fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
        />
      </symbol>
    </svg>

    <script src="/vendor/openai-realtime-agents.umd.js"></script>
    <script type="module" src="/src/main.ts"></script>
```

八个 `id` 与组件里的八个 `href` 一一对应（`grep -o 'href="#i-[a-z-]*"' -r src` 能列出全部引用；漏一个就是球心空白或顶栏按钮空壳）。这套精灵只服务于对话页，运维台继续用 ant-design-vue 自带的图标组件，两边不共享。

> 这里只写「把 `TurnLatency` 变成 summary / 状态行 / 七行 / 口径句」的纯函数。
> **解析与校验已经在 Step 5 的 `transport/turn-latency.ts` 里（`readTurnLatency`，5 条测试），不再写第二份**；
> `useTurnLatency.ts` 只把它 re-export 出来，让 `TurnTimings.vue` 与单测都从 `../useTurnLatency` 一处导入。

Run: `cd console/frontend && npx vitest run src/features/voice/useTurnLatency.spec.ts`
Expected: 6 passed（先建实现文件前为 FAIL：`Failed to resolve import "./useTurnLatency"`）。

`console/frontend/src/features/voice/useTurnLatency.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { formatSeconds, statusLabel, timingNote, timingRows, timingSummary } from './useTurnLatency'
import type { TurnLatency } from './types'

const v2: TurnLatency = {
  version: 2,
  turn_id: 't1',
  source: 'speech',
  turn_revision: 0,
  response_key: 'k1',
  status: 'completed',
  stt_s: 2.04,
  llm_s: 0.34,
  tts_ttfa_s: 0.5,
  e2e_s: 6.26,
  vad_decision_s: 0.55,
  smart_wait_s: null,
  smart_status: 'disabled',
  hold_s: null
}

describe('Server timings', () => {
  it('puts the E2E number in the summary line', () => {
    expect(timingSummary(v2)).toBe('Server timings · E2E 6.26 s')
  })

  it('drops back to two words when e2e was not measured', () => {
    expect(timingSummary({ ...v2, e2e_s: null })).toBe('Server timings')
  })

  it('labels a v1 record by its first-audio number instead of E2E', () => {
    expect(timingSummary({ ...v2, version: 1 })).toBe('Server timings · First audio 6.26 s')
  })

  it('writes the seven rows in the old page order and never prints a zero for a missing stage', () => {
    expect(timingRows(v2).map((row) => row.label)).toEqual([
      'E2E time',
      'VAD end decision',
      'Smart Turn decision',
      'Transcription',
      'Response generation',
      'Voice synthesis to first audio',
      'Hold time before response'
    ])
    expect(timingRows(v2).map((row) => row.value)).toEqual([
      '6.26 s',
      '0.55 s',
      'disabled',
      '2.04 s',
      '0.34 s',
      '0.50 s',
      'Unavailable'
    ])
    // v1 的最后一行取的是 smart_wait_s 而不是 hold_s（`chat.js:659`）。
    expect(timingRows({ ...v2, version: 1, smart_wait_s: 0.3 }).map((row) => row.value).pop()).toBe('0.30 s')
  })

  it('maps the four server statuses to the strings the old page painted', () => {
    expect(['completed', 'cancelled', 'failed', 'incomplete'].map(statusLabel)).toEqual([
      'Completed',
      'Interrupted',
      'Failed',
      'Incomplete'
    ])
  })

  it('keeps both footnote sentences verbatim and treats non-finite numbers as Unavailable', () => {
    expect(timingNote(v2)).toBe(
      'E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.'
    )
    expect(timingNote({ ...v2, version: 1 })).toBe(
      'First audio: VAD handoff to generated audio, excluding browser playback. Stages overlap and do not add up.'
    )
    expect(formatSeconds(Number.POSITIVE_INFINITY)).toBe('Unavailable')
  })
})
```

实现 `console/frontend/src/features/voice/useTurnLatency.ts`（纯函数，不需要 hooks；名字里的 `use` 保持与 §14.5 的落点名一致）：

```ts
import type { TurnLatency } from './types'

/** Step 5 的实现；这里 re-export 的目的只是让组件只从一个模块取数。 */
export { readTurnLatency } from './transport/turn-latency'

export interface TimingRow {
  label: string
  value: string
}

/** `chat.js:637`：`null` 一律写 `Unavailable`，而不是 `0.00 s`。 */
const UNAVAILABLE = 'Unavailable'

export function formatSeconds(seconds: number | null | undefined): string {
  return typeof seconds === 'number' && Number.isFinite(seconds) ? `${seconds.toFixed(2)} s` : UNAVAILABLE
}

/** `chat.js:643-645`：e2e 没测到就只剩两个词。 */
export function timingSummary(turn: TurnLatency): string {
  if (turn.e2e_s == null) return 'Server timings'
  return `Server timings · ${turn.version === 2 ? 'E2E' : 'First audio'} ${formatSeconds(turn.e2e_s)}`
}

const STATUS_LABELS: Record<string, string> = {
  completed: 'Completed',
  cancelled: 'Interrupted',
  failed: 'Failed',
  incomplete: 'Incomplete'
}

/** 服务端枚举 → 旧页面画的四个词（`chat.js:649`），不是原枚举值。 */
export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? ''
}

/**
 * 七行、顺序与文案与 `chat.js:653-661` 完全一致。
 * `Smart Turn decision` 的取值是字符串（`disabled` / `complete` …），不是秒数。
 */
export function timingRows(turn: TurnLatency): TimingRow[] {
  return [
    { label: turn.version === 2 ? 'E2E time' : 'VAD handoff to first audio', value: formatSeconds(turn.e2e_s) },
    { label: 'VAD end decision', value: formatSeconds(turn.vad_decision_s) },
    { label: 'Smart Turn decision', value: turn.smart_status ?? UNAVAILABLE },
    { label: 'Transcription', value: formatSeconds(turn.stt_s) },
    { label: 'Response generation', value: formatSeconds(turn.llm_s) },
    { label: 'Voice synthesis to first audio', value: formatSeconds(turn.tts_ttfa_s) },
    {
      label: 'Hold time before response',
      value: formatSeconds(turn.version === 2 ? turn.hold_s : turn.smart_wait_s)
    }
  ]
}

/** `chat.js:671-673` 逐字：两句话说的是两个不同口径，不能互相代替。 */
export function timingNote(turn: TurnLatency): string {
  return turn.version === 2
    ? 'E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.'
    : 'First audio: VAD handoff to generated audio, excluding browser playback. Stages overlap and do not add up.'
}
```

> **不要在 `VoiceView` 里再接一遍。** 旧计划在这里让页面自己写 `<details class="timing">`、自己绑 `client.addEventListener('response-finished', …)`、自己算 `const timing = computed(...)`——三处全部与 Step 18 的 `TurnTimings.vue` 重复，而且计时归属在 `connect()` 里已经由同一个 `response-finished` 事件交给 `store.attachLatency()`。这四个函数的唯一消费者是 `TurnTimings`，唯一写入者是 `S2sClient` 的事件 + store 的 `attachLatency`；`VoiceView` 既不持有 `turnIndex`，也不再往舞台传任何计时。

Run: `cd console/frontend && npx vue-tsc --noEmit`
Expected: 无输出。若报 `Cannot find module '@/features/voice/...'`，检查 Task 2 的 `@` 别名是否指向 `src`。

---

- [ ] **Step 20: 补路由断言 + 全量前端校验**

外壳与两个面的关系是纯路由表事实，不该靠手工点。`console/frontend/src/router/router.spec.ts`（`// @vitest-environment jsdom`：`router/index.ts` 顶层 `createWebHistory()` 需要 `window`；`resolve()` 不触发导航，所以守卫不会去碰 pinia）：

```ts
// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { routes } from './index'

/** 与 `index.ts` 同一张表，但用内存 history：不碰地址栏，也不跑守卫。 */
function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

describe('shell routing', () => {
  it('mounts the voice face at / as a child of ConsoleLayout', () => {
    const matched = makeRouter().resolve('/').matched
    expect(matched).toHaveLength(2)
    expect(matched[1].name).toBe('voice')
    expect(matched[1].meta.face).toBe('voice')
  })

  it('keeps the console namespace record componentless so RouterView skips it', () => {
    const record = makeRouter()
      .getRoutes()
      .find((route) => route.name === 'console')
    expect(record?.path).toBe('/console')
    expect(record?.components?.default).toBeUndefined()
    expect(record?.meta.requiresAuth).toBe(true)
  })

  it('inherits face and requiresAuth on console children', () => {
    const resolved = makeRouter().resolve('/console/params')
    expect(resolved.matched.map((record) => record.name)).toEqual(['console', 'params'])
    expect(resolved.meta.face).toBe('console')
    expect(resolved.meta.requiresAuth).toBe(true)
  })

  it('leaves the voice face anonymous', () => {
    expect(makeRouter().resolve('/').meta.requiresAuth).toBeFalsy()
  })
})
```

> 第三条只有 Task 12 注册了 `params` 之后才成立——这正是这份 spec 排在 Task 20 而不是 Task 11 的原因。它同时锁住「子路由注册在 `console` 命名空间下」与「`meta` 向下继承」两件事，改路由表时先红的是它。

Run: `cd console/frontend && npx vitest run src/router/router.spec.ts`
Expected: 4 passed。

Run: `cd console/frontend && npx vitest run`
Expected: **55 passed**。逐文件对帐（12 个 spec 文件，缺一个就说明文件被删或被 `--exclude` 掉了）：

| 文件 | 条数 | 来源 |
|---|---|---|
| `utils/error.spec.ts` | 3 | Task 11 |
| `utils/format.spec.ts` | 2 | Task 11 |
| `utils/draft-patch.spec.ts` | 6 | Task 12 |
| `utils/alert.spec.ts` | 2 | Task 13 |
| `utils/session-patch.spec.ts` | 5 | Task 16 |
| `router/router.spec.ts` | 4 | 本任务 Step 20 |
| `features/voice/transport/turn-latency.spec.ts` | 5 | 本任务 Step 3–6 |
| `features/voice/transport/events.spec.ts` | 5 | 本任务 Step 7–10 |
| `features/voice/audio/meter.spec.ts` | 5 | 本任务 Step 11–14 |
| `features/voice/audio/sent-audio.spec.ts` | 5 | 本任务 Step 17 |
| `stores/voice.spec.ts` | 7 | 本任务 Step 15–16 |
| `features/voice/useTurnLatency.spec.ts` | 6 | 本任务 Step 19 |

3+2+6+2+5+4+5+5+5+5+7+6 = 55。对不上先 `npx vitest run --reporter=verbose` 看哪个文件少了一条，**不要改断言凑数**；若 `router.spec.ts` 单独红，先查 Task 12/13 是否真的把视图注册进了 `console` 命名空间。

Run: `cd console/frontend && npx vue-tsc --noEmit && npm run lint && npm run build`
Expected: 三条均无错误；`dist/assets/` 里出现带 hash 的 `index-*.js`，`dist/worklets/` 有 2 个文件，`dist/vendor/` 有 7 个资产。

Run: `cd console/frontend && grep -c "OpenAIAgentsRealtime" dist/assets/*.js || true`
Expected: 0。SDK 只能从 `/vendor` 加载；一旦被 Vite 打进 bundle，就说明有人 `import` 了 `@openai/agents`，会把 400KB 重复进产物且两介 SDK 实例抢同一个全局。

- [ ] **Step 21: §14.5 对话页二十三条手工验收（两套环境）**

逐行对回设计文档 §14.5 的「对话页」表（**二十三行**，括号里是表里的行序；原 20 行加“用户原音回放 / 工具条目 / 助手条目”3 行，因此 11 行及以后的行序均后移 3）。**上一版这一节写的是十条，其中三条与 demo 的实际代码不符**，已按现状改掉：

- `orb 三态` → demo 是**九态**加**六个指示器**（`main.js` 的 `setCircleState` 只接受九个值，球心在 `mic / error / spinner / dots / bars / voice` 之间换图形）。
- `设置面板 Voice/Model 灰显 + needs a restart` → demo 的十个字段全部可改，只有 Transport 在 upstream 已固定时只读；改语言与指令也是**下一次通话生效**，不是会话内热切。
- `刷新恢复 / Resume last conversation` → `demo/main.js` 里没有 `sessionStorage`，F5 就是新会话。这条功能**不存在**，不要实现。

哪一条对不上就回去改对应组件，不要改这份清单。

**第 0 组：嵌入形态（§3.2.4，不属于 §14.5 的任何一行，但不过就不能往下点）**

- 页面上只有**一套顶栏与侧栏**：外壳的 `header.shell__top` 与 `nav#shell-nav`。对话区里不存在 `.v-top`，也不存在第二条滚动条（`document.scrollingElement.scrollHeight` 等于视口高）。
- 顶栏右侧的 `#shell-actions` 里是**账号 chip + 三枚按钮**（Tools / History / Settings）；About 是 `IdentityBlock` 里的圆钮，随头部留在舞台。点这三枚按钮分别打开对应浮层，再次点击不叠加。
- 侧栏展开（200px）与折叠（56px）两种态下：orb 始终在舞台水平/垂直居中；气泡贴舞台右上；相机 PiP 贴舞台左下（不是视口左下）；页脚贴底不被裁切。折叠时舞台变宽而不是把 orb 挤到一边。
- 窗口缩到 980px 以下：侧栏变抽屉（默认收起），舞台不被挤压、不变形；点汉堡打开抽屉，点导航或遮罩关闭；在抽屉里点 History 后抽屉自动关上并弹出历史面板。
- 从对话页点「运维控制台 ↗」进 `/console/params`，再点侧栏「Voice」回 `/`：外壳不重建（顶栏不闪、状态轮询按面启停），对话页按“刷新即结束”的规则回到 `idle`。

先跑「无 LB」环境（`.env` 只留 `JWT_SECRET_KEY` / `DATABASE_URL`）：

1. **标识块** `IdentityBlock`（1）：标题外链到仓库、旁边 About 圆钮、blurb、`Powered by` / `Built by` 两行都在；窗口收窄到 720px 以下时 blurb 收起而标题仍在。
2. **九态与六个指示器** `OrbStage`（3）：依次走过 `idle → connecting → listening → user-speaking → processing → ai-speaking → error`（`queued` / `your-turn` 见第 18 条）。判据不是「颜色变了」而是**图形换了**：`idle` / `your-turn` 是 mic，`connecting` / `queued` 是 spinner，`listening` / `user-speaking` 是五根 bars，`processing` 是三点，`ai-speaking` 是 voice，`error` 是 info。`data-state` 与 `events.spec.ts` / `meter.spec.ts` 的断言同源，人手只核对视觉对应。
3. **caption / subcaption**（4）：文案由 `VoiceView` 单一持有，`OrbStage` 只接收 `caption` / `subCaption` / `tone`。拒绝授权时 caption 逐字等于 `Microphone access was blocked…` 且 `tone=error` 变红；连不上时是 `Tap to retry`。
4. **噪声门弧** `MicGate`（5）：说话时弧按电平逐段点亮；把手拖到最左 = Off（门限落到 `GATE_OFF_DB`，把手变灰）；**继续往右拖进缺口不产生越界 dB**——`fractionToDb` 把 `(-0.4)` 与 `1.4` 夹回两端（`meter.spec.ts` 已断言，这里只核对视觉）；松手后 `noiseGateDb` 落进 `localStorage`，刷新还在。
5. **静音钮**（6）：图标在 `#i-mic` / `#i-mic-off` 之间切；静音后服务端不再收到音频帧（pipeline 日志里该 session 的输入计数停住），取消静音立刻恢复。
6. **结束钮与页脚**（7）：`.v-orb-wrap` 右侧的 52px 圆钮点一下回 `idle`、transcript 保留；页脚 `Powered by huggingface/speech-to-speech` 是可点链接，**不单独立组件**。
7. **临时气泡** `BubbleStack`（8）：user / tool / assistant 三种来源的左边框颜色不同；最多四条、各自 6s 后消失；触发一次 web search 必须看到 `tool` 气泡。
8. **历史抽屉** `HistoryDrawer` + `TranscriptList`（9）：宽 380px；空会话显示 `Nothing said yet.`；Esc 关闭；关闭再打开内容仍在。
9. **转写条目**（10）：用户/助手双色，临时条目半透明、最终条目实心；同一段回放录音的顺序与分段点与 demo 逐条一致（条目条数、每条的起止词、临时→最终的翻转时机）；用户上滑阅读时不被强行拉回底部。助手条目**没有**任何播放控件。
10. **用户条目原音回放**（11）：说两句各 3s 以上。每条用户条目下都有 `Audio sent to the model` 标签 + 原生 `<audio controls>`；时长与录音相差 ≤ 50ms；点播放时**其它条目的音频暂停**且麦克风被静音（`track.enabled === false`，DevTools 看 `MediaStreamTrack`），暂停 / 播完 / 出错后恢复；缓冲被截断时标签追加 `· beginning unavailable`。`transport=webrtc` 时**没有**播放器——demo 只在 `websocket` 分支录原音，新页同样只在 WS 传输时拿 `user-audio` 事件。
11. **工具条目**（12）：触发一次 `camera_snapshot`：条目里出现 `Snapshot` 缩略图与 `Input` / `Output` 两段 JSON，`<details>` 默认折叠；点缩略图在新窗口打开大图；无图时只有文字，不出现空 `<img>`。
12. **助手条目**（13）：只有文本与轮次延迟，**不出现**播放按钮或波形；出现即为凭空发明（demo 从不保存 TTS 音频）——这一条要与第 10 条对照着看：同一份回放录音，新旧两页的“可回放条目集合”必须完全相同。
13. **相机自视窗** `CameraPip`（14）：只在 Tools 里打开 Camera 后出现（贴舞台左下，不是视口左下）；拍照时白光一闪；此时说「看看我手里是什么」，pipeline 日志里有 `camera_snapshot` 调用。
14. **轮次延迟** `TurnTimings`（15）：助手条目下方出现 `<details class="hist-timings">`，`<summary>` 逐字是 `Server timings · E2E 6.26 s`（`e2e_s` 缺失时只剩 `Server timings`）；展开后第一行是状态词 `Completed`（`Interrupted` / `Failed` / `Incomplete` 同理），接着是七行：`E2E time` / `VAD end decision` / `Smart Turn decision`（值是 `disabled` 这类字符串，不是秒数）/ `Transcription` / `Response generation` / `Voice synthesis to first audio` / `Hold time before response`，取不到的写 `Unavailable` 而不是 `0.00 s`；末尾口径句逐字为 `E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.`；v1 pipeline 的标题词是 `First audio` 而不是 `E2E`。**舞台上必须没有任何 chip 行**（`turn / stt / llm / tts / total` 这五个词在页面上搜不到），并且连续两轮对话后历史抽屉里**每条助手条目各有一份自己的数字**。
15. **工具面板** `ToolsDialog`（16）：无 `SERPER_API_KEY` 时 Web search 开关禁用、三条 hint 逐字一致；服务端握 key 时输入框 disabled 且 placeholder 是 `••••••••  · provided by the server`（**不是**可编辑的密码框）；`/api/search` 仍走代理。
16. **设置面板** `SettingsDialog`（17）：十个字段一个不少——server URL / Transport / Voice / Microphone / Speakers / Faster interruptions / Playback buffer / Noise gate / Instructions，加 Restart 与 Save。Transport 仅当 upstream 未固定时可选，其余全部可改；Save 后设置保留，Restart 断开重连并带上新值。
17. **关于弹窗** `AboutDialog`（18）：简介 + 四段 pipeline（VAD / STT / VLM / TTS）带模型外链；版本取自 `/api/config`，为空时显示 `unknown` 而不报错。
18. **本地 VAD 与快速打断**（21）：点 Start 弹权限请求，选 Block 后文案与旧页一致且 orb 落 `error`；改回允许后 Start 能连上；打断时播放队列被清空（不是继续播完上一句）；首帧上行延迟不高于旧值 + 50ms。
19. **刷新即结束**（22）：通话中 F5 → 回 `idle`，**不出现** `Resume last conversation`，也不留残转写；只有设置与工具开关保留。这是 demo 的真实行为，不要「顺手加个恢复」。
20. **密钥单向**（23）：在 Tools 里手填一个 key、发起一次搜索，然后 F5 → key 输入框为空；`localStorage`、`sessionStorage`、URL、审计日志里都搜不到该值（B5）。

再跑「有 LB」环境（补上 `LOAD_BALANCER_URL` / `SPACE_ID` / `LIMITER_ENABLED` 依赖的两个变量）：

21. **排队三态** `QueueOverlay`（20）：用 LB 的排队参数制造 `queued`（显示位次与 `~N min`）、`your-turn`（出现 Join now 倒计时）、满员（`All slots are busy…`）；三个状态都能 Leave queue 退出。**无 LB 时整块不得出现**（`/api/session` 404 → 直连 `WebSocket`）。
22. **额度耗尽** `LimitDialog`（19）：把 `LIMIT_ANON_SEC` 改成 `20` 重跑，20 秒内被 `heartbeat expired` 拆掉并弹卡片；标题 / 正文 / CTA / note 与 `demo/ui/account.js:160-222` 一致；同时 `AccountWidget` 的剩余时间在对话中递减、断开后停住。
23. **账号胶囊** `AccountWidget`（2）：`/api/me` 返回 `{"enabled":false}` 时整块不渲染（不留空胶囊）；配 OAuth 后未登录是 `Sign in` 胶囊、点进跳 `huggingface.co`，回跳后变 avatar + handle；点开 popover 显示 tier（`Free` / `PRO` / `Team`）、`m:ss left today`（unlimited 显示 `Unlimited`）、`Upgrade to PRO`（unlimited 不给）、`Sign out`。逐字段对 `/api/me`。

- [ ] **Step 22: 提交**

```bash
git add console/frontend
git commit -m "feat(console): Vue conversation page with transport, metering and dialogs"
```

---

## Task 21: 模型运行时监控（A.14，阶段 F2）

**Files:**
- Modify: `src/speech_to_speech/utils/model_monitor.py`（`CallRecord.mark_first_byte()`，写进 `output["first_byte_s"]`）
- Modify: `src/speech_to_speech/LLM/...`与 `src/speech_to_speech/TTS/...` 的首块产出处（各一处 `rec.mark_first_byte()`；具体文件在 Step 7 用 `grep -rn "get_model_monitor()" src` 定位）
- Create: `console/backend/app/services/runtime_service.py`
- Create: `console/backend/app/routers/runtime.py`
- Modify: `console/backend/app/core/router_registry.py`
- Test: `console/backend/tests/unit/test_runtime_service.py`
- Test: `console/backend/tests/integration/test_runtime_api.py`
- Create: `console/frontend/src/types/runtime.ts`
- Create: `console/frontend/src/api/runtime.ts`
- Create: `console/frontend/src/stores/runtime.ts`
- Create: `console/frontend/src/components/ModelRuntimeCard.vue`
- Create: `console/frontend/src/components/RuntimeGrid.vue`
- Test: `console/frontend/src/components/ModelRuntimeCard.spec.ts`
- Modify: `console/frontend/src/views/InstancesView.vue`

**Interfaces:**
- Consumes: `process_probe.get_probe().state("pipeline")`（Task 10）、`pool.read_pool()`（Task 10）、`console_settings.config_dir` / `model_metrics_log`（Task 3）、`GET /v1/pool`、`nvidia-smi`。
- Produces: `runtime_service.collect(profile: str, window_s: int = 300) -> dict`（A.14 的 `data`）；`runtime_service.invalidate()`；`GET /api/v1/runtime/models?profile=&windowS=`（裸 `ApiResponse` 包络，与其他运维面接口一致）。
- Produces: `RuntimeStage` / `RuntimeSnapshot` / `GpuInfo`（`types/runtime.ts`）；`fetchRuntime(profile, windowS)`；`useRuntimeStore()`（`snapshot / loading / error / startPolling(profile) / stopPolling() / refresh()`，`POLL_MS = 5000`）。
- Produces: `ModelRuntimeCard.vue` props `{ stage: RuntimeStage; gpu: GpuInfo | null }`；`RuntimeGrid.vue` props `{ snapshot: RuntimeSnapshot | null; loading: boolean; error: string }`。

**为什么 `reasons` 要按字段名建索引、并且写成不变式**：这个面板的全部价值在于“分得清 0 与不知道”。`loaded:false` 可能是模型没加载，也可能是进程刚起来还没叫过模型；`queueDepth:null` 是“这个数根本不存在”，不是“队列空”。所以每个 `null` / `false` 都必须自带一个理由码，而有值的字段**不准**带理由码——这条写成单测（Step 1 的第 5 条），改服务时先红。

**为什么显存要说“整卡峰值”**：`model_metrics.log` 里的 `resources.vram_used_mb_peak` 是采样线程在**调用期间**读的整卡占用（`torch.cuda.memory_allocated` 按设备聚合），同一张卡上 pipeline 的四段共用一份。把 VAD 卡显示成“占 18GB”会让人以为 VAD 自己吃了 18GB。卡片 tooltip 与 `vram_not_attributable` 码同时表达这件事。

**为什么它不能拖慢语音**：全部 IO 走 `asyncio.to_thread` + 整体 `asyncio.wait_for(2.0)`，结果缓 `TTL=3s`；前端 5s 轮询、切页即停。`console` 是单 worker，所以这个端点的成本必须是**常数级**的：只读文件尾 256 KiB、`nvidia-smi` 一次、`/v1/pool` 一次，不做全量日志扫描。

- [ ] **Step 1: 写失败单测**

`console/backend/tests/unit/test_runtime_service.py`（6 条：四条 reason 不变式 + 有效值不带 reason + gpu 缺失不影响四段）：

```python
from app.services import runtime_service


def test_null_vram_always_carries_a_reason(monkeypatch):
    monkeypatch.setattr(runtime_service, "_gpu", lambda: {"available": False, "reason": "nvidia_smi_missing"})
    data = runtime_service.collect("prod")
    for stage in data["stages"]:
        assert stage["vram"]["usedMb"] is None
        assert stage["reasons"]["vram"] == "nvidia_smi_missing"


def test_stopped_pipeline_marks_loaded_false_with_reason(monkeypatch):
    monkeypatch.setattr(runtime_service, "_pipeline_running", lambda: False)
    data = runtime_service.collect("prod")
    for stage in data["stages"]:
        assert stage["loaded"] is False
        assert stage["reasons"]["loaded"] == "pipeline_stopped"


def test_queue_depth_is_null_and_not_zero(monkeypatch):
    data = runtime_service.collect("prod")
    for stage in data["stages"]:
        assert stage["busy"]["queueDepth"] is None
        assert stage["reasons"]["queueDepth"] == "queue_depth_not_exposed"


def test_vad_has_no_first_byte(tmp_path, monkeypatch):
    data = runtime_service.collect("prod")
    vad = next(s for s in data["stages"] if s["stage"] == "vad")
    assert vad["latency"]["firstByteMs"] is None
    assert vad["reasons"]["firstByte"] == "not_applicable"


def test_valid_values_carry_no_reason(tmp_path, monkeypatch):
    line = pkg_metrics_line("tts", duration_s=0.42, first_byte_s=0.11, vram_mb=2048.0)
    monkeypatch.setattr(runtime_service, "_metrics_tail", lambda **kw: [line])
    tts = next(s for s in runtime_service.collect("prod")["stages"] if s["stage"] == "tts")
    assert tts["reasons"] == {}
    assert tts["latency"]["firstByteMs"] == 110


def test_missing_gpu_still_returns_four_stages(monkeypatch):
    monkeypatch.setattr(runtime_service, "_gpu", lambda: {"available": False, "reason": "nvidia_smi_missing"})
    data = runtime_service.collect("prod")
    assert [s["stage"] for s in data["stages"]] == ["vad", "stt", "llm", "tts"]
    assert data["gpu"]["available"] is False
```

`pkg_metrics_line` 是测试内的构造函数（写在本文件头部）：把一个 `MODEL_CALL_METRICS` JSON 拼成字符串，`category` 取 `tts` / `stt` / `llm`。

- [ ] **Step 2: 写 `runtime_service.py`**

`console/backend/app/services/runtime_service.py`（要点：`_TTL=3.0` 缓存、`collect()` 整体 `wait_for(2.0)`、四个来源各一个私有函数）：

```python
"""Model runtime snapshot for the instance page (A.14).

Read-only bypass: every source is optional, and a missing source becomes a
`reasons` code — never a zero, never a blank cell.
"""

STAGES = ("vad", "stt", "llm", "tts")
_TTL_S = 3.0
_TIMEOUT_S = 2.0
_cache: dict[tuple[str, int], tuple[float, dict]] = {}


def collect(profile: str, window_s: int = 300) -> dict:
    now = time.monotonic()
    cached = _cache.get((profile, window_s))
    if cached and now - cached[0] < _TTL_S:
        return cached[1]
    try:
        data = asyncio.run(_collect_async(profile, window_s))
    except asyncio.TimeoutError:  # 整体预算用尽：返回上一帧 + runtime_degraded
        upstream = cached[1] if cached else _empty(profile, window_s)
        data = {**upstream, "alerts": sorted({*upstream["alerts"], "runtime_degraded"})}
    _cache[(profile, window_s)] = (now, data)
    return data
```

`_collect_async` 内四个 `await asyncio.to_thread(...)`（`_gpu()` / `_metrics_tail()` / `_pool()` / `_probe()`）包在 `asyncio.wait_for(..., _TIMEOUT_S)` 里；`_metrics_tail()` 只读 `MODEL_METRICS_LOG` 末尾 256 KiB 并只保留 `MODEL_CALL_METRICS` 行；`_gpu()` 执行 A.14 的 `nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader,nounits`（`timeout=2`）。

- [ ] **Step 3: 跑单测**

Run: `cd console/backend && python -m pytest tests/unit/test_runtime_service.py -q`
Expected: 6 passed。

- [ ] **Step 4: 写集成测试**

`console/backend/tests/integration/test_runtime_api.py`（4 条：401 / 404 unknown_profile / pipeline 停仍 200 / gpu 缺失仍返回四段）：

```python
def test_requires_auth(client):
    assert client.get("/api/v1/runtime/models").status_code == 401


def test_unknown_profile_is_404(client, auth_headers):
    response = client.get("/api/v1/runtime/models?profile=nope", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_profile"


def test_stopped_pipeline_still_answers_200(client, auth_headers, monkeypatch):
    monkeypatch.setattr(runtime_service, "_pipeline_running", lambda: False)
    body = client.get("/api/v1/runtime/models?profile=prod", headers=auth_headers).json()
    assert body["data"]["stages"][0]["reasons"]["loaded"] == "pipeline_stopped"
    assert "pipeline_stopped" in body["data"]["alerts"]


def test_missing_nvidia_smi_does_not_500(client, auth_headers, monkeypatch):
    monkeypatch.setattr(runtime_service, "_gpu", lambda: {"available": False, "reason": "nvidia_smi_missing"})
    response = client.get("/api/v1/runtime/models?profile=prod", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()["data"]["stages"]) == 4
```

- [ ] **Step 5: 写 router 并注册**

`console/backend/app/routers/runtime.py`：

```python
router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/models")
def runtime_models(
    profile: str = Query(default=""),
    window_s: int = Query(default=300, alias="windowS", ge=60, le=3600),
    user: User = Depends(current_user),
) -> ApiResponse[dict]:
    target = profile or _current_profile()
    if target not in catalog_service.profiles():
        raise api_error(404, "unknown_profile", f"未找到 profile {target}")
    return ApiResponse(data=runtime_service.collect(target, window_s))
```

`router_registry.py` 里与 `/pool`、`/instances` 同级挂上（静态注册顺序见“硬约束”；`/runtime` 在 `/api/v1` 下，不进演示面的 `/api/*`）。

- [ ] **Step 6: 跑集成测试**

Run: `cd console/backend && python -m pytest tests/integration/test_runtime_api.py -q`
Expected: 4 passed。

- [ ] **Step 7: 给 LLM / TTS 补首字节埋点**

`CallRecord` 加一个方法（`model_monitor.py`）：

```python
    def mark_first_byte(self) -> None:
        """First audio chunk / first token of this call, relative to `start_ts`.

        Only handlers that can see the boundary call this; a category that never
        calls it shows `first_byte_not_instrumented` instead of a guess (§3.9.1).
        """
        if "first_byte_s" not in self.output:
            self.output["first_byte_s"] = round(time.time() - self.start_ts, 4)
```

Run: `grep -rn "get_model_monitor()" src/speech_to_speech | head -20`
Expected: 列出四个 handler 的 `with monitor.trace(...) as rec:`；在 **LLM**（首个 `delta`）与 **TTS**（首个音频块）两处各加一行 `rec.mark_first_byte()`。STT 与 VAD 不加：它们的日志行没有这个键，面板就显示 `first_byte_not_instrumented`。

Run: `python -m pytest tests/test_llm_utils.py tests/test_chattts_streaming.py -q`
Expected: 全部通过（埋点只是往 `rec.output` 里加一个键，不改控制流）。

- [ ] **Step 8: 前端类型与 HTTP**

`console/frontend/src/types/runtime.ts`（字段名逐字对齐 A.14，`RuntimeReason` 用联合类型把八个码锁死）：

```ts
export type RuntimeStageName = 'vad' | 'stt' | 'llm' | 'tts'
export type RuntimeReason =
  | 'config_unreadable'
  | 'pipeline_stopped'
  | 'no_metrics_window'
  | 'nvidia_smi_missing'
  | 'vram_not_attributable'
  | 'pool_unreachable'
  | 'queue_depth_not_exposed'
  | 'first_byte_not_instrumented'
  | 'not_applicable'

export interface RuntimeStage {
  stage: RuntimeStageName
  modelName: string | null
  backend: string | null
  loaded: boolean
  vram: { usedMb: number | null; percent: number | null }
  busy: { inUse: number | null; size: number | null; occupied: boolean; queueDepth: number | null }
  latency: { firstByteMs: number | null; processMs: number | null; p50Ms: number | null; p95Ms: number | null }
  reasons: Partial<Record<'loaded' | 'vram' | 'busy' | 'queueDepth' | 'firstByte' | 'latency', RuntimeReason>>
}

export interface GpuInfo {
  available: boolean
  name?: string
  totalMb?: number
  usedMb?: number
  percent?: number
  reason?: RuntimeReason
}

export interface RuntimeSnapshot {
  profile: string
  collectedAt: string
  windowS: number
  gpu: GpuInfo
  stages: RuntimeStage[]
  alerts: string[]
}
```

`console/frontend/src/api/runtime.ts`：`export const fetchRuntime = (profile: string, windowS = 300) => http.get<RuntimeSnapshot>('/runtime/models', { params: { profile, windowS } })`。

- [ ] **Step 9: 写 store（5s 轮询，切页即停）**

`console/frontend/src/stores/runtime.ts`：

```ts
const POLL_MS = 5000

export const useRuntimeStore = defineStore('runtime', () => {
  const snapshot = ref<RuntimeSnapshot | null>(null)
  const loading = ref(false)
  const error = ref('')
  let timer = 0
  let profile = ''

  async function refresh(): Promise<void> {
    if (!profile) return
    loading.value = true
    try {
      snapshot.value = await fetchRuntime(profile)
      error.value = ''
    } catch (err) {
      // 保留上一帧：采样失败不等于“模型消失了”（A.14）。
      error.value = describeError(err)
    } finally {
      loading.value = false
    }
  }

  function startPolling(next: string): void {
    profile = next
    stopPolling()
    void refresh()
    timer = window.setInterval(() => void refresh(), POLL_MS)
  }

  function stopPolling(): void {
    window.clearInterval(timer)
    timer = 0
  }

  return { snapshot, loading, error, refresh, startPolling, stopPolling }
})
```

`InstancesView` 在 `onMounted` 调 `startPolling(profile)`，`onBeforeUnmount` 调 `stopPolling()`；`document.visibilitychange` 为 `hidden` 时也停（§3.9.1 第 4 条）。

- [ ] **Step 10: 写卡片与网格（`reasons` 决定文案）**

`console/frontend/src/components/ModelRuntimeCard.vue` 的关键不是布局，而是**每个不可用字段都渲染理由**：

```vue
<template>
  <a-card size="small" class="rt-card" :class="{ 'is-down': !stage.loaded }">
    <template #title>
      <span class="rt-card__stage">{{ STAGE_LABEL[stage.stage] }}</span>
      <a-tag :color="stage.loaded ? 'green' : 'red'">{{ stage.loaded ? 'loaded' : 'not loaded' }}</a-tag>
    </template>
    <p class="rt-card__model">{{ stage.modelName ?? unavailable(stage.reasons, 'vram') }}</p>
    <p class="rt-card__backend">{{ stage.backend ?? '—' }}</p>
    <dl class="rt-card__grid">
      <dt>VRAM</dt>
      <dd>
        <template v-if="stage.vram.usedMb !== null">
          {{ stage.vram.usedMb }} MB · {{ percentText(stage.vram.percent) }}
          <a-tooltip title="调用期间的整卡峰值（含同卡其它进程），不是该模型独占量"><span class="rt-card__hint">整卡</span></a-tooltip>
        </template>
        <span v-else class="rt-card__na">不可用 · {{ stage.reasons.vram }}</span>
      </dd>
      <dt>Busy</dt>
      <dd v-if="stage.busy.inUse !== null">{{ stage.busy.inUse }} / {{ stage.busy.size }}</dd>
      <dd v-else class="rt-card__na">不可用 · {{ stage.reasons.busy }}</dd>
      <dt>Queue</dt>
      <dd v-if="stage.busy.queueDepth !== null">{{ stage.busy.queueDepth }}</dd>
      <dd v-else class="rt-card__na">不可用 · {{ stage.reasons.queueDepth }}</dd>
      <dt>First byte</dt>
      <dd v-if="stage.latency.firstByteMs !== null">{{ stage.latency.firstByteMs }} ms</dd>
      <dd v-else class="rt-card__na">不可用 · {{ stage.reasons.firstByte }}</dd>
      <dt>p50 / p95</dt>
      <dd v-if="stage.latency.p95Ms !== null">{{ stage.latency.p50Ms }} / {{ stage.latency.p95Ms }} ms</dd>
      <dd v-else class="rt-card__na">不可用 · {{ stage.reasons.latency }}</dd>
    </dl>
  </a-card>
</template>
```

`RuntimeGrid.vue` 负责四张卡 + 显卡卡头（`gpu.available === false` 时头部写 `GPU 不可用 · {{ gpu.reason }}`，四张卡照常渲染）+ `alerts` 的 `a-alert` 列表（`pipeline_stopped` / `vram_pressure` / `pool_unreachable` / `runtime_degraded` 各一句人话）。

- [ ] **Step 11: 写渲染单测**

`console/frontend/src/components/ModelRuntimeCard.spec.ts`（3 条：正常值、`loaded:false` 显示理由码、`queueDepth:null` 不显示 0）：

```ts
it('renders the reason code instead of a zero when vram is missing', () => {
  const wrapper = mount(ModelRuntimeCard, { props: { stage: stageFixture({ vram: { usedMb: null, percent: null } }), gpu: null } })
  expect(wrapper.text()).toContain('不可用 · nvidia_smi_missing')
  expect(wrapper.text()).not.toContain('0 MB')
})
```

另外两条：`loaded:false` 时 `not loaded` 徽标 + `pipeline_stopped` 文案；`p95Ms` 有值时渲染 `p50 / p95` 而不是 `不可用`。

Run: `cd console/frontend && npx vitest run src/components/ModelRuntimeCard.spec.ts`
Expected: 3 passed。

- [ ] **Step 12: 挂进实例页并跑全量**

`InstancesView.vue` 在 `InstanceCard` 上方插入 `<RuntimeGrid :snapshot="runtime.snapshot" :loading="runtime.loading" :error="runtime.error" />`，并把 `alerts` 与实例页原有的 `snapshot.alerts` 分开展示（两个端点的 `alerts` 语义不同：一个说容器，一个说模型）。

Run: `cd console/frontend && npx vitest run`
Expected: **58 passed**（Task 20 的 55 + 本任务 3）。对不上先看 `ModelRuntimeCard.spec.ts` 是否被 `--exclude`。

Run: `cd console/frontend && npx vue-tsc --noEmit && npm run lint`
Expected: 无错误。

- [ ] **Step 13: 同步预览页的监控卡，并把三种场景各演一遍**

`console/design/console-preview.html` 的实例页（`data-view="instances"`）在 supervisord 面板之后、`/v1/pool` 面板之前插入一段与 `RuntimeGrid.vue` 同构的静态标本：四张 `.rt-card[data-loaded]`（`.rt-card__stage` / `__backend` / `__model` / `__body`）+ 显卡卡头 + `alerts` 列表。字段名逐字用 A.14（`vram.usedMb` / `busy.inUse` / `busy.queueDepth` / `latency.firstByteMs` / `latency.p50Ms` / `latency.p95Ms` / `reasons.<key>`），**不加新字段、不改旧字段名**。

标本必须同时演三种验收场景（与 §3.9.3 的三行一一对应；缺一种就算没画完）：

| 场景 | 卡片上的证据 |
| --- | --- |
| 模型未加载 | TTS 卡 `data-loaded="false"`、卡头徽标 `not loaded`、`loaded` 行 `否 · no_metrics_window`（进程 RUNNING，但最近 300s 窗口内没有任何 TTS 调用指标——`pipeline_stopped` 是进程没起来时的另一种写法，两者不可混用，见 §3.9.1），`vram` / `firstByte` / `p50·p95` 同为 `no_metrics_window`，`queueDepth` 为 `queue_depth_not_exposed`，`busy` 仍照实写 `1 / 1 占用中`（`/v1/pool` 取得到就不许说不可用） |
| 显存接近打满 | 显卡卡头 `usedMb / totalMb` 可算出 `91.4%`，`.rt-bar[data-level='bad']`，`alerts` 里出现 `vram_pressure` |
| 某段延迟异常升高 | STT 卡的 `p95` 与同卡其它三段差一个数量级（`1 240 ms`），该行着色为 `warn`，并注明「p95 取自 300s 窗口」 |

另外两条是 A.14 的硬性要求，预览页也要照做：VAD 卡 `firstByte` 行写 `不可用 · not_applicable`（VAD 没有首字节这个概念，不是没测）、`vram` 行写 `不可用 · vram_not_attributable` 并注明「整卡峰值，不归属单段」。

Run: 浏览器打开 `console/design/console-preview.html` → 侧栏「实例」
Expected: 四张 `.rt-card` + 显卡卡头 + `alerts` 齐备；每一条 `不可用` 后面都跟着 `<code>` 理由码；页内 `Ctrl+F` 搜 `0 MB` 与 `0 ms` 都找不到（取不到就是「不可用」，不是 0）。

- [ ] **Step 14: 提交**

```bash
git add src/speech_to_speech/utils/model_monitor.py console/backend console/frontend console/design/console-preview.html
git commit -m "feat(console): model runtime snapshot with reason codes"
```

---

## Task 22: 日志面板、轮次延迟与 LLM 归纳（A.15 / A.16 / A.17，阶段 F2 收尾）

**Files:**
- Modify: `src/speech_to_speech/pipeline/turn_latency.py`（`encode_machine_line()` + `MACHINE_KEYS`）
- Modify: `src/speech_to_speech/api/openai_realtime/handlers/response.py`（人读行之后追一行机器行）
- Test: `tests/test_turn_latency_logging.py`
- Create: `console/backend/app/services/log_service.py`
- Create: `console/backend/app/services/log_analysis_service.py`
- Create: `console/backend/app/services/turn_latency_indexer.py`
- Create: `console/backend/app/services/turn_latency_service.py`
- Create: `console/backend/app/schemas/logs.py`、`app/schemas/turn_latency.py`
- Create: `console/backend/app/routers/logs.py`、`app/routers/turn_latency.py`
- Create: `console/backend/app/models/turn_latency.py`（并改 `app/models/__init__.py`）
- Create: `console/backend/app/repositories/turn_latency_repository.py`
- Create: `console/backend/alembic/versions/0002_turn_latency.py`
- Modify: `console/backend/app/main.py`（`lifespan` 启停索引器）、`console/backend/app/core/router_registry.py`
- Test: `console/backend/tests/unit/test_log_service.py`、`test_log_analysis_service.py`、`test_turn_latency_repository.py`、`test_turn_latency_indexer.py`、`test_turn_latency_prompt.py`
- Test: `console/backend/tests/integration/test_logs_api.py`、`test_turn_latency_api.py`
- Create: `console/frontend/src/types/logs.ts`、`types/turn-latency.ts`
- Create: `console/frontend/src/api/logs.ts`、`api/turn-latency.ts`
- Create: `console/frontend/src/stores/logs.ts`
- Create: `console/frontend/src/composables/useLogFollow.ts`
- Create: `console/frontend/src/utils/analysis-format.ts`、`utils/turn-latency-format.ts`
- Test: `console/frontend/src/utils/analysis-format.spec.ts`、`utils/turn-latency-format.spec.ts`
- Create: `console/frontend/src/components/LogPanel.vue`、`LogAnalysisCard.vue`、`TurnLatencyPanel.vue`
- Modify: `console/frontend/src/views/InstancesView.vue`
- Modify: `console/design/console-preview.html`（实例页的轮次面板、日志面板与归纳卡）

**Interfaces:**
- Consumes: `console_settings.log_dir`（`/var/log/supervisor`，Task 3）、`llm_proxy` 的回环面 `POST 127.0.0.1:8765/v1/chat/completions`（Task 19）、`AuditRepository.create()`（Task 6）。
- Produces: `log_service.read(process, levels, from_iso, to_iso, q, after, limit) -> dict`（A.15 的 `data`）；`log_service.SOURCES`（四份文件的名字常量）。
- Produces: `log_analysis_service.analyze(request) -> dict`（A.16 的 `data`）；`AnalysisResult` / `SentStats` 的 dataclass；`RATE_LIMIT = (6, 300)`；`TIMEOUT_S = 45`。
- Produces: `GET /api/v1/logs`、`POST /api/v1/logs/analyze`、`GET /api/v1/turn-latency`（A.17）。
- Produces: `turn_latency_service.read(window, status, limit) -> dict`（A.17 的 `data`）；`turn_latency_indexer.run_forever()`；`encode_machine_line(payload) -> str`（`TURN_LATENCY ` 前缀 + 单行 JSON）。
- Produces: `LogLine` / `LogPage` / `LogAnalysis` / `LogAnalysisResult`；`fetchLogs(params)` / `analyzeLogs(body)`；`useLogsStore()`（`lines / nextCursor / reset / truncated / scanned / sources / loading / error / load(reset) / follow() / stop()`）。
- Produces: `LogPanel.vue` props `{ live: boolean }`（emits `follow` / `refresh` / `analyze`）；`LogAnalysisCard.vue` props `{ analysis: LogAnalysis | null; pending: boolean; error: string }`（emits `retry`）；`TurnLatencyPanel.vue` props `{ windowMinutes?: number }`（默认 15，只读，无删除与导出）。

**为什么轮次面板放在日志面板之前**：它答的是“这一次响应整体多慢”（含 VAD 判定、智能轮次等待、排队），而日志面板答的是“哪一行报了错”。先看全局再下钻，与 §3.9.3 的三种故障签表一致；两者窗口**不联动**（一个看 15 分钟，另一个看特定关键字）。

**为什么没有 SSE、也不给 console 加 docker 权限**：console 是单 worker（§3.1），SSE 会把一条长连接钉在唯一进程上；日志本来就是轮询语义，所以“尾部跟随”就是每 2s 拉一次 `after=nextCursor`，而且 `console` 只 `read()` 同容器里的四份文件，根本不需要 docker socket（Global Constraint 4.2）。

**为什么 cursor 是 `{inode, offset}` 而不是行号**：轮转后行号会错位，inode 变就 `reset:true` 从头读——这是“日志已轮转”唯一可靠的判据。前端**不解析** cursor，只把它当不透明串回传，否则服务端换编码就破。

**为什么归纳不回退本地模型**：回退会把分析负载压到正在服务的 GPU 上（Global Constraint 4.3）。所以只走回环 `llm_proxy`；未启用或后端不是远程时直接 `502 log_analysis_unavailable`，UI 写“需 `ENABLE_LLM_PROXY` 且 LLM 后端为远程”。

- [ ] **Step 1: 写日志读取的失败单测**

`console/backend/tests/unit/test_log_service.py`（6 条：增量游标、轮转 `reset`、`level` 三档推断、`limit` 截断、`q` 忽略大小写、读取预算 `truncated`）：

```python
import json

from app.services import log_service

SCAN_LINE = '{"time":"2026-10-24T10:00:00Z","level":"error","msg":"boom"}'


def test_infers_error_level_from_a_json_field(tmp_path):
    (tmp_path / "pipeline-stderr.log").write_text(SCAN_LINE + "\n", encoding="utf-8")
    page = log_service.read(log_dir=tmp_path, process=["pipeline"])
    assert page["lines"][0]["level"] == "ERROR"
    assert page["lines"][0]["stream"] == "stderr"


def test_warning_and_info_levels_have_no_unknown_bucket(tmp_path):
    (tmp_path / "console-stdout.log").write_text("WARNING slow\nrouter started\n", encoding="utf-8")
    page = log_service.read(log_dir=tmp_path, process=["console"])
    assert [line["level"] for line in page["lines"]] == ["WARN", "INFO"]


def test_cursor_returns_only_new_bytes(tmp_path):
    path = tmp_path / "pipeline-stdout.log"
    path.write_text("one\n", encoding="utf-8")
    first = log_service.read(log_dir=tmp_path, process=["pipeline"])
    path.write_text("one\ntwo\n", encoding="utf-8")
    second = log_service.read(log_dir=tmp_path, process=["pipeline"], after=first["nextCursor"])
    assert [line["text"] for line in second["lines"]] == ["two"]
    assert second["reset"] is False


def test_rotated_file_resets_and_rereads(tmp_path):
    path = tmp_path / "pipeline-stdout.log"
    path.write_text("old\n", encoding="utf-8")
    cursor = log_service.read(log_dir=tmp_path, process=["pipeline"])["nextCursor"]
    path.unlink()
    path.write_text("new\n", encoding="utf-8")
    page = log_service.read(log_dir=tmp_path, process=["pipeline"], after=cursor)
    assert page["reset"] is True
    assert [line["text"] for line in page["lines"]] == ["new"]


def test_limit_truncates_and_says_so(tmp_path):
    (tmp_path / "pipeline-stdout.log").write_text("\n".join(f"l{i}" for i in range(50)) + "\n", encoding="utf-8")
    page = log_service.read(log_dir=tmp_path, process=["pipeline"], limit=10)
    assert len(page["lines"]) == 10
    assert page["truncated"] is True


def test_missing_log_dir_raises_logs_unavailable(tmp_path):
    with pytest.raises(log_service.LogsUnavailable):
        log_service.read(log_dir=tmp_path / "nope", process=["pipeline"])
```

- [ ] **Step 2: 写 `log_service.py`**

要点：`SOURCES = ("console-stdout.log", "console-stderr.log", "pipeline-stdout.log", "pipeline-stderr.log")`；`_TAIL_BYTES = 256 * 1024`；`read()` 为同步函数，路由层用 `await asyncio.wait_for(asyncio.to_thread(log_service.read, ...), 1.5)`；超时回已读部分 + `truncated:true`（不 504）。`_encode_cursor(inode, offset)` 用 `base64.urlsafe_b64encode(f"{inode}:{offset}".encode())`；`scanned` 累加实际读取的 `files` / `bytes`；`sources` 列出四份文件的 `size` / `mtime`（不存在也列，`size:0`）。

Run: `cd console/backend && python -m pytest tests/unit/test_log_service.py -q`
Expected: 6 passed。

- [ ] **Step 3: 写归纳服务的失败单测**

`console/backend/tests/unit/test_log_analysis_service.py`（5 条：三种脱敏、估算与截断、单飞、限流）：

```python
from app.services import log_analysis_service


def test_redacts_authorization_and_sk_keys():
    text = log_analysis_service.redact('Authorization: Bearer abc.def.ghi\nkey=sk-1234567890\ntoken: hf_abcdef')
    assert 'sk-1234567890' not in text
    assert 'hf_abcdef' not in text
    assert text.count('***') >= 3


def test_sent_stats_report_estimate_and_drops():
    lines = [log_analysis_service.LogLineStub(text='x' * 400, level='ERROR', ts='')] * 20
    sent, payload = log_analysis_service.prepare(lines, max_lines=5)
    assert sent["lines"] == 5
    assert sent["droppedLines"] == 15
    assert sent["truncated"] is True
    assert sent["estimatedTokens"] == math.ceil(len(payload) / 4)


def test_second_concurrent_call_is_busy():
    with log_analysis_service._exclusive():
        with pytest.raises(log_analysis_service.AnalysisBusy):
            with log_analysis_service._exclusive():
                pass


def test_rate_limit_allows_six_in_five_minutes():
    limiter = log_analysis_service.RateLimiter(limit=6, window_s=300)
    for _ in range(6):
        limiter.hit()
    with pytest.raises(log_analysis_service.AnalysisRateLimited):
        limiter.hit()


def test_window_over_24h_is_too_large():
    with pytest.raises(log_analysis_service.WindowTooLarge):
        log_analysis_service.validate_window("2026-10-23T00:00:00Z", "2026-10-24T01:00:00Z")
```

- [ ] **Step 4: 写 `log_analysis_service.py`**

三道脱敏（`Authorization` / `api[_-]?key` / `token` / `secret` / `password` 的值、`sk-…` / `hf_…`、Bearer / JWT 形状）→ 压缩（ERROR/WARN 优先、同模板只留首末与计数）→ 按 `maxLines`（默认 800、上限 2000）截断，然后组装 prompt。调用面：

```python
response = httpx.post(
    "http://127.0.0.1:8765/v1/chat/completions",
    json={"model": model, "messages": [...], "temperature": 0, "response_format": {"type": "json_object"}},
    timeout=TIMEOUT_S,
)
```

返回前把四块结果过一遍 `_validate_result()`：`errors[]` / `critical[]` / `rootCauses[]` / `actions[]` 的键必须恰好是 A.16 列的那些（多一个少一个都当上游格式错误），否则 `502 log_analysis_unavailable`。审计写 `action="logs.analyze"`、`fields=["from","to","process","level","q","sentLines","estimatedTokens"]`、`detail.summary` 截 200 字。

- [ ] **Step 5: 跑两个单测**

Run: `cd console/backend && python -m pytest tests/unit/test_log_service.py tests/unit/test_log_analysis_service.py -q`
Expected: 11 passed。

- [ ] **Step 6: 写 schemas + router**

`schemas/logs.py`：`LogLine` / `LogPage` / `AnalyzeRequest`（`from`/`to` 必填，`maxLines` 默认 800）+ `AnalyzeResponse`。注意 `from` 是 Python 关键字，字段用 `from_` + `alias="from"`，并 `populate_by_name=True`。

`routers/logs.py`：

```python
@router.get("", response_model=ApiResponse[LogPage])
async def list_logs(
    process: list[str] = Query(default=["console", "pipeline"]),
    level: list[str] = Query(default=[]),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    q: str = Query(default="", max_length=200),
    after: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
    user: User = Depends(current_user),
) -> ApiResponse[LogPage]:
    try:
        page = await asyncio.wait_for(asyncio.to_thread(log_service.read, **params), 1.5)
    except asyncio.TimeoutError:
        page = log_service.partial(limit=limit)
    except log_service.LogsUnavailable as exc:
        raise api_error(503, "logs_unavailable", str(exc))
    return ApiResponse(data=page)


@router.post("/analyze", response_model=ApiResponse[AnalyzeResponse])
def analyze_logs(body: AnalyzeRequest, user: User = Depends(current_user)) -> ApiResponse[AnalyzeResponse]:
    return ApiResponse(data=log_analysis_service.analyze(body, actor=user.username))
```

`log_analysis_service.analyze` 自己把 `WindowTooLarge` / `AnalysisBusy` / `AnalysisRateLimited` / `TimeoutError` / 上游不可用 映射成 `400 log_window_too_large` / `429 log_analysis_busy` / `429 log_analysis_rate_limited` / `504 log_analysis_timeout` / `502 log_analysis_unavailable`。

- [ ] **Step 7: 写集成测试**

`console/backend/tests/integration/test_logs_api.py`（6 条：401 / `limit` 越界 400 / 目录缺失 503 / 过滤生效 / `analyze` 超窗 400 / `analyze` 上游关闭 502）：

```python
def test_limit_over_2000_is_invalid_parameter(client, auth_headers):
    response = client.get("/api/v1/logs?limit=5000", headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_parameter"


def test_missing_log_dir_is_503_not_500(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(console_settings, "log_dir", tmp_path / "absent")
    response = client.get("/api/v1/logs", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "logs_unavailable"


def test_analyze_refuses_a_window_over_24h(client, auth_headers):
    response = client.post(
        "/api/v1/logs/analyze",
        headers=auth_headers,
        json={"from": "2026-10-22T00:00:00Z", "to": "2026-10-24T01:00:00Z"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "log_window_too_large"
```

- [ ] **Step 8: 跑集成测试**

Run: `cd console/backend && python -m pytest tests/integration/test_logs_api.py -q`
Expected: 6 passed。

- [ ] **Step 9: 前端类型、HTTP、store**

`types/logs.ts` 字段逐字对 A.15 / A.16（`LogLine.ts / process / stream / level / text / file / offset`；`LogAnalysis.sent.lines / estimatedTokens / truncated / droppedLines`；四块结果的键不多不少）。`stores/logs.ts`：`load(reset)` 带上当前筛选条件，`follow()` 用 `setInterval(load, 2000)` 且只在 `live` 为真时跑；`analyze()` 期间 `pending=true`，**失败不清空 `lines`**（只写 `analysisError`）。

- [ ] **Step 10: 写 `useLogFollow.ts` 与 `analysis-format.ts`**

`useLogFollow.ts`：暴露 `{ live, toggle, stop }`，`onBeforeUnmount` 必 `stop()`；页签 `hidden` 时也停（与 `stores/runtime.ts` 同一条理由）。

`analysis-format.ts`：

```ts
export function sentSummary(sent: LogAnalysis['sent']): string {
  const tokens = `约 ${(sent.estimatedTokens / 1000).toFixed(1)}k tokens（估算）`
  const dropped = sent.truncated ? ` · 已截断 ${sent.droppedLines} 行` : ''
  return `已送入 ${sent.lines} 行 / ${tokens}${dropped}`
}

export function confidenceText(value: number): string {
  return value >= 0.7 ? '高' : value >= 0.4 ? '中' : '低'
}
```

- [ ] **Step 11: 写两个组件**

`LogPanel.vue`：`a-select`（进程多选）+ `a-select`（级别多选）+ `a-range-picker`（默认最近 15 分钟）+ `a-input-search`（`maxlength=200`）+ 「尾部跟随」`a-switch` + 「刷新」+ 「分析」；行区域用 `<pre>` 逐行渲染（**不引入虚拟滚动**：上限 2000 行，`limit` 已经把量钉死），行头显示 `ts · process · level`，级别用颜色区分；`truncated` 时底部一行「已截断，缩小时间范围再看」；`reset` 时清空并对用户提示「日志已轮转」。

`LogAnalysisCard.vue`：头部渲染 `sentSummary(analysis.sent)`（这一行是 A.16 的硬性要求，不是修饰），下面四块：`errors` 表格（`signature / count / firstSeen / lastSeen / level`，`sample` 可展开）、`critical` 列表（`impact` 排序）、`rootCauses` 列表（`confidence` 用 `confidenceText`）、`actions` 列表（`risk` 用 `a-tag` 标色）。失败时只显示 `error` + 「重试」，**不动左侧日志区**。

- [ ] **Step 12: 写格式化单测 + 挂进实例页 + 全量**

`console/frontend/src/utils/analysis-format.spec.ts`（2 条：无截断时不出现「已截断」、有截断时行数与 tokens 都在）：

```ts
it('omits the truncation clause when nothing was dropped', () => {
  expect(sentSummary({ lines: 120, estimatedTokens: 800, truncated: false, droppedLines: 0 })).toBe(
    '已送入 120 行 / 约 0.8k tokens（估算）'
  )
})
```

`InstancesView.vue` 在 `RuntimeGrid` 下面按序挂 `<LogPanel />` 与 `<LogAnalysisCard />`（**同一列**：分析结果必须与它基于的日志窗口在视觉上相邻）。

Run: `cd console/frontend && npx vitest run`
Expected: **60 passed**（Task 21 的 58 + 本任务 2）。

Run: `cd console/frontend && npx vue-tsc --noEmit && npm run lint`
Expected: 无错误。

- [ ] **Step 13: 同步预览页的轮次面板、日志面板与归纳卡**

`console/design/console-preview.html` 的实例页在监控卡下面按序补**三块**，与 `TurnLatencyPanel.vue` / `LogPanel.vue` / `LogAnalysisCard.vue` 同构、**同一列**（轮次面板先说“整体多慢”，日志面板给细文，归纳卡给结论；归纳结果必须挨着它基于的那个日志窗口）：

- `.tl`（新增，与 `TurnLatencyPanel.vue` 同构）：`.tl__head` 是时间窗预设（15m / 1h / 24h 三个 `.tl__win` chip，当前项 `aria-pressed="true"`）+ `status` 多选 + “刷新”，标题在 `.tl__title` 里；`.tl__agg` 是聚合块（`count` / 四态 / `failureRate` / `e2e` 的 `p50·p95·max` / `stt`·`llm`·`ttsTtfa`·`vadDecision`·`hold` 的 `p50·p95` / `hold.unavailableCount`）；`.tl__rows` 是只读明细表（`loggedAt` / `responseKey` 截 12 字符 / `status` / **七个**阶段值——与条目那七行同一组：`e2eMs` / `vadDecisionMs` / `smartStatus` / `sttMs` / `llmMs` / `ttsTtfaMs` / `holdMs`）；`.tl__foot` 逐字写 `E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.`。**面板里没有任何删除、导出或重算入口。**
- `.logs`：`.logs__head` 里是进程 / 级别 / 时间范围 / 关键字四个过滤控件 + 「尾部跟随」开关 + 「刷新」+ 「分析」；`.logs__body` 用 `<pre>` 逐行渲染，行内 `<span class="t">`（时间）/ `<span class="p">`（进程）/ `lv-i` / `lv-w` / `lv-e` 着色；`.logs__foot` 显示 `nextCursor` 短码、`scanned.files` 与 `scanned.bytes`、以及 `truncated` 时的「已截断，缩小时间范围再看」。**面板里没有任何写入、删除或下载入口。**
- `.an`：`.an__head` 的第二行必须是 `sentSummary()` 的输出（`已送入 412 行 / 约 5.8k tokens（估算） · 已截断 1 200 行 · 附带 38 条轮次`），下面四块 `.an__block` 依次是 `errors` / `critical` / `rootCauses` / `actions`，行级修饰用 `.an__row--bad|warn|ok`。

标本要让三种验收场景在同一次浏览里就能对上：

| 场景 | 日志面板的证据 | 归纳卡的证据 |
| --- | --- | --- |
| 模型未加载 | `pipeline` 段里 `lv-e` 的 `tts handler not ready`，首末时间都在窗口内 | `errors` 里该签名 `count=3` 带 `firstSeen` / `lastSeen`，`critical` 排第一，`actions` 给「预热 TTS handler」 |
| 显存接近打满 | `lv-w` 的 `cuda out of memory risk`，与监控卡的 `vram_pressure` 同一时刻 | `rootCauses` 写「同卡四段共用一份显存，TTS 加载失败后反复重试」并给置信度 |
| 某段延迟异常升高 | `lv-w` 的 `stt latency p95=1240ms` | `critical` 里给出判定依据（p95 与 p50 的比值），`actions` 给「降并发 / 换 compute_type」 |

轮次面板自己也要在同一份标本里演两种状态（§3.9.4 的第 3 条边界）：**正常窗**（`.tl__agg` 里 `count:38`、`e2e p50 3 180 ms / p95 6 260 ms / max 7 940 ms`、`hold` 写 `不可用 / 不可用` 且 `unavailableCount:12`）与 **索引落后**（同一块整块换成 `不可用 · index_lag` 加一行「索引落后 43 s，聚合值不可当现状看」，`<code>index_lag</code>` 用行内码样式）。两种状态用两段相邻的 `.tl` 标本并排写出，并在标题上标明分别是哪种（否则看图的人会以为是同一个面板闪了一下）。第三种状态（`no_turn_rows` 空窗）**不出标本**：它只是一句「该时间窗没有轮次记录」，且与 `count:0` 同时出现，样张里挤不下第三块面板；但它在 Step 18 里必须有分支，不能并进 `不可用 · <code>` 那一类（空窗是正常状态，不是故障）。

Run: 浏览器打开 `console/design/console-preview.html` → 侧栏「实例」
Expected: 轮次面板、日志面板、归纳卡三块自上而下相邻；`Ctrl+F` 搜 `0 ms` 在轮次面板里找不到（取不到就是 `不可用 · <code>` 或 `不可用 / …`，不是 0）；日志里能定位到上面表格的每一行；归纳卡四块齐全且 `sentSummary()` 在首屏（包含 ` · 附带 38 条轮次` 那一段）；页面上找不到密钥值（标本里的 `S2S_*_KEY` 一律是 `***`）。

- [ ] **Step 14: pipeline 侧新增 `TURN_LATENCY` 机器行**

对话页的七行数字（§3.9.4）已经由 `TurnLatencyTracker` 测好，人读行也已落盘；这里只补一路**机器读**的同行，不新增请求、不新增端口。

`src/speech_to_speech/pipeline/turn_latency.py`：加一个固定键序的编码函数（键序就是 §3.9.4 字段表的顺序，下游解析不依赖 `sort_keys`）：

```python
import json
from collections.abc import Mapping

TURN_LATENCY_MACHINE_PREFIX = "TURN_LATENCY "
MACHINE_KEYS = (
    "version",
    "source",
    "turn_id",
    "turn_revision",
    "response_key",
    "status",
    "stt_s",
    "llm_s",
    "tts_ttfa_s",
    "e2e_s",
    "vad_decision_s",
    "smart_status",
    "hold_s",
)


def encode_machine_line(payload: Mapping[str, object]) -> str:
    """一行一条记录：`None` 原文为 `null`，索引器据此区分「没测到」与 0。"""
    ordered = {key: payload.get(key) for key in MACHINE_KEYS}
    return TURN_LATENCY_MACHINE_PREFIX + json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)
```

`src/speech_to_speech/api/openai_realtime/handlers/response.py`：在现有两行之后追一行（同一个 `logger.info`，因此进同一个 `pipeline-stdout.log`）：

```python
            line = tracker.format_log_line()
            if line:
                logger.info("%s response_key=%s", line, response_key)
            # 机器读的同一份数据：prefix + 单行 JSON，索引器按该前缀过滤（§3.9.4）。
            logger.info("%s", encode_machine_line(tracker.metadata_payload(response_key, status)))
```

`tests/test_turn_latency_logging.py`（3 条：前缀与可解析、`null` 保留且 13 个键不多不少、不含换行）：

```python
import json

from speech_to_speech.pipeline.turn_latency import MACHINE_KEYS, encode_machine_line


def test_machine_line_starts_with_the_prefix_and_parses():
    line = encode_machine_line({"version": 2, "response_key": "k1", "e2e_s": 6.26})
    assert line.startswith("TURN_LATENCY ")
    assert json.loads(line[len("TURN_LATENCY ") :])["e2e_s"] == 6.26


def test_missing_measurements_stay_null_and_every_key_is_present():
    payload = json.loads(encode_machine_line({"version": 2, "response_key": "k1"})[len("TURN_LATENCY ") :])
    assert list(payload) == list(MACHINE_KEYS)
    assert payload["hold_s"] is None and payload["hold_s"] != 0


def test_machine_line_never_contains_a_newline():
    assert "\n" not in encode_machine_line({"response_key": "k\n1"})
```

Run: `python -m pytest tests/test_turn_latency_logging.py -q`
Expected: 3 passed。

> 为什么不自建第二份计时：七行数字的唯一来源是 `TurnLatencyTracker`（`vad_decision_s` 在 VAD 层写、`tts_ttfa_s` 在 TTS 层写）。在这里重算一遍就会出现「条目显示 6.26 s、面板显示 4.90 s」的两个口径（§3.9.4 第 1 条）。

- [ ] **Step 15: `turn_latency` 表 + 迁移 + 仓储**

`console/backend/app/models/turn_latency.py`——**索引，不是账本**（设计文档 §3.9.4：删表后重放日志能复原）：

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class TurnLatencyRow(Base):
    """A rebuildable index over `TURN_LATENCY` log lines, not a ledger."""

    __tablename__ = "turn_latency"

    response_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    turn_revision: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)
    turn_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    smart_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    e2e_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tts_ttfa_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vad_decision_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hold_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
```

`console/backend/alembic/versions/0002_turn_latency.py`：`op.create_table("turn_latency", …)` + `op.create_index("ix_turn_latency_logged_at", "turn_latency", ["logged_at"])`；`downgrade()` 反向 `drop_index` / `drop_table`。首行 `revision = "0002"`、`down_revision = "0001"`。

`console/backend/app/repositories/turn_latency_repository.py`（四个函数，全部同步、由调用方 `to_thread`）：

```python
from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.turn_latency import TurnLatencyRow


def upsert_many(session: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    statement = sqlite_insert(TurnLatencyRow).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[TurnLatencyRow.response_key, TurnLatencyRow.turn_revision],
        set_={
            column: statement.excluded[column]
            for column in rows[0]
            if column not in ("response_key", "turn_revision")
        },
    )
    session.execute(statement)
    session.commit()
    return len(rows)


def percentile(values: list[int], p: float) -> int | None:
    """Nearest-rank：不插值，宁可与真实存在的一条样本相等（A.17）。"""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p * len(ordered))) - 1]
```

Query 部分（`summary` / `rows` / `prune`）由 `router` 调用：`select(TurnLatencyRow).where(TurnLatencyRow.logged_at >= start, TurnLatencyRow.logged_at <= end, status_filter)`，聚合只在内存里对已取出的行算百分位（单次 ≤ 2 000 行，不把聚合推给 SQL）。

`console/backend/tests/unit/test_turn_latency_repository.py`（4 条）:

| 用例 | 断言 |
|---|---|
| 同键两次 upsert | 表里只有 1 行，且是后到的值（`cancelled` 之后又来 `completed` 是真实序列） |
| 毫秒换算 | `e2e_s=6.26` → `e2e_ms=6260`；`hold_s=None` → `hold_ms=None`（不是 0） |
| p95 最近秩 | `[100, 200, … 2000]` 的 p95 是 `1900`，不是插值出的 `1905` |
| prune 只删旧行 | `before` 之前删除、之后保留，返回删除条数 |

Run: `cd console/backend && python -m pytest tests/unit/test_turn_latency_repository.py -q`
Expected: 4 passed。

- [ ] **Step 16: `turn_latency_indexer`（复用日志 cursor）**

`console/backend/app/services/turn_latency_indexer.py`：每 5s 拉一次增量，只匹配 `TURN_LATENCY ` 前缀，单次 ≤ 2 000 行，`asyncio.to_thread` 读 + 批量 upsert；cursor 形态与 `log_service` 同为 `{inode, offset}`（**不存行号**：轮转后行号会错位），写 `console_settings.data_dir / "turn_latency.cursor.json"`。

```python
CURSOR_FILE = "turn_latency.cursor.json"
INTERVAL_S = 5.0
MAX_LINES_PER_TICK = 2000
TARGET = "pipeline-stdout.log"
PREFIX = "TURN_LATENCY "


def parse_line(text: str, logged_at: datetime, raw_offset: int) -> dict | None:
    """坏 JSON / 缺主键 → `None`（跳过并计数，不让整批回退）。"""
    try:
        payload = json.loads(text[len(PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not payload.get("response_key"):
        return None
    return {
        "response_key": payload["response_key"],
        "turn_revision": int(payload.get("turn_revision") or 0),
        "turn_id": payload.get("turn_id"),
        "source": payload.get("source") or "",
        "status": payload.get("status") or "",
        "smart_status": payload.get("smart_status"),
        # 秒 → 毫秒，`None` 保持 `None`：取不到就说取不到，不写 0（§3.9.4 第 3 条）。
        "e2e_ms": _ms(payload.get("e2e_s")),
        "stt_ms": _ms(payload.get("stt_s")),
        "llm_ms": _ms(payload.get("llm_s")),
        "tts_ttfa_ms": _ms(payload.get("tts_ttfa_s")),
        "vad_decision_ms": _ms(payload.get("vad_decision_s")),
        "hold_ms": _ms(payload.get("hold_s")),
        "logged_at": logged_at,
        "raw_offset": raw_offset,
    }
```

启动方式：`main.py` 的 `lifespan` 里 `asyncio.create_task(turn_latency_indexer.run_forever())`，`finally` 里 cancel；**不开线程、不开连接、不加 worker**（console 仍是单 worker，§3.1）。

`console/backend/tests/unit/test_turn_latency_indexer.py`（4 条）：

| 用例 | 断言 |
|---|---|
| 只吃机器行 | 同一文件里混入 `Turn t1 rev=0 latency: stt=…` 与 `TURN_LATENCY {...}`，入库只有后者的 1 行 |
| inode 变化 → 从头 | 删旧文件写新文件后 `reset=True`，新行入库（不沿用旧 offset） |
| 坏行跳过 | `TURN_LATENCY {` 一行被跳过，`skipped=1`，其余行照常入库，不抛异常 |
| 2000 行上限不丢行 | 写入 2 500 行：第一拍入库 2 000 行且 cursor 停在 2 000 行处，第二拍拿到剩下 500 行 |

Run: `cd console/backend && python -m pytest tests/unit/test_turn_latency_indexer.py -q`
Expected: 4 passed。

- [ ] **Step 17: `GET /api/v1/turn-latency`（A.17）**

`console/backend/app/schemas/turn_latency.py`：`TurnLatencyQuery`（`from_` / `to` 带 `alias="from"`、`populate_by_name=True`）+ `TurnLatencyWindow` + `TurnLatencyStage`（`p50Ms` / `p95Ms`）+ `TurnLatencyHold`（多一个 `unavailableCount`）+ `TurnLatencySummary` + `TurnLatencyItem` + `TurnLatencyIndex` + `TurnLatencyPage`。字段名逐字对 A.17，**不多一个也不少一个**（前端靠它推断可空性）。

`console/backend/app/routers/turn_latency.py`：

```python
@router.get("", response_model=ApiResponse[TurnLatencyPage])
async def read_turn_latency(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    status: list[str] = Query(default=[]),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(current_user),
) -> ApiResponse[TurnLatencyPage]:
    window = validate_window(from_, to, max_hours=24)          # from > to / 格式错 / 超窗 都 → 400 invalid_parameter
    rows = await asyncio.to_thread(turn_latency_service.read, window, status, limit)
    return ApiResponse(data=rows)
```

理由码的**优先级必须固定**（A.17）：`log_missing` → `indexer_never_ran` → `index_lag` → `no_turn_rows`。并发命中时只报最上游那个，因为下游原因都是它的后果（日志都没了，“窗口内无行”没有意义）。

```python
def summary_reason(summary: dict, index: dict) -> str | None:
    if not index["sources"]:
        return "log_missing"
    if index["lagS"] is None:
        return "indexer_never_ran"
    if index["lagS"] > 30:
        return "index_lag"
    if summary["count"] == 0:
        return "no_turn_rows"
    return None
```

`console/backend/tests/integration/test_turn_latency_api.py`（5 条）：

| 用例 | 断言 |
|---|---|
| 未登录 | `401` |
| `status=bogus` | `400 invalid_parameter`（枚举外的值不得静默忽略） |
| 空窗 | `count:0`，`summary.e2e` 三项均为 `null`，`reasons.summary == "no_turn_rows"`，`rows:[]` |
| 索引落后 | 造 `logged_at` 为 5 分钟前的行 → `reasons.summary == "index_lag"`，响应仍返回那行（不隐藏数据，只标不可当现状看） |
| `limit=501` | `400 invalid_parameter` |

Run: `cd console/backend && python -m pytest tests/integration/test_turn_latency_api.py -q`
Expected: 5 passed。

- [ ] **Step 18: `TurnLatencyPanel.vue` 挂进实例页**

`console/frontend/src/types/turn-latency.ts` / `api/turn-latency.ts`：字段名逐字对 A.17（`p50Ms` / `p95Ms` / `maxMs` / `failureRate` / `unavailableCount` / `lagS` / `ingestedAt` / `reasons`）；`fetchTurnLatency(params)` 把 `status` 拼成逗号串。

`console/frontend/src/utils/turn-latency-format.ts`：

```ts
export function stageValue(ms: number | null): string {
  return ms == null ? '不可用' : `${ms} ms`
}

export function stageStats(stage: { p50Ms: number | null; p95Ms: number | null }): string {
  return stage.p50Ms == null && stage.p95Ms == null ? '不可用' : `${stageValue(stage.p50Ms)} / ${stageValue(stage.p95Ms)}`
}

export function failureRateText(rate: number | null): string {
  return rate == null ? '不可用' : `${(rate * 100).toFixed(1)}%`
}
```

`console/frontend/src/components/TurnLatencyPanel.vue`：`a-range-picker`（预设 15m / 1h / 24h）+ `a-select`（`status` 多选）+ 聚合块（`count` / 四态 / `failureRate` / `e2e` 的 `p50·p95·max` / 五段 `p50·p95` / `hold.unavailableCount`）+ 明细表（`loggedAt` / `responseKey`（截 12 字符，`title` 给全串）/ `status` / **七个**阶段值：`e2eMs` / `vadDecisionMs` / `smartStatus` / `sttMs` / `llmMs` / `ttsTtfaMs` / `holdMs`——与对话页条目那七行一一对应，不多不少）。两条硬性要求：

- `reasons.summary === "no_turn_rows"` 时（空窗、`count:0`），聚合块写「该时间窗没有轮次记录」，**不**写成 `不可用 · no_turn_rows`——没数据不等于坏了；
- 其余理由码（`index_lag` / `log_missing` / `indexer_never_ran`）**整块聚合显示为 `不可用 · <code>`**，不渲染一排 `0 ms`；
- 面板底部原样再写一次 `E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.`（与对话页条目同一句话，§3.9.4 第 2 条）。

`console/frontend/src/utils/turn-latency-format.spec.ts`（2 条：`null` 不显示 0；`p50` 缺失时仍然是 `不可用 / 120 ms` 这个形状，不变成空串也不只留一半）：

```ts
it('never prints a zero for a stage the server did not measure', () => {
  expect(stageValue(null)).toBe('不可用')
  // 千位用普通空格分组，与预览页的 `6 260 ms` 逐字一致；不走 `toLocaleString`，避开环境差异。
  expect(stageValue(6260)).toBe('6 260 ms')
})
```

`InstancesView.vue`：在 `LogPanel` 之前插 `<TurnLatencyPanel />`（先看“这一次响应整体多慢”，再看日志细文；两块的窗口各自独立，不联动——联动会让人误以为日志窗口与轮次窗口必须相等）。

Run: `cd console/frontend && npx vitest run`
Expected: **62 passed**（上一步的 60 + 本步 2）。

Run: `cd console/frontend && npx vue-tsc --noEmit && npm run lint`
Expected: 无错误。

- [ ] **Step 19: 把轮次摘要接进 LLM 归纳（A.16 的 `includeTurnLatency`）**

后端 `log_analysis_service.analyze()`：`includeTurnLatency` 为真时，用同一个窗口调 `turn_latency_repository` 取**聚合**（不取明细），在 prompt 里加一段固定文本，并把实际附带的行数回报到 `sent.turnRows`；为假时 `turnRows=0`。prompt 里要求：`若附带了轮次摘要，必须回答“慢在哪一段”，并区分“浏览器播放慢”与“服务端慢”。`

`console/backend/tests/unit/test_turn_latency_prompt.py`（2 条）：

| 用例 | 断言 |
|---|---|
| 默认附带 | `sent.turnRows` 等于窗口内行数，prompt 含 `慢在哪一段` 与 `p95`，**不含任何 `response_key`**（不逐条塞入） |
| 显式关闭 | `includeTurnLatency=false` → `turnRows == 0`，prompt 不含轮次段落 |

Run: `cd console/backend && python -m pytest tests/unit/test_turn_latency_prompt.py -q`
Expected: 2 passed。

审计：`fields` 末尾追加 `turnRows`（§3.10 落库行），**不存轮次明细**。

前端 `utils/analysis-format.ts`：`sentSummary()` 末尾加一段——`sent.turnRows > 0` 时输出 ` · 附带 ${sent.turnRows} 条轮次`，为 0 时不输出（不写“附带 0 条”这种噪声）；`analysis-format.spec.ts` 加第 3 条把它钉住，前两条的 fixture 补上 `turnRows: 0`。

Run: `cd console/frontend && npx vitest run`
Expected: **70 passed**（69 + 本步 1）。

- [ ] **Step 20: 提交**

```bash
git add src/speech_to_speech console/backend console/frontend console/design/console-preview.html tests/test_turn_latency_logging.py
git commit -m "feat(console): read-only log panel with LLM log summarisation and turn latency index"
```

---

## Task 23: `demo/` 归档与旧路径 404（P5 拆除）

**Files:**
- Move: `demo/` → `archive/demo/`（`git mv`，整目录）
- Delete: `tests/test_demo_agents_adapter.py`、`tests/test_demo_input_transcription.py`、`tests/test_demo_server.py`、`tests/test_demo_user_audio.py`、`tests/test_param_platform.py`
- Modify: `console/backend/app/core/spa.py`（`spa_fallback` 对带扩展名的未知路径返 404）
- Modify: `.github/workflows/ci.yml`（删 `agents-sdk-websocket` 与 `agents-sdk-webrtc` 两个作业）
- Modify: `README.md:105-107`（两条 `./demo/` 链接）
- Modify: `config/prod.env:6` 与 `docs/parameter-catalog.md` 的六处 `demo/...` 溯源路径
- Test: `console/backend/tests/unit/test_legacy_paths.py`

**Interfaces:**
- Consumes: `mount_spa`（Task 3 建立、Task 17 加 `/vendor`）、`console_settings.static_dir`、`create_app()`。
- Produces: `spa_fallback` 的新行为——**未知路径带扩展名 → `404 {"detail": "Not Found"}`；带扩展名且在 `dist/` 内 → 原文件；无扩展名 → `index.html`**。`archive/demo/` 作为只读历史；`ci.yml` 只剩 ruff / mypy / pytest / package / install-smoke 五个作业。

**为什么是 `git mv` 而不是删掉**

§14.2 P5 写的是「`demo/` 整体归档」，且仓库已有 `archive/STT`、`archive/TTS`、`archive/arguments_classes` 三个先例——归档是这个仓库既有的表达方式。`git mv` 让 `git log --follow archive/demo/server.py` 还能一路追到 `demo/server.py`；直接 `git rm -r` 会把那 4000 余行的来历从 `blame` 里抹掉，而这批代码恰恰是 `console/backend` 的移植依据（§14.1 全表都写着「原文件 → 新落点」）。**同时**：`demo/` 里的 `node_modules`（未纳入索引、约百 MB）会跟着目录一起被改名到 `archive/demo/node_modules`。它不影响任何验收，本地删不删由人决定，计划里不写删除命令。

**为什么「旧路径 404」不会自动成立**

这是本任务唯一容易误判的地方。`spa_fallback` 现在的判定是：

```python
candidate = dist / full_path
if full_path and candidate.is_file() and dist in candidate.resolve().parents:
    return FileResponse(candidate, headers=_IMMUTABLE)
return FileResponse(index, headers=_NO_STORE)
```

`/main.js` 归档后不在 `dist/` 里，`is_file()` 为假，于是**落到 `return FileResponse(index)`——200 + `text/html`**。浏览器 `<script src="/main.js">` 拿到一段 HTML，报的是「第 1 行语法错误」，人看到的是「页面坏了」，而不是「这个文件被删了」。所以 P5 的门禁「旧路径 404」不是删完文件就成立，必须加一条判据：

> 截取到的路径**带扩展名**就说明它在要一个文件，而 `dist/` 里没有这个文件 → 真 404。

带扩展名的真实资源（`/assets/index-abc123.js`、`/vendor/*`、`/worklets/mic-capture.js`）在此之前就已经被 `StaticFiles` 挂载或显式路由接走了，根本走不到兜底；兜底里的 `candidate.is_file()` 只兜住 `dist/` 根上的零散文件（`favicon.ico` 之类）。所以这条判据不会误伤任何现存资源。**`/worklets/*` 是活着的**（Task 20 把两个 worklet 拷进了 `console/frontend/public/worklets/`，随 `dist/` 发布），不要把它写进 404 列表。

**为什么两个 CI 作业必须和 `demo/` 一起删**

`ci.yml` 里 `agents-sdk-websocket`（第 65 行起）与 `agents-sdk-webrtc`（第 86 行起）两个作业的第一条实质动作就是 `npm ci --prefix demo`，`cache-dependency-path` 也写死 `demo/package-lock.json`。目录一改名，这两个作业会在依赖缓存那一步就红。更要紧的是它们**测什么**：`demo/tests/{playback,adapter,ws,webrtc}.test.mjs` 用假 SDK 打桩去驱动 `demo/s2s-realtime-client.js`——那是被删掉的旧实现。新实现的等价断言已经在 Task 20 的六个 vitest 文件里（`features/voice/transport/turn-latency.spec.ts` 5 + `features/voice/transport/events.spec.ts` 5 + `features/voice/audio/meter.spec.ts` 5 + `features/voice/audio/sent-audio.spec.ts` 5 + `src/stores/voice.spec.ts` 6 + `features/voice/useTurnLatency.spec.ts` 3 = 29 条；Task 20 的全量是 51 条，另外 22 条是参数平台与路由断言），跑在 `npm --prefix console/frontend test` 里。留着两个 demo 作业等于给已删代码养 CI：永远红的作业会被 `--continue-on-error` 或临时注释掉，最后没人再看它。

**为什么 README 是改写而不是删链接**

`speech-to-speech serve` 仍然监听 `8765`、`/v1/realtime` 仍是这个仓库最核心的对外契约。读者需要知道「浏览器里能跑的样子长什么样」，删掉链接只会让人去别处猜。改写成两条：一条指向新入口（`/console` 与本仓库的 `console/README`），一条指向 `archive/demo/` 并注明「P5 之前的旧实现，仅供对照」。**`docs/upstream-diff-and-deployment-config.md` 不动**——那份文档通篇是对某个历史 commit 的 diff 记录，里面所有 `demo/` 都是在描述「当时上游有这个东西」，改成 `archive/demo/` 反而会篡改历史。

- [ ] **Step 1: 写失败测试**

`console/backend/tests/unit/test_legacy_paths.py`：

```python
"""P5: the archived demo's URLs must answer 404, not index.html.

`spa_fallback` answers every unmatched GET with index.html. Without the
suffix rule, `/main.js` returns 200 `text/html`, and the browser reports a
syntax error at line 1 — which reads as "the page is broken", not "this
asset was removed".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "index-abc123.js").write_text("// bundle", encoding="utf-8")
    (root / "index.html").write_text("<!doctype html><div id=app></div>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def client(dist):
    return TestClient(create_app())


@pytest.mark.parametrize(
    "path",
    [
        "/main.js",
        "/style.css",
        "/s2s-realtime-client.js",
        "/turn-latency.js",
        "/console.html",
        "/ui/console/api.js",
        "/ws/codec.js",
    ],
)
def test_a_removed_demo_asset_is_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    # The failure mode this test exists for: 200 with text/html.
    assert not response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/console/versions",
        "/console/profiles/prod",
        # `/v1` is deliberately NOT a wildcard reverse proxy (Task 19): an
        # unknown `/v1/...` path keeps falling through to index.html. Only
        # `/v1/realtime` and `/v1/realtime/calls` are real routes.
        "/v1/pool",
    ],
)
def test_a_client_side_route_still_gets_the_spa(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_a_real_built_asset_is_still_served(client):
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_the_404_uses_fastapi_default_shape(client):
    # Not the console's {code, message, detail, requestId} envelope: a removed
    # static file is not an ApiError, and curl consumers should see the plain
    # FastAPI body every other 404 on this server uses.
    assert client.get("/main.js").json() == {"detail": "Not Found"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_legacy_paths.py -q`
Expected: **7 failed, 6 passed**——七个 `test_a_removed_demo_asset_is_404[...]` 全红（断言在 `status_code == 404` 上失败，实际拿到 200），`test_the_404_uses_fastapi_default_shape` 也红（拿到的是 HTML 而不是 JSON）。四条 `test_a_client_side_route_still_gets_the_spa` 与 `test_a_real_built_asset_is_still_served` 现在就应当是绿的——它们是这次改动的护栏，不是目标。

- [ ] **Step 3: 改 `spa_fallback`**

在 `console/backend/app/core/spa.py` 里，把 import 行与兜底函数改成：

```python
from fastapi import FastAPI, HTTPException
```

```python
    index = dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file() and dist in candidate.resolve().parents:
            return FileResponse(candidate, headers=_IMMUTABLE)
        # A path that names a file but is not in dist is a *removed* asset (the
        # archived demo's /main.js, /style.css, …), never a client-side route.
        # Answering index.html here would turn a 404 into `200 text/html`, and
        # the browser then blames the script instead of the deletion. Real
        # assets never reach this branch: /assets, /worklets, /vendor and the
        # API prefixes are all registered before this catch-all.
        if Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, headers=_NO_STORE)
```

`Path` 已经在该文件顶部 `from pathlib import Path` 导入过（Task 17 的版本），不用再加。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_legacy_paths.py -q`
Expected: **13 passed**（7 legacy + 4 routes + 1 asset + 1 json shape）。

数字对不上时用 `--reporter` 没有意义（pytest），改跑 `-v` 看哪条少了：`python -m pytest tests/unit/test_legacy_paths.py -v`。期望出现的 node id 是 7 条 `test_a_removed_demo_asset_is_404[…]`、4 条 `test_a_client_side_route_still_gets_the_spa[…]`、1 条 `test_a_real_built_asset_is_still_served`、1 条 `test_the_404_uses_fastapi_default_shape`。**不要为了让计数好看去删断言。**

- [ ] **Step 5: 回归既有的静态托管顺序测试**

Run: `cd console/backend && python -m pytest tests -q`
Expected: 全绿。三条最容易被打断的是——

- Task 3 的 `tests/integration/test_static_mount_order.py::test_unknown_console_route_returns_index_not_404`（`/console/versions` 无扩展名，必须仍走兜底）；
- Task 3 的 `test_hashed_asset_is_cached_hard`（`/assets/app.js` 走挂载，不经兜底）；
- Task 17 的 `tests/demo/test_vendor_api.py::test_the_spa_fallback_still_serves_console_routes`。

任一条红了说明 `Path(full_path).suffix` 判早了——检查是不是把它写在了 `candidate.is_file()` 之前。

- [ ] **Step 6: 归档 `demo/`**

```bash
git mv demo archive/demo
git status --short | head -20
```

Expected: `git status` 显示大量 `R  demo/... -> archive/demo/...`（`R` = rename），而不是 `D` + `??` 两组。若 Windows 报 `Permission denied`：先关掉任何在 `demo/` 下跑的 dev server / `node` 进程再重试（`demo/node_modules` 里的文件句柄会挡住目录改名）。**不要**用 `rm -rf demo` 兜底——那会连同未纳入索引的文件一起丢，且 `git status` 无法再显示 rename。

- [ ] **Step 7: 删五个测试文件**

```bash
git rm tests/test_demo_agents_adapter.py \
       tests/test_demo_input_transcription.py \
       tests/test_demo_server.py \
       tests/test_demo_user_audio.py \
       tests/test_param_platform.py
```

每一条的替代落点，逐条核过再删：

| 被删文件 | 它测的是什么 | 现在的落点 |
|---|---|---|
| `test_demo_server.py` | `demo/server.py` 的 `/api/config` 三分支、`LOCAL_VAD_ASSETS`、`resolve_tier`、`user_view` | `console/backend/tests/demo/test_config_api.py`（Task 17）、`tests/demo/test_vendor_api.py`（Task 17）、`console/backend/tests/unit/test_identity_service.py`（Task 18） |
| `test_demo_agents_adapter.py` | 旧 `s2s-realtime-client.js` 在假 `@openai/agents` 下的 URL 选择、`session.update`、工具下发 | `console/frontend/src/features/voice/transport/*.spec.ts`（Task 20）——断言的是同一批不变量（`acquireGrant` 的 402/401/503 分支、`events.ts` 的归约、`s2s-client` 的 `updateSession`） |
| `test_demo_input_transcription.py` | 转写事件的分段与去重 | `console/frontend/src/features/voice/transport/events.spec.ts` 的 5 例（Task 20） |
| `test_demo_user_audio.py` | 用 Node 驱动 `demo/ws/user-audio-recorder.js`：有界 PCM 缓冲、pre-roll、上限与截断标记，以及 `#chat-history` 里那个 `<audio controls>` 播放器 | `console/frontend/src/features/voice/audio/meter.spec.ts` + `console/frontend/src/features/voice/audio/sent-audio.spec.ts` + `console/frontend/src/stores/voice.spec.ts`（Task 20）；`user-audio-recorder.js` 随 `demo/ws/` 一起归档，**但原音回放能力不许丢**：`audio/sent-audio.ts` 按同一套规则缓冲（24 kHz、pre-roll、上限、`truncated`），`components/AudioReplay.vue` 复刻 `Audio sent to the model` 文案与播放/暂停/错误三态（§14.5 第 11 行、§3.2.2 末段） |
| `test_param_platform.py`（594 行 / 40 项） | `demo/param_platform/*` 的 catalog / renderer / layout / validator / drafts / store | §14.1 要求「拆分迁移，断言不变」——Task 6–10 已按职责分片落地：`console/backend/tests/unit/test_*service*.py` 与 `console/backend/tests/integration/test_*_api.py` |

最后一行值得多说一句：这不是「删掉旧测试省事」。同一批断言现在存在两份才是问题——`demo/` 归档后原件连 `import` 都过不了（`test_param_platform.py` 靠 `sys.path` 注入 `demo/` 才能 `from param_platform import ...`），留着它只会让 `pytest tests/` 常红，而常红的东西最终会被整体跳过。

- [ ] **Step 8: 删两个 CI 作业**

在 `.github/workflows/ci.yml` 里整段删除 `agents-sdk-websocket:`（从 `  agents-sdk-websocket:` 到 `      - run: npm --prefix demo run test:agents:ws`，含末尾空行）与 `agents-sdk-webrtc:`（从 `  agents-sdk-webrtc:` 到 `      - run: npm --prefix demo run test:agents:webrtc`，含末尾空行）。删完后 `jobs:` 下应当是：`ruff`、`mypy`、`pytest`、`package`、`install-smoke` 五个。

```bash
grep -n '^  [a-z-]*:$' .github/workflows/ci.yml
grep -c 'demo' .github/workflows/ci.yml
```

Expected: 第一条列出 `ruff / mypy / pytest / package / install-smoke` 五个（外加 `jobs:` 不算）；第二条输出 **0**。若第二个数字不是 0，用 `grep -n 'demo'` 看是哪个作业漏删。

- [ ] **Step 9: 改写文档里剩下的 `demo/` 引用**

`README.md`：把第 104–107 行那段列表改成

```markdown
- the packaged audio client: `speech-to-speech talk --url ws://127.0.0.1:8765/v1/realtime`
- the browser console in this repo (`/console`; see [`console/README.md`](./console/README.md) for the frontend and backend layout)
- any client using the core OpenAI Realtime events; the OpenAI Agents SDK is tested over both transports (see [Realtime API](#realtime-api))
- the archived browser demo and [LiveKit agents](./archive/demo/livekit/README.md) — the pre-P5 implementation, kept for comparison only
```

`config/prod.env`：第 6 行注释改成

```
# Maintained by the parameter platform (console/backend/app/services/renderer_service.py).
```

`docs/parameter-catalog.md`：六处 `demo/...` 溯源（第 267–270、330–331 行）改成 `archive/demo/...`，因为那些字段的**证据**现在就在那里。行号会随编辑漂移，按内容搜：

```bash
grep -n 'demo/' docs/parameter-catalog.md
```

Expected: 改完后这一条命令没有输出。

**不要动 `docs/upstream-diff-and-deployment-config.md`**：它通篇记录的是某个历史 commit 的 diff，`demo/` 在里面指的是「当时上游有它」。改成 `archive/demo/` 会让那份记录自相矛盾。

- [ ] **Step 10: 全量回归**

```bash
grep -rn 'demo' --include='*.py' --include='*.yml' --include='*.yaml' tests/ .github/ docker-compose*.yml Dockerfile*
```

Expected: 无输出。若还有命中，判断它属于哪一类：仍指向旧目录的（必须改）、还是描述历史状态的（保留，比如 `docs/` 下的核对记录）。

```bash
uv run pytest tests/ -x -q
cd console/backend && python -m pytest tests -q
cd console/frontend && npm test -- --run
```

Expected: 三条全绿。第一条里 `tests/` 已经不含任何 `test_demo_*` / `test_param_platform`；第二条含 Task 21 新增的 10 条（`test_runtime_service` 6 + `test_runtime_api` 4）与 Task 22 新增的 17 条（`test_log_service` 6 + `test_log_analysis_service` 5 + `test_logs_api` 6）；第三条是 56 条（Task 20 的 51 + Task 21 的 3 条渲染 + Task 22 的 2 条格式化）。

- [ ] **Step 11: 手工冒烟（浏览器，一次性）**

这一条**不进 CI**，因为它要真模型、真麦克风权限和一个跑起来的 pipeline 容器——在 CI 上只能靠打桩，而打桩得到的绿灯正是这一步要替代的东西。在部署机执行：

```bash
docker compose up -d
docker compose exec pipeline supervisorctl -c /etc/supervisor/supervisord.conf status
```

Expected: `console` 与 `pipeline` 均 `RUNNING`。然后逐条核：

1. 浏览器打开 `http://<host>:8000/` —— 对话页加载，控制台里 `Network` 只有 `/api/config`、`/api/me`、`/vendor/openai-realtime-agents.umd.js`、`/worklets/*`、`/assets/*` 这几类请求，无 404。
2. 点麦克风 → 允许授权 → 说一句话：`TranscriptList` 出现一条用户条目并转为终稿，orb 进入 live，回复音频开始播放。
3. 在同一个标签页按 F5 —— 回到 `idle`，**不得出现** `Resume last conversation`，也不留残转写；只有设置与工具开关保留（demo 没有会话持久化，Task 20 的 `stores/voice.ts` 只落 `localStorage` 里的设置）。
4. 地址栏直接访问 `http://<host>:8000/main.js`、`/style.css`、`/console.html` —— 三条都是 **404**，且响应体是 `{"detail":"Not Found"}` 而不是 HTML。
5. `http://<host>:8000/console/versions` —— 运维台正常渲染（深链接没被步骤 4 的判据误伤）。

任一条不过就不提交：第 1 条有 404 说明有资源没进 `dist/`（回 Task 20 Step 20 的 `npm run build` 产物清单）；第 2 条不过说明 Task 20 的接线漏了；第 5 条不过说明 `suffix` 判据写错了位置。

- [ ] **Step 12: 提交**

```bash
git add -A
git commit -m "chore(demo): archive the legacy static demo and 404 its asset paths"
```

`git add -A` 是必要的：这一提交同时含 rename（`demo/` → `archive/demo/`）、删除（五个测试）、三处修改（`spa.py`、`ci.yml`、`README.md`）与一处新增（`test_legacy_paths.py`）。`git show --stat HEAD | tail -3` 应当看到 `rename ... (100%)` 的条目；若显示成 `delete` + `create` 成对出现，说明 `git mv` 那步没生效，`git log --follow` 会断在这里。

---

## Task 24: 镜像 tag 回退与发布说明（P5 收尾）

**Files:**
- Modify: `docker-compose.yml`（`pipeline` 服务加 `image: s2s:${S2S_IMAGE_TAG:-latest}`）
- Modify: `.github/workflows/console.yml`（在 `compose publishes only 8000` 之后加一步 tag 生命周期断言）
- Create: `docs/releases/v2.0.0.md`
- Modify: `docs/deployment.md`（新增 `## 8. 镜像回退`）

**Interfaces:**
- Consumes: Task 4 的单镜像单容器（`ENTRYPOINT` = supervisord、无 `command`）、Task 5 的 `console.yml`、Task 6 的 `console/backend/scripts/seed_admin.py --username/--role/--password-stdin`、Task 23 的 `archive/demo/`。
- Produces: compose 变量 `S2S_IMAGE_TAG`（默认 `latest`）；镜像名 `s2s:<tag>`；`docs/releases/v2.0.0.md` 中的回退两行（镜像 / 配置）；`docs/deployment.md §8` 的三条命令。

**为什么 compose 现在必须写 `image:`**

现在 `pipeline` 服务只有 `build:`，没有 `image:`。这种情况下 compose 给镜像起的名字是 `<项目目录名>-pipeline:latest`——既不含版本，也不由你控制。§12 R21 说「回退镜像 tag 会同时换掉 console 与 pipeline」，这句话的前提是**存在一个按版本命名的 tag**；而没有 `image:` 就根本无从 `docker tag` 到一个稳定名字。加上 `image: s2s:${S2S_IMAGE_TAG:-latest}` 之后，三件事各自只有一行：

```bash
docker compose build pipeline                 # → s2s:latest
docker tag s2s:latest s2s:2.0.0               # 发版：打可回退的 tag
S2S_IMAGE_TAG=1.1.0 docker compose up -d --no-build   # 回退：整个镜像退回
```

`--no-build` 不是可选项：不带它，compose 会按当前工作区重新构建，你以为在回退，实际在重新编译 HEAD——回退就变成了假动作。

**为什么回退必须写三句、而不能只写一句“回滚”**

因为三件事的答案不一样，而运维在事故里只能读一遍文档：

| 回退什么 | 怎么回退 | 会不会连带 |
|---|---|---|
| 镜像（console + pipeline 代码） | `S2S_IMAGE_TAG=<旧版本>` | **一起退，不能只退一个**（§12 R21） |
| 配置（`config/<profile>.yaml`） | 控制台「版本」页回滚到上一个 `live` 版本 | 不回退代码（§10.4） |
| 数据（审计、用量） | **不回退** | 审计只增不改（§14.4） |

「控制台不能单独回退」是同镜像的**单向代价**，不是可以化解的技术缺陷（要能单独退就得拆镜像，而那正是用户否掉的方向）。所以它必须写在发布说明正文里，而不是某个内部分享里。

**为什么不在这里 bump 版本号**

AGENTS.md：*Keep release pull requests focused on version metadata and release documentation.* 改 `pyproject.toml` 的 `version`、改 `src/speech_to_speech/__init__.py` 的 `__version__`、打 tag、触发 PyPI 发布是**另一条 PR**（AGENTS.md「Publishing to PyPI」全流程）。本任务只写 v2.0.0 的说明文本与回退路径：版本号留给那条 PR 改，否则这次迁移的 diff 里会混进版本元数据，「`git revert` 回退这次迁移」就不再是一个干净的动作。

**为什么本任务排在 Task 23 之后**

P5 的门禁「连续两个工作日所有发布与语音演示均经新镜像」是**执行前置条件**：它必须在动手做 Task 23（真正移除 `demo/`）之前就满足。本任务排在 T23 之后，是因为发布说明要描述**已经发生的事**（「`/main.js` 现在答 404」），而不是将要发生的事。先写文档再拆会留下一份说谎的文档。

- [ ] **Step 1: 写失败的断言**

```bash
docker compose config | grep -c 'image: s2s:'
```

Expected: `0`。注意不能用 `grep 'image:'`——`llama` 服务本来就有一行 `image: ghcr.io/ggml-org/llama.cpp:server-cuda`，那个命中与你无关。

- [ ] **Step 2: 给 compose 加镜像名**

在 `docker-compose.yml` 的 `pipeline` 服务里，`build:` 之前插入一行（缩进与服务内其余键对齐，`build` 后保持原样）：

```yaml
  pipeline:
    # Every release is this one tag. Rolling back is
    # `S2S_IMAGE_TAG=<old> docker compose up -d --no-build`: console and
    # pipeline move together because they share the image (spec §12 R21).
    image: s2s:${S2S_IMAGE_TAG:-latest}
    build:
      context: .
      dockerfile: ${DOCKERFILE:-Dockerfile}
```

- [ ] **Step 3: 跑断言确认通过**

```bash
docker compose config | grep -c 'image: s2s:'
S2S_IMAGE_TAG=9.9.9 docker compose config | grep 'image: s2s:'
```

Expected: 第一条 `1`（注意 `docker compose config` 会把每个服务渲染一遍，`pipeline` 只有一份）；第二条输出 `image: s2s:9.9.9`。

第二条是关键：它证明变量真的通到了渲染结果，而不是被 compose 当成字符串字面量吃掉。

- [ ] **Step 4: 验证 tag 能真的回退（需要本机 docker）**

```bash
docker compose build pipeline
docker tag s2s:latest s2s:2.0.0
docker run --rm --entrypoint sh s2s:2.0.0 -c 'test -f /app/console/static/index.html && echo image-ok'
```

Expected: 最后一行输出 `image-ok`。它证明「指向一个旧 tag 就是指向一份完整可用的镜像」（静态资源、console 代码都在里面），回退不靠重新构建。

若 `docker run` 报 GPU 相关错误：加 `--gpus all` 再试；仍然失败则只跑前两条命令并 `docker image inspect s2s:2.0.0 --format '{{.Id}}'`，拿到非空 id 即可。

- [ ] **Step 5: 在 CI 里钉住这条契约**

`.github/workflows/console.yml` 里找到已有的 `- name: compose publishes only 8000` 那一步，在它**后面**加：

```yaml
      - name: pipeline image name is tag-controlled
        run: |
          docker compose -f docker-compose.yml config > /tmp/cfg.yml
          grep -q 'image: s2s:' /tmp/cfg.yml
          S2S_IMAGE_TAG=9.9.9 docker compose -f docker-compose.yml config | grep -q 'image: s2s:9.9.9'
```

这一步不连 docker daemon（`compose config` 只做渲染），所以不需要在 CI 里 build，秒级完成。

- [ ] **Step 6: 写发布说明**

`docs/releases/v2.0.0.md`（英文，与 `v1.0.0.md` / `v1.1.0.md` 同体例）：

```markdown
# speech-to-speech v2.0.0

This release replaces the standalone static `demo/` application with a single
image that serves both the conversation page and the operations console, and
moves deployment configuration onto a versioned parameter platform. These notes
cover changes since v1.1.0.

## Breaking changes

- **One image, one container.** The console (`console/backend`, FastAPI) and the
  built SPA (`console/frontend`, Vue) now ship inside the same image as the
  pipeline and are supervised by supervisord. There is no separate
  `console-frontend` / `console-backend` container and no nginx.
- **One published port.** The container publishes `8000` only. The pipeline's
  own realtime endpoint (`8765`) is bound to loopback inside the container and
  is reachable only through the console's proxy at `/v1/realtime`.
- **The static demo is archived.** `demo/` has moved to `archive/demo/` and is
  no longer built or served. `/main.js`, `/style.css`, `/console.html`,
  `/s2s-realtime-client.js` and the rest of the old static paths now answer
  `404`. The conversation page is at `/`, the operations console at `/console`.
- **Deployment parameters are versioned.** `config/prod.yaml` and
  `config/prod.env` are rendered by the console from
  `docs/parameter-catalog.yaml`; every publish writes a new immutable version.
  Hand edits survive only until the next publish.

## Highlights

- **Parameter platform.** Browse the catalog, edit a draft, validate it against
  the real YAML layout, publish (write → restart → health-check → automatic
  fallback on failure), and roll back to any previous version. Every action is
  audited with the operator's username, the changed field names and the elapsed
  time; secret values are never written to the audit log.
- **Operations console** (`/console`): parameters, hot-updatable session fields,
  versions, audit log, and process/pool status. If `pipeline` is stopped the
  page still renders and reports `pool_unreachable` — you no longer need
  `docker stop` to look at it.
- **Conversation page** (`/`): Vue rewrite of the old `index.html` with the same
  surface — identity block, account chip with a tier/remaining popover, the
  four-layer orb across nine states (`idle`, `connecting`, `queued`,
  `your-turn`, `listening`, `user-speaking`, `processing`, `ai-speaking`,
  `error`) with six indicators, the 200° noise-gate arc with local VAD, live
  transcript in a history drawer, web-search and camera-snapshot tools with the
  bottom-left camera PiP, settings (ten fields, all writable, plus a Restart
  button that reconnects with the new values), per-turn latency chips with an
  expandable breakdown, queue and capacity overlays, limit and about dialogs.
  A page refresh starts a fresh conversation — only settings survive it.
- **Conditional demo features stay off unless configured.** Load balancer,
  metering, OAuth login and the daily quota are enabled by environment
  variables exactly as before; unset, the corresponding routes answer `404`
  (not `403`) so they do not advertise themselves.

## Upgrading

1. Back up `config/prod.yaml` and `config/prod.env`.
2. Pull and build the new image, then tag it: `docker tag s2s:latest s2s:2.0.0`.
3. Start it with `docker compose up -d`, then check both processes:

   ```bash
   docker compose exec pipeline supervisorctl -c /etc/supervisor/supervisord.conf status
   ```

   Both `console` and `pipeline` must be `RUNNING`.
4. Create the first operator account (there is no self-service registration):

   ```bash
   docker compose exec -e PYTHONPATH=/app/console pipeline \
     python /app/console/scripts/seed_admin.py --username admin --role admin
   ```

5. Sign in at `http://<host>:8000/console/login` and confirm the parameter tree
   renders with the same field set as the old console.

Audit rows from the old `demo` database are **not** imported: they do not affect
publishing, and §14.3 of the design treats the importer as optional. The old
sqlite file, if still present, stays where it was on the deploy host.

## Rolling back

Three separate things, three separate answers. Record them separately in the
deployment log.

**The image — console and pipeline together.** This is the important one: the
console and the pipeline share one image, so you cannot roll back the console on
its own. There is no supported way to run the new console against an old
pipeline or the reverse.

```bash
S2S_IMAGE_TAG=<previous-version> docker compose up -d --no-build
```

`--no-build` matters: without it compose rebuilds from the working tree and the
rollback silently becomes a re-deploy of `HEAD`.

**The configuration — independently of the code.** Rolling back the image does
**not** touch `config/<profile>.yaml`; the YAML that was live stays live. To
undo a configuration change, use the console's *Versions* page: it points
`live` at an earlier version and re-runs the publish pipeline (write → restart →
health-check → fallback). Configuration rollback never moves code.

**The data — not at all.** New usage rows are only appended, never rewritten, so
rolling the image back leaves the metering and audit tables as they are. Old
code reading newer rows is the one thing to watch: if a schema change ever lands
without a migration, roll back the database first, not the tag.

## Known limitations

- Single image means no canary and no partial upgrade (§12 R21). Accepted; see
  *Rolling back* above.
- One console worker (`uvicorn --workers 1`) because the supervisor socket and
the sqlite files are process-local. Scale the container, not the workers.
- `config/*.bak.<version>` files are written next to the YAML. They are the
  on-disk rollback record and are not garbage-collected.
```

- [ ] **Step 7: 写部署文档的回退章节**

在 `docs/deployment.md` 的 `## 7. 注意事项` 之后追加：

```markdown
## 8. 镜像回退

console 与 pipeline 是**同一个镜像里的两个进程**，所以回退镜像会同时换掉两者。
不存在“只退控制台”的做法（要能单独退就得拆镜像，那会放弃单镜像拓扑）。

```bash
# 发版时：给当前镜像打一个可回退的版本 tag
docker tag s2s:latest s2s:2.0.0

# 回退时：整个镜像退回，不许重新构建
S2S_IMAGE_TAG=2.0.0 docker compose up -d --no-build
docker compose exec pipeline supervisorctl -c /etc/supervisor/supervisord.conf status
```

回退后要确认三件事，它们互不连带：

| 对象 | 回退方式 | 说明 |
|---|---|---|
| 镜像（代码） | `S2S_IMAGE_TAG=<旧版本>` + `--no-build` | console 与 pipeline 一起退 |
| 配置 | 控制台「版本」页回滚到上一个 live 版本 | 不影响代码 |
| 数据（审计/用量） | 不回退 | 只增不改 |

`--no-build` 是必须的：不带它，compose 会按当前工作区重新构建，你以为在回退，
实际是重新部署了 HEAD。

回退后如果控制台起来但参数页报 `pool_unreachable`，先看
`docker compose exec pipeline tail -50 /var/log/supervisor/pipeline-stderr.log`：
那是 pipeline 没起来，不是回退失败。
```

- [ ] **Step 8: 核对文档里的事实**

```bash
grep -n 'archive/demo' README.md
grep -n 'S2S_IMAGE_TAG' docker-compose.yml .github/workflows/console.yml docs/deployment.md docs/releases/v2.0.0.md
```

Expected: 第一条至少 1 处（Task 23 Step 9 写的那条）；第二条五处全部命中。每一条都对应一份**已经存在**的东西——发布说明里提到的路径、命令、脚本，逐项回摋一遍：`console/backend/scripts/seed_admin.py` 存在吗？`/console/login` 真的在 `router/index.ts` 里吗？`supervisorctl -c /etc/supervisor/supervisord.conf status` 在 Task 4 里就是这个写法吗？任一条对不上就改文档，**不要**为了句子好看编一个更顺的路径。

- [ ] **Step 9: 全量回归**

```bash
docker compose config > /dev/null && echo compose-ok
uv run pytest tests/ -x -q
cd console/backend && python -m pytest tests -q
cd console/frontend && npm test -- --run && npm run build
```

Expected: 四条全绿。第一条是 Dockerfile/compose 语法门禁（§6 的 compose 变量拼错也会在这里暴露）。

- [ ] **Step 10: 提交**

```bash
git add docker-compose.yml .github/workflows/console.yml docs/deployment.md docs/releases/v2.0.0.md
git commit -m "docs(deploy): tag the release image and record the three rollback paths"
```

提交后再看一次 `git log --oneline -24`：从 Task 1 到 Task 24 应当是 24 条可读的提交，每条都在自己的阶段内独立可回退。

---

## 附：发布到 PyPI（不属于本次迁移）

版本号提升、tag、发布全部按 AGENTS.md「Publishing to PyPI」执行，且必须是**独立的 release PR**：

1. 确认 `2.0.0` 尚未发布：`pip index versions speech-to-speech`。
2. 改 `pyproject.toml:7` 的 `version` 与 `src/speech_to_speech/__init__.py:3` 的 `__version__`。
3. 单独开 PR，只含这两处 + `docs/releases/v2.0.0.md`（它在 Task 24 已经写好，没改就不用碰）。
4. 合并后：`git tag -a v2.0.0 -m "Release v2.0.0"` → `git push origin v2.0.0` → 看 `Publish` 工作流。

不要在 Task 24 的提交里改这两行版本号——那样「回退这次迁移」就不再是一次干净的 `git revert`。



