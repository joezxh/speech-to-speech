<script setup lang="ts">
// 会话工具独立页（原型 console-refactor-demo.html#/tools）：统计 / 查询 / 列表三行。
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import type { ToolPayload, ToolRow, ToolType } from '@/api/tools'
import { useAuthStore } from '@/stores/auth'
import { useToolsStore } from '@/stores/tools'
import { applyToolFilter, toolKpis, toolParamText } from './tools.viewmodel'

const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const store = useToolsStore()

const filter = reactive({ q: '', type: 'all', scope: 'all', on: 'all' })
const rows = computed(() => applyToolFilter(store.rows, filter, store.sessionEnabled))
const kpis = computed(() => toolKpis(store.rows, store.sessionEnabled))

const TYPES: ToolType[] = ['web_search', 'calendar', 'weather', 'kb', 'http']
const SCOPES = ['global', 'session', 'tenant'] as const
const METHODS = ['GET', 'POST'] as const

const { open: confirmOpen, title: confirmTitle, content: confirmContent, ask, answer } = useConfirm()

const formOpen = ref(false)
const formId = ref<string | null>(null)
const formError = ref('')
const form = reactive<ToolPayload>({
  name: '', type: 'http', description: '', endpoint: '', method: 'GET', scope: 'global',
  params: [], config: {}
})

function openCreate(): void {
  formId.value = null
  Object.assign(form, {
    name: '', type: 'http', description: '', endpoint: '', method: 'GET', scope: 'global',
    params: [], config: {}
  })
  formError.value = ''
  formOpen.value = true
}

async function openEdit(row: ToolRow): Promise<void> {
  if (row.builtin) {
    const accepted = await ask({
      title: t('tools.warn.builtinTitle'),
      content: t('tools.warn.builtinBody', { name: row.name })
    })
    if (!accepted) return
  }
  formId.value = row.id
  Object.assign(form, {
    name: row.name, type: row.type, description: row.description, endpoint: row.endpoint,
    method: row.method, scope: row.scope, params: row.params.map((p) => ({ ...p })),
    config: { ...row.config }
  })
  formError.value = ''
  formOpen.value = true
}

function addParam(): void {
  form.params.push({ k: '', t: 'string', req: false })
}

async function saveForm(): Promise<void> {
  if (!form.name.trim()) {
    formError.value = t('tools.err.name')
    return
  }
  const payload: ToolPayload = {
    ...form,
    name: form.name.trim(),
    params: form.params.filter((p) => p.k.trim())
  }
  const saved = formId.value === null ? await store.create(payload) : await store.update(formId.value, payload)
  if (!saved) {
    formError.value = t('tools.saveFailed')
    return
  }
  formOpen.value = false
  toast.push(t(formId.value === null ? 'tools.toast.created' : 'tools.toast.saved', { name: saved.name }))
}

async function copyRow(row: ToolRow): Promise<void> {
  const created = await store.copy(row.id)
  if (created) toast.push(t('tools.toast.copied', { name: created.name }))
}

async function removeRow(row: ToolRow): Promise<void> {
  const builtin = row.builtin
  const ok = await ask({
    title: t(builtin ? 'tools.warn.deleteTitle' : 'tools.deleteTitle'),
    content: t(builtin ? 'tools.warn.deleteBody' : 'tools.deleteBody', { name: row.name })
  })
  if (ok && await store.remove(row.id)) toast.push(t('tools.toast.deleted', { name: row.name }))
}

function toggleRow(row: ToolRow): void {
  void store.toggle(row.id, !store.isEnabled(row))
}

function canEdit(row: ToolRow): boolean {
  return row.builtin ? auth.hasPermission('console:tool:update') : row.writable
}

onMounted(() => store.load())
</script>

<template>
  <section class="tools-page">
    <header class="page-head">
      <h1>{{ t('nav.tools') }}</h1>
      <p>{{ t('tools.page.desc') }}</p>
    </header>

    <div class="grid g4">
      <div class="kpi"><div class="label">{{ t('tools.kpi.total') }}</div><div class="value">{{ kpis.total }}</div><div class="sub">{{ t('tools.kpi.sub') }}</div></div>
      <div class="kpi"><div class="label">{{ t('tools.kpi.on') }}</div><div class="value kpi--on">{{ kpis.on }}</div><div class="sub">{{ t('tools.kpi.sub') }}</div></div>
      <div class="kpi"><div class="label">{{ t('tools.kpi.builtin') }}</div><div class="value">{{ kpis.builtin }}</div><div class="sub">{{ t('tools.kpi.sub') }}</div></div>
      <div class="kpi"><div class="label">{{ t('tools.kpi.custom') }}</div><div class="value">{{ kpis.custom }}</div><div class="sub">{{ t('tools.kpi.sub') }}</div></div>
    </div>

    <div class="card card--filter">
      <h3>{{ t('tools.filter.title') }}</h3>
      <search :aria-label="t('tools.filter.title')">
        <div class="filter-grid">
          <div class="fbar wide">
            <label for="tool-kw">{{ t('tools.filter.kw') }}</label>
            <input id="tool-kw" v-model="filter.q" type="search" class="fin" :placeholder="t('tools.filter.kwPh')" autocomplete="off">
          </div>
          <div class="fbar">
            <label for="tool-scope">{{ t('tools.filter.scope') }}</label>
            <select id="tool-scope" v-model="filter.scope" class="fin">
              <option value="all">{{ t('common.all') }}</option>
              <option v-for="scope in SCOPES" :key="scope" :value="scope">{{ t(`tools.scope.${scope}`) }}</option>
            </select>
          </div>
          <div class="fbar">
            <label for="tool-on">{{ t('tools.filter.on') }}</label>
            <select id="tool-on" v-model="filter.on" class="fin">
              <option value="all">{{ t('common.all') }}</option>
              <option value="true">{{ t('tools.on.yes') }}</option>
              <option value="false">{{ t('tools.on.no') }}</option>
            </select>
          </div>
          <div class="fbar-actions">
            <div class="chips">
              <button type="button" class="chip" :class="{ active: filter.type === 'all' }" @click="filter.type = 'all'">{{ t('common.all') }}</button>
              <button v-for="type in TYPES" :key="type" type="button" class="chip" :class="{ active: filter.type === type }" @click="filter.type = type">{{ t(`tools.type.${type}`) }}</button>
            </div>
          </div>
        </div>
      </search>
    </div>

    <div class="card">
      <h3>
        {{ t('nav.tools') }}
        <span class="hint">{{ t('tools.count', { n: rows.length }) }}</span>
        <span class="spacer" />
        <button v-if="auth.hasPermission('console:tool:create')" type="button" class="btn primary sm" @click="openCreate">{{ t('tools.new') }}</button>
      </h3>
      <div class="tbl-scroll">
        <table class="tbl">
          <thead><tr>
            <th>{{ t('tools.col.name') }}</th><th>{{ t('tools.col.type') }}</th><th>{{ t('tools.col.desc') }}</th>
            <th>{{ t('tools.col.params') }}</th><th>{{ t('tools.col.scope') }}</th><th>{{ t('tools.col.on') }}</th>
            <th>{{ t('tools.col.updated') }}</th><th>{{ t('tools.col.actions') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>
                <b>{{ row.name }}</b>
                <span class="tag" :class="row.builtin ? 'tag accent' : ''">{{ row.builtin ? t('tools.builtin') : t('tools.customBadge') }}</span>
                <div class="mono id">{{ row.id }}</div>
              </td>
              <td>{{ t(`tools.type.${row.type}`) }}</td>
              <td class="cell-clip" :title="row.description">{{ row.description || '—' }}</td>
              <td class="mono cell-clip">{{ toolParamText(row) }}</td>
              <td>{{ t(`tools.scope.${row.scope}`) }}</td>
              <td><button type="button" role="switch" class="switch" :class="{ on: store.isEnabled(row) }" :aria-checked="store.isEnabled(row) ? 'true' : 'false'" :aria-label="t('tools.toggle', { name: row.name })" @click="toggleRow(row)" /></td>
              <td class="mono">{{ row.updatedAt ? row.updatedAt.slice(5, 16).replace('T', ' ') : '—' }}</td>
              <td class="acts">
                <button v-if="canEdit(row)" type="button" class="btn sm" @click="openEdit(row)">{{ t('tools.edit') }}</button>
                <button v-if="auth.hasPermission('console:tool:create')" type="button" class="btn sm" @click="copyRow(row)">{{ t('tools.copy') }}</button>
                <button v-if="auth.hasPermission('console:tool:delete') && (!row.builtin || auth.user?.role === 'admin')" type="button" class="btn sm danger" @click="removeRow(row)">{{ t('common.delete') }}</button>
              </td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="empty">{{ t('tools.empty') }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <a-modal :open="formOpen" :title="formId ? t('tools.form.edit', { name: form.name }) : t('tools.form.new')" :footer="null" @cancel="formOpen = false">
      <form novalidate @submit.prevent="saveForm">
        <div class="field"><label for="tf-name">{{ t('tools.f.name') }}</label><input id="tf-name" v-model="form.name" class="fin"><small class="hint">{{ t('tools.f.nameHint') }}</small></div>
        <div class="field"><label for="tf-type">{{ t('tools.f.type') }}</label><select id="tf-type" v-model="form.type" class="fin"><option v-for="type in TYPES" :key="type" :value="type">{{ t(`tools.type.${type}`) }}</option></select></div>
        <div class="field"><label for="tf-desc">{{ t('tools.f.desc') }}</label><textarea id="tf-desc" v-model="form.description" class="fin" rows="3" /></div>
        <div class="field"><label for="tf-endpoint">{{ t('tools.f.endpoint') }}</label><input id="tf-endpoint" v-model="form.endpoint" class="fin" placeholder="https://…"></div>
        <div class="field"><label for="tf-method">{{ t('tools.f.method') }}</label><select id="tf-method" v-model="form.method" class="fin"><option v-for="method in METHODS" :key="method" :value="method">{{ method }}</option></select></div>
        <div class="field"><label for="tf-scope">{{ t('tools.f.scope') }}</label><select id="tf-scope" v-model="form.scope" class="fin"><option v-for="scope in SCOPES" :key="scope" :value="scope">{{ t(`tools.scope.${scope}`) }}</option></select></div>
        <div class="field"><label>{{ t('tools.f.params') }}</label>
          <div v-for="(param, index) in form.params" :key="index" class="prow">
            <input v-model="param.k" class="fin" :aria-label="t('tools.f.paramsName')">
            <select v-model="param.t" class="fin" :aria-label="t('tools.f.paramsType')"><option value="string">string</option><option value="number">number</option><option value="boolean">boolean</option></select>
            <label class="pcheck"><input v-model="param.req" type="checkbox"> {{ t('tools.f.paramsReq') }}</label>
            <button type="button" class="btn sm" @click="form.params.splice(index, 1)">✕</button>
          </div>
          <button type="button" class="btn sm" @click="addParam">{{ t('tools.f.paramsAdd') }}</button>
        </div>
        <p v-if="formError" class="err">{{ formError }}</p>
        <div class="modal-actions"><button type="submit" class="btn primary" :disabled="store.saving">{{ t('tools.form.save') }}</button></div>
      </form>
    </a-modal>

    <ConfirmDialog :open="confirmOpen" :title="confirmTitle" :content="confirmContent" danger @answer="answer" />
  </section>
</template>

<style scoped lang="less">
.tools-page { display: flex; flex-direction: column; }
.page-head { margin: 0 0 18px; h1 { margin: 0 0 6px; font-size: 20px; } p { margin: 0; color: var(--s2s-color-muted); font-size: 13px; } }
.grid { display: grid; gap: 14px; }
.g4 { grid-template-columns: repeat(4, 1fr); }
.card { background: var(--s2s-color-surface); border: 1px solid var(--s2s-color-border); border-radius: var(--s2s-radius-md); padding: 16px 18px; margin-top: 16px; h3 { margin: 0 0 12px; font-size: 14px; display: flex; align-items: center; gap: 8px; } }
.kpi { background: var(--s2s-color-surface); border: 1px solid var(--s2s-color-border); border-radius: var(--s2s-radius-md); padding: 14px 16px; .label { font-size: 12px; color: var(--s2s-color-muted); } .value { font-size: 24px; font-weight: 680; margin-top: 6px; } .sub { font-size: 11px; color: var(--s2s-color-faint); margin-top: 4px; } }
.kpi--on { color: var(--s2s-color-success); }
.hint { font-size: 12px; font-weight: 400; color: var(--s2s-color-faint); }
.spacer { flex: 1; }
.filter-grid { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 12px; align-items: end; }
.fbar { display: flex; flex-direction: column; gap: 6px; label { font-size: 12px; color: var(--s2s-color-muted); } }
.fin { background: var(--s2s-color-surface-2); border: 1px solid var(--s2s-color-border-strong); border-radius: var(--s2s-radius-sm); color: var(--s2s-color-text); font: inherit; font-size: 13px; padding: 7px 10px; width: 100%; }
.fbar-actions { grid-column: 1 / -1; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { background: transparent; border: 1px solid var(--s2s-color-border-strong); border-radius: 999px; color: var(--s2s-color-muted); cursor: pointer; font: inherit; font-size: 12px; padding: 4px 12px; &.active { background: var(--s2s-color-accent-soft); border-color: var(--s2s-color-accent); color: var(--s2s-color-accent); } }
.btn { background: var(--s2s-color-surface-2); border: 1px solid var(--s2s-color-border-strong); border-radius: var(--s2s-radius-sm); color: var(--s2s-color-text); cursor: pointer; font: inherit; font-size: 12.5px; padding: 6px 12px; &.primary { background: var(--s2s-color-accent); border-color: var(--s2s-color-accent); color: var(--s2s-color-bg); } &.danger { color: var(--s2s-color-danger); } &.sm { padding: 3px 9px; font-size: 12px; } &:disabled { opacity: .45; cursor: not-allowed; } }
.tbl-scroll { overflow-x: auto; }
.tbl { border-collapse: collapse; font-size: 13px; width: 100%; th { color: var(--s2s-color-faint); font-size: 12px; font-weight: 500; padding: 8px 10px; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--s2s-color-border-strong); } td { border-bottom: 1px solid var(--s2s-color-border); padding: 9px 10px; vertical-align: middle; } }
.mono { font-family: var(--s2s-font-mono); font-size: 12px; &.id { color: var(--s2s-color-faint); } }
.tag { border: 1px solid var(--s2s-color-border-strong); border-radius: 999px; color: var(--s2s-color-muted); font-size: 11px; margin-left: 6px; padding: 2px 8px; &.accent { color: var(--s2s-color-accent); border-color: var(--s2s-color-accent); } }
.cell-clip { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.switch { background: var(--s2s-color-surface-3); border: 0; border-radius: 999px; cursor: pointer; height: 18px; position: relative; width: 34px; &::after { background: var(--s2s-color-muted); border-radius: 50%; content: ''; height: 14px; left: 2px; position: absolute; top: 2px; transition: transform .15s; width: 14px; } &.on { background: var(--s2s-color-accent); &::after { background: var(--s2s-color-bg); transform: translateX(16px); } } }
.acts { display: flex; gap: 6px; }
.empty { color: var(--s2s-color-faint); text-align: center; }
.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; label { font-size: 12px; color: var(--s2s-color-muted); } }
.prow { display: grid; grid-template-columns: 1fr 100px auto 32px; gap: 8px; margin-bottom: 6px; }
.pcheck { align-items: center; display: flex; font-size: 12px; gap: 4px; }
.modal-actions { display: flex; justify-content: flex-end; }
.err { color: var(--s2s-color-danger); font-size: 12px; }
</style>
