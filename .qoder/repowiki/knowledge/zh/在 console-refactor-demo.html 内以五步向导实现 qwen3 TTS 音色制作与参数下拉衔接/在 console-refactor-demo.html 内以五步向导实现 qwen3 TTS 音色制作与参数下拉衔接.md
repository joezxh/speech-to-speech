---
kind: design
name: 在 console-refactor-demo.html 内以五步向导实现 qwen3 TTS 音色制作与参数下拉衔接
source: session
category: adr
---

# 在 console-refactor-demo.html 内以五步向导实现 qwen3 TTS 音色制作与参数下拉衔接

_来源：545d6f7 → da8dfe3 提交周期内记录的编码计划——内容为规划时意图，实现可能滞后或有出入。_

**状态：** accepted

## 背景
需要在单文件静态原型中新增「新建音色」能力，使创建出的音色能立即出现在 `#/deploy` 的 `qwen3_tts_speaker` / `qwen3_tts_ref_spk` / `qwen3_tts_ref_rvq` / `qwen3_tts_instruct` 四个参数的实际值下拉中；同时保持纯前端、无构建、无新依赖。

## 决策驱动
- 零依赖静态原型约束
- 与既有 machineFormHtml/machineTestHtml 范式一致以降低维护成本
- 新建音色对 deploy 参数表立即可见
- Mock 语义（toast + 内存 VOICES）不引入后端耦合

## 备选方案
- **在现有 voice.test/clone/delete/import 按钮上直接扩展为真实写入** _（已否决）_ — 优点：改动最小；缺点：会改变既有 toast-only 文案语义，且无法表达预计算失败/重试等复杂流程
- **将向导拆分为独立 HTML/JS 模块并引入构建工具** _（已否决）_ — 优点：结构清晰；缺点：违反「纯静态、无新依赖、无构建」约束
- **仅修改 deploy 下拉而不提供音色创建入口** _（已否决）_ — 优点：改动面更小；缺点：无法满足「创建后可被 qwen3 推理链路选用」的需求

## 决策
在 `console/design/console-refactor-demo.html` 内新增 `openVoiceWizard()`：通过 `state.voice` 驱动五步模态（source → audio → preview → precompute → name），每步复用 `.pipe/.stage` 步骤条与 `openModal` 重渲染范式；保存时 `VOICES.push()` 并刷新 `renderChrome()/renderPage()`；同时在 `paramRow` 中以 `VC_PICK` 映射将四行 `qwen3_tts_*` 参数渲染为 `<select class="pv">`，选项由 `voicePick` 从 `VOICES` 派生（过滤 `backend === 'qwen3-tts' && status === 'ready'`）。

## 影响
向导逻辑集中在一个函数块内，后续扩展需继续遵循 `machineFormHtml` 范式；所有写操作仍停留在内存 `VOICES` 与 toast，未触及后端；`src` 字段（builtin/clone/design）和 `art` 产物路径 `/app/data/voices/<ulid>/<f>` 成为后续真实化时的契约；`voice_precompute_failed` 失败分支要求预计算成功才能进入命名步，避免脏数据流入部署参数。