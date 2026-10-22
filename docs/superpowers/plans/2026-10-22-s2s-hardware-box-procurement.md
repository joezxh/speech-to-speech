# Speech-to-Speech 算力盒子选型文档 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `speech-to-speech-src/docs/hardware/` 下增量产出 4 份专题文档（性能假设表、可采购商品清单、边缘/国产盒可行性、到货实测验收）+ 2 份小模型方案（Qwen3.5-2B / 0.8B），并刷新存量 6 份文档，使 6 个 LLM 接入方案的选型结论可采购、可验证、可部署。

**Architecture:** 单一事实来源分层——`performance-assumptions.md` 承载全部估算假设与推导规则，`README.md` 承载显存/占用基线，`procurement-list.md` 独占电商商品与价格数据，`edge-box-feasibility.md` 独占非 CUDA 盒子可行性结论；`plan-1~6.md` 只做方案视角的引用与结论汇总，禁止复制数值（防双源漂移）。所有商品与证据条目必须带检索日期与来源链接。

**Tech Stack:** Markdown 文档 + Docker Compose（既有 `docker-compose.local.yml` / `llm-box` / `pipeline-box`）+ Hugging Face GGUF 权重 + llama.cpp + transformers（Qwen3-ASR / Qwen3-TTS）+ WebSearch/WebFetch 联网检索 + Git 原子提交。

**Spec 来源:** `docs/superpowers/specs/2026-10-22-s2s-hardware-box-procurement-design.md`（commit `f1dd6cf`）

---

## 约定（所有任务通用）

- 工作目录：`d:\work\qwen-audio-agent\speech-to-speech-src`（下文相对路径均以此为根）。
- 每个任务结束**立即提交**，提交信息用中文，格式 `docs(hardware): <做了什么>`。
- 文档语言：中文（正文、表格头、注释），模型名/框架名/参数名保留英文原文。
- 禁止改动：`src/`、任何 `docker-compose*.yml` 的实际服务定义（本计划纯文档）。
- 检索日期统一写 **2026-10-22**；每个外部结论标注 `（检索日期 2026-10-22，来源：<URL>）`。
- 一致性检查脚本统一用 `rg`（ripgrep，项目已可用）；若本机无 `rg`，改用 `Select-String`。

**验证用的通用口径检查（Task 13 汇总执行）：**

```powershell
# 1) 假设数值不得散落在非权威文件（应只在 performance-assumptions.md 与 README 出现）
rg -n "4\.6\s*GB|4633 MiB" docs/hardware --glob '!README.md' --glob '!performance-assumptions.md'
# 2) 商品与价格只在 procurement-list.md 出现
rg -n "¥[0-9,]+" docs/hardware --glob '!procurement-list.md' --glob '!README.md' --glob '!plan-*.md'
# 3) 无占位符
rg -n "TBD|TODO|待补充|fill in" docs/hardware
```

---

## 阶段 0：基线事实固化（不产出文档，只提取输入）

### Task 0.0：把存量 `docs/hardware/` 纳入版本控制

> 当前 `docs/hardware/` 整体为 git **untracked** 状态，若不先提交，Task 10~12 的
> `git add <文件>` 会把"旧文档首次入库"与"本次修改"混在一个 commit 里，无法审阅。

**Files:**
- Add: `docs/hardware/README.md`、`plan-1-remote-llm.md`、`plan-2-qwen3-8b.md`、
  `plan-3-qwen3.5-9b.md`、`plan-4-qwen3.5-4b.md`、`deployment-multibox.md`、
  `docker-compose.llm-box.yml`、`docker-compose.pipeline-box.yml`

- [ ] **Step 1: 确认待提交文件清单（不含任何临时/日志文件）**

```powershell
git status --porcelain docs/hardware
```
Expected: 仅上述 8 个文件；若出现 `.log`、`.tmp`、草稿类文件，不要加入（确认后可归入本地忽略）。

- [ ] **Step 2: 全量提交存量选型文档作为基线**

```powershell
git add docs/hardware/README.md docs/hardware/plan-1-remote-llm.md docs/hardware/plan-2-qwen3-8b.md `
       docs/hardware/plan-3-qwen3.5-9b.md docs/hardware/plan-4-qwen3.5-4b.md `
       docs/hardware/deployment-multibox.md docs/hardware/docker-compose.llm-box.yml `
       docs/hardware/docker-compose.pipeline-box.yml
git commit -m "docs(hardware): 将2026-10版四方案选型文档纳入版本控制（本次增量完善的基线）"
git log --oneline -1
```
Expected: 新增 1 个 commit，8 个文件首次入库；`git status docs/hardware` 干净。

- [ ] **Step 3: 验证可回退**

```powershell
git diff HEAD~1 --stat
```
Expected: 只列出 `docs/hardware/` 下 8 个新增文件，无其他路径。

### Task 0.1：抽取当前流水线事实与模型清单

**Files:**
- Read: `docker-compose.local.yml`
- Read: `.env.local`
- Read: `docs/model-pipeline.md`（§2 参数速查表）
- Read: `src/speech_to_speech/arguments_classes/vad_arguments.py`、`stt_arguments.py`（或 `qwen3_asr_stt_arguments.py`）、`tts_arguments.py`（或 `qwen3_tts_arguments.py`）、`module_arguments.py`
- Create: `docs/hardware/.baseline-facts.md`（工作草稿，Task 0.3 后删除，不提交）

- [ ] **Step 1: 读取 compose 与 env，确认 VAD/STT/LLM/TTS 四段实际参数**

运行：
```powershell
Select-String -Path docker-compose.local.yml -Pattern "^\s*-\s+--" | ForEach-Object { $_.Line.Trim() }
Get-Content .env.local
```
Expected: 得到 `--vad`、`--min_silence_ms`、`--stt`、`--qwen3_asr_model_name`、`--llm_backend`、`--model_name`、`--responses_api_base_url`、`--tts`、`--qwen3_tts_model_name`、`--qwen3_tts_backend`、`--qwen3_tts_device`、`--num_pipelines` 等标志的实际取值。

- [ ] **Step 2: 从 arguments_classes 抄出每项默认值，标注"现网覆盖值 vs 库默认值"**

打开对应 `*_arguments.py`，对 Step 1 得到的每个标志记录：默认值、类型、现网是否覆盖。重点确认 `sample_rate`、`min_silence_ms`、`qwen3_tts_streaming_chunk_size`、`qwen3_asr_gen_max_new_tokens`、`chat_size`、`num_pipelines`。

- [ ] **Step 3: 计算模型 cache 的 sha256 指纹（供验收 T1 使用）**

运行：
```powershell
Get-ChildItem -Recurse cache | Where-Object { -not $_.PSIsContainer -and $_.Length -gt 1MB } |
  ForEach-Object { "{0}`t{1}`t{2}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Length, $_.FullName.Replace((Get-Location).Path + '\', '') } |
  Tee-Object docs/hardware/.baseline-facts.md
```
Expected: 得到 `qwen3-asr-model-hf`、`qwen3-tts-model`、`smart-turn-v3.2-cpu.onnx`、`qwen35-4b`（若存在 GGUF）等文件的 SHA256 + 字节数清单，写入草稿文件。

- [ ] **Step 4: 把 Step 1~3 结果整理成草稿表，写入 `.baseline-facts.md`**

草稿必须含三块表格：① 四段流水线参数表（标志/现网值/库默认）；② 模型文件指纹表；③ 显存实测表（从 `docs/hardware/README.md` §"本机实测" 直接抄：12227 MiB 总量、≈4633 MiB 占用、≈7312 MiB 空闲，日期 2026-10-22）。

- [ ] **Step 5: 校验草稿与 spec 无冲突**

运行：
```powershell
Select-String -Path docs/hardware/.baseline-facts.md -Pattern "qwen3|silero|num_pipelines|4633"
```
Expected: 至少命中 Qwen3-ASR、Qwen3-TTS、Silero、`num_pipelines=1`、4633 MiB 五项；若 compose 里的模型路径与 spec §2 表格不符，**以 compose 为准**并在草稿末尾记录差异（不要静默改 spec）。

> 本任务不提交（草稿文件不入库）。

---

## 阶段 1：假设表（后续所有估算的地基）

### Task 1：创建 `performance-assumptions.md`

**Files:**
- Create: `docs/hardware/performance-assumptions.md`
- Reference: `docs/hardware/.baseline-facts.md`（Task 0.1 草稿）

- [ ] **Step 1: 先写"检查条件"——本文档必须能回答的 9 个假设问题**

在文档顶部以列表写出任务书 §4 要求的 9 项：单轮语音时长/P95、VAD/STT/TTS 是否流式、是否要求打断/双工、采样率/声道/编码、LLM 输入输出 token、远程 LLM 网络延迟、本地 LLM 量化精度、目标端到端延迟、并发档位。后续每节对应回答一项。

- [ ] **Step 2: 写 §1「音频与交互假设」表**

内容（逐行填实，不得留空）：

| 假设项 | 取值 | 依据 |
|---|---|---|
| 输入采样率/编码/声道 | 16 kHz / PCM16 / 单声道 | `.baseline-facts.md` 参数表 `sample_rate` |
| 输出音频 | 24 kHz PCM（Qwen3-TTS 原生） | `TTS/qwen3_tts_handler.py` |
| 单轮用户语音时长 | 典型 3 s，P95 ≤ 10 s | 语音助手短对话场景（标注为**假设**，验收 T2 实测校准） |
| 判停方式 | 句末静音 700 ms（`min_silence_ms=700`），Smart Turn 关闭 | 现网 compose |
| 交互模式 | 半双工 + VAD 打断（barge-in），非全双工 | 现网链路 |
| VAD 流式 | 是（逐帧） | Silero 运行时特征 |
| STT 流式 | **否**——VAD 终段后整段转写 | 现网 `qwen3-asr` handler |
| TTS 流式 | 句内流式，`streaming_chunk_size=4` | 现网 compose |
| LLM 下发粒度 | 流式 + 逐句（`stream_batch_sentences=1`） | 现网 compose |

- [ ] **Step 3: 写 §2「LLM token 与网络假设」表**

| 假设项 | 取值 | 依据 |
|---|---|---|
| LLM 输入 token | 300–800（系统提示 + ≤30 轮历史） | `chat_size` 默认 30 + `voice_prompt.py` 拼装长度 |
| LLM 输出 token | 20–80（一两句口语） | `init_chat_prompt` 要求"very short" |
| 远程 LLM 网络 RTT | 内网 10–80 ms | 现网 GPUStack 同网段（标注为假设，验收 T7 实测） |
| 远程排队附加延迟 | 0–300 ms 区间 | GPUStack 负载不可控 |
| 思考链 | 关闭（`enable_thinking=false` / `reasoning_effort` 空） | 现网 compose |

- [ ] **Step 4: 写 §3「显存与量化基线」表（含 6 个 LLM 档 + 管线）**

管线部分照抄 `README.md` 实测：VAD ~0.03GB（CPU）、STT FP16 ~1.8GB（INT8 0.6–1.0GB）、TTS FP16 ~3.4GB（INT8 ~2GB）、**单路管线实测 ≈4.6GB**。
LLM 部分：

| 模型 | Q4_K_M | Q8_0 | FP16 | KV（8K, q8） | KV（32K, q8） |
|---|---|---|---|---|---|
| Qwen3-8B | ~5.0GB | ~8.5GB | ~16GB | ~0.6GB | ~2.4GB |
| Qwen3.5-9B | ~5.7GB | ~9.8GB | ~18GB | ~0.7GB | ~2.8GB |
| Qwen3.5-4B | ~2.6GB | ~4.5GB | ~8GB | ~0.4GB | ~1.6GB |
| Qwen3.5-2B | ~1.3GB | ~2.2GB | ~4.0GB | ~0.3GB | ~1.2GB |
| Qwen3.5-0.8B | ~0.6GB | ~0.9GB | ~1.6GB | ~0.2GB | ~0.8GB |

并注明权重显存换算规则：`Q4≈0.55GB/B、Q8≈1.1GB/B、FP16≈2.0GB/B`（沿用 README 口径），以及"以上为推导值，验收 T4/T6 实测替换"。

- [ ] **Step 5: 写 §4「并发推导规则」（本次新增的关键修正）**

必须写成可套算的公式 + worked example：

```
单盒最大路数 = min( 槽位约束, 吞吐约束 )
槽位约束   = floor( 可用显存GB × 0.85 ÷ 4.6 )        # 每路独占整套 VAD+STT+TTS handler
               （同机含 LLM 时：可用显存 = 标称显存 − LLM权重 − KV − 0.5~1GB 上下文余量）
吞吐约束   = STT/TTS 计算吞吐上限（12GB 档 ≈20–40 路，README 口径）
```

Worked example（写进文档）：RTX 5070 12GB + Qwen3.5-4B Q4 → 可用 = 12 − 2.6 − 0.4 − 0.8 = 8.2GB → 槽位 = floor(8.2×0.85/4.6) = **1 路**；结论：**同机跑 LLM 时，12GB 卡无法做多路**，多路必须走"多盒拆分"或纯管线盒。此结论要显式点出，因为它推翻了只看吞吐的乐观估算。

- [ ] **Step 6: 写 §5「延迟目标与档位」**

档位 `1 / 3 / 5 / 10 / 20`；目标两档：**舒适 TTFA ≤1 s**、**可用 TTFA ≤2 s**；TTFA 定义 = 用户说完话 → 首个音频帧发出；四个归因时间戳（VAD 判停、STT 出字、LLM 首 token、TTS 首帧）。

- [ ] **Step 7: 写 §6「质量与能力提示」附录**

2B/0.8B 在工具调用、多轮指代、中文长句明显弱于 8B/9B；⑤⑥定位"边缘全栈/成本极限"；建议 prompt 限长 + few-shot。

- [ ] **Step 8: 写 §7「假设项登记表」（HT1~HT4 + 后续新增）**

| 编号 | 假设 | 状态 | 解除方式 |
|---|---|---|---|
| HT1 | Qwen3.5-2B / 0.8B 存在可用 GGUF（Q4_K_M/Q8_0） | 待 Task 2 检索 | 检索 HF/ModelScope |
| HT2 | llama.cpp 支持 Qwen3.5 架构 | 待 Task 2 检索 | 查 llama.cpp 支持列表/issue |
| HT3 | ARM 盒可跑一致的 Qwen3-ASR/TTS（torch/transformers） | 待 Task 4 证据链 | 逐盒评估卡 |
| HT4 | 电商价格为 2026-10-22 快照 | 持续 | 下单前复核 |
| HA1 | 单轮语音 3 s / P95 10 s | 假设 | 验收 T2 实测 |
| HA2 | 内网 RTT 10–80 ms | 假设 | 验收 T7 实测 |

- [ ] **Step 9: 自检并提交**

```powershell
Select-String -Path docs/hardware/performance-assumptions.md -Pattern "TBD|待补充"   # Expected: 无输出
git add docs/hardware/performance-assumptions.md
git commit -m "docs(hardware): 新增语音链路并发与延迟性能假设条件表"
```

---

## 阶段 2：联网检索（产出带来源的事实，供阶段 3 使用）

### Task 2：解除 HT1/HT2——小模型权重与 llama.cpp 支持

**Files:**
- Create: `docs/hardware/.research-small-models.md`（检索原始记录，不提交，Task 7/8 引用后删除）

- [ ] **Step 1: 检索 Qwen3.5-2B / Qwen3.5-0.8B 是否发布**

WebSearch 查询（逐条执行，记录命中结果与 URL）：
```
Qwen3.5-2B Hugging Face GGUF
Qwen3.5-0.8B Hugging Face GGUF
Qwen3.5 small models 0.8B 2B release
Qwen3-0.6B GGUF Q4_K_M
```
Expected: 明确回答三件事——① Qwen3.5 是否存在 <4B 档；② 若不存在，官方最接近的小档是什么（Qwen3-0.6B / Qwen3-1.7B）；③ GGUF 仓库名（如 `Qwen/Qwen3.5-2B-Instruct-GGUF`）与量化文件清单。

- [ ] **Step 2: 检索 llama.cpp 对该架构的支持状态**

```
llama.cpp Qwen3 support merged
llama.cpp Qwen3.5 architecture support issue
llms.txt Qwen3
```
Expected: 得到"支持/需特定分支/不支持"三选一定论 + 证据链接（PR/issue/官方 llms.txt 条目）。

- [ ] **Step 3: 检索 32K 上下文与思考链默认状态**

```
Qwen3.5-2B context length 32K
Qwen3 thinking mode enable_thinking default
```
Expected: 确认用户提供的"0.8B/2B 均 32K"是否与官方模型卡一致；若不一致，以官方模型卡为准并记录差异。

- [ ] **Step 4: 把结论写入检索草稿，按"结论 / 证据 URL / 检索日期 / 置信度"四列格式**

若 Step 1 判定 Qwen3.5-<4B 不存在：草稿必须写出**回退候选**（Qwen3-1.7B、Qwen3-0.6B）及"用户指定的 2B/0.8B 档以何名义落地"的建议（例如改为 `Qwen3-1.7B / Qwen3-0.6B`，或保留命名但在文档显式标注"待官方发布"）。**不得静默替换模型**——把选择权作为 TODO 项回报给用户确认。

- [ ] **Step 5: 更新 HT1/HT2 状态**

编辑 `docs/hardware/performance-assumptions.md` §7 表格，把 HT1/HT2 的"状态"列改为检索所得（如 `已证实（来源 URL，2026-10-22）` 或 `不成立，回退候选见 plan-5 §假设`），并提交：
```powershell
git add docs/hardware/performance-assumptions.md
git commit -m "docs(hardware): 依据检索结论解除小模型权重与llama.cpp支持假设"
```

### Task 3：GPU 整机/显卡在售商品与价格检索

**Files:**
- Create: `docs/hardware/.research-gpu-products.md`

- [ ] **Step 1: 逐档位检索（每档 2~3 条查询）**

档位清单：`RTX 3060 12G`、`RTX 4060 Ti 16G`、`RTX 5060 Ti 16G`、`RTX 5070 12G`、`RTX 5070 Ti 16G`、`RTX 4090 24G`、`RTX 5090 32G`、`L20 48G`、`RTX 5880 Ada 48G`、`DGX Spark`。
查询模板：
```
<型号> 整机 价格 1688
<型号> 涡轮 拆机 价格 淘宝
NVIDIA <型号> 规格 显存 TDP 官方
```
Expected: 每档至少 1 条**具体商品页/店铺**（而非纯搜索页）+ 1 条**官方规格**来源；记录品牌、型号、SKU 关键差异（长度/槽数/涡轮 vs 双风扇）、价格区间、功耗。

- [ ] **Step 2: 补齐规格字段（任务书 §3 要求的硬件字段）**

对每个候选条目补齐：CPU 平台、显存、内存、存储、网口（2.5G/10G）、扩展槽、功耗、散热形态、外部接口（HDMI/USB）。缺失字段标 `未核实`，不要猜。

- [ ] **Step 3: 标注风险项**

逐条判断并写明：涡轮/服务器卡噪音与散热、拆机卡与矿卡风险、保修主体（整机商 vs 显卡厂）、供货稳定性、50 系 CUDA 版本要求（cu128/cu130 镜像差异，参考仓库已有 `Dockerfile.cu128`/`Dockerfile.cu130`）。

- [ ] **Step 4: 按 procurement 条目字段结构写入草稿**

字段顺序固定为：编号占位（D-xx）｜品牌型号｜检索来源+日期｜CPU/GPU/显存/内存/存储/网口/扩展/功耗/散热｜推理栈｜可承载方案｜单盒路数（引用假设表 §4 公式，写出算式）｜TTFA 预估｜价格（区间/实价分开）｜风险｜替代编号。

> 本任务不提交（草稿），Task 5 汇总入库。

### Task 4：边缘/国产算力盒证据链检索

**Files:**
- Create: `docs/hardware/.research-edge-boxes.md`

- [ ] **Step 1: 逐品类检索硬件规格与商品**

品类：Jetson Orin NX 16G、Jetson AGX Orin 32/64G、DGX Spark（GB10 128G）、Atlas 500 Pro / 800I A2、RK3588 16/32G 推理盒（香橙派 5 Plus、Rongals、MegaSpace、Firefly）、寒武纪 MLU370-X4/X8、Intel Core Ultra 迷你主机（OpenVINO 路线：铭凡、Beelink GTR、LattePanda）、地平线 RDK。
查询模板：
```
<品类> 统一内存 功耗 规格 官方
<品类> 边缘计算盒子 价格 1688
```

- [ ] **Step 2: 检索"模型一致性"关键证据（HT3）**

对每个品类检索，并**只接受四类证据**（优先级：官方模型卡 > 芯片厂商模型库 > 社区实测 > 工具链推断）：
```
Qwen3-ASR Jetson aarch64 transformers
Qwen3-TTS ARM64 torch install
Qwen3-ASR Ascend CANN support
Qwen3-ASR ONNX export RKNN
Qwen3 ASR OpenVINO Intel NPU
transformers aarch64 wheel GPU tensor
```
Expected: 每盒得到"已证实 / 待验证 / 高风险"三档之一 + 至少一条带 URL 的证据；无证据时**必须**写"待验证"，不得凭显存数字推断可行。

- [ ] **Step 3: 检索小模型（⑤⑥）在非 CUDA 栈的支持**

```
llama.cpp Ascend backend
llama.cpp RKNN backend
llama.cpp OpenVINO backend
MLC LLM Qwen3 ARM
```
Expected: 得出"哪个盒子能把 Qwen3.5-2B/0.8B 放到本地"的结论与置信度。

- [ ] **Step 4: 为每盒生成 3~6 条买前验证问题（可直接问店铺/查文档）**

示例格式（写入草稿）：
```
1. 该 SKU 出厂系统是否为 Ubuntu 22.04 arm64？是否预装 CUDA/驱动版本 <x>？
2. 官方文档中 Qwen3-ASR / Qwen3-TTS 是否出现在支持模型列表？给出链接。
3. 社区是否有人在该芯片上跑通 transformers 版 Qwen3-TTS？给出 issue/论坛链接。
```

- [ ] **Step 5: 汇总支持矩阵草稿**

行=盒子，列=`VAD / STT(Qwen3-ASR) / TTS(Qwen3-TTS) / 远程LLM① / 本地⑤2B / 本地⑥0.8B`，每格取值：`已证实` / `待验证` / `高风险` / `不适用`。

> 本任务不提交（草稿），Task 6 汇总入库。

---

## 阶段 3：文档产出

### Task 5：创建 `procurement-list.md`

**Files:**
- Create: `docs/hardware/procurement-list.md`
- Input: `docs/hardware/.research-gpu-products.md`、`.research-edge-boxes.md`、`docs/hardware/performance-assumptions.md`

- [ ] **Step 1: 写 §1「使用说明」**

固定三条：① 价格均为 2026-10-22 检索快照，下单前必须复核；② 条目字段定义与置信标注规则（`已核实商品页` / `仅检索式链接`）；③ 本清单是商品与价格的**唯一来源**，`plan-N.md` 只引用 D-xx 编号。

- [ ] **Step 2: 写 §2「快选矩阵」（6 方案 × 4 维度）**

矩阵行=方案①远程 / ②8B / ③9B / ④4B / ⑤2B / ⑥0.8B；列=性价比 / 低延迟 / 高并发 / 备选。每格填一个 D-xx 编号 + 一句话理由。格内无合适条目时写 `暂无：<原因 + 建议>`（不允许留空）。

- [ ] **Step 3: 写 §3「候选商品主表」**

每条目一行的紧凑表，列：编号｜品牌/型号｜GPU/NPU｜显存或统一内存｜内存/存储｜功耗｜可承载方案｜单盒路数｜价格区间｜置信标注。编号规则：`D-G##`=GPU 整机/卡、`D-E##`=边缘盒、`D-S##`=服务器卡（L20/5880）。

- [ ] **Step 4: 写 §4「条目详情」（每条目一个小节）**

逐条输出 Task 3 Step 4 的全字段，**路数必须写出算式**，例：
```
RTX 5070 Ti 16G + Qwen3-8B Q4 + 8K KV
可用 = 16 − 5.0 − 0.6 − 0.8 = 9.6GB → 槽位 = floor(9.6×0.85/4.6) = 1 路（同机）
多盒模式：作为管线盒（不放 LLM）→ floor(16×0.85/4.6) = 2 路；LLM 由 4090 盒集中承载
```
> 这条算式揭示"同机跑 LLM 后单盒只剩 1 路"，是所有方案的共同结论，必须在每个含 LLM 的条目重复出现（数值随卡变化）。

- [ ] **Step 5: 写 §5「多盒组合套餐」**

至少三档：入门（1×5070 管线 + 远程 GPUStack）、均衡（1×4090 LLM 盒 + 2~4×4060Ti 管线盒）、高并发（1×5090/L20 LLM 盒 + N×管线盒）。每档给总价区间、可达路数、需 10GbE/1GbE 的判断（引用 `deployment-multibox.md`）。

- [ ] **Step 6: 写 §6「按方案分组索引」**

①~⑥ 每个方案一段：推荐条目编号、优先级（P0/P1/P2）、适用场景、部署复杂度（低/中/高）、主要风险、链接到 `plan-N.md`。

- [ ] **Step 7: 自检并提交**

```powershell
Select-String -Path docs/hardware/procurement-list.md -Pattern "TBD|待补充|暂无$"   # Expected: 仅允许出现"暂无：<理由>"，不得有裸"暂无$"
git add docs/hardware/procurement-list.md
git commit -m "docs(hardware): 新增可采购算力盒子商品清单（6方案×4维度快选矩阵）"
```

### Task 6：创建 `edge-box-feasibility.md`

**Files:**
- Create: `docs/hardware/edge-box-feasibility.md`
- Input: `.research-edge-boxes.md`、`performance-assumptions.md` §7

- [ ] **Step 1: 写 §1「评估框架」**

三条硬定义：① **一致性定义**——必须能运行与本地一致的 Qwen3-ASR-1.7B（transformers）+ Qwen3-TTS-1.7B（torch 或 ggml 后端），用 whisper/paraformer 替代**不合格**，只能标注"需替换模型 = 不满足一致性"；② **置信三级**定义（已证实=有直接实测证据 / 待验证=工具链存在但该模型无实测 / 高风险=无证据或反证）；③ **证据优先级**（官方模型卡 > 芯片厂商模型库 > 社区实测 > 工具链推断）。

- [ ] **Step 2: 写 §2「逐盒评估卡」（每品类一节，字段固定）**

字段顺序：硬件（SoC/GPU-NPU/统一内存/存储/网口/扩展/功耗/散热）｜推理栈（CUDA/TensorRT/ONNX/OpenVINO/CANN/llama.cpp/MLC/RKNN 状态）｜证据链（逐条：结论 + URL + 检索日期 + 证据类型）｜置信度｜全栈本地可行性（①⑤⑥ 分别结论；②③④ 默认排除并给显存算式）｜买前验证步骤（3~6 条）｜代表商品（引用 `D-E##`）。

- [ ] **Step 3: 写 §3「支持矩阵汇总表」**

行=盒子，列=`VAD / STT / TTS / ①远程LLM / ⑤2B / ⑥0.8B`，取值 `已证实/待验证/高风险/不适用`。表格下方写一句总述：本次评估中"全栈本地（VAD+STT+TTS+LLM 同机）"仅有 <N> 款达到"已证实/待验证"，其余为高风险。

- [ ] **Step 4: 写 §4「买前验证清单（汇总可打印版）」**

按盒子分组的 checkbox 清单，每条是一个可直接问店铺或查官方文档的动作。

- [ ] **Step 5: 写 §5「结论：采购短名单」**

分三档：可进短名单（已证实）/ 可小批量 PoC（待验证，附必须执行的验收 T1/T2 专项）/ 不进短名单（高风险，附排除理由）。

- [ ] **Step 6: 自检并提交**

```powershell
Select-String -Path docs/hardware/edge-box-feasibility.md -Pattern "置信度" | Measure-Object   # Expected: 命中数 == 评估卡数量
git add docs/hardware/edge-box-feasibility.md
git commit -m "docs(hardware): 新增边缘与国产算力盒可行性评估（证据链+置信分级+买前验证）"
```

### Task 7：创建 `plan-5-qwen3.5-2b.md`

**Files:**
- Create: `docs/hardware/plan-5-qwen3.5-2b.md`
- Reference: `docs/hardware/plan-4-qwen3.5-4b.md`（小节结构对齐）

- [ ] **Step 1: 写小节骨架（与 plan-2~4 完全同构）**

`概述 / 显存分配（单盒同卡）/ 商品检索 / 并发与性能估算 / 多盒拆分 / 部署建议 / 假设与待验证项`。

- [ ] **Step 2: 填「显存分配」表（三列量化）**

STT 1.8 + TTS 3.4 + VAD 0.03 + LLM(Qwen3.5-2B)：Q4 ~1.3 / Q8 ~2.2 / FP16 ~4.0 + KV(32K q8) ~1.2 → 小计 Q4 ≈6.3GB、Q8 ≈7.2GB、FP16 ≈9.0GB；建议显存：Q4 需 **8GB 紧 / 12GB 稳**，FP16 需 12GB+。每列同时给"同机槽位路数"与"纯管线盒路数"两个数字（用假设表 §4 公式）。

- [ ] **Step 3: 填「商品检索」——只引用条目编号**

表列：档位（最低成本/推荐/边缘可选）｜条目编号 `D-xx`｜显卡｜显存｜一句话理由。**不写价格**（价格只在 procurement-list）。边缘候选列引用 `edge-box-feasibility.md` 结论（如 Jetson Orin NX / RK3588 32G，附置信度）。

- [ ] **Step 4: 填「并发与性能估算」**

按假设表 §5 两档目标给 TTFA 预估区间与 1/3/5/10/20 档可达性；单流 tok/s 引用检索所得或标注"理论推导，验收 T6 实测"。

- [ ] **Step 5: 填「部署建议」+「假设与待验证项」**

部署：compose 改法（`-hf` 换成 Qwen3.5-2B GGUF 仓库名，Task 2 所得）、关思考链、`-np` 建议值、量化优先级（先量化 LLM 而非 STT/TTS）。假设项：列出 HT1/HT2 结论 + 若 Task 2 判定不存在则写回退候选与命名说明。

- [ ] **Step 6: 自检并提交**

```powershell
Select-String -Path docs/hardware/plan-5-qwen3.5-2b.md -Pattern "¥"   # Expected: 无输出（价格不外泄）
git add docs/hardware/plan-5-qwen3.5-2b.md
git commit -m "docs(hardware): 新增方案⑤ Qwen3.5-2B 本地部署选型"
```

### Task 8：创建 `plan-6-qwen3.5-0.8b.md`

**Files:**
- Create: `docs/hardware/plan-6-qwen3.5-0.8b.md`
- Reference: `docs/hardware/plan-5-qwen3.5-2b.md`

- [ ] **Step 1: 复用同构小节骨架**（`概述 / 显存分配 / 商品检索 / 并发与性能估算 / 多盒拆分 / 部署建议 / 假设与待验证项`）

- [ ] **Step 2: 填「显存分配」**

STT 1.8 + TTS 3.4 + VAD 0.03 + LLM(Qwen3.5-0.8B)：Q4 ~0.6 / Q8 ~0.9 / FP16 ~1.6 + KV(32K q8) ~0.8 → 小计 Q4 ≈5.6GB、FP16 ≈6.6GB；建议显存 **8GB 可跑 / 12GB 舒适**。槽位算式必须逐档写出（沿用假设表 §4 公式）：

```
12GB 卡 + 0.8B-FP16：可用 = 12 − 1.6 − 0.8 − 0.8 = 8.8GB → floor(8.8×0.85/4.6) = 1 路
16GB 卡 + 0.8B-Q8 ：可用 = 16 − 0.9 − 0.8 − 0.8 = 13.5GB → floor(13.5×0.85/4.6) = 2 路
24GB 卡 + 0.8B-FP16：可用 = 24 − 1.6 − 0.8 − 0.8 = 20.8GB → floor(20.8×0.85/4.6) = 3 路
```

- [ ] **Step 3: 填「商品检索」「并发与性能」「部署建议」**

同 Task 7 Step 3~5 规则。特别强调：⑥ 是**边缘盒全栈本地唯一现实的 LLM 档**，正文必须与 `edge-box-feasibility.md` §3 矩阵交叉引用（列出该档下"待验证"盒子的验收前置条件）。

- [ ] **Step 4: 写「质量下限警告」小节（本文档独有）**

0.8B 在多轮指代、工具调用、中文长句上显著弱；给出至少 2 条可直接粘贴的 `--init_chat_prompt` 限长模板 + few-shot 兜底建议；明确"不适合需要可靠工具调度的调解/客服正式场景，仅适合导览/单轮问答/边缘兜底"。

- [ ] **Step 5: 自检并提交**

```powershell
Select-String -Path docs/hardware/plan-6-qwen3.5-0.8b.md -Pattern "¥"   # Expected: 无输出
git add docs/hardware/plan-6-qwen3.5-0.8b.md
git commit -m "docs(hardware): 新增方案⑥ Qwen3.5-0.8B 本地部署选型"
```

### Task 9：创建 `acceptance-test-plan.md`

**Files:**
- Create: `docs/hardware/acceptance-test-plan.md`
- Reference: `latency_test.py`、`docs/hardware/deployment-multibox.md` §"并发压测"、`docker-compose.local.yml`

- [ ] **Step 1: 写「定位与前置」小节**

声明：判定线全部引用 `performance-assumptions.md`（§4 并发公式、§5 延迟档位），本文档不复制数值；工具只用 `latency_test.py` + shell 并行 + 厂商监控；执行前提=已完成采购且能进内网。

- [ ] **Step 2: 写 T0/T1/T2 三个阶段（每阶段：目的 / 命令 / PASS 判据 / 取证）**

T1 命令示例（指纹对齐，Task 0.1 Step 3 的清单即基线）：
```powershell
Get-ChildItem -Recurse cache | Where-Object { -not $_.PSIsContainer -and $_.Length -gt 1MB } |
  ForEach-Object { "{0}`t{1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Length } >到货指纹.txt
Compare-Object (Get-Content 基线指纹.txt) (Get-Content 到货指纹.txt)
```
T1 PASS 判据：所有模型文件 SHA256 与基线一致；容器启动日志无 `device=cpu` 回退、无 `transformers version too old` 类告警；compose 参数 diff 仅显存/设备相关项不同。

- [ ] **Step 3: 写 T3/T4 阶段**

T3：`python latency_test.py ref_audio.wav` 单路多次采样（≥10 次），记录四个时间戳；PASS 判据 = TTFA P95 ≤ 假设表"舒适档"，WARN = 落在舒适与可用档之间，FAIL = 超可用档。
T4：三路显存采样命令
```bash
nvidia-smi --query-gpu=memory.used --format=csv -l 5 > mem.log     # ARM/昇腾分别用 jetson-stats / npu-smi
```
PASS 判据 = 实测 ≤ 采购条目承诺值 ×1.15；1.15~1.30 记 WARN（触发"有条件通过"）；>1.30 记 FAIL。

- [ ] **Step 4: 写 T5 并发阶梯阶段**

沿用 `deployment-multibox.md` 的 for 循环压测（原文粘贴命令并注明出处），阶梯 1→3→5→10→20；记录每档 P50/P95 TTFA、`SERVER ERROR` 次数、GPU 利用率/温度；饱和点定义引用假设表 §5。

- [ ] **Step 5: 写 T6 本地 LLM 专项 + T7 远程 LLM 专项**

T6：`llama-bench` 或 `llama-cli` 单流 tok/s、`-np` 批量吞吐、KV 显存实测；输出"该盒实际可承载路数"并回填 `procurement-list.md` 对应条目。
T7：到 GPUStack 的 RTT/TTFT 实测、拔网线重连、超时兜底文案验证。

- [ ] **Step 6: 写 T8 稳定性 + T9 报告模板**

T8：2h soak（给出循环脚本），关注显存单调上升（泄漏）、温度触顶降频、TTS 音质抽检。
T9：完整报告模板（markdown 表格，含环境快照、逐项 PASS/FAIL/WARN、与采购条目承诺值对照表、结论与整改项），文件名规范 `acceptance-report-<型号>-<YYYYMMDD>.md`。

- [ ] **Step 7: 写「三档判定规则」与「边缘盒挂钩」**

判定规则照 spec §8 表：通过 / 有条件通过（降级）/ 退货；退货三条件（T1 不一致、T2 RTF≥1、T3 单路超可用档）。边缘盒挂钩：`edge-box-feasibility.md` 中"待验证"的盒子必须执行 T1/T2 ARM 一致性专项，失败即触发"需替换模型=不满足一致性"退货条款。

- [ ] **Step 8: 写附录（wav 样本要求 + 一行并发命令 + 报告模板）**

- [ ] **Step 9: 自检并提交**

```powershell
Select-String -Path docs/hardware/acceptance-test-plan.md -Pattern "TTFA ≤|≥ ?1 ?s|≤ ?2s"   # Expected: 判定处均写"见 performance-assumptions §5"而非自建数值
git add docs/hardware/acceptance-test-plan.md
git commit -m "docs(hardware): 新增到货算力盒实测验收方案（T0~T9 与三档判定）"
```

---

## 阶段 4：存量刷新

### Task 10：刷新 `README.md`（总入口）

**Files:**
- Modify: `docs/hardware/README.md`

- [ ] **Step 1: 方案索引表从 4 行扩为 6 行**

新增两行：⑤ Qwen3.5-2B（最低成本单盒 / 推荐单盒 / 多盒拆分 / 并发 / 定位）、⑥ Qwen3.5-0.8B（同结构），数值改为**引用** `plan-5`/`plan-6` 与 `performance-assumptions.md`（表中"并发"列标注推导口径来自假设表）。

- [ ] **Step 2: 新增「文档地图」小节**

列出 4 份新文档的职责与"什么改动该改哪个文件"（对应 spec §4 职责边界表），强调单一事实来源规则。

- [ ] **Step 3: 「电商平台检索入口」小节改为指向清单**

保留原 8 条 1688 链接（作为兜底检索入口），但顶部加一句：**具体在售条目、价格与置信标注见 `procurement-list.md`**。

- [ ] **Step 4: 「组件与显存基线」加日期与实测说明**

现有实测表保留；在表下补一行：实测占用 4.6GB/路 是所有路数推导的基准，任何新镜像需重新测量并同步更新本表与假设表。

- [ ] **Step 5: 自检并提交**

```powershell
Select-String -Path docs/hardware/README.md -Pattern "plan-5|plan-6|procurement-list|edge-box-feasibility|acceptance-test-plan|performance-assumptions" | Measure-Object   # Expected: ≥6 命中
git add docs/hardware/README.md
git commit -m "docs(hardware): README 扩展为6方案总入口并接入新专题文档索引"
```

### Task 11：刷新 `plan-1~4.md`（去重 + 改引用）

**Files:**
- Modify: `docs/hardware/plan-1-remote-llm.md`
- Modify: `docs/hardware/plan-2-qwen3-8b.md`
- Modify: `docs/hardware/plan-3-qwen3.5-9b.md`
- Modify: `docs/hardware/plan-4-qwen3.5-4b.md`

- [ ] **Step 1: 每个文件把「商品检索」表的长链接/价格列替换为 D-xx 引用**

替换规则：删除京东联盟长链与涡轮卡具体价（这些内容迁到 `procurement-list.md`），表格列改为 `档位｜条目编号｜显卡｜显存｜一句话理由`，段末加一行：`> 价格与商品条目详情见 procurement-list.md（检索日期 2026-10-22，下单前复核）`。

- [ ] **Step 2: 每个文件在「并发与性能估算」段首补推导引用**

加入引用块：`> 以下路数按 performance-assumptions.md §4 公式推导（每路管线实测 ≈4.6GB），含 LLM 同机时受槽位约束显著下降；原按吞吐给出的乐观值已标注为多盒模式上限。` 并把该文件的路数数值与该卡型公式结果对齐——若矛盾，**以公式结果为准改写数字**，并在同一行注明"（修订：原估 X 路未计 num_pipelines 显存约束）"。

- [ ] **Step 3: 每个文件尾部加「到货验收」一行**

`- 到货后按 [acceptance-test-plan.md](./acceptance-test-plan.md) 执行 T0~T9，判定线见 performance-assumptions.md。`

- [ ] **Step 4: plan-1 追加边缘盒与远程 LLM 的关系说明**

在 plan-1「部署建议」补：边缘盒（ARM）在方案①下的适用性与置信度引用 `edge-box-feasibility.md`，并强调"ARM 若跑不通一致的 Qwen3-ASR/TTS，则方案①也不成立"。

- [ ] **Step 5: 自检并提交**

```powershell
rg -n "union-click\.jd\.com" docs/hardware/plan-*.md   # Expected: 无输出（长链已迁走）
rg -c "performance-assumptions\.md" docs/hardware/plan-1-remote-llm.md docs/hardware/plan-2-qwen3-8b.md docs/hardware/plan-3-qwen3.5-9b.md docs/hardware/plan-4-qwen3.5-4b.md
# Expected: 四个文件各 ≥1 命中
git add docs/hardware/plan-1-remote-llm.md docs/hardware/plan-2-qwen3-8b.md docs/hardware/plan-3-qwen3.5-9b.md docs/hardware/plan-4-qwen3.5-4b.md
git commit -m "docs(hardware): plan1-4 商品数据迁移至采购清单并对齐并发推导口径"
```

### Task 12：`deployment-multibox.md` 微调

**Files:**
- Modify: `docs/hardware/deployment-multibox.md`（文首 + 压测章节）

- [ ] **Step 1: 文首加口径引用行**

`> 本文所有路数/延迟估算统一引用 [performance-assumptions.md](./performance-assumptions.md)；本文 §并发压测 的命令被 [acceptance-test-plan.md](./acceptance-test-plan.md) T5 直接沿用。`

- [ ] **Step 2: 「盒子角色与显存分配」表补 2B/0.8B 两行**

LLM 盒表中加入 `Qwen3.5-2B ≈1.3GB(Q4)/2.2GB(Q8)`、`Qwen3.5-0.8B ≈0.6GB(Q4)/0.9GB(Q8)`，并发上限参考列补对应档位（数值来源假设表 §3，标注推导）。

- [ ] **Step 3: 提交**

```powershell
git add docs/hardware/deployment-multibox.md
git commit -m "docs(hardware): 多盒部署清单补充小模型档位并统一引用假设表"
```

---

## 阶段 5：终检

### Task 13：跨文档一致性终检与草稿清理

**Files:**
- Delete: `docs/hardware/.baseline-facts.md`、`.research-small-models.md`、`.research-gpu-products.md`、`.research-edge-boxes.md`
- Modify: 上述任一文档（发现问题就地修）

- [ ] **Step 1: 跑占位符扫描**

```powershell
rg -n "TBD|TODO|待补充|fill in" docs/hardware
```
Expected: 无输出（`docs/hardware` 内不允许遗留占位符）。

- [ ] **Step 2: 跑双源泄漏检查**

```powershell
rg -n "¥[0-9,]+" docs/hardware --glob '!procurement-list.md' --glob '!README.md'
```
Expected: 无输出（价格只在清单与 README 概览）。若有，迁移到 `procurement-list.md` 并改为 D-xx 引用。

- [ ] **Step 3: 跑数字一致性检查**

```powershell
rg -n "4\.6GB|4633" docs/hardware
```
Expected: 只出现在 `README.md`、`performance-assumptions.md` 与被允许的引用处；其他文件的每路值若与 4.6GB 冲突（如仍写 5.2GB 理论值），改为引用实测口径。

- [ ] **Step 4: 逐条核对 spec §11 验收清单（9 项）**

对照 spec 的 checkbox 列表逐项验证，任一不满足 → 回到对应任务修文档 → 重新提交。特别检查：快选矩阵 6×4 无空格；每个外部结论带检索日期与 URL；验收文档不自建阈值。

- [ ] **Step 5: 删除四个草稿文件并提交**

```powershell
Remove-Item docs/hardware/.baseline-facts.md, docs/hardware/.research-small-models.md, docs/hardware/.research-gpu-products.md, docs/hardware/.research-edge-boxes.md
git add -A docs/hardware
git commit -m "docs(hardware): 选型文档一致性终检与检索草稿清理"
```

- [ ] **Step 6: 输出交付摘要**

向用户汇报：新增 6 份文档（假设表/采购清单/边缘盒可行性/实测验收/plan-5/plan-6）与修改
6 份文档（README/plan-1~4/deployment-multibox）、6 方案各自的推荐条目与价格区间、HT1~HT4 的最终结论（哪些已证实、哪些仍待验证）、边缘盒短名单，以及**需要用户决策的遗留项**（如小模型命名是否改为 Qwen3-1.7B/0.6B）。

---

## Self-Review（已执行）

**1. Spec coverage：** spec §5.2→Task 1；§6→Task 3+5；§7→Task 4+6；§8→Task 9；§5.1 六方案→Task 7/8 + Task 10/11；§9 存量刷新→Task 10/11/12；§10 执行顺序→阶段编排一致；§11 验收标准→Task 13 Step 4。无遗漏。

**2. Placeholder scan：** 检索类任务的结果内容是"未知"由性质决定，但每个任务都规定了**必须回答的具体问题**与**无结论时的强制写法**（标"待验证"、回退候选需回报用户），无裸 TBD。

**3. Type consistency：** 文档间引用名统一为 `performance-assumptions.md` / `procurement-list.md` / `edge-box-feasibility.md` / `acceptance-test-plan.md` / `plan-5-qwen3.5-2b.md` / `plan-6-qwen3.5-0.8b.md`；条目编号统一 `D-G##`/`D-E##`/`D-S##`；阶段编号统一 `T0~T9`；置信三级统一 `已证实 / 待验证 / 高风险`；假设编号统一 `HT1~HT4`、`HA1~HA2`；并发公式（`floor(可用×0.85÷4.6)`）全篇一致。
