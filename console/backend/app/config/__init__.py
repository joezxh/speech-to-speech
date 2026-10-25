from ._allocator import AllocatorSettings
from ._app import AppSettings, settings
from ._auth import AuthSettings
from ._bootstrap import BootstrapSettings
from ._console import ConsoleSettings
from ._database import DatabaseSettings
from ._demo import DemoSettings

app = settings
console = ConsoleSettings()
database = DatabaseSettings()
auth = AuthSettings()
# First boot only; an empty password keeps it off (see services/bootstrap_service.py).
bootstrap = BootstrapSettings()
demo = DemoSettings()
# 模块级单例：测试里 monkeypatch(allocator, "mode", "local") 即可切换，
# 也让巡检/分配/挂断路由同一个实例读到一致的开关（spec §12）。
allocator_settings = AllocatorSettings()
allocator = allocator_settings

if not auth.jwt_secret_key:
    raise RuntimeError("JWT_SECRET_KEY is required; console refuses to start without it")

__all__ = [
    "AllocatorSettings",
    "AppSettings",
    "AuthSettings",
    "BootstrapSettings",
    "ConsoleSettings",
    "DatabaseSettings",
    "DemoSettings",
    "app",
    "allocator",
    "allocator_settings",
    "auth",
    "bootstrap",
    "console",
    "database",
    "demo",
    "settings",
]
