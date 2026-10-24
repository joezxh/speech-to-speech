from ._app import AppSettings, settings
from ._auth import AuthSettings
from ._console import ConsoleSettings
from ._database import DatabaseSettings

app = settings
console = ConsoleSettings()
database = DatabaseSettings()
auth = AuthSettings()

if not auth.jwt_secret_key:
    raise RuntimeError("JWT_SECRET_KEY is required; console refuses to start without it")

__all__ = [
    "AppSettings",
    "AuthSettings",
    "ConsoleSettings",
    "DatabaseSettings",
    "app",
    "auth",
    "console",
    "database",
    "settings",
]
