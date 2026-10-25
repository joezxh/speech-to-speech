import { defineStore } from 'pinia'
import { ref } from 'vue'

import { AppError } from '@/api/client'
import { fetchRuntime } from '@/api/runtime'
import type { RuntimeSnapshot } from '@/types/runtime'

/** A.14 的采集预算是 2s、服务端缓存 3s，5s 一拉刚好每次都是新帧。 */
const POLL_MS = 5000

export const useRuntimeStore = defineStore('runtime', () => {
  const snapshot = ref<RuntimeSnapshot | null>(null)
  const loading = ref(false)
  const error = ref('')
  let timer: number | undefined
  let profile = ''
  let inFlight = false

  async function refresh(): Promise<void> {
    if (!profile || inFlight) return
    inFlight = true
    loading.value = true
    try {
      snapshot.value = await fetchRuntime(profile)
      error.value = ''
    } catch (caught) {
      // 保留上一帧：一次采样失败不等于「模型消失了」（A.14）。清空会让四张卡
      // 在同一秒里从「已加载」跳到「未知」，看着像事故。
      error.value = caught instanceof AppError ? caught.message : '模型运行时不可读'
    } finally {
      loading.value = false
      inFlight = false
    }
  }

  function startPolling(next: string): void {
    profile = next
    stopPolling()
    void refresh()
    timer = window.setInterval(() => void refresh(), POLL_MS)
  }

  /** 切页即停：页签不可见时也停（§3.9.1 第 4 条）。 */
  function stopPolling(): void {
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  function reset(): void {
    stopPolling()
    snapshot.value = null
    error.value = ''
    profile = ''
  }

  return { snapshot, loading, error, refresh, startPolling, stopPolling, reset }
})
