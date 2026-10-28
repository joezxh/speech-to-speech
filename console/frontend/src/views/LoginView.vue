<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { AppError } from '@/api/client'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const pending = ref(false)
const failure = ref<AppError | null>(null)

// Only same-site root-relative paths are acceptable as a landing target: an
// open redirect on a login form is a phishing primitive. Allow `/`（对话面）and
// `/console*`, but reject protocol-relative `//host` and absolute URLs.
const next = computed(() => {
  const value = route.query.next
  const safe = typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
  return safe ? value : '/console'
})

async function submit(): Promise<void> {
  failure.value = null
  pending.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    password.value = '' // the password does not outlive the request
    await router.replace(next.value)
  } catch (error) {
    failure.value =
      error instanceof AppError ? error : new AppError('unknown', '登录失败，请重试')
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="login">
    <form class="login__card" @submit.prevent="submit">
      <h1 class="login__title">S2S 控制台</h1>

      <label class="login__label" for="username">用户名</label>
      <a-input id="username" v-model:value="username" autocomplete="username" :disabled="pending" />

      <label class="login__label" for="password">密码</label>
      <a-input-password
        id="password"
        v-model:value="password"
        autocomplete="current-password"
        :disabled="pending"
      />

      <ErrorBanner :error="failure" />

      <a-button type="primary" html-type="submit" block :loading="pending">登录</a-button>
    </form>
  </div>
</template>

<style scoped lang="less">
.login {
  align-items: center;
  display: flex;
  justify-content: center;
  min-height: 100vh;

  &__card {
    background: var(--s2s-color-surface);
    border-radius: 10px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 28px;
    width: 320px;
  }

  &__title {
    color: var(--s2s-color-text);
    font-size: 16px;
    margin: 0 0 8px;
  }

  &__label {
    color: var(--s2s-color-muted);
    font-size: 12px;
  }
}
</style>
