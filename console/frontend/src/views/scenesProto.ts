/**
 * 推荐配置方案数据（原型 console-refactor-demo.html 的 SCENES 镜像）。
 *
 * 每条模板通过 `scene` 绑定一份方案；模板只读查看时展示方案内容，
 * 不在部署页直接展开。条目字段与原型一致：p（目录键）/ v（建议值）/
 * why（改动理由）/ gain（预期收益）/ cost（连带代价）/ risk（风险提醒）/ ref（依据）。
 * 生效方式徽章由目录行的 effect 推导，这里不复述。
 */

export interface SceneItem {
  p: string
  v: string
  why: { zh: string; en: string }
  gain: { zh: string; en: string }
  cost: { zh: string; en: string }
  risk: { zh: string; en: string }
  ref: string
}

export interface SceneProto {
  key: string
  note: { zh: string; en: string }
  cross?: boolean
  items: SceneItem[]
}

export const SCENE_PROTOS: SceneProto[] = [
  {
    key: 'latency',
    note: { zh: '安静环境的演示/评测，追求 P95 首音；可以接受偶尔误切句（手册 S11）。', en: 'Quiet demo or evaluation box chasing P95 first audio; occasional over-segmentation is accepted (playbook S11).' },
    items: [
      { p: 'vad.min_silence_ms', v: '400', ref: 'catalog §2.7 · playbook S11',
        why: { zh: '判停静音直接计入每轮响应；450 → 400 少等一档，又不至于频繁误切。', en: 'Endpointing silence is billed to every reply; 450 → 400 shaves the wait without mis-cutting.' },
        gain: { zh: '每轮约省 0.05–0.2s 死等。', en: 'Roughly 0.05–0.2s less dead time per turn.' },
        cost: { zh: '句中短停顿会被判成句末，捕获率略降。', en: 'Shorter pauses get closed as a turn.' },
        risk: { zh: '会话级可热更新，改错立刻影响在线会话。', en: 'Hot-updatable; a wrong value is live immediately.' } },
      { p: 'llm.stream_batch_sentences', v: '1', ref: 'catalog §4.2 · §2.7',
        why: { zh: '逐句下吐才能让 TTS 在回答结束前就出声。', en: 'Sentence-by-sentence hand-off lets TTS speak before the answer ends.' },
        gain: { zh: '首音不再等待整段回答生成完。', en: 'First audio no longer waits for the whole reply.' },
        cost: { zh: 'TTS 调用次数变多、单段变短。', en: 'More, smaller TTS calls.' },
        risk: { zh: '启动生效，重启前线上仍是旧值。', en: 'Start-only; running process keeps the old batching.' } },
      { p: 'tts.qwen3_tts_non_streaming_mode', v: 'false', ref: 'catalog §5.2',
        why: { zh: '句内流式（配合 chunk 4）是压低 TTS 首音的生产选择。', en: 'Intra-sentence streaming (chunk 4) is the production choice for low TTS TTFA.' },
        gain: { zh: 'TTS 首音目标压到 200ms 以内。', en: 'TTS TTFA target under 200 ms.' },
        cost: { zh: '依赖 torch 流式路径。', en: 'Needs the torch streaming path.' },
        risk: { zh: '启动生效；parity_mode / eager 注意力会绕开 CUDA graph。', en: 'Start-only; parity_mode or eager attention bypasses the CUDA-graph path.' } },
      { p: 'stt.qwen3_asr_gen_max_new_tokens', v: '128', ref: 'catalog §3.2 · config/prod.yaml',
        why: { zh: '默认 256 曾出现 47s/53s 失控生成，会拖住整轮。', en: 'The 256 default showed 47s/53s runaway generations.' },
        gain: { zh: '单段转写延迟有上界。', en: 'Bounded STT tail latency per segment.' },
        cost: { zh: '超长段落会被截断。', en: 'Long passages get truncated.' },
        risk: { zh: '启动生效；截断是静默的。', en: 'Start-only; truncation is silent.' } },
      { p: 'vad.smart_turn', v: 'false', ref: 'catalog §2.4',
        why: { zh: '语义判停要多一次 ONNX 确认等待，低延迟场景不划算。', en: 'Semantic endpointing adds an ONNX wait the latency profile cannot afford.' },
        gain: { zh: '省掉数十毫秒 CPU 推理与宽限等待。', en: 'Removes tens of milliseconds of CPU inference.' },
        cost: { zh: '句尾语气词更容易被截断。', en: 'Sentence-final particles get cut more often.' },
        risk: { zh: '启动生效。', en: 'Start-only.' } }
    ]
  },
  {
    key: 'slow',
    note: { zh: '语速慢、句中有思考停顿、长句不允许被拆成两轮（手册 S12）。', en: 'Deliberate speakers, thinking pauses mid-sentence, long sentences that must not be split (playbook S12).' },
    items: [
      { p: 'vad.min_silence_ms', v: '700', ref: 'catalog §2.7 · playbook S12',
        why: { zh: '调参矩阵第一行就是慢语速被切成两轮 → 调大本参数。', en: 'The tuning matrix moves exactly this parameter when slow speech lands in two turns.' },
        gain: { zh: '整句不被切断，重复重开的气泡减少。', en: 'Whole sentences survive; fewer duplicate reopened bubbles.' },
        cost: { zh: '每轮响应延迟增加 0.15–0.35s。', en: '+0.15–0.35s on every reply.' },
        risk: { zh: '可会话级热更新，可直接试。', en: 'Hot-updatable; trial on a live session.' } },
      { p: 'vad.smart_turn', v: 'true', ref: 'catalog §2.4 · §2.7',
        why: { zh: '用语义判停代替纯静音判断「还没说完」。', en: 'Semantic endpointing decides "not finished yet".' },
        gain: { zh: '句尾语气词与自我修正不再丢句。', en: 'Trailing particles keep their sentence.' },
        cost: { zh: '每次判停多一次 ONNX 推理。', en: 'One extra ONNX pass per decision.' },
        risk: { zh: '启动生效；离线机器须预置 smart_turn_model_path。', en: 'Start-only; offline hosts must ship smart_turn_model_path.' } },
      { p: 'vad.smart_turn_threshold', v: '0.6', ref: 'catalog §2.4',
        why: { zh: '从 0.5 提到 0.6，模型需要更多证据才判定「说完了」。', en: 'Raising 0.5 → 0.6 demands more evidence.' },
        gain: { zh: '迟疑语音被过早结束的情况减少。', en: 'Fewer premature closes.' },
        cost: { zh: '更多轮次等到 incomplete_delay 才回答。', en: 'More turns hit the incomplete delay.' },
        risk: { zh: '启动生效。', en: 'Start-only.' } },
      { p: 'vad.short_segment_merge_ms', v: '900', ref: 'catalog §2.3',
        why: { zh: '碎片先 hold 再拼接；取值必须 ≥ min_silence_ms。', en: 'Fragments are held and merged; must stay >= min_silence_ms.' },
        gain: { zh: '呼吸级碎片不再独立成轮。', en: 'Breath-length fragments stop becoming turns.' },
        cost: { zh: '真正的短轮次多等一次拼接窗口。', en: 'Adds merge latency to short turns.' },
        risk: { zh: '启动生效；小于 min_silence_ms 静默失效。', en: 'Start-only; below min_silence_ms silently disables merging.' } },
      { p: 'vad.max_speech_ms', v: '30000', ref: 'catalog §2.2',
        why: { zh: '给连续语音设上限，避免单段无限占用管线。', en: 'A monologue cap prevents one endless segment.' },
        gain: { zh: '单段长度有界。', en: 'Bounded segment length.' },
        cost: { zh: '单段变长，STT 延迟近似线性上升。', en: 'Longer segments raise STT latency linearly.' },
        risk: { zh: '启动生效；强制切分可能切在词中间。', en: 'Start-only; hard splits can cut mid-word.' } }
    ]
  },
  {
    key: 'noisy',
    cross: true,
    note: { zh: '开放办公、门店、车载、风扇噪声 —— 误警优先于漏检（手册 S10）。切 VAD 后端后所有阈值都要重新标定。', en: 'Open office, shop floor, car cabin, fan hum — false triggers matter more than misses (playbook S10). Switching the VAD backend re-calibrates every threshold.' },
    items: [
      { p: 'vad.thresh', v: '0.7', ref: 'catalog §2.7 · playbook S10',
        why: { zh: '呼吸与键盘噪声被计成语音的第一动就是这个阈值。', en: 'The first move for breathing and keyboard noise scored as speech.' },
        gain: { zh: '静默时段的误触发显著下降。', en: 'Silent-room false triggers drop sharply.' },
        cost: { zh: '轻声句尾开始漏检。', en: 'Soft sentence endings get missed.' },
        risk: { zh: '可热更新，对在线会话即时生效。', en: 'Hot-updatable on a live session.' } },
      { p: 'vad.min_speech_ms', v: '500', ref: 'catalog §2.2',
        why: { zh: '短促脉冲噪声过不了最短语音时长，不会开轮。', en: 'Short impulsive noises fail the minimum speech length.' },
        gain: { zh: '键盘声与杂音不再触发打断。', en: 'Keyboards and clicks stop interrupting playback.' },
        cost: { zh: '「嗯」「好」这类短应答会被丢弃。', en: '"mm/ok" style short replies are dropped too.' },
        risk: { zh: '启动生效，session.update 不认这一项。', en: 'Start-only; session.update does not carry it.' } },
      { p: 'vad.audio_enhancement', v: 'true', ref: 'catalog §2.2',
        why: { zh: '稳态噪声下收益最大的是 DeepFilterNet 增强。', en: 'DeepFilterNet suppression is the highest-yield item.' },
        gain: { zh: 'VAD 输入更干净，识别率更好。', en: 'Cleaner VAD input, better recognition.' },
        cost: { zh: '额外 CPU 与 Silero、CPU STT 争核。', en: 'Extra CPU contending with Silero.' },
        risk: { zh: '启动生效；依赖未安装时该项等于没开。', en: 'Start-only; verify the dependency is installed.' } },
      { p: 'vad.vad', v: 'firered', ref: 'catalog §1.2 · §2.5',
        why: { zh: '同一基准下 FireRedVAD 误警率 2.69%，Silero 为 9.41%。', en: 'FireRedVAD reports 2.69% false alarms vs Silero 9.41%.' },
        gain: { zh: '公共空间的幽灵轮次明显减少。', en: 'Materially fewer phantom turns.' },
        cost: { zh: '需要 fireredvad 包与 Stream-VAD 权重目录。', en: 'Needs the fireredvad package plus weights.' },
        risk: { zh: '启动生效且属后端切换：阈值必须重新标定（§2.5.3）。', en: 'Start-only backend switch: thresholds must be re-tuned (§2.5.3).' } },
      { p: 'stt.qwen3_asr_language', v: 'zh', ref: 'catalog §3.2 · §3.4',
        why: { zh: '固定语言可去掉噪声下不可靠的自动语言判定。', en: 'Pinning the language removes unreliable auto-detection.' },
        gain: { zh: '噪声段的错误语言幻觉转写减少。', en: 'Fewer wrong-language hallucinations.' },
        cost: { zh: '说其他语言要靠 session.update 覆盖。', en: 'Other languages need a session.update override.' },
        risk: { zh: '转录语言属真正可热更新的四组之一。', en: 'Transcription language is genuinely hot-updatable.' } }
    ]
  },
  {
    key: 'edge',
    note: { zh: '单机低显存。路数先由 num_pipelines 显存公式决定，再谈其它调优（手册 S1/S2、目录 §6.1）。', en: 'One small box, tight VRAM. Concurrency is decided by the num_pipelines formula first (playbook S1/S2, catalog §6.1).' },
    items: [
      { p: 'platform.num_pipelines', v: '1', ref: 'catalog §6.1',
        why: { zh: '每路独占整套 handler（实测约 4.6GB）；池满直接拒绝新连接。', en: 'Each slot holds a full handler set (~4.6GB measured); the pool rejects instead of queueing.' },
        gain: { zh: '启动不被 OOM 杀掉，超载时可见失败。', en: 'Startup survives; peak load fails visibly.' },
        cost: { zh: '降路数会中断现有会话。', en: 'Shrinking the pool interrupts live sessions.' },
        risk: { zh: '启动生效，且受 floor(显存 × 0.85 / 4.6GB) 硬约束。', en: 'Start-only, capped by floor(VRAM × 0.85 / 4.6GB).' } },
      { p: 'tts.qwen3_tts_backend', v: 'ggml', ref: 'catalog §5.2',
        why: { zh: 'ggml 路线可用量化把权重压小。', en: 'The ggml path lets quantization shrink the talker weights.' },
        gain: { zh: '单路显存下降，为路数公式腾出余量。', en: 'Lower VRAM per pipeline.' },
        cost: { zh: '需先备好 gguf talker/codec 成对文件。', en: 'The gguf pair has to be prepared first.' },
        risk: { zh: '启动生效；后端与路径不匹配会在加载时失败。', en: 'Start-only; mismatched paths fail at load.' } },
      { p: 'tts.qwen3_tts_ggml_quantization', v: 'Q8_0', ref: 'catalog §5.2',
        why: { zh: 'Q8_0 是保守档；Q4_K_M 更省但听感劣化明显。', en: 'Q8_0 is the conservative step; Q4_K_M saves more but is audibly worse.' },
        gain: { zh: '不必走音质评审就能立刻腾出显存。', en: 'Immediate VRAM relief.' },
        cost: { zh: '轻微音质损失，需重新下载量化权重。', en: 'Slight quality loss; re-download weights.' },
        risk: { zh: '启动生效；Q4_K_M 交付前需业务确认。', en: 'Start-only; Q4_K_M needs business sign-off.' } },
      { p: 'tts.qwen3_tts_dtype', v: 'float16', ref: 'catalog §5.2',
        why: { zh: '该模型用 float32 显存翻倍且听感无收益。', en: 'float32 doubles VRAM for no perceptual gain.' },
        gain: { zh: '精度相关显存开销减半。', en: 'Halves precision-related VRAM.' },
        cost: { zh: '部分算子上有细微数值差异。', en: 'Marginal numeric differences.' },
        risk: { zh: '启动生效、expert 级；老驱动上不支持的 dtype 直接加载失败。', en: 'Start-only, expert-level; unsupported dtype fails at load.' } },
      { p: 'tts.qwen3_tts_attn_implementation', v: 'eager', ref: 'playbook S5 · catalog §5.2',
        why: { zh: 'ARM/边缘 CUDA 栈上最先出问题的通常是 flash-attention 内核。', en: 'Flash-attention kernels are the usual first casualty on ARM/edge stacks.' },
        gain: { zh: '在会崩溃的机器上能正常启动。', en: 'Startup succeeds where the fast path crashes.' },
        cost: { zh: '注意力更慢，一般与 parity_mode true 一起用。', en: 'Slower attention; usually paired with parity_mode true.' },
        risk: { zh: '启动生效；负载下吞吐下降可测。', en: 'Start-only; throughput loss is measurable.' } }
    ]
  },
  {
    key: 'mix',
    note: { zh: '中英混说：识别语言飘移、TTS 串音、专名热词不中（手册 S17、目录 §3.4）。', en: 'Chinese-English code switching: language drift, TTS accent bleed and hot-word misses (playbook S17, catalog §3.4).' },
    items: [
      { p: 'stt.qwen3_asr_language', v: 'zh', ref: 'catalog §3.2 · §3.4',
        why: { zh: 'auto 会多花 token 做语言识别，短句还容易误判。', en: 'auto spends tokens on language identification and misjudges short utterances.' },
        gain: { zh: '以中文为主、夹英文术语时转写更稳定。', en: 'Stable Chinese-dominant transcription.' },
        cost: { zh: '整句英文要靠 session.update 覆盖。', en: 'Pure-English turns need the session override.' },
        risk: { zh: '覆盖必须通过后端语言能力校验。', en: 'The override must pass the backend capability check.' } },
      { p: 'stt.qwen3_asr_prompt', v: '产品与专名热词表', ref: 'catalog §3.2',
        why: { zh: '热词/专名正是本参数的用途。', en: 'Product and proper nouns are exactly what the prompt field is for.' },
        gain: { zh: '品牌名不再被改成同音词。', en: 'Brand names stop becoming homophones.' },
        cost: { zh: '每段都摊提示词延迟，需控制长度。', en: 'Every segment pays prompt latency; keep it short.' },
        risk: { zh: '启动生效；过长会明显拖慢每段。', en: 'Start-only; over-long prompts slow each segment.' } },
      { p: 'llm.enable_lang_prompt', v: 'true', ref: 'catalog §4.2',
        why: { zh: '让助手跟随用户语言而不是固定一种。', en: 'Lets the assistant follow the user language.' },
        gain: { zh: '回答不再中途换语言。', en: 'Answers stop switching language mid-conversation.' },
        cost: { zh: '每轮多几条 token。', en: 'A few extra tokens per turn.' },
        risk: { zh: '启动生效。', en: 'Start-only.' } },
      { p: 'platform.detect_llm_output_language', v: 'true', ref: 'catalog §6.4',
        why: { zh: '逐块检测助手输出语言并下发 TTS，才能避免音色串音。', en: 'Per-chunk detection hands the language to TTS, stopping accent bleed.' },
        gain: { zh: '混合语种的回答按正确语言合成。', en: 'Mixed-language replies synthesize correctly.' },
        cost: { zh: '每块多一次本地推理。', en: 'One more local inference per chunk.' },
        risk: { zh: '启动生效；首块过短时不下发语言码。', en: 'Start-only; very short first chunks send no language code.' } },
      { p: 'tts.qwen3_tts_language', v: 'zh', ref: 'catalog §5.2',
        why: { zh: '混合语种下 auto 会串音，固定值更干净。', en: 'auto bleeds accents when the sentence mixes scripts.' },
        gain: { zh: '主语言中文的音色可预期。', en: 'Predictable Chinese timbre.' },
        cost: { zh: '英文占比高的回答依赖逐块语言检测。', en: 'English-heavy replies lean on per-chunk detection.' },
        risk: { zh: '启动生效；部分后端语言在加载时固化。', en: 'Start-only; some backends fix the language at load.' } }
    ]
  },
  {
    key: 'remote',
    cross: true,
    note: { zh: '本地不跑模型：STT、LLM、TTS 全部走托管/网关端点，用每轮网络往返换显存（目录 §3.4/§4.5/§5.3）。', en: 'No local weights: STT, LLM and TTS all go to managed endpoints, trading network round trips for VRAM.' },
    items: [
      { p: 'llm.responses_api_base_url', v: 'http://192.168.40.30/v1-openai', ref: 'catalog §4.3',
        why: { zh: '端点不对时 LLM 块其它字段都不生效；路径要用 /v1-openai。', en: 'Everything else is inert until the gateway endpoint is right; the path must be /v1-openai.' },
        gain: { zh: '本地 GPU 释放，num_pipelines 有空间上调。', en: 'Local GPU freed, so num_pipelines can grow.' },
        cost: { zh: '每轮多一次网络往返，20s 读取超时是源码常量。', en: 'Per-turn RTT plus a 20s source-constant timeout.' },
        risk: { zh: '启动生效；配错表现为 404/502。', en: 'Start-only; a wrong host shows up as 404/502.' } },
      { p: 'llm.responses_api_api_key', v: '{env: GPUSTACK_API_KEY}', ref: 'catalog §4.3 · §6.7',
        why: { zh: '用 {env: NAME} 形式让密钥不落文件。', en: 'The env reference form keeps the secret out of the file.' },
        gain: { zh: '换密钥不用改 YAML。', en: 'Rotatable without touching the YAML.' },
        cost: { zh: '部署多一层环境依赖。', en: 'The deployment depends on env provisioning first.' },
        risk: { zh: 'ops 级、安全类别：.env 不得入仓，控制台只写不回显。', en: 'ops-level, security class: never commit the .env; write-only in console.' } },
      { p: 'llm.responses_api_reasoning_effort', v: 'none', ref: 'catalog §4.3',
        why: { zh: 'none 是跨后端安全取值。', en: 'none is the portable safe value.' },
        gain: { zh: '首 token 不再被上游推理强度拖住。', en: 'First-token latency stops depending on upstream reasoning.' },
        cost: { zh: '对期望显式 effort 的网关少一个提示。', en: 'One fewer hint for gateways expecting an explicit effort.' },
        risk: { zh: '启动生效；照搬另一后端写法会拿到非法值。', en: 'Start-only; copying another backend spelling yields illegal values.' } },
      { p: 'platform.num_pipelines', v: '4', ref: 'catalog §6.1',
        why: { zh: '本地不放权重时，每路 4.6GB 口径不再成立。', en: 'Without local weights the 4.6GB per-slot figure no longer applies.' },
        gain: { zh: '单机可并发更多会话。', en: 'More concurrent sessions per box.' },
        cost: { zh: '必须重新实测每路占用。', en: 'Per-slot usage must be re-measured.' },
        risk: { zh: '启动生效；池满即拒绝。', en: 'Start-only; the pool rejects when full.' } },
      { p: 'vad.smart_turn', v: 'false', ref: 'catalog §2.4',
        why: { zh: 'Smart Turn 权重本身就是本地模型，不跑本地模型的形态应关掉它。', en: 'Smart Turn weights are a local artifact; a no-local profile drops it.' },
        gain: { zh: '少一个需要分发与版本化的本地权重。', en: 'One less local weight to ship.' },
        cost: { zh: '判停回到纯静音规则。', en: 'Endpointing returns to silence-only rules.' },
        risk: { zh: '启动生效。', en: 'Start-only.' } }
    ]
  },
  {
    key: 'meeting',
    cross: true,
    note: { zh: '多人会议需要标记谁说的：开分离不配模型会启动失败，且要先降并发（手册 S16、目录 §6.4）。', en: 'Multi-speaker meetings: enabling diarization without its model fails startup, and concurrency must shrink first (playbook S16, catalog §6.4).' },
    items: [
      { p: 'platform.diarization', v: 'true', ref: 'catalog §6.4',
        why: { zh: '不开就没有说话人归属。', en: 'Without it there is no speaker attribution.' },
        gain: { zh: '转写带说话人标记。', en: 'Transcripts carry who-spoke markers.' },
        cost: { zh: '与 STT/TTS 一起进显存预算。', en: 'Extra VRAM alongside STT and TTS.' },
        risk: { zh: '启动生效；不配模型名会启动失败。', en: 'Start-only; enabling without diarization_model_name fails.' } },
      { p: 'platform.diarization_model_name', v: '本地 checkpoint 路径', ref: 'catalog §6.4',
        why: { zh: '必配项；固定 revision 以免上游权重漂移。', en: 'Mandatory companion; pin a revision.' },
        gain: { zh: '说话人聚类结果可复现。', en: 'Reproducible speaker clustering.' },
        cost: { zh: '离线首启需额外预置权重。', en: 'Another weight to cache for offline starts.' },
        risk: { zh: '启动生效、expert 级；hub id 写错会失败。', en: 'Start-only, expert-level; a wrong hub id fails.' } },
      { p: 'platform.diarization_threshold', v: '0.55', ref: 'catalog §6.4',
        why: { zh: '会议室混响下默认 0.5 会把安静的人拆成多余说话人。', en: 'Default 0.5 splits quiet speakers in a reverberant room.' },
        gain: { zh: '幽灵说话人减少。', en: 'Fewer phantom speakers.' },
        cost: { zh: '轻声轮次开始漏检。', en: 'Quiet turns start being missed.' },
        risk: { zh: '启动生效；越界值校验失败。', en: 'Start-only; out-of-range values fail validation.' } }
    ]
  }
]

export const sceneBykey = (key: string): SceneProto | null =>
  SCENE_PROTOS.find((scene) => scene.key === key) ?? null

/** 与后端 template_service.SCENE_KEYS 同源维护。 */
export const SCENE_KEYS = SCENE_PROTOS.map((scene) => scene.key)
