<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import ConfirmDialog from '@/components/ConfirmDialog.vue'
import TemplateViewModal from '@/components/proto/TemplateViewModal.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import type { TemplatePayload, TemplateRow } from '@/api/templates'
import { useAuthStore } from '@/stores/auth'
import { useTemplatesStore } from '@/stores/templates'
import { SCENE_KEYS } from '@/views/scenesProto'
import { formatTime } from '@/utils/format'

const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const store = useTemplatesStore()

const filter = reactive({ effect: '', platform: '', status: '', q: '' })
const visibleRows = computed(() => store.applyFilter(filter))

const viewOpen = ref(false)
const viewRow = ref<TemplateRow | null>(null)

const { open: confirmOpen, title: confirmTitle, content: confirmContent, ask, answer } = useConfirm()

// ---- 新建 / 编辑弹窗 -------------------------------------------------------

const formOpen = ref(false)
const formId = ref<number | null>(null)
const formError = ref('')
const form = reactive<{
  name: string
  effect: 'runtime' | 'restart'
  platform: string
  status: string
  scene: string
  minVramGb: number | null
  desc: string
  fields: Array<{ key: string; value: string }>
}>({ name: '', effect: 'runtime', platform: 'gpu', status: 'draft', scene: '', minVramGb: null, desc: '', fields: [] })

const effectOptions = [
  { value: 'runtime', label: t('templates.effect.runtime') },
  { value: 'restart', label: t('templates.effect.restart') }
]
const statusOptions = ['draft', 'review', 'published', 'archived'].map((value) => ({ value, label: t(`templates.status.${value}`) }))
const platformOptions = ['gpu', 'npu', 'amd', 'cpu'].map((value) => ({ value, label: t(`templates.platform.${value}`) }))
const sceneOptions = [{ value: '', label: t('templates.scene.none') }].concat(
  SCENE_KEYS.map((key) => ({ value: key, label: t(`templates.scene.${key}`) }))
)

function openCreate(): void {
  formId.value = null
  Object.assign(form, { name: '', effect: 'runtime', platform: 'gpu', status: 'draft', scene: '', minVramGb: null, desc: '', fields: [] })
  formError.value = ''
  formOpen.value = true
}

function openEdit(row: TemplateRow): void {
  formId.value = row.id
  Object.assign(form, {
    name: row.name,
    effect: row.effect,
    platform: row.platform,
    status: row.status,
    scene: row.scene,
    minVramGb: row.minVramGb,
    desc: row.desc,
    fields: row.fields.map((field) => ({ key: field.key, value: field.value }))
  })
  formError.value = ''
  formOpen.value = true
}

function addField(): void {
  form.fields.push({ key: '', value: '' })
}

function removeField(index: number): void {
  form.fields.splice(index, 1)
}

async function saveForm(): Promise<void> {
  if (!form.name.trim()) {
    formError.value = t('templates.form.name')
    return
  }
  const payload: TemplatePayload = {
    name: form.name.trim(),
    effect: form.effect,
    platform: form.platform,
    status: form.status,
    scene: form.scene,
    minVramGb: form.minVramGb,
    fields: form.fields.filter((field) => field.key.trim()),
    desc: form.desc.trim()
  }
  const saved = formId.value === null ? await store.create(payload) : await store.update(formId.value, payload)
  if (saved) {
    formOpen.value = false
    toast.push(t('templates.toast.saved'))
  } else {
    formError.value = store.error?.message ?? ''
  }
}

async function removeRow(row: TemplateRow): Promise<void> {
  const confirmed = await ask({
    title: t('templates.actions.remove'),
    content: t('templates.confirm.remove', { name: row.name })
  })
  if (!confirmed) return
  if (await store.remove(row.id)) toast.push(t('templates.toast.removed'))
}

const platformTagColor = (row: TemplateRow) => ({ gpu: 'geekblue', npu: 'purple', amd: 'red', cpu: 'default' }[row.platform] ?? 'default')
const sceneLabel = (row: TemplateRow) => (row.scene ? t(`templates.scene.${row.scene}`) : t('templates.scene.none'))

onMounted(() => {
  store.load()
})
</script>

<template>
  <div class="tv">
    <header class="tv__head">
      <div>
        <h2>{{ t('templates.title') }}</h2>
        <p class="muted">{{ t('templates.desc') }}</p>
      </div>
      <a-button v-if="auth.hasPermission('console:template:create')" type="primary" @click="openCreate">
        {{ t('templates.actions.create') }}
      </a-button>
    </header>

    <div class="tv__kpis">
      <div class="tv__kpi"><span>{{ t('templates.kpi.total') }}</span><b>{{ store.rows.length }}</b></div>
      <div class="tv__kpi"><span>{{ t('templates.kpi.runtime') }}</span><b>{{ store.runtimeCount }}</b></div>
      <div class="tv__kpi"><span>{{ t('templates.kpi.restart') }}</span><b>{{ store.restartCount }}</b></div>
      <div class="tv__kpi"><span>{{ t('templates.kpi.platforms') }}</span><b>{{ store.platformCount }}</b></div>
    </div>

    <div class="tv__filters">
      <a-select
        v-model:value="filter.effect" style="width: 150px" allow-clear :placeholder="t('templates.filter.effect')"
        :options="effectOptions"
      />
      <a-select
        v-model:value="filter.platform" style="width: 120px" allow-clear :placeholder="t('templates.filter.platform')"
        :options="platformOptions"
      />
      <a-select
        v-model:value="filter.status" style="width: 130px" allow-clear :placeholder="t('templates.filter.status')"
        :options="statusOptions"
      />
      <a-input-search v-model:value="filter.q" style="width: 260px" :placeholder="t('templates.filter.search')" />
      <a-button @click="store.load()">{{ t('common.refresh') }}</a-button>
    </div>

    <a-alert v-if="store.error" type="error" :message="store.error.message" show-icon class="tv__alert" />

    <a-table
      :data-source="visibleRows"
      :loading="store.loading"
      :row-key="(row: TemplateRow) => row.id"
      size="middle"
      :pagination="{ pageSize: 10 }"
    >
      <a-table-column :title="t('templates.col.name')" data-index="name">
        <template #default="{ record }">
          <b>{{ record.name }}</b>
          <div class="muted small">#{{ record.id }}</div>
        </template>
      </a-table-column>
      <a-table-column :title="t('templates.col.effect')" data-index="effect" width="120">
        <template #default="{ record }">
          <a-tag :color="record.effect === 'runtime' ? 'cyan' : 'orange'">{{ t(`templates.effect.${record.effect}`) }}</a-tag>
        </template>
      </a-table-column>
      <a-table-column :title="t('templates.col.platform')" data-index="platform" width="100">
        <template #default="{ record }">
          <a-tag :color="platformTagColor(record)">{{ t(`templates.platform.${record.platform}`) }}</a-tag>
        </template>
      </a-table-column>
      <a-table-column :title="t('templates.col.status')" data-index="status" width="110">
        <template #default="{ record }">
          <a-tag>{{ t(`templates.status.${record.status}`) }}</a-tag>
        </template>
      </a-table-column>
      <a-table-column :title="t('templates.col.scene')" data-index="scene" width="180">
        <template #default="{ record }">{{ sceneLabel(record) }}</template>
      </a-table-column>
      <a-table-column :title="t('templates.col.fields')" width="90">
        <template #default="{ record }">{{ record.fields.length }}</template>
      </a-table-column>
      <a-table-column :title="t('templates.col.vram')" width="100">
        <template #default="{ record }">{{ record.minVramGb ? `${record.minVramGb} GB` : '—' }}</template>
      </a-table-column>
      <a-table-column :title="t('templates.col.createdAt')" width="150">
        <template #default="{ record }">{{ record.createdAt ? formatTime(record.createdAt) : '—' }}</template>
      </a-table-column>
      <a-table-column :title="t('templates.col.updatedAt')" width="150">
        <template #default="{ record }">{{ record.updatedAt ? formatTime(record.updatedAt) : '—' }}</template>
      </a-table-column>
      <a-table-column :title="t('templates.col.desc')" data-index="desc" :ellipsis="true" />
      <a-table-column :title="t('templates.col.actions')" width="220">
        <template #default="{ record }">
          <a-button size="small" @click="viewRow = record; viewOpen = true">{{ t('templates.actions.view') }}</a-button>
          <a-button v-if="auth.hasPermission('console:template:update')" size="small" class="tv__gap" @click="openEdit(record)">
            {{ t('templates.actions.edit') }}
          </a-button>
          <a-button v-if="auth.hasPermission('console:template:delete')" size="small" danger class="tv__gap" @click="removeRow(record)">
            {{ t('templates.actions.remove') }}
          </a-button>
        </template>
      </a-table-column>
      <template #emptyText>{{ t('templates.empty') }}</template>
    </a-table>

    <TemplateViewModal :open="viewOpen" :template="viewRow" @close="viewOpen = false" />

    <ConfirmDialog :open="confirmOpen" :title="confirmTitle" :content="confirmContent" danger @answer="answer" />

    <a-modal
      v-model:open="formOpen"
      :title="formId === null ? t('templates.form.create') : t('templates.form.edit')"
      width="680px"
      :confirm-loading="store.saving"
      @ok="saveForm"
    >
      <a-alert v-if="formError" type="error" :message="formError" show-icon class="tv__alert" />
      <div class="tv__form">
        <label>{{ t('templates.form.name') }}<a-input v-model:value="form.name" /></label>
        <div class="tv__row3">
          <label>
            {{ t('templates.form.effect') }}
            <a-select v-model:value="form.effect" :options="effectOptions" />
            <p class="muted small">{{ t('templates.form.effectHint') }}</p>
          </label>
          <label>
            {{ t('templates.form.platform') }}
            <a-select v-model:value="form.platform" :options="platformOptions" />
          </label>
          <label>
            {{ t('templates.form.status') }}
            <a-select v-model:value="form.status" :options="statusOptions" />
          </label>
        </div>
        <div class="tv__row2">
          <label>
            {{ t('templates.form.scene') }}
            <a-select v-model:value="form.scene" :options="sceneOptions" />
          </label>
          <label>
            {{ t('templates.form.vram') }}
            <a-input-number v-model:value="form.minVramGb" :min="0" style="width: 100%" />
          </label>
        </div>
        <label>{{ t('templates.form.desc') }}<a-textarea v-model:value="form.desc" :rows="2" /></label>
        <div class="tv__fields">
          <div class="tv__fields-head">
            <b>{{ t('templates.form.fields') }}</b>
            <a-button size="small" @click="addField">{{ t('templates.form.addField') }}</a-button>
          </div>
          <div v-for="(field, index) in form.fields" :key="index" class="tv__field-row">
            <a-input v-model:value="field.key" :placeholder="t('templates.form.fieldKey')" />
            <a-input v-model:value="field.value" :placeholder="t('templates.form.fieldValue')" />
            <a-button size="small" danger @click="removeField(index)">{{ t('templates.form.removeField') }}</a-button>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<style scoped lang="less">
.tv {
  display: flex;
  flex-direction: column;
  gap: 16px;

  &__head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    h2 {
      margin: 0 0 4px;
    }
  }
  &__kpis {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }
  &__kpi {
    border: 1px solid var(--ant-color-border-secondary, #eee);
    border-radius: 10px;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    span {
      font-size: 12px;
      color: var(--ant-color-text-secondary, #888);
    }
    b {
      font-size: 22px;
    }
  }
  &__filters {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: center;
  }
  &__gap {
    margin-left: 8px;
  }
  &__alert {
    margin-bottom: 8px;
  }
  &__form {
    display: flex;
    flex-direction: column;
    gap: 12px;
    label {
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 12px;
      color: var(--ant-color-text-secondary, #666);
    }
  }
  &__row3,
  &__row2 {
    display: grid;
    gap: 12px;
  }
  &__row3 {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  &__row2 {
    grid-template-columns: 2fr 1fr;
  }
  &__fields {
    border: 1px solid var(--ant-color-border-secondary, #eee);
    border-radius: 8px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  &__fields-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__field-row {
    display: grid;
    grid-template-columns: 1.4fr 1fr auto;
    gap: 8px;
  }
}
.muted {
  color: var(--ant-color-text-secondary, #888);
}
.small {
  font-size: 12px;
}
</style>
