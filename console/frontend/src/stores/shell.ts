import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { VoiceOverlay } from '@/router/nav'

/** 折叠态是纯视图偏好，允许跨会话保留；整个应用只写这一个键。 */
const COLLAPSED_KEY = 's2s.shell.collapsed'

/** 抽屉阈值：与 `ConsoleLayout` 的 `@media (max-width: 979px)` 必须同值。 */
export const DRAWER_BREAKPOINT = 980

export const useShellStore = defineStore('shell', () => {
  const siderCollapsed = ref(localStorage.getItem(COLLAPSED_KEY) === '1')
  const drawerOpen = ref(false)
  const voiceOverlay = ref<VoiceOverlay | null>(null)
  /** 额度弹窗的请求信号：顶栏的账号 chip 在对话页之外，通过它与 VoiceView 通信。 */
  const limitOpen = ref(false)

  function toggleSider(): void {
    siderCollapsed.value = !siderCollapsed.value
    localStorage.setItem(COLLAPSED_KEY, siderCollapsed.value ? '1' : '0')
  }

  /** 小屏时侧栏是抽屉：点完导航必须自己关上，否则会把舞台挤没。 */
  function closeDrawer(): void {
    drawerOpen.value = false
  }

  function openOverlay(overlay: VoiceOverlay): void {
    voiceOverlay.value = overlay
    drawerOpen.value = false
  }

  function closeOverlay(): void {
    voiceOverlay.value = null
  }

  function openLimit(): void {
    limitOpen.value = true
  }

  function closeLimit(): void {
    limitOpen.value = false
  }

  return {
    siderCollapsed,
    drawerOpen,
    voiceOverlay,
    limitOpen,
    toggleSider,
    closeDrawer,
    openOverlay,
    closeOverlay,
    openLimit,
    closeLimit
  }
})
