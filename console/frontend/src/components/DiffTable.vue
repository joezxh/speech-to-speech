<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ draft: Record<string, unknown>; masked: string[] }>()
const { t } = useI18n()

interface Row {
  key: string
  value: string
}

const columns = computed(() => [
  { title: t('deploy.diffField'), dataIndex: 'key', key: 'key' },
  { title: t('deploy.diffDraftValue'), dataIndex: 'value', key: 'value' }
])

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
