# 异构平台适配设计（AMD ROCm / 昇腾 CANN / 瑞芯微 RKNN）—— 三平台全栈

> **日期**：2026-11-20
> **范围**：`speech-to-speech-src`（本文档所在仓库）从"仅 CUDA"扩展到 **AMD ROCm / 昇腾 CANN / 瑞芯微 RKNN 三个平台的完整全栈部署**，本期全部落地。
> **状态**：待评审 → 批准后进入 `superpowers:writing-plans` 出实施计划。
>
> **前置文档**（本文档是它们的延续，不重复其结论）：
> - `docs/hardware/edge-box-feasibility.md`（2026-10-22，非 CUDA 可行性结论的唯一来源）
> - `docs/hardware/performance-assumptions.md`（显存/并发/延迟档位的唯一推导来源）
> - `docs/hardware/acceptance-test-plan.md`（T0–T9 验收流程）
> - `docs/model-combination-matrix-CN.md`（模型组合矩阵）

---

## 0. 一页速览

| 项 | 内容 |
|---|---|
| **要解决的问题** | 现网仅支持 CUDA；本期扩展到 AMD ROCm、昇腾 CANN（910B / 950 档）、瑞芯微 RK3588 三平台**全栈部署** |
| **主线** | **平台抽象层**（PlatformProfile + Runtime + DeviceOps 三层）先冻结 → 三平台**并行**推进全栈落地 |
| **"全栈"的定义** | 在该平台上跑一个**独立 pipeline 实例**，完整暴露 `/v1/realtime`、`/v1/audio/transcriptions`、`/v1/audio/speech` 三个端点，VAD/STT/LLM/TTS 四个 stage **全部由本机提供**（TTS 可为降级档，须显式标注） |
| **本期承诺** | 三平台各出一个可验收的独立部署实例 + 统一 API 契约 + 分级降级标注 + 跨平台精度/性能对比表 |
| **本期不承诺** | 三平台性能一致；RK3588 满足 TTFA ≤ 2.0 s 实时档；昇腾 ATC→OM 全链路；具体硬件型号的最终选型 |
| **验收红线** | **分级红线**（允许平台原生格式 / 同家族小号 / 量化 / 外部服务，但**强制显式标注**降级档位并重跑 T1/T2/T3） |
| **预算** | 见 §7.3 三档配置；**推荐 4 人 × 13 周**（约 43–46 人周）。维持 2–3 人则周期需延至 16–20 周 |
| **最大风险** | ① AMD 上同款 Qwen3-TTS 实测 RTF 2.25–3.00（慢于实时），W8 为强制决策点；② RK3588 本地 TTS 无任何适配证据；③ 昇腾 `torch_npu` 与 `transformers==5.18.0` 的版本矩阵与算子覆盖 |

---

## 1. 意图与动因

### 1.1 为什么做

现网 `speech-to-speech` 的推理链路（STT=Qwen3-ASR-1.7B / TTS=Qwen3-TTS-1.7B / LLM 走 OpenAI 兼容 HTTP）全部绑在 CUDA 上：

- `pyproject.toml:52,54` 把 `torch`/`torchaudio` 硬 pin 到 `2.11.0+cu128`，并在 `:166-177` 固定 PyTorch cu128 索引；
- `Dockerfile:25` 基座是 `python-torch:cu128`，`:53` 把 `UV_INDEX` 指向 PyTorch cu128 通道；
- 所有 compose 编排带 `deploy.resources.reservations.devices: driver: nvidia`；
- `TTS/qwen3_tts_handler.py:193` 把 Qwen3-TTS 的 torch 后端设备白名单锁死为 `("cuda",)`。

本期目标：在 **AMD ROCm、昇腾 CANN、瑞芯微 RK3588** 三个平台上各部署一个功能完整的 pipeline 实例，用于国产化/信创合规、供应链成本替代、边缘形态三种场景。

### 1.2 本文档要改变的一个既有前提

`docs/hardware/edge-box-feasibility.md` §1.1/§1.2 定义了两条硬门槛：

| 门槛 | 原文 | 后果 |
|---|---|---|
| **G1 运行时** | 必须能跑 PyTorch + transformers **原样权重**；需转 RKNN/RKLLM/OM/OpenVINO IR/TensorRT engine 的一律不合格——"pipeline 里没有对应后端，而**计划禁止改 `src/`**" | 昇腾与 RK3588 被判"高风险 / 不适用" |
| **G2 内存** | 单路管线 4.6 GB（**CUDA 实测值**） | 内存不足出局 |

**本方案明确解除 G1 中"禁止改 `src/`"这一条**——这正是"CUDA 代码解耦与抽象层设计"要做的事。解除后的直接推论：

- G1 从"硬门槛"降级为"**分级红线下的 full 档定义**"：原样权重 = **full 档**；同家族小号 / 量化 / 平台原生格式 / 外部服务 = **degraded 档**，必须显式标注；
- G2 的 4.6 GB/路 是 CUDA 实测值，**跨平台不可直接外推**（原文档 `:532` 已自行标注此方法论风险），三平台一律以 T4 实测替代；
- `edge-box-feasibility.md` §5.2/§5.3 的短名单结论**在抽象层落地后需要复核**（列入 P4 收口）。

### 1.3 决策记录（2026-11-20）

| 决策 | 结论 | 影响 |
|---|---|---|
| 昇腾交付深度 | **全栈本地**，算力档位覆盖 **910B / 950 等数据中心卡**（不限于 500 端侧） | §3.2 重写：内存不再是门槛，形态从"预研"变"落地" |
| 瑞芯微交付深度 | **RK3588 环境也全栈部署** | §3.3 重写：新增"全栈"定义与 TTS 降级档 |
| 一致性红线 | **分级红线**：允许平台原生格式 / 同家族小号 / 量化 / 外部服务，强制显式标注 | 必须修改 `acceptance-test-plan.md` §13 与 `edge-box-feasibility.md` §1.1 |
| 人力与周期 | 2–3 人 × 3 个月（原始输入）；三平台全栈需 §7.3 三档配置之一 | **待评审确认配置档位** |

#### 1.3.1 昇腾算力档位的重新定位

既有文档（`edge-box-feasibility.md` D-E04/D-E05）对昇腾的判定基于**边缘小站**：

- Atlas 500（昇腾 310，8 GB）：可用内存 ≈ 5 GB → 纯管线槽位 `floor(5 × 0.85 ÷ 4.6) = 0 路`
- Atlas 500 A2（310P，12 GB）：可用内存 ≈ 9 GB → 槽位 1 路

**本期算力档位上移到数据中心卡（910B / 950 等）后，上述内存约束不再是主约束**：

- 昇腾侧成熟能力集中在 LLM（vLLM-Ascend / MindIE 支持 Qwen3-8B 等），且提供 **OpenAI 兼容 HTTP**；
- 910B 档的 HBM 容量足以同时容纳 ASR-1.7B + TTS-1.7B + 本地 LLM（具体容量以 T4 实测替代，**不引用未经核实的规格数字**）；
- 因此**昇腾全栈本地在算力上是可行的**，真正的技术风险从"内存"转移到"**算子覆盖 + 框架版本矩阵 + `faster-qwen3-tts` 不可用**"（§3.2）。

> **选型纪律**：910B / 950 的具体型号规格（卡数、HBM 容量、互联方式、功耗），本方案**不做无据断言**，按本仓既有证据纪律（`edge-box-feasibility.md` §1.3/§1.4：官方模型卡 > 芯片厂商模型库 > 社区实测 > 工具链推断）另行检索核实，写入 `docs/hardware/procurement-list.md` 后再回填本方案。§7.2 的昇腾容量推导一律标注"以实测为准"。

### 1.4 目标 / 非目标 / 反目标

**目标**

1. 建立平台抽象层，使"新增一个加速器平台"不再需要改 40 个 handler；
2. **AMD ROCm**：全栈实例，达到**可用档**（TTFA P95 ≤ 2.0 s，STT/TTS RTF < 1.0）；
3. **昇腾 CANN**：全栈实例，STT/TTS/LLM 全部本机提供；LLM 走 vLLM-Ascend/MindIE HTTP（零代码）或 torch_npu；LLM + STT/TTS 至少一条走 torch_npu 原生权重路径；
4. **瑞芯微 RK3588**：全栈实例，VAD(RKNN) + STT(RKNN+RKLLM) + LLM(rk-llama.cpp) + TTS(CPU-GGML 降级档 或 小号 或 远程)；
5. 三平台**同一套 API 契约**（`/v1/realtime`、`/v1/audio/transcriptions`、`/v1/audio/speech`）+ 统一能力矩阵与降级标注 + 跨平台精度/性能对比表。

**非目标（本期不做）**

- 三平台性能一致（差异通过能力矩阵**显式暴露**，不做假统一）
- RK3588 满足 TTFA ≤ 2.0 s 实时档（物理约束，见 §3.3.3）
- 昇腾 ATC→OM 全链路打通（作为备选路径评估，不作为承诺）
- TensorRT / vLLM 深度优化、多节点编排、跨机弹性、模型量化体系的跨平台统一

**反目标（做成了也算失败）**

- **静默降级**：换小模型/换格式/走外部服务后不标注，让验收方误以为与 CUDA 一致
- **抽象层空转**：新增了 PlatformProfile 但 CUDA 路径行为发生变化（CUDA 回归必须零 diff）
- **"接口预留"变成 TODO 堆**：预留的 runtime 必须有可运行的 stub + 单测，否则不算完成
- **API 契约分叉**：三平台各自改端点语义（同一套契约是"全栈"的定义性要求）

---

## 2. 约束

| 类别 | 约束 |
|---|---|
| **技术** | 零自定义 CUDA 扩展（全仓无 `cpp_extension`/`load_inline`/triton kernel）；无 flash-attn/xformers/deepspeed/tensorrt/apex；attention 默认 `eager`（TTS）/ `sdpa`（LLM）；模型为 HF safetensors 格式，无 vendored modeling 代码，绑死 `transformers==5.18.0` |
| **运行时** | ROCm 上 PyTorch 保留 `torch.cuda` API（HIP 透明替换）；昇腾用 `torch_npu`（`torch.npu`）；**RK3588 无 PyTorch GPU 后端**（其 STT/LLM 必须走 RKNN/RKLLM/rk-llama.cpp 专用运行时） |
| **构建** | 现网基座 `ccr.ccs.tencentyun.com/llm-basic/python-torch:cu128`，`UV_INDEX` 指向 PyTorch cu128 通道，`first-index` 策略；`Dockerfile` 构建期会 strip 掉 `torch|torchaudio|nvidia-` constraints |
| **交付** | 三平台全栈并行；硬件采购与到货周期需在 W1 启动（**昇腾服务器采购周期是关键路径**） |
| **质量** | CUDA 现网行为**零变化**；模型指纹与精度基线必须在 P0 内建立（当前缺失） |

---

## 3. 目标平台可行性分析

### 3.1 AMD ROCm

#### 3.1.1 运行时路径

PyTorch 的 ROCm 构建**保留 `torch.cuda` 命名空间**（HIP 后端透明替换），因此：

- `torch.cuda.is_available()` / `torch.cuda.Event` / `torch.cuda.synchronize()` / `torch.cuda.empty_cache()` 在 ROCm 上语义不变；
- `transformers` 原样加载 safetensors **无需任何转换**；
- 抽象层改动量最小——主要工作在**构建层**（wheel 索引、基础镜像、compose 设备保留）与**能力差异处理**（量化、CUDA graph、SDPA 后端）。

结论：**G1 满足**（原样权重可加载），是三平台中改造量最小的一个。

#### 3.1.2 关键约束与已知坑

| 约束 | 事实 | 对本方案的影响 |
|---|---|---|
| **TTS RTF** | 同款 `Qwen3-TTS-12Hz-1.7B-CustomVoice` 在 PyTorch + ROCm 7.2（128 GB Strix Halo）实测 **RTF 平均 3.00 / 最佳 2.25**，首轮 4.20 为 kernel 编译冷启动 | **慢于实时**。同机 F5-TTS RTF 0.64 说明瓶颈在 Qwen3-TTS 的 ROCm 算子路径，不是硬件绝对上限 |
| **官方 wheel 覆盖** | gfx1151（Ryzen AI Max+ 395 / Strix Halo）截至 2026-02 未进官方支持矩阵；ROCm 7.2 可用（PyTorch 2.9.1+rocm7.2），ROCm 7.14 有官方 gfx1151 包，也有 TheRock nightly 通道 | 选型直接决定成败，见 §3.1.4 |
| **AOTriton** | flash-attention 曾**静默失效**；PyTorch 2.10 将 GFX1151 加入 hipBLASLt GEMM 与 AOTriton SDPA | SDPA 后端需按平台白名单校验，不允许默认信任 |
| **bitsandbytes** | 仅 CUDA kernel | `load_in_4bit/8bit` 在非 CUDA 平台必须**显式报错**，不能静默忽略 |
| **faster-qwen3-tts 的 CUDA graph** | triton JIT + CUDA graph 捕获，ROCm 下行为未验证 | 走 `qwen3_tts_parity_mode`（本仓已有该开关，见 `arguments_classes/qwen3_tts_arguments.py:99-102`） |
| **vLLM aiter** | 不支持 gfx1151 | 本期 LLM 走 llama.cpp（ROCm/Vulkan）或远程，不依赖 vLLM |

#### 3.1.3 TTS RTF 攻坚路径（按优先级，P1 W4–W7）

| 序 | 手段 | 说明 |
|---|---|---|
| 1 | **ggml 后端** | `qwen3_tts_backend=ggml` + GGUF（Q8_0 / Q4_K_M）。`faster-qwen3-tts[ggml]` 底层是 `qwentts-cpp-python`（C++/GGML），**零 NVIDIA 依赖**，ROCm/CPU 通吃。本仓已支持：`VALID_GGML_QUANTIZATIONS = ("BF16","Q8_0","Q4_K_M","F32")` + `qwen3_tts_gguf_talker_path/_codec_path`。**注意：GGUF 档本身即 degraded 档**（格式转换 + 量化） |
| 2 | **换 ROCm 版本 / 换硬件** | ROCm 10.0 或 TheRock 构建；MI300X/MI325X 有官方 wheel + 高带宽 |
| 3 | **attention 后端对比** | TTS 侧默认 `eager`；对比 `sdpa`（ROCm 走 AOTriton）实测定优劣 |
| 4 | **量化** | 降到 Q8_0 / Q4_K_M / INT8；精度需按 §6.1 重新验收 |
| 5 | **形态降级** | AMD 只做 STT + LLM，TTS 走远程（`openai` TTS backend 已存在，`backend_registry.py:722-728`）。**注意此选项会使"全栈"定义中的 TTS stage 不由本机提供**，需在验收报告中标注 |

#### 3.1.4 硬件选型建议（与既有采购文档不同，需要复核）

`edge-box-feasibility.md` §5.2 把 `D-E09`（Ryzen AI Max+ 395，128 GB 统一内存）列为 P1 候选，但同卡 TTS RTF 已判"高风险"，且 gfx1151 无官方 wheel。

**本方案建议：AMD 侧首选 MI300X / MI325X 级数据中心卡服务器，而不是 Strix Halo 迷你主机。** 理由：

1. 官方 wheel 齐全，gfx 架构在支持矩阵内，构建可复现（Strix Halo 需 nightly，版本漂移风险直接落到验收上）；
2. HBM 带宽远高于 LPDDR5X 统一内存，TTS 的 AR 解码是带宽瓶颈，收益直接；
3. MI300X 生态（vLLM/SGLang/aiter）完整，LLM 侧不必绕 llama.cpp。

此建议**与既有采购文档结论不一致**，需在 P1 W1 作为独立事项复核（见 §8 R9）。同时需确认该档位硬件的**采购可得性与价格**（`procurement-list.md` 同一纪律）。

### 3.2 昇腾 CANN（910B / 950 档，全栈本地）

#### 3.2.1 一个显著降低风险的工程事实

既有文档（`edge-box-feasibility.md` §1.3）对昇腾的判定偏悲观，理由是"ATC→OM 转换 + 算子适配"。但对本工程而言有一条决定性事实：

> **本工程零自定义 CUDA 扩展、零 flash-attn/xformers/deepspeed，attention 默认 `eager`，模型是标准 safetensors。**

这意味着 `torch_npu` **直接跑 transformers 原样权重**的可行性，远高于"必须转 OM"的直觉。ATC→OM 是"ATC 支持的模型"的路径；而 Qwen3-ASR/TTS 是 transformers 内置实现的自定义架构，ATC 官方模型库本就无覆盖——**主路径应当是 torch_npu 原生算子，OM 仅作为个别算子缺失时的备选**。

同理，`faster-qwen3-tts`（CUDA/GGML 双实现）在昇腾上很可能不可用，需要**绕开它**，改走 `qwen-tts-hf`（已在 `zerogpu` extra 中：`pyproject.toml:77`）+ torch_npu。这是一条真实工作项，见 §4.3。

#### 3.2.2 全栈技术路线

| Stage | 方案 | 档位 | 备注 |
|---|---|---|---|
| **VAD** | Silero VAD ONNX（CPU） | full | 不变，零成本复用 |
| **STT** | `torch_npu` + transformers（**eager attention**）跑 Qwen3-ASR-1.7B 原样权重 | **full**（权重一致） | 主路径；`attn_implementation` 固定 eager 以规避 torch_npu SDPA 行为差异 |
| **TTS** | `qwen-tts-hf` + `torch_npu`（绕开 `faster-qwen3-tts`） | full 或 degraded | 若 Qwen3-TTS 的 talker 算子在 torch_npu 有缺口，降级到 ggml/CPU；这是**昇腾线最大的不确定项** |
| **LLM** | **MindIE / vLLM-Ascend（OpenAI 兼容 HTTP）** | full | **零代码**：本仓 `chat-completions` backend 已存在（`backend_registry.py:562-585`），指向昇腾服务即可；备选 torch_npu + transformers |

**这条路线的分期价值**：即使昇腾 STT/TTS 全部不成立，**LLM 侧仍能作为独立可交付**（零代码路径），分期风险被自然隔离。

#### 3.2.3 障碍清单

| 障碍 | 事实 | 应对 |
|---|---|---|
| `torch.cuda.*` 工具调用 | `torch.cuda.Event`/`synchronize`/`empty_cache`/`is_bf16_supported`/`backends.cuda.matmul.allow_tf32` 在 `torch_npu` 下不存在 | **L1 DeviceOps 抽象直接解决**（§4.2）——抽象层的第一个真实受益者 |
| `faster-qwen3-tts` CUDA 导向 | 包本身以 CUDA + GGML 为两条实现 | 昇腾路径绕开该包，改用 transformers 原生 `qwen_tts` + torch_npu（需新写 `Qwen3TTSTransformersRuntime`） |
| `transformers` 版本矩阵 | 本仓 pin `transformers==5.18.0`，`torch_npu` 与 torch 版本强绑定 | P2 W1 锁定组合并在 `pyproject` 加 npu 分支 pin |
| `attn_implementation="sdpa"`（LLM 侧 `language_model.py:915`） | `torch_npu` 有自己的 SDPA 实现，行为与 CUDA 不同 | 抽象层提供 per-platform 的 attn 白名单；昇腾默认 eager |
| ATC→OM 链 | 官方模型库无 Qwen3-ASR/TTS | 降级为备选路径评估，W6 出结论 |
| 量化工具链 | bitsandbytes 仅 CUDA；昇腾需 W8A8 量化工具链 | 本期量化档位由 `qwen-tts-hf`/GGUF 路线承担，不自建量化链 |

### 3.3 瑞芯微 RK3588（全栈部署）

#### 3.3.1 事实

| 事实 | 来源 |
|---|---|
| RK3588：4×A76 + 4×A55、Mali-G610、NPU **6 TOPS INT8**、最高 32 GB LPDDR4X/5、**51.2 GB/s**、5–20 W | `edge-box-feasibility.md` D-E06 |
| RKNN 必须把模型转成 `.rknn`（定点）；RKLLM 只跑 LLM 且需转 `.rkllm` | 同上 |
| llama.cpp 官方后端表**没有 RKNN**；RK 平台走第三方 `rk-llama.cpp`（invisiofficial 分支） | 同上 |
| **RK3588 / RK3576 可跑 Qwen3-ASR**：RKNN 编码器 + RKLLM 解码器，W8A8 | Seeed 社区方案（2026-09-07） |
| RK3588 + RK1828 算力棒：Qwen3-ASR **48 tokens / 316.94 ms ≈ 151 tokens/s** | 定昌 DC_M588 厂商实测 |
| Qwen3.5-2B 在 8 GB RK3588 板跑通（RKNPU2 backend, Q8_0） | 掘金实战文（2026-09-18） |
| **Qwen3-TTS 在 RK 平台的适配：证据缺失** | 同上 |
| PyTorch + transformers 在 RK3588 上只能 CPU 跑，RTF 远大于 1，无实用价值 | `edge-box-feasibility.md` D-E06 |

#### 3.3.2 全栈技术路线

| Stage | 方案 | 档位 | 工程新增项 |
|---|---|---|---|
| **VAD** | Silero VAD ONNX → **RKNN**（`rknn-toolkit2` 交叉编译 → `rknn-toolkit-lite2` 部署） | full（模型一致，仅格式转换） | 转换脚本 + 精度回归（ONNX vs RKNN 输出比对） |
| **STT** | **RKNN 编码器 + RKLLM 解码器（W8A8）** | degraded（模型切分 + 定点化） | **模型切分脚本**：把 Qwen3-ASR 拆成 encoder / decoder 两部分（思路可复用本仓既有 `scripts/extract_speaker_encoder.py` 的权重切分模式） |
| **LLM** | **`rk-llama.cpp`**（第三方 fork）跑 Qwen3.5-2B / 0.8B GGUF | degraded（换模型档位） | 镜像构建（fork 需自建）+ OpenAI 兼容 HTTP 对接（复用本仓 `chat-completions` backend，零代码） |
| **TTS** | ① **CPU-GGML**：`faster-qwen3-tts[ggml]` + Qwen3-TTS GGUF（Q4_K_M），纯 C++/GGML 无 NVIDIA 依赖 ② 降级小号 TTS ③ 远程 TTS | degraded | 本仓已有 ggml 后端，需确认 `qwentts-cpp-python` 能在 aarch64 上交叉编译 |

**模型切分是 RK3588 线的核心工程项**：Qwen3-ASR 的 encoder（音频侧）与 decoder（文本侧）必须分别走 RKNN 与 RKLLM 两条工具链，两者的 tokenizer/vocab/位置编码对齐是主要风险点。

#### 3.3.3 RK3588 全栈的"可用"边界（必须提前确认）

RK3588 的硬约束是 **6 TOPS NPU + 51.2 GB/s 带宽 + A76/A55 CPU**。因此：

- **VAD / STT / LLM** 有社区与厂商实测支撑，落在 degraded 档但可用；
- **TTS 是真正的卡点**：Qwen3-TTS-1.7B 在该平台的适配**证据完全缺失**，CPU-GGML 路径预计 RTF 远大于 1（**不满足实时档**）。

因此本方案建议把 RK3588 的"全栈"验收标准定为：

> **链路级全栈**：三端点全部可用、VAD/STT/LLM/TTS 四 stage 均由本机提供、出音正确；**但 TTFA 与 RTF 明确标注为"非实时档"，不计入 §6.2 的 TTFA ≤ 2.0 s 判定**。

如果业务要求 RK3588 也满足实时档，则只有两条路：换更大的 SoC（如 RK3588 之外的更高阶 NPU 平台），或接受 TTS 走外部服务（此时 TTS stage 不由本机提供，与"全栈"定义冲突）。**这一条需要在评审时明确拍板**，本方案按上面的"链路级全栈"口径撰写。

### 3.4 三平台横向对比

| 维度 | AMD ROCm | 昇腾 CANN（910B/950 档） | 瑞芯微 RK3588 |
|---|---|---|---|
| **本期档位** | 全栈 | 全栈 | 全栈（链路级） |
| **权重转换** | 不需要（`torch.cuda` 透明） | 主路径不需要（torch_npu 原生）；ATC→OM 为备选 | 必须（ONNX→RKNN / RKLLM / GGUF） |
| **VAD** | ONNX CPU | ONNX CPU | **ONNX→RKNN** |
| **STT** | 原样权重，torch 原生 | 原样权重，torch_npu + eager | RKNN 编码器 + RKLLM 解码器（W8A8） |
| **TTS** | ggml 优先（RTF 攻坚），torch 次选 | `qwen-tts-hf` + torch_npu | CPU-GGML 降级档（预计非实时） |
| **LLM** | llama.cpp ROCm/Vulkan | **vLLM-Ascend / MindIE HTTP，零代码** | `rk-llama.cpp` 第三方 fork |
| **最大技术风险** | TTS RTF ≥ 1.0 | torch_npu 算子覆盖 + `faster-qwen3-tts` 不可用 | TTS 无方案 + 模型切分对齐 |
| **最高降级档** | TTS 可能走远程 | TTS 可能走 ggml/CPU | 三个 stage 均为 degraded |
| **硬件门槛** | MI300X 级服务器优先 | 数据中心卡服务器（910B/950 档，规格待核实） | 16 GB 板足够 |
| **精度基线可比性** | 高（原样权重） | 高（原样权重） | 低（定点化 + 模型切分 + 换家族 LLM） |

---

## 4. 抽象层设计

### 4.1 三层结构总览

现有 CUDA 耦合点分三类，分别对应三层：

- **(a) 设备字符串**散布在 handler 的 `resolve_device(device, <白名单>, ...)` 调用中 → **L3 平台档案**收口；
- **(b) `torch.cuda.*` 工具调用**（计时、显存、精度探测、后端开关） → **L1 设备操作**收口；
- **(c) 平台专有依赖**（bitsandbytes / CTranslate2 / faster-qwen3-tts / RKNN / rk-llama.cpp / 构建层索引） → **L2 运行时** + 构建层收口。

```
┌──────────────────────────────────────────────────────────────┐
│ L3  PlatformProfile —— 平台是一等公民                        │
│     id / arch / os / torch_build / device                    │
│     runtimes: {torch, ggml, onnxrt, http, rknn, rkllm}      │
│     capabilities: dtype / attn / graph / quant / mem_ops     │
│     image / notes                                            │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ L2  Runtime —— STTRuntime / TTSRuntime / LLMRuntime          │
│     handler 退化为 adapter，只声明「需要什么能力」            │
│     降级链 FallbackChain 由 PlatformProfile.capabilities 驱动 │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ L1  DeviceOps —— 平台相关的 torch.* 工具调用                  │
│     empty_cache / synchronize / event / is_bf16_supported    │
│     allow_tf32 / sdpa_backend / mem_info / dtype_policy      │
└──────────────────────────────────────────────────────────────┘
```

**设计原则**

1. **能力而非设备**：handler 声明"我需要 bf16 / 需要流式 / 不需要自定义 attention"，由平台档案决定能不能满足。禁止继续把设备白名单写在每个 handler 里。
2. **CUDA 行为零变化**：L1/L2/L3 落地后，CUDA 路径的输出必须与改造前逐项一致（P0 硬门槛）。
3. **降级必须可观测**：任何降级都进入能力矩阵、启动日志与 API 响应，不允许静默。
4. **平台新增不碰 handler**：新增平台 = 新增一个 Profile + 新增 runtime 实现 + 构建变体，**不改 40 个 handler**。
5. **API 契约不分叉**：三平台跑的是同一套 `src/speech_to_speech/api/openai_realtime/`，平台差异只体现在 runtime 层。

### 4.2 L1：DeviceOps（平台相关的 torch 工具调用）

**问题**：`torch.cuda.*` 在 ROCm 上"恰好可用"，但在 `torch_npu` 上完全不存在，在 RK 上无意义。当前 8 处调用散落（`whisper_stt_handler.py:115-125`、`language_model.py:894-896,909,1067-1082`、`qwen3_tts_handler.py:230,1054-1055`、`sense_voice_handler.py:212-214`、`model_monitor.py:151-165`）。

**设计**：一个按设备类型分发的 ops 对象，取代直接调用。

```python
# src/speech_to_speech/platform/device_ops.py
class DeviceOps(Protocol):
    device: str
    def empty_cache(self) -> None: ...
    def synchronize(self) -> None: ...
    def event(self, enable_timing: bool = True) -> Any: ...
    def is_bf16_supported(self) -> bool: ...
    def allow_tf32(self) -> None: ...
    def sdpa_backend(self) -> str | None: ...      # 平台白名单校验
    def memory_info(self) -> tuple[int, int]: ...  # (free, total) bytes
    def preferred_dtype(self) -> "torch.dtype": ...

def get_device_ops(device: str) -> DeviceOps: ...   # cuda/rocm → CudaOps；npu → NpuOps；cpu → CpuOps
```

**平台实现要点**

| 实现 | 适用 | 说明 |
|---|---|---|
| `CudaOps` | CUDA | 现有行为 1:1 迁移；`allow_tf32` / `enable_cudnn_sdp` 保留 |
| `RocmOps` | ROCm | `torch.cuda.*` 可用，但 `is_bf16_supported()` 语义需实测（gfx1151 的 bf16 支持情况与 CUDA 不同）→ 返回**实测值**而非假设；`sdpa_backend` 需校验 AOTriton 可用性（已知静默失效） |
| `NpuOps` | 昇腾 | `torch.npu.npu.empty_cache()` / `torch.npu.synchronize()`；bf16 支持由 `torch.npu.is_bf16_supported()` 判定；`allow_tf32` 为 no-op |
| `CpuOps` | CPU / RK3588 | 空实现；`preferred_dtype` 返回 fp32 |

**新增/改造点清单**

| 文件 | 现状 | 改造 |
|---|---|---|
| `STT/whisper_stt_handler.py:115-125` | `torch.cuda.Event` / `torch.cuda.synchronize()` | 换 `device_ops` |
| `LLM/language_model.py:894-896` | `torch.backends.cuda.matmul.allow_tf32` / `cudnn.allow_tf32` | 换 `device_ops.allow_tf32()` |
| `LLM/language_model.py:909` | `torch.backends.cuda.enable_cudnn_sdp(True)` | 换 `device_ops.sdpa_backend()` |
| `LLM/language_model.py:1067-1082` | `torch.cuda.Event` / `synchronize()` | 换 `device_ops` |
| `TTS/qwen3_tts_handler.py:230` | `torch.cuda.is_bf16_supported()` | 换 `device_ops` |
| `TTS/qwen3_tts_handler.py:1054-1055` | `torch.cuda.empty_cache()` | 换 `device_ops` |
| `STT/sense_voice_handler.py:212-214` | `torch.cuda.empty_cache()` / `torch.backends.mps` | 换 `device_ops` |
| `utils/model_monitor.py:151-165` | `torch.cuda.is_available()` / `device_count()` / `memory_allocated()` / `utilization()` | 换 `device_ops.memory_info()`；`nvidia-smi` 子进程 → 按平台分派（`rocm-smi` / `npu-smi` / RK 无） |

### 4.3 L2：Runtime 接口

**问题**：现在"一个后端 = 一个 handler 类"，后端与执行方式耦合——`Qwen3TTSHandler` 内部同时管 ggml / torch / mlx 三条加载路径，靠 `self.backend` 分支；`Qwen3ASRSTTHandler` 直接绑死 transformers。

**设计**：把"执行"与"编排"分离。handler 保留编排职责（队列、取消、消息），把模型调用委托给 runtime。

```python
# src/speech_to_speech/platform/runtimes/base.py
@dataclass(frozen=True)
class ModelSpec:
    model_name: str
    device: str
    dtype: str
    extra: Mapping[str, Any]        # backend-specific kwargs

class STTRuntime(Protocol):
    name: str
    fidelity: str                    # "full" | "degraded"
    def load(self, spec: ModelSpec) -> None: ...
    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str | None) -> TranscriptionResult: ...
    def warmup(self) -> None: ...

class TTSRuntime(Protocol):
    name: str
    fidelity: str
    def load(self, spec: ModelSpec) -> None: ...
    def synthesize_stream(self, text: str, voice: VoiceSpec) -> Iterator[np.ndarray]: ...
    def warmup(self) -> None: ...

class LLMRuntime(Protocol):
    name: str
    fidelity: str
    def stream_chat(self, messages, *, gen_kwargs) -> Iterator[str]: ...
```

**Runtime 实现清单**

| Runtime | 对应现状 | 平台 | fidelity |
|---|---|---|---|
| `Qwen3ASRTorchRuntime` | `STT/qwen3_asr_handler.py` 抽取 | CUDA / ROCm / NPU | full（权重原样） |
| `Qwen3ASRTransformersRuntime` | 同上，改用 `qwen_tts`/`qwen_asr` 原生 transformers 路径 | NPU | full |
| `RknnASRRuntime` | 新增（RKNN 编码器 + RKLLM 解码器） | RK3588 | degraded |
| `Qwen3TTSFasterRuntime` | `TTS/qwen3_tts_handler.py` 的 torch 分支 | CUDA / ROCm | full |
| `Qwen3TTSGgmlRuntime` | `TTS/qwen3_tts_handler.py` 的 ggml 分支 | CUDA / ROCm / CPU / NPU / RK3588 | degraded（GGUF 量化） |
| `Qwen3TTSTransformersRuntime` | 新增（`qwen-tts-hf` + torch_npu） | NPU | degraded 或 full |
| `RknnVADRuntime` | 新增（Silero ONNX→RKNN） | RK3588 | full |
| `TransformersLLMRuntime` | `LLM/language_model.py` | CUDA / ROCm / NPU | full |
| `ChatCompletionsLLMRuntime` | `LLM/chat_completions_language_model.py` | 全部（含昇腾 vLLM-Ascend / MindIE、RK 的 rk-llama.cpp） | full / degraded |
| `RkllmLLMRuntime` | 新增（可选，若 rk-llama.cpp 不满足则走此路） | RK3588 | degraded |
| `OpenAICompatibleTTSRuntime` | `TTS/openai_compatible_handler.py` | 全部（远程 TTS 降级路径） | degraded（外部服务） |

**降级链（FallbackChain）**

平台档案声明"本平台能跑什么"，配置声明"想要什么"，二者求交得到实际 runtime 组合；若不可满足则**按预设顺序降级并记录原因**：

```
配置意图:  STT=qwen3-asr(1.7B) / TTS=qwen3(torch) / LLM=local
ROCm 实得: STT=qwen3-asr(1.7B) full / TTS=qwen3(ggml Q8_0) degraded[reason=rocm_torch_rtf_gt_1] / LLM=llama.cpp
RK3588 实得: VAD=rknn full / STT=rknn+rkllm degraded[reason=fixed_point_and_model_split] /
             TTS=ggml_cpu degraded[reason=cpu_only_no_rknn_tts] / LLM=rk-llama.cpp degraded[reason=model_family_swapped]
```

降级原因必须落在**机器可读**的位置（§4.5）。

### 4.4 L3：PlatformProfile

```python
# src/speech_to_speech/platform/profiles.py
@dataclass(frozen=True)
class PlatformProfile:
    id: str                                  # "cuda" | "rocm" | "ascend" | "rk3588" | "cpu"
    display_name: str
    os_family: str
    arch: str                                # x86_64 / aarch64
    torch_build: str                         # "cu128" / "rocm7.2" / "npu" / "cpu"
    torch_device: str | None                 # "cuda" / "cuda" / "npu" / None / "cpu"
    runtimes: frozenset[str]                 # {"torch","ggml","onnxrt","http","rknn","rkllm"}
    capabilities: PlatformCapabilities
    container_image: str
    notes: str

@dataclass(frozen=True)
class PlatformCapabilities:
    dtypes: frozenset[str]                   # {"bf16","fp16","fp32"}
    attn_implementations: frozenset[str]     # {"eager","sdpa"}
    supports_cuda_graph: bool
    supports_bnb_quant: bool                 # bitsandbytes 仅 CUDA
    supports_ctranslate2: bool               # 仅 CPU / CUDA
    quant_modes: frozenset[str]              # {"bf16","fp16","fp32","ggml_q8","ggml_q4","int8","w8a8"}
```

**探测**：`detect_platform()` 依次检查

1. `torch.version.hip` 非空 → ROCm；
2. `torch.npu.is_available()`（懒 import `torch_npu`）→ 昇腾；
3. `/dev/mali0` 存在 或 `rk_env` 可执行 → RK3588；
4. `torch.cuda.is_available()` → CUDA；
5. 否则 CPU。

**与既有代码的衔接**：`utils/utils.py:83` 的 `TORCH_DEVICES = ("cuda","npu","xpu","mps","cpu")` 保留（向后兼容 + `tests/test_device.py` 依赖），但 `resolve_device()` 内部改为查 `PlatformProfile` 的 `torch_device` 与 `runtimes`，**不再由每个 handler 传自己的设备白名单**。

**配置面**

| 新增参数 | 默认 | 说明 |
|---|---|---|
| `--platform` | `auto` | `auto/cuda/rocm/ascend/rk3588/cpu`；`auto` 走 `detect_platform()` |
| `--fidelity` | `auto` | `full`（只接受 full 档 runtime，不满足即启动失败）/ `degraded`（允许降级）/ `auto`（按平台能力择优） |
| `--llm_backend` | 既有 | 指向昇腾 vLLM-Ascend / MindIE、RK 的 rk-llama.cpp 时填其 OpenAI 兼容 base_url，**零代码** |
| `--vad_backend` | 既有 | RK3588 上选 `rknn` |

既有 `--qwen3_asr_device` / `--qwen3_tts_device` / `--qwen3_tts_backend` 保持可用，映射进 Profile。

### 4.5 能力矩阵与降级标注（落实"分级红线"）

**分级定义**

| 档位 | 含义 | 允许内容 |
|---|---|---|
| `full` | 与 CUDA 现网一致 | 同款模型、同款格式（safetensors）、同精度档（FP16/BF16），行为经 T1/T2/T3 验证 |
| `degraded` | 显式降级 | 同家族小号（0.6B）、量化（GGUF Q8/Q4、INT8、W8A8）、平台原生格式（OM/.rknn/.rkllm）、模型切分、外部服务（远程 TTS/LLM） |

**必须显式标注的位置（缺一不可）**

1. `GET /v1/realtime/capabilities` 扩展响应：每个 stage 的 runtime 名、fidelity 档、模型标识、量化档、权重指纹（sha256 前 8 位）、降级原因链；
2. **启动日志**：一行结构化摘要（JSON 友好），含 `platform`、`runtimes`、`fidelity`、`degradation_reasons`；
3. 每次会话建立时在 `session.created` 事件里回带 `fidelity` 与 `platform`；
4. 验收报告（§6）必须引用该矩阵。

**CLI 行为**：`--fidelity full` 时，若任一 stage 只能落到 `degraded`，**启动即失败**并打印原因——这是"分级红线"在工程侧的强制点。RK3588 因三个 stage 天然为 degraded，其部署配置固定用 `--fidelity degraded`，并在启动日志标注原因。

### 4.6 构建层解耦

| 项 | 现状 | 改造 |
|---|---|---|
| `pyproject.toml:51-56` | `torch==2.11.0+cu128` / `torchaudio==2.11.0+cu128`（非 Darwin） | 改为按 platform marker 分支：`cu128`（默认）/ `rocm7.x` / `npu` / `cpu`；新增 `[tool.uv.sources]` 对应条目 |
| `pyproject.toml:166-177` | `[[tool.uv.index]] pytorch-cu128` + `explicit = true` | 增加 `pytorch-rocm6.2` / `pytorch-rocm7.x` 索引条目，用 `explicit = true` + marker 控制 |
| `pyproject.toml:60-61` | `faster-qwen3-tts[ggml]`（非 Darwin/Windows） | 保留；昇腾分支改为 `qwen-tts-hf` |
| `pyproject.toml:40` | `onnxruntime`（CPU 版） | RK3588 侧另加 `rknn-toolkit-lite2`（仅 aarch64 运行时），转换工具 `rknn-toolkit2` 走 x86 构建期 |
| `Dockerfile:25` | `ARG BASE_IMAGE=...python-torch:cu128` | 已参数化；新增 `Dockerfile.rocm` / `Dockerfile.npu` / `Dockerfile.rk3588` 变体，统一为 `ARG BASE_IMAGE` + `ARG UV_INDEX` 双参数 |
| `Dockerfile:53` | `UV_INDEX="https://download.pytorch.org/whl/cu128 ..."` | 改为 `ARG` 注入，避免每个变体改一次 sed |
| `Dockerfile:93` | `grep -vE '^(torch|torchaudio|nvidia-)'` 剥 constraints | ROCm 变体需改为剥 `^rocm` / `^amd` 等前缀；NPU 变体需处理 `torch_npu` 的版本配套 |
| `Dockerfile:151-154` | `sed` 改 site-packages 的 `qwen_tts/_transformers_compat.py` | 保留（与平台无关）；但**昇腾走 transformers 原生路径时需验证该补丁是否仍需要** |
| compose | `deploy.resources.reservations.devices: driver: nvidia` | ROCm 变体用 `device_ids` + 取消 nvidia driver 保留；昇腾用 `ASCEND_RT_VISIBLE_DEVICES`；RK 用 `/dev/mali0` + `/dev/dri` 设备透传 |
| `Dockerfile.arm64` | NVIDIA Jetson/DGX Spark 的 aarch64 CUDA 镜像 | **与昇腾/RK 无关**，不改；新增 `Dockerfile.rk3588`（aarch64 + RKNN/RKLLM runtime） |

**镜像矩阵纪律**：CI 只保留"已验证组合"（cu128 / cu130 / rocm / npu / rk3588），每新增平台必须同时提交 CI 绿灯，否则不合并（§8 R4）。三平台并行期建议**每个平台一个独立 compose 文件**（参照既有 `docker-compose.split.yml` / `docker-compose.allinone.yml` 的组织方式），避免单文件爆炸。

---

## 5. 算子与推理引擎跨平台迁移策略

### 5.1 资产分类与迁移路径

| 资产类型 | 本工程实例 | 可迁移目标 | 转换成本 |
|---|---|---|---|
| **A. 原生 PyTorch 权重** | Qwen3-ASR-1.7B / Qwen3-TTS-1.7B（safetensors） | ROCm（零转换）、昇腾 torch_npu（零转换） | 低 |
| **B. GGUF / GGML** | Qwen3.5-*.gguf（LLM）、Qwen3-TTS GGUF（`gguf_talker_path`/`_codec_path`） | llama.cpp（ROCm/Vulkan/CPU）、`faster-qwen3-tts` ggml、`rk-llama.cpp` | 低（需先产出 GGUF） |
| **C. ONNX** | Silero VAD（`silero_vad.onnx` / `silero_vad_v6.onnx`）、smart-turn（`smart-turn-v3.2-cpu.onnx`） | onnxruntime（CPU）、**RKNN** | 中（需导出） |
| **D. 平台原生格式** | 无 | OM(ATC)、`.rknn`、`.rkllm`、TensorRT engine | 高（需独立维护转换链） |

### 5.2 迁移决策树（写入实现规范）

```
需要平台原生加速？
 ├─ 否 → 优先用 A（torch 原生权重路径）
 │        ROCm ✔  torch.cuda API 透明
 │        昇腾 ✔  torch_npu 原生算子（需 eager attention）
 │        RK3588 ✘  无 PyTorch GPU 后端
 ├─ 是 → 有成熟的 B（GGUF/GGML）实现？
 │        ├─ 是 → 用 B（llama.cpp / ggml 后端 / rk-llama.cpp）★ 首选
 │        │        跨平台通用性最好的中间格式
 │        └─ 否 → 有 C（ONNX）导出路径？
 │                 ├─ 是 → ONNX → 目标运行时（RKNN / OM / TensorRT）
 │                 └─ 否 → 接受 D：为该平台单独维护转换链
 │                          长期成本，必须单独立项，不得塞进本期
```

### 5.3 算子风险清单与实测要求

| 算子/机制 | 出现位置 | ROCm | 昇腾 | RKNN |
|---|---|---|---|---|
| **flash-attention** | 本工程**未使用**（TTS eager / LLM sdpa） | 不适用 | 不适用 | 不适用 |
| **AOTriton SDPA** | LLM 侧 `attn_implementation="sdpa"` | **已知静默失效** → 必须校验后端 | torch_npu 自有 SDPA，行为待验 | 不适用 |
| **CUDA Graph 捕获** | `faster-qwen3-tts` 内部 triton JIT | 不可靠 → 走 `qwen3_tts_parity_mode` | 不适用 | 不适用 |
| **bitsandbytes 4/8bit** | `LLM/language_model.py:901-904` | **不支持** → 非 CUDA 平台显式报错 | 不支持 | 不适用 |
| **CTranslate2** | `STT/faster_whisper_handler.py:61-64` | 不支持（仅 CPU/CUDA）→ 非 CUDA 平台禁用该 backend | 同 | 同 |
| **自定义 attention kernel** | 无 | 无 | 无 | 无 |
| **卷积 codec（talker）** | Qwen3-TTS 的 speech tokenizer | torch 原生 | torch 原生（缺口待验） | 需 RKNN 算子覆盖 |
| **`torch.cuda.Event` 计时** | 4 处 | 可用 | **不存在** → DeviceOps | 不适用 |
| **NPU 专属算子缺口** | — | — | 未知 → 以 P2 逐 stage 实测为准 | — |

### 5.4 三平台推理引擎矩阵（最终形态）

| Stage | CUDA（现网） | AMD ROCm | 昇腾 CANN | RK3588 |
|---|---|---|---|---|
| **VAD** | Silero ONNX（CPU） | 同（CPU） | 同（CPU） | **Silero ONNX → RKNN** |
| **STT** | Qwen3-ASR-1.7B（transformers，eager） | 同（`torch.cuda` 透明） | torch_npu + transformers（eager） | RKNN 编码器 + RKLLM 解码器（W8A8） |
| **TTS** | `faster-qwen3-tts` torch 后端 | **ggml 后端优先**（RTF 攻坚） | `qwen-tts-hf` + torch_npu | **CPU-GGML 降级档** |
| **LLM** | llama.cpp（独立容器，OpenAI 兼容 HTTP） | llama.cpp ROCm/Vulkan | **vLLM-Ascend / MindIE HTTP，零代码** | `rk-llama.cpp`（第三方 fork） |

---

## 6. 性能与精度验证方案

### 6.1 前置缺口：精度基线不存在（必须先补）

现有 `acceptance-test-plan.md` 只验证**功能链路**（转写对不对、RTF、TTFA），**没有量化精度基线**。分级红线允许降级后，必须有"降级到什么程度算可接受"的判据，否则验收无从谈起。三平台并行尤其需要它——否则三份降级结果无法横向比较。

**P0 W1 必须交付的基线集**（在 CUDA 现网机器上采集，作为唯一参照）：

| 项 | 内容 |
|---|---|
| ASR 语料 | 中文测试集（AISHELL-1 test 或 WenetSpeech test 子集），≥200 条；另加含人名/时间/金额的实体集 ≥50 条 |
| ASR 指标 | **CER（字错率）**为主（中文），WER 为辅；分"普通句 / 实体句 / 长句(10s) / 噪声"四组 |
| TTS 语料 | 固定 20 条中文文本（含标点、多音字、数字、英文混排） |
| TTS 指标 | ① **音色一致性**：复用本仓 `voiceprint/` 的 speaker encoder（2048 维 embedding）算克隆音色 vs 预设音色的余弦相似度阈值；② **音质**：3 人主观 MOS 抽检；③ **客观**：输出时长偏差、能量/静音比、削波与爆音检测 |
| 性能基线 | 现网 CUDA 的 STT/TTS RTF、TTFA P50/P95、显存占用（已有 `performance-assumptions.md` §3/§5 口径） |

**降级容忍度（建议值，待评审确认）**

| 维度 | 容忍 | 备注 |
|---|---|---|
| CER 相对劣化 | ≤ +20%（分四组分别判定） | RK3588 因定点化+切分，容忍度需单独确认 |
| 音色相似度 | ≥ 0.75（与 CUDA 基线同口径） | CPU-GGML 档与 RK 档音色一致性可能显著低于基线 |
| MOS | ≥ CUDA 基线 − 0.5 | |
| RTF | < 1.0（硬红线，沿用） | **RK3588 例外**：明确标注为非实时档（§3.3.3） |
| TTFA P95 | ≤ 2.0 s（可用档，沿用 `performance-assumptions.md` §5） | **RK3588 例外**：同上 |

### 6.2 验收流程

复用 `acceptance-test-plan.md` 的 **T0–T9**，新增 **T10 平台一致性专项**、**T11 三平台横向对比**。

| 阶段 | 内容 | 平台差异 |
|---|---|---|
| T0 环境就绪 | 驱动/运行时/设备可见性/架构匹配 | ROCm: `rocm-smi` + `torch.version.hip`；昇腾: `npu-smi` + `torch.npu.is_available()`；RK: `/dev/mali0` + `rknn-toolkit-lite2` |
| T1 模型一致性 | **降级为"档位核对"**：full 档比指纹；degraded 档记录**档位标识**（模型 ID + 量化 + 格式 + 指纹 + 切分标识） | 分级红线生效点 |
| T2 功能链路 | 转写正确性 + **CER 对基线** + RTF + barge-in + 音色 | 新增 CER 与音色项 |
| T3 单路延迟 | ≥10 次采样，**真实 TTFA = Latency after speech end + min_silence_ms/1000** | 沿用；必须标注 `min_silence_ms` |
| T4 显存实测 | 三路采样（空闲 / 满并发 / LLM 加载后），偏差 ≤1.15 PASS / ≤1.30 WARN | ROCm 用 `torch.cuda.mem_get_info()`（`rocm-smi` 在 APU 上恒显 0%，不可用）；昇腾用 `npu-smi info -l`；RK 用 `/proc/meminfo` |
| T5 并发阶梯 | 1→3→5→10→20 阶梯，饱和点判定 | 沿用 |
| T6 本地 LLM | `llama-bench` / 昇腾服务 TTFT / `rk-llama.cpp` | 平台相关 |
| T7 远程 LLM | RTT、TTFT、断网 30 s 恢复 | 沿用；**昇腾 LLM 走这条**（vLLM-Ascend/MindIE） |
| T8 稳定性 | 2 h soak，显存漂移 <5%、TTFA 劣化 <20%、音质无劣化 | 沿用 |
| **T10（新增）** | **平台一致性专项**：能力矩阵快照 + 降级标注完整性（§4.5 四处全有）+ `--fidelity full` 拒绝行为 + 降级原因链与配置意图一致 | 每平台必跑 |
| **T11（新增）** | **三平台横向对比表**：同语料 CER / RTF / TTFA / 显存 / 能力矩阵摘要，一页汇总 | 三平台均完成后 |

### 6.3 文档修订（P0 必须同步完成）

| 文档 | 修订 | 时点 |
|---|---|---|
| `docs/hardware/acceptance-test-plan.md` §13 | "换个小模型就算通过 → 直接退货"改为**分级红线**：允许降级档，但必须标注并重跑 T1/T2/T3；仅当 full 档不可得且业务未显式接受时判 FAIL | P0 W1 |
| `docs/hardware/acceptance-test-plan.md` §14.1 | 基线指纹清单增加"降级档位标识"列 | P0 W1 |
| `docs/hardware/edge-box-feasibility.md` §1.1/§1.2 | G1 从硬门槛改为"full 档定义"，注明抽象层落地后需复核；昇腾/瑞芯微评估卡需按新算力档位重写 | P0 W1（初稿）/ P4（复核） |
| `docs/hardware/performance-assumptions.md` §7 | 新增平台假设项（HT5 ROCm TTS RTF、HT6 昇腾内存与并发口径、HT7 RK3588 档位与带宽） | P1/P2/P3 回填 |
| 新增 `docs/hardware/heterogeneous-acceptance.md` | 跨平台验收差异项（设备采样命令、精度指标、fidelity 断言、三平台对比表模板） | P0 W3 |

---

## 7. 实施路线

> 原则：**能力层地基先行冻结（3 周），三平台随后并行**。每个平台线有独立可验收的出口门槛，某线延期不阻塞其他线收口（除 P0 外）。

### 7.1 时间线（推荐配置：4 人 × 13 周）

```
周次    1  2  3  4  5  6  7  8  9 10 11 12 13
P0 地基  ███
  W1  精度/性能基线集 + 验收文档修订（分级红线）
  W2  L1 DeviceOps + L3 PlatformProfile
  W3  L2 Runtime 接口 + handler 迁移 + 能力矩阵 + 回归全绿
      ↑ P0 出口：CUDA e2e 逐项一致

        ┌────────── P1 AMD ROCm ──────────┐
W4-9    │ 镜像与 wheel 矩阵 → TTS RTF 攻坚 → 验收 T0-T10 │
        └──────────────────────────────────┘
        ┌──────────── P2 昇腾 CANN ─────────────┐
W4-11   │ torch_npu 拉起 → STT 验证 → TTS 路径 → LLM HTTP │
        └───────────────────────────────────────┘
        ┌──────────── P3 RK3588 ──────────────┐
W4-13   │ RKNN VAD → 模型切分 → RKLLM → rk-llama → TTS 降级 │
        └────────────────────────────────────┘
W10-13  P4 三平台验收（T10/T11）+ 文档回写 + CI matrix + 发布
```

### 7.2 阶段出口门槛

| 阶段 | 周期 | 出口门槛（不达标不进入下一阶段） | 交付物 |
|---|---|---|---|
| **P0 地基** | W1–W3 | ① 现有 170 个测试**全绿**；② CUDA 端到端 e2e 与改造前**逐项一致**（转写文本 diff = 0，TTFA/RTF 偏差 ≤5%）；③ 能力矩阵端点可返回 `full` 档；④ `--fidelity full` 在能力不足时正确拒绝启动；⑤ 精度基线集采集完成；⑥ `acceptance-test-plan.md` §13 与 `edge-box-feasibility.md` §1.1 已修订 | `platform/` 包（profiles / device_ops / runtimes / capabilities）、能力矩阵 API、多平台构建骨架、`heterogeneous-acceptance.md` |
| **P1 AMD ROCm** | W4–W9 | ① T0 PASS（`rocm-smi` + `torch.version.hip`）；② **T2：STT RTF < 1.0 且 TTS RTF < 1.0**；③ T3：修正后 TTFA P95 ≤ 2.0 s（可用档）；④ T4：显存偏差 ≤ 1.15；⑤ T5：阶梯达承诺档；⑥ T10：降级标注四处齐全 | ROCm 镜像、wheel 矩阵脚本、AMD 验收报告、实测值回写 `performance-assumptions.md` / `procurement-list.md` |
| **P2 昇腾 CANN** | W4–W11 | ① T0 PASS（`npu-smi` + `torch.npu.is_available()`）；② **STT 在 torch_npu 上跑通且有 RTF 数字**（full 档优先）；③ **TTS 有可用路径**（`qwen-tts-hf`+torch_npu 或 ggml 降级档）并出音正确；④ **LLM 走 vLLN-Ascend/MindIE HTTP 端到端打通**；⑤ ATC→OM 链评估结论；⑥ T10 通过 | 昇腾镜像、`ascend-migration.md`、torch_npu 适配记录、昇腾验收报告 |
| **P3 RK3588** | W4–W13 | ① Silero VAD ONNX→RKNN 跑通（有耗时数字 + 与 ONNX 输出比对）；② **Qwen3-ASR 模型切分脚本完成**，RKNN 编码器 + RKLLM 解码器跑通（有 tokens/s 数字）；③ `rk-llama.cpp` 容器跑通并接进 `chat-completions` backend；④ **TTS 有一可用降级档并出音正确**；⑤ 三端点全部可用；⑥ T10 通过（标注 degraded 原因链） | `Dockerfile.rk3588`、compose、模型切分脚本、`rk3588-migration.md`、RK 验收报告 |
| **P4 收口** | W10–W13 | ① T11 三平台横向对比表完成；② 全部文档回写完成且无双源漂移；③ CI matrix 含 cu128/cu130/rocm/npu/rk3588 五个已验证组合；④ 平台档案与能力矩阵文档化（`docs/platforms.md`） | 发布说明、CI 配置、平台矩阵文档、三平台对比表 |

### 7.3 人力配置

三平台全栈的工作量估算：**P0 ≈ 9 人周，P1 ≈ 8 人周，P2 ≈ 10 人周，P3 ≈ 12 人周，P4 ≈ 6 人周，合计 ≈ 45 人周（≈ 11 人月）**。

| 配置 | 人力 | 周期 | 说明 |
|---|---|---|---|
| **C（保守，原输入）** | 2–3 人 | **16–20 周** | RK3588 线压缩到"链路级最小可交付"，TTS 降级档可用性风险最高；P2/P3 串行化 |
| **B（推荐）** | **4 人** | **13 周** | P0 三人满编 3 周 → P1/P2/P3 各 1 人 + 1 人做 P0 收口/验收/文档；三平台真正并行 |
| **A（激进）** | 5–6 人 | 13 周 | 多 1–2 人做 RK3588 模型切分与昇腾算子调试的并行攻坚，降低单线延期风险；采购与文档需额外协调 |

**角色分工**

| 角色 | 人力 | 主责 | 峰值期 |
|---|---|---|---|
| **A. 平台运行时工程师** | 1.0 | P0 抽象层主体（DeviceOps / Runtime / Profile / 能力矩阵）、ROCm 镜像与 wheel 矩阵 | W1–W9 |
| **B. 推理优化 / 昇腾** | 1.0 | AMD TTS RTF 攻坚、昇腾 torch_npu 适配 + TTS 路径 | W4–W11 |
| **C. RK3588 端到端** | 1.0 | RKNN 转换链、Qwen3-ASR 模型切分、RKLLM / rk-llama.cpp 集成、TTS 降级档 | W4–W13 |
| **D. 测试 / 验收 / 文档** | 1.0（W1 起 0.5，W4 起 1.0） | 精度基线集、三平台验收执行、T10/T11、文档回写 | 全程 |

> **评审待确认**：本方案按配置 B（4 人 × 13 周）编排时间线。若维持原始 2–3 人输入，§7.1 时间线需按 16–20 周重排，且 RK3588 的 TTS 降级档成为最高风险项。**这一点需要在评审时明确选定**。

### 7.4 硬件与资源

| 项 | 需求 | 时点 | 备注 |
|---|---|---|---|
| **AMD 服务器** | MI300X / MI325X 级（**优先**），备选 Strix Halo 128 GB | **W1 前到货** | 见 §3.1.4 选型建议；采购需按 `procurement-list.md` 同一证据纪律核实 |
| **昇腾服务器** | 数据中心卡档位（910B / 950 一类） | **W1 启动采购，W4 前到货** | 昇腾采购周期可能 2–6 周，**是全案最长的采购关键路径**；型号规格待核实（§1.3.1） |
| **RK3588 板** | 16 GB（香橙派 5 Plus 16 GB / Firefly / MegaSpace） | W4 前到货 | 32 GB 版本是否在售需核实；另需 RK1828 算力棒（社区 151 tokens/s 实测所用）作为对照 |
| **主机软件** | ROCm 主机 Ubuntu 22.04/24.04 + amdgpu 驱动；CANN 官方镜像 + torch_npu；RKNN-Toolkit2（x86 交叉编译）+ RKLLM + RKLLM 工具链；`rk-llama.cpp` fork 源码 | 随硬件 | `rk-llama.cpp` 是第三方 fork，需自建镜像，**维护成本需计入** |
| **网络与镜像** | ROCm / CANN / RKNN / torch_npu wheel 需从官方源拉取，国内直连不稳 → **建内部 wheel 镜像缓存** | P0 W3 | 否则三线构建会同时卡在网络 |
| **构建机** | RKNN-Toolkit2 需在 x86 上交叉编译 `.rknn`；建议 CI 加一个"转换产物归档"步骤，避免每台板子重复转换 | P3 W5 | |

---

## 8. 风险登记册

| ID | 风险 | 概率 | 影响 | 触发信号 | 应对 | 责任人 |
|---|---|---|---|---|---|---|
| **R1** | **AMD 上 TTS RTF ≥ 1.0**（已有同权重实测 2.25–3.00，慢于实时） | **高** | **高** | P1 W7 末 RTF 仍 ≥ 1.0 | ① 切 ggml 后端（Q8_0/Q4_K_M）② 换 MI300X/MI325（官方 wheel + 高带宽）③ 量化 ④ 形态降级：AMD 只做 STT+LLM，TTS 走远程（`openai` backend 已存在）。<br>**W7 末为强制决策点** | B |
| **R2** | 昇腾算子缺口：`faster-qwen3-tts` CUDA 导向不可用；ATC 无 Qwen3-ASR/TTS 覆盖；torch_npu SDPA 行为差异 | 中高 | 高 | P2 W7 末 TTS 路径未定 | 主路径 `qwen-tts-hf` + torch_npu（eager）；备选 ggml/CPU；OM 仅评估。**LLM 侧零代码路径可独立交付**，即使 STT/TTS 受阻仍有可交付面 | B |
| **R3** | **RK3588 本地 TTS 无任何适配证据**，CPU-GGML 预计 RTF ≫ 1 | **高** | **高** | P3 W10 末仍无出音或 RTF > 5 | ① CPU-GGML + Q4_K_M 尽力跑通并**明确标注非实时档**；② 降级小号 TTS；③ 远程 TTS（此时标注"TTS stage 不由本机提供"，与全栈定义冲突，需评审裁定）。**验收标准按 §3.3.3 的"链路级全栈"** | C |
| **R4** | 构建矩阵爆炸（cu128/cu130/rocm/npu/rk3588 × 镜像 × wheel 索引 × compose） | **高** | 中 | 三线并行构建互相阻塞 | `ARG` 模板化；**每平台一个独立 compose**；CI matrix 只保留**已验证组合**，新增平台必须同时提交 CI 绿灯 | A |
| **R5** | 验收红线变更引发文档冲突（`acceptance-test-plan.md` §13 与 `edge-box-feasibility.md` §1.1 仍写"换小模型即退货"） | 中 | 中 | P1/P2/P3 验收时判据打架 | **P0 W1 同步修订两份文档**，作为 P0 出口门槛的一部分 | D |
| **R6** | `torch==2.11.0+cu128` 硬 pin 与 ROCm / torch_npu wheel 版本不匹配 | 中 | 中 | P1/P2 `uv sync` 解析失败 | `pyproject` 改 platform marker 条件 pin；lock 分平台维护；预演完整解析再上 CI | A |
| **R7** | ROCm 下 AOTriton SDPA 静默失效（不报错但结果错/慢） | 中 | 高 | P1 输出异常或异常慢 | DeviceOps 的 `sdpa_backend()` 做**平台白名单 + 可用性校验**；非 CUDA 平台默认 `eager` 作为安全档 | A |
| **R8** | 精度基线缺失导致"三份降级结果无法横向比较" | 中 | 高 | P1 T2 无法判定 | P0 W1 强制交付基线集（含 CER 分组口径与音色相似度阈值），**未完成则 P0 不出口** | D |
| **R9** | AMD 选型与既有采购文档结论不一致（既有文档推 Strix Halo，本方案推 MI300X 级） | 中 | 中 | P1 W1 选型评审 | P1 W1 独立复核：官方 wheel 覆盖 + 带宽 + 采购可得性 + 价格；结论回写 `procurement-list.md` | A |
| **R10** | **昇腾服务器采购周期（2–6 周）吃掉并行度** | **高** | 高 | W3 仍未下单/未到货 | **W1 第一件事就是下单**；若周期不可控，配置 B/C 下 P2 起始顺延，整体工期按采购到货日 + 11 周重算；P0/P1/P3 不受影响 | 项目负责人 |
| **R11** | RK3588 模型切分（Qwen3-ASR encoder/decoder）后 tokenizer/位置编码不对齐 | 中高 | 高 | P3 W7 末解码输出乱码 | 切分脚本必须带**数值等价校验**（同输入下 encoder 输出与原模型逐层比对）；复用本仓 `scripts/extract_speaker_encoder.py` 的切分+校验模式 | C |
| **R12** | `rk-llama.cpp` 是第三方 fork，版本/构建随上游漂移 | 中 | 中 | 构建失败或 API 变化 | 固定 commit 并在镜像中记录；优先评估是否可直接用 `ChatCompletionsLLMRuntime` 对接 HTTP 而非嵌入进程 | C |
| **R13** | 2–3 人配置下三线并行不可能，串行化吃掉全部缓冲 | 高 | 中 | 配置未在评审时确认 | **必须在评审时选定 §7.3 的配置档位**；若选配置 C，§7.1 时间线按 16–20 周重排并下调 RK3588 目标 | 项目负责人 |
| **R14** | 零 GPU 的 CI 无法验证加速路径，回归只能靠目标机自测 | 高 | 低 | — | CI 只跑平台无关测试（能力矩阵、配置解析、降级标注、Profile 探测）；加速路径靠 T0–T11 自测脚本 + 目标机回归 | A |
| **R15** | `Dockerfile.arm64` 被误认为"昇腾/RK 的 ARM 镜像"而被复用 | 低 | 中 | 评审提问 | 文档明确标注其用途为 NVIDIA Jetson Orin / DGX Spark 的 aarch64 CUDA 运行时；RK3588 另建 `Dockerfile.rk3588` | A |

---

## 9. 留给实现者的事项

以下留给实现者在实施阶段决定，本文档不做规定：

1. `platform/` 包的**具体模块划分与文件名**（本文只规定分层职责与接口签名）；
2. `PlatformProfile` 的**探测实现细节**（如 `rocm-smi` 输出解析的健壮性策略）；
3. ggml / ONNX / RKNN 转换脚本的**具体实现方式**；
4. Qwen3-ASR **模型切分的具体切点**（encoder/decoder 边界、哪些层留在 CPU）；
5. 精度基线集的**具体语料来源与标注工具**（只要口径满足 §6.1 的分组要求）；
6. 昇腾 910B/950 与 AMD MI300X 的**具体型号选型**（需按同一证据纪律单独检索核实）；
7. 能力矩阵在 `session.created` 中的**具体字段命名**（本文只规定必须包含的内容）；
8. CI matrix 的**具体编排工具与触发条件**；
9. RK3588 的 **TTS 降级档最终形态**（CPU-GGML / 小号 / 远程）——取决于 R3 的实测结果。

**必须由实现者遵守的硬约束**

- P0 阶段 CUDA 行为**零变化**（e2e 逐项一致是 P0 出口门槛）；
- 任何降级都必须落在 §4.5 的四处位置，缺一即为实现缺陷；
- `transformers` 版本不得在本方案外被升级（绑死 `5.18.0`，STT/TTS 无 vendored modeling 代码）；
- 不得引入 `flash-attn` / `xformers` / `deepspeed` 等 NVIDIA 专有依赖（会摧毁跨平台可行性）；
- 平台新增不得修改既有 handler 的业务逻辑（只允许通过 `DeviceOps` / `Runtime` 间接调整）；
- 三平台必须跑**同一套 API 契约**（`src/speech_to_speech/api/openai_realtime/`），平台差异只体现在 runtime 层。

---

## 10. 附：本方案与既有文档的关系

| 既有文档 | 关系 |
|---|---|
| `docs/hardware/edge-box-feasibility.md` | **被本方案部分修订**：G1 从硬门槛改为 full 档定义；昇腾/瑞芯微评估卡按新算力档位重写；§5.2/§5.3 短名单需在 P4 复核。P0 W1 先出初稿修订，P4 出终稿 |
| `docs/hardware/performance-assumptions.md` | **被本方案扩展**：新增平台假设项（HT5–HT7）；§3 的 4.6 GB/路 标注"仅 CUDA 实测，跨平台以 T4 实测替代" |
| `docs/hardware/acceptance-test-plan.md` | **被本方案修订**：§13 的一致性判定改为分级红线；新增 T10 平台一致性专项、T11 三平台横向对比 |
| `docs/model-combination-matrix-CN.md` | **被本方案扩展**：新增"平台 × 运行时"维度与降级档位列 |
| `docs/hardware/acceptance-test-plan.md` §14.1 指纹清单 | **被本方案扩展**：增加降级档位标识列 |

> **单源纪律**：所有显存/并发/延迟数值仍以 `performance-assumptions.md` 为唯一来源，本文档不复制数值规则，只引用。
