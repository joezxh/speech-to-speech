<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ active: boolean }>()
const video = ref<HTMLVideoElement | null>(null)
const flashing = ref(false)
let timer = 0

/** 拍照时闪一下：用户能看见「它刚刚拍了一张」，而不是静默上传。 */
function flash(): void {
  flashing.value = true
  window.clearTimeout(timer)
  timer = window.setTimeout(() => (flashing.value = false), 240)
}

defineExpose({ video, flash })
</script>

<template>
  <div v-if="props.active" class="v-pip" aria-hidden="true">
    <video ref="video" class="v-pip__feed" autoplay playsinline muted />
    <span class="v-pip__flash" :class="{ 'is-on': flashing }" />
    <span class="v-pip__label">camera</span>
  </div>
</template>
