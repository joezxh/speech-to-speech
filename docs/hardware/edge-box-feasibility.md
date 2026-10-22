# 边缘与国产算力盒可行性评估（edge-box-feasibility）

> **检索日期：2026-10-22。** 本文档是 `docs/hardware/` 下**非 CUDA / 边缘盒子可行性结论的唯一来源**。
> 显存、并发、延迟的口径全部引用 [performance-assumptions.md](./performance-assumptions.md)（§3 显存基线、
> §4 并发公式、§5 延迟档位），本文只做"这台机器能不能跑"的判定，不复写数值规则。
> 商品编号与 [procurement-list.md](./procurement-list.md) 保持一致（DGX Spark 在该表编号为 `D-G08` / `D-G09`）。
>
> **本文档回答假设 HT3**：ARM 盒能否跑与本地一致的 Qwen3-ASR-1.7B（transformers）+ Qwen3-TTS-1.7B（torch）。

---

## §1 评估框架

### 1.1 一致性定义（先定"什么算跑通"）

现网 pipeline 的 STT/TTS 是**用 transformers 直接加载 safetensors 并前向推理**：

- STT：`--qwen3_asr_model_name /root/.cache/qwen3-asr-model-hf`，VAD 判定终段后**整段转写**；
- TTS：`--qwen3_tts_backend torch` + `--qwen3_tts_model_name /root/.cache/qwen3-tts-model`，句内流式。

因此"跑通"的判定标准只有一条：

> **必须能在该硬件上运行与原方案相同的 Qwen3-ASR-1.7B（transformers）+ Qwen3-TTS-1.7B（torch 或 ggml 后端），
> 且不修改 `src/` 下的推理代码。**

配套两条边界：

| 情形 | 判定 |
|---|---|
| 换成 whisper / paraformer / matcha / Piper | **不合格**——换模型家族，不是换硬件 |
| 换成 Qwen3-ASR-0.6B / Qwen3-TTS-0.6B | **有条件合格**——同家族小号，但必须重跑 T1/T2/T3，且文档显式标注"非 1.7B 一致配置" |

### 1.2 两条硬门槛（G1 / G2）

| 门槛 | 内容 | 后果 |
|---|---|---|
| **G1 运行时** | 必须能跑 **PyTorch + transformers 原样权重** | 需转 RKNN / RKLLM / OM(ATC) / OpenVINO IR / TensorRT engine / BPU `.hbm` 才能推理的盒子，**一律不合格**——pipeline 里没有对应后端，而计划禁止改 `src/` |
| **G2 内存** | 必须同时容纳 ASR-1.7B（FP16 ≈1.8 GB）+ TTS-1.7B（FP16 ≈3.4 GB）+ 运行时 + 音频缓冲，实测基线 **4.6 GB/路** | 内存 ≤8 GB 的盒子即使能跑，也只剩 0 路余量，且与 OS 争内存 |

> G1 是本文档最重要的过滤器。它把"显存看起来够、但必须转模型格式"的盒子一次性排除，
> 避免"凭显存数字推断可行"的经典错误。G2 进一步排除"格式能跑但内存装不下"的盒子。

### 1.3 置信分级（3 级）

| 等级 | 定义 | 使用条件 |
|---|---|---|
| **已证实** | 有直接实测证据：官方文档给出该模型在该硬件的运行说明，或社区公开可复现的实测（含日志/视频/推理速度） | 可直接进入短名单 |
| **待验证** | 工具链存在（能装 PyTorch / 能跑同家族模型），但**没有**该模型（1.7B）在該硬件的实测 | 只能小批量 PoC，且必须执行 §5.2 的专项验收 |
| **高风险** | 无任何证据，或存在反证（缺算子、内存不足、只支持定点格式、生态未覆盖） | 不进短名单 |
| 不适用 | 连 G1 或 G2 都不满足，无讨论价值 | 仅保留结论供日后复议 |

### 1.4 证据优先级（4 级）

**官方模型卡 > 芯片厂商模型库 > 社区实测 > 工具链推断（含营销材料、生成式博客）**

- 前两级可直接支撑"已证实"；
- 社区实测最多支撑"待验证"（除有完整复现步骤与速度数据）；
- **工具链推断不得支撑任何"已证实"**——本轮检索中出现的"昇腾 910B 适配 Qwen3-TTS 教程"
  全部是无仓库、无 issue、无实测的生成式文章，按此规则**不予采信**。

---

## §2 逐盒评估卡

### D-E01 Jetson Orin NX 16G

**硬件**

| 项 | 规格 |
|---|---|
| SoC / GPU | 1024 核 Ampere（32 Tensor Core）、8 核 Cortex-A78AE、2×NVDLA |
| 统一内存 | 16 GB LPDDR5 / **102 GB/s** |
| 存储 / 网口 | 需载板（NVMe + 千兆由载板提供） |
| 功耗 / 散热 | **15–40 W** 可配；需自配散热 |
| 形态 | 模组（需载板）或第三方整机 |

**推理栈**

- CUDA / TensorRT：✅ JetPack 6.x 自带，aarch64 PyTorch wheel 可用（这是本盒唯一的决定性优势）
- ONNX Runtime：✅（CPU EP 跑 VAD 无压力）
- llama.cpp：✅ CUDA 后端，需 **b8001+** 构建才支持 `qwen35` 架构
- OpenVINO / CANN / RKNN：✗ 不适用

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| Orin NX 16GB 可跑 **Qwen3-ASR-0.6B int4 + Qwen3-TTS CustomVoice int4**（TensorRT-Edge-LLM v0.9.1） | 社区实测（方案级，含镜像版本） | `wiki.seeedstudio.com/cn/solutions/conversational-voice-ai` | 2026-09-07 |
| JetPack 6.2.3 + CUDA 12.6 + PyTorch 2.8 在 Orin 系列跑通 `torch.cuda` | 社区实测（多篇） | NVIDIA 开发者论坛 / Jetson 社区 | 2026 年内 |
| Qwen3-ASR-1.7B / Qwen3-TTS-1.7B 在该 SoC 上的 transformers 实测 | **缺失** | — | — |

**置信度**：待验证——同家族 0.6B + int4 已证实；1.7B + FP16 + transformers 无实测，且 102 GB/s 带宽下 RTF 可能 >1。

**全栈本地可行性**

```
可用内存 ≈ 12 GB（JetPack + CUDA 运行时占 3–4 GB）
纯管线：floor(12 × 0.85 ÷ 4.6) = 2 路（槽位上限）
① 远程 LLM：合格——前提是 1.7B 双模型能跑通（待验证）
② 8B Q4：12 − 5.0 − 0.6 − 0.8 = 5.6 → 1 路（纸面装得下；102 GB/s 下 8B 解码约 15–20 tok/s，TTFA 必然超 2 s）
③ 9B Q4：12 − 5.7 − 0.7 − 0.8 = 4.8 → floor(0.89) = 0 路  ← 装不下
④ 4B Q4：12 − 2.6 − 0.4 − 0.8 = 8.2 → 1 路
⑤ 2B Q4：12 − 1.3 − 0.3 − 0.8 = 9.6 → 1 路
⑥ 0.8B Q4：12 − 0.6 − 0.2 − 0.8 = 10.4 → 1 路
```

**买前验证步骤**

1. 该 SKU 出厂是否预装 **JetPack 6.2+**？现场执行 `nvcc --version` 与 `python -c "import torch;print(torch.version.cuda)"`，输出是多少？
2. 是否为**原厂模组 + 第三方载板**？载板是否提供 NVMe、千兆网口、USB 音频输入？
3. 官方或社区是否有 **Qwen3-ASR-1.7B / Qwen3-TTS-1.7B 在该 SKU 上的 transformers 实测**？给出链接（不接受"显存够就能跑"的口述）。
4. 15 W 与 40 W 两档持续功耗下，长时间推理是否降频？散热方案是否随货提供？

**代表商品**：`D-E01`（procurement-list §4）

---

### D-E02 Jetson AGX Orin 64G

**硬件**

| 项 | 规格 |
|---|---|
| SoC / GPU | 2048 核 Ampere（64 Tensor Core）、12 核 Cortex-A78AE、2×NVDLA + PVA |
| 统一内存 | 64 GB LPDDR5 / **204.8 GB/s** |
| 存储 / 网口 | 需载板；开发者套件含 1 TB NVMe + 万兆 |
| 功耗 / 散热 | **15–60 W** 可配 |
| 形态 | 模组或开发者套件（两种形态报价差异大，见 procurement-list） |

**推理栈**：与 D-E01 同类（CUDA / TensorRT ✅，llama.cpp CUDA ✅，其余 ✗）

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| 同系列 Orin NX 已跑通同家族 0.6B ASR + TTS | 社区实测 | 同 D-E01 | 2026-09-07 |
| 64 GB / 204.8 GB/s 是边缘盒中唯一内存宽裕到能同时驻留两套 1.7B 且留多路余量的档位 | 规格推导 | NVIDIA Jetson 产品页 | 2026-10-22 |
| 1.7B 双模型的 AGX 实测 | **缺失** | — | — |
| Jetson 全系 2026-07-22 涨价：AGX Orin 开发者套件 **+75%**、64 GB 模组 **+88%**（绝对价格见 procurement-list） | 官方调价 | NVIDIA 经销商通知 / 媒体报道 | 2026-07-22 |

**置信度**：待验证——硬件条件在边缘盒中最优，但同样缺 1.7B 实测；且涨价后整机价已逼近桌面 4090 盒。

**全栈本地可行性**

```
可用内存 ≈ 60 GB（系统预留约 4 GB）
纯管线：floor(60 × 0.85 ÷ 4.6) = 11 路（槽位上限）
① 远程 LLM：合格（待 1.7B 实测）
② 8B Q4：60 − 5.0 − 0.6 − 0.8 = 53.6 → 9 路
③ 9B Q4：60 − 5.7 − 0.7 − 0.8 = 52.8 → 9 路
④ 4B Q4：60 − 2.6 − 0.4 − 0.8 = 56.2 → 10 路
⑤ 2B Q4 / ⑥ 0.8B Q4：10–11 路
```

**买前验证步骤**

1. 报价是**模组**还是**开发者套件**？载板/机箱/电源是否含？（这两种形态是两个不同的价格档，必须确认）
2. 64 GB 统一内存下，两套 1.7B FP16 权重（≈6.8 GB）+ 运行时是否稳定不 OOM？
3. 是否有 **Qwen3-TTS torch 后端**在该平台的实测（audio 质量、RTF）？给链接。
4. 60 W 档是否需要主动散热底座？持续满载是否降频到 40 W？

**代表商品**：`D-E02`（procurement-list §4）

---

### D-G08 / D-G09 DGX Spark 64G / 128G

**硬件**

| 项 | 规格 |
|---|---|
| SoC / GPU | GB10：20 核 ARM（10×Cortex-X925 + 10×Cortex-A725）+ Blackwell 48 SM / 6144 CUDA |
| 统一内存 | **64 GB 或 128 GB LPDDR5X / 256 bit / 273 GB/s**（模型可用 ≈56 / 120 GB） |
| 存储 / 网口 | 1–4 TB NVMe；ConnectX-7 @200 Gbps + 10 GbE + WiFi 7 |
| 功耗 / 散热 | 整机 **240 W**（GB10 TDP 140 W）；150×150×50.5 mm / 1.2 kg |
| 系统 | DGX OS（Ubuntu 24.04 **ARM64**），预装 PyTorch with CUDA |

**推理栈**

- CUDA：✅ 原生（Blackwell SM，aarch64）
- vLLM / Ollama / transformers：✅ 官方声明支持
- llama.cpp：⚠️ 需 aarch64 + CUDA 构建（本方案未验证）
- TensorRT / ONNX：✅ 可用
- OpenVINO / CANN / RKNN：✗

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| 128 GB 统一内存、273 GB/s、240 W、DGX OS 原生支持 PyTorch + CUDA + vLLM | 官方规格 | `nvidia.com/en-us/products/workstations/dgx-spark/` | 2026-10-22 |
| 64 GB 版由六大 OEM 供货（2026-10-23 上市）；128 GB FE 在 8 个月内**涨价约 74%**（绝对价格见 procurement-list） | 官方定价 + 媒体 | NVIDIA 官网 / 渠道报价 | 2026-10-22 |
| 本方案 x86_64 镜像与 `cache/` 在 ARM64 上不可直接复用 | 架构事实 | 本仓库 `Dockerfile` / `cache/` | 2026-10-22 |

**置信度**：待验证——运行时无障碍（G1 满足、G2 满足），但**273 GB/s 带宽**是它独有的瓶颈：槽位上限不等于可交付路数；ARM64 镜像需重建。

**全栈本地可行性**

```
D-G08（可用 120 GB）：纯管线 floor(120 × 0.85 ÷ 4.6) = 22 路（槽位上限）
  ② 8B Q4：120 − 5.0 − 0.6 − 0.8 = 113.6 → 20 路（槽位上限）
  ③ 9B Q4：120 − 5.7 − 0.7 − 0.8 = 112.8 → 20 路（槽位上限）
  ④ 4B Q4：120 − 2.6 − 0.4 − 0.8 = 116.2 → 21 路（槽位上限）
D-G09（可用 56 GB）：纯管线 10 路；② 8B 9 路；③ 9B 9 路；④ 4B 9 路（均为槽位上限）
```

> 273 GB/s 约为桌面 GDDR7（~1800 GB/s）的 1/6.6。20 路槽位对应的实际吞吐必须由 **T5 阶梯并发实测**给出，
> 在此之前只能按"待验证"处理，**不得把 20 路写进交付承诺**。

**买前验证步骤**

1. 该 SKU 是 **64 GB OEM 版**还是 **128 GB FE**？两者不是同一价格档，且 OEM 配置因厂商而异。
2. 能否安装 aarch64 版 CUDA 镜像与 aarch64 torch wheel？现网 `cache/` 是否需要重新下载？（预期：需要）
3. 有无 **Qwen3-ASR / Qwen3-TTS 在 ARM64 + CUDA 上的实测**？给链接。
4. 273 GB/s 带宽下，单路 STT+TTS 的 RTF 是多少？是否 ≤1？
5. 内存焊死不可扩——若后续需要更大模型，是否接受"再买一台"？

**代表商品**：`D-G08` / `D-G09`（procurement-list §3 主表，§4 有条目详情）

---

### D-E04 华为 Atlas 500 智能小站（310，型号 3000）

**硬件**

| 项 | 规格 |
|---|---|
| SoC | 昇腾 310，**22/16 TOPS INT8** |
| 内存 | **LPDDR4X 8 GB / 4 GB**，带宽 **51.2 GB/s** |
| 存储 / 网口 | 32/64 GB eMMC + microSD；2×GE |
| 功耗 / 散热 | 25 W（无盘）/ 40 W（有盘）；**无风扇** −40~70 ℃ |

**推理栈**

- CANN：✅（昇腾自有栈）
- PyTorch：⚠️ 需 `torch_npu`；模型需经 **ATC 转 OM**
- transformers 直跑：✗ 无官方路径
- llama.cpp / RKNN / OpenVINO：✗

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| 8 GB / 4 GB 内存、51.2 GB/s、310 算力单元 | 官方规格 | `hiascend.com/hardware`（Atlas 500 规格页） | 2026-10-22 |
| Qwen3-ASR / Qwen3-TTS 在该芯片的支持声明 | **缺失** | — | — |
| 昇腾侧公开证据全部集中在 LLM（vLLM-Ascend / MindIE 支持 Qwen3-8B），无 ASR/TTS 适配记录 | 生态观察 | 昇腾社区 / ModelZoo | 2026-10-22 |

**置信度**：不适用——G2 直接不合格（8 GB 装不下两套 1.7B），G1 需转 OM。

**全栈本地可行性**

```
可用内存 ≈ 5 GB（8 GB − OS/CANN 运行时 3 GB）
纯管线：floor(5 × 0.85 ÷ 4.6) = floor(0.92) = 0 路  ← 连一路都跑不了
②③④⑤⑥：无需计算——STT+TTS 已超出内存
```

**买前验证步骤**

1. 具体是 **310** 还是 **310P**？内存 **8 GB 还是 4 GB**？（型号 3000 与 A2 是两个东西，必须逐字确认）
2. 出厂是否含 **CANN ≥ 7.0 + torch_npu**？版本号？
3. 官方支持模型清单里**有没有语音识别 / 语音合成**条目？给链接（不接受销售口述）。
4. 若坚持使用，Qwen3-ASR/TTS 的算子适配需多少人日、由谁承担？

**代表商品**：不在 procurement-list 收录范围（判定不适用，无采购意义）

---

### D-E05 华为 Atlas 500 A2（310P，12 GB）

**硬件**

| 项 | 规格 |
|---|---|
| SoC | 昇腾 310P，20 TOPS INT8 |
| 内存 | **12 GB** |
| 功耗 | 约 40 W 级 |
| 形态 | 无风扇工控盒 |

**推理栈**：同 D-E04（CANN + `torch_npu`，模型需 OM 转换）

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| 12 GB 内存、20 TOPS INT8 | 官方规格 | 昇腾社区硬件页 | 2026-10-22 |
| Qwen3-ASR / Qwen3-TTS 的算子适配与实测 | **缺失** | — | — |
| 检索到的"昇腾 910B 适配 Qwen3-TTS 教程"均为无仓库的生成式文章 | 反证（工具链推断） | CSDN 类站点 | 2026-10-22 |

**置信度**：高风险——内存勉强够 1 路，但缺算子适配证据；`torch_npu` 对 transformers 自定义 attention 的覆盖未知。

**全栈本地可行性**

```
可用内存 ≈ 9 GB（12 − OS/CANN 运行时 3）
纯管线：floor(9 × 0.85 ÷ 4.6) = floor(1.66) = 1 路
② 8B Q4：9 − 5.0 − 0.6 − 0.8 = 2.6 → floor(0.48) = 0 路
③ 9B Q4：9 − 5.7 − 0.7 − 0.8 = 1.8 → 0 路
④ 4B Q4：9 − 2.6 − 0.4 − 0.8 = 5.2 → floor(0.96) = 0 路
```

**买前验证步骤**

1. 是否含 **CANN ≥ 7.0 + torch_npu**？`torch_npu` 与 PyTorch 版本如何对应？
2. 官方模型库中是否有**语音识别 / 语音合成**条目？给链接。
3. `transformers` 的 `generate` 与自定义 attention 在 `torch_npu` 上是否可用？未支持算子如何回退？
4. 供货与保修由谁承担（华为直供 / 代理 / 二手）？

**代表商品**：不在 procurement-list 收录范围（判定高风险，不进短名单）

---

### D-E06 RK3588 推理盒（香橙派 5 Plus / Firefly / MegaSpace）

**硬件**

| 项 | 规格 |
|---|---|
| SoC | RK3588：4×A76 + 4×A55、Mali-G610 |
| NPU | **6 TOPS**（INT8） |
| 内存 | 最高 32 GB LPDDR4X/5 / **51.2 GB/s** |
| 功耗 / 散热 | 5–20 W；被动散热即可 |
| 代表商品 | 香橙派 5 Plus 16 GB（板卡形态）；工业整机由定昌 / Firefly 等提供 |

**推理栈**

- RKNN：✅ 但**必须**把模型转成 `.rknn`（定点）
- RKLLM：✅ 只能跑 LLM，且需转 `.rkllm`
- llama.cpp 官方后端表：**没有 RKNN**；RK 平台走第三方 `rk-llama.cpp`（invisiofficial 分支）
- PyTorch + transformers 直跑：✗（CPU 上可跑，但 RTF 远大于 1，无实用价值）

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| **RK3588 / RK3576 可跑 Qwen3-ASR**：RKNN 编码器 + RKLLM 解码器，W8A8 | 社区实测（方案级） | `wiki.seeedstudio.com/cn/solutions/conversational-voice-ai` | 2026-09-07 |
| Qwen3-ASR 在 RK3588 + RK1828 算力棒上 **48 tokens / 316.94 ms ≈ 151 tokens/s** | 厂商实测 | 定昌 DC_M588 方案实测文 | 2026 年内 |
| Qwen3.5-2B 在 8 GB RK3588 板跑通（RKNPU2 backend，Q8_0） | 社区实测 | 掘金实战文 | 2026-09-18 |
| Qwen3-TTS 在 RK 平台的适配 | **缺失** | — | — |

**置信度**：高风险（**改代码才可行**）——G1 不合格，必须转 RKNN/RKLLM；且 Qwen3-TTS 无任何 RK 适配证据。

**全栈本地可行性**

```
可用内存 ≈ 28 GB（32 GB − OS 约 4 GB）
纯管线（纸面）：floor(28 × 0.85 ÷ 4.6) = floor(5.17) = 5 路
② 8B Q4：28 − 5.0 − 0.6 − 0.8 = 21.6 → floor(3.99) = 3 路
③ 9B Q4：28 − 5.7 − 0.7 − 0.8 = 20.8 → floor(3.84) = 3 路
④ 4B Q4：28 − 2.6 − 0.4 − 0.8 = 24.2 → floor(4.47) = 4 路
```

> 上述路数全部是**纸面值**：51.2 GB/s 带宽 + 6 TOPS NPU 下，转格式后尚不可行，不转格式则跑不动。
> 唯一可用形态是 ⑤ 2B（rk-llama.cpp 社区已跑通），**作为纯 LLM 盒、不含 STT/TTS**。

**买前验证步骤**

1. 固件里 `rk-llama.cpp` 的分支与提交号是多少？能否自行升级？
2. 内存是 **LPDDR4X 还是 LPDDR5**？32 GB 版本是否真的在售（多数渠道只有 8/16 GB）？价格与交期？
3. 是否接受 **Qwen3-ASR 需转 RKNN + RKLLM**、**Qwen3-TTS 无适配方案**这两个前提？
4. 若只用它的 NPU 跑 LLM（⑤2B），STT/TTS 另配 GPU 盒——这套混合架构是否被业务接受？

**代表商品**：不在 procurement-list 收录范围（判定高风险；仅 ⑤2B 有社区实测）

---

### D-E07 寒武纪 MLU370-X4

**硬件**

| 项 | 规格 |
|---|---|
| 加速器 | MLU370-X4，256 TOPS INT8 |
| 显存 | **24 GB LPDDR5 / 307.2 GB/s** |
| 功耗 / 散热 | **150 W，单槽全长、被动散热** |
| 形态 | PCIe 卡（**不是盒子**，需自配主机 + 风道） |

**推理栈**

- `torch_mlu`：✅ 存在，可加载 PyTorch 模型
- transformers：⚠️ 依赖 `torch_mlu` 对 `generate` / 自定义 attention 的算子覆盖
- llama.cpp：✗ 无官方 MLU 后端
- CANN / OpenVINO / RKNN：✗

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| 24 GB / 307.2 GB/s / 150 W 被动散热 | 官方规格 | `cambricon.com` 产品页 | 2026-10-22 |
| 官方仅把"语音处理"列为应用领域，**无具体模型清单** | 缺失 | 同上 | 2026-10-22 |
| Qwen3-ASR / Qwen3-TTS 的落地案例 | **缺失** | — | — |

**置信度**：高风险——`torch_mlu` 提供栈，但 ASR/TTS 算子覆盖无证据；被动散热需服务器风道。

**全栈本地可行性**

```
可用显存 24 GB
纯管线：floor(24 × 0.85 ÷ 4.6) = floor(4.43) = 4 路
② 8B Q4：24 − 5.0 − 0.6 − 0.8 = 17.6 → floor(3.25) = 3 路
③ 9B Q4：24 − 5.7 − 0.7 − 0.8 = 16.8 → floor(3.10) = 3 路
④ 4B Q4：24 − 2.6 − 0.4 − 0.8 = 20.2 → floor(3.73) = 3 路
```

**买前验证步骤**

1. 是 **X4（24 GB / 150 W）** 还是 **X8（48 GB / 250 W）**？被动散热如何解决风道？
2. `torch_mlu` 与 PyTorch 版本如何对应？是否支持 transformers 的 `generate` 与自定义 attention？
3. 是否有**语音模型（ASR/TTS）**的落地案例？给链接。
4. 供货与保修由谁承担（寒武纪直供 / 代理 / 二手）？

**代表商品**：不在 procurement-list 收录范围（判定高风险，不进短名单）

---

### D-E08 Intel Core Ultra 9 285H 迷你主机

**硬件**

| 项 | 规格 |
|---|---|
| CPU | 16 核（6P + 8E + 2 LPE），**x86_64** |
| iGPU / NPU | Arc 核显 + **NPU 99 TOPS** |
| 内存 | SO-DIMM 可扩（32 / 64 / 96 GB），iGPU 共享显存 |
| 功耗 | 65–120 W |
| 代表商品 | 铭凡 / 极摩客等准系统；32 GB + 1 TB 整机在售 |

**推理栈**

- PyTorch（CPU）：✅ **x86_64 可直接跑原样权重**，G1 无问题
- IPEX（Intel Extension for PyTorch）：✅ 有 XPU 后端，可直接跑原样权重而不转 IR
- OpenVINO：⚠️ llama.cpp 的 OpenVINO 后端在官方表标注 **In Progress**，且**单设备槽、不支持动态形状**
- llama.cpp：✅ CPU 后端可用；OpenVINO 后端待验证
- CANN / RKNN：✗

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| NPU 99 TOPS、SO-DIMM 可扩、x86_64 | 官方规格 | `intel.com` Core Ultra 200H 系列 | 2026-10-22 |
| llama.cpp 官方后端表：OpenVINO → Intel CPU/GPU/NPU 标注 **In Progress** | 工具链状态 | `github.com/ggml-org/llama.cpp` `docs/backend/` | 2026-10-22 |
| Qwen3-ASR / Qwen3-TTS 在该平台的实测（RTF、audio 质量） | **缺失** | — | — |

**置信度**：待验证（**速度存疑**）——G1 通过（x86 CPU 直跑），但 CPU/NPU 上跑 1.7B 双模型的 RTF 大概率 >1。

**全栈本地可行性**

```
按内存 32 GB、iGPU 分配 16 GB 估算
纯管线：floor(16 × 0.85 ÷ 4.6) = 2 路
① 远程 LLM：合格（若 RTF 可接受）
② 8B Q4：16 − 5.0 − 0.6 − 0.8 = 9.6 → 1 路（CPU 解码极慢，不实用）
③ 9B Q4：16 − 5.7 − 0.7 − 0.8 = 8.8 → 1 路（同上）
④ 4B Q4：16 − 2.6 − 0.4 − 0.8 = 12.2 → 2 路（同上）
⑤ 2B Q4：16 − 1.3 − 0.3 − 0.8 = 13.6 → 2 路（llama.cpp OpenVINO 后端可试）
⑥ 0.8B Q4：16 − 0.6 − 0.2 − 0.8 = 14.4 → 2 路
```

**买前验证步骤**

1. 该 SKU 内存是 **SO-DIMM 可换**还是板载？能否扩到 64 GB 以上？
2. **Linux 下 NPU / iGPU 驱动是否可用**？（Windows 可用 ≠ Linux 可用）
3. OpenVINO 版本？是否支持 **PyTorch 前端直接跑**（不经 IR 转换）？IPEX-XPU 是否可用？
4. 有无 **Qwen3-ASR / Qwen3-TTS 在该平台的 RTF 实测**？给链接。

**代表商品**：未进 procurement-list 主表（未达"可采购"门槛）；若后续实测通过，按 `D-E08` 补录

---

### D-E09 AMD Ryzen AI Max+ 395 迷你主机

**硬件**

| 项 | 规格 |
|---|---|
| CPU / GPU | 16 核 Zen 5 + Radeon 8060S（40 CU） |
| 统一内存 | **128 GB / 256 bit**，可分配约 96 GB 作显存 |
| 存储 / 功耗 | 标配 2 TB；**120–140 W** |
| 形态 / 系统 | 迷你主机；**x86_64 + ROCm** |
| 代表商品 | 极摩客 EVO-X2 / 零刻 GTR9 Pro / 铭凡 MS-S1 MAX（`D-E09`） |

**推理栈**

- PyTorch（CPU）：✅ x86_64 直跑原样权重
- ROCm：✅ HIP 后端在 llama.cpp 官方表中；PyTorch ROCm wheel 可用
- LocalAI：✅ 兼容表把 **Qwen3-TTS 列在 ROCm** 支持列表
- OpenVINO / CANN / RKNN：✗

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| 128 GB 统一内存、可分配 96 GB、x86_64 | 官方规格 | `amd.com` Ryzen AI Max+ 395 | 2026-10-22 |
| **LocalAI 兼容表：Qwen3-TTS 支持 CPU / CUDA 12-13 / ROCm / Intel SYCL / Metal / Jetson L4T** | 框架支持矩阵 | `localai.io/docs/model-compatibility` | 2026-07-30 |
| llama.cpp 官方后端表含 **HIP → AMD ROCm** | 工具链状态 | `github.com/ggml-org/llama.cpp` `docs/backend/` | 2026-10-22 |
| Qwen3-ASR-1.7B 在该平台的 transformers 实测（RTF） | **缺失** | — | — |

**置信度**：待验证——三条独立线索都指向"可行"，但**没有一条是实测**；ROCm 对 transformers 自定义 attention 的覆盖是唯一不确定点。

**全栈本地可行性**

```
按可分配 96 GB 计
纯管线：floor(96 × 0.85 ÷ 4.6) = floor(17.74) = 17 路（槽位上限）
① 远程 LLM：合格
② 8B Q4：96 − 5.0 − 0.6 − 0.8 = 89.6 → floor(16.55) = 16 路（槽位上限）
③ 9B Q4：96 − 5.7 − 0.7 − 0.8 = 88.8 → floor(16.41) = 16 路（槽位上限）
④ 4B Q4：96 − 2.6 − 0.4 − 0.8 = 92.2 → floor(17.03) = 17 路（槽位上限）
⑤ 2B Q4：96 − 1.3 − 0.3 − 0.8 = 93.6 → 17 路
⑥ 0.8B Q4：96 − 0.6 − 0.2 − 0.8 = 94.4 → 17 路
```

> 带宽未公开标注（LPDDR5X 256 bit），实际吞吐必须由 T5 实测给出；
> **4.6 GB/路是 CUDA 实测值，跨到 ROCm 不可直接外推**——这是本卡最大的方法论风险。

**买前验证步骤**

1. 128 GB 统一内存**焊死不可扩**——是否接受"扩容 = 再买一台"？
2. `rocm-smi` 是否识别 GPU？PyTorch ROCm wheel 版本与 ROCm 驱动如何对应？
3. 有无 **Qwen3-ASR-1.7B / Qwen3-TTS-1.7B 在该平台的 transformers 实测**（RTF、audio 质量）？给链接。
4. iGPU 可分配显存如何设置（BIOS / 驱动）？96 GB 是不是稳定上限？

**代表商品**：`D-E09`（procurement-list §4）

---

### D-E10 地平线 / 地瓜 RDK X5

**硬件**

| 项 | 规格 |
|---|---|
| SoC | 8 核 Cortex-A55 |
| BPU | **10 TOPS**；GPU 仅 32 GFLOPS |
| 内存 | **4 GB / 8 GB LPDDR4** |
| 功耗 | **约 3 W** |

**推理栈**

- BPU：只吃 **`.hbm` 定点模型**（需地平线工具链转换）
- PyTorch / transformers：✗（CPU 上理论可跑，但 8 GB + A55 无实用价值）
- llama.cpp / RKNN / OpenVINO / CANN：✗

**证据链**

| 结论 | 证据类型 | 来源 | 日期 |
|---|---|---|---|
| 10 TOPS BPU、4/8 GB、约 3 W | 官方规格 | `developer.d-robotics.cc` / 微雪商品页 | 2026-10-22 |
| Qwen3-ASR / Qwen3-TTS 的 BPU 适配 | **缺失** | — | — |

**置信度**：不适用——G1（需转 `.hbm`）与 G2（8 GB）双不合格。

**全栈本地可行性**

```
可用内存 ≈ 6 GB（8 GB − OS 2 GB）
纯管线：floor(6 × 0.85 ÷ 4.6) = floor(1.11) = 1 路（纸面，且需转 .hbm）
②③④⑤⑥：无需计算——4/8 GB 与 3 W 功耗撑不住任何 LLM + 管线组合
```

**买前验证步骤**

1. 是否支持 **PyTorch / ONNX 直接推理**（不转 `.hbm`）？——预期答案是否，用于核实。
2. BPU 工具链版本与支持算子清单？
3. 8 GB 版本能否同时驻留 ASR + TTS？（预期不能）

**代表商品**：不在 procurement-list 收录范围（判定不适用）

---

## §3 支持矩阵汇总表

取值：`已证实` / `待验证` / `高风险` / `不适用`

| 盒子 | VAD（Silero ONNX） | STT（Qwen3-ASR） | TTS（Qwen3-TTS） | ① 远程 LLM | ⑤ 2B | ⑥ 0.8B |
|---|---|---|---|---|---|---|
| **D-E01** Orin NX 16G | 已证实 | 待验证 | 待验证 | 已证实 | 已证实 | 已证实 |
| **D-E02** AGX Orin 64G | 已证实 | 待验证 | 待验证 | 已证实 | 已证实 | 已证实 |
| **D-G08/G09** DGX Spark | 已证实 | 待验证 | 待验证 | 已证实 | 待验证 | 待验证 |
| **D-E04** Atlas 500 (310) | 高风险 | 不适用 | 不适用 | 已证实 | 高风险 | 高风险 |
| **D-E05** Atlas 500 A2 (310P) | 高风险 | 高风险 | 高风险 | 已证实 | 高风险 | 高风险 |
| **D-E06** RK3588 | 高风险 | 高风险 | 不适用 | 已证实 | 已证实 | 待验证 |
| **D-E07** MLU370-X4 | 高风险 | 高风险 | 高风险 | 已证实 | 高风险 | 高风险 |
| **D-E08** Ultra 9 285H | 已证实 | 待验证 | 待验证 | 已证实 | 已证实 | 已证实 |
| **D-E09** Ryzen AI Max+ 395 | 已证实 | 待验证 | 待验证 | 已证实 | 待验证 | 待验证 |
| **D-E10** RDK X5 | 高风险 | 不适用 | 不适用 | 已证实 | 不适用 | 高风险 |

> **总述**：本次评估的 10 款盒子中，"全栈本地（VAD + STT + TTS 同机）"达到 **已证实 / 待验证** 的只有
> **5 款**（D-E01、D-E02、D-G08/G09、D-E08、D-E09），且**没有一款是"已证实"**——全部缺 Qwen3-ASR/TTS-1.7B 的实测。
> 其余 5 款为高风险或不适用。**HT3 无法解除，只能转为"待验证 + PoC 实测"**。
>
> 另一条必须传播的事实：**边缘盒的算力密度远低于同价桌面卡**。D-E04 / D-E06 / D-E10 的有效推理能力
> 都低于一张二手 RTX 3060 12G，差别只在功耗与形态——这条决定了"边缘盒不是省钱方案，是省电/省空间方案"。

---

## §4 买前验证清单（汇总可打印版）

> 用法：截图或打印本节，逐条向店铺/代理确认，或自行查官方文档。
> 任何一条回答不了，按"待验证"处理，**不得按"可行"下单**。

### 通用（所有盒子，4 条）

- [ ] 出厂系统与内核版本？`uname -a` 与 `cat /etc/os-release` 输出？
- [ ] 能否安装 **PyTorch + transformers** 并加载 safetensors？给出版本组合。
- [ ] 官方支持模型清单中是否出现 **Qwen3-ASR / Qwen3-TTS**？给链接。
- [ ] 是否有人在该硬件跑通 **1.7B + FP16 + transformers**？给出 issue/论坛链接与速度数据。

### D-E01 / D-E02（Jetson Orin）

- [ ] JetPack 版本是否 ≥ 6.2？`nvcc --version` 与 `torch.version.cuda`？
- [ ] 是原厂模组 + 第三方载板吗？载板是否提供 NVMe、千兆网口、USB 音频？
- [ ] 15 W / 40 W（NX）与 60 W（AGX）持续功耗下是否降频？散热方案随货吗？
- [ ] 报价是模组还是整机/开发者套件？

### D-G08 / D-G09（DGX Spark）

- [ ] 是 64 GB OEM 版还是 128 GB FE？OEM 厂商与配置？
- [ ] aarch64 镜像与 aarch64 torch wheel 是否可获取？`cache/` 是否需重新下载？
- [ ] 273 GB/s 下单路 STT+TTS 的 RTF 实测值？
- [ ] 内存是否焊死？后续扩容方案？

### D-E04 / D-E05（Atlas 500）

- [ ] 具体是 **310** 还是 **310P**？内存 **8 / 4 / 12 GB**？
- [ ] 是否含 **CANN ≥ 7.0 + torch_npu**？版本号？
- [ ] 官方模型清单有语音识别 / 语音合成条目吗？给链接（不接受销售口述）。
- [ ] 未支持算子的处理方式（Ascend C 重写人日）？

### D-E06（RK3588）

- [ ] `rk-llama.cpp` 的分支与提交号？能否自行升级？
- [ ] LPDDR4X 还是 LPDDR5？32 GB 版本是否在售？
- [ ] 接受 Qwen3-ASR 转 RKNN + RKLLM 的前提吗？转换脚本谁提供？
- [ ] Qwen3-TTS 有 RK 适配方案吗？（预期：无）

### D-E07（寒武纪 MLU370）

- [ ] X4（24 GB / 150 W）还是 X8（48 GB / 250 W）？被动散热风道如何解决？
- [ ] `torch_mlu` 与 PyTorch 版本对应关系？支持 `generate` 与自定义 attention 吗？
- [ ] 有语音模型落地案例吗？给链接。
- [ ] 供货与保修由谁承担？

### D-E08 / D-E09（Intel / AMD 迷你主机）

- [ ] 内存是 SO-DIMM 可换还是板载焊死？
- [ ] Linux 下 NPU / iGPU / ROCm 驱动是否可用？（Windows 可用 ≠ Linux 可用）
- [ ] D-E08：OpenVINO 版本、能否 PyTorch 前端直跑？D-E09：ROCm 版本、`rocm-smi` 是否识别？
- [ ] 有 Qwen3-TTS 在该平台的实测（RTF、audio 质量）吗？

### D-E10（RDK X5）

- [ ] 支持 PyTorch / ONNX 直接推理（不转 `.hbm`）吗？——预期答案是否，用于核实。
- [ ] BPU 工具链版本与支持算子清单？
- [ ] 8 GB 版能同时驻留 ASR + TTS 吗？（预期不能）

---

## §5 结论：采购短名单

### 5.1 可进短名单（已证实）

**无。** 本次评估中没有任何一款盒子达到"已证实"——原因是**全部缺 Qwen3-ASR-1.7B / Qwen3-TTS-1.7B
（transformers + FP16）在该硬件的实测**。唯一有实测的 Seeed 方案用的是 **0.6B + int4 + TensorRT engine**，
按 §1.1 属"有条件合格"的降级配置，不能作为 1.7B 一致方案的证据。

> 这不是"边缘盒不可行"，而是"没人验证过"。在 `src/` 不可改的约束下，
> 唯一能立刻拿到"已证实"的方式是**自己买一台跑 T1/T2/T3**。

### 5.2 可小批量 PoC（待验证）

按"验证价值 / 成本"排序，建议**先买 1 台，跑通再谈批量**：

| 优先 | 条目 | 理由 | 必做专项验收 |
|---|---|---|---|
| **P0** | `D-E01` Jetson Orin NX 16G | 最便宜的一致栈 PoC；CUDA 生态完整；15–40 W | **T1**（模型指纹）+ **T2**（音频质量）+ **T3**（TTFA/RTF）；额外验证 102 GB/s 下 RTF 是否 ≤1 |
| **P1** | `D-E09` Ryzen AI Max+ 395 | x86_64 无需重建镜像；128 GB 统一内存；LocalAI 明确列 Qwen3-TTS/ROCm | T1/T2/T3 + **T6**（ROCm 下 9B 解码速度）；重点验 ROCm 对自定义 attention 的覆盖 |
| **P2** | `D-G08` DGX Spark 128G | 唯一"一台机器同时是 LLM 盒 + 管线盒"的形态；可承载 27B 级 | T1/T2/T3 + **T5**（阶梯并发，273 GB/s 的真实上限）+ arm64 镜像构建 |
| **P3** | `D-E02` AGX Orin 64G | 内存最宽裕的边缘盒；但涨价后已逼近桌面 4090 盒 | 同 P0，重点验 60 W 持续功耗 |

> 四条目的具体报价与套餐组合见 [procurement-list.md](./procurement-list.md) §4 / §5（套餐 D）。

**PoC 的判定线**（任一不达标即该路线否决）：

1. **T1**：模型指纹（权重 SHA256 / 参数规模）与本地一致，或**显式接受 0.6B 降级**并在文档标注；
2. **T2**：中文音频转写 WER 与 TTS MOS 抽检不低于本机基线；
3. **T3**：单路 TTFA P95 ≤ 2.0 s（见 [performance-assumptions.md](./performance-assumptions.md) §5）；
4. **T4**：`num_pipelines=1` 显存 ≤ 该盒可用内存的 85%；
5. 若 RTF 实测 >1（不实时），该路线整体否决，转 `D-G04` / `D-G05`。

### 5.3 不进短名单

| 条目 | 判定 | 排除理由 |
|---|---|---|
| `D-E04` Atlas 500（310） | 不适用 | 8 GB / 4 GB 内存装不下两套 1.7B（纯管线纸面 0 路）；G1 需转 OM |
| `D-E05` Atlas 500 A2（310P） | 高风险 | 12 GB 仅够 1 路；Qwen3-ASR/TTS 算子适配无任何证据；"昇腾适配教程"为生成式内容，不可采信 |
| `D-E06` RK3588 盒 | 高风险 | G1 不合格（必须转 RKNN/RKLLM）；Qwen3-TTS 无 RK 适配；51.2 GB/s 带宽是硬短板。**仅 ⑤2B 可作纯 LLM 盒**（rk-llama.cpp 社区实测） |
| `D-E07` MLU370-X4 | 高风险 | 官方无语音模型清单；`torch_mlu` 对自定义 attention 覆盖未知；被动散热需服务器风道 |
| `D-E08` Ultra 9 285H | 待验证但**不推荐** | G1 通过（x86 CPU 直跑），但 CPU/NPU 跑 1.7B 双模型 RTF 大概率 >1；仅作"低功耗 x86 备选"记录 |
| `D-E10` RDK X5 | 不适用 | BPU 只吃 `.hbm`；8 GB + 3 W 双不合格 |

### 5.4 与采购清单的对应关系

- 进入 §5.2 的四个条目中，`D-E01` / `D-E02` / `D-E09` 已在 [procurement-list.md](./procurement-list.md) §3 主表与 §5 套餐 D 中收录；
  `D-G08` / `D-G09` 收录为主表条目（PoC 定位）。
- 采购口径遵循用户决策：**"判为待验证、保留短名单，先买 1 台样机实测，承担试错成本"**——
  因此本文档不写"边缘盒不可行"，而写"无人验证，需自证"。
- 若 PoC 全部失败，回退路径是 [procurement-list.md](./procurement-list.md) §5 套餐 A/B/C 的 x86 + NVIDIA 路线，
  该路线的显存与并发口径已由 [performance-assumptions.md](./performance-assumptions.md) §4 覆盖。
