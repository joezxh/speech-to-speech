# 语音转口型（Speech to visemes）

这个可选阶段将 Fabio Catania（@fabiocat93）的 [PR #99](https://github.com/huggingface/speech-to-speech/pull/99) 适配到当前流水线，并解决了 [issue #37](https://github.com/huggingface/speech-to-speech/issues/37)。它保留了原有的音素到口型（viseme）映射以及 Wav2Vec2 提取方法。

通过现有的服务器或本地配置启用它：

```bash
speech-to-speech serve --enable_visemes --stv_device cpu
```

默认检查点（checkpoint）是 `bookbot/wav2vec2-ljspeech-gruut`。它会在首次使用时下载，基于英语音素训练。其[模型卡](https://huggingface.co/bookbot/wav2vec2-ljspeech-gruut)描述了训练数据和音素词表。映射表中虽然包含其它语言，但这并不意味着该检查点是多语言的。如需其它语言，请用 `--stv_model_name` 选择一个兼容的 16 kHz CTC 音素检查点。`--stv_device auto` 会选择一个可用的 CUDA、MPS 或 CPU 设备；全局的 `--device` 会覆盖它。该阶段默认不启用，因此关闭口型功能不需要额外的模型下载、内存、预热或缓冲。

## 客户端事件

该阶段会在现有的 Realtime WebSocket 或 WebRTC 数据通道上添加一个 JSON 扩展事件。它不新增端点，也不使用 pickle 序列化。标准音频事件和 RTP 音频保持不变。

```json
{
  "type": "speech_to_speech.output_audio.visemes",
  "event_id": "event_...",
  "response_id": "resp_...",
  "item_id": "item_...",
  "output_index": 0,
  "content_index": 0,
  "visemes": [
    {"viseme": 21, "start_s": 0.02, "end_s": 0.08},
    {"viseme": 6, "start_s": 0.08, "end_s": 0.15}
  ]
}
```

ID 0 到 21 使用原有的、与 Microsoft 兼容的口型映射。每个提示（cue）都带有以秒为单位的区间，相对于该响应生成音频的起点计算，覆盖其所有音频 item。该偏移量跨推理批次连续累加，并在下一个响应时重置。`item_id` 标识承载该批次的助手（assistant）item。复合音素会产生连续的口型区间。映射前会移除 IPA 重音符号。未映射的音素不产生提示。

服务端会在对应音频之前提交口型事件。WebSocket 会保持此消息顺序。WebRTC 使用独立的数据通道和媒体通道，因此无法保证口型事件在对应音频播放之前到达。请参阅 [OpenAI 的传输指南](https://developers.openai.com/api/docs/guides/realtime-conversations#push-to-talk)。请根据实际音频播放（包括客户端缓冲）来调度口型，而不是依据事件的到达时间。当被打断或响应取消时，丢弃已缓冲音频对应的已调度口型，并将嘴型恢复为静止状态。如果你的客户端只需要音频，可以忽略扩展事件。输出重采样会改变采样数量，但不会改变这些时间单位。

浏览器端的 `S2sRealtimeClient` 会向虚拟形象（avatar）消费者暴露该事件：

```javascript
client.addEventListener("visemes", ({ detail }) => {
  avatar.queueVisemes(detail.response_id, detail.visemes);
});
```

这个钩子只负责转发提示；动画和播放时钟由 avatar 自己管理。

## 缓冲与失败行为

在发送每个批次之前，提取过程会缓冲最多 0.5 秒的音频，外加模型推理时间。较短的回复和结尾的尾部音频会在响应完成时、或在有序的文本/工具事件之前被冲刷（flush）。短片段上的推理准确度可能较低。对极短输入做填充只影响模型推理；客户端音频样本会被精确保留。

提取失败时会记录一条错误日志，并保留音频播放和响应完成流程。监听、打断和响应完成仍由当前流水线控制。取消操作会同时丢弃过期的音频和提示。会话结束时会清除所有缓冲音频和计时状态，之后该单元才可被复用。
