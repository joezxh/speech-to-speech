# AgentConsole 双形态镜像 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build three Docker images and two compose files so the s2s pipeline can run either as a single all-in-one process (`--with-agent --with-console`) or as separate `s2s+agent` / `console` containers, deployed locally.

**Architecture:** Three focused Dockerfiles from scratch: `Dockerfile.allinone` (cu130 base + node frontend stage + console deps + s2s, no supervisord), `Dockerfile.agent` (cu130 base + s2s only), `Dockerfile.console` (python:3.12-slim + console backend + built frontend). Two compose files wire them; `.env.agentconsole` overrides Windows paths with container paths. DB migration runs explicitly (`alembic upgrade head`). Agent registration is validated end-to-end via console management API.

**Tech Stack:** Docker / Docker Compose, cu130 CUDA base, Python 3.12, FastAPI, SQLAlchemy/Alembic, Node 20 (build stage only), named volumes, uv.

**Spec:** `docs/superpowers/specs/2026-11-19-agentconsole-docker-images-design.md`

## Global Constraints

- s2s images **must** use base `ccr.ccs.tencentyun.com/llm-basic/python-torch:cu130` (host driver 617.42 requires CUDA 13).
- allinone's `UV_INDEX` **must** use the cu130 PyTorch channel (copy `Dockerfile.cu130:32` exactly); never leave cu128 index.
- `console/backend/.env` **must never** be baked into any image — add to `.dockerignore` and `RUN rm -f` as belt-and-braces.
- DB schema **must** be migrated with `alembic upgrade head` before console serves requests; `/api/v1/health` does not prove this.
- Model weights **must** come from named volume `s2s-model-cache`, populated once from `./cache`; never rely on image-baked weights.
- Naming: `s2s-allinone:local`, `s2s-agent:local`, `s2s-console:local`.
- Ports: allinone maps `8765:8765` + `8000:8765`; split maps `s2s-pipeline:8765:8765`, `s2s-console:8000:8000`.
- `.env.agentconsole` must be gitignored (contains `S2S_ADMIN_TOKEN`, JWT secret, register code).
- All new files go in repo root `d:\work\qwen-audio-agent\speech-to-speech-src`.

## Review Focus

- **`.env` leaking into image**: verify `docker run --rm s2s-console:local cat /app/.env` fails; wrong guess → dev PostgreSQL/Windows paths silently break console in container.
- **Empty SQLite DB**: verify `alembic upgrade head` actually ran (query `param_user` table exists); wrong guess → health 200 but login 500.
- **cu128/cu130 mix**: verify `pip show torch` inside built s2s image shows cu130 and container starts without "driver too old"; wrong guess → TTS/STT silently fall back to CPU.
- **Empty model volume**: verify `/root/.cache/sensevoice-small` exists in container; wrong guess → pipeline crashes on model load.
- **Agent register code missing**: verify `POST /v1/agent/register` succeeds after injecting code and `GET /v1/agent/status` shows `registered=true`; wrong guess → capability green but agent never heartbeats.

---

### Task 1: Dockerfile.allinone (一体镜像)

**Files:**
- Create: `Dockerfile.allinone`
- Modify: `.dockerignore`

**Interfaces:**
- Produces: image `s2s-allinone:local`, with `/app/console` (backend src), `/app/console/static` (built SPA), `/usr/src/app/src/...` (s2s src with agent), `speech-to-speech` on PATH, `alembic` available in `/usr/src/app/.venv`.

- [ ] **Step 1: Add `console/backend/.env` to `.dockerignore`**

Append a line to `.dockerignore`:
```
console/backend/.env
```
Verify: `Select-String -Path .dockerignore -Pattern "console/backend/.env"` shows the line.

- [ ] **Step 2: Write `Dockerfile.allinone`**

Copy `Dockerfile` in full, with these exact changes (use `Dockerfile.cu130` as reference for cu130-specific lines):
- `ARG BASE_IMAGE=ccr.ccs.tencentyun.com/llm-basic/python-torch:cu130`
- Replace `ENV UV_INDEX="...cu128..."` with `ENV UV_INDEX="https://download.pytorch.org/whl/cu130 https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.aliyun.com/pypi/simple"` (verbatim from `Dockerfile.cu130:32`)
- Replace the comment block about cu12 constraints with the cu130 version (copy `Dockerfile.cu130:30-31,68-72`)
- In the apt install step add `sox` to the package list
- After `COPY console/backend /app/console`, add `RUN rm -f /app/console/.env` (belt-and-braces)
- Add `COPY cache/nltk_data /root/nltk_data` then `RUN chmod -R 755 /root/nltk_data && chown -R root:root /root/nltk_data`
- Delete the `COPY console/deploy/supervisord.conf`, `COPY console/deploy/entrypoint.sh`, `RUN chmod 0755 ...`, and `ENTRYPOINT` lines
- Replace with `ENTRYPOINT ["speech-to-speech"]`

Verify: `docker build -f Dockerfile.allinone -t s2s-allinone:local .` succeeds. Expected build 15-30 min; if it fails at uv resolution, compare `UV_INDEX` with `Dockerfile.cu130:32` byte-for-byte.

- [ ] **Step 3: Verify image contents**

Run:
```
docker run --rm --entrypoint sh s2s-allinone:local -c "ls /app/console/app/main.py /app/console/static/index.html /usr/src/app/src/speech_to_speech/agent/embedded.py && test ! -f /app/console/.env && echo OK"
```
Expected: `OK` on last line, no errors.

- [ ] **Step 4: Commit**

```bash
git add .dockerignore Dockerfile.allinone
git commit -m "build: add all-in-one agentconsole image (cu130)"
```

---

### Task 2: Dockerfile.agent (分离 s2s 镜像)

**Files:**
- Create: `Dockerfile.agent`

**Interfaces:**
- Produces: image `s2s-agent:local` with s2s source + agent modules, no console, `speech-to-speech` on PATH.

- [ ] **Step 1: Write `Dockerfile.agent`**

Copy `Dockerfile.cu130` in full, with these changes:
- Add `COPY cache/nltk_data /root/nltk_data` + `RUN chmod -R 755 /root/nltk_data && chown -R root:root /root/nltk_data` after `COPY src ./src`
- Add `sox` to an apt install step (if none exists, insert `RUN apt-get update && apt-get install -y --no-install-recommends sox && rm -rf /var/lib/apt/lists/*` before the workdir step)
- Delete the nltk online download step (lines 90-93 of `Dockerfile.cu130`) — offline resources are baked in
- Replace the final `ENTRYPOINT` (if present) with `ENTRYPOINT ["speech-to-speech"]`

Verify: `docker build -f Dockerfile.agent -t s2s-agent:local .` succeeds.

- [ ] **Step 2: Verify image contents**

Run:
```
docker run --rm --entrypoint sh s2s-agent:local -c "ls /usr/src/app/src/speech_to_speech/agent/embedded.py && test ! -e /app/console && python3 -c 'import torch; assert \"cu130\" in torch.__version__' && echo OK"
```
Expected: `OK`; if torch version assertion fails, rebuild — the cu130 index was not applied.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.agent
git commit -m "build: add s2s+agent image (cu130, no console)"
```

---

### Task 3: Dockerfile.console (轻量 console 镜像)

**Files:**
- Create: `Dockerfile.console`

**Interfaces:**
- Produces: image `s2s-console:local` with `/app/app/main.py`, `/app/static/index.html`, alembic usable from `/app`, no GPU deps.

- [ ] **Step 1: Write `Dockerfile.console`**

```dockerfile
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY console/frontend/package.json console/frontend/package-lock.json ./
RUN npm ci
COPY console/frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY console/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY console/backend /app
RUN rm -f /app/.env && mkdir -p /app/data /app/catalog
COPY --from=frontend-build /build/dist /app/static
COPY docs/parameter-catalog.yaml /app/catalog/parameter-catalog.yaml
ENV PYTHONPATH=/app \
    STATIC_DIR=/app/static \
    DATABASE_URL=sqlite:////app/data/console.sqlite3 \
    PARAM_CONFIG_DIR=/app/config \
    PARAM_CATALOG_PATH=/app/catalog/parameter-catalog.yaml \
    LOG_DIR=/app/data/logs \
    DATA_DIR=/app/data \
    VOICE_DATA_DIR=/app/data/voices \
    SESSION_DATA_DIR=/app/data/sessions \
    PIPELINE_BASE_URL=http://s2s-pipeline:8765 \
    CONSOLE_AUTOSTART=false \
    RESTART_MODE=noop
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
```

Note: `requirements.txt` contains `supervisor==4.2.5` and `psycopg2-binary==2.9.13`; keep them (harmless, and psycopg2 may be needed if DATABASE_URL is later switched to Postgres). If pip fails on psycopg2 in slim, switch base to `python:3.12` (not slim) — this is the only allowed fallback.

Verify: `docker build -f Dockerfile.console -t s2s-console:local .` succeeds.

- [ ] **Step 2: Verify image contents**

Run:
```
docker run --rm --entrypoint sh s2s-console:local -c "ls /app/app/main.py /app/static/index.html /app/alembic.ini && test ! -f /app/.env && echo OK"
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.console
git commit -m "build: add lightweight console image"
```

---

### Task 4: .env.agentconsole + compose files

**Files:**
- Create: `.env.agentconsole`
- Create: `docker-compose.allinone.yml`
- Create: `docker-compose.split.yml`
- Modify: `.gitignore` (add `.env.agentconsole`)

**Interfaces:**
- Consumes: three images from Tasks 1-3.
- Produces: two deployable stacks.

- [ ] **Step 1: Write `.env.agentconsole`**

Copy all keys from `config/prod.env` (values included), then override these:
```
S2S_ASR_MODEL_DIR=/root/.cache/qwen3-asr-0.6b-hf
S2S_TTS_MODEL_DIR=/root/.cache/qwen3-tts-model
S2S_SENSEVOICE_MODEL_DIR=/root/.cache/sensevoice-small
S2S_STV_MODEL_DIR=/root/.cache/wav2vec2-ljspeech-gruut
S2S_AGENT_MACHINE_ID=pipeline-local
S2S_ADMIN_TOKEN=< generate with: python -c "import secrets; print(secrets.token_urlsafe(32))" >
JWT_SECRET_KEY=< generate another 32-byte token >
S2S_AGENT_REGISTER_CODE=
```
Verify: `Select-String -Path .env.agentconsole -Pattern "D:/work"` returns nothing.

- [ ] **Step 2: Add to `.gitignore`**

Append `.env.agentconsole` to `.gitignore`. Verify with `git check-ignore .env.agentconsole` → prints the path.

- [ ] **Step 3: Write `docker-compose.allinone.yml`**

```yaml
name: s2s-allinone
volumes:
  s2s-model-cache:
    name: s2s-model-cache
services:
  pipeline:
    image: s2s-allinone:local
    build:
      context: .
      dockerfile: Dockerfile.allinone
    entrypoint: ["sh", "-c"]
    command: ["cd /app/console && exec /usr/src/app/.venv/bin/alembic upgrade head && exec speech-to-speech serve -f /app/config/prod.yaml --name prod --with-agent --with-console"]
    env_file: [.env.agentconsole]
    environment:
      CONSOLE_HOME: /app/console
      CONSOLE_STATIC_DIR: /app/console/static
      S2S_AGENT_CONSOLE_URL: http://127.0.0.1:8765
      S2S_AGENT_MACHINE_ID: pipeline-local
      HF_HUB_OFFLINE: "1"
      TRANSFORMERS_OFFLINE: "1"
    ports:
      - "8765:8765"
      - "8000:8765"
    volumes:
      - s2s-model-cache:/root/.cache/
      - ./silero-vad:/opt/silero-vad:ro
      - ./config:/app/config
      - ./data:/app/data
      - ./docs/parameter-catalog.yaml:/app/catalog/parameter-catalog.yaml:ro
    extra_hosts: ["host.docker.internal:host-gateway"]
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['0']
              capabilities: [gpu]
```

Verify: `docker compose -f docker-compose.allinone.yml config > $null` → exit 0.

- [ ] **Step 4: Write `docker-compose.split.yml`**

```yaml
name: s2s-split
volumes:
  s2s-model-cache:
    name: s2s-model-cache
services:
  s2s-console:
    image: s2s-console:local
    build:
      context: .
      dockerfile: Dockerfile.console
    ports: ["8000:8000"]
    environment:
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      PIPELINE_BASE_URL: http://s2s-pipeline:8765
    volumes:
      - ./config:/app/config
      - ./data:/app/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  s2s-pipeline:
    image: s2s-agent:local
    build:
      context: .
      dockerfile: Dockerfile.agent
    command: ["serve", "-f", "/app/config/prod.yaml", "--name", "prod", "--with-agent"]
    env_file: [.env.agentconsole]
    environment:
      S2S_AGENT_CONSOLE_URL: http://s2s-console:8000
      S2S_AGENT_MACHINE_ID: pipeline-local
      HF_HUB_OFFLINE: "1"
      TRANSFORMERS_OFFLINE: "1"
    ports: ["8765:8765"]
    volumes:
      - s2s-model-cache:/root/.cache/
      - ./silero-vad:/opt/silero-vad:ro
      - ./config:/app/config
      - ./data:/app/data
    depends_on:
      s2s-console:
        condition: service_healthy
    extra_hosts: ["host.docker.internal:host-gateway"]
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['0']
              capabilities: [gpu]
```

Verify: `docker compose -f docker-compose.split.yml --env-file .env.agentconsole config > $null` → exit 0.

- [ ] **Step 5: Commit**

```bash
git add .gitignore docker-compose.allinone.yml docker-compose.split.yml
git commit -m "build: add all-in-one and split compose stacks"
```
(`.env.agentconsole` is ignored — do not commit.)

---

### Task 5: Build all images and populate model volume

**Files:** none (operations task).

**Interfaces:**
- Consumes: Dockerfiles from Tasks 1-3.
- Produces: local images + populated `s2s-model-cache` volume.

- [ ] **Step 1: Build images**

```bash
docker build -f Dockerfile.allinone -t s2s-allinone:local .
docker build -f Dockerfile.agent -t s2s-agent:local .
docker build -f Dockerfile.console -t s2s-console:local .
```
Verify: `docker images | Select-String "s2s-(allinone|agent|console)"` shows all three, none are `<none>`.

- [ ] **Step 2: Populate model volume**

```bash
docker volume create s2s-model-cache
docker run --rm -v "$PWD/cache:/src:ro" -v s2s-model-cache:/dst `
  s2s-agent:local sh -c "cp -a /src/. /dst/"
```
Verify:
```
docker run --rm -v s2s-model-cache:/root/.cache s2s-agent:local ls /root/.cache/sensevoice-small
```
Expected: model files listed, not "No such file or directory".

- [ ] **Step 3: Write deployment README**

Create `docs/agentconsole-deploy-CN.md` with:
- two deployment commands (allinone / split)
- model volume one-time setup command from Step 2
- agent full registration flow (Task 6 steps)
- port map table
- troubleshooting: cu130 driver check, `.env` not baked (verify command), DB migration verification (`docker exec ... python -c "from app.db.database import SessionLocal; ..."` or `alembic current`)

- [ ] **Step 4: Commit**

```bash
git add docs/agentconsole-deploy-CN.md
git commit -m "docs: add agentconsole deployment guide"
```

---

### Task 6: Deploy and verify (allinone first, then split)

**Files:** none (operations task).

**Interfaces:**
- Consumes: images and compose files from Tasks 4-5.
- Produces: running containers verified end-to-end including agent registration/heartbeat.

- [ ] **Step 1: Start allinone**

```bash
docker compose -f docker-compose.allinone.yml --env-file .env.agentconsole up -d
```
Verify: `docker compose -f docker-compose.allinone.yml ps` → `pipeline` Up. If it restarts, `docker compose -f docker-compose.allinone.yml logs --tail=80` and check: alembic error (DB), `driver too old` (cu128 mix), model path (`D:/...` leaked from env).

- [ ] **Step 2: Verify allinone HTTP endpoints**

```bash
curl -s -o $null -w "%{http_code}" http://localhost:8765/v1/agent/capability   # expect 200
curl -s -o $null -w "%{http_code}" http://localhost:8000/console             # expect 200
curl -s -o $null -w "%{http_code}" http://localhost:8765/docs                # expect 200
curl -s http://localhost:8765/v1/agent/capability | python -c "import json,sys; d=json.load(sys.stdin); assert d['pipeline_reachable'] is True; print('capability OK')"
```
Also verify DB migration really happened (not just `/health`):
```
docker compose -f docker-compose.allinone.yml exec pipeline sh -c "cd /app/console && /usr/src/app/.venv/bin/alembic current"
```
Expected: a revision hash, not "no migrations".

- [ ] **Step 3: Verify agent registration + heartbeat (allinone)**

```bash
# 1) seed admin (if not already)
docker compose -f docker-compose.allinone.yml exec pipeline `
  sh -c "cd /app/console && python scripts/seed_admin.py --username admin --role admin --password '<strong-pwd>'"
# 2) login → JWT
curl -s -X POST http://localhost:8765/api/v1/auth/login -H "Content-Type: application/json" `
  -d '{"username":"admin","password":"<strong-pwd>"}' > login.json
# 3) create machine → registerCode
curl -s -X POST http://localhost:8765/api/v1/machines -H "Content-Type: application/json" `
  -H "Authorization: Bearer <JWT from login.json>" `
  -d '{"name":"pipeline-local","machineId":"pipeline-local"}' > machine.json
# 4) inject register code and restart
#    (edit .env.agentconsole: S2S_AGENT_REGISTER_CODE=<registerCode from machine.json>)
docker compose -f docker-compose.allinone.yml up -d --force-recreate pipeline
# 5) verify
curl -s http://localhost:8765/v1/agent/status | python -c "import json,sys; d=json.load(sys.stdin); assert d['registered'] and d['last_heartbeat_ok']; print('agent registered + heartbeat OK')"
```
If `POST /api/v1/machines` returns 422, inspect the schema at `console/backend/app/schemas/machine.py` — the payload field names may differ; this is the only task step where a schema lookup is allowed.

- [ ] **Step 4: Stop allinone, start split**

```bash
docker compose -f docker-compose.allinone.yml down
docker compose -f docker-compose.split.yml --env-file .env.agentconsole up -d
```
Verify: both containers Up; `curl localhost:8000/api/v1/health` → 200 (with DB migrated via CMD); `curl localhost:8765/v1/agent/capability` → 200.

- [ ] **Step 5: Verify agent registration + heartbeat (split)**

Repeat Step 3 with these changes:
- seed admin inside `s2s-console` container: `docker compose -f docker-compose.split.yml exec s2s-console python scripts/seed_admin.py ...`
- login and create-machine calls go to `http://localhost:8000/api/v1/*`
- restart only `s2s-pipeline`: `docker compose -f docker-compose.split.yml up -d --force-recreate s2s-pipeline`
- status check still on `http://localhost:8765/v1/agent/status`

Expected: `registered=true`, `last_heartbeat_ok=true`; console machine list shows fresh heartbeat time.

- [ ] **Step 6: Final report**

Write a short status section into `docs/agentconsole-deploy-CN.md` with: build durations, container names, verified endpoints, agent registration confirmation, and any deviations from the design. No commit needed for a local-only doc? **Commit it** with message `docs: record agentconsole deployment verification`.

- [ ] **Step 7: Commit any local fixes**

If steps above required edits to Dockerfiles/compose, commit them in one focused commit with a message naming the fix (e.g. `fix: pin psycopg2 wheel for slim console image`). Do not fold unrelated working-tree changes (the user's pre-existing edits to `sense_voice_handler.py`, `qwen3_tts_handler.py`, `config/prod.yaml`, etc.) into these commits — stage only files named in this plan.
