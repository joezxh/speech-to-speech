"""Console backend test bootstrap.

The settings objects are module-level singletons read at import time, so the
env has to be in place before `app.config` is imported. Values point at the
repo's real config/catalog so later tasks exercise the same files the image
ships; only the database is redirected to a per-run temp file.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
_REPO = _BACKEND.parent.parent

sys.path.insert(0, str(_BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="s2s-console-tests-"))

# `app.main` builds one module-level app at import time and `mount_spa` refuses
# to boot without a dist (spec §10.2.3), so the import path needs a real dir.
_STATIC = _TMP / "static"
(_STATIC / "assets").mkdir(parents=True)
(_STATIC / "index.html").write_text("<!doctype html><div id=app></div>", encoding="utf-8")

os.environ.setdefault("STATIC_DIR", str(_STATIC))

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-at-least-32-bytes")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP / 'console.sqlite3').as_posix()}")
os.environ.setdefault("USAGE_DB_PATH", str(_TMP / "usage.sqlite3"))
os.environ.setdefault("PARAM_CONFIG_DIR", str(_REPO / "config"))
os.environ.setdefault("PARAM_CATALOG_PATH", str(_REPO / "docs" / "parameter-catalog.yaml"))
os.environ.setdefault("RESTART_MODE", "noop")
os.environ.setdefault("VENV_VERIFIER_MODE", "noop")
