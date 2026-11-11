"""A console app mounted at "/" must not disturb any s2s route (spec §4.4)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.routing import Mount, WebSocketRoute

from speech_to_speech.api.openai_realtime.websocket_router import create_app
from speech_to_speech.console_integration import ConsoleAttachment


def _is_root_mount(route) -> bool:
    # Starlette normalises Mount("/") to path "" (Mount.__init__ does path.rstrip("/")),
    # so both spellings have to count as the root mount.
    return isinstance(route, Mount) and route.path in {"", "/"}


class _ImmutableStaticFiles(StaticFiles):
    """Mirror the real console: hashed assets carry the immutable header."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["cache-control"] = "public, max-age=31536000, immutable"
        return response


@pytest.fixture
def console(tmp_path):
    """A miniature console: one API route, one immutable asset, an SPA fallback."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "x.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "index.html").write_text("<title>console</title>", encoding="utf-8")
    started = Event()

    @asynccontextmanager
    async def lifespan(_app):
        started.set()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/api/echo")
    async def echo() -> dict[str, str]:
        return {"served_by": "console"}

    app.mount("/assets", _ImmutableStaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"})
        if Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})

    return (
        ConsoleAttachment(
            app=app,
            lifespan=lifespan,
            home=tmp_path,
            static_dir=dist,
            pipeline_base_url="http://127.0.0.1:8765",
        ),
        started,
    )


@pytest.fixture
def client(console):
    attachment, _started = console
    return TestClient(create_app(pool=[], stop_event=Event(), console_attachment=attachment))


def test_console_api_answers(client):
    response = client.get("/api/echo")

    assert response.status_code == 200
    assert response.json() == {"served_by": "console"}


def test_s2s_routes_still_win(client):
    response = client.get("/v1/pool")

    assert response.status_code == 200
    assert response.json()["size"] == 0


def test_realtime_websocket_route_is_registered_before_the_mount(console):
    attachment, _started = console
    app = create_app(pool=[], stop_event=Event(), console_attachment=attachment)
    websocket_index = next(
        index
        for index, route in enumerate(app.routes)
        if isinstance(route, WebSocketRoute) and route.path == "/v1/realtime"
    )
    mount_index = next(index for index, route in enumerate(app.routes) if _is_root_mount(route))

    assert websocket_index < mount_index


def test_root_serves_the_console_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "console" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_frontend_routes_fall_back_to_index(client):
    assert client.get("/console/params").status_code == 200


def test_missing_assets_are_404_not_index(client):
    assert client.get("/main.js").status_code == 404


def test_hashed_assets_are_immutable(client):
    response = client.get("/assets/x.js")

    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_console_lifespan_runs_inside_the_parent_lifespan(console):
    attachment, started = console
    with TestClient(create_app(pool=[], stop_event=Event(), console_attachment=attachment)):
        assert started.is_set()


def test_switch_off_keeps_the_routing_table_untouched():
    app = create_app(pool=[], stop_event=Event())

    assert not any(_is_root_mount(route) for route in app.routes)
    assert TestClient(app).get("/").status_code == 404
