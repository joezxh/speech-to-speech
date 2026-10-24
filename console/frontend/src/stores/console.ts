import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, AppError } from '@/api/client'
import type { StatusSnapshot } from '@/types/api'
import { readProfile, saveProfile } from '@/utils/storage'

export const useConsoleStore = defineStore('console', () => {
  const profile = ref(readProfile())
  const status = ref<StatusSnapshot | null>(null)
  const statusError = ref('')
  let timer: number | undefined

  async function refreshStatus(): Promise<void> {
    try {
      status.value = await api.get<StatusSnapshot>('/status', { params: { profile: profile.value } })
      statusError.value = ''
    } catch (error) {
      // A dead backend is a state the top bar must show, not an exception the
      // layout should blow up on.
      status.value = null
      statusError.value = error instanceof AppError ? error.message : '状态不可读'
    }
  }

  function selectProfile(next: string): void {
    profile.value = next
    saveProfile(next)
    void refreshStatus()
  }

  function startPolling(intervalMs = 15_000): void {
    stopPolling()
    void refreshStatus()
    timer = window.setInterval(() => void refreshStatus(), intervalMs)
  }

  function stopPolling(): void {
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  return { profile, status, statusError, refreshStatus, selectProfile, startPolling, stopPolling }
})
