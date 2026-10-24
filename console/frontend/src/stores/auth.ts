import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import * as authApi from '@/api/auth'
import type { TokenBundle, User } from '@/types/api'
import { clearSession, readBundle, saveBundle } from '@/utils/storage'

export const useAuthStore = defineStore('auth', () => {
  const bundle = ref<TokenBundle | null>(readBundle())
  const user = computed<User | null>(() => bundle.value?.user ?? null)
  const signedIn = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function login(username: string, password: string): Promise<void> {
    const next = await authApi.login(username, password)
    bundle.value = next
    saveBundle(next)
  }

  function logout(): void {
    bundle.value = null
    clearSession()
  }

  return { bundle, user, signedIn, isAdmin, login, logout }
})
