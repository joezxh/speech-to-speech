"""Contract tests for the Swagger UI documentation.

Every route the service mounts must be reachable in ``/docs`` with a purpose,
its parameters, its status codes and a runnable example.  These tests pin that
contract so a later refactor cannot quietly drop an endpoint from the docs.
"""
from __future__ import annotations

import threading

import pytest

from speech_to_speech.api.openai_realtime.openapi_meta import (
    API_TITLE,
    API_VERSION,
    WS_PATH,
)
from speech_to_speech.api.openai_realtime.websocket_router import create_app

#: Paths that only exist when the matching provider is enabled.
VOICEPRINT_PATHS = ("/v1/audio/embeddings", "/v1/audio/embeddings/capability")


@pytest.fixture(scope="module")
def schema() -> dict:
    """The schema with every optional provider mounted.

    ``SER_PROVIDER=local`` mounts the emotion routes and ``VOICEPRINT_ENABLED``
    mounts the voiceprint ones; without them those paths are absent by design
    and the documentation tests would be checking the wrong service.
    """
    patcher = pytest.MonkeyPatch()
    patcher.setenv("SER_PROVIDER", "local")
    patcher.setenv("VOICEPRINT_ENABLED", "true")
    try:
        app = create_app(pool=[], stop_event=threading.Event())
        return app.openapi()
    finally:
        patcher.undo()


def _operations(schema: dict) -> list[tuple[str, str, dict]]:
    return [
        (method, path, operation)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
    ]


def test_info_and_tags_are_set(schema):
    assert schema["info"]["title"] == API_TITLE
    assert schema["info"]["version"] == API_VERSION
    names = [tag["name"] for tag in schema.get("tags", [])]
    assert names == ["实时对话", "音频能力", "运维代理", "LLM 代理", "观测与运维"]


def test_websocket_route_is_injected(schema):
    operation = schema["paths"][WS_PATH]["get"]
    assert operation["x-websocket"] is True
    assert operation["tags"] == ["实时对话"]
    assert "101" in operation["responses"]


def test_every_operation_documents_purpose_parameters_and_example(schema):
    missing = []
    for method, path, operation in _operations(schema):
        description = operation.get("description") or ""
        gaps = []
        if not operation.get("summary"):
            gaps.append("summary")
        if not operation.get("tags"):
            gaps.append("tags")
        if not operation.get("responses"):
            gaps.append("responses")
        if len(description) < 80:
            gaps.append("description")
        if "curl" not in description.lower():
            gaps.append("curl")
        if gaps:
            missing.append((method, path, gaps))
    assert missing == []


def test_multipart_file_fields_are_binary(schema):
    """Swagger UI only draws a file picker for ``format: binary``."""
    for path in ("/v1/audio/transcriptions", "/recognize", "/v1/audio/visemes"):
        body = schema["paths"][path]["post"]["requestBody"]["content"]["multipart/form-data"]
        ref = body["schema"].get("$ref")
        resolved = schema["components"]["schemas"][ref.split("/")[-1]] if ref else body["schema"]
        assert resolved["properties"]["file"]["format"] == "binary"


def test_voiceprint_documents_both_auth_failures(schema):
    for path in VOICEPRINT_PATHS:
        operation = schema["paths"][path]["post" if path.endswith("embeddings") else "get"]
        assert "401" in operation["responses"]
        assert "403" in operation["responses"]


def test_webrtc_call_documents_created_status(schema):
    responses = schema["paths"]["/v1/realtime/calls"]["post"]["responses"]
    assert "201" in responses
    assert "200" not in responses
