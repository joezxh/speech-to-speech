<script setup lang="ts">
import { computed } from 'vue'

import type { AuditRow } from '@/types/profile'
import { formatDuration, formatTime } from '@/utils/format'

const props = defineProps<{ rows: AuditRow[]; loading?: boolean }>()

const data = computed(() => props.rows.map((row) => ({ ...row, key: row.auditId, atText: formatTime(row.at) })))

// 列必须走 `props.columns`：ant-design-vue 4 只认 `columns` 属性或默认插槽里的
// `a-table-column`，`<template #columns>` 会被静默忽略（表格零列）。
const columns = [
  { title: '时间', dataIndex: 'atText', key: 'at', width: 170 },
  { title: '操作人', dataIndex: 'actor', key: 'actor', width: 120 },
  { title: '动作', dataIndex: 'action', key: 'action', width: 130 },
  { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
  { title: '结果', key: 'result', width: 100 },
  { title: '字段（仅名称）', key: 'fields' },
  { title: '耗时', key: 'durationS', width: 90 },
  { title: '错误码', dataIndex: 'errorCode', key: 'errorCode', width: 160 }
]
</script>

<template>
  <a-table size="small" :data-source="data" :loading="loading" :pagination="false" :columns="columns">
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'result'">
        <a-tag :color="record.result === 'ok' ? 'green' : 'red'">{{ record.result }}</a-tag>
      </template>
      <template v-else-if="column.key === 'fields'">
        <a-tag v-for="field in record.fields" :key="field" class="audit-table__field">{{ field }}</a-tag>
        <span v-if="!record.fields.length">—</span>
      </template>
      <template v-else-if="column.key === 'durationS'">
        {{ formatDuration(record.durationS) }}
      </template>
    </template>
  </a-table>
</template>

<style scoped lang="less">
.audit-table__field {
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 2px;
}
</style>
