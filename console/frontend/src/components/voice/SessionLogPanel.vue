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

    <!-- 访问路由：键值行（对齐原型 pane-route）+ 工具开关区 + 最近路由决策留痕 -->
    <div v-else class="slp__body">
      <div class="slp__section">
        <h4>{{ t('sessions.route.title') }}</h4>
        <div v-for="row in routeRows" :key="row.label" class="v-row">
          <span>{{ row.label }}</span>
          <b>{{ row.value }}</b>
        </div>
      </div>
      <div class="slp__section">
        <h4>{{ t('sessions.route.tools') }}</h4>
        <div v-for="tool in toolRows" :key="tool.key" class="v-row">
          <span>{{ tool.label }}</span>
          <button
            type="button"
            role="switch"
            class="slp__switch"
            :class="{ on: voice.settings.tools[tool.key] }"
            :aria-checked="voice.settings.tools[tool.key] ? 'true' : 'false'"
            :aria-label="tool.label"
            @click="onToggleTool(tool.key)"
          ></button>
        </div>
      </div>
      <div class="slp__section">
        <h4>{{ t('sessions.route.recent') }}</h4>
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
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { useClusterStore } from '@/stores/cluster'
import { useVoiceStore } from '@/stores/voice'
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
const emit = defineEmits<{
  (e: 'update:tab', value: 'log' | 'route'): void
  (e: 'tool-change', key: 'web' | 'camera', value: boolean): void
}>()

const { t } = useI18n()
const router = useRouter()
const store = useSessionRecordsStore()
const clusters = useClusterStore()
const voice = useVoiceStore()

/* ── 访问路由：键值行数据源（原型 routeRow 3767-3777 行的行序） ── */
const routeRows = computed(() => {
  const row = clusters.currentRow
  return [
    { label: t('sessions.route.instance'), value: props.live?.instanceId || '—' },
    { label: t('sessions.route.endpoint'), value: props.live?.node ? `${props.live.node}:8765` : '—' },
    { label: t('sessions.route.node'), value: props.live?.node || '—' },
    { label: t('sessions.route.policy'), value: row ? t(`overview.policy.${row.policy}`) : '—' },
    { label: t('sessions.route.registry'), value: row?.registry || '—' },
    { label: t('sessions.route.sticky'), value: '300 s' },
    { label: t('sessions.route.voice'), value: voice.settings.voice },
    {
      label: t('sessions.route.lastttft'),
      value: voice.latency?.tts_ttfa_s != null ? `${Math.round(voice.latency.tts_ttfa_s * 1000)} ms` : '—'
    },
    { label: t('sessions.route.turn'), value: 'smart-turn' },
    { label: t('sessions.route.session'), value: props.live?.pipelineSessionId || '—' }
  ]
})

const toolRows = computed(() => [
  { key: 'web' as const, label: t('sessions.route.toolWeb') },
  { key: 'camera' as const, label: t('sessions.route.toolCamera') }
])

/** 面板是镜子不是第二个状态容器：开关只 emit，由 VoiceView 走 onToolsChange 同一链路。 */
function onToggleTool(key: 'web' | 'camera'): void {
  emit('tool-change', key, !voice.settings.tools[key])
}

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
  &__section {
    h4 {
      margin: 6px 0 4px;
      font-size: 11.5px;
      font-weight: 600;
      color: var(--voice-faint);
      letter-spacing: 0.04em;
    }
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

/* 原型 .v-row / .switch：键值行与工具开关 */
.v-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--voice-faint);
  padding: 5px 0;
  span {
    flex: 0 0 auto;
  }
  b {
    color: var(--voice-text);
    font-weight: 600;
    text-align: right;
    word-break: break-all;
  }
}

.slp__switch {
  appearance: none;
  width: 34px;
  height: 19px;
  border-radius: 999px;
  border: 1px solid var(--voice-border-strong);
  background: var(--voice-surface-mix, var(--voice-surface-2));
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
  &::after {
    content: '';
    position: absolute;
    top: 2px;
    left: 2px;
    width: 13px;
    height: 13px;
    border-radius: 50%;
    background: var(--voice-faint);
    transition: transform 0.15s ease;
  }
  &.on {
    border-color: var(--voice-accent);
    &::after {
      transform: translateX(15px);
      background: var(--voice-accent);
    }
  }
}
</style>
