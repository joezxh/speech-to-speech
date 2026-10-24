from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from app.config import console as console_settings
from app.core.errors import ApiError
from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.repositories.voice_repository import VoiceRepository
from app.schemas.common import ok
from app.schemas.voices import VoiceDuplicateRequest
from app.services import voice_precompute, voice_service

router = APIRouter(prefix="/api/v1", tags=["voices"])


async def _precompute(voice_id: str) -> None:
    """Runs after the response: the upload must not wait 60 s for a child.

    Its own session, because the request's session is closed by then.
    """
    from app.db.database import SessionLocal  # noqa: PLC0415 - avoid import cycle

    with SessionLocal() as session:
        row = VoiceRepository(session).get(voice_id)
        if row is None or row.status == "ready":
            return
        ok_run, code = await voice_precompute.run(
            voice_id, voice_service.audio_path(row), voice_service.voice_dir(voice_id)
        )
        if ok_run:
            voice_service.mark_ready(
                session, row, spk=f"{voice_id}/spk.npy", rvq=f"{voice_id}/rvq.npy"
            )
        else:
            voice_service.mark_failed(session, row, code or "model_not_found")


@router.get("/voices/backends")
def list_backends(user: CurrentUser = Depends(require_user)):
    """Declared before `/voices/{voice_id}` so `backends` is never read as an id."""
    return ok(voice_service.backends())


@router.get("/voices")
def list_voices(
    db: DbSession,
    backend: str = "",
    source: str = "",
    status: str = "",
    q: str = "",
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
):
    return ok(
        voice_service.list_payload(
            db, backend=backend, source=source, status=status, q=q, page=page, page_size=pageSize
        )
    )


@router.post("/voices", status_code=201)
async def create_voice(
    background: BackgroundTasks,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
    name: str = Form(...),
    source: str = Form(...),
    backend: str = Form(...),
    language: str = Form(""),
    refText: str = Form(""),
    instruct: str = Form(""),
    consent: str = Form(""),
    retentionDays: int = Form(30),
    trimStartMs: int = Form(0),
    trimEndMs: int | None = Form(None),
    audio: UploadFile | None = File(None),
):
    """A.18 upload. The checks run in the documented order: consent first, then
    size, then the WAV header, then the name — early failures are cheaper."""
    if consent != "biometric-ack":
        raise ApiError(
            "voice_consent_required",
            "uploading a voice requires an explicit biometric acknowledgement",
            400,
        )
    payload = await audio.read() if audio is not None else None
    if payload is not None and len(payload) > console_settings.voice_max_bytes:
        raise ApiError(
            "voice_too_large",
            f"the audio is larger than {console_settings.voice_max_bytes} bytes",
            413,
        )
    row = voice_service.create(
        db,
        name=name,
        source=source,
        backend=backend,
        language=language,
        ref_text=refText,
        instruct=instruct,
        audio=payload,
        trim_start_ms=trimStartMs,
        trim_end_ms=trimEndMs,
        retention_days=retentionDays,
        actor=user.username,
    )
    if row.status == "precomputing":
        background.add_task(_precompute, row.id)
    return JSONResponse(
        status_code=201,
        content=ok({"id": row.id, "status": row.status, "jobId": f"voice-{row.id}"}),
    )


@router.get("/voices/{voice_id}")
def get_voice(voice_id: str, db: DbSession, user: CurrentUser = Depends(require_user)):
    row = voice_service.get_or_404(db, voice_id)
    return ok(voice_service.row_payload(db, row, detail=True))


@router.get("/voices/{voice_id}/audio")
def get_voice_audio(
    voice_id: str,
    request: Request,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    """Audition is a static read: no `/internal/*`, no pipeline, `no-store`."""
    row = voice_service.get_or_404(db, voice_id)
    path = voice_service.audio_path(row)
    if not path.is_file():
        raise ApiError("voice_expired", "the audio was removed by its retention policy", 410)
    data = path.read_bytes()
    headers = {
        "Cache-Control": "no-store",
        "Content-Disposition": "inline",
        "Accept-Ranges": "bytes",
    }
    raw = request.headers.get("range", "")
    if raw.startswith("bytes="):
        start, _, end = raw[6:].partition("-")
        try:
            first = int(start) if start else 0
            last = int(end) if end else len(data) - 1
        except ValueError as exc:
            raise ApiError("invalid_parameter", "unreadable Range header", 400) from exc
        first = max(0, min(first, len(data) - 1))
        last = max(first, min(last, len(data) - 1))
        chunk = data[first : last + 1]
        headers["Content-Range"] = f"bytes {first}-{last}/{len(data)}"
        return Response(content=chunk, media_type="audio/wav", status_code=206, headers=headers)
    return Response(content=data, media_type="audio/wav", headers=headers)


@router.post("/voices/{voice_id}/duplicate")
def duplicate_voice(
    voice_id: str,
    payload: VoiceDuplicateRequest,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    row = voice_service.duplicate(db, voice_id, payload.name or "")
    return ok({"id": row.id, "name": row.name, "status": row.status})


@router.delete("/voices/{voice_id}")
def delete_voice(voice_id: str, db: DbSession, user: CurrentUser = Depends(require_user)):
    if user.role != "admin":
        raise ApiError("forbidden", "only an admin may delete a voice", 403)
    return ok(voice_service.remove(db, voice_id))
