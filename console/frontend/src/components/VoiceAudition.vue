<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  src: string
  /** 整段音频长度，滑块的右边界。 */
  durationMs: number
  trimStartMs: number
  trimEndMs: number
}>()

const emit = defineEmits<{ 'update:trim': [startMs: number, endMs: number] }>()

/**
 * 48 根占位柱：真波形要从 WAV 解 PCM，`<audio>` 给不了；这里只画形状，
 * 免得界面看起来像“分析过音频”。
 */
const BARS = Array.from({ length: 48 }, (_, index) => 22 + Math.round(60 * Math.abs(Math.sin(index * 0.7))))

const endMs = computed(() => (props.trimEndMs > 0 ? props.trimEndMs : props.durationMs))

const startTip = (value: number): string => `${(value / 1000).toFixed(2)} s`
const endTip = (value: number): string => `${(value / 1000).toFixed(2)} s`

function onStart(value: number): void {
  // 起点不能越过终点：至少留 200 ms，否则后端会得到一段空音频。
  emit('update:trim', Math.max(0, Math.min(value, endMs.value - 200)), endMs.value)
}

function onEnd(value: number): void {
  emit('update:trim', props.trimStartMs, Math.max(props.trimStartMs + 200, Math.min(value, props.durationMs)))
}
</script>

<template>
  <div class="audition">
    <audio :src="src" controls preload="none" class="audition__player" />

    <div class="audition__wave" aria-hidden="true">
      <span
        v-for="(height, index) in BARS"
        :key="index"
        class="audition__bar"
        :style="{ height: `${height}%` }"
      />
    </div>

    <div class="audition__trim">
      <label class="audition__row">
        <span>起点</span>
        <a-slider
          :value="trimStartMs"
          :min="0"
          :max="durationMs"
          :step="10"
          :tip-formatter="startTip"
          class="audition__slider"
          @change="onStart"
        />
      </label>
      <label class="audition__row">
        <span>终点</span>
        <a-slider
          :value="endMs"
          :min="0"
          :max="durationMs"
          :step="10"
          :tip-formatter="endTip"
          class="audition__slider"
          @change="onEnd"
        />
      </label>
      <p class="audition__hint">
        裁剪只改元数据：保存时按区间重写 WAV，服务端不需要重新解码整段（§3.11.2 步骤 3）。
        区间 {{ (trimStartMs / 1000).toFixed(2) }} – {{ (endMs / 1000).toFixed(2) }} s
      </p>
    </div>
  </div>
</template>

<style scoped lang="less">
.audition {
  display: flex;
  flex-direction: column;
  gap: 10px;

  &__player {
    width: 100%;
  }

  &__wave {
    align-items: center;
    background: #101728;
    border-radius: 8px;
    display: flex;
    gap: 2px;
    height: 64px;
    padding: 0 8px;
  }

  &__bar {
    background: linear-gradient(180deg, #4d7cff, #2a3f7a);
    border-radius: 1px;
    flex: 1;
  }

  &__row {
    align-items: center;
    display: flex;
    gap: 8px;

    > span {
      color: #8b93a7;
      font-size: 12px;
      width: 28px;
    }
  }

  &__slider {
    flex: 1;
  }

  &__hint {
    color: #6f7891;
    font-size: 12px;
    margin: 0;
  }
}
</style>
