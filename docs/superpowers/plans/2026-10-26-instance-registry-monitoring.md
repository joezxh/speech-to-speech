# 实例注册管理 + 运行时监控 + 健康检查（P1.0–P1.6）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按设计文档为 console 落地多实例注册表、常驻巡检与状态机、指标落库、本地分配（双模式）与前端多实例视图，支持无共享多 console（H2-lite）。

**Architecture:** 全部落在 console 现有 `routers / services / repositories / models / config` 分层内：注册表与指标落 SQLite/Postgres（真相源），运行时状态驻留内存（`instance_monitor` 巡检推导实例级状态机），分配走 `AllocatorStore` Protocol（本期 `InMemoryAllocatorStore`，Phase 2 仅换注入）。演示面在 `routers/demo/session.py` 单点分支：`lb_url` 有值逐字保持现有转发，为空且 `ALLOCATOR_MODE=local` 时走本地 allocator。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic（双方言 SQL 由 `scripts/dump_schema_sql.py` 生成）+ httpx + PyYAML（seed）+ pytest；前端 Vue 3 + TypeScript + vitest；实例侧仅改 `websocket_router.py` 一个端点的鉴权。

**Spec:** `docs/superpowers/specs/2026-10-26-instance-registry-monitoring-design.md`（本计划逐节对应其 §4–§17；验收标准即其 §15 表）

## Global Constraints

- 演示面契约不可变：grant / queued / `at_capacity` / expired / 402 / 401；匿名、无 envelope（spec §8.1）。
- `lb_service.py` 不修改；`lb_url` 有值时 `lb_service.start/poll/leave` 调用次数与入参逐字不变（spec §15 P1.4）。
- 运维面统一 `schemas.common.ok` 包裹；降级读仍返回 200（spec §11）。
- TTL/过期判定一律 `time.monotonic`，不用墙钟（spec §8.3、§16）。
- 指标 `size/in_use/free/stuck/probe_ms` 不可得写 `NULL`，不写 0（"no data ≠ zero"，spec §5.2）。
- 审计复用 `param_audit`：`action ∈ instance.drain/undrain/probe/hangup/seed`，`profile` 列存 `instance_id`，`fields` 只存字段名（spec §5.3）。
- 所有新增配置项带默认值且默认功能关闭（`ALLOCATOR_MODE=off`、`INSTANCE_QUEUE_ENABLED=false`、`INSTANCE_WEBRTC_HANGUP_ENABLED=false`）。
- console 单 worker 前提写入 `.env.example` 注释；多 console 必须一致的变量在 `/status` 暴露校验（spec §12）。
- 摘除（offline/draining）只停新分配，绝不触碰活跃会话（spec §6.2、§9）。
- ruff：line-length 120，目标 py311；后端测试命令均在 `console/backend` 下用其 `.venv` 运行；仓库根测试用根 `.venv`。
- 不在分支名/PR 标题中使用 `codex`；不提交 `dist/`、`build/` 等构建产物（AGENTS.md）。

## 文件结构总览（spec §4 表 → 任务映射）

| 阶段 | 新增 | 改造 |
|---|---|---|
| P1.0 | `app/config/_allocator.py`、`app/models/param_instance.py`、`app/models/param_instance_metric.py`、`app/repositories/instance_repository.py`、`app/repositories/instance_metric_repository.py`、`app/services/instance_seed.py`、`alembic/versions/0005_instances.py`、`tests/unit/test_instance_seed.py` | `app/config/__init__.py`、`app/models/__init__.py`、`app/main.py`（lifespan seed）、`alembic/sql/init-*.sql`（重生成）、`.env.example` |
| P1.1 | `app/services/instance_probe.py`、`app/services/instance_registry.py`、`tests/unit/test_instance_probe.py`、`tests/unit/test_instance_registry.py` | `app/services/pool.py`（`base_url` 参数） |
| P1.2 | `app/services/instance_monitor.py`、`tests/unit/test_instance_monitor.py` | `app/main.py`（lifespan 巡检+清理任务） |
| P1.3 | `app/schemas/instance.py`、`tests/integration/test_instances_api.py` | `app/services/instances_service.py`、`app/routers/instances.py`、`app/services/status_service.py` |
| P1.4 | `app/services/allocator_store.py`、`app/services/allocator.py`、`tests/unit/test_allocator_store.py`、`tests/unit/test_allocator.py` | `app/routers/demo/session.py` |
| P1.5 | （前端）`src/api/instances.ts` 扩展、`InstancesView.vue` 重写、汇总卡/表格/趋势图组件 | `src/types/api.d.ts`、`src/i18n/*` |
| P1.6 | `tests/openai_realtime/test_webrtc_hangup_auth.py`、`console/backend/tests/integration/test_instances_hangup_api.py`、`console/backend/tests/unit/test_multi_console_overcommit.py` | `src/speech_to_speech/api/openai_realtime/websocket_router.py`（hangup 鉴权）、`app/routers/instances.py` + `app/core/router_registry.py`（条件注册 hangup）、`app/services/instance_probe.py`（`hangup_call`）、`docs/console-service.md` |

---

# Phase P1.0：配置 + 两张表 + alembic 0005 + seed 幂等

验收（spec §15）：空库启动写入 N 条；重复启动不产生重复行；`read_pool()` 无参行为不变（P1.1 验证）；`test_schema_sql.py` 双方言通过。

## Task 1: AllocatorSettings 配置项

**Files:**
- Create: `console/backend/app/config/_allocator.py`
- Modify: `console/backend/app/config/__init__.py`
- Test: `console/backend/tests/unit/test_allocator_settings.py`

**Interfaces:**
- Consumes: 无
- Produces: `app.config.allocator`（`AllocatorSettings` 单例）：`mode: Literal["off","local"]`、`console_id: str`（默认 `""`）+ `resolved_console_id: str` 属性（空则回退 `socket.gethostname()`）、`seed_path: str`、`probe_interval_s: int`、`probe_timeout_s: int`、`fail_threshold: int`、`recover_threshold: int`、`grant_ttl_s: int`、`usage_interval_s: int`、`metric_retention_days: int`、`queue_enabled: bool`、`webrtc_hangup_enabled: bool`。env 名不靠“字段名大写”的默认规则（前缀不统一），而是逐字段 `validation_alias` 对齐 spec §12 的 `ALLOCATOR_MODE`/`CONSOLE_ID`/`INSTANCES_SEED_PATH`/`INSTANCE_*`，配合 `populate_by_name=True` 使测试仍可按字段名构造

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_allocator_settings.py
from app.config import allocator


def test_defaults_keep_everything_off():
    # spec §12: 全部带默认值，且默认不改行为
    assert allocator.mode == "off"
    assert allocator.queue_enabled is False
    assert allocator.webrtc_hangup_enabled is False
    assert allocator.probe_interval_s == 5
    assert allocator.probe_timeout_s == 2
    assert allocator.fail_threshold == 3
    assert allocator.recover_threshold == 2
    assert allocator.grant_ttl_s == 60
    assert allocator.usage_interval_s == 30
    assert allocator.metric_retention_days == 7
    assert allocator.seed_path == ""


def test_console_id_falls_back_to_the_hostname():
    import socket

    # 字段本身默认空（不在类定义里读 hostname，免得导入时机影响取值），
    # 消费方一律走 resolved_console_id（spec §12：CONSOLE_ID 默认主机名）。
    assert allocator.console_id == ""
    assert allocator.resolved_console_id == socket.gethostname()


def test_env_names_match_the_spec(monkeypatch):
    # spec §12 定死了每个变量的 env 名（前缀不统一），alias 写错字就是静默失效，
    # 所以逐条断言一次真实读取。
    env = {
        "ALLOCATOR_MODE": "local",
        "CONSOLE_ID": "console-2",
        "INSTANCES_SEED_PATH": "/app/instances.yaml",
        "INSTANCE_PROBE_INTERVAL_S": "3",
        "INSTANCE_PROBE_TIMEOUT_S": "4",
        "INSTANCE_FAIL_THRESHOLD": "5",
        "INSTANCE_RECOVER_THRESHOLD": "6",
        "INSTANCE_GRANT_TTL_S": "90",
        "INSTANCE_USAGE_INTERVAL_S": "15",
        "INSTANCE_METRIC_RETENTION_DAYS": "14",
        "INSTANCE_QUEUE_ENABLED": "true",
        "INSTANCE_WEBRTC_HANGUP_ENABLED": "true",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = AllocatorSettings(_env_file=None)
    assert settings.mode == "local"
    assert settings.console_id == "console-2"
    assert settings.resolved_console_id == "console-2"
    assert settings.seed_path == "/app/instances.yaml"
    assert settings.probe_interval_s == 3
    assert settings.probe_timeout_s == 4
    assert settings.fail_threshold == 5
    assert settings.recover_threshold == 6
    assert settings.grant_ttl_s == 90
    assert settings.usage_interval_s == 15
    assert settings.metric_retention_days == 14
    assert settings.queue_enabled is True
    assert settings.webrtc_hangup_enabled is True
```

- [ ] **Step 2: 运行确认失败**

Run: `cd console/backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_allocator_settings.py -v`
Expected: FAIL（`ImportError: cannot import name 'allocator'`）

- [ ] **Step 3: 实现**

```python
# console/backend/app/config/_allocator.py
from __future__ import annotations

import socket
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AllocatorSettings(BaseSettings):
    """实例注册/巡检/本地分配的全部开关（spec §12）。每一项都有默认值，
    默认组合（mode=off + 空 seed）= 本期之前的行为完全不变。

    字段名是代码内的短名，env 名一律走 `validation_alias` 对齐 spec §12 的
    `ALLOCATOR_*` / `INSTANCE_*` / `CONSOLE_ID` / `INSTANCES_SEED_PATH`——前缀不
    统一，所以没法用 `env_prefix`，也不能靠“字段名大写”这条默认规则。
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

    mode: Literal["off", "local"] = Field(default="off", validation_alias="ALLOCATOR_MODE")
    # 指标 observed_by：多 console 无共享多活时区分采样来源（spec §5.2）。
    console_id: str = Field(default="", validation_alias="CONSOLE_ID")
    # 空则跳过 seed，DB 为唯一来源（spec §7）。
    seed_path: str = Field(default="", validation_alias="INSTANCES_SEED_PATH")
    probe_interval_s: int = Field(default=5, validation_alias="INSTANCE_PROBE_INTERVAL_S")
    probe_timeout_s: int = Field(default=2, validation_alias="INSTANCE_PROBE_TIMEOUT_S")
    fail_threshold: int = Field(default=3, validation_alias="INSTANCE_FAIL_THRESHOLD")
    recover_threshold: int = Field(default=2, validation_alias="INSTANCE_RECOVER_THRESHOLD")
    grant_ttl_s: int = Field(default=60, validation_alias="INSTANCE_GRANT_TTL_S")
    usage_interval_s: int = Field(default=30, validation_alias="INSTANCE_USAGE_INTERVAL_S")
    metric_retention_days: int = Field(default=7, validation_alias="INSTANCE_METRIC_RETENTION_DAYS")
    # 本地队列本期关闭：满则 503 at_capacity（spec §3）。
    queue_enabled: bool = Field(default=False, validation_alias="INSTANCE_QUEUE_ENABLED")
    webrtc_hangup_enabled: bool = Field(default=False, validation_alias="INSTANCE_WEBRTC_HANGUP_ENABLED")

    @property
    def resolved_console_id(self) -> str:
        return self.console_id.strip() or socket.gethostname()
```

在 `app/config/__init__.py` 增加（模式与既有 `console = ConsoleSettings()` 一致，直接实例化以便测试 monkeypatch 属性）：

```python
from ._allocator import AllocatorSettings
# 模块级单例：测试里 monkeypatch(allocator_settings, "mode", "local") 即可切换
allocator_settings = AllocatorSettings()
allocator = allocator_settings
```

并把 `"AllocatorSettings"`、`"allocator"`、`"allocator_settings"` 加入 `__all__`。

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_allocator_settings.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/config console/backend/tests/unit/test_allocator_settings.py
git commit -m "feat(console): allocator settings for instance registry (P1.0)"
```

## Task 2: 两张表 ORM + alembic 0005 + 双方言 SQL 重生成

**Files:**
- Create: `console/backend/app/models/param_instance.py`、`console/backend/app/models/param_instance_metric.py`、`console/backend/alembic/versions/0005_instances.py`
- Modify: `console/backend/app/models/__init__.py`、`console/backend/alembic/sql/init-sqlite.sql`、`init-postgresql.sql`（重生成）
- Test: `console/backend/tests/unit/test_schema_sql.py`（既有文件自动覆盖）

**Interfaces:**
- Consumes: `app.db.base.Base/utcnow`
- Produces: `ParamInstance`（列：`id/instance_id/base_url/weight/max_sessions_hint/labels_json/enabled/drain_requested/created_at/updated_at/updated_by`）、`ParamInstanceMetric`（列：`id/instance_id/observed_at/observed_by/kind/size/in_use/free/stuck/status/probe_ms/alloc_ok/alloc_fail_no_instance/alloc_fail_instance_503/evict_count/recover_count`），字段语义见 spec §5.1/§5.2

- [ ] **Step 1: 写模型**

```python
# console/backend/app/models/param_instance.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamInstance(Base):
    """注册表：seed 幂等键是 instance_id；enabled/drain_requested 是运维开关，
    seed 永远不覆盖（spec §7）。"""

    __tablename__ = "param_instance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 声明容量：仅展示与偏差告警，永不参与分配（spec 决策 3）。
    max_sessions_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    labels_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 期望态落库，console 重启后 draining 保持（spec §6.2）。
    drain_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
```

```python
# console/backend/app/models/param_instance_metric.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamInstanceMetric(Base):
    """30s 采样 + 状态跳变即时落。不建 FK：实例删除后指标仍可读（spec §5.2）。
    计数列是采样窗口内的增量，非累计；NULL=不可得，不写 0。"""

    __tablename__ = "param_instance_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    # console 标识（CONSOLE_ID，默认主机名）：多 console 多活必需，聚合按实例取最新不累加。
    observed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="sample")
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_use: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stuck: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    probe_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alloc_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alloc_fail_no_instance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alloc_fail_instance_503: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recover_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

在 `app/models/__init__.py` 按字母序加入 `ParamInstance`、`ParamInstanceMetric` 的 import 与 `__all__` 条目。

- [ ] **Step 2: 写迁移**

```python
# console/backend/alembic/versions/0005_instances.py
"""Instance registry + metrics (spec 2026-10-26 §5).

Revision ID: 0005_instances
Revises: 0004_turn_latency
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_instances"
down_revision = "0004_turn_latency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_instance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("weight", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_sessions_hint", sa.Integer(), nullable=True),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("drain_requested", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.UniqueConstraint("instance_id", name="uq_param_instance_instance_id"),
    )
    op.create_table(
        "param_instance_metric",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_by", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), server_default="sample", nullable=False),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("in_use", sa.Integer(), nullable=True),
        sa.Column("free", sa.Integer(), nullable=True),
        sa.Column("stuck", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("probe_ms", sa.Integer(), nullable=True),
        sa.Column("alloc_ok", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alloc_fail_no_instance", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alloc_fail_instance_503", sa.Integer(), server_default="0", nullable=False),
        sa.Column("evict_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("recover_count", sa.Integer(), server_default="0", nullable=False),
    )
    # 面板读法永远是 "这个实例、这个窗口、最新优先"。
    op.create_index("ix_param_instance_metric_instance_id", "param_instance_metric", ["instance_id"])
    op.create_index("ix_param_instance_metric_observed_at", "param_instance_metric", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_param_instance_metric_observed_at", table_name="param_instance_metric")
    op.drop_index("ix_param_instance_metric_instance_id", table_name="param_instance_metric")
    op.drop_table("param_instance_metric")
    op.drop_table("param_instance")
```

- [ ] **Step 3: 重生成双方言 SQL**

Run: `cd console/backend; .\.venv\Scripts\python.exe scripts/dump_schema_sql.py`
Expected: `wrote alembic\sql\init-sqlite.sql ...`、`wrote alembic\sql\init-postgresql.sql ...`（两个文件各新增两张表 + 索引 + `version_num='0005_instances'`  stamp）

- [ ] **Step 4: 跑漂移守卫**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_schema_sql.py -v`
Expected: PASS（4 个用例：sqlite provisioning、双方言列覆盖、迁移链一致、方言类型）。若失败，说明迁移与模型不一致，修迁移后重跑 Step 3。

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/models console/backend/alembic
git commit -m "feat(console): param_instance + param_instance_metric tables, alembic 0005 (P1.0)"
```

## Task 3: InstanceRepository + InstanceMetricRepository

**Files:**
- Create: `console/backend/app/repositories/instance_repository.py`、`console/backend/app/repositories/instance_metric_repository.py`
- Test: `console/backend/tests/unit/test_instance_repository.py`

**Interfaces:**
- Consumes: `ParamInstance`/`ParamInstanceMetric`（Task 2）、conftest 的 `db_session` fixture
- Produces:
  - `InstanceRepository(session)`：`list_all() -> list[ParamInstance]`、`get_by_instance_id(instance_id) -> ParamInstance | None`、`upsert_seed(*, instance_id, base_url, weight, max_sessions_hint, labels, updated_by="seed") -> tuple[ParamInstance, str]`（Task 4 消费）、`set_drain(instance_id, *, drain: bool, updated_by: str) -> ParamInstance | None`、`set_enabled(instance_id, *, enabled: bool, updated_by: str) -> ParamInstance | None`
  - `InstanceMetricRepository(session)`：`insert_many(rows: list[dict]) -> int`、`window(instance_id, *, since: datetime, observed_by: str | None = None) -> list[ParamInstanceMetric]`、`latest_observed_at() -> datetime | None`（**返回 aware UTC**）、`prune_before(cutoff: datetime) -> int`

  ⚠ SQLite 把 `DateTime(timezone=True)` 读回为 **naive UTC**（已实测），Postgres 读回 aware。任何要与 `utcnow()` 比较的读出值必须先 `replace(tzinfo=UTC)`（仓库同一惯例见 `schemas/common.py:iso_utc`、`identity_service.py:97`），否则 `TypeError: can't compare offset-naive and offset-aware datetimes`。写入侧无此问题：本应用一律存 UTC，绑参时丢时区不改数值。

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_instance_repository.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository


def _row(instance_id="pipe-a", **kw):
    return {
        "instance_id": instance_id,
        "observed_at": datetime.now(UTC),
        "observed_by": "console-1",
        "kind": "sample",
        "size": 4,
        "in_use": 1,
        "free": 3,
        "stuck": None,
        "status": "online",
        "probe_ms": 12,
        **kw,
    }


def test_set_drain_roundtrip_and_updated_by(db_session):
    repo = InstanceRepository(db_session)
    repo.upsert_seed(base_url="http://h:8765", instance_id="pipe-a", weight=1,
                     max_sessions_hint=None, labels={})
    row = repo.set_drain("pipe-a", drain=True, updated_by="alice")
    assert row is not None and row.drain_requested is True and row.updated_by == "alice"
    assert repo.set_drain("pipe-a", drain=False, updated_by="alice").drain_requested is False


def test_metric_window_filters_by_instance_and_since(db_session):
    metrics = InstanceMetricRepository(db_session)
    old = datetime.now(UTC) - timedelta(days=2)
    metrics.insert_many([_row(observed_at=old), _row(), _row(instance_id="pipe-b")])
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    rows = metrics.window("pipe-a", since=cutoff)
    assert len(rows) == 1 and rows[0].observed_by == "console-1"


def test_prune_before_deletes_only_expired(db_session):
    metrics = InstanceMetricRepository(db_session)
    old = datetime.now(UTC) - timedelta(days=30)
    metrics.insert_many([_row(observed_at=old), _row()])
    cutoff = datetime.now(UTC) - timedelta(days=7)
    assert metrics.prune_before(cutoff) == 1
    assert metrics.latest_observed_at() > cutoff
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_instance_repository.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现两个 repository**

`instance_repository.py`（模式对齐既有 `audit_repository.py`：构造入 Session、方法内 commit）：

```python
"""Registry writes are seed-idempotent; runtime state never touches this table
(spec §5.1: DB 为真相源，运行时状态驻留内存)。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.param_instance import ParamInstance


class InstanceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[ParamInstance]:
        return list(self.session.scalars(select(ParamInstance).order_by(ParamInstance.instance_id)))

    def get_by_instance_id(self, instance_id: str) -> ParamInstance | None:
        return self.session.scalar(select(ParamInstance).where(ParamInstance.instance_id == instance_id))

    def upsert_seed(
        self,
        *,
        instance_id: str,
        base_url: str,
        weight: int,
        max_sessions_hint: int | None,
        labels: dict,
        updated_by: str = "seed",
    ) -> tuple[ParamInstance, str]:
        """幂等 upsert（spec §7）。返回 (行, 告警名或 "")：
        新行=("",)；base_url 与 seed 冲突=instance_seed_conflict（以 DB 为准）。
        永不覆盖 enabled / drain_requested——运维开关优先于 seed。"""
        row = self.get_by_instance_id(instance_id)
        alert = ""
        if row is None:
            row = ParamInstance(
                instance_id=instance_id, base_url=base_url, weight=weight,
                max_sessions_hint=max_sessions_hint, labels_json=labels,
                enabled=True, drain_requested=False, updated_by=updated_by,
            )
            self.session.add(row)
        elif row.base_url != base_url:
            alert = "instance_seed_conflict"
            # 其余字段仍同步，只有 base_url 以 DB 为准
            row.weight, row.max_sessions_hint, row.labels_json = weight, max_sessions_hint, labels
            row.updated_at = utcnow()
        else:
            row.base_url, row.weight = base_url, weight
            row.max_sessions_hint, row.labels_json = max_sessions_hint, labels
            row.updated_at = utcnow()
        row.updated_by = updated_by
        self.session.commit()
        self.session.refresh(row)
        return row, alert

    def set_drain(self, instance_id: str, *, drain: bool, updated_by: str) -> ParamInstance | None:
        row = self.get_by_instance_id(instance_id)
        if row is None:
            return None
        row.drain_requested, row.updated_by, row.updated_at = drain, updated_by, utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row

    def set_enabled(self, instance_id: str, *, enabled: bool, updated_by: str) -> ParamInstance | None:
        row = self.get_by_instance_id(instance_id)
        if row is None:
            return None
        row.enabled, row.updated_by, row.updated_at = enabled, updated_by, utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row
```

`instance_metric_repository.py`（双方言：清理按 `observed_at` 删、无方言特判，spec §5.2）：

```python
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.param_instance_metric import ParamInstanceMetric

_COUNT_COLUMNS = ("alloc_ok", "alloc_fail_no_instance", "alloc_fail_instance_503", "evict_count", "recover_count")


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite round-trips `DateTime(timezone=True)` as a *naive* UTC value; Postgres
    returns it aware. Consumers compare against `utcnow()`, so normalize here and
    never let a naive value leak out (same idiom as `schemas/common.py:iso_utc`)."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class InstanceMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert_many(self, rows: list[dict]) -> int:
        prepared = []
        for row in rows:
            data = dict(row)
            for column in _COUNT_COLUMNS:
                data.setdefault(column, 0)
            prepared.append(ParamInstanceMetric(**data))
        self.session.add_all(prepared)
        self.session.commit()
        return len(prepared)

    def window(self, instance_id: str, *, since: datetime, observed_by: str | None = None) -> list[ParamInstanceMetric]:
        stmt = (
            select(ParamInstanceMetric)
            .where(ParamInstanceMetric.instance_id == instance_id, ParamInstanceMetric.observed_at >= since)
            .order_by(ParamInstanceMetric.observed_at.asc())
        )
        if observed_by:
            stmt = stmt.where(ParamInstanceMetric.observed_by == observed_by)
        return list(self.session.scalars(stmt))

    def latest_observed_at(self) -> datetime | None:
        return _as_aware(self.session.scalar(select(func.max(ParamInstanceMetric.observed_at))))

    def prune_before(self, cutoff: datetime) -> int:
        result = self.session.execute(delete(ParamInstanceMetric).where(ParamInstanceMetric.observed_at < cutoff))
        self.session.commit()
        return result.rowcount or 0
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_instance_repository.py -v`
Expected: PASS（3 个用例）。第一个测试用例里用到的 `upsert_seed` 关键字调用形式必须与实现一致。

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/repositories console/backend/tests/unit/test_instance_repository.py
git commit -m "feat(console): instance registry repositories (P1.0)"
```

## Task 4: seed 服务 + lifespan 接入 + .env.example

**Files:**
- Create: `console/backend/app/services/instance_seed.py`、`console/backend/tests/unit/test_instance_seed.py`
- Modify: `console/backend/app/main.py`（lifespan）、`console/backend/.env.example`

**Interfaces:**
- Consumes: `InstanceRepository.upsert_seed`（Task 3）、`app.config.allocator.seed_path`、PyYAML（requirements.txt 已有）
- Produces: `apply_seed(session) -> list[str]`（返回告警名列表；`seed_path` 为空返回 `[]` 不做任何事）；告警名：`instance_removed_from_seed`、`instance_seed_conflict`

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_instance_seed.py
from __future__ import annotations

from app.config import allocator as allocator_settings
from app.repositories.instance_repository import InstanceRepository
from app.services import instance_seed

SEED = """\
instances:
  - id: pipe-a
    base_url: http://192.168.40.31:8765
    weight: 2
    max_sessions_hint: 4
    labels: {rack: A, gpu: "4090"}
  - id: pipe-b
    base_url: http://192.168.40.32:8765
    weight: 1
"""


def _seed_file(tmp_path):
    path = tmp_path / "instances.yaml"
    path.write_text(SEED, encoding="utf-8")
    return str(path)


def test_empty_seed_path_is_a_noop(db_session, monkeypatch):
    monkeypatch.setattr(allocator_settings, "seed_path", "")
    assert instance_seed.apply_seed(db_session) == []
    assert InstanceRepository(db_session).list_all() == []


def test_seed_is_idempotent_and_keeps_ops_flags(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(allocator_settings, "seed_path", _seed_file(tmp_path))
    assert instance_seed.apply_seed(db_session) == []
    repo = InstanceRepository(db_session)
    repo.set_drain("pipe-a", drain=True, updated_by="alice")
    repo.set_enabled("pipe-b", enabled=False, updated_by="bob")
    assert instance_seed.apply_seed(db_session) == []  # 第二次：不重复、不覆盖
    rows = {row.instance_id: row for row in repo.list_all()}
    assert len(rows) == 2
    assert rows["pipe-a"].drain_requested is True
    assert rows["pipe-b"].enabled is False
    assert rows["pipe-a"].weight == 2 and rows["pipe-a"].labels_json == {"rack": "A", "gpu": "4090"}


def test_base_url_conflict_warns_and_keeps_db_value(db_session, tmp_path, monkeypatch):
    repo = InstanceRepository(db_session)
    repo.upsert_seed(instance_id="pipe-a", base_url="http://old:8765", weight=1,
                     max_sessions_hint=None, labels={})
    monkeypatch.setattr(allocator_settings, "seed_path", _seed_file(tmp_path))
    alerts = instance_seed.apply_seed(db_session)
    # 告警带实例 id（`name:instance_id`），多 console 排障时要知道是哪台。
    assert "instance_seed_conflict:pipe-a" in alerts
    assert repo.get_by_instance_id("pipe-a").base_url == "http://old:8765"  # DB 为准（spec §7）


def test_instance_missing_from_seed_only_warns(db_session, tmp_path, monkeypatch):
    repo = InstanceRepository(db_session)
    repo.upsert_seed(instance_id="pipe-z", base_url="http://z:8765", weight=1,
                     max_sessions_hint=None, labels={})
    monkeypatch.setattr(allocator_settings, "seed_path", _seed_file(tmp_path))
    alerts = instance_seed.apply_seed(db_session)
    assert "instance_removed_from_seed:pipe-z" in alerts
    assert repo.get_by_instance_id("pipe-z") is not None  # 不删除
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_instance_seed.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
# console/backend/app/services/instance_seed.py
"""声明式 seed → 幂等 upsert（spec §7）。DB 是真相源：seed 冲突不覆盖 DB 的
base_url，seed 里消失的实例不删除，只告警。审计动作 `instance.seed`。"""

from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger
from sqlalchemy.orm import Session

from app.config import allocator
from app.repositories.instance_repository import InstanceRepository


def load_seed(path: str) -> list[dict]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = raw.get("instances") or []
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id") or not item.get("base_url"):
            logger.warning("instances seed: skipping malformed entry {}", item)
            continue
        out.append(
            {
                "instance_id": str(item["id"]),
                "base_url": str(item["base_url"]).rstrip("/"),
                "weight": int(item.get("weight") or 1),
                "max_sessions_hint": item.get("max_sessions_hint"),
                "labels": dict(item.get("labels") or {}),
            }
        )
    return out


def apply_seed(session: Session) -> list[str]:
    if not allocator.seed_path.strip():
        return []
    path = Path(allocator.seed_path)
    if not path.is_file():
        logger.warning("instances seed configured but {} missing", path)
        return []
    repo = InstanceRepository(session)
    alerts: list[str] = []
    seeded: set[str] = set()
    for item in load_seed(str(path)):
        _, alert = repo.upsert_seed(**item, updated_by="seed")
        seeded.add(item["instance_id"])
        if alert:
            alerts.append(f"{alert}:{item['instance_id']}")
    for row in repo.list_all():
        if row.instance_id not in seeded:
            alerts.append(f"instance_removed_from_seed:{row.instance_id}")
    for alert in alerts:
        logger.warning("instances seed alert: {}", alert)
    return alerts
```

- [ ] **Step 4: 接入 lifespan 并验证空库启动写入 N 条（spec P1.0 验收）**

`app/main.py` lifespan 内、`recover_pending` 之后追加（模式与 bootstrap 一致：坏 DB 不能挡 API 启动）：

```python
        # P1.0: declarative seed is idempotent; a missing/empty path is a no-op.
        try:
            for alert in instance_seed.apply_seed(session):
                logger.warning("instances seed: {}", alert)
        except Exception as exc:  # noqa: BLE001 - a bad seed file must not stop the API
            session.rollback()
            logger.error("instances seed skipped: {}", exc)
```

并在顶部 `from app.services import (...)` 里加入 `instance_seed`。

- [ ] **Step 5: .env.example 记录全部新变量与多 console 前提（spec §12、§16）**

在 `console/backend/.env.example` 末尾追加：

```
# ---- 实例注册 / 巡检 / 本地分配（spec 2026-10-26, P1.0–P1.6）----
# off 保持现状；local 启用 console 本地分配（仅当 LOAD_BALANCER_URL 为空时生效）
ALLOCATOR_MODE=off
CONSOLE_ID=
INSTANCES_SEED_PATH=
INSTANCE_PROBE_INTERVAL_S=5
INSTANCE_PROBE_TIMEOUT_S=2
INSTANCE_FAIL_THRESHOLD=3
INSTANCE_RECOVER_THRESHOLD=2
INSTANCE_GRANT_TTL_S=60
INSTANCE_USAGE_INTERVAL_S=30
INSTANCE_METRIC_RETENTION_DAYS=7
INSTANCE_QUEUE_ENABLED=false
INSTANCE_WEBRTC_HANGUP_ENABLED=false
# 多 console 部署必须各机一致：JWT_SECRET_KEY、USAGE_HASH_SECRET（启用配额时）、
# S2S_ADMIN_TOKEN、S2S_INTERNAL_TOKEN、INSTANCES_SEED_PATH 内容（spec §12）。
# console 必须单 worker：AllocatorStore 为进程内内存实现（spec §13、§16）。
```

- [ ] **Step 6: 全量回归 + 提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit -x -q`
Expected: PASS
说明：空库启动写 N 条已被 `test_seed_is_idempotent_and_keeps_ops_flags` 覆盖（两次 apply 后恰 2 行）。

```bash
git add console/backend/app/services/instance_seed.py console/backend/app/main.py console/backend/.env.example console/backend/tests/unit/test_instance_seed.py
git commit -m "feat(console): instances seed into registry at startup, idempotent (P1.0)"
```

---

# Phase P1.1：instance_probe + 实例级状态机

验收（spec §15）：单测覆盖全部跳变与阈值边界（2 次失败不摘、3 次摘；恢复 2 次）；`stuck` 扣减 `effective_free` 正确。

## Task 5: `pool.read_pool/read_usage` 支持指定 base_url

**Files:**
- Modify: `console/backend/app/services/pool.py:51-82`
- Test: `console/backend/tests/unit/test_pool.py`（追加用例）

**Interfaces:**
- Consumes: `console.pipeline_base_url`（默认值路径不变）
- Produces: `read_pool(timeout: float = 5.0, base_url: str | None = None) -> PoolState`、`read_usage(timeout: float = 5.0, base_url: str | None = None) -> dict | None`、`pool_url(base_url: str | None = None) -> str`

- [ ] **Step 1: 写失败测试（追加到 tests/unit/test_pool.py）**

```python
def test_read_pool_with_explicit_base_url_hits_that_host(monkeypatch):
    seen = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"size": 2, "in_use": 0, "units": []}

    def fake_get(url, timeout):
        seen["url"] = url
        return _Resp()

    monkeypatch.setattr(pool.httpx, "get", fake_get)
    state = pool.read_pool(base_url="http://192.168.40.32:8765/")
    assert seen["url"] == "http://192.168.40.32:8765/v1/pool"  # 尾斜杠被剥
    assert state.reachable and state.size == 2


def test_read_pool_without_argument_still_uses_console_default(monkeypatch):
    seen = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"size": 1, "in_use": 0, "units": []}

    monkeypatch.setattr(pool.httpx, "get", lambda url, timeout: seen.update(url=url) or _Resp())
    monkeypatch.setattr("app.services.pool.console.pipeline_base_url", "http://127.0.0.1:8765")
    pool.read_pool()
    assert seen["url"] == "http://127.0.0.1:8765/v1/pool"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_pool.py -v`
Expected: 新用例 FAIL（`read_pool() got an unexpected keyword argument 'base_url'`），旧用例仍 PASS——这同时钉住 spec P1.0 验收 "无参行为不变"。

- [ ] **Step 3: 实现（保持既有函数体，仅参数化 URL）**

```python
def pool_url(base_url: str | None = None) -> str:
    return (base_url or console.pipeline_base_url).rstrip("/")


def read_pool(timeout: float = 5.0, base_url: str | None = None) -> PoolState:
    try:
        response = httpx.get(f"{pool_url(base_url)}/v1/pool", timeout=timeout)
        ...  # 其余逐字不变


def read_usage(timeout: float = 5.0, base_url: str | None = None) -> dict[str, Any] | None:
    try:
        response = httpx.get(f"{pool_url(base_url)}/v1/usage", timeout=timeout)
        ...  # 其余逐字不变
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_pool.py tests/integration/test_instances.py -v`
Expected: PASS（集成测试用 `lambda timeout=5.0: ...` monkeypatch `read_pool`，签名兼容——若失败，检查新参数是否用了关键字默认值而非位置参数）。

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/services/pool.py console/backend/tests/unit/test_pool.py
git commit -m "feat(console): pool readers accept an explicit instance base_url (P1.1)"
```

## Task 6: instance_probe（对指定实例探测并归一化）

**Files:**
- Create: `console/backend/app/services/instance_probe.py`
- Test: `console/backend/tests/unit/test_instance_probe.py`

**Interfaces:**
- Consumes: `pool.read_pool(timeout, base_url)` / `pool.read_usage(timeout, base_url)`（Task 5）
- Produces:
  - `PoolProbe(ok: bool, state: pool.PoolState | None, probe_ms: int, error: str)`（frozen dataclass）
  - `probe_pool(base_url: str, timeout: float = 2.0) -> PoolProbe`
  - `probe_usage(base_url: str, timeout: float = 5.0) -> dict | None`

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_instance_probe.py
from __future__ import annotations

from app.services import instance_probe, pool


def test_probe_pool_ok_records_elapsed_and_snapshot(monkeypatch):
    state = pool.PoolState(reachable=True, size=2, in_use=1,
                           units=({"index": 0, "state": "active", "session_id": "s"},
                                  {"index": 1, "state": "idle", "session_id": None}))
    monkeypatch.setattr(pool, "read_pool", lambda timeout=5.0, base_url=None: state)
    out = instance_probe.probe_pool("http://h:8765", timeout=2.0)
    assert out.ok and out.state is state and out.probe_ms >= 0 and out.error == ""


def test_probe_pool_unreachable_is_not_ok(monkeypatch):
    monkeypatch.setattr(pool, "read_pool",
                        lambda timeout=5.0, base_url=None: pool.PoolState(reachable=False, error="refused"))
    out = instance_probe.probe_pool("http://h:8765")
    assert not out.ok and out.error == "refused" and out.state is None


def test_probe_usage_passthrough(monkeypatch):
    monkeypatch.setattr(pool, "read_usage", lambda timeout=5.0, base_url=None: {"turns": 1})
    assert instance_probe.probe_usage("http://h:8765") == {"turns": 1}
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_instance_probe.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
# console/backend/app/services/instance_probe.py
"""对**指定**实例地址读 pool/usage 并归一化（spec §4 表）。

替换点在 `pool.read_pool/read_usage` 这一层：与 `lb_service._http` 的
"单独一层测试替换点" 惯例一致（spec §17）。探测不新增实例侧端点。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.services import pool


@dataclass(frozen=True)
class PoolProbe:
    ok: bool
    state: pool.PoolState | None
    probe_ms: int
    error: str = ""


def probe_pool(base_url: str, timeout: float = 2.0) -> PoolProbe:
    started = time.monotonic()
    state = pool.read_pool(timeout=timeout, base_url=base_url)
    elapsed = int((time.monotonic() - started) * 1000)
    if not state.reachable:
        return PoolProbe(ok=False, state=None, probe_ms=elapsed, error=state.error)
    return PoolProbe(ok=True, state=state, probe_ms=elapsed)


def probe_usage(base_url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    # usage 失败不参与健康判定，只产生 usage_unavailable 告警（spec §9）。
    return pool.read_usage(timeout=timeout, base_url=base_url)
```

- [ ] **Step 4: 运行确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/services/instance_probe.py console/backend/tests/unit/test_instance_probe.py
git commit -m "feat(console): per-instance pool/usage probe (P1.1)"
```

## Task 7: instance_registry 实例级状态机

**Files:**
- Create: `console/backend/app/services/instance_registry.py`
- Test: `console/backend/tests/unit/test_instance_registry.py`

**Interfaces:**
- Consumes: `PoolProbe`（Task 6）、`ParamInstance`（Task 2）
- Produces:
  - `RuntimeState`（可变 dataclass）：`instance_id, status: str, pool: PoolState | None, probe_ms: int | None, usage: dict | None, consecutive_failures: int, consecutive_successes: int, last_error: str, probe_history: list[int]`（滚动 20 次，供 p50/p95）+ 属性 `effective_free` / `p95_probe_ms`
  - `InstanceRegistry(fail_threshold: int = 3, recover_threshold: int = 2)`：`sync(specs: list[tuple[instance_id, base_url, weight, enabled, drain_requested]]) -> None`、`observe_success(instance_id, state: PoolProbe 的 PoolState, probe_ms: int) -> RuntimeState`、`observe_failure(instance_id, error: str) -> RuntimeState`、`set_drain(instance_id, drain: bool) -> RuntimeState`、`get(instance_id) -> RuntimeState | None`、`snapshot() -> dict[str, RuntimeState]`
  - 状态常量 `ONLINE/OFFLINE/DEGRADED/DRAINING/UNKNOWN`，边沿事件枚举供 monitor 记 `evict_count/recover_count`

- [ ] **Step 1: 写失败测试（阈值边界 + 全跳变，spec §6.2 mermaid 逐边）**

```python
# console/backend/tests/unit/test_instance_registry.py
from __future__ import annotations

import pytest

from app.services.instance_registry import InstanceRegistry
from app.services.pool import PoolState


def _pool(size=4, in_use=0, stuck=0):
    units = []
    for i in range(size):
        if i < stuck:
            units.append({"index": i, "state": "stuck", "session_id": None})
        elif i < in_use:
            units.append({"index": i, "state": "active", "session_id": f"s{i}"})
        else:
            units.append({"index": i, "state": "idle", "session_id": None})
    return PoolState(reachable=True, size=size, in_use=in_use, units=tuple(units))


@pytest.fixture
def reg():
    r = InstanceRegistry(fail_threshold=3, recover_threshold=2)
    r.sync([("pipe-a", "http://a:8765", 1, True, False)])
    return r


def test_starts_unknown_and_not_allocatable(reg):
    state = reg.get("pipe-a")
    assert state.status == "unknown"
    assert reg.allocatable() == []


def test_first_success_goes_online(reg):
    assert reg.observe_success("pipe-a", _pool(), 10).status == "online"


def test_two_failures_do_not_evict_three_do(reg):
    reg.observe_success("pipe-a", _pool(), 10)
    reg.observe_failure("pipe-a", "timeout")
    reg.observe_failure("pipe-a", "timeout")
    assert reg.get("pipe-a").status == "online"  # 2 次不摘（spec §15 P1.1）
    assert reg.observe_failure("pipe-a", "timeout").status == "offline"  # 第 3 次摘


def test_recovery_needs_two_successes(reg):
    reg.observe_failure("pipe-a", "x"); reg.observe_failure("pipe-a", "x"); reg.observe_failure("pipe-a", "x")
    assert reg.get("pipe-a").status == "offline"
    reg.observe_success("pipe-a", _pool(), 5)
    assert reg.get("pipe-a").status == "offline"  # 1 次不恢复
    assert reg.observe_success("pipe-a", _pool(), 5).status == "online"  # 2 次恢复


def test_stuck_makes_degraded_then_clearing_returns_online(reg):
    reg.observe_success("pipe-a", _pool(stuck=1), 5)
    assert reg.get("pipe-a").status == "degraded"
    assert reg.observe_success("pipe-a", _pool(), 5).status == "online"


def test_drain_wins_over_probe_results_and_undrain_restores(reg):
    reg.observe_success("pipe-a", _pool(), 5)
    assert reg.set_drain("pipe-a", True).status == "draining"
    reg.observe_success("pipe-a", _pool(stuck=2), 5)  # 探测不改变 draining
    assert reg.get("pipe-a").status == "draining"
    assert reg.set_drain("pipe-a", False).status == "online"  # 已有健康探测结果，直接回 online


def test_undrain_from_draining_without_any_probe_goes_unknown(reg):
    r = InstanceRegistry(fail_threshold=3, recover_threshold=2)
    r.sync([("pipe-b", "http://b:8765", 1, True, True)])  # 重启后 drain_requested 保持
    assert r.get("pipe-b").status == "draining"
    assert r.set_drain("pipe-b", False).status == "unknown"  # 从未探过，等首轮巡检


def test_effective_free_subtracts_in_use_and_stuck(reg):
    reg.observe_success("pipe-a", _pool(size=4, in_use=2, stuck=1), 5)
    state = reg.get("pipe-a")
    assert state.effective_free == 1  # max(0, 4-2-1-0)，pending 由 allocator 再扣（spec §6.2）


def test_probe_history_keeps_rolling_20_for_percentiles(reg):
    for i in range(25):
        reg.observe_success("pipe-a", _pool(), i)
    assert len(reg.get("pipe-a").probe_history) == 20
    assert reg.get("pipe-a").p95_probe_ms is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_instance_registry.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
# console/backend/app/services/instance_registry.py
"""实例级状态机（spec §6.2）：console 巡检推导，驻留内存。

两层状态绝不混用：unit 级（idle/active/draining/stuck）原样来自 /v1/pool；
这里只管机器级 unknown/online/degraded/offline/draining。摘除只停新分配，
本模块不触碰任何活跃会话（spec §9）。draining 是期望态：drain 优先于一切
探测结果，undrain 后按"是否已有一次成功探测"决定回 online 还是 unknown。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.pool import PoolState

UNKNOWN, ONLINE, DEGRADED, OFFLINE, DRAINING = "unknown", "online", "degraded", "offline", "draining"
PROBE_HISTORY = 20
# 巡检据此记 evict_count / recover_count（spec §10）
EVICTED, RECOVERED = "evicted", "recovered"


@dataclass
class RuntimeState:
    instance_id: str
    base_url: str
    weight: int = 1
    enabled: bool = True
    status: str = UNKNOWN
    pool: PoolState | None = None
    probe_ms: int | None = None
    usage: dict | None = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_error: str = ""
    probe_history: list[int] = field(default_factory=list)

    @property
    def effective_free(self) -> int:
        # pending_local 由 allocator 在选台时再扣（spec §6.2 容量建模）。
        if self.pool is None or self.status not in (ONLINE, DEGRADED):
            return 0
        return max(0, self.pool.size - self.pool.in_use - self.pool.stuck)

    @property
    def p95_probe_ms(self) -> int | None:
        return self._percentile(0.95)

    @property
    def p50_probe_ms(self) -> int | None:
        return self._percentile(0.5)

    def _percentile(self, q: float) -> int | None:
        if not self.probe_history:
            return None
        ordered = sorted(self.probe_history)
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


class InstanceRegistry:
    def __init__(self, fail_threshold: int = 3, recover_threshold: int = 2) -> None:
        self._fail_threshold = max(1, fail_threshold)
        self._recover_threshold = max(1, recover_threshold)
        self._states: dict[str, RuntimeState] = {}

    def sync(self, specs: list[tuple[str, str, int, bool, bool]]) -> None:
        """与注册表对齐：新增补 unknown，删除消失的，enabled/weight/drain 同步。
        specs = [(instance_id, base_url, weight, enabled, drain_requested)]。"""
        seen = set()
        for instance_id, base_url, weight, enabled, drain in specs:
            seen.add(instance_id)
            state = self._states.get(instance_id)
            if state is None:
                state = RuntimeState(instance_id=instance_id, base_url=base_url)
                self._states[instance_id] = state
            state.base_url, state.weight, state.enabled = base_url, weight, enabled
            if not enabled:
                state.status = OFFLINE if state.pool is None else state.status
            if drain and state.status != OFFLINE:
                state.status = DRAINING
            elif not drain and state.status == DRAINING:
                state.status = ONLINE if state.pool is not None else UNKNOWN
        for gone in [k for k in self._states if k not in seen]:
            del self._states[gone]

    def get(self, instance_id: str) -> RuntimeState | None:
        return self._states.get(instance_id)

    def snapshot(self) -> dict[str, RuntimeState]:
        return dict(self._states)

    def allocatable(self) -> list[RuntimeState]:
        # spec §8.2 过滤条件：enabled、weight>0、online/degraded、有余量。
        return [
            s for s in self._states.values()
            if s.enabled and s.weight > 0 and s.status in (ONLINE, DEGRADED) and s.effective_free > 0
        ]

    def observe_success(self, instance_id: str, pool_state: PoolState, probe_ms: int) -> RuntimeState:
        state = self._states[instance_id]
        state.pool, state.probe_ms, state.last_error = pool_state, probe_ms, ""
        state.probe_history = (state.probe_history + [probe_ms])[-PROBE_HISTORY:]
        state.consecutive_failures, state.consecutive_successes = 0, state.consecutive_successes + 1
        if state.status == DRAINING:  # 期望态压过探测
            return state
        if state.status == OFFLINE:
            if state.consecutive_successes >= self._recover_threshold:
                state.status = ONLINE
            return state
        state.status = DEGRADED if pool_state.stuck else ONLINE
        return state

    def observe_failure(self, instance_id: str, error: str) -> RuntimeState:
        state = self._states[instance_id]
        state.last_error, state.pool, state.usage = error, None, None
        state.consecutive_successes, state.consecutive_failures = 0, state.consecutive_failures + 1
        if state.status == DRAINING:
            return state
        if state.consecutive_failures >= self._fail_threshold:
            # offline 期间保持摘除，直到恢复阈值（抖动抑制，spec §9）。
            state.status = OFFLINE
        return state

    def set_drain(self, instance_id: str, drain: bool) -> RuntimeState:
        state = self._states[instance_id]
        if drain:
            state.status = DRAINING
        else:
            state.status = ONLINE if state.pool is not None else UNKNOWN
        return state
```

- [ ] **Step 4: 运行确认通过** → 全部 PASS。注意 `EVICTED/RECOVERED` 常量在 P1.2 monitor 中使用（跳变边沿检测：状态从非 OFFLINE 变 OFFLINE = EVICTED，从 OFFLINE 变 ONLINE = RECOVERED）。

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/services/instance_registry.py console/backend/tests/unit/test_instance_registry.py
git commit -m "feat(console): instance-level state machine with evict/recover thresholds (P1.1)"
```

---

# Phase P1.2：常驻巡检 + 视图缓存 + 指标落库与清理

验收（spec §15）：停一台 15s 内 `offline`、恢复 10s 内 `online`；采样行按 30s 落、跳变即时落；过期清理生效；任务异常不杀循环。

## Task 8: instance_monitor（巡检循环 + 缓存 + 指标）

**Files:**
- Create: `console/backend/app/services/instance_monitor.py`
- Modify: `console/backend/app/main.py`（lifespan 启停，与 `turn_latency_indexer` 同级）
- Test: `console/backend/tests/unit/test_instance_monitor.py`

**Interfaces:**
- Consumes: `InstanceRegistry`/`RuntimeState`/`EVICTED`/`RECOVERED`（Task 7）、`instance_probe.probe_pool/probe_usage`（Task 6）、`InstanceRepository`（Task 3）、`InstanceMetricRepository`（Task 3）、`app.config.allocator`
- Produces:
  - 模块级单例 `registry: InstanceRegistry`、`runtime: dict[str, RuntimeState]`（即 `registry.snapshot()`）
  - `refresh_specs(session) -> None`（注册表 → registry.sync，启动与每轮调用）
  - `probe_all(session) -> None`（一轮：gather 全部实例，更新状态机，跳变即时落指标）
  - `snapshot() -> dict[str, RuntimeState]`（2s 防抖读缓存，同 `runtime_service._TTL_S` 思路）
  - `invalidate() -> None`（发布成功后强制失效，spec §9.1）
  - `sample_metrics(session) -> None`（30s 采样落库 + 读取并清零 allocator 计数器）
  - `prune_metrics(session) -> int`（保留期清理）
  - `run_forever()`（async，lifespan 启停；异常只记日志不杀任务，同 `_usage_sweeper`）

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_instance_monitor.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import allocator as allocator_settings
from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository
from app.services import instance_monitor, instance_probe
from app.services.pool import PoolState


@pytest.fixture
def two_instances(db_session, monkeypatch):
    monkeypatch.setattr(allocator_settings, "metric_retention_days", 7)
    repo = InstanceRepository(db_session)
    repo.upsert_seed(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                     max_sessions_hint=None, labels={})
    repo.upsert_seed(instance_id="pipe-b", base_url="http://b:8765", weight=1,
                     max_sessions_hint=None, labels={})
    instance_monitor.reset_for_tests()
    instance_monitor.refresh_specs(db_session)
    return db_session


def _healthy(timeout=True):
    return instance_probe.PoolProbe(
        ok=True, probe_ms=10,
        state=PoolState(reachable=True, size=2, in_use=0,
                        units=({"index": 0, "state": "idle"}, {"index": 1, "state": "idle"})),
    )


def _down(timeout=True):
    return instance_probe.PoolProbe(ok=False, probe_ms=50, state=None, error="refused")


def test_three_failures_evict_within_the_probe_budget(two_instances, monkeypatch):
    # spec §15 P1.2：连续 3 次失败 ≈ 15s 摘除（5s 间隔 × 3）
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _down())
    for _ in range(2):
        instance_monitor.probe_all(two_instances)
        assert instance_monitor.registry.get("pipe-a").status != "offline"
    instance_monitor.probe_all(two_instances)
    assert instance_monitor.registry.get("pipe-a").status == "offline"


def test_state_change_writes_an_immediate_metric_row(two_instances, monkeypatch):
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _healthy())
    instance_monitor.probe_all(two_instances)
    rows = InstanceMetricRepository(two_instances).window(
        "pipe-a", since=datetime.now(tz=UTC).replace(year=datetime.now(UTC).year - 1))
    assert len(rows) == 1 and rows[0].kind == "state_change" and rows[0].status == "online"
    assert rows[0].observed_by == allocator_settings.resolved_console_id


def test_sample_metrics_writes_null_for_unreachable_not_zero(two_instances, monkeypatch):
    # spec §5.2 "no data != zero"：offline 的实例采样行 size/in_use 必须是 NULL
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _down())
    for _ in range(3):
        instance_monitor.probe_all(two_instances)
    instance_monitor.sample_metrics(two_instances)
    rows = InstanceMetricRepository(two_instances).window(
        "pipe-a", since=datetime.now(tz=UTC).replace(year=datetime.now(UTC).year - 1))
    sample = [r for r in rows if r.kind == "sample"]
    assert len(sample) == 1 and sample[0].size is None and sample[0].in_use is None
    assert sample[0].status == "offline"


def test_prune_metrics_honours_retention(two_instances, monkeypatch):
    metrics = InstanceMetricRepository(two_instances)
    metrics.insert_many([
        {"instance_id": "pipe-a", "observed_at": datetime.now(UTC), "observed_by": "c",
         "kind": "sample", "status": "online"},
        {"instance_id": "pipe-a", "observed_at": datetime(2020, 1, 1, tzinfo=UTC),
         "observed_by": "c", "kind": "sample", "status": "online"},
    ])
    monkeypatch.setattr(allocator_settings, "metric_retention_days", 7)
    assert instance_monitor.prune_metrics(two_instances) == 1


def test_probe_exception_in_one_instance_does_not_break_the_round(two_instances, monkeypatch):
    def flaky(base_url, timeout=2.0):
        if base_url.endswith("b:8765"):
            raise RuntimeError("boom")
        return _healthy()

    monkeypatch.setattr(instance_probe, "probe_pool", flaky)
    instance_monitor.probe_all(two_instances)  # 不抛
    assert instance_monitor.registry.get("pipe-a").status == "online"
    assert instance_monitor.registry.get("pipe-b").status == "unknown"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_instance_monitor.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
# console/backend/app/services/instance_monitor.py
"""常驻巡检：一轮 gather 探全部实例，单台超时不阻塞其余（spec §9）。

跳变即时落 `state_change` 指标；30s 采样落 `sample`；读接口走 2s 防抖缓存
（与 runtime_service._TTL_S 同思路）；任务异常只记日志（同 _usage_sweeper）。
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.config import allocator
from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository
from app.services import instance_probe
from app.services.instance_registry import OFFLINE, ONLINE, EVICTED, RECOVERED, InstanceRegistry

_SNAPSHOT_TTL_S = 2.0
# 边沿事件 → 指标列名（Task 7 的 EVICTED/RECOVERED 是事件标签，落库键必须是 §5.2 的列）
_EDGE_COUNTERS = {EVICTED: "evict_count", RECOVERED: "recover_count"}

registry = InstanceRegistry(fail_threshold=allocator.fail_threshold,
                            recover_threshold=allocator.recover_threshold)
_snapshot_cache: tuple[float, dict[str, Any]] | None = None


def reset_for_tests() -> None:
    """重新绑定模块级注册表。下游模块（allocator_store / allocator）必须采用
    `instance_monitor.registry` 的晚绑定形式，否则测试里拿到的还是旧对象。"""
    global registry, _snapshot_cache
    registry = InstanceRegistry(fail_threshold=allocator.fail_threshold,
                                recover_threshold=allocator.recover_threshold)
    _snapshot_cache = None


def refresh_specs(session: Session) -> None:
    rows = InstanceRepository(session).list_all()
    registry.sync([(r.instance_id, r.base_url, r.weight, r.enabled, r.drain_requested) for r in rows])


def _write_metric(session: Session, instance_id: str, *, kind: str, counters: dict[str, int] | None = None) -> None:
    state = registry.get(instance_id)
    if state is None:
        return
    pool = state.pool
    row = {
        "instance_id": instance_id,
        "observed_at": datetime.now(UTC),
        "observed_by": allocator.resolved_console_id,
        "kind": kind,
        # NULL=不可得：offline 的实例绝不写 0（spec §5.2）。
        "size": pool.size if pool else None,
        "in_use": pool.in_use if pool else None,
        "free": state.effective_free if pool else None,
        "stuck": pool.stuck if pool else None,
        "status": state.status,
        "probe_ms": state.probe_ms,
    }
    row.update(counters or {})
    InstanceMetricRepository(session).insert_many([row])


def probe_all(session: Session) -> None:
    """一轮巡检：对每个已注册实例探测一次，状态跳变即时落指标。"""
    refresh_specs(session)
    for instance_id, state in list(registry.snapshot().items()):
        before = state.status
        try:
            probe = instance_probe.probe_pool(state.base_url, timeout=allocator.probe_timeout_s)
        except Exception as exc:  # noqa: BLE001 - 单台异常不能杀整轮（spec §9）
            logger.warning("probe {} raised: {}", instance_id, exc)
            state = registry.observe_failure(instance_id, f"{type(exc).__name__}: {exc}")
        else:
            if probe.ok and probe.state is not None:
                state = registry.observe_success(instance_id, probe.state, probe.probe_ms)
            else:
                state = registry.observe_failure(instance_id, probe.error)
        if state.status != before:
            # 边沿计数：摘除/恢复各 +1，只写进这一行 state_change（spec §10）
            counters: dict[str, int] = {}
            if state.status == OFFLINE and before != OFFLINE:
                counters[_EDGE_COUNTERS[EVICTED]] = 1
            elif state.status == ONLINE and before == OFFLINE:
                counters[_EDGE_COUNTERS[RECOVERED]] = 1
            _write_metric(session, instance_id, kind="state_change", counters=counters)
    _invalidate_cache()


def sample_metrics(session: Session, counters: dict[str, int] | None = None) -> None:
    """30s 采样：usage 顺带刷新（失败不判健康，spec §9）。

    counters 由调用方从 allocator.drain_counters() 取来（P1.4 接线）：
    全局键 `alloc_fail_no_instance` 写进每行；`alloc_ok:{id}` /
    `alloc_fail_instance_503:{id}` 只写对应实例（spec §10：窗口增量非累计）。
    """
    for instance_id, state in list(registry.snapshot().items()):
        if state.pool is not None:
            usage = instance_probe.probe_usage(state.base_url, timeout=allocator.probe_timeout_s)
            if usage is None and state.usage is not None:
                logger.warning("usage_unavailable: {}", instance_id)
            state.usage = usage
    deltas = counters or {}
    for instance_id in registry.snapshot():
        _write_metric(session, instance_id, kind="sample", counters=_counters_for(instance_id, deltas))
    _invalidate_cache()


def _counters_for(instance_id: str, deltas: dict[str, int]) -> dict[str, int] | None:
    out: dict[str, int] = {}
    if "alloc_fail_no_instance" in deltas:
        out["alloc_fail_no_instance"] = deltas["alloc_fail_no_instance"]
    if f"alloc_ok:{instance_id}" in deltas:
        out["alloc_ok"] = deltas[f"alloc_ok:{instance_id}"]
    if f"alloc_fail_instance_503:{instance_id}" in deltas:
        out["alloc_fail_instance_503"] = deltas[f"alloc_fail_instance_503:{instance_id}"]
    return out or None


def prune_metrics(session: Session) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=allocator.metric_retention_days)
    return InstanceMetricRepository(session).prune_before(cutoff)


def _invalidate_cache() -> None:
    global _snapshot_cache
    _snapshot_cache = None


def invalidate() -> None:
    """发布成功后调用，让面板立即反映新状态（spec §9.1）。"""
    _invalidate_cache()


def snapshot() -> dict[str, Any]:
    """读接口的 2s 防抖入口；巡检写入时已失效，这里只防读侧风暴。"""
    global _snapshot_cache
    now = time.monotonic()
    if _snapshot_cache and now - _snapshot_cache[0] < _SNAPSHOT_TTL_S:
        return _snapshot_cache[1]
    data = registry.snapshot()
    _snapshot_cache = (now, data)
    return data


async def run_forever() -> None:
    """lifespan 启停（与 turn_latency_indexer.run_forever 同模式）。

    每 tick：probe_all；每 usage_interval_s 一次 sample_metrics；每小时一次 prune。
    任何异常只记日志，循环不死（spec §9/§15 P1.2）。
    """
    from app.db.database import SessionLocal  # noqa: PLC0415 - 避免 import 环

    ticks = 0
    while True:
        await asyncio.sleep(allocator.probe_interval_s)
        session = SessionLocal()
        try:
            await asyncio.to_thread(probe_all, session)
            ticks += 1
            if ticks * allocator.probe_interval_s >= allocator.usage_interval_s:
                ticks = 0
                # P1.4 交付后 allocator 已存在：窗口增量从计数器取（spec §10）。
                from app.services import allocator as allocator_service  # noqa: PLC0415

                deltas = allocator_service.drain_counters()
                await asyncio.to_thread(sample_metrics, session, deltas)
                await asyncio.to_thread(prune_metrics, session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("instance monitor tick failed: {}", exc)
            session.rollback()
        finally:
            session.close()
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_instance_monitor.py -v`
Expected: PASS（6 个用例）。本任务阶段 `run_forever` 引用 `allocator.drain_counters`（Task 13 才交付）：lifespan 只在 `mode!="off"` 或配了 seed 时才启动巡检，而默认开关是 off，所以 P1.2 阶段不会触发 ImportError；测试全部直接调 `probe_all`/`sample_metrics`，不经 `run_forever`。

- [ ] **Step 5: lifespan 接线**

`app/main.py`：与 `indexer` 同样创建/取消巡检任务——注意只有配置了 seed 或注册表非空才启动没有意义，直接按开关启动：

```python
    monitor: asyncio.Task | None = None
    if allocator_settings.mode != "off" or allocator_settings.seed_path.strip():
        monitor = asyncio.create_task(instance_monitor.run_forever())
    try:
        yield
    finally:
        if monitor is not None:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor
        indexer.cancel()
        ...
```

（`from app.config import allocator as allocator_settings`、`from app.services import instance_monitor`。）

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_instance_monitor.py tests/integration/test_instances.py -v` → PASS

- [ ] **Step 6: 提交**

```bash
git add console/backend/app/services/instance_monitor.py console/backend/app/main.py console/backend/tests/unit/test_instance_monitor.py
git commit -m "feat(console): resident instance monitor with metrics sampling and pruning (P1.2)"
```

---

# Phase P1.3：GET 聚合改造 + drain/undrain/probe + 审计

验收（spec §15）：旧字段断言全绿（向后兼容）；drain 后 allocator 不再选它；`param_audit` 有 `instance.drain` 行。

## Task 9: instances_service 多实例聚合（旧字段全保留）

**Files:**
- Modify: `console/backend/app/services/instances_service.py`
- Test: `console/backend/tests/integration/test_instances.py`（既有两个用例就是向后兼容断言，必须不改一行代码地继续通过）

**Interfaces:**
- Consumes: `instance_monitor.snapshot()`（Task 8）、`InstanceRepository`（Task 3）、`process_probe`、`pool`（单实例 legacy 路径）
- Produces: `collect(profile: str, version: int | None, *, db: Session) -> dict`，返回结构：旧键 `container/pool/usage/alerts/profile/version` 逐字保留；新增 `summary: {instances_total, online, offline, degraded, draining, slots_total, slots_in_use, slots_free, pending_grants}` 与 `instances: [ {instance_id, base_url, status, weight, enabled, drain_requested, size, in_use, free, stuck, probe_ms, p95_probe_ms, units, last_error, observed_by, declared_mismatch} ]`（spec §10/§11）

- [ ] **Step 1: 先跑既有兼容基线**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_instances.py -v -k "instances"`
Expected: 当前 PASS，作为改造后必须仍 PASS 的断言集（`pool_unreachable`/`pipeline_stopped`/`units` 结构）。

- [ ] **Step 2: 实现双路径聚合**

关键不变量：`ParamInstance` 表为空（未配置注册表）时，`collect` 的旧字段取自现有的 `pool.read_pool()`/`read_usage()` 直连路径，不进入 monitor 缓存——这保证现有测试的 `monkeypatch.setattr(pool, "read_pool", lambda timeout=5.0: ...)` 替换点继续生效；注册表非空时，旧字段取本机实例（`base_url == console.pipeline_base_url`）的巡检视图，`pool` 为 `None` 当且仅当探不到（降级语义不变）。

```python
# console/backend/app/services/instances_service.py（改造后主体）
def collect(profile: str, version: int | None, *, db) -> dict[str, Any]:
    rows = InstanceRepository(db).list_all()
    if rows:
        return _collect_registry(profile, version, rows)
    return _collect_legacy(profile, version)


def _collect_legacy(profile, version):
    # 原函数体逐字搬到这里：read_pool()/read_usage()/process_probe/alerts 不变。
    ...


def _collect_registry(profile, version, rows):
    view = instance_monitor.snapshot()
    local = view.get(next((r.instance_id for r in rows
                          if r.base_url.rstrip("/") == console.pipeline_base_url.rstrip("/")), ""))
    info = process_probe.get_probe().state(console.supervisor_program)
    alerts: list[str] = []
    instances = []
    for row in rows:
        state = view.get(row.instance_id)
        reachable = state is not None and state.pool is not None
        if not reachable:
            alerts.append(f"pool_unreachable:{row.instance_id}")
        elif state.pool.stuck:
            alerts.append(f"pool_stuck:{row.instance_id}")
        if row.max_sessions_hint and reachable and state.pool.size != row.max_sessions_hint:
            alerts.append(f"instance_capacity_mismatch:{row.instance_id}")  # spec §6.2
        instances.append({
            "instance_id": row.instance_id, "base_url": row.base_url,
            "status": state.status if state else "unknown",
            "weight": row.weight, "enabled": row.enabled,
            "drain_requested": row.drain_requested,
            "size": state.pool.size if reachable else None,
            "in_use": state.pool.in_use if reachable else None,
            "free": state.effective_free if reachable else None,
            "stuck": state.pool.stuck if reachable else None,
            "probe_ms": state.probe_ms if state else None,
            "p95_probe_ms": state.p95_probe_ms if state else None,
            "units": [ {"index": u.get("index"), "state": u.get("state"),
                        "sessionId": u.get("session_id")} for u in (state.pool.units if reachable else ()) ],
            "last_error": state.last_error if state else "",
            "observed_by": allocator.resolved_console_id,
            "declared_mismatch": bool(row.max_sessions_hint) and reachable
            and state.pool.size != row.max_sessions_hint,
        })
    # pending_grants 在 P1.4 Task 13 接 allocator.pending_count()；本阶段 P1.4 未交付，
    # 先置 0 保留键位（前端 Task 15 已按可缺省字段处理）。
    summary = {
        "instances_total": len(instances),
        "online": sum(1 for i in instances if i["status"] == "online"),
        "offline": sum(1 for i in instances if i["status"] == "offline"),
        "degraded": sum(1 for i in instances if i["status"] == "degraded"),
        "draining": sum(1 for i in instances if i["status"] == "draining"),
        "slots_total": sum(i["size"] or 0 for i in instances),
        "slots_in_use": sum(i["in_use"] or 0 for i in instances),
        "slots_free": sum(i["free"] or 0 for i in instances),
        "pending_grants": 0,  # Task 13 接线：改 allocator.pending_count() 并删上行注释
    }
    legacy_pool = local.pool if local and local.pool else None
    return {
        "profile": profile, "version": version,
        "container": _container_block(info),  # 与 legacy 分支同构，字段逐字不变
        "pool": None if legacy_pool is None else {
            "size": legacy_pool.size, "in_use": legacy_pool.in_use,
            "units": [{"index": u.get("index"), "state": u.get("state"),
                       "sessionId": u.get("session_id")} for u in legacy_pool.units],
        },
        "usage": local.usage if local else None,
        "alerts": alerts,
        "summary": summary,
        "instances": instances,
    }
```

（`_container_block` 是把现有 `container` dict 字面量提成函数，两分支共用。Task 13 接线时把 `"pending_grants": 0` 改为 `allocator.pending_count()` 并删掉本段上方那行注释。）

- [ ] **Step 3: 新增聚合测试**

```python
# console/backend/tests/integration/test_instances.py 追加
def test_instances_aggregates_registry_rows(client, db_session, monkeypatch):
    from app.models.param_instance import ParamInstance
    from app.services import instance_monitor
    from app.services.instance_registry import RuntimeState
    from app.services.pool import PoolState

    db_session.add(ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=False))
    db_session.add(ParamInstance(instance_id="pipe-b", base_url="http://b:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=True))
    db_session.commit()
    state_a = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry._states["pipe-a"] = state_a
    instance_monitor.registry.observe_success("pipe-a",
        PoolState(reachable=True, size=4, in_use=2, units=()), 12)
    instance_monitor.registry._states["pipe-b"] = RuntimeState(instance_id="pipe-b", base_url="http://b:8765")
    instance_monitor.registry.set_drain("pipe-b", True)

    data = client.get("/api/v1/instances", headers=_auth(client)).json()["data"]
    assert data["summary"]["instances_total"] == 2
    assert data["summary"]["draining"] == 1
    ids = {row["instance_id"] for row in data["instances"]}
    assert ids == {"pipe-a", "pipe-b"}
    row_a = next(r for r in data["instances"] if r["instance_id"] == "pipe-a")
    assert row_a["status"] == "online" and row_a["free"] == 2
    instance_monitor.reset_for_tests()
```

- [ ] **Step 4: 运行新旧一起验证**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_instances.py -v`
Expected: 全部 PASS（两个旧用例的断言一行未改 = 向后兼容，spec §15 P1.3 验收）

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/services/instances_service.py console/backend/tests/integration/test_instances.py
git commit -m "feat(console): multi-instance aggregation, legacy fields intact (P1.3)"
```

## Task 10: 管理路由（drain/undrain/probe/detail/metrics）+ 审计

**Files:**
- Modify: `console/backend/app/routers/instances.py`
- Create: `console/backend/app/schemas/instance.py`
- Test: `console/backend/tests/integration/test_instances_admin_api.py`

**Interfaces:**
- Consumes: `InstanceRepository.set_drain`（Task 3）、`instance_registry.set_drain`（Task 7）、`instance_monitor.probe_all/invalidate/snapshot`（Task 8）、`InstanceMetricRepository.window`（Task 3）、`AuditRepository.record`（既有）、`require_operator`（`app/core/security.py`）
- Produces（spec §11 表，均 `ok()` 包裹）：
  - `POST /api/v1/instances/{instance_id}/drain` → `{instance_id, drain_requested: true}`，审计 `action="instance.drain", profile=instance_id, fields=["drain_requested"]`
  - `POST /api/v1/instances/{instance_id}/undrain` → `{instance_id, drain_requested: false}`，审计 `action="instance.undrain", profile=instance_id, fields=["drain_requested"]`
  - `POST /api/v1/instances/{instance_id}/probe` → 强制一轮巡检后返回该实例行，审计 `instance.probe`
  - `GET /api/v1/instances/{instance_id}` → 详情（units、最近 20 次探测 `probe_history`、计数器）
  - `GET /api/v1/instances/{instance_id}/metrics?window=1h` → 趋势点列表；`window ∈ {1h,6h,24h,7d}`，非法值 400（`ApiError("invalid_request", ...)`）
  - 未知 instance_id 一律 404（`ApiError("not_found", ...)`）

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/integration/test_instances_admin_api.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.models.param_instance import ParamInstance
from app.repositories.audit_repository import AuditRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.user_repository import UserRepository
from app.services import instance_monitor
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
    UserRepository(db_session).create("op", hash_password("correct-horse"), "operator")
    UserRepository(db_session).create("ad", hash_password("correct-horse"), "admin")
    db_session.add(ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=False))
    db_session.commit()
    instance_monitor.reset_for_tests()
    instance_monitor.refresh_specs(db_session)
    yield TestClient(app)
    instance_monitor.reset_for_tests()


def _auth(client, user="op"):
    tokens = client.post("/api/v1/auth/login",
                         json={"username": user, "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_drain_persists_flags_and_audits(client, db_session):
    response = client.post("/api/v1/instances/pipe-a/drain", headers=_auth(client))
    assert response.status_code == 200
    assert response.json()["data"]["drain_requested"] is True
    assert InstanceRepository(db_session).get_by_instance_id("pipe-a").drain_requested is True
    assert instance_monitor.registry.get("pipe-a").status == "draining"
    rows, _ = AuditRepository(db_session).list(action="instance.drain", profile="pipe-a")
    assert len(rows) == 1 and rows[0].actor == "op" and rows[0].fields == ["drain_requested"]


def test_undrain_restores_allocatability(client):
    client.post("/api/v1/instances/pipe-a/drain", headers=_auth(client))
    client.post("/api/v1/instances/pipe-a/undrain", headers=_auth(client))
    # 从未探测过 → 回 unknown，等首轮巡检（spec §6.2）
    assert instance_monitor.registry.get("pipe-a").status == "unknown"


def test_unknown_instance_is_404(client):
    assert client.post("/api/v1/instances/nope/drain", headers=_auth(client)).status_code == 404


def test_bad_window_is_400(client):
    body = client.get("/api/v1/instances/pipe-a/metrics?window=30m", headers=_auth(client)).json()
    assert body["code"] != 200


def test_detail_route_returns_probe_history(client, db_session):
    from app.services.pool import PoolState
    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=2, units=()), 8)
    data = client.get("/api/v1/instances/pipe-a", headers=_auth(client)).json()["data"]
    assert data["instance_id"] == "pipe-a" and data["probe_history"][-1] == 8
```

- [ ] **Step 2: 运行确认失败** → 新路由 404/405

- [ ] **Step 3: 实现 schemas + 路由**

```python
# console/backend/app/schemas/instance.py
from __future__ import annotations

from app.schemas.common import iso_utc

WINDOWS = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}


def metric_point(row) -> dict:
    return {
        "observedAt": iso_utc(row.observed_at),
        "observedBy": row.observed_by,
        "kind": row.kind,
        "status": row.status,
        "size": row.size, "inUse": row.in_use, "free": row.free, "stuck": row.stuck,
        "probeMs": row.probe_ms,
        "allocOk": row.alloc_ok, "allocFailNoInstance": row.alloc_fail_no_instance,
        "allocFailInstance503": row.alloc_fail_instance_503,
        "evictCount": row.evict_count, "recoverCount": row.recover_count,
    }
```

路由追加到 `app/routers/instances.py`（drain 先写 DB 再同步内存态，两边缺一不可，spec §6.2 draining 落库）：

```python
from datetime import UTC, datetime, timedelta

from app.core.errors import ApiError
from app.core.security import require_operator
from app.repositories.audit_repository import AuditRepository
from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository
from app.schemas.common import iso_utc
from app.schemas.instance import WINDOWS, metric_point
from app.services import instance_monitor


def _registry_row(db, instance_id):
    row = InstanceRepository(db).get_by_instance_id(instance_id)
    if row is None:
        raise ApiError("not_found", f"instance {instance_id} is not registered", 404)
    return row


def _request_id(request: Request) -> str:
    # 与 routers/profiles.py:20 同一条路径：RequestIdMiddleware 已经把
    # `x-request-id` 或新生成的 hex 写进 request.state（middleware/request_id.py:11），
    # 读头会拿到空串，审计行就断了关联。
    return getattr(request.state, "request_id", "")


def _audit(db, user, action, instance_id, fields, request_id: str = "") -> None:
    AuditRepository(db).record(actor=user.username, role=user.role, action=action,
                               profile=instance_id, fields=list(fields),
                               request_id=request_id)


@router.post("/instances/{instance_id}/drain")
def drain(instance_id: str, db: DbSession, request: Request,
          user: CurrentUser = Depends(require_operator)):
    row = _registry_row(db, instance_id)
    InstanceRepository(db).set_drain(instance_id, drain=True, updated_by=user.username)
    instance_monitor.registry.set_drain(instance_id, True)
    instance_monitor.invalidate()
    _audit(db, user, "instance.drain", instance_id, ["drain_requested"], _request_id(request))
    return ok({"instance_id": instance_id, "drain_requested": True})


@router.post("/instances/{instance_id}/undrain")
def undrain(instance_id: str, db: DbSession, request: Request,
            user: CurrentUser = Depends(require_operator)):
    _registry_row(db, instance_id)
    InstanceRepository(db).set_drain(instance_id, drain=False, updated_by=user.username)
    instance_monitor.registry.set_drain(instance_id, False)
    instance_monitor.invalidate()
    _audit(db, user, "instance.undrain", instance_id, ["drain_requested"], _request_id(request))
    return ok({"instance_id": instance_id, "drain_requested": False})


@router.post("/instances/{instance_id}/probe")
def probe(instance_id: str, db: DbSession, request: Request,
          user: CurrentUser = Depends(require_operator)):
    _registry_row(db, instance_id)
    instance_monitor.probe_all(db)  # 绕过 2s 缓存：探测本身是实时的（spec §9）
    instance_monitor.invalidate()
    _audit(db, user, "instance.probe", instance_id, [], _request_id(request))
    state = instance_monitor.registry.get(instance_id)
    return ok({"instance_id": instance_id, "status": state.status if state else "unknown",
               "probe_ms": state.probe_ms if state else None})


@router.get("/instances/{instance_id}")
def detail(instance_id: str, db: DbSession, user: CurrentUser = Depends(require_user)):
    _registry_row(db, instance_id)
    state = instance_monitor.registry.get(instance_id)
    return ok({
        "instance_id": instance_id,
        "status": state.status if state else "unknown",
        "units": [{"index": u.get("index"), "state": u.get("state"),
                   "sessionId": u.get("session_id")} for u in (state.pool.units if state and state.pool else ())],
        "probeHistory": list(state.probe_history) if state else [],
        "p50ProbeMs": state.p50_probe_ms if state else None,
        "p95ProbeMs": state.p95_probe_ms if state else None,
        "lastError": state.last_error if state else "",
        "usage": state.usage if state else None,
    })


@router.get("/instances/{instance_id}/metrics")
def metrics(instance_id: str, window: str = "1h", db: DbSession = None,
            user: CurrentUser = Depends(require_operator)):
    if window not in WINDOWS:
        raise ApiError("invalid_request", f"window must be one of {sorted(WINDOWS)}", 400)
    _registry_row(db, instance_id)
    since = datetime.now(UTC) - timedelta(seconds=WINDOWS[window])
    rows = InstanceMetricRepository(db).window(instance_id, since=since)
    return ok({"instance_id": instance_id, "window": window,
               "points": [metric_point(row) for row in rows]})
```

（注意 `metrics` 的 `db` 参数改用既有 `DbSession` 依赖注入写法，与其他路由一致；测试中 `client.post` 后的审计验证已在 Step 1。）

- [ ] **Step 4: 运行确认通过 + 角色边界**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_instances_admin_api.py tests/integration/test_instances.py -v`
Expected: PASS。补一条角色边界断言：operator 可调 drain（`require_operator`），若未来收紧迫 admin 只改依赖。

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/routers/instances.py console/backend/app/schemas/instance.py console/backend/tests/integration/test_instances_admin_api.py
git commit -m "feat(console): instance drain/undrain/probe/detail/metrics routes with audit (P1.3)"
```

## Task 11: /status 暴露 seed 与多活一致性校验

**Files:**
- Modify: `console/backend/app/services/status_service.py`、对应测试
- Test: `console/backend/tests/integration/test_instances.py`（追加，已有 status 用例模式）

**Interfaces:**
- Consumes: `allocator` 设置（Task 1）
- Produces: `/api/v1/status` 新增 `allocatorMode: "off"|"local"`、`instancesRegistered: int`、`seedConfigured: bool`、`consoleId: str`、`secretsConsistent: bool | null`（本期只能校验本机可见性：JWT/USAGE_HASH/ADMIN/INTERNAL 四个密钥是否都配置且非空；跨机一致性靠运维手工，spec §12 只要求暴露校验结果）

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/integration/test_instances.py
def test_status_exposes_allocator_state(client, monkeypatch):
    from app.config import allocator as allocator_settings

    monkeypatch.setattr(allocator_settings, "mode", "local")
    data = client.get("/api/v1/status", headers=_auth(client)).json()["data"]
    assert data["allocatorMode"] == "local"
    assert data["instancesRegistered"] == 0
    assert data["seedConfigured"] is False
    assert isinstance(data["consoleId"], str) and data["consoleId"]
```

- [ ] **Step 2: 实现（在 status_service.snapshot 返回 dict 内追加 5 个键）**

```python
    from app.config import allocator as allocator_settings

    "allocatorMode": allocator_settings.mode,
    "instancesRegistered": len(InstanceRepository(session).list_all()),
    "seedConfigured": bool(allocator_settings.seed_path.strip()),
    "consoleId": allocator_settings.resolved_console_id,
    "secretsConsistent": all(
        (getattr(auth_settings, "jwt_secret_key", ""),
         os.environ.get("USAGE_HASH_SECRET", ""),
         os.environ.get("S2S_ADMIN_TOKEN", ""),
         os.environ.get("S2S_INTERNAL_TOKEN", ""))
    ),
```

- [ ] **Step 3: 运行** `.\.venv\Scripts\python.exe -m pytest tests/integration/test_instances.py -v` → PASS

- [ ] **Step 4: 提交**

```bash
git add console/backend/app/services/status_service.py console/backend/tests/integration/test_instances.py
git commit -m "feat(console): status reports allocator mode and seed consistency (P1.3)"
```

---

# Phase P1.4：本地分配 + 双模式分支 + 503 换台重试

验收（spec §15）：`lb_url` 有值时 `lb_service` 调用次数与入参逐字不变（mock 断言）；注册表空时行为回到现状；注入 503 时重试一次并成功；grant 过期回收；`begin_once` 去重生效。

## Task 12: AllocatorStore Protocol + InMemory 实现

**Files:**
- Create: `console/backend/app/services/allocator_store.py`
- Test: `console/backend/tests/unit/test_allocator_store.py`

**Interfaces:**
- Consumes: `instance_monitor.registry`（Task 7/8，用于 `list_instances`/`snapshot_runtime`）
- Produces（签名冻结自 spec §13，不得增减）：

```python
class AllocatorStore(Protocol):
    def list_instances(self) -> list[InstanceSpec]: ...
    def snapshot_runtime(self) -> dict[str, RuntimeState]: ...
    def upsert_runtime(self, state: RuntimeState) -> None: ...
    def reserve(self, instance_id: str, session_id: str, ttl_s: int) -> bool: ...
    def release(self, session_id: str) -> None: ...
    def expire_pending(self) -> list[str]: ...
    def begin_once(self, dedupe_key: str, window_s: int) -> str | None: ...
    def remember_grant(self, dedupe_key: str, grant: dict) -> None: ...
    def grant_for(self, dedupe_key: str) -> dict | None: ...
    def enqueue(self, ticket_id: str, meta: dict) -> int: ...
    def peek_queue(self) -> list[QueueTicket]: ...
    def pop_queue(self) -> "QueueTicket | None": ...
    def bump(self, counter: str, delta: int = 1) -> int: ...
    def pending_count(self, instance_id: str) -> int: ...
    def drain_counters(self) -> dict[str, int]: ...
```

（在 spec §13 冻结签名之外共补充 4 条，均为 Phase 1 自身实现需要、Phase 2 的 Postgres 版同样适用：`remember_grant`/`grant_for`（§8.5 要求“命中时返回同一个 grant”）、`pending_count`（§6.2 的 `pending_local` 需在选台时扣减）、`drain_counters`（§10 的窗口增量取数）。实现与测试均以本块为准；Phase 2 只需实现这张更大的接口表，业务代码仍零改动。）

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_allocator_store.py
from __future__ import annotations

import time

import pytest

from app.services import instance_monitor
from app.services.allocator_store import InMemoryAllocatorStore
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


@pytest.fixture
def store(monkeypatch):
    instance_monitor.reset_for_tests()
    state = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry._states["pipe-a"] = state
    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=2, units=()), 5)
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    return InMemoryAllocatorStore()


def test_reserve_is_capped_by_effective_free(store):
    assert store.reserve("pipe-a", "s1", 60) is True
    assert store.reserve("pipe-a", "s2", 60) is True
    # size=2，两个 pending 已占满，第三个拒绝（乐观修正，spec §6.2）
    assert store.reserve("pipe-a", "s3", 60) is False
    assert store.pending_count("pipe-a") == 2


def test_release_frees_the_slot(store):
    store.reserve("pipe-a", "s1", 60)
    store.release("s1")
    assert store.pending_count("pipe-a") == 0


def test_expire_pending_uses_monotonic_not_wallclock(store, monkeypatch):
    store.reserve("pipe-a", "s1", 60)
    monkeypatch.setattr(time, "monotonic", lambda: 1061.0)  # +61s
    assert store.expire_pending() == ["s1"]
    assert store.pending_count("pipe-a") == 0


def test_begin_once_dedupes_within_the_window(store, monkeypatch):
    assert store.begin_once("req-1", 10) is None
    assert store.begin_once("req-1", 10) == "deduped"
    monkeypatch.setattr(time, "monotonic", lambda: 1011.0)  # 窗口外
    assert store.begin_once("req-1", 10) is None


def test_bump_accumulates_and_drain_resets(store):
    store.bump("alloc_ok:pipe-a")
    store.bump("alloc_ok:pipe-a")
    store.bump("alloc_fail_no_instance")
    assert store.drain_counters() == {"alloc_ok:pipe-a": 2, "alloc_fail_no_instance": 1}
    assert store.drain_counters() == {}


def test_queue_methods_exist_but_stay_unused_in_p1(store):
    # spec §3：本地队列本期关闭，契约保留即可；不抛异常 = Protocol 完整。
    assert store.enqueue("t1", {}) == 1
    assert store.peek_queue()[0].ticket_id == "t1"
    assert store.pop_queue().ticket_id == "t1"
    assert store.pop_queue() is None
```

- [ ] **Step 2: 运行确认失败** → FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
# console/backend/app/services/allocator_store.py
"""AllocatorStore：Phase 2 的替换点（spec §13，签名冻结）。

本期唯一实现 InMemoryAllocatorStore：单把 threading.Lock，与 console 单
worker 约束一致（spec §16）。时间一律 time.monotonic，避免多实例机器间
时钟偏差抖动租约（spec §8.3）。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.services import instance_monitor
from app.services.instance_registry import RuntimeState

# 注册表一律晚绑定（`instance_monitor.registry`）：`reset_for_tests()` 会重新
# 绑定那个对象，`from ... import registry` 的早绑定会让测试看见旧注册表。


class AllocatorStore(Protocol):
    def list_instances(self) -> list["InstanceSpec"]: ...
    def snapshot_runtime(self) -> dict[str, RuntimeState]: ...
    def upsert_runtime(self, state: RuntimeState) -> None: ...
    def reserve(self, instance_id: str, session_id: str, ttl_s: int) -> bool: ...
    def release(self, session_id: str) -> None: ...
    def expire_pending(self) -> list[str]: ...
    def pending_count(self, instance_id: str) -> int: ...
    def begin_once(self, dedupe_key: str, window_s: int) -> str | None: ...
    def remember_grant(self, dedupe_key: str, grant: dict) -> None: ...
    def grant_for(self, dedupe_key: str) -> dict | None: ...
    def enqueue(self, ticket_id: str, meta: dict) -> int: ...
    def peek_queue(self) -> list["QueueTicket"]: ...
    def pop_queue(self) -> "QueueTicket | None": ...
    def bump(self, counter: str, delta: int = 1) -> int: ...
    def drain_counters(self) -> dict[str, int]: ...


@dataclass(frozen=True)
class InstanceSpec:
    instance_id: str
    base_url: str
    weight: int
    enabled: bool
    effective_free: int
    capacity: int
    status: str


@dataclass
class QueueTicket:
    ticket_id: str
    meta: dict = field(default_factory=dict)


class InMemoryAllocatorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # session_id -> (instance_id, 单调过期时刻)
        self._pending: dict[str, tuple[str, float]] = {}
        # dedupe_key -> 首次看到的单调时刻（spec §8.5：缺省 cookie+10s 时间桶）
        self._begun: dict[str, float] = {}
        self._grants: dict[str, dict] = {}
        self._queue: list[QueueTicket] = []
        self._counters: dict[str, int] = {}

    def list_instances(self) -> list[InstanceSpec]:
        out = []
        for state in instance_monitor.registry.snapshot().values():
            capacity = state.pool.size if state.pool else 0
            out.append(InstanceSpec(
                instance_id=state.instance_id, base_url=state.base_url, weight=state.weight,
                enabled=state.enabled, effective_free=state.effective_free,
                capacity=capacity, status=state.status,
            ))
        return out

    def snapshot_runtime(self) -> dict[str, RuntimeState]:
        return instance_monitor.registry.snapshot()

    def upsert_runtime(self, state: RuntimeState) -> None:
        instance_monitor.registry._states[state.instance_id] = state

    def pending_count(self, instance_id: str) -> int:
        with self._lock:
            return sum(1 for iid, _ in self._pending.values() if iid == instance_id)

    def reserve(self, instance_id: str, session_id: str, ttl_s: int) -> bool:
        state = instance_monitor.registry.get(instance_id)
        if state is None:
            return False
        with self._lock:
            pending = sum(1 for iid, _ in self._pending.values() if iid == instance_id)
            # 占用 = 实例报的 in_use + 本机未反映的 pending；effective_free 已扣
            # stuck，这里只剩 pending 需要再扣（spec §6.2）。
            if state.pool is None or pending >= max(0, state.pool.size - state.pool.in_use - state.pool.stuck):
                return False
            self._pending[session_id] = (instance_id, time.monotonic() + ttl_s)
            return True

    def release(self, session_id: str) -> None:
        with self._lock:
            self._pending.pop(session_id, None)

    def expire_pending(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            gone = [sid for sid, (_, deadline) in self._pending.items() if now >= deadline]
            for sid in gone:
                del self._pending[sid]
            return gone

    def begin_once(self, dedupe_key: str, window_s: int) -> str | None:
        now = time.monotonic()
        with self._lock:
            first = self._begun.get(dedupe_key)
            if first is None:
                self._begun[dedupe_key] = now
                return None
            if now - first <= window_s:
                return "deduped"
            self._begun[dedupe_key] = now
            return None

    def remember_grant(self, dedupe_key: str, grant: dict) -> None:
        with self._lock:
            self._grants[dedupe_key] = dict(grant)

    def grant_for(self, dedupe_key: str) -> dict | None:
        with self._lock:
            grant = self._grants.get(dedupe_key)
            return dict(grant) if grant else None

    def enqueue(self, ticket_id: str, meta: dict) -> int:
        with self._lock:
            self._queue.append(QueueTicket(ticket_id=ticket_id, meta=dict(meta)))
            return len(self._queue)

    def peek_queue(self) -> list[QueueTicket]:
        with self._lock:
            return list(self._queue)

    def pop_queue(self) -> QueueTicket | None:
        with self._lock:
            return self._queue.pop(0) if self._queue else None

    def bump(self, counter: str, delta: int = 1) -> int:
        with self._lock:
            self._counters[counter] = self._counters.get(counter, 0) + delta
            return self._counters[counter]

    def drain_counters(self) -> dict[str, int]:
        with self._lock:
            out = dict(self._counters)
            self._counters.clear()
            return out
```

- [ ] **Step 4: 运行确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/services/allocator_store.py console/backend/tests/unit/test_allocator_store.py
git commit -m "feat(console): AllocatorStore protocol and in-memory implementation (P1.4)"
```

## Task 13: allocator 选台、grant、503 换台、计数器接线

**Files:**
- Create: `console/backend/app/services/allocator.py`
- Modify: `console/backend/app/services/instance_monitor.py`（`sample_metrics` 接真实计数器）、`console/backend/app/services/calls_service.py`（新增反向 scheme helper）
- Test: `console/backend/tests/unit/test_allocator.py`、`console/backend/tests/unit/test_calls_service.py`（追加）

**Interfaces:**
- Consumes: `InMemoryAllocatorStore`（Task 12）、`instance_monitor.registry`、`allocator` 设置
- Produces:
  - `store: InMemoryAllocatorStore`（模块级单例）
  - `grant_connect_url(base_url: str) -> str`（http→ws、https→wss，与 `calls_service.handshake_url` 的映射表对称）
  - `allocate(session_id: str, *, store=None, claim=None) -> dict | None`（`async def`）：选台→`store.reserve`→可选 `claim` 仲裁→返回 `{"state": "granted", "session_id", "connect_url", "expires_in"}`；无可分配实例返回 `None`（调用方落 503 at_capacity）；`store` 缺省用模块单例，传独立实例即可在测试里模拟两台 console 各持内存 store（Task 18）
  - `_candidates(target, exclude) -> list[InstanceSpec]`：spec §8.2 的四步（过滤→`free/capacity` 降序主排序→同分 weight 加权随机）；`free = max(0, spec.effective_free - target.pending_count(id))`，即 §6.2 里的 `pending_local` 在选台时扣，`RuntimeState.effective_free` 本身不扣
  - `claim`：可选异步回调 `async (instance: InstanceSpec) -> str`（""=成功，"session_limit_reached"=503）：默认 `None` 时永成功（槽位由实例在连接时最终仲裁，spec §8.4）；503 时释放 pending、`bump("alloc_fail_instance_503:{id}")`、**排除已试实例再选一台重试一次**（spec §8.2/§8.4）
  - `_rng: random.Random`（模块级，测试里 `monkeypatch.setattr(allocator, "_rng", ...)` 注入确定性）；`drain_counters()` / `pending_count()` 转发；`expire_task()`（单调时钟回收，spec §8.3）

- [ ] **Step 1: 写 grant_connect_url 失败测试（追加到 test_calls_service.py，先断言反向 helper）**

```python
def test_grant_connect_url_flips_the_scheme_map():
    from app.services.allocator import grant_connect_url

    assert grant_connect_url("http://192.168.40.31:8765") == "ws://192.168.40.31:8765/v1/realtime"
    assert grant_connect_url("https://pipe.example.com/") == "wss://pipe.example.com/v1/realtime"
    # 与 handshake_url 对称：ws↔http、wss↔https（spec §8.3）
    from app.services.calls_service import handshake_url

    assert handshake_url(grant_connect_url("http://h:1")) == "http://h:1/v1/realtime/calls"
```

- [ ] **Step 2: 实现 grant_connect_url 与 allocator 主体**

```python
# console/backend/app/services/allocator.py
"""本地分配：选实例→签发 grant→兜底降级（spec §8）。

只依赖 AllocatorStore 与 instance_registry，不直接碰 ORM（spec §4 依赖方向）。
"""

from __future__ import annotations

import random
import time
from urllib.parse import urlsplit, urlunsplit

from loguru import logger

from app.config import allocator as settings
from app.services import instance_monitor
from app.services.allocator_store import InMemoryAllocatorStore, InstanceSpec

SESSION_PATH = "/v1/realtime"
store = InMemoryAllocatorStore()
_rng = random.Random()  # 测试里 monkeypatch allocator._rng = random.Random(42) 保证确定性


def grant_connect_url(base_url: str) -> str:
    """http→ws、https→wss（calls_service.handshake_url 的反向，复用其映射表思路）。"""
    parts = urlsplit(base_url.strip())
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme or "ws")
    path = parts.path.rstrip("/") or SESSION_PATH
    if path == "/":
        path = SESSION_PATH
    return urlunsplit((scheme, parts.netloc, path, parts.query, ""))


def _candidates(target: InMemoryAllocatorStore, exclude: set[str]) -> list[InstanceSpec]:
    # spec §8.2 四步：过滤 → free/capacity 降序主排序 → 同分按 weight 加权随机。
    # §6.2 的 pending_local 在这里扣（RuntimeState.effective_free 不包含它）。
    rows: list[tuple[InstanceSpec, float]] = []
    for spec in target.list_instances():
        if not (spec.enabled and spec.weight > 0 and spec.status in ("online", "degraded")):
            continue
        if spec.instance_id in exclude:
            continue
        free = max(0, spec.effective_free - target.pending_count(spec.instance_id))
        if free <= 0:
            continue
        rows.append((spec, free / spec.capacity if spec.capacity else float(free)))
    if not rows:
        return []
    best = max(ratio for _, ratio in rows)
    tied = [spec for spec, ratio in rows if ratio == best]
    if len(tied) == 1:
        return tied
    first = _rng.choices(tied, weights=[spec.weight for spec in tied], k=1)[0]
    return [first] + [spec for spec in tied if spec is not first]


async def allocate(session_id: str, *, store: InMemoryAllocatorStore | None = None, claim=None) -> dict | None:
    target = store if store is not None else globals()["store"]
    tried: set[str] = set()
    for _attempt in range(2):  # 首次 + 换台重试一次（spec §8.4）
        ranked = _candidates(target, tried)
        if not ranked:
            # 首轮就没候选 = 真的无可用实例；换台后被拒的情况已由 503 计数说明原因。
            if not tried:
                target.bump("alloc_fail_no_instance")
            return None
        spec = ranked[0]
        if not target.reserve(spec.instance_id, session_id, settings.grant_ttl_s):
            tried.add(spec.instance_id)
            continue
        refusal = await claim(spec) if claim is not None else ""
        if refusal == "session_limit_reached":
            # 实例 503：释放本机占位、换一台重试一次（spec §8.4）。
            target.release(session_id)
            target.bump(f"alloc_fail_instance_503:{spec.instance_id}")
            tried.add(spec.instance_id)
            continue
        target.bump(f"alloc_ok:{spec.instance_id}")
        return {
            "state": "granted",
            "session_id": session_id,
            "connect_url": grant_connect_url(spec.base_url),
            "expires_in": settings.grant_ttl_s,
        }
    # 走到这里：连续两台 `reserve` 都被乐观修正拦下 → 本机视图无余量。
    target.bump("alloc_fail_no_instance")
    return None


def drain_counters() -> dict[str, int]:
    return store.drain_counters()


def pending_count() -> int:
    return len(store._pending)


async def expire_task() -> None:
    """单调时钟回收过期 grant（spec §8.3）；随 lifespan 启停。"""
    while True:
        await asyncio.sleep(max(1, settings.grant_ttl_s // 4))
        for session_id in store.expire_pending():
            logger.debug("expired pending grant {}", session_id)
```

（顶部 `import asyncio` 与 `time` 按实际使用保留：`asyncio` 用于 `expire_task`；`time` 若本模块无直接调用则删，否则 ruff F401。）

`instance_monitor` 的计数器接线已在 Task 8 就绪：`run_forever` 里 `from app.services import allocator as allocator_service` 是函数内晚 import，P1.2 阶段因默认 `mode=off` 不启巡检而不会 ImportError；本任务交付 allocator 后那行自动生效。`allocator_store`/`allocator` 反向 import `instance_monitor` 模块（不是 `registry` 名字），因此无 import 环。本步只需确认两处映射：

```python
# instance_monitor.py 已有：sample_metrics(session, counters) 内的 _counters_for 映射
#   deltas["alloc_fail_no_instance"]      → 每行 sample 的 alloc_fail_no_instance
#   deltas[f"alloc_ok:{instance_id}"]    → 该实例的 alloc_ok
#   deltas[f"alloc_fail_instance_503:{id}"] → 该实例的 alloc_fail_instance_503
```

`Task 9` 的 `summary.pending_grants` 接 `allocator_service.pending_count()`（把那一行的 `"pending_grants": 0` 与上方两行注释一起替换为：

```python
        # P1.4 已交付：本机已签发未领取的 grant 数（spec §10）。
        "pending_grants": allocator_service.pending_count(),
```

并在 `instances_service.py` 顶部 `from app.services import allocator as allocator_service`。）

- [ ] **Step 3: 写 allocator 测试**

`console/backend/pyproject.toml` 已配 `asyncio_mode = "auto"`，所以 `async def test_*` 直接可跑（保留显式 marker 也无害）。

```python
# console/backend/tests/unit/test_allocator.py
from __future__ import annotations

import pytest

from app.config import allocator as allocator_settings
from app.services import allocator, instance_monitor
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


class _StubRng:
    """同分加权随机的可观测替身（spec §8.2 第 3 步）。真实 `random.Random` 即使
    固定 seed 也无法在写计划时预测选中哪一个，所以这里按 id 指定胜者并记录入参。"""

    def __init__(self, winner_id: str) -> None:
        self.winner_id = winner_id
        self.calls: list[tuple[list[str], list[int], int]] = []

    def choices(self, population, *, weights, k):
        self.calls.append(([spec.instance_id for spec in population], list(weights), k))
        return [spec for spec in population if spec.instance_id == self.winner_id]


@pytest.fixture
def two_online(monkeypatch):
    """pipe-a 空载 4/0（free ratio 1.0）、pipe-b 5/3（2/5 = 0.4）。
    取 0.4 是为了避开 pipe-a 随 pending 递减的 ratio 列 1.0/0.75/0.5/0.25，
    让主排序直接分出胜负（同分分支由下面的专用用例覆盖）。"""
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._counters.clear()
    for iid, size, in_use in (("pipe-a", 4, 0), ("pipe-b", 5, 3)):
        instance_monitor.registry._states[iid] = RuntimeState(instance_id=iid, base_url=f"http://{iid}:8765")
        instance_monitor.registry.observe_success(
            iid, PoolState(reachable=True, size=size, in_use=in_use, units=()), 5)
    monkeypatch.setattr(allocator_settings, "grant_ttl_s", 60)
    return instance_monitor.registry


async def test_grant_shape_matches_the_demo_contract(two_online):
    grant = await allocator.allocate("s-1")
    assert grant["state"] == "granted" and grant["session_id"] == "s-1"
    assert grant["connect_url"] == "ws://pipe-a:8765/v1/realtime"  # free ratio 1.0 > 0.5
    assert grant["expires_in"] == 60


async def test_least_loaded_switches_when_the_richer_instance_fills_up(two_online):
    for i in range(3):  # pipe-a 的 free ratio 逐次 1.0 → 0.75 → 0.5，均高于 pipe-b 的 0.4
        assert (await allocator.allocate(f"s-{i}"))["connect_url"].startswith("ws://pipe-a")
    # 第 4 次 pipe-a 降到 0.25 < 0.4 → 自然切到次空闲的一台（spec §6.2/§8.2）
    assert (await allocator.allocate("s-x"))["connect_url"].startswith("ws://pipe-b")


async def test_tied_ratio_uses_weighted_random_by_weight(two_online, monkeypatch):
    two_online.get("pipe-a").weight = 3
    two_online.observe_success("pipe-b", PoolState(reachable=True, size=5, in_use=0, units=()), 5)
    # 两台都空载 → free ratio 同为 1.0 → 走同分分支，由注入的 RNG 决定
    stub = _StubRng("pipe-b")
    monkeypatch.setattr(allocator, "_rng", stub)
    assert (await allocator.allocate("s-1"))["connect_url"].startswith("ws://pipe-b")
    assert stub.calls == [(["pipe-a", "pipe-b"], [3, 1], 1)]  # weight 透传，k=1


async def test_503_from_the_first_instance_retries_the_second_once(two_online):
    calls: list[str] = []

    async def claim(spec):
        calls.append(spec.instance_id)
        return "session_limit_reached" if len(calls) == 1 else ""

    grant = await allocator.allocate("s-9", claim=claim)
    assert grant["connect_url"].startswith("ws://pipe-b")
    assert calls == ["pipe-a", "pipe-b"]  # 首台被拒 → 只换台重试一次（spec §8.4）
    assert allocator.drain_counters() == {"alloc_fail_instance_503:pipe-a": 1, "alloc_ok:pipe-b": 1}


async def test_expired_pending_frees_the_slot(two_online):
    # 不 monkeypatch time.monotonic：异步测试里冻结单调会干扰事件循环。直接植入已过期 pending。
    for i in range(4):
        allocator.store._pending[f"old-{i}"] = ("pipe-a", -1.0)
    # pipe-a 的 4 个槽位被过期 pending 扣光 → 只能选 pipe-b
    assert (await allocator.allocate("s-1"))["connect_url"].startswith("ws://pipe-b")
    assert allocator.store.expire_pending() == [f"old-{i}" for i in range(4)]
    # 回收后 pipe-a 回到 free ratio 1.0，又成了首选（spec §8.3）
    assert (await allocator.allocate("s-2"))["connect_url"].startswith("ws://pipe-a")


async def test_empty_registry_returns_none_and_counts_failure(two_online):
    instance_monitor.reset_for_tests()
    assert await allocator.allocate("s-1") is None
    assert allocator.drain_counters() == {"alloc_fail_no_instance": 1}


async def test_draining_instance_is_never_selected(two_online):
    two_online.set_drain("pipe-a", True)
    two_online.set_drain("pipe-b", True)
    assert await allocator.allocate("s-1") is None
    assert allocator.drain_counters() == {"alloc_fail_no_instance": 1}
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_allocator.py tests/unit/test_allocator_store.py tests/unit/test_calls_service.py tests/unit/test_instance_monitor.py -v`
Expected：新文件 7 个用例 PASS；`test_allocator_store.py`/`test_calls_service.py` 既有用例不回归（`test_calls_service.py` 多出 Step 1 的 1 个新用例）。若 `test_tied_ratio_uses_weighted_random_by_weight` 报 `stub.calls == []`，说明 `_candidates` 没走同分分支——检查 pipe-b 是否真的被重新观测为 `in_use=0`。

- [ ] **Step 5: 提交**

```bash
git add console/backend/app/services/allocator.py console/backend/app/services/allocator_store.py console/backend/app/services/calls_service.py console/backend/app/services/instance_monitor.py console/backend/tests/unit
git commit -m "feat(console): local allocator with weighted least-loaded pick and 503 retry (P1.4)"
```

## Task 14: 演示面双模式分支（routers/demo/session.py 唯一分支点）

**Files:**
- Modify: `console/backend/app/routers/demo/session.py`
- Test: `console/backend/tests/demo/test_session_api.py`（追加）

**Interfaces:**
- Consumes: `allocator.allocate/store`（Task 13）、`demo.lb_url`、`instance_monitor.registry`
- Produces: `POST /api/session` 三分支（spec §8.1）：
  1. `demo.lb_url` 非空 → `await lb_service.start(request)`，**一行不改**；
  2. `lb_url` 空 且 `allocator.mode == "local"` 且注册表存在“在线/降级”实例 → 本地分配；
  3. 其余 → 404 防探测（现状）。

  ⚠ 对 spec §8.1 行文字的一处修正性解读：“存在可分配实例”按“存在已注册且未被摘除的实例”理解，不是“存在有余量的实例”。否则 fleet 满载时会命中第三个分支的 404，与 §8.4 要求的 `503 at_capacity` 直接矛盾（前端 QueueOverlay 只有 at_capacity 分支、没有 404 分支）。
  本地分配分支：`dedupe_key = X-Request-Id 头 或 anon cookie + 10s 时间桶`（`identity_service.ANON_COOKIE = "s2s_anon"`）；`store.begin_once` 命中时 `store.grant_for` 返回**同一个已 finalize 的 payload**（不再二次 `metering_service.begin`，否则会重复预留一块，spec §8.5）；无可用实例→`JSONResponse({"state": "at_capacity"}, 503)`（前端已有分支，与 `lb_service.start` 的 503 分支同构，spec §8.4）；响应体直接复用 `lb_service.finalize()` 填充 `tier/limited/remainingSec/heartbeatSec`——它不转 LB，只贴字段与发 cookie，因此演示面契约逐字一致（`lb_service.py` 仍不被修改，只是多一个调用方）。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/demo/test_session_api.py
def test_local_mode_grants_without_touching_lb(dist, lb, monkeypatch):
    # 注册表非空 + mode=local + 无 lb_url → 本地分配，lb_service._http 零调用
    from app.config import allocator as allocator_settings
    from app.services import allocator, instance_monitor
    from app.services.instance_registry import RuntimeState
    from app.services.pool import PoolState

    monkeypatch.setattr(demo_settings, "load_balancer_url", "")
    monkeypatch.setattr(allocator_settings, "mode", "local")
    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=2, units=()), 5)
    with TestClient(create_app()) as client:
        body = client.post("/api/session", headers={"X-Request-Id": "r-1"}).json()
    assert body["state"] == "granted" and body["connect_url"] == "ws://a:8765/v1/realtime"
    assert body["tier"] == "anon" and "expires_in" in body  # finalize 补齐的字段（与 LB 模式同构）
    assert lb == []  # 一次转发都没发生：P1.4 验收证据
    instance_monitor.reset_for_tests()


def test_local_mode_dedupes_by_request_id(dist, monkeypatch):
    from app.config import allocator as allocator_settings
    from app.services import allocator, instance_monitor
    from app.services.instance_registry import RuntimeState
    from app.services.pool import PoolState

    monkeypatch.setattr(allocator_settings, "mode", "local")
    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=2, units=()), 5)
    with TestClient(create_app()) as client:
        first = client.post("/api/session", headers={"X-Request-Id": "same"}).json()
        second = client.post("/api/session", headers={"X-Request-Id": "same"}).json()
    assert first["session_id"] == second["session_id"]  # 同一个 grant，不重复占位
    instance_monitor.reset_for_tests()


def test_local_mode_at_capacity_is_503_when_registry_full(dist, monkeypatch):
    from app.config import allocator as allocator_settings
    from app.services import allocator, instance_monitor
    from app.services.instance_registry import RuntimeState
    from app.services.pool import PoolState

    monkeypatch.setattr(allocator_settings, "mode", "local")
    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=1, in_use=1, units=()), 5)
    with TestClient(create_app()) as client:
        response = client.post("/api/session")
    assert response.status_code == 503 and response.json() == {"state": "at_capacity"}
    instance_monitor.reset_for_tests()


def test_empty_registry_falls_back_to_the_old_404(dist, monkeypatch):
    from app.config import allocator as allocator_settings

    monkeypatch.setattr(allocator_settings, "mode", "local")
    # 注册表空：行为回到本期之前（spec §15 P1.4）
    with TestClient(create_app()) as client:
        assert client.post("/api/session").status_code == 404


def test_lb_mode_still_forwards_verbatim(dist, metered, lb):
    # 既有 fixture：lb 记录 (_http 调用序列)；此用例其实已被文件头部现有用例覆盖，
    # 这里显式把"mock 断言零变化"钉为 P1.4 验收条目（不改任何现有断言）。
    with TestClient(create_app()) as client:
        client.post("/api/session")
    assert lb[0][0] == "POST" and lb[0][1] == "http://lb.internal:9000/session"
```

- [ ] **Step 2: 实现分支（不动 lb_service）**

```python
# console/backend/app/routers/demo/session.py
import asyncio
import time
import uuid

from fastapi.responses import JSONResponse

from app.config import allocator as allocator_settings
from app.config import demo
from app.services import allocator, identity_service, instance_monitor, lb_service, metering_service

GRANT_DEDUPE_WINDOW_S = 10  # spec §8.5：cookie + 10s 时间桶


def _local_mode_on() -> bool:
    if allocator_settings.mode != "local":
        return False
    # 注册表里有“在线/降级”的机器就走本地分配，哪怕余量为 0：满编时的正确
    # 答复是 503 at_capacity（spec §8.4），404 只属于“根本没配注册表”的现状。
    return any(
        state.enabled and state.status in ("online", "degraded")
        for state in instance_monitor.registry.snapshot().values()
    )


def _dedupe_key(request: Request) -> str:
    rid = request.headers.get("X-Request-Id", "").strip()
    if rid:
        return f"h:{rid}"
    anon = request.cookies.get(identity_service.ANON_COOKIE, "")
    bucket = int(time.monotonic() // GRANT_DEDUPE_WINDOW_S)
    return f"c:{anon}:{bucket}"


@router.post("/session")
async def session(request: Request):
    """向 LB 申请会话：授权，或一张排队票。未配 LB 且未开本地分配时 404（防探测）。"""
    if demo.lb_url:
        return await lb_service.start(request)  # 现有转发逐字不变（spec §8.1）
    if not _local_mode_on():
        raise HTTPException(status_code=404, detail="Not found.")  # 空注册表回现状（spec §15 P1.4）

    reason = identity_service.oauth_login_required_reason(request)
    if reason:
        return lb_service.login_required(reason)
    tier, keys, set_cookie = identity_service.resolve_identity(request)
    tracked = lb_service.tracked_for(tier)
    if tracked:  # 预算已没了就别占实例槽位（与 lb_service.start 同序）
        left = await asyncio.to_thread(metering_service.remaining, keys, tier)
        if left is not None and left <= 0:
            return lb_service.spent(tier, set_cookie)

    key = _dedupe_key(request)
    if allocator.store.begin_once(key, GRANT_DEDUPE_WINDOW_S) == "deduped":
        hit = allocator.store.grant_for(key)
        if hit:
            response = JSONResponse(hit)  # 已 finalize 的同一个 payload，不重复占位/不重复预留
            if set_cookie:
                identity_service.set_anon_cookie(response, set_cookie)
            return response
    grant = await allocator.allocate(str(uuid.uuid4()))
    if grant is None:
        response = JSONResponse({"state": "at_capacity"}, status_code=503)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response
    data = dict(grant)
    response = await lb_service.finalize(data, keys, tier, tracked, set_cookie)
    allocator.store.remember_grant(key, data)  # 落盘的是 finalize 后的完整体
    return response
```

（顶部 `Request`/`HTTPException`/`router` 沿用该文件现有 import，一行不改；`lb_service.login_required/spent/tracked_for/finalize` 都是既有公开函数（`lb_service.py:69/81/40/115`），本任务不修改该文件——它只在 `lb_url` 为空的新分支里被调用。`demo.limiter_enabled=False` 时 `finalize` 走不到 `metering_service.begin`，与 spec §2“配额链路默认关闭”一致。）

- [ ] **Step 3: 全量 demo 回归（验收：lb_url 有值时现有 mock 断言全部逐字不变）**

Run: `.\.venv\Scripts\python.exe -m pytest tests/demo tests/integration/test_instances.py tests/unit/test_allocator.py -v`
Expected: PASS，且 `tests/demo/*` 现有用例未改一行即通过（git diff 佐证）

- [ ] **Step 4: 提交**

```bash
git add console/backend/app/routers/demo/session.py console/backend/tests/demo/test_session_api.py
git commit -m "feat(console): dual-mode session entry, local allocation behind lb_url check (P1.4)"
```

---

# Phase P1.5：前端多实例表格 + 汇总卡 + 趋势图 + i18n

验收（spec §15）：vitest 覆盖取数与状态映射；`npm run build` 通过；`observed_by` 不产生重复行。

技术选型约束：`console/frontend/package.json` 无图表库（ant-design-vue 4 不含 charts），而 spec §14 要求"沿用 turn_latency 页已有的取数与图表组件、不新造图形体系"：取数沿用 `api/client.ts` + `composables/usePolling.ts`，图形沿用仓内手写 SVG 路线（新增一个 ≤120 行的 `InstanceTrendChart.vue`，不引入依赖）。

## Task 15: 类型 + API 层 + 纯函数映射（可测层）

**Files:**
- Modify: `console/frontend/src/types/api.d.ts`、`console/frontend/src/api/instances.ts`
- Create: `console/frontend/src/utils/instances-view.ts`、`console/frontend/src/utils/instances-view.spec.ts`

**Interfaces:**
- Consumes: P1.3/P1.4 后的 `GET /api/v1/instances` 响应（`summary` + `instances[]`）、`GET /instances/{id}/metrics` 响应
- Produces：
  - `types/api.d.ts` 新增 `InstancesSummary`、`InstanceRow`、`InstanceMetricPoint`（字段名与后端 `instances_service._collect_registry`/`schemas.instance.metric_point` 逐字一致）；`InstanceSnapshot` 保留旧字段并追加 `summary: InstancesSummary`、`instances: InstanceRow[]`
  - `api/instances.ts`：`getInstances`（既有）、`getInstance(id)`、`getInstanceMetrics(id, window)`、`postInstanceAction(id, 'drain'|'undrain'|'probe')`
  - `utils/instances-view.ts` 纯函数：`statusColor(status: string): string`、`statusLabelKey(status: string): string`、`dedupeByLatestObserver(points: InstanceMetricPoint[]): InstanceMetricPoint[]`（同一 `observedAt±1s` 内按 `instance_id` 取最新一行，不累加，spec §10）、`capacityPercent(row: InstanceRow): number`

- [ ] **Step 1: 写失败 vitest（映射层，spec §17 前端测试策略）**

```typescript
// console/frontend/src/utils/instances-view.spec.ts
import { describe, expect, it } from 'vitest'
import { dedupeByLatestObserver, statusColor, statusLabelKey } from './instances-view'
import type { InstanceMetricPoint } from '@/types/api'

const point = (over: Partial<InstanceMetricPoint>): InstanceMetricPoint => ({
  observedAt: '2026-10-26T08:00:00Z', observedBy: 'console-1', kind: 'sample', status: 'online',
  size: 4, inUse: 1, free: 3, stuck: 0, probeMs: 10, allocOk: 0, allocFailNoInstance: 0,
  allocFailInstance503: 0, evictCount: 0, recoverCount: 0, ...over,
})

describe('instances-view', () => {
  it('maps every instance-level status to a color and an i18n key', () => {
    for (const status of ['unknown', 'online', 'degraded', 'offline', 'draining']) {
      expect(statusColor(status)).toMatch(/^(default|green|orange|red|blue)$/)
      expect(statusLabelKey(status)).toBe(`instances.status.${status}`)
    }
  })

  it('dedupes multi-console samples by latest observer instead of summing', () => {
    const rows = dedupeByLatestObserver([
      point({ observedBy: 'console-1', evictCount: 1 }),
      point({ observedBy: 'console-2', evictCount: 1 }),
    ])
    expect(rows).toHaveLength(1) // 同一实例同时刻两 console 只留一行，避免 ×N（spec §10）
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run（`console/frontend`）: `npm run test -- src/utils/instances-view.spec.ts`
Expected: FAIL（模块/类型不存在）

- [ ] **Step 3: 实现类型、API 函数与纯函数映射**

```typescript
// console/frontend/src/types/api.d.ts 追加（与后端 schemas/instance.metric_point 对齐）
export interface InstanceRow {
  instance_id: string
  base_url: string
  status: 'unknown' | 'online' | 'degraded' | 'offline' | 'draining'
  weight: number
  enabled: boolean
  drain_requested: boolean
  size: number | null
  in_use: number | null
  free: number | null
  stuck: number | null
  probe_ms: number | null
  p95_probe_ms: number | null
  units: PoolUnit[]
  last_error: string
  observed_by: string
  declared_mismatch: boolean
}

export interface InstancesSummary {
  instances_total: number
  online: number
  offline: number
  degraded: number
  draining: number
  slots_total: number
  slots_in_use: number
  slots_free: number
  pending_grants: number
}

export interface InstanceMetricPoint {
  observedAt: string
  observedBy: string
  kind: 'sample' | 'state_change'
  status: string
  size: number | null
  inUse: number | null
  free: number | null
  stuck: number | null
  probeMs: number | null
  allocOk: number
  allocFailNoInstance: number
  allocFailInstance503: number
  evictCount: number
  recoverCount: number
}
```

```typescript
// console/frontend/src/utils/instances-view.ts
import type { InstanceMetricPoint, InstanceRow } from '@/types/api'

const COLORS: Record<string, 'default' | 'green' | 'orange' | 'red' | 'blue'> = {
  unknown: 'default', online: 'green', degraded: 'orange', offline: 'red', draining: 'blue',
}

export const statusColor = (status: string) => COLORS[status] ?? 'default'
export const statusLabelKey = (status: string) => `instances.status.${status}`

/** 跨 console 取数规则：同一秒桶内只留 observedAt 最新的一行，不累加（spec §10）。 */
export function dedupeByLatestObserver(points: InstanceMetricPoint[]): InstanceMetricPoint[] {
  const byBucket = new Map<string, InstanceMetricPoint>()
  for (const point of points) {
    const bucket = point.observedAt.slice(0, 19) // 秒粒度：两台 console 同时刻的重复采样归同一桶
    const kept = byBucket.get(bucket)
    if (!kept || kept.observedAt < point.observedAt) byBucket.set(bucket, point)
  }
  return [...byBucket.values()].sort((a, b) => a.observedAt.localeCompare(b.observedAt))
}

export const capacityPercent = (row: InstanceRow): number =>
  row.size && row.size > 0 ? Math.round(((row.in_use ?? 0) / row.size) * 100) : 0
```

`api/instances.ts` 追加（`api` 客户端自动剥 envelope，沿用仓内现有函数风格）：

```typescript
export const getInstance = (id: string): Promise<Record<string, unknown>> =>
  api.get(`/instances/${id}`)
export const getInstanceMetrics = (id: string, window: '1h' | '6h' | '24h' | '7d') =>
  api.get<{ instance_id: string; window: string; points: InstanceMetricPoint[] }>(
    `/instances/${id}/metrics`, { params: { window } })
export const postInstanceAction = (id: string, action: 'drain' | 'undrain' | 'probe') =>
  api.post(`/instances/${id}/${action}`)
```

- [ ] **Step 4: 运行确认通过 + 提交**

Run: `npm run test -- src/utils/instances-view.spec.ts` → PASS

```bash
git add console/frontend/src/types/api.d.ts console/frontend/src/api/instances.ts console/frontend/src/utils/instances-view.ts console/frontend/src/utils/instances-view.spec.ts
git commit -m "feat(console-frontend): instance types, api layer, view mappers (P1.5)"
```

## Task 16: InstancesView 重写（汇总卡 + 多实例表格 + 行内操作 + 趋势图）

**Files:**
- Modify: `console/frontend/src/views/InstancesView.vue`、`console/frontend/src/components/InstanceCard.vue`（保留给单实例模式或删改）
- Create: `console/frontend/src/components/InstanceTrendChart.vue`
- Modify: `console/frontend/src/i18n/zh-CN.ts`（及英文词条源，按 `i18n/index.ts` 现有 locale 结构同步中英）

**Interfaces:**
- Consumes: Task 15 的 api 函数与映射；`ConfirmDialog`/`useConfirm`（既有）；`usePolling`（既有）
- Produces：页面满族 spec §14：顶部汇总卡（在线数、总/占用/空闲槽位、pending grants、摘除次数、告警）+ 表格（状态灯、size/in_use/free/stuck、weight、最近探测、p95、24h 分配成功率、drain/undrain/probe 行内操作）+ 单实例趋势图（容量/占用/探测耗时，window 选择 1h/6h/24h/7d）；drain/undrain 二次确认 + toast；`observed_by` 以筛选器呈现

- [ ] **Step 1: 重写 InstancesView 骨架**

关键实现约束（验收"observed_by 不产生重复行"在此层生效）：表格数据源直接用 `snapshot.instances`（后端已按 console 聚合，每实例一行），趋势图数据过 `dedupeByLatestObserver`；行内操作后 `invalidate` 当前轮询缓存并 toast；窗口切换重新取数。模板层用 `a-table` + `a-badge`（statusColor 映射 badge status）+ `a-progress`（capacityPercent）。

- [ ] **Step 2: InstanceTrendChart.vue（≤120 行手写 SVG，不新造图形体系）**

polyline 三条：size/free/probe 各一色；x 轴按 `observedAt` 等距；悬停无要求（面板只读趋势）。输入 props：`points: InstanceMetricPoint[]`。

- [ ] **Step 3: i18n 同步中英**

`zh-CN.ts` 新增：`instances.status.{unknown,online,degraded,offline,draining}`、`instances.summary.*`、`instances.action.{drain,undrain,probe}`、`instances.drain.confirm`、`instances.trend.window` 等 key；按 `i18n/index.ts` 的英文回退结构同步英文词条（spec §14）。

- [ ] **Step 4: 验证**

Run（`console/frontend`）: `npm run test` 然 `npm run build` 然 `npm run lint`
Expected: vitest 全绿；`vue-tsc --noEmit && vite build` 通过；eslint 0 warning。

- [ ] **Step 5: 提交**

```bash
git add console/frontend/src/views/InstancesView.vue console/frontend/src/components/InstanceTrendChart.vue console/frontend/src/i18n
git commit -m "feat(console-frontend): multi-instance table, summary cards, trend chart (P1.5)"
```

---

# Phase P1.6：多 console 验证 + hangup 鉴权前置项 + 文档

验收（spec §15）：两台 console 指向同一批实例：无重复会话损坏、超发只表现为一次 503 重试；`DELETE /v1/realtime/calls` 无 token 返 401，有 token 返 200；`docs/console-service.md` 增章。

## Task 17: 实例侧 `DELETE /v1/realtime/calls/{call_id}` 补 S2S_ADMIN_TOKEN（安全前置项）

**Files:**
- Modify: `src/speech_to_speech/api/openai_realtime/websocket_router.py:996-1014`
- Test: `tests/openai_realtime/test_webrtc_hangup_auth.py`（新建）

**Interfaces:**
- Consumes: 既有 `_admin_bearer(request)`、`_admin_error(...)`（websocket_router.py:517/529，`/admin/sessions/update` 同款 fail-closed 模式 :809-814）
- Produces: 鉴权后的 hangup：未配置 token → 503 `admin_disabled`；token 错/缺 → 401 `unauthorized`；合法 → 原逻辑（命中 200，未知 call 404）

- [ ] **Step 1: 写失败测试（无需 aiortc：端点本体只读 pool 里的 session 对象）**

```python
# tests/openai_realtime/test_webrtc_hangup_auth.py
"""P1.6 强制项：挂断端点的 fail-closed Bearer 校验（spec §9.2/§16）。"""
from __future__ import annotations

from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app


class _Transport:
    kind = "webrtc"

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _unit_with_call(call_id: str) -> SimpleNamespace:
    transport = _Transport()
    session = SimpleNamespace(session_id=call_id, released_at=None, transport=transport)
    return SimpleNamespace(index=0, session=session, transport=transport)


def _client(call_id="call-1"):
    return TestClient(create_app([_unit_with_call(call_id)], Event()))


def test_missing_token_env_is_fail_closed_503(monkeypatch):
    monkeypatch.delenv("S2S_ADMIN_TOKEN", raising=False)
    response = _client().delete("/v1/realtime/calls/call-1")
    assert response.status_code == 503


def test_wrong_token_is_401(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "expected")
    response = _client().delete("/v1/realtime/calls/call-1", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_valid_token_hangs_up_200(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "expected")
    response = _client().delete("/v1/realtime/calls/call-1", headers={"Authorization": "Bearer expected"})
    assert response.status_code == 200


def test_valid_token_unknown_call_404(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "expected")
    response = _client().delete("/v1/realtime/calls/nope", headers={"Authorization": "Bearer expected"})
    assert response.status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run（仓库根，用根 `.venv`）: `.\.venv\Scripts\python.exe -m pytest tests/openai_realtime/test_webrtc_hangup_auth.py -v`
Expected: 新用例 FAIL（现状无鉴权：缺 token 也返回 200/404）

- [ ] **Step 3: 实现（与 :809-814 逐字同构）**

```python
    @app.delete("/v1/realtime/calls/{call_id}")
    async def webrtc_hangup_endpoint(call_id: str, request: Request) -> Response:
        """Hang up a WebRTC call — the Location URL advertised by the POST above.

        P1.6: same fail-closed admin token check as /admin/sessions/update; the
        call id is guessable, so an unauthenticated hangup lets anyone drop
        someone else's call.
        """
        expected = os.environ.get("S2S_ADMIN_TOKEN", "").strip()
        if not expected:
            return _admin_error(503, "admin_disabled", "S2S_ADMIN_TOKEN is not configured on this service")
        if not hmac.compare_digest(_admin_bearer(request).encode(), expected.encode()):
            return _admin_error(401, "unauthorized", "a valid Bearer token is required")
        # 以下原循环体逐字保留
        ...
```

- [ ] **Step 4: 回归（现有 hangup 用例如在 test_webrtc.py 中，需同步加 token 头）**

Run: `.\.venv\Scripts\python.exe -m pytest tests/openai_realtime/test_webrtc_hangup_auth.py tests/openai_realtime/test_webrtc.py -v -k "hangup or calls"`（aiortc 缺失时 webrtc 模块自动 skip，属预期）
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/speech_to_speech/api/openai_realtime/websocket_router.py tests/openai_realtime/test_webrtc_hangup_auth.py
git commit -m "fix(api): require S2S_ADMIN_TOKEN on WebRTC hangup endpoint (P1.6)"
```

## Task 18: console 侧 hangup 代理（默认关）+ 多 console 并行分配验证

**Files:**
- Create: `console/backend/tests/integration/test_instances_hangup_api.py`、`console/backend/tests/unit/test_multi_console_overcommit.py`
- Modify: `console/backend/app/routers/instances.py`、`console/backend/app/services/instance_probe.py`、`console/backend/app/schemas/instance.py`、`console/backend/app/core/router_registry.py`

**Interfaces:**
- Consumes: Task 17 的鉴权端点（`DELETE {base_url}/v1/realtime/calls/{call_id}`，Bearer = `S2S_ADMIN_TOKEN`）；`app.config.allocator.webrtc_hangup_enabled`（env `INSTANCE_WEBRTC_HANGUP_ENABLED`，Task 1）；`require_admin`（`app/core/security.py:51`，非 admin → `ApiError("forbidden", …, 403)`）；Task 10 落在 `instances.py` 里的 `_registry_row` / `_audit` / `_request_id`
- Produces:
  - `instance_probe.hangup_call(base_url: str, call_id: str, token: str, timeout: float = 5.0) -> int`——同步（与 `probe_pool` 同构）；返回上游 HTTP 状态码，网络层无响应返回 `0`
  - `instances.hangup_router`（`APIRouter(prefix="/api/v1", tags=["instances"])`）：`POST /instances/{instance_id}/hangup`，body `HangupRequest{session_id: str}`，`require_admin`，审计 `instance.hangup`（spec §9.2/§11）
  - 条件注册点在 `router_registry.register_api_routers()`：`if allocator_settings.webrtc_hangup_enabled: app.include_router(instances.hangup_router)`。与 `main.py:102` 对 `demo_settings.auth_enabled` 的处理同构——开关**在 `create_app()` 内求值**，所以测试只要「先 monkeypatch 开关、再 `create_app()`」，不需要 `importlib.reload`，也不把开关状态藏进模块导入期。

- [ ] **Step 1: hangup 路由测试（默认关 = 路由不存在 404；开关开 = 代理带 Bearer）**

```python
# console/backend/tests/integration/test_instances_hangup_api.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import allocator as allocator_settings
from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.models.param_instance import ParamInstance
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository
from app.services import instance_monitor, instance_probe
from app.services.auth_service import hash_password


def _make_client(db_session, monkeypatch, tmp_path) -> TestClient:
    """Task 10 的 `client` fixture 去掉 fixture 包装：开关用例得在建 app 前改配置。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "missing.yaml"))
    users = UserRepository(db_session)
    users.create("ad", hash_password("correct-horse"), "admin")
    users.create("op", hash_password("correct-horse"), "operator")
    db_session.add(ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=False))
    db_session.commit()
    instance_monitor.reset_for_tests()
    instance_monitor.refresh_specs(db_session)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    yield _make_client(db_session, monkeypatch, tmp_path)
    instance_monitor.reset_for_tests()


def _auth(client, user="ad"):
    tokens = client.post("/api/v1/auth/login",
                         json={"username": user, "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_hangup_route_absent_by_default(client):
    # 默认关：路由未注册 → Starlette 直接 404。SPA catch-all 只注册了 GET
    # （core/spa.py:64），所以 POST 不会被兜成 `200 text/html`。
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "c-1"}, headers=_auth(client))
    assert response.status_code == 404


def test_hangup_proxies_with_admin_token(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(allocator_settings, "webrtc_hangup_enabled", True)
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "pipeline-admin-token")
    seen = {}

    def fake(base_url, call_id, token, timeout=5.0):
        seen.update(base_url=base_url, call_id=call_id, token=token, timeout=timeout)
        return 200

    monkeypatch.setattr(instance_probe, "hangup_call", fake)
    client = _make_client(db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "c-1"}, headers=_auth(client))
    assert response.status_code == 200
    assert response.json()["data"] == {"instance_id": "pipe-a", "session_id": "c-1",
                                       "upstream_status": 200}
    assert seen == {"base_url": "http://a:8765", "call_id": "c-1",
                    "token": "pipeline-admin-token", "timeout": 5.0}
    rows, _ = AuditRepository(db_session).list(action="instance.hangup", profile="pipe-a")
    assert len(rows) == 1 and rows[0].actor == "ad" and rows[0].fields == ["session_id"]


def test_hangup_is_admin_only(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(allocator_settings, "webrtc_hangup_enabled", True)
    client = _make_client(db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "c-1"}, headers=_auth(client, "op"))
    assert response.status_code == 403 and response.json()["code"] == "forbidden"


def test_hangup_without_a_configured_token_is_503(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(allocator_settings, "webrtc_hangup_enabled", True)
    monkeypatch.delenv("S2S_ADMIN_TOKEN", raising=False)
    client = _make_client(db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "c-1"}, headers=_auth(client))
    assert response.status_code == 503 and response.json()["code"] == "admin_disabled"


def test_hangup_unknown_call_passes_the_upstream_404_through(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(allocator_settings, "webrtc_hangup_enabled", True)
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "pipeline-admin-token")
    monkeypatch.setattr(instance_probe, "hangup_call", lambda *args, **kwargs: 404)
    client = _make_client(db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "gone"}, headers=_auth(client))
    assert response.status_code == 404 and response.json()["code"] == "upstream_not_found"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_instances_hangup_api.py -v`
Expected：`test_hangup_route_absent_by_default` 已 PASS（路由本就不存在），其余四个 FAIL/ERROR（`instances.hangup_router` 与 `instance_probe.hangup_call` 还不存在）

- [ ] **Step 3: 实现 `hangup_call`（追加到 `instance_probe.py`，顶部补 `import httpx`）**

```python
def hangup_call(base_url: str, call_id: str, token: str, timeout: float = 5.0) -> int:
    """`DELETE {base_url}/v1/realtime/calls/{call_id}` + Bearer（Task 17 的鉴权端点）。

    只回状态码：`0` 代表网络层没拿到响应，由路由翻成 502。替换点仍然在这一层，
    与 `probe_pool` 一致（spec §17），路由测试不需要碰 httpx。"""
    try:
        response = httpx.delete(
            f"{base_url.rstrip('/')}/v1/realtime/calls/{call_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except httpx.HTTPError:
        return 0
    return response.status_code
```

- [ ] **Step 4: 实现请求模型 + 路由 + 条件注册**

```python
# console/backend/app/schemas/instance.py 追加（顶部补 `from pydantic import BaseModel`）
class HangupRequest(BaseModel):
    # 就是实例侧的 call_id：WebRTC 会话在 /v1/realtime/calls 里以它寻址。
    session_id: str
```

```python
# console/backend/app/routers/instances.py 追加。
# Task 10 已在本文件引入 Depends/Request/CurrentUser/DbSession/ok 与 _registry_row/
# _audit/_request_id；这里只补 `import os`、`from fastapi import APIRouter`、
# `from app.config import allocator as allocator_settings`、`from app.core.errors import
# ApiError`、`from app.core.security import require_admin`、
# `from app.schemas.instance import HangupRequest`、`from app.services import instance_probe`。
hangup_router = APIRouter(prefix="/api/v1", tags=["instances"])


@hangup_router.post("/instances/{instance_id}/hangup")
def hangup(instance_id: str, payload: HangupRequest, request: Request, db: DbSession,
           user: CurrentUser = Depends(require_admin)):
    """spec §9.2：跨机代理实例侧的 WebRTC 挂断。默认不注册，开了才有这条路由。

    只对 WebRTC 传输有效；WS 会话没有服务端断开能力（spec §3）。"""
    row = _registry_row(db, instance_id)
    token = os.environ.get("S2S_ADMIN_TOKEN", "").strip()
    if not token:
        # 与 Task 17 的实例侧行为对齐：没配 token 是功能不可用（503），不是没权限。
        raise ApiError("admin_disabled", "S2S_ADMIN_TOKEN is not configured on this console", 503)
    upstream = instance_probe.hangup_call(row.base_url, payload.session_id, token)
    # 审计先于错误映射：一次挂断尝试无论成败都留痕（spec §5.3）。
    _audit(db, user, "instance.hangup", instance_id, ["session_id"], _request_id(request))
    if upstream == 0:
        raise ApiError("upstream_unreachable", f"instance {instance_id} did not answer the hangup", 502)
    if upstream == 401:
        raise ApiError("upstream_unauthorized", "the instance rejected S2S_ADMIN_TOKEN", 502)
    if upstream == 404:
        raise ApiError("upstream_not_found", f"no call {payload.session_id} on {instance_id}", 404)
    if upstream != 200:
        raise ApiError("upstream_error", f"instance {instance_id} answered {upstream}", 502)
    return ok({"instance_id": instance_id, "session_id": payload.session_id, "upstream_status": upstream})
```

```python
# console/backend/app/core/router_registry.py：紧跟 app.include_router(instances.router)
    from app.config import allocator as allocator_settings  # noqa: PLC0415 - 与本函数内既有延迟 import 同层

    # spec §9.2: the hangup proxy is opt-in. Unregistered means the path 404s —
    # the SPA catch-all is GET-only, so a POST never turns into a 200 HTML.
    if allocator_settings.webrtc_hangup_enabled:
        app.include_router(instances.hangup_router)
```

（`allocator_settings` 的 import 放在 `register_api_routers` 函数体内，和它上面那串 `from app.routers import (...)` 同一层，避免模块级 import 环。开关为真时 `hangup_router` 排在 `instances.router` 之后、SPA catch-all 之前，与 `router_registry` docstring 的“前缀顺序不可变”一致。）

- [ ] **Step 5: 多 console 并行分配回归（spec §17 "多活"层）**

```python
# console/backend/tests/unit/test_multi_console_overcommit.py
import pytest

from app.services import instance_monitor
from app.services.allocator import allocate
from app.services.allocator_store import InMemoryAllocatorStore
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


@pytest.mark.asyncio
async def test_two_stores_overcommit_only_yield_at_capacity():
    """两台 console 各持内存 store，但共享同一个实例视图：实例只有 1 个槽位。

    本机的乐观修正只防同机重复派发，看不见对端的 pending（spec §6.2），所以
    两台都会先拿到本地 grant；实例是槽位的最终仲裁者（spec §8.4），第二个
    连接一定吃 503 → 换台无可换 → allocate 返 None → 调用方回 503 at_capacity。"""
    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry.observe_success(
        "pipe-a", PoolState(reachable=True, size=1, in_use=0, units=()), 5)
    a, b = InMemoryAllocatorStore(), InMemoryAllocatorStore()
    remaining = [1]  # 实例侧只有 1 个真槽位

    async def instance_arbiter(spec):
        if remaining[0] > 0:
            remaining[0] -= 1
            return ""
        return "session_limit_reached"

    g1 = await allocate("s-a", store=a, claim=instance_arbiter)
    g2 = await allocate("s-b", store=b, claim=instance_arbiter)
    assert g1 is not None and g1["session_id"] == "s-a"
    assert g2 is None  # 超发的唯一下场：503 at_capacity，无异常态
    assert a.drain_counters() == {"alloc_ok:pipe-a": 1}
    assert b.drain_counters() == {"alloc_fail_instance_503:pipe-a": 1}
    # B 被拒后释放了自己的乐观占位，不会泄漏 pending_local
    assert b.pending_count("pipe-a") == 0
```

（`allocate(session_id, *, store=None, claim=None)` 的 `store`/`claim` 两个参数在 Task 13 实现时就已包含，本用例不新增任何产品代码；它验证的就是 spec §15 P1.6 的“双 console 超发只会以 at_capacity 收场”。）

- [ ] **Step 6: 运行 + 提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_instances_hangup_api.py tests/unit/test_multi_console_overcommit.py -v` → PASS

再确认默认关没有被别处打开：`.\.venv\Scripts\python.exe -m pytest tests/integration -v` → PASS（旧用例一律不读这个开关）

```bash
git add console/backend/app console/backend/tests
git commit -m "feat(console): optional hangup proxy behind admin flag; multi-console overcommit regression (P1.6)"
```

## Task 19: 文档与 runbook

**Files:**
- Modify: `docs/console-service.md`（已存在，314 行，9 章：1 是什么 / 2 默认账号与密码 / 3 端口与入口 / 4 本机跑起来 / 5 配置项 / 6 启动顺序与依赖 / 7 接口速查 / 8 常见故障 / 9 相关文件）

- [ ] **Step 1: 五处定点插入 + 末尾一章**

  1. **§5.2 之后新开 `### 5.3 实例注册与本地分配`**：把 spec §12 的 12 个变量逐行列成表（`ALLOCATOR_MODE` / `CONSOLE_ID` / `INSTANCES_SEED_PATH` / `INSTANCE_PROBE_INTERVAL_S` / `INSTANCE_PROBE_TIMEOUT_S` / `INSTANCE_FAIL_THRESHOLD` / `INSTANCE_RECOVER_THRESHOLD` / `INSTANCE_GRANT_TTL_S` / `INSTANCE_USAGE_INTERVAL_S` / `INSTANCE_METRIC_RETENTION_DAYS` / `INSTANCE_QUEUE_ENABLED` / `INSTANCE_WEBRTC_HANGUP_ENABLED`），列：变量 / 默认值 / 作什么用，默认值全部取 Task 1 代码块里的字面值，不靠记忆。
  2. **§7 接口速查表补 5 行**（接在既有 `GET /api/v1/instances` 那行之后）：`GET /api/v1/instances/{id}`（operator）、`GET /api/v1/instances/{id}/metrics?window=1h`（operator）、`POST …/drain|undrain|probe`（operator）、`POST …/hangup`（admin，默认不注册）。
  3. **新增 `## 10. 实例注册、巡检与多 console`**（排在现文末尾“9. 相关文件”之后，不改前面的编号），内容清单（逐条对应 spec）：
     - 双模式判定表（§8.1）与回退手段 `ALLOCATOR_MODE=off`（§8.4）
     - seed 文件格式与幂等规则、四类告警名（§7 的三个 + §9 的 `usage_unavailable`）：`instance_capacity_mismatch` / `instance_removed_from_seed` / `instance_seed_conflict` / `usage_unavailable`
     - 实例级状态机图（直接嵌入 spec §6.2 的 mermaid，不重画）
     - 远程实例运维流程：`drain → 该机自行发布/重启 → 巡检自动回 online → undrain`（§9.1）；本机实例仍走现有 `publish_flow_service`
     - 多 console 必须一致的变量清单（`JWT_SECRET_KEY`、`USAGE_HASH_SECRET`、`S2S_ADMIN_TOKEN`、`S2S_INTERNAL_TOKEN`、`INSTANCES_SEED_PATH` 内容）与 `/status` 新字段（`allocatorMode` / `instancesRegistered` / `seedConfigured` / `consoleId` / `secretsConsistent`，Task 11）
     - 部署前提：`/v1/pool`、`/v1/usage` 无应用层鉴权，靠网络 ACL（§16）；`DELETE /v1/realtime/calls/{call_id}` 从 P1.6 起要求 `S2S_ADMIN_TOKEN`（§9.2）——升级前先确认各机都配了 token，否则现有的 WebRTC 挂断调用会吃 503 `admin_disabled`
     - 指标口径：会话时长为估算（`grant_ts → unit 不再 active`）；跳变计数不累加，按 console 分组（§10）
     - console 单 worker 约束（§13/§16）：内存 store 与 `publish_flow_service` 进程内锁同前提
  4. **§9 相关文件表补 5 行**：`app/services/instance_registry.py`（实例级状态机）、`app/services/instance_monitor.py`（常驻巡检 + 指标采样）、`app/services/allocator.py` + `allocator_store.py`（本地分配 / Phase 2 替换点）、`app/services/instance_seed.py`（seed 幂等 upsert 与两类告警，seed 文件形状照抄 spec §7 的例）、`alembic/versions/0005_instances.py`（两张新表）。
  5. **§8 常见故障表补 4 行**（症状 → 原因与处理）：

| 症状 | 原因与处理 |
|---|---|
| 实例行一直停在 `unknown` | 首轮巡检未跑（`ALLOCATOR_MODE=off` 时不起巡检任务），或 seed 落了库但 `enabled=false` |
| `drain` 后仍拿到 grant | 看到的是已签发未领取的 pending（`INSTANCE_GRANT_TTL_S` 内不会消失），或 console 重启后忘了 `refresh_specs()` |
| `POST …/hangup` 返回 404 | `INSTANCE_WEBRTC_HANGUP_ENABLED` 没开，路由根本没注册（默认关，spec §9.2） |
| `POST …/hangup` 返回 503 `admin_disabled` | 这台 console 的 `S2S_ADMIN_TOKEN` 为空；多 console 必须与实例侧同值（spec §12） |

- [ ] **Step 2: 验收自查清单（对照 spec §15 全表逐项打勾）**

| 阶段 | 验收项 | 证据 |
|---|---|---|
| P1.0 | 空库启动 N 条 / 重复启动不重复 / `test_schema_sql` 双方言 | `tests/unit/test_instance_seed.py`、`tests/unit/test_schema_sql.py` |
| P1.1 | 全跳变 + 阈值边界 + stuck 扣减 | `tests/unit/test_instance_registry.py` |
| P1.2 | 15s 摘除 / 10s 恢复 / 跳变即时落 / 清理 / 异常不杀循环 | `tests/unit/test_instance_monitor.py` |
| P1.3 | 旧字段全绿 / drain 后不被选 / 审计落行 | `tests/integration/test_instances.py`、`test_instances_admin_api.py` |
| P1.4 | lb_service mock 逐字不变 / 空表回现状 / 503 换台 / grant 过期 / begin_once | `tests/demo/test_session_api.py`（旧用例 diff=0）、`test_allocator*.py` |
| P1.5 | vitest + `npm run build` + observed_by 不重复 | `instances-view.spec.ts`、构建日志 |
| P1.6 | 无 token 401 / 有 token 200 / 双 console 超发只 503 / 文档 | `test_webrtc_hangup_auth.py`、`test_multi_console_overcommit.py`、`test_instances_hangup_api.py`、docs |

- [ ] **Step 3: 提交**

```bash
git add docs
git commit -m "docs(console): instance registry, monitoring and multi-console runbook (P1.6)"
```

---

## Self-Review（计划完成后自查，已修正项内联于正文）

1. **Spec 覆盖**：§4 文件表→Task 1–19；§5 数据模型→Task 2–3；§6 状态机→Task 7；§7 seed→Task 4；§8 分配→Task 12–14；§9 巡检→Task 5–6、8、17–18；§10 指标→Task 3、8、15；§11 API→Task 10、16、18；§12 配置→Task 1、4、19；§13 Store→Task 12；§14 前端→Task 15–16；§15 验收→Task 19 表；§17 测试→各任务 Step 1；§16 风险→Global Constraints + Task 18/19。无未落任务的 spec 条目。
2. **占位扫描**：已把全部初稿占位改写为可直接照抄的终态：Task 3 的 `InstanceMetricRepository` 残片与 `DEFAULT counters = None` 笔误段→完整 `_COUNT_COLUMNS` + `insert_many`；Task 8 的 `hasattr(allocator_service, ...)` 探测→`sample_metrics(session, counters=None)` 参数注入 + `_counters_for`，`run_forever` 直接传 `allocator_service.drain_counters()`；Task 9 的 `pending_grants` 不再用 `hasattr` 而是固定 0 + Task 13 明指接线块；Task 13 的 `... if False else ""` 伪代码与 `settings.seed if hasattr(...)` →真 `async def allocate` + `await claim(spec)`；Task 13 Step 3 的 `grant = await_allocator = None` 与 `_call_allocate` 辅助函数→直接 `await allocator.allocate(...)`；Task 18 初稿只有“主体断言”的片段测试与一句“执行时选后者”的歧义批注→完整测试文件（含 fixture、默认关 / 代理带 Bearer / 非 admin 403 / 未配 token 503 / 上游 404 透传五个用例）+ `hangup_call` 与 `hangup_router` 的实现块 + `router_registry` 的条件注册行（开关在 `create_app()` 内求值，不靠 `importlib.reload`）；Task 19 的“若不存在则…”对冲措辞→已核实 `docs/console-service.md` 存在（314 行 / 9 章）后改成 5 个具名插入点（新开 §5.3、§7 补 5 行、新增 §10、§9 补 5 行、§8 补 4 行）。全文无 TBD/TODO/“同 Task N”/只有描述没有代码的步骤。
3. **类型一致性**（跨任务逐字校对）：`RuntimeState.effective_free`（Task 7 不扣 pending）与 `_candidates` 里 `free = effective_free - target.pending_count(id)`（Task 13）合起来等于 spec §6.2 公式；`AllocatorStore` 接口块（Task 12 Interfaces）与 `allocator_store.py` 实现块逐字一致（含补充的 `pending_count`/`drain_counters`/`remember_grant`/`grant_for`）；`reserve(instance_id, session_id, ttl_s) -> bool`、`begin_once(dedupe_key, window_s) -> str | None`、`release(session_id) -> None` 在 Task 12/13/14/18 间一致；`allocate(session_id: str, *, store=None, claim=None) -> dict | None` 与 Task 14 的 `await allocator.allocate(str(uuid.uuid4()))`、Task 18 的 `await allocate("s-a", store=a, claim=instance_arbiter)` 一致；计数器键名 `alloc_ok:{id}` / `alloc_fail_instance_503:{id}` / `alloc_fail_no_instance` 在 Task 12 bump、Task 13 产生、Task 8 `_counters_for` 消费三处逐字相同；边沿事件写入的列名 `evict_count`/`recover_count` 通过 Task 8 的 `_EDGE_COUNTERS` 映射，与 Task 2 建表、Task 10 `evictCount`/`recoverCount` 响应字段一致；`instance_probe` 全模块同步口径：`hangup_call(base_url, call_id, token, timeout=5.0) -> int`（Task 18 Step 3）与 `probe_pool`（Task 6）同为同步，Task 18 Step 1 的替身也是 `def fake` 而不是 `async def`；审计关联 id 统一走 `_request_id(request)`（Task 10 定义，读 `request.state.request_id`，与 `routers/profiles.py:20` 同构），Task 18 的 `instance.hangup` 也用它；演示面去重键仍读头 `X-Request-Id`（Task 14，spec §8.5 要求的是客户端传入头，与审计关联不同）。
4. **执行顺序约束**（任务图，供执行者分批）：P1.0 = Task 1→2→3→4（严格串行）；P1.1 = Task 5/6 可并行，Task 7 依赖 Task 5；P1.2 = Task 8 依赖 6+7；P1.3 = Task 9→10→11（依赖 8）；P1.4 = Task 12→13→14（依赖 8）；P1.5 = Task 15→16（依赖 10 的 API 形状）；P1.6 = Task 17→18→19（Task 17 独立，可与 P1.1–P1.4 并行开工）。

