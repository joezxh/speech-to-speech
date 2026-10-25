# Console 与 s2s 单进程同端口整合 设计文档

> 日期：2026-10-25 ｜ 状态：待评审
> 工作目录：仓库根（`speech-to-speech-src`）
> 改动范围：`src/speech_to_speech/**`、`README.md`、`console/README.md`
> **本版取代同日《Console 同时启动与前端内嵌发布》草案**（那份是「spawn console 子进程 + 反代」，
> 已按新的单进程要求作废；旧文件已删除，不留两份互相矛盾的设计）
> console 后端：**零功能改动**（理由见 §4.1）

## 1. 背景与目标

今天 s2s 与 console 是两个进程、两个端口：容器里由 supervisord 拉起
（`console/deploy/supervisord.conf`），本机要分别敲 `speech-to-speech serve …` 与
`uvicorn app.main:app`，console 还要靠 `vite` 代理 `/api`、`/v1` 才能联调。

本次把两者**合成一个进程、一个端口**：

| 开关 | 默认 | 语义 |
|---|---|---|
| `--with-console` / `CONSOLE_AUTOSTART` | 关 | 把 console 后端**合并进 s2s 进程**，并在**同一个端口**提供 console 前端 |

- 打开：s2s 的 uvicorn 端口（默认 `127.0.0.1:8765`）同时承载
  `console 前端（/ 与 /console/*）`、`console API（/api、/api/v1）`、`s2s 自身的 /v1/*`。
- 关闭：与今天**逐字节一致**，且**不 import 任何 console 代码**、不碰 `.env`、不要求 dist 存在。

## 2. 现状（本设计依赖的事实）

1. **s2s 的 HTTP 面**：`api/openai_realtime/websocket_router.py:531 create_app(pool, stop_event, llm_proxy_config)`
   注册 `/v1/realtime`（WebSocket）、`/v1/usage`、`/v1/pool`、`/v1/realtime/calls`、
   `DELETE /v1/realtime/calls/{id}`；**没有** `/`、`/api/*`、`/assets/*`、`/vendor/*`。
   `FastAPI.__init__` 默认还注册了 `/docs`、`/redoc`、`/openapi.json`。
2. **console 后端是一棵可导入的 ASGI 应用**：`app/main.py` 模块级执行 `app = create_app()`，
   `lifespan` 是模块级 `@asynccontextmanager` 函数。lifespan 里做了四件事：
   默认管理员 bootstrap、中断发布恢复、turn-latency 索引器、计量 sweeper。
3. **console 的 SPA 托管已完备**：`app/core/spa.py` 挂 `/assets`、`/worklets`、`/vendor`（immutable），
   两枚 pinned vendor 路由，最后 `/{full_path:path}` 兜底：命中真实文件回文件、**带后缀但不存在回 404**、
   其余回 `index.html`（`no-store`）。这份语义已由 console 自己的测试覆盖，本设计直接复用。
4. **前端产物已适配根挂载**：`console/frontend/dist/index.html` 用绝对路径 `/assets/index-*.js`、
   `/vendor/openai-realtime-agents.umd.js`；`src/router/index.ts:47` 用 `createWebHistory()`（base `/`），
   console 页路由自带 `/console` 前缀 ⇒ **同一份 dist 在 `/` 与 `/console` 下刷新子路由都能加载资源**，
   前端零改动。
5. **console 配置的来源**：`app/config/__init__.py` 在导入时构造六个 settings 实例，各 settings 的
   `model_config` 都是 `env_file=".env"`（相对 **CWD**），并立刻校验 `JWT_SECRET_KEY`。
   ⇒ 进程内导入时必须先把「正确的 env 与 .env」准备好（§4.2）。
6. **依赖隔离可行**：console 的 `app.*` 只在开关打开时才 import（lazy），s2s 运行时依赖里没有
   `loguru`/`sqlalchemy` 等；关闭开关时不会触碰。
7. **dist 里有什么**：`index.html`、`assets/`、`vendor/`（`openai-realtime-agents.umd.js`、`local-vad/`）、
   `worklets/`（`mic-capture.js`、`audio-playback.js`）。
8. **console 的默认值全是容器路径**：`app/config/_console.py:9-16` 的 `param_config_dir="/app/config"`、
   `static_dir="/app/console/static"`、`pipeline_base_url="http://127.0.0.1:8765"`；
   `_database.py:10` 的 `database_url="sqlite:////app/data/console.sqlite3"`、`usage_db_path="/app/data/usage.sqlite3"`。
   ⇒ 在本机直接 import 会用错路径，**必须由 `<home>/.env` 供真实值**。仓库里 `console/backend/.env` 已存在，
   含 `JWT_SECRET_KEY`、`DATABASE_URL`、`USAGE_DB_PATH`、`PARAM_CONFIG_DIR`、`PARAM_CATALOG_PATH`、`STATIC_DIR`、
   `PIPELINE_BASE_URL`、`PIPELINE_CONTAINER`、`RESTART_MODE`、`CORS_ORIGINS` 等键 —— 这正是 §4.2 预载 `.env` 的现实依据，
   不是理论洁癖。
9. **同端口下不需要 CORS**：前端与 API 同源（都从 `:8765` 取），`.env` 里的 `CORS_ORIGINS` 在整合模式下不构成依赖；
   反过来 standalone 形态（`:8000`）才需要它。

## 3. 配置契约

### 3.1 启动参数

| 参数 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `--with-console` | 无值 | 关 | 本次运行整合 console（后端 + 前端，同端口） |
| `--no-with-console` | 无值 | — | 覆盖 `CONSOLE_AUTOSTART=true`，本次不整合 |

适用命令：`serve`、`local`（含 `-f` 文件模式）；`talk` 显式拒绝（`parser.error`）。
两个参数在 `cli.main()` 里**先被剥掉**，再交给 `parse_command()` / HfArgumentParser，
因此不会触发「未知参数」错误，也不影响既有 `-f`/`--name` 的严格校验。

### 3.2 环境变量

| 变量 | 默认 | 用途 |
|---|---|---|
| `CONSOLE_AUTOSTART` | `false` | 同 `--with-console` |
| `CONSOLE_HOME` | `<repo>/console/backend` | 含 `app/main.py` 的目录，导入前插入 `sys.path` |
| `CONSOLE_STATIC_DIR` | `<repo>/console/frontend/dist` | 前端产物；作为 `STATIC_DIR` 交给 console |

- 布尔取值：`1/true/yes/on` 真，`0/false/no/off/空` 假，其它值 → `ConfigurationError`（消息带变量名）。
- 优先级：**CLI > 环境变量 > 默认值**。
- `<repo>` 由 `Path(__file__).resolve().parents[2]` 推导；wheel 安装下推不出仓库根，
  报错文本要求显式给 `CONSOLE_HOME` / `CONSOLE_STATIC_DIR`。
- **不再有** `CONSOLE_HOST` / `CONSOLE_PORT` / `*_TIMEOUT_S`：没有第二个地址，也没有子进程要等。

### 3.3 准备期校验（`options.validate()`，cli 解析完立即调用，早于模型加载）

仅 `autostart` 为真时执行；为假则**不碰文件系统**：

1. `home / "app" / "main.py"` 存在，否则报错并提示设 `CONSOLE_HOME` 或装 console 依赖。
2. `static_dir / "index.html"` 存在，否则报错并提示 `cd console/frontend && npm run build`。
3. 两项都失败 → `ConfigurationError` → **退出码 2**，一个模型都不加载。

## 4. 集成方式

### 4.1 为什么 console 后端可以零改动

- **不需要工厂化**：`app/main.py` 模块级构造的 `app` 就是我们要挂载的对象；
  s2s 导入该模块一次，复用**同一个** ASGI 实例，不会二次构造。
- **lifespan 可手动进入**：`app/main.py` 的 `lifespan` 是模块级 asynccontextmanager，
  s2s 在自己的 lifespan 里 `async with console_lifespan(console_app)` 即可，
  不依赖 Starlette 对子应用的 lifespan 传递（它本来也不传）。
- **配置可外部喂**：console 的 settings 读「CWD 的 .env + 真实环境变量」；
  s2s 在 import 前用 `os.environ.setdefault` 预载 `<home>/.env`（真实环境变量优先），
  再用覆盖方式设两个变量（§4.2），语义与「在 console 目录里启动」一致。
- **静态托管可复用**：见 §2.3，不需要在 s2s 里重写一份 `mount_spa`。

唯一代价是 §10 列的三条已知风险（`app` 包名、loguru 双配置、`/docs` 例外），都由日志或文档兜住。

### 4.2 新增 `src/speech_to_speech/console_integration.py`

| 符号 | 职责 |
|---|---|
| `ConsoleOptions`（frozen dataclass） | `autostart`、`home`、`static_dir`；`validate()`、`resolve_home()`、`resolve_static_dir()` |
| `parse_console_arguments(argv) -> (options, remaining)` | **唯一**读 §3.2 环境变量与 §3.1 参数的地方 |
| `ConsoleAttachment`（frozen dataclass） | `app: FastAPI`、`lifespan: Callable`、`home: Path`、`static_dir: Path` |
| `load_console(options, *, pipeline_base_url, loader=None) -> ConsoleAttachment` | 预载 env → 插入 `sys.path` → import `app.main` → 返回 attachment；`loader` 是测试缝 |
| `ConsoleImportError(ConfigurationError)` | 依赖缺失/配置非法时抛出，由 cli 映射成退出码 2 |

`load_console()` 的动作，顺序固定：

1. `os.environ.setdefault` 逐项预载 `<home>/.env`（缺文件则跳过，不报错）。
2. 覆盖两项：
   - `PIPELINE_BASE_URL = pipeline_base_url`（= `http://<probe_host>:<port>`，即本进程自己；
     console 的状态页、实例页、发布/热更新都要探这同一个进程）；
   - `STATIC_DIR = <static_dir>`（与内嵌挂载同源，避免 console 默认相对路径在别的 CWD 下失配）。
   若操作者原来设了不同的值，打一条 WARNING 说明被覆盖。
3. `sys.path.insert(0, str(home))`，然后 `import app.main`（模块级会构造好 `app`）。
4. 校验 `Path(app.main.__file__)` 位于 `home` 之下；否则说明命中了同名第三方包 →
   报 `ConsoleImportError`，提示改名/隔离 venv。
5. 返回 `ConsoleAttachment(app=app.main.app, lifespan=app.main.lifespan, …)`。
6. `ImportError` / `RuntimeError`（含 `JWT_SECRET_KEY is required`）→ 包装成 `ConsoleImportError`，
   消息里带原始错误与「装依赖 / 配 `.env`」两条指引；原始 traceback 只写 DEBUG。

### 4.3 既有文件（只追加参数，默认值等于旧行为）

| 文件 | 改动 |
|---|---|
| `cli.py` | `main()` 先 `parse_console_arguments(sys.argv[1:])`；`validate()` 失败 → 打印 + `SystemExit(2)`；把 `options` 传给两条运行路径；两个调用点（`run_pipeline_command` 与 `_run_file_command` 里的 `run_configured_command`）都包 `except (ConsoleImportError, ConfigurationError) → exit 2` / `except StartupError → exit 1`，且排在通用 `except Exception → 1` 之前；`talk` 带开关 → `parser.error`。`speech-to-speech --help` / `serve --help` / `local --help` 追加「Console options」段（参数 + 环境变量 + 默认值 + 三种组合的说明） |
| `s2s_pipeline.py` | `run_pipeline_command(command, argv, *, console=None)` → `_run_parsed_pipeline_command(..., console)` → `build_pipeline(args, stop_event, *, console=None)` / `build_local_pipeline(args, stop_event, *, console=None)` → `RealtimeServer(..., console=attachment)` |
| `configured_runtime.py` | `run_configured_command(command, config, *, console=None)` → `_run_configured_command(..., console)` → `build_configured_server(..., console=None)` |
| `api/openai_realtime/server.py` | `RealtimeServer.__init__(..., console=None)`；`run()` 传给 `create_app`；新增 `startup_failed` 标记（§5.3） |
| `api/openai_realtime/websocket_router.py` | `create_app(..., console=None)`：lifespan 包住 console 的 lifespan；末尾 `app.mount("/", console.app)` |
| `README.md` / `console/README.md` | 单端口整合说明、参数与环境变量、验证命令；console 侧加互链并注明「8000 仅 standalone 部署时使用」 |

**console 后端不改**：不加环境变量、不改 `app/main.py`、不动 `spa.py`、不动 supervisord/compose。

### 4.4 挂载与路由顺序（`create_app` 末尾）

```python
app = FastAPI(lifespan=lifespan_with_console)   # 沿用现有构造
...  # 既有 @app.websocket("/v1/realtime") / @app.get("/v1/pool") / ... 全部照旧
if console is not None:
    app.mount("/", console.app)                 # 必须最后
```

Starlette 按注册顺序匹配，因此：

| 请求 | 谁应答 | 说明 |
|---|---|---|
| `/v1/realtime`（WS 升级）、`/v1/pool`、`/v1/usage`、`/v1/realtime/calls` | **s2s 自己的路由** | 先注册，行为与今天完全一致 |
| `/docs`、`/redoc`、`/openapi.json` | s2s（`FastAPI.__init__` 早于一切） | 已知例外，见 §10 |
| `/api/config`、`/api/*`、`/api/v1/*` | console 应用 | 同进程直接调用，**没有反代、没有第二个端口** |
| `/`、`/console/*`、`/assets/*`、`/vendor/*`、`/worklets/*` | console 应用 | `/assets` 等命中真实文件；`/console/params` 回 `index.html`；`/main.js` 回 404 |
| 其它 | console 的 SPA 兜底 | 无后缀回 `index.html`，带后缀回 404 |

**console 自带的三条 `/v1/*` 路由（`/v1/realtime` 代理、`/v1/realtime/calls`）在本模式下永远收不到请求**，
因为父应用的 `/v1/*` 先匹配。它们不是错误，只是死代码；文档里写明，
不要误以为「console 还在反代 pipeline」。

## 5. 生命周期与失败处理

### 5.1 启动时序（`autostart=true`）

```
parse flags ──► options.validate()                 # 失败 exit 2，未加载模型
   │
   ├─ parse s2s args ──► load_console(options, base_url)   # import 失败 → exit 2
   ├─ build models（既有流程）
   ├─ server thread start ──► create_app(console=attachment)
   │        └─ lifespan: async with console_lifespan(console_app):
   │              默认管理员 bootstrap / 中断发布恢复 / turn-latency 索引 / 计量 sweeper
   └─ log: console integrated 一行（§5.4）
```

- **没有子进程、没有健康探活、没有看门狗、没有回收流程**：一个进程，起不来就是起不来。
- console 的 lifespan 在 s2s 的事件循环里运行；它内部对异常都做了 `try/except`（例如 DB 不可用只记
  ERROR 不阻断启动），所以不会把 s2s 拖死。
- `load_console()` 在主线程、模型加载**之前**完成：一旦缺依赖或 `JWT_SECRET_KEY` 缺失，
  在花几十秒加载模型之前就失败退出。

### 5.2 退出码

| 情形 | 退出码 |
|---|---|
| 准备期校验失败（home/dist 缺失、非法布尔） | 2 |
| console 导入失败（缺依赖、`JWT_SECRET_KEY` 缺失、`app` 包名冲突） | 2 |
| s2s 自身监听失败（端口占用）——**本次补齐**，见 §5.3 | 1 |
| Ctrl-C / SIGTERM 正常结束 | 0 |
| `autostart=false` 时的任何失败 | 与今天完全一致（不拦截） |

### 5.3 顺带修掉「端口占用却退出 0」（仅在本开关打开时生效）

现状：uvicorn 绑定失败会在自己的线程里 `sys.exit(1)`，`threading` 吞掉 `SystemExit`，
线程结束 → `ThreadManager.wait()` 正常返回 → 主进程 **exit 0**。

改动：`RealtimeServer.run()` 在 `server.run()` 返回后检查 `server.started`，
为假则置 `self.startup_failed = True` 并打 ERROR。两条运行路径在 wait 返回后检查该标记，
抛出 `StartupError` → cli 收口 **exit 1**。正常关闭时 `started` 已为真，不会误报。

已核过 uvicorn 侧的事实（`.venv/Lib/site-packages/uvicorn/server.py`）：`__init__` 里 `self.started = False`（:72）；
绑定失败走 `sys.exit(STARTUP_FAILURE)`（:118、:192）；成功绑定后才 `self.started = True`（:205）。
所以「run() 返回且 started 为假」是绑定失败的唯一稳定判据，不依赖解析日志文本。

范围限定：`autostart=false` 时不改变退出码语义（避免动到既有部署脚本的行为）。

### 5.4 日志

开关打开时，加载完成后打一行：

```
console: integrated=true | http://127.0.0.1:8765  ui=/  console=/console  api=/api  realtime=/v1/realtime
console: home=<repo>/console/backend  static=<repo>/console/frontend/dist  env_file=<home>/.env
console: PIPELINE_BASE_URL=http://127.0.0.1:8765 (self)
```

开关关闭时只多一行 `console: integrated=false`，其余输出与今天一致。

## 6. 与 standalone console 的关系

| 部署形态 | console 页面 | console API | pipeline |
|---|---|---|---|
| supervisord / compose（现状，不改） | `:8000/console` | `:8000/api/*` | `:8765`（经 console 反代） |
| `--with-console`（本设计） | `:8765/console` 与 `:8765/` | `:8765/api/*` | 同进程 `/v1/*` |
| 不带开关（现状） | 无 | 无 | `:8765` |

同一份 `console/backend` 与同一份 dist 支持两种形态；`PIPELINE_BASE_URL` 在两种形态下都指向
真实 pipeline（整合模式下就是本进程的监听地址）。

## 7. 测试计划

### 7.1 新增 `tests/test_console_integration.py`（纯单元，不 import 真 console）

- `parse_console_arguments`：env 默认、CLI 覆盖、`--no-with-console` 覆盖 `CONSOLE_AUTOSTART=true`、
  非法布尔报 `ConfigurationError`、flag 从 `remaining` 消失。
- `validate()`：缺 `app/main.py` / 缺 `index.html` 的报错文本；开关关时不碰文件系统
  （用 `monkeypatch` 让 `Path.exists` 抛错来证明没被调用）。
- env 预载：临时 `.env` 里的键被填入 `os.environ`；**已存在的真实环境变量不被覆盖**；
  `PIPELINE_BASE_URL` / `STATIC_DIR` 被强制覆盖且打 WARNING。
- `load_console(loader=...)`：注入假模块（带 `app`/`lifespan`/`__file__`）→ 返回 attachment；
  `__file__` 不在 `home` 下 → `ConsoleImportError`；loader 抛 `ImportError`/`RuntimeError`
  → 消息里包含原始错误与两条指引。

### 7.2 新增 `tests/test_console_mount.py`（用假 console 应用验证挂载语义）

构造一个「假 console 应用」：`FastAPI` + `/api/echo` + `/assets/x.js`（StaticFiles）+ SPA 兜底
（复用与 `console/app/core/spa.py` 同规则的 10 行实现），以 `ConsoleAttachment` 形式交给
`create_app(console=...)`，断言：

- `GET /api/echo` → 200（console 路由生效）；
- `GET /v1/pool` → 200 且来自 s2s 的假 pool 路由（**不被 console 抢**）；
- `GET /assets/x.js` → 200 且 `cache-control` 含 `immutable`；
- `GET /console/params` → 200 `index.html`；`GET /main.js` → 404；
- `GET /` → 200 `index.html`；
- WebSocket `/v1/realtime` 仍可完成握手（TestClient 的 websocket_connect，使用既有假协议）；
- console 的 lifespan **确实执行**：attachment 的 lifespan 里置一个 `Event`，TestClient 进入上下文后为真。

### 7.3 追加 `tests/test_cli_defaults.py`

- `serve --with-console --help`：参数与环境变量出现在 help 里；
- `talk --with-console`：`parser.error`；
- 剥掉开关后 `run_pipeline_command` 收到的 argv 不含它（monkeypatch 入口拦截）；
- `RealtimeServer.startup_failed`：monkeypatch `uvicorn.Server.run` 直接返回（`started` 保持 False）
  → `run()` 结束后标记为真、`stop_event` 已置位。

### 7.4 可选的「真集成」测试（`@pytest.mark.skipif`）

`skipif` 条件：`importlib.util.find_spec("loguru") is None`。
临时目录准备 `STATIC_DIR/index.html` 与 `.env`（含 `JWT_SECRET_KEY`），`load_console()` 真导入，
断言 `GET /api/config` 200 且含 `pipeline` 键、`GET /` 200 `text/html`。默认 CI 不满足依赖即跳过。

### 7.5 回归

`pytest tests/ -q`、`ruff check .` 全绿；`console/frontend` 不改，仍跑一次 `npm run test`（95 条）。
`console/backend` 不改，但仍跑一次其全量 pytest（232 条）确认零影响。

## 8. 手工验证（pwsh 7，`curl.exe` 避开 `curl` 别名）

```powershell
cd d:\work\qwen-audio-agent\speech-to-speech-src
cd console\frontend; npm run build; cd ..\..

# 组合 A：开（整合）
speech-to-speech serve -f config/prod.yaml --name prod --with-console
#   期望首行：console: integrated=true | http://127.0.0.1:8765  ui=/ console=/console api=/api …
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/            # 200（console index.html）
curl.exe -s http://127.0.0.1:8765/ | Select-String "<title>S2S"          # 命中
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/console/params  # 200（SPA 回退）
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/main.js     # 404（带后缀不吞）
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/api/config  # 200（同进程 console API）
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/v1/pool     # 200（s2s 自己的路由）
curl.exe -s "http://127.0.0.1:8765/api/v1/health"                        # {"status":"ok",…}
#   注意：/api/v1/health 要摸 DB。若返回 503，说明 <home>/.env 的 DATABASE_URL 指错了地方
#   （容器默认值是 sqlite:////app/data/console.sqlite3）。这是 console 的既有语义，不是本次改动。
Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue  # 无输出：8000 未监听
@'
import asyncio, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8765/v1/realtime", max_size=None) as ws:
        print((await ws.recv())[:120])   # session.created
asyncio.run(main())
'@ | python -

# 组合 B：关（现状）
speech-to-speech serve -f config/prod.yaml --name prod
#   期望：console: integrated=false；GET / = 404；GET /api/config = 404；GET /v1/pool = 200

# 失败注入 1：console 依赖/配置缺失 → exit 2，且未开始加载模型
$env:CONSOLE_AUTOSTART="true"; Remove-Item Env:JWT_SECRET_KEY -ErrorAction SilentlyContinue
speech-to-speech serve -f config/prod.yaml --name prod   # 期望 exit 2，消息指明 JWT_SECRET_KEY
$LASTEXITCODE

# 失败注入 2：dist 缺失 → exit 2
$env:CONSOLE_STATIC_DIR="C:\nope"; speech-to-speech serve -f config/prod.yaml --name prod

# 失败注入 3：端口被占 → exit 1（§5.3）
python -m http.server 8765        # 另一个终端
speech-to-speech serve -f config/prod.yaml --name prod --with-console
$LASTEXITCODE                     # 期望 1，日志有 startup_failed / bind 错误
```

## 9. 非目标

- 不再有 console 子进程、健康探活、看门狗、回收流程（单进程后都不需要）。
- 不做 `/api/*` 反代、不做第二个端口的静态托管（同进程直接路由）。
- 不自动生成 `JWT_SECRET_KEY`、不自动迁移数据库（仍按 `docs/console-service.md` 准备）。
- 不改 `supervisord.conf` / compose；容器形态仍是两进程。
- 不改前端构建与路由（`dist` 已适配根挂载）。
- 不为 `/docs`、`/openapi.json` 让路（见 §10）。

## 10. 风险与限制

| 风险 | 处理 |
|---|---|
| `app` 是最常见包名，`sys.path.insert(0, home)` 可能命中同名第三方包 | import 后校验 `app.main.__file__` 位于 `home` 之下，否则 `ConsoleImportError` 明确报「包名冲突」 |
| 预载 `.env` 会污染进程环境 | 只用 `os.environ.setdefault`（真实 env 优先），且仅在开关打开时执行 |
| `PIPELINE_BASE_URL` / `STATIC_DIR` 被覆盖 | 覆盖是有意的（探自己、挂同一份 dist）；与原值不同时打 WARNING |
| `app/main.py` 导入时 `configure_logging()` 会配置 loguru | 与 s2s 的 stdlib logging 并存；若日志重复/丢失，README 记录 `CONSOLE_*` 的 log level 变量调节 |
| `/docs`、`/redoc`、`/openapi.json` 仍由 s2s 提供，不会被 console 的 SPA 接管 | 文档写明；`/docs` 不是 console 路由，无实际冲突 |
| console 的三条 `/v1/*` 代理路由在本模式下不可达 | 文档写明「整合模式下 console 不再反代 pipeline」 |
| 真集成测试需要 console 依赖 | 默认 `skipif`；靠 §7.1/§7.2 的假模块与假应用覆盖语义 |
| console 的 `RESTART_MODE=supervisor` 在整合模式下仍无 supervisor | 与本机现状一致：发布/重启会 60s 后 `restart_unavailable`；README 注明用 `RESTART_MODE=noop` 并靠重启进程生效 |

## 11. 验收清单

- [ ] `speech-to-speech --help`、`serve --help`、`local --help` 出现 `--with-console` 与 `CONSOLE_AUTOSTART`/`CONSOLE_HOME`/`CONSOLE_STATIC_DIR` 及默认值。
- [ ] 组合 A：日志首行 `integrated=true` 且地址是 s2s 的地址；`/` 200 且是 console `index.html`；`/console/params` 200；`/assets/index-*.js` 200 且 immutable；`/main.js` 404；`/api/config` 200；`/api/v1/health` 200；`/v1/pool` 200；WS `/v1/realtime` 收到 `session.created`；**8000 端口无监听**。
- [ ] 组合 A 的 console 后台任务真的在跑：日志里能看到 bootstrap/indexer 的既有输出；`GET /api/v1/instances` 返回 `200` 且 `pipeline` 指向自身。
- [ ] 组合 B：`integrated=false`；`/` 与 `/api/config` 均 404；`/v1/pool` 200；退出码语义与改造前一致。
- [ ] 缺 `JWT_SECRET_KEY` 且开开关 → exit 2，消息可操作，且在模型加载前返回。
- [ ] 缺 dist 且开开关 → exit 2，提示 `npm run build`。
- [ ] 8765 被占用 → exit 1，日志有 bind 错误/`startup_failed`。
- [ ] `pytest tests/ -q`、`ruff check .` 全绿；console 后端 232 条、前端 95 条仍全绿。
