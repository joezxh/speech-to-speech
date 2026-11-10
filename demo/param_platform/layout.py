"""Where a catalog entry lives in `config/<profile>.yaml`.

The catalog's `stage` is a documentation grouping, not a YAML location. The real
layout is the three-layer model in `docs/configuration.md:15-32`:

    blocks.<block>.settings.<param>     component settings (vad / stt / llm / tts)
    blocks.<block>.backend              the selector that picks the implementation
    pipelines.<p>.stages.<stage>        which block serves each stage
    pipelines.<p>.options.<param>       per-pipeline overrides (ModuleArguments)
    pipelines.<p>.num_pipelines         isolated instance count
    runtime.<param>                     process level, only _MODULE_PROCESS
    runtime.server.<param>              RealtimeServerArguments
    runtime.client.<param>              RealtimeAudioClientConfig

Getting this wrong is silent: the file still parses, and `resolve_config` fails
later with a message about a different key. That is why the mapping is one table
rather than inference from `stage`.

Two catalog stages reach no YAML at all: `deploy` (build args, compose keys) and
`env` (the .env file). Both are reported to the caller, never silently dropped.

Read-only for now. The write side belongs with `renderer`, which must also prune
containers that a delete emptied.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

# `config.py:23 _MODULE_PROCESS`: the only keys allowed directly under `runtime`.
# Everything else the catalog files under `stage: runtime` is a ModuleArguments
# field, which lives under `pipelines.<p>.options`.
PROCESS_LEVEL = frozenset({"log_level", "log_transcripts", "torch_num_threads"})

# `config.py:24 _MODULE_SELECTORS`: these name a backend instead of configuring one.
SELECTORS = {"llm_backend": "llm", "stt": "stt", "tts": "tts"}

BLOCK_STAGES = frozenset({"vad", "stt", "llm", "tts"})

UNREACHABLE = {
    "deploy": "build args and compose keys — edit the compose file",
    "env": "written to the .env file, not the YAML",
}

# Distinguishes "key absent" from "key present with value null": a null in the
# YAML means "unset this", which the console should show differently from "this
# parameter is not in the file".
MISSING = object()


def locate(document: dict[str, Any], profile: str, entry: Any) -> tuple[list[str] | None, str]:
    """The path `entry` occupies, or `(None, reason)` when it occupies none."""
    stage, name = entry.stage, entry.name

    if entry.type == "fixed":
        # `source_priority: [code_constant]` — chunk_samples is 512 in service.py,
        # cors_policy is "no CORSMiddleware installed". Editing is not configuration.
        return None, "code constant, not configurable"

    if stage in UNREACHABLE:
        return None, UNREACHABLE[stage]

    if stage == "server":
        return ["runtime", "server", name], ""

    if stage == "client":
        return ["runtime", "client", name], ""

    if stage == "runtime":
        if name in PROCESS_LEVEL:
            return ["runtime", name], ""
        if name == "num_pipelines":
            return ["pipelines", profile, "num_pipelines"], ""
        if name in SELECTORS:
            block = block_for(document, SELECTORS[name], entry.backend)
            if block is None:
                return None, f"no {SELECTORS[name]!r} block with backend {entry.backend!r}"
            return ["blocks", block, "backend"], ""
        # device, diarization_*, llm_backend's siblings: per-pipeline overrides.
        return ["pipelines", profile, "options", name], ""

    if stage in BLOCK_STAGES:
        block = block_for(document, stage, entry.backend)
        if block is None:
            return None, f"no {stage!r} block with backend {entry.backend!r}"
        return ["blocks", block, "settings", name], ""

    return None, f"unknown stage {stage!r}"


def block_for(document: dict[str, Any], kind: str, backend: str | None = None) -> str | None:
    """The block ID serving `kind`, optionally restricted to one backend.

    `docs/configuration.md` allows several blocks to share a backend with
    different settings, and the patch key `<stage>.<name>` cannot say which one
    it means. Refusing beats writing to an arbitrary block.

    `backend` is the implementation the catalog entry names. Passing it matters:
    `llm.model_name` exists once for the local backend and once for
    responses-api, so without the filter the responses-api default would be
    read from — and later written into — a chat-completions block.
    """
    blocks = document.get("blocks")
    if not isinstance(blocks, dict):
        return None

    same_kind = [
        block_id
        for block_id, block in blocks.items()
        if isinstance(block, dict) and block.get("kind") == kind
    ]
    if backend:
        same_kind = [b for b in same_kind if blocks[b].get("backend") == backend]
    if len(same_kind) == 1:
        return same_kind[0]
    return None


def read(document: dict[str, Any], path: Sequence[str]) -> Any:
    """The value at `path`, or `MISSING`."""
    node: Any = document
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return MISSING
        node = node[key]
    return node


def read_values(
    document: dict[str, Any], profile: str, entries: Iterable[Any]
) -> dict[str, Any]:
    """`{<stage>.<name>: value}` for every entry the document actually sets.

    Entries the file leaves out are absent from the result rather than filled
    with the catalog default: "not in the file" and "explicitly set to the
    default" are different states, and only the first one means the platform can
    still adopt a new default.
    """
    values: dict[str, Any] = {}
    for entry in entries:
        path, _ = locate(document, profile, entry)
        if path is None:
            continue
        value = read(document, path)
        if value is not MISSING:
            values[entry.key] = value
    return values


def stage_backends(document: dict[str, Any], profile: str) -> dict[str, str | None]:
    """`{stage: backend}` for one pipeline, resolving the block references."""
    pipeline = (document.get("pipelines") or {}).get(profile)
    if not isinstance(pipeline, dict):
        return {}
    stages = pipeline.get("stages")
    if not isinstance(stages, dict):
        return {}

    blocks = document.get("blocks") or {}
    resolved: dict[str, str | None] = {}
    for stage, block_id in stages.items():
        block = blocks.get(block_id) if isinstance(blocks, dict) else None
        resolved[str(stage)] = block.get("backend") if isinstance(block, dict) else None
    return resolved


# ── write side ───────────────────────────────────────────────────────────────


def apply(
    document: dict[str, Any],
    profile: str,
    patches: dict[str, Any],
    entries: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    """Apply `{<stage>.<name>: value}` to `document` in place.

    A `null` value *deletes* the key rather than writing YAML null. That is what
    "go back to the default" has to mean: `validate_config` reads an explicit
    null as a value, while an omitted key is what lets a later change to the
    dataclass default take effect.

    Returns the keys applied and the ones refused, each with its reason, so a
    partial patch is never reported as a complete one.
    """
    applied: list[str] = []
    refused: list[dict[str, str]] = []

    for key, value in patches.items():
        entry = entries.get(key)
        if entry is None:
            refused.append({"key": key, "reason": "unknown parameter"})
            continue
        path, reason = locate(document, profile, entry)
        if path is None:
            refused.append({"key": key, "reason": reason})
            continue
        if value is None:
            _discard(document, path)
        else:
            _assign(document, path, value)
        applied.append(key)

    prune(document)
    return applied, refused


def _assign(document: dict[str, Any], path: Sequence[str], value: Any) -> None:
    node: Any = document
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            # `settings` or `options` may be absent on a block that has always
            # run on defaults; create it rather than failing the whole patch.
            child = {}
            node[key] = child
        node = child
    node[path[-1]] = value


def _discard(document: dict[str, Any], path: Sequence[str]) -> None:
    node: Any = document
    for key in path[:-1]:
        if not isinstance(node, dict) or key not in node:
            return
        node = node[key]
    if isinstance(node, dict):
        node.pop(path[-1], None)


def prune(document: dict[str, Any]) -> None:
    """Drop the containers a delete emptied.

    `settings: {}` is legal but it makes the file claim something it does not
    mean, and it hides "this block is entirely on defaults" from a diff. Blocks
    themselves are never dropped: `pipelines.<p>.stages` references them by ID.
    """
    blocks = document.get("blocks")
    if isinstance(blocks, dict):
        for block in blocks.values():
            if isinstance(block, dict) and block.get("settings") == {}:
                block.pop("settings")

    pipelines = document.get("pipelines")
    if isinstance(pipelines, dict):
        for pipeline in pipelines.values():
            if isinstance(pipeline, dict) and pipeline.get("options") == {}:
                pipeline.pop("options")
