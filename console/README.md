# console

The operations console and the conversation page. Both are built into the same
image as the pipeline; see [`../docs/deployment.md`](../docs/deployment.md) for
the deployment and rollback procedure.

Inside the container supervisord runs two processes (§13.4 of the design):

| program | command | listens on |
|---|---|---|
| `console` | `uvicorn app.main:app` | `0.0.0.0:8000` — the only published port |
| `pipeline` | `speech-to-speech serve -f /app/config/prod.yaml` | `127.0.0.1:8765` — loopback only |

The console proxies the pipeline's realtime endpoint at `/v1/realtime`, and
`8765` is never published. The built SPA is served by FastAPI itself: the
conversation page at `/`, the console pages at `/console`, and a path that names
a file but is not in `dist/` is a `404` rather than `index.html`.

## Layout

```
backend/            FastAPI app (PYTHONPATH=/app/console)
  app/api/          routers: config, sessions, params, versions, audit, … /api/*
  app/services/     renderer, validator, publisher, restart, pool, log, voice
  app/repositories/ sqlite access (sqlalchemy 2.x, alembic migrations)
  app/config/       pydantic-settings groups: auth, console, database
  app/core/         app factory, spa mounting, logging, security helpers
  scripts/          seed_admin.py — the only script (there is no self-service signup)
  alembic/          migration environment; `alembic upgrade head` runs it
  tests/            unit/ and integration/ (httpx TestClient)
frontend/           Vue 3 + TS + Pinia + ant-design-vue, built by Vite
  src/views/        ParamsView, VersionsView, AuditView, SessionsView, VoicesView…
  src/features/     the conversation page (orb, transcript, tools, settings)
  src/components/   log panel, turn-latency panel, voice picker, shared tables
  src/stores/       pinia: auth, params, logs, voice, instances
  scripts/          copy-vendors.mjs (the /vendor/* assets) and check-contract.mjs
deploy/             supervisord.conf and the image entrypoint
design/             console-preview.html — the visual reference the views follow
```

## Environment

Read by `app/config/*` through pydantic-settings (`env_file=".env"`, case
insensitive). In the container they come from `config/prod.env`.

| variable | default | notes |
|---|---|---|
| `JWT_SECRET_KEY` | — | **required**; the console refuses to start without it. At least 32 bytes from a CSPRNG. Rotating it signs everyone out. |
| `DATABASE_URL` | `sqlite:////app/data/console.sqlite3` | the `data/` volume; **the image does not migrate on boot** — run `alembic upgrade head` once per new database |
| `RESTART_MODE` | `supervisor` | `noop` disables restarts (tests, CI) |
| `PARAM_CONFIG_DIR` | `/app/config` | the only directory the console writes to |
| `PARAM_CATALOG_PATH` | `/app/catalog/parameter-catalog.yaml` | mounted read-only from `docs/parameter-catalog.yaml` |
| `STATIC_DIR` | `/app/console/static` | the built SPA; a missing directory fails at boot |
| `PIPELINE_BASE_URL` | `http://127.0.0.1:8765` | loopback inside the container |
| `SUPERVISOR_SOCKET` | `/run/s2s-console/supervisor.sock` | process status and restarts |
| `LOG_DIR` | `/var/log/supervisor` | read-only source for the log panel |
| `DATA_DIR` | `/app/data` | turn-latency cursor, voice library |

## Working on it

Backend, from `console/backend` (this is what CI runs):

```bash
python -m pip install -e ../.. --no-deps
python -m pip install -r requirements-dev.txt
python -m pytest tests/unit -q
python -m pytest tests/integration -q
```

To run the API against a local source tree, build the SPA first — the app
refuses to boot without `STATIC_DIR`:

```bash
cd ../frontend && npm ci && npm run build && cd ../backend
cp .env.example .env        # then edit STATIC_DIR; the other dev defaults are fine
alembic upgrade head        # sqlite:///./dev.db, per .env
JWT_SECRET_KEY=local-dev-secret-at-least-32-bytes \
DATABASE_URL=sqlite:///./dev.db RESTART_MODE=noop STATIC_DIR=../frontend/dist \
PYTHONPATH=. uvicorn app.main:app --port 8000
```

`seed_admin.py` creates the first operator, and it needs the same environment:

```bash
PYTHONPATH=. python scripts/seed_admin.py --username admin --role admin --password-stdin
```

Frontend, from `console/frontend`:

```bash
npm ci
npm run dev        # Vite dev server on :3000, proxying /api, /vendor and /v1 to :8000
npm run test       # vitest
npm run lint       # eslint, --max-warnings 0
npm run build      # copy-vendors → vue-tsc --noEmit → vite build
```

`npm run build` is the only supported way to produce `dist/`: it also copies the
pinned `/vendor/*` assets (the Agents SDK bundle and the local VAD worklets) that
the conversation page needs at runtime.
