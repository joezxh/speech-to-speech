FROM node:24-slim AS agents-sdk

WORKDIR /sdk
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# Single runtime container: serves the static front-end AND API proxies.
# HF Spaces (sdk: docker) routes traffic to $PORT, default 7860.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=agents-sdk /sdk/node_modules/@openai/agents-realtime/dist/bundle/openai-realtime-agents.umd.js /app/vendor/openai-realtime-agents.umd.js

# ── Deployment parameter console (console.html + /admin/*) ────────────────────
# `param_platform.catalog` resolves `parameter-catalog.yaml` first-readable-wins:
#   1. $PARAM_CATALOG_PATH
#   2. <app>/catalog/parameter-catalog.yaml   -> /app/catalog/... in this image
#   3. <app>/../docs/parameter-catalog.yaml   -> only true in a source checkout
#
# The build context is this directory (demo/), so the 90 KB catalog that lives at
# speech-to-speech-src/docs/parameter-catalog.yaml never reaches the image and
# rule 3 cannot fire in a container. Pick exactly one:
#
#   A. Baked in (published image). Keep a copy at catalog/ and uncomment the COPY
#      below:  cp ../docs/parameter-catalog.yaml catalog/
#      It stays commented because `COPY` of a missing file fails the build, and a
#      Space running only the voice demo must still build.
#   B. Mounted at run time. No image change:
#      -v $PWD/docs/parameter-catalog.yaml:/app/catalog/parameter-catalog.yaml:ro
#   C. Shipped without it. index.html/console.html still load; /admin/catalog
#      answers 503 `catalog_unavailable` and the console prints the hint, while
#      the read-only views (versions / audit / instances) keep working.
#
# Everything else the console needs is a path or a token, all optional and all
# resolved at request time: PARAM_CONFIG_DIR (default ./config, one
# `<profile>.yaml` + optional `<profile>.env` per profile), PARAM_DB_PATH
# (SQLite: drafts / versions / audit), PARAM_COMPOSE_FILE + PARAM_COMPOSE_SERVICE
# (which container a publish recreates), PARAM_POOL_URL (the `/v1/pool` the
# publish flow probes), PARAM_VRAM_GB + PARAM_PIPELINE_VRAM_GB (the VRAM budget a
# render is validated against), ADMIN_TOKEN + OPERATOR_TOKEN (who may write),
# S2S_ADMIN_TOKEN (chain B forwarding to the pipeline's own admin route).
# COPY catalog/parameter-catalog.yaml /app/catalog/parameter-catalog.yaml

EXPOSE 7860

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
