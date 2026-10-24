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
    def __init__(self, app, max_body_bytes: int = 2 * 1024 * 1024) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_body_bytes:
            return JSONResponse({"code": "invalid_parameter", "message": "request body too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = _CSP
        return response
