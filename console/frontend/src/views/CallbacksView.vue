<!-- 回调管理（spec 2026-11-25 §8.5）：回调目标 CRUD / 批量操作 / 测试投递 + 投递日志页签 -->
<template>
  <div class="callbacks">
    <a-tabs v-model:activeKey="activeTab">
      <a-tab-pane key="targets" :tab="t('callbacks.targetsTab')">
        <a-space class="callbacks__bar">
          <a-button type="primary" @click="openCreate">{{ t('callbacks.create') }}</a-button>
          <a-button :disabled="!selectedRowKeys.length" @click="batch('enable')">
            {{ t('callbacks.batchEnable') }}
          </a-button>
          <a-button :disabled="!selectedRowKeys.length" @click="batch('disable')">
            {{ t('callbacks.batchDisable') }}
          </a-button>
          <a-popconfirm :title="t('callbacks.batchDeleteConfirm')" @confirm="batch('delete')">
            <a-button danger :disabled="!selectedRowKeys.length">
              {{ t('callbacks.batchDelete') }}
            </a-button>
          </a-popconfirm>
        </a-space>
        <a-table
          row-key="id"
          size="small"
          :columns="columns"
          :data-source="targets"
          :loading="loading"
          :pagination="{ total, current: page, pageSize, showSizeChanger: false, onChange: load }"
          :row-selection="{ selectedRowKeys, onChange: onSelectionChange }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'events'">
              <a-tag v-for="event in record.events" :key="event" class="callbacks__tag">
                {{ event }}
              </a-tag>
            </template>
            <template v-else-if="column.key === 'enabled'">
              <a-switch :checked="record.enabled" @change="() => toggleEnabled(record)" />
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-button type="link" size="small" @click="openEdit(record)">
                {{ t('callbacks.edit') }}
              </a-button>
              <a-button
                type="link"
                size="small"
                :loading="testingId === record.id"
                :disabled="testingId !== null"
                @click="runTest(record)"
              >
                {{ t('callbacks.test') }}
              </a-button>
              <a-popconfirm :title="t('callbacks.deleteConfirm')" @confirm="removeOne(record)">
                <a-button type="link" size="small" danger>{{ t('callbacks.delete') }}</a-button>
              </a-popconfirm>
            </template>
          </template>
        </a-table>
      </a-tab-pane>
      <a-tab-pane key="logs" :tab="t('callbacks.logsTab')">
        <a-space class="callbacks__bar">
          <a-select
            v-model:value="logStatus"
            style="width: 160px"
            allow-clear
            :placeholder="t('callbacks.logStatusFilter')"
            :options="statusOptions"
            @change="() => loadLogs(1)"
          />
        </a-space>
        <a-table
          row-key="id"
          size="small"
          :columns="logColumns"
          :data-source="logs"
          :loading="logsLoading"
          :pagination="{
            total: logsTotal,
            current: logsPage,
            pageSize: logPageSize,
            showSizeChanger: false,
            onChange: loadLogs
          }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag :color="record.status === 'success' ? 'green' : record.status === 'retrying' ? 'orange' : 'red'">
                {{ record.status }}
              </a-tag>
            </template>
            <template v-else-if="column.key === 'detail'">
              <a-button type="link" size="small" @click="showLogDetail(record)">
                {{ t('callbacks.viewDetail') }}
              </a-button>
            </template>
          </template>
        </a-table>
      </a-tab-pane>
      <a-tab-pane key="live" :tab="t('callbacks.liveTab')">
        <LiveSubtitlesPanel />
      </a-tab-pane>
    </a-tabs>

    <a-drawer
      v-model:open="editorOpen"
      :title="editingId !== null ? t('callbacks.editTitle') : t('callbacks.createTitle')"
      :width="520"
      @close="resetEditor"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('callbacks.field.name')" required>
          <a-input v-model:value="form.name" :maxlength="128" />
        </a-form-item>
        <a-form-item :label="t('callbacks.field.type')" required>
          <a-radio-group v-model:value="form.targetType" :disabled="editingId !== null">
            <a-radio value="java">Java</a-radio>
            <a-radio value="python">Python</a-radio>
          </a-radio-group>
          <div class="callbacks__hint">
            {{ form.targetType === 'java' ? t('callbacks.hint.javaUrl') : t('callbacks.hint.pythonUrl') }}
          </div>
        </a-form-item>
        <a-form-item :label="t('callbacks.field.baseUrl')" required>
          <a-input v-model:value="form.baseUrl" placeholder="http://" />
        </a-form-item>
        <a-form-item :label="t('callbacks.field.authType')" required>
          <a-select v-model:value="form.authType" :options="authTypeOptions" />
        </a-form-item>
        <a-form-item v-if="form.authType === 'header_token'" :label="t('callbacks.field.authHeaderName')">
          <a-input v-model:value="form.authHeaderName" placeholder="X-Callback-Token" />
        </a-form-item>
        <a-form-item v-if="form.authType !== 'none'" :label="t('callbacks.field.authToken')">
          <a-input-password v-model:value="form.authToken" />
          <div class="callbacks__hint">{{ t('callbacks.field.authTokenHint') }}</div>
        </a-form-item>
        <a-form-item :label="t('callbacks.field.timeoutMs')">
          <a-input-number v-model:value="form.timeoutMs" :min="100" :max="60000" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="t('callbacks.field.retry')">
          <a-space>
            <a-input-number v-model:value="form.retryMaxAttempts" :min="1" :max="10" />
            <span>× backoff</span>
            <a-input-number v-model:value="form.retryBackoffMs" :min="0" :max="60000" />
            <span>ms</span>
          </a-space>
        </a-form-item>
        <a-form-item :label="t('callbacks.field.events')" required>
          <a-checkbox-group v-model:value="form.events" :options="eventOptions" />
          <div v-if="form.targetType === 'java'" class="callbacks__hint">
            {{ t('callbacks.hint.javaEvents') }}
          </div>
        </a-form-item>
        <a-form-item :label="t('callbacks.field.filters')">
          <a-select
            v-model:value="filterSpeakers"
            mode="tags"
            allow-clear
            :placeholder="t('callbacks.field.filterSpeakers')"
            style="margin-bottom: 8px"
          />
          <a-input-number
            v-model:value="filterMinTextLen"
            :min="0"
            :placeholder="t('callbacks.field.filterMinLen')"
            style="width: 200px"
          />
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button type="primary" :loading="saving" @click="save">
              {{ t('callbacks.save') }}
            </a-button>
            <a-button @click="editorOpen = false">{{ t('common.cancel') }}</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </a-drawer>

    <a-drawer v-model:open="logDetailOpen" :title="t('callbacks.logDetail')" :width="560">
      <a-descriptions v-if="logDetail" :column="1" size="small">
        <a-descriptions-item label="URL">{{ logDetail.requestUrl }}</a-descriptions-item>
        <a-descriptions-item label="HTTP">{{ logDetail.httpStatus ?? '-' }}</a-descriptions-item>
        <a-descriptions-item label="attempt">{{ logDetail.attempt }}</a-descriptions-item>
        <a-descriptions-item :label="t('callbacks.log.duration')">{{ logDetail.durationMs }}ms</a-descriptions-item>
        <a-descriptions-item :label="t('callbacks.field.payload')">
          <pre class="callbacks__payload">{{ logDetail.requestPayload }}</pre>
        </a-descriptions-item>
        <a-descriptions-item :label="t('callbacks.field.response')">
          <pre class="callbacks__payload">{{ logDetail.responseSnippet }}</pre>
        </a-descriptions-item>
        <a-descriptions-item v-if="logDetail.error" :label="t('callbacks.field.error')">
          {{ logDetail.error }}
        </a-descriptions-item>
      </a-descriptions>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { message } from 'ant-design-vue'

import { AppError } from '@/api/client'
import LiveSubtitlesPanel from '@/components/LiveSubtitlesPanel.vue'
import {
  batchTargets,
  createTarget,
  deleteTarget,
  listLogs,
  listTargets,
  testTarget,
  updateTarget,
  type AuthType,
  type CallbackTarget,
  type DeliveryLog,
  type EventType,
  type TargetType
} from '@/api/callbacks'

const { t } = useI18n()

function errText(caught: unknown, fallback: string): string {
  return caught instanceof AppError ? caught.message : fallback
}

// ---- 回调目标列表 ----
const activeTab = ref<'targets' | 'logs' | 'live'>('targets')
const targets = ref<CallbackTarget[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const selectedRowKeys = ref<number[]>([])

const columns = computed(() => [
  { title: t('callbacks.field.name'), dataIndex: 'name', key: 'name' },
  { title: t('callbacks.field.type'), dataIndex: 'targetType', key: 'targetType', width: 90 },
  { title: 'URL', dataIndex: 'baseUrl', key: 'baseUrl', ellipsis: true },
  { title: t('callbacks.field.authType'), dataIndex: 'authType', key: 'authType', width: 130 },
  { title: t('callbacks.field.events'), key: 'events' },
  { title: t('callbacks.field.enabled'), key: 'enabled', width: 90 },
  { title: t('callbacks.actions'), key: 'actions', width: 200 }
])

function onSelectionChange(keys: Array<string | number>): void {
  selectedRowKeys.value = keys.map((key) => Number(key))
}

async function load(p = page.value): Promise<void> {
  loading.value = true
  try {
    const data = await listTargets(p, pageSize.value)
    targets.value = data.list
    total.value = data.total
    page.value = p
  } catch (caught) {
    message.error(errText(caught, t('callbacks.loadFailed')))
    targets.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

// ---- 投递日志 ----
const logs = ref<DeliveryLog[]>([])
const logsLoading = ref(false)
const logsPage = ref(1)
const logPageSize = ref(20)
const logsTotal = ref(0)
const logStatus = ref<string | undefined>(undefined)
const statusOptions = computed(() =>
  (['success', 'failed', 'retrying'] as const).map((s) => ({ value: s, label: t(`callbacks.status.${s}`) }))
)
const logDetail = ref<DeliveryLog | null>(null)
const logDetailOpen = ref(false)

const logColumns = computed(() => [
  { title: 'ID', dataIndex: 'id', width: 70 },
  { title: t('callbacks.log.target'), dataIndex: 'targetId', width: 80 },
  { title: t('callbacks.log.event'), dataIndex: 'eventType', width: 150 },
  { title: 'URL', dataIndex: 'requestUrl', ellipsis: true },
  { title: 'HTTP', dataIndex: 'httpStatus', width: 80 },
  { title: 'Status', key: 'status', width: 100 },
  { title: t('callbacks.log.duration'), dataIndex: 'durationMs', width: 110 },
  { title: '', key: 'detail', width: 80 }
])

async function loadLogs(p = logsPage.value): Promise<void> {
  logsLoading.value = true
  try {
    const data = await listLogs({
      page: p,
      pageSize: logPageSize.value,
      status: logStatus.value || undefined
    })
    logs.value = data.list
    logsTotal.value = data.total
    logsPage.value = p
  } catch (caught) {
    message.error(errText(caught, t('callbacks.loadFailed')))
    logs.value = []
    logsTotal.value = 0
  } finally {
    logsLoading.value = false
  }
}

function showLogDetail(record: DeliveryLog): void {
  logDetail.value = record
  logDetailOpen.value = true
}

// ---- 新建 / 编辑抽屉 ----
interface EditorForm {
  name: string
  targetType: TargetType
  baseUrl: string
  authType: AuthType
  authHeaderName: string
  authToken: string
  timeoutMs: number
  retryMaxAttempts: number
  retryBackoffMs: number
  events: EventType[]
}

const editorOpen = ref(false)
const editingId = ref<number | null>(null)
const editingSnapshot = ref<CallbackTarget | null>(null)
const saving = ref(false)
const eventOptions = (['transcript', 'segment_attributed', 'session_end'] as EventType[]).map((v) => ({
  value: v,
  label: v
}))
const filterSpeakers = ref<string[]>([])
const filterMinTextLen = ref<number | undefined>(undefined)

const defaultForm = (): EditorForm => ({
  name: '',
  targetType: 'python',
  baseUrl: '',
  authType: 'none',
  authHeaderName: '',
  authToken: '',
  timeoutMs: 3000,
  retryMaxAttempts: 3,
  retryBackoffMs: 500,
  events: ['transcript']
})
const form = reactive<EditorForm>(defaultForm())

const authTypeOptions = computed(() =>
  form.targetType === 'java'
    ? [{ value: 'header_token' as AuthType, label: 'header_token' }]
    : (['none', 'bearer', 'header_token'] as AuthType[]).map((v) => ({ value: v, label: v }))
)

// Java 目标鉴权固定 header_token（后端 _validate_protocol 会拒绝其他取值）。
watch(
  () => form.targetType,
  (type) => {
    if (type === 'java') form.authType = 'header_token'
  }
)

function openCreate(): void {
  Object.assign(form, defaultForm())
  editingId.value = null
  editingSnapshot.value = null
  filterSpeakers.value = []
  filterMinTextLen.value = undefined
  editorOpen.value = true
}

function openEdit(record: CallbackTarget): void {
  Object.assign(form, {
    ...defaultForm(),
    name: record.name,
    targetType: record.targetType,
    baseUrl: record.baseUrl,
    authType: record.authType,
    authHeaderName: record.authHeaderName ?? '',
    authToken: record.authToken,
    timeoutMs: record.timeoutMs,
    retryMaxAttempts: record.retryMaxAttempts,
    retryBackoffMs: record.retryBackoffMs,
    events: [...record.events]
  })
  editingId.value = record.id
  editingSnapshot.value = record
  filterSpeakers.value = [...(record.filters?.speakers ?? [])]
  filterMinTextLen.value = record.filters?.min_text_len
  editorOpen.value = true
}

function resetEditor(): void {
  Object.assign(form, defaultForm())
  editingId.value = null
  editingSnapshot.value = null
}

async function save(): Promise<void> {
  saving.value = true
  try {
    const hasFilters =
      filterSpeakers.value.length > 0 || filterMinTextLen.value !== undefined
    const payload: Partial<CallbackTarget> = {
      name: form.name,
      targetType: form.targetType,
      baseUrl: form.baseUrl,
      authType: form.authType,
      authHeaderName: form.authHeaderName || null,
      authToken: form.authToken,
      extraHeaders: editingSnapshot.value?.extraHeaders ?? {},
      timeoutMs: form.timeoutMs,
      retryMaxAttempts: form.retryMaxAttempts,
      retryBackoffMs: form.retryBackoffMs,
      events: [...form.events],
      enabled: editingSnapshot.value?.enabled ?? true,
      filters: hasFilters
        ? {
            ...(filterSpeakers.value.length > 0 ? { speakers: filterSpeakers.value } : {}),
            ...(filterMinTextLen.value !== undefined ? { min_text_len: filterMinTextLen.value } : {})
          }
        : null
    }
    if (editingId.value !== null) await updateTarget(editingId.value, payload)
    else await createTarget(payload)
    message.success(t('callbacks.saved'))
    editorOpen.value = false
    resetEditor()
    await load()
  } catch (caught) {
    message.error(errText(caught, t('callbacks.saveFailed')))
  } finally {
    saving.value = false
  }
}

// ---- 行内与批量操作 ----
async function toggleEnabled(record: CallbackTarget): Promise<void> {
  try {
    await updateTarget(record.id, { ...record, enabled: !record.enabled })
    await load()
  } catch (caught) {
    message.error(errText(caught, t('callbacks.actionFailed')))
  }
}

async function removeOne(record: CallbackTarget): Promise<void> {
  try {
    await deleteTarget(record.id)
    message.success(t('callbacks.deleted'))
    await load()
  } catch (caught) {
    message.error(errText(caught, t('callbacks.actionFailed')))
  }
}

async function batch(action: 'enable' | 'disable' | 'delete'): Promise<void> {
  try {
    await batchTargets(selectedRowKeys.value, action)
    selectedRowKeys.value = []
    message.success(t('callbacks.saved'))
    await load()
  } catch (caught) {
    message.error(errText(caught, t('callbacks.actionFailed')))
  }
}

// 测试投递是真实请求：同一目标进行中置 loading，全局同时只允许一条。
const testingId = ref<number | null>(null)

async function runTest(record: CallbackTarget): Promise<void> {
  if (testingId.value !== null) return
  testingId.value = record.id
  try {
    const result = await testTarget(record.id)
    if (result.ok) {
      message.success(`${t('callbacks.testOk')} (HTTP ${result.httpStatus}, ${result.durationMs}ms)`)
    } else {
      message.error(`${t('callbacks.testFail')}: ${result.error}`)
    }
  } catch (caught) {
    message.error(errText(caught, t('callbacks.testFail')))
  } finally {
    testingId.value = null
  }
}

onMounted(() => {
  void load()
  void loadLogs()
})
</script>

<style scoped lang="less">
.callbacks {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__bar {
    margin-bottom: 12px;
  }

  &__tag {
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 2px;
  }

  &__hint {
    color: var(--s2s-color-muted);
    font-size: 12px;
    margin-top: 4px;
  }

  &__payload {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    margin: 0;
    max-height: 220px;
    overflow: auto;
    white-space: pre-wrap;
  }
}
</style>
