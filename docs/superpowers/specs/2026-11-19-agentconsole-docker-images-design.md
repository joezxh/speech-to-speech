# 2026-11-19 一体 / 分离双形态 Docker 镜像设计

## 意图与背景

工作区刚为 `speech-to-speech serve` 新增 `--with-agent`（内嵌 s2s-agent + `/v1/agent/*` REST）与既有的 `--with-console`（内嵌 console 前后端）。需要把这两种能力容器化并部署到本机，且同时提供两种部署形态：

1. **一体形态**：单个容器、单个进程（`serve --with-agent --with-console`），console/API/WS/agent 全部由 8765 提供。
2. **分离形态**：`s2s+agent` 容器 + 独立 `console` 容器，各自 8765 / 8000，通过 compose 网络互通，agent 通过服务名访问 console。

用户明确选择：**完整重建**（不复用 11.8GB 旧镜像做增量）、轻量纯 console 镜像、tag 用 `s2s-*:local`、agent **要做完整注册+心跳**（不只验 capability）。

### Builder check 后的技术修正（必须落实）

1. **禁止把宿主开发 `.env` 烤进镜像**：`console/backend/.env` 含 Windows 路径与开发用 PostgreSQL URL，且未被 `.dockerignore` 排除。构建时用 `.dockerignore` 追加 `console/backend/.env`，或在 Dockerfile 里 `RUN rm -f /app/console/.env`；所有运行期配置统一由 compose `environment` 注入。
2. **DB 必须显式迁移**：console 不在启动时自动建表，空库会让 `/api/v1/health` 假通过、注册/登录 API 500。console 容器入口改为 `sh -c "alembic upgrade head && uvicorn ..."`；一体形态在 `command` 前置一个初始化步骤（见 §4）。
3. **allinone 换 cu130 基座时同步换 `UV_INDEX`**：主 `Dockerfile` 写死 cu128 索引，必须改为 `Dockerfile.cu130` 的 cu130 索引 + 对应的 constraints 处理，否则会把 cu128 torch 装进 cu130 基座。
4. **模型 named volume 灌入**：定义卷 `s2s-model-cache`，首次由一段 `docker run --rm -v ./cache:/src:ro -v s2s-model-cache:/dst ... cp -a /src/. /dst/` 灌入（README 里给命令）；compose 只挂载卷。
5. **agent 注册流程**：按用户选择，部署后执行 console 建管理员 → 登录取 JWT → 创建 machine 拿注册码 → 注入 `S2S_AGENT_REGISTER_CODE` → 重启 → 验证心跳。catalog 与验证清单都要体现。

## 目标 / 非目标

**目标**
- 3 个可重复构建的镜像：`s2s-allinone:local`、`s2s-agent:local`、`s2s-console:local`。
- 2 份 compose：一体（`docker-compose.allinone.yml`）与分离（`docker-compose.split.yml`）。
- 本机驱动 617.42 → s2s 镜像必须 cu130 基座。
- 保留用户现有 `config/prod.env`（PyCharm 运行配置）不动，容器专用 env 另起文件。
- 对外访问：`localhost:8765`（API/WS/agent）、`localhost:8000`（console UI）。

**非目标**
- 不做真实语音端到端（需音频输入设备）；只验证镜像构建、容器 Up、三入口 HTTP 200、agent capability。
- 不改业务代码（上一轮已交付）。
- 不发布到镜像仓库，仅本地 tag。

## 约束（已核对）

| 事实 | 影响 |
|---|---|
| 宿主驱动 617.42（CUDA 13） | s2s 镜像必须用 `ccr.ccs.tencentyun.com/llm-basic/python-torch:cu130`；主 `Dockerfile` 默认 cu128 会 driver too old |
| `node:20-alpine` 与 cu130 基座已成功拉取 | 完整重建的网络前提已满足 |
| 主 `Dockerfile` = s2s + console 前后端 + supervisord（cu128 基座），`COPY src` 会带上全部新 agent 代码 | 一体镜像可在它基础上换基座、绕过 supervisord 即可 |
| `Dockerfile.cu130` = 纯 s2s（无 console / 无 sox / 无 nltk 资源 / 无 ASR-TTS REST 补丁） | 分离形态的 s2s 镜像需补这几项，或接受源码自带 mount 不含补丁的旧行为 |
| 源码 `websocket_router.py` 已直接 `mount_audio_services` / `mount_voiceprint` 等 | ASR/TTS/声纹端点由源码提供，**无需** `patch_pipeline_rest.py` / `patch_voiceprint_embeddings.py` |
| `config/prod.env` 含 Windows 路径（`D:/work/.../cache/sensevoice-small`） | 容器需 `.env.agentconsole` 覆盖为 `/root/.cache/...` |
| `cache/nltk_data`、`silero-vad`、`cache/*` 模型目录均存在 | 可烤进镜像或卷挂载；模型走 named volume 避免 Windows 绑定挂载慢 |
| `data/` 不存在 | compose 挂载会自动创建 |

## 方案（Approaches）

### 方案 A：三个独立 Dockerfile（选定）

| 镜像 | Dockerfile | 基座 | 内容 |
|---|---|---|---|
| `s2s-allinone:local` | `Dockerfile.allinone` | `python-torch:cu130` | 主 Dockerfile 全部阶段（node 前端 build + console deps + s2s deps + `COPY src` + nltk + sox + TTS compat），但 entrypoint 改为直接 `serve`，不用 supervisord |
| `s2s-agent:local` | `Dockerfile.agent` | `python-torch:cu130` | `Dockerfile.cu130` 全部步骤 + 补 sox / COPY `cache/nltk_data` / 显式 `CONSOLE_*=false`，entrypoint 直接 `serve --with-agent` |
| `s2s-console:local` | `Dockerfile.console` | `python:3.12-slim` | node 前端 build stage + console backend + requirements（去掉 GPU 相关）+ uvicorn 入口，无 s2s 源码、无 torch |

**优点**：职责单一、镜像体积最优、完全可重复。
**缺点**：3 个 Dockerfile 有重复阶段（node build / console deps），维护成本略高。

### 方案 B：单 Dockerfile 多 target

一个 Dockerfile 用 `AS allinone / AS agent / AS console` 三个 target，compose 用 `target:` 选择。
**放弃理由**：cu130 基座与 python-slim 基座不同，多 target 无法干净共用；分支逻辑反而更复杂。

### 方案 C：复用旧镜像增量

**放弃理由**：用户明确要求完整重建。

## 详细设计

### 1. `Dockerfile.allinone`（一体）

基于 `Dockerfile` 完整复制，改动：
- `ARG BASE_IMAGE=ccr.ccs.tencentyun.com/llm-basic/python-torch:cu130`；**同步**把 `UV_INDEX` 改为 cu130 通道（照抄 `Dockerfile.cu130:32` 与 `:72` 的 constraints 处理），不能留 cu128 索引
- 保留 `FROM node:20-alpine AS frontend-build` 阶段
- 保留 console backend deps（`requirements.txt`）
- 补 `apt-get install sox`（`Dockerfile.local` 做法）
- 补 `COPY cache/nltk_data /root/nltk_data && chmod 755`
- `.dockerignore` 追加 `console/backend/.env`，避免开发配置烤进镜像
- 删除 supervisord 相关（`COPY supervisord.conf`、`COPY entrypoint.sh`、`ENTRYPOINT`）
- 改为 `ENTRYPOINT ["speech-to-speech"]`（compose 用 `command` 传 `serve ...`）
- **DB 迁移**：一体形态没有独立 console 进程来做 alembic。compose 用一个一次性 init service（同镜像、`command: ["sh","-c","cd /app/console && alembic upgrade head"]`）在 pipeline 启动前跑完；或把迁移放进 pipeline 的 entrypoint 前置（`sh -c "cd /app/console && alembic upgrade head && exec speech-to-speech serve ..."`）——本设计选后者，避免多 service 竞态。注意 alembic.ini 在 `/app/console`，迁移脚本的 `env.py` 需能找到 `DATABASE_URL` 环境变量。

### 2. `Dockerfile.agent`（分离 s2s）

基于 `Dockerfile.cu130` 完整复制，改动：
- 补 `apt-get install sox`
- 补 `COPY cache/nltk_data /root/nltk_data && chmod 755`
- 删除 nltk 在线下载步骤（已有本地资源，避免挂起）
- `ENTRYPOINT ["speech-to-speech"]`

### 3. `Dockerfile.console`（分离 console）

```
FROM node:20-alpine AS frontend-build
COPY console/frontend/... → npm ci && npm run build

FROM python:3.12-slim
WORKDIR /app
COPY console/backend/requirements.txt → pip install --no-cache-dir -r
COPY console/backend → /app   # 注意：.dockerignore 排除 console/backend/.env
RUN rm -f /app/.env || true
COPY --from=frontend-build /build/dist → /app/static
ENV PYTHONPATH=/app STATIC_DIR=/app/static DATABASE_URL=sqlite:////app/data/console.sqlite3 \
    PARAM_CONFIG_DIR=/app/config PARAM_CATALOG_PATH=/app/catalog/parameter-catalog.yaml \
    LOG_DIR=/app/data/logs DATA_DIR=/app/data VOICE_DATA_DIR=/app/data/voices \
    SESSION_DATA_DIR=/app/data/sessions \
    PIPELINE_BASE_URL=http://s2s-pipeline:8765 \
    JWT_SECRET_KEY=<由 compose environment 注入> \
    CONSOLE_AUTOSTART=false
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
```
去掉 `supervisor==4.2.5`（不需要），保留其余 console 依赖。`DATABASE_URL` 默认 SQLite；如需 PostgreSQL 由 compose environment 覆盖。

### 4. 两份 compose

**`docker-compose.allinone.yml`**
- service `pipeline`：`image: s2s-allinone:local`、`build`（Dockerfile.allinone）
- `entrypoint: ["sh", "-c"]`
- `command: ["cd /app/console && alembic upgrade head && exec speech-to-speech serve -f /app/config/prod.yaml --name prod --with-agent --with-console"]`（DB 迁移在进程内先跑完）
- env_file: `.env.agentconsole`
- `environment` 覆盖关键项（compose 的 environment 优先于 env_file）：
  - `CONSOLE_HOME=/app/console`、`CONSOLE_STATIC_DIR=/app/console/static`
  - `S2S_AGENT_CONSOLE_URL=http://127.0.0.1:8765`（自调用）
  - `S2S_AGENT_MACHINE_ID=pipeline-local`
- ports: `8765:8765`、`8000:8765`
- volumes: model named volume、`./config:/app/config`、`./data:/app/data`、`./silero-vad:/opt/silero-vad:ro`
- GPU reservation device `0`

**`docker-compose.split.yml`**
- service `s2s-pipeline`：`image: s2s-agent:local`、`build`（Dockerfile.agent）
  - `command: ["serve", "-f", "/app/config/prod.yaml", "--name", "prod", "--with-agent"]`
  - env_file `.env.agentconsole`
  - `S2S_AGENT_CONSOLE_URL=http://s2s-console:8000`（服务名）
  - ports: `8765:8765`
  - volumes / GPU 同上
- service `s2s-console`：`image: s2s-console:local`、`build`（Dockerfile.console）
  - ports: `8000:8000`
  - volumes: `./config:/app/config`、`./data:/app/data`
  - 无 GPU
- `depends_on`: s2s-pipeline 依赖 s2s-console（healthcheck 通过 `/api/...`）

### 5. `.env.agentconsole`（容器专用，gitignore）

从 `config/prod.env` 复制所有键，覆盖：
```
S2S_ASR_MODEL_DIR=/root/.cache/qwen3-asr-0.6b-hf
S2S_TTS_MODEL_DIR=/root/.cache/qwen3-tts-model
S2S_SENSEVOICE_MODEL_DIR=/root/.cache/sensevoice-small
S2S_STV_MODEL_DIR=/root/.cache/wav2vec2-ljspeech-gruut
S2S_AGENT_CONSOLE_URL=...（由 compose environment 再覆盖）
S2S_AGENT_MACHINE_ID=pipeline-local
S2S_ADMIN_TOKEN=<secrets.token_urlsafe(32)>
S2S_AGENT_REGISTER_CODE=   # 部署后由建档 API 生成再回填
```

**模型卷一次性灌入**（两种形态共用）：
```bash
docker volume create s2s-model-cache
docker run --rm -v "$PWD/cache:/src:ro" -v s2s-model-cache:/dst \
  <任一 s2s 镜像> sh -c "cp -a /src/. /dst/"
```

## 验证清单

1. `docker compose -f docker-compose.allinone.yml --env-file .env.agentconsole up -d --build`（记录耗时）
2. `curl localhost:8765/v1/agent/capability` → HTTP 200，`pipeline_reachable=true`
3. `curl localhost:8000/console` → console UI HTML（且 DB 已迁移，登录 API 可用）
4. `curl localhost:8765/docs` → Swagger UI（含「运维代理」分组）
5. `docker compose -f docker-compose.allinone.yml down` → 切到分离形态
6. `docker compose -f docker-compose.split.yml --env-file .env.agentconsole up -d --build`
7. `curl localhost:8000/api/v1/health` → console 后端健康（DB 已迁移）
8. `curl localhost:8765/v1/agent/capability` → HTTP 200

**agent 完整注册+心跳验收**（两种形态都要做，用户已确认要求）：
1. 在 console 侧建管理员：`docker compose exec <console容器> python /app/scripts/seed_admin.py --username admin --role admin --password <pwd>`
2. 登录取 JWT：`POST /api/v1/auth/login` → `accessToken`
3. 创建 machine 拿注册码：`POST /api/v1/machines` → `registerCode`（需 JWT）
4. 把 `S2S_AGENT_REGISTER_CODE=<registerCode>` 写入 `.env.agentconsole`，重启 s2s 容器
5. 验证：`GET /v1/agent/status` → `registered=true`、`last_heartbeat_ok=true`；console 侧机器列表心跳时间更新
6. 一体形态因 console 自调用，注册码同样通过 env 注入，流程一致

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 完整重建耗时 15-30 分钟 | 用 uv cache mount；分阶段构建可单独重试某个镜像 |
| console 轻量镜像缺 `psycopg2-binary` 编译 | 用 `--no-cache-dir` + 预编译 wheel；若失败退回 `python:3.12` 非 slim |
| 分离形态 agent 自注册到 console 需要 DB | console 用 SQLite 挂载 `./data`，首次启动自动建表（现有 console 行为） |
| 一体形态 `S2S_AGENT_CONSOLE_URL` 自调用在启动瞬间还没绑定端口 | agent 首次心跳失败会指数退避重试；不影响服务启动 |
