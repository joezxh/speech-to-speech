"""The demo face: byte-compatible with `demo/server.py` (A.13), never enveloped."""

from . import config

ROUTERS = (config.router,)

__all__ = ["ROUTERS", "config"]
