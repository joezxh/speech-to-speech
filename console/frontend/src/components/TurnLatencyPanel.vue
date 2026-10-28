<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import { fetchTurnLatency } from '@/api/turn-latency'
import type { TurnLatencyPage } from '@/types/turn-latency'
import {
  E2E_NOTE,
  failureRateText,
  lagText,
  responseKeyShort,
  stageStats,
  stageValue
} from '@/utils/turn-latency-format'
import { formatTime, groupThousands } from '@/utils/format'

/**
 * A.17 的只读面板：没有任何删除、导出或重算入口。
 *
 * 两块的时间窗各自独立（日志面板不跟着它变）：联动会让人以为日志窗口与
 * 轮次窗口必须相等，而它们本来只在「排查这一次」时才该被人为对齐。
 */
const props = withDefaults(defineProps<{ windowMinutes?: number }>(), { windowMinutes: 15 })

const { t } = useI18n()

type Preset = '15m' | '1h' | '24h'

const PRESETS: { key: Preset; label: string; minutes: number }[] = [
  { key: '15m', label: '15m', minutes: 15 },
  { key: '1h', label: '1h', minutes: 60 },
  { key: '24h', label: '24h', minutes: 1440 }
]

const STATUS_OPTIONS = [
  { label: 'completed', value: 'completed' },
  { label: 'failed', value: 'failed' },
  { label: 'cancelled', value: 'cancelled' },
  { label: 'incomplete', value: 'incomplete' }
]

const preset = ref<Preset>(PRESETS.find((item) => item.minutes === props.windowMinutes)?.key ?? '15m')
const status = ref<string[]>([])
const page = ref<TurnLatencyPage | null>(null)
const loading = ref(false)
const error = ref('')

const minutes = computed(() => PRESETS.find((item) => item.key === preset.value)?.minutes ?? 15)

const reason = computed(() => page.value?.reasons.summary ?? null)
/** 空窗是正常状态：`count:0` 与它同时出现，不能说成「坏了」。 */
const emptyWindow = computed(() => reason.value === 'no_turn_rows')
const unavailable = computed(() => reason.value !== null && reason.value !== 'no_turn_rows')

const summary = computed(() => page.value?.summary ?? null)

const rows = computed(() =>
  (page.value?.rows ?? []).map((row, index) => ({
    ...row,
    key: `${row.responseKey}:${row.turnRevision}:${index}`
  }))
)

const columns = computed(() => [
  { title: t('latency.columns.loggedAt'), key: 'loggedAt', width: 170 },
  { title: t('latency.columns.response'), key: 'responseKey', width: 130 },
  { title: t('latency.columns.status'), dataIndex: 'status', key: 'status', width: 100 },
  { title: 'E2E', key: 'e2eMs', width: 110 },
  { title: t('latency.columns.vadDecision'), key: 'vadDecisionMs', width: 110 },
  { title: 'smart', key: 'smartStatus', width: 90 },
  { title: 'STT', key: 'sttMs', width: 100 },
  { title: 'LLM', key: 'llmMs', width: 100 },
  { title: 'TTS TTFA', key: 'ttsTtfaMs', width: 110 },
  { title: 'hold', key: 'holdMs', width: 100 }
])

async function load(): Promise<void> {
  loading.value = true
  try {
    const end = new Date()
    const start = new Date(end.getTime() - minutes.value * 60_000)
    page.value = await fetchTurnLatency(start.toISOString(), end.toISOString(), [...status.value], 100)
    error.value = ''
  } catch (caught) {
    // 一次读取失败不清空上一页：正是需要看历史的时候。
    error.value = caught instanceof AppError ? caught.message : t('latency.unreadable')
  } finally {
    loading.value = false
  }
}

function pick(value: Preset): void {
  preset.value = value
  void load()
}

onMounted(() => void load())
</script>

<template>
  <section class="tl">
    <div class="tl__head">
      <span class="tl__title">{{ t('latency.title') }}</span>
      <a-button-group size="small">
        <a-button
          v-for="item in PRESETS"
          :key="item.key"
          class="tl__win"
          size="small"
          :aria-pressed="preset === item.key"
          :type="preset === item.key ? 'primary' : 'default'"
          @click="pick(item.key)"
        >
          {{ item.label }}
        </a-button>
      </a-button-group>
      <a-select
        v-model:value="status"
        mode="multiple"
        size="small"
        style="min-width: 200px"
        :placeholder="t('latency.statusAll')"
        :options="STATUS_OPTIONS"
        :max-tag-count="2"
        @change="load()"
      />
      <a-button size="small" :loading="loading" @click="load()">{{ t('latency.refresh') }}</a-button>
      <span v-if="page" class="tl__meta">
        {{ t('latency.turnsCount', { count: groupThousands(page.summary.count) }) }} · {{ lagText(page.index.lagS) }}
      </span>
    </div>

    <a-alert v-if="error" type="error" show-icon :message="error" />

    <div v-if="unavailable" class="tl__agg tl__agg--off">
      <span class="tl__off">{{ t('latency.unavailable') }} · <code>{{ reason }}</code></span>
      <span v-if="reason === 'index_lag'" class="tl__note">
        {{ t('latency.indexLagNote', { lag: lagText(page?.index.lagS ?? null) }) }}
      </span>
    </div>
    <a-empty v-else-if="emptyWindow" :description="t('latency.empty')" />
    <div v-else-if="summary" class="tl__agg">
      <div class="tl__grid">
        <div class="tl__cell">
          <span class="tl__k">{{ t('latency.metric.turns') }}</span>
          <span class="tl__v">{{ groupThousands(summary.count) }}</span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">{{ t('latency.metric.states') }}</span>
          <span class="tl__v">
            {{ summary.completed }} / {{ summary.failed }} / {{ summary.cancelled }} /
            {{ summary.incomplete }}
          </span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">{{ t('latency.metric.failureRate') }}</span>
          <span class="tl__v">{{ failureRateText(summary.failureRate) }}</span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">E2E p50 · p95 · max</span>
          <span class="tl__v">
            {{ stageValue(summary.e2e.p50Ms) }} · {{ stageValue(summary.e2e.p95Ms) }} ·
            {{ stageValue(summary.e2e.maxMs) }}
          </span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">STT p50 · p95</span>
          <span class="tl__v">{{ stageStats(summary.stages.stt) }}</span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">LLM p50 · p95</span>
          <span class="tl__v">{{ stageStats(summary.stages.llm) }}</span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">TTS TTFA p50 · p95</span>
          <span class="tl__v">{{ stageStats(summary.stages.ttsTtfa) }}</span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">{{ t('latency.metric.vadDecision') }}</span>
          <span class="tl__v">{{ stageStats(summary.stages.vadDecision) }}</span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">hold p50 · p95</span>
          <span class="tl__v">{{ stageStats(summary.stages.hold) }}</span>
        </div>
        <div class="tl__cell">
          <span class="tl__k">{{ t('latency.metric.holdUnavailable') }}</span>
          <span class="tl__v">{{ t('latency.turnsCount', { count: groupThousands(summary.stages.hold.unavailableCount) }) }}</span>
        </div>
      </div>
    </div>

    <a-table
      v-if="rows.length"
      class="tl__rows"
      size="small"
      :columns="columns"
      :data-source="rows"
      :pagination="false"
      :scroll="{ x: 1100 }"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'loggedAt'">{{ formatTime(record.loggedAt) }}</template>
        <template v-else-if="column.key === 'responseKey'">
          <span :title="record.responseKey">{{ responseKeyShort(record.responseKey) }}</span>
        </template>
        <template v-else-if="column.key === 'smartStatus'">
          {{ record.smartStatus ?? t('latency.unavailable') }}
        </template>
        <template v-else-if="column.key === 'e2eMs'">{{ stageValue(record.e2eMs) }}</template>
        <template v-else-if="column.key === 'vadDecisionMs'">
          {{ stageValue(record.vadDecisionMs) }}
        </template>
        <template v-else-if="column.key === 'sttMs'">{{ stageValue(record.sttMs) }}</template>
        <template v-else-if="column.key === 'llmMs'">{{ stageValue(record.llmMs) }}</template>
        <template v-else-if="column.key === 'ttsTtfaMs'">{{ stageValue(record.ttsTtfaMs) }}</template>
        <template v-else-if="column.key === 'holdMs'">{{ stageValue(record.holdMs) }}</template>
      </template>
    </a-table>

    <div class="tl__foot">
      <span>{{ E2E_NOTE }}</span>
      <span v-if="page?.truncated" class="tl__cut">{{ t('latency.rowsTruncated') }}</span>
    </div>
  </section>
</template>

<style scoped lang="less">
.tl {
  display: flex;
  flex-direction: column;
  gap: 8px;

  &__head {
    align-items: center;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  &__title {
    font-size: 14px;
    font-weight: 600;
  }

  &__meta {
    color: #8b93a7;
    font-size: 12px;
    margin-left: auto;
  }

  &__agg {
    background: #171b26;
    border: 1px solid #1c2130;
    border-radius: 8px;
    padding: 10px 12px;

    &--off {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
  }

  &__off {
    color: #ff6a75;
    font-size: 13px;
  }

  &__note {
    color: #8b93a7;
    font-size: 12px;
  }

  &__grid {
    display: grid;
    gap: 8px 16px;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  }

  &__cell {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  &__k {
    color: #8b93a7;
    font-size: 12px;
  }

  &__v {
    font-size: 13px;
  }

  &__foot {
    color: #8b93a7;
    display: flex;
    flex-direction: column;
    font-size: 12px;
    gap: 2px;
  }

  &__cut {
    color: #f59e0b;
  }
}

code {
  color: #ff6a75;
  font-family: 'JetBrains Mono', monospace;
}
</style>
