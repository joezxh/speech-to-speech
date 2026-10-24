<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ draft: Record<string, unknown>; masked: string[] }>()

interface Row {
  key: string
  value: string
}

const columns = [
  { title: '字段', dataIndex: 'key', key: 'key' },
  { title: '草稿值', dataIndex: 'value', key: 'value' }
]

const rows = computed<Row[]>(() =>
  Object.keys(props.draft)
    .sort()
    .map((key) => ({
      key,
      value: props.masked.includes(key) ? '***' : JSON.stringify(props.draft[key])
    }))
)
</script>

<template>
  <a-table
    size="small"
    :data-source="rows"
    :pagination="false"
    :columns="columns"
    row-key="key"
  />
</template>
