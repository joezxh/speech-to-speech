<template>
  <aside class="slp">
    <div class="slp__tabs" role="tablist">
      <button
        v-for="item in ['log', 'route']"
        :key="item"
        type="button"
        role="tab"
        class="slp__tab"
        :class="{ active: tab === item }"
        :aria-selected="tab === item"
        @click="emit('update:tab', item as 'log' | 'route')"
      >
        {{ item === 'log' ? t('sessions.tabLog') : t('sessions.tabRoute') }}
      </button>
    </div>

    <!-- 会话记录列表 / 详情抽屉（面板内切换，不打断对话） -->
    <div v-if="tab === 'log'" class="slp__body">
      <template v-if="store.detail">
        <button type="button" class="btn sm ghost slp__back" @click="store.closeDetail()">
          ← {{ t('sessions.backToList') }}
        </button>
        <SessionRecordDetail :record-id="store.detail.id" @close="store.closeDetail()" @changed="store.load()" />
      </template>
      <template v-else>
        <button type="button" class="btn sm slp__history" @click="router.push('/history')">
          {{ t('sessions.openHistory') }}
        </button>
        <button
          v-for="row in store.rows"
          :key="row.id"
          type="button"
          class="slp__card"
          @click="store.openDetail(row.id)"
        >
          <span class="slp__dot" :data-state="row.state"></span>
          <span class="slp__cardmain">
            <strong>{{ row.title }}</strong>
            <small>{{ row.createdAt }} · {{ row.instanceId || row.node || '—' }}</small>
            <span class="slp__badges">
              <PBadge kind="accent" :text="t('sessions.turnsBadge', { n: row.turns })" />
              <PBadge kind="ro" :text="fmtDuration(row.durationMs)" />
              <PBadge v-if="row.ttfaMs != null" kind="hot" :text="`TTFA ${row.ttfaMs}ms`" />
            </span>
          </span>
        </button>
        <p v-if="!store.loading && !store.rows.length" class="slp__empty">{{ t('sessions.noRecords') }}</p>
      </template>
    </div>

    <!-- 访问路由：最近的 LB 路由决策（只读） -->
    <div v-else class="slp__body">
      <div class="slp__routetoolbar">
        <button type="button" class="btn sm" @click="store.loadRouteLogs()">{{ t('common.refresh') }}</button>
      </div>
      <table class="slp__tbl">
        <thead>
          <tr>
            <th>{{ t('sessions.routeCol.time') }}</th>
            <th>{{ t('sessions.routeCol.instance') }}</th>
            <th>{{ t('sessions.routeCol.matched') }}</th>
            <th>{{ t('sessions.routeCol.tokens') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in store.routeLogs" :key="index">
            <td class="mono">{{ row.at }}</td>
            <td class="mono">{{ row.instanceId || '—' }}</td>
            <td>
              <PBadge :kind="row.matched ? 'ok' : 'equal'" :text="row.matched ? 'rule' : 'policy'" />
            </td>
            <td class="mono">{{ row.inputTokens }}/{{ row.outputTokens }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!store.routeLogs.length" class="slp__empty">{{ t('sessions.noRouteLogs') }}</p>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import PBadge from '@/components/proto/PBadge.vue'
import SessionRecordDetail from '@/components/voice/SessionRecordDetail.vue'
import { useSessionRecordsStore } from '@/stores/sessionRecords'

const props = defineProps<{ tab: 'log' | 'route' }>()
const emit = defineEmits<{ (e: 'update:tab', value: 'log' | 'route'): void }>()

const { t } = useI18n()
const router = useRouter()
const store = useSessionRecordsStore()

// 右栏常驻：按当前 tab 拉数据；切 tab 时补拉对应数据源。
watch(
  () => props.tab,
  (tab) => {
    if (tab === 'log') void store.load()
    else void store.loadRouteLogs()
  },
  { immediate: true }
)

function fmtDuration(ms: number): string {
  if (ms <= 0) return '0s'
  const totalSec = Math.round(ms / 1000)
  if (totalSec < 60) return `${totalSec}s`
  return `${Math.floor(totalSec / 60)}m${totalSec % 60}s`
}
</script>

<style scoped lang="less">
.slp {
  /* 右栏常驻卡（原型 .v-panel 语义）：由 voice-grid 的 360px 列撑开，不再悬浮抽屉。 */
  background: var(--voice-surface);
  border: 1px solid var(--voice-border);
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  padding: 16px;
  color: var(--voice-text);
  min-height: 0;

  &__tabs {
    display: flex;
    gap: 2px;
    margin: -16px -16px 12px;
    padding: 0 10px;
    border-bottom: 1px solid var(--voice-border);
  }
  &__tab {
    appearance: none;
    background: transparent;
    border: 0;
    border-bottom: 2px solid transparent;
    color: var(--voice-faint);
    font: inherit;
    font-size: 12.5px;
    padding: 13px 10px 10px;
    cursor: pointer;
    &.active {
      color: var(--voice-accent);
      border-bottom-color: var(--voice-accent);
      font-weight: 600;
    }
  }
  &__body {
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow-y: auto;
    min-height: 0;
    max-height: 62vh;
  }
  &__back {
    align-self: flex-start;
  }
  &__history {
    align-self: flex-start;
  }
  &__card {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    text-align: left;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: transparent;
    padding: 10px 12px;
    cursor: pointer;
    color: inherit;
    small {
      display: block;
      color: var(--muted);
      margin: 2px 0 6px;
    }
  }
  &__dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-top: 6px;
    flex-shrink: 0;
    background: var(--ok-text);
    &[data-state='failed'] {
      background: var(--danger-text);
    }
  }
  &__badges {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  &__routetoolbar {
    display: flex;
    justify-content: flex-end;
  }
  &__tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    th,
    td {
      text-align: left;
      padding: 6px 8px;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
  }
  &__empty {
    color: var(--muted);
    font-size: 12px;
    text-align: center;
    padding: 16px 0;
  }
}
</style>
