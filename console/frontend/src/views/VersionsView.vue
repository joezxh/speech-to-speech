<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import { getVersions, rollbackProfile } from '@/api/profiles'
import { releasesApi, type ReleaseRow } from '@/api/releases'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import VersionTable from '@/components/VersionTable.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useConsoleStore } from '@/stores/console'
import type { VersionRow } from '@/types/profile'
import { rollPct, stageDots } from './release.viewmodel'

const { t } = useI18n()
const consoleStore = useConsoleStore()
const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const rows = ref<VersionRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<AppError | null>(null)
const rollbackError = ref<AppError | null>(null)
// 发布流水线台账（Task 24 的 R1–R4 在页面的呈现；console 只记账）。
const releases = ref<ReleaseRow[]>([])
const pendingBackfill = ref(0)
/** 当前 live 的那一行不应该有「回滚到它」：它已经是了。 */
const liveVersion = computed(() => rows.value.find((row) => row.status === 'live')?.version ?? null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await getVersions(consoleStore.profile, page.value, pageSize.value)
    rows.value = data.list
    total.value = data.total
    const [ledger, summary] = await Promise.all([
      releasesApi.list(),
      releasesApi.summary(),
    ])
    releases.value = ledger.releases
    pendingBackfill.value = summary.pending_backfill
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', t('release.loadFailed'))
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch([() => consoleStore.profile, page, pageSize], () => void load(), { immediate: true })

async function rollback(target: number): Promise<void> {
  const confirmed = await askConfirm({
    title: t('release.rollbackConfirmTitle', { version: target }),
    content: t('release.rollbackConfirmContent')
  })
  if (!confirmed) return
  rollbackError.value = null
  try {
    await rollbackProfile(consoleStore.profile, { targetVersion: target, note: `rollback to v${target}` })
    await load()
    await consoleStore.refreshStatus()
  } catch (caught) {
    rollbackError.value = caught instanceof AppError ? caught : new AppError('unknown', t('release.rollbackFailed'))
  }
}
</script>

<template>
  <div class="versions">
    <section class="ledger">
      <h2>{{ t('release.ledgerTitle') }}
        <span v-if="pendingBackfill" class="backfill">{{ t('release.pendingBackfill') }}: {{ pendingBackfill }}</span>
      </h2>
      <table class="ledger__tbl">
        <thead><tr><th>version</th><th>profile</th><th>pipeline</th><th>rollout</th><th>by</th></tr></thead>
        <tbody>
          <tr v-for="release in releases" :key="release.release_id">
            <td>{{ release.version }}</td>
            <td>{{ release.profile }}</td>
            <td>
              <span v-for="dot in stageDots(release)" :key="dot.key" class="dot" :class="dot.state" :title="dot.key" />
            </td>
            <td><span class="bar"><span class="bar__fill" :style="{ width: `${rollPct(release)}%` }" /></span></td>
            <td>{{ release.created_by }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <ErrorBanner :error="error" />
    <ErrorBanner :error="rollbackError" />
    <VersionTable :rows="rows" :loading="loading" :live-version="liveVersion" @rollback="rollback" />
    <a-pagination
      v-model:current="page"
      v-model:page-size="pageSize"
      :total="total"
      size="small"
      show-size-changer
      :page-size-options="['20', '50', '100']"
    />

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
.versions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ledger {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
}
.ledger__tbl { width: 100%; border-collapse: collapse; }
.ledger__tbl th, .ledger__tbl td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; background: var(--muted); }
.dot.done { background: var(--ok-text); }
.dot.active { background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.backfill { margin-left: 8px; font-size: 12px; color: var(--warn-text); }
.bar { display: inline-block; width: 120px; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
.bar__fill { display: block; height: 100%; background: var(--accent); }
</style>
