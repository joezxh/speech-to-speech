<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { VersionRow } from '@/types/profile'
import { formatDuration, formatTime } from '@/utils/format'

const { t } = useI18n()
const props = defineProps<{ rows: VersionRow[]; loading?: boolean; liveVersion?: number | null }>()
const emit = defineEmits<{ rollback: [version: number] }>()

const data = computed(() =>
  props.rows.map((row) => ({ ...row, key: row.version, createdAtText: formatTime(row.createdAt) }))
)
</script>

<template>
  <a-table
    size="small"
    :data-source="data"
    :loading="loading"
    :pagination="false"
    :columns="[
      { title: t('release.columns.version'), dataIndex: 'version', key: 'version', width: 80 },
      { title: t('release.columns.status'), dataIndex: 'status', key: 'status', width: 110 },
      { title: t('release.columns.author'), dataIndex: 'author', key: 'author', width: 120 },
      { title: t('release.columns.time'), dataIndex: 'createdAtText', key: 'createdAt', width: 170 },
      { title: t('release.columns.duration'), dataIndex: 'durationS', key: 'durationS', width: 90 },
      { title: t('release.columns.note'), dataIndex: 'note', key: 'note' },
      { title: t('release.columns.actions'), key: 'actions', width: 130 }
    ]"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'status'">
        <a-tag :color="record.status === 'live' ? 'green' : record.status === 'failed' ? 'red' : 'default'">
          {{ record.status }}
        </a-tag>
      </template>
      <template v-else-if="column.key === 'durationS'">
        {{ formatDuration(record.durationS) }}
      </template>
      <template v-else-if="column.key === 'note'">
        <span>{{ record.note || '—' }}</span>
        <a-tag v-if="record.rolledBackTo" color="orange">{{ t('release.rolledBackFrom', { version: record.rolledBackTo }) }}</a-tag>
      </template>
      <template v-else-if="column.key === 'actions'">
        <a-button
          v-if="record.status === 'live' || record.status === 'rolled_back'"
          type="link"
          size="small"
          :disabled="record.version === liveVersion"
          @click="emit('rollback', record.version)"
        >
          {{ t('release.rollbackToThis') }}
        </a-button>
        <span v-else>—</span>
      </template>
    </template>
  </a-table>
</template>
