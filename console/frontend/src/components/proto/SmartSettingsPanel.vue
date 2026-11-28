<script setup lang="ts">
// 原型 smartPanel（前台/运维共用）：agent 拉取当前参数与日志 + AI 故障分析 + 逐条应用。
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useSmartSettingsStore } from '@/stores/smartSettings'

const props = defineProps<{ machineId: string; mode: 'live' | 'deploy' }>()
const emit = defineEmits<{ apply: [key: string, value: string] }>()
const { t } = useI18n()
const store = useSmartSettingsStore()

const fault = ref('')

watch(
  () => props.machineId,
  (value, previous) => {
    if (value && value !== previous) {
      store.reset()
      void store.fetch(value)
    }
  },
  { immediate: true }
)

function analyze(): void {
  void store.analyze(props.machineId, fault.value)
}

function apply(key: string, value: string): void {
  emit('apply', key, value)
}

/** 应用语义随模式不同：live=对话态热更（session.update），deploy=写机器草稿。 */
const applyHint = () =>
  props.mode === 'live' ? t('smart.appliedHint') : t('templates.panel.applyNote')
</script>

<template>
  <div class="ssp">
    <div class="ssp__head">
      <b>{{ t('smart.title') }}</b>
      <span class="ssp__hint">{{ t('smart.hint', { machine: machineId || '—' }) }}</span>
      <span class="ssp__spacer" />
      <button class="ssp__btn" :disabled="store.data.loading || !machineId" @click="store.fetch(machineId)">
        {{ store.data.loading ? t('smart.busy') : t('smart.fetch') }}
      </button>
    </div>

    <p v-if="store.data.error" class="ssp__error">{{ store.data.error.message }}</p>

    <template v-if="store.data.fetched">
      <div class="ssp__section">
        <b>{{ t('smart.currentParams') }} ({{ store.data.fetched.params.length }})</b>
        <div class="ssp__scroll">
          <table class="ssp__tbl">
            <thead>
              <tr>
                <th>{{ t('smart.currentCol.key') }}</th>
                <th>{{ t('smart.currentCol.actual') }}</th>
                <th>{{ t('smart.currentCol.expected') }}</th>
                <th>{{ t('smart.currentCol.effect') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in store.data.fetched.params" :key="row.key">
                <td class="mono">{{ row.key }}</td>
                <td class="mono">{{ row.actual ?? '—' }}</td>
                <td class="mono">{{ row.expected ?? '—' }}</td>
                <td>{{ row.effect }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="ssp__section">
        <b>{{ t('smart.logs') }} ({{ store.data.fetched.logs.length }})</b>
        <pre v-if="store.data.fetched.logs.length" class="ssp__logs">{{ store.data.fetched.logs.map((line) => `${line.ts} ${line.text}`).join('\n') }}</pre>
        <span v-else class="ssp__hint">—</span>
      </div>
    </template>

    <div class="ssp__section">
      <b>{{ t('smart.fault') }}</b>
      <textarea v-model="fault" class="ssp__fault" :placeholder="t('smart.faultPlaceholder')" rows="2" />
      <div class="ssp__rowline">
        <button class="ssp__btn primary" :disabled="store.data.analyzing" @click="analyze">
          {{ store.data.analyzing ? t('smart.busy') : t('smart.analyze') }}
        </button>
        <span class="ssp__hint">{{ applyHint() }}</span>
      </div>
    </div>

    <div v-if="store.data.analysis" class="ssp__section ssp__analysis">
      <div class="ssp__rowline">
        <b>{{ t('smart.recommendations') }}</b>
        <span class="ssp__source" :data-source="store.data.analysis.source">
          {{ t(`smart.source.${store.data.analysis.source}`) }} · {{ store.data.analysis.durationMs }}ms
        </span>
      </div>
      <p class="ssp__summary">{{ store.data.analysis.summary }}</p>
      <p v-if="store.data.analysis.source === 'rules'" class="ssp__rules">{{ t('smart.rulesNote') }}</p>
      <table class="ssp__tbl">
        <thead>
          <tr>
            <th>{{ t('smart.recCol.key') }}</th><th>{{ t('smart.recCol.from') }}</th>
            <th>{{ t('smart.recCol.to') }}</th><th>{{ t('smart.recCol.reason') }}</th><th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="rec in store.data.analysis.recommendations" :key="rec.key">
            <td class="mono">{{ rec.key }}</td>
            <td class="mono">{{ rec.from || '—' }}</td>
            <td class="mono">{{ rec.to }}</td>
            <td>{{ rec.reason }}</td>
            <td>
              <button class="ssp__btn" @click="apply(rec.key, rec.to)">{{ t('smart.apply') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped lang="less">
.ssp {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__head { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
  &__hint { color: var(--muted); font-size: 12px; }
  &__spacer { flex: 1; }
  &__btn {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 12px;
    cursor: pointer;
    color: var(--text);
    &.primary { background: var(--accent); color: var(--surface); }
    &:disabled { opacity: 0.6; cursor: default; }
  }
  &__error { color: var(--danger-text); font-size: 12px; }
  &__section {
    border-top: 1px solid var(--border);
    padding-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  &__scroll { max-height: 200px; overflow: auto; }
  &__tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
  &__tbl th, &__tbl td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  &__logs {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font-size: 11px;
    max-height: 140px;
    overflow: auto;
    margin: 0;
    white-space: pre-wrap;
    word-break: break-all;
  }
  &__fault {
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    border-radius: 4px;
    padding: 6px 8px;
    resize: vertical;
  }
  &__rowline { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  &__source {
    font-size: 11px;
    border-radius: 999px;
    padding: 2px 8px;
    border: 1px solid var(--border);
    &[data-source='llm'] { color: var(--ok-text); }
    &[data-source='rules'] { color: var(--warn-text); }
  }
  &__summary { margin: 0; font-size: 13px; }
  &__rules { margin: 0; font-size: 12px; color: var(--warn-text); }
}
.mono { font-family: var(--mono, monospace); }
</style>
