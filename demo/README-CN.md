---
title: HF Realtime Voice
emoji: 🎙️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: 通过 WebSocket 或 WebRTC 对接 HF speech-to-speech 的语音聊天
hf_oauth: true
hf_oauth_expiration_minutes: 10080
---

> 🌐 Language / 语言：**中文版** · [English](./README.md)

# Realtime 语音 Demo

面向 [huggingface/speech-to-speech](https://github.com/huggingface/speech-to-speech) 后端的浏览器语音聊天 UI，通过 **WebSocket**（默认）或 **WebRTC**（Settings → Transport，仅环境变量固定的部署——见 [WebRTC 传输](#webrtc-传输)）讲 OpenAI Realtime **GA** 协议。

两种选择都在固定的官方 `@openai/agents` 包的现成（stock）传输类之上运行一个 `RealtimeSession` 适配器。适配器把 demo 专属的队列、音频、可视化、设备、摄像头和计量行为排除在协议实现之外。

## 快速开始（本地）

1. **启动 speech-to-speech 后端**（从仓库根目录；更多模型组合见[后端 README](https://github.com/huggingface/speech-to-speech/blob/main/src/speech_to_speech/api/openai_realtime/README-CN.md)）：

   ```bash
   uv run speech-to-speech serve \
     --stt parakeet-tdt \
     --llm_backend transformers \
     --tts kokoro \
     --model_name "Qwen/Qwen3-4B-Instruct-2507" \
     --llm_device mps \
     --llm_torch_dtype float16 \
     --enable_live_transcription
   ```

   实时服务器默认监听 `ws://localhost:8765/v1/realtime`（用 `--host` / `--port` 修改）。

2. **安装固定的浏览器 SDK 并启动本应用**，用 `SPEECH_TO_SPEECH_URL` 把它指向后端：

   ```bash
   npm ci --prefix demo
   uv pip install -r demo/requirements.txt
   export SPEECH_TO_SPEECH_URL=ws://localhost:8765/v1/realtime
   export SERPER_API_KEY=...   # 可选；没有它则网络搜索被禁用
   export STARTUP_GREETING=... # 可选；为空则禁用自动问候
   uv run uvicorn --app-dir demo server:app --reload --port 7860
   ```

   或用 Docker：

   ```bash
   docker build -t s2s-demo demo/
   docker run -p 7860:7860 -e SPEECH_TO_SPEECH_URL=ws://host.docker.internal:8765/v1/realtime s2s-demo
   ```

   > **Docker + 宿主机后端：WebSocket 和 WebRTC 需要不同的主机名。**
   > 两种传输从不同网络命名空间拨号后端：
   >
   > - **WebRTC** 是**服务端**拨号的——浏览器把它的 SDP offer POST 到 demo 的 `/api/calls` 代理，该代理从*容器内部*转发它。在那里 `host.docker.internal` 解析到你的宿主机，因此上面的命令有效。
   > - **WebSocket** 是**客户端**拨号的——demo 把 URL 直接交给浏览器，由浏览器自己打开 socket。浏览器运行在你的*宿主机*上，在那里 `host.docker.internal` 不是真正的 DNS 名称，因此连接永远到不了后端，服务器也不记录任何内容。
   >
   > 因此单个 Docker 的 `SPEECH_TO_SPEECH_URL` 一次只能让一种传输工作（`localhost:8765` 对应 WebSocket，`host.docker.internal:8765` 对应 WebRTC）。要在不交换环境变量的情况下同时尝试**两种**，请在**没有 Docker** 的情况下运行 demo（上面的 `uvicorn` 命令），这样宿主机和容器命名空间会合并——然后 `ws://localhost:8765/v1/realtime` 对两者都有效。

3. 打开 <http://localhost:7860/>，点击球体，允许麦克风，开始说话。

   > 浏览器要求 **HTTPS 或 `localhost`** 才能使用 `getUserMedia()`（麦克风 + 摄像头）。
   > `127.0.0.1` 和 `localhost` 都有效；普通的 `http://192.168.x.y` 不行。

从 shell 冒烟测试后端：

```bash
websocat ws://localhost:8765/v1/realtime
# -> 你应当立刻得到一个 session.created 事件
```

## 工作原理

1. 适配器用配置的 `/v1/realtime` URL，通过官方的 Agents SDK `RealtimeSession` 与现成的 WebSocket 传输创建会话。
2. SDK 使用 OpenAI Realtime **GA** 模式执行 `session.update`。
3. SDK 以 PCM16 24 kHz 单声道 base64 块的形式流式传输麦克风音频（`input_audio_buffer.append`，约每 40 ms 一帧）。
4. 浏览器保留这些已发送帧的一个有界内存副本，并使用服务器 VAD 边界将可回放的用户录音添加到对话历史。不会上传或单独持久化任何录音。
5. 服务器推送 `response.output_audio.delta`（PCM16 24 kHz 单声道 base64）和转写增量。

后端为每个流水线单元提供一并发会话（`--num_pipelines` 用于服务更多）。

## WebRTC 传输

在设置了 `SPEECH_TO_SPEECH_URL` 的情况下，**Settings → Transport** 提供 WebRTC 作为 WebSocket 的替代。相同的对话，不同的管道：

1. SDK 现成的 WebRTC 传输把浏览器的麦克风轨道及其数据通道添加到一个 `RTCPeerConnection`，并把 SDP offer POST 到同源的 `/api/calls` 代理，后者把它转发到后端的 `POST /v1/realtime/calls`（OpenAI GA 握手）。代理之所以存在，是因为 s2s 服务器没有 CORS 中间件——而且它只转发到环境变量固定的 URL，绝不会转发到客户端提供的 URL，因此它不能被用作开放代理。这就是为什么当 URL 未被固定时（用户键入的 URL、LB 模式），该开关被锁定为 WebSocket。
2. 只有握手经过代理：协商后的音频（双向 Opus RTP）和数据通道直接在浏览器 ↔ 后端之间流动。
3. 数据通道上的 JSON 事件与 WebSocket 相同的 GA 协议，只是去掉了音频：麦克风音频走媒体轨道（绝不是 `input_audio_buffer.append`，后端在 WebRTC 上会拒绝它），而助手的语音作为远程音频轨道到达（绝不是 `response.output_audio.delta`）。打断刷新是服务端进行的。

后端要求：需要 `webrtc` 扩展（`pip install "speech-to-speech[webrtc]"`），否则 `/v1/realtime/calls` 返回 501，握手以清晰消息失败。

与 WebSocket 相比的注意事项：

- **用户录音回放**：对话历史录音当前使用经过 `input_audio_buffer.append` 发送的精确 PCM 帧，因此只在 WebSocket 传输上可用。
- **NAT**：默认只提供 host ICE 候选——浏览器和后端在同一台机器 / 局域网时没问题。跨互联网时，在本应用上设置 `RTC_ICE_SERVERS`（一个 `RTCIceServer` 字典的 JSON 列表，或逗号分隔的 STUN / TURN URL；通过 `/api/config` 提供给浏览器），并在后端设置 `SPEECH_TO_SPEECH_ICE_SERVERS`。没有 TURN 中继回退，因此对称 NAT 的设置可能仍然无法连接。
- **噪声门**：实现在 WebSocket 捕获 worklet 中，因此在 WebRTC 上是隐藏的——改为发送原始的麦克风轨道（带有浏览器自身的 `noiseSuppression`）。
- **摄像头快照**被重新编码以适配一个数据通道消息（约 60 KB），因此模型可能看到比 WebSocket 上更小的帧。
- **负载均衡器模式目前仅支持 WebSocket**。

## 连接到后端

三种模式，由环境变量选择（`/api/config` 告诉客户端哪个处于活动状态）：

- **`SPEECH_TO_SPEECH_URL` 环境变量**——本地使用的模式，也是最高优先级。浏览器**直接**连接到这个实时 WebSocket URL；它在 Settings 中只读显示。设置它会完全禁用负载均衡器逻辑（没有 `/api/session` 代理、没有队列、没有计量、没有登录）。与 LB 地址不同，它不是机密。接受完整的 `ws(s)://host/v1/realtime` URL 或裸主机名如 `localhost:8765`（应用会补上 `/v1/realtime`）。
- **未设置任何环境变量**——**Settings → Speech-to-speech server URL**：粘贴一个完整的连接 URL 或裸主机名，浏览器直接连接到它。
- **`LOAD_BALANCER_URL` 环境变量**——仅用于多计算部署：浏览器 POST 到同源的 `/api/session` 代理，服务器转发到 LB，浏览器拨号 LB 交回的每会话计算 URL。LB 地址永远不会到达浏览器；Settings 中的 URL 字段被隐藏。在启用 OAuth 的 Spaces 上，代理通过 `X-Reachy-Mini-Authorization` 把登录用户的 HF 访问令牌转发给 LB，以便后端归属用量。令牌保持在服务端；匿名请求不含任何凭据。

| `SPEECH_TO_SPEECH_URL` | `LOAD_BALANCER_URL` | `SPACE_ID` | 连接 | URL 字段 | 传输 | 计量 |
|:---:|:---:|:---:|---|---|---|---|
| ✅ | 任意 | 任意 | 直接 → 固定 URL | 可见，锁定 | WS 或 WebRTC | 关 |
| – | – | 任意 | 直接 → 用户 URL | 可编辑 | 仅 WS | 关 |
| – | ✅ | ✅ | LB 代理 | 隐藏 | 仅 WS | **开** |
| – | ✅ | – | LB 代理 | 隐藏 | 仅 WS | 关 |

**Settings → Restart** 用当前的 voice、指令和 URL 重新连接。

## 启动问候

默认情况下，每个新连接会创建一个隐藏的用户项，向模型请求一个简短的问候，然后请求一个响应。除了自然地开启对话之外，这也预热了首个口语轮次所使用的相同提示前缀。

设置 `STARTUP_GREETING` 以自定义隐藏提示，或将其设为空值以禁用自动生成。适配器在连接后通过新的 `RealtimeSession` 发送一次。

## 工具

助手可以在对话中途调用两个工具（从右上角的 **Tools** 按钮切换）：

- **网络搜索**——通过 Serper.dev 的 Google 结果，服务端代理，因此密钥永远不会到达浏览器。将 `SERPER_API_KEY` 设为环境变量 / Space 密钥。没有它，该工具被禁用，除非用户在 Tools 面板中粘贴自己的密钥。
- **摄像头**——启用时，左下角显示实时自视图；当模型调用该工具时，当前帧被发送给视觉—语言模型，以便它能看到你展示给它的东西。

## 用量上限（仅部署的 Space）

对话时间按登录层级每个 UTC 天计量（见 `limiter.py` / `auth.py`），但**仅在部署的 Space 上**——计量只在 `LOAD_BALANCER_URL` 和 `SPACE_ID`（由 HF Space 运行时自动注入）都存在时开启。本地运行——即使导出了 `LOAD_BALANCER_URL`——也使应用不受计量。可通过环境变量调优：

| 环境变量 | 默认 | 说明 |
|-----|---------|------|
| `LIMIT_ANON_SEC` | `300` | 匿名访客每日秒数（5 分钟） |
| `LIMIT_FREE_SEC` | `600` | 登录的非 PRO 用户每日秒数（10 分钟） |
| `UNLIMITED_ORGS` | _(加到默认值)_ | 额外获得**无限**用量的 HF 组织名，如同 PRO |
| `USAGE_HASH_SECRET` | _(随机)_ | 用于哈希身份密钥 + 签署匿名 cookie 的 HMAC 密钥 |

PRO 成员始终无限。开箱即用的 `cerebras`、`HuggingFaceM4`、`smolagents` 和 `pollen-robotics` 的成员无限（显示为 "Team"，而非 "PRO"）；设置 `UNLIMITED_ORGS=my-team` 以添加更多。与用户来自 HF OAuth 的组织进行大小写不敏感匹配。

## 设置（存储在 `localStorage` 中）

| 键 | 说明 |
|-----|------|
| Speech-to-speech server URL | 直接的实时 WebSocket URL（被环境变量固定时隐藏 / 锁定） |
| Transport | WebSocket（默认）或 WebRTC；仅在环境变量固定的 URL 下可选 |
| Microphone | 用于捕获的输入设备。在下次对话 / Restart 时生效。 |
| Speakers | 助手音频的输出设备。Chrome / Edge 可通过 `AudioContext.setSinkId` 实时切换；其他浏览器保持系统默认。 |
| Voice | Qwen3-TTS 说话人名称（Aiden、Ryan、Dylan、Eric、Ono_Anna、Serena、Sohee、Uncle_Fu、Vivian） |
| Instructions | 连接打开后一次性发送在 `session.update` 中的系统提示 |

localStorage 键以 `s2s.ws.*` 为命名空间（外加用于传输选择的 `s2s.transport`，以及用于设备的 `s2s.audio.inputId` / `s2s.audio.outputId`）。

## 文件

| 文件 | 角色 |
|------|------|
| `index.html` | 单页，球体 + 设置模态（与 WebRTC 应用相同的 UI） |
| `main.js` | 状态机、设置、工具、摄像头、噪声门 UI 接线 |
| `ui/chat.js` | `ChatView`：历史面板、短暂气泡、转写 / 工具流式、用户录音回放 |
| `ui/account.js` | `Account`：HF 登录 chip + 弹窗、每日上限模态 |
| `ui/dom.js` | 共享辅助：`$`、`escHtml`、`truncateError`、`DEBUG` |
| `auth.py` | HF OAuth + 每请求身份（层级、哈希密钥） |
| `limiter.py` | SQLite 每日本地对话时长预算（分块的服务器时钟预留） |
| `s2s-realtime-client.js` | 围绕一个 Agents SDK `RealtimeSession` 及其现成 WebSocket / WebRTC 传输的窄 demo 适配器 |
| `package.json` / `package-lock.json` | 精确的官方 Agents SDK 和浏览器测试依赖固定版本 |
| `ws/codec.js` | base64 <-> PCM 辅助 + 转写提取（纯函数） |
| `ws/user-audio-recorder.js` | 有界的已发送 PCM 缓冲区 + VAD 切片 + 浏览器可播放的 WAV 封装 |
| `ws/orb-visualizer.js` | `OrbVisualiser`：FFT 频段 -> 球体 CSS 自定义属性 |
| `worklets/mic-capture.js` | AudioWorklet：48 kHz Float32 -> 24 kHz Int16 PCM，约每 40 ms 发送一块 |
| `worklets/audio-playback.js` | AudioWorklet：24 kHz Float32 环形缓冲 -> 48 kHz，线性插值，淡入 / 淡出 |
| `style.css` | 球体动画、布局、深色主题（逐字来自 WebRTC 应用） |

## 音频流水线说明

- **输入**：`getUserMedia({ echoCancellation, noiseSuppression, autoGainControl })` 以 `AudioContext` 的采样率馈送 `mic-capture` worklet。worklet 重采样到 24 kHz（在 48 -> 24 快速路径上用盒式低通 + 抽取，奇数速率回退到线性插值）并打包为 Int16 LE。
- **用户回放**：WebSocket 客户端只保留它实际发送的 PCM 的有界副本。`speech_started` / `speech_stopped` 时间戳挑选每一句话，将其封装为内存中的 WAV 并附加到用户行。开始播放会临时静音外发麦克风音频以防止反馈。
- **输出**：`response.output_audio.delta` 解码为 Int16 -> Float32，并发布到 `audio-playback` worklet。worklet 维护一个每上下文环形缓冲，线性插值 24 -> 48，并在进出时施加短的 32 帧淡变以抑制咔哒声。
- **打断（Barge-in）**：当服务器 VAD 在响应中途检测到用户语音（`input_audio_buffer.speech_started` 同时 `ai-speaking`），客户端向播放 worklet 发布 `{ kind: "clear" }` 以立即清空队列。服务器自身取消在途响应。

## 署名

- 后端：[huggingface/speech-to-speech](https://github.com/huggingface/speech-to-speech)
- UI 逐字来自 `amir-tfrere/minimal-conversation-app-s2s-backend`（Pollen Robotics × Hugging Face）
