from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.services import asset_service

# Built assets carry a content hash in the filename, so they can be cached hard;
# index.html must not be cached or a browser keeps an old bundle across deploys
# (spec R16).
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_NO_STORE = {"Cache-Control": "no-store"}


class _ImmutableStaticFiles(StaticFiles):
    """StaticFiles with the one header a hashed bundle needs.

    Mounted sub-apps answer before the SPA fallback, so the header has to be
    attached here as well; otherwise `GET /assets/app-<hash>.js` reaches the
    browser without a Cache-Control at all (spec R16).
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.update(_IMMUTABLE)
        return response


def mount_spa(app: FastAPI, dist_dir: str | Path) -> None:
    """Serve the built SPA. Call this **after** every API router is registered.

    Starlette matches routes in registration order, so a catch-all registered
    first would answer /api/config with index.html.
    """
    dist = Path(dist_dir)
    if not dist.is_dir():
        # A missing dist is a broken image, not a runtime condition worth
        # pretending to survive: fail loudly at boot.
        raise RuntimeError(f"static dir {dist} is missing; the image was built without the frontend")

    for name in ("assets", "worklets"):
        directory = dist / name
        if directory.is_dir():
            app.mount(f"/{name}", _ImmutableStaticFiles(directory=directory), name=name)

    # Two pinned asset routes (A.13). They are registered before the catch-all so
    # that a missing file is a 503 the frontend can read, not a silent index.html.
    @app.get("/vendor/openai-realtime-agents.umd.js", include_in_schema=False)
    def agents_sdk() -> FileResponse:
        return FileResponse(
            asset_service.agents_sdk_path(), media_type="text/javascript", headers=_IMMUTABLE
        )

    @app.get("/vendor/local-vad/{filename}", include_in_schema=False)
    def local_vad(filename: str) -> FileResponse:
        path, media_type = asset_service.vad_path(filename)
        return FileResponse(path, media_type=media_type, headers=_IMMUTABLE)

    index = dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file() and dist.resolve() in candidate.resolve().parents:
            return FileResponse(candidate, headers=_IMMUTABLE)
        # A path that names a file but is not in dist is a *removed* asset (the
        # archived demo's /main.js, /style.css, …), never a client-side route.
        # Answering index.html here would turn a 404 into `200 text/html`, and
        # the browser then blames the script instead of the deletion. Real
        # assets never reach this branch: /assets, /worklets, /vendor and the
        # API prefixes are all registered before this catch-all.
        if Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, headers=_NO_STORE)
