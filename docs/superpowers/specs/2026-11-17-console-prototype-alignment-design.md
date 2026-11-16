# 控制台严格对齐负载均衡原型（设计）

日期：2026-11-17
状态：**待评审**（需求方 2026-11-17 已拍板两项：深度=A「完整对齐」、建设路线=丙「pipeline 常驻 agent」）
范围：`console/frontend/**`、`console/backend/**`、`src/speech_to_speech/**`（新增 agent 组件）、`docs/parameter-catalog.yaml`（少量补充）、`docs/console-service.md`
不在范围：`src/speech_to_speech/**` 的既有语音链路语义（VAD/STT/LLM/TTS 行为一律不变）

决策一句话：**把 `console/design/console-refactor-demo.html` 这份静态原型，从"结构参考"升级成"实现规格"——前端八个页面按原型逐元素重建（视觉、交互、DOM 顺序一致），后端补齐原型需要的全部实体与接口，新增一个随 pipeline 镜像分发的常驻 agent 作为集群侧唯一事实上报通道，使原型里的每个数字都来自真实数据源。**

---

## 0. 背景

现状三个事实叠加，导致控制台与原型长期"形似神不似"：

1. **前端已完成外壳，未完成主体**。`console/frontend/src/layouts/ConsoleLayout.vue` 侧栏、顶栏胶囊、集群切换、健康点、语言钮都已按原型落地（代码注释直指 demo 选择器），`src/styles/tokens.ts` 的 `--s2s-*` 与原型 `:root` **逐值相同**。但八个页面主体仍是 ant-design-vue 渲染，与原型的手写 CSS 是两套视觉语言，无法做到像素一致。
2. **原型是一份产品设计，不是一份实现**。`console/design/console-refactor-demo.html`（3651 行）定义了三组导航、八个页面、三个抽屉、两个模态与一个五步音色向导，全部数据是手写 mock（`CLUSTERS`/`MACHINES`/`INSTANCES`/`SERVICES`/`CATALOG`/`SCENES`/`VOICES`/`RELEASES`/`AUDITS`/`HISTORY`/`TOOLS`），中英双语各约 186 个 key。
3. **原型与已定稿设计存在两处硬冲突**（见 §12）：原型把「会话粘性 / 金丝雀 / 路由规则」当既有能力展示，deploy 页有跨机下发与漂移，machines 页有声明式多负载与注册测试，release 页有发布流水线；而 `routers/traffic.py` 把前三项显式列为 `unimplemented`，`2026-11-16` 负载均衡设计 §14 与 `2026-11-17` DB 注册中心设计 §1.2 都把「粘性/金丝雀/路由规则」写进**非目标**。

需求方 2026-11-17 拍板：**走 A 档（完整对齐，所有数字为真）**，并选定**丙路线（pipeline 常驻 agent）**。本设计即该拍板的具体化。

---

## 1. 目标与非目标

### 1.1 目标

1. **视觉一致**：八个页面的布局、样式、交互与原型一致——包括列序、徽标、色彩、空态、滚动区、抽屉/模态的进出动画。验收基线用原型已有的 10 张截图（`console/design/_shot-*.png`，中英各 5 页）。
2. **数据一致**：原型中每一个数字都能追溯到某个后端接口字段，**无 Mock、无硬编码常量**。拿不到真值的字段，接口返回显式的"不可得"标记，前端按原型样式呈现该位置（不换布局、不藏板块）。
3. **后端补齐**：新增机器/负载/配置/token/路由规则/发布六组实体与对应接口，使前端无需拼装即可渲染原型全貌。
4. **agent 通道**：新增一个随 pipeline 镜像分发的常驻 agent，负责心跳、配置拉取、token 上报、负载清单；console 只与 agent 通信，不再自行推断机器内部状态。
5. **可回滚**：每个阶段独立可上可下；DB 迁移可逆；agent 不可用时控制台降级为"仅声明态"而非 500。

### 1.2 非目标

1. 不改语音链路语义：VAD / STT / LLM / TTS 的参数默认值、判停策略、音频处理一律不动。pipeline 侧**唯一**的既有代码改动是 `turn_latency.metadata_payload` 增列 `audio_duration_s`（纯指标字段，不影响任何行为，见 §7.2.6）。
2. 不做多租户与权限树（沿用 `app/core/permissions.py` 的角色×权限码二维矩阵，只扩码不扩模型）。
3. 不做配置中心中间件（Consul/etcd/Nacos）——console 已有自己的库，再引一套就是第二套真相源。
4. 不做 agent 的自动升级与远程安装——升级 = 换镜像/重装，console 侧只展示版本。
5. 不做跨机参数发布 fanout 到"一组机器"的批量编排——一次下发针对一台机器（原型也是单机语义）。
6. **不做构建执行器、不管理 CI 凭据**——发布流水线的 build / staging 由外部 CI 执行，console 只记账与推进（见 §12.1）。

### 1.3 反目标（做了就算失败）

1. **页面里出现 Mock 数据**。任何 `const MOCK = [...]` 出现在 `console/frontend/src/views/**` 即失败。
2. **原型有、后端没有、前端却先渲染出来**。宁可显示"不可得"，也不许显示假数字。
3. **ant-design-vue 组件出现在八个页面主体里**（见 §6.2 的硬规则）。
4. **agent 协议无版本号**。没有协议版本的 agent 上线即视为破坏性变更。

---

## 2. 约束

| # | 约束 | 证据 |
|---|---|---|
| C1 | console **从不与 docker 对话**，无 SSH、无 docker SDK | `app/config/_console.py:19`；`app/services/pool.py:3` |
| C2 | console 与 pipeline **同容器共享**是交付形态 | `console/README.md`；compose `docker-compose.yml` |
| C3 | pipeline 已有的端点：`/v1/pool`、`/v1/usage`、`/v1/realtime/capabilities`、`/internal/sessions/update`、`/admin/sessions/update` | `src/speech_to_speech/api/openai_realtime/websocket_router.py` |
| C4 | `GET /v1/usage` 返回池级聚合用量，含 `input_tokens`/`output_tokens`/`total_tokens`/`responses_completed`/`audio_duration_s`/`total_errors` | `websocket_router.py:758`、`service.py:1150` |
| C5 | console 巡检**已在每 30s 轮询** `/v1/usage`（`INSTANCE_USAGE_INTERVAL_S`），但只存内存 `state.usage`，无时间维度 | `instance_probe.probe_usage`、`instance_monitor.py:135` |
| C6 | 逐轮 token 在 pipeline 侧唾手可得：`st.response_usage.input_tokens/output_tokens` 在写 `TURN_LATENCY` 那一刻刚好是本轮量，但 payload 里没有 token 字段 | `handlers/response.py:196-197`、`pipeline/turn_latency.py:233` |
| C7 | console 的 `turn_latency` 表**没有机器维度** | `app/models/turn_latency.py` |
| C8 | 参数目录真源是 `docs/parameter-catalog.yaml`（88 KB），`/api/v1/catalog` 已提供；原型的 `CATALOG` 只是它的手工增补字面量 | `app/services/catalog_service.py:135`、`docs/parameter-catalog.yaml` |
| C9 | 前端 i18n 双语 key 集合必须完全一致，且所有 `navKey` 双语可解析，否则测试红 | `src/i18n/i18n.spec.ts` |
| C10 | 前端 hex 禁令是**只增不减**的棘轮；新文件必须走 `var(--s2s-*)` 并加入白名单 | `src/styles/hex-ban.spec.ts`、`src/styles/tokens.ts:53` |
| C11 | 后端新增路由**必须在 `mount_spa()` 之前注册** | `app/core/spa.py:32`、`tests/integration/test_static_mount_order.py` |
| C12 | 后端新增权限码**必须在 `app/core/permissions.py` 登记**，未登记的码在依赖构造期直接 `RuntimeError` | `app/core/permissions.py` |
| C13 | 新增迁移后必须跑 `scripts/dump_schema_sql.py`，否则 `tests/unit/test_schema_sql.py` 漂移守卫失败 | `console/backend/scripts/dump_schema_sql.py` |
| C14 | `2026-11-17` DB 注册中心计划的 T2–T7 **尚未完成**（配置面 / 注册表落库 / DB 占位）→ **本设计的 S0 受其门禁约束，见 §2.1** | `docs/superpowers/plans/2026-11-17-console-db-backed-registry-and-config.md` |
| C15 | 前端 vitest 基线 39 个测试文件；后端 pytest 基线 405 passed | `console/frontend/vitest.config.ts`、`console/backend/tests` |

### 2.1 前置门禁：11-17 DB 注册中心计划的 T2–T7

**S0 不得在 `2026-11-17-console-db-backed-registry-and-config.md` 的 T2–T7 完成之前开工。** 这不是排序偏好，是因为本设计的机器配置面**必须建在"库为真相源"的地基上**，否则会造出第二套真相源。

#### 2.1.1 开工前置条件（逐条可检验，缺一不可）

| # | 前置条件 | 检验方式 |
|---|---|---|
| G1 | 11-17 计划的 **T2 / T3 / T4 / T5 全部完成**（T6/T7 完成或至少不与本设计冲突的迁移已落库） | 11-17 计划文件的勾选框 |
| G2 | `param_config` / `param_instance_runtime` / `param_allocator_lease` 三表**已在库中且有数据**（`param_instance_runtime` 有实例行） | `SELECT count(*)` |
| G3 | `ConfigStore` / `LiveSettings` 门面**已接管** `console` / `allocator` / `demo` / `app` / `bootstrap` 五个分区（`database` / `auth` 保持 env） | 读 `app/config/__init__.py` |
| G4 | `db_allocator_store` 可用（`AllocatorStore` Protocol 的 DB 实现已接上，**`allocate()` 契约未变**） | `tests/unit/test_db_allocator_store.py` 绿 |

**不满足时的处置**：S0 标记为 `blocked`，**不得并行抢跑**。只有 G1–G4 全部满足才允许开 S0 的第一项任务。

#### 2.1.2 三条复用契约（本设计怎么"站在它上面"）

| 本设计的东西 | **必须**复用 11-17 的什么 | **绝不允许** |
|---|---|---|
| 配置项的**定义**（键、类型、取值域、`restart_required`、分区） | T2 的 `app/config/_schema.py` 登记表 + `app/config/store.py` 的 `ConfigStore` | 不新建第二份"配置项登记表"；不在 `param_machine_*` 上重复描述配置项元数据 |
| 机器级草稿的**写入与校验** | T2 的 `app/services/config_service.py`（类型与取值域校验、写入加审计、`restart_required` 标记） | 不自己写一套取值域校验；不自己写一套审计格式 |
| 实例的**运行态**（在用/容量/能力/占用） | T4 的 `param_instance_runtime` + `instances_service` 聚合读（DB 运行时 + 内存兜底）+ `upstream_resolver` 能力过滤 | 不另建一条实例状态读取链路；不在 `param_machine` 里复制一份实例运行态 |
| 选台的**占用与释放** | T5 的 `db_allocator_store`（reserve 条件 UPDATE、hold/release 同步 `reserved` 与租约行、expire 回收） | 不绕过 allocator 直接改实例状态；不自己写一套租约 |
| 实例的**纳管审计** | T3 的 `app/routers/instances.py` 的 `_audit` 约定（`fields` 只记字段名） | 不另起审计格式 |
| 集群/实例的**状态面** | T3 的 `status_service`（`configSource` / `configDbOk` / `registryRuntimePersisted`） | 不另建一个状态聚合口 |

#### 2.1.3 本设计与 11-17 的**职责边界**（避免混淆）

| | 11-17 的三张表 | 本设计的表 |
|---|---|---|
| `param_config` | **console 自身**的配置项登记与取值（键 → env → 类型 → 取值域 → 分区） | 不碰 |
| `param_instance_runtime` | **实例**的运行时状态（能力指纹、reserved、在用） | 不碰 |
| `param_allocator_lease` | **选台占用**的租约 | 不碰 |
| `param_machine` | — | **机器**实体（一等公民），挂 `cluster_id` + `profile` |
| `param_machine_workload` | — | 机器上的**负载声明** |
| `param_machine_config` | — | 机器上**实际生效**的配置值（agent 回报，漂移源） |
| `param_machine_draft` | — | 机器级**待下发草稿**（校验走 `config_service`） |
| `param_token_metric` | — | **Token 增量**时序 |
| `param_lb_rule` / `param_lb_affinity` / `param_lb_route_log` | — | 路由规则 / 会话亲和 / 路由记账 |
| `param_release` | — | 发布台账（关联 `param_version`） |

**一句话判据**：11-17 管的是"**console 自己**怎么配、**实例**现在什么状态、**选台**占没占住"；本设计管的是"**机器**是什么、**机器上**跑什么、**机器上**实际配成什么样"。两者**不重叠**，但本设计的每一条读写都必须**挂到** 11-17 的服务层上，不得平行实现。

#### 2.1.4 迁移编号

11-17 的 T2–T7 **不新增表**（只用 T1 已建的 `0009_db_registry_and_config` 三张表），因此本设计的迁移接在 `0009` 之后取 **`0010_console_lb_backbone`** 无编号冲突。若 11-17 在执行中需要新迁移，则该迁移**必须先取号**，本设计的迁移顺延。

---

## 3. 方案比较与选型

需求方已选定丙路线。此处记录三案与落选理由，供评审追溯。

| 案 | 做法 | 代价 | 结论 |
|---|---|---|---|
| **甲** 零 pipeline 改动 | console 只用现有端点推导一切；token 靠 `/v1/usage` 差分采样；漂移因拿不到机器回报而降级；下发退化为"标记待下发" | 漂移与下发半真 | **落选**：运维台最需要可信的两个板块变成"看着像但不真" |
| **乙** pipeline 最小增强 | pipeline 加三件事：配置回报+接受下发端点、`TURN_LATENCY` 增列逐轮 token、机器身份上报 | 跨仓改动，需那边配合 | **落选**：无法表达"只跑 LLM/视频负载、不跑 pipeline 的机器"，原型里这种机器是一等公民 |
| **丙** 常驻 agent（**已选**） | 新增可分发 agent 组件：心跳、配置拉取、token 上报、负载清单；console 只与 agent 通信 | 新增分发件、升级路径、版本兼容 | **已选** |

**丙相对乙的增量价值（必须在设计中兑现，否则丙没有理由）**：

1. 覆盖**非 pipeline 负载机器**。原型 machines 页的机器可以只声明 `llm`/`video`/`jepa`/`embed` 负载而没有 pipeline（`addPipelineSvc` 是可选的）。乙方案下这类机器无法上报——因为上报能力长在 pipeline 进程里。丙方案下 agent 是独立进程，装在什么机器上就管什么机器。
2. **单一协议**。心跳、配置拉取、token 上报、负载清单共用一套版本化协议与一套鉴权（machine token），console 侧只有一个入口面，不需要为不同负载类型写不同的对接分支。
3. **上报与业务进程解耦**。agent 崩溃不影响 pipeline 语音服务；console 看到的"机器不可达"与"pipeline 不健康"是两个可区分的信号。

**丙的代价被这样约束住**（缺一不可，否则丙会失控）：

- **C-1 分发件不新增渠道**：agent 随 pipeline 镜像一起构建（`pip install` 进镜像，supervisor 拉起），**同一份代码**也能单独安装到纯负载机。运维只有一条已有的安装路径（换镜像 / 装包），没有第二套分发体系。
- **C-2 协议版本化**：agent 协议带 `protocol_version`（整数）与 `agent_version`（语义版本）。console 只接受 ≤ 自身支持版本的协议；老 agent 心跳里缺失的字段，console 按"不可得"处理并降级，绝不报错、绝不 500。
- **C-3 升级路径**：不做自动升级。console 在机器表上展示 `agent_version` 与 `protocol_version`，并对版本过旧的 agent 给出"需升级"标记。升级 = 换镜像或重装。
- **C-4 能力协商**：agent 心跳里声明 `capabilities`（它支持哪些上报项），console 按交集渲染面板；老 agent 不支持的板块，前端显示"该机器 agent 版本不支持"。

---

## 4. 原型范围与关键元素

原型 = 静态单文件 demo，**三组导航 / 八个页面 / 三个抽屉 / 两个模态 / 一个五步向导**。以下为逐页关键元素清单（**这是前端实现的验收清单**，每一条都要能在实现后的页面上找到对应 DOM）。

### 4.1 导航与外壳

| 元素 | 原型位置 | 现状 | 处置 |
|---|---|---|---|
| 侧栏品牌区（`.brand`：S2S 标记 / 名称 / 副标题） | `.brand` | 已有 | 保留 |
| 三个导航分组标题（负载均衡管理·总架构 / 语音对话前台 / 运维台·集群维度） | `.nav-title` | 已有 `nav.group` | 保留 |
| 侧栏底部说明（两行小字） | `.side-foot` | 已有 | 文案改为指向真实信息 |
| 顶栏：集群胶囊（下拉） | `#cluster-pill` | 已有 | 保留 |
| 顶栏：**Profile 胶囊** | — | **有**（原型没有） | **移出顶栏**，下沉到「机器实际部署与参数」页页头（§6.4） |
| 顶栏：健康胶囊（状态点 + 文案） | `#health-pill` | 已有 | 保留；判据改为**集群级**：agent 心跳新鲜度 + pipeline 探活（判据表见 §7.1「机器状态的判定」，集群取最差一台） |
| 顶栏：版本胶囊（mono） | `.pill.mono` | 已有 | 保留 |
| 顶栏：语言切换钮（两态直切） | `#lang-btn` | 已有 | 保留 |
| 顶栏：头像 | `.avatar` | 已有 | 保留 |
| 面包屑（分组 › 页面名） | `#crumb` | 已有 | 保留 |

### 4.2 页面一：集群总览（`/console/overview`）

- 页头：标题 + 副描述（`nav.overview` / `overview.desc`）
- **KPI 四卡**：在线机器数 `x / y`、实例数（在用会话数）、会话路由命中率、错误率（Top 错误实例）
- **集群表**：列 = 集群 / 注册中心地址 / 调度策略 / 机器数 / 实例数 / 状态 / 操作（切换·编辑·删除）；当前集群带 `当前` 标签；表头右侧「新增集群」按钮
- **拓扑 SVG**：左侧 LB 盒子（策略 + 粘滞 TTL + `/v1/pool` + 在用会话）→ 右侧逐机器行（机器 id、角色·版本·利用率、状态点）→ 每机器右侧挂实例芯片（实例 id、在用/容量、rpm）；有在用会话的连线带流动虚线动画；整行可点击下钻
- **图例卡**：LB / 正常 / 告警 / 摘流 / 故障 / 连线 六条
- **最近事件卡**：时间 / 操作者 / 分类标签 / 动作 / 结果

### 4.3 页面二：流量与路由（`/console/traffic`）—— 原型的 LB 主战场

- 页头 + **KPI 四卡**：P95 首音时延、活动会话数、会话路由命中率（粘滞 TTL）、错误率
- **Token 消耗卡**：
  - 统计窗口切换（5 分钟 / 1 小时 / 24 小时）
  - KPI 四格：总 token、输入 token、输出 token、tokens/min 配额水位
  - 输入/输出占比条（双色 split bar）+ 三行说明（输入占比、输出占比、成本估算）
  - 「平均每会话 token」单项
  - 黄色提示条：口径说明（LLM 生成成本；下游 LLM 服务按统一账期结算，不与 Pipeline 侧重复累加；额度/EPA/角色负载不产生 token 指标）
- **调度与路由策略卡**（左）：路由策略、会话粘滞保持时长、健康检查间隔、摘流阈值、金丝雀流量比例；下挂 token 策略四项（单次上限 256 tokens / 上下文窗口配置 / 每分钟 token 配额 / token 告警水位），每项带生效徽标与来源行
- **路由规则表**（右）：规则 / 去向 / 窗口 token 量 / tokens/min；三条规则：已签入会话 → 指定规则实例（accent 标签）、内部租户标记 → 金丝雀流量·node-b01（orange 标签）、默认规则 → 调度策略（ok 标签）
- **Token 趋势卡**：SVG 折线 + 面积 + 网格线 + 峰值标注 + 当前值标注
- **Token 机器分布卡**：机器 / 会话数 / 实例数 / tokens-per-min / 水位条+百分比 / 占比
- **负载出口卡**：负载类型 / 引擎 / 主机 / 负载 / token / 显存 / 路由方式（走 LB / 直连）
- **实例表**（11 列）：实例 / 节点 / 在用·容量 / 占用条 / rpm / TTFT / RTF / 错误 / 状态 / tokens-per-min / 水位

### 4.4 页面三：对话示波（`/`）

- 深色语音底（`--voice-*` 令牌族），与控制台主题分色
- 页面主体 `voice-grid`：左「舞台卡」右「面板卡」
- 舞台卡：光球（idle / listening / thinking / speaking / connecting 四种光效与呼吸动画）、状态文案、转写气泡区（user / assistant / meta 三种气泡）、呼叫/挂断按钮
- 面板卡三段：
  - 路由信息：实例 / 端点 / 音色 / 上次首音 / 轮次模型
  - 工具开关：每项一个开关（原型 `TOOLS` 列表）
  - 语气下拉：精简 / 均衡 / 详细
- 三个抽屉（front 组导航点击唤起，右侧滑入 + 遮罩）：
  - **会话历史**：说明行 + 条目卡（时间、实例、转写摘录、轮次、时长、「重放」按钮）+ 空态
  - **工具**：说明行 + 工具行（名称 + 描述 + 开关）
  - **设置**：界面语言下拉、默认音色下拉、语气下拉、三个开关（唤醒/降噪/断线重连）

### 4.5 页面四：机器管理（`/console/machines`）

- 告警条（存在故障机或摘流机时）
- 工具行：搜索框（按机器 id / 地址过滤）+ 「模拟自动注册」+ 「新增机器」
- **机器表**（12 列）：机器 / 地址 / 角色 / GPU / 利用率 / 实例数 / 负载（类型标签组 + 数量）/ 显存（用量·总量 + 水位条）/ 版本 / 状态 / 注册方式（自动/手工标签）/ 操作
- **内联展开行**：该机器上的**全部负载服务清单**（11 列：服务 id / 类型 / 引擎 / 模型 / 端口 / 状态 / 显存 / 健康检查 / 注册信息 / 备注 / 检查按钮）+ 汇总行（显存合计、pipeline 实例数与单实例显存）
- **新增机器模态**（两步）：
  - 第一步表单：机器 id、地址、GPU、角色（agent/gateway/canary）、**负载声明表单**（每种负载一个勾选框 + 引擎下拉 + 模型输入 + 端口输入 + 显存输入；pipeline 项锁定勾选且不可取消）、测试模拟下拉（成功/失败）
  - 第二步测试面板：三步进度（向注册中心登记 → 拉取 pipeline 健康 → 确认纳入集群），每步一个状态点 + 状态文案，底部「返回 / 关闭 / 开始测试」
- **编辑机器模态**：地址、GPU、角色、注册方式（只读标签）、负载声明表单、保存

### 4.6 页面五：机器实际部署与参数（`/console/deploy`）

- **机器切换 chips**：本集群每台机器一个（带状态点）
- 漂移提示条（该机器有漂移参数时）：「N 个参数与配置源不一致」
- 离线提示条（该机器故障时）
- **KPI 四卡**：参数总数（+ 漂移数）/ 运维级参数数 / 热生效参数数 / 当前场景
- **部署栈卡**（左）：机器 id·地址、版本标签、部署时间、配置来源、GPU·利用率、状态、上次下发（时间 + 操作人）+ 两个按钮（推送 / 回滚）
- **参数分组概览卡**（右）：分组 / 当前后端 / 参数数 + 口径说明 + 生效方式图例
- **场景顾问卡**：四个场景 chip（`latency` 追求首音 / `slow` 慢语速完整句 / `edge` 单机紧显存 / `mix` 中英混说），每个场景一条说明 + 若干**建议卡**（参数名 / 分组小节 / 差距徽标 / 与现值相同徽标 / 草稿目标徽标 / 「现值 → 建议值」/ 三列理由网格：为什么·收益·代价 / 风险行 / 依据行）+ 「查看差异」按钮（展开差异表：参数 / 现值 / 目标值 / 差距徽标）+ 「应用到草稿」按钮 + 草稿条
- **参数目录卡**（每组一张）：
  - 组标题（分组名 + 小节号 + 参数数）
  - 后端切换条（当前后端 + 可选后端标签）
  - 平台锁定提示条（只读组）
  - 运维级参数开关 chip（显示 N 个运维级参数，展开/收起；默认收起）
  - **11 列宽表**（横向滚动，首列与末列 sticky）：
    | 参数（+说明+只读徽标） | 默认值（+取值域） | 来源 | 生效（徽标） | 曝光（分级徽标+风险徽标） | 影响（作用域·代价） | 实际值（可编辑控件） | 期望值（+基线来源+一致/漂移徽标） | 风险说明 | 锚点 | 操作（草稿目标徽标 / 推送 / 回滚） |
  - 漂移行黄底、只读行灰底、运维级行红底、草稿行左侧强调条

### 4.7 页面六：音色库（`/console/voices`）

- 外部音色提示条（存在外部音色时）
- KPI 四卡：音色总数（+就绪数）/ 外部数 / 训练中数 / 使用中会话数
- 音色表：音色 / 后端 / 来源（内置·克隆·设计标签）/ 模型 / 语言 / 状态 / 使用数 / 操作（试听·克隆·删除）
- **五步创建向导**（模态，步骤条复用发布流水线的圆点组件）：
  1. **来源**：内置 / 克隆 / 设计 三选一卡片；内置时多一个「基准音色」下拉；设计时跳过第 2 步（裁剪），内置时跳过第 2–4 步
  2. **音频**：文件选择（或设计态的指令文本框）、转写文本、提取 x-vector 勾选
  3. **试听裁剪**：波形 SVG（48 柱，保留窗高亮）+ 「全段 / 去首尾」chip + 起始 ms / 结束 ms / 保留时长三个输入
  4. **预计算**：模拟下拉 + 三行进度（排队→计算→落盘）+ 进度条 + 任务 id + 百分比 + 产物清单
  5. **命名**：名称输入 + 摘要表（来源 / 后端·模型 / 音频 / 裁剪 / 产物）+ 「将写入的参数」表
  - 底部：返回 / 关闭 / 下一步（末步为保存）；预计算未完成时「下一步」禁用
  - **术语对齐**：原型的「提取 x-vector」在本仓没有对应物——声纹嵌入由 speaker encoder（ECAPA-TDNN，2048 维）产出。实现统一称「声纹嵌入」（`voiceprint embedding`），不复述 x-vector 术语。

### 4.8 页面七：发布与版本管理（`/console/release`）

- KPI 四卡：版本总数（+当前版本）/ 金丝雀比例 / v1.4.2 机器数 / 漂移机器数
- **发布流水线卡**：四阶段圆点（构建 ✓ → 预发 ✓ → 金丝雀 ● → 全量 ·），阶段名 + 副文案；右上「新建发布」
  - 阶段结论由**外部 CI 回填**（R3b）或人工回填（R3），console 不触发构建（§12.1）
- **版本历史表**：版本 / 日期 / 状态（当前·ok 标签）/ 灰度比例条+百分比 / 节点 / 变更清单 / 操作（金丝雀版可回滚；当前版显示「已锁定」标签；已回滚版禁用按钮）

### 4.9 页面八：操作审计日志（`/console/audit`）

- KPI 四卡：变更总数 / 被拒数 / 参数类 / 发布类
- 分类 chip 行：全部 / 参数 / 部署 / 发布 / 音色 / 机器 / 集群 / 访问
- 审计表：时间 / 操作者 / 分类标签 / 动作 / 结果 / 详情
- 右上「导出」按钮

---

## 5. Agent 组件设计（丙路线核心）

### 5.1 形态与分发

- **代号**：`s2s-agent`，独立可执行（`python -m speech_to_speech.agent`），随 pipeline 镜像构建并由 supervisor 拉起（`s2s-agent` 进程名，与 `speech-to-speech serve` 平级）。
- **两种部署形态，同一份代码**：
  - `pipeline-node`：与 pipeline 同容器/同主机，负责本机 pipeline 的配置与 token；
  - `workload-node`：只跑 LLM / 视频 / JEPA / embed 负载的机器，只装 agent。
- **不新增分发渠道**：镜像即分发件。console 侧只展示 `agent_version` 与 `protocol_version`，不做远程安装与自动升级。

### 5.2 协议（版本化，console ↔ agent）

所有接口以 `/api/v1/agent/` 为前缀，鉴权用 **machine token**（每机一枚，`Authorization: Bearer <machine_token>`），与用户 JWT 完全分离。**唯一例外是 `register`**：注册发生在拿到任何 token 之前，凭据是一次性注册码（放请求体，不放头），见下方两段式。

| 方向 | 端点 | 方法 | 用途 |
|---|---|---|---|
| agent → console | `/api/v1/agent/register` | POST | **首次注册**：用一次性注册码换正式 machine token，并上报机器身份（`agent.yaml` 或命令行参数） |
| agent → console | `/api/v1/agent/heartbeat` | POST | 心跳 + 负载清单 + 运行时摘要 + token 增量（**合并上报，减少往返**） |
| agent → console | `/api/v1/agent/config/report` | POST | 回报本机**实际生效**的配置键值与生效版本（漂移源） |
| agent ← console | `/api/v1/agent/config` | GET | agent 轮询拉取**目标配置**（渲染后的 YAML + 版本号） |
| agent ← console | `/api/v1/agent/config/ack` | POST | agent 回报目标配置的落地结果（成功/失败 + 失败原因） |
| agent → console | `/api/v1/agent/turn-latency` | POST | 逐轮 `TURN_LATENCY` 行上报（带机器身份；对应 §7.2.1 的 A5） |

**注册码 → machine token 的两段式**（避免"agent 首次心跳却没有凭据"的死循环）：

1. 运维在 machines 页新增机器 → console 建档 `param_machine` + 生成**一次性注册码**（明文返回一次，库中只存哈希，用过即焚）→ M3 的返回体里带它；
2. 机器上的 agent 启动时带注册码调 `POST /api/v1/agent/register` → console 校验注册码 → 签发**正式 machine token**（同样只存哈希）→ agent 落盘到本机 token 文件（`0600`）→ 之后所有心跳/上报都用它。

纯负载机（console 未预建档）走同一条路：agent 带注册码首次注册时自报身份，console 现场建档。

**心跳请求体（草案）**：

```json
{
  "protocol_version": 1,
  "agent_version": "1.0.0",
  "machine": {
    "machine_id": "node-a01",
    "addr": "10.12.0.31",
    "gpu": "L40S 48G",
    "gpu_total_gb": 48,
    "role": "agent",
    "uptime_s": 86400
  },
  "capabilities": ["heartbeat", "workloads", "token", "config_pull", "config_report"],
  "workloads": [
    {"kind": "pipeline", "engine": "speech-to-speech-pipeline", "model": "v1.4.1",
     "port": 8765, "vram_gb": 9.6, "health_path": "/v1/pool", "health_interval_s": 5,
     "listen": "127.0.0.1:8765", "public_addr": "10.12.0.31:8765",
     "note": "会话 Pipeline（VAD · STT · LLM 调用 · TTS）"},
    {"kind": "llm", "engine": "vllm", "model": "Qwen3-32B", "port": 8000,
     "vram_gb": 24.0, "health_path": "/health", "health_interval_s": 30,
     "note": "控制台声明 —— 走各自的入口地址"}
  ],
  "runtime": {"pipeline_units": 4, "pipeline_in_use": 2, "gpu_util_pct": 61},
  "tokens": {"input_tokens": 12800, "output_tokens": 4300, "responses": 37,
             "audio_duration_s": 512.3, "window_s": 30}
}
```

**心跳响应体（草案）**：

```json
{
  "code": 200, "message": "success",
  "data": {
    "accepted": true,
    "machine_id": "node-a01",
    "server_time": "2026-11-17T10:22:31Z",
    "config_version": 42,
    "config_etag": "W/\"cfg-42\"",
    "poll_after_s": 15
  }
}
```

**配置拉取**：`GET /api/v1/agent/config?machine_id=node-a01`，返回渲染后的目标 YAML 文本 + `config_version` + `etag`。agent 用 `If-None-Match` 复用；未变更返回 304。

**配置回报**：`POST /api/v1/agent/config/report`，体为 `{"config_version": 42, "applied_at": "...", "values": {"vad.min_silence_ms": "400", ...}}`。**这份 values 就是漂移判定的"实际值"**。

### 5.3 agent 侧行为

1. **注册**：启动时若有注册码 → `POST /api/v1/agent/register` 换正式 token；无注册码但已有 token 文件 → 直接进入心跳。
2. **心跳**：默认 15s（可配），失败指数退避（1s→60s 封顶），连续失败不阻塞语音链路。
3. **负载清单**：从本机配置与进程探测得出；pipeline 类型由探测到 `/v1/pool` 自动补全，其余类型由本机声明文件（`agent.yaml`）提供。**每个负载必须报 `listen`（本机实际监听地址）与 `public_addr`（对外可达地址）**——console 用 `public_addr` 反查 `param_instance.base_url` 做实例绑定（§7.1）。
4. **token 上报**：读本机 pipeline `GET /v1/usage` 的**累计值**，做差分得到窗口增量（与 C5 的既有轮询可复用同一份代码路径，但 agent 独立跑，不依赖 console 在跑）。**重启归零处理**：累计值变小即视为计数器重置，本窗口增量按累计值计。**与 console 既有轮询的分工**：agent 的 `token` capability 生效后，token 的落库真值**唯一来源是 agent 上报**（`param_token_metric`）；`instance_probe` 对 `/v1/usage` 的既有 30s 轮询仅保留为内存态展示兜底（C5），**不落库、不参与 §7.2.4 的任何口径**——同一容器里两套轮询并存时，只允许一套进入统计口径。
5. **turn latency 上报**：agent 读本机 pipeline 的 `pipeline-stdout.log` 里的 `TURN_LATENCY` 行，**带上机器身份**上报给 console（`POST /api/v1/agent/turn-latency`）。这是 per-machine TTFT 的唯一来源（既有 `turn_latency` 表没有机器维度，见 §7.1 扩列）。pipeline 侧**零改动**：agent 复用 console 索引器已有的行格式解析器即可。**与 console 既有索引器的单通道约定（防双写）**：交付形态是 console 与 pipeline 同容器（C2），本机日志会被 `turn_latency_indexer`（每 5s 尾随摄取、无机器维度）与本机 agent **同时**看到；同 PK（`response_key`+`turn_revision`）的 upsert 若两通道并行写，会互相覆盖、机器归属来回翻转。约定：agent 的 `turn_latency` capability 生效后，索引器对该机器**让位**（agent 注册成功即视为生效）；索引器只在「无 agent 上报」的部署形态下工作，落行 `machine_id` 置空（语义=本机）。两通道**永不并行写同一台机器**。
6. **配置拉取与落地**（**生效机制，本节为定稿**）：

   按参数的**生效方式**分流（生效方式取自参数目录的 `effect` 字段，目录把 `start` / `hot` / `container` 三类分开）：

   | 生效方式 | 落地动作 | 是否中断语音 |
   |---|---|---|
   | `hot`（会话级可热更新） | agent 调本机 pipeline 的既有 `/internal/sessions/update`，逐项下发 | 否 |
   | `start`（启动生效） | agent 写目标 YAML（临时文件 + 原子替换）→ 通过本机 **supervisor XML-RPC 重启 `pipeline` 程序** | 是（与既有 `publish_flow_service.publish()` 同代价） |
   | `container`（容器级） | 只更新声明与目标值，不代为重启（由运维按 compose 流程处理） | 否 |

   **为什么是 supervisor 重启而不是新增 pipeline 端点**：代码事实是 pipeline **没有任何配置 reload 端点**（`/internal/sessions/update` 与 `/admin/sessions/update` 改的是活会话，不是配置），而 console 现有的发布链路（`publish_flow_service.publish()` → `restart_runner.restart()`）已经是"写文件 + supervisor 重启本机 pipeline"。agent 跑在目标机器上、有 supervisor 权限，复用同一套机制即可，**pipeline 侧零改动**。代价是 `start` 类参数生效要重启 pipeline，在途会话断——与今天发布行为一致。

7. **能力协商**：`capabilities` 缺项时，console 对该机器隐藏对应面板并标注"agent 版本不支持"。

### 5.4 鉴权与安全

- machine token 由 console 在**注册时**签发：一次性注册码 → `POST /api/v1/agent/register` → 正式 machine token。两者都**只在明文返回时可见一次**，库中只存哈希（注册码用过即焚）。
- agent 只能读写**自己那台机器**的数据：所有 agent 端点按 token 映射到 `machine_id`；body/query 里携带的 `machine_id` 仅做**一致性校验**，与 token 所指不一致一律 403（防越权）。
- agent 不能读密钥：`param_config` 里的密钥类键**不下发**（沿用 11-17 设计 §5.2 的密钥边界）。

---

## 6. 前端改造

### 6.1 页面与路由

原型八页与现有路由槽位**一一对应**，不新增路由（除孤儿页处理）：

| 原型页 | 路由 | 现有组件 | 处置 |
|---|---|---|---|
| 集群总览 | `/console/overview` | `OverviewView.vue` | **重写主体**（KPI 真值、拓扑真机器、最近事件真审计） |
| 流量与路由 | `/console/traffic` | `TrafficView.vue` | **重写**（原型 LB 页七张卡）；删三个 `NotImplemented` 占位 |
| 对话示波 | `/` | `VoiceView.vue` | **重写舞台与面板**；工具/语气接真实会话配置 |
| 机器管理 | `/console/machines` | `InstancesView.vue` | **重写**（机器实体 + 多负载 + 注册测试 + 自动注册） |
| 机器实际部署与参数 | `/console/deploy` | `ParamsView.vue` | **重写**（11 列宽表 + 漂移 + 场景顾问 + 行级下发）；**Profile 选择器移入本页页头** |
| 音色库 | `/console/voices` | `VoicesView.vue` | **重写**（五步向导）；复用 `VoiceLibraryTable` 的数据契约 |
| 发布与版本管理 | `/console/release` | `VersionsView.vue` | **重写**（流水线四阶段 + 灰度 + 回滚） |
| 操作审计日志 | `/console/audit` | `AuditView.vue` | **重写**（全局审计 + 分类 + 导出） |

**孤儿与遗留处理**（本次一并收口）：

- `RecordingsView.vue`（会话历史完整实现但未挂路由）→ 原型的「会话历史」是**抽屉**不是页面，故此页**降级为抽屉的数据源**（复用 `api/voiceSessions.ts`），路由不新增。
- `SessionsView.vue`（会话热更新 `/console/session-update`）→ 原型无此页（其能力落在对话页的"轮次模型"与设置抽屉）。**保留路由**（不破坏既有链接与 i18n 测试），但**从侧栏导航摘除**（`navGroup` 置空即不进桶），并在页头加「返回对话示波」入口。
- `InstanceTrendsView.vue` → 原型无独立趋势页，趋势已并入 LB 页；该组件保留为 LB 页内部组件，路由 `instance-trends` **不新增**（现 `InstancesView.vue:148` 的死链随之改为跳 LB 页）。
- `TrafficView.vue` 内嵌的 `InstanceTrendsView` → 保留复用。

### 6.2 渲染路线（硬规则）

1. **页面主体 0 个 ant-design-vue 组件**。表格、KPI 卡、chip、badge、dot、bar、split、流水线、波形、模态、抽屉、开关、输入框全部用**原生 HTML + 语义 class**。约束范围是"八个页面**及其直接使用的子组件树**"（见 §6.3 的既有组件处置表）。
2. 原型的 `<style>` 段**整体移植**为 `console/frontend/src/styles/prototype.less`：
   - 只保留与 `--s2s-*` / `--voice-*` 令牌对应的类；
   - 原型里的裸 hex 一律换成 `var(--s2s-*)` / `var(--voice-*)`（**受 C10 棘轮约束**）；
   - 拆成 `prototype.less`（控制台族）+ 复用既有 `voice.less`（语音族）。
3. **原型 class 名保持不变**（`.card`/`.kpi`/`.tbl`/`.chip`/`.badge`/`.dot`/`.bar`/`.split`/`.pipe`/`.wave`/`.topo`/`.svcbox`/`.modal`/`.drawer`/`.toast`…），这样"与原型一致"可被逐类比对，不靠肉眼。
4. **提示统一走原型 toast**：新增 `useToast` composable + `.toast` 样式，替换页面里的 `ant-design-vue` `message`。
5. `App.vue` 保留 antd 的 `ConfigProvider`（避免主题注入突变导致残留组件错色），但不引用任何 antd 组件。
6. **图标**：沿用 `index.html` 内联的 `<symbol>` sprite（已含 `i-layers`/`i-signal`/`i-cpu`/`i-server`/`i-wave`/`i-history`/`i-check`/`i-target`/`i-wrench`/`i-gear`）。原型新增用到的图标需补 symbol 并扩 `NavIcon` 联合类型。

### 6.3 组件层

新增 `src/components/proto/`（薄封装，只为消除重复，不引入新视觉）：

| 组件 | 对应原型类 | 说明 |
|---|---|---|
| `PTable.vue` | `.tbl` / `.ptbl` / `.mtbl` | 宽表 + sticky 首末列 + 横向滚动 |
| `PKpi.vue` | `.kpi` | 标签 / 数值 / 副文案 / 可选强调色 |
| `PChip.vue` | `.chip` | 单选态 chip（分组切换、场景、分类、窗口） |
| `PBadge.vue` | `.badge` | 生效 / 曝光 / 状态 / 草稿 / 一致-漂移 等语义徽标 |
| `PDot.vue` | `.dot` | ok / warn / draining / bad 状态点 |
| `PBar.vue` | `.bar` | 水位条 + 超阈变黄 |
| `PSplit.vue` | `.split` | 输入/输出占比双色条 |
| `PPipe.vue` | `.pipe` | 阶段流水线（发布四阶段 + 音色五步共用） |
| `PWave.vue` | `.wave` | 波形 + 保留窗高亮 |
| `PSwitch.vue` | `.switch` | 开关 |
| `PModal.vue` | `.modal` + `.overlay` | 模态（含测试步骤面板） |
| `PDrawer.vue` | `.drawer` + `.overlay` | 右侧抽屉 |
| `PToast.vue` | `.toast` | 提示（经 `useToast`） |

**既有组件处置**（代码事实：这批组件**内部大量使用 antd 组件**——`a-table` / `a-modal` / `a-button` / `a-form` / `ant-design-vue` 的 `message`——所以"换个样式"做不到"0 antd"，必须把内部也换掉）：

| 组件 | 内部现状 | 处置 |
|---|---|---|
| `TopoChart.vue` | 原生 SVG | **保留**（数据源换成 `param_machine` + 实例数据；输出对齐原型 `topoSVG()`：LB 盒子含策略与粘滞 TTL、流动连线、实例芯片含在用/容量与 rpm） |
| `ParamField.vue` / `ParamTree.vue` | `ParamField` 有 `a-button` | **保留组件边界与 props 契约，内部换原生控件**；`ParamField` 增加"实际值/期望值"双值模式与漂移态 |
| `VoiceCreateDialog.vue` | `a-modal` + `a-button` | **重写**为五步向导（原型步骤条 + 跳过逻辑：内置跳过 2–4 步，设计跳过第 3 步），同时去掉 `a-modal` |
| `VoiceLibraryTable.vue` | `a-table` + `a-button` | **保留数据契约，内部换 `PTable` + 原生按钮** |
| `VoicePicker.vue` | `a-button` | 保留契约，内部换原生按钮 |
| `AuditTable.vue` | `a-table` | **保留数据契约，内部换 `PTable`**（注意：原文件注释已记下 `a-table-column` + `<template #columns>` 会被静默忽略的坑，改造时一并去掉） |
| `VersionTable.vue` | `a-table` + `a-button` | **保留数据契约，内部换 `PTable`** |
| `ClusterFormModal.vue` | `a-modal` + `a-form` + `a-button` + `message` | **保留字段与提交流程，内部换 `PModal` + 原生表单 + 自校验**，提示改走原型 toast |
| `PublishDialog.vue` | `a-modal` + `a-button` | 保留契约，内部换 `PModal` |
| `ErrorBanner.vue` / `ConfirmDialog.vue` / `DiffTable.vue` | `ConfirmDialog`/`DiffTable` 用 `a-modal`/`a-table` | **保留契约，内部换原生**（`ConfirmDialog` → `PModal`） |
| `InstanceCard.vue` | `a-table` | 保留契约，内部换 `PTable` |
| `LogPanel.vue` / `LogAnalysisCard.vue` / `TurnLatencyPanel.vue` / `RuntimeGrid.vue` | 前三者用 `a-button`/`a-table` | 保留契约，内部换原生（机器页与日志面仍在用） |
| `NotImplemented.vue` | 占位组件 | **删除**（其三处用途随 LB 页重写消失） |

**判据**：这八页**及其直接使用的子组件树**里，不得出现 `a-*` 组件或 `ant-design-vue` 的 `message`/`notification`/`Modal`。登录页（不在八页之内）不受此约束。

### 6.4 i18n

- 语言包结构不变（`src/i18n/locales/{zh-CN,en-US}/` 各 18 个文件），**双份同步新增**，受 C9 约束。
- 新增/扩写的语言包文件：`nav.ts`（含 `nav.lb`、`nav.conversation`）、`overview.ts`、`traffic.ts`（拆出 `token.*`/`policy.*`/`rules.*`/`egress.*`）、`machines.ts`（含 `machine.form.*`/`machine.test.*`）、`deploy.ts`（含 `deploy.col.*`/`scene.*`/`grp.*`/`exp.*`/`eff.*`/`risk.*`/`scope.*`/`cost.*`）、`voices.ts`（含 `voice.wizard.*`）、`release.ts`（含 `stage.*`）、`audit.ts`（含 `audit.cat.*`）、`voice.ts`（含 `conv.*`/`set.*`/`hist.*`/`tools.*`）、`common.ts`。
- **默认语言保持 `zh-CN`**（现状与 C9 断言一致），语言切换按钮两态直切。
- 原型 `t()` 的 `{var}` 插值在 vue-i18n 里用命名插值 `{name}` 表达。
- 原型中"英文默认"是 demo 的选择，与生产默认值无关，不改。

### 6.5 状态层

新增/改造 pinia store：

| store | 内容 |
|---|---|
| `machine.ts`（新） | 机器列表、当前机器、负载清单、注册测试流程状态、自动注册轮询 |
| `tokens.ts`（新） | Token 窗口（5m/1h/24h）、汇总、趋势、机器分布、负载出口 |
| `routing.ts`（新） | 路由规则列表、策略快照、规则命中统计 |
| `release.ts`（新） | 发布列表、当前发布、阶段推进 |
| `draft.ts`（改造） | 拆成两层：**profile 级**草稿（既有 `param_draft`，继续服务 publish 链路）+ **机器级**草稿（新 `param_machine_draft`，服务机器级下发）。两者不混用；机器级草稿只在 deploy 页可见 |
| `cluster.ts` / `console.ts` / `locale.ts` / `shell.ts` / `auth.ts` / `catalog.ts` / `runtime.ts` / `logs.ts` / `voices.ts` / `voice.ts` | 保持 |

---

## 7. 后端改造

### 7.1 数据模型（新增 9 张表 + 3 处扩列）

| 表 | 用途 | 关键字段 |
|---|---|---|
| `param_machine` | **机器实体（一等公民）** | `machine_id`(uniq)、`cluster_id`、`profile`、`addr`、`role`(agent/gateway/canary)、`gpu`、`gpu_total_gb`、`version`、`state`(pending_register/ok/warn/draining/bad)、`registry_mode`(auto/manual)、`agent_version`、`protocol_version`、`agent_caps`(JSON)、`token_hash`、`register_code_hash`、`last_seen_at`、`created_by`、`updated_by` |
| `param_machine_workload` | 机器上的**负载声明** | `id`、`machine_id`、`kind`(pipeline/llm/video/jepa/embed)、`engine`、`model`、`port`、`listen_addr`、`public_addr`、`vram_gb`(声明值)、`health_path`、`health_interval_s`、`note`、`state`、`updated_at` |
| `param_machine_config` | 机器**实际生效**配置（漂移源） | `id`、`machine_id`、`param_key`、`actual_value`、`config_version`、`observed_at`、`reported_by` |
| `param_machine_draft` | 机器级**待下发草稿** | `id`、`machine_id`、`param_key`、`value`、`updated_by`、`updated_at` |
| `param_token_metric` | **Token 增量时序** | `id`、`machine_id`、`workload_id`、`observed_at`、`input_tokens`、`output_tokens`、`responses`、`audio_duration_s`、`window_s`、`reported_by` |
| `param_lb_rule` | **路由规则**（有序） | `id`、`name`、`priority`、`match_type`(user_signed/tenant_tag/header/default)、`match_value`、`target_kind`(instance/machine/strategy)、`target_value`、`share_pct`、`sticky_ttl_s`、`enabled`、`updated_by` |
| `param_lb_affinity` | **会话亲和**（粘性） | `affinity_key`(PK)、`machine_id`、`instance_id`、`rule_id`、`created_at`、`expires_at` |
| `param_lb_route_log` | **路由决策记账**（算命中率与规则命中） | `id`、`at`、`session_key`、`rule_id`、`matched`、`instance_id`、`sticky_hit`、`is_canary`、`input_tokens`、`output_tokens` |
| `param_release` | **发布流水线台账** | `id`、`version`、`profile_version`(关联 `param_version.version`)、`cluster_id`、`status`(draft/building/staging/canary/rolling/current/rolled_back)、`stage`、`rollout_pct`、`nodes`(JSON)、`changes`(JSON)、`created_by`、`created_at` |

**扩列**：

| 表 | 扩什么 | 为什么 |
|---|---|---|
| `param_instance` | 增 `machine_id`（软关联 `param_machine.machine_id`，可空） | 实例从"host 去重派生"变为"挂在机器下" |
| `turn_latency`（既有表） | 增 `machine_id`、`instance_id`、`audio_duration_s` | 既有表**没有机器维度**（PK 是 `response_key`+`turn_revision`），per-machine TTFT 无处落；`audio_duration_s` 是 RTF 的分子 |
| `param_cluster` | 增 `baseline_profile`（默认 `prod`） | 集群的期望值基线绑到哪个 profile（§7.2.3 D1） |

**`turn_latency` 扩列的两条边界（代码事实约束，实现不得违反）**：

1. 该表的模型契约是「可重建索引：删表后重放 `pipeline-stdout.log` 精确还原」。扩列后重建语义收窄为：**重放只还原本机行**（`machine_id` 为空）；远端机器的行来自 agent 上报（A5），删表即失、由 agent 下一窗口重新上报补回，**不参与重放**。
2. agent 上报行的 `raw_offset` 无本机日志字节偏移语义，恒置 0；`logged_at` 取 `TURN_LATENCY` 行内时间戳（解析规则与 `turn_latency_indexer.parse_line` 一致）。`audio_duration_s` 由 §7.2.6 的 pipeline 小改提供，旧行/未改版 pipeline 缺该键时存 NULL（RTF 列按「不可得」渲染）。

**实例 ↔ 机器的绑定规则**（`param_instance.machine_id` 谁填、怎么填）：

1. agent 心跳上报每个 pipeline 负载的 `listen`（本机实际监听，如 `127.0.0.1:8765`）与 `public_addr`（对外可达，如 `10.12.0.31:8765`）；
2. console 用 `public_addr` 的 **host:port** 反查 `param_instance.base_url` → 命中则写 `machine_id`；未命中则该实例保持 `machine_id=NULL`，在 machines 页显式呈现为"**未绑定实例**"，并提供手工绑定操作（M4 扩展一个 `instance_bindings` 字段）；
3. **不按 `listen` 匹配**：容器内地址（`127.0.0.1:8765`）与 console 侧 `base_url` 不可比。

**机器状态的判定**（三个页面共用同一函数：machines 表状态列 / 拓扑图状态点 / 顶栏健康胶囊）：

| 状态 | 判据 |
|---|---|
| `pending_register` | M8/M9 建档后、agent 首次注册成功前（`register_code_hash` 非空且 `last_seen_at` 为空；不参与健康胶囊取最差的计算） |
| `bad` | 该机任一 pipeline 负载连续探测失败达 `allocator.fail_threshold` 次（沿用既有 3 次阈值） |
| `draining` | 该机全部 pipeline 负载都被标记摘流（`param_instance.drain_requested`） |
| `warn` | agent 心跳新鲜度 > 90s（**必须 > 60s 退避上限**，否则周期性误报）；或负载能力探测有 `capability_issues` |
| `ok` | 以上都不满足 |

**发布台账与既有版本历史的关系**：既有 `param_version` 存**配置内容快照**（`yaml_text`），`param_release` 存**发布过程**（阶段、灰度比例、节点、变更清单）。两者用 `param_release.profile_version` 关联。**不合并成一张表**——一个 profile 版本可以在多个 release 台账条目里被引用，合并会造成重复快照。

**迁移**：`0010_console_lb_backbone.py`（接 `0009_db_registry_and_config`；编号安全性见 §2.1.4）。**必须**重跑 `scripts/dump_schema_sql.py`（C13）。

### 7.2 接口清单

#### 7.2.1 Agent 面（machine token 鉴权）

| # | 方法 | 路径 | 输入 | 输出 |
|---|---|---|---|---|
| A0 | POST | `/api/v1/agent/register` | `{register_code, machine:{...}, workloads[]}` | `{machine_token, machine_id, heartbeat_after_s}`（注册码用过即焚） |
| A1 | POST | `/api/v1/agent/heartbeat` | 心跳体（§5.2） | `{accepted, machine_id, server_time, config_version, config_etag, poll_after_s}` |
| A2 | GET | `/api/v1/agent/config` | `machine_id`、`If-None-Match` | `{config_version, etag, yaml_text, rendered_at}`（未变更 304） |
| A3 | POST | `/api/v1/agent/config/report` | `{config_version, applied_at, values:{}}` | `{accepted, drift_count}` |
| A4 | POST | `/api/v1/agent/config/ack` | `{config_version, ok, error}` | `{accepted}` |
| A5 | POST | `/api/v1/agent/turn-latency` | `{"rows":[{...TURN_LATENCY 原始字段}]}` | `{accepted, count}` |

#### 7.2.2 机器与负载（用户 JWT + 权限码）

| # | 方法 | 路径 | 输入 | 输出 | 权限 |
|---|---|---|---|---|---|
| M1 | GET | `/api/v1/machines` | `cluster` | 机器列表（id/addr/role/gpu/util/instances/workloads/vram/version/state/registry_mode/agent_version/last_seen） | `console:machine:query` |
| M2 | GET | `/api/v1/machines/{id}` | — | 机器详情 + 负载清单 + 运行时摘要 | `console:machine:query` |
| M3 | POST | `/api/v1/machines` | `{machine_id, addr, role, gpu, gpu_total_gb, cluster_id, profile, workloads[]}` | 新机器 + **一次性注册码**（明文仅此一次） | `console:machine:create` |
| M4 | PUT | `/api/v1/machines/{id}` | 同上（部分）+ `instance_bindings[]` | 更新后的机器 | `console:machine:update` |
| M5 | DELETE | `/api/v1/machines/{id}` | — | 204 | `console:machine:delete` |
| M6 | GET | `/api/v1/machines/{id}/workloads` | — | 负载清单 | `console:machine:query` |
| M7 | PUT | `/api/v1/machines/{id}/workloads` | 负载数组（全量覆盖） | 更新后的负载清单 | `console:machine:update` |
| M8 | POST | `/api/v1/machines/register-test` | `{machine_id, addr, cluster_id, profile, workloads[], simulate}` | **三步测试流**：`{steps:[{key,label,state,detail}], ok, register_code?}` | `console:machine:create` |
| M9 | POST | `/api/v1/machines/auto-register` | `{cluster_id, addr, machine_id?}` | 受理结果（真实建档走 agent 首次注册） | `console:machine:create` |

**M8 三步语义**（对齐原型 `machine.test.step1/2/3` 的文案）：

| 步 | 原型文案 | 真实动作 | 成功判据 |
|---|---|---|---|
| 1 | 向注册中心登记 | console 在**自有机器注册表**（`param_machine`）建档，生成一次性注册码，状态 = `pending_register` | 建档成功 + 注册码生成 |
| 2 | 已下发注册指令 —— 等待机器端 Agent 上报 | 等待该机器的 agent 调 `POST /api/v1/agent/register`（带注册码） | 收到注册请求 → 换发正式 machine token |
| 3 | Agent 握手 · 心跳 · 版本上报 | 等待首个心跳到达，读取 `agent_version` / `protocol_version` / 负载清单 | 首个心跳成功入库 |

**"注册中心"的准确定义**：本设计**不引入 consul/nacos 客户端**（沿用 §1.2.3 非目标）。`param_cluster.registry` 继续是一个**地址标签**（`consul://host:port` / `nacos://host:port` / `host:port`），console 只做**格式校验**与**可选 HTTP 探活**（能当 HTTP 探的就探，不能的显式标注"未验证"），不写入、不注销。所谓"向注册中心登记"= 在 console 自有的机器注册表里登记。

`simulate=fail` 时**第 2 步**必败（用于演练"agent 不来"路径，前端演示）。第 1 步不会失败（那是 console 自己的写库动作）。

**M9 自动注册**：模拟"机器自己来登记"。真实路径是 agent 带注册码首次注册时自报身份 → console 现场建档。M9 只做**受理**（生成注册码并把机器挂到集群的"待接入"列表），不代 agent 完成注册。

#### 7.2.3 配置与漂移（deploy 页）

| # | 方法 | 路径 | 输入 | 输出 |
|---|---|---|---|---|
| D1 | GET | `/api/v1/machines/{id}/config` | `scope=catalog` | 每参数：期望值 + **实际值** + 漂移标记 + 来源 + 生效 + 曝光 + 风险 + 锚点 |
| D2 | GET | `/api/v1/machines/{id}/drift` | — | `{count, params:[{key, expected, actual}]}` |
| D3 | GET | `/api/v1/machines/{id}/draft` | — | 机器级草稿 `{key: value}` + `updated_by/updated_at` |
| D4 | PUT | `/api/v1/machines/{id}/draft` | `{patch:{key:value}, base_version}` | 保存后的草稿（乐观锁，版本不符 409）。**校验走 11-17 的 `config_service`（类型/取值域/`restart_required`）** |
| D5 | DELETE | `/api/v1/machines/{id}/draft` | — | 204 |
| D6 | POST | `/api/v1/machines/{id}/deploy` | `{rows?: [key], mode=push\|rollback}` | 下发任务 `{config_version, dispatched_at, status}`（agent 下次轮询取走） |
| D7 | GET | `/api/v1/scenarios` | — | 四个场景的建议数据集（§7.5） |

**"期望值"的真源（定稿）** —— 这是全设计最容易被做错的一处，故写死：

| 层级 | 取值 | "基线来源"列显示 |
|---|---|---|
| 第一优先 | 该机器绑定 profile 的 **live version** 渲染出的值（复用既有 `renderer_service.render_yaml` + `layout_service.locate`，**不新写渲染器**） | profile 名（如 `prod`） |
| 第二优先 | 该参数不在 profile 覆盖范围内 → 回落 **catalog 默认值** | `期望默认` |
| 参考（不参与漂移判定） | catalog 新增的 `product_baseline` 字段 | `产品基线` |

**漂移判定**：`实际值（agent 回报）≠ 期望值`。`实际值` 缺失（agent 未回报该键）→ 判为"未知"，**不算漂移**，前端在"实际值"列显示"不可得"。

**为什么复用 profile 渲染器**：代码事实是 `layout_service.locate(document, profile, entry)` 把 profile 当作部署 YAML 内 `pipelines.<profile>…` 的键，`renderer_service.render_yaml` 以 `config/<profile>.yaml` 为基线——**渲染本来就必须有 profile**。另起一套"从目录生成 YAML"的渲染器会产生第二套真相源，且远端机器上的 profile 绑定没有对应物。所以 `param_machine` 必须有 `profile` 列，`param_cluster.baseline_profile` 给出集群默认。

**"下发"的两种模式**（`mode`）：

- `push`：把**目标值**（期望值 + 机器级草稿叠加）渲染成 YAML 下发给该机器；
- `rollback`：把该机**最近一次 agent ack 成功的 `config_version` 所对应的目标 YAML** 重新下发（"回到上次好使的状态"），不动 profile。**不能用「最近一次上报的实际值」**：agent 周期回报的就是当下状态，机器漂移时最近回报恰恰是坏状态，回滚它等于把坏状态固化下发。因此 console 必须在 A4 ack 成功时保存该版本的下发快照（每机保留最近 N 版），无 ack 记录的机器 `mode=rollback` 不可用（接口返回 409，前端按钮置灰并说明原因）。

**三处"回滚"语义不混**：

| 位置 | 回滚到什么 | 走哪条链路 |
|---|---|---|
| deploy 页·行级「回滚」 | 该机的目标值回到 profile live 值（清掉该行草稿） | D5 + D6(`mode=push`) |
| deploy 页·部署栈「回滚」 | 该机整体回到最近一次 ack 成功版本的目标 YAML（见上 `rollback` 模式） | D6(`mode=rollback`) |
| release 页·版本「回滚」 | 该 release 关联的 profile 版本回退 | 既有 `POST /api/v1/profiles/{profile}/rollback` |

#### 7.2.4 Token 与 LB 观测（traffic 页）

| # | 方法 | 路径 | 输入 | 输出 |
|---|---|---|---|---|
| T1 | GET | `/api/v1/tokens/summary` | `cluster`、`window=5m\|1h\|24h` | `{total, input, output, per_minute, quota, water_pct, cost_usd, per_session, per_session_turns}` |
| T2 | GET | `/api/v1/tokens/trend` | `cluster`、`window`、`buckets` | 时间序列点 `[{t, total, input, output}]` |
| T3 | GET | `/api/v1/tokens/distribution` | `cluster`、`window` | 逐机器 `[{machine_id, sessions, instances, tokens_per_min, water_pct, share_pct}]` |
| T4 | GET | `/api/v1/tokens/egress` | `cluster` | 逐负载类型 `[{kind, engines, hosts, load, tokens, vram_gb, route}]` |
| T5 | GET | `/api/v1/tokens/policy` | — | 单次上限 / 上下文窗口 / 每分钟配额 / 告警水位（含来源与生效徽标） |
| L1 | GET | `/api/v1/lb/policy` | — | 调度策略 / 粘滞 TTL / 健康间隔 / 摘流阈值 / 金丝雀比例 |
| L2 | GET | `/api/v1/lb/rules` | — | 规则列表（有序，含目标集与 share） |
| L3 | POST | `/api/v1/lb/rules` | 规则体 | 新规则 |
| L4 | PUT | `/api/v1/lb/rules/{id}` | 规则体 | 更新后的规则 |
| L5 | DELETE | `/api/v1/lb/rules/{id}` | — | 204 |
| L6 | GET | `/api/v1/lb/routes` | `window` | 规则命中统计 `{rule_id, matched, tokens, share_pct}` + 粘滞命中率 |

#### 7.2.5 发布与审计

| # | 方法 | 路径 | 输入 | 输出 |
|---|---|---|---|---|
| R1 | GET | `/api/v1/releases` | `cluster` | 发布列表（含阶段与灰度比例） |
| R2 | POST | `/api/v1/releases` | `{version, cluster_id, nodes[], changes[], rollout_pct}` | 新发布（status=`building`，等待 CI 回填） |
| R3 | POST | `/api/v1/releases/{id}/advance` | `{stage, result?, note?}` | 阶段推进后的发布（`result` 供人工/CI 回填阶段结论） |
| R3b | POST | `/api/v1/releases/{id}/stage-result` | `{stage, ok, artifact_ref, note, signature}` | CI 回调入口：写入阶段结论（`signature` 校验，缺省按内网受信调用放行并审计） |
| R4 | POST | `/api/v1/releases/{id}/rollback` | — | 回滚后的发布（连带触发 `POST /api/v1/profiles/{profile}/rollback`） |
| R5 | GET | `/api/v1/audit` | `actor/action/result/field/category/from/to/page/pageSize` | 审计分页（**全局**，不限于 profile） |
| R6 | GET | `/api/v1/audit/export` | 同筛选 | CSV 附件 |

#### 7.2.6 既有接口的扩展（不是新增）

| 接口 | 扩展 |
|---|---|
| `GET /api/v1/instances` | 增加 `machine_id` 维度；实例对象补 `rpm`、`ttft_ms`、`rtf`、`err_count`、`tokens_per_min` |
| `GET /api/v1/instances/{id}/metrics` | 增加 `kind=token` 维度（逐实例 token 增量） |
| `GET /api/v1/status` | 增加 `machinesTotal/Online`、`agentVersions`、`configSource`（承接 11-17 T3） |
| `GET /api/v1/clusters` | 集群行补机器数与实例数（当前由前端算） |

**实例表各列的真值来源（逐列定死）** —— 这几列是"§9.2 无占位"里最容易被打回的地方：

| 列 | 来源 | 拿不到时 |
|---|---|---|
| `rpm`（每分钟请求数） | `param_instance_metric.alloc_ok` 的窗口增量 ÷ 窗口分钟数（分配次数即请求数）；或 agent 上报的 turn 计数 | 标"不可得" |
| `ttft_ms` | `turn_latency.tts_ttfa_ms`（经 agent 上报带机器维度后按实例分组） | 标"不可得" |
| `rtf`（实时因子） | `turn_latency.audio_duration_s`（新扩列）÷ `turn_latency.e2e_ms`（换算到秒） | 标"不可得" |
| `err_count` | `param_proxy_metric.fail_count` 的窗口增量 | 标"不可得" |
| `tokens_per_min` | `param_token_metric` 按 `machine_id` 的窗口增量 ÷ 窗口分钟数 | 标"不可得" |
| `在用/容量`、`状态` | 既有 `param_instance_runtime`（11-17 T4 落库后） | 既有降级路径 |

**`audio_duration_s` 的来源**：pipeline 的 `UsageMetrics.audio_duration_s` 已经是累计音频时长，但**不在 TURN_LATENCY 行里**。本设计要求 **pipeline 侧在 `metadata_payload` 增列 `audio_duration_s`**（一个字段，跨仓小改），agent 上报时原样带上。这是本期**唯一需要动 pipeline 既有语音代码**的地方（其余 pipeline 侧零改动）。若该字段拿不到，RTF 列按上表标"不可得"。

### 7.3 路由与权限登记

- `app/core/router_registry.py`：新增 `agent.router`（**必须在 `mount_spa()` 之前**，C11）与 `machines.router`、`lb.router`、`tokens.router`、`releases.router`；`audit` 扩展挂在 `profiles.router` 之外新开 `audit.router`。
- `app/core/permissions.py` 新增权限码（未登记会启动即 `RuntimeError`，C12）：
  - `console:machine:query|create|update|delete`
  - `console:lb:query|rule:write`
  - `console:token:query`
  - `console:release:query|write`
  - `console:audit:query|export`
  - `console:scenario:query`
  - `console:agent:enroll`（机器 token 面不走角色，用 token 映射）

### 7.4 数据面改造（选台路径）

**先厘清真实入口**（代码事实，设计的落点必须与之一致）：

| 路径 | 今天的选台方式 | 本设计的插桩点 |
|---|---|---|
| WS `/v1/realtime` | `lb_mode=proxy` → `routers/realtime.py:179` 直接调 `upstream_resolver.rank_session()`；`lb_mode=off` → `_proxy_to_loopback()` 固定回环，**不选台** | `rank_session()` 之前插入 `RoutingEngine` |
| WebRTC `/api/calls` | `services/calls_service.py:99` 自己调 `rank_session()` | 同上（同一个 `rank_session` 入口，一处插桩两处生效） |
| REST 反代（ASR/TTS/声纹/情感） | `upstream_resolver.py:148 rank_stateless()`（另一套判据，无会话概念） | **不插入**（无会话 → 无粘性/金丝雀可言）；stateless 路径保持既有行为 |
| demo 面 `POST /api/session` | `routers/demo/session.py:65` → `allocator.allocate()` | **不插入**（demo 面不是生产链路） |

**关键约束**：`allocator.allocate()` 的返回结构**不可变**（11-16 计划的全局约束，`tests/unit/test_allocator.py` 依赖键集合）。本设计因此**不改 `allocate()`**，路由决策信息写进 `param_lb_route_log`，不动既有返回值。

**`RoutingEngine` 的形态**（插在 `rank_session()` 之前）：

```
RoutingEngine.resolve(session_ctx) -> RoutingDecision
  1. 身份解析：从 WS 握手 query 的 ticket 换取身份（可选，见下）→ 验票 → username / role / tenant_tag；
     无有效票据 → 匿名（affinity key = anon:<客户端指纹>）。
  2. 规则求值：按 priority 取第一条 enabled 且匹配的规则
     - user_signed：会话已登录
     - tenant_tag：租户标记命中（来自用户记录或配置）
     - header：请求头标记命中
     - default：兜底
  3. 粘性：命中 affinity 且未过期 → 直接锁定该 instance（sticky_hit=true）
  4. 金丝雀：规则带 share_pct 且命中 → 按比例分流到 canary 目标集
  5. 目标集 → 交给既有 rank_session() 选台（容量感知排序不变）

RoutingDecision 携带 {rule_id, sticky_hit, is_canary, affinity_key}
  → 选台成功后写 param_lb_route_log（命中率与规则命中统计的来源）
```

**身份怎么带到选台那一瞬间**（`/v1/realtime` 今天**没有任何鉴权**，选台瞬间只有握手头可用；pipeline 的 `session.id` 要等 `session.created` 帧回来才拿得到，那时选台早已完成）：

- **传输事实（先校准方案）**：前端经 openai SDK 的 `OpenAIRealtimeWebSocket`（浏览器原生 WebSocket）连同源 `/v1/realtime`——**浏览器 WS API 无法设置 `Authorization` 头**；console 鉴权是纯 Bearer JWT（`core/security.py` HTTPBearer），没有可蹭的 cookie。「握手头带 JWT」**不可实现**，故改为一次性短票据：
  - `POST /api/v1/realtime/ticket`（用户 JWT 鉴权）→ 返回一次性 ticket（128bit 随机，内存表 `ticket → {username, role}`，TTL 60s，**用过即焚**）；
  - 前端把 `?ticket=<ticket>` 拼进 WS URL；console 在 `routers/realtime.py` 握手阶段验票换取身份（不查库），拿到 username / role；无票据 / 过期 / 已消费 → 匿名，走 `anon` 亲和键；
  - 这**推翻评审阶段「不新增票据端点」的决定**：不是信任问题，是传输能力问题——除票据外只剩 cookie（鉴权体系没有）与子协议塞 token（污染 `sec-websocket-protocol` 协商，SDK 侧不可控）两条死路。票据表在内存、console 重启即失效，不引入新的持久化与密钥边界。

**规则为空时行为与今天完全一致**（全走 default → `rank_session()`），确保灰度零风险。

**粘性与既有换台循环的交手（必须定义，否则实现各猜各的）**：`_proxy_with_failover` 的既有语义是「满员/不可达就换下一台」，粘性引入后：

- 粘性命中且目标实例可用（reserve 成功、握手成功）→ 直连该实例，**不做跨实例 failover**（换台就违背了粘性承诺）；
- 粘性目标满员/不可达 → 删除该亲和行，回落 `rank_session()` 重选并重建亲和，本次记 `sticky_hit=false`（理由 `sticky_target_unavailable`）——粘性是「优先」，不是「钉死到死」；
- 亲和行写入时机：选台成功后**异步**写 `param_lb_affinity`（`expires_at = now + L1 粘滞 TTL`），不得让首帧等待一次同步写库。

**`CONSOLE_LB_MODE` 的处置**：

- **默认值保持 `off`**（不改既有部署的行为，11-16 的"默认行为逐字一致"约束不破）；
- **本期验收环境必须是 `lb_mode=proxy` 的多实例集群形态**。原因：`lb_mode=off` 时 WS 走固定回环，**根本不选台**，粘性/金丝雀/路由规则/会话路由命中率全部无法真实验收，S3 的验收无从谈起；
- 也就是说：**目标部署形态是 LB 集群（多机器多实例，compose 显式开 `proxy`），不是单机形态**。这不是"顺带把 LB 打开"，而是"本期交付的就是 LB 形态"。

**粘滞 TTL 到期**由后台 sweeper 清理 `param_lb_affinity`（复用 11-17 的 `expire_pending` 模式，按 `expires_at` 判定）。

**占用与释放一律走 11-17 的 `db_allocator_store`**（T5）：RoutingEngine 只**决定选谁**（产出目标实例集合），真正的 reserve / hold / release / expire 仍由 allocator 完成。粘性命中时也要走 reserve（只是目标实例被亲和表钉死），**不绕过 allocator 直接改实例状态**。这样租约回收、多副本最后写入者胜、`reserved` 归零等既有语义全部自动继承。

**`param_lb_route_log` 的写入是热路径上的额外一次写**：必须**异步批量落库**（攒批或走内存队列），不得让一次选台多一次同步 DB 往返。命中率与规则命中统计允许有秒级延迟。

### 7.5 场景顾问数据集（4 个场景）

原型有四个场景（`latency` 追求首音 / `slow` 慢语速完整句 / `edge` 单机紧显存 / `mix` 中英混说），每个场景含若干建议项：`{参数键, 建议值, 依据, 为什么, 收益, 代价, 风险, 引用}`。

**数据集落在 `docs/scenarios.yaml`**（新增，与 `docs/parameter-catalog.yaml` 同族），由 `GET /api/v1/scenarios` 提供。理由：

- 场景条目全部引用参数目录的键，**必须与目录同步演进**；
- 每个建议项的"生效边界（hot/restart/container）"**从目录行派生，不复述**（原型注释明确如此），避免两处漂移；
- 中英双语放在 YAML 的 `note`/`why`/`gain`/`cost`/`risk` 字段里（`{en, zh}` 双语对象，与原型一致），后端原样下发，前端按当前语言取。

**键的形式约定**：场景里引用参数用**点号形式** `<stage>.<name>`，与 `catalog_service.Entry.key` **完全一致**（原型里的冒号形式 `vad:smart_turn` 是 demo 的简写，移植时统一改成点号）。

**必须新增一个校验脚本**（仓库根 `scripts/` 下**没有**目录校验脚本，S4 要自己写）：`console/backend/scripts/validate_scenarios.py` —— 校验每个场景引用的键存在于 `docs/parameter-catalog.yaml`，且建议值满足该行的 `choices`/`type` 约束；不通过则非零退出。它同时是 CI 的一道闸。

### 7.6 参数目录补字段 + 与 11-17 配置项登记表的**单一真源**

原型的参数表比现有 `CatalogEntry` 多几项信息，需在 `docs/parameter-catalog.yaml` 的条目里**补字段**（向后兼容，缺省即不渲染该列内容）：

| 新字段 | 含义 | 对应原型列 | 填哪些行 |
|---|---|---|---|
| `what` | 参数是什么（面向人的一句说明） | 参数列的说明行 | **全部**条目（机器生成可接受：按 `stage` + `impact` 拼一句） |
| `scope` | 作用域（session / pipeline / platform / tenant） | 影响列的「作用域」 | **全部**条目（按 `stage` 推导） |
| `product_baseline` | 产品基线值（区别于默认值的推荐值） | 期望值列的「产品基线」 | **只填被场景或产品口径明确指定的子集**（约 30–50 条），其余留空 |
| `anchor` | 锚点（文档章节） | 锚点列 | 全部条目（可由 `source_ref` 推导） |

**与 11-17 的 T2 配置项登记表的关系 —— 这就是"不造第二套真相源"的落点**：

两份东西都在描述"有哪些配置项"，必须按**职责切分 + 键集合双向校验**来防漂移：

| 字段 | 唯一真源 | 另一侧怎么处理 |
|---|---|---|
| **键集合**（有哪些参数） | `docs/parameter-catalog.yaml` | T2 的 `app/config/_schema.py` **不得手写键清单**，其键集合从 YAML 派生（或至少由校验脚本强制一致） |
| 类型、取值域 | YAML（`type` / `choices` 已有） | `_schema.py` **引用** YAML，不重复定义 |
| **说明** | YAML 的 `what` | `_schema.py` 不再写说明（避免两份文案漂移） |
| env 名、分区、`restart_required` | T2 的 `_schema.py`（YAML 没有的运行期字段） | YAML 里可留空，不复述 |
| 来源、曝光、影响、风险、锚点 | YAML（`source_ref` / `exposure` / `impact` / `risk`） | `_schema.py` 不涉及 |

**必须新增第二个校验脚本**（仓库根 `scripts/` 下**没有**目录校验脚本，S4 要自己写）：`console/backend/scripts/validate_catalog_schema.py` —— 校验 `docs/parameter-catalog.yaml` 的键集合与 `app/config/_schema.py` 的登记表**完全一致**（双向：YAML 有而 schema 无、schema 有而 YAML 无，都算失败），并校验 `choices` 与 `type` 相容。不通过则非零退出。它与 `validate_scenarios.py` 一起作为 CI 的两道闸。

> **注意**：这条约束是**对 11-17 计划 T2 的追加要求**。若 T2 已按"手写 `_schema.py` 键清单"实现，则在 T2 完成前必须改为派生或补上校验脚本——否则 S0 开工时会有两份会漂移的键清单。已在 11-17 计划文件中标注。

> **状态（2026-11-17，T2 已完成）**：走的是**派生**这条路。`docs/parameter-catalog.yaml` 新增了 `console_parameters` 段（控制台自己的运行开关，与 pipeline 部署参数的 `parameters` 段分开，**不进部署页参数树**），`app/config/_schema.py` 从该段派生键集合、类型、取值域、说明、env 名与 `restart_required`，**不再持有任何键清单**。本节要求的校验脚本已由 T2 交付：`console/backend/scripts/validate_catalog_schema.py`（双向一致 + `choices` 与 `type` 相容 + env 名对得上 settings 字段 + 默认值落在取值域内，不通过非零退出），回归守卫 `tests/unit/test_catalog_schema_drift.py`。S4 只需再补 `validate_scenarios.py`；给 `parameters` 段补 `what`/`scope`/`product_baseline`/`anchor` 时注意 `console_parameters` 段已有 `what`，别把控制台条目混进 pipeline 参数树。

`app/services/catalog_service.py` 解析这些字段并透出；`CatalogEntry` TS 类型同步扩展（全部可空）。`exposure: ops` 有 52 条，是"运维级参数"的现成来源，deploy 页的运维级开关直接用它。

### 7.7 后端测试矩阵

| 领域 | 用例要点 |
|---|---|
| agent 心跳 | 首次心跳建档、重复心跳更新负载清单与运行时摘要、token 增量累加正确、计数器归零处理、协议版本过高被拒、capabilities 缺失降级 |
| 配置拉取 | 304 复用、版本递增、密钥不下发、目标 YAML 渲染正确 |
| 配置回报与漂移 | 回报后漂移数收敛、行级期望值取自目录 |
| 草稿与下发 | 乐观锁冲突 409、下发后 agent 取走、草稿清空、回滚单行 |
| 路由引擎 | 规则优先级、粘性命中与过期、粘性目标满员回落（`sticky_target_unavailable`）、金丝雀分流比例（统计近似）、无规则时行为不变、**亲和 key 越权防护** |
| Token 汇总 | 窗口聚合正确、prompt/completion 拆分、成本公式、每会话 token 估算 |
| 发布 | 阶段推进合法转移、灰度比例、回滚 |
| 审计 | 全局查询、分类筛选、CSV 导出内容 |
| 回归 | 既有 405 passed 不回退；`test_schema_sql.py` 过；双方言 `alembic upgrade head --sql` 无错 |
| turn_latency 重建边界 | 重放只还原本机行（`machine_id` 空）、远端行不被重放覆盖；agent 与索引器**不并行写同一台机器**（单通道约定）；agent 行 `raw_offset=0` |

---

## 8. 交付切分

每个阶段**后端 + 前端 + 测试**一起交付，可独立上线下。

| 阶段 | 内容 | 出口判据 |
|---|---|---|
| **S0 地基** | agent 协议定稿；`0010` 迁移（9 表 + 3 扩列）；`param_machine` 仓储；agent 骨架进程（注册码换 token → 心跳 → 能力协商）；`console:machine:*` 权限码；agent 端点注册；supervisord 第三个 program | agent 能注册并心跳建档；pytest 绿 |
| **S1 机器页** | 机器 CRUD + 负载声明 + 三步注册测试（M8）+ 自动注册（M9）；实例↔机器绑定（走 T4 的 `instances_service` 聚合读）；`PTable`/`PKpi`/`PModal` 等 proto 组件；machines 页重写 | machines 页与原型逐元素对齐 |
| **S2 Token 与 LB 页上半** | agent token 上报 → `param_token_metric` → T1–T5；`param_lb_rule` 存读；L1–L6；traffic 页重写（Token 卡 + 策略卡 + 规则表 + 趋势 + 分布 + 出口 + 实例表） | traffic 页与原型逐元素对齐；数字全部有接口字段 |
| **S3 路由引擎** | `RoutingEngine` 插在 `rank_session()` 前；粘性表 + 金丝雀 + 规则求值；`param_lb_route_log` 记账（异步批量落库）；命中率真值 | **在 `lb_mode=proxy` 形态下**数据面行为按规则分流；关规则时与改动前等价 |
| **S4 参数漂移与下发** | `param_machine_config` / `param_machine_draft`；D1–D7；参数目录补字段 + `docs/scenarios.yaml` + 校验脚本；deploy 页重写（11 列宽表 + 场景顾问 + 行级下发） | deploy 页与原型逐元素对齐；下发链路闭环（agent 收→落→回报→漂移收敛） |
| **S5 发布与审计** | `param_release` + R1–R4（含 CI 回填入口 R3b）；全局审计 + 分类 + CSV 导出（R5–R6）；release/audit 页重写 | release/audit 页与原型逐元素对齐；**CI 回填通路可复现** |
| **S6 音色向导与对话页** | 五步向导重写（跳过逻辑、波形裁剪、预计算进度）；对话页舞台 + 面板 + 三抽屉；WS 票据换身份（身份注入，§7.4）；工具与语气接真实配置 | voices/conversation 页与原型逐元素对齐 |
| **S7 视觉收口** | `prototype.less` 全量落地；hex 禁令白名单扩展；10 张截图逐页比对；antd 组件从页面主体清零；i18n 双语补齐 | 截图比对通过；lint/build/test 全绿 |

**验收环境**：本期的目标部署形态是 **`CONSOLE_LB_MODE=proxy` 的多实例集群**（compose 显式开 proxy），不是单机形态。原因见 §7.4：`lb_mode=off` 时 WS 走固定回环、根本不选台，S3 的粘性/金丝雀/命中率无从验收。`lb_mode` 的**默认值保持 off**，既有部署行为不变。

**开工顺序门禁（硬约束）**：

```
11-17 DB 注册中心计划：T1 ✅ ──▶ T2 ──▶ T3 ──▶ T4 ──▶ T5 ──▶ T6/T7
                                                          │
                                                          ▼  （G1–G4 全部满足才放行）
本设计：S0 地基 ──▶ S1 机器页 ──▶ S2 Token/LB ──▶ S3 路由引擎 ──▶ S4 漂移与下发 ──▶ S5 发布审计 ──▶ S6 音色/对话 ──▶ S7 视觉收口
```

**S0 的第一项任务不是写代码，而是执行 §2.1.1 的门禁检查（G1–G4）**。门禁不满足时，S0 整体标记 `blocked`，不并行抢跑——本设计的机器配置面必须建在 11-17 的"库为真相源"地基上，否则会造出第二套真相源（详见 §2.1.2 的六条复用契约）。

**依赖**：S1 依赖 S0；S2 的负载出口卡依赖 S1 的负载清单；S4 依赖 S1（机器）+ S0（agent 配置面）；S3 依赖 S2 的规则表。S5/S6 可与 S2–S4 并行。

---

## 9. 验收标准与一致性要求

### 9.1 视觉一致性（硬门槛）

1. **基线**：原型已有的 10 张截图（`_shot-lb-{en,zh}.png`、`_shot-machines-{en,zh}.png`、`_shot-deploy-voicepick-{en,zh}.png`、`_shot-voices-{en,zh}.png`、`_shot-voice-wizard-{en,zh}.png`）。每张对应页面在中英两语言下与基线**并排比对**。
2. **像素基线扩展**：原型未截图的 4 页（总览 / 对话示波 / 发布 / 审计）需补基线截图，作为 S7 的输入。
3. **DOM 级一致性**：原型的 class 名原样保留在实现中（§6.2 第 3 条），可用脚本比对"原型有而实现无"的 class。
4. **令牌一致性**：实现中不得出现裸 hex（受 C10 棘轮），白名单从 7 个文件扩到全部改造过的文件。
5. **交互一致性**：抽屉/模态的进出动画、气泡滚动到底、光球呼吸动画、流动连线、表格 sticky 列、横向滚动，全部按原型 CSS 行为。

### 9.2 功能与数据一致性

1. **无 Mock**：前端 `src/views/**` 与 `src/stores/**` 不得出现硬编码数据集（§1.3 反目标 1）。
2. **无占位**：原型中的每个板块都能在接口响应里找到对应字段；后端给不出的字段，接口返回显式空值 + `available:false` 语义，前端渲染原型位置的"不可得"态，**不换布局、不删板块**。
3. **双端对应**：每张前端表格/卡片 ↔ 一个接口字段的映射表随交付物提交（§7.2 已经是该表的接口侧）。
4. **口径一致**：Token 成本、每会话 token、显存水位等**换算公式在前后端各实现一次会漂移** → 公式只在后端算，前端只渲染后端给的数值与百分比；前端仅做展示格式化（千分位、单位）。
5. **审计一致**：所有写操作（机器增删改、负载变更、规则增删改、下发、回滚、发布推进、配置写入）落 `param_audit`，`action` 前缀沿用既有约定：`machine.*` / `lb.*` / `deploy.*` / `release.*` / `voice.*` / `cluster.*`，`fields` 只记字段名不记值。

### 9.3 工程门槛

| 项 | 门槛 |
|---|---|
| 后端测试 | `pytest console/backend/tests` 全绿，基线 405 passed 不回退 |
| 后端迁移 | 双方言 `alembic upgrade head --sql` 无错；`test_schema_sql.py` 漂移守卫过 |
| 后端路由顺序 | `test_static_mount_order.py` 过（新增路由在 `mount_spa()` 之前） |
| 前端测试 | `vitest run` 全绿，基线 39 个测试文件不回退；新增纯函数模块（视图模型）同步补测 |
| 前端 i18n | `i18n.spec.ts` 绿（双语 key 集合一致 + navKey 双语可解析） |
| 前端样式 | `hex-ban.spec.ts` 绿（白名单只增不减） |
| 前端 antd 清零 | 八个页面及其子组件树的源码中**无** `a-*` 组件、无 `ant-design-vue` 的 `message`/`notification`（建议加一条脚本化检查进 vitest） |
| 前端构建 | `npm run build`（含 `vue-tsc --noEmit`）零错误 |
| 前端 lint | `npm run lint` 零 error |
| 契约脚本 | `scripts/check-contract.mjs` 绿 |

### 9.4 数据一致性专项（因为选了 A 档）

| 指标 | 口径 | 验证方法 |
|---|---|---|
| Token 总量 | agent 30s 差分累加 | 连续 3 个窗口内 `sum(delta) == 当前累计 - 上次累计`；进程重启归零后不出现负增量 |
| 会话路由命中率 | `sticky_hit / (sticky_hit + 新建路由)` | 关闭规则时恒为 0（无粘性）；**必须在 `lb_mode=proxy` 形态下验证** |
| 规则 token 占比 | `param_lb_route_log` 按规则分组求和 | 与 `param_token_metric` 总和的差 ≤ 1%（未归因部分显式计入"未匹配"） |
| 漂移参数数 | `param_machine_config` 中 `actual != expected` 且 `actual` 非空的行数 | 与 agent 回报的 `values` 逐键比对 |
| P95 首音 | `turn_latency.tts_ttfa_ms` 的 P95（**经 agent 上报带机器维度后**按实例/机器分组） | 与原型展示口径一致（窗口内分位数） |
| rpm | `param_instance_metric.alloc_ok` 窗口增量 ÷ 窗口分钟数 | 与 `param_proxy_metric` 的代理请求计数同量级 |
| RTF | `turn_latency.audio_duration_s` ÷ `turn_latency.e2e_ms`(→秒) | 落在 [0.1, 3] 的合理区间；越界即判定口径算错 |

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| **agent 成为新的单点** | agent 挂了该机器就"不可见" | agent 崩溃不影响 pipeline 语音服务；console 对无心跳的机器显式标注"agent 失联"而非静默；重连退避上限 60s |
| **协议演进砸掉老 agent** | 升级期间面板空白 | 协议版本号 + capabilities 协商 + 字段级可空；console 只接受 ≤ 支持版本 |
| **Token 差分在进程重启时归零** | 出现负增量或暴涨 | 累计值变小即视为重置，本窗口增量按累计值计；单窗口异常增量上限告警 |
| **下发把机器改坏** | 生产事故 | 下发只改**声明目标**，落地由 agent 执行；console 在 ack 成功时保存下发快照、回滚回到最近 ack 成功版本（§7.2.3 D6）；下发接口强制二次确认 + 审计；**首期只允许下发到 `role=canary` 的机器** |
| **WS 票据被滥用冒充身份** | 路由规则按错人分流 | ticket 一次性、60s TTL、必须持有效用户 JWT 换取；票据表在内存、重启即清；无票据一律匿名（`anon` 键，享受不到用户级规则） |
| **9 张新表 + 3 扩列的迁移风险** | 迁移失败阻塞启动 | 迁移纯加列加表，可逆；`param_instance.machine_id` 可空，回滚不丢数据 |
| **CI 回填延迟** | 发布阶段状态长时间停在 `building`，页面看着像卡住 | console 只记账是需求方拍板的边界；缓解：阶段停留超阈值（默认 30 分钟）在流水线上标"待回填"提示，并显示最后回填时间；`R3` 允许人工补录 |
| **与 11-17 在飞计划撞车** | 两套配置面并存 | **硬门禁**：S0 不得在 11-17 的 T2–T7 完成前开工（§2.1.1 的 G1–G4）；本设计的每一条读写都挂到 11-17 的服务层上（§2.1.2 的六条复用契约），不平行实现 |
| **参数目录与配置项登记表双份键清单漂移** | 目录页与配置面显示的参数不一致 | YAML 持有键集合与类型/取值域，`_schema.py` 只补 env 名/分区/`restart_required`；`validate_catalog_schema.py` 强制双向一致（S4 交付） |
| **antd 清零导致既有交互回归** | 登录页、列表页失灵 | 登录页保留 antd 表单（不在八页之内）；清零范围限定在 §6.1 的八个页面；S7 收口时逐页回归 |
| **参数目录补字段破坏既有消费方** | `/catalog` 契约变化 | 新字段全部可空；`CatalogEntry` TS 类型扩为可选；`tests/unit/test_catalog*.py` 补断言 |

---

## 11. 与既有设计的关系（须同步修订）

本设计**修订**两份已评审定稿设计的非目标条款，修订记录必须写回原文档：

| 文档 | 原条款 | 处置 |
|---|---|---|
| `2026-11-16-console-s2s-load-balancing-design.md` §14 | 「会话级粘性、金丝雀比例、路由规则…本期维持」 | **改为本期实现**，指向本设计 §7.4 |
| `2026-11-16-console-s2s-load-balancing-design.md` §14 | 「跨机参数发布 fanout（需先定义配置是集群级还是单机级）」 | **本设计定义为单机级**（一次下发针对一台机器），见 §7.2.3 |
| `2026-11-16-console-s2s-load-balancing-design.md` §11 | 「`allocate()` 契约：返回 dict 的键集合与改前一致」 | **保持不变** —— 本设计不扩 `allocate()` 返回值，路由信息写 `param_lb_route_log`（见 §7.4） |
| `2026-11-17-console-db-backed-registry-and-config-design.md` §1.2 | 「不做多租户、权限树、会话粘性、金丝雀比例」 | **粘性与金丝雀改为本期实现**（多租户与权限树仍不做） |
| `2026-11-17-console-db-backed-registry-and-config-design.md` §1.2 | 「不做跨机参数发布 fanout」 | **改为单机级下发**（同上） |
| `console/backend/app/routers/traffic.py` | `"unimplemented": ["session-stickiness","canary-ratio","routing-rules"]` | **删除该字段**（三项已实现），或替换为真实的 `unimplemented: []` |
| `console/frontend/src/components/NotImplemented.vue` | 占位组件 | **删除** |
| `console/backend/app/models/turn_latency.py` | 无机器维度、无音频时长 | **扩 3 列**（`machine_id`/`instance_id`/`audio_duration_s`） |
| `src/speech_to_speech/pipeline/turn_latency.py` | `metadata_payload` 无 `audio_duration_s` | **增 1 个字段**（本期唯一需要动 pipeline 既有语音代码的地方，见 §7.2.6） |
| `2026-11-17-console-db-backed-registry-and-config.md` | T2 手写 `app/config/_schema.py` 键清单 | **追加要求**：键集合从 `docs/parameter-catalog.yaml` 派生，或至少由 `validate_catalog_schema.py` 强制双向一致（见 §7.6）；说明字段不重复写 |

**同时需要更新的文档**：`docs/console-service.md`（新增 agent 面、机器/负载/路由规则/发布四组接口与开关表）、`console/README.md`（agent 部署形态与端口）、`docs/parameter-catalog.md`（新增四个 catalog 字段的说明）。

---

## 12. 风险已识别、留给需求方的问题

### 12.1 已在本设计中定稿（原三问的结论）

| 原问题 | 结论 | 依据 |
|---|---|---|
| agent 让 pipeline 生效配置的机制 | **agent 落盘 YAML + 通过本机 supervisor 重启 pipeline**；`hot` 类参数改走既有 `/internal/sessions/update`。**pipeline 侧不新增配置端点** | pipeline 没有任何配置 reload 端点；而 console 现有发布链路（`publish_flow_service.publish()` → `restart_runner.restart()`）已是"写文件 + supervisor 重启"，agent 在目标机器上有同样权限 |
| "期望值"的真源 | **profile 的 live version 渲染值**（复用 `renderer_service` + `layout_service`），回落 catalog 默认；`product_baseline` 只作参考不参与漂移判定 | 渲染本来就必须带 profile（`layout_service.locate`），另起渲染器=第二套真相源 |
| 首期允许下发到哪些机器 | **只允许 `role=canary`**；`role=agent` 的正式机器需二次确认（带输入确认词）才放行 | 生产风险控制；`canary` 角色在原型里本就是一等概念 |
| **发布流水线的 build / staging 由谁执行** | **console 只记账**（需求方 2026-11-17 拍板）：构建在外部 CI 里完成，结果回填（`R3b` 阶段结论回调 / `R3` 人工回填）；console **不做构建执行器、不管理 CI 凭据**，只负责阶段状态、灰度比例与节点范围 | console 本就不在机器上，无构建能力；引入 CI 凭据会再开一类密钥边界，收益不抵成本 |

### 12.2 仍需需求方拍板

**无。** 评审阶段提出的所有问题均已由需求方拍板或按代码事实定稿（见 §12.1）。

### 12.3 已识别但不阻塞、留给实现者按默认推进

| # | 事项 | 默认 |
|---|---|---|
| N1 | `param_lb_route_log` 异步批量落库的具体实现（内存队列 vs 攒批表） | 实现者自选，但必须**不让选台多一次同步 DB 往返** |
| N2 | agent 在 supervisord 里的 priority / 日志路径 / 环境变量注入方式 | 与既有 `console`(priority 10) / `pipeline`(priority 20) 并列，取 priority 15 |
| N3 | 纯负载机（无 pipeline）的 agent 安装方式 | 同一份代码 `pip install` 后独立运行（systemd 或 nohup），不强制 supervisord |
| N4 | `product_baseline` 具体填哪 30–50 条 | 由场景数据集反推：四个场景引用到的参数必须有 `product_baseline` |
| N5 | 匿名会话的亲和键构造（`anon:<指纹>` 的具体指纹来源） | 用 console 侧看到的客户端 IP 的哈希（不落原文） |

---

## 13. 验收清单（交付时逐条勾）

- [ ] **门禁检查通过**：11-17 的 T2–T7 全部完成，G1–G4 逐条验证通过（§2.1.1）
- [ ] **无第二套真相源**：配置项键集合只在 `docs/parameter-catalog.yaml` 一处手写；`validate_catalog_schema.py` 双向校验通过
- [ ] 本设计的机器配置读写全部走 11-17 的 `config_service` / `instances_service` / `db_allocator_store`（§2.1.2 六条复用契约逐条核对）
- [ ] 原型八页在生产实现中逐元素存在，class 名与原型一致
- [ ] 10 张基线截图（中英各 5 页）比对通过，另 4 页补齐基线
- [ ] `src/views/**` 无 Mock 数据
- [ ] agent **注册 / 心跳 / 配置拉取 / 配置回报 / token 上报 / 负载清单 / turn-latency 上报**七条链路各有可复现的验证步骤
- [ ] `turn_latency` 单通道约定成立：agent 上报与本地索引器**永不并行写同一台机器**；重放重建只还原本机行、不覆盖远端行（§7.1 / §7.7）
- [ ] 部署栈「回滚」回到最近 ack 成功版本，而非最近上报的实际值；无 ack 记录时回滚不可用（409 + 前端置灰）
- [ ] 新增 9 表 + 3 扩列迁移可逆，双方言裸 SQL 重新生成
- [ ] 新增权限码全部登记，未登记码不导致启动失败
- [ ] agent 端点校验 token 归属，越权请求 403；一次性注册码用过即焚
- [ ] `allocator.allocate()` 返回结构的键集合与改前一致（11-16 契约测试不回退）
- [ ] 无规则时数据面行为与改动前逐字节一致（回归断言）
- [ ] `CONSOLE_LB_MODE=proxy` 的多实例集群形态下完成 S3 全量验收（粘性命中、金丝雀分流、命中率真值）
- [ ] Token 差分在进程重启场景下不产生负增量
- [ ] 漂移数 = agent 回报值与 profile live 渲染值逐键比对的结果；agent 未回报的键不计漂移
- [ ] 下发闭环可复现：下发 → agent 取到 → 落盘 → 回报 → 漂移收敛
- [ ] 写操作全部落审计且 `fields` 只记字段名
- [ ] CI 阶段结论回填通路可复现（`R3b`），且 console **未**持有任何 CI 凭据
- [ ] `validate_scenarios.py` 通过，场景引用的键全部存在于参数目录
- [ ] pytest / vitest / lint / build 全绿，基线不回退
- [ ] 两份已定稿设计的修订记录已写回，`traffic.py` 的 `unimplemented` 已清
- [ ] `docs/console-service.md`、`console/README.md`、`docs/parameter-catalog.md` 已同步
