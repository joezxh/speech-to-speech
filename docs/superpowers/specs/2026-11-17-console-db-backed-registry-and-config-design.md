# 控制台注册中心与运行配置落到数据库（设计）

日期：2026-11-17
状态：**已评审定稿**（需求方 2026-11-17 拍板四项范围：运行时注册表 + 选台占位都落库 / console 全部非密钥配置落库 / DB 优先 env 兜底 / 热生效）
范围：`console/backend/**` + `docs/console-service.md` + `config/prod.env`
不在范围：`src/speech_to_speech/**`（pipeline 侧零改动）

决策一句话：**控制台自建的注册中心与配置面整体从「进程内存 + 环境变量」搬到「数据库表」——库是真相源，env 只做首次播种与兜底，读侧带短 TTL 热生效。**

---

## 0. 背景

2026-11-16 的负载均衡设计（`2026-11-16-console-s2s-load-balancing-design.md`）把选台放进了控制台，但注册中心与运行配置当时仍是"内存 + 环境变量"：

| 层 | 2026-11-16 的状态 | 问题 |
|---|---|---|
| 实例声明数据 | 已在 `param_instance` 表 | 无 |
| 运行时注册表（健康五态、槽位、能力指纹） | 纯内存 `InstanceRegistry` | 控制台重启即丢；多副本各看各的 |
| 选台占位（pending/held） | 进程内 `InMemoryAllocatorStore` | 多副本各算余量 → 超发（spec §14 明列为"本期不做"） |
| 运行开关 | 全部 env（pydantic-settings） | 改一个值要重启进程；唯一改法是改 `.env` |

本次把这两层一起搬进数据库：**Phase 2 的共享分配状态（`PostgresAllocatorStore`）与"配置集中管理"一并落地**。

---

## 1. 目标与非目标

### 1.1 目标

1. **注册表状态持久化**：实例健康五态、槽位占用、能力指纹、探测计数写进 DB；控制台重启后直接读到上次状态，不必等首轮探测。
2. **选台占位跨副本共享**：pending/held 落库，两个副本不会各自看到"还有余量"而同时派发到同一台；占位超时自动回收。
3. **配置集中到一张表**：console 全部**非密钥**配置项可在线查看与修改，改完数秒内生效，不必重启控制台。
4. **兼容现有部署**：`.env` 保留（首次播种 + 兜底），现有 compose 形态不需要立刻清理；密钥类**仍只走 env**。
5. **在线纳管实例**：补 `POST/DELETE /api/v1/instances`，纳管一台机器不必再改 seed 文件 + 重启。

### 1.2 非目标

1. 不做多租户、权限树、会话粘性、金丝雀比例（`routers/traffic.py` 已列 `unimplemented`，维持）。
2. 不引入配置中心中间件（Consul/etcd/Nacos）——控制台已有自己的库，再引一套就是第二套真相源。
3. 不做跨机参数发布 fanout（仍需先定义"配置是集群级还是单机级"）。
4. 不做"探测领导者选举"：多副本仍各探各的，写侧最后写入者胜（§3.1）。
5. 不把密钥搬进 DB（§5.2）。

---

## 2. 数据模型

### 2.1 三张新表（职责分离，沿用"槽位语义与代理语义不混一张表"的既有口径）

| 表 | 内容 | 谁写 | 谁读 |
|---|---|---|---|
| `param_instance`（**已存在，不动结构**） | 声明数据：instance_id / base_url / weight / max_sessions_hint / labels_json / enabled / drain_requested / cluster_id | seed upsert + 运维 API | 注册表同步 |
| `param_instance_runtime`（**新**） | 运行时状态：status、pool_size/in_use/stuck、probe_ms、capabilities、capability_issues、consecutive_failures/successes、last_error、probe_history、**reserved**、observed_at、observed_by | 巡检探测后 upsert；选台时改 reserved | 选台、面板、状态接口 |
| `param_allocator_lease`（**新**） | 占位明细：lease_key(PK)、instance_id、state(pending/held)、expires_at、console_id、created_at、updated_at | reserve/hold/release/expire | 占位统计与回收 |
| `param_config`（**新**） | 配置项：config_key(唯一)、value、value_type、section、description、restart_required、version、updated_by、created_at、updated_at | 播种 + 配置 API | 配置门面 |

都不建 FK：实例删除后历史仍可读，与 `param_instance_metric` 既有做法一致。

**为什么 `reserved` 放在运行时表而不是单独一张计数表**：占位判定必须与"这台机器还剩几个槽位"在同一条 UPDATE 里完成，分表就得两次往返，中间会有窗口（§3.2）。

### 2.2 配置项为什么用"字符串值 + 类型标记"

配置项有 str/int/float/bool 四种类型，还可能有取值域约束。若每种类型一列，加一个配置项就要改表结构；用 `value` + `value_type` 配对，改一个键只是多一行数据。类型转换与取值域校验在服务层做（§4.3），表只负责存。

### 2.3 与既有表的边界

- `param_instance_metric`：**槽位采样的时序**，30s 一行，窗口增量计数，**不混装**运行时状态与代理指标。
- `param_proxy_metric`：**代理侧的时序**，按 (instance_id, service) 聚合。
- `param_instance_runtime`：**当前状态**（一行一实例，最后一次观测）。
- `param_draft` / `param_version`：流水线**参数**（发到 pipeline 的配置），与控制台自身配置无关，不复用。

---

## 3. 并发与一致性

### 3.1 多副本模型

控制台强制单 worker（`supervisord.conf`），但**可以有多个副本**（每副本一台机器）。DB 落库后，多副本共享同一份余量与健康真相源：

- **写侧**：每个副本都探同一批实例 → 同一行被多次写 → "最后写入者胜"。探测对象相同，覆盖无害；`observed_by` 保留来源，`observed_at` 供排查。
- **读侧**：直接读该行（它就是最后一次写入的结果）。

### 3.2 抢占用：条件 UPDATE + rowcount（方言无关）

SQLite 没有 `SELECT … FOR UPDATE`，所以**不用行锁**。占位判定与递增合并成一条原子 UPDATE：

```sql
UPDATE param_instance_runtime
   SET reserved = reserved + 1, updated_at = :now
 WHERE instance_id = :id
   AND reserved < (COALESCE(pool_size, 0) - COALESCE(in_use, 0) - COALESCE(stuck, 0))
```

判定成功与否看 `rowcount`：SQLite 与 PostgreSQL 语义一致，无需显式事务锁。

- 与内存版语义一致（`InMemoryAllocatorStore.reserve`）：`reserved < free` 才允许预留；`pool_size` 为空（从未探测到）时 `free = 0` → 预留失败，与内存版 `state.pool is None → False` 同义。
- `pending` 与 `held` 都计入 `reserved`（两者都占槽位，spec 2026-11-16 §5.3）。
- `release` 用 `UPDATE … WHERE lease_key = ?` 并把 `reserved` 递减到不小于 0。
- **SQLite 单写者**：条件 UPDATE 把锁持有时间压到一条语句；`create_engine` 增加 `timeout`（busy_timeout）参数，避免并发写直接报 `database is locked`。

### 3.3 时间基准

内存版用 `time.monotonic()`（避免机器间时钟偏差）；DB 版必须用**墙钟**（`expires_at`），因为跨进程要共享时间基准。TTL 回收按 `expires_at < now()` 判定。

### 3.4 不做的事

- 不做"探测领导者选举"：每个副本都探，重复探测的代价是几次 HTTP GET，收益是任何一个副本挂掉都不会让注册表停止更新。
- 不做跨副本协调缓存：TTL 缓存是单调降级（最终一致），不引入需要协调的协议。

---

## 4. 配置面：库优先、env 兜底、热生效

### 4.1 配置项登记表（从参数目录派生）

`app/config/_schema.py` 是控制台配置项的登记表：键名、env 名、类型、取值域、分区、是否需重启、说明。**只有登记在册的键能进表**——这张表是白名单，不是任意键值袋。密钥类（JWT、口令、S2S token）**不在册**。

**登记表不再手写键清单**：唯一真源是参数目录 `docs/parameter-catalog.yaml` 的 `console_parameters` 段（键集合、类型、取值域、说明、env 名、是否需重启都在那里），`_schema.py` 只做"目录条目 → `ConfigItem`"的翻译。这样仓库里就不存在第二份会漂移的清单。

- 目录段与 pipeline 参数段的 `parameters` 是两件事：`parameters` 进部署页的参数树，`console_parameters` 进控制台的配置面（`GET/PUT /api/v1/config`），互不污染。
- 目录文件位置：`PARAM_CATALOG_PATH` → 仓库 `docs/` → 容器挂载点 `/app/catalog/parameter-catalog.yaml`。**刻意不读配置表里的 `console.param_catalog_path`**——登记表是配置面自己的地基，不能依赖它自己配出来的值。
- 目录文件不可用或条目不合法时，登记表为空（或跳过坏条目），所有开关退回 env 默认值，控制台照常启动（§5.1 的降级矩阵）。
- **CI 闸**：`console/backend/scripts/validate_catalog_schema.py` 强制目录与登记表**双向一致**（目录有而登记表没有、登记表有而目录没有，都算失败），并校验 `choices` 与 `type` 相容、`env` 名确实是 settings 字段真正读的那个变量名、settings 默认值落在取值域内。不通过则非零退出；`tests/unit/test_catalog_schema_drift.py` 是同一套判定的回归守卫。

### 4.2 读取路径（门面对象，42 处调用点不变）

现状是 `from app.config import console` 后直接属性访问，全仓 42 处消费点。逐个改成函数调用会让改动面爆炸，所以保持调用点不变，把 `app/config/__init__.py` 导出的 `console` / `allocator` / `demo` / `app` / `bootstrap` 换成**门面对象**：

```
LiveSettings.__getattr__(name)
  → ConfigStore.get("section.name")     # 库优先
  → 库中无该键 或 查库失败 → env 默认值    # 兜底
```

`database`（要先有连接串才能连库）与 `auth`（密钥）保持现状走 env。

**写（赋值）落在门面自己的覆盖层**，不直接改 pydantic 实例：门面上有该属性时优先于库值，
`monkeypatch.setattr(console, "x", v)` 撤销时（`delattr`）能精确还原，也不会把 env
解析出来的只读快照永久改掉。

### 4.3 写入路径

`ConfigStore.set(key, value, actor)`：类型与取值域校验 → 写表（`version + 1`）→ 失效本进程缓存（立即生效）→ 写审计（`param_audit`，`fields` 只记字段名不记值）。非法项直接 400 且**整批不落库**（不做部分写入）。

### 4.4 生效时机

- **热生效**（数秒内）：探针间隔与阈值、换台次数、各端点超时、上传闸、能力探测间隔、LB 模式、目录路径、音色/会话上限、演示面开关。
- **需重启**（`restart_required = true`）：`ALLOCATOR_MODE`（决定是否起巡检任务）、`INSTANCE_WEBRTC_HANGUP_ENABLED`（决定是否注册路由）、`INSTANCES_SEED_PATH`（决定播种来源）。写 API 返回 `restart_required: true`，前端明示"需重启"。

### 4.5 播种（首次启动）

`ConfigStore.seed_missing(session)`：把 env 解析出的默认值写进 `param_config`，**只写缺失的键**。已存在的键不覆盖——这落实"env 仅首次播种/兜底"：改 `.env` 不影响已在跑的实例，要改就改表。

---

## 5. 兼容与降级

### 5.1 降级矩阵

| 故障 | 表现 | 降级 |
|---|---|---|
| DB 不可用（配置读） | 读配置失败 | **回退 env 默认值**，语音链路不中断 |
| DB 不可用（注册表读） | 读运行时状态失败 | 沿用上一次内存快照，不 500 |
| DB 不可用（占位） | 抢占/释放失败 | 选台直接失败 → REST 503 `no_available_instance`、WS 握手失败。**绝不用陈旧租约继续派发**（宁可少派不超发） |
| 首次启动无表 | 迁移未跑 | 播种跳过，注册表为空 → 无候选（既有行为） |
| 配置项被删 | 表里没了该键 | 回退 env 默认值 |

### 5.2 密钥不进 DB

`JWT_SECRET_KEY`、`USAGE_HASH_SECRET`、`S2S_ADMIN_TOKEN`、`S2S_INTERNAL_TOKEN`、演示面的 `serper_api_key` / `lb_hf_token`、首次启动口令**仍只走 env**。理由：密钥需要轮换与加密存储，搬进普通配置表会让轮换路径与泄露面都变复杂；`status_service.secretsConsistent` 的多副本一致性校验逻辑不变。

### 5.3 迁移与 schema

新增迁移 `0009_db_registry_and_config`（接在 `0008_proxy_metrics` 之后）建三张表；随后必须跑 `console/backend/scripts/dump_schema_sql.py` 重新生成 `alembic/sql/init-sqlite.sql` 与 `init-postgresql.sql`（`tests/unit/test_schema_sql.py` 是漂移守卫）。列名不叫 `key`：SQLite 把 KEY 当保留字，SQLAlchemy 会加引号（`"key"`），双方言裸 SQL 就对不上——统一用 `config_key`。

### 5.4 seed 与纳管的关系

`instances.yaml` 继续可用（启动时幂等 upsert，只写缺失键，不覆盖 `enabled`/`drain_requested`），但**不再是唯一入口**：新增 `POST /api/v1/instances`（纳管）与 `DELETE /api/v1/instances/{id}`（摘除，运行时行与租约一并清理）。运行期增删不必重启控制台。

---

## 6. 接口

### 6.1 配置面

| 端点 | 方法 | 权限 | 说明 |
|---|---|---|---|
| `/api/v1/config` | GET | `require_user` | 全部有效值 + 来源（db/env）+ 类型 + 说明 + 是否需重启 |
| `/api/v1/config/schema` | GET | `require_user` | 配置项元数据（供前端渲染） |
| `/api/v1/config` | PUT | `require_admin` | 批量写入，逐项校验，整批拒绝非法值，写审计 |

### 6.2 实例纳管

| 端点 | 方法 | 权限 | 说明 |
|---|---|---|---|
| `/api/v1/instances` | POST | `require_admin` | 新增实例（instance_id/base_url/weight/labels） |
| `/api/v1/instances/{id}` | DELETE | `require_admin` | 删除实例：声明行 + 运行时行 + 租约一并清理 |

### 6.3 状态面

`GET /api/v1/status` 增加：`configSource`（db/env/混合）、`configDbOk`、`registryRuntimePersisted`。

---

## 7. 性能与可靠性

- **数据面额外开销**：WS 会话路径新增 3 次本地 DB 往返（reserve / hold / release）。sqlite 同机亚毫秒级、postgres 同网约 1ms，相对上游握手 RTT 可忽略。选台排序读走 1s 本地缓存，避免每请求多次查库。
- **锁粒度**：sqlite 写锁只覆盖单条 UPDATE，不跨业务逻辑；postgres 无隐式全表锁。
- **不引入跨进程协调缓存**：TTL 缓存是单调降级（最终一致）。
- **审计**：配置写入与实例增删都留审计行，`fields` 只存字段名。

---

## 8. 与既有设计的关系

- 本设计**继承** 2026-11-16 负载均衡设计的全部数据面语义：两套选台策略（session/stateless）、WS 静默换台、能力指纹判定表、REST 反代错误码，均不变。
- **决策变更一处**：2026-11-16 §5.1 写"能力指纹只驻留内存、不落库、不进 seed"。本次改为落 `param_instance_runtime`（不进 seed、不混进 `param_instance_metric`），理由是"多副本共享 + 重启不丢"。该变更已在 2026-11-16 文档的修订记录里同步。
- **补齐 2026-11-16 §14 的"本期不做"**：多副本共享分配状态（Phase 2）本次落地。

---

## 9. 实现落点（与代码的对应）

| 关注点 | 代码位置 |
|---|---|
| 配置项登记表 | `console/backend/app/config/_schema.py`（`ConfigItem` / `ITEMS` / `coerce`） |
| 配置读取门面 | `console/backend/app/config/_store.py`（`ConfigStore`）、`app/config/__init__.py`（`LiveSettings`） |
| 配置读写 | `app/repositories/config_repository.py`、`app/services/config_service.py`、`app/routers/config.py` |
| 运行时状态 | `app/models/param_instance_runtime.py`、`app/repositories/instance_runtime_repository.py`、`app/services/instance_monitor.py` |
| 选台占位 | `app/models/param_allocator_lease.py`、`app/repositories/allocator_lease_repository.py`、`app/services/db_allocator_store.py` |
| store 选择 | `app/services/allocator.py`（`_build_store()`：`local` + `proxy` → DB store，否则内存） |
| 实例在线纳管 | `app/routers/instances.py`（`POST /api/v1/instances`、`DELETE /api/v1/instances/{id}`） |

两处命名决定：

1. **配置表的列叫 `config_key` 不叫 `key`**：SQLite 把 `KEY` 当保留字，SQLAlchemy 会
   给它加引号（`"key"`），双方言的裸 SQL 就对不上（schema 漂移守卫会报列缺失）。
2. **租约键叫 `lease_key`，值是控制台自己生成的 uuid**（`res_key`），不是上游
   session_id——`reserve → hold → release` 始终是同一把 key，换台不会漏成两把。

---

## 10. 验收清单

1. `console/backend/tests` 全绿（基线 405 passed）。
2. `alembic upgrade head --sql` 双方言无错；`scripts/dump_schema_sql.py` 重新生成后 `test_schema_sql.py` 通过。
3. 配置项：改表后 ≤ 数秒生效（探针间隔类可观察到）；env 改动不影响运行中的实例；DB 不可用时回退 env。
4. 注册表：控制台重启后状态不丢（读 `param_instance_runtime`）；能力指纹随探测刷新。
5. 占位：两个 store 实例并发预留同一台，只有一个成功；`expire_pending` 按 `expires_at` 回收；`hold`/`release` 后 `reserved` 归零。
6. API：配置读写权限正确、非法值 400 且不落库、审计行只记字段名；实例增删后运行时行与租约被清理。

## 1.2 修订记录

- **2026-11-17（原型对齐批次落地）**：D 面（机器参数期望/草稿/下发/回滚）与 T/L/R 面在 2026-11-17 计划中交付。期望值唯一真源改为 profile live 渲染值（原先假定的 catalog 默认回落保留为次级）；未回报的键 actual=None 且 drift=False（"未知"不是漂移）；回滚目标=最近 ack 成功快照。
