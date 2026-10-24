<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { AppError } from '@/api/client'
import { fetchVoiceAudio } from '@/api/voices'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import VoiceCreateDialog from '@/components/VoiceCreateDialog.vue'
import VoiceLibraryTable from '@/components/VoiceLibraryTable.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useVoicesStore } from '@/stores/voices'
import type { VoiceFilter, VoiceRow, VoiceSource } from '@/types/voice-library'
import { describeInUse, sourceLabel } from '@/utils/voice-text'

const store = useVoicesStore()
const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const filter = ref<VoiceFilter>({})
const dialogOpen = ref(false)
const createBackend = ref('')
const auditionRow = ref<VoiceRow | null>(null)
const auditionUrl = ref('')
const auditionError = ref<AppError | null>(null)
const notice = ref('')
const deleteError = ref<AppError | null>(null)

const backendOptions = computed(() =>
  store.catalogued.map((item) => ({ value: item.backend, label: item.backend }))
)

const createSources = computed<VoiceSource[]>(
  () => store.catalogued.find((item) => item.backend === createBackend.value)?.sources ?? []
)

const filterCount = computed(() => Object.values(filter.value).filter((value) => value).length)

async function reload(): Promise<void> {
  await store.load({ ...filter.value })
}

onMounted(async () => {
  await Promise.all([store.loadBackends(), store.load({})])
  createBackend.value = store.catalogued[0]?.backend ?? ''
})

function applyFilter(patch: Partial<VoiceFilter>): void {
  filter.value = { ...filter.value, ...patch }
  void reload()
}

function clearFilter(): void {
  filter.value = {}
  void reload()
}

async function audition(row: VoiceRow): Promise<void> {
  closeAudition()
  auditionRow.value = row
  try {
    auditionUrl.value = await fetchVoiceAudio(row.id)
  } catch (caught) {
    auditionError.value = caught instanceof AppError ? caught : new AppError('unknown', '试听加载失败')
  }
}

function closeAudition(): void {
  if (auditionUrl.value) URL.revokeObjectURL(auditionUrl.value)
  auditionUrl.value = ''
  auditionRow.value = null
  auditionError.value = null
}

async function duplicate(row: VoiceRow): Promise<void> {
  notice.value = ''
  deleteError.value = null
  if (await store.duplicate(row.id)) notice.value = `已复制「${row.name}」`
  else deleteError.value = store.error
}

async function remove(row: VoiceRow): Promise<void> {
  notice.value = ''
  deleteError.value = null
  const confirmed = await askConfirm({
    title: '删除音色',
    content: `删除「${row.name}」会把音频与预计算产物一起移除，且不可恢复。`
  })
  if (!confirmed) return
  if (await store.remove(row.id)) {
    notice.value = `已删除「${row.name}」`
    return
  }
  // 409 的 detail 是唯一可信的引用计数来源，原样翻成那一句固定文案。
  deleteError.value =
    store.error?.code === 'voice_in_use'
      ? new AppError('voice_in_use', describeInUse(row.name, store.error.detail))
      : store.error
}

function onCreated(): void {
  dialogOpen.value = false
  notice.value = '音色已创建，预计算完成后可以选择它'
  void reload()
}
</script>

<template>
  <div class="voices">
    <div class="voices__toolbar">
      <a-select
        :value="filter.backend ?? undefined"
        :options="backendOptions"
        placeholder="后端"
        allow-clear
        class="voices__filter"
        @change="(value: unknown) => applyFilter({ backend: value ? String(value) : undefined })"
      />
      <a-select
        :value="filter.source ?? undefined"
        :options="(['builtin', 'clone', 'design'] as VoiceSource[]).map((value) => ({ value, label: sourceLabel(value) }))"
        placeholder="来源"
        allow-clear
        class="voices__filter"
        @change="(value: unknown) => applyFilter({ source: value ? String(value) : undefined })"
      />
      <a-select
        :value="filter.status ?? undefined"
        :options="[
          { value: 'ready', label: '可用' },
          { value: 'precomputing', label: '制作中' },
          { value: 'failed', label: '失败' },
          { value: 'draft', label: '草稿' }
        ]"
        placeholder="状态"
        allow-clear
        class="voices__filter"
        @change="(value: unknown) => applyFilter({ status: value ? String(value) : undefined })"
      />
      <a-input-search
        :value="filter.q ?? ''"
        placeholder="按名字搜索"
        allow-clear
        class="voices__search"
        @search="(value: string) => applyFilter({ q: value || undefined })"
      />
      <a-button v-if="filterCount > 0" type="link" @click="clearFilter">清空筛选</a-button>

      <span class="voices__spacer" />

      <a-select
        v-model:value="createBackend"
        :options="backendOptions"
        placeholder="后端"
        class="voices__filter"
      />
      <a-button type="primary" :disabled="!createBackend" @click="dialogOpen = true">新建音色</a-button>
    </div>

    <a-alert v-if="notice" type="success" show-icon :message="notice" />
    <ErrorBanner :error="deleteError" />
    <ErrorBanner :error="store.error?.code === 'voice_in_use' ? null : store.error" />

    <VoiceLibraryTable
      :rows="store.rows"
      :loading="store.loading"
      @audition="audition"
      @duplicate="duplicate"
      @remove="remove"
    />

    <a-empty
      v-if="!store.loading && store.rows.length === 0"
      description="还没有音色：上传一段参考音频，或直接用后端内置音色"
    />

    <VoiceCreateDialog
      :open="dialogOpen"
      :backend="createBackend"
      :sources="createSources"
      @update:open="(open: boolean) => (dialogOpen = open)"
      @created="onCreated"
    />

    <a-modal
      :open="auditionRow !== null"
      :title="auditionRow ? `试听 · ${auditionRow.name}` : '试听'"
      :footer="null"
      :width="520"
      @cancel="closeAudition"
    >
      <ErrorBanner :error="auditionError" />
      <audio v-if="auditionUrl" :src="auditionUrl" controls preload="auto" class="voices__player" />
      <p class="voices__hint">
        试听走 <code>GET /api/v1/voices/{{ '{id}' }}/audio</code> 的 Range 读，不经过 8765，也不占用 pipeline。
      </p>
    </a-modal>

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
.voices {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__toolbar {
    align-items: center;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  &__filter {
    width: 140px;
  }

  &__search {
    width: 200px;
  }

  &__spacer {
    flex: 1;
  }

  &__player {
    width: 100%;
  }

  &__hint {
    color: #6f7891;
    font-size: 12px;
    margin: 8px 0 0;
  }
}
</style>
