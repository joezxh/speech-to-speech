# Speech-to-Speech 算力盒子选型（增量完善）设计文档

> 日期：2026-10-22 ｜ 状态：待评审
> 工作目录：`speech-to-speech-src/docs/hardware/`
> 前置成果：`README.md` + `plan-1~4` + `deployment-multibox.md`（2026-10 版，已提交到工作区未跟踪目录）
> 本文档是对既有选型体系的**增量完善**，不推倒重写。

## 1. 背景与目标

本地已用 `docker-compose.local.yml` 跑通 VAD→STT→LLM→TTS 实时语音链路（基线机
RTX 5070 Ti Laptop 12GB）。`docs/hardware/` 已有一版 4 方案选型文档，但存在三个缺口：

1. **可采购性不足**：只有 1688/淘宝检索式链接，无具体在售商品条目（店铺、实价、SKU、保修）；
2. **边缘/国产算力盒覆盖薄弱**：Jetson 一句带过，昇腾 Atlas、RK3588、OpenVINO 迷你主机、
   寒武纪、DGX Spark 等未评估；
3. **性能假设不显式**：并发路数/延迟估算缺完整假设条件链，且未把 `num_pipelines`
   每路 ≈4.6GB 显存的硬约束纳入推导；
4. **缺买回后的验收手段**：候选盒到货后没有统一的实测流程与判定线，无法客观得出
   "通过 / 降级使用 / 退货" 结论（本次评审追加项）。

本次目标：新增 4 份专题文档（假设表、采购清单、边缘盒可行性、实测验收）+ 2 份小模型
方案文档，刷新存量 6 份文档，把方案体系扩展为
**6 个 LLM 接入方案**（远程 / Qwen3-8B / Qwen3.5-9B / Qwen3.5-4B / Qwen3.5-2B / Qwen3.5-0.8B），
形成可直接用于采购评估的候选设备清单。

## 2. 当前流水线基线（事实来源：`docs/model-pipeline.md`、`docker-compose.local.yml`、`nvidia-smi` 实测）

| 环节 | 模型与版本 | 推理框架/运行方式 | 占用 | 流式能力 |
|---|---|---|---|---|
| VAD | Silero VAD v5（`--vad silero`，Smart Turn v3.2 ONNX 已挂载但 `--no_smart_turn` 关闭） | ONNX / CPU | ~30MB 内存 | 实时逐帧；`min_silence_ms=700` 判停 |
| STT | **Qwen3-ASR-1.7B**（`/root/.cache/qwen3-asr-model-hf`） | transformers / CUDA，FP16，`language=auto` | ~1.8GB（量化 0.6–1.0GB） | 非流式：VAD 终段后整段转写 |
| LLM | Qwen3-8B @ GPUStack（`http://192.168.40.30/v1-openai`） | OpenAI 兼容 chat-completions，远程 HTTP，流式，`enable_thinking=false`，`stream_batch_sentences=1` | 0（本机） | 流式逐句下发 TTS |
| TTS | **Qwen3-TTS-12Hz-1.7B-CustomVoice**（`/root/.cache/qwen3-tts-model`，speaker=Aiden） | torch backend / CUDA（备选 ggml 后端 CPU 量化） | ~3.4GB（INT8 ~2GB） | 句内流式，`streaming_chunk_size=4` |
| 管线合计 | — | Docker 镜像 `speech-to-speech-pipeline:latest` | **实测 ≈4.6GB/路**（`nvidia-smi`，2026-10-22） | — |
| 服务接口 | OpenAI-Realtime WebSocket `:8765/v1/realtime`；输入 16kHz PCM 单声道，输出 24kHz PCM | uvicorn 单实例 | — | — |
| 并发约束 | `num_pipelines=1`（当前），每加一路 = 整套 handler ≈4.6GB | — | 12GB 卡单路受限 | — |

**假设与待验证项**（不得静默替换模型）：

- HT1：Qwen3.5-2B / Qwen3.5-0.8B 的 GGUF（Q4_K_M/Q8_0）权重在 HF/ModelScope 可用 —— 联网核实项；
  若不存在，回退候选：Qwen3-1.7B / Qwen3-0.6B，并在文档显式标注替代原因。
- HT2：Qwen3.5 系列在 llama.cpp 的架构支持状态（新架构可能需要较新分支）—— 联网核实项。
- HT3：ARM 盒（Jetson/RK3588 等）上 transformers 版 Qwen3-ASR / Qwen3-TTS（torch/CUDA）
  能否直接运行 —— 逐盒证据链评估，结论分级，不预设可行。
- HT4：所有电商价格为 2026-10-22 检索快照，正文标注"下单前复核"。

## 3. 关键决策（评审已确认）

| 决策 | 结论 |
|---|---|
| 组织方式 | 方案 A：新增专题文档 + 存量轻引用，禁止双源复制数据 |
| 商品验证深度 | WebSearch/WebFetch 联网检索验证；逐条标注检索日期与来源；不强制浏览器实查 |
| 边缘盒评估标准 | **模型一致硬约束**：候选盒必须能跑与本地一致的 Qwen3-ASR-1.7B + Qwen3-TTS-1.7B；跑 whisper/paraformer 替代不算合格，只能标"需替换模型，不满足一致性" |
| 边缘盒深度 | 证据链（官方支持列表/社区实测/工具链状态）+ 置信度三级（已证实/待验证/高风险）+ 买前验证步骤清单 |
| 方案体系 | 6 方案：①远程 ②8B ③9B ④4B ⑤Qwen3.5-2B ⑥Qwen3.5-0.8B（⑤⑥独立成案，各自一文件） |
| 到货验收 | 新增 `acceptance-test-plan.md`：T0~T9 十阶段流程 + 三档判定线（通过/有条件通过/退货），判定阈值一律引用假设表，不另设口径 |

## 4. 文件结构与职责边界

```
docs/hardware/
├── README.md                      # 刷新：总入口 + 6 方案索引 + 新文档链接 + 显存基线（唯一来源）
├── performance-assumptions.md     # 新增：并发/延迟假设条件表（唯一来源）
├── procurement-list.md            # 新增：可采购商品清单（6 方案 × 维度快选矩阵 + 条目详情）
├── edge-box-feasibility.md        # 新增：边缘/国产算力盒可行性（证据链 + 验证步骤）
├── plan-1-remote-llm.md           # 轻刷：并发段落改引假设表；商品表压缩为 D-xx 引用
├── plan-2-qwen3-8b.md             # 同上
├── plan-3-qwen3.5-9b.md           # 同上
├── plan-4-qwen3.5-4b.md           # 同上
├── plan-5-qwen3.5-2b.md           # 新增：结构对齐 plan-2~4
├── plan-6-qwen3.5-0.8b.md         # 新增：结构对齐 plan-2~4
├── acceptance-test-plan.md        # 新增：到货实测验收方案（T0~T9 + 判定规则 + 报告模板）
├── deployment-multibox.md         # 微改：加一行指向假设表，并被验收方案引用压测命令
├── docker-compose.llm-box.yml     # 不动
└── docker-compose.pipeline-box.yml# 不动
```

| 信息类型 | 唯一归属 | 其他文档 |
|---|---|---|
| 显存/占用基线（含 4.6GB/路实测） | README | 只引用 |
| 性能假设条件 | performance-assumptions.md | 只引用 |
| 电商商品/价格 | procurement-list.md | plan-N 只写 D-xx 引用 |
| 边缘/国产盒结论 | edge-box-feasibility.md | plan-N 只写结论 + 链接 |
| 验收判定阈值 | performance-assumptions.md | acceptance-test-plan.md 只引用不复制数值 |
| 部署步骤/compose | 既有文档 | 不动 |

## 5. 六方案体系与假设数值

### 5.1 方案总览（README 索引表扩展）

| 方案 | LLM | 定位 | 单盒最低显存（FP16 管线 + Q4 LLM） |
|---|---|---|---|
| ① 远程 | GPUStack Qwen3-8B | 现状、最省、上线最快 | 8GB（推荐 12–16GB） |
| ② Qwen3-8B | 本地 GGUF | 质量/成本均衡 | 16GB（Q4 紧）/ 24GB（Q8） |
| ③ Qwen3.5-9B | 本地 GGUF | 质量最高、最吃显存 | 24GB（Q4）/ 32GB+（Q8/FP16） |
| ④ Qwen3.5-4B | 本地 GGUF | 并发高、延迟低 | 12GB（Q4） |
| ⑤ Qwen3.5-2B | 本地 GGUF | 边缘全栈主力、32K 上下文 | 8GB（Q4） |
| ⑥ Qwen3.5-0.8B | 本地 GGUF | 成本极限、边缘全栈下限 | 8GB（FP16 亦可行） |

### 5.2 performance-assumptions.md 假设取值（唯一来源）

**音频与交互**：输入 16kHz/PCM16/单声道；输出 24kHz PCM；单轮语音时长典型 3s、P95 ≤10s；
句末静音 700ms 判停（`min_silence_ms`）；半双工 + VAD 打断（barge-in）；STT 非流式（VAD 终段
整段转写）；TTS 句内流式（chunk_size=4）；LLM 逐句流式下发（`stream_batch_sentences=1`）。

**LLM token 规模**：输入 300–800（系统提示 + ≤30 轮历史），输出 20–80（语音短回复）。

**远程 LLM 网络**：内网 RTT 10–80ms；GPUStack 排队 +0–300ms 区间标注。

**量化基线**（LLM 权重显存，Q4_K_M / Q8_0 / FP16）：

| 模型 | Q4 | Q8 | FP16 | KV（32K, q8） |
|---|---|---|---|---|
| Qwen3-8B | ~5.0GB | ~8.5GB | ~16GB | 小上下文 ~0.6GB |
| Qwen3.5-9B | ~5.7GB | ~9.8GB | ~18GB | 同上 |
| Qwen3.5-4B | ~2.6GB | ~4.5GB | ~8GB | ~0.4GB（8K） |
| Qwen3.5-2B | ~1.3GB | ~2.2GB | ~4.0GB | ~0.5GB（32K） |
| Qwen3.5-0.8B | ~0.6GB | ~0.9GB | ~1.6GB | ~0.3GB（32K） |

**并发推导规则**：

- 档位：1 / 3 / 5 / 10 / 20 路，逐档给 TTFA P50/P95 与饱和判定；
- 硬约束①（槽位显存）：单盒最大 `num_pipelines` = ⌊可用显存 × 0.85 ÷ 4.6GB⌋（同机含 LLM 时先扣
  LLM 权重 + KV）；
- 硬约束②（管线吞吐）：STT/TTS 计算吞吐上限（12GB 档 ≈20–40 路，README 口径），
  两约束取小者；
- 多盒时并发上限由 LLM 盒吞吐决定（llama.cpp `-np` + 各模型 tok/s），管线盒可横向堆叠；
- 目标延迟两档：**舒适 TTFA ≤1s / 可用 TTFA ≤2s**（TTFA = 说完 → 首音频帧）。

**质量提示**（附录）：2B/0.8B 在工具调用、多轮指代、中文长句上明显弱于 8B/9B；⑤⑥定位为
"边缘全栈 / 成本极限"，需 prompt 限长 + few-shot 兜底，非质量优先场景。

## 6. procurement-list.md 结构

```
1. 使用说明（价格时效声明、检索日期、置信标注规则）
2. 快选矩阵：6 方案 × 4 维度（性价比 / 低延迟 / 高并发 / 备选）→ 每格一个 D-xx 条目编号
3. 候选商品主表（每条目一行）+ 条目详情小节
4. 按方案①~⑥分组的明细引用
5. 多盒组合套餐（1×LLM 盒 + N×管线盒整包建议，含总价与路数）
```

**条目字段**：编号（D-01…）｜品牌/型号/SKU｜检索来源（搜索链接 + 核实到的商品页链接 +
检索日期 2026-10-22）｜CPU/GPU/显存/内存/存储/网口/扩展/功耗/散热｜推理栈（CUDA 版本、
能否直接复用 `speech-to-speech-pipeline:latest`）｜可承载方案（①~⑥多选）｜单盒并发路数
（按 §5.2 推导）｜TTFA 预估｜价格（区间 + 已核实实价分开标注）｜风险（涡轮/二手/矿卡/
保修/供货/散热）｜替代条目编号。

**检索范围**：GPU 整机与显卡（4060 Ti 16G / 5060 Ti 16G / 5070 12G / 5070 Ti 16G / 4090 24G /
5090 32G / L20 48G / 5880 Ada 等）、迷你工作站（DGX Spark、5090 迷你主机）、边缘盒品牌
（映泰/研华/正基 Apinc/LattePanda/升腾/华为 Atlas/香橙派/Orange Pi/Radxa/Rongals/MegaSpace/
寒武纪/地平线）。ARM 盒的**可行性结论**只在 edge-box-feasibility.md 给出，本清单条目引用其结论。

## 7. edge-box-feasibility.md 结构

```
1. 评估框架（一致性定义、置信度三级、证据类型优先级：官方模型卡 > 芯片厂商模型库 >
   社区实测 > 工具链推断）
2. 逐盒评估卡
3. 汇总表：盒子 × {VAD / STT / TTS / 远程LLM / ⑤2B / ⑥0.8B} 支持矩阵
4. 买前验证清单（每款 3–6 条可执行确认点：店铺咨询问题、官方文档核对项、社区 issue 检索词）
5. 结论：可进采购短名单的盒子
```

**评估卡模板**：硬件（SoC/GPU-NPU/统一内存/存储/网口/功耗）｜推理栈（CUDA/TensorRT/ONNX/
OpenVINO/CANN/llama.cpp 后端/MLC/RKNN 支持状态）｜证据链（四条证据类型逐条列，附链接与日期）｜
置信度（已证实/待验证/高风险）｜全栈本地可行性（方案①与⑤⑥分别评估；②③④默认排除并说明显存理由）｜
买前验证步骤。

**覆盖品类**：Jetson Orin NX 16G、Jetson AGX Orin 32/64G、DGX Spark（GB10 128G）、昇腾
Atlas 500 Pro / 800I A2、RK3588 16–32G 推理盒（香橙派 5 Plus / Rongals / MegaSpace 等）、
寒武纪 MLU370-X4/X8、Intel Core Ultra 迷你主机（OpenVINO 路线，铭凡/Beelink GTR 等）、
地平线 RDK。检索中若发现更合适的在售品类可增补，删减需在文档记录原因。

## 8. acceptance-test-plan.md 结构（到货实测验收）

**定位**：任一候选盒采购到货后，按此流程执行即得出结构性结论；所有延迟/并发/显存判定线
引用 performance-assumptions.md，本文档不复制数值（避免双源）。不依赖任何新增被测代码，
工具只用现有 `latency_test.py` + shell 并行压测 + 厂商监控（`nvidia-smi` / `jetson-stats` /
`npu-smi`）。

**十个阶段**：

| 阶段 | 内容 | 取证 |
|---|---|---|
| T0 环境就绪 | x86：CUDA 版本与镜像匹配、Docker GPU 直通可见；ARM：aarch64 镜像构建通过；模型 cache 挂载成功 | 版本与设备列表快照 |
| T1 模型一致性 | cache 文件 sha256 对齐基线机清单；启动无降级日志；启动参数与 `docker-compose.local.yml` 逐项 diff | 校验值 + diff 结果 |
| T2 功能链路 | 单路跑通；中文音频转写正确性人工核对；音色/语种正常；barge-in 打断可用；记录 STT RTF 与 TTS RTF | 转写文本 + RTF 值 |
| T3 单路延迟基线 | TTFA P50/P95 对照假设表双档；四个时间戳（VAD 判停、STT 出字、LLM 首 token、TTS 首帧）逐段归因 | 延迟时间线 |
| T4 显存实测 | 三路采样：单路常驻 / `num_pipelines` 打满 / 本地 LLM 加载后；与 procurement-list 该条目承诺值对比 | 显存曲线 + 偏差百分比 |
| T5 并发阶梯 | 1→3→5→10→20 路并行压测（命令沿用 deployment-multibox.md）；每档记录 P50/P95 TTFA、报错率、GPU 利用率/温度 | 饱和点 = P95 超目标档或出 `SERVER ERROR` |
| T6 本地 LLM 专项（②~⑥） | llama.cpp 单流 tok/s、`-np` 批量吞吐、KV 显存实测；判定该盒“可承载方案”是否成立 | 吞吐表 |
| T7 远程 LLM 专项（①） | 到 GPUStack 的 RTT/TTFT 实测、断网重连、超时兜底文案验证 | 网络样本 |
| T8 稳定性 | 2h 连续对话 soak：显存泄漏曲线、热降频、音质劣化抽检 | soak 报告 |
| T9 验收报告 | 固定模板：环境快照 / 逐项 PASS・FAIL・WARN / 与采购条目承诺值对照表 / 结论与整改项 | `acceptance-report-<型号>-<日期>.md` |

**三档判定规则**：

| 结论 | 条件 |
|---|---|
| **通过** | T0–T5 全 PASS，且该条目承诺并发档实测达成 |
| **有条件通过**（降级使用） | T4 偏差 15–30%，或 T5 达成档位比承诺低一档；记录实际容量上限并写回 procurement-list |
| **退货 / 替换** | T1 不一致（模型被替或跑不起来）、T2 RTF≥1（跟不上实时）、T3 单路就超 2s |

**边缘盒挂钩**：edge-box-feasibility.md 中结论为“待验证”的盒子，验收时强制执行 T1/T2 的
ARM 一致性专项（torch/transformers wheel 安装、FP16 推理 RTF）；失败即触发“需替换模型 =
不满足一致性”退货条款。

**附录**：测试用 wav 样本要求（16kHz 单声道、典型 3s / P95 10s 各若干条）、并行压测一行命令、
验收报告模板。

## 9. 存量文档刷新点（最小改动）

1. `README.md`：方案索引扩为 6 行；新增 4 文档 + plan-5/6 链接；"电商平台检索入口"小节改为
   指向 procurement-list.md；保留显存基线与实测表（唯一来源）。
2. `plan-1~4.md`：并发/TTFA 段落改为"按 performance-assumptions.md §5.2 推导"并保留结论数值；
   "商品检索"表压缩为 D-xx 引用行；尾部加一行"到货验收见 acceptance-test-plan.md"。
3. 新增 `plan-5-qwen3.5-2b.md`、`plan-6-qwen3.5-0.8b.md`：小节结构对齐 plan-2~4
   （概述/显存分配/商品检索/并发与性能/多盒拆分/部署建议）；显式列出 HT1/HT2 假设项。
4. `deployment-multibox.md`：文首加一行"并发与延迟估算统一引用 performance-assumptions.md，
   压测命令被 acceptance-test-plan.md T5 沿用"。

## 10. 执行顺序与检索批次

1. 写 `performance-assumptions.md`（不依赖外部检索）；
2. 联网检索批次一：Qwen3.5-2B/0.8B GGUF 权重与 llama.cpp 支持（解除 HT1/HT2）；
3. 联网检索批次二：GPU 整机/显卡在售商品与价格（填充 procurement-list GPU 部分）；
4. 联网检索批次三：边缘/国产盒证据链（模型支持、社区实测、工具链）；
5. 写 `procurement-list.md`、`edge-box-feasibility.md`；
6. 写 plan-5/6；写 `acceptance-test-plan.md`（不依赖检索，仅依赖假设表与现有工具）；
7. 刷新 README、plan-1~4、deployment-multibox；
8. 按 §11 验收标准自检。

## 11. 验收标准

- [ ] 用户任务书 6 项输出要求逐条可指认到文档位置（映射表见附录 A）；
- [ ] 每个价格/链接带检索日期；无证据处显式标注"待验证"；
- [ ] 所有并发/延迟数字可回溯到 performance-assumptions.md 推导，无裸估值；
- [ ] 快选矩阵 6 方案 × 4 维度无空格（无合适条目时写"暂无 + 建议"）；
- [ ] 与 README 实测基线（4.6GB/路）无口径冲突；
- [ ] 边缘盒结论均带置信度分级与买前验证步骤；
- [ ] 验收方案 T0~T9 完整，判定规则三档可执行且阈值均指向假设表（无自建数值）；
- [ ] 双源检查：商品数据只出现在 procurement-list.md，假设与阈值只在假设表出现。

### 附录 A：任务书要求 → 文档位置映射

| 任务书条款 | 落点 |
|---|---|
| 1. 本地基线确认与假设项 | 本 spec §2；README；performance-assumptions |
| 2. 六方案分组 | plan-1~6；README 索引 |
| 3. 候选盒 12 项字段 | procurement-list 条目字段（§6） |
| 4. 并发假设条件 | performance-assumptions（§5.2） |
| 5. 方案对比表分组维度 | procurement-list 快选矩阵 + README 索引 |
| 6. 优先级/场景/成本/复杂度/风险 | procurement-list 条目 + plan-N"部署建议/风险"小节 |
| 追加项：到货实测验收 | acceptance-test-plan.md（本 spec §8） |

## 12. 范围外（YAGNI）

- 不含浏览器实查下单验证（用户已选联网检索深度）；
- 不修改任何运行时代码与 compose 模板逻辑；
- 不评估 x86 纯 CPU 服务器（无 GPU/NPU，STT/TTS RTF 不达标）与 AMD GPU（ROCm 上
  transformers Qwen3-TTS 无现成证据链，若检索发现反例再补）；
- 不实际执行验收（本次只交付验收方案文档，执行需等硬件到货）；不新增任何压测代码，
  沿用 `latency_test.py` 与 shell 并行包装；
- 不涉及 cloud API 定价对比（远程 LLM 按现网 GPUStack 内网假设）。
