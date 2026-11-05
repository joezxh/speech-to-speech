# 集群总览（CON-02）改造设计

> 状态：已与需求方对齐（2026-11-05 评审通过三点决策：权限码层 / 下钻跳 machines 页 / 派生错误率+命中率空态）。
> 验收依据：`docs/scene/console-scene.md` §5.2 CON-02 九个测试场景；视觉与交互基准 `console/design/console-refactor-demo.html`（`renderOverview()` / `clusterRows()` / `topoSVG()` / 集群 CRUD 弹窗）。
> 原则：功能、信息架构、视觉与交互对齐原型，但数据全部来自真实接口，不引入 Mock。

## 1. 目标与非目标

**目标**

1. 真实控制台「集群总览」页（`/console/overview`，`OverviewView.vue`）改造为原型形态：KPI 四卡、集群表 CRUD、拓扑 SVG、图例卡、最近事件表。
2. 后端新增集群实体与 CRUD 接口，服务端校验链与前端等价；写操作全部落审计（含失败）。
3. 引入权限码层（`console:` 前缀），为后续模块铺路。
4. 顶栏集群下拉由硬编码 `['prod','dev']` profile 映射改为真实集群列表，全局集群选中态联动 KPI / 集群表 / 拓扑 / 下钻。

**非目标 / 硬约束**

- 不改动本范围外的其他页面行为。`InstancesView.vue` 仅允许一处最小增量：读 `route.query.host` 做高亮/筛选，不碰其余逻辑。
- 参数事实源仍是 `docs/parameter-catalog.yaml`，本任务不新增参数数据源。
- 不真的对接 consul/nacos：`registry` 是集群边界的管理标签（字符串字段），无探活。
- 不提交 `dist/` 等构建产物；分支与 PR 标题不含 `codex`；未经明确确认不合并 PR。

## 2. 数据模型与迁移

### 2.1 `param_cluster` 新表（`alembic/versions/0006_clusters.py`）

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | Integer | PK |
| `name` | String(64) | `uq_param_cluster_name` 唯一，非空 |
| `registry` | String(255) | 非空，`server_default=""`；**DB 层不加唯一约束**，"非空 registry 全局唯一"由服务层校验（default 集群 registry 为空串，见 2.3） |
| `policy` | String(16) | 非空，`server_default="least"`，取值 `least` / `rr` / `lat` |
| `note` | String(255) | 非空，`server_default=""` |
| `created_at` / `updated_at` | DateTime(timezone=True) | 非空，`utcnow` |
| `updated_by` | String(64) | 非空，`server_default=""` |

风格对齐 `0005_instances.py`：软关联、无外键、`op.create_table` + `server_default`。

### 2.2 `param_instance` 加列

- `cluster_id` String(64)，非空，`server_default="default"`，加索引 `ix_param_instance_cluster_id`。
- 语义：一个实例（pipeline 端点）注册进一个集群。「机器」不是表——**机器 = 集群内按 `base_url` 的 host 去重派生的展示实体**。`在线机器数 = 至少有一个 online 实例的 host 数`。

### 2.3 default 集群 seed（存量零感知 + 可重入）

- 迁移在同一事务内 seed 一行 `name="default", registry="", policy="least", note=""`。
- **可重入写法**：`INSERT INTO param_cluster ... SELECT ... WHERE NOT EXISTS (SELECT 1 FROM param_cluster WHERE name='default')`（用 `sqlalchemy.table/columns` 构造，不裸插），保证即使手工补插过 default 行也不会因唯一约束中断迁移。
- 存量 `param_instance` 行经 `server_default` 自动归属 `default`，读取路径（无 `cluster` 参数 = 全部行）行为逐字节不变。
- `downgrade()`：drop 索引 → drop 列 → drop 表（seed 行随表消失）。

### 2.4 迁移编号风险

其他工作线存在 `0006_voice_sessions` / `0007_speaker_profiles`（本分支 worktree 无对应 `.py`，仅 pycache 残留）。若那些分支先合入，本迁移需 rebase 为后续编号——交付说明中显式记录此事项。

## 3. 权限码层（新文件 `app/core/permissions.py`）

- 权限码 → 允许角色映射（常量表 `PERMISSION_ROLES: dict[str, frozenset[str]]`）：

| 权限码 | 允许角色 |
|---|---|
| `console:cluster:query` / `switch` | `admin`, `operator` |
| `console:cluster:create` / `update` / `delete` | `admin` |

> `switch` 必须含 `operator`：它只是切换视图的审计留痕，若限 admin，operator 切集群会 403，与原型「任何登录用户可切换」冲突。

- 依赖工厂 `require_permission(code)`：内部复用 `require_user` 解出 `CurrentUser.role` 再查映射；不在映射内的角色 → `ApiError("forbidden", …, 403)`；未注册权限码在依赖构造期直接 `RuntimeError`（启动即失败，防打字错误）。
- 本期只有 cluster 一族码落表；映射表结构为后续模块（`console:machine:*` 等）留扩展位，既有端点不改挂权限码。
- 前端镜像：`console/frontend/src/utils/permissions.ts` 同表（code → 角色集合），`stores/auth.ts` 增 `hasPermission(code)` 用于按钮显隐；后端始终兜底 403。

## 4. 后端 API（`routers/clusters.py` + `services/cluster_service.py` + `repositories/cluster_repository.py`）

路由前缀 `/api/v1`，注册进 `core/router_registry.py`（紧随 `instances` 之后）。响应一律走 `schemas/common.ok` 信封，字段 snake_case（与 `/instances` 一致）。

| 操作 | 方法与路径 | 权限码 |
|---|---|---|
| 列表 | `GET /api/v1/clusters` | `console:cluster:query` |
| 详情 | `GET /api/v1/clusters/{name}` | `console:cluster:query` |
| 创建 | `POST /api/v1/clusters` | `console:cluster:create` |
| 更新 | `PUT /api/v1/clusters/{name}` | `console:cluster:update` |
| 删除 | `DELETE /api/v1/clusters/{name}` | `console:cluster:delete` |
| 切换（仅审计） | `POST /api/v1/clusters/{name}/switch` | `console:cluster:switch` |

### 4.1 字段与校验（服务端与原型规则逐条一致）

- `name`：必填；正则 `^[a-z0-9][a-z0-9-]{1,39}$`；全表唯一（编辑路径不接受 name 变更——PUT body 无 name 字段，404 优先于校验）。
- `registry`：创建/更新必填；正则 `^([a-z][a-z0-9+.-]*://)?[\w.-]+:\d{2,5}$`（大小写不敏感）；**非空值全局唯一，编辑排除自身**；default 集群的空 registry 仅存量合法，一旦提交非空值即参与唯一校验。
- `policy`：枚举 `least|rr|lat`；`note`：可选，≤255 字符。
- 错误码（`ApiError`，与前端 i18n errors 表对齐）：
  - `invalid_request` 400 —— 正则/枚举/长度不合法
  - `duplicate_name` 409 / `duplicate_registry` 409
  - `cluster_not_found` 404
  - `cluster_not_empty` 409 —— 删除时该集群仍有 `param_instance` 行（`machines_blocking = 该集群实例数`，写入 message）
  - `last_cluster` 409 —— 删除后集群数将为 0

### 4.2 列表聚合

`GET /clusters` 每行返回：`name, registry, policy, note, machines_total, machines_online, instances_total, healthy, updated_at, updated_by`。聚合口径与 `/instances` 的 summary 共用同一派生函数（host 去重、`status in {online}` 计在线、`healthy = machines_online > 0`），避免两处口径漂移。

### 4.3 审计（写操作全覆盖，失败也记录）

- action 命名（≤32 字符，点分前缀=分类，与 `instance.drain` 同风格）：`cluster.create` / `cluster.update` / `cluster.delete` / `cluster.switch`；`profile` 列存集群名（与 instances 路由把 instance_id 写入 profile 的既有做法一致）；`fields` 只列字段名不列值（spec §10.1 约定）。
- **校验失败/业务阻塞同样落行**：`result="error"` + `error_code=ApiError.code`，随后原样抛出异常。实现：路由层 try/except `ApiError` → 记审计 → re-raise。
- 边界：401（无 token）发生在解析 actor 之前，无法归属操作人，不记审计——「失败也要记录」指业务失败（400/403/404/409），此边界在测试注释中显式声明。
- `switch`：只校验集群存在并写审计行，无 DB 状态变更；集群不存在 → 记 `result="error"` 后 404。

### 4.4 KPI 数据链路（`/instances` 扩展）

- `GET /api/v1/instances` 新增可选 query `cluster`：缺省 = 全部行（现状不变）；给定 = 过滤 `cluster_id`。legacy 单实例直连路径（registry 空表）无行可过滤，`cluster` 参数自然无效，行为与现状一致。
- `summary` 块扩展字段（registry 路径专属，legacy 单实例路径不出现，与现状一致）：
  - `machines_total` / `machines_online`（host 派生，口径同 4.2）
  - `error_rate_5m`：**近 300s**（常量 `ERROR_RATE_WINDOW_S = 300`）本集群 `param_instance_metric`（`kind='sample'`）行聚合：
    - `denominator = Σalloc_ok + Σalloc_fail_instance_503 + Σalloc_fail_no_instance`
    - `rate = (Σalloc_fail_instance_503 + Σalloc_fail_no_instance) / denominator`
    - 一次分配尝试恰好落入三个计数器之一（allocator 每次只 bump 其一），**两类失败不重复计数**；
    - 窗口求和成立的前提：`instance_monitor` 落 `param_instance_metric` 的是采样 tick 间的 **delta 增量**（非累计值），已核实现有实现即如此；
    - `denominator == 0`（窗口内无任何样本）→ 字段为 **`null`，绝不返回 0**；前端渲染 DASH。
  - `top_error_instance`：`argmax(alloc_fail_instance_503 + alloc_fail_no_instance)` 的 instance_id；全部为零或无样本 → `null`。
- 路由命中率：后端**不提供**字段；前端 KPI 第三卡子文案渲染 i18n 占位（「会话粘滞命中率 · 待 S3 交付」），主值=活跃会话（`slots_in_use`）正常展示。

## 5. 前端

### 5.1 状态与请求

- `api/clusters.ts`：list/detail/create/update/remove/switch 六个封装；`api/client.ts` 补 `put` 方法（与既有 get/post/delete 同构）。
- `stores/cluster.ts`（新 pinia store）：`clusters` 列表、`current` 集群名、`load()`、`switchTo(name)`（先调 `/switch` 审计再落本地）。
- 当前集群持久化：`sessionStorage` 键 `s2s.console.cluster`（与 `s2s.console.profile` 的存放约定一致——关标签页即结束，见 `utils/storage.ts` 注释；修正设计中「localStorage」的口误）。缺省/失效回落：列表第一个（default 恒在最前由后端 `ORDER BY id` 保证）。
- 联动：`cluster.current` 变化 → OverviewView 重新拉 `/instances?cluster=`、拓扑、KPI；machines/deploy 等页按 profile 取数的路径不动。

### 5.2 OverviewView.vue 改造（路由、nav、页面名零变更）

自上而下五段，全部对齐原型 `renderOverview()` 信息架构：

1. **KPI 四卡**（a-card）：在线机器 `machines_online / machines_total`（子文案「在线 N」）；Pipeline 实例数（子文案活跃会话）；活跃会话（子文案=命中率占位）；错误率 `error_rate_5m`（警告色阈值≥5%，子文案主要错误来源 instance 或空态文案）。数值一律经 `overviewMetrics.ts` 纯函数映射，`null → DASH`，禁止出现 NaN/0 伪装。
2. **集群表**：列=集群 / registry / 策略 / 机器数(online/total) / 实例数 / 状态 / 操作。当前集群行带「当前」tag 且**不渲染切换按钮**；非当前行渲染 切换/编辑/删除；表头右侧「新增集群」。registry、policy 枚举值、端口以代码态原文展示不翻译。
3. **拓扑卡**：`TopoChart.vue`（新组件）四层：集群 → LB（展示 registry 与 policy）→ 机器 → 实例 chip（`inUse/size · rpm` 用现有池字段 `in_use/size`，rpm 无来源则省略该段）。节点状态色 健康/降级/故障/排空 = token `--s2s-color-success/warning/danger` 及橙色系变量；有 `in_use>0` 实例的连线加 flow 动效 class（CSS animation，尊重 `prefers-reduced-motion`）。**点击机器** → `router.push({ name: 'machines', query: { host } })`；`InstancesView.vue` 读 `route.query.host` 对该 host 的实例行高亮并提示可清除筛选（唯一允许的 machines 页增量）。
4. **图例卡**：五项（在线/告警/排水/故障/流量线），色点与拓扑同源 token。
5. **最近集群事件表**：复用既有 `GET /api/v1/audit`（`profiles.py` 的 audit 端点），取最新 4 条，列=时间/操作人/分类/动作/结果；分类由 action 点分前缀派生并 i18n 化。

### 5.3 ClusterFormModal.vue（新组件）

- a-modal + a-form；新增态字段：名称（可编辑）、registry、策略下拉（least/rr/lat）、备注；编辑态名称 disabled 回填。
- 保存：先跑本地校验（与服务端同正则），提交后服务端错误同样映射到**内联错误条（a-alert）+ toast 双反馈**，弹窗不关闭且回显已填值。
- 删除走既有 `useConfirm` 二次确认；`cluster_not_empty` / `last_cluster` 的 409 以 toast + 错误条呈现，列表不动。
- 成功 toast 文案带集群名（对齐原型 `toast.cluster.*`）。

### 5.4 ConsoleLayout.vue（公共外壳，向后兼容）

- 顶栏胶囊拆为两枚：**集群下拉**（新，来自 `stores/cluster`）与 **profile 下拉**（沿用现有 `profileOptions` 控件与 `consoleStore.selectProfile` API，仅 label 从 `shell.cluster` 改为 `shell.profile`，新增 i18n 键）。
- `consoleStore.profile` 的语义、存储键、所有页面消费点全部不动。

### 5.5 i18n 与样式

- `overview` 命名空间扩展 en/zh 成对键：`cluster.*`、`topology.*`、`legend.*`、`events.*`、`form.errors.*`、`kpi.*`；`shell.profile` 新增；`errors` 命名空间补 §4.1 新错误码（`duplicate_name`、`duplicate_registry`、`cluster_not_found`、`cluster_not_empty`、`last_cluster`）的 en/zh 文案。切语言实时重刷（vue-i18n 现机制）。
- 颜色/圆角/字号一律 `styles/tokens.ts` + `--s2s-*` 变量；拓扑 SVG 内不得出现十六进制字面量（`hex-ban.spec.ts` 拦截）。

## 6. 降级与空态（CON-02 场景 9 + 需求第 7 点）

| 情形 | 呈现 |
|---|---|
| 空集群（0 机器） | KPI `0 / 0`、拓扑 LB 之下空态文案、机器/实例列 0；无 NaN、无 JS 错误 |
| 无健康实例 | 错误率卡 DASH + 子文案「窗口内无分配样本」；集群状态列 tag 灰 |
| `/clusters` 失败 | ErrorBanner + 集群表空态，页面对其余段（拓扑/事件）各自独立降级（与现有「两端点各自失败各自降级」模式一致） |
| `/instances` 单端点失败 | 只降级 KPI 与拓扑段，集群表/事件表照常 |
| 事件接口失败 | 事件卡内 ErrorBanner，不影响其它段 |

## 7. 测试计划

**后端 pytest**（`console/backend/tests`，沿用 instances 测试风格）

- 校验链：name 正则/唯一、registry 格式/非空唯一/编辑排除自身、policy 枚举；
- 删除阻塞：`cluster_not_empty`、`last_cluster`、删除当前集群后回落由前端负责（后端只保证列表序）；
- 审计：四个动作各一行成功 + 至少两类失败各一行 `result="error"`；`switch` 不存在集群 → error 审计 + 404；
- 权限：operator 调 create → 403；无 token → 401；未知权限码构造 → RuntimeError；
- `/instances?cluster=` 过滤正确且**无参数响应与改造前逐字段一致**；
- `error_rate_5m`：无样本=null、分母为 0 不返回 0、三类计数器互斥不重叠、top_error_instance 并列取 instance_id 字典序最小（确定性）。

**前端 vitest + 静态检查**

- `overviewMetrics` 派生：空集群 0/0、null→DASH、错误率百分比格式化；
- `permissions.ts` 映射与 auth store `hasPermission`；
- `vue-tsc --noEmit`、`npm run lint`（--max-warnings 0）、`npm run build` 全绿。

**联调（CON-02 九场景逐条）**

- 前置：`alembic upgrade head`（0005→0006）→ uvicorn :8000 监听确认（吸取 ECONNREFUSED 教训，`/api/v1/health` 探活）→ Vite :3000（必要时 `VITE_DEV_BACKEND`）→ admin 登录；
- 场景 1–9 按 `console-scene.md` §5.2.2 断言执行，截图归档 `qa-artifacts-archive/`；
- 交付说明：改动文件清单、新增接口与字段、迁移说明（含 rebase 风险）、已验证项与未覆盖项。

## 8. 验收对照（原型功能点 → 实现落点）

| 需求功能点 | 落点 |
|---|---|
| 1 KPI 四卡随集群联动 | §5.2-1 + §4.4 |
| 2 集群表与「当前」标签 | §5.2-2 |
| 3 集群 CRUD 与校验 | §4.1 + §5.3 |
| 4 顶栏下拉与切换等效 | §5.4 + §5.1 |
| 5 拓扑 SVG 与下钻 | §5.2-3 |
| 6 图例卡 + 最近事件 | §5.2-4/5 |
| 7 降级态 | §6 |
| 后端分层/复用实例注册/审计/权限码 | §2–§4 |
| i18n/token/数据源/范围约束 | §5.5 + §1 |
