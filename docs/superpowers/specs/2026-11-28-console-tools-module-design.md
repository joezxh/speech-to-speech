# 控制台工具模块：原型对齐 + 工具后端 + 语音可调用（2026-11-28）

## 1. 意图与背景

用户要求把控制台 `/tools` 页（localhost:3000）严格对齐原型 `console/design/console-refactor-demo.html#/tools`，包括上/左留白，页面三行结构：

1. 工具统计（4 张 KPI 卡）；
2. 工具查询（关键字、作用域、启用状态、类型 chip）；
3. 工具列表（8 列表格 + 新建/编辑/复制/删除/启停）。

同时在当前工程真正实现四类工具：联网搜索（Anspire、博查为主，另接几个常用 AI 搜索）、日历（可操作事件）、天气、知识库检索；工具启用后必须能被语音对话演示调用。

与用户确认的两个关键决策：

- **provider 策略 = 混合**：有 key 走真实 provider，无 key 自动降级到演示数据，结果里标明模式；补 key 只改环境变量。
- **CRUD 程度 = B**：完整 CRUD + 后端持久化，用户自建的 HTTP 工具也能被语音调用。

## 2. 目标 / 非目标

**目标**

- `/tools` 页视觉上逐像素贴近原型三行结构，不再显示原始 i18n key。
- 工具的增删改查、启停、复制持久化到数据库；刷新/重启后保留。
- 四类工具（搜索/日历/天气/知识库）在没有外部 key 时也能演示，有 key 时调真实 API。
- 语音页开启的工具进入 RealtimeAgent 的工具声明，模型 function call 由后端统一执行；结果以同一格式回灌。

**非目标**

- 不改 S2S pipeline 里的工具协议（`RealtimeAgent` / SDK function calling 已能工作）。
- 不做真正的 Google/飞书日历账号授权（日历用本地事件存储，属于混合方案的"无 key 降级" branch）。
- 不做向量化知识库/RAG embedding；知识库只做 `docs/**/*.md` 的全文检索。
- 不做租户管理后台；本后端没有 tenant 表，`scope=tenant` 用 `owner`（创建者用户名）近似。

**反目标（做了就算失败）**

- 页面只是"看起来像原型"但开关不影响语音调用。
- 无 key 时工具调用直接报错，导致语音演示空转。
- 把 API key 下发给浏览器或写进前端源码。

## 3. 现状约束（已核实）

- 后端：SQLAlchemy 同步 ORM；SQLite 默认、本地 `DATABASE_URL` 指向 Postgres `s2s_db`；Alembic 线性迁移，当前 head `0021_session_clips`；`/api/v1/*` 走 `require_user` / `require_permission`，`/api/*`（demo）匿名；无工具表、无工具 API。
- 前端：`/tools` 路由存在但 `ToolsView.vue` 只有 web/camera 两个开关，且它用的 i18n key 在所有 locale 里都不存在；`ConsoleLayout` 的 console 面内容区已是 `padding: 22px 26px 60px`，与原型 `.content` 一致，所以页面本身**不要再额外加外层 padding**。
- 语音链路：`voice store (localStorage)` → `VoiceView.vue` 的 `tools` computed → `S2sClient` 构造 `RealtimeAgent({tools})` → 模型 function call → `executeTool` → `POST /api/search` → 回灌。启用/停用工具会走 `setTools()` 重建 agent，确实生效。
- 现有搜索：`console/backend/app/services/search_service.py` 只支持 Serper；无 calendar/weather/kb 实现。
- HTTP 客户端后端统一用 `httpx`；环境变量配置集中在 `app/config/_demo.py` 等 `BaseSettings` 类。

## 4. 方案比较与选择

| 方案 | 做法 | 取舍 | 结论 |
| --- | --- | --- | --- |
| A 展示+启停 | 4 个内置工具写死，开关存 localStorage，CRUD 按钮只提示 | 改动小，但没有持久化，也没有用户自建工具 | 否，用户选 B |
| B 完整 CRUD | 工具表 + API + 通用执行器，自建 HTTP 工具可调用 | 要动 DB/迁移/模型/路由/前端 store，工作量大 | **选定** |
| C 前台 CRUD | 按钮可用但只存 localStorage | 折中但两边不讨好 | 否 |
| 全真 provider | 所有工具调真实外部服务 | 无 key 功能空转 | 否 |
| 全演示数据 | 全部本地样例 | 无法接真实服务 | 否 |
| 混合 provider | 有 key 真调、无 key 降级，格式一致 | 多一层 provider 抽象 | **选定** |

## 5. 详细设计

### 5.1 数据模型与迁移

新增 `alembic/versions/0022_tools.py`（`down_revision = "0021_session_clips"`），建两张表：

- `ai_console_tool`：`id VARCHAR(64) PK`（稳定 id，如 `tool-search`）、`name`、`type`、`description`、`endpoint`、`method`、`scope`、`enabled BOOLEAN`、`builtin BOOLEAN`、`owner VARCHAR(64)`、`params JSON`（`[{k,t,req}]`）、`config JSON`（provider 优先级、城市列表等）、`created_by`/`updated_by`、`created_at`/`updated_at`。
- `ai_console_calendar_event`：`id INTEGER PK autoincrement`、`owner VARCHAR(64)`、`title`、`start_at`、`end_at`、`description`、`created_at`。日历工具的本地事件存储。

迁移里 seed 4 个内置工具，字段照原型 `TOOLS` 常量：`tool-search`(web_search/global/on)、`tool-calendar`(calendar/global/off)、`tool-weather`(weather/global/on)、`tool-kb`(kb/tenant/off)，`builtin=true`，`owner` 为空。

模型/仓储/服务/路由镜像 `template.py` 垂直切片：`models/tool.py`、`repositories/tool_repository.py`、`services/tool_service.py`、`schemas/tool.py`、`routers/tools.py`，并在 `core/router_registry.py` 注册。

### 5.2 API

`APIRouter(prefix="/api/v1/tools")`，权限码新增 `console:tool:query/create/update/delete`（`core/permissions.py` + 前端镜像）。角色映射：四个码全部给 `{admin, operator}`（含 create/update/delete），这样 operator 能创建并维护自己的工具；服务端再做所有权与边界校验——`scope=global` 的创建/修改、以及内置工具的删除，要求 `role == admin`，其余情况只要求 `owner == username`。**启停开关 `PUT /enabled` 只要求 `require_user`**，否则普通用户无法在语音演示里切换内置工具——这与"启用后即可被语音调用"的目标冲突。`/invoke` 只挂 `require_user`：

- `GET /api/v1/tools`：按可见性返回——**内置工具（`builtin=true`）一律对所有登录用户可见**，避免 seed 时 `tool-kb` 的 `tenant/owner 空` 让它永久隐身；自定义工具才按 `owner == current username` 过滤（`scope=global` 的自定义工具所有用户可见但仅 admin 可改）。响应里带 `effectiveEnabled`（定义见下）。`effectiveEnabled` = 工具行的 `enabled`（global/tenant）或浏览器本地覆盖值（session，服务端返回 `null` 让前端决定）。前端表格开关与语音工具列表**都以 `effectiveEnabled` 为准**。
- `POST /api/v1/tools`：创建，服务端生成 id（自定义工具用 `tool-custom-<短 uuid>`），`builtin=false`，`owner=username`。
- `PUT /api/v1/tools/{id}` / `DELETE /api/v1/tools/{id}`：内置工具允许编辑（前端弹原型里的 builtin-warning），删除内置工具需二次确认；事务里记审计。
- `POST /api/v1/tools/{id}/copy`：复制（新 id/name 加 " Copy"）。
- `PUT /api/v1/tools/{id}/enabled`：切换启用；`scope=session` 的工具不落库，返回前端由 localStorage 管理。
- `POST /api/v1/tools/{id}/invoke`：**语音与页面共用的执行端点**。body 为 `arguments` 对象；服务端按 `type` 分派到 provider，返回 `{ mode: "live"|"demo"|"local", provider, data, ... }`。 authenticated，任意用户可调用其可见且启用的工具。**SDK 适配**：`s2s-client.ts` 的 `executeTool` 必须返回 `{ output: string }`；前端把整个信封 `JSON.stringify` 成 `output` 交给模型（让模型知道是否 demo），工具气泡只显示 `data` 的可读摘要；工具 schema 的 `name` 用工具 id（如 `tool-search`），`executeTool(name, args)` 用 `name` 作 path param 调 `/invoke`。

校验口径参照 `template_service.py`：Pydantic 只做基本类型，`type`/`scope`/`method` 的枚举校验、重复名、必填 endpoint 放 service 层，抛 `ApiError` 让统一错误体处理。

### 5.3 工具执行与 provider

`services/tool_execution_service.py` + `services/tool_providers/`：

- **web_search**：provider 顺序从 `config` 读（默认 `anspire,bocha,serper,you,tavily`），逐个检查 key，第一个有 key 的走真实 API，全部无 key 返回内置演示结果。`mode` 标 `live`/`demo`。归一化输出 `{ results: [{title,url,snippet}], provider, mode }`。真实 API 用 `httpx.AsyncClient`，超时 12s，失败时降级到下一个 provider、全失败再降级演示数据并把错误写日志（不回传 key）。
  - Anspire：`GET https://plugin.anspire.cn/api/ntsearch/search`，参数 `query`/`top_k`，key 走其文档指定的 header。
  - 博查：`POST https://api.bocha.cn/v1/web-search`，`Authorization: Bearer`，body `{query, summary:true, count:5}`。
  - Serper：复用现有 `search_service.py`（`X-API-KEY`，`https://google.serper.dev/search`）。
  - You.com：`YDC_API_KEY`；Tavily：`TAVILY_API_KEY`。
- **calendar**：`list_events` / `create_event` / `delete_event`，数据落在 `ai_console_calendar_event`，按 owner 过滤。没有真实账号授权时的操作就是本地事件库，输出 `{ mode: "local", events: [...] }`。
- **weather**：有 `OPENWEATHER_API_KEY` 调 OpenWeatherMap Current Weather（`mode=live`）；无 key 用内置城市样例（北京/上海/深圳/杭州等）按 city 关键词匹配（`mode=demo`）。归一化 `{ city, temperature, condition, humidity, wind, mode }`。
- **kb**：启动时/首次调用时对 `docs/**/*.md` 建简单倒排/子串索引（按段落切块，标题加权），返回 top-k 段 `{ path, heading, snippet, score }`，`mode=local`。索引按文件 mtime 缓存失效。目录可配置 `TOOL_KB_DOCS_DIR`，默认仓库 `docs/`。
- **http（自建工具）**：按工具行里的 `endpoint`/`method`/`params` 用 `httpx` 发请求；仅允许 http/https，超时 8s，响应体截断（如 64KB），禁止把调用者的浏览器 header/cookie 透传；SSRF 防护：默认拒绝环回/内网/链路本地地址，除非显式配置 `TOOLS_HTTP_ALLOW_PRIVATE=true`。

环境变量集中在 `app/config/_tools.py`（新 `ToolSettings(BaseSettings)`），复用 `demo.serper_api_key`；补到 `console/backend/.env.example`。**任何 key 都不下发前端。**

### 5.4 前端页面严格对齐

重写 `views/ToolsView.vue`，按原型 `renderTools()` 的三行结构：

1. `head('nav.tools','tools.page.desc')` 对应 `.page-head`（h1 20px、下距 6px，整体下距 18px）；
2. `.grid.g4` 四张 KPI 卡（总数/已启用/内置/自定义，`gap:14px`，卡内 `padding:14px 16px`）；
3. 查询卡（`card` + `h3` + `filter-grid` + 关键字/作用域/启用状态/类型 chips）；
4. 列表卡（`card` + `h3` + `tool-count` + 新建按钮 + `tbl-scroll/table.tbl` 8 列 + 行内启停 switch + 编辑/复制/删除）。

样式直接采用原型同值 token：卡 `padding:16px 18px; margin-bottom:16px`、表格 `td padding:9px 10px`、chip `padding:4px 12px` 等；外层 padding 由 `ConsoleLayout` 提供，**页面内不再加**。返回原始 key 的问题通过新增 `i18n/locales/{en-US,zh-CN}/tools.ts` 解决，并在两个 `index.ts` 注册；key 名与原型一致（`tools.kpi.*`、`tools.filter.*`、`tools.col.*`、`tool.type.*`、`tool.scope.*`、`tool.form.*` 等）。

新建/编辑/复制/删除用 `a-modal` 表单（原型字段：name/type/desc/endpoint/method/scope/params 行），复用 `useConfirm`/`useToast`，内置工具编辑与删除弹对应 warning。表格筛选全在前端 computed 完成（与原型的 `toolFiltered()` 一致）。

### 5.5 前端 store 与语音接线

- 新增 `api/tools.ts`（`list/create/update/remove/copy/toggle/invoke`，baseURL `/api/v1`）与 `stores/tools.ts`（Pinia：`rows/loading/saving/filtered/enabledTools`，CRUD 后 reload）。
- `ToolsView` 从 store 取数，不再用 `getDemoConfig()` 的 `search` 开关；旧的 `settings.tools.web` 迁移到内置工具 `tool-search.enabled`（首次加载时若 localStorage 里 web=false 则同步一次，之后以 DB 为准）。
- `VoiceView.vue` 的 `tools` computed 改为：`enabledTools`（来自 store，含所有可见且 `effectiveEnabled=true` 的工具，**包括 session 工具**，否则 session 开关就是无效操作） + 浏览器本地 `camera_snapshot`（保留旧能力，不进工具表、不在 `/tools` 页显示）。`executeTool` 对后端工具调 `POST /api/v1/tools/{id}/invoke`；对 camera 仍走本地 `snapshot()`。
- `ToolsDialog.vue` 改为渲染同一份工具列表与开关（去掉硬编码英文），开关走 `toolsStore.toggle()`；`scope=session` 的工具 enabled 写 localStorage。
- `Store` 的 `enabledTools` 需要响应页面开关变更；voice 页订阅 store 并在变更时调用 `client.setTools()`（已有机制）。

### 5.6 测试与验证

- 后端 pytest：工具 CRUD（权限/隔离/重复名）、迁移 upgrade/downgrade、provider 真假分支（mock httpx）、calendar 事件增删改查、kb 检索、http 工具 SSRF 拒绝、`/invoke` 契约。
- 前端 vitest：`tools` store 的筛选/启停、ToolsView 三行结构与 i18n key 全有、语音 `ToolDef[]` 随开关变化。
- 浏览器人工比对：打开 `http://localhost:3000/tools` 与原型 `#/tools` 对照留白/卡片/表格；打开语音演示，启用搜索/天气工具后用语音提问，确认工具调用气泡与结果。
- 不跑 S2S 音频 eval（未改音频路径/LLM prompt 模板）。

## 6. 本设计里由我（实现者）拍定的点

以下没有其他可行答案或用户已把 how 交给我，我在实现时按这里执行：

- calendar 用本地事件表而不是接 Google/飞书（无账号授权，符合混合方案降级分支）。
- knowledge base 用 `docs/**/*.md` 全文检索而非向量库（"简单知识库工具"）。
- `scope=tenant` 用 `owner=username` 近似（后端无 tenant 抽象）。
- `scope=session` 的 enabled 存 localStorage，工具定义本身仍落库。
- camera 保留为浏览器本地工具，不进 `/tools` 表格（原型 4 个工具没有 camera）。
- provider 顺序默认值 `anspire,bocha,serper,you,tavily`，可被工具 `config` 覆盖。

## 7. 留给实现者的自由度

- 具体 CSS 组织（scoped less vs 新增 `styles/tools.less`）与组件拆分，只要视觉与原型一致。
- i18n key 文案的精确措辞（以原型中文/英文为准）。
- 迁移中 seed 的实现方式（`op.bulk_insert` 或直接 SQL）。
- `httpx` 调用是同步还是异步封装（服务层现有两种用法都有）。
