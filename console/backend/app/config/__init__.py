"""控制台配置入口（spec 2026-11-17 §4）。

对外仍然是 `from app.config import console` 这种用法，属性访问照旧；
区别是取值改成**库优先、env 兜底**：库里有值就用库里的（改表后数秒内生效），
库里没有或读库失败就回退环境变量默认值。

`database`（要先有连接串才能连库）与 `auth`（密钥）**保持现状走 env**。
"""

from __future__ import annotations

import socket
from typing import Any

from ._allocator import AllocatorSettings
from ._app import AppSettings, settings
from ._auth import AuthSettings
from ._bootstrap import BootstrapSettings
from ._console import ConsoleSettings
from ._database import DatabaseSettings
from ._demo import DemoSettings
from ._schema import item_for, items_for_section
from ._store import SOURCE_DB, ConfigStore, coerce
from ._tools import ToolSettings

_app_settings = settings
_console_settings = ConsoleSettings()
_database_settings = DatabaseSettings()
_auth_settings = AuthSettings()
_tools_settings = ToolSettings()
# First boot only; an empty password keeps it off (see services/bootstrap_service.py).
_bootstrap_settings = BootstrapSettings()
_demo_settings = DemoSettings()
# 模块级单例：测试里 monkeypatch(allocator, "mode", "local") 即可切换，
# 也让巡检/分配/挂断路由同一个实例读到一致的开关（spec §12）。
_allocator_settings = AllocatorSettings()


class LiveSettings:
    """库优先的配置门面（spec §4.2）。

    - 读：登记在册的键查配置表（TTL 缓存）；库里没有或值不合法就回退 env 默认值；
      未登记的属性（派生属性、密钥）直接落到原 pydantic 实例。
    - 写：落到门面自己的**覆盖层**（`__dict__`），覆盖层优先于库值。
      之所以不直接改 pydantic 实例：`monkeypatch.setattr(console, "x", v)` 撤销时
      会对门面做 `delattr`，门面身上没有这个属性就会报错；而且改 pydantic 实例是
      改不回去的（那是 env 解析出来的只读快照）。覆盖层让撤销=精确还原。
    """

    def __init__(self, section: str, settings_obj: Any, store: ConfigStore) -> None:
        object.__setattr__(self, "_section", section)
        object.__setattr__(self, "_settings", settings_obj)
        object.__setattr__(self, "_store", store)

    @property
    def section(self) -> str:
        return object.__getattribute__(self, "_section")

    def __getattr__(self, name: str) -> Any:
        # 只在常规属性查找失败时触发；内部属性与显式赋值都走正常路径。
        settings_obj = object.__getattribute__(self, "_settings")
        item = item_for(self.section, name)
        if item is None:
            return getattr(settings_obj, name)
        store = object.__getattribute__(self, "_store")
        raw, source = store.get_raw(item.key)
        if source == SOURCE_DB:
            try:
                return coerce(item, raw)
            except ValueError:
                pass  # 库里存了非法值：回退 env 默认值，别把控制台带崩
        return getattr(settings_obj, name)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        try:
            object.__delattr__(self, name)
        except AttributeError:
            # 覆盖层里没有这个名字：按"本来就没有覆盖"处理（no-op）。
            # 绝不下探删 pydantic 实例的字段——pydantic v2 的字段就在实例
            # `__dict__` 里，一删永失，会把整个进程的取值链路打断（pytest 对
            # 动态属性按 #10644 记 delattr 账，undo 时走到这里，曾把全量测试
            # 炸出 232 个 AttributeError）。
            return

    def __dir__(self) -> list[str]:
        settings_obj = object.__getattribute__(self, "_settings")
        return sorted(set(dir(settings_obj)) | {item.attr for item in items_for_section(self.section)})

    def __repr__(self) -> str:
        return f"<LiveSettings section={self.section!r}>"


class AllocatorLiveSettings(LiveSettings):
    """注册中心分区的门面，派生属性按**生效值**算（不是 env 默认值）。"""

    @property
    def resolved_console_id(self) -> str:
        return str(self.console_id or "").strip() or socket.gethostname()


class DemoLiveSettings(LiveSettings):
    """演示面分区的门面；密钥项（serper_api_key、lb_hf_token）不在登记表内，仍走 env。"""

    @property
    def pinned_url(self) -> str:
        return str(self.speech_to_speech_url or "").strip()

    @property
    def lb_url(self) -> str:
        return "" if self.pinned_url else str(self.load_balancer_url or "").strip()

    @property
    def limiter_enabled(self) -> bool:
        return bool(self.lb_url) and bool(self.space_id)

    @property
    def oauth_configured(self) -> bool:
        return bool(self.oauth_client_id)

    @property
    def auth_enabled(self) -> bool:
        return self.limiter_enabled and self.oauth_configured

    @property
    def server_search(self) -> bool:
        return bool(self.serper_api_key) and (self.auth_enabled or not self.space_id)


def _defaults_for(section: str, source: Any) -> dict[str, Any]:
    """登记项对应的 env 默认值（播种与兜底都用它）。"""
    return {item.attr: getattr(source, item.attr, None) for item in items_for_section(section)}


# 库优先、env 兜底的配置存储（进程内 TTL 缓存；读库失败静默降级）。
store = ConfigStore(
    {
        "app": _defaults_for("app", _app_settings),
        "console": _defaults_for("console", _console_settings),
        "allocator": _defaults_for("allocator", _allocator_settings),
        "demo": _defaults_for("demo", _demo_settings),
        "bootstrap": _defaults_for("bootstrap", _bootstrap_settings),
    }
)

# 对外的门面对象：属性访问不变，取值改成库优先。
app = LiveSettings("app", _app_settings, store)
console = LiveSettings("console", _console_settings, store)
bootstrap = LiveSettings("bootstrap", _bootstrap_settings, store)
demo = DemoLiveSettings("demo", _demo_settings, store)
allocator = AllocatorLiveSettings("allocator", _allocator_settings, store)

# 连接串与密钥不搬进配置表，保持走 env。
database = _database_settings
auth = _auth_settings
tools = _tools_settings
# 原始 pydantic 实例保留给需要直接读 env 解析值的场合。
allocator_settings = _allocator_settings

if not auth.jwt_secret_key:
    raise RuntimeError("JWT_SECRET_KEY is required; console refuses to start without it")

__all__ = [
    "AllocatorLiveSettings",
    "AllocatorSettings",
    "AppSettings",
    "AuthSettings",
    "BootstrapSettings",
    "ConsoleSettings",
    "DatabaseSettings",
    "DemoLiveSettings",
    "DemoSettings",
    "ToolSettings",
    "LiveSettings",
    "app",
    "allocator",
    "allocator_settings",
    "auth",
    "bootstrap",
    "console",
    "database",
    "demo",
    "settings",
    "store",
    "tools",
]
