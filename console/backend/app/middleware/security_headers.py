from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# worker-src blob: is required by the local VAD (it spawns a blob worker) and
# media-src blob: by the playback queue. Narrow either and the voice page dies
# in a way that only shows up in the browser console.
_CSP = (
    "default-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "worker-src 'self' blob:; "
    "script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        max_body_bytes: int = 2 * 1024 * 1024,
        upload_body_bytes: int | None = None,
        upload_paths: tuple[str, ...] = ("/api/v1/voices",),
    ) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes
        # A voice upload is capped at VOICE_MAX_BYTES (10 MiB) by its own
        # endpoint, which answers `413 voice_too_large`. The 2 MiB guard here
        # would refuse it first with the wrong code (design §3.11.2 vs §2.5).
        self.upload_body_bytes = upload_body_bytes or max_body_bytes
        self.upload_paths = upload_paths

    async def dispatch(self, request: Request, call_next):
        declared = request.headers.get("content-length")
        limit = (
            self.upload_body_bytes
            if request.method == "POST" and request.url.path in self.upload_paths
            else self.max_body_bytes
        )
        if declared and declared.isdigit() and int(declared) > limit:
            return JSONResponse({"code": "invalid_parameter", "message": "request body too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = _CSP
        return response
