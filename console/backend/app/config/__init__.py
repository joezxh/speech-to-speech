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

if not auth.jwt_secret_key:
    raise RuntimeError("JWT_SECRET_KEY is required; console refuses to start without it")

__all__ = [
    "AppSettings",
    "AuthSettings",
    "BootstrapSettings",
    "ConsoleSettings",
    "DatabaseSettings",
    "DemoSettings",
    "app",
    "auth",
    "bootstrap",
    "console",
    "database",
    "demo",
    "settings",
]
