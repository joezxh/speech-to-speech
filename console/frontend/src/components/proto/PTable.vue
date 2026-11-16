<template>
  <div class="tscroll">
    <table class="tbl">
      <thead>
        <tr>
          <th
            v-for="col in columns"
            :key="col.key"
            :class="[col.cls, col.sticky === 'start' ? 'sticky-start' : '', col.sticky === 'end' ? 'sticky-end' : '']"
            :style="col.width ? { width: typeof col.width === 'number' ? col.width + 'px' : col.width } : undefined"
          >
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in rows"
          :key="rowKey ? String(row[rowKey]) : index"
          :class="{ clickable: clickable, selected: rowKey && selected === row[rowKey] }"
          @click="onRowClick(row)"
        >
          <td
            v-for="col in columns"
            :key="col.key"
            :class="[col.cls, col.sticky === 'start' ? 'sticky-start' : '', col.sticky === 'end' ? 'sticky-end' : '']"
          >
            <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">{{ row[col.key] }}</slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
export interface PColumn {
  key: string
  label: string
  width?: number | string
  sticky?: 'start' | 'end'
  cls?: string
}

defineProps<{
  columns: PColumn[]
  rows: Record<string, unknown>[]
  rowKey?: string
  clickable?: boolean
  selected?: string
}>()

const emit = defineEmits<{ (e: 'row-click', row: Record<string, unknown>): void }>()

function onRowClick(row: Record<string, unknown>): void {
  emit('row-click', row)
}
</script>

<style scoped>
.tbl :deep(th.sticky-start),
.tbl :deep(td.sticky-start) {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--s2s-color-surface-2);
}
.tbl :deep(th.sticky-end),
.tbl :deep(td.sticky-end) {
  position: sticky;
  right: 0;
  z-index: 1;
  background: var(--s2s-color-surface-2);
  border-left: 1px solid var(--s2s-color-border);
}
</style>
