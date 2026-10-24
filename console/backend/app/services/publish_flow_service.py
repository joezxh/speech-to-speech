"""Steps 2–4 of chain A: turn a set of values into bytes and validate them.

Nothing here writes. `publish_service` (Task 15) owns the writes, which is what
keeps the rollback ordering reviewable in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import console
from app.core.errors import ApiError
from app.services import catalog_service, renderer_service, validator_service


@dataclass(frozen=True)
class Rendered:
    """What a set of values turns into, before anything is written."""

    text: str
    values: dict[str, Any]
    applied: list[str] = field(default_factory=list)
    env_text: str | None = None
    expected_size: int | None = None
    resolved: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def profile_path(profile: str) -> Path:
    return Path(console.param_config_dir) / f"{profile}.yaml"


def env_path(profile: str) -> Path:
    """`config/<profile>.env`, the file compose names in `env_file`.

    Not `.env`: compose reads that from the project root for its own variable
    interpolation, and writing there would leave the container still reading
    the values this publish was supposed to replace.
    """
    return Path(console.param_config_dir) / f"{profile}.env"


def require_profile(profile: str) -> Path:
    path = profile_path(profile)
    if not path.is_file():
        raise ApiError("unknown_profile", f"{path.name} does not exist", 404)
    return path


def entries() -> dict[str, catalog_service.Entry]:
    loaded = catalog_service.load()
    if not loaded.available:
        raise ApiError("catalog_unavailable", loaded.hint or "catalog not mounted", 503)
    return loaded.by_key()


def live_version(profile: str, versions) -> int:
    """0 when nothing has been published yet, which is what `If-Match` compares."""
    latest = versions.latest_live(profile)
    return int(latest.version) if latest else 0


def render(profile: str, values: dict[str, Any], *, environ: dict[str, str] | None = None) -> Rendered:
    """`config/<profile>.yaml` plus `values`, validated. Nothing is written.

    A refused key aborts the render: publishing the half of a patch that
    happened to apply is how a deployed file ends up different from the one
    that was reviewed.
    """
    path = require_profile(profile)
    known = entries()
    base = renderer_service.load_base(path)
    yaml_patches, env_patches = renderer_service.split_patches(values, known)
    text, applied, refused = renderer_service.render_yaml(base, profile, yaml_patches, known)
    if refused:
        raise ApiError(
            "invalid_parameter",
            "some parameters have no place in this profile's YAML",
            400,
            detail=refused,
        )

    env_text: str | None = None
    if env_patches:
        existing = env_path(profile).read_text(encoding="utf-8") if env_path(profile).is_file() else ""
        env_text, _ = renderer_service.render_env(existing, env_patches)

    # The rendered `.env` wins over the process environment: it is the file the
    # container will actually read.
    merged = {**os.environ, **renderer_service.parse_env(env_text or ""), **(environ or {})}
    result = validator_service.validate(
        text, profile, entries=known, patches=values, environ=merged, vram_gb=vram_budget()
    )
    if not result["ok"]:
        raise ApiError(
            validation_code(result["errors"]),
            "the rendered profile does not pass validation",
            422,
            detail=result["errors"],
        )

    return Rendered(
        text=text,
        values=values,
        applied=applied,
        env_text=env_text,
        expected_size=expected_size(result, text, profile),
        resolved=result["resolved"],
        warnings=result["warnings"],
    )


def validation_code(errors: list[dict[str, Any]]) -> str:
    """A budget failure is a different answer than a typo; A.5 separates them."""
    for error in errors:
        if error.get("field") == "runtime.num_pipelines" and error.get("details"):
            return "vram_budget_exceeded"
    return "validation_failed"


def expected_size(result: dict[str, Any], text: str, profile: str) -> int | None:
    """How many units the new YAML asks for, or None when that cannot be known.

    `{env: N}` for `num_pipelines` only resolves at startup, so the pool is then
    judged on reachability alone — inventing a size and failing on it would
    refuse a config that is actually correct.
    """
    count = (result.get("resolved") or {}).get("num_pipelines")
    if type(count) is int:
        return count
    try:
        document = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None
    pipeline = (document.get("pipelines") or {}).get(profile)
    if not isinstance(pipeline, dict):
        return None
    count = pipeline.get("num_pipelines", 1)
    return count if type(count) is int else None


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        from loguru import logger

        logger.warning("ignoring {}={!r}: not a number", name, raw)
        return None


def vram_budget() -> float | None:
    return _float_env("PARAM_VRAM_GB")


def health_timeout() -> float:
    return _float_env("PARAM_HEALTH_TIMEOUT") or 180.0
