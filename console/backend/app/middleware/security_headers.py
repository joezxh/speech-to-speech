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

# The API reference page is not the console bundle: FastAPI's Swagger UI pulls
# its JS/CSS from a CDN and boots with an inline <script>, so the strict
# 'self'-only policy above would render /docs as a blank page. This policy is
# applied to the docs routes only — every other page keeps the strict one.
_DOCS_CSP = (
    "default-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' data: https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://cdn.jsdelivr.net"
)

#: Paths served with the docs policy instead of the strict one.
DOCS_PATHS = ("/docs", "/redoc")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        max_body_bytes: int = 2 * 1024 * 1024,
        upload_body_bytes: int | None = None,
        upload_paths: tuple[str, ...] = ("/api/v1/voices",),
        exempt_paths: tuple[str, ...] = (),
        docs_paths: tuple[str, ...] = DOCS_PATHS,
    ) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes
        # A voice upload is capped at VOICE_MAX_BYTES (10 MiB) by its own
        # endpoint, which answers `413 voice_too_large`. The 2 MiB guard here
        # would refuse it first with the wrong code (design §3.11.2 vs §2.5).
        self.upload_body_bytes = upload_body_bytes or max_body_bytes
        self.upload_paths = upload_paths
        # Paths whose size limit is enforced by the handler itself. The proxy
        # face answers 413 in the pipeline error shape, and two different 413
        # shapes for the same limit is worse than one (spec §5.4).
        self.exempt_paths = exempt_paths
        self.docs_paths = docs_paths

    async def dispatch(self, request: Request, call_next):
        declared = request.headers.get("content-length")
        if request.url.path in self.exempt_paths:
            limit = None
        else:
            limit = (
                self.upload_body_bytes
                if request.method == "POST" and request.url.path in self.upload_paths
                else self.max_body_bytes
            )
        if limit is not None and declared and declared.isdigit() and int(declared) > limit:
            return JSONResponse({"code": "invalid_parameter", "message": "request body too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.headers.get("content-type", "").startswith("text/html"):
            policy = _DOCS_CSP if request.url.path in self.docs_paths else _CSP
            response.headers["Content-Security-Policy"] = policy
        return response
