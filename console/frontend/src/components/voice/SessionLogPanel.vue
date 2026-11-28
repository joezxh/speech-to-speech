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
        <!-- 卡片流（原型 .sess）：live/待保存卡置顶，其后是后端记录列表卡。 -->
        <SessionCards :cards="cards" @open="openRecord" />
        <p v-if="!store.loading && !cards.length" class="slp__empty">{{ t('sessions.noRecords') }}</p>
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
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import SessionCards from '@/components/voice/SessionCards.vue'
import type { LiveCard, SessionCardLine, SessionCardState, SessionCardVM } from '@/components/voice/SessionCards.vue'
import SessionRecordDetail from '@/components/voice/SessionRecordDetail.vue'
import { usableEntriesOf, useSessionRecordsStore } from '@/stores/sessionRecords'
import type { SessionRecordRow } from '@/api/sessionRecords'
import type { TranscriptEntry } from '@/features/voice/types'

const props = defineProps<{
  tab: 'log' | 'route'
  /** 通话中的 live 卡 / 挂断后的待处置卡；null = 没有进行中的卡。 */
  live: LiveCard | null
  /** 保存流程状态：pending=保存中，saved/partial/unsaved=终态（决定卡的处置）。 */
  saveState: 'pending' | 'saved' | 'partial' | 'unsaved'
}>()
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

/** saveState → 卡片徽标态：保存中沿用 live 外观，saved 卡会被合并移除。 */
function liveCardState(): SessionCardState {
  if (props.saveState === 'unsaved') return 'unsaved'
  if (props.saveState === 'partial') return 'partial'
  if (props.saveState === 'saved') return 'done'
  return 'live'
}

/** 逐行转写 → 卡片行（ordinal = usableEntriesOf 下标，与 clip.messageOrdinal 同键；tool 行不渲染）。 */
function liveLinesOf(entries: readonly TranscriptEntry[]): SessionCardLine[] {
  return usableEntriesOf(entries)
    .map((entry, ordinal) => ({ entry, ordinal }))
    .filter(({ entry }) => entry.role !== 'tool')
    .map(({ entry, ordinal }) => ({
      ordinal,
      role: entry.role === 'assistant' ? ('assistant' as const) : ('user' as const),
      asr: entry.role === 'user' ? entry.text : '',
      text: entry.role === 'assistant' ? entry.text : '',
      stt:
        entry.role === 'user'
          ? entry.text.trim() !== ''
            ? ('ok' as const)
            : entry.audio
              ? ('fail' as const)
              : ('none' as const)
          : ('none' as const),
      tts:
        entry.role === 'assistant'
          ? entry.text.trim() !== '' && !entry.interrupted
            ? ('ok' as const)
            : entry.latency
              ? ('fail' as const)
              : ('none' as const)
          : ('none' as const),
      durMs: entry.audio?.durationMs ?? 0,
      audioUrl: entry.audio?.url ?? null
    }))
}

function fmtClock(at: number): string {
  return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const cards = computed<SessionCardVM[]>(() => {
  const list: SessionCardVM[] = []
  if (props.live) {
    const firstAssistant = usableEntriesOf(props.live.entries).find(
      (entry) => entry.role === 'assistant' && entry.latency?.tts_ttfa_s != null
    )
    list.push({
      key: `live:${props.live.pipelineSessionId || 'adhoc'}`,
      kind: 'live',
      state: liveCardState(),
      when: fmtClock(props.live.startedAtMs ?? Date.now()),
      inst: props.live.instanceId,
      node: props.live.node,
      lines: liveLinesOf(props.live.entries),
      id: props.live.pipelineSessionId || '—',
      turns: props.live.entries.filter((entry) => entry.role === 'assistant').length,
      durMs: props.live.startedAtMs ? Math.max(0, Date.now() - props.live.startedAtMs) : 0,
      ttfaMs:
        firstAssistant?.latency?.tts_ttfa_s != null
          ? Math.round(firstAssistant.latency.tts_ttfa_s * 1000)
          : null
    })
  }
  for (const row of store.rows) list.push(savedCardVm(row))
  return list
})

/** 后端列表行卡：无逐行消息（不逐行拉详情），用摘录展示；点开详情回放片段。 */
function savedCardVm(row: SessionRecordRow): SessionCardVM {
  return {
    key: `row:${row.id}`,
    kind: 'saved',
    state: row.state,
    when: row.createdAt,
    inst: row.instanceId,
    node: row.node,
    lines: [],
    excerpt: row.excerpt,
    id: row.pipelineSessionId || String(row.id),
    turns: row.turns,
    durMs: row.durationMs,
    ttfaMs: row.ttfaMs,
    recordId: row.id
  }
}

function openRecord(recordId: number): void {
  void store.openDetail(recordId)
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
