from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.security import CurrentUser, require_user
from app.schemas.common import ok
from app.services import catalog_service

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/catalog")
def get_catalog(
    exposure: str | None = None,
    stage: str | None = None,
    backend: str | None = None,
    user: CurrentUser = Depends(require_user),
):
    """The parameter tree (A.1).

    `exposure=basic,advanced` is cumulative, so the highest level named is the
    level shown — asking for basic and advanced and getting expert back would
    defeat the point of the ladder.
    """
    loaded = catalog_service.load()
    if not loaded.available:
        raise ApiError("catalog_unavailable", loaded.hint or "catalog not mounted", 503)

    levels = [part.strip() for part in (exposure or "").split(",") if part.strip()]
    try:
        entries = loaded.filtered(exposure=levels[-1] if levels else None, stage=stage)
    except catalog_service.CatalogError as exc:
        raise ApiError("invalid_parameter", str(exc), 400) from exc
    if backend:
        entries = [entry for entry in entries if entry.backend in (None, backend)]

    counts: dict[str, int] = {}
    for entry in loaded.entries:
        counts[entry.exposure] = counts.get(entry.exposure, 0) + 1

    return ok(
        {
            "schema": loaded.schema,
            "generatedFrom": loaded.generated_from,
            "generatedAt": loaded.generated_at,
            "total": len(loaded.entries),
            "returned": len(entries),
            "exposureLevels": list(catalog_service.EXPOSURE_LEVELS),
            "exposureCounts": counts,
            "variantKeys": loaded.variant_keys,
            "parameters": [entry.as_json() for entry in entries],
        }
    )
