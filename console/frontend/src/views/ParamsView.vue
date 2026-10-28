<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DiffTable from '@/components/DiffTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import ParamField from '@/components/ParamField.vue'
import ParamTree from '@/components/ParamTree.vue'
import PublishDialog from '@/components/PublishDialog.vue'
import VoicePicker from '@/components/VoicePicker.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useAuthStore } from '@/stores/auth'
import { useCatalogStore } from '@/stores/catalog'
import { useConsoleStore } from '@/stores/console'
import { useDraftStore } from '@/stores/draft'
import { useVoicesStore } from '@/stores/voices'
import type { CatalogEntry, Exposure } from '@/types/catalog'
import { countLabel, dedupe, groupByStage, isReadOnlyRow } from '@/utils/catalog-view'
import { baseline, buildPatch, resetValue, type Values } from '@/utils/draft-patch'
import { formatTime } from '@/utils/format'
import { bindings, slotKey, voiceIdIn, voiceSlot, type VoiceSlot } from '@/utils/voice-refs'

const { t } = useI18n()

const auth = useAuthStore()
const consoleStore = useConsoleStore()
const catalogStore = useCatalogStore()
const draftStore = useDraftStore()
const voicesStore = useVoicesStore()
const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const exposure = ref<Exposure>('advanced')
/** 选中 `stage::backend` 分组（17 组，§6.1）；空串表示不过滤。 */
const group = ref('')
const values = ref<Values>({})
const saveError = ref<AppError | null>(null)
const notice = ref('')
const publishOpen = ref(false)

const deduped = computed(() => dedupe(catalogStore.entries))
/** 表单用去重后的 193 行：同名字段只出现一次（§6.1）。 */
const items = computed(() => deduped.value.items)
/** 树用 catalog 原始 196 行：每组的条数必须与 §6.1 的表逐字相等，合计 196。 */
const groups = computed(() => groupByStage(catalogStore.entries))
/** 计数行只能由纯函数生成，不手写数字（§14.7）。 */
const countText = computed(() => countLabel(catalogStore.entries.length, deduped.value))
const groupReadOnly = computed(() => groups.value.find((item) => item.key === group.value)?.readOnly ?? false)

const LEVEL_ORDER: Exposure[] = ['basic', 'advanced', 'expert', 'ops']

/**
 * 分级表只管「能不能写」：只读行（`type=fixed` 与 deploy/env/client）没有写入口，
 * 所以在任何一档都显示——藏起来只会让运维以为参数不存在（§7.3）。
 */
function withinLevel(entry: CatalogEntry): boolean {
  if (isReadOnlyRow(entry)) return true
  return LEVEL_ORDER.indexOf(entry.exposure) <= LEVEL_ORDER.indexOf(exposure.value)
}

/** operator 看得见 expert/ops，只是控件禁用；真正的拦截在服务端 403（§7.3 / A.0.2）。 */
const visible = computed(() =>
  items.value.filter(
    (entry) => (group.value === '' || `${entry.stage}::${entry.backend ?? ''}` === group.value) && withinLevel(entry)
  )
)

/** basic / advanced 与只读行直出；expert / ops 折进一个折叠面板（§7.3）。 */
const direct = computed(() =>
  visible.value.filter((entry) => isReadOnlyRow(entry) || entry.exposure === 'basic' || entry.exposure === 'advanced')
)
const folded = computed(() =>
  visible.value.filter((entry) => !isReadOnlyRow(entry) && (entry.exposure === 'expert' || entry.exposure === 'ops'))
)
const opsCount = computed(() => folded.value.filter((entry) => entry.exposure === 'ops').length)

/** 音色路径的默认缓存目录：catalog 里取不到时的兜底值（§3.11.2）。 */
const CACHE_DIR_FALLBACK = '/app/data/voices'

type RenderRow =
  | { kind: 'field'; entry: CatalogEntry }
  | { kind: 'voice'; entry: CatalogEntry; slot: VoiceSlot }

/**
 * 音色字段按「后端 × 来源」收成三个控件位：同一个槽位的后续字段不再各渲染一次
 * （14 条字段 → 每个后端最多 3 个选择器，§3.11.1）。非音色字段原样逐个渲染，
 * 所以它们仍是 `ParamField`，草稿与 diff 的形状不变。
 */
function planRows(entries: CatalogEntry[]): RenderRow[] {
  const seen = new Set<string>()
  const rows: RenderRow[] = []
  for (const entry of entries) {
    const slot = voiceSlot(entry.name)
    const key = slotKey(entry.backend, entry.name)
    if (slot === null || key === null) {
      rows.push({ kind: 'field', entry })
      continue
    }
    if (seen.has(key)) continue
    seen.add(key)
    rows.push({ kind: 'voice', entry, slot })
  }
  return rows
}

const directRows = computed(() => planRows(direct.value))
const foldedRows = computed(() => planRows(folded.value))

const cacheDir = computed(() => {
  const entry = items.value.find((item) => item.name === 'qwen3_tts_ref_cache_dir')
  const value = entry ? values.value[entry.key] : null
  return typeof value === 'string' && value.trim() ? value.trim() : CACHE_DIR_FALLBACK
})

/** 槽位当前值：优先拿带 `/voices/<id>/` 的那个字段，其次第一个非空字段。 */
function slotCurrent(entry: CatalogEntry, slot: VoiceSlot): unknown {
  const fields = bindings(slot, entry.backend ?? '')
  if (!fields) return null
  const keys = Object.values(fields).map((name) => `${entry.stage}.${name}`)
  for (const key of keys) {
    if (voiceIdIn(values.value[key])) return values.value[key]
  }
  for (const key of keys) {
    const value = values.value[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

/** `bindPatch` 给的是不带 stage 的字段名，这里补回 `key` 形状再并进表单。 */
function applyVoicePatch(stage: string, patch: Record<string, unknown>): void {
  const keyed: Values = {}
  for (const [name, value] of Object.entries(patch)) keyed[`${stage}.${name}`] = value
  values.value = { ...values.value, ...keyed }
}

const patch = computed(() => buildPatch(items.value, values.value, draftStore.draft))
const dirty = computed(() => Object.keys(patch.value).length > 0)
/**
 * 已保存的草稿也要能丢：`DELETE /draft` 是参数页三个动作之一（设计 1587），
 * 只跟 `dirty` 联动会让保存后的草稿永远清不掉——页面显示「草稿」标签却没有入口。
 */
const draftExists = computed(() => Object.keys(draftStore.draft ?? {}).length > 0)
const structural = computed(() => draftStore.validation?.mode === 'structural')

async function reload(): Promise<void> {
  saveError.value = null
  // 目录不带 exposure 参数：计数行是 catalog 级陈述（196 条 · 193 个唯一名），
  // 服务端按级别裁剪后 `entries.length` 就变成分子，两个数字不可兼得。
  await catalogStore.load()
  try {
    await draftStore.load(consoleStore.profile)
  } catch (error) {
    saveError.value = error instanceof AppError ? error : new AppError('unknown', t('deploy.draftLoadFailed'))
  }
  // 音色库是旁路：读失败不影响参数页，只让选择器少几个选项。
  void voicesStore.load()
  void voicesStore.loadBackends()
  values.value = baseline(items.value, draftStore.draft)
  // 切 profile 会改变分组集合，但不能把用户刚选中的组默默换掉。
  if (!groups.value.some((item) => item.key === group.value)) group.value = groups.value[0]?.key ?? ''
}

watch(() => consoleStore.profile, () => void reload(), { immediate: true })

function reset(key: string): void {
  const entry = items.value.find((candidate) => candidate.key === key)
  if (entry) values.value = { ...values.value, [key]: resetValue(entry, draftStore.draft) }
}

function isMasked(key: string): boolean {
  return draftStore.masked.includes(key)
}

function inDraft(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(draftStore.draft, key)
}

function isDisabled(entry: CatalogEntry): boolean {
  return !auth.isAdmin && (entry.exposure === 'expert' || entry.exposure === 'ops')
}

async function save(): Promise<void> {
  saveError.value = null
  notice.value = ''
  if (!dirty.value) {
    notice.value = t('deploy.noticeNone')
    return
  }
  try {
    await draftStore.save(consoleStore.profile, patch.value)
    // 保存响应不带 `updatedAt` / `updatedBy`（A.3 的契约），重读一次让工具栏里的
    // 「draft v0 · 谁 · 何时」与刚写进去的那一行一致，而不是停在「未编辑」。
    await draftStore.load(consoleStore.profile).catch(() => undefined)
    values.value = baseline(items.value, draftStore.draft)
    notice.value = t('deploy.noticeSaved', { version: draftStore.baseVersion ?? 0 })
  } catch (error) {
    saveError.value = error instanceof AppError ? error : new AppError('unknown', t('deploy.saveFailed'))
  }
}

async function discard(): Promise<void> {
  const confirmed = await askConfirm({
    title: t('deploy.discard'),
    content: t('deploy.discardConfirm')
  })
  if (!confirmed) return
  saveError.value = null
  try {
    await draftStore.discard(consoleStore.profile)
    values.value = baseline(items.value, draftStore.draft)
    notice.value = t('deploy.noticeDiscarded')
  } catch (error) {
    saveError.value = error instanceof AppError ? error : new AppError('unknown', t('deploy.discardFailed'))
  }
}

/** 发布后草稿已消失且盘上文件已换：表单、基线、实例状态三个都得重读。 */
async function onPublished(): Promise<void> {
  await reload()
  await consoleStore.refreshStatus()
  notice.value = t('deploy.noticePublished')
}
</script>

<template>
  <div class="params">
    <div class="params__toolbar">
      <a-select
        :value="exposure"
        :options="[
          { value: 'basic', label: t('deploy.exposure.basic') },
          { value: 'advanced', label: t('deploy.exposure.advanced') },
          { value: 'expert', label: t('deploy.exposure.expert') },
          { value: 'ops', label: t('deploy.exposure.ops') }
        ]"
        class="params__exposure"
        @change="(value: unknown) => (exposure = value as Exposure)"
      />

      <span class="params__count">{{ countText }}</span>

      <span class="params__meta">
        draft v{{ draftStore.baseVersion ?? 0 }} · {{ draftStore.updatedBy || t('deploy.notEdited') }}
        <template v-if="draftStore.updatedAt"> · {{ formatTime(draftStore.updatedAt) }}</template>
      </span>

      <span class="params__spacer" />

      <a-badge :status="dirty ? 'warning' : 'default'" :text="dirty ? t('deploy.dirty') : t('deploy.clean')" />
      <a-button :disabled="(!dirty && !draftExists) || draftStore.saving" @click="discard">
        {{ t('deploy.discard') }}
      </a-button>
      <a-button
        type="primary"
        :disabled="!dirty"
        :loading="draftStore.saving"
        @click="save"
      >
        {{ t('deploy.saveDraft') }}
      </a-button>
      <!-- 本地有未保存改动时不能发：发出去的是库里的草稿，不是屏幕上看到的值。 -->
      <a-button
        type="primary"
        danger
        :disabled="dirty || draftStore.saving"
        @click="publishOpen = true"
      >
        {{ t('deploy.publish') }}
      </a-button>
    </div>

    <a-alert
      v-if="structural"
      type="warning"
      show-icon
      :message="t('deploy.structuralOnly')"
      :description="t('deploy.structuralDesc')"
    />
    <a-alert v-else-if="notice" type="info" show-icon :message="notice" />
    <a-alert
      v-if="groupReadOnly"
      type="info"
      show-icon
      :message="t('deploy.groupReadOnly')"
      :description="t('deploy.groupReadOnlyDesc')"
    />
    <ErrorBanner :error="saveError" />
    <ErrorBanner :error="catalogStore.error" />

    <div class="params__body">
      <aside class="params__tree">
        <ParamTree
          :entries="catalogStore.entries"
          :selected="group"
          :uncatalogued="voicesStore.uncatalogued"
          @select="(value: string) => (group = value)"
        />
      </aside>

      <section class="params__form">
        <template v-for="row in directRows" :key="row.entry.key">
          <VoicePicker
            v-if="row.kind === 'voice'"
            :entry="row.entry"
            :backend="row.entry.backend ?? ''"
            :voices="voicesStore.rows"
            :current="slotCurrent(row.entry, row.slot)"
            :cache-dir="cacheDir"
            :in-draft="inDraft(row.entry.key)"
            :disabled="isDisabled(row.entry)"
            @update:model-value="(patch: Record<string, unknown>) => applyVoicePatch(row.entry.stage, patch)"
          />
          <ParamField
            v-else
            :entry="row.entry"
            :model-value="values[row.entry.key]"
            :masked="isMasked(row.entry.key)"
            :in-draft="inDraft(row.entry.key)"
            :suggested="row.entry.exposure === 'advanced' && row.entry.default != null ? row.entry.default : undefined"
            :disabled="isDisabled(row.entry)"
            @update:model-value="(value: unknown) => (values = { ...values, [row.entry.key]: value })"
            @reset="reset(row.entry.key)"
          />
        </template>

        <a-collapse v-if="folded.length" class="params__fold" ghost>
          <a-collapse-panel
            key="expert-ops"
            :header="t('deploy.foldHeader', { count: folded.length, ops: opsCount })"
          >
            <template v-for="row in foldedRows" :key="row.entry.key">
              <VoicePicker
                v-if="row.kind === 'voice'"
                :entry="row.entry"
                :backend="row.entry.backend ?? ''"
                :voices="voicesStore.rows"
                :current="slotCurrent(row.entry, row.slot)"
                :cache-dir="cacheDir"
                :in-draft="inDraft(row.entry.key)"
                :disabled="isDisabled(row.entry)"
                @update:model-value="(patch: Record<string, unknown>) => applyVoicePatch(row.entry.stage, patch)"
              />
              <ParamField
                v-else
                :entry="row.entry"
                :model-value="values[row.entry.key]"
                :masked="isMasked(row.entry.key)"
                :in-draft="inDraft(row.entry.key)"
                :disabled="isDisabled(row.entry)"
                @update:model-value="(value: unknown) => (values = { ...values, [row.entry.key]: value })"
                @reset="reset(row.entry.key)"
              />
            </template>
          </a-collapse-panel>
        </a-collapse>

        <a-empty v-if="!visible.length && !catalogStore.loading" :description="t('deploy.noParams')" />
      </section>

      <aside class="params__preview">
        <h3>{{ t('deploy.changesTitle', { count: Object.keys(patch).length }) }}</h3>
        <DiffTable :draft="patch" :masked="draftStore.masked" />
      </aside>
    </div>

    <ConfirmDialog
      :open="confirmOpen"
      :title="confirmTitle"
      :content="confirmContent"
      danger
      @answer="answerConfirm"
    />

    <PublishDialog
      :open="publishOpen"
      :profile="consoleStore.profile"
      :base-version="draftStore.baseVersion"
      :draft="draftStore.draft"
      :masked="draftStore.masked"
      @close="publishOpen = false"
      @published="onPublished"
    />
  </div>
</template>

<style scoped lang="less">
.params {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__toolbar {
    align-items: center;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }

  &__exposure {
    width: 168px;
  }

  &__count {
    color: #e6e8f0;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  &__meta {
    color: #8b93a7;
    font-size: 12px;
  }

  &__form {
    max-height: calc(100vh - 300px);
    overflow-y: auto;
    padding-right: 4px;
  }

  &__fold {
    border-top: 1px solid #1e2742;
    margin-top: 8px;

    :deep(.ant-collapse-header) {
      color: #d89614;
      font-size: 12px;
    }
  }

  &__spacer {
    flex: 1;
  }

  &__body {
    display: grid;
    gap: 16px;
    grid-template-columns: 200px minmax(320px, 1fr) 280px;
  }

  &__tree,
  &__preview {
    background: #141a2e;
    border-radius: 10px;
    padding: 12px;
  }

  &__preview h3 {
    color: #8b93a7;
    font-size: 12px;
    margin: 0 0 8px;
  }
}
</style>
