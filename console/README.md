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
  scripts/          seed_admin.py (first operator) and dump_schema_sql.py (init SQL)
  alembic/          migration environment; `alembic upgrade head` runs it
    sql/            init-sqlite.sql / init-postgresql.sql — generated, do not edit
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

## Running inside the pipeline process

`speech-to-speech serve --with-console` hosts this backend and the built frontend on
the pipeline's own port (default `:8765`), so `/`, `/console/*`, `/api/*` and `/v1/*`
share one origin and one process. That mode reads `console/backend/.env` for its
settings and overrides two of them: `PIPELINE_BASE_URL` points at the process itself,
`STATIC_DIR` at the built `dist`. The uvicorn on `:8000` described below is the
standalone deployment and stays unchanged; you do not need it when the switch is on.

Two console routes are dead in that mode: `/v1/realtime` and `/v1/realtime/calls` are
the standalone proxies to a remote pipeline, and the pipeline's own `/v1/*` routes
answer first.

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
| `PIPELINE_CONTAINER` | `speech-to-speech-local-pipeline-1` | label only: the container behind `PIPELINE_BASE_URL`, shown in the voice page's Settings |
| `SUPERVISOR_SOCKET` | `/run/s2s-console/supervisor.sock` | process status and restarts |
| `LOG_DIR` | `/var/log/supervisor` | read-only source for the log panel |
| `DATA_DIR` | `/app/data` | turn-latency cursor, voice library |

## Pointing the console at a local pipeline-1

On a dev box the pipeline runs as its own container
(`docker-compose.local.yml`, compose project `speech-to-speech-local`, service
`pipeline` → container `speech-to-speech-local-pipeline-1`, published on
`0.0.0.0:8765`). Three consumers read the same two settings, so there is exactly
one place to change:

| path | consumer | uses |
|---|---|---|
| `GET /v1/pool` | `services/pool.py` → `/api/v1/status`, `/api/v1/instances` | `PIPELINE_BASE_URL` |
| `POST /internal/sessions/update` | `services/hot_update_service.py` (parameter publish) | `PIPELINE_BASE_URL` |
| `WS /v1/realtime`, `POST /v1/realtime/calls` | `routers/realtime.py` (the browser's voice link) | `PIPELINE_BASE_URL` |

`.env` for that setup:

```dotenv
PIPELINE_BASE_URL=http://127.0.0.1:8765
PIPELINE_CONTAINER=speech-to-speech-local-pipeline-1
# SPEECH_TO_SPEECH_URL stays empty: the browser dials same-origin /v1/realtime
# and this process proxies it. Filling it pins the upstream and disables the LB
# face, queueing and sign-in.
```

The browser never learns `8765`: `npm run dev` proxies `/v1` (with `ws: true`) to
the console on `:8000`, which forwards the socket to the pipeline. Same-origin
means no second CORS surface, and `8765` stays unpublished in the container
deployment.

### Verifying the wire, in order

```bash
# 1. the pipeline itself answers
curl -s http://127.0.0.1:8765/v1/pool          # {"size":1,"in_use":0,"units":[…]}
docker ps --filter name=pipeline --format '{{.Names}} {{.Status}} {{.Ports}}'

# 2. the console advertises the same endpoint (no token needed)
curl -s http://127.0.0.1:8000/api/config       # …"pipeline":{"baseUrl":"http://127.0.0.1:8765",…}

# 3. the status probe reaches it (JWT required)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/status
                                               # "pipeline": "ok"

# 4. the voice link upgrades and the pipeline greets the socket
python - <<'PY'
import asyncio, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8000/v1/realtime", max_size=None) as ws:
        print((await ws.recv())[:120])          # session.created
asyncio.run(main())
PY
```

On a dev box there is no supervisord, so the process probe answers `unknown`;
`/api/v1/status` then trusts `/v1/pool` for its single word — answering means
serving. Inside the container the probe still wins: a stopped program reports
`unreachable` even if a stale socket answers.

## Provisioning a database

`alembic/sql/` holds the whole schema as plain SQL, one file per dialect:

| file | run it with | floor |
|---|---|---|
| `init-sqlite.sql` | `sqlite3 /app/data/console.sqlite3 < init-sqlite.sql` | SQLite 3.35+ (the version stamp is an `INSERT … RETURNING`) |
| `init-postgresql.sql` | `psql -v ON_ERROR_STOP=1 -f init-postgresql.sql` | PostgreSQL 12+ |

Both files create the six tables (`param_user`, `param_draft`,
`param_version`, `param_audit`, `voices`, `turn_latency`), the two indexes, and
the `alembic_version` row set to the current head — so a database provisioned
from either file is **already migrated** and the next `alembic upgrade head` is
a no-op. That matters because the image does not migrate on boot.

They are generated, not written by hand, by `alembic upgrade head --sql` for
each dialect. After adding a migration, regenerate and commit both:

```bash
cd console/backend
python scripts/dump_schema_sql.py
```

`tests/unit/test_schema_sql.py` fails if either file stops covering a model
column or stamps the wrong revision, so the regeneration cannot be forgotten
silently. For an existing database use `alembic upgrade head` instead of these
files — they assume an empty database.

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
