# 多盒 + 内网 LLM 端点部署清单

## 架构
把 LLM 推理与语音管线**物理分离到不同盒子**，通过内网 OpenAI 兼容端点（`chat-completions`）连接：

```
┌─────────────┐         ┌──────────────┐   ┌──────────────┐
│ LLM 盒       │         │ 管线盒 P1     │   │ 管线盒 P2     │   ...  N× 管线盒
│ llama.cpp    │◄────────│ VAD+STT+TTS  │   │ VAD+STT+TTS  │
│ Qwen3-xB     │ 内网HTTP │ :8765/ws     │   │ :8765/ws     │
│ :8080/v1     │         └──────────────┘   └──────────────┘
└─────────────┘
   1 张 LLM 卡服务 N 张管线卡（线性扩展）
```

- **LLM 盒**：只跑 `llama.cpp`（`docker-compose.llm-box.yml`），对外暴露 `:8080/v1`。
- **管线盒**：只跑 `speech-to-speech` pipeline（VAD/STT/TTS），LLM 后端指向 `http://<LLM盒IP>:8080/v1`（`docker-compose.pipeline-box.yml`）。
- 每类盒子可独立增减；**并发上限由 LLM 盒吞吐决定**，管线盒可横向堆到 LLM 卡饱和。

## 为什么多盒比单盒更省
- LLM 是显存与算力大头，管线（STT/TTS）显存小、算力轻。
- 单盒同卡时 LLM 与 TTS 抢显存/显存带宽；分离后各用各的卡，互不影响，且小卡（4060 Ti 16G ~¥8k）即可胜任管线。
- 例：1× 4090(LLM,¥25k) + 4× 4060Ti(管线,¥8k×4=32k) ≈ ¥57k 支持 ~50 路；同等并发单盒需多张 4090/5090，成本更高。

## 盒子角色与显存分配
### LLM 盒（以 Qwen3-8B 为例）
| 项 | 值 |
|---|---|
| 显卡 | 4090 24G / 5070 Ti 16G（4B）/ 5090 32G（9B） |
| LLM 权重 | 4B≈2.6GB / 8B≈5GB(Q4) / 8B≈8.5GB(Q8) / 9B≈5.7GB(Q4) |
| KV 缓存 | 8k≈0.6GB，32k≈2.4GB（按 `-c` 与 `-np` 放大） |
| 并发上限参考 | 4B ~30+ 路 / 8B ~15–20 路 / 9B ~12–18 路（单卡） |

### 管线盒（每台）
| 项 | 值 |
|---|---|
| 显卡 | 4060 Ti 16G / 5070 12G / 5060 Ti 16G |
| STT (Qwen3-ASR FP16) | ~1.8GB |
| TTS (Qwen3-TTS FP16) | ~3.4GB |
| VAD (Silero, CPU) | ~0.03GB |
| **单台管线显存** | **~5.2GB** |
| 单台并发 | 20–40 路（受 STT/TTS 吞吐） |

## 网络要求
- LLM 盒 ↔ 管线盒：建议 **同二层交换机 / 10GbE**；至少 1GbE。
- 单轮 LLM 请求体（prompt+stream）通常 <100KB，1GbE 可支撑数百路；瓶颈在 LLM 卡算力而非带宽。
- 管线盒对外暴露 `:8765`（WebSocket Realtime），前端/网关连管线盒，不直接连 LLM 盒。

## 部署步骤
1. **LLM 盒**：把 `docker-compose.llm-box.yml` 与 `./cache`（含 LLM GGUF）放到 LLM 盒，按目标模型改 `-hf`：
   ```bash
   # Qwen3-8B（默认）、Qwen3.5-4B、Qwen3.5-9B 改对应 -hf
   docker compose -f docker-compose.llm-box.yml up -d
   curl http://localhost:8080/v1/models   # 验证 LLM 就绪
   ```
2. **管线盒**：把 `docker-compose.pipeline-box.yml`、`./cache`（含 qwen3-asr / qwen3-tts / silero）、以及 `../.silero-dl2/silero-vad-master` 挂载放到每台管线盒，启动前设置环境变量：
   ```bash
   export LLM_BASE_URL=http://<LLM盒IP>:8080/v1
   export LLM_MODEL=Qwen/Qwen3-8B-Instruct-GGUF   # 须与 LLM 盒一致
   export PIPELINE_PORT=8765
   docker compose -f docker-compose.pipeline-box.yml up -d
   curl http://localhost:8765/v1/models             # 验证 pipeline 就绪
   ```
3. **扩容**：复制步骤 2 到更多管线盒（不同 IP，端口可保持 8765），LLM 盒不变。
4. **网关**：前端/负载均衡连各管线盒 `:8765/ws`，按会话数轮询分发。

## 并发压测（latency_test.py 参数）
`latency_test.py` 通过 WebSocket Realtime 连 `:8765/v1`，发送一段音频并测首响延迟（TTFA）。

### 单会话参数
| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| 音频文件 | 命令行第 1 个参数 | `ref_audio.wav` | 16kHz 单声道 wav；脚本会自动重采样 |
| 短语数 | `PHRASES` | `1` | 一次连接内连续说几段（模拟多轮） |
| 间隔 | `GAP` | `2.0` | 每段之间的静音秒数 |

```bash
PHRASES=3 GAP=2.0 python latency_test.py /path/to/ref_audio.wav
```
输出 `TTFA`、`Latency after speech end`、时间线，用以评估单路延迟。

### 多会话并发压测
脚本端点在源码中硬编码为 `127.0.0.1:8765`。对分布式管线盒压测时，二选一：
- **(推荐) 把压测跑在管线盒本机**，直接 `127.0.0.1` 即可；或
- 修改 `latency_test.py` 第 51–54 行的 `base_url` / `websocket_base_url` 为 `http://<管线盒IP>:8765/v1`。

并发启动 N 路（后台并行）：
```bash
# 在管线盒本机，或改脚本指向管线盒 IP 后，启动 20 路并发
for i in $(seq 1 20); do
  PHRASES=2 GAP=3 python latency_test.py ref_audio.wav > /tmp/load_$i.log 2>&1 &
done
wait
# 汇总每路的 TTFA
grep "TTFA" /tmp/load_*.log
```
- 逐步加大并发数（10→20→50→…），直到 TTFA 明显上升或报错，即为该 LLM 盒+管线盒组合的饱和点。
- 关注指标：P50/P95 TTFA、是否出现 `SERVER ERROR`、GPU 显存占用（`nvidia-smi`）、LLM 盒 CPU/GPU 利用率。

## 调优要点
- LLM 盒 `-np`（并行数）按并发目标设（4B 可设 8–16，8B/9B 设 4–8），`-c` 控上下文，KV 量化 `-ctk/-ctv q8_0` 省显存。
- 关闭思考链：`--reasoning-budget 0` + pipeline 侧 `enable_thinking=false`，降低语音延迟。
- 管线盒 STT/TTS 若显存紧张，将 Qwen3-ASR 量化到 INT8 / Qwen3-TTS 量化到 INT8。
- 同机多管线容器时，用 `--num_pipelines` 或每盒独立容器，避免互相抢占 GPU。
