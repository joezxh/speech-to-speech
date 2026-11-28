<script setup lang="ts">
// 原型「对话态热更」模块：8 个运行时可变参数，白名单内的走 POST /sessions/update 即时生效。
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { machineConfigApi, type MachineParamRow } from '@/api/machineConfig'
import { updateSessions } from '@/api/sessions'
import { useToast } from '@/composables/useToast'
import { HOT_PARAMS, actualForParam, buildSessionPatch, hotParamByName } from '@/utils/hotParams'

const props = defineProps<{ machineId: string }>()
const { t, locale } = useI18n()
const toast = useToast()

const rows = ref<MachineParamRow[]>([])
const loading = ref(false)
const applying = ref(false)
const notice = ref('')
const values = reactive<Record<string, string>>({})
const zh = computed(() => locale.value.startsWith('zh'))

onMounted(refresh)

async function refresh(): Promise<void> {
  if (!props.machineId) return
  loading.value = true
  try {
    const view = await machineConfigApi.view(props.machineId)
    rows.value = view.rows
    for (const param of HOT_PARAMS) {
      const actual = actualForParam(view.rows, param.catalogKey)
      if (actual != null && values[param.name] === undefined) values[param.name] = actual
    }
  } finally {
    loading.value = false
  }
}

const rowOf = (paramName: string) => {
  const param = HOT_PARAMS.find((item) => item.name === paramName)!
  return actualForParam(rows.value, param.catalogKey)
}

/** 智能设置面板把推荐值写进本表（SettingsView 通过 ref 调用），由人确认后统一下发。 */
function setValue(name: string, value: string): void {
  if (hotParamByName(name)) values[name] = value
}
defineExpose({ setValue })

/** 8 个参数里只有白名单路径能即时下发；其余灰显（值仍可保存为模板/随重启发布）。 */
const whitelisted = (paramName: string) => {
  const param = HOT_PARAMS.find((item) => item.name === paramName)!
  return buildSessionPatch({ [paramName]: values[paramName] ?? '' }).rejected.length === 0 && param.patch !== ''
}

async function applyAll(): Promise<void> {
  const selected: Record<string, string> = {}
  for (const param of HOT_PARAMS) {
    const value = values[param.name]?.trim()
    if (value != null && value !== '' && whitelisted(param.name)) selected[param.name] = value
  }
  const { patch, rejected } = buildSessionPatch(selected)
  if (!Object.keys(patch).length) {
    notice.value = t('settings.hotNothingToApply')
    return
  }
  applying.value = true
  try {
    const result = await updateSessions({ scope: 'all', session: patch })
    const failed = result.failed.length
    notice.value =
      t('settings.hotApplied', { accepted: result.updated.length, total: Object.keys(patch).length }) +
      (failed ? ` · ${t('settings.hotFailed', { n: failed })}` : '') +
      (result.hint ? ` · ${result.hint}` : '')
    if (rejected.length) notice.value += ` · ${t('settings.hotRejected', { names: rejected.join(', ') })}`
    toast.push(t('settings.hotApplied', { accepted: result.updated.length, total: Object.keys(patch).length }))
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <div class="hu">
    <div class="hu__head">
      <b>{{ t('settings.hotTitle') }}</b>
      <span class="hu__hint">{{ t('settings.hotHint', { machine: machineId || '—' }) }}</span>
      <span class="hu__spacer" />
      <button class="hu__btn" :disabled="loading" @click="refresh">{{ t('common.refresh') }}</button>
      <button
        v-if="machineId"
        class="hu__btn primary"
        :disabled="applying || loading"
        @click="applyAll"
      >
        {{ applying ? t('settings.hotApplying') : t('settings.hotApply') }}
      </button>
    </div>

    <p v-if="notice" class="hu__notice">{{ notice }}</p>
    <p class="hu__note">{{ t('settings.hotNote') }}</p>

    <table class="hu__tbl">
      <thead>
        <tr>
          <th>{{ t('settings.hotCol.param') }}</th>
          <th>{{ t('settings.hotCol.current') }}</th>
          <th>{{ t('settings.hotCol.value') }}</th>
          <th>{{ t('settings.hotCol.patch') }}</th>
          <th>{{ t('settings.hotCol.source') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="param in HOT_PARAMS" :key="param.name">
          <td>
            {{ zh ? param.label.zh : param.label.en }}
            <small class="hu__hint mono">{{ param.name }}</small>
          </td>
          <td class="mono">{{ rowOf(param.name) ?? '—' }}</td>
          <td>
            <input
              v-model="values[param.name]"
              class="hu__input"
              :class="{ cold: !whitelisted(param.name) }"
              :placeholder="rowOf(param.name) ?? ''"
            />
          </td>
          <td class="mono small">{{ param.patch }}</td>
          <td>
            <span class="hu__tag" :data-hot="whitelisted(param.name)">
              {{ whitelisted(param.name) ? t('settings.hotLive') : t('settings.hotCold') }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!machineId" class="hu__hint">{{ t('settings.pickMachine') }}</p>
  </div>
</template>

<style scoped lang="less">
.hu {
  display: flex;
  flex-direction: column;
  gap: 10px;

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
  &__notice { background: var(--ok-soft); color: var(--ok-text); border-radius: 4px; padding: 6px 10px; font-size: 12px; margin: 0; }
  &__note { color: var(--muted); font-size: 12px; margin: 0; }
  &__tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  &__tbl th, &__tbl td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
  &__input {
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    border-radius: 4px;
    padding: 4px 8px;
    width: 160px;
    &.cold { opacity: 0.55; }
  }
  &__tag {
    font-size: 11px;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px 8px;
    &[data-hot='true'] { color: var(--ok-text); }
    &[data-hot='false'] { color: var(--warn-text); }
  }
  .mono { font-family: var(--mono, monospace); }
  .small { font-size: 11px; }
}
</style>
