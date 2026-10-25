<script setup lang="ts">
import dayjs, { type Dayjs } from 'dayjs'
import { computed, onMounted } from 'vue'

import { useLogFollow } from '@/composables/useLogFollow'
import { useLogsStore } from '@/stores/logs'
import { formatTime } from '@/utils/format'
import type { LogLine } from '@/types/logs'

/**
 * A.15 的面板。只读：没有写入、没有删除、没有下载入口。
 *
 * 不引虚拟滚动：`limit` 上限 2000 行，量已经被钉死；为 2000 行引入一个滚动
 * 依赖，换来的是「滚动时行高跳动」这类新问题。
 */
const props = defineProps<{ live: boolean }>()
const emit = defineEmits<{ follow: [value: boolean]; refresh: []; analyze: [] }>()

const store = useLogsStore()
useLogFollow()

const PROCESS_OPTIONS = [
  { label: 'console', value: 'console' },
  { label: 'pipeline', value: 'pipeline' }
]
const LEVEL_OPTIONS = [
  { label: 'ERROR', value: 'ERROR' },
  { label: 'WARN', value: 'WARN' },
  { label: 'INFO', value: 'INFO' }
]

const range = computed<[Dayjs, Dayjs] | undefined>(() => {
  const { from, to } = store.filters
  return from && to ? [dayjs(from), dayjs(to)] : undefined
})

const cursorShort = computed(() => (store.nextCursor ? store.nextCursor.slice(-8) : '—'))

function onRangeChange(value: unknown): void {
  const picked = value as [Dayjs, Dayjs] | null
  store.filters.from = picked ? picked[0].toISOString() : ''
  store.filters.to = picked ? picked[1].toISOString() : ''
  void store.reload()
}

function levelClass(level: string): string {
  if (level === 'ERROR') return 'lv-e'
  if (level === 'WARN') return 'lv-w'
  return 'lv-i'
}

function lineKey(line: LogLine, index: number): string {
  return `${line.file}:${line.offset}:${index}`
}

onMounted(() => {
  if (!store.lines.length) void store.load(true)
})
</script>

<template>
  <section class="logs">
    <div class="logs__head">
      <span class="logs__title">日志</span>
      <a-select
        v-model:value="store.filters.process"
        mode="multiple"
        size="small"
        style="min-width: 180px"
        :options="PROCESS_OPTIONS"
        :max-tag-count="2"
        @change="store.reload()"
      />
      <a-select
        v-model:value="store.filters.level"
        mode="multiple"
        size="small"
        style="min-width: 160px"
        placeholder="全部级别"
        :options="LEVEL_OPTIONS"
        :max-tag-count="2"
        @change="store.reload()"
      />
      <a-range-picker
        size="small"
        show-time
        :value="range"
        :placeholder="['起始时间', '结束时间']"
        @change="onRangeChange"
      />
      <a-input-search
        v-model:value="store.filters.q"
        size="small"
        allow-clear
        :maxlength="200"
        placeholder="关键字（大小写不敏感）"
        style="width: 200px"
        @search="store.reload()"
      />
      <span class="logs__live">
        尾部跟随
        <a-switch
          size="small"
          :checked="props.live"
          @update:checked="emit('follow', $event as boolean)"
        />
      </span>
      <a-button size="small" :loading="store.loading" @click="emit('refresh')">刷新</a-button>
      <a-button size="small" type="primary" :loading="store.pending" @click="emit('analyze')">
        分析
      </a-button>
    </div>

    <a-alert v-if="store.error" type="error" show-icon :message="store.error" />
    <a-alert
      v-if="store.reset"
      type="warning"
      show-icon
      message="日志已轮转，已从头重读"
    />

    <pre v-if="store.lines.length" class="logs__body"><span
      v-for="(line, index) in store.lines"
      :key="lineKey(line, index)"
      class="logs__line"
    ><span class="t">{{ formatTime(line.ts) }}</span> <span class="p">{{ line.process }}</span> <span class="lv" :class="levelClass(line.level)">{{ line.level }}</span> <span class="m">{{ line.text }}</span>
</span></pre>
    <a-empty v-else :description="store.loading ? '读取中…' : '该时间窗没有日志行'" />

    <div class="logs__foot">
      <span>cursor {{ cursorShort }}</span>
      <span>{{ store.scanned.files }} 个文件 / {{ store.scanned.bytes }} 字节</span>
      <span v-if="store.truncated" class="logs__cut">已截断，缩小时间范围再看</span>
    </div>
  </section>
</template>

<style scoped lang="less">
.logs {
  display: flex;
  flex-direction: column;
  gap: 8px;

  &__head {
    align-items: center;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  &__title {
    font-size: 14px;
    font-weight: 600;
  }

  &__live {
    align-items: center;
    color: #8b93a7;
    display: inline-flex;
    font-size: 12px;
    gap: 6px;
    margin-left: auto;
  }

  &__body {
    background: #12151f;
    border: 1px solid #1c2130;
    border-radius: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    line-height: 1.5;
    margin: 0;
    max-height: 420px;
    overflow: auto;
    padding: 10px;
    white-space: pre-wrap;
    word-break: break-all;
  }

  &__line {
    display: block;
  }

  &__foot {
    color: #8b93a7;
    display: flex;
    font-size: 12px;
    gap: 16px;
  }

  &__cut {
    color: #f59e0b;
  }
}

.t {
  color: #6b7280;
}

.p {
  color: #60a5fa;
}

.lv-i {
  color: #9ca3af;
}

.lv-w {
  color: #f59e0b;
}

.lv-e {
  color: #ff6a75;
}

.m {
  color: #c8cede;
}
</style>
