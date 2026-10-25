"""Load `parameter-catalog.yaml` and expose it to the console.

The catalog is metadata only: what each parameter is, where it comes from, how
exposed it is. It never says where a parameter lives in the deployment YAML —
that is `layout.py`'s job, because the catalog's `stage` is a documentation
grouping rather than a location.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("s2s.params")

# Ordered least to most privileged. `filtered()` treats a level as cumulative:
# requesting `advanced` returns basic + advanced.
EXPOSURE_LEVELS = ("basic", "advanced", "expert", "ops")
_RANK = {level: rank for rank, level in enumerate(EXPOSURE_LEVELS)}

EXPECTED_SCHEMA = "s2s-parameter-catalog-v1"


class CatalogError(RuntimeError):
    """The file exists but cannot be used as a catalog."""


@dataclass(frozen=True)
class Entry:
    stage: str
    backend: str | None
    name: str
    type: str
    default: Any
    choices: tuple[str, ...] = ()
    required: bool = False
    effect: str = ""
    exposure: str = "expert"
    impact: str = ""
    change_cost: str = ""
    risk: str = ""
    source_ref: str = ""
    source_priority: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """The patch key shape the API uses: `<stage>.<name>`.

        Ambiguous when one stage holds several blocks of the same kind; `layout`
        refuses those rather than guessing a block.
        """
        return f"{self.stage}.{self.name}"

    def as_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "stage": self.stage,
            "backend": self.backend,
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "choices": list(self.choices),
            "required": self.required,
            "effect": self.effect,
            "exposure": self.exposure,
            "impact": self.impact,
            "change_cost": self.change_cost,
            "risk": self.risk,
            "source_ref": self.source_ref,
            "source_priority": list(self.source_priority),
        }


@dataclass
class Catalog:
    available: bool
    hint: str = ""
    path: str = ""
    schema: str = ""
    generated_from: str = ""
    generated_at: str = ""
    entries: list[Entry] = field(default_factory=list)
    # `<stage>.<name>` that more than one backend defines with a different
    # default: `llm.model_name` is `Qwen/Qwen3.5-4B` for the local backend and
    # `gpt-5.6-terra` for responses-api. Not a defect — a profile serves each
    # stage with exactly one backend, so only one variant can ever be located.
    variant_keys: list[str] = field(default_factory=list)

    def by_key(self) -> dict[str, Entry]:
        """First entry per key.

        Ambiguous for `variant_keys`, where the backend decides which default
        applies. Use `entries_for()` there.
        """
        index: dict[str, Entry] = {}
        for entry in self.entries:
            index.setdefault(entry.key, entry)
        return index

    def entries_for(self, key: str) -> list[Entry]:
        """Every backend variant sharing `key`."""
        return [entry for entry in self.entries if entry.key == key]

    def filtered(self, *, exposure: str | None = None, stage: str | None = None) -> list[Entry]:
        """Entries up to and including `exposure`, optionally one stage only."""
        if exposure is None:
            limit = len(EXPOSURE_LEVELS) - 1
        else:
            limit = _RANK.get(exposure, -1)
            if limit < 0:
                raise CatalogError(f"unknown exposure {exposure!r}")
        selected = []
        for entry in self.entries:
            rank = _RANK.get(entry.exposure, -1)
            # An unknown exposure is a catalog defect; excluding it is safer than
            # letting a typo silently widen the console.
            if rank < 0 or rank > limit:
                continue
            if stage and entry.stage != stage:
                continue
            selected.append(entry)
        return selected


# Parsing 88 KB of YAML on every console refresh is wasteful, and the file only
# changes when someone edits it, so cache on (path, mtime).
_cache: dict[Path, tuple[float, Catalog]] = {}


def load(path: Path | None = None) -> Catalog:
    target = path or default_path()
    if target is None:
        return Catalog(
            available=False,
            hint="no parameter-catalog.yaml found; set PARAM_CATALOG_PATH",
        )
    try:
        mtime = target.stat().st_mtime
    except OSError as exc:
        return Catalog(available=False, hint=f"cannot stat {target}: {exc}")

    cached = _cache.get(target)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        loaded = _read(target)
    except CatalogError as exc:
        logger.warning("catalog %s rejected: %s", target, exc)
        loaded = Catalog(available=False, path=str(target), hint=str(exc))
    _cache[target] = (mtime, loaded)
    return loaded


def default_path() -> Path | None:
    """First readable catalog. Two layouts, because the same code runs in a
    container (catalog copied beside the app) and in the repo (`docs/`)."""
    explicit = os.environ.get("PARAM_CATALOG_PATH", "").strip()
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.is_file() else None

    here = Path(__file__).resolve().parent.parent
    for candidate in (
        here / "catalog" / "parameter-catalog.yaml",
        here.parent / "docs" / "parameter-catalog.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None


def _read(target: Path) -> Catalog:
    try:
        document = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"cannot parse {target.name}: {exc}") from exc

    if not isinstance(document, dict):
        raise CatalogError(f"{target.name} must be a mapping at the top level")

    schema = str(document.get("schema") or "")
    if schema != EXPECTED_SCHEMA:
        # A silently accepted wrong schema means every field name below is a
        # guess, which is worse than refusing the file.
        raise CatalogError(f"{target.name} schema is {schema!r}, expected {EXPECTED_SCHEMA!r}")

    raw = document.get("parameters")
    if not isinstance(raw, list) or not raw:
        raise CatalogError(f"{target.name} has no `parameters` list")

    entries: list[Entry] = []
    variants: list[str] = []
    seen: set[str] = set()
    for position, row in enumerate(raw):
        entry = _entry(row, position, target)
        if entry.key in seen and entry.key not in variants:
            variants.append(entry.key)
        seen.add(entry.key)
        entries.append(entry)

    if variants:
        logger.info(
            "catalog defines %d key(s) in more than one backend: %s",
            len(variants),
            ", ".join(variants),
        )

    return Catalog(
        available=True,
        path=str(target),
        schema=schema,
        generated_from=str(document.get("generated_from") or ""),
        generated_at=str(document.get("generated_at") or ""),
        entries=entries,
        variant_keys=variants,
    )


def _entry(row: Any, position: int, target: Path) -> Entry:
    if not isinstance(row, dict):
        raise CatalogError(f"{target.name} entry #{position} is not a mapping")
    stage = str(row.get("stage") or "").strip()
    name = str(row.get("name") or "").strip()
    if not stage or not name:
        raise CatalogError(f"{target.name} entry #{position} lacks stage or name")

    exposure = str(row.get("exposure") or "").strip()
    if exposure not in _RANK:
        raise CatalogError(
            f"{target.name} entry {stage}.{name} has exposure {exposure!r}, "
            f"expected one of {', '.join(EXPOSURE_LEVELS)}"
        )

    return Entry(
        stage=stage,
        backend=row.get("backend"),
        name=name,
        type=str(row.get("type") or "").strip(),
        default=row.get("default"),
        choices=tuple(row.get("choices") or ()),
        required=bool(row.get("required")),
        effect=str(row.get("effect") or ""),
        exposure=exposure,
        impact=str(row.get("impact") or ""),
        change_cost=str(row.get("change_cost") or ""),
        risk=str(row.get("risk") or ""),
        source_ref=str(row.get("source_ref") or ""),
        source_priority=tuple(row.get("source_priority") or ()),
    )
