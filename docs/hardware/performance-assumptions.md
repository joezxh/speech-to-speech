# 语音链路性能假设条件表（performance-assumptions）

> **本文档是 `docs/hardware/` 下所有显存/并发/延迟数字的唯一推导来源。**
> `plan-N.md`、`procurement-list.md`、`acceptance-test-plan.md` 只允许引用本文结论，
> 禁止复制数值自行改写（防双源漂移）。
>
> 基线事实采集日期：**2026-10-22**（来源：`docker-compose.local.yml`、
> `docs/hardware/docker-compose.pipeline-box.yml`、`src/speech_to_speech/arguments_classes/*.py`、
> `docs/hardware/README.md` §本机实测）。
>
> 文档状态：**假设表 v1.1**（v1.1 变更：回填 HT3 边缘盒结论，依据 `edge-box-feasibility.md`）。
> 所有"推导值"必须由到货实测（`acceptance-test-plan.md` T1~T9）替换，
> 替换时同步修改本文档与本表版本号。

---

## 检查条件：本文档必须回答的 9 个问题

在给出任何路数/延迟结论前，必须先明确以下 9 项。§1~§5 逐一对应：

1. 单轮用户语音时长是多少（典型值与 P95）？
2. VAD / STT / TTS 各自是否流式？
3. 是否要求打断（barge-in）/ 双工？
4. 输入采样率、声道、编码是什么？
5. LLM 输入 / 输出 token 规模是多少？
6. 远程 LLM 的网络延迟区间是多少？
7. 本地 LLM 采用什么量化精度？
8. 目标端到端延迟（TTFA）是多少？
9. 需要支撑哪些并发档位？

---

## §1 音频与交互假设

| 假设项 | 取值 | 依据 |
|---|---|---|
| 输入采样率 / 编码 / 声道 | 16 kHz / PCM16 / 单声道 | `vad_arguments.py` `sample_rate=16000` |
| 输出音频 | 24 kHz PCM（Qwen3-TTS 原生输出） | `Qwen3-TTS-12Hz-1.7B-CustomVoice` 模型规格 |
| 单轮用户语音时长 | 典型 3 s，P95 ≤ 10 s | **假设 HA1**，语音助手短对话场景；验收 T2 实测校准 |
| 判停方式（目标盒子） | 句末静音 700 ms，Smart Turn 关闭 | `docker-compose.pipeline-box.yml` + 137 部署记录 |
| 判停方式（本机调优） | 句末静音 64 ms，Smart Turn 关闭 | `docker-compose.local.yml`（延迟优先实验配置） |
| 判停延迟对 TTFA 的影响 | 700 ms 档直接计入 TTFA 基线；64 ms 档仅作下限参考 | 静音判停 = 用户停止说话后的固定等待 |
| 交互模式 | 半双工 + VAD 打断（barge-in），非全双工 | 现网链路：`--no_smart_turn` + VAD 触发新轮 |
| VAD 流式 | 是（逐帧，CPU/ONNX 推理） | Silero VAD 运行时特征 |
| STT 流式 | **否**——VAD 判定终段后整段转写 | `qwen3-asr` handler：整段音频一次送入 transformers |
| TTS 流式 | 是，句内流式（`streaming_chunk_size=4`，`non_streaming_mode=False`） | `docker-compose.local.yml` |
| LLM 下发粒度 | 流式 + 逐句（`stream_batch_sentences=1`） | `docker-compose.local.yml`（库默认 3） |
| 实时字幕 | 开启，0.5 s 刷新（不改变显存口径） | `--enable_live_transcription` |

> 关键含义：**STT 非流式**意味着"用户说完 → 等 700 ms 静音 → 整段转写 → 才轮到 LLM"，
> 这 700 ms 与整段转写时间是 TTFA 中无法用流式优化掉的两段固定成本。

---

## §2 LLM token 与网络假设

| 假设项 | 取值 | 依据 |
|---|---|---|
| 上下文轮数 | 现网 20 轮 / 库默认 30 轮 | `chat_size=20`（local compose）/ 默认 30 |
| LLM 输入 token | 300–800（系统提示 + 历史 + 本轮转写） | 20~30 轮中文短句 + `init_chat_prompt` 估算；验收 T7 实测 |
| LLM 输出 token | 20–80（一到两句口语） | `init_chat_prompt` 要求 "one or two spoken sentences" |
| 思考链 | **关闭** | `--responses_api_reasoning_effort ""`；本地 GGUF 加 `--reasoning-budget 0` |
| 远程 LLM 网络 RTT | 内网同网段 10–80 ms | **假设 HA2**；现网 GPUStack 192.168.40.30 同网段；验收 T7 实测 |
| 远程排队附加延迟 | 0–300 ms | GPUStack 多租户负载不可控；验收 T7 记录 P95 |
| 远程 LLM 首 token（TTFT） | 100–400 ms（8B，Q4/Q8，8K 上下文） | 经验区间；验收 T7 实测替换 |
| 本地 LLM 首 token（TTFT） | 30–150 ms（4B Q4，单流，桌面卡） | 经验区间；验收 T6 用 `llama-bench` 实测替换 |

---

## §3 显存与量化基线

### 3.1 管线常驻（与 `README.md` 实测一致）

| 组件 | 精度 | 显存 | 备注 |
|---|---|---|---|
| VAD（Silero v5） | ONNX | ≈0.03 GB | CPU 推理，GPU 侧可忽略 |
| STT（Qwen3-ASR-1.7B） | FP16 | ≈1.8 GB | 磁盘文件 4.08 GB（含 tokenizer/多分片），运行期显存按 FP16 权重估算 |
| STT（Qwen3-ASR-1.7B） | INT8 | 0.6–1.0 GB | 需自行量化，非现网默认 |
| TTS（Qwen3-TTS-1.7B） | FP16 | ≈3.4 GB | torch backend + speech_tokenizer |
| TTS（Qwen3-TTS-1.7B） | INT8 | ≈2.0 GB | 需自行量化，非现网默认 |
| **单路管线合计** | **FP16** | **≈4.6 GB（实测 4633 MiB）** | `num_pipelines=1` 时整套 handler 独占 |

> `num_pipelines=N` 表示 N 套**完全隔离**的 VAD/STT/LM/TTS handler 与对话状态，
> 因此每增加一路，显存近似线性增加 ≈4.6 GB。这是"路数 = 显存 / 4.6"的直接依据。

### 3.2 LLM 权重与 KV 推导表

权重换算规则（沿用 `README.md` 口径）：
`Q4_K_M ≈ 0.55 GB/B`、`Q8_0 ≈ 1.1 GB/B`、`FP16 ≈ 2.0 GB/B`（含少量 embedding/输出层开销）。

KV cache 规则（q8_0 KV，1 byte/元素）：
`KV ≈ 2 × 层数 × KV头数 × head_dim × token数 × 1 byte`
以 Qwen3-8B（36 层 × 8 KV 头 × 128）为例：72 KB/token → 8K ≈ 0.59 GB、32K ≈ 2.4 GB。

| 模型 | Q4_K_M | Q8_0 | FP16 | KV 8K（q8） | KV 32K（q8） |
|---|---|---|---|---|---|
| Qwen3-8B | ~5.0 GB | ~8.5 GB | ~16 GB | ~0.6 GB | ~2.4 GB |
| Qwen3.5-9B | ~5.7 GB | ~9.8 GB | ~18 GB | ~0.7 GB | ~2.8 GB |
| Qwen3.5-4B | ~2.6 GB | ~4.5 GB | ~8 GB | ~0.4 GB | ~1.6 GB |
| Qwen3.5-2B | ~1.3 GB | ~2.2 GB | ~4.0 GB | ~0.3 GB | ~1.2 GB |
| Qwen3.5-0.8B | ~0.6 GB | ~0.9 GB | ~1.6 GB | ~0.2 GB | ~0.8 GB |

> 表内为**推导值**，验收 T4（显存）/ T6（本地 LLM）实测后替换。
> 2B/0.8B 档已证实存在（Qwen3.5 Small 系列，2026-03-02 开源），GGUF 见
> `unsloth/Qwen3.5-2B-GGUF` / `unsloth/Qwen3.5-0.8B-GGUF`（检索日期 2026-10-22）；
> 模型上限 256K 上下文，表中 32K 为**部署配置**而非模型能力。

---

## §4 并发推导规则（本文档最关键口径）

**单盒最大路数 = min(槽位约束, 吞吐约束)**

```
槽位约束 = floor( 可用显存GB × 0.85 ÷ 4.6 )
            # 4.6 = 单路管线实测占用；0.85 = 留 15% 余量防降频/碎片
            # 同机含 LLM 时：可用显存 = 标称显存 − LLM权重 − KV − 0.5~1.0GB 上下文余量
吞吐约束 = STT/TTS 计算吞吐上限
            # 12GB 桌面卡（5070 级）≈ 20–40 路（README 口径，CUDA 全 GPU 管线）
            # 该上限只在"纯管线盒"（不放 LLM）时才可能成为约束
```

**Worked example（写死口径，供其他文档引用）：**

```
RTX 5070 12GB + Qwen3.5-4B Q4 + KV 8K
可用 = 12 − 2.6 − 0.4 − 0.8 = 8.2 GB
槽位 = floor(8.2 × 0.85 ÷ 4.6) = floor(1.51) = 1 路
吞吐 = 20–40 路（不构成约束）
→ 同卡结论：1 路

同一张卡改作纯管线盒（LLM 走远程）：
槽位 = floor(12 × 0.85 ÷ 4.6) = floor(2.22) = 2 路
```

**结论（必须显式传播）：**

1. **同机跑 LLM 时，12GB 卡无法做多路**——即便 0.8B Q4 也只到 2 路（`floor((12−0.6−0.2−0.8)×0.85/4.6)=1.9→1` 附近，见 `plan-6` 逐档算式）。
2. 多路只有两条路：**纯管线盒堆叠**（LLM 集中到单独盒子）或 **≥24GB 卡**。
3. 任何"12GB 卡 20–40 路"的说法只在"纯管线 + 不含 LLM"时成立，报价/方案文档必须标明属于哪种模式。

---

## §5 延迟目标与档位

- 并发档位：**1 / 3 / 5 / 10 / 20** 路（单盒或多盒合计）。
- 延迟目标两档：
  - **舒适：TTFA P95 ≤ 1.0 s**
  - **可用：TTFA P95 ≤ 2.0 s**
  - 超过 2.0 s 视为不通过（判定见 `acceptance-test-plan.md`）。
- **TTFA 定义**：用户说完最后一个字 → 客户端收到首个音频帧。
- 四个归因时间戳（T3/T5 必须逐项记录）：
  1. `t_vad_end`：VAD 判定说话结束（含 700 ms 静音等待）
  2. `t_stt_first`：STT 吐出首个（或整段）转写结果
  3. `t_llm_first`：LLM 首个 token 到达
  4. `t_tts_first`：TTS 首个音频帧发出

参考预算（700 ms 判停档，用于方案对比，实测替换）：

| 环节 | 舒适档预算 | 可用档预算 |
|---|---|---|
| VAD 判停 | 700 ms | 700 ms |
| STT 整段转写（3 s 语音） | 150–300 ms | 300–600 ms |
| LLM TTFT（远程/本地） | 150–300 ms | 300–600 ms |
| TTS 首帧 | 100–200 ms | 200–400 ms |
| 网络/序列化等杂项 | 50–100 ms | 100–200 ms |
| **合计（TTFA）** | **≤1.0 s** | **≤2.0 s** |

> 若延续本机 64 ms 判停，可把 VAD 项替换为 64 ms，其余不变——这是"延迟优先"实验配置，
> 代价是误切句概率上升，不作为采购验收基线。

---

## §6 质量与能力提示（2B / 0.8B 附录）

- Qwen3.5-2B / 0.8B 在**工具调用、多轮指代、中文长句理解**上明显弱于 8B/9B；
  0.8B 更适合导览、单轮问答、边缘兜底，不适合需要可靠工具调度的正式业务场景。
- 若必须用 2B/0.8B：`init_chat_prompt` 限长（一两句）、关闭思考链、必要时加 few-shot 兜底；
  验收阶段需增加"中文长句 / 指代 / 拒答"抽检（见 `plan-6` §质量下限警告）。
- 5 个本地档的质量排序：9B > 8B > 4B > 2B > 0.8B；成本与显存排序相反。

---

## §7 假设项登记表

| 编号 | 假设 | 状态 | 解除方式 |
|---|---|---|---|
| HT1 | Qwen3.5-2B / 0.8B 存在可用 GGUF（Q4_K_M / Q8_0） | **已证实**：Qwen3.5 Small 系列 2026-03-02 开源；GGUF 见 unsloth/Qwen3.5-{2B,0.8B}-GGUF（2026-10-22） | 已解除；部署时核对文件体积与 SHA256 |
| HT2 | llama.cpp 支持 Qwen3.5 架构 | **已证实**：qwen35 于 2026-05 合入（需 b8001+ 构建，旧版报 unknown architecture）（2026-10-22） | 已解除；镜像/二进制须 ≥2026-05 |
| HT3 | ARM 盒可跑一致的 Qwen3-ASR / Qwen3-TTS（torch / transformers） | **待验证（未解除）**：10 款盒子无一具备「1.7B + FP16 + transformers」的实测；Orin NX 16G 仅有 0.6B int4 方案级证据（Seeed，2026-09-07）；x86 的 Ultra 9 285H / Ryzen AI Max+ 395 与 DGX Spark 同为待验证（`edge-box-feasibility.md` §2/§3） | 按 `edge-box-feasibility.md` §5.2 买 1 台跑 T1/T2/T3；RTF>1 则整体否决 |
| HT4 | 电商价格为 2026-10-22 快照 | 持续有效 | 下单前复核（`procurement-list.md` 每条带日期） |
| HA1 | 单轮语音典型 3 s / P95 10 s | 假设 | 验收 T2 实测 |
| HA2 | 内网 RTT 10–80 ms | 假设 | 验收 T7 实测 |
| HA3 | 目标盒子判停 700 ms（本机调优 64 ms） | 已核实配置差异 | 验收 T3 记录实际值；两者都需保留 |
| HA4 | 单路管线 4.6 GB、每路线性叠加 | 本机实测（`num_pipelines=1`） | 验收 T4 在多路下复测 |

> 状态取值约定：`待检索` / `已证实（来源 URL，日期）` / `不成立（回退候选见 plan-N）` /
> `假设` / `本机实测`。任何"已证实"必须带可点击 URL 与检索日期。
