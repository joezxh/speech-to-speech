import { MicVAD } from '@ricky0123/vad-web'

const ASSET_BASE = '/vendor/local-vad/'

export interface LocalVadOptions {
  stream: MediaStream
  isEnabled: () => boolean
  onChange: (speaking: boolean) => void
}

/**
 * Client-side barge-in aid. It never gates the uplink: the pipeline still runs
 * its own server VAD — this only lets the orb react before the server answers.
 */
export async function startLocalVad(options: LocalVadOptions): Promise<{ destroy: () => Promise<void> }> {
  const vad = await MicVAD.new({
    baseAssetPath: ASSET_BASE,
    onnxWASMBasePath: ASSET_BASE,
    // vad-web 0.0.31 的默认模型是 `legacy`（会去拉 silero_vad_legacy.onnx），
    // 而 copy-vendors 只发布 silero_vad_v6.onnx：不显式指定就是 404 + ORT 报错。
    model: 'v6',
    startOnLoad: false,
    processorType: 'AudioWorklet',
    audioContext: undefined,
    // 回调必须返回 `void`：写成 `() => cond && cb()` 会把 boolean 交给 SDK 的类型。
    onSpeechStart: () => {
      if (options.isEnabled()) options.onChange(true)
    },
    onSpeechEnd: () => options.onChange(false)
  })
  await vad.start()
  return {
    destroy: async () => {
      await vad.destroy()
    }
  }
}
