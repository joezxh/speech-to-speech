<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{ url: string; truncated: boolean; active: boolean }>()
const emit = defineEmits<{ (e: 'play'): void; (e: 'stop'): void }>()

const audio = ref<HTMLAudioElement | null>(null)

// 父级换了“当前播放的那一条”就把自己停下：同时两条原音会让回声抑制失效。
watch(
  () => props.active,
  (active) => {
    if (!active && audio.value && !audio.value.paused) audio.value.pause()
  }
)
</script>

<template>
  <div class="hist-audio">
    <span class="hist-audio__label">
      Audio sent to the model
      <template v-if="props.truncated">· beginning unavailable</template>
    </span>
    <audio
      ref="audio"
      :src="props.url"
      controls
      preload="metadata"
      aria-label="Replay your audio"
      :title="
        props.truncated
          ? 'Replay your audio (the beginning was no longer buffered)'
          : 'Replay the audio sent to the model'
      "
      @play="emit('play')"
      @pause="emit('stop')"
      @ended="emit('stop')"
      @error="emit('stop')"
    />
  </div>
</template>
