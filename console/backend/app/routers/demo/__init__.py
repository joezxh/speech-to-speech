"""The demo face: byte-compatible with `demo/server.py` (A.13), never enveloped."""

from . import config, me

ROUTERS = (config.router, me.router)

__all__ = ["ROUTERS", "config", "me"]
