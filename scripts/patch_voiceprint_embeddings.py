"""构建期注入声纹嵌入端点（POST /v1/audio/embeddings、GET .../capability）。

与 scripts/patch_pipeline_rest.py 同机制：把路由注入到
  src/speech_to_speech/api/openai_realtime/websocket_router.py 的 create_app() 内，
  **构建期固化** → 容器重建后端点仍在（满足 G0-b），无需运行时 docker exec 打补丁。

设计依据：docs/voiceprint-embedding-service-design-CN.md §4 / §5 / §6。

配置来源：环境变量（create_app 拿不到 ModuleArguments）：
  VOICEPRINT_ENABLED / VOICEPRINT_API_KEY / VOICEPRINT_MODEL /
  VOICEPRINT_MAX_AUDIO_MS / VOICEPRINT_MAX_BYTES / VOICEPRINT_MIN_SPEECH_MS /
  VOICEPRINT_STRICT_REJECT / VOICEPRINT_QUEUE_CAPACITY /
  VOICEPRINT_MAX_CONCURRENCY / VOICEPRINT_INFER_TIMEOUT_MS / VOICEPRINT_DEVICE

幂等：已打过补丁则直接跳过（可反复构建）。
"""

import sys

TARGET = "/usr/src/app/src/speech_to_speech/api/openai_realtime/websocket_router.py"
MARKER = "    app = FastAPI(lifespan=lifespan)\n"

NEW_BLOCK = '''
    # ── Voiceprint embedding endpoints (injected by patch_voiceprint_embeddings.py) ──
    import os as _vp_os

    from fastapi import Form as _vp_form
    from fastapi import Request as _vp_request
    from fastapi import UploadFile as _vp_upload

    from speech_to_speech.voiceprint.errors import VoiceprintErrorCode as _vp_code
    from speech_to_speech.voiceprint.errors import error_body as _vp_error_body
    from speech_to_speech.voiceprint.errors import http_status as _vp_http_status
    from speech_to_speech.voiceprint.service import VoiceprintRequestError as _vp_req_error
    from speech_to_speech.voiceprint.service import VoiceprintService as _vp_service

    def _vp_flag(name: str, default: str = "") -> bool:
        return _vp_os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")

    _vp_enabled = _vp_flag("VOICEPRINT_ENABLED", "false")

    if _vp_enabled:
        _vp_svc = _vp_service(
            api_key=_vp_os.environ.get("VOICEPRINT_API_KEY"),
            model_name=_vp_os.environ.get("VOICEPRINT_MODEL") or None,
            max_audio_ms=int(_vp_os.environ.get("VOICEPRINT_MAX_AUDIO_MS", "30000")),
            max_bytes=int(_vp_os.environ.get("VOICEPRINT_MAX_BYTES", "10485760")),
            min_speech_ms=int(_vp_os.environ.get("VOICEPRINT_MIN_SPEECH_MS", "800")),
            strict_reject=_vp_flag("VOICEPRINT_STRICT_REJECT", "false"),
            queue_capacity=int(_vp_os.environ.get("VOICEPRINT_QUEUE_CAPACITY", "16")),
            max_concurrency=int(_vp_os.environ.get("VOICEPRINT_MAX_CONCURRENCY", "4")),
            infer_timeout_ms=int(_vp_os.environ.get("VOICEPRINT_INFER_TIMEOUT_MS", "3000")),
            device=_vp_os.environ.get("VOICEPRINT_DEVICE") or None,
        )
        _vp_svc.attach_pool(pool, _vp_os.environ.get("VOICEPRINT_ENCODER_DIR") or None)

        @app.post("/v1/audio/embeddings")
        async def _vp_embeddings(
            request: _vp_request,
            file: _vp_upload | None = None,
            model: str = _vp_form(""),
            purpose: str = _vp_form(""),
        ):
            try:
                _vp_svc.authorize(request.headers.get("authorization"))
            except _vp_req_error as _exc:
                from fastapi.responses import JSONResponse as _vp_json

                return _vp_json(status_code=_exc.status_code, content=_exc.body)
            if file is None:
                _data = b""
            else:
                _data = await file.read()
            try:
                _result = _vp_svc.embed(_data, model=model or None, purpose=purpose or None)
            except _vp_req_error as _exc:
                from fastapi.responses import JSONResponse as _vp_json

                return _vp_json(status_code=_exc.status_code, content=_exc.body)
            except Exception:  # noqa: BLE001
                from fastapi.responses import JSONResponse as _vp_json

                return _vp_json(
                    status_code=_vp_http_status(_vp_code.INTERNAL_ERROR),
                    content=_vp_error_body(_vp_code.INTERNAL_ERROR),
                )
            return _result

        @app.get("/v1/audio/embeddings/capability")
        async def _vp_capability(request: _vp_request):
            try:
                _vp_svc.authorize(request.headers.get("authorization"))
            except _vp_req_error as _exc:
                from fastapi.responses import JSONResponse as _vp_json

                return _vp_json(status_code=_exc.status_code, content=_exc.body)
            return _vp_svc.capability()
'''


def main() -> None:
    with open(TARGET, encoding="utf-8") as f:
        content = f.read()
    if "_vp_embeddings" in content:
        print("PATCH ALREADY APPLIED")
        return
    if MARKER not in content:
        print("MARKER NOT FOUND")
        sys.exit(1)
    content = content.replace(MARKER, MARKER + NEW_BLOCK, 1)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)
    print("PATCH APPLIED")


if __name__ == "__main__":
    main()
