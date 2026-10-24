import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// `formatTime` renders the local wall clock (spec A.0), so an assertion on an
// exact string only holds when the test process has a known zone. Node reads TZ
// on first Date use, which happens after this file is evaluated, so pinning it
// here keeps the suite deterministic on a dev box in UTC+8 and on CI in UTC.
process.env.TZ = 'UTC'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    environment: 'node',
    include: ['src/**/*.spec.ts'],
    reporters: 'dot'
  }
})
