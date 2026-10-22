# 多盒 + 内网 LLM 端点部署清单

> 本文所有路数/延迟估算统一引用 [performance-assumptions.md](./performance-assumptions.md)；
> 本文 §并发压测 的命令被 [acceptance-test-plan.md](./acceptance-test-plan.md) 的 T5 直接沿用。
> 商品编号（`D-xx`）与价格见 [procurement-list.md](./procurement-list.md)。

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
- 单盒同卡时 LLM 与 TTS 抢显存/显存带宽；分离后各用各的卡，互不影响，且小卡（`D-G02` 16G 级）即可胜任管线。
- 例：1× `D-G06`（24G，LLM 盒）+ 4× `D-G02`（16G，管线盒）= **8 路**
  （4 台 × 2 路/台，见假设表 §4）。此时 8B Q4 的 LLM 侧远未饱和，可继续加管线盒直到 LLM 吞吐打满。
- 反例：同样 8 路塞进一台单盒，需要 `8 × 4.6 = 36.8 GB` 管线显存 + 8B 权重 + KV，
  单卡无解——即便 `D-S01` 48G 同机 8B 也只能 7 路（假设表 §4）。
- 具体金额见 [procurement-list.md](./procurement-list.md) §5 的四档套餐。

## 盒子角色与显存分配
### LLM 盒（5 个本地档通用）
| 项 | 值 |
|---|---|
| 显卡 | `D-G05` 16G（4B/2B/0.8B）/ `D-G06` 24G（8B/4B）/ `D-G07` 32G（9B）/ `D-S01` 48G（9B 高密度） |
| LLM 权重（Q4 / Q8） | **0.8B** 0.6 / 0.9 ｜ **2B** 1.3 / 2.2 ｜ **4B** 2.6 / 4.5 ｜ **8B** 5.0 / 8.5 ｜ **9B** 5.7 / 9.8（GB） |
| KV 缓存（8K / q8） | 0.8B≈0.2 ｜ 2B≈0.3 ｜ 4B≈0.4 ｜ 8B≈0.6 ｜ 9B≈0.7（GB）；32K 约 4×（见假设表 §3.2） |
| 并发上限参考（**LLM 侧**） | 4B ~30+ / 8B ~15–20 / 9B ~12–18（旧口径区间，**均需 T6 实测替换**）；0.8B / 2B 显存完全不是约束，上限由解码吞吐决定，同样待 T6 回填 |

> 权重与 KV 数值来源：[performance-assumptions.md](./performance-assumptions.md) §3.2（Q4_K_M ≈0.55 GB/B、
> Q8_0 ≈1.1 GB/B、KV 按 `2 × 层数 × KV头 × head_dim × token × 1 byte` 推导）。
> **“LLM 侧并发”与“单盒同机路数”是两回事**：LLM 盒不跑 STT/TTS，所以不受 4.6GB/路 的槽位约束；
> 而管线盒的 4.6GB/路 才是 `num_pipelines` 的真正成本。

### 管线盒（每台）
| 项 | 值 |
|---|---|
| 显卡 | `D-G02` 16G / `D-G04` 12G / `D-G05` 16G |
| STT (Qwen3-ASR FP16) | ~1.8GB |
| TTS (Qwen3-TTS FP16) | ~3.4GB |
| VAD (Silero, CPU) | ~0.03GB |
| **单台管线显存** | 理论合计 **~5.2GB** / 实测整套 handler **4.6GB（4633 MiB）** |
| 单台并发（`num_pipelines` 槽位） | 12G→**2 路** / 16G→**2 路** / 24G→**4 路**（`floor(显存×0.85÷4.6)`，见假设表 §4） |

> 旧版写“单台 20–40 路”是 **STT/TTS 计算吞吐上限**，不是显存能支撑的路数：
> 每路 `num_pipelines` 独占一套 VAD/STT/LM/TTS handler（实测 4.6GB），12G 卡实际只有 2 路。
> 达到 20–40 路需要 10–20 台管线盒堆叠。

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
- 逐步加大并发数（按假设表 §5 的档位 **1→3→5→10→20**），直到 TTFA 明显上升或报错，即为该组合的饱和点。
- **饱和点定义**（与 `acceptance-test-plan.md` §7 T5 一致）：P95 TTFA 超目标档、出现任意 `SERVER ERROR`、
  或 GPU 温度触顶降频——三者任一出现即为饱和点，减一档就是“可交付路数”。
- 关注指标：P50/P95 TTFA（**须加 `min_silence_ms/1000` 才是真实 TTFA**，见验收方案 §1.3）、
  是否出现 `SERVER ERROR`、GPU 显存占用（`nvidia-smi`）、LLM 盒 CPU/GPU 利用率。

## 调优要点
- LLM 盒 `-np`（并行数）按并发目标设（4B 可设 8–16，8B/9B 设 4–8；0.8B/2B 权重小，
  可先按 16 起测，上限由 `acceptance-test-plan.md` T6 的 `-np` 吞吐实测决定）；
  `-c` 控上下文，KV 量化 `-ctk/-ctv q8_0` 省显存。
- 关闭思考链：`--reasoning-budget 0` + pipeline 侧 `enable_thinking=false`，降低语音延迟。
- 管线盒 STT/TTS 若显存紧张，将 Qwen3-ASR 量化到 INT8 / Qwen3-TTS 量化到 INT8。
- 同机多管线容器时，用 `--num_pipelines` 或每盒独立容器，避免互相抢占 GPU。
