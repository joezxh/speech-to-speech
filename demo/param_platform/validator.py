"""Decide whether a rendered profile may go live.

Two tiers, because the same code runs in two places.

*Runtime mode* — `speech_to_speech` is importable, so `load_config`,
`validate_config` and `resolve_config` decide. The platform never re-implements
those rules; it calls them and formats their failures. `resolve_config` is also
where `{env: NAME}` references are resolved, so a missing variable surfaces here
rather than as a credential error at startup.

*Structural mode* — the demo container ships without the runtime package. The
schema shape and the value types (against the catalog) are still checked, and
the result says `mode: structural` so the console can refuse to publish instead
of implying the config was verified.

The catalog is the only source of types and defaults. Duplicating defaults here
would let the two drift, which is the failure mode spec §8.3 rules out.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("s2s.params")

TOP_LEVEL_KEYS = {"schema_version", "runtime", "blocks", "pipelines"}
STAGES = ("vad", "stt", "llm", "tts")

# Measured on an RTX 5070 Ti Laptop (12 GB): VAD + STT + TTS hold ~4.6 GB per
# pipeline. Leave 15 % headroom for fragmentation and the CUDA context.
DEFAULT_PIPELINE_VRAM_GB = 4.6
VRAM_HEADROOM = 0.85

# `.*?` rather than `[^:]+?`: a Windows temp path starts with `C:`, and a
# colon-free file segment silently fails to match there, leaving every runtime
# error without a field name on the very host this demo usually runs on.
_LOCATION = re.compile(r"^(?P<file>.*?)(?::\d+){0,2}: (?P<rest>.+)$")
_FIELD = re.compile(r"^(?P<field>[A-Za-z_][A-Za-z0-9_.]*): (?P<message>.+)$")

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    # `type(v) is int` rather than `isinstance`: `True` is an int in Python, and
    # a boolean where an integer belongs is the mistake this is here to catch.
    "integer": lambda v: type(v) is int,
    "float": lambda v: type(v) in (int, float),
    "boolean": lambda v: type(v) is bool,
    "list": lambda v: isinstance(v, list),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def _runtime():
    """The runtime's config trio, or None when the package is absent."""
    try:
        from speech_to_speech.config import (  # noqa: PLC0415 - optional dependency
            ConfigurationError,
            load_config,
            resolve_config,
            validate_config,
        )
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        return None
    return ConfigurationError, load_config, validate_config, resolve_config


def _ensure_runtime_importable() -> None:
    """Make this checkout's `speech_to_speech` the one that gets imported.

    Two layouts need handling. A demo run from a bare checkout only has `src/`
    on disk, so it has to be added to `sys.path`. And a virtualenv may already
    hold a *different* `speech_to_speech` — the published runtime predates the
    YAML config layer — which the failed import has already cached. A
    `sys.modules` hit wins over `sys.path`, so adding the source tree is not
    enough; the cached package has to go, or the validator would report
    structural mode on the very machine that has the full check.
    """
    if _runtime() is not None:
        return

    src = Path(__file__).resolve().parent.parent.parent / "src"
    if not src.is_dir():
        return
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    for name in [key for key in sys.modules if key.split(".")[0] == "speech_to_speech"]:
        del sys.modules[name]


def is_env_ref(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"env"} and isinstance(value["env"], str)


def validate(
    text: str,
    profile: str,
    *,
    entries: dict[str, Any],
    patches: dict[str, Any] | None = None,
    environ: dict[str, str] | None = None,
    vram_gb: float | None = None,
) -> dict[str, Any]:
    """`{ok, mode, errors, warnings, checks, resolved}`.

    `patches` are the values this publish touched, so type errors can name the
    parameter instead of a YAML line. `environ` is the merged view of the
    process environment and the rendered `.env`.
    """
    shape_errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: dict[str, str] = {}

    try:
        document = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return {
            "ok": False,
            "mode": "structural",
            "errors": [{"field": None, "message": f"YAML does not parse: {exc}"}],
            "warnings": [],
            "checks": {"parse": "failed"},
            "resolved": {},
        }
    if not isinstance(document, dict):
        return {
            "ok": False,
            "mode": "structural",
            "errors": [{"field": None, "message": "the top level is not a mapping"}],
            "warnings": [],
            "checks": {"parse": "failed"},
            "resolved": {},
        }
    checks["parse"] = "ok"

    shape_errors.extend(_check_structure(document, profile))
    checks["structure"] = "ok" if not shape_errors else "failed"

    type_errors: list[dict[str, Any]] = []
    if patches:
        type_errors, type_warnings = check_values(patches, entries)
        warnings.extend(type_warnings)
        checks["types"] = "ok" if not type_errors else "failed"

    trio = _runtime()
    if trio is None:
        _ensure_runtime_importable()
        trio = _runtime()
    resolved: dict[str, Any] = {}
    if trio is None:
        checks["load"] = "skipped: speech_to_speech is not importable"
        checks["resolve"] = "skipped"
        mode = "structural"
        runtime_errors: list[dict[str, Any]] = []
    else:
        mode = "runtime"
        runtime_errors, resolved = _run_runtime(text, profile, trio, environ or {})
        checks["load"] = "ok" if not runtime_errors else "failed"
        checks["resolve"] = "ok" if not runtime_errors else "skipped"

    budget_errors, budget_note = _check_vram(resolved, document, profile, vram_gb)
    checks["vram"] = budget_note

    # The runtime's own checks cover the same shape rules, so in runtime mode a
    # structural error on a field it already flagged is the same problem said
    # twice — and its second wording (a file, a line, a column) is the good one.
    errors = _merge_errors(shape_errors, type_errors, runtime_errors, budget_errors)

    return {
        "ok": not errors,
        "mode": mode,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "resolved": resolved,
    }


def _merge_errors(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Concatenate, then keep only the last report of any one `field`.

    Later groups are more authoritative: the runtime knows a line number, the
    catalog knows the type, the shape check only knows the schema. An error with
    no field is kept as-is, because two document-level complaints are usually
    two different complaints.
    """
    merged: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for group in groups:
        for error in group:
            field = error.get("field")
            if field and field in seen:
                merged[seen[field]] = error
                continue
            if field:
                seen[field] = len(merged)
            merged.append(error)
    return merged


def check_values(
    patches: dict[str, Any], entries: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Catalog-driven type, enum and required checks.

    A `{env: NAME}` reference is exempt: its value does not exist yet, and
    resolving it here would duplicate what `resolve_config` already does.
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for key, value in patches.items():
        entry = entries.get(key)
        if entry is None:
            errors.append({"field": key, "message": "unknown parameter"})
            continue

        if value is None:
            if entry.required:
                errors.append(
                    {
                        "field": key,
                        "message": "this parameter is required and cannot be unset",
                        "source_ref": entry.source_ref,
                    }
                )
            continue

        if isinstance(value, str) and value.strip().startswith("{env:"):
            # Spec §12 R9: quoted, this is a literal string, not a reference.
            warnings.append(
                {
                    "field": key,
                    "message": 'looks like a quoted "{env: NAME}"; it must be a mapping',
                }
            )
            continue

        if is_env_ref(value):
            continue

        validator = _TYPE_CHECKS.get(entry.type)
        if validator is not None and not validator(value):
            errors.append(
                {
                    "field": key,
                    "message": f"expected {entry.type}, got {type(value).__name__}",
                    "source_ref": entry.source_ref,
                }
            )
            continue

        if entry.choices and value not in entry.choices:
            # `null` in `choices` means the key may be explicitly cleared, and
            # that case is handled by the `value is None` branch above.
            errors.append(
                {
                    "field": key,
                    "message": f"expected one of {entry.choices}, got {value!r}",
                    "source_ref": entry.source_ref,
                }
            )

    return errors, warnings


def _check_structure(document: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []

    extra = set(document) - TOP_LEVEL_KEYS
    if extra:
        errors.append(
            {"field": None, "message": f"unknown top-level keys: {', '.join(sorted(extra))}"}
        )

    if document.get("schema_version") != 1:
        errors.append(
            {"field": "schema_version", "message": "must be the integer 1"}
        )

    blocks = document.get("blocks")
    pipelines = document.get("pipelines")
    if not isinstance(blocks, dict) or not blocks:
        errors.append({"field": "blocks", "message": "must be a nonempty mapping"})
    if not isinstance(pipelines, dict) or not pipelines:
        errors.append({"field": "pipelines", "message": "must be a nonempty mapping"})
        return errors

    if profile not in pipelines:
        errors.append({"field": f"pipelines.{profile}", "message": "the profile is not defined"})
        return errors

    pipeline = pipelines[profile]
    if not isinstance(pipeline, dict):
        errors.append({"field": f"pipelines.{profile}", "message": "must be a mapping"})
        return errors

    stages = pipeline.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        errors.append(
            {
                "field": f"pipelines.{profile}.stages",
                "message": f"must reference exactly {', '.join(STAGES)}",
            }
        )

    count = pipeline.get("num_pipelines", 1)
    if not is_env_ref(count) and (type(count) is not int or count < 1):
        errors.append(
            {
                "field": f"pipelines.{profile}.num_pipelines",
                "message": "must be a positive integer",
            }
        )

    return errors


def _run_runtime(
    text: str,
    profile: str,
    trio: tuple[Any, ...],
    environ: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    configuration_error, load_config, validate_config, resolve_config = trio

    with tempfile.TemporaryDirectory(prefix="s2s-params-") as directory:
        path = Path(directory) / f"{profile}.yaml"
        path.write_text(text, encoding="utf-8")
        try:
            document = load_config(path)
            validate_config(document)
            resolved = resolve_config(
                document,
                names=[profile],
                # The rendered `.env` wins over the process environment: that
                # file is what the container will actually see.
                environ={**os.environ, **environ},
            )
        except configuration_error as exc:
            return [_parse_error(str(exc))], {}

    pipeline = resolved.pipelines[profile]
    return (
        [],
        {
            "pipelines": list(resolved.pipelines),
            "num_pipelines": pipeline.num_pipelines,
            "stages": {name: stage.backend for name, stage in pipeline.stages.items()},
        },
    )


def _parse_error(message: str) -> dict[str, Any]:
    """Split `file:line:col: path: message` into something a form can show.

    `path` is the raw key path the runtime named (`blocks.llm.settings.x`);
    `field` is the same thing only when it parses, because a form needs a key it
    can highlight and a message it can print verbatim.
    """
    detail: dict[str, Any] = {"field": None, "path": None, "message": message}
    location = _LOCATION.match(message)
    if location is None:
        return detail

    rest = location.group("rest")
    field = _FIELD.match(rest)
    if field is not None:
        detail["field"] = field.group("field")
        detail["path"] = field.group("field")
        detail["message"] = field.group("message")
    return detail


def _check_vram(
    resolved: dict[str, Any],
    document: dict[str, Any],
    profile: str,
    vram_gb: float | None,
) -> tuple[list[dict[str, Any]], str]:
    count = (resolved or {}).get("num_pipelines")
    if type(count) is not int:
        # Structural mode produces no `resolved`, and an untouched
        # `num_pipelines` is absent from the patch. Read it from the rendered
        # document so the budget is checked on every path.
        pipeline = (document.get("pipelines") or {}).get(profile)
        if isinstance(pipeline, dict):
            count = pipeline.get("num_pipelines", 1)
    if type(count) is not int:
        return [], "skipped: no integer num_pipelines to budget"

    limit = os.environ.get("PARAM_VRAM_GB", "").strip()
    available = vram_gb if vram_gb is not None else (float(limit) if limit else None)
    if available is None:
        # The demo container has no nvidia-smi and no torch. Refusing every
        # publish would be worse than saying the budget was not checked.
        return [], "skipped: set PARAM_VRAM_GB to enable the budget check"

    per_pipeline = float(
        os.environ.get("PARAM_PIPELINE_VRAM_GB", "").strip() or DEFAULT_PIPELINE_VRAM_GB
    )
    max_allowed = int(available * VRAM_HEADROOM // per_pipeline)
    if count <= max_allowed:
        return [], f"ok: {count} <= {max_allowed}"

    return (
        [
            {
                "field": "runtime.num_pipelines",
                "message": (
                    f"{count} pipelines need about {per_pipeline * count:.1f} GB, "
                    f"but {available:.1f} GB allows {max_allowed} "
                    f"({per_pipeline} GB each, {int(VRAM_HEADROOM * 100)}% headroom)"
                ),
                "details": {
                    "max_allowed": max_allowed,
                    "available_gb": available,
                    "per_pipeline_gb": per_pipeline,
                },
            }
        ],
        f"failed: {count} > {max_allowed}",
    )
