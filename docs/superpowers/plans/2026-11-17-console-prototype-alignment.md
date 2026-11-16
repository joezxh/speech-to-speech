# 控制台严格对齐负载均衡原型 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `console/design/console-refactor-demo.html` 从结构参考升级为实现规格——前端八页按原型逐元素重建，后端补齐 9 表 + 40 接口，新增常驻 agent 作为集群侧唯一事实上报通道，原型每个数字都来自真实数据源。

**Architecture:** 后端：9 张新表（`0010_console_lb_backbone` 迁移）+ 6 组路由（agent / machines / tokens / lb / releases / audit）+ 选台路径插桩（`RoutingEngine` 插在 `rank_session()` 之前，`allocate()` 契约不变）。Agent：`src/speech_to_speech/agent/`（注册→心跳→配置拉取→落盘→回报→token/turn-latency 上报的常驻进程）。前端：`prototype.less`（原型 CSS 移植）+ 13 个 `proto/` 薄组件 + 八页重写（页面主体 0 antd）。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic（双方言 sqlite/postgres）；Vue 3 + TS + pinia + Less + vitest；`speech-to-speech` 包内新增 agent 进程。

**Spec:** `docs/superpowers/specs/2026-11-17-console-prototype-alignment-design.md`（下称"设计 §"；执行者必须同时持有两份文档）

## Global Constraints（每条来自设计 §，逐字生效）

- **G 门禁**：S0 第一项任务是执行设计 §2.1.1 的 G1–G4；不满足则本计划整体 `blocked`，不并行抢跑。
- `allocator.allocate()` 返回 dict 的**键集合不可变**（11-16 §11；`tests/unit/test_allocator.py` 依赖）。
- 新增路由**必须在 `mount_spa()` 之前**注册（C11）；新增权限码**必须在 `app/core/permissions.py` 登记**（C12）。
- 迁移后**必须**跑 `console/backend/scripts/dump_schema_sql.py`（C13）；迁移纯加表加列、可逆。
- 前端 hex 禁令**只增不减**（C10）：原型 CSS 移植时裸 hex 一律换 `var(--s2s-*)`/`var(--voice-*)`。
- **页面主体 0 antd**：八个页面及其子组件树无 `a-*`、无 antd `message`/`notification`；登录页与 `App.vue` 的 `ConfigProvider` 豁免（§6.2）。
- i18n 双语 key 集合必须一致（C9）；默认语言保持 `zh-CN`。
- 写操作审计 `fields` **只记字段名不记值**（§9.2.5）。
- pipeline 侧唯一既有代码改动 = `turn_latency.metadata_payload` 增列 `audio_duration_s`（§7.2.6）；其余语音链路零改动。
- **单通道约定**（§5.3.4/5.3.5）：token 落库只认 agent 上报（`instance_probe` 轮询仅内存兜底）；agent 与 `turn_latency_indexer` **永不并行写同一台机器**（agent 注册成功即让位，索引器落行 `machine_id` 置空）。
- 机器级草稿校验走 11-17 的 `config_service`（类型/取值域/`restart_required`），不自己写校验（§2.1.2）。
- `mode=rollback` 回到**最近 ack 成功版本**；无 ack 记录 → 409（§7.2.3）。
- **首期只允许下发到 `role=canary` 的机器**；`role=agent` 需输入确认词二次确认（§12.1）。
- 发布 build/staging 由外部 CI 执行，console **只记账、不持有 CI 凭据**（R3b 回填）。
- 配置项键集合唯一手写处在 `docs/parameter-catalog.yaml`；`_schema.py` 只补 env/分区/`restart_required`（§7.6）。
- agent 协议带 `protocol_version`(int) 与 `agent_version`(semver)；console 只接受 ≤ 支持版本（C-2）。
- 提交信息遵循 `feat(console): ...` 惯例；**不得含 "codex"**；不提交构建产物（AGENTS.md）。
- 测试命令：后端 `python -m pytest console/backend/tests/... -v`（在 console/backend 的虚拟环境中）；前端 `cd console/frontend && npx vitest run <file>`、`npm run build`、`npm run lint`。

## Review Focus（规格隐含但单测最易漏的失败模式；每条已指到拥有它的任务）

1. **Token 计数器进程重启归零** → 差分出现负增量或暴涨。人期望：重启后首窗按累计值计、永不出现负增量。→ Task 14 步骤 1。
2. **turn_latency 双写** → agent 与索引器并行写同一机器，机器归属来回翻转。人期望：一台机器同一时刻只有一个写入方。→ Task 8 步骤 1。
3. **粘性目标满员/不可达** → 粘性"钉死到死"，会话永久失败。人期望：删亲和行、回落 `rank_session()` 重选、记 `sticky_hit=false`（理由 `sticky_target_unavailable`）。→ Task 17 步骤 1。
4. **匿名/无票据/无规则会话** → 行为与改前不一致。人期望：无规则时与改动前**逐字一致**（等价性回归断言）。→ Task 17 步骤 1（等价性用例）。
5. **agent 未回报的键** → 被当成漂移。人期望：判"未知/不可得"，不计入漂移数。→ Task 21 步骤 1。
6. **回滚取"最近上报实际值"** → 把坏状态固化下发。人期望：回到最近 ack 成功版本；无 ack → 409。→ Task 22 步骤 1。

---

# S0 · 地基（前置：门禁通过）

### Task 1: 执行开工门禁（G1–G4）

**Files:** 无代码改动；结果记录到本文件 Task 1 勾选项。

**Interfaces:** Produces：放行/阻塞结论。阻塞时**停止执行本计划**并向需求方报告。

- [x] **Step 1: 检验 G1** — 读 `docs/superpowers/plans/2026-11-17-console-db-backed-registry-and-config.md`，确认 T2/T3/T4/T5 勾选框全部为 `- [x]`。Expected: 全部完成；否则 STOP。
- [x] **Step 2: 检验 G2** — 对库执行 `SELECT count(*) FROM param_config; SELECT count(*) FROM param_instance_runtime; SELECT count(*) FROM param_allocator_lease;`。Expected: `param_instance_runtime` > 0，三表存在。
- [x] **Step 3: 检验 G3** — 读 `console/backend/app/config/__init__.py`，确认 `console`/`allocator`/`demo`/`app`/`bootstrap` 五分区走 `LiveSettings` 门面（`database`/`auth` 保持 env）。Expected: 已接管。
- [x] **Step 4: 检验 G4** — `python -m pytest console/backend/tests/unit/test_db_allocator_store.py -v`。Expected: PASS。
- [x] **Step 5: 勾选本任务**，若任一项不满足 → 在本任务下追加 `**BLOCKED:** <原因>` 并停止。

### Task 2: `0010_console_lb_backbone` 迁移 + 9 个模型 + 3 处扩列

**Files:**
- Create: `console/backend/alembic/versions/0010_console_lb_backbone.py`
- Create: `console/backend/app/models/machine.py`（`ParamMachine` / `ParamMachineWorkload`）、`machine_config.py`（`ParamMachineConfig` / `ParamMachineDraft`）、`token_metric.py`（`ParamTokenMetric`）、`lb.py`（`ParamLbRule` / `ParamLbAffinity` / `ParamLbRouteLog`）、`release.py`（`ParamRelease`）
- Modify: `console/backend/app/models/__init__.py`（注册）、`app/models/comments.py`（中文注释）、`app/models/turn_latency.py`（+`machine_id`/`instance_id`/`audio_duration_s`，均可空）、`param_instance`（+`machine_id` 可空）、`param_cluster`（+`baseline_profile` 默认 `'prod'`）
- Test: `console/backend/tests/unit/test_lb_backbone_models.py`

**Interfaces:** Produces：上述 9 个 ORM 模型（表名/字段严格按设计 §7.1 两张表：`param_machine` 含 `state` 枚举 `pending_register|ok|warn|draining|bad`、`register_code_hash`、`agent_caps(JSON)`；`turn_latency` 重建语义=重放只还原本机行）。

- [x] **Step 1: 写失败测试** —— 断言：9 张表全部 `__tablename__` 就位；`ParamMachine.state` 默认 `pending_register`；`ParamMachine.token_hash`/`register_code_hash` 唯一性约束存在；`ParamLbAffinity.affinity_key` 为主键；`ParamLbRouteLog` 有 `at` 默认 now；`ParamRelease.profile_version` 可空；`turn_latency` 新三列可空；`param_cluster.baseline_profile` server_default `'prod'`。
- [x] **Step 2:** `python -m pytest console/backend/tests/unit/test_lb_backbone_models.py -v` → Expected: FAIL（ImportError / 表缺失）。
- [x] **Step 3: 实现** 模型 + 迁移（`down_revision='0009'`（以实际 head 为准）；upgrade 纯 `create_table`/`add_column`，downgrade 精确逆操作）；中文注释进 `comments.py`。
- [x] **Step 4:** `python -m pytest console/backend/tests/unit/test_lb_backbone_models.py tests/unit/test_schema_sql.py -v` → PASS；`python console/backend/scripts/dump_schema_sql.py` 重生成双方言 SQL；`alembic -x db_url=sqlite:// upgrade head --sql` 与 postgres 方言离线 SQL 无错。
- [x] **Step 5: Commit** `feat(console): 0010 迁移——机器/负载/配置/token/LB/发布 9 表与 3 处扩列`

### Task 3: 机器仓储 + 机器服务（M1–M7）

**Files:**
- Create: `console/backend/app/repositories/machine_repository.py`、`console/backend/app/services/machine_service.py`
- Test: `console/backend/tests/unit/test_machine_service.py`

**Interfaces:**
- Produces（后续任务按这些签名调用）：

```python
# services/machine_service.py
def list_machines(cluster: str | None = None) -> list[MachineOut]
def get_machine(machine_id: str) -> MachineDetail            # 详情+负载+运行时摘要
def create_machine(p: MachineCreate, actor: str) -> tuple[MachineOut, str]   # (机器, 注册码明文，仅此一次)
def update_machine(machine_id: str, p: MachineUpdate, actor: str) -> MachineOut
def delete_machine(machine_id: str, actor: str) -> None      # 连带清理 workload/draft/config 行（复用 11-17 T3 的实例删除清理语义）
def upsert_workloads(machine_id: str, items: list[WorkloadIn], actor: str) -> list[WorkloadOut]
```

- Consumes：`param_machine`/`param_machine_workload` 模型（Task 2）；审计沿用 T3 `instances.py` 的 `_audit` 约定。

- [x] **Step 1: 写失败测试** —— 用例清单：create 返回注册码且库中只存哈希（再查明文不可得）；`machine_id` 重复 → 409 语义（`ValueError` 由路由层映射）；update 部分字段；delete 连带清理四表行；workloads 全量覆盖；审计行 `action='machine.create'|'machine.update'|'machine.delete'` 且 `fields` 只含字段名。
- [x] **Step 2:** 跑测试 → FAIL。
- [x] **Step 3: 实现**（注册码 = `secrets.token_urlsafe(24)`；哈希 = sha256；审计调用仿 `instances.py`）。
- [x] **Step 4:** 跑测试 → PASS。
- [x] **Step 5: Commit** `feat(console): 机器实体仓储与服务（M1–M7，注册码一次一明文）`

### Task 4: agent 注册与心跳（A0/A1）+ 注册码两段式

**Files:**
- Create: `console/backend/app/schemas/agent.py`、`console/backend/app/services/agent_registry_service.py`、`console/backend/app/routers/agent.py`
- Modify: `console/backend/app/core/permissions.py`（新增 `console:machine:query|create|update|delete`、`console:agent:enroll`）、`app/core/router_registry.py`（注册 `agent.router`，**在 mount_spa 之前**）
- Test: `console/backend/tests/unit/test_agent_registry.py`、`tests/integration/test_agent_endpoints.py`

**Interfaces:**
- Produces：

```python
# services/agent_registry_service.py
def register(body: AgentRegisterIn) -> AgentRegisterOut      # 校验一次性注册码→签发 machine token；建档或绑档
def heartbeat(machine_id: str, body: HeartbeatIn) -> HeartbeatOut
```

- 协议字段严格按设计 §5.2 心跳体（`protocol_version`/`agent_version`/`machine{}`/`capabilities[]`/`workloads[]`(含 `listen`/`public_addr`)/`runtime{}`/`tokens{}`）与响应体（`accepted`/`machine_id`/`server_time`/`config_version`/`config_etag`/`poll_after_s`）。
- 越权规则（§5.4）：agent 端点按 token 映射 `machine_id`；body/query 里 `machine_id` 仅做一致性校验，不一致 → 403。

- [x] **Step 1: 写失败测试** —— 用例：合法注册码换 token、注册码二次使用 → 401、错误注册码 → 401、`protocol_version` 高于支持值 → 400、心跳首到建档（`state` 从 `pending_register` → `ok`）、重复心跳更新负载清单与 `last_seen_at`、token 差分字段入库（暂存内存，Task 14 接表）、body `machine_id` 与 token 不符 → 403、capabilities 缺项 → 面板可用性标记降级（服务返回 `caps` 交集）。
- [x] **Step 2:** 跑测试 → FAIL。
- [x] **Step 3: 实现**（`token_hash`/`register_code_hash` sha256；心跳 upsert 负载清单按 `kind+port` 对齐；`config_version`/`config_etag` 本任务先返回 0/空串，Task 7 接 `agent_config_service`）。
- [x] **Step 4:** 跑两个测试文件 → PASS；`python -m pytest console/backend/tests/integration/test_static_mount_order.py -v` → PASS。
- [x] **Step 5: Commit** `feat(console): agent 注册与心跳端点（A0/A1，一次性注册码两段式）`

### Task 5: 目标配置渲染与版本（A2 的后端内核）

**Files:**
- Create: `console/backend/app/services/agent_config_service.py`
- Modify: `console/backend/app/models/param_config.py` 或新增 `app/models/config_version.py`——**落地方式**：在 `param_config` 同库新增轻量版本表 `param_agent_config_version(machine_id PK, config_version int, yaml_hash str, yaml_text TEXT, rendered_at)`（设计 §7.1 表清单之外的实现载体，命名遵循 `param_*` 惯例；若评审反对可并入 `param_machine` 列，实现者不得另起第二套版本管理）。**注：该表须并入 Task 2 的迁移**——若 Task 2 已提交，则追加迁移 `0011_agent_config_version` 并重跑 dump_schema_sql。
- Test: `console/backend/tests/unit/test_agent_config_service.py`

**Interfaces:**
- Produces：

```python
# services/agent_config_service.py
def render_target(machine_id: str) -> tuple[int, str, str]   # (config_version, etag, yaml_text)
def peek_version(machine_id: str) -> int
def secret_keys_filtered(values: dict) -> dict               # 密钥类键不下发（11-17 §5.2 边界）
```

- Consumes：`renderer_service.render_yaml` + `layout_service.locate`（设计 §7.2.3：**复用，不新写渲染器**）；机器的 `profile`（`param_machine.profile`，回落 `param_cluster.baseline_profile`）。

- [x] **Step 1: 写失败测试** —— 用例：同一机器重复渲染版本号递增、内容不变时 etag 稳定、密钥键被过滤、profile 回落集群默认、YAML 含机器级草稿叠加值（draft 为空时等于 live 渲染）。
- [x] **Step 2:** 跑测试 → FAIL。
- [x] **Step 3: 实现**（draft 叠加逻辑：live 渲染后按 `param_machine_draft` 覆盖对应键）。
- [x] **Step 4:** 跑测试 → PASS。
- [x] **Step 5: Commit** `feat(console): agent 目标配置渲染与版本管理（复用 profile 渲染器）`

### Task 6: agent 配置面（A2/A3/A4）+ 票据化 turn-latency 入口预留

**Files:**
- Modify: `console/backend/app/routers/agent.py`（+A2/A3/A4）
- Create: `console/backend/app/repositories/machine_config_repository.py`（写 `param_machine_config`——A3 的落点）
- Test: `console/backend/tests/unit/test_agent_config_flow.py`

**Interfaces:**
- Produces：A3 `report` 把 `values` 逐键 upsert 进 `param_machine_config`（`observed_at=now`，`reported_by='agent'`），返回 `{accepted, drift_count}`；A4 `ack` 成功时**保存该版本下发快照**（最近 N=5 版，表即 Task 5 的 `param_agent_config_version`，按机保留）。

- [x] **Step 1: 写失败测试** —— 用例：report 后 `param_machine_config` 有行且 `drift_count` 正确（与 profile live 期望值比对）、ack 成功后快照可查（最近 5 版环形）、ack `ok=false` 不产生快照、304 语义（`If-None-Match` 命中当前 etag → 304）。
- [x] **Step 2:** 跑测试 → FAIL。
- [x] **Step 3: 实现**。
- [x] **Step 4:** 跑测试 → PASS。
- [x] **Step 5: Commit** `feat(console): agent 配置拉取/回报/确认（漂移源与 ack 快照）`

### Task 7: agent 进程本体（pipeline 仓）+ supervisord 接线

**Files:**
- Create: `src/speech_to_speech/agent/__init__.py`、`__main__.py`、`settings.py`、`client.py`、`collectors.py`、`config_sync.py`
- Modify: `console/deploy/supervisord.conf`（新增 `s2s-agent` program，priority 15）
- Test: `console/backend/tests/unit/test_agent_collectors.py`（采集器纯函数；agent 进程本体不做端到端自动测试，验证步骤人工）

**Interfaces:**
- `settings.py` 读 env：`S2S_AGENT_CONSOLE_URL`、`S2S_AGENT_REGISTER_CODE`、`S2S_AGENT_TOKEN_FILE`、`S2S_AGENT_MACHINE_ID`、`S2S_AGENT_HEARTBEAT_S`(默认15)。
- `collectors.py` Produces：

```python
def collect_workloads() -> list[Workload]     # pipeline 由探测 /v1/pool 补全；其余读 agent.yaml
def usage_diff(prev: Usage | None, cur: Usage) -> UsageDelta   # 累计值变小=重置：本窗增量=累计值
def tail_turn_latency(path: str, since_offset: int) -> tuple[int, list[dict]]  # (新 offset, 解析行)
```

- `config_sync.py`：拉取（`If-None-Match`）→ 临时文件+原子替换 → 按 `effect` 分流（`hot`→`/internal/sessions/update`；`start`→supervisor XML-RPC 重启 `pipeline`，复用 `restart_runner` 的调用方式；`container`→只记声明）→ `config/report` 回报 `values` → `config/ack`。
- 主循环（`__main__.py`）：无 token 且有注册码 → register；心跳失败指数退避 1→60s；任一环节失败不抛出、不阻塞语音。

- [x] **Step 1: 写失败测试** —— `usage_diff`：正常递增、计数器归零（prev>cur → delta=cur）、None 首次；`tail_turn_latency`：断点续读、offset 回退容错。
- [x] **Step 2:** 跑测试 → FAIL。
- [x] **Step 3: 实现** 采集器 + 主循环 + client（`httpx`）+ supervisord 条目。
- [x] **Step 4:** 跑测试 → PASS。
- [x] **Step 5:** 人工验证步骤（写入计划不写入代码）：`S2S_AGENT_CONSOLE_URL=http://127.0.0.1:8000 S2S_AGENT_REGISTER_CODE=<M3 返回值> python -m speech_to_speech.agent` → 观察机器表 `state=ok`、`last_seen_at` 刷新。**Commit** `feat(agent): s2s-agent 常驻进程（注册/心跳/配置拉取/退避）`

### Task 8: A5 turn-latency 上报 + 单通道让位

**Files:**
- Modify: `console/backend/app/routers/agent.py`（+A5）、`console/backend/app/services/turn_latency_indexer.py`（让位逻辑）
- Test: `console/backend/tests/unit/test_turn_latency_channels.py`

**Interfaces:**
- Produces：A5 按 `response_key+turn_revision` upsert，`machine_id`=token 所指机器、`instance_id`=空、`raw_offset=0`、`logged_at`=行内时间戳（解析规则与 `parse_line` 一致）；索引器对"已有 agent 心跳的机器"让位（落行 `machine_id` 置空）。

- [x] **Step 1: 写失败测试** —— 用例（Review Focus #2）：agent 行 upsert 覆盖旧值不产生重复 PK；同一机器上 agent 生效后索引器跳过；无 agent 机器索引器照常；重建重放只还原本机行（`machine_id` 空），远端行不被重放覆盖；agent 行 `raw_offset=0`、`logged_at` 取行内时间戳。
- [x] **Step 2:** 跑测试 → FAIL。
- [x] **Step 3: 实现**。
- [x] **Step 4:** 跑测试 → PASS。
- [x] **Step 5: Commit** `feat(console): agent turn-latency 上报与索引器单通道让位`

---

# S1 · 机器页

### Task 9: M8 注册测试（三步）+ M9 自动注册

**Files:**
- Modify: `console/backend/app/services/machine_service.py`（+`register_test`/`auto_register`）、`app/routers/machines.py`（新建，挂 M1–M9 全部端点）、`app/core/router_registry.py`
- Test: `console/backend/tests/unit/test_machine_register_flow.py`、`tests/integration/test_machines_api.py`

**Interfaces:**
- Produces：

```python
def register_test(p: RegisterTestIn, actor: str) -> RegisterTestResult
# steps 顺序固定：[{key:'registry',...},{key:'agent',...},{key:'heartbeat',...}]
def auto_register(p: AutoRegisterIn, actor: str) -> AutoRegisterResult
```

- M8 三步真实语义按设计 §7.2.2 表：①建档+注册码（`state=pending_register`）②等 agent register ③等首个心跳；`simulate='fail'` → 第 2 步必败；第 1 步不会失败。

- [x] **Step 1: 写失败测试** —— 成功路径三步全 `ok` 且返回注册码；`simulate=fail` 第 2 步 `state='fail'`；M8 幂等（重复调用对同 `machine_id` 复用未消费注册码）；M9 只受理不代注册；集成测试覆盖 M1–M9 的权限码（无权限 → 403）与 404/409。
- [x] **Step 2:** 跑测试 → FAIL。
- [x] **Step 3: 实现** routers/machines.py（权限依赖用 `console:machine:*`）。
- [x] **Step 4:** 跑测试 → PASS。
- [x] **Step 5: Commit** `feat(console): 机器注册测试三步流与自动注册受理（M8/M9）`

### Task 10: 实例↔机器绑定

**Files:**
- Modify: `console/backend/app/services/instances_service.py`（聚合读带 `machine_id` 维度）、`app/services/agent_registry_service.py`（心跳时按 `public_addr` 反查绑定）、`app/routers/instances.py`（+`instance_bindings` 手工绑定）
- Test: `console/backend/tests/unit/test_instance_binding.py`

**Interfaces:**
- 绑定规则（设计 §7.1）：用 `public_addr` 的 host:port 反查 `param_instance.base_url`；**不按 `listen` 匹配**；未命中保持 `machine_id=NULL` 并呈现"未绑定实例"。

- [x] **Step 1: 写失败测试** —— public_addr 命中绑定；listen 不参与匹配；未命中保持 NULL；手工绑定写入 `param_instance.machine_id`；`GET /instances` 响应含 `machine_id`。
- [x] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS。
- [x] **Step 5: Commit** `feat(console): 实例按 public_addr 绑定机器`

### Task 11: 前端原型外观层（prototype.less + 13 个 proto 组件 + useToast）

**Files:**
- Create: `console/frontend/src/styles/prototype.less`、`src/components/proto/{PTable,PKpi,PChip,PBadge,PDot,PBar,PSplit,PPipe,PWave,PSwitch,PModal,PDrawer,PToast}.vue`、`src/composables/useToast.ts`
- Modify: `console/frontend/src/styles/tokens.ts`（hex 白名单加入 `prototype.less` 与 13 个组件文件）
- Test: `console/frontend/src/components/proto/proto.spec.ts`、`src/composables/useToast.spec.ts`

**Interfaces:**
- class 名与原型逐字一致（`.card/.kpi/.tbl/.chip/.badge/.dot/.bar/.split/.pipe/.wave/.topo/.svcbox/.modal/.drawer/.toast`）。
- Props（薄封装，仅为消重复）：

```ts
// PTable: { columns: {key;label;width?;sticky?:'start'|'end';cls?}[]; rows: Row[] }
// PKpi:   { label:string; value:string|number; sub?:string; tone?:'ok'|'warn'|'bad'|'accent' }
// PChip:  { items:{key;label}[]; modelValue:string }  · PBadge:{ kind:Tone; text:string }
// PDot:{ state:'ok'|'warn'|'draining'|'bad' } · PBar:{ pct:number; warnAbove?:number }
// PSplit:{ aPct:number } · PPipe:{ steps:{key;label;sub?;state:'done'|'active'|'todo'}[] }
// PWave:{ bars:number[]; window?:[number,number] } · PSwitch:{ modelValue:boolean }
// PModal/PDrawer:{ open:boolean; title:string } · useToast(): { push(msg, kind?:'ok'|'warn'|'bad') }
```

- [x] **Step 1: 写失败测试** —— proto.spec：每个组件渲染出对应原型 class 的根节点；PBar `pct>100` 截断到 100；PWave 柱数 = props.bars.length；useToast push 后 toast 容器出现、3.5s 自动消失。
- [x] **Step 2:** `npx vitest run src/components/proto/proto.spec.ts` → FAIL。
- [x] **Step 3: 实现**：从 `console/design/console-refactor-demo.html` 的 `<style>` 段移植类到 `prototype.less`（**裸 hex → token**）；13 组件 + useToast；tokens.ts 白名单追加。
- [x] **Step 4:** vitest PASS；`npx vitest run src/styles/hex-ban.spec.ts` PASS。
- [x] **Step 5: Commit** `feat(console-front): 原型外观层——prototype.less 与 13 个 proto 组件`

### Task 12: 机器页重写（InstancesView → 机器管理）

**Files:**
- Rewrite: `console/frontend/src/views/InstancesView.vue`
- Create: `src/api/machines.ts`、`src/stores/machine.ts`、`src/components/proto/MachineFormModal.vue`、`MachineTestPanel.vue`
- Modify: `src/i18n/locales/{zh-CN,en-US}/machines.ts`（双语同步）、`src/router/index.ts`（路由不变）
- Test: `src/views/machines.viewmodel.spec.ts`（视图模型纯函数）

**Interfaces:**
- Consumes：M1–M9（Task 9/10）。视图模型纯函数（可测）：

```ts
// machines.viewmodel.ts
export function filterMachines(rows: Machine[], q: string): Machine[]
export function vramSummary(rows: Workload[]): { usedGb: number; totalGb: number; pct: number }
export function workloadTags(rows: Workload[]): { kind: string; count: number }[]
export function testStepsToView(steps: TestStep[]): { key; label; state }[]
```

- 页面元素按设计 §4.5 逐条：告警条 / 搜索 + 两按钮 / 12 列机器表 / 内联展开 11 列负载清单+汇总行 / 新增两步模态（负载声明表单，pipeline 锁定勾选）+ 三步测试面板 / 编辑模态。

- [x] **Step 1: 写失败测试** —— viewmodel：搜索命中 id 与 addr；vram 汇总与水位；标签分组计数；`simulate=fail` 时测试面板第 2 步呈失败态。
- [x] **Step 2:** FAIL。
- [x] **Step 3: 实现**（antd 零引用；模态/开关用 proto 组件；i18n 双语 key 成对）。
- [x] **Step 4:** vitest PASS；`npm run build` 零错误；`npx vitest run src/i18n/i18n.spec.ts` PASS。
- [x] **Step 5: Commit** `feat(console-front): 机器管理页按原型重写（多负载/注册测试/自动注册）`

---

# S2 · Token 与 LB 页

### Task 13: token 落库（A1 tokens → `param_token_metric`，单通道）

**Files:**
- Modify: `console/backend/app/services/agent_registry_service.py`（心跳的 `tokens` 段落库）、`app/repositories/machine_config_repository.py` 拆出 `token_metric_repository.py`
- Test: `console/backend/tests/unit/test_token_ingest.py`

**Interfaces:**
- Produces：

```python
# repositories/token_metric_repository.py
def append_delta(machine_id: str, workload_id: str | None, d: TokenDelta) -> None
def window_sum(machine_id: str | None, since: datetime, until: datetime) -> TokenSum
```

- 单通道：`instance_probe` 对 `/v1/usage` 的既有轮询**不落库**（保持内存兜底）；落库真值唯一来源是 agent。

- [ ] **Step 1: 写失败测试**（含 Review Focus #1）—— 正常差分累加；**计数器归零**（prev>cur → delta=cur，无负行）；连续 3 窗 `sum(delta)==累计差`；`window_sum` 聚合正确。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS。
- [ ] **Step 5: Commit** `feat(console): token 增量落库与窗口聚合（单通道=agent）`

### Task 14: token/LB 观测接口（T1–T5, L1–L6）

**Files:**
- Create: `console/backend/app/services/token_analytics_service.py`、`app/services/lb_policy_service.py`、`app/routers/tokens.py`、`app/routers/lb.py`、`app/schemas/token.py`、`app/schemas/lb.py`
- Modify: `app/core/permissions.py`（`console:token:query`、`console:lb:query|rule:write`）、`app/core/router_registry.py`
- Test: `console/backend/tests/unit/test_token_analytics.py`、`tests/unit/test_lb_rules_api.py`、`tests/integration/test_tokens_api.py`

**Interfaces:**
- Produces：

```python
# token_analytics_service.py   （成本/每会话等公式只在后端算，§9.2.4）
def summary(cluster, window: '5m|1h|24h') -> TokenSummary      # {total,input,output,per_minute,quota,water_pct,cost_usd,per_session,per_session_turns}
def trend(cluster, window, buckets: int) -> list[TrendPoint]
def distribution(cluster, window) -> list[MachineDist]
def egress(cluster) -> list[EgressRow]
def policy() -> TokenPolicy                                    # 含来源与生效徽标
# lb_policy_service.py
def policy_snapshot() -> LbPolicyOut
def rules() -> list[LbRuleOut] / def create_rule(...) / def update_rule(id,...) / def delete_rule(id)
def route_stats(window) -> {rules:[{rule_id,matched,tokens,share_pct}], sticky_hit_rate}
```

- [ ] **Step 1: 写失败测试** —— 窗口边界（5m/1h/24h 对齐整窗）；prompt/completion 拆分来自 input/output；成本公式单测（单价常量进配置）；分布 share_pct 归一（sum=100±0.5）；egress 按 kind 聚合、`route='lb'|'direct'` 由 `kind==pipeline` 推导；规则 CRUD 优先级唯一、缺 `match_value` 400；**route_stats 在无路由日志时 `sticky_hit_rate=None`（不可得，不是 0）**。
- [ ] **Step 2:** FAIL → **Step 3:** 实现（路由注册在 mount_spa 前）→ **Step 4:** PASS + `test_static_mount_order.py` PASS。
- [ ] **Step 5: Commit** `feat(console): token 观测与路由规则接口（T1–T5/L1–L6）`

### Task 15: traffic 页重写

**Files:**
- Rewrite: `console/frontend/src/views/TrafficView.vue`
- Create: `src/api/tokens.ts`、`src/api/lb.ts`、`src/stores/tokens.ts`、`src/stores/routing.ts`、`src/components/TokenTrendChart.vue`
- Delete: `src/components/NotImplemented.vue`（三处占位随重写消失）
- Modify: i18n `traffic.ts` 双语
- Test: `src/views/traffic.viewmodel.spec.ts`

**Interfaces:**
- 视图模型：

```ts
export function splitBar(input: number, output: number): { aPct: number }
export function trendPath(points: TrendPoint[], w: number, h: number): { line: string; area: string; peak: {x;y} }
export function egressRoute(kind: string): 'lb' | 'direct'
```

- 七张卡按设计 §4.3 逐条：KPI×4 / Token 卡（窗口 chip + 四格 + split + 口径黄条）/ 策略卡（含 token 策略四项与生效徽标）/ 规则表 / 趋势 SVG / 机器分布 / 负载出口 / 实例表（11 列，列宽横滚）。

- [ ] **Step 1: 写失败测试** —— splitBar 输入 0 时 aPct=0；trendPath 峰值点取 y 最小；egressRoute pipeline→lb 其余→direct。
- [ ] **Step 2:** FAIL → **Step 3:** 实现（含删除 NotImplemented）→ **Step 4:** vitest + `npm run build` PASS；`npx vitest run src/components/NotImplemented.spec.ts` 若存在则同步删除。
- [ ] **Step 5: Commit** `feat(console-front): 流量与路由页按原型重写（七卡，无占位）`

---

# S3 · 路由引擎

### Task 16: WS 票据端点 + 票据表

**Files:**
- Create: `console/backend/app/services/realtime_ticket.py`、`app/schemas/realtime.py`
- Modify: `console/backend/app/routers/realtime.py`（+`POST /api/v1/realtime/ticket`，用户 JWT 鉴权）
- Test: `console/backend/tests/unit/test_realtime_ticket.py`

**Interfaces:**
- Produces：

```python
# services/realtime_ticket.py
def issue(username: str, role: str) -> str          # 128bit urlsafe；内存表 TTL 60s
def consume(ticket: str) -> TicketIdentity | None   # 一次性：消费即焚；过期/不存在 → None
```

- [ ] **Step 1: 写失败测试** —— 换票需 JWT（无 → 401）；消费一次后二次消费 → None；60s 过期 → None；消费成功返回 `{username, role}`。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS。
- [ ] **Step 5: Commit** `feat(console): realtime 一次性短票据（60s TTL，一次性）`

### Task 17: RoutingEngine + `rank_session` 插桩 + 亲和

**Files:**
- Create: `console/backend/app/services/routing_service.py`、`app/repositories/lb_repository.py`（亲和读写 + 过期清理）
- Modify: `console/backend/app/services/upstream_resolver.py`（`rank_session` 调用点插桩）、`app/services/calls_service.py`（同一入口生效）
- Test: `console/backend/tests/unit/test_routing_engine.py`、`tests/unit/test_rank_session_equivalence.py`

**Interfaces:**
- Produces：

```python
@dataclass(frozen=True)
class RoutingDecision:
    rule_id: str | None; sticky_hit: bool; is_canary: bool; affinity_key: str
    candidates: CandidateSpec        # pinned_instance | machine_filter | canary_group | default

class RoutingEngine:
    def resolve(self, ctx: SessionContext) -> RoutingDecision
```

- 硬规则（设计 §7.4）：规则空/无票据 → 与改前**逐字一致**；粘性命中且 reserve 成功 → 直连不 failover；粘性目标满员/不可达 → **删亲和行 + 回落重选 + `sticky_hit=false`(理由 `sticky_target_unavailable`)**；亲和行**异步**写；金丝雀按 `share_pct` 统计近似分流；占用一律走 `db_allocator_store`。

- [ ] **Step 1: 写失败测试**（含 Review Focus #3/#4）—— 规则优先级取第一条 enabled 命中；user_signed 匹配（有票据 username）；tenant_tag / header / default；粘性命中直连；**粘性目标满员 → 亲和行被删 + 回落重选 + 记录理由**；粘性过期（`expires_at` 已过）→ 视为新路由；金丝雀 20% 在 1000 次模拟中分流 [12%,28%]；**等价性：规则表清空 + 无票据时，rank_session 的返回与改动前同一输入逐字一致**；亲和 key 越权（A 用户票据写 B 用户 key）→ 拒绝。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS + `tests/unit/test_allocator.py` PASS（契约未变）+ `test_db_allocator_store.py` PASS。
- [ ] **Step 5: Commit** `feat(console): RoutingEngine 插桩 rank_session（粘性/金丝雀/规则，等价性受保护）`

### Task 18: 路由记账异步落库 + L6 统计接真值

**Files:**
- Create: `console/backend/app/services/route_log_writer.py`
- Modify: `console/backend/app/services/routing_service.py`（选台成功后投递）、`app/services/lb_policy_service.py`（`route_stats` 读 `param_lb_route_log`）
- Test: `console/backend/tests/unit/test_route_log_writer.py`

**Interfaces:**
- Produces：

```python
# route_log_writer.py
def submit(entry: RouteLogEntry) -> None        # 内存队列，绝不阻塞选台
def flush() -> int                              # lifespan 周期任务批量入库
```

- [ ] **Step 1: 写失败测试** —— submit 后 flush 落库行数正确；队列满丢弃并计数（不阻塞）；`sticky_hit_rate = sticky/(sticky+新建)` 口径；未归因 token 计入"未匹配"。
- [ ] **Step 2:** FAIL → **Step 3:** 实现（lifespan 注册周期 flush）→ **Step 4:** PASS。
- [ ] **Step 5: Commit** `feat(console): 路由记账异步批量落库与命中率统计`

---

# S4 · 参数漂移与下发

### Task 19: 参数目录补字段 + scenarios.yaml + 两个校验脚本

**Files:**
- Modify: `docs/parameter-catalog.yaml`（条目补 `what`/`scope`/`product_baseline`/`anchor`；`product_baseline` 由四个场景引用到的参数反推）
- Create: `docs/scenarios.yaml`（4 场景：latency/slow/edge/mix；键用点号形式；`note/why/gain/cost/risk` 为 `{en,zh}`）
- Create: `console/backend/scripts/validate_scenarios.py`、`console/backend/scripts/validate_catalog_schema.py`
- Modify: `console/backend/app/services/catalog_service.py`（解析并透出新字段）、`console/frontend/src/types/catalog.d.ts`（4 字段可选）
- Test: `console/backend/tests/unit/test_catalog_extra_fields.py`

**Interfaces:**
- 校验脚本失败即非零退出（CI 两道闸）；`_schema.py` 键集合与 YAML 双向一致（§7.6）。

- [ ] **Step 1: 写失败测试** —— catalog 新字段解析透出；`exposure:ops` 行数仍 52；scenarios 键全部存在于 catalog 且建议值满足 `choices`；`validate_catalog_schema` 在人为注入不一致键时失败（fixture 临时 YAML）。
- [ ] **Step 2:** FAIL → **Step 3:** 实现（catalog 补字段可由脚本从现有行派生 `what/scope/anchor` 草稿再人工核对；scenarios 引用的键必须有 `product_baseline`，N4）→ **Step 4:** PASS + 两脚本对真实文件跑通退出码 0。
- [ ] **Step 5: Commit** `feat(console): 参数目录四字段、场景数据集与两道校验闸`

### Task 20: 期望值计算 + 漂移（D1/D2）

**Files:**
- Create: `console/backend/app/services/machine_config_service.py`
- Modify: `console/backend/app/routers/machines.py`（+D1/D2）
- Test: `console/backend/tests/unit/test_machine_config_expected.py`

**Interfaces:**
- Produces：

```python
def expected_value(machine_id: str, entry: CatalogEntry) -> tuple[str | None, str]
# 返回 (期望值, 基线来源)：profile live 渲染值 → 回落 catalog 默认；product_baseline 只作参考
def config_view(machine_id: str) -> list[ParamRow]     # 每目录行：expected/actual/drift/source/effect/exposure/risk/anchor
def drift(machine_id: str) -> DriftSummary             # actual 缺失 → '未知'，不算漂移
```

- [ ] **Step 1: 写失败测试**（含 Review Focus #5）—— profile 覆盖的键期望值=live 渲染值；未覆盖回落默认且来源=`期望默认`；**agent 未回报的键 `drift=False` 且 actual=None**；漂移数 = actual 非空且不等期望的行数。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS。
- [ ] **Step 5: Commit** `feat(console): 机器参数期望值与漂移判定（profile 渲染真源）`

### Task 21: 机器级草稿（D3–D5）

**Files:**
- Modify: `console/backend/app/services/machine_config_service.py`（+草稿）、`app/routers/machines.py`（+D3–D5）
- Test: `console/backend/tests/unit/test_machine_draft.py`

**Interfaces:**
- Produces：`get_draft/clear_draft/put_draft(machine_id, patch, base_version, actor)`；**校验走 11-17 `config_service`**（类型/取值域/`restart_required`）；乐观锁：`base_version` 与当前不符 → 409 语义。

- [ ] **Step 1: 写失败测试** —— 保存后可读、`updated_by/updated_at` 正确；非法值（取值域外）被 `config_service` 拒绝且不落库；`base_version` 过期 → 409；清除后行消失；审计 `action='machine.draft.set'`。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS。
- [ ] **Step 5: Commit** `feat(console): 机器级草稿（复用 config_service 校验，乐观锁）`

### Task 22: 下发与回滚（D6）+ ack 快照消费

**Files:**
- Modify: `console/backend/app/services/machine_config_service.py`（+`deploy`）、`app/routers/machines.py`（+D6）
- Test: `console/backend/tests/unit/test_machine_deploy.py`

**Interfaces:**
- Produces：

```python
def deploy(machine_id: str, rows: list[str] | None, mode: 'push'|'rollback', actor: str) -> DeployResult
# push: 期望值+草稿叠加 → bump config_version（agent 下次轮询取走）
# rollback: 取最近 ack 成功版本的快照重新下发；无 ack 记录 → DeployError(409)
# 风控：target machine.role!='canary' → 需 confirm_word==machine_id，否则 403
```

- [ ] **Step 1: 写失败测试**（含 Review Focus #6）—— push 后 `config_version` 递增且 agent 视角 `GET config` 取到新 YAML；**rollback 取 ack 快照而非最近上报实际值**；无 ack → 409；非 canary 机器无确认词 → 403、带确认词 → 放行并审计；行级 push 只影响指定键。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS。
- [ ] **Step 5: Commit** `feat(console): 机器级下发与 ack 快照回滚（canary 风控）`

### Task 23: deploy 页重写

**Files:**
- Rewrite: `console/frontend/src/views/ParamsView.vue`
- Create: `src/api/machineConfig.ts`、`src/stores/draft.ts` 改造（两层草稿）、`src/components/proto/ScenarioAdvisor.vue`
- Modify: `src/layouts/ConsoleLayout.vue`（Profile 胶囊移出顶栏）、i18n `deploy.ts`
- Test: `src/views/deploy.viewmodel.spec.ts`

**Interfaces:**
- Consumes：D1–D7、`GET /catalog`。视图模型：

```ts
export function rowTone(r: ParamRow): 'drift'|'ro'|'ops'|'draft'|null
export function diffRows(scene: Scene, actual: Record<string,string>): DiffRow[]
export function applyScenario(scene: Scene, patch: Record<string,string>): Record<string,string>
```

- 元素按设计 §4.6 逐条：机器 chips / 漂移条 / 离线条 / KPI×4 / 部署栈卡（推送·回滚）/ 分组概览 / 场景顾问（四 chip、建议卡三列理由、差异表、应用到草稿）/ 11 列宽表（首末列 sticky，四类行底色）。

- [ ] **Step 1: 写失败测试** —— rowTone 优先级 drift > ops > ro > draft；applyScenario 只写差距键；diffRows 标记 `same`（现值=建议）。
- [ ] **Step 2:** FAIL → **Step 3:** 实现（Profile 选择器落位页头；下发按钮 canary 之外弹确认词输入）→ **Step 4:** vitest + build + i18n spec PASS。
- [ ] **Step 5: Commit** `feat(console-front): 部署与参数页按原型重写（11 列宽表/场景顾问/行级下发）`

---

# S5 · 发布与审计

### Task 24: 发布台账（R1–R4 + R3b）

**Files:**
- Create: `console/backend/app/repositories/release_repository.py`、`app/services/release_service.py`、`app/routers/releases.py`、`app/schemas/release.py`
- Modify: `app/core/permissions.py`（`console:release:query|write`）、`app/core/router_registry.py`
- Test: `console/backend/tests/unit/test_release_flow.py`

**Interfaces:**
- Produces：

```python
def create_release(p: ReleaseCreate, actor: str) -> ReleaseOut          # status='building'
def advance(release_id: str, stage: str, result: str | None, note: str | None, actor: str) -> ReleaseOut
def stage_result(release_id: str, body: StageResultIn) -> ReleaseOut    # CI 回填；signature 可空=内网受信并审计
def rollback(release_id: str, actor: str) -> ReleaseOut                 # 连带 POST /api/v1/profiles/{profile}/rollback
```

- 阶段转移合法性：`building→staging→canary→rolling→current`；`rolled_back` 仅可从 `canary|rolling`；非法转移 → 409。

- [ ] **Step 1: 写失败测试** —— 合法转移链；非法转移 409；R3b 覆盖阶段结论并记录 `artifact_ref`；rollback 触发 profile rollback 一次（mock）；`signature` 缺省放行但审计记录 `fields=['signature_absent']`；停留 30 分钟标 `pending_backfill`（用注入时钟测）。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS。
- [ ] **Step 5: Commit** `feat(console): 发布台账与 CI 回填入口（console 只记账）`

### Task 25: 全局审计（R5/R6）

**Files:**
- Create: `console/backend/app/routers/audit.py`
- Modify: `app/core/permissions.py`（`console:audit:query|export`）、`app/core/router_registry.py`
- Test: `console/backend/tests/integration/test_audit_api.py`

**Interfaces:**
- Produces：`GET /api/v1/audit?actor&action&result&field&category&from&to&page&pageSize` 分页；`GET /api/v1/audit/export` CSV（`Content-Disposition: attachment`）；`category` 由 `action` 前缀推导（`machine./lb./deploy./release./voice./cluster.`）。

- [ ] **Step 1: 写失败测试** —— 筛选组合各一条；分页边界；CSV 首行表头 + 行数 = 筛选总数；无权限 → 403。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS。
- [ ] **Step 5: Commit** `feat(console): 全局审计查询与 CSV 导出`

### Task 26: release 页 + audit 页重写

**Files:**
- Rewrite: `console/frontend/src/views/VersionsView.vue`、`AuditView.vue`
- Create: `src/api/releases.ts`、`src/stores/release.ts`
- Modify: `src/components/{VersionTable,AuditTable}.vue`（内部换 `PTable`）、i18n `release.ts`/`audit.ts`
- Test: `src/views/release.viewmodel.spec.ts`

**Interfaces:**
- 视图模型：

```ts
export function stageDots(r: Release): { key; state: 'done'|'active'|'todo' }[]
export function rollPct(r: Release): number
export function auditCategory(a: AuditRow): string
```

- 元素按设计 §4.8/§4.9：四阶段圆点流水线（含"待回填"态）+ 新建发布模态（`PublishDialog` 内部换 PModal）/ 版本历史表（灰度条、已锁定标签、回滚禁用态）；审计 KPI×4 / 分类 chip / 导出按钮。

- [ ] **Step 1: 写失败测试** —— stageDots 对 `building`（构建 active）与 `rolled_back` 的状态映射；auditCategory `machine.create→machine`。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** vitest + build + i18n PASS。
- [ ] **Step 5: Commit** `feat(console-front): 发布与审计页按原型重写`

---

# S6 · 音色向导与对话页

### Task 27: 五步音色向导重写

**Files:**
- Rewrite: `console/frontend/src/components/VoiceCreateDialog.vue`（去 `a-modal`，换 `PModal` + `PPipe` 步骤条）
- Modify: `src/components/VoicePicker.vue`（去 `a-button`）、i18n `voices.ts`（`voice.wizard.*`）
- Test: `src/components/voiceWizard.viewmodel.spec.ts`

**Interfaces:**
- 视图模型（跳过逻辑是核心，设计 §4.7）：

```ts
export function stepsFor(source: 'builtin'|'clone'|'design'): WizardStep[]   // builtin 跳 2–4；design 跳 3
export function trimWindow(bars: number[], startMs: number, endMs: number): { bars: number[]; window: [number,number] }
export function canAdvance(step: WizardStep, s: WizardState): boolean        // 预计算未完成 → 禁用下一步
```

- 术语：界面文案用「声纹嵌入」（不出现 x-vector）。

- [ ] **Step 1: 写失败测试** —— `stepsFor('builtin')` 长度 2（来源+命名）；`stepsFor('design')` 长度 4；`stepsFor('clone')` 长度 5；trimWindow 高亮窗计算；预计算 `pending` 时 `canAdvance=false`。
- [ ] **Step 2:** FAIL → **Step 3:** 实现（波形 SVG 48 柱、保留窗高亮、三输入联动）→ **Step 4:** PASS + build。
- [ ] **Step 5: Commit** `feat(console-front): 五步音色向导按原型重写（跳过逻辑/裁剪/预计算）`

### Task 28: 对话页重写 + WS 票据接线

**Files:**
- Rewrite: `console/frontend/src/views/VoiceView.vue`（舞台 + 面板）
- Create: `src/composables/useRealtimeTicket.ts`
- Modify: `src/features/voice/**`（`HistoryDrawer`/`ToolsDrawer`/`SettingsDrawer` 换 `PDrawer`；`RecordingsView.vue` 逻辑降级为历史抽屉数据源；`SessionsView.vue` 从侧栏摘除 `navGroup` 并加返回入口）、i18n `voice.ts`
- Test: `src/views/voice.viewmodel.spec.ts`、`src/composables/useRealtimeTicket.spec.ts`

**Interfaces:**
- 视图模型：

```ts
export function orbState(s: VoiceState): 'idle'|'listening'|'thinking'|'speaking'|'connecting'
export function bubblesScroll(to: number, atBottom: boolean): boolean
export function toolRows(tools: ToolCfg[], enabled: Set<string>): ToolRow[]
```

- 票据接线：呼叫前 `POST /api/v1/realtime/ticket` → `?ticket=` 拼进 WS URL；401/过期 → 匿名继续（不阻塞呼叫）。

- [ ] **Step 1: 写失败测试** —— orbState 五态映射；`bubblesScroll(false)` 强制滚动、用户上翻时不抢滚动；toolRows 只列启用项；`useRealtimeTicket` 失败时返回 null 且呼叫继续（mock 401）。
- [ ] **Step 2:** FAIL → **Step 3:** 实现（三个抽屉换 PDrawer；光球四态动画走 voice.less 变量）→ **Step 4:** PASS + build + i18n。
- [ ] **Step 5: Commit** `feat(console-front): 对话示波页按原型重写（光球/气泡/三抽屉/票据换身份）`

---

# S7 · 视觉收口

### Task 29: 总览页重写（KPI/拓扑/最近事件真值）

**Files:**
- Rewrite: `console/frontend/src/views/OverviewView.vue`
- Modify: `src/components/TopoChart.vue`（数据源换 `param_machine`；输出对齐原型 `topoSVG()`）、i18n `overview.ts`
- Test: `src/views/overview.viewmodel.spec.ts`

**Interfaces:**
- Consumes：M1、L6（命中率）、R5（最近事件）、`/instances`。视图模型：

```ts
export function overviewKpis(m: Machine[], i: Instance[], s: LbStats, a: AuditRow[]): Kpi[]
export function topoRows(m: Machine[], i: Instance[]): TopoRow[]
export function eventRows(a: AuditRow[]): EventRow[]      // 取最近 N=8
```

- [ ] **Step 1: 写失败测试** —— KPI：在线机器 `x/y`、路由命中率无数据→`不可得`；topoRows 按 machine 分组实例；eventRows 截取 8 条。
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS + build。
- [ ] **Step 5: Commit** `feat(console-front): 集群总览页按原型重写（KPI/拓扑/最近事件真值）`

### Task 30: antd 清零清扫 + 剩余组件原生化

**Files:**
- Modify: `src/components/{ClusterFormModal,PublishDialog,ConfirmDialog,DiffTable,InstanceCard,LogPanel,LogAnalysisCard,TurnLatencyPanel,ParamField,VoiceLibraryTable}.vue`（逐个去 `a-*`/`message`）
- Create: `console/frontend/src/styles/antd-free.spec.ts`
- Test: 同上 spec

**Interfaces:**
- antd-free.spec：扫描 `src/views/**` 与八页引用的组件源码，断言无 `/<a-[a-z-]+/`、无 `from 'ant-design-vue'`；豁免清单：`LoginView`、`App.vue`。

- [ ] **Step 1: 写失败测试** —— antd-free.spec 先跑：对当前树应 FAIL（列出不合规文件），该输出即本任务的清扫清单。
- [ ] **Step 2:** 逐文件清扫（`a-form` 校验改自校验；`message.*` 改 `useToast().push(...)`）。
- [ ] **Step 3:** `npx vitest run src/styles/antd-free.spec.ts` PASS。
- [ ] **Step 4:** `npm run build`、`npm run lint` 零 error；`npx vitest run` 全绿（基线 39 文件不回退）。
- [ ] **Step 5: Commit** `feat(console-front): 八页子组件树 antd 清零`

### Task 31: i18n 补齐 + hex 棘轮扩展 + 基线截图比对 + 文档同步

**Files:**
- Modify: `src/i18n/locales/{zh-CN,en-US}/*.ts`（补 `nav.lb`/`nav.conversation` 等全部新 key）、`src/styles/tokens.ts`（白名单扩到全部改造文件）、`src/router/index.ts` 的 nav 元数据（`session-update` 摘除）、`src/index.html`（新图标 symbol）
- Modify: `docs/console-service.md`（agent 面 + 四组接口 + 开关表）、`console/README.md`（agent 部署形态）、`docs/parameter-catalog.md`（4 新字段说明）、`docs/superpowers/specs/2026-11-16-console-s2s-load-balancing-design.md` §14 修订记录、`docs/superpowers/specs/2026-11-17-console-db-backed-registry-and-config-design.md` §1.2 修订记录
- Modify: `console/backend/app/routers/traffic.py`（`unimplemented` 清为 `[]`）
- Test: `npx vitest run src/i18n/i18n.spec.ts src/styles/hex-ban.spec.ts`

**Interfaces:** 无新接口；本任务是收口与一致性验证。

- [ ] **Step 1:** `npx vitest run src/i18n/i18n.spec.ts` → 若双语不一致则按输出补 key（预期至少补 `nav.lb`、`nav.conversation`）。
- [ ] **Step 2:** hex 白名单扩到全部改造文件；`hex-ban.spec.ts` PASS。
- [ ] **Step 3: 基线截图比对**（人工步骤，写入本任务勾选）：10 张既有基线（`_shot-lb/-machines/-deploy-voicepick/-voices/-voice-wizard` 中英各 5）并排比对；另补 4 页基线（总览/对话示波/发布/审计，中英各 1），存 `console/design/`。
- [ ] **Step 4:** 文档修订记录写回两份既有 spec；`traffic.py` 的 `unimplemented` 清空；三份使用文档同步。
- [ ] **Step 5:** 后端全量 `python -m pytest console/backend/tests -v`（基线 405 不回退）+ 前端 `npx vitest run` + `npm run build` + `npm run lint` 全绿。**Commit** `feat(console): 原型对齐收口——i18n/样式棘轮/基线截图/文档修订`

---

## Self-Review 记录

1. **Spec 覆盖**：§4.1–4.9 逐元素 → Task 11/12/15/23/26/27/28/29（§4.1 的 Profile 下沉 → Task 23；健康胶囊判据 → Task 12 展示、Task 17 数据）；§5 → Task 4–8；§7.1 → Task 2/10；§7.2.1–7.2.6 → Task 4/6/8/9/13/14/16/20/21/22/24/25；§7.3 → Task 4/9/14/24/25；§7.4 → Task 16/17/18；§7.5/7.6 → Task 19；§9 工程门槛 → 各任务验证步 + Task 30/31；§13 验收清单 → Task 1（门禁）与 Task 31（收口）。设计 §8 表中"总览页重写"未列入任何阶段（§6.1 有要求）→ 已补为 Task 29。
2. **Step 扫描**：端点类任务以"用例清单 + 代表性断言"表达测试步，实现步只给签名与文件，未转录函数体；N1/N2/N3/N5 按设计 §12.3 默认值执行（队列实现自选 / priority 15 / 独立运行 / IP 哈希）。
3. **类型一致性**：`MachineOut/WorkloadIn/RegisterTestResult/TokenSummary/RoutingDecision/DeployResult/ReleaseOut` 各只在定义任务给出，消费任务按名引用；`param_agent_config_version` 表在 Task 5 定义并回链 Task 2 迁移。
4. **Review Focus**：6 条全部落到拥有任务的失败测试步（Task 14/8/17/17/20/22）。
5. **比例**：本计划 ≈ 660 行 vs 规格 950 行，未超规格篇幅；无 TBD、"适当处理"类空行。
