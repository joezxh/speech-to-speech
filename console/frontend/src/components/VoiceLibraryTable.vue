<script setup lang="ts">
import type { VoiceRow } from '@/types/voice-library'
import { formatSeconds, sourceText, statusText } from '@/utils/voice-text'

const props = defineProps<{ rows: VoiceRow[]; loading?: boolean }>()

const emit = defineEmits<{
  audition: [row: VoiceRow]
  duplicate: [row: VoiceRow]
  remove: [row: VoiceRow]
}>()

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '来源', key: 'source', width: 96 },
  { title: '后端', dataIndex: 'backend', key: 'backend', width: 140 },
  { title: '时长', key: 'audioSeconds', width: 88 },
  { title: '状态', key: 'status', width: 140 },
  { title: '引用', key: 'usedBy', width: 180 },
  { title: '操作', key: 'actions', width: 208 }
]

const STATUS_COLOR: Record<string, string> = {
  ready: 'green',
  precomputing: 'blue',
  failed: 'red',
  draft: 'default'
}

/** 引用列：草稿名 + 已发布版本数（A.18 的 `usedBy` 就是这两个字段）。 */
function usageText(row: Record<string, unknown>): string {
  const usedBy = (row.usedBy ?? {}) as { profiles?: unknown; versions?: unknown }
  const profiles = Array.isArray(usedBy.profiles) ? usedBy.profiles.map(String) : []
  const versions = typeof usedBy.versions === 'number' ? usedBy.versions : 0
  if (profiles.length === 0 && versions === 0) return '—'
  const parts: string[] = []
  if (profiles.length > 0) parts.push(`${profiles.join('、')}（草稿）`)
  if (versions > 0) parts.push(`${versions} 个版本`)
  return parts.join(' · ')
}

function progressOf(row: Record<string, unknown>): number | null {
  const precompute = row.precompute as { progress?: unknown } | undefined
  return typeof precompute?.progress === 'number' ? precompute.progress : null
}

function errorOf(row: Record<string, unknown>): string {
  const precompute = row.precompute as { errorCode?: unknown } | undefined
  return typeof precompute?.errorCode === 'string' ? precompute.errorCode : ''
}
</script>

<template>
  <a-table
    size="small"
    :data-source="rows"
    :columns="columns"
    :loading="loading"
    :pagination="false"
    row-key="id"
  >
    <template #bodyCell="{ column, record, index }">
      <template v-if="column.key === 'source'">{{ sourceText(record.source) }}</template>

      <template v-else-if="column.key === 'audioSeconds'">{{ formatSeconds(record.audioSeconds) }}</template>

      <template v-else-if="column.key === 'status'">
        <a-tag :color="STATUS_COLOR[String(record.status)] ?? 'default'">{{ statusText(record.status) }}</a-tag>
        <span v-if="progressOf(record) !== null" class="voice-table__progress">{{ progressOf(record) }}%</span>
        <a-tooltip v-if="errorOf(record)" :title="errorOf(record)">
          <span class="voice-table__error">{{ errorOf(record) }}</span>
        </a-tooltip>
      </template>

      <template v-else-if="column.key === 'usedBy'">{{ usageText(record) }}</template>

      <template v-else-if="column.key === 'actions'">
        <a-space size="small">
          <!-- 内置音色没有参考音频（`audio_seconds=0`），试听会是 410，直接禁掉。 -->
          <a-tooltip :title="Number(record.audioSeconds ?? 0) > 0 ? '' : '内置音色没有参考音频'">
            <a-button
              type="link"
              size="small"
              :disabled="Number(record.audioSeconds ?? 0) <= 0"
              @click="emit('audition', props.rows[index])"
            >
              试听
            </a-button>
          </a-tooltip>
          <a-button type="link" size="small" @click="emit('duplicate', props.rows[index])">复制</a-button>
          <a-button type="link" size="small" danger @click="emit('remove', props.rows[index])">删除</a-button>
        </a-space>
      </template>
    </template>
  </a-table>
</template>

<style scoped lang="less">
.voice-table {
  &__progress {
    color: #4d7cff;
    font-size: 12px;
    margin-left: 6px;
  }

  &__error {
    color: #d4380d;
    font-size: 12px;
    margin-left: 6px;
    text-decoration: underline dotted;
  }
}
</style>
