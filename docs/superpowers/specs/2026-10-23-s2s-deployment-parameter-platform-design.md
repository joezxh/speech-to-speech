# S2S 部署参数配置平台设计文档

> 日期：2026-10-23 ｜ 状态：待评审
> 修订：2026-10-24 —— 部署参数控制台改为 `console/` 工程（`frontend` + `backend` 两个子项目），与 pipeline **同镜像同容器**部署；控制台完整承接 `demo/` 的前后端能力
> 工作目录：`speech-to-speech-src/`
> 配套交付：`docs/parameter-catalog.md`（人读清单）、`docs/parameter-catalog.yaml`（机器可读目录，schema `s2s-parameter-catalog-v1`）、`console/`（控制台工程，随 s2s 镜像一起发布）
> 边界：**只做设计**。不写平台代码，不改 `speech-to-speech-src` 源码；下文所有"源码改动点"均为设计标注，实施阶段才落地。
> 技术选型参照：`D:\projects\MinWorkBuddy`（仅作技术栈参考，不修改该项目，不复制其业务代码）

## 1. 背景与目标

### 1.1 要解决的问题

当前 S2S 服务的全部业务参数都以两种方式硬编码在部署物里：

1. `docker-compose.yml` 的 `command:` 数组里散落 40+ 个 CLI 开关（`--min_silence_ms 700`、`--qwen3_tts_streaming_chunk_size 4` …）；
2. 少量环境变量（`HF_HUB_OFFLINE`、`GPUSTACK_API_KEY`）靠 `${VAR:-default}` 替换。

带来四个具体痛点：

| 痛点 | 现状证据 | 后果 |
|---|---|---|
| 改参必须手工编辑 compose | `docker-compose.yml:44-101` 全是字面量 | 无审计、无回滚、误改靠 git diff 兜底 |
| 参数含义无单一来源 | 196 个可配字段分散在 40+ 个 `arguments_classes/*.py` | 新人靠读源码猜默认值与合法范围 |
| 热更新能力不可见 | 仅 4 类字段真正可热更（见 §2.2） | 运营以为改 YAML 就能换人设，实际要重启 |
| 危险参数无分级 | `enable_llm_proxy`、`host`、`log_transcripts` 与 `thresh` 平铺在同一命令行 | 误开代理或明文落转写无人拦 |

### 1.2 目标

1. **单一参数目录**：196 条参数带 13 字段元数据与 `file:symbol` 溯源，人和机器可读（`parameter-catalog.{md,yaml}`）。
2. **分层覆盖**：`basic / advanced / expert / ops` 四级暴露，UI 按级别渲染，越界字段不可见。
3. **两条生效链路显式化**：重启链路（**容器内 pipeline 子进程重启**）与热更新链路（会话级 `session.update`），每条都有健康检查与回滚。
4. **配置版本不可变**：每次发布留版本快照与审计记录，回滚 = 指向上一个版本。
5. **控制台随 s2s 镜像一起交付**：`console/` 是仓库内的独立工程，内含 `frontend` 与 `backend` 两个可独立开发、构建、测试的子项目；**部署上与 pipeline 共用同一个镜像、同一个容器**（`supervisord` 管两个进程），对外只有 `:8000` 一个入口。
6. **完整承接既有演示能力**：`demo/` 的语音对话页与全部后端代理能力（搜索、WebRTC 信令、队列/用量、`/vendor/*` 资产）迁入 `console/`，对话页按新前端技术栈重写，不出现功能缺口。

### 1.3 非目标

- 不做多实例编排、K8s、灰度发布、跨机调度（单机 compose 是当前唯一部署形态）。
- 不做参数值的自动调优（A/B、自动寻参）。
- 不重写 `arguments_classes`，不改 `config.py` 的 YAML 语义。
- 本文给出 `console/` 的工程边界、目录结构、技术栈、接口契约与部署方式，但不含实现代码与逐字段 DDL；表结构在实施阶段由 Alembic 迁移落地。
- **不给控制台单独做镜像或单独开容器**。`console-frontend` / `console-backend` 只作为代码子项目存在，不是部署单元；也不引入 nginx 边车（静态资源由 `console/backend` 的 `StaticFiles` 直出）。
- **不让控制台在容器内驱动 docker**。链路 A 只重启容器内的 pipeline 子进程，不挂 `/var/run/docker.sock`，不执行 `docker compose`。
- 运维面（JWT）与演示面（HF OAuth / 匿名 cookie / 每日配额）是两套并存的**身份体系**，各自独立、互不代理；不把运维 JWT 复用到语音接口上，也不把演示侧的 tier 映射成运维角色。
- 不做前后端代码共享的 monorepo 工具链（不引入 pnpm/turbo workspace、不引入 Nx）；两个子项目用各自的包管理器与构建工具，靠 HTTP 契约协作。

### 1.4 术语

| 术语 | 含义 | 不再使用的旧说法 |
|---|---|---|
| **console 工程** | 仓库内 `console/` 目录，一个独立工程的根，含两个子项目，不参与 `speech_to_speech` wheel 打包 | 「控制台页面」「console.html」 |
| **console/frontend** | 前端子项目：Vue 3 + Vite 单 SPA 双布局，含运维台与语音对话页两块 | 「demo 前端」「ui/console」「index.html」 |
| **console/backend** | 后端子项目：FastAPI 单应用，一个进程同时服务运维面 `/api/v1/*`、演示面 `/api/*`、语音面 `/v1/*` 与前端静态资源；唯一有写权限的一方（写 `config/`、经 supervisor 重启 pipeline 子进程） | 「param_api」「server.py」「参数平台」 |
| **pipeline 子进程** | 容器内由 supervisor 托管的 `speech-to-speech serve` 进程，监听 `127.0.0.1:8765`；即被管理的对象 | 「pipeline 容器」「主服务」 |
| **链路 A（重启）** | 改 `config/<profile>.yaml` → `supervisorctl restart pipeline` → `127.0.0.1:8765/v1/pool` 探活 | 「重建容器」 |
| **链路 B（热更新）** | 对活跃会话下发 `session.update`，不重启进程 | 同左 |
| **运维面** | `/console/*` + `/api/v1/*`，JWT 鉴权，给运维人员用 | 「控制台」 |
| **演示面** | `/` + `/api/*`，匿名 cookie 或 HF OAuth，给语音演示的访问者用 | 「demo」 |
| **语音面** | `/v1/realtime*` 同源反代到 `127.0.0.1:8765`，供浏览器直连 WebSocket 与 WebRTC 信令 | 「s2sUrl」「直连」 |
| **profile** | 一份可发布的配置集合，形如 `prod`，对应 `config/prod.yaml` + `config/prod.env`（两文件生效方式不同，见 §4.2） | 同左 |
| **draft / version** | 草稿（唯一可变状态，patch 语义）/ 不可变版本快照（append-only） | 同左 |
| **recreate（容器重建）** | 由宿主执行 `docker compose up -d --force-recreate pipeline`；只有它能改变进程环境变量，控制台不代办 | 「重启」 |

## 2. 源码配置模型结论

### 2.1 两条独立通道

| 维度 | 通道 A：启动参数 | 通道 B：会话运行时 |
|---|---|---|
| 入口 | `cli.py`（`serve`/`talk`/`local`）+ `arguments_classes/*.py` 的 dataclass；文件模式 `-f/--file` + `--name` | `api/openai_realtime/runtime_config.py:RuntimeConfig` + WebSocket `session.update` 事件 |
| 载体 | CLI 参数，或 YAML（`schema_version: 1`） | OpenAI Realtime 协议 JSON |
| 解析/校验 | `config.py:load_config` → `validate_config` → `resolve_config` | `handlers/session.py:24-77 handle_session_update` → `RuntimeConfig.apply_session_update`（`runtime_config.py:102-105`） |
| 作用域 | 进程 / 容器 | 单条连接（`conn_id`） |
| 生效代价 | 重启 pipeline 子进程（秒级）；触及 `.env` 则必须重建容器（分钟级，§4.2） | 毫秒级，下一次 LLM/TTS 调用即读到新值 |
| 覆盖面 | 所有 pipeline、所有新老会话 | 仅被点名的连接 |

两条通道**互不知道对方存在**：`RuntimeConfig` 在 `service.py:407-422 register()` 里新建，只从 `self._default_instructions` 取一个字符串种子；启动参数里的 `init_chat_prompt` 通过 `s2s_pipeline.py:635 → 643` 传成 `default_instructions`。这是"改了 YAML 但当前通话没变"的根因。

YAML 模型的关键事实（`config.py:373-445`、`docs/configuration.md:99-134`）：

- 顶层只允许 `schema_version` / `runtime` / `blocks` / `pipelines` 四键，未知键报错；
- `schema_version` 必须是整数 `1`；
- `pipelines.<name>` 只允许 `stages` / `num_pipelines` / `options`，`device` 等进程级覆盖放 `options`；
- `{env: NAME}` 是**流式映射**而非字符串，只能放在标量位置；缺失变量**在 resolve 期报错**，不回退默认值；
- 单文件上限 1 MiB、容器层级上限 32，禁用 anchors/aliases/merge keys/explicit tags。

### 2.2 可热更新字段清单（附证据）

计划初判"7 类字段可热更新"。逐条取证后需要修正——真正改变行为的只有 4 类，另有 2 类是**协议兼容字段**：

| 字段路径 | 真实生效 | 证据 | 平台归类 |
|---|---|---|---|
| `instructions` | 是 | `base_openai_compatible_language_model.py:972-974`、`language_model.py:617-619`：`response.instructions or runtime_config.session.instructions` | 热更新 |
| `audio.input.turn_detection.create_response` | 是 | `runtime_config.py:59-68 create_response_enabled` | 热更新 |
| `audio.input.turn_detection.interrupt_response` | 是 | `runtime_config.py:70-88 interrupt_response_enabled`（缺省 `True`） | 热更新 |
| `audio.input.transcription.language` | 是，带校验 | `handlers/session.py:42-64`：`auto` 需 `stt_auto_reset_supported`，具体值须在 `stt_supported_languages` / `tts_supported_languages` 内；`runtime_config.py:107-115 selected_language` | 热更新 |
| `extensions` | 是 | `runtime_config.py:90-100`，目前只识别 `speech_to_speech.input_audio_transcription.snapshot` | 热更新（仅此一个取值） |
| `audio.output.voice` | **否，仅协议回显** | `handlers/response.py:519-525` 把 voice 回填进 `RealtimeResponse.audio.output.voice` 后返回给客户端；TTS 实际音色来自 `qwen3_tts_speaker` 启动参数 | 协议兼容，不进热更新面板 |
| `model` | **否，仅记日志** | `handlers/session.py:66-68` 只 `logger.info`，不触碰已加载的 LLM 后端 | 协议兼容，同上 |

合并语义（`runtime_config.py:10-24 _apply_update`）：只遍历 `update.model_fields_set`，即**只合并客户端真正发过的字段**，未发字段保持原值；嵌套 BaseModel 递归合并。因此部分更新安全，但"发 `null` 清空"和"不发"是两种语义，平台侧必须区分。

### 2.3 只能重启生效的边界

除上表 4 类字段外，其余全部需要重启 pipeline 子进程（其中少部分还连带需要重建容器，见 §4.2），包括常被误认为可热更的：

- `init_chat_prompt`（`s2s_pipeline.py:635`）：只作为**新连接**的 `instructions` 种子（`service.py:416`）。改它 = 重启 + 只影响后续新连接，老连接仍持旧人设。这是"半热"状态，平台必须把"改默认人设"拆成两个动作：热更新存量连接 + 重启改未来连接（见 §5.4）。
- `qwen3_tts_speaker`、`qwen3_tts_model_name`：TTS 引擎在启动时加载模型，会话层无法换。
- `num_pipelines`、`device`、`host`、`port`：属进程/容器拓扑。

### 2.4 `effect` 在平台侧的解释（7 条 `hot` + 7 条 `both`）

`parameter-catalog.yaml` 的 `effect` 说的是“源码里有几条写入口”，不是“控制台能改几条”。平台必须按 §2.2 的取证再落一档，否则会出现「界面写着热更新、改完一点用没有」：

| catalog `effect` | 条数 | 字段 | `EffectBadge` 徽标 | 实际链路 |
|---|---|---|---|---|
| `hot` | 5 | `session.instructions`、`session.audio.input.turn_detection.create_response`、`session.audio.input.turn_detection.interrupt_response`、`session.audio.input.transcription.language`、`session.extensions` | `热更新` | A.9 → A.12，只影响活跃连接（§5.4） |
| `hot` | 2 | `client.instructions`、`client.voice` | `不可配置` | 属对话页浏览器侧 CLI（`api/openai_realtime/audio_client.py`），服务端没有入口 |
| `both` | 3 | `init_chat_prompt`、`qwen3_asr_language`、`qwen3_tts_language` | `启动 + 热更` | 两个动作都要做：写 YAML + 重启（管未来连接）／`session.update`（管存量连接） |
| `both` | 3 | `qwen3_tts_speaker`、`kokoro_voice`、`openai_tts_voice` | `启动`（小字 `catalog: both`） | 会话层的 `audio.output.voice` 只是协议回显（§2.2 第 6 行），不换引擎；这三项**不进**热更新面板 |
| `both` | 1 | `client/model` | `不可配置` | 同 `client.*` |
| `startup` | 182 | 其余全部 | `启动` | A.2–A.6；`stage=env` 的 18 条在 publish 前置门禁就 `409 env_requires_recreate`（§4.1 步骤 5） |

徽标只允许三个取值：`启动` / `热更新` / `启动 + 热更`。**不得**直接把 catalog 的 `startup|hot|both` 原文当标签用——原文只在字段详情里以 `catalog: both` 小字出现，并链到本节。这样“catalog 说什么”与“平台怎么做”两条信息都在，但不会互相冒充。

## 3. 平台架构

平台由**两个代码子项目 + 一个部署单元**构成：`console/frontend`（视图层）、`console/backend`（控制与持久化层），两者与 `speech-to-speech serve` **打进同一个镜像、跑在同一个容器的两个进程里**，由 `supervisord` 托管。本节先给拓扑与职责，再给工程结构与技术栈，最后给组件图与依赖方向。

### 3.1 部署拓扑

```
浏览器（访问者 / 运维人员）
  │  http(s)://<host>:8000   同源：页面 + /api/v1/* + /api/* + /vendor/* + /v1/realtime(WS/SDP)
  ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ s2s 容器（根 Dockerfile 扩 Stages，compose 服务名仍为 pipeline）             │
│  supervisord（PID 1，unix socket /run/s2s-console/supervisor.sock）         │
│   ├─ [console] uvicorn app.main:app  0.0.0.0:8000                          │
│   │    /console/*     运维台 SPA（Vite dist，登录守卫）                      │
│   │    /              对话页 SPA（同一 dist，另一条路由）                    │
│   │    /api/v1/*      运维面（JWT）                                         │
│   │    /api/*         演示面（匿名 cookie / HF OAuth，条件启用）             │
│   │    /vendor/*      构建期烤入的 Agents SDK UMD + VAD 资产                 │
│   │    /v1/realtime*  反代（WebSocket + SDP）→ 127.0.0.1:8765               │
│   └─ [pipeline] speech-to-speech serve -f /app/config/prod.yaml --name prod │
│                 监听 127.0.0.1:8765（**不 publish**）                        │
└───────────────────────────────────────────────────────────────────────────┘
   │ /app/config（容器内可写，唯一写入方是 console 进程）
   │ /app/data  （命名卷：console.sqlite3 / usage.sqlite3）
   ▼
宿主：docker compose up -d --force-recreate pipeline
      —— 只有这一步能改容器环境变量（env_file），由人或部署脚本执行，控制台不代办
```

| 部署单元 | 镜像来源 | 端口 | 网络暴露 | 生命周期 |
|---|---|---|---|---|
| **s2s 容器**（compose 服务 `pipeline`） | 根 `Dockerfile`（新增 `node:20-alpine` 前端构建阶段 + 拷入 `console/backend`） | `8000`（对外）、`8765`（仅 `127.0.0.1`） | 唯一对外入口 `8000` | `compose up -d` 创建；**发布只重启内部 pipeline 子进程**，容器不动 |
| `postgres`（可选 profile `pg`） | `postgres:16` | 5432 | 不映射宿主机 | 独立数据卷；默认不启用（用 SQLite） |
| `llama-server`（既有，可选） | 现有 compose 服务 | 8080 | 按现有配置 | 不变 |

容器内两个托管进程：

| program | 命令 | 监听 | 重启影响面 |
|---|---|---|---|
| `console` | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | `0.0.0.0:8000` | 页面与全部 API 短暂不可用（发布链路 A **不会**触发它） |
| `pipeline` | `speech-to-speech serve -f /app/config/prod.yaml --name prod` | `127.0.0.1:8765` | 所有活跃语音会话中断（这是链路 A 的设计代价，UI 必须预告） |

部署约定（与上一版逐条相反，逐条给出理由）：

- **一个镜像**：`console/frontend` 的 `dist/` 与 `console/backend/` 在构建期烤进 s2s 镜像，运行期不需要 node、不需要 `node_modules`（§3.4.3 D10）。
- **一个容器**：`docker-compose.yml` 里没有 `console-frontend`（nginx）也没有 `console-backend`；两个代码子项目不是部署单元。
- **一个对外端口**：只有 `8000`。`8765` 绑 `127.0.0.1` 且不 publish，浏览器经 `/v1/realtime` 反代访问。代价是多一跳回环（<1ms），换来单一入口、无需 CORS、无需给 pipeline 单独开防火墙（§12 R19）。
- **无 CORS**：页面与所有 API 同源同端口；`CORS_ORIGINS` 只用于开发态 `vite dev` 直连调试（§10.2）。
- **无 docker.sock**：链路 A 用 supervisor 的 unix socket 重启 `pipeline` 子进程，不需要 docker CLI；权限面从「宿主 root 等价」降到「只能重启两个受管进程」（§10.3）。
- **console 进程必须单 worker**：发布单飞依赖进程内锁（§4.1），多 worker 会各持一把锁；`supervisord` 的 `console` program 不传 `--workers`。
- **同容器共享资源配额**：pipeline 是重负载（torch + 模型），console 必须设 CPU/内存上限，否则会与语音抢核（§12 R18）。

### 3.2 组件职责

职责按子项目分两张表。**前端不接触 docker、不接触 `config/` 文件、不持有任何写权限**；**后端不产出 HTML 片段、不做前端路由**（但它确实用 `StaticFiles` 把构建好的 `dist/` 发出去，这是静态托管，不是服务端渲染）。

前端有两块：**运维台**（`/console/*`）与**对话页**（`/`）。两者共用一个 Vite 构建产物，路由级 `import()` 让两个面的**页面代码**互不进对方的 chunk。但 **`ant-design-vue` 是全局的，不分叉**：`main.ts` 里 `app.use(Antd)`，`App.vue` 用 `<a-config-provider :theme="themeConfig">` 包住 `<router-view />`。

这不是随便选的：暗色主题必须由最外层一次接管，否则被 `teleport` 到 `body` 的 `a-modal` / `a-select` 弹层拿不到 `theme.darkAlgorithm`，会以 `ant-design-vue/dist/reset.css` 的**亮色**基线贴在 `#0b1020` 上——按钮、输入框、表格、弹窗全是刺眼白块（§3.4.4）。所以「对话页首屏不背 antd」是**主动放弃**的目标：多背一个组件库，换一个不会在弹层上翻车的暗色基线，对内部运维工具这笔交换划算。真正必须留在 `/vendor` 之外、绝不能进 bundle 的是语音 SDK（§3.4.3 D10）——那才是会把两套 SDK 实例塞进同一个 `globalThis` 的隐患。

#### 3.2.1 `console/frontend` 运维台（视图层）

| 组件 | 职责 | 数据来源 | 明确不做 |
|---|---|---|---|
| `views/LoginView.vue` | 账号密码登录，写 token 与用户信息 | `POST /api/v1/auth/login` | 不存密码、不做注册 |
| `layouts/ConsoleLayout.vue` | 顶栏（profile 选择、连接状态、当前用户、退出）+ 侧边导航 | `GET /api/v1/status` | 不做业务逻辑 |
| `views/ParamsView.vue` | 左树右表单：按 `exposure` 分组渲染 catalog，右侧编辑 draft patch，展示校验结果 | `GET /api/v1/catalog`、`GET / POST /api/v1/profiles/{id}/draft` | 不在前端判定字段合法性（只做类型/范围提示） |
| `views/SessionsView.vue` | 链路 B：只呈现 §2.2 的 4 类可热更字段，服务端错误码翻译成人话 | `POST /api/v1/sessions/update` | 不提供 `model` / `audio.output.voice`（§2.2 判定无效） |
| `views/VersionsView.vue` | append-only 版本列表 + 回滚（回滚写新版本） | `GET /api/v1/profiles/{id}/versions`、`POST .../rollback` | 不删除历史版本 |
| `views/InstancesView.vue` | 容器状态 + `/v1/pool` 真实 unit 表 + 用量段 | `GET /api/v1/instances`（轮询） | 不直连 pipeline |
| `views/AuditView.vue` | 审计表：操作人、版本、结果、耗时、字段名 | `GET /api/v1/profiles/{id}/audit` | 不展示密钥值 |
| `components/ParamField.vue`、`SecretField.vue` | 单个字段控件；密钥类只写不读（回显 `***`） | props | 不把密钥写进 `localStorage` / 日志 |
| `components/DiffTable.vue`、`ExposureTag.vue` | 字段 diff、暴露级别标签 | props | 不计算 diff（后端给） |
| `api/*.ts` | 每个后端资源一个模块，统一走 `api/client.ts` 的 axios 实例 | — | 不在组件里裸调 axios |
| `stores/{auth,catalog,draft,console}.ts` | Pinia：登录态、catalog 缓存、draft 脏标记、profile 上下文 | `api/*` | 不缓存密钥明文 |
| `router/index.ts` | 路由与登录守卫（无 token → `/console/login`） | `stores/auth` | 不做权限树 |

#### 3.2.2 `console/frontend` 对话页（语音能力，迁自 `demo/`）

对话页的组件清单**按 `demo/index.html` 的 DOM 节点逐个点名**：十四个展示组件，每一个都能指回旧页的一个 id 或 class。漏一块就是功能缺失，多一块就是凭空发明。

对话页**没有自己的 `VoiceLayout.vue`**，但它**也不是一条全屏独立路由**：`/`（name `voice`）是 `ConsoleLayout.vue` 的子路由，`meta.face='voice'`，与 `/console/*` 共用同一套顶栏、侧栏与路由外壳；`VoiceView.vue` 只负责 content 区里的舞台（§3.2.4）。旧稿“对话页没有侧栏，也不复用运维台顶栏与侧栏”的表述**已作废**——那是把迁移过来的功能页面当成第二个应用；实际部署形态是**一个应用、一套外壳、两个面**。

| 组件 | 对应 demo | 职责 | 明确不做 |
|---|---|---|---|
| `views/VoiceView.vue` | `index.html` 的 `.orb-wrap` 舞台部分 | 渲染在 `ConsoleLayout` 的 content 里：identity 头部、球体舞台、气泡、相机 PiP、页脚、五个浮层；持有 `bubbles`、设备列表、四个弹窗与抽屉的开关这类页面局部状态；用 `<Teleport to="#shell-actions">` 把账号 chip（`AccountWidget`）与工具 / 历史 / 设置三枚按钮挂到外壳顶栏（About 圆钮随 `IdentityBlock` 留在舞台） | 不放样式（全在 `styles/voice.less`）、不直连 WebSocket、不读 `localStorage`、不重复画一套顶栏与侧栏（外壳归 `ConsoleLayout`） |
| `components/IdentityBlock.vue` | `.ident` | `Hugging Face Realtime` 外链、About 圆钮、blurb、`Powered by` / `Built by` 两行鸣谢 | 不联网、不读 `/api/config`（全是构建期常量） |
| `components/AccountWidget.vue` | `#account` + `ui/account.js` | chip 只有 avatar + handle（`pro` / `org` 多一枚 `PRO` / `TEAM` 徽章）；点开 popover 才是 tier / `m:ss left today`（unlimited 显示 `Unlimited`）/ Upgrade PRO / Sign out；未登录且 `loginUrl` 存在时 chip 整个换成 `Sign in` 胶囊 | 不存 HF token（B5）；`/api/me` 返回 `enabled:false` 时整块不渲染 |
| `components/OrbStage.vue` | `.orb-wrap` + `#main-circle` + `#circle-caption` / `#circle-subcaption` | 四层球体（glow / ring / ring-outer / core）+ 六个指示器（mic / error / spinner / dots / bars / voice）；**九态原样透传到 `data-state`，配色全在 CSS 的 `--glow`** | 不持有文案（`caption` / `subCaption` 由 `VoiceView` 决定）；不自己算会话状态；没有“三态降维” |
| `components/MicGate.vue` | `#mic-gate`（`#mic-btn` + `#mic-gate-arc`） | 52px 圆形静音钮 + 80px 200° 噪声门弧：拖拽改门限、弧按实时电平逐段点亮 | 不在主线程做 VAD；不显示授权失败文案（那属于 `caption`） |
| `components/BubbleStack.vue` | `#bubble-stack` | 右上角临时气泡：`user` / `tool` / `assistant` 三种来源，最多四条自动消失 | 不做持久化、不当转写用（正文归历史抽屉） |
| `components/TranscriptList.vue` | `#chat-history` | 三种条目（user / tool / assistant，双色、临时条目半透明）+ 仅在用户已贴底时自动跟随；user 条目在文字下方挂 `AudioReplay`，tool 条目挂可展开的 `Input` / `Output` 与 `Snapshot` 图 | 不把转写写回服务端；不自己解码 PCM（那是 `audio/sent-audio.ts`） |
| `components/AudioReplay.vue` | `ui/chat.js:onUserAudio` 的 `.hist-audio` | 标签 `Audio sent to the model`（截断时 `· beginning unavailable`）+ `<audio controls preload="metadata" aria-label="Replay your audio">`；点播放时暂停其它条目并回调 `true`，`pause` / `ended` / `error` 回调 `false` | 不持有 Blob（由 store 给的 objectURL 播放）、不做波形、不尝试补齐已经滚出缓冲的开头 |
| `components/HistoryDrawer.vue` | `#chat-panel` | 右侧 380px 会话历史抽屉（标题 / 关闭 / 条目数 / 空态文案），承载 `TranscriptList` | 不做搜索、导出、删除 |
| `components/CameraPip.vue` | `#cam-pip` / `#cam-video` / `.cam-flash` / `.cam-label` | 相机开启时的左下自视窗；`defineExpose({ video, flash })`，`snapshot()` 读的就是它的 `<video>` | 不自己求权限（由 `VoiceView.startCamera()` 开）；不在组件内上传 |
| `components/TurnTimings.vue` | `ui/chat.js:636-678` 的 `_appendTimings`（`details.hist-timings`） | 助手条目里的可折叠计时块：`<summary>` 写 `Server timings`（`e2e_s` 为空）或 `Server timings · E2E 6.26 s`（v2）或 `· First audio 6.26 s`（v1）；`p.timing-status` 四态 `Completed` / `Interrupted` / `Failed` / `Incomplete`；`<dl>` 七行——`E2E time`（v1 为 `VAD handoff to first audio`）/ `VAD end decision` / `Smart Turn decision` / `Transcription` / `Response generation` / `Voice synthesis to first audio` / `Hold time before response`；末尾一个 `<p>` 是口径说明（`Stages overlap and do not add up.`）；同一 response 再来一次时替换旧节点而不是追加 | 不做舞台 chip 行（`demo/index.html` 与 `main.js` 里**没有任何 latency 节点**，所有计时只在历史条目里）、不累加各段、不把 `null` 显示成 `0.00 s`（一律 `Unavailable`）、不自己校验 metadata（归 `transport/turn-latency.ts` 的 `readTurnLatency()`，本组件只格式化） |
| `components/ToolsDialog.vue` | `#tools-modal` | Web search 开关 + Serper key + Camera 开关 + 三条 hint；搜索仍走服务端 `/api/search` | 不回显服务端密钥；用户自带 key 只进内存（B5） |
| `components/SettingsDialog.vue` | `#settings-modal` | **十个字段一个不少**：server URL（只读）、Transport、Voice（9 项）、Microphone、Speakers、Faster interruptions、Playback startup buffer、Noise gate、Instructions、Restart + Save | 不做第二个状态容器（每次打开从 store 重取）；不提供 `model` 写入口（§2.2） |
| `components/AboutDialog.vue` | `#about-modal` | 项目简介 + 四段 pipeline（VAD / STT / VLM / TTS，各带模型外链）+ 版本 | 不联网拉模型卡 |
| `components/LimitDialog.vue` | `#limit-modal` | 额度耗尽卡片：HF 徽章、标题、正文、CTA、note | 不算额度（数字来自 `/api/me`） |
| `components/QueueOverlay.vue` | `#queue-actions` / `#join-queue-btn` / `#leave-queue-btn` | 球体下方的一行动作：排队位次 / `your-turn` 的 Join now 倒计时 / 满员提示 / Leave queue | 不估算等待时长（只展示位置，见 CONTEXT 术语）；无 LB 时不出现 |
| `features/voice/tools/camera.ts` | `main.js` 的相机采集 | `getUserMedia` + `canvas` 抽帧 → data URL | 不自己决定何时发（由工具调用触发） |
| `stores/voice.ts` | — | `state / entries / grant / queue / me / config / latency / settings` 与 `connect() / stop() / restart()`；**设置是唯一持久化的东西（`localStorage`），会话不落地**；`entries[].audio` 只存 `objectURL + durationMs + truncated`，`clear()` 逐个 `revokeObjectURL` | 不碰 DOM、不写 UI 文案、不把 Blob 或 objectURL 写进任何 storage |
| `features/voice/transport/s2s-client.ts` | `s2s-realtime-client.js` | OpenAI Realtime 协议客户端（WebSocket 与 WebRTC 两路）；**仅 WebSocket 传输**在 `input_audio_buffer.speech_started` / `speech_stopped` 上驱动 `SentAudioRecorder`，并在 `speech_stopped` 时 emit `user-audio` | 不读环境变量、不拼绝对地址；WebRTC 下不伪造回放（demo 的 recorder 只挂在 WS 上） |
| `features/voice/transport/agents-sdk.ts` | `main.js` 的 `sdk()` | 动态 `import('/vendor/openai-realtime-agents.umd.js')` 并给 typed shim 与单次加载缓存 | 不把 UMD 打进 bundle（§3.4.3 D10） |
| `features/voice/audio/*` | `main.js` 的电平与门限 / `worklets/*` | AudioWorklet 加载与播放队列、本地 VAD（`@ricky0123/vad-web`）、电平与门限（`meter.ts`） | 不在主线程解码或重采样 |
| `features/voice/audio/sent-audio.ts` | `ws/user-audio-recorder.js`（198 行，逐行移植） | `USER_AUDIO_SAMPLE_RATE=24000`、`DEFAULT_PREROLL_MS=5000`、`DEFAULT_MAX_BUFFER_MS=120000` 三个常量 + `pcm16ToWavBlob()` + `SentAudioRecorder`（`append` / `speechStarted` / `speechStopped` / `reset`，同 item 重开段做拼接，`truncated` 标记开头已滚出缓冲） | 不改采样率、不重采样、不上传音频；缓冲只有上限没有落盘 |

> 旧 demo 里还有两个不属于任何组件的节点：`#stop-btn`（52px 结束钮）与 `footer`（`Powered by huggingface/speech-to-speech`）。它们各自只有一行模板，直接写在 `VoiceView` 的 `.v-orb-wrap` 与 `.v-foot` 里，**不单独立组件**——为一行 `<button>` 建一个文件只会让“这一块归谁”变得难查。

**助手条目没有音频，这是 demo 的事实，不是遗漏**：`ui/chat.js` 只给用户条目挂 `.hist-audio`，助手条目是文本 + `Server timings`（`response-finished` 的 `timings`）。这份计时全部由**服务端**测（`TurnLatencyTracker.metadata_payload()`），客户端只做校验与格式化：`readTurnLatency()`（`features/voice/transport/turn-latency.ts`）→ `useTurnLatency.ts` 的五个展示纯函数（`formatSeconds` / `timingSummary` / `statusLabel` / `timingRows` / `timingNote`，本文件只 re-export 前者、不重复校验）→ `TurnTimings.vue`（§14.5 第 15 行）。计时**挂在对应那条助手条目上**（`store.attachLatency()` 只写最后一条助手条目，`TranscriptEntry.latency`），不存一份“最新值”——否则历史抽屉里除最后一句之外全部没有数字。

**“有音频的条目”= 用户条目**。`s2s-realtime-client.js:577-604` 在 `transport === 'websocket'` 时把 `speech_started` / `speech_stopped` 的 `item_id` 交给 `SentAudioRecorder`，`speech_stopped` 返回 `{itemId, audio: Blob, durationMs, truncated}` 并派发 `user-audio`；`main.js:372-406` 收到 `onUserAudioPlaybackChange(true)` 就把麦克风轨道 `enabled=false` 并 `client.setMuted(true)`，防止用扬声器回放时把刚放出来的原音再录回去。三段（缓冲 → WAV → 控件）在 Vue 侧一一对应 `audio/sent-audio.ts` → `TranscriptList` → `AudioReplay`，缺一段就等于丢掉回放。

#### 3.2.3 `console/backend`（服务层）

| 组件 | 职责 | 输入 | 输出 | 明确不做 |
|---|---|---|---|---|
| `routers/*` | 薄 HTTP 层：解析、鉴权、调一个流程函数、整形响应 | HTTP 请求 | `ApiResponse` | 不写业务分支（发布八步只能在 `services/publish_flow.py` 里） |
| `services/catalog_service.py` | 加载 `parameter-catalog.yaml`，按 `exposure`/`stage`/`backend` 过滤 | catalog 文件 | 字段列表 | 不校验用户值、不持久化 |
| `services/layout_service.py` | catalog 条目 → `config/<profile>.yaml` 真实路径（catalog 的 `stage` 只是文档分组） | catalog 条目 + YAML 文档 | 路径 / 错误 | 不读写盘 |
| `services/renderer_service.py` | draft + 现有 YAML → 新 YAML 文本与 `.env` 文本；旧文件备份为 `.bak.<version>` | 已校验 draft | 文本 + 备份 | 不做健康检查 |
| `services/validator_service.py` | 调 `speech_to_speech.config` 的 `load/validate/resolve`；再做显存预算与跨字段约束。包不可用时降级为结构校验并**显式上报 `mode=structural`** | YAML 文本 | 错误列表 / `ResolvedConfig` | 不写盘、不调 docker、不重新实现默认值 |
| `services/publish_flow.py` | 链路 A 步骤 1–9 的唯一编排点（顺序即设计） | 已校验 draft | 版本 + 状态 | 不直接操作 HTTP |
| `services/restart_runner.py` | 调 `supervisor_client` 重启 `pipeline` 子进程、`/v1/pool` 探活、回滚重启 | 版本号 | 实例状态 / 命令结果 | 不拼 shell 命令、不读 compose 文件 |
| `services/supervisor_client.py` | XML-RPC（unix socket）调 `stopProcess` / `startProcess`，返回退出码与耗时 | 版本号 | 进程状态 | 只允许目标 `pipeline`，program 名不从请求推导 |
| `services/realtime_proxy.py` | `/v1/realtime`（WebSocket）与 `/v1/realtime/calls`（SDP）反代到 `127.0.0.1:8765` | 浏览器 | 流式转发 | 不做协议改写、不复用服务端会话状态 |
| `services/demo_config_service.py` | 组装 `/api/config` 的引导字段 | 环境变量 + 请求 Host | `{search, lb, allowDirect, s2sUrl, rtc, iceServers, startupGreeting}` | 不回传 `LOAD_BALANCER_URL` 本身或任何密钥 |
| `services/identity_service.py` | 匿名 cookie、HF OAuth（`attach`/`resolve_identity`/`resolve_tier`）、登录门禁 | `huggingface_hub[oauth]` + `authlib` | tier / 身份视图 / `Set-Cookie` | 条件启用；未配置时全部降为 `enabled:false` / 404 |
| `services/metering_service.py` | 每日配额：`begin`/`heartbeat`/`end`/`sweep`、`take_search`、`session_live` | 裸 `sqlite3` 连接 | `remainingSec` / `expired` / 位次 | 与参数库分开，不共用 SQLAlchemy 会话（§3.4.3 D11） |
| `services/search_proxy.py` | Serper 调用 + 服务端密钥门禁（签名用户 + 活跃会话 + 每日上限） | 查询串 / 会话 id | Serper 原始结果 | 不接受客户端指定目标 URL（防 SSRF） |
| `services/asset_service.py` | `/vendor/*` 与 SPA 静态资源（`dist/`）发布，SPA 回退 | 请求路径 | 文件流 | 不读 `node_modules`、不列目录 |
| `services/hot_update.py` | 链路 B：只放行 §2.2 的 4 类字段，转发 pipeline `/internal/sessions/update` | 会话补丁 | `updated[] / failed[]` | 不复制 `handle_session_update` 的校验 |
| `services/auth_service.py` | bcrypt 校验密码、签/验 JWT（`sub`+`exp`）、角色判定 | 账号密码 / token | token / 当前用户 | 不做租户、不做菜单权限 |
| `services/audit_service.py` | 每次 draft/publish/rollback 落审计，附 `auditId` | 调用上下文 | 审计行 | 不改写业务结果 |
| `services/runtime_service.py` | 四段模型（VAD / STT / LLM / TTS）的运行时快照：模型名与后端、加载状态、显存、繁忙、延迟 | `config/<profile>.yaml` 的解析值 + `process_probe` + `pool.read_pool()` + `nvidia-smi` + `model_metrics.log` | `{profile, collectedAt, gpu, stages[]}` | 不跑推理、不改配置、不重启进程；采不到就回 `available:false + reason`，不算 0 |
| `services/log_service.py` | 读 `/var/log/supervisor/{console,pipeline}-{stdout,stderr}.log` 的尾部，按 cursor 增量返回并做过滤 | `?process&level&from&to&q&after&limit` | `{lines[], nextCursor, truncated, sources[]}` | 不写、不删、不轮转日志；单次读有字节上限，过滤在读取后内存里做 |
| `services/log_analysis_service.py` | 把选定窗口的日志脱敏、去重、截断后交 LLM，返回四块结构化结果 | 已过滤的日志行 + 时间窗 | `{result, sent, model, durationMs}` | 不改配置、不回写参数库、不记密钥；超时/限流/失败都返回稳定错误码，原始日志由前端保留 |
| `repositories/*` | SQLAlchemy 访问：draft / version / audit / user | ORM 会话 | 模型对象 | 不含业务规则 |
| `models/*` | 4 张表：`param_user`、`param_draft`、`param_version`、`param_audit` | — | — | 不建业务表、不做软删除 |
| `middleware/*` | `request_id`、审计路由类、异常 → 统一错误体 | 请求 | 响应 | 不改写成功响应 |
| `core/security.py` | JWT 编解码、`require_admin` / `require_operator` 依赖 | header | 当前用户 | 不接触数据库以外状态 |

两条既有约束在此仍然成立，其中一条换了对象：**所有写盘与调 supervisor 的代码只在 `services/` 下**，`routers/` 只做整形；**`validator_service` 是唯一 import `speech_to_speech` 的模块**，其余模块只依赖 catalog、文件系统、数据库与 HTTP。

监控与日志分析**不新增第五条例外**：`runtime_service` 不 import `speech_to_speech`，它读的是已解析的 YAML、`model_metrics.log` 的 JSONL、回环 HTTP 与 `nvidia-smi` 的文本输出；`log_analysis_service` 只发一次回环 `POST /v1/chat/completions`（`services/llm_proxy` 那条透传面），不引入新的模型客户端依赖。

#### 3.2.4 对话页的嵌入形态（`/` 是 `ConsoleLayout` 的子路由）

迁移过来的功能页面必须服从 console 的整体部署形态：**一个应用、一套外壳、两个面**。具体到五个决定：

1. **路由**：`/`（`name:'voice'`，`meta:{face:'voice'}`）与 `/console/*`（`meta:{face:'console', requiresAuth:true}`）**并列成为 `ConsoleLayout.vue` 的子路由**。守卫只看 `meta.requiresAuth`，所以 `/` 仍是免登录入口：匿名用户直接开 `/` 不会被踢到 `/console/login`，但点侧栏里的「运维控制台」会被送到登录页（并带 `?next=/console`）。`/:pathMatch(.*)*` 仍回 `/`。
2. **外壳**：`ConsoleLayout` 从 `route.meta.face` 推出 `data-face`，挂在根节点上；顶栏与侧栏是**同一份 DOM**，只是内容按面切换。顶栏右侧留一个 `<div id="shell-actions">`；对话页用 `<Teleport to="#shell-actions">` 把账号 chip（`AccountWidget`）与工具 / 历史 / 设置三枚按钮挂进去（About 仍是 `IdentityBlock` 里的圆钮）。**对话页不再有自己的 `.v-top` 顶栏**，`IdentityBlock` 退回舞台头部（标题 / blurb / 鸣谢，属于内容而不是 chrome）。
3. **侧栏**：`router/nav.ts` 导出两组 `NAV_GROUPS`——`console` 五项（参数 / 会话 / 版本 / 实例 / 审计）与 `voice` 五项（对话 / 会话历史 / 工具 / 设置 / 关于）。对话页这五项里只有「对话」是路由，其余四个是**打开浮层的按钮**（demo 的四个模态也没有 URL），最后一行是「运维控制台」外链。
4. **舞台高度**：`face=voice` 时 `.shell__content { padding: 0; overflow: hidden }`，`.v-page` 用 `height: 100%` 而**不是 `100vh`**，行模板是 `auto minmax(0, 1fr) auto`（头部 / 舞台 / 页脚）。`html, body, #app` 必须一路 `height: 100%`；`div.shell` 用 `display:flex; flex-direction:column; height:100%`，内部两行是 `.shell__top` 与 `.shell__body`（`display:flex; flex:1 1 auto; min-height:0`），`.shell__nav` 与 `.shell__content`（`flex:1 1 auto; min-width:0; min-height:0`）在 `.shell__body` 里横排——只要有一层漏了 `min-height:0`，`1fr` 就会被内容顶开、页脚跑到视口外。orb 在 `1fr` 行里居中（`place-items: center`），气泡绝对定位在舞台右上，**相机 PiP 从 `position: fixed` 改成 `position: absolute`**（基准是 `.v-stage` 的 `position:relative`，不是 `.v-page`；`fixed` 会压到侧栏上），页脚贴底。
5. **折叠与小屏**：`stores/shell.ts` 持有 `siderCollapsed`（写 `localStorage['s2s.shell.collapsed']`，不是密钥）、`drawerOpen` 与 `voiceOverlay`；侧栏宽度 `200 → 56`（只留图标），舞台随 `flex: 1; min-width: 0` 自适应变宽。视口 `< DRAWER_BREAKPOINT(980)` 时侧栏改为抽屉（`nav.shell__nav` 平移出屏 + `.shell__scrim` 遮罩，**不用 `a-drawer`**：它 Teleport 到 body，会把顶栏汉堡与外链盖在下面），顶栏左侧出现汉堡，舞台占满整行，**不允许出现横向滚动、不允许压缩 orb 的圆形**（`.v-orb` 用 `min(38vh, 320px)` 而不是固定 px）。

三点理由，回答“为什么不保留独立全屏路由”：

- **运维台与对话页是同一个部署的两个面**，不是两个产品。两个外壳就意味着两套顶栏 DOM、两套登录态入口、两套窄屏行为，改一处忘一处。
- **导航必须可达**：运营在 `/console/instances` 看完监控，要能一键进对话页复现问题；全屏独立路由上没有任何回到运维台的入口。
- **硬约束没变**：共用外壳不等于共用数据面——`/` 仍是演示面（匿名 cookie、`/api/*`、不套 `ApiResponse`），`/console/*` 仍是运维面（JWT、`/api/v1/*`）。两个面在**同一个 SPA、同一个构建产物**里靠路由与 `face` 区分（§3.5.1 B9）。

### 3.3 工程边界与目录结构

#### 3.3.1 工程边界

| 维度 | 约定 |
|---|---|
| 归属 | `console/` 在 `speech-to-speech-src` 仓库内，但**不参与** `speech_to_speech` 的 wheel 打包（`pyproject.toml` 的 `packages.find.include = ["speech_to_speech*"]` 已把它排除），也不被 `pip install .` 安装 |
| 构建独立性 | 两个子项目各有自己的依赖清单、构建入口与测试命令，可分别开发与测试；**但部署产物只有一个**：前端 `dist/` 与后端代码都进 s2s 镜像；`console/` 下不得出现跳子项目的相对 import |
| 共享物 | 三样：`docs/parameter-catalog.yaml`（只读输入）、`config/`（被管对象，console 写、pipeline 读）、`/app/data`（参数库与用量库） |
| 与 demo 的关系 | `demo/` 是**功能来源与回归基线**，不是运行期依赖；`console/` 不 import `demo/` 任何模块，全部按语义移植（§14.1）。P4 后 `demo/` 不再部署，代码保留在仓库作历史 |
| 与 speech_to_speech 的关系 | 单向：console 调用 pipeline 的 HTTP 接口（回环），并且 `services/validator_service.py` 是唯一 import `speech_to_speech.config` 的模块；反向不依赖（pipeline 不知道 console 存在，除本期新增的 `/internal/*` 路由） |
| 版本化 | `console/` 与 `speech-to-speech-src` 同仓同提交，catalog 漂移检测因此可在同一 commit 内完成；**镜像 tag 同时代表前端、后端与 pipeline 三者版本**（同镜像即同版本） |

#### 3.3.2 `console/frontend`

```
console/frontend/
├── package.json / package-lock.json   npm；锁文件必须提交（D2）
├── tsconfig.json / tsconfig.node.json strict + @/* 路径别名
├── vite.config.ts                     dev :3000；/api、/v1、/vendor → :8000（ws:true）
├── vitest.config.ts                   node 环境，src/**/*.spec.ts（纯逻辑层）
├── playwright.config.ts               e2e，baseURL http://127.0.0.1:8000
├── index.html                         唯一入口（SPA，双布局）+ 对话页图标精灵 <symbol>（#i-*）
├── scripts/copy-vendors.mjs           prebuild：node_modules → public/vendor（D10）
├── public/
│   ├── vendor/openai-realtime-agents.umd.js   从 @openai/agents-realtime 复制
│   ├── vendor/local-vad/*                     从 @ricky0123/vad-web + onnxruntime-web 复制（6 个资产）
│   └── worklets/{audio-playback.js,mic-capture.js}  原样搬迁，audioWorklet.addModule 直接加载
└── src/
    ├── main.ts / App.vue / vite-env.d.ts
    ├── router/{index.ts,nav.ts}        `/` → ConsoleLayout 的 voice 子路由；`/console/*` → 同一布局的 console 子路由
    ├── api/{client,auth,catalog,profiles,sessions,instances,runtime,demo,logs,turn-latency,voices}.ts
    ├── types/{api.d.ts,catalog.d.ts,profile.d.ts,voice.d.ts,voice-library.ts,logs.ts,turn-latency.ts}
    ├── stores/{auth,catalog,draft,console,voice,runtime,shell,logs,voices}.ts
    ├── layouts/ConsoleLayout.vue       两个面共用：按 route.meta.face 切顶栏/侧栏内容，#shell-actions 供对话页 teleport
    ├── views/{LoginView,ParamsView,SessionsView,VersionsView,InstancesView,AuditView,VoiceView,VoicesView}.vue
    ├── features/voice/
    │   ├── types.ts / useTurnLatency.ts
    │   ├── components/{IdentityBlock,AccountWidget,OrbStage,MicGate,BubbleStack,
    │   │               TranscriptList,HistoryDrawer,CameraPip,TurnTimings,
    │   │               ToolsDialog,SettingsDialog,AboutDialog,LimitDialog,QueueOverlay}.vue
    │   ├── transport/{s2s-client,agents-sdk,events,turn-latency}.ts
    │   ├── audio/{capture,vad,meter,sent-audio}.ts
    │   └── tools/camera.ts
    ├── components/{ParamTree,ParamField,SecretField,ExposureTag,EffectBadge,FixedField,
    │               VoicePicker,VoiceLibraryTable,VoiceCreateDialog,VoiceAudition,
    │               DiffTable,VersionTable,AuditTable,InstanceCard,RuntimeGrid,
    │               ModelRuntimeCard,TurnLatencyPanel,LogPanel,LogAnalysisCard,
    │               ErrorBanner,ConfirmDialog}.vue
    ├── composables/{useProfile,usePolling,useConfirm,useLogFollow}.ts
    ├── directives/{permission}.ts         v-permission 按角色隐藏写操作
    ├── i18n/{index.ts,zh-CN.ts}           先只出 zh-CN，保留机制
    ├── styles/{index.less,variables.less,voice.less,theme.ts}
    └── utils/{format.ts,error.ts,storage.ts,analysis-format.ts,turn-latency-format.ts,
               voice-refs.ts}     voice-refs：名字去重、绑定表、patch 生成（纯函数，可测）
```

不再有的东西：`Dockerfile`、`nginx.conf`、`nginx.default.conf`、`vite preview` 对外发布。前端只产出 `dist/`，发布方式是“被后端静态托管”（§3.4.3 D1）。

#### 3.3.3 `console/backend`

```
console/backend/
├── requirements.txt / requirements-dev.txt   共享依赖写下界（D9）
├── .env.example
├── alembic.ini
├── alembic/{env.py,versions/}                唯一 DDL 来源；0001 建 4 张表 + 1 个管理员，0003 建 voices
├── conftest.py                               把 backend/ 注入 sys.path，pytest 可 import app.*
├── deploy/
│   ├── supervisord.conf                      PID 1：两个 program + unix socket
│   └── entrypoint.sh                         只 exec supervisord，不跑业务逻辑
├── app/
│   ├── main.py                               FastAPI、lifespan、中间件、静态托管、router 注册
│   ├── deps.py
│   ├── config/{__init__,_app,_database,_auth,_console,_demo}.py
│   ├── core/{router_registry,security,errors,logging,spa}.py   spa：SPA 回退与 /vendor
│   ├── db/{database.py,base.py}
│   ├── models/{param_user,param_draft,param_version,param_audit,voice}.py
│   ├── schemas/{common,auth,catalog,profiles,sessions,instances,demo,voices}.py
│   ├── repositories/{user,draft,version,audit,voice}_repository.py
│   ├── routers/{auth,catalog,profiles,sessions,instances,runtime,status,health,voices}.py   运维面
│   ├── routers/demo/{config,me,search,calls,session,queue}.py               演示面
│   ├── routers/realtime.py                   语音面反代（WS + SDP）
│   ├── services/{auth,catalog,layout,renderer,validator,publish_flow,restart_runner,
│   │            supervisor_client,realtime_proxy,demo_config,identity,metering,
│   │            search_proxy,asset,hot_update,audit,runtime,log,log_analysis,
│   │            voice,voice_precompute}_service.py 等（详见 §3.2.3）
│   ├── services/voice_precompute.py           预计算子进程入口（CPU-only，单并发，§3.11.5）
│   ├── middleware/{request_id,audit_route,exception_handler,security_headers}.py
│   └── utils/{secrets,yamlio,paths,sqlite_usage}.py
├── scripts/{seed_admin.py,import_legacy_sqlite.py}
└── tests/
    ├── conftest.py
    ├── unit/            catalog/layout/renderer/validator/auth/metering 纯逻辑
    ├── integration/     routers + 真实 SQLite（tmp_path）+ supervisor/httpx 打桩
    └── demo/            演示面：Serper / LB / OAuth 全部 httpx 打桩
```

目录约定取自 MinWorkBuddy 的既有分层（`app/{config,core,db,models,repositories,routers,schemas,services,middleware,utils}` + `deps.py` + `alembic/` + `conftest.py`），以保证两处工程的心智模型一致。

### 3.4 技术栈对齐

下表逐项核对自 `D:\projects\MinWorkBuddy` 的实际源码（核对证据见 §16）。**只对齐技术选型，不复制其业务代码**。

#### 3.4.1 前端

| 维度 | 选型 | 版本 | 核对出处 |
|---|---|---|---|
| 语言 | TypeScript（`strict`、`noUnusedLocals`、`noUnusedParameters`） | 5.4 | `frontend/tsconfig.json`、`package.json` devDeps |
| 框架 | Vue 3（SFC） | 3.4 | `frontend/package.json` dependencies |
| 路由 | vue-router | 4.3 | 同上 |
| 状态 | pinia | 2.1 | 同上 |
| UI 组件库 | ant-design-vue + @ant-design/icons-vue | 4.1 / 7.0 | 同上 |
| 样式 | Less（Sass 并存，console 只用 Less） | 4.6 / 1.71 | `package.json` devDeps |
| HTTP | axios（单实例 + 请求/响应拦截器） | 1.6 | `package.json`、`frontend/src/utils/request.ts` |
| 时间 | dayjs | 1.11 | `package.json` |
| 国际化 | vue-i18n | 9.13 | `package.json`；console 先只出 zh-CN |
| 包管理器 | npm（提交 `package-lock.json`） | — | `frontend/package-lock.json`（无 pnpm-lock） |
| 构建 | Vite + @vitejs/plugin-vue + vue-tsc | 5.1 / 5.0 / 2.0 | `vite.config.ts`、`package.json` |
| 代码检查 | ESLint + eslint-plugin-vue + @typescript-eslint | 8.57 / 9.22 / 7.1 | `package.json` devDeps、`lint` 脚本 |
| 测试（逻辑） | Vitest（node 环境，`src/**/*.spec.ts`） | 2.1 | `vitest.config.ts` |
| 测试（e2e） | Playwright（来自 `demo/package.json` 的同一版本） | 1.62.1 | `demo/package.json:20`（D8） |
| 语音客户端依赖 | `@openai/agents`（**只取 UMD 产物**）、`@ricky0123/vad-web`、`onnxruntime-web` | 0.14.3 / 0.0.31 / 1.22.0 | `demo/package.json:13,14,16`（D10） |
| 运行形态 | `vite build` 产出 `dist/`，由 `console/backend` 的 `StaticFiles` 托管；**无 nginx、无独立前端镜像** | — | D7 |
| 反向代理 | 开发态 Vite `server.proxy`（`/api` `/v1` `/vendor`，`ws:true`）；生产态由应用层反代（§3.5.1） | — | `vite.config.ts`；不再有 `nginx.default.conf` |

**明确不引入**（MinWorkBuddy 有、console 不需要）：Electron 44 / electron-builder 与桌面端运行时配置注入；`@antv/g2`、`@antv/s2`、`echarts`、`vue-echarts`、`d3`、`@vue-flow/*`；`@file-viewer/*`；`markdown-it` / `marked` / `highlight.js`；`watermark-js-plus`。引入标准是「本周视图需要」而不是「上游有」。

#### 3.4.2 后端

| 维度 | 选型 | 版本 | 核对出处 |
|---|---|---|---|
| 语言/运行时 | Python **3.12**（沿用 s2s 基座 `python-torch:cu128`）；代码只用 3.11 兼容子集 | 3.12 | s2s 根 `Dockerfile:25`、`:69`；MinWorkBuddy 为 3.11（D12） |
| API 框架 | FastAPI + Starlette | `>=0.115.0`（由 s2s 的 `uv sync` 解析，不在 console 里精确 pin） | s2s `pyproject.toml`、`demo/requirements.txt`（D9） |
| ASGI 服务器 | uvicorn[standard]（单进程单 worker，由 supervisor 托管） | `>=0.30.0` | s2s `pyproject.toml`（不再引 gunicorn） |
| 配置 | pydantic + pydantic-settings（`app/config/` 分关注点拆类） | ≥2.7.4 / ≥2.1.0 | 同上、`app/config/_database.py` |
| ORM | SQLAlchemy（`create_engine` + `declarative_base` + `sessionmaker` + `get_db()`） | ≥2.0.35 | `app/db/database.py` |
| 迁移 | Alembic（`alembic/versions`） | 1.13.1 | `backend/alembic/` |
| 数据库 | PostgreSQL（psycopg2-binary，可选 profile）；**默认 SQLite 落 `/app/data/console.sqlite3`**（同构，卷持久化） | ≥2.9.10 | `app/config/_database.py` 拼 `postgresql://`；单容器默认不引外部 DB |
| 鉴权 | python-jose（HS256，载荷 `sub` + `exp`）+ bcrypt + `HTTPBearer` | 3.3.0 / ≥4.0 | `app/services/auth_service.py`、`app/deps.py` |
| 日志 | loguru（stdout + 轮转文件） | 0.7.2 | `app/main.py` |
| HTTP 客户端 | httpx（调 pipeline） | ≥0.26.0 | `requirements.txt` |
| 参数文件读写 | PyYAML（catalog + 渲染 YAML） | `>=6,<7` | s2s `pyproject.toml`（已是主依赖，无需单独引入） |
| 进程管理 | supervisord（PID 1，unix socket + 两个 program） | 4.x | 本期新增；PID 1 不能是 uvicorn（§3.1） |
| WebSocket 反代 | `websockets` 客户端（`/v1/realtime` 双向转发） | `>=12.0` | s2s `pyproject.toml`（已是主依赖） |
| 演示侧身份 | `huggingface_hub[oauth]`（拖入 `authlib` + `itsdangerous`） | `>=0.34.0` | s2s `pyproject.toml` 已依赖 hub，只需补 `[oauth]` extra（见下段） |
| 测试 | pytest + pytest-asyncio | 8.0.1 / 0.23.5 | `requirements.txt` |
| 代码检查 | ruff（console 自带配置；MinWorkBuddy 仅有 `.ruff_cache`） | — | `backend/.ruff_cache/` |
| 容器 | **没有自己的 Dockerfile**：`console/backend` 拷进 s2s 镜像，`PYTHONPATH=/app/console`；依赖追装进同一个 venv | — | D7 |
| API 前缀 | `API_PREFIX=/api/v1`（运维面）；演示面固定 `/api`，不参与前缀配置 | — | `backend/env.example` |
| CORS | **仅开发态**生效（`vite dev :3000` 直连调试）；生产同源，不装 `CORSMiddleware` | — | 与 MinWorkBuddy 不同：它为了桌面端而常开 CORS（D7） |
| JWT 参数 | `JWT_SECRET_KEY` / `JWT_ALGORITHM=HS256` / `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30` / `JWT_REFRESH_TOKEN_EXPIRE_DAYS=7` | — | `backend/env.example` |

**明确不引入**：celery / kombu / arq（无异步队列需求）、neo4j / graphiti / pgvector（无图与向量）、agentscope / mcp（不承载对话）、LangChain 系、`semantica`、`apscheduler`（无定时任务；用量回收靠 lifespan 内的 `asyncio` 定时任务，与 demo 同构）、OpenTelemetry 全量导出。

与 MinWorkBuddy 相比，console 真正“额外新增”的只剩两样：`supervisord`（管两个进程，它没有）与 `huggingface_hub` 的 `[oauth]` extra（演示面身份）。其余三项**不是**额外引入：`PyYAML` 与 `websockets` 已是 s2s 的主依赖，`speech_to_speech` 包在同镜像里直接 `import`（§9.1）——都不需要第二次安装。

#### 3.4.3 显式差异与理由

| # | 差异 | 理由 |
|---|---|---|
| D1 | 不做 Electron / 桌面端地址注入（`getApiBase()` / `onApiBaseChange`） | 控制台是同源 Web，地址由同源反代决定（前端只认相对路径），不接受客户端改后端地址 |
| D2 | 不照抄 `frontend/Dockerfile.prod` 里的 `pnpm` + `pnpm-lock.yaml` | 该文件与仓库现有 `package-lock.json` 不一致（无 pnpm 锁文件）；console 统一 npm |
| D3 | 鉴权只做本地账号 + JWT，不做租户（`tenant_id`）、菜单树、API Key 双模 | 控制台是单机运维面，不是多租户业务系统；角色只有 `admin` / `operator` |
| D4 | 成功响应统一 `ApiResponse{code,message,data}`，错误统一一种错误体 | MinWorkBuddy 现状为两种（HTTPException → `{detail}`；全局 → `{message,detail}`），console 只定义一种，见 §3.5.2 |
| D5 | 只建 4 张表，不做租户拦截器（`tenant_resolver` / `do_orm_execute`） | 无租户维度；加了会让每次查询多一层隐式过滤 |
| D6 | 不做 `scripts/build.cjs` 多 mode 打包链 | console 只有 production 一种发布模式，`vite build --mode production` 足够 |
| D7 | 前端不做独立镜像、不引 nginx；生产同源不装 `CORSMiddleware` | 与 pipeline 同容器后，静态资源由 FastAPI `StaticFiles` + SPA 回退直接托管，多一个 nginx 进程只会多一个要监控的 PID（§3.1） |
| D8 | 测试加 Playwright e2e（1.62.1，与 `demo/` 同版本）；仍不引入 `@vue/test-utils` / `jsdom` | 语音页有 Worklet、WebRTC、canvas 与自动播放限制，纯 node 环境测不了；但这些逻辑已被拆到 `features/voice/{transport,audio}` 的纯 TS 模块，仍可用 node 环境 Vitest 覆盖枚举/状态机 |
| D9 | 与 s2s 共用的包**写下界不写精确 pin**（`fastapi>=0.115.0` 而非 `==0.115.0`） | 同一镜像里只有一个 venv，s2s 的 `uv sync` 已解析过这些包；再精确 pin 会制造 `uv` 无可解或运行期两套版本。只有 console 独占包（SQLAlchemy / alembic / psycopg2 / python-jose / bcrypt / loguru / supervisord）写精确版本 |
| D10 | `@openai/agents` 只取 UMD 产物，构建期复制到 `public/vendor/`；运行期不读 `node_modules` | `demo/server.py` 能在运行期回退读 `node_modules/...`，是因为它把整个目录拷进了镜像；同镜像合并后那会多背一整棵 node 依赖树（百 MB 级）。Vite 的 `public/` 直拷能拿到同样的字节 |
| D11 | 参数库（SQLAlchemy）与演示用量库（stdlib `sqlite3`）**分两个文件** | `demo/limiter.py` 用裸 `sqlite3` + 自定义 PRAGMA；硬接进 SQLAlchemy 会话会制造两套事务语义与锁竞争。分开后各自 WAL、各自备份，互不影响 |
| D12 | Python 用 **3.12**（s2s 基座），不是 MinWorkBuddy 的 3.11 | 同一个容器只能有一个解释器；s2s 基座已把 3.12 写进 `requires-python` 收窄逻辑（`Dockerfile:69`）。代价：console 代码需保持 3.11+ 兼容写法（不用 3.12 独占语法），以便将来回退到 3.11 基座 |
| D13 | console 的日志用 loguru，但**不接管 pipeline 日志** | pipeline 已在用 stdlib `logging`（§“基于 Python logging 的流水线上下文”），接管会拆掉它的上下文/脱敏过滤器；两个 program 各自输出到 stdout，由 `docker logs` 合流 |
| D14 | 暗色主题用 `<a-config-provider>` + `theme.darkAlgorithm` 落地，不逐组件手改 CSS | `ant-design-vue/dist/reset.css` 是**亮色**基线：不接管算法时 `a-input` / `a-select` / `a-table` / `a-modal` 全是白底浅灰边，贴在 `#0b1020` 上会形成大面积刺眼白块。这不是“颜色没调好”，而是从未安装主题算法；逐组件覆盖则是把同一个决定重复写几十遍 |

#### 3.4.4 暗色主题契约（ConfigProvider + token）

`main.ts` 只 `import 'ant-design-vue/dist/reset.css'` 是不够的——那是亮色基线。**必须**由 `App.vue` 在最外层固定包一层 `<a-config-provider>`，一次接管算法与色板：

```vue
<!-- console/frontend/src/App.vue -->
<script setup lang="ts">
import { themeConfig } from '@/styles/theme'
</script>

<template>
  <a-config-provider :theme="themeConfig">
    <router-view />
  </a-config-provider>
</template>
```

```ts
// console/frontend/src/styles/theme.ts —— 唯一主题事实来源
import { theme } from 'ant-design-vue'

export const themeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#5b8cff',
    colorBgBase: '#0b1020',
    colorBgLayout: '#0b1020',
    colorBgContainer: '#141a2e',
    colorBgElevated: '#1a2138',
    colorBorder: '#232b45',
    colorBorderSecondary: '#1e2740',
    colorTextBase: '#e6e8f0',
    colorText: '#e6e8f0',
    colorTextSecondary: '#8b93a7',
    colorTextTertiary: '#5b6478',
    colorSuccess: '#35c48a',
    colorWarning: '#e8b339',
    colorError: '#f0655c',
    colorInfo: '#5b8cff',
    borderRadius: 8,
    fontSize: 13,
    fontFamily: "'Inter', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
  }
}
```

`styles/variables.less` 与 `theme.ts` 必须**同值**，两边任一处改动都要同步另一处：

| Less 变量 | AntD token | 值 | 用在哪 |
|---|---|---|---|
| `@color-bg` | `colorBgBase` / `colorBgLayout` | `#0b1020` | 页面底、`body` |
| `@color-surface` | `colorBgContainer` | `#141a2e` | 顶栏、侧栏、卡片、表格底 |
| （`--surface-2`） | `colorBgElevated` | `#1a2138` | 下拉弹层、悬浮行、输入框底 |
| （`--border`） | `colorBorder` | `#232b45` | 面板描边、控件边框 |
| （`--border-soft`） | `colorBorderSecondary` | `#1e2740` | 表格行分隔线 |
| `@color-text` | `colorText` / `colorTextBase` | `#e6e8f0` | 正文、表头值 |
| `@color-muted` | `colorTextSecondary` | `#8b93a7` | 说明文字、列头、`draft-meta` |
| （`--text-faint`） | `colorTextTertiary` | `#5b6478` | 占位符、禁用态 |
| `@color-accent` | `colorPrimary` / `colorInfo` | `#5b8cff` | 主按钮、选中项、链接 |
| （`--success`） | `colorSuccess` | `#35c48a` | `live` / `ok` / `RUNNING` |
| （`--warning`） | `colorWarning` | `#e8b339` | 未保存改动、结构性校验、`draining` |
| （`--danger`） | `colorError` | `#f0655c` | `failed` / `healthcheck_timeout` / 回滚确认 |
| `@radius-md` | `borderRadius` | `10px` / `8px` | 面板 10、控件 8（AntD 侧统一 8） |

四条约束：

1. **组件内不写死颜色**。需要强调色时用 `@color-*`（Less）或 `token.color*`（TS），不要出现 `#141a2e` 这类字面量；`console/design/console-preview.html` 里那段 `:root` 只是预览页自用。
2. **首帧不闪白**。`index.less` 的 `body { background: @color-bg }` 是 FOUC 兜底；最终底色以 `colorBgBase` 为准，两者必须同值。
3. **侧栏 `a-menu theme="dark"` 不叠加 AntD 默认深蓝**（`#001529`）。它只表达“选中态样式”，颜色仍由 token 决定；若出现 `#001529`，说明有组件没被 `ConfigProvider` 覆盖。
4. **视觉基线是 `console/design/console-preview.html`**（零依赖单文件）。预览页的视图分组：运维台六视图（参数 / 会话 / 版本 / 实例 / 审计 / 登录）+ 对话页四视图（待机 / 通话中 / 排队 / 弹层叠加），**全部跑在同一个 `.topbar + .sider + .content` 外壳里**——对话页那四块把 `.v-page` 嵌在 content 内（`height: calc(100vh - 56px)`），预览页**不再隐藏顶栏与侧栏**（旧稿的 `body[data-view^='voice'] .sider { display: none }` / `.topbar { display: none }` 已作废，它会把部署形态误读成“语音页是独立应用”）。实例页另有三块：模型运行时卡片（四段）、日志面板、归纳结果卡片。改主题的顺序是：先改预览页看效果 → 再改上表 → 最后同步 `theme.ts` 与 `variables.less`。预览页里对话页那四块**故意不用 antd 的亮色组件**：它们展示的是 `styles/voice.less` 的暗色基线（`:root` 上的 `--voice-*`），因为对话页的模态和抽屉会被 teleport 到 `body`，拿不到 `.v-page` 上的变量。

### 3.5 前后端边界与接口约定

#### 3.5.1 边界规则

| # | 规则 | 反例（禁止） |
|---|---|---|
| B1 | 前端不接触 docker、文件系统与 pipeline；一切副作用经 `console/backend` | 前端直接 `fetch http://pipeline:8765/v1/pool` |
| B2 | 后端不产出 HTML、不做前端路由、不做 302 登录跳转 | 后端 `redirect` 到 `/login`；后端返回 Jinja 模板 |
| B3 | 权限判定在后端；前端 `v-permission` 只是视觉隐藏 | 仅靠隐藏按钮拦住 operator 改 `ops` 字段 |
| B4 | 字段合法性判定在后端；前端只做类型与范围提示 | 前端允许 `num_pipelines` 越过显存上限后提交 |
| B5 | 密钥单向：读接口永远 `***`；前端不得把密钥值写进 `localStorage`、URL、日志或前端错误上报 | 「显示已保存的 API Key」 |
| B6 | 契约前缀 `/api/v1`，破坏性变更升 `v2`，不原地改字段语义 | 把 `draft` 从对象改成数组 |
| B7 | 错误码是稳定的机器标识，前端据此翻译文案；后端 `message` 不含输入值 | 把 `responses_api_api_key` 的值拼进 `message` |
| B8 | OpenAPI 是契约源：后端暴露 `/api/v1/openapi.json`；前端类型手写但由契约测试对齐 | 引入代码生成器（本期不需要） |
| B9 | 三个面按前缀划分，不共用一个前缀：运维面 `/api/v1/*`（JWT）、演示面 `/api/*`（匿名 cookie / HF OAuth）、语音面 `/v1/*`（无鉴权反代） | 把运维接口放到 `/api/*` 下，或用 JWT 拦住语音接口（浏览器无法带 Bearer 的 WebSocket 握手） |
| B10 | 演示面的响应形状**不套** `ApiResponse`，必须与 `demo/server.py` 逐字节兼容（`{search,lb,…}`、`{enabled:false}`、裸 SDP、`{ok:true}`） | 把 `/api/config` 改成 `{code,message,data}`，对话页与旧客户端全部失效 |
| B11 | 语音面只做透明反代：不改协议、不注入会话状态、不改写帧 | 在代理层改写 `session.update`，或在代理层补发工具定义 |
| B12 | 监控、日志与归纳全部**只读**：不写 `config/`、不调 publish/rollback、不重启进程、不存原始日志正文；归纳结果只作为 `param_audit` 的一条审计（字段名 + 摘要），不进配置也不进参数库 | 在分析结果里放「一键应用」，或把原始日志/密钥存进 `param_audit.detail` |

#### 3.5.2 接口约定

| 项 | 约定 | 依据 |
|---|---|---|
| Base：运维面 | `/api/v1` | MinWorkBuddy `API_PREFIX` 约定 |
| Base：演示面 | `/api` | 与 `demo/server.py` 的 11 组路由逐一对应（§15.13） |
| Base：语音面 | `/v1` | 透传 pipeline 的 OpenAI 兼容路径（`/v1/realtime`、`/v1/realtime/calls`） |
| 成功包络（仅运维面） | `{"code": 200, "message": "success", "data": <payload>}`（`ApiResponse[T]`） | MinWorkBuddy `app/schemas/common.py` |
| 错误包络（仅运维面） | `{"code": "<machine_code>", "message": "...", "detail": [...] , "requestId": "..."}`，随 HTTP 状态码 | D4：MinWorkBuddy 现有两种错误体，console 统一一种 |
| 鉴权：运维面 | `Authorization: Bearer <access_token>`；缺失/失效 → `401 unauthorized`；角色不足 → `403 forbidden` | MinWorkBuddy `HTTPBearer` + `require_admin` |
| 鉴权：演示面 | 匿名 cookie（`s2s_anon`，首次访问下发）+ 可选 HF OAuth；`LIMITER_ENABLED=false` 时一切开放（与 `docker run` 本地行为一致） | `demo/auth.py` 的既有语义，原样移植（§9） |
| 鉴权：语音面 | 无应用层鉴权；边界靠“8765 不 publish + 8000 只绑内网” | §10.1 网络暴露 |
| Token 存储 | 前端内存 + `localStorage` 只存 token 与用户名；不存密码、不存密钥 | B5 |
| 时间 | ISO 8601 UTC（`2026-10-23T14:05:11Z`）；展示本地化由 dayjs 负责 | 避开时区歧义 |
| 分页 | `?page=1&pageSize=50`，响应 `data.list / data.total / data.page / data.pageSize` | MinWorkBuddy `PageParams` / `PageData` |
| 并发 | 写操作带 `If-Match: <version>`；不匹配 → `409 version_conflict` | §4.1 步骤 1 |
| 单飞 | 同一 profile 同时只允许一个 publish/rollback；第二个 → `409 publish_in_progress` | §4.3 状态机 |
| 审计 | 每个写操作响应 `data.auditId`；审计可反查 | §10.1 |
| 请求追踪 | 后端生成/透传 `X-Request-Id`，回应与日志同一值 | 排障 |
| 健康检查 | `GET /api/v1/health` → `{"status":"ok","version":"…"}`，不鉴权、不碰下游 | 容器 healthcheck 用 |

### 3.6 组件图（链路 A 一次发布）

```
 浏览器（/console）
   │ ① POST /api/v1/profiles/prod/publish   Authorization: Bearer <JWT>
   ▼
 console 进程（同容器，:8000）  routers/profiles.py
   │ ② 解 JWT → 必须 admin
   │ ③ publish_flow（同 profile 单飞）
   ▼
 ┌────────────────────────────────────────────────┐
 │ renderer_service：现有 YAML + draft → 新文本      │
 │ validator_service：load/validate/resolve        │
 │                  + 显存预算与跨字段约束          │
 └───────────────────┬────────────────────────────┘
                     │ ④ 通过：落 version 行（publishing）
                     │    写 /app/config/<profile>.yaml
                     │    旧文件 → .bak.<version>
                     ▼
 restart_runner → supervisor_client
                     │ ⑤ XML-RPC stopProcess/startProcess("pipeline")
                     │    （**只重启子进程，console 自己不重启**）
                     ▼
 GET http://127.0.0.1:8765/v1/pool（≤180s，轮询）
                     │ ⑥ size==num_pipelines 且 in_use 下降 → live
                     │    否则恢复 .bak → 再重启 → 再探活 → rolled_back
                     ▼
 audit_service 落审计 → 响应 data{version,status,healthcheck,durationS,auditId}
```

链路 B（热更新）不经过 renderer / restart_runner：`routers/sessions.py` → `hot_update` → `POST http://127.0.0.1:8765/internal/sessions/update` → 逐连接 `handle_session_update`。两条链在 `/api/v1/sessions/update` 与前缀为 `/profiles/{id}/*` 的发布接口上分开，**不共用一个端点**（原设计把两条链都放在 `/admin` 下，会导致「改文件」与「改会话」在日志与防火墙规则上无法区分）。

两个必须写进 UI 的事实：发布**会断开所有在聊会话**（pipeline 子进程重启）；发布**不会**让控制台页面掉线（console 进程不动）。这恰好是进程级重启相对于容器重建的核心收益（§12 R19 的替代关系）。

### 3.7 依赖方向

```
console/frontend ──HTTP /api/v1、/api──▶ console/backend ──HTTP /v1/*──▶ pipeline（回环 :8765）
                                          │
                  routers ──▶ services ──▶ repositories ──▶ models
                                │
      catalog_service ──▶ layout_service ──▶ renderer_service ──▶ validator_service
                                ▲
                          publish_flow（唯一编排者）
                                │
                restart_runner（出进程）/ hot_update（出网）/ realtime_proxy（转流）
                                │
      ┌─────────────────────────┼──────────────────────────┐
      ▼                         ▼                          ▼
  /app/config 文件      supervisor unix socket        pipeline 子进程（127.0.0.1:8765）
  （唯一写入方）         （只允许 restart pipeline）
```

单向无环。三条硬约束：

- **子项目之间只有一个依赖边**：HTTP。前端不 import 后端代码，后端不知道前端存在（除它托管 `dist/` 这个静态事实）。
- **`validator_service` 是唯一 `import speech_to_speech` 的模块**，故 console 不需要理解 pipeline 的运行时对象；其余服务只依赖 catalog、文件系统、数据库与 HTTP，可以单独测试。
- **console 不持有 docker 权限**：它只能通过 supervisor 的 unix socket 启停 `pipeline` 一个 program（§10.3）。

### 3.8 明确不做的事

- 不管理多台机器、不做容器编排替代品（仍只驱动本机一份 compose，且只由宿主动手）。
- 不在平台侧重新实现参数默认值——默认值一律从 catalog 读，catalog 与源码不一致属 catalog 缺陷。
- 不做「改一个字段就重启一次」，发布是整份 profile 的原子动作。
- **不让 console 与 pipeline 耦合到同一个进程**：它们是同容器的两个独立进程，pipeline 崩了不影响页面，console 重启不影响在跑的通话（除那一瞬）。但也**不给 pipeline 做热重载**：配置仍然只能通过重启生效（§2.3）。
- 不做控制台内的多租户、菜单权限树、审批流、注册/改密自助页（首个管理员由 `scripts/seed_admin.py` 建）。

### 3.9 模型运行时监控与日志（旁路）

实例页的监控区、日志面板与归纳结果都是**旁路**：它们读文件与回环 HTTP，不碰 GPU、不碰 pipeline 的事件循环（Global Constraint 4.3）。两个面共用一个原则：**拿不到就写“不可用 + 原因码”，绝不拿 0 或空白窗委过去**。

#### 3.9.1 四段模型卡：字段与真实来源

`GET /api/v1/runtime/models`（A.14）为 VAD / STT / LLM / TTS 各返回一个 `stage` 对象，字段与来源逐项绑定：

| 字段 | 类型 | 真实来源 | 取不到时的 `reason` |
|---|---|---|---|
| `stage` | `vad` / `stt` / `llm` / `tts` | 固定枚举（四段就是 pipeline 的四段） | — |
| `modelName` / `backend` | `string` / `string` | 当前 profile 的 `config/<profile>.yaml` 解析值（`vad.backend`、`stt.backend`、`llm.model`、`tts.model`） | `config_unreadable` |
| `loaded` | `bool` | `process_probe.state("pipeline").running` **且** 该段在最近 `window_s` 内有成功调用（`model_metrics.log`） | `pipeline_stopped` / `no_metrics_window` |
| `vram.usedMb` / `vram.percent` | `number` / `0..1` | 该段最近窗口内 `resources.vram_used_mb_peak` 的均值（单卡场景）；卡总量取 `nvidia-smi --query-gpu=memory.total` | `nvidia_smi_missing` / `vram_not_attributable` |
| `busy.inUse` / `busy.size` / `busy.occupied` | `number` / `number` / `bool` | `GET /v1/pool` 的 `in_use` / `size` 与 `units[].state` / `session_id` | `pool_unreachable` |
| `busy.queueDepth` | `number \| null` | **本期无来源**：`/v1/pool` 不暴露每 unit 待处理请求数 | `queue_depth_not_exposed` |
| `latency.firstByteMs` | `number \| null` | `MODEL_CALL_METRICS` 行里的 `output.first_byte_s`（handler 埋点，Task 21 新增） | `not_applicable`（VAD）/ `first_byte_not_instrumented`（旧日志） |
| `latency.processMs` / `p50Ms` / `p95Ms` | `number \| null` | 同一行里的 `duration_s`，以及 `MODEL_CALL_AGGREGATE` 的 `avg_latency_s` / `p50_latency_s` / `p95_latency_s` | `no_metrics_window` |

四条不能跨的线：

1. **不加 docker 依赖**：进程状态走已有的 `process_probe`（supervisord XML-RPC），显存走 `nvidia-smi` 子进程（`timeout=2s`，整卡数据，失败不抛 500）；**不读 `docker ps`、不读 `cgroup` 以外的容器元数据**。
2. **不采不算**：`model_metrics.log` 是唯一延迟来源。`qwen3_asr_handler` 今天没接 `monitor.trace`，STT 段就会老老实实显示“不可用 · 该后端未接指标埋点”，而不是填一个估算值。
3. **显存归属要说清楚**：`vram_used_mb_peak` 是**调用期间的整卡峰值**（含同卡其它进程），不是该模型的独占量；卡片上的 tooltip 必须写明这一点，否则“VAD 占 18GB”会让人误判。
4. **采样成本有上限**：`runtime_service.collect()` 的整体超时 `2.0s`，结果缓在进程内 `TTL=3s`；前端 `stores/runtime.ts` 每 5s 轮询一次，页签切走就 `stopPolling()`。即使 `nvidia-smi` 卡住，也只是这一块回到上一帧 + `runtime_degraded`，不会拖慢任何 HTTP 请求（全部 `run_in_executor` + `asyncio.wait_for`）。

#### 3.9.2 日志面板

`GET /api/v1/logs`（A.15）只读 `/var/log/supervisor/{console,pipeline}-{stdout,stderr}.log` 四份文件（Task 4 的 `supervisord.conf` 已把它们分开），四条设计：

- **按 cursor 增量**：`?after=<cursor>` 游标是“文件 inode + 字节偏移”的编码，只读新行；前端“尾部跟随”就是每 2s 拉一次 `after=nextCursor`。不用 SSE：console 是**单 worker**，SSE 会把长连接钉在一个进程上，而日志本来就是轮询语义。
- **过滤在服务端做粗、在客户端做细**：`process` / `level` / `from` / `to` / `q` 都支持，但服务端只在读取后做行级过滤与 `limit` 截断（默认 500 行，上限 2000），返回 `truncated:true` 让前端提示“已截断”。
- **只读**：没有 `DELETE`、没有 `POST /logs/write`、没有日志级别切换；日志级别由 supervisord 与 uvicorn 启动参数决定，不属这个控制台。
- **不阻塞语音**：全部 `asyncio.to_thread` + `asyncio.wait_for(1.5s)`；单次最多读 256 KiB 尾部。pipeline 正在服务时读日志只是 `read()` 文件尾，不影响它的事件循环（两者是两个进程）。

#### 3.9.3 三种故障的判定签表

验收（§14.6）要人工造三种现象，这张表是“看到什么算什么”的口径，写进 UI 的判定依据也用它：

| 现象 | 监控面板 | 日志面板 | 归纳输出 |
|---|---|---|---|
| **模型未加载** | 该段 `loaded:false + pipeline_stopped`（或进程 RUNNING 但无任何指标、`no_metrics_window`） | `pipeline-stderr.log` 里的 `ModuleNotFoundError` / `OSError: … checkpoint` / `Unsupported backend` 行 | 错误条目指向加载失败那行；根因是“权重/后端名与 catalog 不一致”；方案是 `POST /profiles/{id}/draft` 改回可用后端并发布 |
| **显存接近打满** | 四段 `vram.percent ≥ 0.9`，`gpu` 卡头变红，`alerts` 带 `vram_pressure` | `torch.OutOfMemoryError` / `CUDA out of memory` 行（不一定有——OOM 前也可能只是变慢） | 错误摘要里 OOM 计数与首次/末次时间；根因是 `llm.gpu_layers` / `num_pipelines` 超预算；方案是降 `num_pipelines` 或换更小量化 |
| **某段延迟异常升高** | 该段 `p95Ms` 明显高于其它段（卡片上“较上一窗口 +N%”），其余段正常 | 无错误行（正常请求）——重点看 `WARN` 的 `slow` / 重试 / 排队日志 | 归纳必须给出“无错误但有延迟尖峰”的结论与对应时间段，建议查 `p50/p95` 背离与并发 |

#### 3.9.4 轮次延迟：条目呈现、存储与分析

对话页的每条助手条目都有一个 `Server timings` 折叠块（§3.2.2 的 `TurnTimings.vue`），七行数字全部**由服务端测**，浏览器只负责校验与格式化。同一份数据同时提供两个去处：人看（条目 + 日志面板）与机器看（`turn_latency` 表 + 实例页轮次面板）。两条路共用同一事实源——**容器日志行**，不引入第三个副本。

**事实源（已存在）**：`src/speech_to_speech/pipeline/turn_latency.py` 的 `TurnLatencyTracker`。`response.py` 在响应终止时 `pop` 出 tracker，先打一行人读日志，再（Task 22 新增）打一行机器读 JSON：

| 字段 | 含义（与 `metadata_payload()` 逐字对应） |
|---|---|
| `version` | 固定 `2`；v1 只有 `e2e_s`，标题写作 `First audio` |
| `source` | `speech` / `client` / `tool`（`tool` 追问单独一个 tracker） |
| `turn_id` / `turn_revision` / `response_key` | 幂等键用后两个；`source=client`·`tool` 时 `turn_id` 可为空 |
| `status` | `completed` / `cancelled` / `failed` / `incomplete`（条目上的 `Completed` / `Interrupted` / `Failed` / `Incomplete` 就是它的四态译文） |
| `stt_s` | `Transcription` 行 |
| `llm_s` | `Response generation` 行（完整生成，含锁等待；`llm_ttft_s` 是内部量，不进记录） |
| `tts_ttfa_s` | `Voice synthesis to first audio` 行（首个模型音频块） |
| `e2e_s` | `E2E time` 行：估算语音结束到首个生成音频，**不含浏览器播放** |
| `vad_decision_s` | `VAD end decision` 行（整段最终 STT 闸门等待） |
| `smart_status` | `Smart Turn decision` 行：`complete` / `incomplete` / `failed` / `disabled` |
| `hold_s` | `Hold time before response` 行（客户端请求的处理延迟并集，`null` 显示 `Unavailable`） |

新增的机器行固定是 `TURN_LATENCY {json}`，与现有 `Turn … latency: …` 人读行**相邻输出、同一 logger**，因此它天然就在 `/var/log/supervisor/pipeline-stdout.log` 里——这正是“与容器日志一起存储”的字面含义。不新增网络请求、不新增端口、不依赖 console 存活（console 挂了语音照跑，行照样落盘）。

**存储（`turn_latency` 表）**：与 `param_audit` 同一个 SQLite 库，一个事实源两份视图：

| 项 | 约定 |
|---|---|
| 列 | `response_key` / `turn_revision` / `turn_id` / `source` / `status` / `smart_status` / `e2e_ms` / `stt_ms` / `llm_ms` / `tts_ttfa_ms` / `vad_decision_ms` / `hold_ms`（全部毫秒整数，`null` 保留 `null`）/ `logged_at` / `raw_offset` / `ingested_at` |
| 主键与幂等 | `PRIMARY KEY (response_key, turn_revision)`；后到的覆盖先到的（`cancelled` 之后又来 `completed` 是真实序列） |
| 保留期 | 14 天或 20 万行（先到者生效），按 `logged_at` 删；删表不影响日志 |
| 可重建 | `DELETE FROM turn_latency` 后由索引器重放日志能恢复同样行数——表是索引，不是账本 |
| 索引器 | `turn_latency_indexer` 复用 §3.9.2 的 `{inode, offset}` cursor，每 5s 拉一次增量，只匹配 ` TURN_LATENCY ` 行；单次 ≤ 2 000 行，`asyncio.to_thread` 读 + 批量 upsert |
| 落后 | `indexLagS = now - max(logged_at)`；超过 30s 时面板显示 `不可用 · index_lag`，不显示陈旧峰值充当现状 |

**实例页展示（`TurnLatencyPanel.vue`，A.17）**：时间窗（15m / 1h / 24h）+ `status` 过滤 + 两张块：

- **聚合块**：`count` / `completed` / `failed` / `cancelled` / `incomplete` / `failureRate`；`e2e` 的 `p50Ms` / `p95Ms` / `maxMs`；`stt` / `llm` / `ttsTtfa` / `vadDecision` / `hold` 的 `p50Ms` / `p95Ms`；`hold.unavailableCount`。
- **明细表**：`logged_at` / `response_key`（截 12 字符，悬停看全）/ `status` / 七个阶段值——这七个**就是**条目那七行（`e2eMs` / `vadDecisionMs` / `smartStatus` / `sttMs` / `llmMs` / `ttsTtfaMs` / `holdMs`），不多不少，所以任取一条条目都能和表里同一行逐格对上（§14.6 第 1 条）。表格只读，无删除与导出。

四条边界：

1. **两个口径不可互相替代**：模型卡（§3.9.1）是 handler 单次调用埋点（`MODEL_CALL_METRICS`）；轮次面板是端到端一次响应（含 VAD 判定、智能轮次等待、会话排队）。同一段变慢可能只在一处出现。
2. **各段不可相加**：`e2e_s` 是墙钟跨度，`stt` / `llm` / `tts_ttfa` 是各自内部的区间，互相重叠；条目末尾那句 `Stages overlap and do not add up.` 就是这个意思，面板上也必须原样再说一次。
3. **取不到就说取不到**：无记录 `no_turn_rows`；索引落后 `index_lag`；日志文件缺失 `log_missing`；某一阶段全为 `null` 时该行写 `Unavailable`，绝不写 `0 ms`。
4. **不阻塞语音**：索引器读的是另一个进程的日志文件，`read()` 尾巴；console 仍是单 worker，索引在后台任务里跑，60s 一次的聚合在 `to_thread` 里做（与 §3.9.2 同一套做法）。

### 3.10 LLM 日志归纳：能力边界

`POST /api/v1/logs/analyze`（A.16）把“选定时间窗 + 过滤条件”内的日志交给 LLM，输出四块结构化结果。它**是分析器，不是执行器**：

| 项 | 约定 |
|---|---|
| 只读 | 不写 `config/`、不调 `POST /profiles/*/draft|publish`、不重启进程；响应里没有“一键应用”按钮，方案只是文本 |
| 输入窗口 | 必填 `from`/`to`，最大 24h；`process` / `level` / `q` 可选。超窗 → `400 log_window_too_large` |
| 轮次摘要 | 默认 `includeTurnLatency=true`：把同窗口内的 `turn_latency` 聚合成**一段**结构化摘要（count / 四态计数 / `e2e` 的 p50·p95·max / `stt`·`llm`·`ttsTtfa`·`vadDecision`·`hold` 的 p50·p95 / `hold.unavailableCount`），**不逐条塞入**；`sent.turnRows` 报实际附带的轮次行数，`false` 时为 `0`。prompt 里明确要求“若附带了轮次摘要，必须回答慢在哪一段” |
| 脱敏 | 发送前过三道：① `Authorization` / `api[_-]?key` / `token` / `secret` / `password` / `sk-…` / `hf_…` 做值替换为 `***`；② Bearer / JWT 形状串整体替换；③ 用户自带的 Serper key 不存在服务端，无需处理（B5 下客户端 key 从不进后端日志） |
| 截断 | 先按级别（ERROR/WARN 优先）+ 去重（同模板行只留首末与计数）压缩，再按 token 预算截断；**响应必须回 `sent:{lines, estimatedTokens, truncated, droppedLines, turnRows}`**，前端把它渲染在结果卡头部（“已送入 412 行 / 约 5.8k tokens / 已截断 1.2k 行 / 附带 38 条轮次”）。token 估算用 `len(text)/4` 的粗估值并标注为估算 |
| 超时与限流 | 单次 `timeout=45s`；同进程单飞（第二个并发请求 → `429 log_analysis_busy`）；每 5 分钟最多 6 次（`429 log_analysis_rate_limited`）；上游 5xx → `502 log_analysis_unavailable` |
| 失败 | 前端**保留原始日志视图**，只在结果卡里显示失败原因 + “重试”，不清空已加载的日志行 |
| 输出四块 | `errors[]`（`signature` / `count` / `firstSeen` / `lastSeen` / `level` / `sample`）、`critical[]`（`signature` / `impact` / `rationale` / `evidence`）、`rootCauses[]`（`hypothesis` / `confidence` / `evidence`）、`actions[]`（`title` / `detail` / `expectedEffect` / `risk`） |
| 落库 | 只在 `param_audit` 写一条 `action="logs.analyze"`：字段名级别的 `fields:[from,to,process,level,q,sentLines,estimatedTokens,turnRows]` 与 `summary`（前 200 字），**不存原始日志、不存轮次明细、不存密钥、不存模型原文** |
| 走哪条路 | 优先回环 `POST http://127.0.0.1:8765/v1/chat/completions`（`llm_proxy` 的透传面）。未启用（`501`）或后端不是远程时 → `503 log_analysis_unavailable` 并在 UI 写“需 `ENABLE_LLM_PROXY` 且 LLM 后端为远程”；**不回退到本地模型**（那会把分析负载压到正在服务的 GPU 上，违反 4.3） |

### 3.11 音色制作与音色库（旁路）

TTS 音色不是“一个字符串参数”，而是一组互相约束的字段。本节把“制作一个音色”与“把音色写进配置”分成两件事：前者落在音色库（本节的表与文件），后者仍然只走 A.2–A.6 的草稿 / 版本 / 发布链路——**音色库不是第二条配置通道**。

#### 3.11.1 三种来源与字段绑定

| 来源 `source` | 含义 | `qwen3` 绑定字段 | `openai_compatible` | `kokoro` |
|---|---|---|---|---|
| `builtin` | 后端自带音色，只记名字 | `qwen3_tts_speaker` | `openai_tts_voice` | `kokoro_voice` + `kokoro_lang_code` |
| `clone` | 参考音频 + 逐字转写 → 说话人向量 | `qwen3_tts_ref_audio` + `qwen3_tts_ref_text`（运行时计算）**或** `qwen3_tts_ref_spk` + `qwen3_tts_ref_rvq` + `qwen3_tts_ref_text`（预计算），二选一 | 不支持（音色由提供商定义，只能选内置） | 不支持（`kokoro` 无参考音频入口） |
| `design` | 指令式音色设计 | `qwen3_tts_instruct`（要求 `qwen3_tts_model_name` 为 VoiceDesign 系） | `openai_tts_task_type=VoiceDesign` + `openai_tts_instructions` | 不支持 |

这张表是**唯一**的字段映射来源：前端 `VoicePicker` 与后端 `voice_service.bindings()` 共用同一张表（前端只拼 patch 做展示，后端在 A.3 校验时复算一遍）。`cosyvoice` / `omnivoice` 等 B4 目录化后端不在表里——它们的参考音频字段没有进机器目录（`docs/parameter-catalog.md` B4 只有后端级条目），所以参数页把它们渲染成 `catalogued:false` 的后端卡，不给可编辑控件、也不允许音色绑定。这是“不发明 catalog 之外字段”的直接后果，不是遗漏。

#### 3.11.2 制作流程（五步，全部在 console 进程）

| 步骤 | 交互 | 实现 | 失败 |
|---|---|---|---|
| 1 来源 | 选 `builtin` / `clone` / `design` | 纯前端 | — |
| 2 音频 | 录制（`MediaRecorder` → 16 kHz 单声道 WAV）或上传；上限 30 s / 10 MiB | `POST /api/v1/voices` 的 `audio` 分片；用标准库 `wave` 校验 PCM16 / 16 kHz / 单声道，不引入解码器 | `413 voice_too_large`、`400 voice_audio_invalid`（采样率 / 位深 / 声道 / 时长不符） |
| 3 试听与裁剪 | 波形 + 首尾裁剪手柄；试听走 `GET /api/v1/voices/{id}/audio`（Range），浏览器 `<audio>` 直接播 | 裁剪只改元数据 `trimStartMs` / `trimEndMs`，保存时按区间重写 WAV | — |
| 4 校对转写 | 逐字文本，必须与音频内容一致（catalog `qwen3_tts_ref_text` 的 `risk`：不是逐字转写会失真） | 前端**不**自动转写（那会把 STT 负载压到 pipeline），由操作人填写；非空才允许保存 | `422 validation_failed`（`detail[{field:"refText"}]`） |
| 5 预计算 + 命名 | 进度 `queued → loading → spk → rvq → done` + 失败原因；命名后进库与选择器 | `voice_precompute.py` 起**独立子进程**（`CUDA_VISIBLE_DEVICES=-1`），单并发 | `voice_precompute_failed`，`errorCode` 原样展示：`model_not_found` / `audio_too_short` / `oom_cpu` / `timeout` |

预计算产物写进 `qwen3_tts_ref_cache_dir` 指向的目录（默认 `/app/data/voices/<id>/`）：`spk.npy`、`rvq.npy`。`status=ready` 之前，该音色在选择器里显示“制作中”，不可绑定。`qwen3_tts_backend=ggml` 时跳过预计算，只保留 `ref_audio` + `ref_text` 两个字段（ggml 路径没有 spk / rvq 入口，详见 catalog 的 `qwen3_tts_ref_spk` 互斥说明）。

#### 3.11.3 表与文件

`voices`（迁移 `0003_voices.py`，与 `param_*` 同库不同表）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | varchar(26) PK | ULID，时间有序 |
| `name` | varchar(64) | 唯一（大小写不敏感），允许中文 |
| `source` / `backend` / `language` | varchar(16) | 见 §3.11.1 |
| `status` | varchar(16) | `draft` / `precomputing` / `ready` / `failed` |
| `audio_relpath` / `audio_bytes` / `audio_seconds` | varchar / int / float | 相对 `/app/data/voices` 的路径，**不存绝对路径** |
| `trim_start_ms` / `trim_end_ms` | int | 裁剪区间 |
| `ref_text` / `instruct` | text | 克隆的逐字转写 / 设计的指令 |
| `spk_relpath` / `rvq_relpath` | varchar | 预计算产物 |
| `error_code` | varchar(32) | `status=failed` 时非空 |
| `created_at` / `created_by` / `consent_ack_at` | datetime / varchar | 授权时间戳必须非空（A.18 强制） |
| `retention_days` | int | 默认 30，上限 180；到期由 lifespan 里的 sweep 清 |

文件：`/app/data/voices/<id>/{ref.wav,spk.npy,rvq.npy,manifest.json}`，目录 `0700`、文件 `0600`；`/app/data` 是卷（§4.2 的 `./data:/app/data`），不入 git、不进镜像层。`manifest.json` 只记 `id / name / source / backend / durationMs / createdAt`，**不写转写文本**。

#### 3.11.4 引入配置、引用计数与回滚

- 选中音色 → `VoicePicker` 按 §3.11.1 生成 patch（`{field: value}`）→ 走 A.3 存草稿；**不新增写通道**。`ref_audio` / `ref_spk` / `ref_rvq` 的值是容器内绝对路径 `<ref_cache_dir>/<id>/…`。
- 跨字段校验在 **A.3 的 validator**（早于 publish）：`ref_audio` 与 `ref_spk` 互斥 → `422 voice_binding_conflict`（`detail[{field, conflictWith}]`）；`ref_rvq` 缺 `ref_spk` / `ref_text` → 同码；`design` 但 `model_name` 非 VoiceDesign → 同码（`reason:"model_not_voicedesign"`）。失败停在草稿层，不会先重启 pipeline 再回滚。
- 审计只记字段名 + 音色 ID：`param_audit.detail.voiceRefs=[{field,voiceId}]`，**不记音频、不记转写文本**。A.8 原样返回该数组。
- 版本快照：YAML 里存的是路径，所以回滚天然跟随版本回退（旧版本指向旧音色目录）。若旧音色文件已被删除，回滚后 validator 报 `422 validation_failed`（`detail[{field:"qwen3_tts_ref_spk",reason:"file_missing"}]`），**不静默回退到内置音色**。
- 删除：`DELETE` 前数引用——`param_draft.draft` 与 `param_version.rendered` 里出现该 `id` 的路径即算引用；有引用 → `409 voice_in_use` + `detail[{field:"profiles",value:["prod"]},{field:"versions",value:12}]`。**草稿里的引用也要计入**，否则删掉后草稿直接失效。

#### 3.11.5 旁路与隐私（硬约束）

| 约束 | 做法 |
|---|---|
| 不占 pipeline 显存 | 预计算子进程 `CUDA_VISIBLE_DEVICES=-1`，在 CPU 上跑；`qwen3_tts_backend=ggml` 时跳过预计算（见 §3.11.2） |
| 不占 pipeline 事件循环 | 预计算是 console 进程 `asyncio.create_subprocess_exec` 出去的子进程，`VOICE_PRECOMPUTE_CONCURRENCY=1`；试听是静态文件 Range 读，不经过 8765 |
| 不阻塞会话 | 全程不调 `/internal/*`、不重启、不写 `config/`；验收项是「上传 + 预计算前后 `GET /v1/pool` 的 `in_use` 不变」（§14.7） |
| 生物特征 | 上传前必须显式勾选授权（`consent:"biometric-ack"`，缺省 → `400 voice_consent_required`），`consent_ack_at` 落库；界面写明留存期限与“到期自动删除” |
| 权限与落盘 | 目录 `0700`、文件 `0600`；日志只写 `voiceId` 不写路径值；`manifest.json` 不含转写；`/app/data` 不在 git、不在镜像 |
| 试听 | 只对已登录运维开放（A.0.2）；响应头 `Cache-Control: no-store`、`Content-Disposition: inline` |

## 4. 生效链路 A（重启）

适用：除 §2.2 四类字段外的全部参数（约 90%）。

### 4.1 流程

| 步骤 | 动作（均发生在 `console` 进程） | 失败处理 |
|---|---|---|
| 1 | `routers/profiles.py` 收 `POST /api/v1/profiles/{id}/draft`；`repositories/draft` 落 `draft` 与 `baseVersion`；`audit_service` 记一条 | `If-Match` 不匹配 → 409 `version_conflict` |
| 2 | `renderer_service` 生成 YAML 文本（**不落盘**），`validator_service` 调 `load_config` + `validate_config` | 422，错误带 `file:symbol` 与期望类型 |
| 3 | `validator_service` 调 `resolve_config`，检查 `{env:}` 引用的变量是否齐备 | 422，指出缺失的变量名（不回退默认） |
| 4 | `validator_service` 做显存预算：`num_pipelines <= floor(可用显存GB × 0.85 / 4.6)` | 422，给出当前卡型号与允许上限 |
| 5 | publish 前置门禁：若 draft 触及 `.env` 类字段（`stage=env`）→ `409 env_requires_recreate`，**不写盘、不版本化**（§4.2） | 提示管理员在部署窗口执行 recreate；`detail[]` 只列变量名。**必须在落版本之前判定**，否则会留下一条永远无法生效的 `publishing` 行 |
| 6 | publish：`repositories/version` 落不可变版本（状态 `publishing`）；`renderer_service` 写 `/app/config/<profile>.yaml`，旧文件备份为 `.bak.<version>` | 写失败保留旧文件并告警，版本标 `aborted` |
| 7 | `restart_runner` → `supervisor_client.restart("pipeline")`：先 `stopProcess(wait=True)` 再 `startProcess`，等回 `RUNNING` | socket 不可达 → 版本标 `aborted` 并恢复 `.bak`；单次重启超时 60s |
| 8 | 轮询 `GET http://127.0.0.1:8765/v1/pool` 直到 `size == <num_pipelines>` 且 `in_use` 在下降；超时 180s | 视为失败，进步骤 9 |
| 9 | 回滚：恢复 `.bak.<version>` + 再重启 + 再探 `/v1/pool` | 回滚也失败 → `failed`，告警人工介入，保留 supervisor 与 pipeline 最近 200 行日志 |

步骤 2–9 在**同一进程**内串行完成：`publish_flow` 以 profile 为键持进程内锁，同一 profile 同时只能有一个发布（多 worker 会各持一把锁，故 `console` program 必须单 worker，见 §3.1）。

**启动自检**（必须实现，否则会留下中间态）：console 进程启动时扫描版本表，若发现 `publishing` 悬挂（上一次发布在步骤 6–9 之间被容器重建打断），立即做一次恢复判定：探 `/v1/pool`，健康且盘上 YAML 与版本字节一致 → 标 `live`；否则恢复 `.bak` + 重启 + 标 `rolled_back`。

**与容器重建的语义差异**（必须写进 UI）：

| 场景 | 旧设计（重建容器） | 本设计（重启子进程） | 差异后果 |
|---|---|---|---|
| 发布耗时长 | 10–60s，控制台全程失联 | 5–15s，**控制台不掉线** | 运维可以在发布后直接轮询状态 |
| 发布时在聊会话 | 全断 | 全断 | 相同；UI 发布前必须二次确认 |
| `.env` 变更 | 随重建生效 | **不生效**，直接 409 | 需宿主 `compose up -d --force-recreate`（§4.2） |
| 镜像/代码变更 | 重建即生效 | 不适用（不重启容器） | 升镜像仍需宿主 recreate |

### 4.2 YAML 与 ENV 的两种生效方式（必须分开）

文件模式只接受 `-f/--file` 与 `--name`，其余参数必须写进 YAML（`cli.py:_run_file_command`：`File mode accepts only --file and --name`）。因此 compose 服务的 `command` 需要从当前 40+ 个 CLI 开关改为：

```yaml
command: [speech-to-speech, serve, -f, /app/config/prod.yaml, --name, prod]
env_file: ./config/prod.env          # 容器创建时注入，进程重启拿不到新值
volumes:
  - ./config:/app/config            # 容器内可写（唯一写入方是 console 进程）
  - ./data:/app/data
```

`serve` 要求恰好选中一个 definition（`cli.py`：`serve and local require exactly one selected definition; use --name`），故 `--name` 不可省。这一改动意味着 **compose 的 command 由固定模板维护**，console 只能重启子进程，**不生成也不改写 compose 文件**。

两个文件的生命周期完全不同：

| 文件 | 读取时机 | 改完怎么生效 | 控制台能不能代办 |
|---|---|---|---|
| `config/<profile>.yaml` | 子进程启动时（`-f`） | `supervisorctl restart pipeline` | **能**（步骤 7） |
| `config/<profile>.env` | **容器创建时**（`env_file` → 进程环境） | 只能 `docker compose up -d --force-recreate pipeline` | **不能**，直接 409（§4.1 步骤 5） |

这条差异是本次拓扑变更带来的最大行为倒退，必须显式告知：**`.env` 类参数在控制台里可以看、可以校验（按候选 env 解析 `{env:}`），但发布被拒**，并给出可复制的 recreate 命令。校验按“候选 env”而非 console 进程自己的 `os.environ`，否则新建变量会被误判为缺失（§11.2）。

“谁写、谁读”现在是同一个容器同一路径，不再有双容器路径错位问题（旧 R18）：

| 角色 | 路径 | 权限 | 行为 |
|---|---|---|---|
| `console` 进程 | `/app/config` | **rw** | `renderer_service` 写 `<profile>.yaml`，旧文件改名 `.bak.<version>`；`.env` 只在“要求 recreate”时写入 |
| `pipeline` 进程 | `/app/config` | **ro**（自身不做写入） | 只通过 `-f /app/config/prod.yaml` 读取，环境变量来自容器 |

### 4.3 版本状态机

```
draft ──validate──▶ validated ──publish──▶ publishing ──healthcheck ok──▶ live
  │                    │                       │
  └──abandon           └──reject               ├──restart failed──▶ aborted（已恢复 .bak）
                                               └──healthcheck fail──▶ rolled_back
                                                                        │
                                                         ──rollback fail──▶ failed(需人工)
```

只有 `live` 与 `rolled_back` 可被 `rollback` 指向；`draft` 不入版本历史。`env_requires_recreate` **不是版本状态**：它在写盘前就被拒，不产生版本行，所以在版本列表里看不到。

## 5. 生效链路 B（热更新）

适用：§2.2 表中 4 类字段。

### 5.1 源码最小改动点

| # | 文件 | 改动 | 性质 |
|---|---|---|---|
| 1 | `api/openai_realtime/websocket_router.py` | 在 `create_app()`（当前 `510-514` 行，与 `/v1/pool`、`/v1/usage` 同级）新增 `POST /internal/sessions/update` 路由 | 新增路由，不触碰既有路由 |
| 2 | `api/openai_realtime/service.py` | 新增只读访问器（如 `active_connection_ids()`）暴露 `_conns` 的键集合，供 fanout 枚举；`_conns` 当前仅私有（`service.py:384`） | 新增方法，不改既有逻辑 |
| 3 | （可选）`service.py:register()` | 把单值 `_default_instructions` 换成"平台默认值对象"，让新连接读到最新默认人设 | 后续阶段，非本期必需 |

路由内部：构造 `SessionUpdateEvent` 并逐目标调用 `SessionHandler.handle_session_update`，复用其合并、语言校验、`invalid_session_type` 拒绝逻辑——**不复制一份校验代码**。

端点名从原设计的 `/admin/sessions/update` 改为 `/internal/sessions/update`，原因是 console 自己也有一整组 `/api/v1/*` 路由，两边同叫 `admin` 会让日志、告警与审计无法区分“改文件”与“改会话”。`/internal/*` 只接受来自 console 进程的机对机调用，**不经 8000 反代暴露**（语音面只透传 `/v1/*`）。

同容器后仍然保留机对机 token，不是冗余：8765 在容器内对所有进程可达，没有 token 就没有任何东西区分“console 发的”与“其他进程/误配的试请求”；且一旦将来拆回双容器（例如为隔离 GPU 资源），这条链路不需要重写。

### 5.2 鉴权

pipeline 侧的 `/internal/*` 不建立用户体系，只验证机对机 token：`S2S_INTERNAL_TOKEN` 环境变量提供 token，缺失时路由**一律 503 拒绝**（fail closed，不回退为无鉴权）。请求头 `Authorization: Bearer <token>`，比较用 `hmac.compare_digest`。

`console` 侧呈现为两个动作：

| 谁 | 凭证 | 失效表现 |
|---|---|---|
| 运维人员 → console | JWT（`Authorization: Bearer <access_token>`） | 401，前端跳登录 |
| console → pipeline `/internal/*` | `S2S_INTERNAL_TOKEN`（环境变量注入，不落库、不回显） | pipeline 返 503，console 转成 502 `pipeline_token_missing` 并提示运维检查 `.env` |

### 5.3 请求语义

```http
POST http://127.0.0.1:8765/internal/sessions/update
Authorization: Bearer <S2S_INTERNAL_TOKEN>
Content-Type: application/json

{
  "scope": "all",
  "session": {
    "instructions": "你是简洁的语音助手，每次回复不超过两句话，跟随用户语言。",
    "audio": { "input": { "turn_detection": { "interrupt_response": true } } }
  }
}
```

- `scope=all`：向所有 pipeline 的所有活跃连接 fanout；
- `scope=pipeline` + `target=<index>`：只 fanout 该 unit；
- `scope=session` + `target=<session_id>`：只 fanout 单条连接。

响应返回 `{"updated": [...], "failed": [{"session_id": ..., "error": ...}]}`。部分失败不整体回滚——热更新是幂等覆盖写。

### 5.4 行为约束（必须写进 UI 文案）

| 约束 | 原因 | 后果 |
|---|---|---|
| 只影响**当前活跃**连接 | fanout 基于 `_conns` | 新连接读 `init_chat_prompt`，与热更新值可能不一致 |
| 空闲 unit 无连接可 fanout | `unit.session is None` | "改默认人设"必须同时改 YAML 并重启，否则重启后又回到旧默认 |
| 不支持 `transcription` 类型会话 | `handlers/session.py:36-40` 返回 `invalid_session_type` | 必须用 `realtime` 类型会话 |
| `language` 必须被活跃后端支持 | `handlers/session.py:52-63` | `auto` 需 `stt_auto_reset_supported`，否则 400 |
| `model` / `voice` 不生效 | §2.2 取证 | UI 不得把这两个字段放进热更新面板 |

## 6. 参数条目规范

每个参数一条记录，13 字段（10 基础 + 3 平台扩展）。YAML 目录用同名 14 字段（多一个 `stage` 分组键）。

| # | 字段 | 含义 | 取值/约束 | 示例 |
|---|---|---|---|---|
| 1 | 参数名称 | 源码字段名或 YAML 路径 | 与源码逐字一致 | `min_silence_ms` |
| 2 | 作用 | 一句话说明对人可感知的影响 | 不写实现细节 | 「判定用户说完话所需的静音时长」 |
| 3 | 模块/文件 | 字段定义位置 | 文件名 + 符号 | `arguments_classes/vad_arguments.py:min_silence_ms` |
| 4 | 默认值 | 源码默认值 | 必须带 `file:symbol` 溯源 | `700` |
| 5 | 范围/格式 | 类型与合法区间 | 枚举需列全 | `int, 0..2000` |
| 6 | 必填 | 是否必须显式给出 | `是` / `否` | `否` |
| 7 | 来源优先级 | 取值链 | 见 §8 | `yaml > env > default` |
| 8 | 生效方式 | 何时生效 | `启动` / `热更新` / `启动+热更新` / `固定` | `启动` |
| 9 | 建议暴露 | 默认暴露级别 | `basic` / `advanced` / `expert` / `ops` | `advanced` |
| 10 | 风险 | 配错的表现 | 一句话，可操作 | 「过高→开头被截，过低→误触噪首」 |
| 11 | 暴露级别 | 最终分级（可被 profile 覆盖） | 同字段 9 | `advanced` |
| 12 | 影响面 | 改动波及范围 | `process` / `pipeline` / `session` / `container` | `pipeline` |
| 13 | 变更代价 | 生效所需时间 | `seconds` / `restart` / `minutes` | `restart` |

`stage` 枚举固定为 `vad|stt|llm|tts|runtime|server|client|deploy|env`，通用层参数 `backend: null`。

### 6.1 196 条的落点矩阵（先清点，再改）

`docs/parameter-catalog.yaml` 是唯一事实来源；本文、计划、预览页出现的参数名 / 默认值 / 层级 / 生效方式都以它为准（`generated_at` 见文件头，三者不一致时先重生成 catalog 再改文档）。按“运维面能不能改”分三类，计数相加必须等于 196：

| 类 | 条数 | 判据 | 落点 |
|---|---|---|---|
| 已覆盖 | 120 | `stage ∈ {vad, stt, llm, tts, runtime, server}` 且 `type ≠ fixed` | `ParamTree` 分组 + `ParamField` 通用渲染（Task 12）；链路按 §2.4 的徽标落 A.2–A.6 或 A.9 |
| 待补（本轮新增形态） | 16 | 音色绑定 14 条 + 人设双动作 2 条（`init_chat_prompt` / `session.instructions`） | `VoicePicker` / `VoiceCreateDialog` / `VoiceLibraryView`（§3.11、A.18）；人设走“两动作”提示块（§5.4） |
| 明确不暴露 | 60 | `type=fixed` 17 + `stage=deploy` 16 + `stage=env` 18 + `stage=client` 18 − 交集 9（deploy 里的 fixed） | 只读行：写“不可配置”+ 原因 + `source_ref`；无输入控件、无 `↺`、不进 patch |

音色绑定 14 条（`(stage, backend, name)` 逐条）：`tts/qwen3` 的 `qwen3_tts_speaker`、`qwen3_tts_ref_audio`、`qwen3_tts_ref_text`、`qwen3_tts_ref_spk`、`qwen3_tts_ref_rvq`、`qwen3_tts_ref_cache_dir`、`qwen3_tts_instruct`、`qwen3_tts_backend`、`qwen3_tts_model_name`、`qwen3_tts_xvec_only`；`tts/openai_compatible` 的 `openai_tts_voice`、`openai_tts_task_type`、`openai_tts_model`；`tts/kokoro` 的 `kokoro_voice`。

60 条不暴露有四种原因，界面文案固定：

| 原因 | 条数 | 文案 |
|---|---|---|
| 源码常量 / 编排写死 | 17 | `不可配置 · 源码常量` + `source_ref`（如 `service.py:110 CHUNK_SAMPLES`）；含 `deploy` 里的 9 条 fixed |
| 部署事实（compose / Dockerfile） | 7 | `平台维护 · 改它要重建镜像` + 文件与键路径；`deploy` 共 16 条，其中 9 条 fixed 已计上一类 |
| 环境变量（`env_file` 注入） | 18 | `需重建容器` + 草稿里可校验、publish 被 `409 env_requires_recreate` 拒绝（§4.2） |
| 浏览器侧 CLI | 18 | `属对话页客户端，不在运维面` + `api/openai_realtime/audio_client.py` |
| **合计** | **60** | 17 + 7 + 18 + 18，与上表的「明确不暴露」相等 |

**按名去重**：196 行里只有 3 个重名——`log_transcripts`（`client` + `runtime`）、`model_name`（`llm` + `llm/responses-api`）、`responses_api_reasoning_effort`（`llm/chat-completions` + `llm/responses-api`）。规则固定：**服务端优先于客户端**（`log_transcripts` 取 `runtime`）、**名字前缀所属 backend 优先**（`responses_api_reasoning_effort` 取 `responses-api`）、`model_name` 取通用 `llm` 组；被合并的两条以 `aliases` 出现在详情里，树与表单各只出现一次。因此界面总计数写 `196 条 · 193 个唯一名 · 2 个多后端字段`。

17 个分组的条目数（分组名与条数都必须三处逐字相等；`· 通用` 对应 `backend=null` 的组，`ParamTree` 固定渲染 `· {{ group.backend ?? '通用' }}`）：

| 分组 | 条数 | 分组 | 条数 |
|---|---|---|---|
| `vad · 通用` | 19 | `tts · qwen3` | 23 |
| `vad · firered` | 2 | `tts · openai_compatible` | 13 |
| `stt · qwen3-asr` | 6 | `tts · kokoro` | 6 |
| `stt · openai_compatible` | 7 | `runtime · 通用` | 33 |
| `stt · parakeet-tdt` | 3 | `server · 通用` | 2 |
| `llm · 通用` | 10 | `deploy · 通用`（只读） | 16 |
| `llm · transformers` | 9 | `env · 通用`（只读） | 18 |
| `llm · responses-api` | 10 | `client · 通用`（只读） | 18 |
| `llm · chat-completions` | 1 | **合计** | **196** |

## 7. 暴露分级策略

### 7.1 判定条件

按"谁能改、改错的后果有多重"四级判定，**取最严格的那一级**：

| 级别 | 判定条件（满足任一即归入） | 典型字段 |
|---|---|---|
| `basic` | 语义对非工程人员直观；配错最坏结果是体验差，不会不可用 | `instructions`、`voice`（展示用）、`min_silence_ms` |
| `advanced` | 需要懂音频/模型基础；配错会导致断句异常或音质劣化，但服务仍可用 | `thresh`、`qwen3_tts_streaming_chunk_size`、`stream_batch_sentences` |
| `expert` | 需要懂推理栈与硬件；配错可能 OOM、崩进程或显著变慢 | `num_pipelines`、`device`、`qwen3_tts_max_new_tokens`、`smart_turn` 相关阈值 |
| `ops` | 触碰安全边界、隐私数据或环境绑定；**改错会泄露、越权或换环境失效** | `host`、`enable_llm_proxy`、`*_api_key`、`log_transcripts`、`HF_HUB_OFFLINE` |

### 7.2 `ops` 必须标注风险类别

`exposure=ops` 的条目在 catalog 中 `risk` 字段必填，且必须能归入以下三类之一：

| 类别 | 判据 | 代表字段 | 平台动作 |
|---|---|---|---|
| **安全** | 扩大攻击面或绕过鉴权 | `host=0.0.0.0`（`/v1/*` 无鉴权）、`enable_llm_proxy`（自带代理无鉴权）、`responses_api_api_key` | 只允许管理员改；改 `host` 需二次确认；密钥只写不读 |
| **隐私** | 会落盘或外泄用户语音/文本 | `log_transcripts`（落转写全文）、`log_level=debug`（含内容） | 默认关闭；开启需审计记录操作人 |
| **环境绑定** | 换机器/换镜像后取值失效 | `HF_HUB_OFFLINE`、`TRANSFORMERS_OFFLINE`、GPU `device_ids`、端口映射、`qwen3_*_model_name` 路径 | 标记"随环境变化"；回滚时不跨环境复用 |

目录中 `ops` 条目共 52 条，全部带风险描述。

### 7.3 层级 → 控件形态

| 级别 | 展开方式 | 控件 | 附加 |
|---|---|---|---|
| `basic` | 直出（分组展开即见） | 原生控件（`a-input` / `a-switch` / `a-select`） | 一句话作用说明；catalog 无 `description` 时用 `source_ref` 的符号名，不编造 |
| `advanced` | 直出 | 同上 | 显示 `default` 与建议区间；`chips` 给 2–3 个常用值（如 `min_silence_ms: 500 / 700 / 900`） |
| `expert` | `a-collapse` 折叠，默认收起 | 同上 | 折叠头带 `expert` 徽标；展开后顶部一句警告，文案取 catalog `risk` |
| `ops` | 折叠 + 二次确认 | 同上；密钥用 `SecretField` | 必须先显示风险类别徽标 `安全` / `隐私` / `环境绑定`（§7.2）；类别从 `risk` 前缀解析，解析不出一律按 `安全` 处理并标红 |

`type=fixed` 的条目无论 `exposure` 为何都渲染成只读行（§6.1），**不套用上表**。`operator` 角色下 `expert` / `ops` 渲染为只读（`v-permission` + 后端 403 双保险），但**仍然显示**——隐藏会让人以为参数不存在。

## 8. 来源优先级

### 8.1 主链路

```
显式 YAML 字段 / CLI 参数（最高）
  > {env: NAME} 引用（缺失即报错，不回退默认值）
    > dataclass 字段默认值（最低）
```

注意 `{env: NAME}` 不是"更低的优先级"，而是**延后取值的显式值**：写它就等于声明"这个值必须来自环境"，因此环境缺失是硬错误而非回退到默认（`docs/configuration.md:112`：`Missing explicit environment values fail even when a backend has a credential fallback`）。

### 8.2 覆盖型规则

| 规则 | 出处 | 说明 |
|---|---|---|
| `device` 覆盖 `*_device` | `module_arguments.py:device` | 进程级 `device` 一旦显式给出，覆盖各组件自己的 `*_device` |
| `mac_optimal_settings` 提供预设 | `module_arguments.py:mac_optimal_settings` | 预设先铺底，同名字段的显式值再覆盖预设 |
| `pipelines.<name>.options` 覆盖 `runtime` | `config.py` 三层结构 | pipeline 级选项优先于进程级 runtime |
| `session.update` 覆盖已解析会话字段 | `runtime_config.py:10-24` | 只合并 `model_fields_set` 中的字段 |
| `response.instructions` 覆盖会话 `instructions` | `base_openai_compatible_language_model.py:972-974` | 单次响应可临时覆盖人设 |
| `init_chat_prompt` 仅作新连接种子 | `s2s_pipeline.py:635-643` → `service.py:416` | 不改已有连接 |

### 8.3 平台侧落地

`validator` 必须按此顺序复算，**不允许**在平台侧再定义一套默认值：默认值一律读 catalog（其 `default` 与 `source_ref` 同源）。

## 9. 与既有能力复用

复用分四种，不是一种：**调接口**（不改对方代码）、**移植纯逻辑**（拷代码 + 重写测试）、**功能重写**（保留行为、换实现）、**不复用**。

同容器后"调接口"多了一层限定：被调方虽在同一容器内，但仍在回环 `127.0.0.1` 上以 HTTP/WS 走一圈，**不改成同进程函数调用**——否则两套代码共用一个解释器与一个事件循环，pipeline 崩溃会连带 console（§12 R19），且链路 B 的"跨进程下发"语义会消失。

### 9.1 对 pipeline 与既有运维逻辑

| 既有能力 | 出处 | 复用方式 | 不复用/不复制的部分 |
|---|---|---|---|
| `/v1/pool` | `websocket_router.py:639-674` | 链路 A 健康检查唯一数据源：`{size, in_use, units[{index, state, session_id, draining_for_s, stuck_for_s}]}`，`state ∈ idle/active/draining/stuck`，由 `restart_runner` 以 httpx 调用 `http://127.0.0.1:8765/v1/pool` | 不新增探活端点（同容器也不复用 healthcheck 脚本领，两套判定会漂移）；`stuck` 单独告警，不归入 publish 失败 |
| `/v1/usage` | `websocket_router.py:615-637` | 实例视图的用量段：逐 unit 汇总 + `llm_proxy` | 不重算指标 |
| pipeline `/internal/sessions/update` | 本期新增（§5.1） | 链路 B 唯一下发通道，由 `hot_update` 以 httpx 调用 | console **不**直接操作 `_conns`，也不复制 `handle_session_update` 的校验 |
| `demo/param_platform/` 的纯逻辑 | `layout.py`、`renderer.py`、`validator.py` | **移植**：函数级逻辑（catalog → YAML 路径、字节级稳定渲染、双模校验）搬进 `console/backend/app/services/`，行为保持不变 | 不作运行时依赖；`routers` / `store` / `drafts` / `publish_flow` 按新分层重写 |
| `demo/param_platform/compose_runner.py` | 329 行 | **重写为 `restart_runner`**：只保留"执行 → 轮询 → 超时 → 失败回退"的骨架，执行体换成 XML-RPC 调 supervisor（§10.3） | 不再拼 `docker compose` 命令、不再解析 `docker logs`；compose 相关分支与 `S2S_HOST_ROOT` 路径补丁（旧 R18）整体删除 |
| `speech_to_speech` 包本体 | `config.py` 的 `load/validate/resolve` | **同镜像直接 import**，`validator` 常态即 `mode=runtime` | 只 import 配置层（`config`、`arguments_classes` 的数据类），不 import `s2s_pipeline` / `service` 等运行期模块——那会把 torch 与全局状态拖进 console 进程 |
| `docs/configuration.md` | `99-134`（值/路径/校验语义） | 作为 YAML 语义的**唯一权威引用** | catalog 不复制其语法说明，只给结论并链接 |
| `utils/model_monitor.py` | `METRICS_LOG_PATH`（`:50`）、`MAX_BYTES`（`:51`）、`BACKUPS`（`:52`） | 「模型调用耗时」字段的数据源，实例视图只读展示 | 不改造其轮转逻辑 |
| `demo/auth.py` | `attach`（`:62`）、`resolve_identity`（`:263`）、`resolve_tier`（`:216`） | **移植**为 `services/identity_service.py`：HF OAuth 回调、匿名 cookie、tier 映射（§3.2.3） | 运维面角色仍由 `console_users` 表定义，**不**把 demo 的 tier 映射成 `admin`/`operator`（§1.3） |
| `demo/limiter.py` | `begin/heartbeat/end/sweep`、`budget_for`、`sign_cookie` | **移植**为 `services/metering_service.py`：每日配额、排队位次、签名 cookie，存储沿用裸 `sqlite3` + `/app/data/usage.sqlite3`（D11） | 参数平台的发布/回滚不经过它；两套存储各管各的，不共用一个连接池 |

### 9.2 对 demo 演示面的复用（本次新增）

| 既有能力 | 出处与规模 | 复用方式 | 说明 |
|---|---|---|---|
| 语音对话页 | `index.html` 39KB、`main.js` 70KB、`style.css` 76KB、`ui/chat.js` 31KB、`ui/account.js` 13.7KB、`ui/dom.js`、`s2s-realtime-client.js` 40KB、`turn-latency.js`、`ws/*.js` 4 个、`worklets/*.js` 2 个 | **功能重写**为 `console/frontend/src/features/voice/*`（成分见 §3.2.2 二十行表） | 行为逐项对齐；DOM 结构与 CSS 不逐行搬运，只保留 orb 九态 / 噪声门弧 / 气泡与抽屉 / 轮次延迟这几块的视觉参数 |
| `demo/server.py` 的 11 组演示面路由 | `GET /api/config`、`GET /api/me`、`POST /api/search`、`POST /api/calls`、`POST /api/session`、`GET` 与 `DELETE /api/queue/{id}`、`POST /api/queue/end`、`POST /api/session/heartbeat`、`POST /api/session/end` | **移植**到 `routers/demo/*`，路径、方法、载荷形状与状态码**保持字节兼容**（B10，逐条契约见 §15 A.13） | 不套 `ApiResponse`；这是全仓唯一允许偏离统一包络的接口组，因为浏览器侧客户端已按该形状写死 |
| 启动期钩子 | `@app.on_event("startup")`：`store.init()`、条件 `limiter.init()`、`asyncio.create_task(_sweeper())` | 合并进 console 的 lifespan：先建表（SQLAlchemy + Alembic）、再条件启 `metering`、最后起 sweeper | 三个动作的顺序不能变：sweeper 依赖 `metering` 已建表 |
| `/vendor/openai-realtime-agents.umd.js`、`/vendor/local-vad/{6 资产}` | `server.py` 运行时优先读 `demo/vendor/`，否则回退 `node_modules/...`，缺失返 503 | **改为构建期复制**（D10）：`scripts/copy-vendors.mjs` 从 `node_modules` 拷到 `public/vendor/`，随 `dist/` 烤进镜像 | 运行期不再探测 `node_modules`；漏拷在构建期就失败，而不是上线后 503 |
| `StaticFiles(html=True)` 兜底 | `server.py` 末尾挂 `/` | 由 `core/spa.py` 接管：`/console/*` 与其余路径分别回落到对应 `index.html`，并对 `index.html` 禁用强缓存 | 顺序变了：必须先注册 `/api`、`/vendor`、`/v1`，最后才 mount 静态目录，否则会把接口一起吞掉 |
| 前端构建工具链 | `package.json` 用 `node --test` 跑 12 个 `.mjs` | **不搬迁**：逻辑层改由 Vitest（node 环境）覆盖，旅程由 Playwright 覆盖（D8） | 断言内容可参考这 12 个文件，但测试运行器与目录跟随 `console/frontend` |
| `demo/` 工程壳 | `Dockerfile`（54 行，含 node 构建阶段）、`requirements.txt`、`s2s-params.sqlite3` | **不复用**：镜像与依赖清单由 s2s 统一提供 | `demo/` 在 P5 整体归档（§14.2） |

## 10. 安全、鉴权与回滚

### 10.1 安全

| 项 | 要求 |
|---|---|
| 三面鉴权 | 三层且互不代理：① 运维人 → 运维面 `/api/v1/*` 用 JWT（`sub` + `exp`，HS256）；② 访问者 → 演示面 `/api/*` 用匿名 cookie 或 HF OAuth 会话（§9.2）；③ console → pipeline `/internal/*` 用 `S2S_INTERNAL_TOKEN`。三个密钥都只从环境读，不入库、不回显。同容器**不取消** ③：保留它才能让 pipeline 侧保持"未配置即 503"的 fail-closed 行为（§5.1） |
| 角色 | `admin`（可发布/回滚/改 `expert` 与 `ops` 字段）、`operator`（只能改 `basic` / `advanced` 并发起 draft）。判定在后端，不在前端 |
| JWT 密钥 | `JWT_SECRET_KEY` 至少 32 字节随机值，只存 `.env`（`0600`）；轮换 = 所有已发 token 立即失效，需在发布说明里写明 |
| 密码 | bcrypt 存哈希（`bcrypt.hashpw` + `gensalt`）；登录失败 5 次/5 分钟按 IP 节流；无自助注册 |
| 密钥字段 | 只写不读：读接口一律返回 `***`，长度与字符集不外泄；日志与审计只记字段名 |
| 明文配置 | `config/*.yaml` 只放 `{env: NAME}`，真实密钥只进 `.env`（`0600`） |
| 审计 | 每次 draft/publish/rollback 记：操作人（JWT `sub` → 用户名）、版本号、字段 diff（只记名与旧值指纹，不记密钥值）、结果、耗时、`requestId` |
| 网络暴露 | 宿主只发布一个端口 `8000`；`8765` 由 supervisord 里的 pipeline 绑 `127.0.0.1`、**不 publish**；PG（可选 profile）不映射。于是"pipeline 的 `/v1/*` 无鉴权"这件事在拓扑上就不可被外部直达，只能经 console 的 `/v1/realtime*` 反代进来 |
| 反代入口 | `/v1/realtime*` 是唯一把外部请求送进 8765 的通道（§10.2.3）。转发**不注入、不剥离**身份：pipeline 侧的鉴权语义与 demo 阶段一致，不引入新的放行条件，也不把运维 JWT 传下去 |
| 安全响应头 | 由 `console/backend/app/core/middleware.py` 的 Starlette 中间件统一加 `X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: same-origin`；HTML 响应额外加 CSP：`default-src 'self'; connect-src 'self' ws: wss:; worker-src 'self' blob:`（blob 是本地 VAD 的 wasm/worker 需要）。**无 `client_max_body_size`**，改为中间件按 `Content-Length` 拦 2 MiB 以上请求 |
| 演示面身份 | 匿名 cookie（`sign_cookie`）或 HF OAuth 会话，与运维 JWT **完全独立**：`/api/*` 只认前者，`/api/v1/*` 只认后者，两个前缀的依赖注入不共享。OAuth 未配置（无 `SPACE_ID`）时 `AUTH_ENABLED=false`，`/api/me` 返回匿名身份而非 401 |
| 静态资产完整性 | `/vendor/*` 只从构建期烤入的固定目录读，路径先做 `Path.resolve()` 白名单校验禁 `..`；缺失返回 503 `asset_missing`（与 `demo` 一致的语义，只是原因从"没跑 npm ci"变成"镜像少资产"） |
| 参考音频（生物特征） | `voices` 的音频是生物特征：必须 `consent_ack_at` 非空才能保存，`retention_days` 上限 180 且到期真删文件；目录 `0700`、文件 `0600`；不写日志值；不入 git、不进镜像；试听接口同样受 JWT 保护（§3.11.5） |

### 10.2 鉴权、跨域与反向代理

#### 10.2.1 登录与令牌

```
POST /api/v1/auth/login  {username, password}
   → 200 data{accessToken, tokenType:"bearer", expiresIn:1800, refreshToken, user:{username, role}}
POST /api/v1/auth/refresh {refreshToken}
   → 200 新的 accessToken（refresh 有效期 7 天，rotation 不强制）
GET  /api/v1/auth/me
   → 200 data{username, role, lastLoginAt}
```

（字段命名以 A.0 为准：HTTP 载荷 camelCase。）

有效期对齐 MinWorkBuddy：`JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30`、`JWT_REFRESH_TOKEN_EXPIRE_DAYS=7`。前端在响应拦截器里遇 `401` 先试一次 `refresh`，仍失败则清 token 跳 `/login`；**不在前端做无感重试以外的绕过**。

#### 10.2.2 跨域

同容器同端口后，生产态**没有任何跨域场景**：页面、`/api/v1/*`、`/api/*`、`/vendor/*`、`/v1/realtime` 全在 `:8000` 一个 origin 上。CORS 只服务一个残余场景——开发态前端在 `:3000` 直连 `:8000`。

| 场景 | 做法 | 是否需要 CORS |
|---|---|---|
| 开发（`vite dev` :3000） | 首选 Vite `server.proxy` 把 `/api`、`/vendor`、`/v1` 都转发到 `http://localhost:8000`（`/v1` 需 `ws: true`） | **不需要**（浏览器看到同源） |
| 开发直连调试（不开 proxy） | `CORS_ORIGINS` 白名单生效 | 需要 |
| 生产（`:8000` 同源） | 无跨域请求 | **不需要**，且 `CORS_ORIGINS` 为空时根本不注册中间件 |

`CORS_ORIGINS` 默认只含 `http://localhost:3000,http://127.0.0.1:3000`；因 `allow_credentials=True`，**不得写 `*`**（与 MinWorkBuddy `main.py` 的 CORS 配置同一个坑）。生产 profile 下**必须留空**：留空即不装中间件，比"装了但白名单不命中"更难被误配（D7 的落地方式）。

#### 10.2.3 反向代理（进程内实现，不是 nginx）

四条反代职责全部由 `routers/realtime.py` 与 `core/spa.py` 承担，没有边车（D7）：

| 路径 | 实现 | 关键约束 |
|---|---|---|
| `/v1/realtime`（WebSocket） | `websockets.connect("ws://127.0.0.1:8765/…")`，双向 `asyncio.gather` 转发；一侧关闭即关另一侧 | 必须原样转发 `Sec-WebSocket-Protocol`（Realtime 协议用它协商子协议）；不得缓冲帧，否则 TTS 首字节延迟被放大（§12 R20） |
| `POST /v1/realtime/calls`（SDP） | httpx 流式转发到 `http://127.0.0.1:8765/v1/realtime/calls`，`Content-Type: application/sdp` | 不回填绝对 URL/`Location`（否则指向回环地址，浏览器拿不到）；上游 4xx/5xx 原样透出 |
| `/`、`/console/*` | `StaticFiles(html=True)` 兜底，未知路径回落对应 `index.html` | 必须先注册 `/api`、`/vendor`、`/v1` 再 mount `/`；`index.html` 不缓存，带 hash 的资源长缓存 |
| `/vendor/*` | `asset_service` 从固定目录直出，`immutable` 长缓存 | 同一份 UMD 只允许一个版本（`@openai/agents` 0.14.3），升级靠镜像 tag 而非运行期探测 |

三个不能改的点：反代**不做路径重写**（否则 `/v1/realtime` 被吞成 `/`，上游 404）；WebSocket 断开必须是**双向**的（客户端关或上游关都要终止另一侧，否则回环端口积压僵尸连接）；前端**不把 upstream 地址烘进构建产物**（D1）——页面只认同源相对路径。

### 10.3 权限面：supervisor 套接字

不再需要 docker。console 进程能做的破坏被压缩到一件事：**启停容器内的 `pipeline` program**。靠四层收窄：

| 措施 | 说明 |
|---|---|
| 只开一个 unix socket | `/run/s2s-console/supervisor.sock`，`chmod 0700`、属主为容器内同一用户；**不启 `[inet_http_server]`**，所以从网络侧无法访问 |
| 只允许固定动作 | `supervisor_client` 只暴露 `restart(name)`（`stopProcess(name, wait=True)` + `startProcess(name)`）与 `getState(name)`；program 名从 `SUPERVISOR_PROGRAM=pipeline` 读，不从请求体取 |
| supervisord 配置由镜像提供 | `console/deploy/supervisord.conf` 只声明两个 program 与一个 group；不启用 `[supervisorctl]`，不额外开放 `[rpcinterface:*]` 以外的能力 |
| 不降级的失败语义 | socket 不可达 → `502 restart_unavailable`，版本标 `aborted` 并恢复 `.bak`；不得"跳过重启直接标 live" |
| 日志边界 | console 只 `tail` 读 `/var/log/supervisor/pipeline-std*.log`（仅在上游日志接口不可用时兜底），**不写** pipeline 日志，也不把 loguru 装到根 logger（D13） |

代价要写明：容器内一个 RCE 仍可重启 pipeline（拒绝服务），但**不能**创建容器、挂载宿主目录或提权——这与旧设计"持 docker.sock ≈ 宿主 root"差一个量级（§12 R11）。

### 10.4 回滚

- 配置版本**不可变**：publish 产生新版本，旧版本永不改写；回滚 = 指向上一个 `live` 版本并重新执行链路 A 的步骤 5–9（写盘 → 重启 → 探活 → 失败再回退）。
- 回滚粒度是整份 profile，不是单字段（单字段回滚 = 编辑新 draft 后发布）。
- 回滚触发条件：步骤 7 重启失败、步骤 8 探活超时、`/v1/pool` 出现 `stuck`。
- 连续两次回滚失败 → 停止自动重试，保留现场（pipeline 日志 + 盘上 `.bak`），转人工。
- **控制台自身的回滚**与配置回滚是两件事：回退镜像 tag 会同时换掉 console 与 pipeline（同一镜像），因此**控制台不能单独回退**——这是同镜像的单向代价，写进发布说明（§12 R21）。配置回滚不回退代码。

## 11. 测试策略

### 11.1 已完成（本次交付）

| 测试 | 方法 | 结果 |
|---|---|---|
| catalog 结构约束 | 脚本读 `parameter-catalog.yaml`：schema 固定、14 字段齐全、枚举合法、`ops` 必有 `risk`、`effect=hot` 必为 `impact=session`、`(stage,backend,name)` 唯一且升序 | 通过（196 条，0 错误） |
| catalog 默认值 ↔ 源码（131 条全量） | 逐条 import `arguments_classes` 的 dataclass，比对字段默认值与 catalog `default` | 通过（131 条一致，0 处不符） |
| `ops` 风险类别覆盖 | 52 条 `ops` 条目的 `risk` 必须含「安全/隐私/环境绑定」之一 | 通过（安全 14 / 隐私 3 / 环境绑定 35） |
| 样例可解析 | `docs/parameter-catalog.md` 附录 A.1 的 YAML 片段落盘后调 `load_config` + `validate_config` + `resolve_config` | 通过（`pipelines=['prod']`） |
| `{env:}` 语义 | 移除 `GPUSTACK_API_KEY` 后 `resolve_config` 应报错 | 通过（`ConfigurationError`） |
| 未知字段拒绝 | 把 `min_silence_ms` 改成 `min_silence_ms_typo` | 通过（`ConfigurationError`） |

### 11.2 `console/backend`（pytest）

用例按新分层重组，迁入 `console/backend/tests/`：`unit/` 不起数据库、不碰 supervisor（socket 用假实现注入）；`integration/` 用 `tmp_path` 下的 SQLite 与 httpx 打桩，覆盖路由 ↔ 服务 ↔ 仓储的真实拼装。原 `tests/test_param_platform.py`（594 行 / 40 项）按此边界拆分，**断言不变，只换 import 路径与夹具**。

| 用例组 | 断言 |
|---|---|
| catalog ↔ 源码一致性 | 遍历 `arguments_classes/*.py` 的 dataclass 字段与 catalog `name` 集合比对，缺一即失败（防源码加字段后 catalog 漂移） |
| catalog 过滤 | `exposure=basic,advanced` 只回这两级；operator 可读 `ops` 但写被 403 |
| 布局映射 | 每个 catalog 条目落在 `runtime.*` / `blocks.<kind>.settings.*` / `pipelines.<name>.options.*` 三处之一；`deploy` / `env` stage 明确映射不到 YAML 并给出原因 |
| `validator` 黄金用例 | `example_configs/mac.yaml` 必须通过；改坏 `schema_version`、顶层多键、`num_pipelines: "2"`（字符串）三种必须失败 |
| `validator` 降级 | `speech_to_speech` 不可 import 时返回 `mode=structural` 且**显式上报**，不得静默认为“通过” |
| `renderer` 幂等 | 同一 draft 渲染两次输出字节完全一致（便于 diff 与审计） |
| 显存预算 | `num_pipelines` 超上限 → 步骤 4 拦下，`details.max_allowed` 存在 |
| 回滚 | 发布会崩的版本（错误模型路径）→ 自动恢复 `.bak` + 重启 + 再探活 → `rolled_back`；连续两次失败 → `failed` 且不再重试 |
| 重启失败 | supervisor socket 不可达 → `502 restart_unavailable` + `aborted`；断言盘上 YAML 已回到 `.bak` 字节（逐字节比对，不只看状态码） |
| `.env` 类字段拒绝 | patch 含 `stage=env` 字段 → 发布返回 `409 env_requires_recreate`；断言**不产生版本行、不改盘**（`PUT` 前先记文件 mtime + sha256） |
| 启动自检 | 构造悬挂 `publishing` 版本：① 盘上字节一致 + `/v1/pool` 健康 → 启动后标 `live`；② 字节不一致 → 恢复 `.bak` + 重启 + 标 `rolled_back` |
| 演示面契约 | 逐条打 11 组 `/api/*`：路径、方法、状态码、响应键名与 `demo/server.py` 一致；**响应不带 `code`/`message` 包络**（B10） |
| 条件能力开关 | 无 `LOAD_BALANCER_URL` 或无 `SPACE_ID` 时：`/api/queue/{id}` 404、`/api/me` 返匿名、`/api/search` 走本地直连分支；两项都配齐时行为翻到限流分支 |
| 静态托管顺序 | 注册 `/` 兜底后，`/api/config`、`/vendor/*`、`/v1/realtime` 仍命中各自路由（防 `StaticFiles` 吞路由）；`/console/versions` 返 `index.html` 而非 404 |
| 并发 | `If-Match` 过期 → 409；同 profile 并发 publish → 第二个 409 `publish_in_progress` |
| 鉴权 | 无 token → 401；operator 改 `expert`/`ops`、发布、回滚 → 403；JWT 过期 → 401；密码错 5 次 → 429 |
| 密钥不泄露 | 读 draft/publish 响应与审计日志，全文搜索密钥字面量必须 0 次命中；审计只记字段名 |
| 审计完整性 | 每个写操作产生一行，含 actor（JWT `sub`）、版本、字段名、结果、耗时、`requestId` |
| 热更新隔离 | 两个并发连接，`scope=session` 只改一条，另一条不出现 `session.updated`（在 httpx 打桩层断言载荷） |
| 音色服务（`unit/test_voice_service.py`） | §3.11.1 绑定表：`source × backend` 三个后端全部映射正确；`ref_audio` 与 `ref_spk` 互斥、`ref_rvq` 缺 `ref_spk`/`ref_text`、`design` 但非 VoiceDesign → 均 `422 voice_binding_conflict`；引用计数同时统计 `param_draft.draft` 与 `param_version.rendered`；名字大小写不敏感唯一 → 第二个同名 `409 voice_name_taken` |
| 音色端点（`integration/test_voices.py`） | 上传 → 校验 PCM16/16 kHz/单声道 → 预计算子进程打桩 → `ready` 全链；缺 `consent` → `400 voice_consent_required`；超 10 MiB → `413 voice_too_large`；采样率不符 → `400 voice_audio_invalid`；被引用 → `409 voice_in_use` 且 `detail[]` 带 profile 名与版本号；试听 `Range: bytes=0-` → `206`；`ggml` 后端跳过预计算只留 `ref_audio` + `ref_text` |

### 11.3 `console/frontend`（Vitest）

环境对齐 MinWorkBuddy：`vitest.config.ts` 用 `node` 环境、`@vitejs/plugin-vue` 编译 SFC、`@/*` 别名同源。结论是**不做 DOM 断言**（MinWorkBuddy 也没装 `@vue/test-utils` / `jsdom`），视图正确性交给 §11.4 的 e2e。对话页的逻辑层刻意写成不依赖 Vue 的纯 TS（`features/voice/{transport,audio}`），就是为了能用同一个 node 环境跑测试。

| 用例 | 断言 |
|---|---|
| `api/client.ts` | 401 触发一次 refresh，仍失败则清 token；错误体 `{code,message,detail}` 映射为稳定文案键；密钥值永不出现在请求 URL |
| `stores/draft.ts` | 未改字段不进 patch；`null` 表示"回退默认"且保留该键；`baseVersion` 变化把 draft 标脏 |
| `stores/catalog.ts` | 按 `exposure` 过滤与分组排序（stage → backend → name）；operator 不渲染 `expert`/`ops` 的可写控件 |
| `utils/format.ts` | ISO 8601 UTC → 本地展示；`duration_s` / `change_cost` 文案映射 |
| `utils/voice-refs.ts` | 名字去重（§6.1 的 3 条规则）；`source × backend` → 绑定字段（§3.11.1）；`ref_audio` 与 `ref_spk` 互斥的 patch 生成；同 name 多行只产生一个控件 |
| `router` | 无 token 访问 `/console/params` 重定向 `/console/login`；已登录访问登录页重定向回列表 |
| `features/voice/transport/session.ts` | `session.update` 载荷只含四个热字段（§2.2）；`null` 与"不发"生成不同帧；`response.create` 的触发时机与 `create_response_enabled` 一致 |
| `features/voice/audio/playback.ts` | 播放队列按到达顺序出队；`interrupt` 清空且不回调 `onended`（对应 `demo/tests/playback.test.mjs`） |
| `features/voice/audio/vad.ts` | 本地 VAD 阈值/静音时长映射为 `demo/tests/local-vad.test.mjs` 同组用例；未加载 wasm 时降级到服务端 VAD 且上报一次事件 |
| `features/voice/audio/meter.ts` | orb 频谱数据源：FFT 长度与帧率固定，静音帧不外推（对应 `visemes.test.mjs`） |
| `turn-latency.ts` | 各阶段时间戳差值（对应 `turn-latency.test.mjs`），首字节与末字节命名不变 |

### 11.4 契约与端到端

| 层 | 做法 | 阻断条件 |
|---|---|---|
| 契约 | `console/frontend/scripts/check-contract.mjs` 拉 `GET /api/v1/openapi.json`，比对手写 `types/*.d.ts` 的字段名与类型；**演示面另一份** `types/demo.ts` 与 `demo/server.py` 的响应键比对 | 任一前端类型与后端 schema / 演示面实际响应不一致 |
| 端到端（运维面） | Playwright（与 `demo/package.json` 同版本 1.62.1）跑 `vite preview` + 真实 console 进程（SQLite，supervisor 打桩） | 七个旅程任一失败：登录→改 `basic`→发布成功；operator 改 `ops` 被 403；发布会崩→自动回滚；改 `.env` 字段→`409 env_requires_recreate`；热更新只影响目标会话；上传音色→预计算完→在参数页选中→发布后 YAML 里是 `<ref_cache_dir>/<id>/spk.npy`；删除被引用的音色→`409 voice_in_use` 并显示引用计数 |
| 端到端（对话页） | 同上环境，pipeline 用假 WS 服务（回放固定帧序列） | 三个旅程任一失败：点麦克风→拿到麦克风授权→首帧音频上行；收到转写→列表追加且 orb 有幅度；点"结束"→`/api/session/end` 被调且队列位次释放 |
| 镜像 | 单镜像构建后 `docker compose -f docker-compose.yml config` + 从**宿主**或 CI runner 打 `:8000/api/v1/health` 与 `:8000/api/config`（镜像内不装 `curl`，容器内探活走 `python -c urllib`，§13.4） | 构建产物缺 `dist/index.html` 或 `vendor/*`；`8765` 被意外 publish；健康检查返非 200 |

### 11.5 与 `docs/configuration.md` 的一致性

catalog 与本文不得重新定义 YAML 语义。核对点：`{env:}` 是映射且缺失即错、路径字段按 YAML 目录解析、1 MiB/32 层限制、未知键拒绝——四项均为引用而非改写。

## 12. 风险清单

| # | 风险 | 触发条件 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | `num_pipelines` 撞显存 | 每路 ≈4.6GB（`nvidia-smi` 实测），12GB 卡上限 2 路 | OOM，连带现有会话抖动 | `validator` 强制显存预算；发布前必须过步骤 4 |
| R2 | `enable_llm_proxy` 无自带鉴权 | 开启后代理端点对 `host` 暴露 | 任意人可消耗 LLM 额度 | 归 `ops`-安全；开启需管理员 + 二次确认；`host` 保持 `127.0.0.1` |
| R3 | `log_transcripts` 隐私 | 开启后转写全文落盘 | 用户语音内容泄露 | 归 `ops`-隐私；默认关闭；开启写审计 |
| R4 | `host` 被改回 `0.0.0.0` 后暴露未鉴权 API | `/v1/realtime`、`/v1/pool`、`/v1/usage` 均无鉴权；容器 profile 下有人把 `host` 改成 `0.0.0.0` 且外部又 publish 了 `8765` | 任意人可占用会话、读用量 | 双重拦截：① `host` 归 `ops`-安全且容器 profile 下 `validator` **强制推导**为 `127.0.0.1`（可改但下一次发布会覆盖回）；② compose **不 publish** `8765` |
| R5 | 热更新与新连接默认值不一致 | 只做热更新不改 YAML | 重启后回退旧人设，运营误判 | §5.4 写入 UI；"改默认"必须同时走链路 A |
| R6 | catalog 与源码漂移 | 源码新增字段但未更新 catalog | 平台看不到新参数，或被误认为已覆盖 | §11.2 一致性测试；catalog 记录 `generated_from` commit |
| R7 | YAML 与 CLI 双写冲突 | compose 同时留 CLI 开关与 `-f` 文件 | 文件模式拒绝 CLI 参数，容器直接退出 | §4.2 固定模板；发布前 grep 校验 compose 不含业务 CLI 开关 |
| R8 | 回滚跨环境复用 | 换机器后回滚到旧版本 | 旧路径/旧设备号在新机不存在 | §7.2 环境绑定类不进回滚候选；回滚前重跑 `validator` |
| R9 | `{env:}` 写成字符串 | 手写 `"{env: NAME}"`（带引号） | 被当作字面量密钥，服务报鉴权失败或静默用错 key | catalog 与本文均标注"是映射，不能加引号"；`validator` 检测字符串形如 `{env:` 时告警 |
| R10 | 部分 fanout 失败被忽略 | 热更新多连接时个别失败 | 部分用户仍是旧人设，状态不一致 | 响应返回 `failed[]`；UI 提示重试 |
| R11 | 容器内 RCE ≈ 可重启 pipeline（拒绝服务） | console 进程被远程代码执行或恶意依赖利用 | 攻击者可重启 pipeline 中断所有语音会话，但**不能**创建容器/挂载宿主目录/提权 | unix socket 只开 `0700`、不启 `inet_http_server`、只暴露 `restart`/`getState`（§10.3）；镜像内不装 docker CLI；不加 `--privileged` |
| R12 | 迁移期双实现漂移 | 旧 `demo` 镜像与新镜像同时运行，且都指向同一个宿主 `./config` 目录 | 两份代码对同一 profile 渲染出不同字节 | 迁移期两者**不能共享 `./config`**：`demo` 用旧卷、新镜像用新卷；或以 `ADMIN_TOKEN` 置空的方式把旧侧降为只读（§14.4） |
| R13 | 唯一对外面 `8000` 同时承载运维、演示、语音三个面 | 暴露到公网且无速率限制 | JWT 爆破、弱口令登录、演示面配额被刷 | 只绑内网/回环；登录失败 5 次/5 分钟节流；演示面配额由 `metering_service` 管（§9.2）；`JWT_SECRET_KEY` ≥ 32 字节随机 |
| R14 | PostgreSQL 成为新单点 | 容器重启、磁盘满、无备份 | 草稿与审计不可写，发布被阻断 | 独立数据卷 + 每日 `pg_dump`；PG 不可用时只读视图返回明确错误（`db_unavailable`）而非 500 |
| R15 | 前端重写丢掉边界行为 | 旧 `ui/console/*.js` 的隐式行为（密钥掩码、错误文案映射、轮询退避）与对话页的隐性约定（麦克风释放时机、打断时队列清空）未逐条对照 | 功能对等缺口，运维按旧习惯出错、访问者感受到通话行为变化 | §14.5 功能对等清单逐条验收；对话页以 `demo/tests/*.mjs` 的 12 个用例为行为基线（§11.3）；旧文件在拆除前保留在 git 历史 |
| R16 | 前后端版本漂移 | 新后端上线、浏览器仍用缓存旧 `dist` | 旧前端调新 API，字段缺失 | 静态资源带 hash 文件名 + `index.html` 不缓存；契约测试（§11.4）；破坏性变更升 `v2` |
| R17 | 控制台与 pipeline 的 catalog 不同步 | 镜像内的 `parameter-catalog.yaml` 与仓库不同 commit | UI 展示的默认值与实际未生效值不一致 | catalog 以只读挂载方式从仓库注入（不 COPY 进镜像）；`/api/v1/catalog` 回 `generated_from` commit，前端顶栏展示该 commit |
| R18 | （已消除）容器内跑 `docker compose` 时相对路径错位 | — | — | 同容器后不再执行 `docker compose`（§10.3），旧的 `S2S_HOST_ROOT` 同路径挂载与 R18 一并删除 |
| R19 | console 与 pipeline 同容器耦合 | console 进程被 OOM killer 杀掉或启动失败，或两者抢同一块显存/CPU | supervisord 把 console 拉回但活跃语音会话全断；反之上游卡顿也拖垮控制台 | 两者**不共享解释器与事件循环**（§9.1）；`supervisord.conf` 各自 `autorestart=true` + `startretries=3`；console 的 `num_pipelines` 不做并发压测就不得上调；发布前后监控 `ps` 内存峰值（§14.5） |
| R20 | WS 反代背压与延迟 | 浏览器 ↔ console ↔ `127.0.0.1:8765` 多一跳，而转发层缓冲帧 | TTS 首字节延迟上升，or 播放端提前收到成块音频 | 转发层逐帧 `send` 不做 coalesce；**关闭** `permessage-deflate`；`docs/response-latency.md` 的 p95 基线在接入反代后重测一次，超出 20ms 即视为回退 |
| R21 | 同镜像单向绑定 | 想单独升级控制台或单独回退 pipeline | 无法灰度：换镜像 tag 会同时换掉两个进程 | 接受此代价（用户选择的拓扑）；变更按整镜像发版；发布说明必须写明"回退镜像 = 控制台与 pipeline 一起回退"（§10.4） |
| R22 | 演示面路径与包络被"顺手统一" | 后续开发把 `/api/*` 也改成 `ApiResponse` 或加前缀 | 浏览器侧客户端（`s2s-realtime-client.js` 及其 Vue 重写）直接解析失败，对话页整体不可用 | §3.5.2 B10 + §11.2 "演示面契约"用例 + `types/demo.ts` 契约比对三重约束；改形状必须先改客户端并同步升版本 |

## 13. 开发、构建、测试与部署

### 13.1 环境要求

| 组件 | 版本 | 用途 |
|---|---|---|
| Node.js + npm | 20 LTS / 10+ | 前端开发与构建（与根 `Dockerfile` 新增的 `node:20-alpine` 阶段同版本） |
| Python | 3.12 | 后端开发与测试（对齐基座 `python-torch:cu128`，D12） |
| Docker Engine + Compose v2 | 24+ / v2 | 构建与运行**那一个**镜像 |
| `supervisor`（pip 包） | 4.x | 只在容器内必需；开发态可直接两终端跑 |
| PostgreSQL | 16 | **可选**，仅当启用 `pg` profile（默认 SQLite） |
| NVIDIA 容器工具链 | — | pipeline 进程需要；console 不用但仍同容器 |

### 13.2 独立开发

两个**子项目**各开一个终端，互不为前置；pipeline 第三个终端可选（仅链路 A/B 联调时需要）：

```bash
# 终端 A：console/backend
cd console/backend
python -m venv .venv && . .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -e ../.. --no-deps                      # 让 speech_to_speech.config 可 import（D9）
pip install -r requirements-dev.txt
cp .env.example .env                                # 填 JWT_SECRET_KEY，其余用开发默认值
alembic upgrade head
python scripts/seed_admin.py --username admin --role admin --password-stdin
uvicorn app.main:app --reload --port 8000
```

```bash
# 终端 B：console/frontend
cd console/frontend
npm ci
npm run dev        # http://localhost:3000，/api、/vendor、/v1 由 Vite proxy 转到 :8000
```

```bash
# 终端 C（可选）：pipeline
speech-to-speech serve -f ../config/prod.yaml --name prod    # 8765；不跑时控制台报 pool_unreachable
```

开发态 `.env.example` 的默认值（必须能直接跑起来）：

```
DATABASE_URL=sqlite:///./dev.db
USAGE_DB_PATH=./usage-dev.sqlite3
PARAM_CONFIG_DIR=../../../config
PARAM_CATALOG_PATH=../../../docs/parameter-catalog.yaml
PIPELINE_BASE_URL=http://127.0.0.1:8765
SUPERVISOR_SOCKET=/tmp/s2s-console/supervisor.sock
SUPERVISOR_PROGRAM=pipeline
RESTART_MODE=noop
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

三个要点：
- **`RESTART_MODE=noop`**：开发态不发真的重启请求，只写日志并继续走后续步骤；**但健康检查仍真探活**，pipeline 没跑就如实报 `pool_unreachable`。测试里需要验证重启语义时必须显式改成 `supervisor` 并注入假 socket。
- 开发态不需要 supervisord：想验证真重启，要么进容器（§13.4），要么本机装 `supervisor` 后把 `SUPERVISOR_SOCKET` 指过去。
- 前端在后端未启动时仍能启动并渲染登录页（不做 mock 数据，与 MinWorkBuddy 的 `VITE_USE_MOCK` 不同）。

### 13.3 构建（单镜像）

只有一个构建单元：根 `Dockerfile`。在现有阶段之前插一个前端阶段，并让运行时阶段多拷两样东西：

| 阶段 | 基镜像 | 做什么 | 产物去向 |
|---|---|---|---|
| `frontend-build`（新增） | `node:20-alpine` | `npm ci` → `vue-tsc --noEmit` → `npm run test` → `npm run build`（含 `scripts/copy-vendors.mjs`） | `/build/dist` |
| 运行时（现有阶段） | `python-torch:cu128` | `uv sync`（含 console 独占依赖）→ `COPY src ./src` → `COPY console/backend /app/console` → `COPY --from=frontend-build /build/dist /app/console/static` → `COPY console/deploy/supervisord.conf /etc/supervisor/conf.d/` | **一个镜像，两个 program** |

镜像内容约定（每条都有对应的反面代价）：

- `ENTRYPOINT ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]`，compose **不再给 `command`**——给了就会覆盖 ENTRYPOINT，supervisord 永远不启动。
- 前端产物落在 `/app/console/static`（`StaticFiles` 的 root），**不是** `/usr/share/nginx/html`；镜像里**没有 nginx**（D7）。
- `speech_to_speech` 已由现有 `uv pip install -e .` 装好，console 用 `PYTHONPATH=/app/console` **复用同一个 venv**；镜像内**只有一棵 Python 依赖树**（D9）。
- `npm ci` 与 `node_modules` 全部在 `frontend-build` 阶段内，运行镜像只有 `dist/`；`@openai/agents` 的 UMD 与 VAD 资产以静态文件形式存在，**运行期不读 `node_modules`**（D10）。
- 构建门禁（任一不过即不出镜像）：`npm run lint`、`npm run test`（Vitest）、`npm run build`、`ruff check`、`pytest tests/unit`、`pytest tests/integration`、`scripts/check-contract.mjs`。
- 镜像体积敏感项：`dist/` 预估 2–4 MB、vendor 资产 6 个（VAD wasm/onnx + UMD）约 15–20 MB；这些进镜像但**不进** `uv` 层，两者缓存互不干扰。

### 13.4 部署

根 `docker-compose.yml` 的 `pipeline` 服务改成下面这个样子（其余服务不动）：

```yaml
services:
  pipeline:
    build: .
    image: ccr.ccs.tencentyun.com/llm-basic/speech-to-speech:cu128-1.0
    env_file:
      - ./config/prod.env          # 容器创建时注入（含 S2S_INTERNAL_TOKEN）
    ports:
      - "8000:8000"                # 唯一对外端口
    volumes:
      - ./config:/app/config       # rw：console 唯一写入点
      - ./data:/app/data           # rw：console.sqlite3 + usage.sqlite3
      - ./cache:/root/.cache       # 既有模型权重
      - ./silero-vad:/opt/silero-vad:ro
      - ./docs/parameter-catalog.yaml:/app/catalog/parameter-catalog.yaml:ro
    # command 刻意不给：由 ENTRYPOINT 的 supervisord 决定跑什么
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 120s           # pipeline 加载模型慢；start_period 内失败不计入
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]
```

`supervisord.conf`（`console/deploy/supervisord.conf`）的关键段：

```ini
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log
pidfile=/run/supervisord.pid

[unix_http_server]
file=/run/s2s-console/supervisor.sock
chmod=0700

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[program:console]
command=uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
directory=/app/console
environment=PYTHONPATH="/app/console"
autostart=true
autorestart=true
startretries=3
stdout_logfile=/var/log/supervisor/console-stdout.log
stderr_logfile=/var/log/supervisor/console-stderr.log

[program:pipeline]
command=speech-to-speech serve -f /app/config/prod.yaml --name prod
autostart=true
autorestart=true
startretries=3
stopwaitsecs=30
stdout_logfile=/var/log/supervisor/pipeline-stdout.log
stderr_logfile=/var/log/supervisor/pipeline-stderr.log
```

四条硬约束：

- `console` **必须 `--workers 1`**：supervisor 状态、单飞锁、内存中的 draft 缓存都假定单进程（§7 的并发控制靠进程内锁）。
- **不写 `[supervisorctl]` 段、不启 `[inet_http_server]`**：socket 只给容器内进程用（§10.3）。
- `[program:pipeline]` 的 `command` **只含 `-f` 与 `--name`**，不得夹带业务 CLI 开关（R7）；否则文件模式会直接报错退出。
- 停启顺序：`supervisord` 作 PID 1 收 SIGTERM 时按 `priority` 逆序停（默认 console 先停，pipeline 后停），`stopwaitsecs=30` 给 pipeline 收尾。

上线步骤：

| 步 | 动作 | 校验 |
|---|---|---|
| 1 | 准备一份 `config/prod.env`：`S2S_INTERNAL_TOKEN`、`JWT_SECRET_KEY`、`HF_HUB_OFFLINE` 等全在里面 | `S2S_INTERNAL_TOKEN` 非空（否则链路 B 全线 503）；`JWT_SECRET_KEY` ≥ 32 字节 |
| 2 | `docker compose build pipeline && docker compose up -d pipeline` | `docker compose ps` 显示 healthy；`docker compose exec pipeline supervisorctl status` 两个 program 均 `RUNNING` |
| 3 | 首次建管理员：`docker compose exec pipeline python /app/console/scripts/seed_admin.py` | `POST /api/v1/auth/login` 返回 token |
| 4 | 验证入口：`curl http://127.0.0.1:8000/api/v1/health` 与 `curl http://127.0.0.1:8000/api/config` | 两个都 200；宿主上 `8765` 不可达（`curl` 应失败） |
| 5 | 首次发布：控制台改一个 `basic` 字段 → 发布 | `version=live`，`/v1/pool` 的 `size` 符合预期，**且发布期间控制台一直可访问**（这是链路 A 改成进程级重启的核心验收点） |

关于 `S2S_INTERNAL_TOKEN`：它只出现在 `config/prod.env` 一处（同容器内两个进程通过 `env_file` 同时拿到，调用方与被调方自然同值）。**不进 catalog、不可在 UI 修改**，属部署期注入的机对机密钥。同容器后它从"跨容器信任边界"降级为"防误调用的标记"，但**必填**——删掉它会让 pipeline 的 `/internal/*` 走入 fail-closed 分支（§5.1）。

### 13.5 环境变量

同容器后环境变量只有**一张表**，全部由 `config/prod.env` 提供（`env_file` 注入，改它必须 recreate，§4.2）。表中不再有“前端/后端分离”的归属列，只有“谁读”：

| 变量 | 谁读 | 默认/必填 | 说明 |
|---|---|---|---|
| `JWT_SECRET_KEY` | console | **必填**，≥ 32 字节 | 缺失则 console 启动失败（fail closed），supervisord 重试 3 次后放弃 |
| `DATABASE_URL` | console | 默认 `sqlite:////app/data/console.sqlite3` | PG 时写 `postgresql://...`；两库分离见 D11 |
| `USAGE_DB_PATH` | console | `/app/data/usage.sqlite3` | 演示面计量库（裸 `sqlite3`），与参数库不共用 |
| `JWT_ALGORITHM` / `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` / `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | console | `HS256` / `30` / `7` | 对齐 MinWorkBuddy `env.example` |
| `CORS_ORIGINS` | console | 生产**留空** | 留空即不装中间件（§10.2.2） |
| `PARAM_CONFIG_DIR` | console | `/app/config` | 被管配置目录，**唯一写入点** |
| `PARAM_CATALOG_PATH` | console | `/app/catalog/parameter-catalog.yaml` | catalog 只读挂载（R17） |
| `PIPELINE_BASE_URL` | console | `http://127.0.0.1:8765` | 回环，不再走 compose 服务名 |
| `PIPELINE_TIMEOUT_S` | console | `180` | 与 §4.1 步骤 8 一致 |
| `SUPERVISOR_SOCKET` / `SUPERVISOR_PROGRAM` | console | `/run/s2s-console/supervisor.sock` / `pipeline` | 链路 A 的执行通道（§10.3） |
| `RESTART_MODE` | console | 生产 `supervisor`；开发可 `noop` | `noop` 只写日志不重启（§13.2） |
| `S2S_INTERNAL_TOKEN` | console + pipeline | **必填** | 机对机 token；缺失时链路 B 返回 `502 pipeline_token_missing` |
| `LOAD_BALANCER_URL` / `SPACE_ID` | console | 空 | 演示面限流/队列/OAuth 的**总开关**：两个都有才启用（§9.2） |
| `SERPER_KEY` | console | 空 | 搜索代理；空则 `/api/search` 走本地直连分支 |
| `VITE_API_BASE_URL` / `VITE_APP_TITLE` | frontend（**构建期**） | 空 / `S2S 部署参数控制台` | 前者只在开发直连时用；**不把 upstream 地址烘进产物** |

`s2s` 侧的原有变量（`HF_HUB_OFFLINE`、`GPUSTACK_API_KEY`…）不变，仍在同一份 `config/prod.env` 里。前后端共享一份变量文件是同容器的直接好处：不再存在“两个 `.env` 里同名变量取不同值”的隐患（旧设计里这一点只能靠人工核对）。

### 13.6 CI

四条独立作业，可并行，任何一个红即阻断合并：

| 作业 | 内容 |
|---|---|
| frontend | `npm ci` → `npm run lint` → `npm run test`（Vitest）→ `npm run build`（含 `copy-vendors.mjs`，断言 `public/vendor/` 下 6 个 VAD 资产 + 1 个 UMD 存在） |
| backend | `pip install -e . --no-deps` + `pip install -r requirements-dev.txt` → `ruff check` → `pytest tests/unit` → `pytest tests/integration`（SQLite） |
| 契约 | 启 console（SQLite，`RESTART_MODE=noop`）→ `check-contract.mjs`：运维面 `types/*.d.ts` + 演示面 `types/demo.ts` 两份都要过 |
| 镜像 | `docker build` 单镜像 → 断言镜像内存在 `dist/index.html`、`vendor/openai-realtime-agents.umd.js`、`vendor/local-vad/*`、`supervisord.conf` → `docker compose config` 校验端口只有 `8000` 且 `8765` 未 publish |

平台与 pipeline 的联调（`docker compose up`、显存预算、真实回滚）不在 CI 里装，必须在部署机上跑（§11.4 已标注）。

## 14. 迁移与回滚

### 14.1 现有资产归属

| 现有资产 | 规模 | 归属 | 关系 | 备注 |
|---|---|---|---|---|
| `demo/param_api.py` | 520 行，10 个路由 | `console/backend/app/routers/*` + `deps.py` | **废弃重写** | 鉴权从静态 token 改为 JWT；响应改统一包络 |
| `demo/param_platform/catalog.py` | 255 行 | `app/services/catalog_service.py` | **迁移**（函数级） | 路径改为 `Settings` 注入 |
| `demo/param_platform/layout.py` | 248 行 | `app/services/layout_service.py` | **迁移** | 纯函数，无改动 |
| `demo/param_platform/renderer.py` | 200 行 | `app/services/renderer_service.py` | **迁移** | 保留字节级幂等 |
| `demo/param_platform/validator.py` | 431 行 | `app/services/validator_service.py` | **迁移** | 双模（runtime/structural）保留 |
| `demo/param_platform/compose_runner.py` | 329 行 | `app/services/restart_runner.py` + `core/supervisor_client.py` | **重写** | 执行体从 `docker compose` 换成 supervisor XML-RPC（§10.3）；compose 路径与环境推导全部删除 |
| `demo/param_platform/hot_update.py` | 210 行 | `app/services/hot_update.py` | **迁移** | 端点改 `/internal/sessions/update` |
| `demo/param_platform/publish_flow.py` | 569 行 | `app/services/publish_flow.py` | **迁移 + 改写持久化** | 八步顺序不变；存储改注入仓储 |
| `demo/param_platform/drafts.py` | 108 行 | `app/services/draft_service.py` + `repositories/draft_repository.py` | **重写** | 草稿落 PG/SQLite 而非内存/sqlite3 直连 |
| `demo/param_platform/store.py` | 336 行 | `app/repositories/*` + `alembic/versions/` | **重写** | sqlite3 → SQLAlchemy + Alembic |
| `demo/console.html` | 9 KB | `console/frontend/src/views/*` | **废弃（功能重写）** | 五个 tab 对应六个视图（多一个登录） |
| `demo/console.css` | 15 KB | `console/frontend/src/styles/*` | **废弃** | 样式基线改为 ant-design-vue 主题 + Less 变量 |
| `demo/ui/console/app.js` | 8.6 KB | `layouts/ConsoleLayout.vue` + `stores/console.ts` | **功能重写** | 顶栏/标签页/令牌弹窗 → 路由 + 登录态 |
| `demo/ui/console/params.js` | 16.6 KB | `views/ParamsView.vue` + `components/{ParamTree,ParamField,SecretField,DiffTable}` | **功能重写** | 左树右表单结构不变 |
| `demo/ui/console/sessions.js` | 7.6 KB | `views/SessionsView.vue` | **功能重写** | 仍只呈现 4 类热字段 |
| `demo/ui/console/versions.js` | 4.6 KB | `views/VersionsView.vue` | **功能重写** | 回滚仍写新版本 |
| `demo/ui/console/instances.js` | 4.4 KB | `views/InstancesView.vue` | **功能重写** | 降级状态仍需可见 |
| `demo/ui/console/audit.js` | 2.9 KB | `views/AuditView.vue` | **功能重写** | 仍只展示字段名 |
| `demo/ui/console/api.js` | 5.9 KB | `src/api/client.ts` + `src/api/*.ts` | **功能重写** | token 头、错误体、`X-Operator` → JWT `sub` |
| `demo/ui/console/html.js` | 3.5 KB | — | **废弃** | 转义模板由 Vue 模板引擎代替 |
| `demo/server.py`（全部 731 行） | 11 组演示面路由 + 2 条 `/vendor` 路由 + 末尾 `StaticFiles(html=True)` | `routers/demo/*` + `services/{identity,metering,search_proxy,realtime_proxy,asset}_service.py` + `core/spa.py` | **迁移（路径与载荷不变）** | 见 §9.2；`param_api.install(app)` 那一行删除，运维面改由 `router_registry` 注册 |
| `demo/index.html`(39KB)、`main.js`(70KB)、`style.css`(76KB)、`s2s-realtime-client.js`(40KB)、`turn-latency.js` | 约 245KB | `src/features/voice/**` + `src/features/voice/transport/s2s-client.ts` | **功能重写**（Vue 3 + TS） | 行为基线是 `demo/tests/*.test.mjs` 的 12 个用例（§11.3） |
| `demo/ui/chat.js`(31KB)、`ui/account.js`(13.7KB)、`ui/dom.js` | 约 45KB | `features/voice/components/{TranscriptList,ToolsDialog,SettingsDialog,AccountWidget,IdentityBlock,AboutDialog}.vue` | **功能重写** | 账号/身份两块必须与 `identity_service` 的返回形状对齐 |
| `demo/ws/*.js`（4 个）、`demo/worklets/*.js`（2 个） | 6 个 | `public/worklets/*`（原样） + `features/voice/audio/*`（重写） | **资产原样 / 逻辑重写** | worklet 脚本必须原样进 `public/`：它跑在 AudioWorklet 全局，不能过 Vite 的 TS 转换 |
| `demo/auth.py`、`demo/limiter.py` | 2 个 | `services/identity_service.py`、`services/metering_service.py` | **移植** | `LIMITER_ENABLED = bool(LOAD_BALANCER_URL) and bool(SPACE_ID)` 的开关语义不变 |
| `demo/Dockerfile`、`demo/requirements.txt`、`demo/package.json` | 3 个 | — | **删除** | 依赖已合并进 s2s 的 `pyproject.toml` 与 `console/frontend/package.json`（D9） |
| `demo/s2s-params.sqlite3`（+ `-shm` / `-wal`） | 32 KB | 归档只读 | **不迁入** | 见 §14.3 |
| `tests/test_param_platform.py` | 594 行 / 40 项 | `console/backend/tests/{unit,integration}` | **拆分迁移** | 断言不变 |
| `tests/openai_realtime/test_websocket_router.py::TestAdminHotUpdate` | 6 项 | 原地保留 | **改名** | 端点改 `/internal/sessions/update` |
| `docs/parameter-catalog.{md,yaml}` | 196 条 | 原地保留 | **继续作为唯一参数源** | console 只读消费，不复制 |

### 14.2 分阶段迁移

| 阶段 | 内容 | 门禁（不过则不进入下一阶段） | 可回退 |
|---|---|---|---|
| P0 | 目录与骨架：`console/{frontend,backend}`、`console/deploy/supervisord.conf`、根 `Dockerfile` 加 `frontend-build` 阶段、CI 四条作业 | 单镜像能起两个进程（`supervisorctl status` 均 RUNNING），`:8000/api/v1/health` 200、`/` 返回 `dist/index.html` | 是（仅新增） |
| P1 | 后端只读 API：`auth` / `catalog` / `draft(GET)` / `versions` / `audit` / `instances` / `health` | §11.2 unit+integration 绿；与旧 `param_api` 对同一 catalog 的 JSON 做对照，除包络外字段一致 | 是（旧 demo 仍可写） |
| P2 | 前端运维台只读视图：登录 + 参数树 + 版本 + 审计 + 实例 | §11.3 绿；四视图对真实后端可览 | 是 |
| P3 | 写入链路：`draft(POST/DELETE)` / `publish` / `rollback` / `sessions`（含 `restart_runner` 与启动自检） | §11.4 运维面五个旅程绿；在部署机完成一次真发布 + 一次真回滚；发布期间控制台 HTTP 不中断 | 是（把 `ADMIN_TOKEN` 给回旧 demo） |
| P4 | 演示面迁移：11 组 `/api/*` + `/vendor/*` + 对话页 Vue 重写 + 条件能力（OAuth/配额/队列） | §14.5 对话页清单逐项通过；两套关闭/开启环境各跑一遍 | 是（旧 `demo` 镜像仍可单独跑） |
| P5 | 切流与拆除：`demo/` 整体归档（含 `param_api.py`、`param_platform/`、`console.*`、`ui/console/`、`index.html`、`main.js`、`style.css`、`s2s-realtime-client.js`、`ws/`、`worklets/`、`server.py`、旧 sqlite、`Dockerfile`） | 连续两个工作日所有发布与语音演示均经新镜像；旧路径 404 | 否（只能 git revert + 回退镜像 tag） |

### 14.3 数据迁移

| 数据 | 处理 | 理由 |
|---|---|---|
| `param_draft`（草稿） | **不导入** | 草稿是瞬时意图，旧库里的草稿对当前 `config/` 已无意义；导入反而制造一个与文件不一致的补丁 |
| `param_version`（版本） | **默认不导入**，可选 | 已发布版本的回滚真相是 `config/<profile>.yaml` 与 `.bak.<version>` 文件，不是数据库行 |
| `param_audit`（审计） | **可选导入**（`--audit-only`） | 便于“上次是谁改的”追溯；不导入也不影响发布 |
| 用户 | 新建 | 旧系统只有共享 token，无用户可迁；`scripts/seed_admin.py` 建首个管理员 |
| 密钥值 | 不迁 | 从未入库（`.env` 才是唯一存放处） |

`scripts/import_legacy_sqlite.py` 只做两件事，且必须 `--dry-run` 先跑：读旧 sqlite → 写 audit 行（`--audit-only`）/ 写 version 行（`--include-versions`）。导入前必须备份旧文件；导入后旧文件转只读归档。

### 14.4 迁移期共存与回滚

- **共存期只能有一个写入方**：P1–P4 期间把旧 `demo` 容器的 `ADMIN_TOKEN` 置空（写接口 503，只读仍可用），并且**不让两个实例指向同一个宿主 `./config` 目录**（§12 R12）。这同时是 R12 的缓解措施。
- **回退到旧形态**（P5 之前）：停新容器 → 启旧 `demo` 镜像 → 给它恢复 `ADMIN_TOKEN` → 用 `config/*.bak.<version>` 恢复配置并重启旧 pipeline。全程不碰已发布的 YAML，除非主动选择回滚。
- **P5 之后回滚**：只能 `git revert` 拆除提交 + **回退整个镜像 tag**（console 与 pipeline 一起回退，不能只退一个，§12 R21）；数据不回退（审计只增不改）。
- **配置与代码解耦**：回退镜像 tag 不影响已生效的 `config/<profile>.yaml`；配置回滚也不回退代码（§10.4）。两件事在发布说明里分行记录。

### 14.5 功能对等验收清单

两块都要验收：旧 `console.html` 的五个 tab（运维台）与旧 `index.html` 的全部交互（对话页）。任何一项在 P5 之前没有落点，就不得进入 P5（拆除）。

运维台部分逐项取自 `demo/console.html` + `demo/ui/console/{app,params,sessions,versions,instances,audit}.js` 的实际代码，不是凭印象列的“大功能”。**“对齐”指的是这四张表里的每一行都能在新界面上找到对等物**；新界面可以换控件形状（tab → 侧栏、`<details>` → `a-collapse`），但不能少一个可操作点。

**外壳（`app.js`）**

| 旧能力（证据） | 新落点 | 验收方式 |
|---|---|---|
| 启动自检→状态 pill：可写 / 只读 / 连不上（`start()` 按 `writes_enabled` 分流） | `ConsoleLayout` 顶栏 `a-badge` + `stores/console` | 三种状态均可人工触发：admin 登录=可写；operator 对 `expert` 字段=只读；停 console 进程=连不上 |
| 全局 banner 四条：读不到 `/admin/status`、`catalog.available=false`（附 `hint`）、`compose.available=false`、`ADMIN_TOKEN` 未配置 | `ErrorBanner` + 启动自检提示列表 | 四条文案与旧页逐字对应；`catalog` 不可用时版本/审计页仍可览 |
| profile 下拉（来自 `boot.profiles`，切一个就重载当前 tab） | 顶栏 `a-select` + `consoleStore.profile` | 切 profile 后当前视图重新请求；旧页与浏览器刷新保持一致 |
| 令牌弹窗：`Authorization: Bearer` + `X-Operator`（只存 sessionStorage） | `LoginView` + 顶栏用户菜单 | 无“手输 token”入口；操作人取自 JWT `sub`（审计里的 `actor`） |
| toast：3.2s 自动消失，ok / bad 两色，用于保存、发布、回滚、热更新 | AntD `message` | 四类写操作各有成功与失败两条文案 |

**参数（`params.js` 360 行）**

| 旧能力（证据） | 新落点 | 验收方式 |
|---|---|---|
| 目录搜索：对 `key` / `backend` / `risk` 三字段做包含匹配 | `ParamTree` 顶部 `a-input-search` | 输 `onnx`、`serper`、`silero` 三个词，命中集合与旧页一致 |
| 级别过滤 + 计数行 `${len} / 共 ${total} 条 · ${variant_keys} 个多后端字段` | toolbar 的 exposure `a-select` + 计数行 | 四档 exposure 下分子/分母/多后端字段数均与旧页一致 |
| 分组可折叠（`<details open>`）、每参数项带 exposure 徽标、已在草稿内的项高亮（`in-draft`） | `ParamTree`（`a-collapse` + 逐项） | 折叠后仍可展开；点一个未入草稿的字段→出现在表单；已入草稿的字段带高亮 |
| 草稿元信息：`基于 v12 · 9 个字段 · 3 项未保存` | toolbar meta | 保存后“未保存”归零；`base_version` 不跳变 |
| 字段行六种徽标：exposure / 生效方式 / backend / 必填 / 用默认值 / 风险 + 风险说明段 | `ParamField` + `ExposureTag` | 与 catalog 条目逐字段对应；`ops` 无 `risk` 时不得渲空框 |
| 行操作：`↺ 恢复目录默认`、`× 从草稿里去掉`（后者把 `null` 写进 patch，语义是“回落默认”） | `ParamField` 行按钮 | 两者都只改 patch，不动已发布值；`×` 后刷新页面，该字段不再出现在草稿 |
| secret 输入框占位：`已设置（改成新值才会写入）` / `未设置`，值永不回填 | `SecretField` | 打开页面后 `input.value` 必为空；审计里只有字段名 |
| 校验区：ok/bad、`mode=runtime|structural`、`resolved_pipelines`、`expected_pool_size`、`skipped_masked`、`warnings[]` | 校验面板 | 4 个维度都有展示位；422 时保留已填值不清空 |
| 三个动作：保存草稿 / 放弃草稿（`window.confirm`）/ 发布（note ≤ 500 字） | toolbar + 发布对话框（Task 15） | 放弃走确认对话框；note 落到 `param_version.note` 与审计详情 |
| 发布中按钮态（`发布中…` 且禁用）与发布后整页重载（包括探活失败已回滚的情形） | 发布对话框 loading + 成功后 revalidate | 双击不会发两次；返回 `status=rolled_back` 时页面仍刷新 |

**会话（`sessions.js`，链路 B）**

| 旧能力（证据） | 新落点 | 验收方式 |
|---|---|---|
| scope 三态 `all` / `pipeline` / `session`，target 字段随 scope 改标签与 placeholder（数值 vs `sess_…`） | `SessionsView` 范围下拉 + 条件输入框 | 三种 scope 各发一次：`all` 不带 target，`pipeline` 发整数，`session` 发字符串 |
| `interrupt_response` **三态**：`不改` / `允许打断` / `不允许打断`（`""` 不等于 `false`） | 三选一 select | 选“不改”时请求体里不得出现 `turn_detection` |
| `instructions`（留空=不改）、`language`（留空=不改）、`extensions` JSON（留空=不改，非法 JSON 不发送） | 四个控件 | 空请求被前端拦下（“至少填一项”）；非法 JSON 提示后不发请求 |
| 结果区：`N 条连接已更新 / M 条失败`、session id 列表、`scope=… · 审计 #id`、部分失败不回滚说明 | 结果面板 | 失败项逐条显示 `session_id: error`；无活跃连接时有专门文案 |
| 五条约束文案（只影响活跃连接 / 空闲 unit / 不支持 `transcription` / `model`·`voice` 不生效 / `language` 需后端支持） | 面板底部说明 | 五条逐字保留，不合并、不删减 |

**版本 / 实例 / 审计（`versions.js` / `instances.js` / `audit.js`）**

| 旧能力（证据） | 新落点 | 验收方式 |
|---|---|---|
| 版本表 7 列：版本（含“当前”徽标）/ 状态 / 时间 / 操作人 / 说明（或“回滚到 vN”）/ 基于 / 体积 + 失败行的 `error` | `VersionTable` | 列与旧页一一对应；`rendered_bytes` 不能丢（新仓储里叫 `renderedBytes`） |
| 回滚：仅 `live`/`rolled_back` 且非当前版可回；二次确认写“会重建容器，正在通话的用户会掉线” | `ConfirmDialog` | 新形态文案改为“会重启 pipeline，控制台不中断”（同一事实，不同实现） |
| 实例 7 个 stat：版本 / 容器 / 状态 / 启动时间 / 镜像 / pool size / in_use | `InstanceCard` | 降级时仍渲染：未发布显示“未发布”，pool 不可达显示“不可达” |
| `alerts[]` 列表、容器查询错误行、pool 不可达说明（“不应该以这个状态收尾”） | 同上 | `supervisorctl stop pipeline` 后页面不白屏、不报 500 |
| unit 表 5 列：unit / 状态 / session / 释放中（`draining_for_s`）/ 卡住（`stuck_for_s`） | `InstanceCard` 内表格 | `draining` / `stuck` 两种状态的徽标色与旧页一致 |
| 审计 7 列：时间 / 动作 / 操作人 / 版本 / 结果 / 耗时 / 详情（可展开 `N 项` + JSON） | `AuditTable` | 详情里只有字段名与计数，**无密钥值**；`actor` 为登录用户名 |
| 三张表的刷新按钮（每次切 tab 重新请求） | 视图 `onMounted` + 手动刷新 | 切回来必须重新请求；不得只靠首次加载 |

**对话页**（逐项对照 `demo/index.html` + `main.js` 的交互面）：

| 旧能力（证据） | 新落点 | 验收方式 |
|---|---|---|
| `.ident`（`index.html:23-52`）：标题外链、About 圆钮、blurb、`Powered by` / `Built by` 两行 | `IdentityBlock.vue` | 三部分都在；<720px 时 blurb 收起而标题仍在 |
| 账号胶囊（`#account` + `ui/account.js`）：chip 上是 avatar + handle（PRO / TEAM 徽章按 tier 加），点开 popover 才是 tier、今日剩余分钟、Upgrade PRO、Sign out；未登录是 `Sign in` 胶囊 | `AccountWidget.vue` | 与 `/api/me` 逐字段对应；剩余时间**不在 chip 上**；`enabled:false` 时整块不渲染（不留空胶囊） |
| 球体四层 + 九态（`#main-circle` 的 `state-*` 类）+ 六个指示器（`.ind-mic/-error/-spinner/-thinking/-bars/-voice`） | `OrbStage.vue` + `audio/meter.ts` | 九态逐一可见（`idle / connecting / queued / your-turn / listening / user-speaking / processing / ai-speaking / error`）；指示器**换图形而不只是换色**；`ai-speaking` 时光晕随电平起伏 |
| `#circle-caption` / `#circle-subcaption`：状态文案、排队位次、授权拒绝提示、`Tap to retry` | `OrbStage.vue` 的 `caption` / `subCaption` / `tone` props | 文案由 `VoiceView` 单一持有；出错时变红且与旧页逐字一致（`Microphone access was blocked…`） |
| 噪声门弧（`#mic-gate`，`main.js:493-516` 的 200° 几何 + 拖拽）：拖拽改门限、弧显示实时电平、最左 = Off | `MicGate.vue` + `audio/meter.ts` | 说话时弧按电平逐段点亮；拖到最左把门限关掉（把手变灰）；拖进右侧缺口不会产生越界 dB；松手后 `noiseGateDb` 写进 `localStorage` |
| 麦克风静音钮（`#mic-btn`）：切音轨 `enabled` 与图标 | `MicGate.vue` 的 52px 圆钮 | 图标在 `#i-mic` / `#i-mic-off` 之间切换；静音后服务端不再收到音频帧 |
| 结束钮（`#stop-btn`）与页脚 `Powered by …` | `VoiceView.vue` 的 `.v-orb-wrap` / `.v-foot` | 结束钮回 `idle`；页脚链接到仓库，**不单独立组件** |
| 临时气泡（`#bubble-stack`）：`user` / `tool` / `assistant` 三种来源 | `BubbleStack.vue` | 最多四条、自动消失；工具调用以 `tool` 标记出现 |
| 会话历史（`#chat-panel`）：右侧抽屉 + 条目数 + 空态 | `HistoryDrawer.vue` + `TranscriptList.vue` | 380px 抽屉；空会话显示 `Nothing said yet.`；关闭重开内容仍在 |
| 转写条目（`#chat-history`）：用户/助手双色、临时条目半透明、贴底滚动 | `TranscriptList.vue` | 同一段回放录音的顺序与分段点一致；用户上滑阅读时不被强行拉回底部 |
| 用户条目原音回放（`ui/chat.js:onUserAudio` + `ws/user-audio-recorder.js`）：`Audio sent to the model` 标签 + `<audio controls>`，截断时加 `· beginning unavailable`；播放期间音轨 `enabled=false` 防回声 | `AudioReplay.vue` + `features/voice/audio/sent-audio.ts` | 说两句各 3s 以上：每条用户条目下都有播放器，时长与录音相差 ≤ 50ms；点播放时其它条目的音频暂停、麦克风被静音（`track.enabled===false`）；暂停/播完/出错后恢复；`transport=webrtc` 时**没有**播放器（demo 同样只有 `websocket` 分支录原音） |
| 工具条目（`_appendHistTool` / `_appendHistImage`）：`Input` / `Output` 可展开 + `Snapshot` 缩略图 | `TranscriptList.vue` 的 tool 分支 | 触发一次 `camera_snapshot`：条目里出现 `Snapshot` 缩略图与 `Input` / `Output` 两段 JSON；点击缩略图在新窗口打开大图；无图时只有文字，不出现空 `<img>` |
| 助手条目：只有文本与轮次延迟（demo 不保存 TTS 音频） | `TranscriptList.vue` + `TurnTimings.vue` | 助手条目下**不出现**任何播放控件；出现即为凭空发明（§3.2.2 末段） |
| 相机自视窗（`#cam-pip` / `.cam-flash` / `.cam-label`） | `CameraPip.vue` + `tools/camera.ts` | 打开相机才出现；拍照时白光一闪；`camera_snapshot` 读它的 `<video>`，pipeline 日志有调用记录 |
| 轮次延迟（`ui/chat.js:636-678` 的 `details.hist-timings`） | `TurnTimings.vue` + `useTurnLatency.ts` | 逐项对齐：`<summary>` 为 `Server timings`（`e2e_s=null`）或 `Server timings · E2E 6.26 s`（v2）/ `· First audio 6.26 s`（v1）；状态行 `Completed` / `Interrupted` / `Failed` / `Incomplete` 随 `status`；`<dl>` 七行顺序与文案一字不差；`null` 一律 `Unavailable`；末尾口径句是 `E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.`（v1 换成 `First audio: VAD handoff to generated audio…`）。**舞台上没有任何 chip 行**——demo 的 `index.html` 里搜不到 latency 节点，凭空加一条就是发明 |
| 轮次延迟的持久化：每条计时同时落进容器日志，可在实例页按时间窗回查 | `TURN_LATENCY` 日志行 + `turn_latency` 表 + `TurnLatencyPanel.vue`（§3.9.4、A.17） | 说完三轮后，实例页轮次面板出现三条记录，且 E2E 与条目 summary 里的数字逐条相等；重启 console 后旧记录仍在（事实源是日志行，不是内存）；把 `pipeline-stdout.log` 删掉重放另一份旧日志，表能重建出同样的行数 |
| 工具面板（`#tools-modal`）：Web search 开关 + Serper key + Camera 开关 + 三条 hint | `ToolsDialog.vue` | 无服务端 key 时开关禁用、hint 逐字一致；服务端握 key 时输入框禁用且 placeholder 是 `••••••••  · provided by the server`；`/api/search` 仍走代理 |
| 设置面板（`#settings-modal`）：十个字段 + Restart + Save | `SettingsDialog.vue` | 字段一个不少（server URL / Transport / Voice / Microphone / Speakers / Faster interruptions / Playback buffer / Noise gate / Instructions / Restart）；Save 后设置保留、Restart 断开重连并带上新值 |
| 关于弹窗（`#about-modal`）：简介 + 四段 pipeline + 版本 | `AboutDialog.vue` | 四段（VAD / STT / VLM / TTS）带模型外链；版本取自 `/api/config`，缺省显示 `unknown` 而不报错 |
| 额度耗尽（`#limit-modal`） | `LimitDialog.vue` | 把 `LIMIT_ANON_SEC` 调到 20 重跑，额度用完弹出卡片；CTA 与 note 与旧页一致 |
| 排队动作（`#queue-actions`）：位次 / `your-turn` 的 Join now / 满员 / Leave queue | `QueueOverlay.vue` | 无 LB 时**不出现**；有 LB 时三个状态都可人工触发，每个都能 Leave |
| 本地 VAD 与快速打断（`@ricky0123/vad-web`） | `audio/vad.ts` + `s2s-client` | 拒绝授权时文案与旧页一致；允许后首帧上行延迟不高于旧值 + 50ms |
| **刷新即结束**（demo 没有 `sessionStorage`） | `stores/voice.ts` | F5 后回 `idle`，**不出现** `Resume last conversation`；只有设置与工具开关保留 |
| 密钥单向（B5）：搜索 key 只在内存 | `VoiceView.searchKey` + `ToolsDialog` | 刷新后 key 输入框为空；`localStorage` 与 URL 里搜不到该值 |

### 14.6 监控、日志与归纳验收（三种构造）

监控与日志分析属旁路（Global Constraint 4.3），验收要同时证明两件事：**看到了**与**没打扰**。三种构造都按 §3.9.3 的判定签表逐项对照，四列全绿才算通过。

| # | 构造（只用手边手段） | 监控面板应显示 | 日志面板应能定位 | 归纳应给出 |
|---|---|---|---|---|
| 1 | 模型未加载：`POST /profiles/prod/draft` 把 `tts.model` 改成不存在的目录，再 publish | TTS 卡 `loaded:false`，`reasons.loaded="pipeline_stopped"`；其余三段 `loaded:true` | `pipeline-stderr.log` 命中 `OSError` / `No such file`；`q=checkpoint` 过滤后仍是同一行 | `errors[]` 有该签名与次数；`rootCauses[]` 指向「权重路径与 catalog 不一致」；`actions[]` 给出改回可用后端的操作序列 |
| 2 | 显存接近打满：`num_pipelines` 调到预算上限，再并发两路会话 | 四段 `vram.percent ≥ 0.9`、卡头标红、`alerts` 含 `vram_pressure`；`busy.inUse == busy.size` | 命中 `CUDA out of memory` 行，或（未 OOM 时）`level=WARN` 里的 `slow` 行 | OOM 计数 + 首次/末次时间；根因指向并发与显存预算；方案给出降 `num_pipelines` 或换更小量化 |
| 3 | 某段延迟异常升高：给 LLM 后端注入 800ms 固定延迟（mock 端点或本地代理 sleep） | 只有 LLM 卡 `p95Ms` 抬升并标「较上一窗口 +N%」，STT/TTS 持平 | 没有 `ERROR` 行；`level=WARN` 能定位到重试/慢请求行 | 明确写出「无错误但有延迟尖峰」+ 时间段 + p50/p95 背离，并给排查动作（并发、KV cache、后端预热） |

每种构造都要同时看一眼实例页的**轮次面板**（`TurnLatencyPanel.vue`，A.17）：它答的是「这一次响应整体多慢」，与模型卡的单次调用埋点是两个口径（§3.9.4 第 1 条），不能拿一个去推断另一个：

| 构造 | 轮次面板应显示 | 不该出现 |
|---|---|---|
| 1 模型未加载 | `count` 照常增长（能跑完的轮次），`status` 以 `completed` 为主；`stages.ttsTtfa` 的 `p50Ms` 为 `null`，`hold.unavailableCount` 与该段缺失行数一致 | 把缺失的 TTS 段算成 `0 ms` |
| 2 显存打满 | `e2e.p95Ms` 明显抬高、`maxMs` 是 OOM 那次的墙钟值；`failureRate > 0`（被 OOM 打断的轮次 `status=failed`） | 只显示均值把长尾掩盖掉 |
| 3 延迟注入 | 只有 `stages.llm` 的 p95 抬升，`stages.stt` / `stages.ttsTtfa` 持平；`e2e` 涨幅与注入值同向 | 把 `e2e` 的涨幅归到 STT 头上 |

轮次面板自己还有三条硬性检查：

1. **字段一一相等**：任取一条对话页条目，其 `E2E time` 与面板对应行的 `e2eMs / 1000` 保留两位后相等；`Transcription` / `Response generation` / `Voice synthesis to first audio` 同理。
2. **可重建**：停 console → `DELETE FROM turn_latency` → 启 console，等一个索引周期（5s），行数恢复到清空前（同一时间窗内）。这证明表只是日志的索引。
3. **不显示 0**：窗口调到没有任何轮次的时段，`summary` 各数值为 `null` 且 `reasons.summary="no_turn_rows"`，页面写「该时间窗没有轮次记录」。

三条共同的验收动作（每一条都要人工跑）：

1. **显卡不可见**：把 `nvidia-smi` 从 PATH 拿掉或容器不给 GPU。四张卡都显示「不可用 · `nvidia_smi_missing`」，**不出现 0 MB、不出现空白格**。
2. **pipeline 停掉**：`supervisorctl stop pipeline`。监控显示 `pipeline_stopped`；日志面板仍能读 `pipeline-stdout.log` 的历史部分（A.15 不因进程停了而 5xx）；顶栏状态 pill 与 §14.5 外壳行一致。
3. **分析失败**：让 `127.0.0.1:8765` 不可达（或关掉 `ENABLE_LLM_PROXY`）后点「分析」。结果卡显示 `502 log_analysis_unavailable`（或 `503`）+ 「重试」，**原始日志行一行不消失**；`config/prod.yaml` 与 `param_version` 表在这三种构造前后逐字节不变。

### 14.7 参数覆盖与音色制作验收（可勾选）

前置：`docs/parameter-catalog.yaml` 与三处产物同一份 `generated_at`。下列每一条都能手工复现，勾不上就是没做完。

**覆盖完整性**

- [ ] `pytest tests/unit/test_voice_service.py tests/unit/test_catalog_service.py -q` 绿；`test_catalog_service` 断言：解析出的 196 条按 §6.1 的三类分组相加 = 196，且 17 个分组的计数与表逐字相等
- [ ] 参数页计数行读 `196 条 · 193 个唯一名 · 2 个多后端字段`；把 exposure 依次切到 `basic` / `advanced` / `expert` / `ops`，分母始终是 196，分子与 `exposureCounts` 逐档相等（26 / 61 / 57 / 52）
- [ ] 逐个展开 17 个分组，树头数字与 §6.1 表相等；输入 `serper` / `onnx` / `silero` 三个词，命中集合与 `grep` catalog 的结果一致
- [ ] 3 个重名各只出现一个控件：`log_transcripts` 在 `runtime` 分组、`model_name` 在 `llm · 通用`、`responses_api_reasoning_effort` 在 `llm · responses-api`；另两处只在详情里显示 `aliases`

**固定与不暴露**

- [ ] 17 条 `type=fixed` 都是只读行：没有 input / select / switch，没有 `↺`，点击行只展开详情；详情写 `不可配置 · 源码常量` + `source_ref`
- [ ] `runtime.pipeline_sample_rate` 手工请求 `POST /draft {patch:{"runtime.pipeline_sample_rate":8000}}` → `400 invalid_parameter`（值不在 catalog 条目上），页面无法构造出这个请求
- [ ] `env` 组 18 条：草稿可保存、`publish` → `409 env_requires_recreate`，`detail[]` 只有变量名；版本列表不新增行
- [ ] `deploy` / `client` 两组各 16 / 18 条只读，文案与 §6.1 的四行表逐字一致

**抽样 10 条走全链（覆盖 4 个 exposure × 3 个 effect）**

| # | 字段 | exposure | effect | 全链验收 |
|---|---|---|---|---|
| 1 | `vad.min_silence_ms` | `basic` | `startup` | 改 700→900 → 保存 → 发布 → `/v1/pool` 探活 → YAML 字节里是 900 |
| 2 | `llm.llm_gen_temperature` | `basic` | `startup` | 同上（值 0.7→0.55） |
| 3 | `tts.kokoro_voice` | `basic` | `both` | 徽标写 `启动` + 小字 `catalog: both`；发布后生效，热更面板里搜不到它 |
| 4 | `vad.thresh` | `advanced` | `startup` | 同 1；建议值 chips 出现 |
| 5 | `tts.qwen3_tts_streaming_chunk_size` | `advanced` | `startup` | 改成 4 → 发布 → 首音延迟下降；填 `abc` → 前端先拦、后端再 422 双保险 |
| 6 | `runtime.num_pipelines` | `expert` | `startup` | 改成 8 超过预算 → `422 vram_budget_exceeded` + `maxAllowed:4`；改回 4 可发布 |
| 7 | `stt.qwen3_asr_device` | `expert` | `startup` | 折叠展开有 warning 句；改成 `cuda:9` 在 resolve 期报错而不是静默回 CPU |
| 8 | `runtime.device` | `ops` | `startup` | 徽标 `环境绑定`；二次确认；改后即使各 `*_device` 没变，覆盖规则生效（§8.2） |
| 9 | `llm.responses_api_api_key` | `ops` | `startup` | 输入框值永为空，回显 `***`；提交 `***` 视为不改，审计里只有字段名 |
| 10 | `session.instructions` | `basic` | `hot` | 徽标 `热更新`；下发只影响活跃会话；同时改 `init_chat_prompt` 时页面给「两动作」提示 |

**音色全链**

- [ ] 上传 8 s 参考音频 + 逐字文本 → 预计算进度跑完 → 列表里 `status=ready`；期间 `GET /v1/pool` 的 `in_use` 与 `size` 不变（旁路）
- [ ] 在 `tts · qwen3` 的 `qwen3_tts_speaker` 行点「选择音色」→ 选中该音色 → 生成的 patch 是 `{qwen3_tts_speaker:null, qwen3_tts_ref_spk:"<ref_cache_dir>/<id>/spk.npy", qwen3_tts_ref_rvq:"...", qwen3_tts_ref_text:"<逐字文本>"}`
- [ ] 再手动把 `qwen3_tts_ref_audio` 也填上 → 保存草稿就 `422 voice_binding_conflict`（早于发布，不重启）
- [ ] 发布后 `config/prod.yaml` 里是上述四个键；版本详情与审计里只有字段名 + `voiceRefs:[{field,voiceId}]`，**没有音频、没有转写文本**
- [ ] 删除该音色 → `409 voice_in_use`，页面显示被 `prod` 与 `v12` 引用；把草稿与版本都换掉后再删 → 文件真的消失（`ls /app/data/voices/<id>` 不存在）
- [ ] 回滚到使用旧音色的版本 → YAML 指回旧 `<id>`；若手工删了旧目录再回滚 → `422 validation_failed` + `file_missing`，**不静默换成内置音色**
- [ ] `cosyvoice` / `omnivoice` 出现在 `/voices/backends` 里但 `catalogued:false`、`sources:[]`；参数页没有它们的可编辑字段

**三处一致**

- [ ] 对下表逐字比：`docs`、计划 Task 12 / 12B、预览页三处的类名、端点、错误码、字段名完全相等

| 名称类 | 唯一写法 |
|---|---|
| 组件 | `ParamTree` / `ParamField` / `EffectBadge` / `FixedField` / `VoicePicker` / `VoiceLibraryTable` / `VoiceCreateDialog` / `VoiceAudition` |
| 路由 | `/console/params` / `/console/voices` |
| 端点 | `GET|POST /api/v1/voices`、`GET /api/v1/voices/{id}`、`GET /api/v1/voices/{id}/audio`、`POST /api/v1/voices/{id}/duplicate`、`DELETE /api/v1/voices/{id}`、`GET /api/v1/voices/backends` |
| 错误码 | `voice_not_found` / `voice_name_taken` / `voice_audio_invalid` / `voice_too_large` / `voice_consent_required` / `voice_in_use` / `voice_expired` / `voice_precompute_failed` / `voice_precompute_busy` / `voice_binding_conflict` |
| 徽标 | `启动` / `热更新` / `启动 + 热更`；风险类别 `安全` / `隐私` / `环境绑定` |
| 状态词 | `draft`=制作中 / `precomputing`=预计算中 / `ready`=可用 / `failed`=制作失败 |

## 15. 附录 A：管理 API 契约

### A.0 通用约定

本附录定义**三组**契约，不要混用：

| 组 | Base | 调用方 | 鉴权 | 错误体 |
|---|---|---|---|---|
| 运维面 | `/api/v1`（同源，`http://<host>:8000/api/v1`） | `console/frontend` 运维分支 | JWT（HS256），`Authorization: Bearer <access_token>` | `{"code","message","detail","requestId"}` |
| 演示面 | `/api`（同源，同一端口） | `console/frontend` 对话页 | 无（匿名 cookie）或 HF OAuth 会话 | FastAPI 默认 `{"detail": …}`，**不套包络**（A.13） |
| 机对机 | `http://127.0.0.1:8765/internal`（回环，不出容器） | `console/backend` | `Authorization: Bearer <S2S_INTERNAL_TOKEN>` | `{"error":{"code","message"}}`（沿用 `demo` 侧形状，不会出现在前端） |

三组同源但不同前缀：`/api/v1/*` 与 `/api/*` 只差一段路径，**但鉴权与响应形状完全不同**。路由注册顺序与中间件必须按前缀分流，并且 `StaticFiles` 必须最后挂（§10.2.3）。

运维面契约的通用项：

| 项 | 约定 |
|---|---|
| 成功包络 | `{"code":200,"message":"success","data":<payload>}`；HTTP 状态码与 `code` 一致 |
| 错误包络 | `{"code":"<machine_code>","message":"...","detail":[{...}],"requestId":"..."}`；`message` 不含输入值（B7） |
| 错误码 | 稳定机器标识：`unauthorized`、`forbidden`、`invalid_parameter`、`version_conflict`、`validation_failed`、`vram_budget_exceeded`、`publish_in_progress`、`render_failed`、`restart_unavailable`、`healthcheck_timeout`、`pipeline_token_missing`、`pipeline_unavailable`、`pool_unreachable`、`catalog_unavailable`、`db_unavailable`、`unknown_profile`、`unknown_version`、`version_not_rollbackable`、`no_draft`、`runtime_unavailable`、`logs_unavailable`、`log_window_too_large`、`log_analysis_busy`、`log_analysis_rate_limited`、`log_analysis_unavailable`、`log_analysis_timeout`、`voice_not_found`、`voice_name_taken`、`voice_audio_invalid`、`voice_too_large`、`voice_consent_required`、`voice_in_use`、`voice_expired`、`voice_precompute_failed`、`voice_precompute_busy`、`voice_binding_conflict`、`catalog_entry_missing`。前端据此翻译文案，不解析 `message` |
| 字段命名 | HTTP 载荷 camelCase（`baseVersion`、`auditId`、`durationS`、`poolSize`）；**catalog 条目字段保持 snake_case**（`source_priority`、`change_cost`、`source_ref`），因为它是 `parameter-catalog.yaml` 的直映（§6） |
| 鉴权缺省 | 除 `GET /health` 外全部端点要求 JWT；缺失/过期 → `401 unauthorized`；角色不足 → `403 forbidden` |
| 并发控制 | 写操作可带 `If-Match: <version>`；带了且过期 → `409 version_conflict`；不带视为首次写入 |
| 内容类型 | `application/json; charset=utf-8` |
| 密钥字段 | 读接口一律 `***`；写后不可回读（B5） |
| 审计 | 写操作在 `data.auditId` 返回，可用 A.8 反查 |
| 分页 | `?page=1&pageSize=50` → `data{list,total,page,pageSize}` |
| 时间 | ISO 8601 UTC；本地化展示由前端 dayjs 负责 |
| 追踪 | 请求头 `X-Request-Id` 可入参，缺失则后端生成；响应头与日志同值 |

#### A.0.1 认证与健康

| 端点 | 请求 | 200 `data` | 错误 |
|---|---|---|---|
| `POST /api/v1/auth/login` | `{username, password}` | `{accessToken, tokenType:"bearer", expiresIn:1800, refreshToken, user:{username, role}}` | `401 invalid_credentials`、`429 too_many_attempts`（5 次/5 分钟，§12 R13） |
| `POST /api/v1/auth/refresh` | `{refreshToken}` | 同 login 的 token 段 | `401 invalid_refresh_token` |
| `GET /api/v1/auth/me` | — | `{username, role, lastLoginAt}` | `401` |
| `GET /api/v1/health` | — | `{"status":"ok","version":"…"}`（**不套 `ApiResponse`**） | `503 db_unavailable` |

`/health` 是唯一裸响应：它被 `docker-compose.yml` 的 healthcheck 直接消费（§13.4），多一层包络只会让探测脚本多一次解包。`/api/config` 在演示面里也同样是裸对象，原因不同——它是 `demo` 的公共契约（A.13）。

#### A.0.2 角色与权限矩阵

| 端点 | admin | operator | 说明 |
|---|---|---|---|
| `GET /catalog`、`GET /status`、`GET /instances` | ✓ | ✓ | 只读 |
| `GET /profiles/{id}/draft`、`GET .../versions`、`GET .../audit` | ✓ | ✓ | 只读 |
| `POST /profiles/{id}/draft`，patch 只含 `basic` / `advanced` | ✓ | ✓ | operator 的写面上限（`OPERATOR_EXPOSURE`） |
| `POST /profiles/{id}/draft`，patch 含 `expert` / `ops` | ✓ | ✗ `403 forbidden`（`detail[]` 逐个列出越权字段） | 整份 patch 拒绝，不做“丢掉越权键后部分写入” |
| `DELETE /profiles/{id}/draft` | ✓ | ✗ | 丢弃草稿是破坏性动作 |
| `POST /profiles/{id}/publish`、`POST .../rollback` | ✓ | ✗ | 会重启 pipeline 子进程（中断活跃语音会话），不重启容器 |
| `POST /sessions/update` | ✓ | ✓ | 只改活跃会话，不写文件 |
| `GET /runtime/models` | ✓ | ✓ | 只读；采集失败只体现在 `reasons`，不因下游不可达报错 |
| `GET /logs` | ✓ | ✓ | 只读四份 supervisor 日志文件；无写入/删除入口 |
| `logs` / `logs.analyze` | 见 §3.10；两者都只读，不写配置 |
| `voices` 列表 / 详情 / 试听 | 见 §3.11、A.18；只读 |
| `voices` 新建 / 复制 / 删除、音色绑定写进草稿 | 见 A.18；删除在“有引用”时 `409 voice_in_use`；绑定本身走 A.3 的权限（`operator` 只能绑 `basic` / `advanced` 字段，`qwen3_tts_ref_*` 是 `expert` → 403） |

### A.1 `GET /api/v1/catalog`

返回字段目录（可按级别过滤）。catalog 以只读挂载注入（§12 R17），不从镜像内 COPY。

| 项 | 内容 |
|---|---|
| Query | `exposure=basic,advanced`（可选，逗号分隔）；`stage=vad`（可选）；`backend=silero`（可选） |
| 200 `data` | `{schema:"s2s-parameter-catalog-v1", generatedFrom:"speech-to-speech-src@<commit>", parameters:[{stage, backend, name, type, default, choices, required, source_priority, effect, exposure, impact, change_cost, risk, source_ref}]}` |
| 语义 | 只读；`default` 一律由后端给出，前端不自行推导；`risk` 仅 `ops` 级非空（§7.2）；`generatedFrom` 取 catalog 文件顶层的 `generated_from`，供 §12 R17 的漂移核对 |
| 错误 | `401`、`503 catalog_unavailable`（文件缺失或 schema 不符） |

### A.2 `GET /api/v1/profiles/{id}/draft`

| 项 | 内容 |
|---|---|
| 200 `data` | `{profile:"prod", baseVersion:7, draft:{"<field_path>": <value>}, updatedAt:"…", updatedBy:"…"}` |
| 语义 | `draft` 是**覆盖集合**（只含真正改过的字段），不是完整配置；密钥字段回 `***`；无草稿时 `draft:{}` 且 `baseVersion` 为当前 `live` 版本 |
| 错误 | `401`、`404 unknown_profile` |

### A.3 `POST /api/v1/profiles/{id}/draft`

| 项 | 内容 |
|---|---|
| 请求头 | `If-Match: 7`（可选；缺失即不比对） |
| 请求体 | `{"patch": {"vad.min_silence_ms": 700, "llm.responses_api_api_key": "<secret>"}, "baseVersion": 7}` |
| 200 `data` | `{draft:{...}, validation:{ok:true, resolvedPipelines:["prod"], mode:"runtime"}, auditId:"…"}` |
| 语义 | patch 合并；`null` 表示“回退到 catalog 默认值”且**保留该键**；密钥落库加密、读取回 `***`；`mode` 为 `runtime` 或 `structural`，后者必须在 UI 显式提示“仅结构校验”，不得当成通过（§11.2） |
| 错误 | `400 invalid_parameter`（未知字段）、`403 forbidden`（operator 改 `expert`/`ops`）、`409 version_conflict`、`422 validation_failed`（`detail[{field, expected, got, source_ref}]`）、`401` |

### A.4 `DELETE /api/v1/profiles/{id}/draft`

| 项 | 内容 |
|---|---|
| 200 `data` | `{discarded:true, revertedTo:"catalog-defaults" 或 "<version>", auditId:"…"}` |
| 语义 | 丢弃草稿**不产生版本**，`live` 配置不受影响；语义承接原 `demo/param_platform/drafts.py` 的同名端点 |
| 错误 | `401`、`403 forbidden`、`404 no_draft` |

### A.5 `POST /api/v1/profiles/{id}/publish`

| 项 | 内容 |
|---|---|
| 请求头 | `If-Match: 7`（可选） |
| 请求体 | `{"baseVersion": 7, "note": "把判停从 700 调到 900"}` |
| 200 `data` | `{version:8, status:"live", healthcheck:{poolSize:2, inUse:0}, durationS:41.2, auditId:"…"}` |
| 流程 | 即 §4.1 步骤 2–9；单飞锁按 profile 生效（§4.3）；`status` 只能是 `live` 或 `rolled_back` |
| 错误 | `409 publish_in_progress`、`409 version_conflict`、`422 validation_failed`、`422 vram_budget_exceeded`（`detail` 含 `maxAllowed`）、`500 render_failed`、`502 restart_unavailable`、`504 healthcheck_timeout`（已自动回滚，`status=rolled_back`） |

### A.6 `POST /api/v1/profiles/{id}/rollback`

| 项 | 内容 |
|---|---|
| 请求体 | `{"targetVersion": 7, "note": "v8 探活超时"}` |
| 200 `data` | `{version:9, rolledBackTo:7, status:"live", auditId:"…"}` |
| 语义 | 回滚**产生新版本号**（9），不删除 v8；`rolledBackTo` 指内容来源版本；执行前重跑 validator（§12 R8） |
| 错误 | `404 unknown_version`、`409 version_not_rollbackable`（目标非 `live`/`rolled_back`）、`422 validation_failed`（换机后路径失效等）、`502 restart_unavailable`、`504 healthcheck_timeout` |

### A.7 `GET /api/v1/profiles/{id}/versions`

| 项 | 内容 |
|---|---|
| Query | `?page=1&pageSize=20`（倒序，新在前） |
| 200 `data` | `{list:[{version:9, status:"live", author:"alice", note:"…", createdAt:"…", durationS:41.2, rolledBackTo:7 或 null}], total, page, pageSize}` |
| 语义 | append-only；`status ∈ draft / validated / publishing / live / rolled_back / failed`（§4.3）；回滚目标候选 = `live` 与 `rolled_back`，环境绑定字段失效的版本只展示不可选（§12 R8） |
| 错误 | `401`、`404 unknown_profile` |

### A.8 `GET /api/v1/profiles/{id}/audit`

| 项 | 内容 |
|---|---|
| Query | `from` / `to`（ISO 8601）；`actor`；`action`；`result`；`field`；分页参数 |
| 200 `data` | `{list:[{auditId, at, actor, role, action:"draft.patch"/"draft.discard"/"publish"/"rollback"/"session.update", version, fields:["<field_path>"], result:"ok"/"failed", errorCode:null, durationS, requestId}], total, page, pageSize}` |
| 语义 | **只记字段名不记值**（§10.1）；`actor` 是 JWT 的 `sub`（登录用户名），不再是共享 token + `X-Operator` 头。原 `demo` 侧审计缺少 `role` / `requestId` 两列，迁移时补齐（§14.1） |
| 错误 | `401`、`404 unknown_profile` |

### A.9 `POST /api/v1/sessions/update`

链路 B 的控制台入口。请求体与响应沿用 §5.3 的语义，但**载荷在这里先按 §2.2 白名单剪一遍**，再转发 A.12。

| 项 | 内容 |
|---|---|
| 请求体 | `{"scope":"all"/"pipeline"/"session", "target": <index> 或 <sessionId> 或 null, "session": {…}}` |
| 允许字段 | `instructions`、`audio.input.turn_detection`、`audio.input.transcription.language`、`extensions`；其他键（含 `model`、`audio.output.voice`）→ `400 unsupported_field`，**不静默丢弃** |
| 200 `data` | `{updated:["<session_id>"], failed:[{sessionId, error}], auditId:"…"}` |
| 语义 | 部分失败不回滚（幂等覆盖写，§12 R10）；响应同时附 `hint` 文案提醒“只影响当前活跃连接”（§5.4） |
| 错误 | `400 unsupported_field`、`400 invalid_request_error`（语言不被支持、`auto` 不可重置）、`422 invalid_session_type`（`transcription` 会话）、`501 not_implemented`（§5.1 源码改动未落地）、`502 pipeline_token_missing`、`502 pipeline_unavailable`、`401` |

### A.10 `GET /api/v1/instances`

| 项 | 内容 |
|---|---|
| 200 `data` | `{profile:"prod", version:8, container:{name, status, startedAt, image}, pool:{size:2, inUse:1, units:[{index:0, state:"active", sessionId:"…"}, {index:1, state:"idle", sessionId:null}]}, usage:{...}, alerts:[...]}` |
| 数据来源 | supervisor `getState("pipeline")` + `getpid`（替代 `docker inspect`）+ `GET /v1/pool`（`websocket_router.py:639`）+ `GET /v1/usage`（`:615`）；前端只调本端点（B1） |
| 语义 | 只读聚合。`pool` 不可达时 `pool` 为 `null` 且 `alerts:["pool_unreachable"]`，**HTTP 仍 200**——实例页的价值恰好在 pipeline 挂掉时仍能展示容器状态；`state=stuck` 时同样走 `alerts`，不靠 HTTP 错误码表达 |
| 错误 | `401`（不因下游不可达而报错） |

### A.11 `GET /api/v1/status`

| 项 | 内容 |
|---|---|
| 200 `data` | `{profile:"prod", version:8, status:"live", catalogCommit:"<sha>", validatorMode:"runtime", db:"ok", pipeline:"ok" 或 "unreachable", internalTokenConfigured:true}` |
| 语义 | 顶栏与发布闸门的数据源：`internalTokenConfigured=false` 时链路 B 按钮置灰并给出环境变量名；`validatorMode=structural` 时发布前弹二次确认 |
| 错误 | `401`；`db` 不可达时仍 200 且 `db:"unavailable"` |

### A.12 `POST /internal/sessions/update`（pipeline 侧，机对机）

热更新在 pipeline 中的落地端点，需先完成 §5.1 的源码改动。未改动前该路由不存在（404），`console` 把 404 映射成 `501 not_implemented` 并提示“走链路 A”。

| 项 | 内容 |
|---|---|
| Base | `http://127.0.0.1:8765/internal`；回环，不出容器，也不经 `:8000` 反代暴露 |
| 鉴权 | `Authorization: Bearer <S2S_INTERNAL_TOKEN>`，`hmac.compare_digest` 比较；变量未配置 → `503 internal_token_missing`（fail closed，§5.2） |
| 请求体 | `{"scope": "all"/"pipeline"/"session", "target": <index> 或 <session_id> 或 null, "session": {<OpenAI Realtime session 部分字段>}}` |
| 允许字段 | 同 §2.2；其他字段 → `400 unsupported_field` |
| 200 响应 | `{"updated": ["<session_id>"], "failed": [{"session_id": "…", "error": "invalid_request_error"}]}`（**裸对象**，不套 `ApiResponse`） |
| 语义 | 逐连接调 `SessionHandler.handle_session_update`，复用其合并、语言校验与 `invalid_session_type` 拒绝；控制台侧不复制任何校验逻辑（§3.2.2） |
| 错误 | `400 unsupported_field`、`400 invalid_request_error`、`422 invalid_session_type`、`401 unauthorized`、`503 internal_token_missing` |

`console` 只做三件事：按白名单剪载荷、透传、把机对机错误体翻译成运维面错误包络（`401`/`503` → `502 pipeline_token_missing`，连不上 → `502 pipeline_unavailable`，`400`/`422` 原样透出）。

### A.13 演示面契约（`/api/*`，与 `demo` 字节兼容）

三条硬约定：

1. **不套 `ApiResponse`**：直接返回对象或 FastAPI 默认 `{"detail": …}`。前端对话页与旧页共用同一形状。
2. **路径、方法、状态码不变**：`demo/server.py` 的 11 组路由逐个搬，不重命名、不合并、不加版本前缀。
3. **条件关闭用 404 而不是 403**：未配置 `LOAD_BALANCER_URL` 时 `/api/session`、`/api/queue/*` 一律 404——`demo` 的注释写得很清楚（"404 so it's indistinguishable from a missing route"），这是防探测设计，不得"改进"成 403。

| 端点 | 方法 | 启用条件 | 关键返回 | 语义要点 |
|---|---|---|---|---|
| `/api/config` | GET | 总是 | `{search, lb, allowDirect, s2sUrl, rtc, iceServers, startupGreeting}` | 引导配置；**绝不下发 `LOAD_BALANCER_URL` 本身** |
| `/api/me` | GET | 总是 | 未启用计量 → `{"enabled": false}`；启用 → `{enabled, auth, …, remainingSec, limitSec, loginUrl, logoutUrl}` | 首次访问设置匿名跟踪 cookie |
| `/api/search` | POST | `SERVER_SEARCH = bool(SERPER_KEY) and (AUTH_ENABLED or not SPACE_ID)` | Serper 原始结果 | 服务端 key 要过 `_search_gate`（需活跃会话）；用户自带 key 仅用于当次 |
| `/api/calls` | POST | `bool(SPEECH_TO_SPEECH_URL)`，否则 404 | SDP answer 原文 | **只转发到环境变量钉死的地址**；一旦接受客户端目标就是开放代理（SSRF） |
| `/api/session` | POST | `bool(LOAD_BALANCER_URL)`，否则 404 | LB 的 `{connect_url, …}` + 计量字段 | 预算耗尽 → 402；`connect_url` 必然暴露，但 LB 稳定地址不暴露 |
| `/api/queue/{id}` | GET | 同上 | 位次，或排到头部时的 grant | 排到头部时**在此刻重新校验预算**（等待期间预算可能已被别处花掉） |
| `/api/queue/{id}` | DELETE | 同上 | `{"ok": true}` | "离开队列"按钮 |
| `/api/queue/end` | POST | 同上 | `{"ok": true}` | 给 `navigator.sendBeacon` 用；body `{queueId}`；只支持 POST |
| `/api/session/heartbeat` | POST | `LIMITER_ENABLED`，否则 404 | `{"expired": bool}` | 逐块续期；`expired=true` 时前端必须拆会话 |
| `/api/session/end` | POST | `LIMITER_ENABLED`，否则 404 | `{"ok": true}` | 按真实时长结算并退回未用块；**无响应也必须成功** |
| `/vendor/openai-realtime-agents.umd.js` | GET | 总是 | `text/javascript` | 构建期烤入；缺失 503 `asset_missing` |
| `/vendor/local-vad/{filename}` | GET | 总是（仅 6 个白名单文件名） | 按扩展名定 media type | 非白名单 → 404；缺失 503 `asset_missing` |

为什么 `/api/calls` 与 `/v1/realtime` 并存：WebRTC 的 SDP 握手走 `/api/calls`（浏览器无法向 `8765` 跨源 POST `application/sdp`），WebSocket 传输直接走同源 `/v1/realtime` 反代。两条路都不需要 CORS，也不需要把 LB 地址发到浏览器。

## A.14 `GET /api/v1/runtime/models`

实例页「模型运行时」四张卡的数据源。只读旁路：任何一个来源失败都只让对应字段变 `null` 并在 `reasons` 里写码，**不返回 5xx**（实例页的价值恰好在 pipeline 不正常时）。

| 项 | 内容 |
|---|---|
| Query | `profile=prod`（可选，缺省取顶栏当前 profile）；`windowS=300`（可选，60–3600） |
| 200 `data` | `{profile, collectedAt, windowS, gpu:{available, name, totalMb, usedMb, percent, reason?}, stages:[{stage, modelName, backend, loaded, vram:{usedMb, percent}, busy:{inUse, size, occupied, queueDepth}, latency:{firstByteMs, processMs, p50Ms, p95Ms}, reasons:{<field>:"<code>"}}], alerts:[]}` |
| `stage` 枚举 | `vad` / `stt` / `llm` / `tts`，固定四条，顺序即上表顺序 |
| `reasons` | 以字段名为键：`loaded` / `vram` / `busy` / `queueDepth` / `firstByte` / `latency`。**不变式：某字段为 `null` 或 `false` 时必须有一个对应 reason，为有效值时不得带 reason**（单测按这条断言） |
| 取值码 | `config_unreadable`、`pipeline_stopped`、`no_metrics_window`、`nvidia_smi_missing`、`vram_not_attributable`、`pool_unreachable`、`queue_depth_not_exposed`、`first_byte_not_instrumented`、`not_applicable`（VAD 没有首字节概念） |
| `gpu` | `nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader,nounits`；失败 → `{available:false, reason:"nvidia_smi_missing"}`，四张卡照常返回 |
| `alerts` | `pipeline_stopped` / `vram_pressure`（任一 `percent ≥ 0.9`）/ `pool_unreachable` / `runtime_degraded`（采集超时，返回上一帧） |
| 采集预算 | 整体 `asyncio.wait_for(2.0s)` + 进程内 `TTL=3s`；`nvidia-smi` 与 `model_metrics.log` 解析全部 `asyncio.to_thread`；前端 5s 轮询、页签切走即停（§3.9.1 第 4 条） |
| 错误 | `401`；`404 unknown_profile`；profile 读不到时 200 + `reasons`，不报 500 |

### A.15 `GET /api/v1/logs`

实例页日志面板。只读 `/var/log/supervisor/{console,pipeline}-{stdout,stderr}.log` 四份文件，**没有**写入、删除、轮转、改级别入口。

| 项 | 内容 |
|---|---|
| Query | `process=console,pipeline`（可多值，缺省两者）；`level=ERROR,WARN,INFO`（可多值，缺省全部）；`from`/`to`（ISO 8601，缺省最近 15 分钟）；`q`（子串，大小写不敏感，≤ 200 字符）；`after`（上一页的 `nextCursor`）；`limit`（默认 500，上限 2000） |
| 200 `data` | `{lines:[{ts, process:"pipeline", stream:"stderr", level:"ERROR", text:"…", file:"pipeline-stderr.log", offset:12345}], nextCursor:"…", reset:false, truncated:false, scanned:{files:4, bytes:262144}, sources:[{file, size, mtime}]}` |
| cursor | 服务端把 `{inode, offset}` 编码成不透明串，前端**不解析**。文件被轮转（inode 变化）或变小 → `reset:true` 且从头读，前端清空已加载行并提示「日志已轮转」 |
| `level` 推断 | 行内含 `"level":"error"` / `ERROR` / `Traceback (most recent call last)` → `ERROR`；`WARNING`/`WARN` → `WARN`；其余 `INFO`。**不引入 `unknown` 档**，否则按级别过滤时会整类消失 |
| 读取预算 | 单次只读文件尾部 ≤ 256 KiB；`asyncio.to_thread` + `wait_for(1.5s)`；超时返回已读部分 + `truncated:true`，**不 504** |
| 语义 | 只读聚合；不落库、不回填、不做跨文件排序以外的加工（`lines` 按 `ts` 升序，同 `ts` 按 `process` 稳定排序）；日志里出现密钥值属日志卫生缺陷（§12），该端点不负责擦除，只在 A.16 发送前脱敏 |
| 错误 | `401`；`400 invalid_parameter`（`limit` 越界、时间格式错、`from > to`、`q` 超长）；`503 logs_unavailable`（目录不存在或无读权限） |

### A.16 `POST /api/v1/logs/analyze`

LLM 归纳。能力边界见 §3.10，这里只定契约。

| 项 | 内容 |
|---|---|
| 请求体 | `{from, to, process?, level?, q?, maxLines?, includeTurnLatency?}`；`maxLines` 默认 800、上限 2000；`includeTurnLatency` 默认 `true`（§3.10 的轮次摘要） |
| 200 `data` | `{analysisId, model, durationMs, sent:{lines, estimatedTokens, truncated, droppedLines, turnRows}, result:{errors[], critical[], rootCauses[], actions[]}, auditId}` |
| `sent` | **必填**，即使没有截断也要回 `truncated:false, droppedLines:0, turnRows:0`；`estimatedTokens` 是 `ceil(chars/4)` 的估算值，UI 必须标注「估算」 |
| 四块输出 | `errors[]`：`signature` / `count` / `firstSeen` / `lastSeen` / `level` / `sample`；`critical[]`：`signature` / `impact` / `rationale` / `evidence`；`rootCauses[]`：`hypothesis` / `confidence` / `evidence`；`actions[]`：`title` / `detail` / `expectedEffect` / `risk`（形状与 §3.10 一致，不多不少） |
| 语义 | 单飞（并发第二个 → `429 log_analysis_busy`）、5 分钟 6 次（→ `429 log_analysis_rate_limited`）、单次 `timeout=45s`（→ `504 log_analysis_timeout`）；脱敏与截断在组装 prompt 前完成并计入 `sent`；走回环 `POST 127.0.0.1:8765/v1/chat/completions`，未启用或后端非远程 → `502 log_analysis_unavailable`，**不回退本地模型**（§3.10） |
| 审计 | 成功后写一条 `param_audit`：`action="logs.analyze"`、`detail` 只含 `from/to/process/level/q/sentLines/estimatedTokens/turnRows` 与 200 字 `summary`——**无原始日志、无轮次明细、无密钥、无模型原文**（B12） |
| 错误 | `400 invalid_parameter`、`400 log_window_too_large`（> 24h）、`429 log_analysis_busy`、`429 log_analysis_rate_limited`、`502 log_analysis_unavailable`、`504 log_analysis_timeout`、`401` |

### A.17 `GET /api/v1/turn-latency`

轮次延迟的读取面（§3.9.4）。只读；事实源是 `/var/log/supervisor/pipeline-stdout.log` 里的 `TURN_LATENCY` 行，`turn_latency` 表只是索引。

| 项 | 内容 |
|---|---|
| Query | `from`/`to`（ISO 8601，缺省最近 15 分钟，最大 24h）；`status`（可多值：`completed,cancelled,failed,incomplete`）；`limit`（明细行数，默认 100，上限 500） |
| 200 `data` | `{window:{from,to}, summary:{count, completed, failed, cancelled, incomplete, failureRate, e2e:{p50Ms,p95Ms,maxMs}, stages:{stt:{p50Ms,p95Ms}, llm:{p50Ms,p95Ms}, ttsTtfa:{p50Ms,p95Ms}, vadDecision:{p50Ms,p95Ms}, hold:{p50Ms,p95Ms,unavailableCount}}}, rows:[{loggedAt, responseKey, turnRevision, source, status, smartStatus, e2eMs, sttMs, llmMs, ttsTtfaMs, vadDecisionMs, holdMs}], truncated:false, index:{lagS, ingestedAt, sources:[{file,size,mtime}]}, reasons:{<field>:"<code>"}}` |
| 空窗 | `count:0` 不是错误：`summary` 的数值字段为 `null` 且 `reasons.summary="no_turn_rows"`；前端写「该时间窗没有轮次记录」，**不显示 0 ms** |
| 理由码 | `no_turn_rows`（窗口内无行）/ `index_lag`（`index.lagS > 30`，聚合值不可当现状看）/ `log_missing`（`/var/log/supervisor` 下无 pipeline 日志）/ `indexer_never_ran`（进程刚起、cursor 未建立） |
| 语义 | 只读；无写入、无删除、无重算入口；聚合在 `asyncio.to_thread` 里做，单次 ≤ 2 000 行（超出的旧行计入 `truncated`）；`p95` 用最近秩（nearest-rank），不插值；`hold` 为 `null` 的行计入 `unavailableCount` 而不是当 0 |
| 错误 | `401`；`400 invalid_parameter`（时间格式、`from > to`、跨度 > 24h、`status` 非法、`limit` 越界）；`503 turn_latency_unavailable`（迁移未执行） |

### A.18 `GET /api/v1/voices`（音色库）

音色制作与选择（§3.11）。只写 `voices` 表与 `/app/data/voices/`，**不碰** `config/`、不重启、不调 `/internal/*`。

| 端点 | 请求 | 200 `data` | 错误 |
|---|---|---|---|
| `GET /api/v1/voices` | `?backend=&source=&q=&status=&page=1&pageSize=50` | `{list:[{id,name,source,backend,language,status,audioSeconds,createdAt,createdBy,refCount,usedBy:{profiles,versions}}],total,page,pageSize}` | `401` |
| `POST /api/v1/voices` | `multipart/form-data`：`name`、`source`、`backend`、`language`、`consent="biometric-ack"`、`retentionDays`、`trimStartMs`、`trimEndMs`、`audio`（`clone` 必填）、`refText`（`clone` 必填）、`instruct`（`design` 必填） | `{id,status:"precomputing",jobId}` | `400 voice_audio_invalid`、`400 voice_consent_required`、`409 voice_name_taken`、`413 voice_too_large`、`422 validation_failed`（`design` 但本次后端不是 VoiceDesign）、`429 voice_precompute_busy` |
| `GET /api/v1/voices/{id}` | — | `{id,name,source,backend,language,status,audioSeconds,trimStartMs,trimEndMs,refText,instruct,createdAt,createdBy,consentAckAt,retentionDays,precompute:{stage,progress,errorCode},usedBy:{profiles,versions}}` | `404 voice_not_found` |
| `GET /api/v1/voices/{id}/audio` | 支持 `Range` | `audio/wav`（裸响应，不套包络） | `404 voice_not_found`、`410 voice_expired` |
| `POST /api/v1/voices/{id}/duplicate` | `{name?}` | `{id,name,status}` | `404 voice_not_found`、`409 voice_name_taken` |
| `DELETE /api/v1/voices/{id}` | — | `{deleted:true}` | `404 voice_not_found`、`409 voice_in_use`（`detail[{field:"profiles",value:[…]},{field:"versions",value:N}]`） |
| `GET /api/v1/voices/backends` | — | `{list:[{backend,stage,catalogued,sources:["builtin","clone","design"],fields:{speaker,refAudio,refText,refSpk,refRvq,instruct},notes}]}` | `401` |

`GET /voices/backends` 是唯一告诉前端“哪些来源可用”的接口：`catalogued:false` 的 19 个 B4 目录化后端（含 `cosyvoice` / `omnivoice`）只出现在这张表里，`sources:[]`、`fields:{}`、`notes:"字段未进机器目录"`，参数页据此渲染只读后端卡而不是可编辑表单（§3.11.1）。前端不内置后端清单，也不根据名字前缀猜绑定字段。

`status` 的四个值在 UI 上的固定文案：`draft` → 制作中（未预计算）、`precomputing` → 预计算中（带进度）、`ready` → 可用、`failed` → 制作失败（附 `errorCode`）。只有 `ready` 可以被 `VoicePicker` 选中。

## 16. 附录 B：MinWorkBuddy 技术栈核对证据

核对日期 2026-10-24，对象 `D:\projects\MinWorkBuddy`。**只读**：未修改该仓库，未复制其业务代码；下表每个版本号都能在所述文件中逐字查到，§3.4.1 / §3.4.2 的选型表即由本表归纳，取舍差异编号见 §3.4.3。

### B.1 前端

| 项 | 核对文件 | 证据 | `console/frontend` 采用 |
|---|---|---|---|
| 语言 | `frontend/package.json:71`、`frontend/tsconfig.json` | `"typescript": "^5.4.2"`；`strict` + `noUnusedLocals` + `noUnusedParameters` + `ES2020` | 同 |
| 框架 | `frontend/package.json:46` | `"vue": "^3.4.21"` | 同 |
| 路由 / 状态 | `frontend/package.json:49`、`:45` | `vue-router ^4.3.0`、`pinia ^2.1.7` | 同 |
| UI 组件库 | `frontend/package.json:35`、`:23` | `ant-design-vue ^4.1.2`、`@ant-design/icons-vue ^7.0.1` | 同 |
| 样式方案 | `frontend/package.json:68`、`:70` | `less ^4.6.3`（另有 `sass ^1.71.1`） | 只用 Less；不引 Sass |
| HTTP | `frontend/package.json:36` + `frontend/src/utils/request.ts` | `axios ^1.6.7`；`axios.create({baseURL: getApiBase(), timeout: 30000})` + 拦截器注入 `getToken()` | 同构：`src/api/client.ts` 单实例 |
| 时间 / i18n | `frontend/package.json:39`、`:48` | `dayjs ^1.11.10`、`vue-i18n ^9.13.1` | 同（i18n 只出 zh-CN，保留机制） |
| 图表 | `frontend/package.json:41`、`:24`、`:47` | `echarts ^5.5.0`、`@antv/g2 ^5.4.8`、`vue-echarts ^6.6.9` | **不引**：实例页用量用表格 + 进度条足够 |
| 包管理器 | `frontend/` 根目录 | 只有 `package-lock.json`，无 `pnpm-lock.yaml` → **npm** | npm，提交 `package-lock.json` |
| 构建工具 | `frontend/package.json:72`、`:63`、`:74` | `vite ^5.1.5`、`@vitejs/plugin-vue ^5.0.4`、`vue-tsc ^2.0.6` | 同；`vue-tsc --noEmit` + `vite build`（不用 `scripts/build.cjs`，D6） |
| 开发端口与代理 | `frontend/vite.config.ts` | `server.port = 3000`；`proxy['/api'] → env.VITE_API_BASE_URL`（未设置时回落 `http://localhost:8000`） | 同 |
| 路径别名 | `frontend/vite.config.ts`、`frontend/tsconfig.json` | `@` → `src`；`paths: {"@/*": ["src/*"]}` | 同 |
| 代码检查 | `frontend/package.json:66`、`:67`、`:61`、`:62`、`:19` | `eslint ^8.57.0`、`eslint-plugin-vue ^9.22.0`、`@typescript-eslint/{eslint-plugin,parser} ^7.1.1`；`lint` 脚本带 `--ext .vue,.ts,…` | 同（ESLint 8 而非 9，与上游一致） |
| 测试框架 | `frontend/package.json:73` + `frontend/vitest.config.ts` | `vitest ^2.1.9`；`environment:'node'`、`include:['src/**/*.spec.ts']`；未装 `@vue/test-utils` / `jsdom` / `happy-dom` | 同：只做纯逻辑单测，DOM 与旅程交 Playwright（§11.4） |
| 运行形态 | `frontend/Dockerfile.prod`、`frontend/nginx.default.conf` | 多阶段 `node:20-alpine` → nginx；`try_files $uri $uri/ /index.html`；静态资源 1y 缓存 + 安全头 | **不同**：多阶段 `node:20-alpine` 只产出 `dist/`，交给 console 的 `StaticFiles`；**无 nginx、无 `try_files`**（D7） |
| 反向代理 | `frontend/nginx.default.conf` | `location /api/ { proxy_pass http://<backend>; }`；`location /health` 单独转发 | **不同**：反代改在进程内（`routers/realtime.py`），开发态用 Vite proxy（§10.2.3） |
| 桌面壳 | `frontend/package.json:64`、`:65` | `electron ^44.2.0`、`electron-builder ^26.15.3` | **不引**（D1） |

核对中发现的一处不一致（作为取舍依据，**不照抄**）：`Dockerfile.prod` 写的是 `npm install -g pnpm` + `COPY package.json pnpm-lock.yaml`，而仓库只有 `package-lock.json`；同时 `package.json` 的 `test` 脚本是 `node --test src/utils/__tests__/audioDsp.spec.ts`，而 devDeps 装的是 Vitest。console 取“npm + `vitest run`”这条自洽路径（D2）。

### B.2 后端

| 项 | 核对文件 | 证据 | `console/backend` 采用 |
|---|---|---|---|
| 语言 / 基镜像 | `backend/Dockerfile` | `FROM python:3.11-slim` 多阶段（`build-essential` + `libpq-dev` → `libpq5`）；`ENV PYTHONPATH=/app` | **不同**：跟随 s2s 基座 `python-torch:cu128`（Python 3.12，D12），且**不是** slim（torch/CUDA 已预装） |
| API 框架 | `backend/requirements.txt:2`、`:3` | `fastapi==0.115.0`、`uvicorn[standard]>=0.31.1` | **写下界不写精确 pin**（`fastapi>=0.115.0`，D9）；只用 uvicorn 且 **必须 `--workers 1`**（§13.4） |
| 配置与校验 | `requirements.txt:25`、`:26`；`backend/app/config/_database.py` | `pydantic>=2.7.4,<3.0.0`、`pydantic-settings>=2.1.0`；`app/config/` 按关注点拆类 | 同 |
| ORM | `requirements.txt:8`；`backend/app/db/database.py` | `sqlalchemy>=2.0.35`；`create_engine` + `declarative_base` + `sessionmaker` + `get_db()` | 同 |
| 迁移 | `requirements.txt:13`；`backend/alembic/` | `alembic==1.13.1` | 同（`alembic/versions` 为唯一 DDL 来源） |
| 生产存储 | `requirements.txt:9`；`backend/env.example` | `psycopg2-binary>=2.9.10`；`DATABASE_URL` 拼 `postgresql://` | 保留但**默认不用**：默认 SQLite，PG 只在 `pg` profile 下启（§13.4） |
| 开发/测试存储 | `requirements-dev.txt:75` | `aiosqlite>=0.20` | 用**同步** SQLite（`sqlite:///./dev.db`），不引异步引擎 |
| JWT / 密码 | `requirements.txt:20`、`:21` | `python-jose[cryptography]==3.3.0`、`bcrypt>=4.0.0` | 同 |
| JWT 参数 | `backend/env.example` | `JWT_ALGORITHM=HS256`、`JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30`、`JWT_REFRESH_TOKEN_EXPIRE_DAYS=7` | 同 |
| 鉴权依赖 | `backend/app/deps.py` | `security = HTTPBearer()`；`get_current_user` / `require_admin` | 同（落在 `core/security.py`） |
| 令牌/密码实现 | `backend/app/services/auth_service.py` | `bcrypt.checkpw` / `hashpw`+`gensalt`；`jose.jwt` 编码解码；payload 含 `sub`、`tenant_id`、`exp` | 同，但**不带 `tenant_id`**（D3） |
| API 前缀 | `backend/env.example` | `API_PREFIX=/api/v1` | 同 |
| 响应包络 | `backend/app/schemas/common.py` | `ApiResponse[T]{code:int=200, message:str="success", data:Optional[T]}`；`PageParams{page, pageSize, keyword}`；`PageData[T]{list, total, page, pageSize}` | 同；`keyword` 只在审计检索上启用 |
| 路由注册 | `backend/app/core/router_registry.py` | `register_routers(app)` 声明式清单 | 同（新增/下线模块只改一处） |
| CORS | `backend/app/main.py`；`env.example` 的 `CORS_ORIGINS` | `CORSMiddleware(allow_origins=settings.cors_origins_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])` | 同；`allow_origins` 不得为 `*`（§10.2.2） |
| 健康检查 | `backend/app/main.py` | `@app.get("/health")` → `{"status":"ok","version":…}` | 同（A.0.1，同样不套包络） |
| 日志 | `requirements.txt:67` | `loguru==0.7.2` | 同（`core/logging.py`） |
| 出站 HTTP | `requirements.txt:29` | `httpx>=0.26.0` | 同（调 `/v1/pool`、`/v1/usage`、`/internal/*`） |
| 测试 | `requirements.txt:79`、`:80`；`backend/conftest.py` | `pytest==8.0.1`、`pytest-asyncio==0.23.5`；`conftest.py` 把 `backend/` 注入 `sys.path` | 同 |
| YAML 解析 | `requirements-dev.txt:78`（**仅 dev**） | `PyYAML>=6.0.1` | 提为**主依赖**：renderer 运行期必需（§3.4.2） |
| 分层目录 | `backend/app/{config,core,db,models,repositories,routers,schemas,services,middleware,utils}` + `deps.py` + `alembic/` + `conftest.py` | 与 §3.3.3 同构 | 同 |

不在 console 引入的依赖及理由：`celery` / `kombu` / `arq`（无后台任务）、`redis`（无缓存与队列）、`pgvector` / `neo4j` / `graphiti-core`（无向量与图谱）、`agentscope` / `mcp`（不承载对话与 MCP 服务）、`apscheduler`（实例视图靠前端轮询）。

### B.3 演示工程（`demo/`）依赖核对

核对日期 2026-10-24，对象本仓 `demo/`。本表解释 §3.4 里“语音客户端依赖”三行的出处，以及 D9 / D10 / D11 的取舍依据。

| 项 | 核对文件 | 证据 | `console` 采用 |
|---|---|---|---|
| 语音客户端 SDK | `demo/package.json:13` | `"@openai/agents": "0.14.3"` | 同版本；**只取 UMD 产物**（`@openai/agents-realtime/dist/bundle/openai-realtime-agents.umd.js`，D10） |
| 本地 VAD | `demo/package.json:14` | `"@ricky0123/vad-web": "0.0.31"` | 同版本；6 个白名单资产构建期拷入 `public/vendor/local-vad/` |
| WASM 运行时 | `demo/package.json:16` | `"onnxruntime-web": "1.22.0"` | 同版本（VAD 的传递运行期，显式声明以防升级漂移） |
| `hono` / `zod` | `demo/package.json:15`、`:17` | `4.13.0` / `4.4.3` | **不引**：全仓 `.js` / `.mjs` 中 0 处 import，它们是 `@openai/agents` 的传递依赖 |
| 测试运行器 | `demo/package.json:5-10` | `node --test` 跑 12 个 `.mjs`（adapter / ws / webrtc / playback / local-vad / visemes / turn-latency / ui） | 换 Vitest（D8）；**用例语义作基线**（§11.3） |
| e2e | `demo/package.json:20` | `"@playwright/test": "1.62.1"` | 同版本 |
| Python 依赖 | `demo/requirements.txt` | `fastapi==0.115.6`、`uvicorn[standard]==0.34.0`、`httpx==0.28.1`、`pyyaml==6.0.2`、`huggingface_hub[oauth]>=0.30,<1.0` | **全部改成下界**（D9）：s2s 的 `pyproject.toml` 已依赖 `fastapi>=0.115.0`、`uvicorn>=0.30.0`、`httpx>=0.28.0`、`PyYAML>=6,<7`、`huggingface-hub>=0.34.0`；其中 `huggingface_hub` 下界由 `0.30` 提到 `0.34`（跟随 s2s，OAuth 接口在两者间无破坏性变更） |
| `/vendor` 资产清单 | `demo/server.py:179-186` | `LOCAL_VAD_ASSETS` 恰好 6 个键；`demo/Dockerfile:18-19` 实际拷 7 个文件（多一个 `bundle.min.js.LICENSE.txt`） | 白名单保持 6 个；多拷的 LICENSE 不影响行为 |
| 镜像 | `demo/Dockerfile:1-19` | `node:24-slim` 构建阶段**只为拷 7 个 vendor 文件**进 `python:3.11-slim` | 不需要这个壳：前端阶段产出的是完整 `dist/`，vendor 已在其中（D10） |
| 端口 | `demo/Dockerfile:51-53` | `EXPOSE 7860`；`CMD uvicorn server:app --port 7860` | 改 `8000`（§13.4）；本行是全文唯一保留 `7860` 的地方，仅作为迁移证据 |

### B.4 核对方法与边界

逐文件只读读取，记录“路径 + 行号 + 原文字符串 + 版本约束”；凡未能逐字查到版本的项，不写入 §3.4 的表。本文只借技术选型：目录分层、错误体形状等可直接对齐，但不引入 MinWorkBuddy 的租户、Agent、知识库、Electron 等业务模型（D1–D6）；与本次拓扑变更相关的取舍单独编号 D7–D13（§3.4.3）。若后续 `MinWorkBuddy` 升级主版本，以本文 §3.4 的固定版本为准，不跟随漂移；需要升级时另开设计变更。
