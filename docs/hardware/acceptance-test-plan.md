# 到货算力盒实测验收方案（acceptance-test-plan）

> **适用对象**：所有从 [procurement-list.md](./procurement-list.md) 采购的盒子（GPU 整机、服务器卡、边缘盒）。
> **判定线不复制**：延迟档位、并发公式、显存基线全部引用
> [performance-assumptions.md](./performance-assumptions.md)（§3 显存 / §4 并发公式 / §5 延迟档位），
> 本文只定义"怎么测、测完怎么判"。
> **工具只有三样**：`latency_test.py`（仓库根目录）+ shell 并行 + 厂商监控命令
> （`nvidia-smi` / `tegrastats` / `npu-smi`）。不引入新的压测框架。

---

## §1 定位与前置

### 1.1 这份文档管什么

| 管 | 不管 |
|---|---|
| 到货后 **T0~T9** 十阶段怎么执行 | 采购决策（见 `procurement-list.md`） |
| 每个阶段的 **PASS / WARN / FAIL** 判据 | 估算值的推导（见 `performance-assumptions.md`） |
| 证据怎么留（命令输出、日志、曲线） | 性能调优（见 `deployment-multibox.md` §调优要点） |
| 三档结论（通过 / 有条件通过 / 退货）与写回动作 | 应用层功能正确性（那是业务测试，不在本方案） |

### 1.2 执行前提

1. 盒子已到货、已上电、能进内网；
2. `cache/` 模型目录已挂载（或已按 `Dockerfile` 重建镜像）；
3. 有一份**基线指纹清单**——本文 §14.1 已固化了 2026-10-22 本机实测的 8 项基线，
   到货机直接与它比对，不需要回头找原机器；
4. `ref_audio.wav` 已准备（要求见 §14.2）。

### 1.3 必须先读的实测陷阱：`latency_test.py` 的输出不等于 TTFA

`latency_test.py` 打印两行延迟（源码第 158–159 行）：

```
TTFA (t0 -> first audio):      3.42s     ← 从"开始推音频"算起，含 3 s 语音播放时长
Latency after speech end:      0.45s     ← 从"服务端 VAD 判定 speech_stopped"算起
```

而假设表 §5 定义的 TTFA 是 **"用户说完最后一个字 → 客户端收到首个音频帧"**。对应关系：

```
真实 TTFA = Latency after speech end + min_silence_ms / 1000
```

- `base` 取的是时间线里的 `speech_stopped(srv)`，**发生在用户说完之后 `min_silence_ms`**；
- 所以日志里的 `0.45s` 在 `--min_silence_ms 700` 配置下，**真实 TTFA ≈ 1.15s**；
- 在 `--min_silence_ms 64` 的本机配置下，两者只差 0.064s，容易误以为"模型很快"。

> **执行纪律**：T3 记录的每一个 TTFA 都必须标注当时的 `min_silence_ms`，
> 并同时给出"日志值"和"修正后 TTFA"。只报日志值一律视为无效证据。

---

## §2 T0 环境就绪

**目的**：确认驱动、容器运行时、加速卡可见性、系统架构与镜像匹配。

**命令**

```bash
# 1) 系统与架构
uname -m && cat /etc/os-release | head -3

# 2) 加速卡可见性（按硬件三选一）
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv      # NVIDIA / Jetson
tegrastats --interval 1000 | head -3                                      # Jetson（或 jtop）
npu-smi info                                                              # 昇腾
rocm-smi                                                                  # AMD

# 3) 容器 GPU 直通
docker info --format '{{json .Runtimes}}'
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi

# 4) PyTorch 与 CUDA 匹配
python -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# 5) 模型目录挂载
ls -lh cache/ | head
```

**PASS 判据**

- 架构（`x86_64` / `aarch64`）与镜像标签一致；
- 加速卡被 `nvidia-smi` / `tegrastats` / `npu-smi` 识别，显存容量与采购条目一致；
- `torch.cuda.is_available()` 为 `True`（非 CUDA 平台则确认对应后端可用）；
- `cache/` 能列出模型文件且总大小与基线量级一致。

**取证**：把 5 条命令的**完整输出**贴进报告 §环境快照。任何一条失败 → 停在 T0，不进 T1。

---

## §3 T1 模型一致性

**目的**：证明到货机跑的是**同一份模型**，没有降级、没有替换、没有下载到一半的半成品。

**命令（Windows / 基线机）**

```powershell
Get-ChildItem -Recurse cache | Where-Object { -not $_.PSIsContainer -and $_.Length -gt 1MB } |
  ForEach-Object { "{0}`t{1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Length } > 到货指纹.txt
Compare-Object (Get-Content 基线指纹.txt) (Get-Content 到货指纹.txt)
```

**命令（Linux 到货机）**

```bash
find cache -type f -size +1M -print0 | xargs -0 sha256sum | sort -k2 > 到货指纹.txt
diff <(sort -k2 基线指纹.txt) 到货指纹.txt && echo "T1 PASS: 指纹完全一致"
```

**PASS 判据**

1. §14.1 的 8 项基线文件 **SHA256 全部一致**（`0.8B` 那项除外，见下）；
2. 容器启动日志中**无** `device=cpu` 回退、**无** `transformers version too old`、
   **无** `falling back to` 类降级告警；
3. 启动参数与 `docker-compose.local.yml` 逐项 diff，差异**只允许**出现在显存/设备/端口相关项
   （`--num_pipelines`、`--qwen3_asr_device`、`--qwen3_tts_device`、`LLM_BASE_URL`、`PIPELINE_PORT`）。

**取证**：`到货指纹.txt` 全文 + `diff` 结果 + 容器启动日志前 100 行。

> **已知问题**：本机 `cache/qwen35-08b/Qwen3.5-0.8B-Q4_K_M.gguf` 只有 8.95 MB，
> 是下载未完成的占位文件，**不可作为 0.8B 已就绪的证据**。
> 走方案⑥时必须以 `unsloth/Qwen3.5-0.8B-GGUF` 重新下载并记录新的 SHA256，
> 基线清单里该行标注"待补"。

---

## §4 T2 功能链路

**目的**：证明"能听、能懂、能说"，并量化 STT / TTS 的实时性。

**命令**

```bash
# 单轮，完整时间线
PHRASES=1 GAP=2.0 python latency_test.py ref_audio.wav

# 三轮，验证多轮与历史
PHRASES=3 GAP=2.0 python latency_test.py ref_audio.wav
```

**人工核对项（逐条打勾）**

- [ ] `TRANSCRIPT:` 输出的中文与音频内容一致（错字/漏字要记录）；
- [ ] 回复语种与用户一致，音色为 `Aiden`（CustomVoice 默认）；
- [ ] 音频无截断、无爆音、无重复念同一句；
- [ ] 语音打断（barge-in）可用：TTS 播放中说话，回复应停止并转入新轮；
- [ ] 三轮对话中，第二轮能引用第一轮的信息（验证 `--chat_size` 生效）。

**RTF 计算（关键判据）**

```
STT RTF = (t_stt_first − t_vad_end) / 音频时长
TTS RTF = (t_tts_first − t_llm_first) / 首句音频时长
```

- `t_vad_end` 取时间线里的 `speech_stopped(srv)`；
- 音频时长从 `Audio total sent duration` 读取；
- 两项都要记录，不要只报一个。

**PASS 判据**

- 转写无关键错漏（人名/时间/金额这类实体错 = FAIL）；
- barge-in 可用；
- **STT RTF 与 TTS RTF 均小于 1.0**（`≥ 1.0` 即"跟不上实时"，触发退货，见 §12）。

**取证**：完整时间线输出 + 转写文本 + 两项 RTF 值。

---

## §5 T3 单路延迟基线

**目的**：给出该盒的 TTFA 分布，并做四段归因，判断瓶颈在哪一段。

**命令（≥10 次采样）**

```bash
for i in $(seq 1 10); do
  PHRASES=1 GAP=2.0 python latency_test.py ref_audio.wav | tee /tmp/t3_$i.log
done
grep "Latency after speech end" /tmp/t3_*.log | awk '{print $NF}'
```

**计算**

1. 把 10 次 `Latency after speech end` 排序，取 P50 与 P95；
2. **加上 `min_silence_ms / 1000`** 得到真实 TTFA（见 §1.3）；
3. 四段归因：`t_vad_end`、`t_stt_first`、`t_llm_first`、`t_tts_first`，各段占比填进报告。

**PASS 判据**（阈值见 `performance-assumptions.md` §5）

| 结果 | 判定 |
|---|---|
| 修正后 TTFA P95 落在**舒适档** | PASS |
| 落在舒适档与**可用档**之间 | WARN（记录实际值，可交付但需评估） |
| 超出**可用档** | FAIL → 触发退货条款（见 §12） |

> 判定时**必须**用修正后的 TTFA，不是日志里的 `Latency after speech end`。
> 这是本方案唯一容易系统性低估 700 ms 的地方。

**取证**：10 份日志 + 排序表 + 四段时间线截图。

---

## §6 T4 显存实测

**目的**：验证"4.6 GB/路"在该硬件上成立，并核对采购条目承诺的路数。

**三路采样（缺一不可）**

```bash
# 采样器（后台跑）
nvidia-smi --query-gpu=memory.used --format=csv -l 5 > mem.log     # NVIDIA
# Jetson：tegrastats --interval 5000 > mem.log
# 昇腾：npu-smi info -l 1 -t 5 > mem.log

# 采样点 1：单路常驻（启动后空闲 3 分钟）
# 采样点 2：num_pipelines 打满（并发到该条目承诺路数）
# 采样点 3：本地 LLM 加载后（方案②~⑥ 才有）
```

**PASS 判据**

`实测峰值 / 采购条目承诺值` 的偏差：

| 偏差 | 判定 |
|---|---|
| ≤ 1.15 | PASS |
| 1.15 ~ 1.30 | WARN（"有条件通过"，须把实测值写回 `procurement-list.md`） |
| > 1.30 | FAIL |

**额外判据**：三路采样中，显存曲线应在前 2 分钟内趋于平稳。
若持续单调上升 → 疑似泄漏，转入 T8 观察。

**取证**：`mem.log` 三段区间 + 一条时序曲线（任意绘图工具，或直接把 csv 贴在报告里）。

---

## §7 T5 并发阶梯

**目的**：找出该盒的**饱和点**，验证"槽位约束"是否真的是约束（还是吞吐先生效）。

**命令**（沿用 [deployment-multibox.md](./deployment-multibox.md) §并发压测的 for 循环，原样粘贴）

```bash
# 阶梯：1 → 3 → 5 → 10 → 20，逐档替换 N
N=5
for i in $(seq 1 $N); do
  PHRASES=2 GAP=3 python latency_test.py ref_audio.wav > /tmp/load_$i.log 2>&1 &
done
wait
grep "Latency after speech end" /tmp/load_*.log
grep -c "SERVER ERROR" /tmp/load_*.log
```

**每档必须记录**

| 指标 | 采集方式 |
|---|---|
| P50 / P95 TTFA（修正后） | 同上，逐档排序 |
| `SERVER ERROR` 次数 | `grep -c` |
| GPU 利用率 / 温度 | `nvidia-smi --query-gpu=utilization.gpu,temperature.gpu --format=csv -l 5` |
| 显存峰值 | T4 的采样器 |

**饱和点定义**（见 spec §8 与假设表 §5）

> P95 TTFA 超过目标档，**或**出现任意 `SERVER ERROR`，**或** GPU 温度触顶降频——
> 三者任一出现即记为饱和点。饱和点减一档即为"可交付路数"。

**PASS 判据**

- 采购条目承诺的档位全部跑通，且未触饱和；
- 若只跑到"承诺低一档"→ WARN（"有条件通过"）；
- 承诺档位出现 `SERVER ERROR` 或 TTFA 超可用档 → FAIL。

**取证**：逐档汇总表（档位 / P50 / P95 / 报错数 / 利用率 / 温度 / 显存峰值）。

---

## §8 T6 本地 LLM 专项（方案②~⑥）

**目的**：验证 llama.cpp 在该盒的真实吞吐，并回填"可承载路数"。

**命令**

```bash
# 单流 tok/s（-p 提示处理，-n 生成）
llama-bench -m cache/qwen35-4b/Qwen3.5-4B-Q4_K_M.gguf -p 512 -n 128 -r 3

# 批量吞吐（-np 等于目标并发）
llama-server -m <gguf> -np 4 -c 16384 -fa on --host 0.0.0.0 --port 8080 &
python -c "
import json,urllib.request
req=urllib.request.Request('http://localhost:8080/v1/chat/completions',
  data=json.dumps({'model':'local','messages':[{'role':'user','content':'你好，请用一句话介绍你自己。'}],'max_tokens':64}).encode(),
  headers={'Content-Type':'application/json'})
print(urllib.request.urlopen(req).read().decode()[:400])
"
```

**判据**

| 项 | 判据 |
|---|---|
| 单流 tok/s | 不低于 `plan-5`/`plan-6` §并发与性能估算的**预期实测区间下限** |
| 思考链 | 输出中**不得**出现 ` thinking` 段（`--reasoning-budget 0` 生效） |
| `-np` 吞吐 | N 路并行的总 tok/s ≥ 单流 × N × 0.6（低于说明批调度退化） |
| 显存 | `权重 + KV` 与假设表 §3.2 的推导值偏差在 ±20% 内 |

**动作**：把实测的"可承载路数"**写回 `procurement-list.md` 对应条目**，
并在该行标注"实测（日期 / 盒子型号）"。

**取证**：`llama-bench` 原始输出 + 并发请求的响应时间 + `nvidia-smi` 快照。

---

## §9 T7 远程 LLM 专项（方案①）

**目的**：验证"管线盒 + 远程 GPUStack"这条最省钱的路线在网络侧的稳定性。

**命令**

```bash
# 1) 网络 RTT（20 次）
ping -c 20 192.168.40.30 | tail -3

# 2) 首 token 延迟（TTFT，5 次取中位数）
for i in $(seq 1 5); do
  curl -s -o /dev/null -w "%{time_starttransfer}\n" \
    -X POST http://192.168.40.30/v1-openai/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"Qwen3-8B","messages":[{"role":"user","content":"你好"}],"stream":true}'
done

# 3) 断网重连：拔网线 / 关闭对端网口 30 s 后恢复，观察 pipeline 日志
docker logs -f <pipeline-container> | grep -iE "error|retry|timeout|reconnect"
```

**判据**

| 项 | 判据 |
|---|---|
| RTT | 落在假设表 §2 的"内网 RTT"区间内 |
| TTFT | 落在假设表 §2 的"远程 LLM 首 token"区间内 |
| 断网 30 s 后恢复 | 3 分钟内自动恢复对话，**不需要重启容器** |
| 超时兜底 | LLM 不可用时，用户听到的是**明确的提示音/文案**，不是静默或无限等待 |

**取证**：`ping` 输出、5 次 TTFT、断网期间的容器日志片段、兜底文案的实际录音或转写。

---

## §10 T8 稳定性（soak）

**目的**：抓长跑才暴露的问题：显存泄漏、热降频、音质劣化。

**命令（2 小时循环）**

```bash
# 后台起采样
nvidia-smi --query-gpu=memory.used,temperature.gpu,clocks_throttle_reasons.active \
  --format=csv -l 30 > soak_mem.log &

# 2 小时 soak：每 60 s 一轮，共 120 轮
END=$((SECONDS+7200)); i=0
while [ $SECONDS -lt $END ]; do
  i=$((i+1))
  PHRASES=2 GAP=5 python latency_test.py ref_audio.wav > /tmp/soak_$i.log 2>&1
  sleep 60
done
grep -h "Latency after speech end" /tmp/soak_*.log | awk '{print $NF}' > soak_ttfa.txt
```

**判据**

| 项 | 判据 |
|---|---|
| 显存 | 第 2 小时的均值 − 第 1 小时的均值 < 5%（>5% 判泄漏） |
| 温度 | 不触发热降频（`clocks_throttle_reasons.active` 全程为 `0x0`） |
| TTFA | 第 2 小时的 P95 相对第 1 小时劣化 < 20% |
| 音质 | 抽检首尾各 3 条录音，无明显劣化/断续 |

**取证**：`soak_mem.log` + `soak_ttfa.txt` + 首尾音频各 3 段。

---

## §11 T9 验收报告

**文件名**：`acceptance-report-<型号>-<YYYYMMDD>.md`
（例：`acceptance-report-d-g04-20261105.md`）

**模板**

```markdown
# 验收报告：<型号 / 条目编号>

## 1. 环境快照
| 项 | 值 |
|---|---|
| 盒子型号 / 序列号 | |
| 架构 / OS / 内核 | |
| 加速卡 / 驱动 / CUDA | |
| 容器运行时 | |
| 镜像标签 | |
| 采购条目编号 | D-xx |
| 验收日期 | YYYY-MM-DD |

## 2. 逐项结果
| 阶段 | 结果 | 关键指标 | 证据位置 |
|---|---|---|---|
| T0 环境就绪 | PASS/FAIL | | |
| T1 模型一致性 | PASS/FAIL | 8/8 指纹一致 | |
| T2 功能链路 | PASS/WARN/FAIL | STT RTF=，TTS RTF= | |
| T3 单路延迟 | PASS/WARN/FAIL | TTFA P50=，P95=（修正后，min_silence= ms） | |
| T4 显存实测 | PASS/WARN/FAIL | 偏差 +xx% | |
| T5 并发阶梯 | PASS/WARN/FAIL | 饱和点 = N 路 | |
| T6 本地 LLM | PASS/WARN/FAIL | tok/s=，-np 吞吐= | |
| T7 远程 LLM | PASS/WARN/FAIL | RTT=，TTFT= | |
| T8 稳定性 | PASS/WARN/FAIL | 显存漂移 +x% | |

## 3. 与采购条目承诺值对照
| 项 | 采购条目承诺 | 实测 | 偏差 |
|---|---|---|---|
| 单盒路数 | | | |
| 显存占用 | | | |
| 价格（复核） | | | |

## 4. 结论
- 三档结论：通过 / 有条件通过 / 退货
- 理由（引用 §2 的判据编号）

## 5. 整改项
| 项 | 负责人 | 期限 | 状态 |
|---|---|---|---|

## 6. 写回动作
- [ ] `procurement-list.md` 对应条目的"单盒路数"已更新为实测值
- [ ] `performance-assumptions.md` §7 的假设状态已更新（如涉及 HA1~HA4）
```

---

## §12 三档判定规则

| 结论 | 条件 | 后续动作 |
|---|---|---|
| **通过** | T0–T5 全 PASS，且该条目承诺的并发档实测达成 | 可批量采购；把实测值写回 `procurement-list.md` |
| **有条件通过**（降级使用） | T4 的 `实测峰值 / 承诺值` 落在 WARN 区间（见 §6 的偏差表），**或** T5 达成档位比承诺低一档 | 记录实际容量上限并写回 `procurement-list.md`；按降级后的路数重新规划套餐 |
| **退货 / 替换** | ① T1 不一致（模型被替换或跑不起来）；② T2 的 STT 或 TTS **RTF ≥ 1.0**；③ T3 单路修正后 TTFA 已超出可用档 | 立即启动退货流程；该条目从短名单移除并标注原因 |

> 三条退货条件**任一命中即退货**，不做加权、不做"再测一次看看"。
> **性能判据**（TTFA 档位、RTF = 1.0 红线）的数值一律从 `performance-assumptions.md` 取，本表不重复；
> **测量容差**（§6 的 1.15 / 1.30 偏差带、§8 的 ±20%）是本方案的操作判据，用于区分"测量误差"与"货不对板"，
> 不属于性能假设，故意不写进假设表。

---

## §13 边缘盒挂钩

[edge-box-feasibility.md](./edge-box-feasibility.md) §3 中结论为**待验证**的盒子，
到货后**必须额外执行 T1 / T2 的"ARM / 非 CUDA 一致性专项"**：

| 盒子 | 专项内容 | 失败后果 |
|---|---|---|
| `D-E01` Jetson Orin NX 16G | T1 指纹比对 + T2 的 STT/TTS RTF（102 GB/s 下的真实值） | RTF ≥ 1.0 → 触发"不满足一致性"退货条款 |
| `D-E02` Jetson AGX Orin 64G | 同上，加 60 W 持续功耗下的降频检查 | 同上 |
| `D-G08` / `D-G09` DGX Spark | 加 **arm64 镜像构建**与 `cache/` 重下 | 镜像跑不起来 → 退货或转 x86 |
| `D-E09` Ryzen AI Max+ 395 | 加 **ROCm 一致性**：`rocm-smi` 识别 + transformers 原样权重可加载 | ROCm 跑不动 → 转 x86 + NVIDIA |
| `D-E08` Ultra 9 285H | 加 CPU/NPU 路径的 RTF 实测 | RTF ≥ 1.0 → 仅作办公机，不作管线盒 |

**判定口径**（与 spec 一致）

> 若为跑通而**替换模型**（换成 whisper / paraformer / Piper 等），
> 按 edge-box-feasibility.md §1.1 判为"**不满足一致性**"，直接触发退货条款——
> **不允许"换个小模型就算通过"**。
> 唯一例外是 Qwen3-ASR / TTS 的 0.6B 同家族小号，但必须在报告中显式标注
> "非 1.7B 一致配置"，并重新跑 T1（指纹）/ T2（音频）/ T3（延迟）全套。

---

## §14 附录

### 14.1 基线指纹清单（2026-10-22 本机 `cache/` 实测）

T1 比对用。8 项基线 + 1 项待补：

| 文件（相对 `cache/`） | 字节数 | SHA256 |
|---|---|---|
| `qwen3-asr-model-hf/model.safetensors` | 4076193080 | `2DB53C7D81BD9B8CBC6A074E89BE2C968A0D373FB4EE68BB1B1E14F7042DFEE1` |
| `qwen3-asr-model-hf/tokenizer.json` | 11429653 | `FE1FAD59BE22A41EE293363FCF95FDEDBC7C93F3B49270B1D2E18BD1399A7A05` |
| `qwen3-tts-model/model.safetensors` | 3833402552 | `38B1D5971BDBD982B561CCCEC982669A53B0537C3CF5E9BD4778ED07BB2F5137` |
| `qwen3-tts-model/speech_tokenizer/model.safetensors` | 682293092 | `836B7B357F5EA43E889936A3709AF68DFE3751881ACEFE4ECF0DBD30BA571258` |
| `qwen3-tts-model/merges.txt` | 1671839 | `599BAB54075088774B1733FDE865D5BD747CBCC7A547C5BC12610E874E26F5E3` |
| `qwen3-tts-model/vocab.json` | 2776833 | `CA10D7E9FB3ED18575DD1E277A2579C16D108E32F27439684AFA0E10B1440910` |
| `smart-turn-v3.2-cpu.onnx` | 8679182 | `2BB026316B14A660486A75B1733CD3FBAB8C2FD0314DC9AF7BE49F8CCA967E4F` |
| `qwen35-4b/Qwen3.5-4B-Q4_K_M.gguf` | 2740937888 | `00FE7986FF5F6B463E62455821146049DB6F9313603938A70800D1FB69EF11A4` |
| `qwen35-08b/Qwen3.5-0.8B-Q4_K_M.gguf` | **待补** | **待补**（本机文件不完整，须重新下载后校验） |

> HF 缓存 `cache/huggingface/hub/blobs/**` 下的同内容大文件与上表为硬链接/副本，指纹一致，
> **不需要**重复比对；按"相对 `cache/` 的 canonical 路径"比即可。
> 换镜像或换模型版本后，本表必须重新生成并同步更新本节。

### 14.2 `ref_audio.wav` 样本要求

| 项 | 要求 |
|---|---|
| 格式 | WAV / PCM16 / 单声道 |
| 采样率 | 16 kHz（`latency_test.py` 会自动重采样，但原生 16 kHz 最准） |
| 时长 | 主样本 **3 s 左右**（对应假设表 HA1 的典型值）；另备一条 **10 s** 长句 |
| 内容 | 中文、无背景音乐、无多人对话；含至少一个实体（人名/时间/金额）用于转写核对 |
| 音量 | 峰值不超过 −3 dBFS，避免削波 |
| 命名 | `ref_audio.wav`（3 s）、`ref_audio_long.wav`（10 s） |

### 14.3 一行并发命令（复制即用）

```bash
N=5; for i in $(seq 1 $N); do PHRASES=2 GAP=3 python latency_test.py ref_audio.wav > /tmp/load_$i.log 2>&1 & done; wait; grep -h "Latency after speech end" /tmp/load_*.log | awk '{print $NF}' | sort -n | awk '{a[NR]=$1} END {print "P50="a[int(NR*0.5)], "P95="a[int(NR*0.95)], "N="NR}'
```

> 改 `N` 即可跑 1/3/5/10/20 各档。注意这一行的 P50/P95 是**日志值**，
> 报告里必须加上 `min_silence_ms / 1000`（见 §1.3）。

### 14.4 报告模板

见 §11。模板字段不得删减——尤其"与采购条目承诺值对照"与"写回动作"两节，
它们保证验收结论能回流到 `procurement-list.md` 与 `performance-assumptions.md`。
