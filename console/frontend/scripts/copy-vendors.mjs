// Copy browser-only third-party bundles into public/vendor at build time.
// Spec D10: the runtime image has no node_modules, so a missing asset must
// fail the build here instead of returning 503 at 3am.
import { access, cp, mkdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const vendor = join(root, 'public', 'vendor')
const vad = join(vendor, 'local-vad')

const UMD = ['@openai/agents-realtime', 'dist', 'bundle', 'openai-realtime-agents.umd.js']
const VAD_WEB = ['bundle.min.js', 'vad.worklet.bundle.min.js', 'silero_vad_v6.onnx']
const ORT = ['ort.wasm.min.js', 'ort-wasm-simd-threaded.mjs', 'ort-wasm-simd-threaded.wasm']

await mkdir(vad, { recursive: true })
await cp(join(root, 'node_modules', ...UMD), join(vendor, 'openai-realtime-agents.umd.js'))
for (const file of VAD_WEB) {
  await cp(join(root, 'node_modules', '@ricky0123', 'vad-web', 'dist', file), join(vad, file))
}
for (const file of ORT) {
  await cp(join(root, 'node_modules', 'onnxruntime-web', 'dist', file), join(vad, file))
}

for (const file of [...VAD_WEB, ...ORT]) await access(join(vad, file))
await access(join(vendor, 'openai-realtime-agents.umd.js'))
console.log(`[copy-vendors] 7 assets -> public/vendor`)
