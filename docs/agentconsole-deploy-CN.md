# AgentConsole 双形态本地部署

基于设计 `docs/superpowers/specs/2026-11-19-agentconsole-docker-images-design.md`
与实施计划 `docs/superpowers/plans/2026-11-19-agentconsole-docker-images.md`。

本目录提供两种部署形态、三个镜像：

| 形态 | 镜像 | 端口 | compose |
|---|---|---|---|
| 一体（s2s+console+agent 单进程） | `s2s-allinone:local` | 宿主 8765→容器 8765（API/WS/agent）、宿主 8000→容器 8765（console UI） | `docker-compose.allinone.yml` |
| 分离（s2s+agent / console 两容器） | `s2s-agent:local` + `s2s-console:local` | s2s 8765、console 8000 | `docker-compose.split.yml` |

## 前置条件

- Docker Desktop + NVIDIA Container Toolkit；宿主驱动 ≥ 580（本机 617.42，CUDA 13）。
- 镜像基座 `ccr.ccs.tencentyun.com/llm-basic/python-torch:cu130` 与 `node:20-alpine` 可拉取。
- 本地模型缓存 `cache/`、silero-vad 仓库 `silero-vad/` 存在。
- `console/backend/.env` 存在（console 的 JWT/DB 等开发配置）。

## 一次性准备

```bash
# 1) 生成容器专用 env（从 config/prod.env 派生 + 容器路径/令牌/DB）
#    .env.agentconsole 含敏感信息，已加入 .gitignore，禁止提交。
python gen_env_tmp.py            # 见附录：生成脚本需自行保留或按下面模板手写

# 2) 生成容器专用 config（关闭 visemes——容器没有 STV 模型）
python gen_container_config_tmp.py

# 3) 灌入模型卷（避免 Windows 绑定挂载读权重极慢）
docker volume create s2s-model-cache
docker run --rm -v "$PWD/cache:/src:ro" -v s2s-model-cache:/dst `
  --entrypoint sh s2s-agent:local -c "cp -a /src/. /dst/"
```

`.env.agentconsole` 关键覆盖项：

```dotenv
S2S_ASR_MODEL_DIR=/root/.cache/qwen3-asr-0.6b-hf
S2S_TTS_MODEL_DIR=/root/.cache/qwen3-tts-model
S2S_SENSEVOICE_MODEL_DIR=/root/.cache/sensevoice-small
S2S_STV_MODEL_DIR=/root/.cache/wav2vec2-ljspeech-gruut
S2S_AGENT_MACHINE_ID=pipeline-local
S2S_ADMIN_TOKEN=<secrets.token_urlsafe(32)>
JWT_SECRET_KEY=<secrets.token_urlsafe(32)>
S2S_AGENT_REGISTER_CODE=
DATABASE_URL=postgresql+psycopg2://postgres:postgres%402026!@192.168.100.80:5432/mediation_db
```

> **数据库**：按本次部署要求，console 连接远程共享库
> `192.168.100.80:5432/mediation_db`（用户 postgres）。密码中的 `@` 必须写成
> `%40`。Alembic 的 `env.py` 已修复 `%` 插值问题；0007 迁移已修复对尚未创建的
> 表/列执行 `COMMENT ON` 导致 PostgreSQL 迁移失败的问题（用 DO block 捕获
> `undefined_table`/`undefined_column` 后跳过）。该库 public schema 下 348 张表，
> 无同名 console 表，alembic 只新增不覆盖。

## 部署命令

### 一体形态

```bash
docker compose -f docker-compose.allinone.yml --env-file .env.agentconsole up -d
```

启动后等待约 2 分钟（首次加载 SenseVoice 13s 推理 + Qwen3-TTS CUDA graph warmup），
验证：

```bash
curl http://localhost:8765/v1/agent/capability   # 200
curl http://localhost:8765/v1/agent/status       # 200
curl http://localhost:8000/console               # 200 (console UI)
curl http://localhost:8765/docs                  # 200 (Swagger UI, 含「运维代理」分组)
```

### 分离形态

```bash
docker compose -f docker-compose.split.yml --env-file .env.agentconsole up -d
```

验证：

```bash
curl http://localhost:8765/v1/agent/capability   # 200
curl http://localhost:8000/api/v1/health         # 200 (console 后端)
```

agent 通过 compose 服务名 `http://s2s-console:8000` 访问 console。

## agent 完整注册 + 心跳

两种形态一致（一体走 `localhost:8765/api/v1`，分离走 `localhost:8000/api/v1`）：

1. console 建管理员（首次）：
   ```bash
   docker compose exec <console容器> python /app/scripts/seed_admin.py --username admin --role admin --password '<pwd>'
   ```
   一体形态的 console 嵌在 pipeline 容器内，容器名为 `s2s-allinone-pipeline-1`。
2. 登录取 JWT：`POST /api/v1/auth/login` → `accessToken`
3. 创建 machine 拿注册码：`POST /api/v1/machines` → `registerCode`（需 JWT）
4. 回填 `.env.agentconsole` 的 `S2S_AGENT_REGISTER_CODE`，重启 s2s 容器
5. 验证：`GET /v1/agent/status` 的 `registered=true`、`last_heartbeat_ok=true`

## 关键坑与修复记录

| 问题 | 修复 |
|---|---|
| `uv sync` 拉 cu128 torch 时 TLS handshake eof | cu130 基座完整重建也需要访问 pytorch 索引；设置 `UV_NATIVE_TLS=true` + `--index-strategy unsafe-best-match`；cu128 pin 从 pyproject 改写中剥掉，让基座 cu130 wheel 生效 |
| 一体镜像缺 `funasr`（`ModuleNotFoundError`） | 两个 s2s Dockerfile 在 `uv pip install -e . --no-deps` 后补装 `funasr>=1.1.6` |
| 容器 `Restarting (0)` 无错误日志 | compose command 里第一个 `exec alembic ...` 把 shell 替换掉，`&&` 后面的 serve 永不执行；去掉第一个 `exec`，只在 serve 前保留 |
| 宿主 PyCharm 的 `serve --with-agent` 占 8765 → 容器无法绑定 | 停掉宿主进程后再 `up` |
| `S2S_STV_MODEL_DIR` 指向不存在的模型 → handler 失败拖垮 runtime | 生成 `config.container/prod.yaml`，把 `enable_visemes: true` 改为 `false`，compose 挂载该目录 |
| alembic URL 中 `%40` 被 configparser 当插值报错 | `console/backend/alembic/env.py` 在 `set_main_option` 前把 `%` 转义为 `%%` |
| PostgreSQL 下 0007 迁移 `COMMENT ON` 不存在的表/列 | 0007 迁移把每条 COMMENT 包进 `DO ... EXCEPTION WHEN undefined_table OR undefined_column THEN NULL` |

## 验证状态（2026-11-19）

- 三镜像构建成功：`s2s-allinone:local`、`s2s-agent:local`（cu130 torch 2.15.0+cu132）、`s2s-console:local`。
- 模型卷 `s2s-model-cache` 已从 `cache/` 灌入，含 `cache/qwen3-speaker-encoder/` 切分权重。
- 一体形态：容器稳定 `Up`，DB 指向 `192.168.100.80/mediation_db`，alembic 迁移跑完，
  `/v1/agent/capability`、`/v1/agent/status`、`/console`、`/docs` 均实测 **HTTP 200**。
  agent status 显示 `enabled=true, running=true, pipeline_reachable=true`；
  `registered=false` 因尚未做注册（预期，注册后心跳启动）。
- 分离形态：镜像/编排已就绪，未做最终端到端（与一体共用同一套 agent/console 逻辑）。
- agent 完整注册+心跳：流程已文档化，尚未在本轮执行（需提供管理员密码与注册码流程 API）。
