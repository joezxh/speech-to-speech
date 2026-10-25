<script setup lang="ts">
import { computed } from 'vue'

import type { MeResponse } from '../types'

const props = defineProps<{ me: MeResponse }>()
const emit = defineEmits<{ (e: 'limit'): void }>()

const PRO_URL = 'https://huggingface.co/subscribe/pro'
const unlimited = computed(() => props.me.tier === 'pro' || props.me.tier === 'org')
const remaining = computed(() => {
  if (!props.me.enabled) return ''
  if (unlimited.value || props.me.remainingSec == null) return 'Unlimited'
  return `${Math.max(0, Math.floor(props.me.remainingSec / 60))} min left today`
})
// 额度已耗尽时点胶囊直接弹限制卡，而不是让用户自己去找。
const spent = computed(() => !unlimited.value && props.me.remainingSec != null && props.me.remainingSec <= 0)
</script>

<template>
  <!-- 未开启账号体系时整块不渲染（§14.5 第八条） -->
  <template v-if="props.me.enabled">
    <a v-if="!props.me.loggedIn && props.me.auth && props.me.loginUrl" class="v-account v-account--signin" :href="props.me.loginUrl">
      Sign in for more time
    </a>
    <a-popover v-else-if="props.me.loggedIn" placement="bottomRight" trigger="click">
      <template #content>
        <p class="v-account__tier">{{ props.me.tier === 'pro' ? 'PRO' : props.me.tier === 'org' ? 'Team' : 'Free' }}</p>
        <p class="v-account__remaining">{{ remaining }}</p>
        <a v-if="!unlimited" class="v-account__link" :href="PRO_URL" target="_blank" rel="noopener">Upgrade to PRO</a>
        <a class="v-account__link" :href="props.me.logoutUrl || '#'">Sign out</a>
      </template>
      <button class="v-account" :class="{ 'is-spent': spent }" @click="spent && emit('limit')">
        <img v-if="props.me.avatar" class="v-account__avatar" :src="props.me.avatar" alt="" width="20" height="20" />
        <span>{{ props.me.username || 'you' }}</span>
      </button>
    </a-popover>
  </template>
</template>
