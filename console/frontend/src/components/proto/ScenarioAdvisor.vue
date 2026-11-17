<script setup lang="ts">
import { computed } from 'vue'

import { applyScenario, diffRows, type Scene } from '@/views/deploy.viewmodel'

const props = defineProps<{ scenes: Scene[]; actual: Record<string, string>; patch: Record<string, string> }>()
const emit = defineEmits<{ apply: [patch: Record<string, string>] }>()

const selected = defineModel<Scene | null>({ default: null })
const diff = computed(() => (selected.value ? diffRows(selected.value, props.actual) : []))
const changed = computed(() => (selected.value ? applyScenario(selected.value, props.patch) : {}))

function apply(): void {
  if (selected.value) emit('apply', changed.value)
}
</script>

<template>
  <div class="scenario-advisor">
    <div class="chips">
      <button v-for="scene in scenes" :key="scene.name" class="chip" :class="{ active: selected?.name === scene.name }" @click="selected = scene">
        {{ scene.name }}
      </button>
    </div>
    <template v-if="selected">
      <div class="reason-grid">
        <div><strong>why</strong><p>{{ selected.why }}</p></div>
        <div><strong>gain</strong><p>{{ selected.gain }}</p></div>
        <div><strong>cost / risk</strong><p>{{ selected.cost }} · {{ selected.risk }}</p></div>
      </div>
      <table class="tbl"><thead><tr><th>key</th><th>current</th><th>suggested</th><th>state</th></tr></thead><tbody>
        <tr v-for="row in diff" :key="row.key">
          <td>{{ row.key }}</td><td>{{ row.current || '—' }}</td><td>{{ row.suggested }}</td><td>{{ row.state }}</td>
        </tr>
      </tbody></table>
      <button class="apply" @click="apply">应用到草稿</button>
    </template>
  </div>
</template>

<style scoped lang="less">
.chips { display: flex; gap: 8px; margin-bottom: 12px; }
.chip { border: 1px solid var(--border); background: transparent; border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.chip.active { background: var(--accent); color: var(--surface); }
.reason-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.tbl { width: 100%; border-collapse: collapse; margin: 12px 0; }
.tbl th, .tbl td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.apply { background: var(--accent); color: var(--surface); border: 0; border-radius: 4px; padding: 6px 16px; cursor: pointer; }
</style>
