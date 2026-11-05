# 集群总览（CON-02）改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把真实控制台「集群总览」页按静态原型 `console-refactor-demo.html` 完成前后端一体改造：新集群实体（表+迁移+CRUD API+权限码层+审计）、KPI 四卡、集群表、拓扑 SVG、图例与最近事件，数据全部来自真实接口。

**Architecture:** 后端沿用 `routers → services → repositories → models` 分层与 `ok()` 信封、`ApiError` 错误、`AuditRepository` 审计的既有模式，新增 `param_cluster` 表与 `console:cluster:*` 权限码依赖工厂；前端新增 cluster pinia store（sessionStorage 持久化当前集群），OverviewView 重写为五段结构，机器为按 `base_url` host 派生的展示实体（非表）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (Mapped) + Alembic + pytest；Vue 3 + ant-design-vue 4 + Pinia + vue-i18n + Vitest + vue-tsc + less。

**Spec:** `docs/superpowers/specs/2026-11-05-cluster-overview-design.md`（本计划逐节实现该 spec，冲突以 spec 为准）

## Global Constraints

- 迁移编号使用 `0006_clusters`，`down_revision = "0005_instances"`；其他分支已占用 0006/0007 时在交付说明记录 rebase 事项（spec §2.4）。
- 全部写操作落审计（`param_audit`），业务失败（400/403/404/409）同样记 `result="error"` + `error_code`；401 发生在解析操作人之前，不记审计。
- 权限码 `console:` 前缀；未注册权限码在依赖构造期直接 `RuntimeError`。
- 校验正则（前后端逐字一致）：名称 `^[a-z0-9][a-z0-9-]{1,39}$`；registry `^([a-z][a-z0-9+.-]*://)?[\w.-]+:\d{2,5}$`（忽略大小写）；policy 枚举 `least|rr|lat`。
- `error_rate_5m` 窗口 300s；窗口分母为 0 → 字段 `null`，绝不返回 0；前端渲染 `DASH`（`'—'`）；`alloc_fail_instance_503` 与 `alloc_fail_no_instance` 不重复计数。
- 前端文案全部走 i18n en/zh 成对（`i18n/i18n.spec.ts` parity 测试强制）；registry、policy 枚举、端口、instance_id、host 以代码态原文展示不翻译。
- 颜色一律 `--s2s-*` CSS 变量（`styles/hex-ban.spec.ts` 禁止新增十六进制字面量）。
- 不改动范围外页面；`InstancesView.vue` 唯一允许的增量是读 `route.query.host` 高亮/筛选。
- 当前集群持久化用 `sessionStorage` 键 `s2s.console.cluster`（与 `s2s.console.profile` 同规则，`utils/storage.ts` 约定）。
- 不提交 `dist/` 等构建产物；分支/提交信息不含 `codex`；未经明确确认不合并 PR。
- 后端命令在 `console/backend` 目录运行（pytest 配置在该目录 pyproject.toml）；前端命令在 `console/frontend` 运行。
- 存量回归红线：`GET /api/v1/instances` 不带 `cluster` 参数时，legacy 单实例路径（注册表为空）响应逐字段与改造前一致。

**执行前提**：当前分支 `feat/cluster-overview-console`（已含 spec 提交）。每个任务结束时提交一次；提交信息用 `feat/fix/test/refactor/chore(scope): ...`，不带 codex。任务顺序：后端迁移/权限码层（T1-T2）→ 集群 API（T3-T5）→ 前端组件（T6-T13）→ 联调九场景（T14）。

---

### Task 1: 集群模型 + Alembic 迁移 0006_clusters

**Files:**
- Create: `console/backend/app/models/param_cluster.py`
- Create: `console/backend/alembic/versions/0006_clusters.py`
- Modify: `console/backend/app/models/__init__.py`
- Modify: `console/backend/app/models/param_instance.py`（加 `cluster_id` 列）
- Test: `console/backend/tests/unit/test_migration_0006_clusters.py`

**Interfaces:**
- Consumes: 无（链路起点）
- Produces: `ParamCluster(id, name, registry, policy, note, created_at, updated_at, updated_by)`；`ParamInstance.cluster_id: Mapped[str]`（默认 `"default"`）；表 `param_cluster` 含 seed 行 `default`；索引 `ix_param_instance_cluster_id`

- [ ] **Step 0: 确认 alembic 可用**

Run（cwd = `console/backend`）: `D:/work/qwen-audio-agent/speech-to-speech-src/.venv/Scripts/python.exe -c "import alembic; print(alembic.__version__)"`
Expected: 打印版本号。若 ImportError，先 `uv pip install alembic` 并在交付说明记录。

- [ ] **Step 1: 写失败测试**

Create `console/backend/tests/unit/test_migration_0006_clusters.py`:

```python
"""0006_clusters 迁移的形状与 seed（spec §2）。

tests/conftest.py 的 db_session 走 `Base.metadata.create_all`，不跑迁移，
所以这里用 alembic programmatic API 在一个独立临时 SQLite 库上升级到 head，
验证真迁移能跑通且 default 行可重入。
"""
from __future__ import annotations

import pathlib

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime import migration
from alembic.script import ScriptDirectory

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _upgrade(url: str, revision: str = "head") -> None:
    cfg = _config(url)
    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            context = migration.MigrationContext.configure(connection)
            already = set(context.get_current_heads()) >= heads
        if not already:
            command.upgrade(cfg, revision)
    finally:
        engine.dispose()


def _table_names(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _cluster_names(url: str) -> list[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return [r[0] for r in conn.execute(sa.text("SELECT name FROM param_cluster ORDER BY id"))]
    finally:
        engine.dispose()


def test_upgrade_creates_cluster_table_with_default_seed(tmp_path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    _upgrade(url)
    assert "param_cluster" in _table_names(url)
    assert _cluster_names(url) == ["default"]


def test_seed_is_reentrant_when_default_row_exists_first(tmp_path):
    # 运维手工补插过 default 行 → 迁移仍不得因唯一约束中断（spec §2.3 可重入）
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    _upgrade(url, "0005_instances")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO param_cluster "
                "(name, registry, policy, note, created_at, updated_at, updated_by) "
                "VALUES ('default', '', 'least', '', datetime('now'), datetime('now'), 'manual')"
            )
        )
    engine.dispose()
    _upgrade(url, "head")
    assert _cluster_names(url) == ["default"]


def test_instance_cluster_id_backfills_and_index_exists(tmp_path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    _upgrade(url, "0005_instances")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO param_instance (instance_id, base_url, weight, labels_json, enabled, "
                "drain_requested, created_at, updated_at, updated_by) "
                "VALUES ('legacy-a', 'http://a:8765', 1, '{}', 1, 0, datetime('now'), datetime('now'), 'seed')"
            )
        )
    engine.dispose()
    _upgrade(url, "head")
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            value = conn.execute(
                sa.text("SELECT cluster_id FROM param_instance WHERE instance_id = 'legacy-a'")
            ).scalar_one()
        idx = {i["name"] for i in sa.inspect(engine).get_indexes("param_instance")}
    finally:
        engine.dispose()
    assert value == "default"
    assert "ix_param_instance_cluster_id" in idx
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_migration_0006_clusters.py -v`
Expected: FAIL —— `no such table: param_cluster`（`sa.exc.OperationalError`）。

- [ ] **Step 3: 模型**

Create `console/backend/app/models/param_cluster.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamCluster(Base):
    """集群边界的管理标签（spec §2.1）。不建 FK：`param_instance.cluster_id` 是软关联，
    与 param_instance/param_instance_metric 既有做法一致。
    registry 空串 = default 集群（存量零感知的落点）；非空值的全局唯一由服务层校验，
    DB 层不加唯一约束（spec §2.1）。"""

    __tablename__ = "param_cluster"
    __table_args__ = (UniqueConstraint("name", name="uq_param_cluster_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    registry: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    policy: Mapped[str] = mapped_column(String(16), nullable=False, default="least")
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
```

Modify `console/backend/app/models/__init__.py`：`from .param_audit import ParamAudit` 之后加 `from .param_cluster import ParamCluster`，并把 `"ParamCluster"` 加进 `__all__`（紧跟 `"ParamAudit"`）。

Modify `console/backend/app/models/param_instance.py`：在 `updated_by` 之后追加：

```python
    # 集群归属（spec §2.2）：软关联 param_cluster.name，存量经 server_default 落 default。
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
```

- [ ] **Step 4: 迁移**

Create `console/backend/alembic/versions/0006_clusters.py`:

```python
"""Cluster registry (spec 2026-11-05 §2).

Revision ID: 0006_clusters
Revises: 0005_instances
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_clusters"
down_revision = "0005_instances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_cluster",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("registry", sa.String(255), server_default="", nullable=False),
        sa.Column("policy", sa.String(16), server_default="least", nullable=False),
        sa.Column("note", sa.String(255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.UniqueConstraint("name", name="uq_param_cluster_name"),
    )
    # 可重入 seed（spec §2.3）：INSERT … SELECT … WHERE NOT EXISTS，
    # 手工补插过 default 行的库重跑迁移不中断、不重复插。参数化常量 SQL，无注入面。
    op.execute(
        sa.text(
            "INSERT INTO param_cluster "
            "(name, registry, policy, note, created_at, updated_at, updated_by) "
            "SELECT 'default', '', 'least', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'migration' "
            "WHERE NOT EXISTS (SELECT 1 FROM param_cluster WHERE name = 'default')"
        )
    )
    # param_instance 加列：SQLite 下 ADD COLUMN 带 NOT NULL 必须有 server_default，
    # batch_alter_table 兼容 Postgres 与 SQLite 的重建语义。
    with op.batch_alter_table("param_instance") as batch:
        batch.add_column(
            sa.Column("cluster_id", sa.String(64), server_default="default", nullable=False)
        )
    op.create_index("ix_param_instance_cluster_id", "param_instance", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_param_instance_cluster_id", table_name="param_instance")
    with op.batch_alter_table("param_instance") as batch:
        batch.drop_column("cluster_id")
    op.drop_table("param_cluster")
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/unit/test_migration_0006_clusters.py -v` → 3 passed。
Run: `pytest tests/unit tests/integration -x -q` → 存量全绿（`cluster_id` 加列不影响既有 create_all 路径）。

- [ ] **Step 6: Commit**

```bash
git add console/backend/app/models console/backend/alembic/versions/0006_clusters.py console/backend/tests/unit/test_migration_0006_clusters.py
git commit -m "feat(backend): add param_cluster table and 0006 migration with reentrant default seed"
```

---

### Task 2: 权限码层 `app/core/permissions.py`

**Files:**
- Create: `console/backend/app/core/permissions.py`
- Test: `console/backend/tests/unit/test_permissions.py`

**Interfaces:**
- Consumes: `app.core.security.CurrentUser`、`require_user`、`app.core.errors.ApiError`
- Produces: `PERMISSION_ROLES: dict[str, frozenset[str]]`（键 `console:cluster:query|switch|create|update|delete`）；`ensure_permission(code, user) -> CurrentUser`；`require_permission(code) -> Callable[..., CurrentUser]`（未注册码构造时 `RuntimeError`）

- [ ] **Step 1: 写失败测试**

Create `console/backend/tests/unit/test_permissions.py`:

```python
from __future__ import annotations

import pytest

from app.core.errors import ApiError
from app.core.permissions import PERMISSION_ROLES, ensure_permission, require_permission
from app.core.security import CurrentUser


def test_registry_contains_the_five_cluster_codes():
    assert set(PERMISSION_ROLES) == {
        "console:cluster:query",
        "console:cluster:switch",
        "console:cluster:create",
        "console:cluster:update",
        "console:cluster:delete",
    }
    assert PERMISSION_ROLES["console:cluster:switch"] == frozenset({"admin", "operator"})
    assert PERMISSION_ROLES["console:cluster:create"] == frozenset({"admin"})


def test_unknown_permission_code_raises_at_factory_time():
    with pytest.raises(RuntimeError):
        require_permission("console:cluster:teleport")


def test_operator_passes_query_switch_and_fails_create():
    ensure_permission("console:cluster:query", CurrentUser(username="op", role="operator"))
    ensure_permission("console:cluster:switch", CurrentUser(username="op", role="operator"))
    with pytest.raises(ApiError) as excinfo:
        ensure_permission("console:cluster:create", CurrentUser(username="op", role="operator"))
    assert excinfo.value.code == "forbidden"
    assert excinfo.value.status == 403


def test_client_role_fails_even_query():
    with pytest.raises(ApiError) as excinfo:
        ensure_permission("console:cluster:query", CurrentUser(username="c", role="client"))
    assert excinfo.value.code == "forbidden"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_permissions.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.core.permissions'`。

- [ ] **Step 3: 实现**

Create `console/backend/app/core/permissions.py`:

```python
"""Permission-code layer (spec 2026-11-05 §3).

角色制（require_admin/require_operator）继续服务既有端点；新模块一律挂权限码。
映射集中在此一处，前端 `utils/permissions.ts` 是同表镜像——改这里必须同步改那里，
两处不一致时以后端 403 为准。
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends

from app.core.errors import ApiError
from app.core.security import CurrentUser, require_user

# 未注册的码在依赖构造期直接 RuntimeError（启动即失败，防打字错误）。
PERMISSION_ROLES: dict[str, frozenset[str]] = {
    "console:cluster:query": frozenset({"admin", "operator"}),
    # switch 只是视图切换的审计留痕；限 admin 会让 operator 切集群吃 403，
    # 与原型「任何登录用户可切换」冲突（spec §3 注）。
    "console:cluster:switch": frozenset({"admin", "operator"}),
    "console:cluster:create": frozenset({"admin"}),
    "console:cluster:update": frozenset({"admin"}),
    "console:cluster:delete": frozenset({"admin"}),
}


def ensure_permission(code: str, user: CurrentUser) -> CurrentUser:
    roles = PERMISSION_ROLES.get(code)
    if roles is None:
        raise RuntimeError(f"unregistered permission code: {code}")
    if user.role not in roles:
        raise ApiError("forbidden", f"role {user.role} lacks {code}", 403)
    return user


def require_permission(code: str) -> Callable[..., CurrentUser]:
    if code not in PERMISSION_ROLES:
        raise RuntimeError(f"unregistered permission code: {code}")

    def dependency(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        return ensure_permission(code, user)

    return dependency
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_permissions.py -v` → passed。

- [ ] **Step 5: Commit**

```bash
git add console/backend/app/core/permissions.py console/backend/tests/unit/test_permissions.py
git commit -m "feat(backend): add console:cluster:* permission-code layer with factory-time registry check"
```

---

### Task 3: ClusterRepository + cluster_service 校验链

**Files:**
- Create: `console/backend/app/repositories/cluster_repository.py`
- Create: `console/backend/app/services/cluster_service.py`
- Modify: `console/backend/app/repositories/instance_repository.py`（加 `cluster_counts`）
- Test: `console/backend/tests/unit/test_cluster_service.py`

**Interfaces:**
- Consumes: `ParamCluster`、`ParamInstance.cluster_id`（Task 1）、`ApiError`
- Produces:
  - `ClusterRepository(session)`: `list_all()`（`ORDER BY id`，default 恒在最前）、`get_by_name(name)`、`count_registry_conflicts(registry, *, exclude_name="")`、`create(...)`、`update(row, *, registry, policy, note, updated_by)`、`delete(row)`
  - `InstanceRepository.cluster_counts() -> dict[str, int]`
  - `cluster_service`: 常量 `NAME_RE`、`REGISTRY_RE`、`POLICIES`；函数 `list_clusters(db)`、`get_cluster(db, name)`、`exists(db, name)`、`create_cluster(db, *, name, registry, policy, note, actor)`、`update_cluster(db, *, name, registry, policy, note, actor)`、`delete_cluster(db, *, name, actor)`；错误码 `invalid_request|duplicate_name|duplicate_registry|cluster_not_found|cluster_not_empty|last_cluster`

- [ ] **Step 1: 写失败测试**

Create `console/backend/tests/unit/test_cluster_service.py`:

```python
from __future__ import annotations

import pytest

from app.core.errors import ApiError
from app.models.param_cluster import ParamCluster
from app.models.param_instance import ParamInstance
from app.services import cluster_service


def _seed(db, name="default", registry="", policy="least", note=""):
    row = ParamCluster(name=name, registry=registry, policy=policy, note=note)
    db.add(row)
    db.commit()
    return row


def test_create_valid_cluster(db_session):
    _seed(db_session)
    row = cluster_service.create_cluster(
        db_session, name="gray-01", registry="consul://10.12.0.9:8500",
        policy="rr", note="canary pool", actor="alice",
    )
    assert row.name == "gray-01" and row.updated_by == "alice"


@pytest.mark.parametrize("bad", ["a", "A", "-x", "x" * 41, "has_dot", "under_score", "中文名"])
def test_create_rejects_bad_name(db_session, bad):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(db_session, name=bad, registry="h:8500", policy="least", note="", actor="a")
    assert excinfo.value.code == "invalid_request"


def test_create_rejects_duplicate_name(db_session):
    _seed(db_session, name="gray-01", registry="h1:8500")
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(db_session, name="gray-01", registry="h2:8500", policy="least", note="", actor="a")
    assert excinfo.value.code == "duplicate_name" and excinfo.value.status == 409


@pytest.mark.parametrize("bad", ["", "ftp://host", "host", "host:", "http://h:1", "tcp://h:65536x"])
def test_create_rejects_bad_registry(db_session, bad):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(db_session, name="new-01", registry=bad, policy="least", note="", actor="a")
    assert excinfo.value.code == "invalid_request"


def test_registry_match_is_case_insensitive_scheme(db_session):
    _seed(db_session)
    row = cluster_service.create_cluster(
        db_session, name="new-01", registry="CONSUL://Host:8500", policy="least", note="", actor="a"
    )
    assert row.registry == "CONSUL://Host:8500"


def test_create_rejects_duplicate_registry(db_session):
    _seed(db_session, name="gray-01", registry="consul://h:8500")
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(db_session, name="new-02", registry="consul://h:8500", policy="least", note="", actor="a")
    assert excinfo.value.code == "duplicate_registry" and excinfo.value.status == 409


def test_create_rejects_bad_policy(db_session):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(db_session, name="new-03", registry="h:8500", policy="fifo", note="", actor="a")
    assert excinfo.value.code == "invalid_request"


def test_update_keeps_name_and_allows_own_registry(db_session):
    _seed(db_session, name="gray-01", registry="consul://h:8500")
    row = cluster_service.update_cluster(
        db_session, name="gray-01", registry="consul://h:8500", policy="lat", note="edited", actor="alice"
    )
    assert row.policy == "lat" and row.note == "edited"


def test_update_rejects_registry_owned_by_other(db_session):
    _seed(db_session, name="gray-01", registry="consul://h:8500")
    _seed(db_session, name="blue-01", registry="consul://h:8600")
    with pytest.raises(ApiError) as excinfo:
        cluster_service.update_cluster(db_session, name="gray-01", registry="consul://h:8600", policy="least", note="", actor="a")
    assert excinfo.value.code == "duplicate_registry"


def test_update_unknown_cluster_is_404(db_session):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.update_cluster(db_session, name="ghost", registry="h:1", policy="least", note="", actor="a")
    assert excinfo.value.code == "cluster_not_found" and excinfo.value.status == 404


def test_delete_blocked_by_instances(db_session):
    _seed(db_session)
    _seed(db_session, name="gray-01", registry="h:8500")
    db_session.add(ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=False, cluster_id="gray-01"))
    db_session.commit()
    with pytest.raises(ApiError) as excinfo:
        cluster_service.delete_cluster(db_session, name="gray-01", actor="a")
    assert excinfo.value.code == "cluster_not_empty" and "1" in excinfo.value.message


def test_delete_blocked_on_last_cluster(db_session):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.delete_cluster(db_session, name="default", actor="a")
    assert excinfo.value.code == "last_cluster"


def test_delete_ok_when_empty(db_session):
    _seed(db_session)
    _seed(db_session, name="gray-01", registry="h:8500")
    cluster_service.delete_cluster(db_session, name="gray-01", actor="a")
    assert [c.name for c in cluster_service.list_clusters(db_session)] == ["default"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_cluster_service.py -v`
Expected: FAIL —— `ImportError`/`AttributeError`（cluster_service、ClusterRepository、cluster_counts 不存在）。

- [ ] **Step 3: Repository**

Create `console/backend/app/repositories/cluster_repository.py`:

```python
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.param_cluster import ParamCluster


class ClusterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[ParamCluster]:
        # ORDER BY id：default（seed 行）恒在最前，前端回落依赖这个顺序（spec §5.1）。
        return list(self.session.scalars(select(ParamCluster).order_by(ParamCluster.id)))

    def get_by_name(self, name: str) -> ParamCluster | None:
        return self.session.scalar(select(ParamCluster).where(ParamCluster.name == name))

    def count_registry_conflicts(self, registry: str, *, exclude_name: str = "") -> int:
        stmt = select(func.count()).select_from(ParamCluster).where(ParamCluster.registry == registry)
        if exclude_name:
            stmt = stmt.where(ParamCluster.name != exclude_name)
        return int(self.session.scalar(stmt) or 0)

    def create(self, *, name: str, registry: str, policy: str, note: str, updated_by: str) -> ParamCluster:
        row = ParamCluster(name=name, registry=registry, policy=policy, note=note, updated_by=updated_by)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def update(self, row: ParamCluster, *, registry: str, policy: str, note: str, updated_by: str) -> ParamCluster:
        # name 永不变更（spec §4.1：编辑态名称禁用，PUT body 无 name）。
        row.registry, row.policy, row.note = registry, policy, note
        row.updated_by, row.updated_at = updated_by, utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete(self, row: ParamCluster) -> None:
        self.session.delete(row)
        self.session.commit()
```

Modify `console/backend/app/repositories/instance_repository.py`：import 改为 `from sqlalchemy import func, select`，在类末尾追加：

```python
    def cluster_counts(self) -> dict[str, int]:
        """每集群实例数：集群列表聚合与删除阻塞共用（spec §4.1/§4.2）。"""
        rows = self.session.execute(
            select(ParamInstance.cluster_id, func.count()).group_by(ParamInstance.cluster_id)
        )
        return {cluster_id: int(total) for cluster_id, total in rows}
```

- [ ] **Step 4: Service（校验链与原型逐条一致）**

Create `console/backend/app/services/cluster_service.py`:

```python
from __future__ import annotations

import re

from app.core.errors import ApiError
from app.repositories.cluster_repository import ClusterRepository
from app.repositories.instance_repository import InstanceRepository

# 与原型 saveClusterForm（console-refactor-demo.html L2878-2908）逐字一致（spec §4.1）。
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
REGISTRY_RE = re.compile(r"^([a-z][a-z0-9+.-]*://)?[\w.-]+:\d{2,5}$", re.IGNORECASE)
POLICIES = ("least", "rr", "lat")


def _validate_fields(*, registry: str, policy: str, note: str) -> None:
    # registry 创建/更新必填：default 集群的空 registry 只是存量 seed 态，
    # 任何一次提交都必须给出合法 registry（spec §4.1）。
    if not isinstance(registry, str) or not REGISTRY_RE.match(registry or ""):
        raise ApiError("invalid_request", "registry must look like host:port or scheme://host:port", 400)
    if policy not in POLICIES:
        raise ApiError("invalid_request", f"policy must be one of {list(POLICIES)}", 400)
    if not isinstance(note, str) or len(note) > 255:
        raise ApiError("invalid_request", "note must be a string of at most 255 chars", 400)


def list_clusters(db) -> list:
    return ClusterRepository(db).list_all()


def get_cluster(db, name: str):
    row = ClusterRepository(db).get_by_name(name)
    if row is None:
        raise ApiError("cluster_not_found", f"cluster {name} does not exist", 404)
    return row


def exists(db, name: str) -> bool:
    return ClusterRepository(db).get_by_name(name) is not None


def create_cluster(db, *, name: str, registry: str, policy: str, note: str, actor: str):
    if not NAME_RE.match(name or ""):
        raise ApiError("invalid_request", "name must match ^[a-z0-9][a-z0-9-]{1,39}$", 400)
    repo = ClusterRepository(db)
    if repo.get_by_name(name) is not None:
        raise ApiError("duplicate_name", f"cluster {name} already exists", 409)
    _validate_fields(registry=registry, policy=policy, note=note)
    if repo.count_registry_conflicts(registry) > 0:
        raise ApiError("duplicate_registry", f"registry {registry} is already used by another cluster", 409)
    return repo.create(name=name, registry=registry, policy=policy, note=note, updated_by=actor)


def update_cluster(db, *, name: str, registry: str, policy: str, note: str, actor: str):
    repo = ClusterRepository(db)
    row = repo.get_by_name(name)
    if row is None:
        raise ApiError("cluster_not_found", f"cluster {name} does not exist", 404)
    _validate_fields(registry=registry, policy=policy, note=note)
    if repo.count_registry_conflicts(registry, exclude_name=name) > 0:
        raise ApiError("duplicate_registry", f"registry {registry} is already used by another cluster", 409)
    return repo.update(row, registry=registry, policy=policy, note=note, updated_by=actor)


def delete_cluster(db, *, name: str, actor: str) -> None:
    repo = ClusterRepository(db)
    row = repo.get_by_name(name)
    if row is None:
        raise ApiError("cluster_not_found", f"cluster {name} does not exist", 404)
    if len(repo.list_all()) <= 1:
        raise ApiError("last_cluster", "the last cluster cannot be deleted", 409)
    blocking: int = InstanceRepository(db).cluster_counts().get(name, 0)
    if blocking > 0:
        raise ApiError("cluster_not_empty", f"cluster {name} still has {blocking} instance(s)", 409)
    repo.delete(row)
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/unit/test_cluster_service.py -v` → 全绿。
Run: `pytest tests/unit tests/integration -x -q` → 存量不回归。

- [ ] **Step 6: Commit**

```bash
git add console/backend/app/repositories console/backend/app/services/cluster_service.py console/backend/tests/unit/test_cluster_service.py
git commit -m "feat(backend): add cluster repository and service validation chain mirroring the prototype"
```

---

### Task 4: `/api/v1/clusters` 路由（CRUD + switch + events，审计全落）

**Files:**
- Create: `console/backend/app/schemas/cluster.py`
- Create: `console/backend/app/routers/clusters.py`
- Modify: `console/backend/app/core/router_registry.py`
- Modify: `console/backend/app/repositories/audit_repository.py`（加 `list_prefix`）
- Modify: `console/backend/app/services/cluster_service.py`（加 `instance_host_stats`、`_host_of`）
- Test: `console/backend/tests/integration/test_clusters_api.py`

**Interfaces:**
- Consumes: `cluster_service`（Task 3）、`require_permission`（Task 2）、`AuditRepository.record`、`ok()`、`iso_utc()`、`instance_monitor.snapshot()`（既有）
- Produces:
  - 端点：`GET /api/v1/clusters`（行含 `machines_total/machines_online/healthy/instances_total`）、`GET /api/v1/clusters/events?limit=4`、`GET /api/v1/clusters/{name}`、`POST /api/v1/clusters`、`PUT /api/v1/clusters/{name}`、`DELETE /api/v1/clusters/{name}`、`POST /api/v1/clusters/{name}/switch`（均挂权限码）
  - `ClusterCreate`/`ClusterUpdate`（pydantic，`extra="forbid"`，字段无约束——校验在 service 层以保证失败可审计）
  - `AuditRepository.list_prefix(action_prefix, *, limit) -> list[ParamAudit]`
  - `cluster_service.instance_host_stats(db, cluster_name) -> dict`、`_host_of(base_url) -> str`

- [ ] **Step 1: 写失败测试**

Create `console/backend/tests/integration/test_clusters_api.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.models.param_audit import ParamAudit
from app.models.param_cluster import ParamCluster
from app.models.param_instance import ParamInstance
from app.repositories.user_repository import UserRepository
from app.services import process_probe
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
    UserRepository(db_session).create("bob", hash_password("correct-horse"), "operator")
    UserRepository(db_session).create("carol", hash_password("correct-horse"), "client")
    process_probe.set_probe(process_probe.NullProbe("test has no supervisor"))
    yield TestClient(app)
    process_probe.set_probe(None)


def _auth(client, username, password="correct-horse"):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _seed_cluster(db, name="default", registry="", policy="least", note=""):
    db.add(ParamCluster(name=name, registry=registry, policy=policy, note=note))
    db.commit()


def _audit_rows(db, action):
    return list(db.scalars(select(ParamAudit).where(ParamAudit.action == action)))


def test_list_returns_seeded_default_first(client, db_session):
    _seed_cluster(db_session)
    rows = client.get("/api/v1/clusters", headers=_auth(client, "alice")).json()["data"]
    assert rows[0]["name"] == "default"
    assert {"name", "registry", "policy", "note", "machines_total", "machines_online",
            "instances_total", "healthy", "updated_at", "updated_by"} <= set(rows[0])


def test_create_valid_cluster_writes_ok_audit(client, db_session):
    _seed_cluster(db_session)
    response = client.post(
        "/api/v1/clusters", headers=_auth(client, "alice"),
        json={"name": "gray-01", "registry": "consul://10.12.0.9:8500", "policy": "rr", "note": "canary"},
    )
    assert response.status_code == 200 and response.json()["data"]["name"] == "gray-01"
    rows = _audit_rows(db_session, "cluster.create")
    assert len(rows) == 1 and rows[0].result == "ok" and rows[0].profile == "gray-01"
    assert rows[0].actor == "alice"


def test_create_invalid_name_writes_error_audit(client, db_session):
    _seed_cluster(db_session)
    response = client.post(
        "/api/v1/clusters", headers=_auth(client, "alice"),
        json={"name": "BAD NAME", "registry": "h:8500", "policy": "least", "note": ""},
    )
    assert response.status_code == 400 and response.json()["code"] == "invalid_request"
    rows = _audit_rows(db_session, "cluster.create")
    assert len(rows) == 1 and rows[0].result == "error" and rows[0].error_code == "invalid_request"


def test_create_duplicate_registry_is_409_with_audit(client, db_session):
    _seed_cluster(db_session, name="gray-01", registry="consul://h:8500")
    response = client.post(
        "/api/v1/clusters", headers=_auth(client, "alice"),
        json={"name": "blue-01", "registry": "consul://h:8500", "policy": "least", "note": ""},
    )
    assert response.status_code == 409 and response.json()["code"] == "duplicate_registry"
    assert _audit_rows(db_session, "cluster.create")[0].error_code == "duplicate_registry"


def test_update_allows_own_registry_blocks_foreign(client, db_session):
    _seed_cluster(db_session, name="gray-01", registry="consul://h:8500")
    _seed_cluster(db_session, name="blue-01", registry="consul://h:8600")
    ok_response = client.put(
        "/api/v1/clusters/gray-01", headers=_auth(client, "alice"),
        json={"registry": "consul://h:8500", "policy": "lat", "note": "self-ok"},
    )
    assert ok_response.status_code == 200 and ok_response.json()["data"]["policy"] == "lat"
    bad = client.put(
        "/api/v1/clusters/gray-01", headers=_auth(client, "alice"),
        json={"registry": "consul://h:8600", "policy": "least", "note": ""},
    )
    assert bad.status_code == 409 and bad.json()["code"] == "duplicate_registry"


def test_update_unknown_is_404(client, db_session):
    _seed_cluster(db_session)
    response = client.put(
        "/api/v1/clusters/ghost", headers=_auth(client, "alice"),
        json={"registry": "h:8500", "policy": "least", "note": ""},
    )
    assert response.status_code == 404 and response.json()["code"] == "cluster_not_found"


def test_delete_blocked_by_instances_then_ok(client, db_session):
    _seed_cluster(db_session)
    _seed_cluster(db_session, name="gray-01", registry="h:8500")
    inst = ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1, labels_json={},
                         enabled=True, drain_requested=False, cluster_id="gray-01")
    db_session.add(inst)
    db_session.commit()
    blocked = client.delete("/api/v1/clusters/gray-01", headers=_auth(client, "alice"))
    assert blocked.status_code == 409 and blocked.json()["code"] == "cluster_not_empty"
    assert _audit_rows(db_session, "cluster.delete")[0].error_code == "cluster_not_empty"
    db_session.delete(inst)
    db_session.commit()
    done = client.delete("/api/v1/clusters/gray-01", headers=_auth(client, "alice"))
    assert done.status_code == 200
    assert {r.result for r in _audit_rows(db_session, "cluster.delete")} == {"error", "ok"}


def test_delete_last_cluster_is_blocked(client, db_session):
    _seed_cluster(db_session)
    response = client.delete("/api/v1/clusters/default", headers=_auth(client, "alice"))
    assert response.status_code == 409 and response.json()["code"] == "last_cluster"


def test_switch_records_audit_for_existing_and_missing(client, db_session):
    _seed_cluster(db_session)
    headers = _auth(client, "bob")  # operator 也必须能切
    assert client.post("/api/v1/clusters/default/switch", headers=headers).status_code == 200
    missing = client.post("/api/v1/clusters/ghost/switch", headers=headers)
    assert missing.status_code == 404
    rows = _audit_rows(db_session, "cluster.switch")
    assert {r.result for r in rows} == {"ok", "error"}
    assert next(r for r in rows if r.result == "error").error_code == "cluster_not_found"


def test_operator_can_query_switch_but_not_write(client, db_session):
    _seed_cluster(db_session)
    headers = _auth(client, "bob")
    assert client.get("/api/v1/clusters", headers=headers).status_code == 200
    denied = client.post(
        "/api/v1/clusters", headers=headers,
        json={"name": "nope-01", "registry": "h:8500", "policy": "least", "note": ""},
    )
    assert denied.status_code == 403 and denied.json()["code"] == "forbidden"


def test_client_role_cannot_even_query(client, db_session):
    _seed_cluster(db_session)
    assert client.get("/api/v1/clusters", headers=_auth(client, "carol")).status_code == 403


def test_unauthenticated_is_401_and_no_audit(client, db_session):
    _seed_cluster(db_session)
    assert client.get("/api/v1/clusters").status_code == 401
    assert client.post("/api/v1/clusters/default/switch").status_code == 401
    assert _audit_rows(db_session, "cluster.switch") == []  # 401 发生在解析操作人之前（spec §4.3）


def test_events_returns_latest_cluster_actions(client, db_session):
    _seed_cluster(db_session)
    for i in range(5):
        client.post(
            "/api/v1/clusters", headers=_auth(client, "alice"),
            json={"name": f"c{i:02d}", "registry": f"h{i}:8500", "policy": "least", "note": ""},
        )
    data = client.get("/api/v1/clusters/events?limit=4", headers=_auth(client, "bob")).json()["data"]
    assert len(data) == 4
    assert all(row["action"].startswith("cluster.") for row in data)
    assert {"at", "actor", "role", "action", "result", "errorCode", "profile"} <= set(data[0])
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/integration/test_clusters_api.py -v`
Expected: FAIL —— 404（路由未注册）/`AttributeError: list_prefix`。

- [ ] **Step 3: schemas**

Create `console/backend/app/schemas/cluster.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ClusterCreate(BaseModel):
    """字段一律无 pydantic 约束：校验链在 cluster_service，失败才能被路由体的
    try/except 捕获并审计（RequestValidationError 不进路由体，spec §4.3）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    registry: str
    policy: str
    note: str = ""


class ClusterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry: str
    policy: str
    note: str = ""
```

- [ ] **Step 4: AuditRepository.list_prefix**

Modify `console/backend/app/repositories/audit_repository.py`，在 `list()` 之后追加：

```python
    def list_prefix(self, action_prefix: str, *, limit: int = 4) -> list[ParamAudit]:
        """按 action 前缀取最新行（集群总览「最近事件」卡，spec §5.2-5）。
        LIKE 前缀匹配 + 参数绑定，转义交驱动。"""
        stmt = (
            select(ParamAudit)
            .where(ParamAudit.action.like(f"{action_prefix}%"))
            .order_by(ParamAudit.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
```

- [ ] **Step 5: cluster_service 追加 host 派生**

Modify `console/backend/app/services/cluster_service.py`，顶部 import 补：

```python
from urllib.parse import urlparse

from app.services import instance_monitor
```

文件末尾追加：

```python
def _host_of(base_url: str) -> str:
    try:
        return urlparse(base_url).hostname or base_url
    except ValueError:
        return base_url


def instance_host_stats(db, cluster_name: str) -> dict:
    """该集群的机器/实例计数（spec §4.2）：机器 = base_url host 去重；
    machines_online = 至少有一个 online 实例的 host 数（实时状态取 instance_monitor 快照）。"""
    rows = [r for r in InstanceRepository(db).list_all() if r.cluster_id == cluster_name]
    hosts = {_host_of(r.base_url) for r in rows}
    view = instance_monitor.snapshot()
    online_hosts = {
        _host_of(r.base_url)
        for r in rows
        if (state := view.get(r.instance_id)) is not None and state.status == "online"
    }
    return {
        "machines_total": len(hosts),
        "machines_online": len(online_hosts),
        "instances_total": len(rows),
    }
```

- [ ] **Step 6: 路由**

Create `console/backend/app/routers/clusters.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.repositories.audit_repository import AuditRepository
from app.repositories.cluster_repository import ClusterRepository
from app.schemas.cluster import ClusterCreate, ClusterUpdate
from app.schemas.common import iso_utc, ok
from app.services import cluster_service

router = APIRouter(prefix="/api/v1", tags=["clusters"])


def _request_id(request: Request) -> str:
    # 与 routers/instances.py 同一条路径：RequestIdMiddleware 已写入 request.state。
    return getattr(request.state, "request_id", "")


def _audited(db, user, action: str, name: str, fields: list[str], request_id: str, fn):
    """成功记 ok、ApiError 记 error 后原样重抛（spec §4.3：失败也要记录）。
    401 到不了这里——require_permission 在解析操作人之前就拒绝了。"""
    try:
        result = fn()
    except ApiError as exc:
        AuditRepository(db).record(
            actor=user.username, role=user.role, action=action, profile=name,
            fields=list(fields), result="error", error_code=exc.code, request_id=request_id,
        )
        raise
    AuditRepository(db).record(
        actor=user.username, role=user.role, action=action, profile=name,
        fields=list(fields), request_id=request_id,
    )
    return result


def _row_payload(db, cluster) -> dict:
    stats = cluster_service.instance_host_stats(db, cluster.name)
    return {
        "name": cluster.name,
        "registry": cluster.registry,
        "policy": cluster.policy,
        "note": cluster.note,
        "machines_total": stats["machines_total"],
        "machines_online": stats["machines_online"],
        "instances_total": stats["instances_total"],
        "healthy": stats["machines_online"] > 0,
        "updated_at": iso_utc(cluster.updated_at),
        "updated_by": cluster.updated_by,
    }


@router.get("/clusters")
def list_clusters(db: DbSession, user: CurrentUser = Depends(require_permission("console:cluster:query"))):
    return ok([_row_payload(db, cluster) for cluster in ClusterRepository(db).list_all()])


@router.get("/clusters/events")
def cluster_events(
    db: DbSession,
    limit: int = 4,
    user: CurrentUser = Depends(require_permission("console:cluster:query")),
):
    """最近集群审计事件（spec §5.2-5）：复用 param_audit，action 前缀 'cluster.'。"""
    limit = max(1, min(int(limit), 20))
    rows = AuditRepository(db).list_prefix("cluster.", limit=limit)
    return ok([
        {
            "auditId": str(row.id),
            "at": iso_utc(row.at),
            "actor": row.actor,
            "role": row.role,
            "action": row.action,
            "profile": row.profile,  # 存的是集群名
            "fields": list(row.fields or []),
            "result": row.result,
            "errorCode": row.error_code,
        }
        for row in rows
    ])


@router.get("/clusters/{name}")
def get_one_cluster(name: str, db: DbSession, user: CurrentUser = Depends(require_permission("console:cluster:query"))):
    return ok(_row_payload(db, cluster_service.get_cluster(db, name)))


@router.post("/clusters")
def create_cluster(
    payload: ClusterCreate,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_permission("console:cluster:create")),
):
    row = _audited(
        db, user, "cluster.create", payload.name, ["name", "registry", "policy", "note"], _request_id(request),
        lambda: cluster_service.create_cluster(
            db, name=payload.name, registry=payload.registry, policy=payload.policy,
            note=payload.note, actor=user.username,
        ),
    )
    return ok(_row_payload(db, row))


@router.put("/clusters/{name}")
def update_cluster(
    name: str,
    payload: ClusterUpdate,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_permission("console:cluster:update")),
):
    row = _audited(
        db, user, "cluster.update", name, ["registry", "policy", "note"], _request_id(request),
        lambda: cluster_service.update_cluster(
            db, name=name, registry=payload.registry, policy=payload.policy, note=payload.note, actor=user.username
        ),
    )
    return ok(_row_payload(db, row))


@router.delete("/clusters/{name}")
def delete_cluster(
    name: str,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_permission("console:cluster:delete")),
):
    _audited(
        db, user, "cluster.delete", name, [], _request_id(request),
        lambda: cluster_service.delete_cluster(db, name=name, actor=user.username),
    )
    return ok({"name": name, "deleted": True})


@router.post("/clusters/{name}/switch")
def switch_cluster(
    name: str,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_permission("console:cluster:switch")),
):
    # 只校验存在 + 审计留痕，无 DB 状态变更；当前集群持久在前端 sessionStorage（spec §5.1）。
    def _check_exists():
        if not cluster_service.exists(db, name):
            raise ApiError("cluster_not_found", f"cluster {name} does not exist", 404)
        return True

    _audited(db, user, "cluster.switch", name, [], _request_id(request), _check_exists)
    return ok({"name": name, "switched": True})
```

- [ ] **Step 7: 注册路由**

Modify `console/backend/app/core/router_registry.py`：import 列表加 `clusters`（字母序，`auth` 之后、`health` 之前），`app.include_router(instances.router)`（33 行）之后加 `app.include_router(clusters.router)`（spec §4：紧随 instances）。

- [ ] **Step 8: 运行确认通过**

Run: `pytest tests/integration/test_clusters_api.py -v` → 全绿。
Run: `pytest tests/unit tests/integration -x -q` → 存量不回归。

- [ ] **Step 9: Commit**

```bash
git add console/backend/app/schemas/cluster.py console/backend/app/routers/clusters.py console/backend/app/core/router_registry.py console/backend/app/repositories/audit_repository.py console/backend/app/services/cluster_service.py console/backend/tests/integration/test_clusters_api.py
git commit -m "feat(backend): add /clusters CRUD+switch+events with audited failure path"
```

---

### Task 5: `/instances` 扩展——cluster 过滤 + summary 派生字段（错误率）

**Files:**
- Modify: `console/backend/app/services/instances_service.py`
- Modify: `console/backend/app/routers/instances.py`
- Modify: `console/backend/app/repositories/instance_metric_repository.py`
- Test: `console/backend/tests/integration/test_instances_cluster.py`

**Interfaces:**
- Consumes: `ParamInstance.cluster_id`（Task 1）、`instance_monitor.snapshot()`、`ParamInstanceMetric` 计数器
- Produces:
  - `GET /api/v1/instances` 新可选 query `cluster`；registry 路径 `summary` 新键 `machines_total: int`、`machines_online: int`、`error_rate_5m: float | None`、`top_error_instance: str | None`
  - `instances_service.collect(profile, version, *, db, cluster=None)`（新关键字参，既有调用零改动）
  - `InstanceMetricRepository.alloc_window_by_cluster(cluster_id, *, since) -> list[dict]`
  - `instances_service.host_of(base_url) -> str`、`derive_machine_counts(rows, status_lookup) -> tuple[int,int]`、`ERROR_RATE_WINDOW_S = 300`

- [ ] **Step 1: 写失败测试**

Create `console/backend/tests/integration/test_instances_cluster.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.models.param_cluster import ParamCluster
from app.models.param_instance import ParamInstance
from app.models.param_instance_metric import ParamInstanceMetric
from app.repositories.user_repository import UserRepository
from app.services import instance_monitor, process_probe
from app.services.auth_service import hash_password
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


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
    process_probe.set_probe(process_probe.NullProbe("test"))
    yield TestClient(app)
    process_probe.set_probe(None)
    instance_monitor.reset_for_tests()


def _auth(client):
    tokens = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _seed_registry(db):
    db.add(ParamCluster(name="default"))
    db.add(ParamCluster(name="gray-01", registry="h:8500"))
    db.add(ParamInstance(instance_id="pipe-a", base_url="http://host1:8765", weight=1, labels_json={},
                         enabled=True, drain_requested=False, cluster_id="default"))
    db.add(ParamInstance(instance_id="pipe-b", base_url="http://host2:8765", weight=1, labels_json={},
                         enabled=True, drain_requested=False, cluster_id="gray-01"))
    db.commit()
    for iid, url in (("pipe-a", "http://host1:8765"), ("pipe-b", "http://host2:8765")):
        instance_monitor.registry._states[iid] = RuntimeState(instance_id=iid, base_url=url)
        instance_monitor.registry.observe_success(iid, PoolState(reachable=True, size=2, in_use=1, units=()), 10)


def test_no_cluster_param_keeps_legacy_shape(client, db_session):
    # 存量红线：注册表为空 + 不带参数 → 与改造前逐字段一致（不含 summary/新键）
    data = client.get("/api/v1/instances", headers=_auth(client)).json()["data"]
    assert "summary" not in data
    assert data["pool"] is None


def test_cluster_filter_selects_rows_and_machines(client, db_session):
    _seed_registry(db_session)
    data = client.get("/api/v1/instances", params={"cluster": "gray-01"}, headers=_auth(client)).json()["data"]
    assert [r["instance_id"] for r in data["instances"]] == ["pipe-b"]
    assert data["summary"]["instances_total"] == 1
    assert data["summary"]["machines_total"] == 1
    assert data["summary"]["machines_online"] == 1


def test_summary_without_cluster_counts_all_hosts_deduped(client, db_session):
    _seed_registry(db_session)
    db_session.add(ParamInstance(instance_id="pipe-c", base_url="http://host1:9999", weight=1, labels_json={},
                                 enabled=True, drain_requested=False, cluster_id="gray-01"))
    db_session.commit()
    data = client.get("/api/v1/instances", headers=_auth(client)).json()["data"]
    # host1 两个实例（不同端口）= 同一台机器
    assert data["summary"]["machines_total"] == 2
    assert data["summary"]["instances_total"] == 3


def test_error_rate_derived_from_deltas(client, db_session):
    _seed_registry(db_session)
    db_session.add_all([
        # gray-01 窗口内：2 成功、1 个 503、1 个 no_instance → rate = 2/4 = 0.5
        ParamInstanceMetric(instance_id="pipe-b", observed_by="c1", kind="sample", status="online",
                            alloc_ok=2, alloc_fail_instance_503=1, alloc_fail_no_instance=1),
        # default 窗口内的样本不得泄漏进 gray-01 的口径
        ParamInstanceMetric(instance_id="pipe-a", observed_by="c1", kind="sample", status="online",
                            alloc_fail_instance_503=9),
    ])
    db_session.commit()
    data = client.get("/api/v1/instances", params={"cluster": "gray-01"}, headers=_auth(client)).json()["data"]
    assert data["summary"]["error_rate_5m"] == pytest.approx(0.5)
    assert data["summary"]["top_error_instance"] == "pipe-b"


def test_error_rate_null_when_no_samples(client, db_session):
    _seed_registry(db_session)
    data = client.get("/api/v1/instances", params={"cluster": "gray-01"}, headers=_auth(client)).json()["data"]
    # 无样本 = null，绝不 0（需求确认点 4）
    assert data["summary"]["error_rate_5m"] is None
    assert data["summary"]["top_error_instance"] is None


def test_top_error_instance_tie_breaks_lexicographically(client, db_session):
    _seed_registry(db_session)
    db_session.add(ParamInstance(instance_id="pipe-b2", base_url="http://host3:8765", weight=1, labels_json={},
                                 enabled=True, drain_requested=False, cluster_id="gray-01"))
    db_session.add_all([
        ParamInstanceMetric(instance_id="pipe-b", observed_by="c1", kind="sample", status="online", alloc_fail_instance_503=3),
        ParamInstanceMetric(instance_id="pipe-b2", observed_by="c1", kind="sample", status="online", alloc_fail_instance_503=3),
    ])
    db_session.commit()
    data = client.get("/api/v1/instances", params={"cluster": "gray-01"}, headers=_auth(client)).json()["data"]
    assert data["summary"]["top_error_instance"] == "pipe-b"  # 并列取字典序最小
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/integration/test_instances_cluster.py -v`
Expected: FAIL —— 未知 query 被忽略 / summary 缺新键 / `AttributeError: alloc_window_by_cluster`。

- [ ] **Step 3: 指标仓储聚合**

Modify `console/backend/app/repositories/instance_metric_repository.py`：import 补 `from app.models.param_instance import ParamInstance`，类末尾追加：

```python
    def alloc_window_by_cluster(self, cluster_id: str | None, *, since: datetime) -> list[dict]:
        """窗口内按实例聚合的分配计数器（增量行求和，spec §4.4 前提：metric 落的是
        采样 tick 间 delta，非累计值，窗口求和成立）。cluster_id=None = 全部集群。"""
        stmt = (
            select(
                ParamInstanceMetric.instance_id,
                func.sum(ParamInstanceMetric.alloc_ok).label("ok"),
                func.sum(ParamInstanceMetric.alloc_fail_instance_503).label("fail_503"),
                func.sum(ParamInstanceMetric.alloc_fail_no_instance).label("fail_none"),
            )
            .where(ParamInstanceMetric.observed_at >= since, ParamInstanceMetric.kind == "sample")
            .group_by(ParamInstanceMetric.instance_id)
        )
        if cluster_id is not None:
            stmt = stmt.join(
                ParamInstance, ParamInstance.instance_id == ParamInstanceMetric.instance_id
            ).where(ParamInstance.cluster_id == cluster_id)
        return [
            {
                "instance_id": r.instance_id,
                "ok": int(r.ok or 0),
                "fail_503": int(r.fail_503 or 0),
                "fail_none": int(r.fail_none or 0),
            }
            for r in self.session.execute(stmt)
        ]
```

- [ ] **Step 4: service 派生**

Modify `console/backend/app/services/instances_service.py`：import 区补：

```python
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from app.repositories.instance_metric_repository import InstanceMetricRepository
```

模块级新增（放在 `collect` 之前）：

```python
# spec §4.4：窗口分母为 0 → null，绝不 0（需求确认点 4）。
ERROR_RATE_WINDOW_S = 300


def host_of(base_url: str) -> str:
    """机器身份 = base_url 的 host（不含端口，spec §2.2）。解析失败退回原串。"""
    try:
        return urlparse(base_url).hostname or base_url
    except ValueError:
        return base_url


def derive_machine_counts(rows: list, status_lookup) -> tuple[int, int]:
    """(machines_total, machines_online)：host 去重；在线 = 该 host 至少有一个 online 实例。
    /clusters 聚合与本文件 summary 共用，防口径漂移（spec §4.2）。"""
    hosts = {host_of(row.base_url) for row in rows}
    online_hosts = {
        host_of(row.base_url)
        for row in rows
        if (state := status_lookup(row.instance_id)) is not None and state.status == "online"
    }
    return len(hosts), len(online_hosts)


def _error_fields(db, cluster: str | None) -> dict:
    since = datetime.now(UTC) - timedelta(seconds=ERROR_RATE_WINDOW_S)
    per_instance = InstanceMetricRepository(db).alloc_window_by_cluster(cluster, since=since)
    ok_total = sum(r["ok"] for r in per_instance)
    fail_503 = sum(r["fail_503"] for r in per_instance)
    fail_none = sum(r["fail_none"] for r in per_instance)
    # 一次分配尝试恰好落入三类计数器之一（allocator 每次只 bump 其一）——两类失败不重复计数。
    denominator = ok_total + fail_503 + fail_none
    rate = None if denominator == 0 else round((fail_503 + fail_none) / denominator, 4)
    failures = [(r["instance_id"], r["fail_503"] + r["fail_none"]) for r in per_instance]
    # 并列取 instance_id 字典序最小（确定性）：先按 -失败数、再按 id 升序。
    top = min((t for t in failures if t[1] > 0), key=lambda t: (-t[1], t[0]), default=None)
    return {"error_rate_5m": rate, "top_error_instance": top[0] if top else None}
```

`collect` 改签名并透传 cluster：

```python
def collect(profile: str, version: int | None, *, db, cluster: str | None = None) -> dict:
    rows = InstanceRepository(db).list_all()
    if rows and cluster is not None:
        # 缺省 = 全部行（现状不变）；给定 = 过滤 cluster_id（spec §4.4）。
        rows = [row for row in rows if row.cluster_id == cluster]
    if rows:
        return _collect_registry(profile, version, rows, db=db, cluster=cluster)
    return _collect_legacy(profile, version)
```

`_collect_registry` 签名改 `(profile, version, rows, *, db, cluster)`，在既有 `summary` dict 定义之后、`return` 之前合并新键：

```python
    machines_total, machines_online = derive_machine_counts(rows, view.get)
    summary.update({"machines_total": machines_total, "machines_online": machines_online})
    summary.update(_error_fields(db, cluster))
```

（`view` 是函数内既有的 `instance_monitor.snapshot()`；legacy 路径不含这些键——legacy 响应形状逐字节不变，spec §4.4。）

- [ ] **Step 5: 路由透传**

Modify `console/backend/app/routers/instances.py` 的 `get_instances`：

```python
@router.get("/instances")
def get_instances(
    db: DbSession,
    profile: str = "prod",
    cluster: str | None = None,
    user: CurrentUser = Depends(require_user),
):
    """A.10: a degraded read is still a 200. cluster 缺省 = 全部行（现状不变）。"""
    latest = VersionRepository(db).latest_live(profile)
    return ok(instances_service.collect(profile, int(latest.version) if latest else None, db=db, cluster=cluster))
```

同任务把 Task 4 的 `cluster_service.instance_host_stats` 改用共享派生（防口径漂移，行为不变，Task 4 测试必须仍绿）：

```python
# cluster_service.instance_host_stats 内：
from app.services import instances_service

rows = [r for r in InstanceRepository(db).list_all() if r.cluster_id == cluster_name]
view = instance_monitor.snapshot()
machines_total, machines_online = instances_service.derive_machine_counts(rows, view.get)
return {"machines_total": machines_total, "machines_online": machines_online, "instances_total": len(rows)}
```

- [ ] **Step 6: 运行确认通过**

Run: `pytest tests/integration/test_instances_cluster.py tests/integration/test_instances.py tests/integration/test_clusters_api.py -v` → 全绿（旧 instances 测试是存量红线）。
Run: `pytest tests/unit tests/integration -x -q` → 全绿。

- [ ] **Step 7: Commit**

```bash
git add console/backend
git commit -m "feat(backend): add cluster filter to /instances with machine and error-rate derived summary"
```

---

### Task 6: 前端基建——`api.put`、集群 API 封装、类型扩展、storage 集群键

**Files:**
- Modify: `console/frontend/src/api/client.ts:101-108`（`api` 对象补 `put`）
- Create: `console/frontend/src/api/clusters.ts`
- Modify: `console/frontend/src/types/api.d.ts`（新增 `ClusterRow`/`ClusterEventRow`/`ClusterWritePayload`；`InstancesSummary` 加派生键）
- Modify: `console/frontend/src/utils/storage.ts:5-7`（新增 `CLUSTER_KEY` 读写）
- Test: `console/frontend/src/api/clusters.spec.ts`

**Interfaces:**
- Consumes: Task 4 的 REST 形状——`GET /clusters` 行 `{name,registry,policy,note,machines_total,machines_online,instances_total,healthy,updated_at,updated_by}`；`GET /clusters/events` 行 `{auditId,at,actor,role,action,profile,fields,result,errorCode}`；Task 5 的 summary 新键 `machines_total/machines_online/error_rate_5m/top_error_instance`。
- Produces:
  - `api.put<T>(url, body?, config?)`（与 get/post/delete 同信封解包）
  - `clustersApi.list() / events(limit) / create(payload) / update(name, payload) / remove(name) / switchTo(name)`
  - `readCluster(): string` / `saveCluster(name: string)`，sessionStorage 键 `s2s.console.cluster`，缺省 `'default'`（与 `readProfile` 同约定，见 storage.ts 头注释）
  - TS 类型 `ClusterRow`、`ClusterEventRow`、`ClusterWritePayload`

- [ ] **Step 1: 写失败测试**

Create `console/frontend/src/api/clusters.spec.ts`（仓库惯例：spec 与源文件同目录，vi.mock 打桩 `@/api/client`）：

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls = vi.hoisted(() => [] as Array<{ verb: string; url: string; rest: unknown[] }>)

vi.mock('@/api/client', () => {
  const record = (verb: string) => (url: string, ...rest: unknown[]) => {
    calls.push({ verb, url, rest })
    return Promise.resolve('ok' as never)
  }
  return { api: { get: record('get'), post: record('post'), put: record('put'), delete: record('delete') } }
})

import { clustersApi } from './clusters'

describe('clustersApi', () => {
  beforeEach(() => {
    calls.length = 0
  })

  it('maps every verb onto the /clusters routes the backend exposes', async () => {
    await clustersApi.list()
    await clustersApi.events(4)
    await clustersApi.create({ name: 'gray-01', registry: 'h:8500', policy: 'rr', note: '' })
    await clustersApi.update('gray-01', { registry: 'h:8600', policy: 'lat', note: 'x' })
    await clustersApi.remove('gray-01')
    await clustersApi.switchTo('gray-01')

    expect(calls.map((c) => c.verb)).toEqual(['get', 'get', 'post', 'put', 'delete', 'post'])
    expect(calls[0].url).toBe('/clusters')
    expect(calls[1].url).toBe('/clusters/events')
    expect(calls[1].rest[0]).toEqual({ params: { limit: 4 } })
    expect(calls[3].url).toBe('/clusters/gray-01')
    expect(calls[4].url).toBe('/clusters/gray-01')
    expect(calls[5].url).toBe('/clusters/gray-01/switch')
  })

  it('url-encodes cluster names', async () => {
    await clustersApi.remove('a/b')
    expect(calls[0].url).toBe('/clusters/a%2Fb')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd console/frontend; npx vitest run src/api/clusters.spec.ts`
Expected: FAIL —— `Failed to resolve import './clusters'`（或等价的模块不存在报错）。

- [ ] **Step 3: `api` 对象补 `put`**

Modify `console/frontend/src/api/client.ts`，在 `post` 与 `delete` 之间插入：

```typescript
  put: <T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> =>
    request<T>({ ...config, url, method: 'put', data: body }),
```

- [ ] **Step 4: 集群 API 封装 + 类型 + storage 键**

Create `console/frontend/src/api/clusters.ts`:

```typescript
import { api } from '@/api/client'
import type { ClusterEventRow, ClusterRow, ClusterWritePayload } from '@/types/api'

/** `/api/v1/clusters` 的唯一前端出入口（spec §4）；信封解包由 api/client 完成。 */
const path = (name: string) => `/clusters/${encodeURIComponent(name)}`

export const clustersApi = {
  list: (): Promise<ClusterRow[]> => api.get<ClusterRow[]>('/clusters'),
  events: (limit = 4): Promise<ClusterEventRow[]> =>
    api.get<ClusterEventRow[]>('/clusters/events', { params: { limit } }),
  create: (payload: ClusterWritePayload): Promise<ClusterRow> => api.post<ClusterRow>('/clusters', payload),
  update: (name: string, payload: Omit<ClusterWritePayload, 'name'>): Promise<ClusterRow> =>
    api.put<ClusterRow>(path(name), payload),
  remove: (name: string): Promise<{ name: string; deleted: boolean }> =>
    api.delete<{ name: string; deleted: boolean }>(path(name)),
  switchTo: (name: string): Promise<{ name: string; switched: boolean }> =>
    api.post<{ name: string; switched: boolean }>(`${path(name)}/switch`)
}
```

Modify `console/frontend/src/types/api.d.ts`——文件末尾追加（snake_case 字段名与后端 Task 4 `_row_payload` 逐字一致）：

```typescript
/** 集群行：字段名与后端 routers/clusters.py `_row_payload` 逐字一致。 */
export interface ClusterRow {
  name: string
  registry: string
  policy: 'least' | 'rr' | 'lat'
  note: string
  machines_total: number
  machines_online: number
  instances_total: number
  healthy: boolean
  updated_at: string
  updated_by: string
}

/** 集群写载荷：POST 全量、PUT 不含 name（name 在路径上）。 */
export interface ClusterWritePayload {
  name: string
  registry: string
  policy: string
  note: string
}

/** 最近事件行：字段名与后端 `/clusters/events` 逐字一致（camelCase）。 */
export interface ClusterEventRow {
  auditId: string
  at: string
  actor: string
  role: string
  action: string
  profile: string
  fields: string[]
  result: 'ok' | 'error'
  errorCode: string
}
```

并给 `InstancesSummary`（L108-118）追加可选派生键（legacy 直连路径不返回，故可选）：

```typescript
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
  // Task 5 派生键：legacy 路径不返回，必须保持可选。
  machines_total?: number
  machines_online?: number
  error_rate_5m?: number | null
  top_error_instance?: string | null
}
```

Modify `console/frontend/src/utils/storage.ts`——常量区加 `const CLUSTER_KEY = 's2s.console.cluster'`，`DEFAULT_PROFILE` 旁加 `export const DEFAULT_CLUSTER = 'default'`，文件末尾追加（沿用头注释里的 sessionStorage 口径）：

```typescript
/** 当前集群：与 profile 同存 sessionStorage，关标签页即回缺省（spec §5.1）。 */
export function readCluster(): string {
  return sessionStorage.getItem(CLUSTER_KEY) || DEFAULT_CLUSTER
}

export function saveCluster(cluster: string): void {
  sessionStorage.setItem(CLUSTER_KEY, cluster)
}
```

- [ ] **Step 5: 运行确认通过**

Run: `cd console/frontend; npx vitest run src/api/clusters.spec.ts` → PASS。
Run: `npx vue-tsc --noEmit` → 无类型错误。

- [ ] **Step 6: Commit**

```bash
git add console/frontend/src/api/client.ts console/frontend/src/api/clusters.ts console/frontend/src/api/clusters.spec.ts console/frontend/src/types/api.d.ts console/frontend/src/utils/storage.ts
git commit -m "feat(frontend): add clusters api wrapper, cluster types and sessionStorage cluster key"
```

---

### Task 7: 集群 store + 权限码镜像 + `auth.hasPermission`

**Files:**
- Create: `console/frontend/src/stores/cluster.ts`
- Create: `console/frontend/src/utils/permissions.ts`
- Modify: `console/frontend/src/stores/auth.ts:8-26`
- Test: `console/frontend/src/stores/cluster.spec.ts`
- Test: `console/frontend/src/utils/permissions.spec.ts`

**Interfaces:**
- Consumes: `clustersApi`（Task 6）、`readCluster/saveCluster`（Task 6）、后端 Task 2 的 `PERMISSION_ROLES` 语义。
- Produces:
  - `useClusterStore()`：`rows: Ref<ClusterRow[]>`、`current: Ref<string>`、`currentRow: ComputedRef<ClusterRow | null>`、`error: Ref<AppError | null>`、`load()`（并发去重）、`select(name)`、`switchTo(name): Promise<boolean>`、`remove(name)`
  - `PERMISSION_ROLES: Record<string, readonly string[]>`（后端 `app/core/permissions.py` 的前端镜像）与 `roleHasPermission(role, code): boolean`
  - `useAuthStore().hasPermission(code): boolean`

- [ ] **Step 1: 写失败测试（权限镜像）**

Create `console/frontend/src/utils/permissions.spec.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import { PERMISSION_ROLES, roleHasPermission } from './permissions'

describe('permission mirror', () => {
  it('mirrors the backend matrix: operator may query+switch but not write', () => {
    expect(roleHasPermission('operator', 'console:cluster:query')).toBe(true)
    expect(roleHasPermission('operator', 'console:cluster:switch')).toBe(true)
    expect(roleHasPermission('operator', 'console:cluster:create')).toBe(false)
    expect(roleHasPermission('admin', 'console:cluster:delete')).toBe(true)
    expect(roleHasPermission('viewer', 'console:cluster:query')).toBe(false)
  })

  it('unknown codes and roles fail closed', () => {
    expect(roleHasPermission('admin', 'console:nonexistent')).toBe(false)
    expect(roleHasPermission('', 'console:cluster:query')).toBe(false)
  })

  it('covers exactly the five cluster codes the backend registers', () => {
    expect(Object.keys(PERMISSION_ROLES).sort()).toEqual([
      'console:cluster:create',
      'console:cluster:delete',
      'console:cluster:query',
      'console:cluster:switch',
      'console:cluster:update'
    ])
  })
})
```

- [ ] **Step 2: 运行确认失败 → 实现权限镜像**

Run: `cd console/frontend; npx vitest run src/utils/permissions.spec.ts` → FAIL（模块不存在）。

Create `console/frontend/src/utils/permissions.ts`:

```typescript
/**
 * 后端 `app/core/permissions.py` 的 PERMISSION_ROLES 镜像（spec §4.4）。
 * 仅供前端少摆按钮；服务端每个端点仍独立校验，这里不是安全边界。
 * 改后端矩阵必须同步改这里，permissions.spec.ts 会拦住漂移。
 */
export const PERMISSION_ROLES: Record<string, readonly string[]> = {
  'console:cluster:query': ['admin', 'operator'],
  'console:cluster:switch': ['admin', 'operator'],
  'console:cluster:create': ['admin'],
  'console:cluster:update': ['admin'],
  'console:cluster:delete': ['admin']
}

export function roleHasPermission(role: string, code: string): boolean {
  return PERMISSION_ROLES[code]?.includes(role) ?? false
}
```

Run: `npx vitest run src/utils/permissions.spec.ts` → PASS。

- [ ] **Step 3: `auth.hasPermission`**

Modify `console/frontend/src/stores/auth.ts`——import 区加 `import { roleHasPermission } from '@/utils/permissions'`；`isAdmin` 下方加：

```typescript
  /** 少摆按钮用；真正的门禁在服务端（utils/permissions 镜像）。 */
  function hasPermission(code: string): boolean {
    return roleHasPermission(user.value?.role ?? '', code)
  }
```

return 语句改为 `return { bundle, user, signedIn, isAdmin, hasPermission, login, logout }`。

- [ ] **Step 4: 写失败测试（集群 store）**

Create `console/frontend/src/stores/cluster.spec.ts`（mock 掉 `@/utils/storage` 以免依赖 jsdom 的 sessionStorage，与 stores/locale.spec.ts 的 createPinia 写法一致）：

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  list: vi.fn(),
  events: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  switchTo: vi.fn()
}))

vi.mock('@/api/clusters', () => ({ clustersApi: apiMock }))
vi.mock('@/utils/storage', () => {
  const bag = new Map<string, string>()
  return {
    readCluster: () => bag.get('cluster') ?? 'default',
    saveCluster: (v: string) => void bag.set('cluster', v)
  }
})

import { AppError } from '@/api/client'
import { useClusterStore } from './cluster'
import type { ClusterRow } from '@/types/api'

const row = (name: string): ClusterRow => ({
  name,
  registry: 'consul://h:8500',
  policy: 'least',
  note: '',
  machines_total: 2,
  machines_online: 2,
  instances_total: 4,
  healthy: true,
  updated_at: '2026-11-05T00:00:00+00:00',
  updated_by: 'alice'
})

describe('cluster store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('keeps a stored current cluster when it still exists', async () => {
    apiMock.list.mockResolvedValue([row('default'), row('gray-01')])
    const store = useClusterStore()
    await store.load()
    expect(store.current).toBe('default')
  })

  it('falls back to the first cluster when the stored one is stale', async () => {
    apiMock.list.mockResolvedValue([row('gray-01'), row('default')])
    const store = useClusterStore()
    store.current = 'ghost-99'
    await store.load()
    expect(store.current).toBe('gray-01')
  })

  it('dedupes concurrent loads into one request', async () => {
    let resolve!: (rows: ClusterRow[]) => void
    apiMock.list.mockReturnValue(new Promise((r) => { resolve = r }))
    const store = useClusterStore()
    const first = store.load()
    const second = store.load()
    resolve([row('default')])
    await Promise.all([first, second])
    expect(apiMock.list).toHaveBeenCalledTimes(1)
  })

  it('does not switch when the server rejects (audit recorded error)', async () => {
    apiMock.switchTo.mockRejectedValue(new AppError('cluster_not_found', 'missing'))
    const store = useClusterStore()
    const ok = await store.switchTo('ghost')
    expect(ok).toBe(false)
    expect(store.current).toBe('default')
    expect(store.error?.code).toBe('cluster_not_found')
  })

  it('reloads the list after remove so a deleted current falls back', async () => {
    apiMock.list.mockResolvedValue([row('default')])
    apiMock.remove.mockResolvedValue({ name: 'gray-01', deleted: true })
    const store = useClusterStore()
    await store.load()
    store.current = 'default'
    await store.remove('default')
    expect(apiMock.list).toHaveBeenCalledTimes(2)
  })
})
```

- [ ] **Step 5: 运行确认失败 → 实现集群 store**

Run: `cd console/frontend; npx vitest run src/stores/cluster.spec.ts` → FAIL（模块不存在）。

Create `console/frontend/src/stores/cluster.ts`:

```typescript
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { AppError } from '@/api/client'
import { clustersApi } from '@/api/clusters'
import type { ClusterRow } from '@/types/api'
import { readCluster, saveCluster } from '@/utils/storage'

/**
 * 当前集群是纯前端视图态（spec §5.1）：持久在 sessionStorage，切换动作走
 * `POST /clusters/{name}/switch` 只留审计。失败（含审计失败）不切换。
 */
export const useClusterStore = defineStore('cluster', () => {
  const rows = ref<ClusterRow[]>([])
  const current = ref(readCluster())
  const error = ref<AppError | null>(null)
  const currentRow = computed(() => rows.value.find((row) => row.name === current.value) ?? null)
  let inFlight: Promise<void> | null = null

  function select(name: string): void {
    current.value = name
    saveCluster(name)
  }

  /** 存量视图里找不到保存的当前集群（改名/删除/换标签页数据漂移）→ 回落第一个。 */
  function syncCurrent(): void {
    if (!rows.value.length) return
    if (!rows.value.some((row) => row.name === current.value)) select(rows.value[0].name)
  }

  async function load(): Promise<void> {
    if (inFlight) return inFlight
    inFlight = (async () => {
      try {
        rows.value = await clustersApi.list()
        error.value = null
        syncCurrent()
      } catch (caught) {
        error.value = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
      } finally {
        inFlight = null
      }
    })()
    return inFlight
  }

  async function switchTo(name: string): Promise<boolean> {
    try {
      await clustersApi.switchTo(name)
      select(name)
      return true
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
      return false
    }
  }

  async function remove(name: string): Promise<void> {
    await clustersApi.remove(name)
    await load()
  }

  return { rows, current, currentRow, error, load, select, switchTo, remove }
})
```

- [ ] **Step 6: 运行确认通过**

Run: `cd console/frontend; npx vitest run src/stores/cluster.spec.ts src/utils/permissions.spec.ts` → 全绿。
Run: `npx vue-tsc --noEmit` → 无类型错误。

- [ ] **Step 7: Commit**

```bash
git add console/frontend/src/stores/cluster.ts console/frontend/src/stores/cluster.spec.ts console/frontend/src/stores/auth.ts console/frontend/src/utils/permissions.ts console/frontend/src/utils/permissions.spec.ts
git commit -m "feat(frontend): add cluster store with stale fallback and permission-code mirror"
```

---

### Task 8: 集群表单校验 `clusterForm.ts` + `ClusterFormModal.vue`

**Files:**
- Create: `console/frontend/src/utils/clusterForm.ts`
- Create: `console/frontend/src/components/ClusterFormModal.vue`
- Modify: `console/frontend/src/styles/tokens.ts:53-60`（ratchet 加入 Modal）
- Test: `console/frontend/src/utils/clusterForm.spec.ts`

**Interfaces:**
- Consumes: `clustersApi`（Task 6）、Task 10 将新增的 `overview.form.*` / `overview.policy.*` / `errors.*` i18n 键（本任务先引用，Task 10 落键；vue-i18n 缺键会回显键名，不影响类型/构建）。
- Produces:
  - `NAME_RE`、`REGISTRY_RE`、`POLICIES`、`validateClusterForm(values, editing?) : ClusterFormErrors`（值 = i18n 键）
  - 组件 `ClusterFormModal`：props `{ open: boolean; cluster: ClusterRow | null }`，emits `update:open` / `saved(ClusterRow)`

- [ ] **Step 1: 写失败测试**

Create `console/frontend/src/utils/clusterForm.spec.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import { REGISTRY_RE, NAME_RE, validateClusterForm } from './clusterForm'

const base = { name: 'gray-01', registry: 'consul://10.0.0.1:8500', policy: 'rr', note: '' }

describe('validateClusterForm', () => {
  it('accepts a well-formed create payload', () => {
    expect(validateClusterForm(base)).toEqual({})
  })

  it('requires a name and enforces the shared regex', () => {
    expect(validateClusterForm({ ...base, name: '' })).toEqual({ name: 'overview.form.nameRequired' })
    expect(validateClusterForm({ ...base, name: 'Bad_Name!' })).toEqual({ name: 'overview.form.nameInvalid' })
    expect(NAME_RE.test('a'.repeat(40))).toBe(true)
    expect(NAME_RE.test('a'.repeat(41))).toBe(false)
  })

  it('skips the name in edit mode (the field is disabled)', () => {
    expect(validateClusterForm({ ...base, name: 'IGNORED' }, true)).toEqual({})
  })

  it('requires a registry with host:port, scheme optional and case-insensitive', () => {
    expect(validateClusterForm({ ...base, registry: '' })).toEqual({ registry: 'overview.form.registryRequired' })
    expect(validateClusterForm({ ...base, registry: 'consul://host' })).toEqual({
      registry: 'overview.form.registryInvalid'
    })
    expect(REGISTRY_RE.test('CONSUL://Host:8500')).toBe(true)
    expect(REGISTRY_RE.test('10.0.0.1:8500')).toBe(true)
  })

  it('pins the policy enum and the note length', () => {
    expect(validateClusterForm({ ...base, policy: 'fifo' })).toEqual({ policy: 'overview.form.policyInvalid' })
    expect(validateClusterForm({ ...base, note: 'x'.repeat(256) })).toEqual({ note: 'overview.form.noteTooLong' })
  })
})
```

- [ ] **Step 2: 运行确认失败 → 实现校验**

Run: `cd console/frontend; npx vitest run src/utils/clusterForm.spec.ts` → FAIL（模块不存在）。

Create `console/frontend/src/utils/clusterForm.ts`:

```typescript
/**
 * 集群表单校验：正则与后端 `cluster_service.NAME_RE/REGISTRY_RE/POLICIES`
 * 逐字一致（spec §4.1），前端只为即时反馈，服务端仍是唯一裁判。
 */
export const NAME_RE = /^[a-z0-9][a-z0-9-]{1,39}$/
export const REGISTRY_RE = /^([a-z][a-z0-9+.-]*:\/\/)?[\w.-]+:\d{2,5}$/i
export const POLICIES = ['least', 'rr', 'lat'] as const

export interface ClusterFormValues {
  name: string
  registry: string
  policy: string
  note: string
}

/** 值 = i18n 键（overview.form.*），由弹窗渲染。 */
export type ClusterFormErrors = Partial<Record<keyof ClusterFormValues, string>>

export function validateClusterForm(values: ClusterFormValues, editing = false): ClusterFormErrors {
  const errors: ClusterFormErrors = {}
  if (!editing) {
    const name = values.name.trim()
    if (!name) errors.name = 'overview.form.nameRequired'
    else if (!NAME_RE.test(name)) errors.name = 'overview.form.nameInvalid'
  }
  const registry = values.registry.trim()
  if (!registry) errors.registry = 'overview.form.registryRequired'
  else if (!REGISTRY_RE.test(registry)) errors.registry = 'overview.form.registryInvalid'
  if (!(POLICIES as readonly string[]).includes(values.policy)) errors.policy = 'overview.form.policyInvalid'
  if (values.note.length > 255) errors.note = 'overview.form.noteTooLong'
  return errors
}
```

Run: `npx vitest run src/utils/clusterForm.spec.ts` → PASS。

- [ ] **Step 3: 弹窗组件（失败不关窗 + 双反馈 + 编辑名称禁用）**

Create `console/frontend/src/components/ClusterFormModal.vue`:

```vue
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import { clustersApi } from '@/api/clusters'
import type { ClusterRow } from '@/types/api'
import { camel } from '@/utils/error'
import { POLICIES, validateClusterForm, type ClusterFormErrors, type ClusterFormValues } from '@/utils/clusterForm'

/**
 * 新增/编辑集群共用一个弹窗（原型 openClusterForm）。校验失败与服务端失败都
 * 不关窗（spec §5.2-3/4）：服务端 duplicate_name/duplicate_registry 回填到
 * 对应字段的 .ferr，其余错误码走 errors.<camel(code)> 横幅。
 */
const props = defineProps<{ open: boolean; cluster: ClusterRow | null }>()
const emit = defineEmits<{ 'update:open': [open: boolean]; saved: [row: ClusterRow] }>()
const { t } = useI18n()

const form = reactive<ClusterFormValues>({ name: '', registry: '', policy: 'least', note: '' })
const errors = ref<ClusterFormErrors>({})
const banner = ref('')
const saving = ref(false)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.name = props.cluster?.name ?? ''
    form.registry = props.cluster?.registry ?? ''
    form.policy = props.cluster?.policy ?? 'least'
    form.note = props.cluster?.note ?? ''
    errors.value = {}
    banner.value = ''
  }
)

function fail(caught: unknown): void {
  const err = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
  const key = camel(err.code)
  if (err.code === 'duplicate_name') errors.value = { ...errors.value, name: `errors.${key}` }
  else if (err.code === 'duplicate_registry') errors.value = { ...errors.value, registry: `errors.${key}` }
  else banner.value = t(`errors.${key}`)
}

async function save(): Promise<void> {
  errors.value = {}
  banner.value = ''
  const invalid = validateClusterForm(form, props.cluster !== null)
  if (Object.keys(invalid).length) {
    errors.value = invalid
    return
  }
  saving.value = true
  try {
    const row = props.cluster
      ? await clustersApi.update(props.cluster.name, {
          registry: form.registry.trim(),
          policy: form.policy,
          note: form.note
        })
      : await clustersApi.create({
          name: form.name.trim(),
          registry: form.registry.trim(),
          policy: form.policy,
          note: form.note
        })
    emit('saved', row)
    emit('update:open', false)
  } catch (caught) {
    fail(caught)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <a-modal
    :open="props.open"
    :title="props.cluster ? t('overview.form.editTitle') : t('overview.form.createTitle')"
    :ok-text="t('common.confirm')"
    :cancel-text="t('common.cancel')"
    :confirm-loading="saving"
    @ok="save"
    @update:open="(next: boolean) => emit('update:open', next)"
  >
    <a-form layout="vertical" @submit.prevent>
      <a-form-item :label="t('overview.form.name')">
        <a-input v-model:value="form.name" :disabled="props.cluster !== null" data-testid="cluster-name" />
        <p v-if="errors.name" class="ferr">{{ t(errors.name) }}</p>
      </a-form-item>
      <a-form-item :label="t('overview.form.registry')">
        <a-input v-model:value="form.registry" placeholder="consul://host:8500" data-testid="cluster-registry" />
        <p v-if="errors.registry" class="ferr">{{ t(errors.registry) }}</p>
      </a-form-item>
      <a-form-item :label="t('overview.form.policy')">
        <a-select v-model:value="form.policy">
          <a-select-option v-for="policy in POLICIES" :key="policy" :value="policy">
            {{ t(`overview.policy.${policy}`) }}
          </a-select-option>
        </a-select>
        <p v-if="errors.policy" class="ferr">{{ t(errors.policy) }}</p>
      </a-form-item>
      <a-form-item :label="t('overview.form.note')">
        <a-textarea v-model:value="form.note" :rows="2" :maxlength="255" />
        <p v-if="errors.note" class="ferr">{{ t(errors.note) }}</p>
      </a-form-item>
      <p v-if="banner" class="ferr ferr--banner">{{ banner }}</p>
    </a-form>
  </a-modal>
</template>

<style scoped lang="less">
.ferr {
  color: var(--s2s-color-danger);
  font-size: 12px;
  margin: 4px 0 0;

  &--banner {
    background: var(--s2s-color-surface-2);
    border: 1px solid var(--s2s-color-border);
    border-radius: var(--s2s-radius-sm);
    padding: 8px;
  }
}
</style>
```

注意：编辑模式 `clustersApi.update` 不发送 `name`（后端 PUT 载荷无 name），名称输入框禁用（场景 5）。

- [ ] **Step 4: ratchet 加入新文件**

Modify `console/frontend/src/styles/tokens.ts` 的 `TOKEN_ENFORCED_GLOBS`，`'src/components/NotImplemented.vue'` 之后追加一行：

```typescript
  'src/components/ClusterFormModal.vue'
```

Run: `cd console/frontend; npx vitest run src/styles/hex-ban.spec.ts` → PASS（Modal 只用 `var(--s2s-*)`）。

- [ ] **Step 5: 静态检查 + Commit**

Run: `cd console/frontend; npx vue-tsc --noEmit` → 无错误。
Run: `npx vitest run src/utils/clusterForm.spec.ts` → PASS。

```bash
git add console/frontend/src/utils/clusterForm.ts console/frontend/src/utils/clusterForm.spec.ts console/frontend/src/components/ClusterFormModal.vue console/frontend/src/styles/tokens.ts
git commit -m "feat(frontend): add cluster form validation and create/edit modal with failure-preserving UX"
```

---

### Task 9: 拓扑布局 `topoLayout.ts` + `TopoChart.vue`（四层 SVG）

**Files:**
- Create: `console/frontend/src/utils/topoLayout.ts`
- Create: `console/frontend/src/components/TopoChart.vue`
- Modify: `console/frontend/src/styles/tokens.ts`（ratchet 加入 TopoChart）
- Test: `console/frontend/src/utils/topoLayout.spec.ts`

**Interfaces:**
- Consumes: `ClusterRow`、`InstanceRow`（现有类型）；设计 token CSS 变量 `--s2s-color-surface-2 / --s2s-color-accent / --s2s-color-success / --s2s-color-warning / --s2s-color-danger / --s2s-color-orange / --s2s-color-border / --s2s-color-muted / --s2s-color-text / --s2s-font-mono`（applyTokens.ts 由 shellTokens 生成，名字已核实）。
- Produces:
  - `layoutTopo(input: TopoInput): TopoLayout`（纯函数，无框架依赖）
  - 组件 `TopoChart`：props `{ layout: TopoLayout }`，emits `machine(host: string)`

- [ ] **Step 1: 写失败测试**

Create `console/frontend/src/utils/topoLayout.spec.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import { layoutTopo } from './topoLayout'

const full = layoutTopo({
  cluster: 'default',
  machines: [
    { host: 'host1', online: true },
    { host: 'host2', online: false }
  ],
  instances: [
    { id: 'pipe-a', status: 'online', host: 'host1' },
    { id: 'pipe-b', status: 'degraded', host: 'host1' },
    { id: 'pipe-c', status: 'offline', host: 'host2' }
  ]
})

describe('layoutTopo', () => {
  it('stacks the four layers in prototype order', () => {
    expect(full.layers.map((layer) => layer.key)).toEqual(['cluster', 'lb', 'machine', 'instance'])
    expect(full.layers.map((layer) => layer.nodes.length)).toEqual([1, 1, 2, 3])
  })

  it('spreads sibling nodes evenly and keeps y constant per layer', () => {
    const machines = full.layers[2].nodes
    expect(machines[0].x).toBeCloseTo(900 / 3)
    expect(machines[1].x).toBeCloseTo((900 / 3) * 2)
    expect(new Set(machines.map((n) => n.y)).size).toBe(1)
  })

  it('maps status to tones: online=ok, degraded=warn, everything else=bad', () => {
    expect(full.layers[2].nodes.map((n) => n.tone)).toEqual(['ok', 'bad'])
    expect(full.layers[3].nodes.map((n) => n.tone)).toEqual(['ok', 'warn', 'bad'])
  })

  it('wires cluster→lb, lb→machine, machine→instance edges', () => {
    expect(full.edges).toHaveLength(1 + 2 + 3)
    expect(full.edges[0]).toEqual({ from: 'cluster:default', to: 'lb:console' })
    expect(full.edges.some((e) => e.from === 'machine:host2' && e.to === 'instance:pipe-c')).toBe(true)
  })

  it('keeps an empty cluster renderable with muted placeholders', () => {
    const empty = layoutTopo({ cluster: 'gray-01', machines: [], instances: [] })
    expect(empty.layers[2].nodes).toEqual([
      { id: 'machine:empty', kind: 'machine', label: '', x: 450, y: 232, tone: 'muted' }
    ])
    expect(empty.layers[3].nodes.every((n) => n.tone === 'muted')).toBe(true)
  })
})
```

- [ ] **Step 2: 运行确认失败 → 实现布局**

Run: `cd console/frontend; npx vitest run src/utils/topoLayout.spec.ts` → FAIL（模块不存在）。

Create `console/frontend/src/utils/topoLayout.ts`:

```typescript
/**
 * 四层拓扑的纯布局（原型 topoSVG，spec §5.2-8）：集群 → LB → 机器 → pipeline 实例。
 * 只算坐标与色调档，不碰 DOM、不碰 i18n；渲染在 TopoChart.vue。
 */
export type TopoTone = 'ok' | 'warn' | 'bad' | 'muted'
export type TopoKind = 'cluster' | 'lb' | 'machine' | 'instance'

export interface TopoNode {
  id: string
  kind: TopoKind
  label: string
  x: number
  y: number
  tone: TopoTone
}

export interface TopoEdge {
  from: string
  to: string
}

export interface TopoLayer {
  key: TopoKind
  y: number
  nodes: TopoNode[]
}

export interface TopoInput {
  cluster: string
  machines: Array<{ host: string; online: boolean }>
  instances: Array<{ id: string; status: string; host: string }>
}

export interface TopoLayout {
  width: number
  height: number
  layers: TopoLayer[]
  edges: TopoEdge[]
}

const WIDTH = 900
const HEIGHT = 380
const LAYER_Y: Record<TopoKind, number> = { cluster: 48, lb: 140, machine: 232, instance: 324 }

const toneForInstance = (status: string): TopoTone =>
  status === 'online' ? 'ok' : status === 'degraded' ? 'warn' : 'bad'

/** n 个同层节点在 WIDTH 内等距：第 i 个落在 (i+1)·WIDTH/(n+1)。 */
function spread(kind: TopoKind, items: Array<{ id: string; label: string; tone: TopoTone }>): TopoNode[] {
  if (!items.length) {
    return [{ id: `${kind}:empty`, kind, label: '', x: WIDTH / 2, y: LAYER_Y[kind], tone: 'muted' }]
  }
  const gap = WIDTH / (items.length + 1)
  return items.map((item, i) => ({
    id: item.id,
    kind,
    label: item.label,
    x: gap * (i + 1),
    y: LAYER_Y[kind],
    tone: item.tone
  }))
}

export function layoutTopo(input: TopoInput): TopoLayout {
  const clusterNodes = spread('cluster', [{ id: `cluster:${input.cluster}`, label: input.cluster, tone: 'ok' }])
  const lbNodes = spread('lb', [{ id: 'lb:console', label: 'Console LB', tone: 'ok' }])
  const machineNodes = spread(
    'machine',
    input.machines.map((m) => ({ id: `machine:${m.host}`, label: m.host, tone: m.online ? 'ok' : 'bad' }))
  )
  const instanceNodes = spread(
    'instance',
    input.instances.map((i) => ({ id: `instance:${i.id}`, label: i.id, tone: toneForInstance(i.status) }))
  )

  const edges: TopoEdge[] = [{ from: clusterNodes[0].id, to: lbNodes[0].id }]
  for (const machine of machineNodes) {
    if (machine.id !== 'machine:empty') edges.push({ from: lbNodes[0].id, to: machine.id })
  }
  for (const instance of instanceNodes) {
    if (instance.id === 'instance:empty') continue
    const host = input.instances.find((i) => `instance:${i.id}` === instance.id)?.host
    const machineId = `machine:${host}`
    if (machineNodes.some((n) => n.id === machineId)) edges.push({ from: machineId, to: instance.id })
  }

  return {
    width: WIDTH,
    height: HEIGHT,
    layers: [
      { key: 'cluster', y: LAYER_Y.cluster, nodes: clusterNodes },
      { key: 'lb', y: LAYER_Y.lb, nodes: lbNodes },
      { key: 'machine', y: LAYER_Y.machine, nodes: machineNodes },
      { key: 'instance', y: LAYER_Y.instance, nodes: instanceNodes }
    ],
    edges
  }
}
```

Run: `npx vitest run src/utils/topoLayout.spec.ts` → PASS。

- [ ] **Step 3: SVG 渲染组件（纯 token 上色）**

Create `console/frontend/src/components/TopoChart.vue`:

```vue
<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { TopoLayout, TopoNode, TopoTone } from '@/utils/topoLayout'

/**
 * 拓扑渲染（spec §5.2-8）：节点=圆角矩形+状态点+标签，边=直线；
 * 机器节点可点/可键盘激活，跳部署参数页由父组件决定（emit machine）。
 * 颜色一律走 --s2s-* 变量，本文件已进 hex-ban ratchet。
 */
const props = defineProps<{ layout: TopoLayout }>()
const emit = defineEmits<{ machine: [host: string] }>()
const { t } = useI18n()

const NODE_W = 128
const NODE_H = 34

const TONE_VAR: Record<TopoTone, string> = {
  ok: 'var(--s2s-color-success)',
  warn: 'var(--s2s-color-warning)',
  bad: 'var(--s2s-color-danger)',
  muted: 'var(--s2s-color-muted)'
}

const nodeById = (id: string): TopoNode | undefined =>
  props.layout.layers.flatMap((layer) => layer.nodes).find((node) => node.id === id)

const edgePoints = () =>
  props.layout.edges
    .map((edge) => {
      const from = nodeById(edge.from)
      const to = nodeById(edge.to)
      if (!from || !to) return null
      return { x1: from.x, y1: from.y + NODE_H / 2, x2: to.x, y2: to.y - NODE_H / 2, key: `${edge.from}->${edge.to}` }
    })
    .filter((p): p is NonNullable<typeof p> => p !== null)

function onMachine(node: TopoNode): void {
  if (node.id === 'machine:empty') return
  emit('machine', node.label)
}
</script>

<template>
  <svg
    class="topo"
    :viewBox="`0 0 ${props.layout.width} ${props.layout.height}`"
    role="img"
    :aria-label="t('overview.topology.title')"
  >
    <line
      v-for="edge in edgePoints()"
      :key="edge.key"
      :x1="edge.x1"
      :y1="edge.y1"
      :x2="edge.x2"
      :y2="edge.y2"
      class="topo__edge"
    />
    <g v-for="layer in props.layout.layers" :key="layer.key">
      <text :x="8" :y="layer.y - 14" class="topo__caption">{{ t(`overview.topology.${layer.key}Layer`) }}</text>
      <g
        v-for="node in layer.nodes"
        :key="node.id"
        :transform="`translate(${node.x - 64}, ${node.y - 17})`"
        :class="['topo__node', `is-${node.kind}`]"
        :tabindex="node.kind === 'machine' && node.id !== 'machine:empty' ? 0 : undefined"
        :role="node.kind === 'machine' && node.id !== 'machine:empty' ? 'button' : undefined"
        :aria-label="node.kind === 'machine' && node.id !== 'machine:empty' ? node.label : undefined"
        @click="node.kind === 'machine' && onMachine(node)"
        @keydown.enter="node.kind === 'machine' && onMachine(node)"
      >
        <rect :width="128" :height="34" rx="8" class="topo__box" :stroke="TONE_VAR[node.tone]" />
        <circle v-if="node.id !== `${node.kind}:empty`" cx="14" cy="17" r="4" :fill="TONE_VAR[node.tone]" />
        <text x="26" y="22" class="topo__label">{{ node.label || '—' }}</text>
      </g>
    </g>
  </svg>
</template>

<style scoped lang="less">
.topo {
  width: 100%;

  &__edge {
    stroke: var(--s2s-color-border);
    stroke-width: 1.5;
  }

  &__caption {
    fill: var(--s2s-color-muted);
    font-family: var(--s2s-font-mono);
    font-size: 11px;
  }

  &__box {
    fill: var(--s2s-color-surface-2);
    stroke-width: 1.5;
  }

  &__label {
    fill: var(--s2s-color-text);
    font-family: var(--s2s-font-mono);
    font-size: 12px;
  }

  &__node.is-machine {
    cursor: pointer;

    &:hover .topo__box {
      stroke: var(--s2s-color-accent);
    }

    &:focus-visible .topo__box {
      stroke: var(--s2s-color-accent);
      stroke-width: 2.5;
    }
  }
}
</style>
```

- [ ] **Step 4: ratchet 加入 + 验证**

Modify `console/frontend/src/styles/tokens.ts` 的 `TOKEN_ENFORCED_GLOBS`，追加 `'src/components/TopoChart.vue'`（置于 `ClusterFormModal.vue` 之后）。

Run: `cd console/frontend; npx vitest run src/utils/topoLayout.spec.ts src/styles/hex-ban.spec.ts` → 全绿。
Run: `npx vue-tsc --noEmit` → 无错误。

- [ ] **Step 5: Commit**

```bash
git add console/frontend/src/utils/topoLayout.ts console/frontend/src/utils/topoLayout.spec.ts console/frontend/src/components/TopoChart.vue console/frontend/src/styles/tokens.ts
git commit -m "feat(frontend): add four-layer topo layout and token-only TopoChart with machine drilldown"
```

---

### Task 10: 派生计算（`clusterKpis.ts`、`hostOf`）+ i18n 成对落键

**Files:**
- Create: `console/frontend/src/utils/clusterKpis.ts`
- Create: `console/frontend/src/utils/host.ts`
- Modify: `console/frontend/src/i18n/locales/zh-CN/overview.ts`（整文件重写）
- Modify: `console/frontend/src/i18n/locales/en-US/overview.ts`（整文件重写，键集与 zh 逐一对齐）
- Modify: `console/frontend/src/i18n/locales/zh-CN/errors.ts` / `en-US/errors.ts`（新增集群错误码 + `load.events`）
- Test: `console/frontend/src/utils/clusterKpis.spec.ts`
- Test: `console/frontend/src/utils/host.spec.ts`

**Interfaces:**
- Consumes: `ClusterRow`/`InstancesSummary`（Task 6）。
- Produces:
  - `clusterKpis(row: ClusterRow | null, summary: InstancesSummary | null): ClusterKpi[]`（固定 4 张：machines/instances/sessions/errorRate；`error_rate_5m` 为 null/undefined 时 `primary === DASH`，绝不显示 0 或 NaN——spec 口径④）
  - `hostOf(baseUrl: string): string`（与后端 `instances_service.host_of` 同口径：取 hostname，忽略端口，缺 scheme 也能解析）
  - i18n 键 `overview.{kpi.errorRate, policy.*, table.*, status.*, actions.*, form.*, confirm.*, legend.*, events.*, topology.*}` 与 `errors.{invalidRequest, duplicateName, duplicateRegistry, clusterNotFound, clusterNotEmpty, lastCluster, load.events}`（Task 8/9/11/12 引用）

- [ ] **Step 1: 写失败测试**

Create `console/frontend/src/utils/clusterKpis.spec.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import type { ClusterRow, InstancesSummary } from '@/types/api'
import { clusterKpis } from './clusterKpis'

const row: ClusterRow = {
  name: 'default',
  registry: 'consul://h:8500',
  policy: 'least',
  note: '',
  machines_total: 2,
  machines_online: 2,
  instances_total: 4,
  healthy: true,
  updated_at: '2026-11-05T00:00:00+00:00',
  updated_by: 'alice'
}

const summary = (over: Partial<InstancesSummary> = {}): InstancesSummary => ({
  instances_total: 4,
  online: 2,
  offline: 0,
  degraded: 0,
  draining: 0,
  slots_total: 16,
  slots_in_use: 9,
  slots_free: 7,
  pending_grants: 0,
  machines_total: 2,
  machines_online: 2,
  error_rate_5m: null,
  top_error_instance: null,
  ...over
})

const byKey = (kpis: ReturnType<typeof clusterKpis>) => Object.fromEntries(kpis.map((k) => [k.key, k]))

describe('clusterKpis', () => {
  it('renders exactly the four prototype cards', () => {
    expect(clusterKpis(row, summary()).map((k) => k.key)).toEqual(['machines', 'instances', 'sessions', 'errorRate'])
  })

  it('prefers the live summary over the catalog row', () => {
    const k = byKey(clusterKpis(row, summary({ machines_online: 1 })))
    expect(k.machines.primary).toBe('1 / 2')
    expect(k.sessions.primary).toBe('9')
    expect(k.sessions.sub).toBe('7')
  })

  it('shows DASH (never 0) when the error-rate window has no samples', () => {
    const k = byKey(clusterKpis(row, summary({ error_rate_5m: null })))
    expect(k.errorRate.primary).toBe('—')
    expect(k.errorRate.sub).toBe('—')
    expect(k.errorRate.tone).toBe('muted')
    // legacy 直连：summary 整个缺席同样 DASH，machines 回落 catalog 行。
    const legacy = byKey(clusterKpis(row, null))
    expect(legacy.errorRate.primary).toBe('—')
    expect(legacy.machines.primary).toBe('2 / 2')
  })

  it('formats a sampled rate as one-decimal percent with warn tone when > 0', () => {
    const warn = byKey(clusterKpis(row, summary({ error_rate_5m: 0.0234, top_error_instance: 'pipe-b' })))
    expect(warn.errorRate.primary).toBe('2.3%')
    expect(warn.errorRate.tone).toBe('warn')
    expect(warn.errorRate.sub).toBe('pipe-b')
    const clean = byKey(clusterKpis(row, summary({ error_rate_5m: 0 })))
    expect(clean.errorRate.primary).toBe('0.0%')
    expect(clean.errorRate.tone).toBe('ok')
  })

  it('never leaks NaN into any card', () => {
    const cards = clusterKpis(null, summary({ slots_in_use: Number.NaN }))
    for (const card of cards) expect(card.primary + card.sub).not.toContain('NaN')
  })
})
```

Create `console/frontend/src/utils/host.spec.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import { hostOf } from './host'

describe('hostOf', () => {
  it('extracts the hostname with or without a scheme, dropping the port', () => {
    expect(hostOf('http://host1:8765')).toBe('host1')
    expect(hostOf('https://10.12.0.9:8765')).toBe('10.12.0.9')
    expect(hostOf('host2:8765')).toBe('host2')
  })

  it('falls back to the raw string for garbage instead of throwing', () => {
    expect(hostOf(':::')).toBe(':::')
    expect(hostOf('')).toBe('')
  })
})
```

- [ ] **Step 2: 运行确认失败 → 实现两个 util**

Run: `cd console/frontend; npx vitest run src/utils/clusterKpis.spec.ts src/utils/host.spec.ts` → FAIL（模块不存在）。

Create `console/frontend/src/utils/host.ts`:

```typescript
/**
 * 机器身份 = base_url 的 hostname（spec §3：机器是从实例派生的，不是表）。
 * 与后端 instances_service.host_of 同口径；缺 scheme 的 host:port 也按 http 解析。
 */
export function hostOf(baseUrl: string): string {
  const url = baseUrl.includes('://') ? baseUrl : `http://${baseUrl}`
  try {
    return new URL(url).hostname
  } catch {
    return baseUrl
  }
}
```

Create `console/frontend/src/utils/clusterKpis.ts`:

```typescript
import type { ClusterRow, InstancesSummary } from '@/types/api'
import { DASH } from '@/utils/format'

/**
 * KPI 四卡的派生（原型 renderOverview 顶部卡片）。summary 缺席（legacy 直连）
 * 或窗口无样本（error_rate_5m === null）时按 spec 口径④渲染 DASH，绝不伪造 0。
 */
export interface ClusterKpi {
  key: 'machines' | 'instances' | 'sessions' | 'errorRate'
  primary: string
  sub: string
  tone: 'ok' | 'warn' | 'muted'
}

const num = (value: number | null | undefined): string =>
  typeof value === 'number' && Number.isFinite(value) ? String(value) : DASH

export function clusterKpis(row: ClusterRow | null, summary: InstancesSummary | null): ClusterKpi[] {
  const machinesPrimary = `${num(summary?.machines_online ?? row?.machines_online)} / ${num(
    summary?.machines_total ?? row?.machines_total
  )}`
  const rate = summary?.error_rate_5m
  const hasRate = typeof rate === 'number' && Number.isFinite(rate)
  return [
    {
      key: 'machines',
      primary: machinesPrimary,
      sub: '',
      tone: (row?.healthy ?? true) ? 'ok' : 'warn'
    },
    {
      key: 'instances',
      primary: num(summary?.instances_total ?? row?.instances_total),
      sub: num(summary?.online),
      tone: 'ok'
    },
    {
      key: 'sessions',
      primary: num(summary?.slots_in_use),
      sub: num(summary?.slots_free),
      tone: 'ok'
    },
    {
      key: 'errorRate',
      primary: hasRate ? `${(rate * 100).toFixed(1)}%` : DASH,
      sub: hasRate ? summary?.top_error_instance || DASH : DASH,
      tone: !hasRate ? 'muted' : rate > 0 ? 'warn' : 'ok'
    }
  ]
}
```

Run: `npx vitest run src/utils/clusterKpis.spec.ts src/utils/host.spec.ts` → PASS。

- [ ] **Step 3: zh-CN overview.ts 整文件重写**

Replace `console/frontend/src/i18n/locales/zh-CN/overview.ts` 全文：

```typescript
export default {
  kpi: {
    machines: '机器数',
    pipelineInstances: 'Pipeline 实例',
    online: '在线',
    degraded: '降级',
    offline: '离线',
    draining: '摘除中',
    activeSessions: '活跃会话',
    freeSlots: '空闲槽位',
    totalSlots: '槽位总数',
    pendingGrants: '待领取授权',
    clusterAlerts: '集群告警',
    catalogCommit: '参数目录版本',
    version: '生效版本',
    status: '发布状态',
    allocatorMode: '分配器模式',
    consoleId: '控制台实例',
    dbHealth: '数据库健康',
    pipelineHealth: 'Pipeline 健康',
    instancesRegistered: '已注册实例',
    seedConfigured: '种子配置',
    secretsConsistent: '密钥一致性',
    errorRate: '错误率 (5m)'
  },
  topology: {
    title: '集群拓扑',
    clusterLayer: '集群',
    lbLayer: '负载均衡层',
    machineLayer: '机器层',
    instanceLayer: 'Pipeline 实例层'
  },
  policy: {
    least: '最少会话',
    rr: '轮询',
    lat: '最低延迟'
  },
  table: {
    cluster: '集群',
    registry: 'Registry',
    policy: '策略',
    machines: '机器',
    instances: '实例',
    status: '状态',
    actions: '操作',
    current: '当前',
    empty: '暂无集群'
  },
  status: {
    healthy: '正常',
    unhealthy: '异常'
  },
  actions: {
    create: '新增集群',
    switchTo: '切换',
    edit: '编辑',
    delete: '删除'
  },
  form: {
    createTitle: '新增集群',
    editTitle: '编辑集群',
    name: '名称',
    registry: 'Registry',
    policy: '策略',
    note: '备注',
    nameRequired: '必填 · 名称',
    nameInvalid: '名称需为 2–40 位小写字母/数字/连字符，且以字母或数字开头',
    registryRequired: '必填 · registry',
    registryInvalid: 'registry 需为 scheme://host:port 或 host:port（端口 2–5 位）',
    policyInvalid: '策略仅支持 least / rr / lat',
    noteTooLong: '备注不超过 255 字'
  },
  confirm: {
    deleteContent: '删除集群 {name}？该操作会写入审计。'
  },
  legend: {
    title: '图例',
    cluster: '集群',
    lb: '负载均衡',
    machine: '机器',
    instance: 'Pipeline 实例',
    online: '在线',
    degraded: '降级',
    offline: '离线',
    muted: '暂无数据'
  },
  events: {
    title: '最近事件',
    at: '时间',
    actor: '操作人',
    role: '角色',
    action: '动作',
    target: '对象',
    result: '结果',
    ok: '成功',
    error: '失败',
    empty: '暂无集群操作'
  }
}
```

（`unimpl.*` 与 `topology.pipelineLayer` 随本次重写移除：`pipelineLayer` 被 `instanceLayer` 取代，unimpl 空态卡由 Task 11 的真数据视图替代。`kpi.*` 老键保留——parity 与旧引用都稳。）

- [ ] **Step 4: en-US overview.ts 整文件重写**

Replace `console/frontend/src/i18n/locales/en-US/overview.ts` 全文（结构与 zh 逐键对应，`i18n.spec.ts` 的 flatten-parity 会拦住任何漂移）：

```typescript
export default {
  kpi: {
    machines: 'Machines',
    pipelineInstances: 'Pipeline instances',
    online: 'Online',
    degraded: 'Degraded',
    offline: 'Offline',
    draining: 'Draining',
    activeSessions: 'Active sessions',
    freeSlots: 'Free slots',
    totalSlots: 'Total slots',
    pendingGrants: 'Pending grants',
    clusterAlerts: 'Cluster alerts',
    catalogCommit: 'Catalog commit',
    version: 'Live version',
    status: 'Publish status',
    allocatorMode: 'Allocator mode',
    consoleId: 'Console instance',
    dbHealth: 'Database health',
    pipelineHealth: 'Pipeline health',
    instancesRegistered: 'Registered instances',
    seedConfigured: 'Seed config',
    secretsConsistent: 'Secret consistency',
    errorRate: 'Error rate (5m)'
  },
  topology: {
    title: 'Cluster topology',
    clusterLayer: 'Cluster',
    lbLayer: 'Load balancer',
    machineLayer: 'Machines',
    instanceLayer: 'Pipeline instances'
  },
  policy: {
    least: 'Least sessions',
    rr: 'Round robin',
    lat: 'Lowest latency'
  },
  table: {
    cluster: 'Cluster',
    registry: 'Registry',
    policy: 'Policy',
    machines: 'Machines',
    instances: 'Instances',
    status: 'Status',
    actions: 'Actions',
    current: 'Current',
    empty: 'No clusters yet'
  },
  status: {
    healthy: 'Healthy',
    unhealthy: 'Unhealthy'
  },
  actions: {
    create: 'New cluster',
    switchTo: 'Switch',
    edit: 'Edit',
    delete: 'Delete'
  },
  form: {
    createTitle: 'New cluster',
    editTitle: 'Edit cluster',
    name: 'Name',
    registry: 'Registry',
    policy: 'Policy',
    note: 'Note',
    nameRequired: 'Required · name',
    nameInvalid: 'Name must be 2–40 lowercase letters, digits or hyphens, starting with a letter or digit',
    registryRequired: 'Required · registry',
    registryInvalid: 'Registry must be scheme://host:port or host:port (2–5 digit port)',
    policyInvalid: 'Policy must be one of least / rr / lat',
    noteTooLong: 'Note must be 255 characters or fewer'
  },
  confirm: {
    deleteContent: 'Delete cluster {name}? This action is audited.'
  },
  legend: {
    title: 'Legend',
    cluster: 'Cluster',
    lb: 'Load balancer',
    machine: 'Machine',
    instance: 'Pipeline instance',
    online: 'Online',
    degraded: 'Degraded',
    offline: 'Offline',
    muted: 'No data'
  },
  events: {
    title: 'Recent events',
    at: 'Time',
    actor: 'Actor',
    role: 'Role',
    action: 'Action',
    target: 'Target',
    result: 'Result',
    ok: 'OK',
    error: 'Failed',
    empty: 'No cluster operations yet'
  }
}
```

- [ ] **Step 5: errors 命名空间补集群码（zh + en 成对）**

在 `zh-CN/errors.ts` 顶层（`forbidden` 键之后）追加：

```typescript
  invalidRequest: '请求不合法',
  duplicateName: '集群名已存在',
  duplicateRegistry: '该 registry 已被其他集群使用',
  clusterNotFound: '集群不存在',
  clusterNotEmpty: '集群下仍有机器，无法删除',
  lastCluster: '至少需要保留一个集群',
```

在 `en-US/errors.ts` 同位置追加：

```typescript
  invalidRequest: 'The request is invalid',
  duplicateName: 'Cluster name already exists',
  duplicateRegistry: 'That registry is already used by another cluster',
  clusterNotFound: 'Cluster does not exist',
  clusterNotEmpty: 'The cluster still owns machines and cannot be deleted',
  lastCluster: 'At least one cluster must remain',
```

并在两个文件的 `load` 分组内各追加一条（zh）`events: '最近事件加载失败',`、（en）`events: 'Failed to load recent events',`。

（键名即 `camel(后端错误码)`：`utils/error.ts` 的 translate 走 `errors.${camel(code)}`，AppError 横幅与 ClusterFormModal 的 fail() 共用此映射。）

- [ ] **Step 6: 验证 + Commit**

Run: `cd console/frontend; npx vitest run src/i18n/i18n.spec.ts src/utils/clusterKpis.spec.ts src/utils/host.spec.ts` → 全绿。

```bash
git add console/frontend/src/utils/clusterKpis.ts console/frontend/src/utils/clusterKpis.spec.ts console/frontend/src/utils/host.ts console/frontend/src/utils/host.spec.ts console/frontend/src/i18n/locales
git commit -m "feat(frontend): add cluster kpi derivation, hostOf util and paired en/zh overview copy"
```

---

### Task 11: `OverviewView.vue` 五段重写 + 顶栏集群/Profile 双胶囊联动

**Files:**
- Modify: `console/frontend/src/views/OverviewView.vue`（整文件重写）
- Modify: `console/frontend/src/layouts/ConsoleLayout.vue:84-89, 240-247`
- Delete: `console/frontend/src/views/overviewMetrics.ts`、`console/frontend/src/views/overviewMetrics.spec.ts`
- Test: `console/frontend/src/views/overviewViewSections.spec.ts`

**Interfaces:**
- Consumes: `useClusterStore`（Task 7）、`clustersApi`（Task 6）、`ClusterFormModal`（Task 8）、`TopoChart`/`layoutTopo`（Task 9）、`clusterKpis`/`hostOf`/`overview.*` i18n（Task 10）、`useConfirm`/`ConfirmDialog`/`ErrorBanner`/`formatTime`（现有）、`auth.hasPermission`（Task 7）。
- Produces: 集群总览页五段结构（spec §5.2）——①KPI 四卡 ②集群表（CRUD+当前标签）③拓扑 ④图例+最近4条事件 ⑤全降级态；顶栏 `clusterStore.rows` 下拉与 `switchTo` 联动（场景 7：与表内「切换」按钮等效）。

- [ ] **Step 1: 写失败测试（段落渲染契约）**

仓库无 SFC 挂载测试设施，段落结构用「源码文本契约」做最低可执行的闸（重写前必红，重写后被 Task 13/14 的走查复核视觉）：

Create `console/frontend/src/views/overviewViewSections.spec.ts`:

```typescript
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const source = readFileSync(join(__dirname, 'OverviewView.vue'), 'utf8')

describe('OverviewView sections (spec §5.2)', () => {
  it('composes the five prototype sections', () => {
    for (const marker of ['overview.kpi.', 'overview.table.', 'TopoChart', 'overview.legend.', 'overview.events.']) {
      expect(source).toContain(marker)
    }
  })

  it('gates every write action behind the mirrored permission codes', () => {
    for (const code of [
      'console:cluster:create',
      'console:cluster:switch',
      'console:cluster:update',
      'console:cluster:delete'
    ]) {
      expect(source).toContain(code)
    }
  })

  it('derives machines for the topo from instance hosts', () => {
    expect(source).toContain('hostOf(')
    expect(source).toContain('layoutTopo(')
  })

  it('drills a machine click into the deploy page with ?host=', () => {
    expect(source).toContain(`name: 'machines'`)
    expect(source).toContain('query: { host')
  })
})
```

Run: `cd console/frontend; npx vitest run src/views/overviewViewSections.spec.ts` → FAIL（现文件无 TopoChart/权限码）。

- [ ] **Step 2: 重写 OverviewView.vue**

Replace `console/frontend/src/views/OverviewView.vue` 全文：

```vue
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { api, AppError } from '@/api/client'
import { clustersApi } from '@/api/clusters'
import ClusterFormModal from '@/components/ClusterFormModal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import TopoChart from '@/components/TopoChart.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useAuthStore } from '@/stores/auth'
import { useClusterStore } from '@/stores/cluster'
import { useConsoleStore } from '@/stores/console'
import type { ClusterEventRow, ClusterRow, InstanceRow, InstanceSnapshot, InstancesSummary } from '@/types/api'
import { clusterKpis } from '@/utils/clusterKpis'
import { DASH, formatTime } from '@/utils/format'
import { hostOf } from '@/utils/host'
import { layoutTopo } from '@/utils/topoLayout'

/**
 * 集群总览（spec §5.2，原型 renderOverview/clusterRows/topoSVG）：
 * 五段=KPI 四卡 / 集群表 CRUD / 拓扑 / 图例+最近事件 / 全降级态。
 * 数据只有三个来源：/clusters、/clusters/events、/instances?cluster=，不引 Mock。
 * 端点各败各的：一条告警或一个端点不可用都不能让整页空白。
 */
const consoleStore = useConsoleStore()
const clusterStore = useClusterStore()
const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()
const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const summary = ref<InstancesSummary | null>(null)
const instances = ref<InstanceRow[]>([])
const alerts = ref<string[]>([])
const events = ref<ClusterEventRow[]>([])
const instancesError = ref<AppError | null>(null)
const eventsError = ref<AppError | null>(null)
const actionError = ref<AppError | null>(null)
const formOpen = ref(false)
const formCluster = ref<ClusterRow | null>(null)

const kpis = computed(() => clusterKpis(clusterStore.currentRow, summary.value))

// 机器层不是表：从当前集群实例的 base_url host 去重派生（spec §3）。
const topo = computed(() => {
  const hosts = new Map<string, boolean>()
  for (const row of instances.value) {
    const host = hostOf(row.base_url)
    hosts.set(host, (hosts.get(host) ?? false) || row.status === 'online')
  }
  return layoutTopo({
    cluster: clusterStore.current,
    machines: [...hosts].map(([host, online]) => ({ host, online })),
    instances: instances.value.map((row) => ({ id: row.instance_id, status: row.status, host: hostOf(row.base_url) }))
  })
})

async function loadClusterData(): Promise<void> {
  const [instancesResult, eventsResult] = await Promise.allSettled([
    api.get<InstanceSnapshot>('/instances', {
      params: { profile: consoleStore.profile, cluster: clusterStore.current }
    }),
    clustersApi.events(4)
  ])
  if (instancesResult.status === 'fulfilled') {
    summary.value = instancesResult.value.summary ?? null
    instances.value = instancesResult.value.instances ?? []
    alerts.value = instancesResult.value.alerts ?? []
    instancesError.value = null
  } else {
    summary.value = null
    instances.value = []
    alerts.value = []
    instancesError.value =
      instancesResult.reason instanceof AppError
        ? instancesResult.reason
        : new AppError('unknown', t('errors.load.instances'))
  }
  if (eventsResult.status === 'fulfilled') {
    events.value = eventsResult.value
    eventsError.value = null
  } else {
    events.value = []
    eventsError.value =
      eventsResult.reason instanceof AppError
        ? eventsResult.reason
        : new AppError('unknown', t('errors.load.events'))
  }
}

onMounted(async () => {
  await clusterStore.load()
  await loadClusterData()
})

watch(() => clusterStore.current, () => void loadClusterData())
watch(() => consoleStore.profile, () => void loadClusterData())

function openCreate(): void {
  formCluster.value = null
  formOpen.value = true
}

function openEdit(row: ClusterRow): void {
  formCluster.value = row
  formOpen.value = true
}

async function onSaved(row: ClusterRow): Promise<void> {
  const isNew = formCluster.value === null
  await clusterStore.load()
  // 场景 3：新增成功后自动切入新集群，便于紧接着加机器；switchTo 顺带留审计。
  if (isNew) await clusterStore.switchTo(row.name)
  await loadClusterData()
}

async function switchCluster(row: ClusterRow): Promise<void> {
  actionError.value = null
  const ok = await clusterStore.switchTo(row.name)
  if (!ok) actionError.value = clusterStore.error
  else await loadClusterData()
}

async function removeCluster(row: ClusterRow): Promise<void> {
  const confirmed = await askConfirm({
    title: t('overview.actions.delete'),
    content: t('overview.confirm.deleteContent', { name: row.name })
  })
  if (!confirmed) return
  actionError.value = null
  try {
    await clusterStore.remove(row.name)
  } catch (caught) {
    actionError.value = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
  }
  await loadClusterData()
}

// 场景 8：拓扑里的机器跳部署参数页，用 query.host 带身份（Task 12 接手高亮/筛选）。
function goMachine(host: string): void {
  void router.push({ name: 'machines', query: { host } })
}

const tableColumns = computed(() => [
  { title: t('overview.table.cluster'), key: 'name' },
  { title: t('overview.table.registry'), key: 'registry' },
  { title: t('overview.table.policy'), key: 'policy', width: 130 },
  { title: t('overview.table.machines'), key: 'machines', width: 90 },
  { title: t('overview.table.instances'), key: 'instances', width: 90 },
  { title: t('overview.table.status'), key: 'status', width: 90 },
  { title: t('overview.table.actions'), key: 'actions', width: 220 }
])

const eventColumns = computed(() => [
  { title: t('overview.events.at'), key: 'at', width: 160 },
  { title: t('overview.events.actor'), dataIndex: 'actor', key: 'actor', width: 110 },
  { title: t('overview.events.action'), key: 'action', width: 140 },
  { title: t('overview.events.target'), dataIndex: 'profile', key: 'target', width: 130 },
  { title: t('overview.events.result'), key: 'result', width: 90 }
])
</script>

<template>
  <div class="overview">
    <ErrorBanner :error="instancesError" />
    <ErrorBanner :error="eventsError" />
    <ErrorBanner :error="clusterStore.error" />
    <ErrorBanner :error="actionError" />

    <section v-if="alerts.length" class="overview__alerts">
      <a-alert v-for="alert in alerts" :key="alert" type="warning" show-icon :message="alert" />
    </section>

    <!-- ① KPI 四卡：机器 / 实例 / 活跃会话 / 错误率(5m)，随当前集群联动。 -->
    <div class="overview__grid">
      <a-card v-for="kpi in kpis" :key="kpi.key" size="small" class="kpi">
        <p class="kpi__label">{{ t(`overview.kpi.${kpi.key === 'instances' ? 'pipelineInstances' : kpi.key === 'sessions' ? 'activeSessions' : kpi.key}`) }}</p>
        <p class="kpi__value" :class="`is-${kpi.tone}`" :data-metric="`kpi.${kpi.key}`">{{ kpi.primary }}</p>
        <p v-if="kpi.sub" class="kpi__sub">{{ kpi.sub }}</p>
      </a-card>
    </div>

    <!-- ② 集群表：当前行带「当前」标签且不摆切换按钮（场景 2）。 -->
    <a-card size="small" :title="t('shell.cluster')">
      <template #extra>
        <a-button v-if="auth.hasPermission('console:cluster:create')" size="small" type="primary" @click="openCreate">
          {{ t('overview.actions.create') }}
        </a-button>
      </template>
      <a-table
        size="small"
        row-key="name"
        :pagination="false"
        :data-source="clusterStore.rows"
        :columns="tableColumns"
        :locale="{ emptyText: t('overview.table.empty') }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <span class="cluster-name">{{ record.name }}</span>
            <a-tag v-if="record.name === clusterStore.current" color="blue">{{ t('overview.table.current') }}</a-tag>
            <p v-if="record.note" class="cluster-note">{{ record.note }}</p>
          </template>
          <template v-else-if="column.key === 'registry'">
            <span class="mono">{{ record.registry || DASH }}</span>
          </template>
          <template v-else-if="column.key === 'policy'">
            {{ t(`overview.policy.${record.policy}`) }}
          </template>
          <template v-else-if="column.key === 'machines'">
            <span class="mono">{{ record.machines_online }} / {{ record.machines_total }}</span>
          </template>
          <template v-else-if="column.key === 'instances'">
            <span class="mono">{{ record.instances_total }}</span>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-badge :status="record.healthy ? 'success' : 'error'" :text="t(record.healthy ? 'overview.status.healthy' : 'overview.status.unhealthy')" />
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button
                v-if="record.name !== clusterStore.current && auth.hasPermission('console:cluster:switch')"
                size="small"
                @click="switchCluster(record as ClusterRow)"
              >{{ t('overview.actions.switchTo') }}</a-button>
              <a-button
                v-if="auth.hasPermission('console:cluster:update')"
                size="small"
                @click="openEdit(record as ClusterRow)"
              >{{ t('overview.actions.edit') }}</a-button>
              <a-button
                v-if="auth.hasPermission('console:cluster:delete')"
                size="small"
                danger
                @click="removeCluster(record as ClusterRow)"
              >{{ t('overview.actions.delete') }}</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- ③ 拓扑：集群→LB→机器→pipeline 实例，机器可点跳部署参数页（场景 8）。 -->
    <a-card size="small" :title="t('overview.topology.title')">
      <TopoChart :layout="topo" @machine="goMachine" />
    </a-card>

    <div class="overview__split">
      <!-- ④a 图例 -->
      <a-card size="small" :title="t('overview.legend.title')">
        <ul class="legend">
          <li><span class="legend__dot is-ok" />{{ t('overview.legend.online') }}</li>
          <li><span class="legend__dot is-warn" />{{ t('overview.legend.degraded') }}</li>
          <li><span class="legend__dot is-bad" />{{ t('overview.legend.offline') }}</li>
          <li><span class="legend__dot is-muted" />{{ t('overview.legend.muted') }}</li>
        </ul>
      </a-card>

      <!-- ④b 最近事件：audit action 代码态不翻译（spec §8.4 口径），结果列翻译。 -->
      <a-card size="small" :title="t('overview.events.title')">
        <a-table
          v-if="events.length"
          size="small"
          row-key="auditId"
          :pagination="false"
          :data-source="events"
          :columns="eventColumns"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'at'"><span class="mono">{{ formatTime(record.at) }}</span></template>
            <template v-else-if="column.key === 'action'"><span class="mono">{{ record.action }}</span></template>
            <template v-else-if="column.key === 'result'">
              <a-tag :color="record.result === 'ok' ? 'green' : 'red'">
                {{ t(record.result === 'ok' ? 'overview.events.ok' : 'overview.events.error') }}<template v-if="record.result === 'error' && record.errorCode"> · {{ record.errorCode }}</template>
              </a-tag>
            </template>
          </template>
        </a-table>
        <p v-else class="events-empty">{{ t('overview.events.empty') }}</p>
      </a-card>
    </div>

    <ClusterFormModal v-model:open="formOpen" :cluster="formCluster" @saved="onSaved" />
    <ConfirmDialog :open="confirmOpen" :title="confirmTitle" :content="confirmContent" @answer="answerConfirm" />
  </div>
</template>

<style scoped lang="less">
.overview {
  display: flex;
  flex-direction: column;
  gap: 16px;

  &__alerts {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  }

  &__split {
    display: grid;
    gap: 12px;
    grid-template-columns: 260px 1fr;
  }
}

.kpi {
  &__label {
    color: var(--s2s-color-muted);
    font-size: 12px;
    margin: 0 0 4px;
  }

  &__value {
    color: var(--s2s-color-text);
    font-family: var(--s2s-font-mono);
    font-size: 18px;
    margin: 0;

    &.is-warn {
      color: var(--s2s-color-warning);
    }

    &.is-muted {
      color: var(--s2s-color-muted);
    }
  }

  &__sub {
    color: var(--s2s-color-faint);
    font-family: var(--s2s-font-mono);
    font-size: 11px;
    margin: 4px 0 0;
  }
}

.cluster-name {
  color: var(--s2s-color-text);
  font-weight: 600;
}

.cluster-note {
  color: var(--s2s-color-muted);
  font-size: 11px;
  margin: 2px 0 0;
  white-space: pre-wrap;
}

.mono {
  font-family: var(--s2s-font-mono);
  font-size: 12px;
}

.legend {
  list-style: none;
  margin: 0;
  padding: 0;

  li {
    align-items: center;
    color: var(--s2s-color-text);
    display: flex;
    font-size: 12px;
    gap: 8px;
    padding: 2px 0;
  }

  &__dot {
    border-radius: 50%;
    height: 8px;
    width: 8px;

    &.is-ok {
      background: var(--s2s-color-success);
    }

    &.is-warn {
      background: var(--s2s-color-warning);
    }

    &.is-bad {
      background: var(--s2s-color-danger);
    }

    &.is-muted {
      background: var(--s2s-color-muted);
    }
  }
}

.events-empty {
  color: var(--s2s-color-muted);
  font-size: 12px;
  margin: 0;
}
</style>
```

- [ ] **Step 3: 删除被替换的旧派生**

```bash
git rm console/frontend/src/views/overviewMetrics.ts console/frontend/src/views/overviewMetrics.spec.ts
```

（Grep 已确认 `overviewMetrics` 仅被旧 OverviewView 与其自身 spec 引用。）

- [ ] **Step 4: 顶栏拆成集群 + Profile 两枚胶囊**

Modify `console/frontend/src/layouts/ConsoleLayout.vue`：

脚本区——import 加 `import { useClusterStore } from '@/stores/cluster'`；`consoleStore` 声明旁加 `const clusterStore = useClusterStore()`；`onProfileChange` 之后加：

```typescript
// 集群胶囊：切换走 store.switchTo（POST /switch 留审计），失败不切、select 回弹。
function onClusterChange(event: Event): void {
  const select = event.target as HTMLSelectElement
  void clusterStore.switchTo(select.value).then((ok) => {
    if (!ok) select.value = clusterStore.current
  })
}
```

`onMounted` 回调体内（`mql` 初始化之前）加 `void clusterStore.load()`。

模板区——把 L240-247 的单枚「集群胶囊」（`<!-- 集群胶囊（demo `#cluster-pill`）…` 注释 + 单个 `<label class="shell__pill">`）整体替换为两枚：

```html
      <!-- 集群胶囊（demo `#cluster-pill`）：真实集群列表，切换=switch 审计（spec §5.1）。 -->
      <label class="shell__pill">
        <span>{{ t('shell.cluster') }}</span>
        <select :value="clusterStore.current" :aria-label="t('shell.cluster')" @change="onClusterChange">
          <option v-for="row in clusterStore.rows" :key="row.name" :value="row.name">{{ row.name }}</option>
        </select>
      </label>

      <!-- Profile 胶囊：从旧集群胶囊拆出，profile 语义保持不变（部署环境档位）。 -->
      <label class="shell__pill">
        <span>{{ t('shell.profile') }}</span>
        <select :value="consoleStore.profile" :aria-label="t('shell.profile')" @change="onProfileChange">
          <option v-for="opt in profileOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
      </label>
```

- [ ] **Step 5: 验证**

Run: `cd console/frontend; npx vitest run src/views/overviewViewSections.spec.ts src/styles/hex-ban.spec.ts src/i18n/i18n.spec.ts` → 全绿。
Run: `npx vue-tsc --noEmit` → 无错误（旧 overviewMetrics 引用已清）。

- [ ] **Step 6: Commit**

```bash
git add console/frontend/src/views/OverviewView.vue console/frontend/src/layouts/ConsoleLayout.vue
git commit -m "feat(frontend): rebuild overview page with kpi cards, cluster CRUD table, topo and events"
```

---

### Task 12: `InstancesView` 读 `route.query.host`——唯一允许的最小增量

**Files:**
- Modify: `console/frontend/src/views/InstancesView.vue:2-4, 65, 183-190`
- Modify: `console/frontend/src/i18n/locales/zh-CN/machines.ts` / `en-US/machines.ts`（加 1 个键）
- Test: `console/frontend/src/views/instancesViewHost.spec.ts`

**Interfaces:**
- Consumes: `hostOf`（Task 10）；Task 11 拓扑机器点击写入的 `router.push({ name: 'machines', query: { host } })`。
- Produces: 部署参数页按 `?host=` 过滤实例表并可一键清除；除过滤/清除条外 **不改该页任何其他逻辑**（spec §6 决议③，用户已确认这是唯一允许的最小增量）。

- [ ] **Step 1: 写失败测试（源码契约）**

Create `console/frontend/src/views/instancesViewHost.spec.ts`:

```typescript
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const source = readFileSync(join(__dirname, 'InstancesView.vue'), 'utf8')

describe('InstancesView host drilldown (spec §6 决议③)', () => {
  it('reads route.query.host and feeds it to the table datasource', () => {
    expect(source).toContain('route.query.host')
    expect(source).toContain('visibleInstances')
    expect(source).toContain(':data-source="visibleInstances"')
  })

  it('keeps the unfiltered rows computed intact', () => {
    expect(source).toContain('const instances = computed(() => snapshot.value?.instances ?? [])')
  })
})
```

Run: `cd console/frontend; npx vitest run src/views/instancesViewHost.spec.ts` → FAIL（无 route.query.host）。

- [ ] **Step 2: 最小增量改造**

Modify `console/frontend/src/views/InstancesView.vue`：

L4 的 `import { useRouter } from 'vue-router'` 改为 `import { useRoute, useRouter } from 'vue-router'`；`const router = useRouter()` 之后加 `const route = useRoute()`。

import 区加 `import { hostOf } from '@/utils/host'`。

L65 `const instances = computed(...)` 之后加（`instances` 原样保留——summary 卡片、徽标等仍看全量）：

```typescript
// 拓扑下钻（Task 11）写入 ?host=：只影响这张表，其余页面逻辑不动（spec §6 决议③）。
const hostFilter = computed(() => String(route.query.host ?? ''))
const visibleInstances = computed(() =>
  hostFilter.value ? instances.value.filter((row) => hostOf(row.base_url) === hostFilter.value) : instances.value
)

function clearHostFilter(): void {
  void router.replace({ name: 'machines', query: { ...route.query, host: undefined } })
}
```

表格区（L183 起）：`v-if="instances.length"` 保持不变（全量有行才渲染表格区），`:data-source="instances"` 改为 `:data-source="visibleInstances"`；在 `<a-table` 之前插入过滤提示条：

```html
    <a-alert
      v-if="hostFilter"
      class="instances__hostfilter"
      type="info"
      show-icon
      closable
      :message="t('machines.hostFilter', { host: hostFilter })"
      @close="clearHostFilter"
    />
```

样式块追加（该文件不在 hex-ban ratchet，但仍走 token，不写裸色值）：

```less
.instances__hostfilter {
  margin-bottom: 8px;
}
```

- [ ] **Step 3: i18n 成对落键**

`zh-CN/machines.ts` 顶层加：`hostFilter: '仅显示机器 {host} 上的实例',`
`en-US/machines.ts` 同位置加：`hostFilter: 'Showing instances on machine {host} only',`

- [ ] **Step 4: 验证 + Commit**

Run: `cd console/frontend; npx vitest run src/views/instancesViewHost.spec.ts src/i18n/i18n.spec.ts` → 全绿。
Run: `npx vue-tsc --noEmit` → 无错误。

```bash
git add console/frontend/src/views/InstancesView.vue console/frontend/src/views/instancesViewHost.spec.ts console/frontend/src/i18n/locales
git commit -m "feat(frontend): filter deploy table by ?host= drilldown link, minimal increment only"
```

---

### Task 13: 前端全量静态闸

**Files:**
- 无新文件；本任务只跑闸并修复暴露的问题。

**Interfaces:**
- Consumes: Task 6-12 的全部前端产物。
- Produces: 绿灯的 `vue-tsc` / `eslint --max-warnings 0` / `vitest run` / 生产构建，作为 Task 14 联调与后续 PR 的门面。

- [ ] **Step 1: 逐闸运行**

```powershell
cd console/frontend
npx vue-tsc --noEmit
npm run lint
npx vitest run
npm run build
```

Expected（按 package.json scripts，Node 16.20.2）：
- `vue-tsc` 零错误；
- `lint` 零 warning（仓库 lint 脚本已带 `--max-warnings 0` 语义；若脚本不带，用 `npm run lint -- --max-warnings 0`）；
- `vitest run` 全绿——特别关注 `i18n.spec.ts`（zh/en flatten 键集 parity）、`hex-ban.spec.ts`（ClusterFormModal/TopoChart/OverviewView/ConsoleLayout 全在 ratchet 内，模板与 style 块不得出现裸 hex）、`router.spec.ts`（本轮不动路由，必须仍绿）；
- `build` 成功产出 `dist/`（**不提交**，AGENTS.md 明令 dist/build 不入库）。

- [ ] **Step 2: 后端回归闸**

```powershell
cd console/backend
python -m pytest tests/unit tests/integration -q
python -m ruff check app tests
```

Expected: 全绿、ruff 零违规（line-length 120）。

- [ ] **Step 3: 若有修复则提交**

```bash
git add console/frontend console/backend
git commit -m "fix: resolve static gate findings for cluster overview"
```

（全绿无改动则跳过提交，直接进入 Task 14。）

---

### Task 14: 联调 + CON-02 九场景走查 + 交付说明

**Files:**
- Create: `qa-artifacts-archive/cluster-overview/`（截图与走查记录，**不提交入库**）

**Interfaces:**
- Consumes: Task 1-13 全部产物；`docs/scene/console-scene.md` §5.2 CON-02（九场景原文）。
- Produces: 走查证据 + 交付说明（改动清单/接口/迁移风险/已验证与未覆盖），PR 就绪但**不合并**（AGENTS.md：merge 需用户显式确认）。

- [ ] **Step 1: 起后端并确认迁移**

```powershell
cd console/backend
python -m alembic upgrade head          # 0005 → 0006
python -m alembic current               # 期望 0006 (head)
python -m uvicorn app.main:app --port 8000
```

另开终端探活（用户交付要求：先确认 :8000 在监听再谈联调）：

```powershell
curl.exe -s http://127.0.0.1:8000/api/v1/health
```

Expected: `{"code":0,...}`。若目标机器上 :8000 已被既有容器占用，先确认它就是本项目 console 后端（版本含 0006），否则停掉再起。
**存量红线回归**：登录取 token 后 `GET /api/v1/instances`（不带 cluster 参数）与改造前逐字段一致；单实例 legacy 部署下响应不含 `machines_total` 等新键（`optional`），前端渲染 DASH。

- [ ] **Step 2: 起前端**

```powershell
cd console/frontend
npm run dev                              # Vite，默认端口以启动日志为准（约定 :3000）
```

用 admin 账号登录控制台，进入「调度 → 集群总览」（路由 `overview`）。

- [ ] **Step 3: CON-02 九场景逐条走查**

对照 `docs/scene/console-scene.md` §5.2.1 逐条执行并截图到 `qa-artifacts-archive/cluster-overview/`（命名 `scene-<n>-<slug>.png`）：

1. **KPI 四卡联动**：切到另一集群，机器/实例/活跃会话/错误率四卡数值随 `cluster` 参数刷新；切到 machines=0 的空集群显示 `0 / 0` 无 NaN；错误率无样本时为 `—`（不是 0），有故障时警告色。
2. **集群表**：表头 集群/registry/策略/机器/实例/状态/操作 齐全；当前行有「当前」标签且无「切换」按钮；非当前行有 切换/编辑/删除；策略列显示 i18n 文案（最少会话/轮询/最低延迟）；有 note 的行下方出现小字。
3. **新增校验**：名称留空报「必填 · 名称」且不关窗；`Bad_Name!` 报名称格式；重名报「集群名已存在」（回填到名称字段）；合法保存后 toast/弹窗关闭/下拉含新集群且视图自动切入。
4. **registry 校验**：留空报必填；`consul://host`（无端口）报格式；与其他集群重复报重复；`CONSUL://Host:8500` 大写合法。
5. **编辑**：名称禁用；registry/policy/note 回填并可保存；保存后表格与顶栏下拉同步更新。
6. **删除**：当前集群/最后一个集群被服务端拒绝（`last_cluster`/`cluster_not_empty` 文案正确）；有 confirm 确认；删除成功后 `clusterStore.load()` 回落逻辑生效。
7. **顶栏等效切换**：顶栏集群下拉与表内「切换」按钮都走 `POST /clusters/{name}/switch`；`param_audit` 里能看到 `cluster.switch` 成功与失败记录（对不存在的集群手动发一次 switch 验证失败也留痕，前端不切换）。
8. **拓扑下钻**：四层 集群→LB→机器→实例 渲染；机器节点点击进入部署参数页且 URL 带 `?host=`；过滤条可关闭恢复全量。
9. **图例与最近事件**：图例四项渲染；事件表恰好 4 条、按时间倒序、action 保持代码态（`cluster.create` 等不翻译）、失败行显示 errorCode；中英文切换后除代码态外全部翻译（i18n parity）。

另加降级态抽查：停掉后端 → 页面出现 ErrorBanner 且不白屏；重启后端 → 轮询/重载恢复。

- [ ] **Step 4: 审计与权限抽查**

operator 账号登录：能查询/切换，「新增/编辑/删除」按钮不渲染，直接 `POST /api/v1/clusters` 返回 403 且**有审计**（result=error, error_code=forbidden 不成立——403 发生在依赖注入层，无操作人解析失败问题；确认 `require_permission` 抛的 403 走 api_error_handler 正常返回）。未登录 `POST /clusters/default/switch` 返回 401 且审计表**无**新增行（spec §4.3）。

- [ ] **Step 5: 收尾提交与交付说明**

```bash
git status   # 确认 qa-artifacts-archive/、dist/ 未被 add
git log --oneline main..HEAD
```

推送分支并按 AGENTS.md 开 PR（分支/标题不含 `codex`；只报告状态，不合并）。交付说明含：

- 改动清单（后端 T1-T5 文件 + 前端 T6-T12 文件）
- 新接口一览（`/clusters` CRUD/switch/events、`/instances?cluster=`）
- 迁移注意事项：0006 可重入 seed；已有部署滚动升级需先 `alembic upgrade head` 再切新镜像；回滚有序（downgrade 反序 DROP）
- 已验证（九场景 + 存量红线 + 静态闸）与未覆盖（多浏览器视觉、真实 Consul 联通性）

---

## Self-Review（计划完成后按 writing-plans 三项检查执行）

1. **Spec coverage**：spec §3（集群/机器实体）→ T1/T5；§4.1（校验）→ T3/T8；§4.2（端点）→ T4/T6；§4.3（审计，失败也记）→ T4/T7/T14-Step3(7)；§4.4（权限码）→ T2/T7；§5.1（sessionStorage/switch）→ T6/T7/T11；§5.2（五段页面）→ T8-T11/T14；§6（machines 最小增量）→ T12；口径④（null/DASH/不重复计数）→ T5/T10/T14-Step3(1)。
2. **Placeholder 扫描**：无 TBD/“同理”/裸“添加校验”；所有测试与实现均给出全文。
3. **类型一致性**：`clustersApi.switchTo`（T6）= store.switchTo 调用（T7）= 顶栏调用（T11）；`ClusterRow` 字段（T6）与后端 `_row_payload`（T4）逐字一致；`overview.topology.*Layer` 键（T10）与 TopoChart 模板生成式（T9）一致；`visibleInstances`（T12）与契约测试字符串一致。
