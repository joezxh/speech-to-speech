import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const target = process.env.VITE_DEV_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 3000,
    proxy: {
      '/api': { target, changeOrigin: true },
      '/vendor': { target, changeOrigin: true },
      // ws:true is what makes the voice page work against a local backend:
      // the browser dials /v1/realtime on :3000 and Vite upgrades the socket.
      '/v1': { target, changeOrigin: true, ws: true }
    }
  },
  build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false }
})
