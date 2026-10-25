<script setup lang="ts">
import { computed } from 'vue'

import type { VoiceState } from '../types'

const props = defineProps<{
  state: VoiceState
  levelDb: number
  caption: string
  subCaption: string
  tone: 'info' | 'error'
}>()
const emit = defineEmits<{ (e: 'activate'): void }>()

/** demo/main.js 的六个指示器：球心随状态换图形，而不是只有一个光斑。 */
type Indicator = 'mic' | 'error' | 'spinner' | 'dots' | 'bars' | 'voice'

const INDICATOR: Record<VoiceState, Indicator> = {
  idle: 'mic',
  connecting: 'spinner',
  queued: 'spinner',
  'your-turn': 'mic',
  listening: 'bars',
  'user-speaking': 'bars',
  processing: 'dots',
  'ai-speaking': 'voice',
  error: 'error'
}

const indicator = computed(() => INDICATOR[props.state])
// 只有待机与出错时球体才是一个按钮；通话中它只是显示器。
const activatable = computed(() => props.state === 'idle' || props.state === 'error')
// 电平只允许驱动光晕，且只在通话中：待机时的环境噪声不该让球体发亮。
const glow = computed(() => (activatable.value ? 0 : Math.min(1, Math.max(0, (props.levelDb + 60) / 60))))
</script>

<template>
  <div class="v-orb-wrap">
    <slot name="left" />
    <button
      class="v-orb"
      :data-state="props.state"
      :disabled="!activatable"
      :aria-label="props.caption || props.state"
      :style="{ '--glow-strength': glow }"
      @click="activatable && emit('activate')"
    >
      <span class="v-orb__glow" aria-hidden="true" />
      <span class="v-orb__ring" aria-hidden="true" />
      <span class="v-orb__ring v-orb__ring--outer" aria-hidden="true" />
      <span class="v-orb__core">
        <span class="v-orb__ind">
          <svg v-if="indicator === 'mic'" class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-mic" /></svg>
          <svg v-else-if="indicator === 'error'" class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-info" /></svg>
          <span v-else-if="indicator === 'spinner'" class="v-spinner" />
          <span v-else-if="indicator === 'dots'" class="v-dots"><i /><i /><i /></span>
          <span v-else-if="indicator === 'bars'" class="v-bars"><i v-for="n in 5" :key="n" /></span>
          <svg v-else class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-voice" /></svg>
        </span>
      </span>
    </button>
    <slot name="right" />
  </div>

  <p class="v-caption" :class="{ 'v-caption--error': props.tone === 'error' }" role="status">{{ props.caption }}</p>
  <p v-if="props.subCaption" class="v-sub">{{ props.subCaption }}</p>
</template>
