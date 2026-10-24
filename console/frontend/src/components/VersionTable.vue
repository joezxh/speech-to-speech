<script setup lang="ts">
import { computed } from 'vue'

import type { VersionRow } from '@/types/profile'
import { formatDuration, formatTime } from '@/utils/format'

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
      { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
      { title: '状态', dataIndex: 'status', key: 'status', width: 110 },
      { title: '作者', dataIndex: 'author', key: 'author', width: 120 },
      { title: '时间', dataIndex: 'createdAtText', key: 'createdAt', width: 170 },
      { title: '耗时', dataIndex: 'durationS', key: 'durationS', width: 90 },
      { title: '说明', dataIndex: 'note', key: 'note' },
      { title: '操作', key: 'actions', width: 130 }
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
        <a-tag v-if="record.rolledBackTo" color="orange">回滚自 v{{ record.rolledBackTo }}</a-tag>
      </template>
      <template v-else-if="column.key === 'actions'">
        <a-button
          v-if="record.status === 'live' || record.status === 'rolled_back'"
          type="link"
          size="small"
          :disabled="record.version === liveVersion"
          @click="emit('rollback', record.version)"
        >
          回滚到此版本
        </a-button>
        <span v-else>—</span>
      </template>
    </template>
  </a-table>
</template>
