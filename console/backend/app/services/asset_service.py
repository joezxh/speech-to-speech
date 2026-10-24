"""`/vendor/*`: build-time assets, runtime whitelist (A.13).

No `node_modules` probing at request time (D10): a missing asset is a broken
image and must say so loudly instead of falling back to a directory that the
runtime image does not contain.
"""

from __future__ import annotations

from pathlib import Path

from app.config import console
from app.core.errors import ApiError

AGENTS_SDK = "openai-realtime-agents.umd.js"

# The six pinned VAD assets and their media types (demo/server.py:179-186).
LOCAL_VAD_ASSETS: dict[str, str] = {
    "bundle.min.js": "text/javascript",
    "vad.worklet.bundle.min.js": "text/javascript",
    "silero_vad_v6.onnx": "application/octet-stream",
    "ort.wasm.min.js": "text/javascript",
    "ort-wasm-simd-threaded.mjs": "text/javascript",
    "ort-wasm-simd-threaded.wasm": "application/wasm",
}


def vendor_dir() -> Path:
    return Path(console.static_dir) / "vendor"


def agents_sdk_path() -> Path:
    return _require(vendor_dir() / AGENTS_SDK)


def vad_path(filename: str) -> tuple[Path, str]:
    """`(path, media_type)`. An unlisted name is not a 503 — it does not exist."""
    media_type = LOCAL_VAD_ASSETS.get(filename)
    if media_type is None:
        raise ApiError("not_found", "no such asset", 404)
    return _require(vendor_dir() / "local-vad" / filename), media_type


def _require(path: Path) -> Path:
    if not path.is_file():
        raise ApiError(
            "asset_missing",
            f"{path.name} is missing from the image; the frontend build did not run",
            503,
        )
    return path
