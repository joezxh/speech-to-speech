<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { AppError } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DiffTable from '@/components/DiffTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import ParamField from '@/components/ParamField.vue'
import ParamTree from '@/components/ParamTree.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useAuthStore } from '@/stores/auth'
import { useCatalogStore } from '@/stores/catalog'
import { useConsoleStore } from '@/stores/console'
import { useDraftStore } from '@/stores/draft'
import type { CatalogEntry, Exposure } from '@/types/catalog'
import { countLabel, dedupe, groupByStage, isReadOnlyRow } from '@/utils/catalog-view'
import { baseline, buildPatch, resetValue, type Values } from '@/utils/draft-patch'
import { formatTime } from '@/utils/format'

const auth = useAuthStore()
const consoleStore = useConsoleStore()
const catalogStore = useCatalogStore()
const draftStore = useDraftStore()
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
    saveError.value = error instanceof AppError ? error : new AppError('unknown', '草稿读取失败')
  }
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
    notice.value = '没有改动'
    return
  }
  try {
    await draftStore.save(consoleStore.profile, patch.value)
    // 保存响应不带 `updatedAt` / `updatedBy`（A.3 的契约），重读一次让工具栏里的
    // 「draft v0 · 谁 · 何时」与刚写进去的那一行一致，而不是停在「未编辑」。
    await draftStore.load(consoleStore.profile).catch(() => undefined)
    values.value = baseline(items.value, draftStore.draft)
    notice.value = `草稿已保存（v${draftStore.baseVersion ?? 0}）`
  } catch (error) {
    saveError.value = error instanceof AppError ? error : new AppError('unknown', '保存失败')
  }
}

async function discard(): Promise<void> {
  const confirmed = await askConfirm({
    title: '丢弃草稿',
    content: '草稿会被删除，已发布的版本不受影响。'
  })
  if (!confirmed) return
  saveError.value = null
  try {
    await draftStore.discard(consoleStore.profile)
    values.value = baseline(items.value, draftStore.draft)
    notice.value = '草稿已丢弃'
  } catch (error) {
    saveError.value = error instanceof AppError ? error : new AppError('unknown', '丢弃失败')
  }
}
</script>

<template>
  <div class="params">
    <div class="params__toolbar">
      <a-select
        :value="exposure"
        :options="[
          { value: 'basic', label: 'basic · 直出' },
          { value: 'advanced', label: 'advanced · 带建议值' },
          { value: 'expert', label: 'expert · 折叠 + 警告' },
          { value: 'ops', label: 'ops · 仅运维可见' }
        ]"
        class="params__exposure"
        @change="(value: unknown) => (exposure = value as Exposure)"
      />

      <span class="params__count">{{ countText }}</span>

      <span class="params__meta">
        draft v{{ draftStore.baseVersion ?? 0 }} · {{ draftStore.updatedBy || '未编辑' }}
        <template v-if="draftStore.updatedAt"> · {{ formatTime(draftStore.updatedAt) }}</template>
      </span>

      <span class="params__spacer" />

      <a-badge :status="dirty ? 'warning' : 'default'" :text="dirty ? '有未保存改动' : '无改动'" />
      <a-button :disabled="(!dirty && !draftExists) || draftStore.saving" @click="discard">
        丢弃草稿
      </a-button>
      <a-button
        type="primary"
        :disabled="!dirty"
        :loading="draftStore.saving"
        @click="save"
      >
        保存草稿
      </a-button>
    </div>

    <a-alert
      v-if="structural"
      type="warning"
      show-icon
      message="仅校验了结构"
      description="运行时包不在本进程，字段是否能被 pipeline 接受未经运行验证。"
    />
    <a-alert v-else-if="notice" type="info" show-icon :message="notice" />
    <a-alert
      v-if="groupReadOnly"
      type="info"
      show-icon
      message="该组只读"
      description="deploy / env / client 不在运维面可写范围：前两类改它要重建容器，第三类属对话页客户端。只读行不进 patch，也不会触发发布。"
    />
    <ErrorBanner :error="saveError" />
    <ErrorBanner :error="catalogStore.error" />

    <div class="params__body">
      <aside class="params__tree">
        <ParamTree :entries="catalogStore.entries" :selected="group" @select="(value: string) => (group = value)" />
      </aside>

      <section class="params__form">
        <ParamField
          v-for="entry in direct"
          :key="entry.key"
          :entry="entry"
          :model-value="values[entry.key]"
          :masked="isMasked(entry.key)"
          :in-draft="inDraft(entry.key)"
          :suggested="entry.exposure === 'advanced' && entry.default != null ? entry.default : undefined"
          :disabled="isDisabled(entry)"
          @update:model-value="(value: unknown) => (values = { ...values, [entry.key]: value })"
          @reset="reset(entry.key)"
        />

        <a-collapse v-if="folded.length" class="params__fold" ghost>
          <a-collapse-panel
            key="expert-ops"
            :header="`expert / ops ${folded.length} 条（含 ${opsCount} 条仅运维可见）—— 展开前先读完警告`"
          >
            <ParamField
              v-for="entry in folded"
              :key="entry.key"
              :entry="entry"
              :model-value="values[entry.key]"
              :masked="isMasked(entry.key)"
              :in-draft="inDraft(entry.key)"
              :disabled="isDisabled(entry)"
              @update:model-value="(value: unknown) => (values = { ...values, [entry.key]: value })"
              @reset="reset(entry.key)"
            />
          </a-collapse-panel>
        </a-collapse>

        <a-empty v-if="!visible.length && !catalogStore.loading" description="该级别下没有参数" />
      </section>

      <aside class="params__preview">
        <h3>本次改动（{{ Object.keys(patch).length }}）</h3>
        <DiffTable :draft="patch" :masked="draftStore.masked" />
        <!-- 发布入口由 Task 15 的 PublishPanel 挂在这里：草稿 → 校验 → 发布/热更 → 生效/回滚。 -->
      </aside>
    </div>

    <ConfirmDialog
      :open="confirmOpen"
      :title="confirmTitle"
      :content="confirmContent"
      danger
      @answer="answerConfirm"
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
