# 实施计划：控制台注册中心与运行配置落到数据库

依据：`docs/superpowers/specs/2026-11-17-console-db-backed-registry-and-config-design.md`（下称"设计 §"）
范围：只改 `console/backend/**` 与文档；`src/speech_to_speech/**` 零改动。
工具探针：写入工具本轮异常时的临时标记，随后删除。

## 后续设计依赖（2026-11-17 控制台原型对齐）

本计划 T2–T7 是**后续设计的前置门禁**。`docs/superpowers/specs/2026-11-17-console-prototype-alignment-design.md`（控制台严格对齐负载均衡原型）的 **S0 不得在本计划 T2–T7 完成前开工**——该设计的机器配置面要建在本计划"库为真相源"的地基上，否则会造出第二套真相源。

具体要求：

1. **T2 的配置项登记表不得手写第二份键清单。** `app/config/_schema.py` 的键集合应从 `docs/parameter-catalog.yaml` 派生；若坚持手写，则必须补一个校验脚本 `console/backend/scripts/validate_catalog_schema.py`，强制与 YAML **双向一致**（YAML 有而 schema 无、schema 有而 YAML 无都算失败）。参数目录侧的说明、类型、取值域以 YAML 为准，`_schema.py` 不复述，只补 YAML 没有的运行期字段（env 名、分区、`restart_required`）。
   - **已落地（2026-11-17）**：走的是"派生"这条路。`docs/parameter-catalog.yaml` 新增 `console_parameters` 段（控制台自己的运行开关，与 pipeline 部署参数的 `parameters` 段分开，不进部署页参数树），`_schema.py` 从它派生键集合、类型、取值域、说明、env 名与 `restart_required`，**不再持有任何键清单**。
   - 校验脚本 `console/backend/scripts/validate_catalog_schema.py` 双向一致 + `choices` 与 `type` 相容 + env 名对得上 settings 字段 + 默认值落在取值域内，不通过非零退出；回归守卫 `tests/unit/test_catalog_schema_drift.py`。
   - 落点偏差说明：目录的 `console_parameters` 段自带 `env` 与 `effect`（= `restart_required`），所以 env 名与分区也由目录给出；否则 `_schema.py` 必须再手写一份键名映射，仍然是两份清单。
2. **后续设计会复用本计划的服务层**，不得平行实现：
   - 配置项定义与取值校验 → `app/config/_schema.py` + `app/services/config_service.py`
   - 实例运行态 → `app/services/instances_service.py`（DB 运行时 + 内存兜底）
   - 选台占用与租约 → `app/services/db_allocator_store.py`（`allocate()` 契约不变）
   - 实例纳管审计格式 → `app/routers/instances.py` 的 `_audit` 约定（`fields` 只记字段名）
3. 本计划 T2–T7 **不新增表**（只用 T1 已建的 `0009_db_registry_and_config` 三张表），后续设计的迁移接在 `0009` 之后取 `0010_console_lb_backbone` 无编号冲突；若本计划后续需要新迁移，须先取号。

## T1 设计文档与三张新表

- [x] 设计文档
- [x] 模型 `param_config` / `param_instance_runtime` / `param_allocator_lease` + 注册
- [x] 中文注释补齐（`app/models/comments.py`）
- [x] 迁移 `0009_db_registry_and_config`（接 `0008_proxy_metrics`）
- [x] `scripts/dump_schema_sql.py` 重新生成双方言 SQL，漂移守卫通过

## T2 配置项登记表 + ConfigStore + LiveSettings 门面

- [x] `app/config/_schema.py`：配置项登记表（键、env 名、类型、取值域、分区、restart_required、说明）。**键集合与类型/取值域从 `docs/parameter-catalog.yaml` 的 `console_parameters` 段派生，说明取目录的 `what`；登记表不再手写键清单**
- [x] `console/backend/scripts/validate_catalog_schema.py`：目录 ↔ 登记表双向一致 + `choices` 与 `type` 相容 + env 名对得上 settings + 默认值落在取值域内，不通过非零退出
- [x] `app/config/store.py`：`ConfigStore`（seed_missing / get / source / set / snapshot / invalidate），TTL 2s，本地写立即失效，DB 异常回退 env
- [x] `app/config/__init__.py`：`console`/`allocator`/`demo`/`app`/`bootstrap` 换 `LiveSettings` 门面；`database`/`auth` 保持 env
- [x] `app/repositories/config_repository.py`：读写 + 只写缺失键的播种语义
- [x] `app/services/config_service.py`：有效值聚合、类型与取值域校验、写入加审计、restart_required 标记

验收：单测覆盖 DB 优先、env 兜底、播种只写缺失键、TTL 失效、非法值拒绝。

## T3 配置 API、状态面、实例在线纳管

- [x] `app/schemas/config.py` 与 `app/routers/config.py`：GET 配置、GET schema、PUT 配置（admin）
- [x] `app/core/router_registry.py`：注册 config.router
- [x] `app/routers/instances.py`：POST 实例、DELETE 实例（审计沿用既有 `_audit`）
- [x] `app/services/status_service.py`：configSource / configDbOk / registryRuntimePersisted
- [x] `app/main.py`：lifespan 内先播种配置再播种实例

验收：权限正确、非法值 400 且不落库、审计只记字段名、实例删除连带清理运行时行与租约。

## T4 运行时注册表落库

- [x] `app/repositories/instance_runtime_repository.py`：upsert / list / get / reserved 原子占用与释放
- [x] `app/services/instance_monitor.py`：refresh_specs 合并声明表与运行时表；probe_all 与 apply_capabilities 落库；DB 读失败沿用内存快照
- [x] `app/services/instance_registry.py`：RuntimeState 增加 reserved，effective_free 语义不变
- [x] `app/services/instances_service.py`：聚合读改为 DB 运行时状态加内存兜底
- [x] `app/services/upstream_resolver.py`：能力过滤读合并后的运行时状态

验收：重启不丢状态；能力指纹随探测刷新；多副本最后写入者胜。

## T5 DB 版选台占位

- [x] `app/services/db_allocator_store.py`：AllocatorStore Protocol 的 DB 实现（reserve 条件 UPDATE 加 rowcount、hold/release 同步 reserved 与租约行、expire 按 expires_at 回收、只读方法 1s 缓存）
- [x] `app/repositories/allocator_lease_repository.py`：insert/hold/release/expire/count
- [x] `app/services/allocator.py`：模块级 store 按模式选择；allocate 契约不变
- [x] `app/db/database.py`：sqlite 连接加 busy timeout

验收：并发预留只成功一次；expire 回收；hold/release 后 reserved 归零；Protocol 方法集合一致。

## T6 文档同步

- [x] `docs/console-service.md`：新增配置面章节；更新开关表、seed 关系、多副本一致性
- [x] 2026-11-16 负载均衡设计：修订记录补能力指纹改为落库与 Phase 2 已落地
- [x] `config/prod.env`：追加注释——仅作首次播种与兜底，运行期以数据库为准

## 未交付（可选项）

- [ ] 前端「系统配置」页（`console/frontend/src/api/config.ts` + `views/ConfigView.vue`）：
      本期只交付后端接口（`GET /api/v1/config`、`GET /api/v1/config/schema`、`PUT /api/v1/config`），
      前端页面按 schema 渲染表单即可接入。

## T7 测试与回归

- [x] 新增 `test_config_store.py`、`test_db_allocator_store.py`、`test_instance_runtime.py`、`test_catalog_schema_drift.py`、`tests/integration/test_console_config_api.py`（原名 `test_config_api.py` 与 `tests/demo/` 同名冲突，已改名）、`tests/integration/test_instances_registration_api.py`
- [x] 改造 `test_instance_registry.py`、`test_instance_monitor.py`、`test_allocator.py`、`test_allocator_store.py`
- [x] 全量 `pytest console/backend/tests`（基线 405 passed，不得回退）——实测 **449 passed**（新增 44 条）
- [x] 双方言离线迁移与 schema 漂移守卫通过（`alembic upgrade head --sql` sqlite / postgresql 均 exit 0）
- [x] `scripts/validate_catalog_schema.py` exit 0（61 个配置项 ↔ 61 条目录条目）

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| DB 写压力变大 | 条件 UPDATE 单语句；只读走缓存；sqlite 同机亚毫秒 |
| 占位残留导致余量被永久占用 | expire_pending 周期回收；实例删除时清理租约 |
| 门面改造漏改消费点 | `__getattr__` 对未知属性回落到原 pydantic 实例 |
| 迁移未跑导致运行时报错 | 播种与读表都 try/except 降级；迁移是交付前置 |
| 回滚 | 配置回落 env；占位回落内存 store；镜像回退后多余数据无害 |
