<script setup lang="ts">
// 原型 templatePanel：机器实际部署参数 × 模板硬件校验，支持应用草稿与保存为模板。
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import TemplateViewModal from './TemplateViewModal.vue'
import { templatesApi, type TemplateRow } from '@/api/templates'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { useTemplatesStore } from '@/stores/templates'
import type { MachineParamRow } from '@/api/machineConfig'
import { SCENE_KEYS } from '@/views/scenesProto'
import {
  checkTemplateHardware,
  inferEffect,
  snapshotFields,
  templateActualRows,
  type TemplateMachineInput
} from '@/views/templatePanel.viewmodel'

const props = defineProps<{
  machine: TemplateMachineInput | null
  rows: MachineParamRow[]
  patch: Record<string, string>
}>()
const emit = defineEmits<{ apply: [values: Record<string, string>] }>()
const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const store = useTemplatesStore()

const viewOpen = ref(false)
const viewRow = ref<TemplateRow | null>(null)
const expanded = ref<number | null>(null)

// 保存为模板表单（快照预填，键名/取值可改）。
const saveOpen = ref(false)
const saveError = ref('')
const saving = ref(false)
const saveForm = ref({
  name: '',
  effect: 'restart' as 'runtime' | 'restart',
  platform: 'gpu',
  status: 'draft',
  scene: '',
  minVramGb: null as number | null,
  desc: '',
  fields: [] as Array<{ key: string; value: string }>
})

const actual = computed(() => Object.fromEntries(props.rows.map((row) => [row.key, row.actual ?? ''])))
const hotKeys = computed(() => new Set(props.rows.filter((row) => row.effect.includes('hot')).map((row) => row.key)))
const summary = computed(() =>
  props.machine
    ? [
        { label: t('templates.panel.platform'), value: props.machine.platform || '—' },
        { label: t('templates.panel.driver'), value: props.machine.driver || '—' },
        { label: t('templates.panel.vram'), value: props.machine.gpuTotalGb == null ? '—' : `${props.machine.gpuTotalGb} GB` }
      ]
    : []
)

const checkOf = (template: TemplateRow) =>
  props.machine ? checkTemplateHardware(template, props.machine) : null
const rowsOf = (template: TemplateRow) => (props.machine ? templateActualRows(template, actual.value) : [])

function openView(template: TemplateRow): void {
  viewRow.value = template
  viewOpen.value = true
}

function toggle(template: TemplateRow): void {
  expanded.value = expanded.value === template.id ? null : template.id
}

function applyTemplate(template: TemplateRow): void {
  const values = Object.fromEntries(
    template.fields.filter((field) => !field.hot).map((field) => [field.key, field.value])
  )
  if (!Object.keys(values).length) return
  emit('apply', values)
}

function openSave(): void {
  if (!props.machine) return
  const keys = props.rows.map((row) => row.key)
  const fields = snapshotFields(keys, props.patch, actual.value)
  saveForm.value = {
    name: `${props.machine.machineId} snapshot`,
    effect: inferEffect(fields, hotKeys.value),
    platform: props.machine.platform || 'gpu',
    status: 'draft',
    scene: '',
    minVramGb: props.machine.gpuTotalGb,
    desc: `${t('templates.panel.save')} · ${props.machine.machineId}`,
    fields
  }
  saveError.value = ''
  saveOpen.value = true
}

async function submitSave(): Promise<void> {
  saving.value = true
  saveError.value = ''
  try {
    await templatesApi.create({
      name: saveForm.value.name.trim(),
      effect: saveForm.value.effect,
      platform: saveForm.value.platform,
      status: saveForm.value.status,
      scene: saveForm.value.scene,
      minVramGb: saveForm.value.minVramGb,
      fields: saveForm.value.fields.filter((field) => field.key.trim()),
      desc: saveForm.value.desc.trim()
    })
    saveOpen.value = false
    await store.load()
    toast.push(t('templates.panel.saved'))
  } catch {
    saveError.value = t('templates.saveFailed')
  } finally {
    saving.value = false
  }
}

const sceneOptions = [{ value: '', label: t('templates.scene.none') }].concat(
  SCENE_KEYS.map((key) => ({ value: key, label: t(`templates.scene.${key}`) }))
)
</script>

<template>
  <div class="tp">
    <h2>{{ t('templates.panel.title') }} <span class="tp__hint">{{ t('templates.panel.summaryHint') }}</span></h2>

    <p v-if="!machine" class="tp__hint">{{ t('templates.panel.noMachine') }}</p>
    <template v-else>
      <div class="tp__summary">
        <div v-for="item in summary" :key="item.label" class="tp__sum">
          <span>{{ item.label }}</span><b>{{ item.value }}</b>
        </div>
        <button
          v-if="auth.hasPermission('console:template:create')"
          class="tp__save"
          @click="openSave"
        >
          {{ t('templates.panel.save') }}
        </button>
      </div>

      <p v-if="!store.rows.length" class="tp__hint">{{ t('templates.panel.noTemplates') }}</p>
      <div v-for="template in store.rows" :key="template.id" class="tp__row">
        <div class="tp__line">
          <button class="tp__name" @click="toggle(template)">{{ template.name }}</button>
          <span class="tp__effect" :data-effect="template.effect">{{ t(`templates.effect.${template.effect}`) }}</span>
          <span
            v-if="checkOf(template)"
            class="tp__check"
            :data-ok="checkOf(template)!.ok"
          >
            {{ t('templates.panel.check') }}:
            {{ checkOf(template)!.ok
              ? t('templates.panel.checkOk')
              : checkOf(template)!.reasons.map((reason) => t(`templates.${reason}`)).join(' / ') }}
          </span>
          <span class="tp__spacer" />
          <button class="tp__btn" @click="openView(template)">{{ t('templates.actions.view') }}</button>
          <button
            v-if="template.effect === 'restart' && checkOf(template)?.platformOk"
            class="tp__btn"
            @click="applyTemplate(template)"
          >
            {{ t('templates.panel.apply') }}
          </button>
        </div>
        <table v-if="expanded === template.id" class="tp__tbl">
          <thead>
            <tr>
              <th>{{ t('templates.form.fieldKey') }}</th>
              <th>{{ t('templates.panel.templateCol') }}</th>
              <th>{{ t('templates.panel.actualCol') }}</th>
              <th>{{ t('templates.panel.matchCol') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rowsOf(template)" :key="row.field.key">
              <td class="mono">{{ row.field.key }}</td>
              <td class="mono">{{ row.field.value || '—' }}</td>
              <td class="mono">{{ row.actual || '—' }}</td>
              <td>{{ row.match == null ? '—' : row.match ? '✓' : '✗' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <TemplateViewModal :open="viewOpen" :template="viewRow" @close="viewOpen = false" />

    <teleport to="body">
      <div v-if="saveOpen" class="tp__modal-mask" @click.self="saveOpen = false">
        <div class="tp__modal" role="dialog" :aria-label="t('templates.panel.saveTitle')">
          <h3>{{ t('templates.panel.saveTitle') }}</h3>
          <p v-if="saveError" class="tp__error">{{ saveError }}</p>
          <label>{{ t('templates.form.name') }}<input v-model="saveForm.name" /></label>
          <div class="tp__grid">
            <label>{{ t('templates.form.effect') }}
              <select v-model="saveForm.effect">
                <option value="runtime">{{ t('templates.effect.runtime') }}</option>
                <option value="restart">{{ t('templates.effect.restart') }}</option>
              </select>
              <small class="tp__hint">{{ t('templates.form.effectHint') }}</small>
            </label>
            <label>{{ t('templates.form.platform') }}
              <select v-model="saveForm.platform">
                <option v-for="platform in ['gpu', 'npu', 'amd', 'cpu']" :key="platform" :value="platform">
                  {{ t(`templates.platform.${platform}`) }}
                </option>
              </select>
            </label>
            <label>{{ t('templates.form.status') }}
              <select v-model="saveForm.status">
                <option v-for="status in ['draft', 'review', 'published', 'archived']" :key="status" :value="status">
                  {{ t(`templates.status.${status}`) }}
                </option>
              </select>
            </label>
            <label>{{ t('templates.form.scene') }}
              <select v-model="saveForm.scene">
                <option v-for="option in sceneOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>{{ t('templates.form.vram') }}<input v-model.number="saveForm.minVramGb" type="number" min="0" /></label>
          </div>
          <label>{{ t('templates.form.desc') }}<textarea v-model="saveForm.desc" rows="2" /></label>
          <div class="tp__fields">
            <b>{{ t('templates.form.fields') }} ({{ saveForm.fields.length }})</b>
            <div v-for="field in saveForm.fields" :key="field.key" class="tp__field-row">
              <input v-model="field.key" :placeholder="t('templates.form.fieldKey')" />
              <input v-model="field.value" :placeholder="t('templates.form.fieldValue')" />
            </div>
          </div>
          <p class="tp__hint">{{ t('templates.panel.applyNote') }}</p>
          <div class="tp__actions">
            <button class="tp__btn" @click="saveOpen = false">{{ t('common.cancel') }}</button>
            <button class="tp__save" :disabled="saving" @click="submitSave">{{ t('templates.actions.create') }}</button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<style scoped lang="less">
.tp {
  &__hint { color: var(--muted); font-size: 12px; }
  &__summary {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    align-items: center;
    margin: 10px 0;
  }
  &__sum {
    display: flex;
    flex-direction: column;
    gap: 2px;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 12px;
    span { color: var(--muted); font-size: 12px; }
  }
  &__save {
    background: var(--accent);
    color: var(--surface);
    border: 0;
    border-radius: 4px;
    padding: 6px 14px;
    cursor: pointer;
    &:disabled { opacity: 0.6; cursor: default; }
  }
  &__row { border-top: 1px solid var(--border); padding: 8px 0; }
  &__line { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  &__name { background: none; border: 0; color: var(--text); font-weight: 600; cursor: pointer; }
  &__effect {
    font-size: 11px;
    border-radius: 999px;
    padding: 2px 8px;
    border: 1px solid var(--border);
    &[data-effect='runtime'] { color: var(--ok-text); }
    &[data-effect='restart'] { color: var(--warn-text); }
  }
  &__check {
    font-size: 12px;
    &[data-ok='true'] { color: var(--ok-text); }
    &[data-ok='false'] { color: var(--danger-text); }
  }
  &__spacer { flex: 1; }
  &__btn {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 3px 10px;
    cursor: pointer;
    color: var(--text);
  }
  &__tbl { width: 100%; border-collapse: collapse; margin-top: 8px; }
  &__tbl th, &__tbl td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--border); font-size: 12px; }
  &__modal-mask {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 45%);
    display: grid;
    place-items: center;
    z-index: 1000;
  }
  &__modal {
    background: var(--surface);
    border-radius: 8px;
    padding: 20px;
    width: min(680px, 92vw);
    max-height: 84vh;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
    h3 { margin: 0; }
    label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
    input, select, textarea {
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      border-radius: 4px;
      padding: 4px 8px;
    }
  }
  &__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  &__fields { border: 1px solid var(--border); border-radius: 6px; padding: 10px; display: flex; flex-direction: column; gap: 6px; }
  &__field-row { display: grid; grid-template-columns: 1.4fr 1fr; gap: 6px; }
  &__error { color: var(--danger-text); font-size: 12px; }
  &__actions { display: flex; justify-content: flex-end; gap: 8px; }
}
.mono { font-family: var(--mono, monospace); }
</style>
