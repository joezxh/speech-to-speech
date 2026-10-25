import { computed, onBeforeUnmount } from 'vue'

import { useLogsStore } from '@/stores/logs'

/**
 * 尾部跟随的开关。两条硬性约束：
 * 1. 组件卸载必须 `stop()`，否则离开实例页后还在每 2s 读一次日志；
 * 2. 页签不可见时也停 —— 与 `stores/runtime.ts` 同一条理由（§3.9.1 第 4 条）：
 *    console 与 pipeline 同容器，一个被遗忘的后台标签页是唯一可能伤到语音的东西。
 */
export function useLogFollow() {
  const store = useLogsStore()
  let resumeOnVisible = false

  function onVisibility(): void {
    if (document.hidden) {
      resumeOnVisible = store.live
      store.stop()
    } else if (resumeOnVisible) {
      resumeOnVisible = false
      store.follow()
    }
  }

  document.addEventListener('visibilitychange', onVisibility)

  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisibility)
    store.stop()
  })

  return {
    live: computed(() => store.live),
    toggle: () => (store.live ? store.stop() : store.follow()),
    stop: () => store.stop()
  }
}
