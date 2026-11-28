# console 设置页对齐原型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/settings` 前台设置页改成与原型 `console/design/console-refactor-demo.html#/settings` 逐像素一致，并在后端新增「前台设置」的存储与读写端点，使保存 → 刷新 → 读取的链路真正闭合。

**Architecture:** 后端新增一张全局表 `param_front_setting`（键=参数名，值=字符串+类型）与一个字段目录（`front_setting_catalog.FIELD_CATALOG`，7 条前台热更字段，含 patch 路径、白名单可下发标记、别名消歧用的 `patchOwner`）。前端 `SettingsView.vue` 按原型的 7 块结构重写，字段目录与已存值全部来自后端，前端只做渲染与校验提示；热更下发复用既有 `POST /api/v1/sessions/update`（白名单由后端裁剪）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic（SQLite/Postgres 双方言）；Vue 3 `<script setup>` + TypeScript + Pinia + vue-i18n v9 + Less。

**Spec:** `docs/superpowers/specs/2026-11-28-console-settings-align-design.md`（已批准，用户拍板 A/A/A）

> **本计划已做过一轮"实现者视角"核对**（38 项逐条比对真实仓库），修正了 14 处会卡住实现的问题。改动要点见文末 §核对修正记录。**照抄代码前请先读那 14 条。**

## Global Constraints

以下约束适用于**每一个** task，不再逐条重复：

- **前端样式 token**：只用 `var(--s2s-*)`（shell token）与 `var(--voice-*)`（voice token），**禁止裸 hex**（`src/styles/hex-ban.spec.ts` 强制清单含 `src/styles/**` 与 `src/components/proto/**`）。
- **原型 class 名逐字照抄**：`card` `chips` `chip` `dot` `tag` `btn` `primary` `tbl` `tscroll` `mono` `note` `rowline` `spacer` `muted` `page-head` `set-grid` `sfield` `sw` `ta-wrap` `fin` `counter` `set-actions` `tpl-banner` `tpl-src` `switch` `on` `rec` `rec-top` `rname` `p-risk` `smart-log` `field` `fhint`。**不新增原型里没有的 class 名**（可用 `card--bar` 这类修饰类）。
- **i18n key 不得含点号字面量**：vue-i18n v9 按 `.` 拆路径，`t('set.reset.body')` 会去找 `set → reset → body`，而 `reset` 是字符串 → 解析失败。**任何 key 路径都不能穿过一个字符串叶子**。因此：
  - 用 `set.reset.label` / `set.reset.body`（`reset` 必须是对象），**不要** `set.reset` + `set.reset.body` 两个平铺键。
  - 用 `tpl.field.thresh.label` / `tpl.field.thresh.hint`（`thresh` 必须是对象）。
  - 用 `tpl.save.label` / `tpl.save.hint`、`tpl.saveAs.label` / `tpl.saveAs.hint` / `tpl.saveAs.desc`。
  - 用 `tpl.toast.hot` / `set.toast.saved` / `set.toast.reset`（**不是**根级 `toast.*`——两个 locale 的 index 里都没有根级 `toast` 模块）。
  - 后端下发的 `labelKey`/`hintKey` 必须是**能解析的嵌套路径**。
- **zh-CN 与 en-US 的扁平 key 集合必须完全相同且都非空**（`src/i18n/i18n.spec.ts`）。
- **前端 i18n 模块在根级合并**（`src/i18n/locales/*/index.ts` 的 `export default { … }` 是平铺的），所以新建 `tpl.ts` / `set.ts` 模块即得根级 `tpl.*` / `set.*`；**不要**把它们塞进 `settings` 模块。
- **审计只记字段名不记值**（`param_audit.fields`）。
- **成功信封**：后端返回 `{code,message,data}`；前端 `api.get/post/put` 已自动拆包（`src/api/client.ts:96-99`），调用方只看到 `data`。baseURL 是 `/api/v1`。
- **不新增前端依赖**；本页不新增 ant-design-vue 组件（确认弹窗复用既有 `src/components/ConfirmDialog.vue`，它内部用 antd 是仓库既有事实）。
- **提交**：本仓库当前工作区有大量与本次无关的未提交改动。**除非用户明确要求，不执行 `git commit`**；每个 task 末尾的"检查点"步骤只跑测试。

## Review Focus

以下五类输入/故障最可能咬到真实用户。**每一条都要有测试钉住**（测试写在哪一步见各 task）：

1. **同一条 patch path 的两个字段互相冲掉**：`init_chat_prompt` 与 `instructions` 都是 `instructions`；`qwen3_tts_speaker` 与 `voice` 都是 `audio.output.voice`。用户只填了 `instructions`（人设留空）时，下发的 `instructions` 必须是用户填的值，不能是空串；两个都填时按别名优先（`init_chat_prompt` 赢）且被覆盖的那个要有提示。
2. **白名单外字段（音色）**：`voice` / `qwen3_tts_speaker` 的 patch `audio.output.voice` 不在热更白名单 → **保存必须成功**，但下发必须被拒并灰显提示「非白名单」，不能整批 400。
3. **提示词超 2000 字**：后端落库 400 拒绝且整批不落库；前端字数计数与后端上限一致（2000）。
4. **下发失败但已落库**：pipeline 不可达（502）时，设置**已经存进库了**，不能回滚；页面要分开提示「已保存」与「下发失败」。
5. **operator 看不到「保存为模板」**：`POST /api/v1/templates` 需 admin-only 权限码，operator 面前该按钮必须隐藏（不是点了报 403）。

---

### Task 1: 后端存储层（模型 + 迁移 0023 + 中文注释）

**Files:**
- Create: `console/backend/app/models/front_setting.py`
- Create: `console/backend/alembic/versions/0023_front_settings.py`
- Modify: `console/backend/app/models/__init__.py`
- Modify: `console/backend/app/models/comments.py`
- Test: `console/backend/tests/unit/test_front_setting_model.py`（新建）

**Interfaces:**
- Consumes: `app.db.base.Base`、`app.db.base.utcnow`（**是可调用函数**，不是常量）
- Produces: `ParamFrontSetting`（表 `param_front_setting`），列 `id / config_key / value / value_type / updated_by / updated_at`；唯一约束名 `uq_param_front_setting_key`

> ⚠️ **迁移号是 0023 不是 0022**：`alembic/versions/0022_tools.py` 已占用（`revision="0022_tools"`, `down_revision="0021_session_clips"`），当前 head 是它。用 0022 会造成 **alembic 双 head**，`alembic upgrade head` 直接报错，`tests/unit/test_schema_sql.py` 的 `_head()` 也会抛。

- [ ] **Step 1: 写失败测试**

新建 `console/backend/tests/unit/test_front_setting_model.py`：

```python
from sqlalchemy import UniqueConstraint

from app.models.front_setting import ParamFrontSetting


def test_table_and_columns():
    table = ParamFrontSetting.__table__
    assert table.name == "param_front_setting"
    assert [c.name for c in table.columns] == [
        "id", "config_key", "value", "value_type", "updated_by", "updated_at",
    ]


def test_config_key_is_unique():
    constraints = [
        c for c in ParamFrontSetting.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert any(c.name == "uq_param_front_setting_key" for c in constraints)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/unit/test_front_setting_model.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.models.front_setting'`

- [ ] **Step 3: 实现模型**

新建 `console/backend/app/models/front_setting.py`：

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamFrontSetting(Base):
    """前台设置：对话态热更参数的账号级取值（spec 2026-11-28 §后端 1）。

    全局一份，不按机器分列：语义对齐原型的 `state.settings` —— 改一次全站生效。
    值按字符串存（`value` + `value_type` 配对），与 `param_config` 同一思路；
    这里放宽到 2048 以容下 2000 字的提示词。
    """

    __tablename__ = "param_front_setting"
    __table_args__ = (UniqueConstraint("config_key", name="uq_param_front_setting_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 列名不叫 key：SQLite 把 KEY 当保留字（见 param_config 的同款说明）。
    config_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="str")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
```

- [ ] **Step 4: 注册模型 + 写迁移**

`console/backend/app/models/__init__.py`：加 `from .front_setting import ParamFrontSetting`（按字母序插在 `.comments` 与 `.lb` 之间），并把 `"ParamFrontSetting"` 加进 `__all__`（插在 `"ParamDraft"` 与 `"ParamInstance"` 之间）。

新建 `console/backend/alembic/versions/0023_front_settings.py`：

```python
"""前台设置表（对话态热更参数的账号级取值）。

Revision ID: 0023_front_settings
Revises: 0022_tools
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0023_front_settings"
down_revision = "0022_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_front_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(2048), server_default="", nullable=False),
        sa.Column("value_type", sa.String(16), server_default="str", nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("config_key", name="uq_param_front_setting_key"),
    )


def downgrade() -> None:
    op.drop_table("param_front_setting")
```

- [ ] **Step 5: 补中文注释**

`console/backend/app/models/comments.py`：
- `TABLE_COMMENTS`（`dict[str, str]`）加 `"param_front_setting": "前台设置：对话态热更参数的账号级取值，全局一份，不按机器分列",`
- `COLUMN_COMMENTS`（`dict[str, dict[str, str]]`）加同名的 dict，**6 个列一个不能少也不能多**（`tests/unit/test_comments.py:25-31` 断言注释集合恰好等于模型列集合）：`id` / `config_key` / `value` / `value_type` / `updated_by` / `updated_at`。
- 注释里**不能出现单引号和 `TIMESTAMP`**（同文件 37-45 行的既有约束）。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/unit/test_front_setting_model.py tests/unit/test_comments.py -v`
Expected: PASS

- [ ] **Step 7: 重生成 schema SQL 并跑 drift guard**

Run: `cd console/backend && .venv\Scripts\python.exe scripts\dump_schema_sql.py`
（脚本**不接受参数**，工作目录必须是 `console/backend`；两个方言都写：`alembic/sql/init-sqlite.sql` 与 `init-postgresql.sql`。）
Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/unit/test_schema_sql.py -v`
Expected: PASS

- [ ] **Step 8: 检查点（不自动提交）**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/unit -q`
Expected: 全部 PASS

---

### Task 2: 字段目录与白名单判定（后端唯一真源）

**Files:**
- Create: `console/backend/app/services/front_setting_catalog.py`
- Modify: `console/backend/app/services/hot_update_service.py`
- Test: `console/backend/tests/unit/test_front_setting_catalog.py`（新建）

**Interfaces:**
- Consumes: `app.services.template_service.HOT_FIELDS`（`dict[str, str]`）；`app.services.hot_update_service.WHITELIST`
- Produces:
  - `hot_update_service.hot_whitelisted(path: str) -> bool`
  - `front_setting_catalog.FrontField`（TypedDict）
  - `front_setting_catalog.FIELD_CATALOG: list[FrontField]` —— 7 条，顺序固定
  - `front_setting_catalog.FIELD_BY_KEY: dict[str, FrontField]`
  - `front_setting_catalog.defaults() -> dict[str, Any]`
  - `front_setting_catalog.field_out(field: FrontField) -> dict`

> ⚠️ **`def` 是 Python 关键字**，TypedDict 里不能写 `def: Any`，构造函数里也不能写 `def=`。Python 侧一律用 `default`，JSON 出参也是 `default`（前端 `FrontField.default`）。**不要**做 `def` → `default` 的出参映射，多一层就多一个能漂移的地方。

- [ ] **Step 1: 写失败测试**

新建 `console/backend/tests/unit/test_front_setting_catalog.py`：

```python
from app.services import front_setting_catalog as cat
from app.services import hot_update_service
from app.services.template_service import HOT_FIELDS


def test_catalog_has_the_seven_front_fields_in_order():
    assert [f["key"] for f in cat.FIELD_CATALOG] == [
        "thresh", "min_silence_ms", "qwen3_asr_language",
        "init_chat_prompt", "instructions", "qwen3_tts_speaker", "voice",
    ]


def test_every_patch_agrees_with_the_template_alias_table():
    for field in cat.FIELD_CATALOG:
        assert field["patch"] == HOT_FIELDS[field["key"]]


def test_whitelist_marks_the_four_pushable_paths():
    assert hot_update_service.hot_whitelisted("audio.input.turn_detection.threshold")
    assert hot_update_service.hot_whitelisted("audio.input.turn_detection.silence_duration_ms")
    assert hot_update_service.hot_whitelisted("audio.input.transcription.language")
    assert hot_update_service.hot_whitelisted("instructions")
    assert not hot_update_service.hot_whitelisted("audio.output.voice")
    assert not hot_update_service.hot_whitelisted("model")


def test_patch_owner_resolves_the_two_shared_paths():
    assert cat.FIELD_BY_KEY["init_chat_prompt"]["patchOwner"] == "init_chat_prompt"
    assert cat.FIELD_BY_KEY["instructions"]["patchOwner"] == "init_chat_prompt"
    assert cat.FIELD_BY_KEY["qwen3_tts_speaker"]["patchOwner"] == "qwen3_tts_speaker"
    assert cat.FIELD_BY_KEY["voice"]["patchOwner"] == "qwen3_tts_speaker"


def test_label_and_hint_keys_are_root_level():
    for field in cat.FIELD_CATALOG:
        for key in (field["labelKey"], field["hintKey"]):
            assert key.startswith(("tpl.", "set.", "settings.f.")), key
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/unit/test_front_setting_catalog.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.front_setting_catalog'`

- [ ] **Step 3: 给 hot_update_service 加白名单判定**

在 `console/backend/app/services/hot_update_service.py` 的 `prune()` 之后加（`Any` 该文件第 10 行已导入）：

```python
def hot_whitelisted(path: str) -> bool:
    """True when `path` survives A.9's whitelist.

    Same tree as `prune`, but answering for one dotted path instead of a
    payload: the front-office settings page needs to know which fields it
    may push to live sessions before it offers to push them.
    """
    node: Any = WHITELIST
    for part in path.split("."):
        if node is None:
            return True
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return node is None
```

> `WHITELIST` 的实际形状是
> `{"instructions": None, "extensions": None, "audio": {"input": {"turn_detection": None, "transcription": {"language": None}}}}`
> —— 叶子是 `None`（整棵子树放行），中间层是 dict。所以 `audio.input.turn_detection` 为 True（子树放行），
> `audio.input.transcription` 为 False（分支不是终点），与 `prune` 的 `_walk` 语义一致。

- [ ] **Step 4: 实现字段目录**

新建 `console/backend/app/services/front_setting_catalog.py`：

```python
"""前台设置字段目录（spec 2026-11-28 §后端 2）。

镜像原型 `console/design/console-refactor-demo.html` 的 `PARAM_TEMPLATES`
中 surface=front|both 的 7 条。它是**前端渲染表单的唯一依据**：label/hint
给的是 i18n key（前端 `t()` 解析），type/min/max/step/opts 决定控件，
patch 是 `session.update` 的下发路径。

能不能即时下发由 `hot_update_service.WHITELIST` 判定（`hot` 字段），
不在这里重复编码 —— 白名单只有一份。

`patchOwner` 解决原型照搬带来的坑：`init_chat_prompt` 与 `instructions`
共用 `instructions` 这条路径，`qwen3_tts_speaker` 与 `voice` 共用
`audio.output.voice`。owner = 该路径上目录顺序里的第一个 key（下发时
owner 优先，同组其余值只提示"被覆盖"，不丢数据）。

`labelKey` / `hintKey` 必须是 vue-i18n 能解析的**嵌套路径**，且任何一段
都不能是字符串叶子（否则 `t()` 会解析失败）。
"""

from __future__ import annotations

from typing import Any, TypedDict, cast

from app.services.hot_update_service import hot_whitelisted
from app.services.template_service import HOT_FIELDS

PLATFORMS = ["gpu", "npu", "amd", "cpu"]
TEXTAREA_MAX = 2000


class FrontField(TypedDict):
    key: str
    group: str
    type: str
    hot: bool
    patch: str
    catalogKey: str
    src: str
    default: Any
    min: float | None
    max: float | None
    step: float | None
    opts: Any
    labelKey: str
    hintKey: str
    platform: list[str]
    patchOwner: str


_RAW: list[dict[str, Any]] = [
    {
        "key": "thresh", "group": "vad", "type": "number",
        "min": 0, "max": 1, "step": 0.05, "default": 0.6,
        "catalogKey": "vad.thresh", "src": "§2.2 · vad_arguments.py:22",
        "labelKey": "tpl.field.thresh.label", "hintKey": "tpl.field.thresh.hint",
    },
    {
        "key": "min_silence_ms", "group": "vad", "type": "number",
        "min": 0, "max": 5000, "step": 50, "default": 450,
        "catalogKey": "vad.min_silence_ms", "src": "§2.2 · vad_arguments.py:34",
        "labelKey": "tpl.field.min_silence_ms.label",
        "hintKey": "tpl.field.min_silence_ms.hint",
    },
    {
        "key": "qwen3_asr_language", "group": "stt", "type": "select",
        "opts": ["auto", "zh", "en"], "default": "auto",
        "catalogKey": "stt.qwen3_asr_language", "src": "§3.2 · §7.5",
        "labelKey": "tpl.field.qwen3_asr_language.label",
        "hintKey": "tpl.field.qwen3_asr_language.hint",
    },
    {
        "key": "init_chat_prompt", "group": "llm", "type": "textarea",
        "default": "", "catalogKey": "llm.init_chat_prompt", "src": "§4.2 · §7.5",
        "labelKey": "tpl.field.init_chat_prompt.label",
        "hintKey": "settings.f.init_chat_prompt",
    },
    {
        "key": "instructions", "group": "llm", "type": "textarea",
        "default": "", "catalogKey": "llm.instructions", "src": "§7.5 · 客户端首帧",
        "labelKey": "tpl.field.instructions.label", "hintKey": "settings.f.instructions",
    },
    {
        "key": "qwen3_tts_speaker", "group": "tts", "type": "select",
        "opts": "voices", "default": "", "catalogKey": "tts.qwen3_tts_speaker",
        "src": "§5.2 · §7.5",
        "labelKey": "tpl.field.qwen3_tts_speaker.label",
        "hintKey": "tpl.field.qwen3_tts_speaker.hint",
    },
    {
        "key": "voice", "group": "tts", "type": "select",
        "opts": "voices", "default": "", "catalogKey": "tts.voice", "src": "§7.5 · 客户端首帧",
        "labelKey": "tpl.field.voice.label", "hintKey": "settings.f.voice",
    },
]


def _build() -> list[FrontField]:
    owners: dict[str, str] = {}
    for raw in _RAW:
        patch = HOT_FIELDS[raw["key"]]
        owners.setdefault(patch, raw["key"])
    out: list[FrontField] = []
    for raw in _RAW:
        patch = HOT_FIELDS[raw["key"]]
        entry = {
            "key": raw["key"], "group": raw["group"], "type": raw["type"],
            "hot": hot_whitelisted(patch), "patch": patch,
            "catalogKey": raw["catalogKey"], "src": raw["src"],
            "default": raw["default"],
            "min": raw.get("min"), "max": raw.get("max"), "step": raw.get("step"),
            "opts": raw.get("opts"), "labelKey": raw["labelKey"], "hintKey": raw["hintKey"],
            "platform": list(PLATFORMS), "patchOwner": owners[patch],
        }
        out.append(cast(FrontField, entry))
    return out


FIELD_CATALOG: list[FrontField] = _build()
FIELD_BY_KEY: dict[str, FrontField] = {field["key"]: field for field in FIELD_CATALOG}


def defaults() -> dict[str, Any]:
    """默认值快照：未存过的键回落到这里。"""
    return {field["key"]: field["default"] for field in FIELD_CATALOG}


def field_out(field: FrontField) -> dict[str, Any]:
    """出参（键名与 FrontField 一致，不再改名）。"""
    return dict(field)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/unit/test_front_setting_catalog.py tests/unit/test_hot_update_whitelist.py -v`
Expected: PASS

- [ ] **Step 6: 检查点（不自动提交）**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/unit -q`
Expected: 全部 PASS

---

### Task 3: 设置的读写端点（服务层 + 仓储 + 路由 + 权限码）

**Files:**
- Create: `console/backend/app/repositories/front_setting_repository.py`
- Create: `console/backend/app/schemas/settings.py`
- Create: `console/backend/app/services/front_setting_service.py`
- Create: `console/backend/app/routers/settings.py`
- Modify: `console/backend/app/core/permissions.py`
- Modify: `console/backend/app/core/router_registry.py`
- Test: `console/backend/tests/integration/test_settings_api.py`（新建）

**Interfaces:**
- Consumes: `front_setting_catalog.FIELD_CATALOG / FIELD_BY_KEY / defaults / field_out`；`hot_update_service.hot_whitelisted`；`AuditRepository.record`；`app.schemas.common.ok` / `iso_utc`
- Produces:
  - `GET /api/v1/settings/front` → `{fields, values, defaults, updatedAt, updatedBy}`
  - `PUT /api/v1/settings/front`（body `{values: dict[str, Any]}`）→ `{fields, values, defaults, updatedAt, updatedBy, applied}`
  - `POST /api/v1/settings/front/reset` → `{values, applied: [], updatedAt: null, updatedBy: null}`
  - 权限码 `console:settings:query` / `console:settings:write`（都是 admin + operator）

> ⚠️ **分层约定**：本仓是「service 层抛 `ValueError` 子类 → router 层映射成 `ApiError`」
> （`app/services/config_service.py:20-22` 的 `ConfigError` + `app/routers/config.py:60-61`）。
> 按这个约定写，别在 service 里直接抛 `ApiError`。
>
> ⚠️ **`ApiError` 的 docstring 明写 "Never carries input values"** —— 错误消息**不许回显用户输入**
> （不要 `f"收到 {raw!r}"`）。
>
> ⚠️ **时间戳走 `app.schemas.common.iso_utc()`**（带 `Z` 后缀）；`isoformat()` 会丢时区。

- [ ] **Step 1: 写失败测试**

新建 `console/backend/tests/integration/test_settings_api.py`。**`auth` / `operator_auth` 这两个 fixture 全仓不存在**
（只有 `test_templates_api.py:29-33` 里的 `_auth()` 普通函数），所以本文件要自己造：

```python
"""前台设置 HTTP 契约（spec 2026-11-28 §后端 3）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.models.front_setting import ParamFrontSetting
from app.models.param_audit import ParamAudit
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
    UserRepository(db_session).create("op", hash_password("correct-horse"), "operator")
    yield TestClient(app)


def _auth(client: TestClient, username: str = "alice") -> dict:
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


@pytest.fixture
def auth(client):
    return _auth(client)


@pytest.fixture
def operator_auth(client):
    return _auth(client, "op")
```

再写这些用例：

```python
def test_get_front_returns_the_seven_fields_and_defaults(client, auth):
    resp = client.get("/api/v1/settings/front", headers=auth)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [f["key"] for f in data["fields"]] == [
        "thresh", "min_silence_ms", "qwen3_asr_language",
        "init_chat_prompt", "instructions", "qwen3_tts_speaker", "voice",
    ]
    assert data["defaults"]["thresh"] == 0.6
    assert data["values"]["thresh"] == 0.6
    assert data["updatedAt"] is None


def test_put_stores_values_and_audits_only_keys(client, auth, db_session):
    resp = client.put(
        "/api/v1/settings/front",
        headers=auth,
        json={"values": {"thresh": 0.8, "init_chat_prompt": "你是客服助手"}},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["values"]["thresh"] == 0.8
    assert data["applied"] == ["init_chat_prompt", "thresh"]
    assert data["updatedAt"] is not None
    rows = db_session.query(ParamFrontSetting).all()
    assert {row.config_key for row in rows} == {"thresh", "init_chat_prompt"}
    audit = db_session.query(ParamAudit).filter(ParamAudit.action == "settings.front.update").one()
    assert sorted(audit.fields) == ["init_chat_prompt", "thresh"]


def test_put_rejects_the_whole_batch_on_a_bad_value(client, auth, db_session):
    resp = client.put(
        "/api/v1/settings/front",
        headers=auth,
        json={"values": {"thresh": "not-a-number"}},
    )
    assert resp.status_code == 400
    assert db_session.query(ParamFrontSetting).count() == 0


def test_put_rejects_unknown_keys(client, auth):
    resp = client.put("/api/v1/settings/front", headers=auth, json={"values": {"nope": 1}})
    assert resp.status_code == 400


def test_put_rejects_a_prompt_over_two_thousand_characters(client, auth):
    resp = client.put(
        "/api/v1/settings/front",
        headers=auth,
        json={"values": {"init_chat_prompt": "x" * 2001}},
    )
    assert resp.status_code == 400


def test_put_rejects_a_value_out_of_range(client, auth):
    resp = client.put("/api/v1/settings/front", headers=auth, json={"values": {"thresh": 5}})
    assert resp.status_code == 400


def test_put_rejects_a_value_outside_the_enum(client, auth):
    resp = client.put(
        "/api/v1/settings/front", headers=auth, json={"values": {"qwen3_asr_language": "fr"}}
    )
    assert resp.status_code == 400


def test_null_value_drops_the_row_and_falls_back_to_the_default(client, auth, db_session):
    client.put("/api/v1/settings/front", headers=auth, json={"values": {"thresh": 0.9}})
    resp = client.put("/api/v1/settings/front", headers=auth, json={"values": {"thresh": None}})
    assert resp.status_code == 200
    assert resp.json()["data"]["values"]["thresh"] == 0.6
    assert db_session.query(ParamFrontSetting).count() == 0


def test_reset_clears_every_row(client, auth, db_session):
    client.put("/api/v1/settings/front", headers=auth, json={"values": {"thresh": 0.9}})
    resp = client.post("/api/v1/settings/front/reset", headers=auth)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["values"]["thresh"] == 0.6
    assert data["updatedAt"] is None
    assert db_session.query(ParamFrontSetting).count() == 0


def test_operator_may_read_and_write(client, operator_auth):
    assert client.get("/api/v1/settings/front", headers=operator_auth).status_code == 200
    assert client.put(
        "/api/v1/settings/front", headers=operator_auth, json={"values": {"thresh": 0.7}}
    ).status_code == 200


def test_anonymous_is_rejected(client):
    assert client.get("/api/v1/settings/front").status_code == 401
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/integration/test_settings_api.py -v`
Expected: FAIL —— 404（路由不存在）

- [ ] **Step 3: 写请求模型**

新建 `console/backend/app/schemas/settings.py`：

```python
"""前台设置的读写模型（spec 2026-11-28 §后端 3）。

值的类型是 `Any`：服务端按字段目录的类型强转（与 `app/config/_schema.py` 的
`coerce()` 同一套取值域校验口径，但类型由字段目录决定而非 `ConfigItem`），
非法值 400 且整批不落库。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FrontSettingsUpdate(BaseModel):
    """`values` 是部分 upsert；值为 `null` 表示回落默认（删行）。"""

    values: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: 写仓储**

新建 `console/backend/app/repositories/front_setting_repository.py`：

```python
"""前台设置的读写（行数极小，一次全取）。"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.front_setting import ParamFrontSetting


class FrontSettingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def all(self) -> list[ParamFrontSetting]:
        return list(self.session.scalars(select(ParamFrontSetting)))

    def get(self, config_key: str) -> ParamFrontSetting | None:
        return self.session.scalar(
            select(ParamFrontSetting).where(ParamFrontSetting.config_key == config_key)
        )

    def upsert(self, *, config_key: str, value: str, value_type: str, actor: str) -> ParamFrontSetting:
        row = self.get(config_key)
        if row is None:
            row = ParamFrontSetting(config_key=config_key)
            self.session.add(row)
        row.value = value
        row.value_type = value_type
        row.updated_by = actor
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete(self, config_key: str) -> bool:
        row = self.get(config_key)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True

    def clear(self) -> int:
        result = self.session.execute(delete(ParamFrontSetting))
        self.session.commit()
        return int(result.rowcount or 0)
```

- [ ] **Step 5: 写服务层**

新建 `console/backend/app/services/front_setting_service.py`：

```python
"""前台设置的读写与校验（spec 2026-11-28 §后端 3）。

校验口径与 `app/services/config_service.py` 一致：**任一项非法就整批拒绝**，
一项都不落库。值按字段目录的类型强转，类型由目录决定，不由客户端声明。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories.audit_repository import AuditRepository
from app.repositories.front_setting_repository import FrontSettingRepository
from app.schemas.common import iso_utc
from app.services.front_setting_catalog import (
    FIELD_BY_KEY,
    FIELD_CATALOG,
    TEXTAREA_MAX,
    defaults,
    field_out,
)
from app.services.hot_update_service import hot_whitelisted

VALUE_TYPES = {"number": "float", "select": "str", "textarea": "str", "text": "str", "switch": "bool"}


class FrontSettingError(ValueError):
    """设置值不合法。router 层映射成 400。"""


def _coerce(key: str, raw: Any) -> tuple[str, str]:
    """返回值字符串与它的类型；不合法抛 FrontSettingError。"""
    field = FIELD_BY_KEY[key]
    kind = field["type"]
    if kind == "number":
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise FrontSettingError(f"{key} 期望数值") from exc
        if field["min"] is not None and number < field["min"]:
            raise FrontSettingError(f"{key} 不得小于 {field['min']}")
        if field["max"] is not None and number > field["max"]:
            raise FrontSettingError(f"{key} 不得大于 {field['max']}")
        return str(number), "float"
    if kind == "switch":
        text = str(raw).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return "true", "bool"
        if text in ("0", "false", "no", "off", ""):
            return "false", "bool"
        raise FrontSettingError(f"{key} 期望布尔值")
    text = "" if raw is None else str(raw)
    if kind == "select":
        options = field["opts"]
        if isinstance(options, list) and options and text not in options:
            raise FrontSettingError(f"{key} 只能是 {', '.join(options)} 之一")
    if kind == "textarea" and len(text) > TEXTAREA_MAX:
        raise FrontSettingError(f"{key} 不得长于 {TEXTAREA_MAX} 字")
    return text, VALUE_TYPES[kind]


def _cast_back(stored: dict[str, str]) -> dict[str, Any]:
    """把库里的字符串按目录类型还原成 JSON 值。"""
    out: dict[str, Any] = {}
    for key, value in stored.items():
        field = FIELD_BY_KEY.get(key)
        if field is None:
            continue
        if field["type"] == "number":
            try:
                out[key] = float(value)
            except ValueError:
                out[key] = value
        elif field["type"] == "switch":
            out[key] = value.strip().lower() in ("1", "true", "yes", "on")
        else:
            out[key] = value
    return out


def read_front(db: Session) -> dict[str, Any]:
    repo = FrontSettingRepository(db)
    rows = repo.all()
    stored = {row.config_key: row.value for row in rows}
    latest = max(rows, key=lambda row: row.updated_at) if rows else None
    merged = defaults()
    merged.update(_cast_back(stored))
    return {
        "fields": [field_out(field) for field in FIELD_CATALOG],
        "values": merged,
        "defaults": defaults(),
        "updatedAt": iso_utc(latest.updated_at) if latest else None,
        "updatedBy": latest.updated_by if latest else None,
    }


def update_front(db: Session, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
    repo = FrontSettingRepository(db)
    # 先整批校验：任一项非法就整批拒绝，一项都不落库。
    planned: list[tuple[str, str, str]] = []
    for key, raw in payload.items():
        if key not in FIELD_BY_KEY:
            raise FrontSettingError(f"未知的设置项 {key}")
        if raw is None:
            planned.append((key, "", ""))  # 删行
            continue
        value, value_type = _coerce(key, raw)
        planned.append((key, value, value_type))
    for key, value, value_type in planned:
        if value_type == "":
            repo.delete(key)
        else:
            repo.upsert(config_key=key, value=value, value_type=value_type, actor=actor)
    applied = sorted(
        key for key, _, value_type in planned
        if value_type != "" and hot_whitelisted(FIELD_BY_KEY[key]["patch"])
    )
    AuditRepository(db).record(
        actor=actor, role="", action="settings.front.update", profile="console",
        fields=sorted(payload.keys()),
    )
    snapshot = read_front(db)
    snapshot["applied"] = applied
    return snapshot


def reset_front(db: Session, *, actor: str) -> dict[str, Any]:
    FrontSettingRepository(db).clear()
    AuditRepository(db).record(
        actor=actor, role="", action="settings.front.reset", profile="console", fields=[],
    )
    return {
        "values": defaults(),
        "applied": [],
        "updatedAt": None,
        "updatedBy": None,
    }
```

- [ ] **Step 6: 写路由**

新建 `console/backend/app/routers/settings.py`：

```python
"""前台设置读写接口（spec 2026-11-28 §后端 3）。

- `GET  /api/v1/settings/front`：字段目录 + 已存值（未存过的回落默认）。
- `PUT  /api/v1/settings/front`：部分 upsert；值为 null 表示回落默认。
- `POST /api/v1/settings/front/reset`：清空所有行，回到默认值。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.settings import FrontSettingsUpdate
from app.services import front_setting_service
from app.services.front_setting_service import FrontSettingError

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("/front")
def get_front(db: DbSession, user: CurrentUser = Depends(require_permission("console:settings:query"))):
    return ok(front_setting_service.read_front(db))


@router.put("/front")
def put_front(
    payload: FrontSettingsUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:settings:write")),
):
    try:
        result = front_setting_service.update_front(db, payload.values, actor=user.username)
    except FrontSettingError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc
    return ok(result)


@router.post("/front/reset")
def reset_front(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:settings:write")),
):
    return ok(front_setting_service.reset_front(db, actor=user.username))
```

> ⚠️ `require_permission` 在 **`app.core.permissions`**，不在 `app.core.security`
> （后者只有 `require_user / require_admin / require_operator`）。`CurrentUser` 在
> `app.core.security`，字段是 `username` / `role`。

- [ ] **Step 7: 注册权限码与路由**

`console/backend/app/core/permissions.py` 的 `PERMISSION_ROLES`（`dict[str, frozenset[str]]`）里加两行：

```python
    # 前台设置（spec 2026-11-28）：读与写都开放给操作员，与对话态热更同级。
    "console:settings:query": frozenset({"admin", "operator"}),
    "console:settings:write": frozenset({"admin", "operator"}),
```

`console/backend/app/core/router_registry.py`：在 `from app.routers import (...)` 里加 `settings,`（插在 `sessions_records,` 与 `smart_settings,` 之间 —— `sessions_records` < `settings` < `smart_settings`），并在 `app.include_router(smart_settings.router)` 之后加：

```python
    # 前台设置（spec 2026-11-28）：字段目录 + 账号级设置读写。
    app.include_router(settings.router)
```

- [ ] **Step 8: 运行测试确认通过**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest tests/integration/test_settings_api.py -v`
Expected: PASS

- [ ] **Step 9: 检查点（不自动提交）**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS

---

### Task 4: 前端数据层（api + store + 热更工具 + 权限镜像）

**Files:**
- Create: `console/frontend/src/api/settings.ts`
- Create: `console/frontend/src/stores/settings.ts`
- Modify: `console/frontend/src/utils/hotParams.ts`
- Modify: `console/frontend/src/utils/hotParams.spec.ts`
- Modify: `console/frontend/src/utils/permissions.ts`
- Modify: `console/frontend/src/utils/permissions.spec.ts`
- Modify: `console/frontend/src/api/templates.ts`
- Test: `console/frontend/src/stores/settings.spec.ts`（新建）

**Interfaces:**
- Consumes: `api/client.ts` 的 `api`（`get/post/put`）与 `AppError`
- Produces:
  - `api/settings.ts`：`FrontField`、`FrontSettingValue`、`FrontSettingsSnapshot`、`FrontSettingsUpdate`、`settingsApi.getFront/putFront/resetFront`
  - `stores/settings.ts`：`useFrontSettingsStore()` → `{fields, values, defaults, updatedAt, updatedBy, loading, saving, error, load, save, reset}`
  - `utils/hotParams.ts`：新增 `HotFieldLike`；`buildSessionPatch(fields, values)` → `{patch, rejected, overridden}`
  - `api/templates.ts`：`TemplatePayload.fields` 类型扩成 `Array<{key: string; value: string; patch?: string; source?: string}>`

> ⚠️ **本 task 不删 `HOT_PARAMS` / `hotParamByName`**：它们还被
> `src/components/proto/HotUpdateSettings.vue:9` 与 `src/views/SettingsView.vue:12` 引用，
> 而那两个文件要到 Task 9 才重写/删除。提前删会让 Task 4 的 `vue-tsc` 检查点必红。
> **删除挪到 Task 9 Step 4。** 本 task 只重写 `buildSessionPatch` + 加 `HotFieldLike`。

- [ ] **Step 1: 写失败测试**

新建 `console/frontend/src/stores/settings.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { settingsApi } from '@/api/settings'
import { useFrontSettingsStore } from './settings'

vi.mock('@/api/settings', () => ({
  settingsApi: {
    getFront: vi.fn(),
    putFront: vi.fn(),
    resetFront: vi.fn()
  }
}))

const mocked = vi.mocked(settingsApi)

const snapshot = {
  fields: [
    {
      key: 'thresh', group: 'vad', type: 'number' as const, hot: true,
      patch: 'audio.input.turn_detection.threshold', catalogKey: 'vad.thresh',
      src: '§2.2', default: 0.6, min: 0, max: 1, step: 0.05, opts: null,
      labelKey: 'tpl.field.thresh.label', hintKey: 'tpl.field.thresh.hint',
      platform: ['gpu'], patchOwner: 'thresh'
    }
  ],
  values: { thresh: 0.6 },
  defaults: { thresh: 0.6 },
  updatedAt: null,
  updatedBy: null
}

describe('front settings store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('load keeps the catalog and the values', async () => {
    mocked.getFront.mockResolvedValue(snapshot)
    const store = useFrontSettingsStore()
    await store.load()
    expect(store.fields).toHaveLength(1)
    expect(store.values.thresh).toBe(0.6)
    expect(store.error).toBeNull()
  })

  it('save stores the returned values', async () => {
    mocked.getFront.mockResolvedValue(snapshot)
    mocked.putFront.mockResolvedValue({
      ...snapshot, values: { thresh: 0.8 }, applied: ['thresh']
    })
    const store = useFrontSettingsStore()
    await store.load()
    await store.save({ thresh: 0.8 })
    expect(mocked.putFront).toHaveBeenCalledWith({ thresh: 0.8 })
    expect(store.values.thresh).toBe(0.8)
  })

  it('reset falls back to the defaults', async () => {
    mocked.getFront.mockResolvedValue(snapshot)
    mocked.resetFront.mockResolvedValue({
      values: { thresh: 0.6 }, applied: [], updatedAt: null, updatedBy: null
    })
    const store = useFrontSettingsStore()
    await store.load()
    await store.reset()
    expect(store.values.thresh).toBe(0.6)
  })

  it('a failing load records the error', async () => {
    mocked.getFront.mockRejectedValue(new Error('boom'))
    const store = useFrontSettingsStore()
    await store.load()
    expect(store.error).not.toBeNull()
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/frontend && npx vitest run src/stores/settings.spec.ts`
Expected: FAIL —— 无法解析 `@/api/settings`

- [ ] **Step 3: 写 api/settings.ts**

新建 `console/frontend/src/api/settings.ts`：

```ts
import { api } from './client'

/** 前台设置字段目录条目（后端 `front_setting_catalog.FIELD_CATALOG` 的出参）。 */
export interface FrontField {
  key: string
  group: string
  type: 'number' | 'select' | 'textarea' | 'text' | 'switch'
  /** 能否即时下发到活跃会话（后端按热更白名单判定）。 */
  hot: boolean
  /** session.update 的下发路径。 */
  patch: string
  /** 机器配置视图里的目录键（匹配实时值用）。 */
  catalogKey: string
  /** 目录溯源（展示用）。 */
  src: string
  /** 默认值。 */
  default: string | number | boolean
  min: number | null
  max: number | null
  step: number | null
  /** 固定枚举，或 `'voices'`（音色下拉），或 null。 */
  opts: string[] | 'voices' | null
  /** i18n key（根级、嵌套可解析：tpl.* / set.* / settings.f.*）。 */
  labelKey: string
  hintKey: string
  platform: string[]
  /** 同一条 patch 上的优先者（别名消歧）。 */
  patchOwner: string
}

export type FrontSettingValue = string | number | boolean

export interface FrontSettingsSnapshot {
  fields: FrontField[]
  values: Record<string, FrontSettingValue>
  defaults: Record<string, FrontSettingValue>
  updatedAt: string | null
  updatedBy: string | null
}

export interface FrontSettingsUpdate extends FrontSettingsSnapshot {
  applied: string[]
}

export const settingsApi = {
  getFront: () => api.get<FrontSettingsSnapshot>('/settings/front'),
  putFront: (values: Record<string, unknown>) =>
    api.put<FrontSettingsUpdate>('/settings/front', { values }),
  resetFront: () => api.post<FrontSettingsUpdate>('/settings/front/reset')
}
```

- [ ] **Step 4: 写 store**

新建 `console/frontend/src/stores/settings.ts`：

```ts
// stores/settings.ts — 前台设置的读写状态（spec 2026-11-28 §前端 6）。
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { AppError } from '@/api/client'
import {
  settingsApi,
  type FrontField,
  type FrontSettingValue
} from '@/api/settings'

export const useFrontSettingsStore = defineStore('frontSettings', () => {
  const fields = ref<FrontField[]>([])
  const values = ref<Record<string, FrontSettingValue>>({})
  const defaults = ref<Record<string, FrontSettingValue>>({})
  const updatedAt = ref<string | null>(null)
  const updatedBy = ref<string | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<AppError | null>(null)

  function apply(snapshot: {
    fields?: FrontField[]
    values: Record<string, FrontSettingValue>
    defaults?: Record<string, FrontSettingValue>
    updatedAt?: string | null
    updatedBy?: string | null
  }): void {
    if (snapshot.fields) fields.value = snapshot.fields
    values.value = snapshot.values
    if (snapshot.defaults) defaults.value = snapshot.defaults
    if (snapshot.updatedAt !== undefined) updatedAt.value = snapshot.updatedAt
    if (snapshot.updatedBy !== undefined) updatedBy.value = snapshot.updatedBy
  }

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      apply(await settingsApi.getFront())
    } catch (exc) {
      error.value = exc as AppError
    } finally {
      loading.value = false
    }
  }

  async function save(payload: Record<string, FrontSettingValue>): Promise<boolean> {
    saving.value = true
    error.value = null
    try {
      apply(await settingsApi.putFront(payload))
      return true
    } catch (exc) {
      error.value = exc as AppError
      return false
    } finally {
      saving.value = false
    }
  }

  async function reset(): Promise<boolean> {
    saving.value = true
    error.value = null
    try {
      apply(await settingsApi.resetFront())
      return true
    } catch (exc) {
      error.value = exc as AppError
      return false
    } finally {
      saving.value = false
    }
  }

  return { fields, values, defaults, updatedAt, updatedBy, loading, saving, error, load, save, reset }
})
```

- [ ] **Step 5: 改造 utils/hotParams.ts 的 buildSessionPatch**

**保留** `HOT_PARAMS` / `hotParamByName`（Task 9 才删）、`isHotPath`、`actualForParam`。
把 `buildSessionPatch` 改成吃后端目录：

```ts
/** 下发用的字段形状：只需要 key 与 patch。 */
export interface HotFieldLike {
  key: string
  patch: string
  /** 同一条 patch 上的优先者（别名消歧）。 */
  patchOwner: string
}

/**
 * 把若干 (参数名, 值) 组装成 session.update 形状的 patch。
 *
 * - 不在白名单里的字段进 `rejected`（保存可以，推送不行）。
 * - 同一条 patch 上有多个字段时，值非空且靠前（目录顺序）的那个生效，
 *   其它被覆盖的 key 进 `overridden`（提示用，不丢数据）。
 */
export function buildSessionPatch(
  fields: HotFieldLike[],
  values: Record<string, string | number | boolean>
): { patch: Record<string, unknown>; rejected: string[]; overridden: string[] } {
  const patch: Record<string, unknown> = {}
  const rejected: string[] = []
  const overridden: string[] = []
  const byPath = new Map<string, HotFieldLike[]>()
  for (const field of fields) {
    if (!isHotPath(field.patch)) {
      rejected.push(field.key)
      continue
    }
    const bucket = byPath.get(field.patch) ?? []
    bucket.push(field)
    byPath.set(field.patch, bucket)
  }
  for (const [path, bucket] of byPath) {
    const parts = path.split('.')
    let chosen: { key: string; value: string | number | boolean } | null = null
    for (const field of bucket) {
      const raw = values[field.key]
      const text = raw === undefined || raw === null ? '' : String(raw)
      if (!text) continue
      if (chosen === null) chosen = { key: field.key, value: raw as string | number | boolean }
      else overridden.push(field.key)
    }
    if (chosen === null) continue
    let node = patch as Record<string, unknown>
    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index]
      if (index === parts.length - 1) node[part] = chosen.value
      else {
        if (typeof node[part] !== 'object' || node[part] === null) node[part] = {}
        node = node[part] as Record<string, unknown>
      }
    }
  }
  return { patch, rejected, overridden }
}
```

> ⚠️ 注意：`src/utils/session-patch.ts:24` 还有**另一个**同名 `buildSessionPatch`（`SessionsView.vue` 在用）。
> 两者不冲突，但别 import 错了文件。

- [ ] **Step 6: 改写 hotParams.spec.ts**

重写 `console/frontend/src/utils/hotParams.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { actualForParam, buildSessionPatch, isHotPath } from './hotParams'

const fields = [
  { key: 'thresh', patch: 'audio.input.turn_detection.threshold', patchOwner: 'thresh' },
  { key: 'init_chat_prompt', patch: 'instructions', patchOwner: 'init_chat_prompt' },
  { key: 'instructions', patch: 'instructions', patchOwner: 'init_chat_prompt' },
  { key: 'voice', patch: 'audio.output.voice', patchOwner: 'voice' }
]
```

断言：

1. `isHotPath('audio.input.turn_detection.threshold')` 为 true；`isHotPath('audio.output.voice')` 为 false；`isHotPath('model')` 为 false；`isHotPath('audio.input.transcription')` 为 false（分支不是终点）。
2. `buildSessionPatch(fields, { thresh: 0.8 }).patch` 等于 `{ audio: { input: { turn_detection: { threshold: 0.8 } } } }`。
3. **别名消歧（Review Focus #1）**：`buildSessionPatch(fields, { instructions: '人设' }).patch` 等于 `{ instructions: '人设' }` —— 只有 `instructions` 填了时，用的是它的值，不被空的 `init_chat_prompt` 覆盖。
4. 两个都填时 `init_chat_prompt` 生效：`buildSessionPatch(fields, { init_chat_prompt: 'A', instructions: 'B' }).patch` 等于 `{ instructions: 'A' }`，且 `overridden` 含 `'instructions'`。
5. **白名单外（Review Focus #2）**：`buildSessionPatch(fields, { voice: 'x' }).rejected` 含 `'voice'`，且 `patch` 为 `{}`。
6. `actualForParam([{ key: 'vad.min_silence_ms', actual: '450' }], 'vad.min_silence_ms')` 为 `'450'`；后缀匹配 `actualForParam([{ key: 'min_silence_ms', actual: '450' }], 'vad.min_silence_ms')` 为 `'450'`；无匹配为 `null`。

- [ ] **Step 7: 同步权限镜像与模板类型**

`console/frontend/src/utils/permissions.ts` 的 `PERMISSION_ROLES`（`Record<string, readonly string[]>`，角色是**普通字符串数组**）加两行：

```ts
  'console:settings:query': ['admin', 'operator'],
  'console:settings:write': ['admin', 'operator'],
```

`console/frontend/src/utils/permissions.spec.ts` 的写死列表（第 27-53 行）加 `'console:settings:query'` 与 `'console:settings:write'`
（插在 `'console:release:write'` 之后、`'console:smart:analyze'` 之前 —— `settings` < `smart`）。
**必须同步，否则这条精确集合断言会红。**

`console/frontend/src/api/templates.ts` 的 `TemplatePayload.fields` 改成：

```ts
  fields: Array<{ key: string; value: string; patch?: string; source?: string }>
```

> 后端 `app/schemas/template.py:8-14` 的 `TemplateFieldIn` 确实接受 `patch` / `source`，
> `normalize_fields()` 会补齐，所以加宽是安全的。

- [ ] **Step 8: 运行测试确认通过**

Run: `cd console/frontend && npx vitest run src/stores/settings.spec.ts src/utils/hotParams.spec.ts src/utils/permissions.spec.ts`
Expected: PASS

- [ ] **Step 9: 检查点（不自动提交）**

Run: `cd console/frontend && npx vitest run`
Expected: 全部 PASS
Run: `cd console/frontend && npx vue-tsc --noEmit 2>&1 | Select-String "api/settings|stores/settings|hotParams"`
Expected: 无输出（本次新增/改动文件无类型错误）

---

### Task 5: i18n（tpl / set 新模块 + settings.f + index 注册）

**Files:**
- Create: `console/frontend/src/i18n/locales/zh-CN/tpl.ts`
- Create: `console/frontend/src/i18n/locales/en-US/tpl.ts`
- Create: `console/frontend/src/i18n/locales/zh-CN/set.ts`
- Create: `console/frontend/src/i18n/locales/en-US/set.ts`
- Modify: `console/frontend/src/i18n/locales/zh-CN/settings.ts`
- Modify: `console/frontend/src/i18n/locales/en-US/settings.ts`
- Modify: `console/frontend/src/i18n/locales/zh-CN/smart.ts`
- Modify: `console/frontend/src/i18n/locales/en-US/smart.ts`
- Modify: `console/frontend/src/i18n/locales/zh-CN/index.ts`
- Modify: `console/frontend/src/i18n/locales/en-US/index.ts`
- Test: `console/frontend/src/i18n/i18n.spec.ts`（既有）

**Interfaces:**
- Produces: 根级 i18n key `tpl.*` / `set.*` / `settings.f.*` / `smart.currentCol.src`

> ⚠️ **结构约束**（Global Constraints 已强调，这里是完整的目标结构）：
> **任何 key 路径都不能穿过一个字符串叶子。** 所以 `reset` 必须是对象（`set.reset.label` / `set.reset.body`），
> `thresh` 必须是对象（`tpl.field.thresh.label` / `tpl.field.thresh.hint`）。
>
> ⚠️ `tpl.save` / `tpl.saveAs` 也要做成对象：`tpl.save.label` / `tpl.save.hint` / `tpl.saveAs.label` / `tpl.saveAs.hint` / `tpl.saveAs.desc`。
>
> ⚠️ **没有根级 `toast` 模块** → toast 文案放 `set.toast.{saved,reset}` 与 `tpl.toast.hot`。

- [ ] **Step 1: 写失败测试**

在 `console/frontend/src/i18n/i18n.spec.ts` 里追加一条用例（注意：vitest 的 `toHaveProperty` 把 `.` 当路径分隔符，
所以**不要**用 `toHaveProperty('set.reset.body')` 这种"路径里带点"的写法 —— 用下面这种不含歧义的路径）：

```ts
it('exposes the front-office template copy in both locales', async () => {
  const { default: zh } = await import('./locales/zh-CN')
  const { default: en } = await import('./locales/en-US')
  for (const key of [
    'tpl.title', 'tpl.desc', 'tpl.source', 'tpl.effectRuntime',
    'tpl.live.title', 'tpl.live.col.field', 'tpl.field.thresh.label',
    'tpl.field.thresh.hint', 'tpl.save.label', 'tpl.saveAs.label',
    'tpl.toast.hot',
    'set.page.desc', 'set.reset.label', 'set.reset.body',
    'set.toast.saved', 'set.toast.reset',
    'settings.f.init_chat_prompt', 'settings.f.instructions', 'settings.f.voice'
  ]) {
    expect(zh).toHaveProperty(key)
    expect(en).toHaveProperty(key)
  }
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/frontend && npx vitest run src/i18n/i18n.spec.ts`
Expected: FAIL —— `tpl.title` 不存在

- [ ] **Step 3: 写 set.ts（中英各一份）**

`console/frontend/src/i18n/locales/zh-CN/set.ts`：

```ts
export default {
  page: { desc: '当前账号的语音模型、角色提示词与通话参数。' },
  reset: { label: '重置', body: '所有参数将恢复为默认值。' },
  err: { prompt: 'role 提示词需控制在 2000 字以内。' },
  save: '保存设置',
  toast: { saved: '设置已保存', reset: '设置已恢复默认值' }
}
```

`console/frontend/src/i18n/locales/en-US/set.ts`：

```ts
export default {
  page: { desc: 'Voice model, role prompt and call parameters of this account.' },
  reset: { label: 'Reset', body: 'Every parameter goes back to its default value.' },
  err: { prompt: 'The role prompt must stay under 2 000 characters.' },
  save: 'Save the settings',
  toast: { saved: 'Settings saved', reset: 'Settings restored to the defaults' }
}
```

- [ ] **Step 4: 写 tpl.ts（中英各一份）**

`console/frontend/src/i18n/locales/zh-CN/tpl.ts`：

```ts
export default {
  title: '统一参数模板',
  desc: '前台设置与运维部署共用同一份目录驱动模板。热更项即时作用于当前 runtime，其余需发布并重启。',
  source: '来源：参数目录',
  sourceFront: '前台热更设置',
  effectRuntime: '对话态热更',
  hot: '热更',
  restart: '需重启',
  plat: { gpu: 'GPU', npu: 'NPU', amd: 'AMD', cpu: 'CPU' },
  col: { field: '字段', actual: '实际值', effect: '生效方式' },
  live: {
    title: '对话态热更参数',
    hint: '{n} 项可动态更新参数',
    note: '这些值只作用于当前会话（热更白名单）；发布前新连接仍读 YAML 默认值。',
    edit: { label: '编辑对话态热更参数', hint: '修改即时作用于当前 runtime' },
    col: {
      field: '参数',
      value: '当前值',
      patch: 'session.update 路径',
      src: '目录溯源'
    }
  },
  field: {
    thresh: {
      label: 'VAD 语音判定阈值',
      hint: '§7.5 热更：turn_detection.threshold；0–1，默认 0.6。'
    },
    min_silence_ms: {
      label: '句末静音时长（ms）',
      hint: '§7.5 热更：turn_detection.silence_duration_ms；生产 450 ms。'
    },
    qwen3_asr_language: {
      label: '转写语言',
      hint: '§7.5 热更：transcription.language；需通过后端语言能力校验。'
    },
    init_chat_prompt: { label: '系统人设提示词' },
    instructions: { label: '指令（客户端首帧）' },
    qwen3_tts_speaker: {
      label: 'TTS 音色',
      hint: '§7.5 热更：audio.output.voice；仅 qwen3 支持列表内音色生效。'
    },
    voice: { label: '音色（客户端首帧）' }
  },
  save: { label: '应用热更', hint: '仅热更字段推送到活跃会话（热更白名单），其余留在运维侧。' },
  saveAs: {
    label: '保存为模板',
    hint: '用当前参数创建可复用模板',
    desc: '来自 {source} 的快照 —— 将采集 {n} 个参数。'
  },
  group: { hint: '{hot} 项热更 · {cold} 项需重启' },
  cold: { note: '当前 runtime 不支持修改 ——', link: '到运维台配置' },
  toast: { hot: '已向当前 runtime 下发 {n} 项热更参数' }
}
```

`console/frontend/src/i18n/locales/en-US/tpl.ts`：

```ts
export default {
  title: 'Unified parameter template',
  desc: 'Front-office settings and ops deployment share one catalog-driven template. Hot fields apply to the live runtime; the rest require publish + restart.',
  source: 'source: parameter catalog',
  sourceFront: 'front-office hot settings',
  effectRuntime: 'Conversation hot',
  hot: 'hot',
  restart: 'restart required',
  plat: { gpu: 'GPU', npu: 'NPU', amd: 'AMD', cpu: 'CPU' },
  col: { field: 'Field', actual: 'Actual value', effect: 'Effect' },
  live: {
    title: 'Conversation hot settings',
    hint: '{n} live-updatable parameters',
    note: 'These values apply to the active session only (session.update whitelist). New connections read YAML defaults until published.',
    edit: {
      label: 'Edit conversation hot settings',
      hint: 'changes apply to the live runtime'
    },
    col: {
      field: 'Parameter',
      value: 'Current value',
      patch: 'session.update path',
      src: 'Catalog ref'
    }
  },
  field: {
    thresh: {
      label: 'VAD speech threshold',
      hint: '§7.5 hot via turn_detection.threshold; 0–1, default 0.6.'
    },
    min_silence_ms: {
      label: 'Trailing silence (ms)',
      hint: '§7.5 hot via turn_detection.silence_duration_ms; production 450 ms.'
    },
    qwen3_asr_language: {
      label: 'Transcription language',
      hint: '§7.5 hot via transcription.language; backend capability check applies.'
    },
    init_chat_prompt: { label: 'System persona prompt' },
    instructions: { label: 'Instructions (client first frame)' },
    qwen3_tts_speaker: {
      label: 'TTS speaker',
      hint: '§7.5 hot via audio.output.voice; only qwen3 supported speakers take effect.'
    },
    voice: { label: 'Voice (client first frame)' }
  },
  save: {
    label: 'Apply hot settings to runtime',
    hint: 'Only hot fields are pushed to live sessions (hot_update whitelist). Others stay on the ops side.'
  },
  saveAs: {
    label: 'Save as template',
    hint: 'Create a reusable template from current parameters',
    desc: 'Snapshot from {source} — {n} parameters will be captured.'
  },
  group: { hint: '{hot} hot · {cold} restart-required' },
  cold: { note: 'Runtime change not supported —', link: 'open in ops console' },
  toast: { hot: 'Applied {n} hot fields to the current runtime' }
}
```

> 注意 `init_chat_prompt` / `instructions` / `voice` **只有 label、没有 hint** —— 它们的 hint 走
> `settings.f.*`（见 Step 5）。所以这三个对象里不要放 `hint` 键。

- [ ] **Step 5: 补 settings.f 与 smart.currentCol.src**

`console/frontend/src/i18n/locales/zh-CN/settings.ts` 的 `export default { … }` 里加（该文件是扁平结构，
没有 `f` 子对象，直接加即可）：

```ts
  f: {
    init_chat_prompt: '语音助理的人设。请控制在 2000 字以内 —— 提示词过长会抬高首 token 延迟与 KV 显存。',
    instructions: '由客户端在首帧下发，会覆盖 role 提示词。',
    voice: '新建通话使用的音色。'
  },
```

`console/frontend/src/i18n/locales/en-US/settings.ts` 加同名的三个英文键：

```ts
  f: {
    init_chat_prompt: 'Persona of the voice assistant. Keep it under 2 000 characters — a long prompt raises the first-token latency and the KV VRAM.',
    instructions: 'Sent on the first frame by the client; overrides the role prompt.',
    voice: 'Timbre used on the new calls.'
  },
```

`console/frontend/src/i18n/locales/zh-CN/smart.ts` 的 `currentCol` 加 `src`：

```ts
  currentCol: { key: '参数', actual: '实际值', expected: '期望值', effect: '生效方式', src: '目录溯源' },
```

`console/frontend/src/i18n/locales/en-US/smart.ts` 同步：

```ts
  currentCol: { key: 'Parameter', actual: 'Actual value', expected: 'Expected value', effect: 'Effect', src: 'Catalog ref' },
```

- [ ] **Step 6: 注册模块**

`console/frontend/src/i18n/locales/zh-CN/index.ts` 与 `en-US/index.ts`：
- 加 `import set from './set'` —— 插在 `import sessions from './sessions'` 与 `import settings from './settings'` 之间。
- 加 `import tpl from './tpl'` —— 插在 `import templates from './templates'` 与 `import traffic from './traffic'` 之间（`tpl` < `traffic`，因为 `p` < `r`）。
- `export default { … }` 那一行（单行）追加 `set` 与 `tpl` 两个键。

- [ ] **Step 7: 运行测试确认通过**

Run: `cd console/frontend && npx vitest run src/i18n/i18n.spec.ts`
Expected: PASS（zh/en 扁平 key 集合一致）

- [ ] **Step 8: 检查点（不自动提交）**

Run: `cd console/frontend && npx vitest run src/i18n`
Expected: PASS

---

### Task 6: 样式补齐 + PSwitch 可达性

**Files:**
- Modify: `console/frontend/src/styles/prototype.less`
- Modify: `console/frontend/src/components/proto/PSwitch.vue`
- Modify: `console/frontend/src/components/proto/proto.spec.ts`
- Test: `console/frontend/src/styles/hex-ban.spec.ts`（既有）

**Interfaces:**
- Produces: 全局 class `set-grid` `sfield` `sw` `ta-wrap` `counter` `set-actions` `tpl-banner` `tpl-src` `muted` `card--bar` `page-head` `switch`（+ `textarea.fin` 规则）；`PSwitch` 渲染 `<button class="switch" role="switch">`

> 已存在（**不要重定义**，它们被 `InstancesView` / `HistoryView` / `MachineFormModal` / `SessionRecordDetail` 在用）：
> `.card`(8) `.tbl`(68) `.mono`(99) `.dot`(103) `.tag`(123) `.btn`(195) `.chips`(232) `.chip`(238) `.note`(285) `.rowline`(294) `.spacer`(300) `.tscroll`(305) `.field`(988) `.fin`(997) `.fhint`(1012)。
> 确实不存在（本次新增，无冲突）：`.switch` `.muted` `.page-head` `.set-grid` `.sfield` `.counter` `.set-actions` `.tpl-banner` `.tpl-src`。

- [ ] **Step 1: 写失败测试**

在 `console/frontend/src/components/proto/proto.spec.ts` 里**沿用既有 PSwitch 用例的挂载代码**
（第 140-166 行是 `createApp(defineComponent({ data, render }))` 那种写法，**不是** `root.querySelector` 直查），
只把断言改成：

```ts
const sw = root.querySelector('button.switch') as HTMLButtonElement
expect(sw.getAttribute('role')).toBe('switch')
expect(sw.getAttribute('aria-checked')).toBe('false')
await sw.click()
expect(sw.getAttribute('aria-checked')).toBe('true')
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/frontend && npx vitest run src/components/proto/proto.spec.ts`
Expected: FAIL —— `button.switch` 找不到（现在渲染的是 `div.switch`）

- [ ] **Step 3: 改 PSwitch.vue**

替换 `console/frontend/src/components/proto/PSwitch.vue` 全文（当前是 9 行、根节点是 `<div class="switch" role="switch">`）：

```vue
<template>
  <button
    type="button"
    class="switch"
    :class="{ on: modelValue }"
    role="switch"
    :aria-checked="modelValue ? 'true' : 'false'"
    @click="emit('update:modelValue', !modelValue)"
  ></button>
</template>

<script setup lang="ts">
defineProps<{ modelValue: boolean }>()

const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()
</script>
```

> `:aria-checked` 必须绑**字符串** `'true'/'false'`，不能绑布尔（ARIA 属性要字符串值）。

- [ ] **Step 4: 补样式**

在 `console/frontend/src/styles/prototype.less` 末尾追加（**全部用 `var(--s2s-*)` / `var(--voice-*)`，禁止裸 hex**）：

```less
/* ---- front-office settings page（原型 #/settings）---- */
.set-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
  @media (max-width: 1100px) {
    grid-template-columns: 1fr;
  }
}
.sfield {
  min-width: 0;
  > label,
  .f-lbl {
    display: block;
    font-size: 12.5px;
    color: var(--s2s-color-muted);
    margin-bottom: 6px;
  }
  &.sw .switch {
    align-self: flex-start;
  }
  &.ta-wrap {
    grid-column: span 2;
  }
}
textarea.fin {
  resize: vertical;
  min-height: 96px;
  font-family: var(--s2s-font-mono);
  font-size: 12px;
  line-height: 1.6;
}
.counter {
  text-align: right;
  font-size: 11px;
  color: var(--s2s-color-faint);
  margin-top: 4px;
  font-variant-numeric: tabular-nums;
}
.set-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  @media (max-width: 700px) {
    flex-wrap: wrap;
  }
}
.tpl-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-left: 3px solid var(--s2s-color-accent);
  p {
    margin: 4px 0 0;
    font-size: 12px;
  }
  @media (max-width: 1100px) {
    flex-direction: column;
    align-items: flex-start;
  }
}
.tpl-src {
  display: block;
  font-size: 10.5px;
  color: var(--s2s-color-faint);
  margin-top: 3px;
  font-family: var(--s2s-font-mono);
}
.muted {
  color: var(--s2s-color-muted);
  font-size: 12.5px;
}
.card--bar {
  padding: 10px 14px;
}
.switch {
  width: 36px;
  height: 20px;
  border-radius: 10px;
  background: var(--voice-surface-2);
  border: 1px solid var(--voice-border);
  position: relative;
  cursor: pointer;
  transition: 0.2s;
  flex: 0 0 36px;
  padding: 0;
  &::after {
    content: '';
    position: absolute;
    top: 2px;
    left: 2px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--voice-dim);
    transition: 0.2s;
  }
  &.on {
    background: color-mix(in srgb, var(--voice-accent) 35%, transparent);
    border-color: var(--voice-accent);
    &::after {
      left: 18px;
      background: var(--voice-accent);
    }
  }
  &:focus-visible {
    outline: 2px solid var(--s2s-color-accent);
    outline-offset: 2px;
  }
}
.page-head {
  margin: 0 0 18px;
  h1 {
    margin: 0 0 6px;
    font-size: 20px;
  }
  p {
    margin: 0;
    color: var(--s2s-color-muted);
    font-size: 13px;
  }
}
```

> 用到的 token 全部存在：`--s2s-color-muted` `colorMuted`、`--s2s-color-faint` `colorFaint`、
> `--s2s-color-accent` `colorAccent`、`--s2s-color-surface-2` `colorSurface2`、
> `--s2s-color-border-strong` `colorBorderStrong`、`--s2s-radius-sm` `radiusSm`、
> `--s2s-font-mono` `fontMono`、`--voice-surface-2` `voiceSurface2`、`--voice-border` `voiceBorder`、
> `--voice-dim` `voiceDim`、`--voice-accent` `voiceAccent`。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd console/frontend && npx vitest run src/components/proto/proto.spec.ts src/styles`
Expected: PASS（`hex-ban.spec.ts` 也要绿）

- [ ] **Step 6: 检查点（不自动提交）**

Run: `cd console/frontend && npx vitest run src/components src/styles`
Expected: PASS

---

### Task 7: 字段控件组件 + 表单 viewmodel

**Files:**
- Create: `console/frontend/src/components/proto/SettingField.vue`
- Create: `console/frontend/src/views/settings.viewmodel.ts`
- Test: `console/frontend/src/views/settings.viewmodel.spec.ts`（新建）

**Interfaces:**
- Consumes: `api/settings.ts` 的 `FrontField`；`api/machineConfig.ts` 的 `MachineParamRow`
- Produces:
  - `views/settings.viewmodel.ts`：`initialValues(fields, values)`、`visibleFields(fields, platform)`、`voiceOptions(voices)`、`liveValue(field, rows, saved)`
  - `components/proto/SettingField.vue`：props `{ field: FrontField; modelValue: FrontSettingValue; voiceIds: string[] }`，emit `update:modelValue`

> ⚠️ `liveValue` 的 `rows` 参数类型用 `Array<Pick<MachineParamRow, 'key' | 'actual' | 'expected'>>`，
> 不要直接写 `MachineParamRow[]` —— spec 里的字面量只有 3 个字段，会 TS2345。

- [ ] **Step 1: 写失败测试**

新建 `console/frontend/src/views/settings.viewmodel.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import {
  initialValues,
  liveValue,
  visibleFields,
  voiceOptions
} from './settings.viewmodel'
import type { FrontField } from '@/api/settings'

const field = (over: Partial<FrontField>): FrontField => ({
  key: 'thresh', group: 'vad', type: 'number', hot: true,
  patch: 'audio.input.turn_detection.threshold', catalogKey: 'vad.thresh',
  src: '', default: 0.6, min: 0, max: 1, step: 0.05, opts: null,
  labelKey: 'tpl.field.thresh.label', hintKey: 'tpl.field.thresh.hint',
  platform: ['gpu', 'cpu'], patchOwner: 'thresh',
  ...over
})

describe('settings viewmodel', () => {
  it('falls back to the default for a missing value', () => {
    expect(initialValues([field({})], {}).thresh).toBe(0.6)
  })

  it('keeps the saved value', () => {
    expect(initialValues([field({})], { thresh: 0.8 }).thresh).toBe(0.8)
  })

  it('filters the fields by the machine platform', () => {
    const fields = [field({ key: 'a', platform: ['gpu'] }), field({ key: 'b', platform: ['cpu'] })]
    expect(visibleFields(fields, 'gpu').map((f) => f.key)).toEqual(['a'])
    expect(visibleFields(fields, 'cpu').map((f) => f.key)).toEqual(['b'])
  })

  it('lists only the ready voices', () => {
    expect(voiceOptions([{ id: 'v1', status: 'ready' }, { id: 'v2', status: 'failed' }])).toEqual(['v1'])
  })

  it('prefers the machine actual value over the saved one', () => {
    const rows = [{ key: 'vad.thresh', actual: '0.9', expected: '0.6' }]
    expect(liveValue(field({}), rows, 0.8)).toBe('0.9')
  })

  it('falls back to the saved value when the machine has no actual', () => {
    const rows = [{ key: 'vad.thresh', actual: null, expected: null }]
    expect(liveValue(field({}), rows, 0.8)).toBe(0.8)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/frontend && npx vitest run src/views/settings.viewmodel.spec.ts`
Expected: FAIL —— 无法解析 `./settings.viewmodel`

- [ ] **Step 3: 实现 viewmodel**

新建 `console/frontend/src/views/settings.viewmodel.ts`：

```ts
// views/settings.viewmodel.ts — 设置页的纯函数（可测，不碰网络与 DOM）。
import type { FrontField, FrontSettingValue } from '@/api/settings'
import type { MachineParamRow } from '@/api/machineConfig'

/** 实时值只需要机器行里的三列。 */
export type ParamRow = Pick<MachineParamRow, 'key' | 'actual' | 'expected'>

/** 表单初值：已存值优先，缺的回落字段默认值。 */
export function initialValues(
  fields: FrontField[],
  values: Record<string, FrontSettingValue>
): Record<string, FrontSettingValue> {
  const out: Record<string, FrontSettingValue> = {}
  for (const field of fields) out[field.key] = values[field.key] ?? field.default
  return out
}

/** 按所选机器的平台过滤字段（原型 `renderSettings` 的 platform 过滤）。 */
export function visibleFields(fields: FrontField[], platform: string): FrontField[] {
  return fields.filter((field) => !field.platform.length || field.platform.includes(platform || 'gpu'))
}

/** 音色下拉：只留 ready 的音色 id。 */
export function voiceOptions(voices: Array<{ id: string; status: string }>): string[] {
  return voices.filter((voice) => voice.status === 'ready').map((voice) => voice.id)
}

/** 实时值：机器实际值 → 机器期望值 → 已存设置 → 默认值。 */
export function liveValue(
  field: FrontField,
  rows: ParamRow[],
  saved: FrontSettingValue
): FrontSettingValue {
  const suffix = field.catalogKey.split('.').pop() ?? field.catalogKey
  const row =
    rows.find((item) => item.key === field.catalogKey) ??
    rows.find((item) => item.key === suffix || item.key.endsWith(`.${suffix}`))
  const actual = row?.actual ?? row?.expected
  if (actual !== undefined && actual !== null && actual !== '') return actual
  return saved
}
```

- [ ] **Step 4: 写 SettingField.vue**

新建 `console/frontend/src/components/proto/SettingField.vue`：

```vue
<template>
  <div class="sfield" :class="{ sw: field.type === 'switch', 'ta-wrap': field.type === 'textarea' }">
    <span v-if="field.type === 'switch'" class="f-lbl">{{ t(field.labelKey) }}</span>
    <label v-else :for="inputId">{{ t(field.labelKey) }}</label>

    <PSwitch
      v-if="field.type === 'switch'"
      :model-value="asBoolean"
      @update:model-value="emit('update:modelValue', $event)"
    />

    <template v-else>
      <textarea
        v-if="field.type === 'textarea'"
        :id="inputId"
        class="fin"
        rows="4"
        :value="asText"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      ></textarea>
      <div v-if="field.type === 'textarea'" class="counter">{{ asText.length }}</div>

      <select
        v-else-if="field.type === 'select'"
        :id="inputId"
        class="fin"
        :value="asText"
        @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="option in options" :key="option" :value="option">{{ option }}</option>
      </select>

      <input
        v-else-if="field.type === 'number'"
        :id="inputId"
        type="number"
        class="fin"
        :value="asNumber"
        :min="field.min ?? undefined"
        :max="field.max ?? undefined"
        :step="field.step ?? undefined"
        @input="emit('update:modelValue', Number(($event.target as HTMLInputElement).value))"
      />

      <input
        v-else
        :id="inputId"
        type="text"
        class="fin"
        :value="asText"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      />
    </template>

    <div class="fhint">
      {{ t(field.hintKey) }}
      <span v-if="field.src" class="tpl-src">{{ field.src }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FrontField, FrontSettingValue } from '@/api/settings'

import PSwitch from './PSwitch.vue'

const props = defineProps<{
  field: FrontField
  modelValue: FrontSettingValue
  voiceIds: string[]
}>()

const emit = defineEmits<{ (e: 'update:modelValue', value: FrontSettingValue): void }>()

const { t } = useI18n()

const inputId = computed(() => `set-${props.field.key}`)

const asText = computed(() =>
  props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue)
)
const asNumber = computed(() => Number(props.modelValue ?? 0))
const asBoolean = computed(() => Boolean(props.modelValue))

const options = computed(() => {
  if (props.field.opts === 'voices') return props.voiceIds
  if (Array.isArray(props.field.opts)) return props.field.opts
  return []
})
</script>
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd console/frontend && npx vitest run src/views/settings.viewmodel.spec.ts`
Expected: PASS

- [ ] **Step 6: 检查点（不自动提交）**

Run: `cd console/frontend && npx vue-tsc --noEmit 2>&1 | Select-String "settings.viewmodel|SettingField"`
Expected: 无输出（本次新增文件无类型错误）

---

### Task 8: 智能设置卡按原型重写

**Files:**
- Modify: `console/frontend/src/components/proto/SmartSettingsPanel.vue`
- Test: `console/frontend/src/components/proto/smartSettingsPanel.spec.ts`（新建）

**Interfaces:**
- Consumes: `stores/smartSettings.ts` 的 `useSmartSettingsStore()`（`data` = `{machineId, fetched, analysis, loading, analyzing, error}`，动作 `reset/fetch/analyze`）
- Produces: props `{ machineId: string; mode: 'live' | 'deploy' }`、emits `apply: [key: string, value: string]`（**契约不变，只改渲染**）

> ⚠️ 现有组件的 scoped less 用的是 `--muted` / `--border` / `--accent` / `--surface` / `--text` / `--mono`
> 等**未定义变量**（和 `SettingsView.vue` 同一个毛病）。重写时一律改成 `var(--s2s-*)` / `var(--voice-*)`。

- [ ] **Step 1: 写失败测试**

新建 `console/frontend/src/components/proto/smartSettingsPanel.spec.ts`（jsdom；桩掉 `@/stores/smartSettings`）：

```ts
// @vitest-environment jsdom
import { createApp, defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import SmartSettingsPanel from './SmartSettingsPanel.vue'

const state = {
  data: {
    machineId: '', fetched: null, analysis: null, loading: false, analyzing: false, error: null
  },
  reset: vi.fn(),
  fetch: vi.fn(),
  analyze: vi.fn()
}

vi.mock('@/stores/smartSettings', () => ({ useSmartSettingsStore: () => state }))

function mount(props: Record<string, unknown>): HTMLElement {
  const root = document.createElement('div')
  document.body.appendChild(root)
  const app = createApp(defineComponent({ render: () => h(SmartSettingsPanel as never, props) }))
  app.mount(root)
  return root
}

describe('smart settings panel follows the prototype card', () => {
  it('renders the card with the prototype class names', () => {
    const root = mount({ machineId: 'node-a01', mode: 'live' })
    expect(root.querySelector('.card')).toBeTruthy()
    expect(root.querySelector('.card h3 .tag.accent')?.textContent).toBe('AI')
    expect(root.querySelector('.btn.sm')).toBeTruthy()
    expect(root.querySelector('textarea.fin')).toBeTruthy()
    expect(root.querySelector('.btn.primary.sm')).toBeTruthy()
  })
})
```

> 若 `t()` 在无 i18n provider 下抛错，就给 `app.use(i18n)` 装上真实 i18n 实例（`src/i18n/index.ts` 导出）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/frontend && npx vitest run src/components/proto/smartSettingsPanel.spec.ts`
Expected: FAIL —— 现有组件渲染的是别的 class 组合

- [ ] **Step 3: 重写 SmartSettingsPanel.vue**

替换 `console/frontend/src/components/proto/SmartSettingsPanel.vue` 全文，markup 对齐原型 `smartPanel(m, mode)`
（`console/design/console-refactor-demo.html:3326-3355`）：

```
.card
├ h3  smart.title + .hint(smart.hint {machine}) + .tag.accent "AI"
├ .rowline  [.btn.sm smart.fetch] [.muted smart.fetchHint] [.spacer] [.tag.ok smart.fetched]
├ 已拉取时：.tscroll > table.tbl（4 列：smart.currentCol.key / actual / effect / src）+ pre.smart-log
├ .field    label smart.fault + textarea.fin(rows=2, placeholder smart.faultPlaceholder)
├ .rowline  [.btn.primary.sm smart.analyze]（busy 时加 .muted smart.busy）
└ 有结果时：p.note(smart.rulesNote) + 每条推荐 .rec > .rec-top(.rname.mono / from→to / .btn.sm smart.apply) + .p-risk(reason)
```

**i18n 键全部复用既有的 `smart.ts`**（`title` `hint` `fetch` `fetchHint` `fetched` `fault` `faultPlaceholder`
`analyze` `busy` `apply` `logs` `currentParams` `currentCol.*` `recCol.*` `rulesNote` `source.*`），
Task 5 已给 `currentCol` 补了 `src`。

实现要点：
- `mode === 'live'` 时表格只列**前台 7 条字段**（`mode === 'deploy'` 时维持现状：全部 fetched params）；
  值取自 `fetched.params`，按 `catalogKey` 精确匹配、失败再按后缀匹配。
- 推荐条目的 key 先按别名、再按后缀归一到前台字段；**归一不到的一律只读展示（不给「应用」按钮）**。
- 「应用」按钮 emit `apply(key, value)`；父组件（设置页）写进 `draft`，不自动下发。
- `fetched` 的日志用 `<pre class="smart-log">`（原型 class）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd console/frontend && npx vitest run src/components/proto/smartSettingsPanel.spec.ts src/stores/smartSettings.spec.ts`
Expected: PASS

- [ ] **Step 5: 检查点（不自动提交）**

Run: `cd console/frontend && npx vitest run src/components src/stores`
Expected: PASS

---

### Task 9: 设置页重写 + 删除旧热更组件

**Files:**
- Modify: `console/frontend/src/views/SettingsView.vue`
- Delete: `console/frontend/src/components/proto/HotUpdateSettings.vue`
- Modify: `console/frontend/src/utils/hotParams.ts`（**这一步才删 `HOT_PARAMS` / `hotParamByName`**）
- Modify: `console/frontend/src/utils/hotParams.spec.ts`（删掉对已删导出的引用）
- Test: `console/frontend/src/views/settingsView.spec.ts`（新建）

**Interfaces:**
- Consumes: `stores/settings.ts`；`stores/machine.ts`（`machines` / `fetch()`）；`stores/auth.ts`（`hasPermission(code)`）；
  `api/machineConfig.ts`（`machineConfigApi.view(id)` → `{rows}`）；`api/machines.ts`（`listMachines()` → `{machines}`）；
  `api/voices.ts`（`listVoices({status,pageSize})` → `Page<VoiceRow>`，**取 `.list`**）；`api/sessions.ts`（`updateSessions({scope,session})`）；
  `api/templates.ts`（`templatesApi.create(payload)`）；`utils/hotParams.ts`；`views/settings.viewmodel.ts`；
  `components/proto/SettingField.vue`；`components/proto/SmartSettingsPanel.vue`；`components/ConfirmDialog.vue`
- Produces: `/settings` 页面，7 块结构（见 spec §前端 1）

> ⚠️ `templatesApi.create` 的 payload 里 **`scene: string` 与 `minVramGb: number | null` 是必填**，必须补上。
>
> ⚠️ 音色列表：`listVoices()` 返回 `Page<VoiceRow>` = `{list,total,page,pageSize}`，要取 `.list` 再喂 `voiceOptions()`。
>
> ⚠️ 确认弹窗：复用 `src/components/ConfirmDialog.vue`（props `{open,title,content,danger?}`，emit `answer(confirmed)`）——
> 它在 `components/` 而非 `components/proto/`，内部用 antd 是仓库既有事实。

- [ ] **Step 1: 写失败测试**

新建 `console/frontend/src/views/settingsView.spec.ts`（jsdom；桩掉 `@/stores/settings`、`@/stores/machine`、`@/api/sessions`、
`@/api/templates`、`@/api/voices`、`vue-router`）：

```ts
// @vitest-environment jsdom
import { createApp, defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import SettingsView from './SettingsView.vue'

// …桩：settings store 返回 7 条字段与已存值；machine store 返回一台机器；
//     auth store 的 hasPermission 返回 false；router 的 useRoute/useRouter 返回 { query: {} }。

describe('settings view', () => {
  it('renders the seven prototype blocks', () => {
    const root = mount()
    expect(root.querySelector('.page-head')).toBeTruthy()
    expect(root.querySelector('.card--bar .chips')).toBeTruthy()
    expect(root.querySelector('.tpl-banner')).toBeTruthy()
    expect(root.querySelector('.set-grid')).toBeTruthy()
    expect(root.querySelector('.set-actions')).toBeTruthy()
    expect(root.querySelectorAll('.sfield').length).toBe(7)
  })

  it('hides the save-as-template button without the create permission', () => {
    const root = mount()
    expect(root.querySelector('[data-act="save-as-template"]')).toBeNull()
  })
})
```

> 桩的具体写法照 `src/views/HistoryView.spec.ts` / `src/stores/smartSettings.spec.ts` 的既有模式。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/frontend && npx vitest run src/views/settingsView.spec.ts`
Expected: FAIL —— 现在的页面结构与原型不符

- [ ] **Step 3: 重写 SettingsView.vue**

替换 `console/frontend/src/views/SettingsView.vue` 全文。结构（严格按原型顺序）：

```
section.sv-page
├ .page-head            h1 = t('nav.settings') ；p = t('set.page.desc')
├ .card.card--bar       .chips > button.chip（PDot + machineId + 平台小字 tpl.plat.*，选中 .chip.active）
├ .card.tpl-banner      左：strong tpl.title + p.muted tpl.desc ；右：span.tag.ok tpl.source
├ SmartSettingsPanel（mode="live"）
├ .card 热更只读表       h3 tpl.live.title + .hint tpl.live.hint{n} + .tag.ok tpl.effectRuntime
│                       .tscroll > table.tbl（tpl.live.col.field/value/patch/src）
│                       p.note tpl.live.note
├ .card 热更字段编辑卡    h3 tpl.live.edit.label + .hint tpl.live.edit.hint
│                       .set-grid > SettingField × 7
└ .card.set-actions     span.muted tpl.save.hint + span.spacer
                        button.btn[data-act="save-as-template"] tpl.saveAs.label（仅 hasPermission('console:template:create')）
                        button.btn tpl.reset.label（重置 → 实际用 set.reset.label，tpl 模块无 reset）
                        button.btn.primary tpl.save.label（应用热更 = 落库 + 下发）
```

行为要点：

| 交互 | 实现 |
|---|---|
| 机器条 | 点击切换 `selectedMachine`；`watch(() => route.query.machine)` 同步；默认第一台。切机器后重新拉 `machineConfigApi.view(id)` 拿实时值。 |
| 智能推荐「应用」 | `@apply="(key, value) => { draft[key] = value }"` —— 只写表单，不下发。 |
| 「应用热更」（primary） | **落库 + 下发串联**：<br>1. `await settingsStore.save(draft)` → 失败则 toast 错误并**中止**（不往下发）。<br>2. `const { patch, rejected, overridden } = buildSessionPatch(fields, draft)`；`patch` 为空则跳过下发。<br>3. `await updateSessions({ scope: 'all', session: patch })` → toast `t('tpl.toast.hot', { n })`。<br>4. 下发失败（catch）→ toast「已保存，下发失败：{message}」，**不回滚已落库的值**（Review Focus #4）。<br>5. `rejected` 非空 → 额外提示「未下发（非白名单）：{names}」（复用既有 `settings.hotRejected`）。<br>6. `overridden` 非空 → 提示「{names} 已被同组的优先字段覆盖」。 |
| 「保存为模板」 | 仅 `auth.hasPermission('console:template:create')` 时渲染；点击弹保存表单，用 `templatesApi.create({ name, effect: 'runtime', platform: 选中机器的平台 ?? 'gpu', status: 'draft', scene: '', minVramGb: null, fields: 7 条 {key, value: String(value), patch}, desc })`。 |
| 「重置」 | `ConfirmDialog`（props `{open,title,content}`，`@answer`）确认 → `await settingsStore.reset()` → `draft` 回落默认 → toast `t('set.toast.reset')`。文案用 `t('set.reset.label')` / `t('set.reset.body')`。 |
| 实时值 | `liveValue(field, rows, saved)`；`rows` 来自 `machineConfigApi.view(machineId)`。 |
| 音色下拉 | `const page = await listVoices({ status: 'ready', pageSize: 200 })` → `voiceOptions(page.list)` → 传给 `SettingField` 的 `voiceIds`。 |
| 无机器 | 机器条为空时，实时值表显示空态（`.note`），其余区块照常。 |

- [ ] **Step 4: 删除旧组件 + 旧常量**

- 删除 `console/frontend/src/components/proto/HotUpdateSettings.vue`（全仓仅 `SettingsView` 引用，已确认）。
- `console/frontend/src/utils/hotParams.ts`：删掉 `HOT_PARAMS` 与 `hotParamByName`（真源已移到后端目录）。
  `isHotPath` / `actualForParam` / `buildSessionPatch` / `HotFieldLike` 保留。
- `console/frontend/src/utils/hotParams.spec.ts`：删掉对 `HOT_PARAMS` / `hotParamByName` 的引用。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd console/frontend && npx vitest run src/views/settingsView.spec.ts src/views/settings.viewmodel.spec.ts src/utils/hotParams.spec.ts`
Expected: PASS

- [ ] **Step 6: 检查点（不自动提交）**

Run: `cd console/frontend && npx vitest run`
Expected: 全部 PASS
Run: `cd console/frontend && npx vue-tsc --noEmit 2>&1 | Select-String "SettingsView|SettingField|SmartSettingsPanel|settings\.|hotParams"`
Expected: 无输出

---

### Task 10: 前后端联通核对（端到端清单）

**Files:** 无新文件（只跑与核对）

- [ ] **Step 1: 起后端**

Run: `cd console/backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
（若仓库有既有的启动脚本，以既有脚本为准。）

- [ ] **Step 2: 起前端**

Run: `cd console/frontend && npm run dev`
Expected: `http://localhost:3000` 可打开（vite `server.port = 3000`，`proxy['/api'] → http://localhost:8000`）

- [ ] **Step 3: 用 curl 核对后端契约**

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/json" -d '{"username":"<admin>","password":"<pass>"}'
curl -s http://localhost:8000/api/v1/settings/front -H "Authorization: Bearer <token>"
```
Expected: `data.fields` 有 7 条；`data.defaults.thresh == 0.6`；`data.values.thresh == 0.6`；`data.updatedAt == null`

```bash
curl -s -X PUT http://localhost:8000/api/v1/settings/front -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"values":{"thresh":0.8}}'
curl -s http://localhost:8000/api/v1/settings/front -H "Authorization: Bearer <token>"
```
Expected: 第二次 GET 的 `data.values.thresh == 0.8`、`data.updatedAt != null`、`data.applied == ["thresh"]`

- [ ] **Step 4: 浏览器核对清单**（`http://localhost:3000/settings`）

1. 页头 / 机器条 / 模板横幅 / 智能卡 / 热更只读表 / 热更编辑卡 / 底部操作条 —— **7 块都在**，class 名与原型一致。
2. 编辑卡里 **7 个字段**，控件类型正确：`thresh`/`min_silence_ms` 是 number、`qwen3_asr_language` 是 select（auto/zh/en）、`init_chat_prompt`/`instructions` 是 textarea（带字数计数）、`qwen3_tts_speaker`/`voice` 是 select（音色库）。
3. 开关渲染可见（`.switch` 有尺寸），`role="switch"`、`aria-checked` 正确。
4. 改 `thresh` → 点「应用热更」→ toast 出现「已向当前 runtime 下发 1 项热更参数」→ **刷新页面后值仍是改后的值**（落库生效）。
5. 改 `voice` → 点「应用热更」→ 保存成功、提示里有「未下发（非白名单）」，页面不报错（Review Focus #2）。
6. 只填 `instructions`、把 `init_chat_prompt` 清空 → 下发的 patch 里 `instructions` 是你填的值（Review Focus #1）。
7. 提示词填 2001 字 → 保存被拒，提示「role 提示词需控制在 2000 字以内」（Review Focus #3）。
8. 「重置」→ 二次确认 → 所有值回落默认，刷新后仍是默认。
9. 用 operator 账号登录 → 「保存为模板」按钮**不可见**，其余可操作（Review Focus #5）。
10. 窗口宽度拖到 ≤1100px → `.set-grid` 塌成单列。

- [ ] **Step 5: 跑全量测试**

Run: `cd console/backend && .venv\Scripts\python.exe -m pytest -q`
Expected: 全部 PASS
Run: `cd console/frontend && npx vitest run`
Expected: 全部 PASS

---

## 核对修正记录

本计划初稿做过一轮 38 项的仓库逐条比对，修正了 14 处会卡住实现的问题（3 处直接跑不起来）：

| # | 初稿写法 | 问题 | 现在 |
|---|---|---|---|
| 1 | `from app.core.security import require_permission` | `require_permission` 在 `app.core.permissions` → ImportError | Task 3 Step 6 已改 |
| 2 | 迁移 `0022_front_settings` | `0022_tools` 已占用 → alembic 双 head | 改 `0023_front_settings` / `down_revision="0022_tools"` |
| 3 | TypedDict 里 `def: Any`、`def=` | `def` 是 Python 关键字 → SyntaxError | Python / JSON / TS 三处统一用 `default` |
| 4 | 集成测试用 `auth` / `operator_auth` fixture | 全仓没有这两个 fixture | Task 3 Step 1 自建（照抄 `test_templates_api.py:15-33`） |
| 5 | Task 4 就删 `HOT_PARAMS` / `hotParamByName` | 还被 `HotUpdateSettings.vue:9` 与 `SettingsView.vue:12` 引用 → Task 4 检查点必红 | 删除挪到 Task 9 Step 4 |
| 6 | i18n 用 `set.reset` + `set.reset.body` 点号字面量键 | vue-i18n v9 按 `.` 拆路径，字符串叶子挡路 → `t()` 渲染出原始 key | 全部改成嵌套（`set.reset.label` / `set.reset.body`） |
| 7 | toast 文案放 `set` 模块的 `'toast.set.saved'` | 两个 locale 都没有根级 `toast` 模块 → `t('toast.set.saved')` 取不到 | 改 `set.toast.saved` / `set.toast.reset` / `tpl.toast.hot` |
| 8 | `liveValue(rows: MachineParamRow[])` | spec 里的字面量只有 3 个字段 → TS2345 | 改 `Pick<MachineParamRow,'key'\|'actual'\|'expected'>` |
| 9 | `templatesApi.create({name,effect,platform,status,fields,desc})` | `scene` / `minVramGb` 是必填 → TS 报错 | Task 9 Step 3 已补 `scene: ''`、`minVramGb: null` |
| 10 | 用 `ConfirmDialog.vue` | 它在 `components/`（非 `proto/`）且内部用 antd，与"本页不用 antd"冲突 | 放宽约束：复用既有组件，注明"不新增 antd 组件" |
| 11 | `import tpl from './tpl'` 插在 sessions 与 settings 之间 | 字母序应在 `templates` 与 `traffic` 之间 | Task 5 Step 6 已改 |
| 12 | PSwitch 测试片段是伪代码 | 既有 `proto.spec.ts:140-166` 是 `createApp(defineComponent({data,render}))` 挂载 | Task 6 Step 1 改为"沿用既有挂载代码，只改断言" |
| 13 | 错误消息里回显 `raw!r` | `ApiError` 的 docstring 明写 "Never carries input values" | Task 3 Step 5 已去掉输入回显 |
| 14 | `latest.updated_at.isoformat()` | SQLite 返回 naive datetime，`isoformat()` 会丢时区 | 改用 `app.schemas.common.iso_utc()` |

另外两处已按仓库约定对齐（非缺陷但会影响风格）：

- **service 层抛 `ValueError` 子类、router 层映射成 `ApiError`**（与 `config_service` / `config.py` 一致），
  不在 service 里直接抛 `ApiError`。
- **`value` 列宽 2048**（`param_config` 是 1024），注释已改成"同一思路，放宽到 2048 以容下 2000 字的提示词"，
  不再声称"与 `param_config` 同口径"。

