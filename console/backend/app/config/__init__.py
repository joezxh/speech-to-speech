from ._app import AppSettings, settings
from ._auth import AuthSettings
from ._console import ConsoleSettings
from ._database import DatabaseSettings
from ._demo import DemoSettings

app = settings
console = ConsoleSettings()
database = DatabaseSettings()
auth = AuthSettings()
demo = DemoSettings()

if not auth.jwt_secret_key:
    raise RuntimeError("JWT_SECRET_KEY is required; console refuses to start without it")

__all__ = [
    "AppSettings",
    "AuthSettings",
    "ConsoleSettings",
    "DatabaseSettings",
    "DemoSettings",
    "app",
    "auth",
    "console",
    "database",
    "demo",
    "settings",
]
