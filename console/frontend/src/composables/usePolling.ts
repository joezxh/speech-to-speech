import { onBeforeUnmount, ref } from 'vue'

export interface Polling {
  active: import('vue').Ref<boolean>
  start: () => void
  stop: () => void
  refresh: () => Promise<void>
}

/**
 * 定时间隔轮询，且保证两次执行不重叠：`/instances` 要探 pool 和 supervisor，
 * 一次可能要好几秒，重叠后请求会跷起。
 */
export function usePolling(task: () => Promise<void>, intervalMs = 5000): Polling {
  const active = ref(false)
  let timer: number | undefined
  let running = false

  async function refresh(): Promise<void> {
    if (running) return
    running = true
    try {
      await task()
    } finally {
      running = false
    }
  }

  function stop(): void {
    active.value = false
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  function start(): void {
    stop()
    active.value = true
    void refresh()
    timer = window.setInterval(() => void refresh(), intervalMs)
  }

  onBeforeUnmount(stop)

  return { active, start, stop, refresh }
}
