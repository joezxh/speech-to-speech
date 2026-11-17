# Console 承担 S2S 数据面负载均衡（设计）

日期：2026-11-16
状态：**已评审定稿**（2026-11-16，需求方确认 §15 两项 + 全文）
范围：`console/backend`（数据面代理 + 选台）、`docker-compose.yml`（8765 收敛）、`config/prod.env`（前端入口切换）

决策一句话：**选台放在 console 内（复用已有 registry/allocator），nginx 若引入只做 console 多副本之间的 L4 轮询，不承担 S2S 选台语义。**

---

## 0. 修订记录

### 0.1 2026-11-17：注册表与配置落库

本文定稿后，需求方决定把**注册中心与运行配置整体搬到数据库**
（`docs/superpowers/specs/2026-11-17-console-db-backed-registry-and-config-design.md`）。对本文有两处变更：

1. **§5.1「能力指纹只驻留内存，不落库」改为落 `param_instance_runtime`**：理由是多副本
   共享（各副本探到的是同一批实例，最后写入者胜）+ 控制台重启不丢状态。它**仍不进
   seed、仍不混进 `param_instance_metric`**（那张表的列语义是槽位）。
2. **§14「本期不做：多副本共享分配状态（Phase 2）」本期落地**：占位落
   `param_allocator_lease` + `param_instance_runtime.reserved`，判定用带条件的原子
   UPDATE（SQLite 没有行锁，见新设计 §3.2）。

数据面语义（两套选台策略、WS 三种终态、静默换台、REST 错误码）**一律不变**。

### 0.2 2026-11-16：定稿前的评审

本文经一名未参与讨论的工程师按"拿到文档就能写实施计划"的标准核对过代码，共产出 16 项问题。处理结果：

| 类别 | 数量 | 处理 |
|---|---|---|
| 被代码证伪的事实错误 | 2 | 直接改正（见 F3、R2、R6） |
| 文档自相矛盾 | 3 | 改正（capabilities 存哪、WS 失败语义、grant 路径） |
| 缺判定规则 / 缺实现路径 | 7 | 补齐并写明取舍（§5.1/§5.4/§5.5/§6.1/§6.2） |
| 范围问题 | 2 | 一项由我做主砍掉（数据面 DELETE 路由），一项沿用既有约定 |
| 需要你拍板 | 2 | 见 §15 |

关键修正（会改变实现）：

1. **浏览器当前并不走 console**：`config/prod.env:21` 把 `SPEECH_TO_SPEECH_URL` 钉死成 `ws://localhost:8765/v1/realtime` → `allowDirect=true` → 前端**直连 8765**（`s2s-client.ts:260-265,271-273`）。这个 `localhost` 在任何真实部署里都是错的（浏览器的 localhost 不是服务器），是本地开发遗留。**清空它 → 前端自动回落同源 `/v1/realtime`（前端零改动）**，这是 8765 收敛的前置条件，已写进 T6。
2. **WS 握手阶段不存在 HTTP 503**：Starlette 在 `accept()` 前 `close()` 会让 ASGI 回 **HTTP 403 握手失败**，close code 送不到浏览器（`routers/realtime.py:74` 注释已指出）。原设计的"503 `no_available_instance`"与"close 1013"两种说法互斥，现统一为三种终态（§5.3）。
3. **能力探针的判定规则不完整**：声纹在未配 key 时回 **503**（`voiceprint/service.py:184-187`）而非 401；情感的 `/health` 会同步打 SER（5s 超时，`config/prod.env:56`）**必然超过 2s 的探针超时**。判定表已重写（§5.1）。
4. **数据面 `DELETE /v1/realtime/calls/{id}` 本期砍掉**：前端没有挂断调用（`console/frontend/src` 全文无 `realtime/calls` 的 DELETE），运维面 `POST /api/v1/instances/{id}/hangup` 已覆盖该需求。本期不做无调用方的路由。

---

## 1. 目标与非目标

### 1.1 目标

1. **Console 成为 S2S 唯一数据面入口**：浏览器语音链路、ASR、TTS、声纹、情感全部经 console `:8000` 进入，`8765` 收敛为容器内/内网端口。
2. **跨机负载均衡**：一台 console 管多台 pipeline 盒，按**空闲槽位 + 能力 + 权重**选台，而不是轮询连接数。
3. **复用已有控制面**：实例注册表、巡检、drain/undrain、容量模型、指标落库全部沿用 `instance_registry` / `instance_monitor` / `allocator`，不新建第二套语义。
4. **失败对浏览器不可见**：上游满员、连接失败、能力不匹配，浏览器看到的是"连不上"或最终错误，不看到中间态。

### 1.2 非目标

1. 不做多租户/权限树、不做用户级会话粘性。
2. 不改 `publish_flow_service` / `hot_update_service` 的语义：参数发布与热更**仍然只对本机 pipeline 生效**，远程实例走 `drain → 人工发布 → undrain`（现状即如此，`docs/console-service.md` §10.4）。
3. 不做 `PostgresAllocatorStore`（Phase 2），本期仍是进程内 `InMemoryAllocatorStore` + 单 worker。
4. 不改 pipeline 侧任何代码（`src/speech_to_speech/**` 零改动）。
5. 不引入 nginx / Traefik 容器编排依赖；nginx 若采纳是独立文件，不进主 compose（且只在 console 多副本 HA 时才需要）。

### 1.3 反目标（做了就算失败）

- **8765 仍在公网可达**：取消 publish 后仍能从宿主机直连 `8765` → 安全收敛没做到。
- **console 变成"只转发不判断"的透明代理**：选台逻辑若写在 nginx 而 console 只是转发，则 drain/容量模型/能力指纹全部失效。
- **选台退化为轮询**：最终实现若是"按连接数轮询"，pipeline 满员时仍会把会话打过去，等于重写了 allocator 却没解决问题。

---

## 2. 现状事实（代码证据）

| # | 事实 | 证据 |
|---|---|---|
| F1 | 容器内 console `:8000` 与 pipeline `:8765` 同镜像同容器，supervisord 双进程 | `console/deploy/supervisord.conf:13-25`、`docker-compose.yml:56-65` |
| F2 | 8765 **当前是 publish 的**（宿主机可直连） | `docker-compose.yml:63` `"8765:8765/tcp"` |
| F3 | console **具备** `/v1/realtime` 反代路由，但**当前部署下浏览器不用它**：`config/prod.env:21` 钉死 `SPEECH_TO_SPEECH_URL` → `allowDirect=true`（`demo_config_service.py:36`）→ 前端直连（`s2s-client.ts:260-265`） | 见 §0 修订 1 |
| F4 | 浏览器 WebRTC 的 SDP 走 `POST /api/calls`（`VoiceView.vue:258`）→ `routers/demo/calls.py:16-18` 转发到 pin 的地址 | `demo_config_service.py:38` 的 `rtc` |
| F5 | console 已有容量感知的本地分配器（过滤 → free/capacity 降序 → weight 加权随机 → reserve 乐观占位 → 一次换台重试） | `services/allocator.py:32-87`、`services/allocator_store.py:95-106` |
| F6 | 分配器**没有**接在数据面上，只在 demo 面签 grant | `routers/demo/session.py:65`（对比 `routers/realtime.py:56` 仍硬编码回环） |
| F7 | 实例注册表 + 巡检 + 容量模型 + 指标落库齐备 | `services/instance_registry.py:57-128`、`services/instance_monitor.py:66-119`、表 `param_instance` / `param_instance_metric` |
| F8 | ASR/TTS/声纹/情感端点**完全绕过 console**，由 pipeline `:8765` 直接提供 | `src/.../audio_services.py:53,78`、`voiceprint_routes.py:52,75`、`emotion_routes.py:60,80` |
| F9 | ASR/TTS **不占 pipeline unit 槽位**（直接复用 pool 里的 handler，不 claim unit） | `audio_services.py:31-41,61`（`find_handlers()` 不调 `_claim_unit`） |
| F10 | 声纹只在 `VOICEPRINT_ENABLED=true` 时注册路由，否则 404 | `voiceprint_routes.py:31-36` |
| F11 | 声纹鉴权三态：无 key → **503** `AUTH_NOT_CONFIGURED`（`voiceprint/service.py:186-187`）；无 Bearer → 401；错 token → 403 | `voiceprint/service.py:184-193` |
| F12 | 情感只在 `SER_ENABLED=true` 且 `SER_BASE_URL`+`SER_API_KEY` 齐备时注册，否则 404；**当前 `config/prod.env:55` 的 `SER_API_KEY=` 为空 → 情感路由根本没注册** | `emotion_routes.py:44-53` |
| F13 | 情感的 `/health` 会**同步转发 SER**，超时 = `SER_TIMEOUT_MS/1000`（5s，`config/prod.env:56`） | `emotion_routes.py:80-91` |
| F14 | pipeline 满员时在 **WS 已握手之后**回 `error` 事件（`session_limit_reached`）再 close 1008 | `src/.../websocket_router.py:603-623`、`service.py:1068-1078` |
| F15 | WebRTC 满员时回 **503 + `session_limit_reached` JSON**（HTTP 层，可识别）；无 webrtc extra 时回 **501** | `websocket_router.py:891-896,908-918` |
| F16 | WebRTC：offer → answer 在同一请求内完成，事件走 `oai-events` data channel，**没有第二条 WS 连接** | `websocket_router.py:882-1003` |
| F17 | 挂断 `DELETE /v1/realtime/calls/{call_id}` 是**实例本地**的，要求 Bearer `S2S_ADMIN_TOKEN`，找不到 → 404，缺 token → 503 | `websocket_router.py:1005-1033` |
| F18 | `/v1/pool`、`/v1/usage` **无应用层鉴权** | `websocket_router.py:665,689`（无 auth 分支） |
| F19 | console 强制单 worker（内存 `AllocatorStore` + 发布锁同前提） | `.env.example:96`、`supervisord.conf:14` |
| F20 | 仓库零个 nginx/traefik/envoy 配置 | 全仓 `nginx*` 搜索 0 命中 |
| F21 | pipeline 成功握手后第一帧固定是 `session.created`；WS 路由**先 accept 再 claim unit** | `websocket_router.py:608,640`、`handlers/session.py:86-90` |
| F22 | SPA catch-all 是 `GET /{full_path:path}`：未注册的 `/v1/audio/xxx`（GET 无后缀）→ **200 + index.html**；POST → **405** | `core/spa.py:64-77`、`docs/console-service.md:349` |
| F23 | 上传闸只有一个**共享桶**（`upload_body_bytes`，现值 = voice 10 MiB + 1 MiB = 11 MiB），`upload_paths` 默认只有 `/api/v1/voices`；闸**只看 `content-length`** | `middleware/security_headers.py:22-45`、`main.py:115` |
| F24 | httpx 默认解压响应体，但 `response.headers` 仍带 `content-encoding` 与旧 `content-length` | httpx 默认行为 |
| F25 | 前端**没有任何挂断调用**（`console/frontend/src` 全文无 `realtime/calls` 的 DELETE） | 全文检索 |
| F26 | 巡检只在 `mode != "off" or seed_path` 时启动，且 `run_forever` **先 sleep 再探** | `main.py:89`、`services/instance_monitor.py:160` |

**F9 是本设计最关键的一条**：只有 `/v1/realtime`（WS）与 `/v1/realtime/calls`（WebRTC）会 claim unit 槽位；ASR / TTS / 声纹 / 情感是**无状态请求**，不占槽位。因此**不能**用同一套"free/capacity"判据给所有端点选台（否则 ASR 会被"会话占满"的机器误杀）。

---

## 3. 两个候选方案的评估

### 3.1 方案 A：nginx / HAProxy 承担 S2S 数据面

形态：`浏览器 → nginx(:80/:443) → pipeline 盒 × N(:8765)`，console 退化为纯控制面。

可行配置要点：

```nginx
upstream s2s_pipes {
    least_conn;                       # 只有连接数，没有槽位概念
    server 10.0.0.11:8765 max_fails=2 fail_timeout=10s;
    server 10.0.0.12:8765 max_fails=2 fail_timeout=10s;
    keepalive 32;
}
location /v1/realtime {
    proxy_pass http://s2s_pipes;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
    proxy_buffering off;
}
```

优点：成熟、TLS/限流/访问日志现成、console 保持轻、故障域小。

致命短板（按严重度排序）：

1. **看不到槽位**。`least_conn` 看到 TCP 连接数，而 pipeline 的容量是 `num_pipelines` 个 unit。unit 满员不是 TCP 失败（F14：握手成功后回 error 事件），nginx 认为后端健康并继续打。要修正必须再写一个 agent 读 `/v1/pool` 的 `size/in_use/stuck` 喂给 nginx（nginx OSS 无 consul/etcd 动态解析，得上 openresty/lua）——**等于自己再实现一遍 registry + 探针 + 动态上游**，两套语义并存。
2. **不能在"握手成功后"换台**。nginx 必须先给客户端 101，之后上游才回 `session_limit_reached`；nginx 无法撤回已发出的 101，只能把错误事件透传给前端，前端自己重连（当前前端无此分支）。console 可以做到：不把 101 交给浏览器，先与上游完成握手 + 读到 `session.created` 再决定（§5.3）。
3. **健康检查无法表达"降级"**。console 的状态机有 `unknown/online/degraded/offline/draining` 五态（`instance_registry.py:14`），`degraded`（有 stuck unit）仍可分配。nginx 只有 up/down 两态。
4. **drain/排空无处安放**。`drain` 要"只停新分配、不动活跃会话"，nginx 的 `down` 会掐断在途连接。
5. **动态上游是运维负担**：静态 upstream 文件 + `nginx -s reload`，加机器要改文件重载；nginx OSS 无 DNS 动态解析。
6. **`/v1/audio/*` 的 multipart 边界**需要 `proxy_request_buffering off` 等一堆细节，且这些端点当前没有健康检查语义。

### 3.2 方案 B：console 内实现（选型）

形态：`浏览器 → console(:8000) → [选台] → pipeline 盒 × N(:8765)`，8765 收敛为容器内/内网。

做法：把已有的 `instance_registry` / `instance_monitor` / `allocator` 接进数据面——

- `routers/realtime.py` 的上游从"固定回环"改为"选台"；
- 新增 `/v1/audio/*` 反代路由；
- `routers/demo/calls.py` 的转发目标从"pin 的地址"改为"选台结果"。

优点：

1. **容量感知**：`free = size - in_use - stuck` 直接来自 `/v1/pool`（`instance_registry.py:36-40`），选台判据与 pipeline 的真实槽位一致。
2. **握手后换台**：console 是浏览器与上游之间的中间人，可以在把 101 交给浏览器之前先验证上游可用（§5.3）。这是 nginx 做不到的，也是"失败对浏览器不可见"的技术基础。
3. **能力感知**：声纹/情感是条件注册的（F10/F12），只有 console 的巡检能把"这台机器有没有这个能力"纳入选台。
4. **drain/排空语义现成**：`draining` 停新分配、不动活跃会话（F7）。
5. **指标闭环**：选台成败已有计数位（`alloc_ok` `allocator.py:78`、`alloc_fail_instance_503` `allocator.py:75`、`alloc_fail_no_instance` `allocator.py:86`）并落 `param_instance_metric`；代理层指标顺着同一条管道落库。

代价：

1. **console 从控制面变数据面**：多一份流量转发（音频上行、wav 下行）。
2. **单点**：console 挂了语音链路就断（今天也断，但那时它只是运维面）。→ 多副本时由 nginx/HAProxy 做 console 之间的 L4 轮询（**这是 nginx 在本架构中的正确位置**）。
3. **多副本各自算余量**：`InMemoryAllocatorStore` 是进程内的（F19），两副本各算各的 `pending_local`，可能同时把会话发给同一台 → 超发。兜底是既有的"一次 503 换台"（`allocator.py:60-77`）。彻底解决要 Phase 2 的共享 store。
4. **重启即断线**：console 重启会断掉所有在途 WS（现状同此）。

### 3.3 逐项对比

| 维度 | A：nginx 做数据面 | B：console 内实现 |
|---|---|---|
| 选台判据 | 连接数（`least_conn`） | 空闲槽位 + 能力 + 权重（F5） |
| 满员感知 | 做不到（F14：不是 TCP 失败） | `/v1/pool` 直读，天然可感 |
| 握手后换台 | 做不到（101 已发出） | 可以在交给浏览器前换台（§5.3） |
| 能力感知（声纹/情感） | 做不到（F10/F12 条件注册） | 巡检指纹，天然可感（§5.1） |
| drain/排空 | 只能掐连接 | 只停新分配，不动在途（F7） |
| 五态健康（degraded 等） | 两态 | 五态（F7） |
| 动态增删实例 | 改文件 + reload | seed/DB upsert + 巡检自愈 |
| 指标闭环 | 需自建 agent | 已有 `param_instance_metric` 管道 |
| 运维复杂度 | 多一套 nginx 配置与 reload 流程 | 复用已有 console 运维面 |
| 数据面故障域 | 小（nginx 与 pipeline 解耦） | 大（console 同源依赖） |
| 鉴权收口 | 8765 仍需网络 ACL | console 可统一收口（§8） |
| 现有代码复用 | 全部 registry/allocator 作废 | 直接接线 |
| 实施工作量 | 中（配置）但含动态上游 agent | 中（代码）但无新组件 |

### 3.4 结论

**选 B。** 决定性理由是三条能力只有 B 有：槽位感知、握手后换台、能力感知。这三条恰好是"语音会话负载均衡"与"HTTP 反向代理"的区别所在；A 能做的是后者。

**A 与 B 不互斥，是分层关系**：本设计落地后，若要 console 多副本 HA，仍需一个 L4 均衡器在 console 副本之间做轮询。那个 nginx **不需要**理解槽位、不需要处理 `session_limit_reached`、不需要 drain 语义——它只是把请求轮着丢给 console 副本：

```
浏览器 → nginx(L4 轮询, 零语义) → console × 2 (选台 + 状态机) → pipeline 盒 × N
```

这条分层是本设计对"要不要上第三方 LB"的正式回答：**要，但只放在它擅长的层**。

---

## 4. 目标架构

### 4.1 数据流

```
                    ┌──────────────────── console (:8000, 唯一对外) ────────────────────┐
                    │  routers/realtime.py (WS)        routers/audio_proxy.py (REST)     │
 浏览器 ──WS/─────►│  ├─ 选台 → 连上游 → 读首帧 ─┐   ├─ 选台 → 转发 body ─┐                │
                    │  │   session.created? accept │   │  multipart 原样     │                │
 浏览器 ──POST────►│  │   error? → 换台重试      │   │  Bearer 原样透传    │                │
   /api/calls      │  └──────────────────────────┘   └────────────────────┘                │
  (WebRTC SDP)     │  services/upstream_resolver.py（新）                                   │
                    │      ↓ 选台（策略 + 能力 + 容量）                                     │
                    │  services/allocator.py（扩展）  ← instance_monitor（巡检/探针/指标）   │
                    └──────────────────────┼───────────────────────────────────────────────┘
                                           │  ws:// / http://  10.0.0.1x:8765（内网，不再 publish）
                              ┌────────────┴────────────┐
                        pipeline 盒 P1            pipeline 盒 P2
```

### 4.2 模式与开关

新增 `CONSOLE_LB_MODE`（`config/_console.py`，默认 `off`）：

| `CONSOLE_LB_MODE` | `/v1/realtime` | `/v1/audio/*` | `/api/calls` | 说明 |
|---|---|---|---|---|
| `off`（默认） | 反代到回环 pipeline（现状） | **注册但回 501 `lb_disabled`** | 现状（转发到 pin，无 pin 则 404） | 与本期之前**行为等价** |
| `proxy` | 选台后反代到实例 | 注册并选台 | 选台后转发 | 需 `ALLOCATOR_MODE=local` 且注册表非空 |

**为什么 `off` 也要注册 `/v1/audio/*`**（F22）：不注册的话，`GET /v1/audio/embeddings/capability` 会命中 SPA catch-all 拿到 **200 + index.html**（探针解析 JSON 直接炸），POST 则拿到 **405**。显式注册并回 501 JSON，调用方至少拿到一个可解析的"未启用"。

**降级规则**（fail-safe，朝"能工作"的方向降级）：

- `proxy` 但 `ALLOCATOR_MODE != local` → 记 WARNING，**退回 `off`**（配置形态问题，退回能继续服务）。
- `proxy` 但注册表**内存快照**为空 → 退回 `off`（F26：巡检未跑或 `param_instance` 无行）。
- `proxy` 但选台失败（注册表非空却无健康/无余量实例）→ **不回退**：WS 走 §5.3 的"握手失败"，REST 走 503 `no_available_instance`。回退等于把流量打回本机已满的 pipeline，掩盖故障。

> **实现与本文的偏差（Task 4/5 落地后记录）**：前两条"退回 `off`"**没有实现**。
> 实际行为是：`proxy` 模式下只要注册表里没有健康且能力匹配的实例，一律回
> 503 `no_available_instance`（WS 走握手失败），**不会**静默退回 `off`。
> 理由：`ALLOCATOR_MODE != local` 时巡检根本不起任务（`main.py:89`），注册表会长期
> 为空，"静默退回 off"会让 `/v1/audio/*` 在无人察觉的情况下变成 501 `lb_disabled`，
> 而 503 能把"注册表是空的"这件事直接说清楚。配置形态错误应当显式暴露，而不是安静降级。
> 代价：交付形态（`config/prod.env`）必须同时配好 `ALLOCATOR_MODE=local` 与
> `INSTANCES_SEED_PATH`，否则数据面整体不可用——见 `docs/console-service.md` §11.1。

**启动瞬间的空窗**（F26）：巡检 `run_forever` 先 sleep 再探，首轮探测前注册表为空 → `effective_free=0` → 无候选。
对策：proxy 模式下在 `lifespan` 里**同步做一次** `instance_monitor.probe_all`（`asyncio.to_thread`），不等 5s。首轮探测仍需一次 RTT，因此**console 重启后的头 1~2 秒内可能仍无候选**（表现为浏览器握手失败，前端有重连）。

`ALLOCATOR_MODE` 语义不变（`off|local`），只新增"选台结果可被数据面使用"这一用途。

### 4.3 端点代理矩阵

| 端点 | 方法 | 本期是否进 console | 选台策略 | 能力要求 | 备注 |
|---|---|---|---|---|---|
| `/v1/realtime` | WS | 是（已存在，改造） | session | `realtime` | 静默换台（§5.3） |
| `/api/calls` | POST | 是（已存在，改造） | session | `realtime` | **浏览器 WebRTC 的实际入口**（F4），proxy 模式下目标由 console 选台决定 |
| `/v1/realtime/calls` | POST | 是（新增，同源/服务端用） | session | `realtime` | 与 `/api/calls` 共用转发实现 |
| `/v1/audio/transcriptions` | POST | **新增** | stateless | `asr` | multipart，≤11 MiB |
| `/v1/audio/speech` | POST | **新增** | stateless | `tts` | 返回 `audio/wav` 整段 |
| `/v1/audio/embeddings` | POST | **新增** | stateless | `voiceprint` | Bearer 透传 |
| `/v1/audio/embeddings/capability` | GET | **新增** | stateless | `voiceprint` | Bearer 透传，选一台原样返回 |
| `/v1/audio/emotion` | POST | **新增** | stateless | `emotion` | 裸 body / multipart |
| `/v1/audio/emotion/health` | GET | **新增** | stateless | `emotion` | 选一台原样返回 |
| `DELETE /v1/realtime/calls/{id}` | DELETE | **本期不做** | — | — | 无调用方（F25）；运维面 `POST /api/v1/instances/{id}/hangup` 已覆盖 |
| `/v1/pool`、`/v1/usage` | GET | **否** | — | — | 运维数据，console 服务端自己读（F18，不往公网放） |
| `/internal/sessions/update`、`/admin/sessions/update` | POST | **否** | — | — | 控制面，console 直发本机（`hot_update_service.py:149`），本期不改 |

### 4.4 路由注册顺序

`core/router_registry.py:58-59` 现在把 `realtime.router` 最后注册。新增 `audio_proxy.router` 时：

- `/v1/audio/*` 与 `/api/*`、`/api/v1/*` 前缀不冲突，放在 `realtime.router` 之后、SPA catch-all 之前。
- **单进程模式（`speech-to-speech serve --with-console`）下，pipeline 自己的 `/v1/audio/*` 先注册并先匹配**（`websocket_router.py:586` 先挂 pipeline 路由，`app.mount("/", console_attachment.app)` 注释明写"Must stay last"）→ console 的反代**永远不会被命中**。该形态下 console 不代理，语义与今天一致（`console/README.md:51-53` 已说明 `/v1/realtime` 在该形态下是死路由）。
  → **推论**：本设计的验证只能在 standalone 形态（console `:8000` + pipeline `:8765` 两个进程）做，单进程形态下新代码是死代码。这是既有架构决定的，不是本设计引入的。

---

## 5. 关键机制

### 5.1 能力指纹（capability fingerprint）

**问题**：同一批实例的端点集合可能不同——声纹只在 `VOICEPRINT_ENABLED=true` 的机器上（F10），情感只在 `SER_ENABLED=true` 且 SER 配置齐备的机器上（F12，当前 prod.env 因 `SER_API_KEY=` 为空而**未注册**）。若不做能力过滤，console 会把请求发给没有该路由的机器，拿到 404，表现为"偶发功能不可用"。

**探测方式**（关键：不持有凭据也能判断路由是否存在）：

| 能力 | 探测（不带 Authorization） | 判定 |
|---|---|---|
| `realtime` | `GET /v1/pool` | 200 → 有（F7 已有） |
| `asr` / `tts` | 不探测 | 路由恒注册（F8）；handler 缺失时上游 503 → 记一次 `proxy_fail:{svc}:upstream_unavailable`，下轮重试 |
| `voiceprint` | `GET /v1/audio/embeddings/capability` | **404 → 无能力**（未启用，F10）／**401/403 → 有能力**（F11 路由在且鉴权生效）／**503 → 路由在但未配 key → 不可用**（F11）／**超时 → 不可用** |
| `emotion` | `GET /v1/audio/emotion/health` | **404 → 无能力**（F12）／**其它 HTTP 状态 → 路由在**（含 5xx）／**超时 → 不可用**（F13：SER 慢或挂） |

> **为什么用 401 判"路由在"**：`VOICEPRINT_API_KEY` 由**调用方**（Java 网关）持有，console 不持有（F11）。但"路由存在"与"token 有效"是两件事——路由不存在时 FastAPI 直接 404，路由存在而 token 缺失时 401/403。所以 401 恰好是"路由在"的免费信号。
> **为什么情感的 503 与超时不同**：503 = SER 明确报错（路由在、后端拒了）；超时 = 可能是 SER 慢。两者都判"不可用"，但告警文案不同。

**探测轮与容量轮分离**（F26 + 串行探测的放大效应）：`instance_monitor.probe_all` 是**同步串行**（`instance_monitor.py:66-89`，for 循环逐台探），跑在 `asyncio.to_thread` 里。加 2 个能力探测会让一轮耗时变成 `N × (2s + 声纹 + 情感)`，一台慢就推迟其余（模块 docstring 声称"单台超时不阻塞其余"，实现其实只是"不崩"）。

对策：

- 能力探测**独立一轮**：`LB_CAPABILITY_INTERVAL_S`（默认 30s），用 `asyncio.gather` **并发**执行，每实例一个独立 task，**单实例超时独立**（`LB_CAPABILITY_PROBE_TIMEOUT_S`，默认 6s——必须 > `SER_TIMEOUT_MS/1000` = 5s，F13）。
- 能力结果写 `RuntimeState.capabilities`（**内存**），**不写 `param_instance_metric`**（那张表的列语义是槽位：`size/in_use/free/stuck`，塞入代理耗时会让两套口径混在一张表里，而 UI 已按列语义画图）。
- **不落库、不进 seed**：能力是镜像/env 的函数（`VOICEPRINT_ENABLED`/`SER_ENABLED`），会随实例重建变化；落库就产生陈旧真相源。**放弃"声明式能力上界"这个特性**（本期不做，§14）。跨实例能力全景由 `GET /api/v1/instances` 的每实例 `capabilities` 字段给出。

**字段形状**：`capabilities` 放在**每个 instance 对象内**（不放在顶层），空注册表时 `instances` 为**空数组**而非缺字段（避免 `instances_service._collect_legacy` 分支导致形状随注册表有无而变）。

### 5.2 两套选台策略

这是本设计最容易做错的地方（F9）。

**策略 A：`session`（占 unit 槽位的端点）** —— `/v1/realtime`、`/api/calls`、`/v1/realtime/calls`

沿用 `allocator._candidates` 的四步不变（F5）：

1. 过滤：`enabled and weight>0 and status in (online, degraded)` + 能力含 `realtime` + `effective_free - pending_count > 0`
2. 主排序：`free / capacity` 降序
3. 同分：`weight` 加权随机
4. `reserve()` 乐观占位（`allocator_store.py:95`）

**策略 B：`stateless`（不占槽位的端点）** —— ASR / TTS / 声纹 / 情感

**不看 `free/capacity`**（这些端点不 claim unit，F9；机器"会话满"不代表"ASR 不能服务"）。

判据：

1. 过滤：`enabled and weight>0 and status in (online, degraded)` + 能力匹配
2. 主排序：**console 侧在途计数（inflight）升序** —— console 自己知道每个实例上有多少个未完成的代理请求（WS 会话 + REST 请求）。这才是真正的 least-conn 近似。
   > **为什么不用 `probe_ms`**：它来自 `/v1/pool` 的探测耗时（F7），与负载无关；所有实例都是毫秒级、几乎相同 → 排序退化成任意顺序；而且它是 `int | None`（`instance_registry.py:29`），首次探测成功前为 `None` → 排序会 `TypeError`。
3. 同分：`weight` 加权随机
4. 上限：某实例 inflight 达到 `LB_STATELESS_MAX_INFLIGHT`（默认 0 = 不限）则跳过

**inflight 存哪**：`upstream_resolver` 的进程内字典（与 `AllocatorStore` 同生命周期，单 worker）。REST 请求进入 +1、结束 -1；WS 会话在 accept 成功后 +1、断开后 -1。

**实现落点**：新增 `services/upstream_resolver.py`：

```python
def select_session(capability: str) -> Allocation | None: ...   # 策略 A
def select_stateless(capability: str) -> Allocation | None: ... # 策略 B
```

`Allocation` 是一次性 dataclass：`instance_id, base_url, connect_url, release()`。

**`allocator.allocate()` 契约不变**（F5）：它返回 `dict | None`（`allocator.py:79-84`，**不含 `instance_id`**），既有测试 `tests/unit/test_allocator.py` 依赖这个形状。实现上让 `allocate()` 内部调用 `select_session()` 再映射回原有 dict（**不加字段**），demo 面与既有测试零影响。

### 5.3 WS 静默换台（核心机制）

**目标**：浏览器只应看到两种结果——连上了（收到 `session.created`）或明确的最终错误；中间的"这台满了，换一台"不该出现在浏览器事件流里。

**机制**：console 连上上游后**先读第一帧再决定要不要 accept 浏览器**。

```
browser ──WS upgrade──► console
                          │
                          ├─ 选台 P1（reserve）
                          ├─ websockets.connect(P1)          ← 失败 → 换台
                          ├─ first = await wait_for(P1.recv(), T_ready)
                          │     ├─ first.type == "session.created"  → accept(browser) → 转发 first → 双向转发
                          │     ├─ first.type == "error"
                          │     │   && first.error.type == "session_limit_reached"
                          │     │        → close(P1); release(); 换台重试
                          │     └─ 其它 error                        → accept(browser) → 转发（语义透传）
                          └─ 超时 T_ready → close(P1); release(); 换台重试
```

**为什么必须在 accept 之前**（F14）：pipeline 满员是"握手成功之后"才回 error。nginx 在 101 之后无法撤回；console 因为自己是 WebSocket 服务端，可以在 accept 之前自己先完成上游握手与首帧校验。

**三种终态（统一口径，F22 的教训：WS 握手阶段没有 HTTP 状态码）**：

| 终态 | 触发 | 浏览器看到 | 与今天是否一致 |
|---|---|---|---|
| **成功** | 首帧 `session.created` | 正常会话 | 一致 |
| **满员** | 上游明确回 `error/session_limit_reached`，且换台耗尽 | accept 后转发该 error 事件 + close **1008** | **一致**（今天直连 pipeline 也是这个事件与 close code）→ 前端零改动 |
| **不可达 / 无候选** | 上游连不上、首帧超时、或注册表里没有候选 | **不 accept，直接 close** → ASGI 回 **HTTP 403 握手失败** | **一致**（`routers/realtime.py:72-76` 今天就是这样，close code 送不到浏览器） |

> **删除**原设计里的"503 `no_available_instance`"（WS 阶段不存在）与"close 1013 送不到浏览器"的表述。`503 no_available_instance` **只用于 REST**（§5.4）。

**重试上限**：`LB_FAILOVER_ATTEMPTS`（默认 2，即最多尝试 3 台）。只对 `session_limit_reached` 与连接失败重试；其它 error 不重试（真实错误，重试无意义）。

**占位生命周期**：`reserve` 在选台时发生（`allocator_store.py:105` 写 `_pending`），但会话期间必须保持占位，否则选台会高估余量。当前 `_pending` 只靠 TTL 回收（`allocator_store.py:112-119`，`grant_ttl_s` 默认 60s）——**60s 远短于一次会话**，所以必须区分"已预留未连接"与"已建立会话"：

- 新增 `AllocatorStore.hold(session_id, instance_id)`：把 `_pending` 里的占位转成 `_held`（会话期间有效，随会话结束释放）。
- `release(session_id)` 扩展为同时清 `_pending` 与 `_held`（方法已存在，只是语义扩展）。
- `hold` 的 key 是 **console 自己生成的预留 key（uuid）**，不是上游 session_id —— 上游 session_id 只用于日志与指标。这样"预留 → 会话"是同一把 key，不会出现两个 id 空间对不上、占位泄漏到 TTL 才回收。
- 协议新增方法数：**2 个**（`hold`、`occupied_count`），另有 2 个既有方法语义扩展（`release`、`pending_count`）。`AllocatorStore` Protocol 的"签名冻结"（`allocator_store.py:1-6`）针对的是 Phase 2 的替换实现，本期无 Postgres 实现，但要在 §11 加一条测试守住"Protocol 方法集合 ⊆ InMemoryAllocatorStore 实现"。

### 5.4 REST 反代

**新增文件**：`console/backend/app/routers/audio_proxy.py`（6 条路由）+ `console/backend/app/services/audio_proxy_service.py`（转发实现）。

**body 处理**：

- **原样透传**：把 `Content-Type`（含 multipart boundary）连同原始 bytes 交给上游，**不重新编码 multipart**（重新拼 boundary 是这类代理最常见的 bug 源）。
- **整读而非流式**（我的取舍）：用 `await request.body()` 一次读完，**不**用 `request.stream()`。
  > **理由**：(a) `console/backend/requirements.txt:4` 只 pin `fastapi>=0.115.0`，starlette 随构建浮动，`request.stream()` 在 `BaseHTTPMiddleware`（`main.py:110-116`）下的行为依赖 starlette 版本，行为不确定；(b) body 上限 11 MiB（F23），内存估算 = 11 MiB × 并发请求数，ASR 并发通常个位数、几十并发也就几百 MB，可接受；(c) 整读后 `request._body` 有缓存，后续任何读取都安全。
  > **代价**：大并发下内存线性增长。`LB_AUDIO_MAX_BYTES` 可调；若将来并发上到百级，再改成纯 ASGI 中间件 + 流式。
- **上传闸由代理自己把关**：现有闸只有一个**共享桶**（F23），且 `upload_paths` 默认只有 `/api/v1/voices`；命中它的超限请求会拿到 console envelope 的 413（`{"code":"invalid_parameter",...}`），与本节错误表的 `{"error":{"code":"request_too_large"}}` 形状不一致。**决策：把 `/v1/audio/transcriptions`、`/v1/audio/embeddings`、`/v1/audio/emotion` 从中间件的体积闸里豁免**（中间件新增 `exempt_paths` 参数），413 只由代理产生，形状唯一。
  > **代价**：不带 `content-length` 的 chunked 请求会先进内存再判大小。代理的顺序是"先看 `content-length`（超限直接 413，不读 body）→ 再整读并复核"，部署文档要写明"上传请带 content-length"。
  > 上限值：`LB_AUDIO_MAX_BYTES` = 11 MiB（= 声纹 `VOICEPRINT_MAX_BYTES` 10 MiB + 1 MiB multipart 余量），与现有 voice 桶同量级。
- **chunked 请求（无 `content-length`）**：F23 的闸只看 `content-length` → chunked 完全不被拦。整读之后，console 侧在 `await request.body()` 之后按**实际字节数**再判一次 → 超限回 413（此时还没向上游发任何字节，不会出现"上游收到半个 multipart"）。
  > 若将来改回流式，超限只能断流 → 上游会看到不完整 multipart 回 400，而 console 已经是 413 语义，两者会打架。整读方案天然消除这个歧义。

**请求头透传规则**（明确白名单，避免踩坑）：

| 头 | 处置 |
|---|---|
| `content-type` | **透传**（含 multipart boundary——任何"重新构造 header"的写法都会丢 boundary） |
| `authorization` | **透传**（声纹 Bearer；console 不校验、不解析、**不写日志**，只记 present/absent） |
| `accept` | 透传 |
| `host` / `connection` / `content-length` / `transfer-encoding` | **不透传**（httpx 重算或用 chunked） |
| `accept-encoding` | 不透传（让 httpx 用默认，避免 F24 的解压/编码错配） |
| 其它自定义头 | 默认不透传（白名单之外一律丢弃） |

**响应透传规则**（F24）：httpx 默认解压响应体但保留 `content-encoding` 与旧 `content-length` → 照抄上游头会把 wav 弄坏。因此：

- **只回** `content-type` + **自算** `content-length`（用解压后的字节长度）+ `X-Request-Id`（沿用 `middleware/request_id.py`）。
- 其余上游响应头**一律丢弃**。
- `/v1/audio/speech` 返回 `audio/wav`（整段，非流式，`audio_services.py:147`）→ 原样回字节，不转码。

**超时**（分端点，不复用 `PIPELINE_TIMEOUT_S=180`，那是给 `/v1/pool` 的）：

| 端点 | 变量 | 默认 |
|---|---|---|
| ASR | `LB_ASR_TIMEOUT_S` | 120 |
| TTS | `LB_TTS_TIMEOUT_S` | 120 |
| 声纹 | `LB_VOICEPRINT_TIMEOUT_S` | 30 |
| 情感 | `LB_EMOTION_TIMEOUT_S` | 30 |

**错误映射**（`/v1/*` 是反代面，用 pipeline 的错误体风格 `{"error":{"code","message","retryable"}}`，**不用** console 的 `{code,message,detail,requestId}` 信封——保持 OpenAI 兼容面的调用方不改）：

| 情况 | 状态码 | body |
|---|---|---|
| 上游 2xx/4xx/5xx | 原样 | 原样 |
| 上游连不上 | 502 | `{"error":{"code":"upstream_unreachable","message":"...","retryable":true}}` |
| 上游超时 | 504 | `{"error":{"code":"upstream_timeout","message":"...","retryable":true}}` |
| 无可用实例（健康/能力都不匹配） | 503 | `{"error":{"code":"no_available_instance","message":"...","retryable":true}}` |
| 请求体超限 | 413 | `{"error":{"code":"request_too_large","message":"...","retryable":false}}` |
| LB 未启用（`CONSOLE_LB_MODE=off`） | 501 | `{"error":{"code":"lb_disabled","message":"...","retryable":false}}` |

上游原样透传：ASR 400/500、TTS 400/500、声纹 400/401/403/404/503（`voiceprint_service.error_body` 的 code 集）、情感 503/504。

`/v1/audio/embeddings/capability` 与 `/v1/audio/emotion/health` 的语义：**选一台健康且能力匹配的实例，原样返回**。不聚合（聚合会给调用方一个自造 schema，比透传更难解释）。多实例能力全景由 console 自己的 `GET /api/v1/instances` 提供。

### 5.5 WebRTC 入口与换台

F16：offer → answer 在一个请求内完成（媒体与事件走 data channel，**没有第二条 WS**），所以 WebRTC 不需要跨请求亲和——**除了挂断**，而挂断本期不做（F25）。

**浏览器入口是 `POST /api/calls`**（F4，`VoiceView.vue:258`），不是 `/v1/realtime/calls`。因此：

- `routers/demo/calls.py:16-18` 今天转发到 **pin** 的地址；**proxy 模式下改为转发到选台结果**（目标由服务端决定，不是开放代理——沿用该文件既有的安全约定"目标只来自 env/服务端"）。
- 前端**零改动**。
- 同时注册 `POST /v1/realtime/calls`（同源/服务端调用），与 `/api/calls` 共用同一转发实现。

**换台**（F15）：上游满员时回 **503 + `session_limit_reached` JSON**（HTTP 层，可识别）→ console 换台重试（≤`LB_FAILOVER_ATTEMPTS`）；**501**（无 webrtc extra）→ **不换台**，直接透传 501（配置问题，重试无意义）。

**Location 语义**：上游 201 的 `Location: /v1/realtime/calls/{session_id}`（`websocket_router.py:1002`）在 proxy 模式下**恰好正确**（console 自己也注册了这个路径）→ **原样回填**。`calls_service.forward(url, offer, keep_location=bool)` 的"原样回填"语义不变，但：
- `keep_location` 的含义改为"是否回填到 console 自身可解析的路径"：proxy 模式 true，pin 模式 false（pin 指向外部地址，浏览器拿不到，保持现状）。
- `calls_service._http()` 现在只设 `Content-Type`、不带其它头、超时固定 15s（`calls_service.py:39-42`）→ 统一改走 `audio_proxy_service` 的转发实现（含分端点超时与 header 白名单）。

**挂断**：本期不做数据面 DELETE（无调用方）。运维面 `POST /api/v1/instances/{id}/hangup`（`routers/instances.py:158`）保持不变——它需要 `S2S_ADMIN_TOKEN`（`routers/instances.py:170`），未配置时回 503 `admin_disabled`（既有语义）。

### 5.6 前端入口分流（澄清，不是新机制）

`/api/config` 的 `allowDirect = not demo.lb_url`（`demo_config_service.py:36`），`lb_url` 在 `pinned_url` 非空时被强制置空（`config/_demo.py:32-34`）。因此三种形态下前端的分流是：

| 部署 | `pinned_url` | `lb_url` | `allowDirect` | 浏览器 WS 走向 |
|---|---|---|---|---|
| 现状（prod.env 钉了 localhost） | 非空 | 空 | true | **直连 `ws://localhost:8765`**（F3，真实部署里是错的） |
| proxy 模式（清空 pin） | 空 | 空 | true | `directSocketUrl()` → pinned 为空 → 回落 `sameOriginRealtimeUrl()` → **同源 `/v1/realtime`** → console 反代 |
| 外部 LB 模式 | 空 | 非空 | false | 走 `/api/session` 拿 grant → 直连 LB/实例（demo 形态，逐字不变） |

**结论**：清空 `SPEECH_TO_SPEECH_URL` 之后，`allowDirect` 仍为 true，前端**自动**落到同源反代，**前端零改动**；demo 的 grant 路径只在外部 LB 形态下生效，与本设计无交集。

→ **原设计的 §5.6「grant 与 WS 的绑定（`?grant=`）」整节删除**：proxy 模式下前端不请求 `/api/session`，console 每次握手独立选台即可。也因此不需要 `CONSOLE_PUBLIC_URL`、不需要 grant→instance 索引、不需要改 `allocator.allocate()` 的返回形状。

### 5.7 控制面不动

- `hot_update_service._forward` 仍打回环（`hot_update_service.py:149`）：热更只对本机生效。
- `publish_flow_service` 不变：发布=本机重启，远程实例人工流程（`docs/console-service.md` §10.4）。
- `instance_probe.hangup_call` 不变（运维面）。
- **跨机参数 fanout 本期不做**（§14）。

---

## 6. 数据模型与配置

### 6.1 新增配置（`config/_console.py`，全部有默认值，默认组合 = 现状行为不变）

| 变量 | 默认 | 说明 |
|---|---|---|
| `CONSOLE_LB_MODE` | `off` | `off`/`proxy`（§4.2） |
| `LB_FAILOVER_ATTEMPTS` | `2` | 换台重试次数（不含首次） |
| `LB_UPSTREAM_READY_TIMEOUT_S` | `5.0` | 等上游首帧的上限 |
| `LB_ASR_TIMEOUT_S` | `120` | ASR 上游超时 |
| `LB_TTS_TIMEOUT_S` | `120` | TTS 上游超时 |
| `LB_VOICEPRINT_TIMEOUT_S` | `30` | 声纹上游超时 |
| `LB_EMOTION_TIMEOUT_S` | `30` | 情感上游超时 |
| `LB_AUDIO_MAX_BYTES` | `11534336`（11 MiB） | 音频上传闸（= 声纹 10 MiB + 1 MiB multipart 余量） |
| `LB_CAPABILITY_INTERVAL_S` | `30` | 能力探测轮间隔（与容量轮分离） |
| `LB_CAPABILITY_PROBE_TIMEOUT_S` | `6` | 能力探测单实例超时（必须 > `SER_TIMEOUT_MS/1000`=5s） |
| `LB_STATELESS_MAX_INFLIGHT` | `0`（不限） | 单实例无状态请求在途上限 |

**不新增** `CONSOLE_PUBLIC_URL`（§5.6 已消解该需求）。

`S2S_ADMIN_TOKEN` **不进 pydantic settings**：沿用 `routers/instances.py:170` 的 `os.environ.get` 读法（它是运维令牌，不属于 console 的常规配置面）。

### 6.2 数据模型

**`param_instance` 不动**（`instance_id/base_url/weight/enabled/drain_requested/cluster_id` 已够）。capabilities 不落库（§5.1）。

**`param_instance_metric` 不动**（槽位语义，不混装代理指标）。

**新增 `param_proxy_metric`**（alembic `0008_proxy_metrics`）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `instance_id` | str | 目标实例 |
| `service` | str | `asr/tts/voiceprint/emotion/realtime/webrtc` |
| `observed_at` | datetime | 采样时刻 |
| `observed_by` | str | 采样来源（`allocator.resolved_console_id`，与 `param_instance_metric.observed_by` 同义，`instance_monitor.py:52`）——多 console 必须能区分来源 |
| `ok` | int | 成功数（窗口增量，非累计） |
| `fail_count` | int | 失败数（窗口增量，非累计）。列名**不用** `fail`——那是 SQL 保留字，alembic 会生成 `"fail"`，破坏 schema 守护测试的列名正则 |
| `fail_reason` | str | 空 = 无失败；取值见附录 B |
| `duration_ms` | int | 窗口内平均耗时 |

索引：`(instance_id, observed_at)`、`(service, observed_at)`。

`alembic/sql/init-*.sql` 需用 `scripts/dump_schema_sql.py` 重新生成（`tests/unit/test_schema_sql.py` 守护）。

**`AllocatorStore` Protocol 变更**（Phase 2 替换点签名同步）：

```python
def hold(self, session_id: str, instance_id: str) -> None: ...      # 新增：pending → 会话期占位
def occupied_count(self) -> int: ...                                # 新增：pending + held 总数
def release(self, session_id: str) -> None: ...                     # 语义扩展：同时清 pending 与 held
def pending_count(self, instance_id: str) -> int: ...               # 语义扩展：pending + held（两者都占槽位）
```

> `_pending` 是"已预留未连接"（TTL 回收，`grant_ttl_s`），`_held` 是"会话已建立"（随会话结束释放，无 TTL）。**两者都必须从 free 里扣**。`allocator.pending_count()`（模块级函数，读 `_pending` 长度）语义不变，仍是"已签发未领取的 grant 数"。

### 6.3 seed 与注册表

`instances.yaml` 结构不变（`docs/console-service.md` §10.2），**不新增 `capabilities` 字段**（§5.1：能力纯探测派生，不落库不进 seed）。

---

## 7. 观测与指标

**结构化日志**（loguru，字段化）：

```
lb route path=/v1/audio/speech upstream=pipe-b status=200 ms=812 attempt=1
lb failover path=/v1/realtime upstream=pipe-a reason=session_limit_reached next=pipe-b
lb no_instance path=/v1/audio/embeddings capability=voiceprint tried=2
lb capability instance=pipe-a caps=realtime,asr,tts,voiceprint
```

**绝不记录**：声纹 Bearer 值、请求体内容、音频字节。只记 `service/instance/status/ms/attempt/reason/caps`。

**指标**：`param_proxy_metric`（§6.2）；分配侧沿用 `alloc_ok` / `alloc_fail_instance_503` / `alloc_fail_no_instance`。

**面板**：

- `GET /api/v1/instances` → 每个 instance 对象内加 `capabilities` 字段（数组）；空注册表时 `instances` 为空数组（形状恒定）。
- `GET /api/v1/instances/{id}/metrics` → 新增 `?kind=proxy` 维度（需新 repository 方法 + `schemas/instance.py` 的 `metric_point` 扩展，**T5 文件清单要列上 `schemas/instance.py`**）。
- `GET /api/v1/status` → 增加 `lbMode` / `lbUpstreams`（可用实例数）/ `lbCapabilities`（可用能力并集）。
- 前端"负载均衡"组新增一个轻量"代理健康"卡片（可选，T5）。

**没有 Prometheus/OTel**（全仓 0 命中），沿用自研 DB 时序，本次不引入新观测栈。

---

## 8. 安全收敛（取消 8765 publish）

**改动**：`docker-compose.yml:63` 删除 `"8765:8765/tcp"`，保留 `expose: 8765/tcp`（容器内可达）。

**收益**：`/v1/pool`、`/v1/usage`、`/v1/audio/*` 大多无应用层鉴权（F18、F8、F11 声纹除外），取消 publish 后这些端点不再对宿主机网段暴露。

**逐个 compose 的处置**（必须写死，否则"收敛"目标不成立）：

| compose | 现状 | 处置 | 理由 |
|---|---|---|---|
| `docker-compose.yml` | publish 8765 | **收敛**（删 publish） | 交付形态，唯一对外入口是 console `:8000` |
| `docker-compose.local.yml` | publish 8765 | 保留 | 本地开发需要直连 8765 调试 |
| `docker-compose.baked.yml` / `.baked.cu130.yml` | 视情况 | 保留 | 烘焙镜像的实验形态 |
| `docker-compose.cu130.yml` / `.gpustack.yml` / `.llm-bundled.yml` / `.vn.ms.llm-bundled.yml` | publish 8765 | 保留 | 服务器/GPUStack 部署形态，外部有直连调用方 |
| `docker-compose.thirdparty.yml` | publish 8765 | 保留 | 声纹/情感的外部调用方直连 8765 |
| `docker-compose.voiceprint.yml` | publish 8765 | 保留 | 同上 |

**影响清单**：

| 影响 | 处置 |
|---|---|
| **浏览器当前直连 8765**（F3） | **前置条件**：T6 必须清空 `config/prod.env` 的 `SPEECH_TO_SPEECH_URL`，让前端回落同源 `/v1/realtime`（§5.6，前端零改动）。否则删 publish = 直接打断语音链路 |
| 跨机部署时 console → 远程 `pipeline:8765` | 靠内网可达 + 网络 ACL，不是 publish |
| `instance_probe` / `pool.read_pool` 读回环 8765 | 不受影响（同容器 loopback） |
| `--with-console` 单进程模式 | pipeline 自己应答 `/v1/*`，console 的反代不被命中（§4.4） |
| demo 形态（独立 compose，直连实例） | 不在本期范围（不同部署形态、不同 compose） |

**灰度顺序**：先上线 `CONSOLE_LB_MODE=proxy`（8765 仍 publish，验证代理链路）→ 再删 publish 条目（安全收敛）。两步分开，避免"代理还没好就把直连关了"。

---

## 9. 失败模式与降级

| 故障 | 表现 | 降级 |
|---|---|---|
| 某实例进程挂 | 巡检 3 次失败 → `offline` | 不再选中；已在其上的会话继续到结束（drain 语义） |
| 某实例有 stuck unit | `degraded` | 仍可分配（`effective_free` 已扣 stuck，F7） |
| 某实例没开声纹 | 能力指纹不含 `voiceprint` | 声纹请求不选它 |
| 某实例声纹没配 key | 能力探测得 503 | 视为不可用，不选它，记 `capability_misconfigured` |
| 上游满员（WS） | 首帧 `error/session_limit_reached` | 静默换台（§5.3） |
| 上游满员（WebRTC） | 503 + `session_limit_reached` | 换台 |
| 上游拒连 | connect 异常 | 换台 |
| 全部实例满 | 换台耗尽 | WS：accept 后转发 error + close 1008；REST：503 `no_available_instance` |
| console 重启 | 全部在途 WS 断；重启后 1~2 秒内无候选 | 既有行为；`CONSOLE_LB_MODE=off` 回退不需要重启 pipeline |
| 多 console 副本 | 各自算余量 → 可能超发 | 上游 503 → 一次换台（`allocator.py:60-77`）；彻底解决需 Phase 2 共享 store |
| 代理内存压力 | 进程 RSS 随并发线性上升 | body 整读 + 11 MiB 闸；并发上到百级时改纯 ASGI 中间件 + 流式 |

---

## 10. 交付拆分

| 任务 | 内容 | 触及文件（新增/改造） | 依赖 |
|---|---|---|---|
| **T1** | 能力指纹（独立并发轮）+ 两套选台策略 + `upstream_resolver` | 新 `services/upstream_resolver.py`；改 `services/instance_registry.py`（`capabilities`）、`services/instance_monitor.py`（能力轮）、`services/allocator.py`（复用 `select_session`，**`allocate()` 契约不变**）、`services/allocator_store.py`（`hold`/`release`/`_held`） | — |
| **T2** | WS 静默换台 + 三种终态 + 占位 hold/release | 改 `routers/realtime.py`（首帧判定、accept 时机、换台循环） | T1 |
| **T3** | REST 反代 6 条路由 + 501 兜底 + 上传闸 per-path | 新 `routers/audio_proxy.py`、`services/audio_proxy_service.py`；改 `core/router_registry.py`、`middleware/security_headers.py`（per-path 闸）、`main.py`（闸配置）、`config/_console.py` | T1 |
| **T4** | WebRTC：`/api/calls` 选台转发 + 换台 + `Location` 回填 | 改 `routers/demo/calls.py`、`services/calls_service.py`；新增 `POST /v1/realtime/calls` | T1、T2 |
| **T5** | 指标/日志/状态/前端 | 迁移 `alembic/versions/0008_proxy_metrics.py`；新 `repositories/proxy_metric_repository.py`；改 `routers/instances.py`、`routers/status.py`、`services/status_service.py`、`services/instances_service.py`、`schemas/instance.py`；前端实例表能力列 + 代理健康卡片 | T1-T4 |
| **T6** | 入口切换 + compose 收敛 + 文档 | 改 `config/prod.env`（**清空 `SPEECH_TO_SPEECH_URL`**）、`docker-compose.yml`（删 publish）；改 `docs/console-service.md`、`console/README.md`、`docs/service-enablement-CN.md` | T5 |

**建议顺序**：T1 → T2 → T3 → T4 → T5 → T6。T6 的两处改动（prod.env / compose）**分开提交**，便于紧急回滚。

---

## 11. 测试矩阵

**单元（`tests/unit/`）**

| 用例 | 断言 |
|---|---|
| 能力探测判定 | 401/403 → 含 `voiceprint`；404 → 不含；503 → 不可用；超时 → 不可用 |
| 情感能力判定 | 404 → 不含；500 → 路由在；超时 → 不可用 |
| 能力轮不影响容量轮 | 能力探测慢/挂 → 容量探测仍按原节奏完成 |
| session 策略排序 | free/capacity 降序；同分按 weight 加权 |
| stateless 策略 | 不看 `free`；满员实例仍可选；按 inflight 升序；`probe_ms=None` 不炸 |
| 能力过滤 | 缺能力的实例被排除；全缺 → `None` |
| drain 排除 | `draining` 实例不被选 |
| 首帧判定 | `session.created` → 放行；`error/session_limit_reached` → 换台；其它 error → 不换台直接透传 |
| 换台上限 | 尝试次数 = `1 + LB_FAILOVER_ATTEMPTS` |
| 占位生命周期 | accept 后 `hold`；断开后 `release` 清 `_held`；`_pending` TTL 回收不受影响 |
| Protocol 一致性 | `AllocatorStore` 的 Protocol 方法集合 ⊆ `InMemoryAllocatorStore` 的实现 |
| `allocate()` 契约 | 返回 dict 的键集合与改前一致（既有测试 + 新增一条快照断言） |

**集成（`tests/integration/`）**：用本地假上游（`httpx.MockTransport` 或一个真实桩）覆盖：

- WS：假上游先回 `error/session_limit_reached` 再回 `session.created` → 断言浏览器只收到 `session.created`。
- WS：假上游全失败 → 断言浏览器握手失败（不是 101，也不是 error 事件）。
- WS：假上游首帧回别的 error → 断言直接透传、不换台。
- ASR：multipart body → 断言上游收到的 boundary 与内容原样一致（**最容易被 proxy 搞坏的一条**）。
- ASR：超限 body → 断言 413，且**上游没有收到任何字节**。
- 声纹：Bearer 原样透传（断言上游收到的 header）+ 上游 401 原样透传为 401。
- TTS：`audio/wav` 原样回传（字节级相等），且响应头**不含** `content-encoding`。
- 情感：裸 body 与 multipart 两种都通。
- `CONSOLE_LB_MODE=off`：`GET /v1/audio/embeddings/capability` → 501 JSON（**不是** SPA HTML、不是 405）。

**回归**：`tests/unit` + `tests/integration` 全绿；`tests/unit/test_legacy_paths.py`（`/v1` 未命中路径落到 index.html 的语义，`:57-61`）必须继续通过——**新增路由不得把 `/v1/*` 变成通配**；`/v1/unknown` 仍应落到 SPA。

**脚本**：`scripts/dump_schema_sql.py` 重新生成 `alembic/sql/init-*.sql`。

---

## 12. 灰度与回滚

**灰度步骤**：

1. 部署新镜像，`CONSOLE_LB_MODE=off`（默认）→ 行为与今天完全一致（零风险）。
2. 配 `instances.yaml`（seed）+ `ALLOCATOR_MODE=local`，观察实例页：状态灯、能力列、探测 p95 是否正常。**此时数据面还没切**。
3. `CONSOLE_LB_MODE=proxy` → 数据面切换。观察：`lb route` 日志、`param_proxy_metric` 成功率、WS 换台计数、前端语音页是否正常。
4. **清空 `config/prod.env` 的 `SPEECH_TO_SPEECH_URL`** → 前端从"直连 8765"切到"同源 `/v1/realtime`"（这一步之前直连仍然可用，是安全网）。
5. 稳定观察 ≥1 个业务周期后，删除 compose 的 8765 publish（§8 两步走）。

**回滚**：

| 级别 | 动作 | 影响 |
|---|---|---|
| L1 | `CONSOLE_LB_MODE=off` + 重启 console | 数据面回到回环直连；**在途 WS 断**（console 重启的既有代价）；pipeline 不受影响 |
| L1' | 恢复 `SPEECH_TO_SPEECH_URL` + 重启 console | 前端回到直连 8765（需 8765 仍 publish，故必须在步骤 5 之前） |
| L2 | 回退镜像（上一版） | 同上 + 新表留在库里（向前兼容，旧代码不读它） |
| L3 | 恢复 compose 的 8765 publish | 直连通道恢复 |

**开关生效方式**：pydantic-settings **只在启动时读**（`docs/console-service.md:346`），改 `CONSOLE_LB_MODE` 需要重启 console 进程。必须写进运维手册。

---

## 13. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| console 成为数据面单点 | console 挂 → 语音全断 | 多副本 + L4 均衡（§3.4）；本期先单机 |
| **清空 pin 切前端入口** | 前端从直连 8765 变成同源反代，若 console 代理有 bug → 语音不可用 | 灰度步骤 3 先验证代理链路，步骤 4 才切；`SPEECH_TO_SPEECH_URL` 是 L1' 回滚开关 |
| console 转发带宽/内存 | 大音频流经 console | body 整读 + 11 MiB 闸；并发上到百级改流式 |
| 多副本各自算余量 | 超发 → 一次 503 换台 | Phase 2 共享 store |
| 能力指纹误判 | 声纹被路由到不支持的机器 | 判定表覆盖 404/401/403/503/超时（F11/F13）；独立轮次 + 30s 刷新 |
| 换台引入首帧延迟 | TTFA 变差 | T6 实测对比；`LB_UPSTREAM_READY_TIMEOUT_S` 可调 |
| 8765 收敛后直连客户端断 | 既有集成方受影响 | 收敛清单逐个 compose 写死（§8）；两步灰度 |
| `AllocatorStore` Protocol 变动 | Phase 2 的 Postgres 实现要补 `hold` | 本期无 Postgres 实现；新增"Protocol 一致性"测试守住 |
| 单进程形态下新代码是死代码 | `--with-console` 模式验证不到 | 既有架构决定（§4.4）；验证只在 standalone 形态做，文档写明 |

---

## 14. 本期不做

- 多 console 副本的共享分配状态（Phase 2 `PostgresAllocatorStore`）。
- 数据面 `DELETE /v1/realtime/calls/{id}`（无浏览器调用方，F25）；若将来要做，需先决定鉴权方式（建议：console 签发 call 票据，浏览器凭票据挂断，console 注入 `S2S_ADMIN_TOKEN`）。
- 会话级粘性（同一用户回到同一实例）、金丝雀比例、路由规则（`routers/traffic.py:40` 已把这三项列为 `unimplemented`，本期维持）。
- **声明式能力上界**（seed 里的 `capabilities` 字段）——能力纯探测派生，不落库（§5.1）。
- 跨机参数发布 fanout（需先定义"配置是集群级还是单机级"）。
- nginx / HAProxy 配置文件本身（等 console 多副本 HA 时再引入，且只做 L4）。
- 把 console 拆成独立的"网关进程"（本期 console 仍是单进程双角色）。
- console 持有声纹密钥做"提前拒绝"（调用方持钥，console 只透传）。

---

## 15. 已拍板的两点（2026-11-16）

1. **数据面 `DELETE /v1/realtime/calls/{id}` 本期不做** —— 已确认。前端全文没有任何挂断调用（`console/frontend/src` 无该 DELETE），运维面 `POST /api/v1/instances/{id}/hangup` 已覆盖。将来要做时用 console 签发 call 票据（避免匿名面能挂断他人通话）。
2. **compose 收敛清单** —— 已确认：**只收敛交付形态 `docker-compose.yml`**；`local/baked/cu130/gpustack/llm-bundled/thirdparty/voiceprint` **保留 8765 publish**（声纹/情感的外部调用方直连 8765）。

---

## 附录 A：端点清点（pipeline 侧，来源 `src/speech_to_speech/api/openai_realtime/`）

| 路径 | 注册位置 | 鉴权 | 占 unit | 备注 |
|---|---|---|---|---|
| `WS /v1/realtime` | `websocket_router.py:603` | 无 | 是 | 首帧 `session.created`；满员 → error + 1008 |
| `GET /v1/usage` | `websocket_router.py:665` | 无 | — | 运维数据，不代理 |
| `GET /v1/pool` | `websocket_router.py:689` | 无 | — | 探针数据，不代理 |
| `POST /internal/sessions/update` | `websocket_router.py:738` | `S2S_INTERNAL_TOKEN` | — | 控制面，不代理 |
| `POST /admin/sessions/update` | `websocket_router.py:805` | `S2S_ADMIN_TOKEN` | — | 控制面，不代理 |
| `POST /v1/realtime/calls` | `websocket_router.py:882` | 无 | 是 | 201 + `Location`；满员 → 503 JSON；无 webrtc → 501 |
| `DELETE /v1/realtime/calls/{id}` | `websocket_router.py:1005` | `S2S_ADMIN_TOKEN` | — | 实例本地；**本期不代理** |
| `POST /v1/audio/transcriptions` | `audio_services.py:53` | 无 | **否** | multipart |
| `POST /v1/audio/speech` | `audio_services.py:78` | 无 | **否** | `audio/wav` |
| `POST /v1/audio/embeddings` | `voiceprint_routes.py:52` | Bearer | **否** | 条件注册 |
| `GET /v1/audio/embeddings/capability` | `voiceprint_routes.py:75` | Bearer | **否** | 条件注册；无 key → 503 |
| `POST /v1/audio/emotion` | `emotion_routes.py:60` | 无（服务端注入 `X-API-Key`） | **否** | 条件注册 |
| `GET /v1/audio/emotion/health` | `emotion_routes.py:80` | 无 | **否** | 同步打 SER，5s 超时 |

## 附录 B：错误码

**console 数据面（`/v1/*` 反代，pipeline 风格 `{"error":{"code","message","retryable"}}`）**

| code | 状态码 | 含义 |
|---|---|---|
| `upstream_unreachable` | 502 | 选中的实例连不上 |
| `upstream_timeout` | 504 | 上游超时 |
| `no_available_instance` | 503 | 无健康且能力匹配的实例（**仅 REST**；WS 走 §5.3 的握手失败） |
| `request_too_large` | 413 | 超过 `LB_AUDIO_MAX_BYTES` |
| `lb_disabled` | 501 | `CONSOLE_LB_MODE=off` |
| `upstream_error` | 502 | 上游 5xx（非 OpenAI 兼容体） |
| `session_limit_reached` | WS 事件 + close 1008 / REST 503 | 全部实例满员（透传 pipeline 语义） |

**上游原样透传**：ASR 400/500、TTS 400/500、声纹 400/401/403/404/503（`voiceprint_service.error_body` 的 code 集）、情感 503/504。

**内部计数**（落 `param_proxy_metric.fail_reason`）：`upstream_unreachable`、`upstream_timeout`、`no_available_instance`、`upstream_5xx`、`capability_mismatch`、`capability_misconfigured`、`body_too_large`。

## 16. 修订记录

- **2026-11-17（原型对齐批次落地）**：本设计的 §7.4（规则/粘性/金丝雀）、§8（发布流水线）等在 `docs/superpowers/plans/2026-11-17-console-prototype-alignment.md` 中以 31 任务实施完毕（Task 17 数据面接线除外，见 SDD 台账）。关键落地差异：ack 成功标记复用 `param_agent_config_version.yaml_hash` 前缀（不新增列）；阶段历史存 `param_release.changes`（JSON），未新建 stage 表；规则评估的 header 匹配为占位（Task 18 域）。
