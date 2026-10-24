"""The voice library: what a source binds to, and what deleting one would break.

A voice is not a second configuration channel (spec §3.11): picking one only
produces a patch that goes through A.3 like any other edit. Everything here is
therefore either metadata or a reference count — nothing writes `config/`.
"""

from __future__ import annotations

import io
import os
import wave
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import console
from app.core.errors import ApiError
from app.core.ids import ulid
from app.models.param_draft import ParamDraft
from app.models.param_version import ParamVersion
from app.models.voice import Voice
from app.repositories.voice_repository import VoiceRepository
from app.schemas.common import iso_utc
from app.services import catalog_service

# §3.11.1 is the only field map. `(source, backend)` → `{role: field name}`.
BINDINGS: dict[tuple[str, str], dict[str, str]] = {
    ("builtin", "qwen3"): {"speaker": "qwen3_tts_speaker"},
    ("builtin", "openai_compatible"): {"speaker": "openai_tts_voice"},
    ("builtin", "kokoro"): {"speaker": "kokoro_voice", "language": "kokoro_lang_code"},
    ("clone", "qwen3"): {
        "refAudio": "qwen3_tts_ref_audio",
        "refText": "qwen3_tts_ref_text",
        "refSpk": "qwen3_tts_ref_spk",
        "refRvq": "qwen3_tts_ref_rvq",
    },
    ("design", "qwen3"): {"instruct": "qwen3_tts_instruct"},
    ("design", "openai_compatible"): {
        "instruct": "openai_tts_instructions",
        "taskType": "openai_tts_task_type",
    },
}

# The roles each catalogued backend exposes, regardless of source (§3.11.1).
BACKEND_FIELDS: dict[str, dict[str, str]] = {
    "qwen3": {
        "speaker": "qwen3_tts_speaker",
        "refAudio": "qwen3_tts_ref_audio",
        "refText": "qwen3_tts_ref_text",
        "refSpk": "qwen3_tts_ref_spk",
        "refRvq": "qwen3_tts_ref_rvq",
        "instruct": "qwen3_tts_instruct",
    },
    "openai_compatible": {
        "speaker": "openai_tts_voice",
        "instruct": "openai_tts_instructions",
        "taskType": "openai_tts_task_type",
    },
    "kokoro": {"speaker": "kokoro_voice", "language": "kokoro_lang_code"},
}

# B4 in `docs/parameter-catalog.md`: real backends whose reference-audio fields
# never made it into the machine catalog. They are listed so the console can say
# "not here" instead of hiding them (§3.11.1).
B4_BACKENDS: tuple[tuple[str, str], ...] = (
    ("stt", "paraformer"),
    ("stt", "sensevoice"),
    ("stt", "sense_voice"),
    ("stt", "whisper"),
    ("stt", "faster-whisper"),
    ("stt", "mlx-audio-whisper"),
    ("stt", "nemotron-streaming"),
    ("stt", "orukeet"),
    ("stt", "parakeet-unified"),
    ("stt", "openai-realtime"),
    ("stt", "vllm-realtime"),
    ("tts", "cosyvoice"),
    ("tts", "minimax"),
    ("tts", "pocket"),
    ("tts", "facebookmms"),
    ("tts", "supertonic"),
    ("tts", "omnivoice"),
    ("tts", "drama3"),
    ("tts", "kitten"),
    ("tts", "chat-tts"),
)

SOURCES = ("builtin", "clone", "design")
PATCH_COMPATIBLE = {"qwen3", "openai_compatible", "kokoro"}


def bindings(source: str, backend: str) -> dict[str, str] | None:
    """`None` means "this source is not supported by this backend" — the table
    above decides, so neither side ever guesses from a name prefix."""
    return BINDINGS.get((source, backend))


def conflicts(patch: Mapping[str, Any]) -> list[dict[str, str]]:
    """Cross-field rules that must stop at the draft, before a restart (§3.11.4)."""
    errors: list[dict[str, str]] = []
    if "qwen3_tts_ref_audio" in patch and "qwen3_tts_ref_spk" in patch:
        errors.append({"field": "qwen3_tts_ref_spk", "conflictWith": "qwen3_tts_ref_audio"})
    if "qwen3_tts_ref_rvq" in patch and not {"qwen3_tts_ref_spk", "qwen3_tts_ref_text"} <= set(patch):
        errors.append({"field": "qwen3_tts_ref_rvq", "reason": "requires_spk_and_text"})
    return errors


def _marker(voice_id: str) -> str:
    return f"/voices/{voice_id}/"


def count_references(
    voice_id: str,
    *,
    drafts: Mapping[str, Mapping[str, Any]] | None = None,
    versions: Sequence[tuple[str, int, str]] = (),
) -> dict[str, list]:
    """Profiles and versions whose values point into this voice's directory.

    Drafts count too: deleting a voice a draft still references would make that
    draft unpublishable with no visible cause (§3.11.4).
    """
    marker = _marker(voice_id)
    profiles = sorted(profile for profile, patch in (drafts or {}).items() if marker in repr(patch))
    used = sorted(version for _profile, version, text in versions if marker in text)
    return {"profiles": profiles, "versions": used}


def references(db, voice_id: str) -> dict[str, list]:
    drafts = {row.profile: dict(row.patch or {}) for row in db.scalars(select(ParamDraft)).all()}
    versions = [(row.profile, row.version, row.yaml_text or "") for row in db.scalars(select(ParamVersion)).all()]
    return count_references(voice_id, drafts=drafts, versions=versions)


def voice_dir(voice_id: str) -> Path:
    return Path(console.voice_data_dir) / voice_id


def audio_path(row: Voice) -> Path:
    if not row.audio_relpath:
        raise ApiError("voice_not_found", "this voice has no audio", 404)
    return Path(console.voice_data_dir) / row.audio_relpath


def validate_wav(data: bytes) -> float:
    """PCM16 / 16 kHz / mono, 0 < length <= 30 s — stdlib `wave`, no decoder.

    The pipeline reads 16 kHz mono PCM16; accepting anything else means the
    speaker vector is computed from a resampled guess.
    """
    try:
        with wave.open(io.BytesIO(data)) as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
    except (wave.Error, EOFError) as exc:
        raise ApiError("voice_audio_invalid", "the upload is not a readable WAV file", 400) from exc
    if channels != 1 or width != 2 or rate != 16000:
        raise ApiError(
            "voice_audio_invalid",
            "expected mono 16-bit PCM at 16 kHz",
            400,
            detail=[{"field": "channels", "value": channels}, {"field": "sampleWidth", "value": width}, {"field": "sampleRate", "value": rate}],
        )
    seconds = frames / rate if rate else 0.0
    if seconds <= 0 or seconds > console.voice_max_seconds:
        raise ApiError(
            "voice_audio_invalid",
            f"expected 0 < duration <= {console.voice_max_seconds:g}s",
            400,
            detail=[{"field": "audioSeconds", "value": round(seconds, 3)}],
        )
    return round(seconds, 3)


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_bytes(data)
    os.chmod(path, 0o600)


def _trim(data: bytes, start_ms: int, end_ms: int | None) -> bytes:
    """Rewriting the WAV on save is cheaper than teaching playback about trims."""
    if start_ms <= 0 and end_ms is None:
        return data
    with wave.open(io.BytesIO(data)) as handle:
        params = handle.getparams()
        frames = handle.readframes(handle.getnframes())
    width = 2
    first = max(0, int(start_ms * 16)) * width
    last = len(frames) if end_ms is None else max(first, int(end_ms * 16) * width)
    with io.BytesIO() as out:
        with wave.open(out, "wb") as handle:
            handle.setparams(params)
            handle.writeframes(frames[first:last])
        return out.getvalue()


def ggml_configured() -> bool:
    """`qwen3_tts_backend=ggml` has no spk/rvq entry point, so clone stays on
    `ref_audio` + `ref_text` and skips precompute (§3.11.2)."""
    base = Path(console.param_config_dir)
    if not base.is_dir():
        return False
    for path in base.glob("*.yaml"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("qwen3_tts_backend:") and "ggml" in stripped:
                return True
    return False


def needs_precompute(source: str, backend: str) -> bool:
    if source != "clone" or backend != "qwen3":
        return False
    return not ggml_configured()


def create(
    db,
    *,
    name: str,
    source: str,
    backend: str,
    language: str = "",
    ref_text: str = "",
    instruct: str = "",
    audio: bytes | None,
    trim_start_ms: int = 0,
    trim_end_ms: int | None = None,
    retention_days: int = 30,
    actor: str = "",
) -> Voice:
    """Insert the row and its files. The caller has already checked consent and
    the multipart size limit, in that order (A.18)."""
    clean = name.strip()
    if not clean:
        raise ApiError("validation_failed", "name is required", 422, detail=[{"field": "name"}])
    if len(clean) > 64:
        raise ApiError("validation_failed", "name is longer than 64 characters", 422, detail=[{"field": "name"}])
    if source not in SOURCES:
        raise ApiError("validation_failed", f"unknown source {source!r}", 422, detail=[{"field": "source"}])
    if backend not in PATCH_COMPATIBLE:
        raise ApiError(
            "voice_binding_conflict",
            f"backend {backend!r} has no voice fields in the catalog",
            422,
            detail=[{"field": "backend", "reason": "not_catalogued"}],
        )
    if bindings(source, backend) is None:
        raise ApiError(
            "voice_binding_conflict",
            f"{source} is not supported by {backend}",
            422,
            detail=[{"field": "source", "reason": "unsupported_source"}],
        )
    if VoiceRepository(db).by_name(clean) is not None:
        raise ApiError("voice_name_taken", f"a voice named {clean!r} already exists", 409)

    seconds = 0.0
    if audio is not None:
        seconds = validate_wav(audio)
    if source == "clone" and audio is None:
        raise ApiError("voice_audio_invalid", "clone needs a reference audio", 400)
    if source == "clone" and not ref_text.strip():
        raise ApiError("validation_failed", "clone needs the verbatim transcript", 422, detail=[{"field": "refText"}])
    if source == "design" and not instruct.strip():
        raise ApiError("validation_failed", "design needs an instruction", 422, detail=[{"field": "instruct"}])

    voice_id = ulid()
    row = Voice(
        id=voice_id,
        name=clean,
        source=source,
        backend=backend,
        language=language or None,
        # Only a clone that has to build spk/rvq waits; builtin and design are
        # usable the moment the row exists (§3.11.2 step 5).
        status="precomputing" if needs_precompute(source, backend) else "ready",
        audio_seconds=seconds,
        trim_start_ms=max(0, trim_start_ms),
        trim_end_ms=trim_end_ms,
        ref_text=ref_text or None,
        instruct=instruct or None,
        created_at=datetime.now(UTC),
        created_by=actor,
        consent_ack_at=datetime.now(UTC),
        retention_days=max(1, min(int(retention_days or 30), console.voice_retention_max_days)),
    )

    if audio is not None:
        trimmed = _trim(audio, row.trim_start_ms, row.trim_end_ms)
        relpath = f"{voice_id}/ref.wav"
        _write_private(Path(console.voice_data_dir) / relpath, trimmed)
        row.audio_relpath = relpath
        row.audio_bytes = len(trimmed)
        row.audio_seconds = validate_wav(trimmed)

    if needs_precompute(source, backend):
        row.status = "precomputing"
    return VoiceRepository(db).add(row)


def mark_precomputing(db, row: Voice) -> Voice:
    row.status = "precomputing"
    row.error_code = None
    return VoiceRepository(db).save(row)


def mark_ready(db, row: Voice, *, spk: str, rvq: str) -> Voice:
    row.status = "ready"
    row.spk_relpath = spk
    row.rvq_relpath = rvq
    row.error_code = None
    return VoiceRepository(db).save(row)


def mark_failed(db, row: Voice, code: str) -> Voice:
    row.status = "failed"
    row.error_code = code
    return VoiceRepository(db).save(row)


def used_by(db, voice_id: str) -> dict[str, Any]:
    refs = references(db, voice_id)
    return {"profiles": refs["profiles"], "versions": len(refs["versions"])}


def row_payload(db, row: Voice, *, detail: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "source": row.source,
        "backend": row.backend,
        "language": row.language or "",
        "status": row.status,
        "audioSeconds": row.audio_seconds,
        "createdAt": iso_utc(row.created_at),
        "createdBy": row.created_by,
        "refCount": len(references(db, row.id)["profiles"]),
        "usedBy": used_by(db, row.id),
    }
    if detail:
        from app.services import voice_precompute  # noqa: PLC0415 - progress sidecar only

        stage, progress = voice_precompute.progress(row)
        payload.update(
            {
                "trimStartMs": row.trim_start_ms,
                "trimEndMs": row.trim_end_ms,
                "refText": row.ref_text or "",
                "instruct": row.instruct or "",
                "consentAckAt": iso_utc(row.consent_ack_at),
                "retentionDays": row.retention_days,
                "precompute": {
                    "stage": stage,
                    "progress": progress,
                    "errorCode": row.error_code,
                },
            }
        )
    return payload


def list_payload(db, **filters) -> dict[str, Any]:
    rows, total = VoiceRepository(db).list(**filters)
    return {
        "list": [row_payload(db, row) for row in rows],
        "total": total,
        "page": filters.get("page", 1),
        "pageSize": filters.get("page_size", 20),
    }


def get_or_404(db, voice_id: str) -> Voice:
    row = VoiceRepository(db).get(voice_id)
    if row is None:
        raise ApiError("voice_not_found", f"no voice {voice_id!r}", 404)
    return row


def duplicate(db, voice_id: str, name: str) -> Voice:
    source = get_or_404(db, voice_id)
    clean = (name or f"{source.name} 2").strip()[:64]
    if VoiceRepository(db).by_name(clean) is not None:
        raise ApiError("voice_name_taken", f"a voice named {clean!r} already exists", 409)
    return VoiceRepository(db).add(
        Voice(
            id=ulid(),
            name=clean,
            source=source.source,
            backend=source.backend,
            language=source.language,
            status=source.status,
            audio_relpath=source.audio_relpath,
            audio_bytes=source.audio_bytes,
            audio_seconds=source.audio_seconds,
            trim_start_ms=source.trim_start_ms,
            trim_end_ms=source.trim_end_ms,
            ref_text=source.ref_text,
            instruct=source.instruct,
            spk_relpath=source.spk_relpath,
            rvq_relpath=source.rvq_relpath,
            created_at=datetime.now(UTC),
            created_by=source.created_by,
            consent_ack_at=datetime.now(UTC),
            retention_days=source.retention_days,
        )
    )


def remove(db, voice_id: str) -> dict[str, bool]:
    row = get_or_404(db, voice_id)
    refs = references(db, voice_id)
    if refs["profiles"] or refs["versions"]:
        raise ApiError(
            "voice_in_use",
            f"voice {row.name!r} is still referenced",
            409,
            detail=[
                {"field": "profiles", "value": refs["profiles"]},
                # A.18 spells the second entry as a count, not a list of numbers.
                {"field": "versions", "value": len(refs["versions"])},
            ],
        )
    directory = voice_dir(voice_id)
    VoiceRepository(db).remove(row)
    if directory.is_dir():
        for child in directory.iterdir():
            child.unlink(missing_ok=True)
        directory.rmdir()
    return {"deleted": True}


def backends() -> dict[str, Any]:
    """Which sources and fields each TTS backend actually has in the catalog."""
    loaded = catalog_service.load()
    present = {entry.backend for entry in loaded.entries if entry.stage == "tts" and entry.backend}
    rows = [
        {
            "backend": backend,
            "stage": "tts",
            "catalogued": True,
            "sources": [source for source in SOURCES if (source, backend) in BINDINGS],
            "fields": BACKEND_FIELDS[backend],
            "notes": "",
        }
        for backend in ("qwen3", "openai_compatible", "kokoro")
        if backend in present
    ]
    for stage, backend in B4_BACKENDS:
        if backend in present:
            continue
        rows.append(
            {
                "backend": backend,
                "stage": stage,
                "catalogued": False,
                "sources": [],
                "fields": {},
                "notes": "字段未进机器目录",
            }
        )
    return {"list": rows}


def reference_marker(voice_id: str) -> str:
    """Exposed for the audit trail: the only thing it records is this marker."""
    return _marker(voice_id)


def voice_ids_in(values: Iterable[Any]) -> list[str]:
    """Ids referenced by a patch, in field order, for `detail.voiceRefs`."""
    found: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        parts = Path(value).parts
        if "voices" in parts:
            index = parts.index("voices")
            if index + 1 < len(parts) and parts[index + 1] not in found:
                found.append(parts[index + 1])
    return found
