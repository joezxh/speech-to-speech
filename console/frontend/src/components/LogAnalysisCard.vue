<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { LogAnalysis, LogCritical } from '@/types/logs'
import { confidenceText, riskLevel, sentSummary } from '@/utils/analysis-format'
import { formatTime, groupThousands } from '@/utils/format'

/**
 * A.16 的结果卡。它只读 `analysis` / `pending` / `error` 三个 prop，
 * 失败时**不**清空、也**不**改动左侧日志区：日志是证据，归纳是结论，
 * 结论失败不该让人失去证据。
 */
const props = defineProps<{
  analysis: LogAnalysis | null
  pending: boolean
  error: string
}>()
const emit = defineEmits<{ retry: [] }>()

const { t } = useI18n()

const errorColumns = computed(() => [
  { title: t('logs.analysis.columns.signature'), dataIndex: 'signature', key: 'signature' },
  { title: t('logs.analysis.columns.count'), dataIndex: 'count', key: 'count', width: 80 },
  { title: t('logs.analysis.columns.firstSeen'), key: 'firstSeen', width: 170 },
  { title: t('logs.analysis.columns.lastSeen'), key: 'lastSeen', width: 170 },
  { title: t('logs.analysis.columns.level'), dataIndex: 'level', key: 'level', width: 90 }
])

const errorRows = computed(() =>
  (props.analysis?.result.errors ?? []).map((row, index) => ({ ...row, key: `${row.signature}:${index}` }))
)

/**
 * `impact` 是模型写的自由文本，没有枚举可依。这里只把明显的「高」提到前面，
 * 其余保持模型给的顺序（稳定排序），避免用字符串比较制造一个假的分级。
 */
function impactRank(impact: string): number {
  const text = impact.toLowerCase()
  if (text.includes('高') || text.includes('high') || text.includes('严重')) return 0
  if (text.includes('中') || text.includes('medium')) return 1
  return 2
}

const criticalRows = computed<LogCritical[]>(() =>
  [...(props.analysis?.result.critical ?? [])].sort((a, b) => impactRank(a.impact) - impactRank(b.impact))
)

const rootCauses = computed(() => props.analysis?.result.rootCauses ?? [])
const actions = computed(() => props.analysis?.result.actions ?? [])
</script>

<template>
  <section class="an">
    <div class="an__head">
      <span class="an__title">{{ t('logs.analysis.title') }}</span>
      <span v-if="analysis" class="an__meta">
        {{ analysis.model }} · {{ groupThousands(analysis.durationMs) }} ms
      </span>
      <a-spin v-if="pending" size="small" />
    </div>

    <div v-if="error" class="an__fail">
      <a-alert type="error" show-icon :message="error" />
      <a-button size="small" :loading="pending" @click="emit('retry')">{{ t('logs.analysis.retry') }}</a-button>
    </div>

    <template v-else-if="analysis">
      <!-- A.16 的硬性要求：先说清这份结论基于多少证据。 -->
      <p class="an__sent">{{ sentSummary(analysis.sent) }}</p>

      <div class="an__block">
        <h3 class="an__label">{{ t('logs.analysis.errorsBlock') }}</h3>
        <a-table
          size="small"
          :columns="errorColumns"
          :data-source="errorRows"
          :pagination="false"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'firstSeen'">{{ formatTime(record.firstSeen) }}</template>
            <template v-else-if="column.key === 'lastSeen'">{{ formatTime(record.lastSeen) }}</template>
            <template v-else-if="column.key === 'level'">
              <a-tag :color="record.level === 'ERROR' ? 'red' : 'orange'">{{ record.level }}</a-tag>
            </template>
          </template>
          <template #expandedRowRender="{ record }">
            <pre class="an__sample">{{ record.sample }}</pre>
          </template>
        </a-table>
      </div>

      <div class="an__block">
        <h3 class="an__label">{{ t('logs.analysis.criticalBlock') }}</h3>
        <a-empty v-if="!criticalRows.length" :description="t('logs.analysis.criticalEmpty')" />
        <ul v-else class="an__list">
          <li v-for="(row, index) in criticalRows" :key="`${row.signature}:${index}`" class="an__row">
            <div class="an__row-head">
              <span class="an__sig">{{ row.signature }}</span>
              <a-tag :color="riskLevel(row.impact) === 'bad' ? 'red' : 'orange'">{{ row.impact }}</a-tag>
            </div>
            <p class="an__text">{{ row.rationale }}</p>
            <p class="an__evidence">{{ row.evidence }}</p>
          </li>
        </ul>
      </div>

      <div class="an__block">
        <h3 class="an__label">{{ t('logs.analysis.rootCausesBlock') }}</h3>
        <a-empty v-if="!rootCauses.length" :description="t('logs.analysis.rootCausesEmpty')" />
        <ul v-else class="an__list">
          <li v-for="(row, index) in rootCauses" :key="`rc:${index}`" class="an__row">
            <div class="an__row-head">
              <span class="an__text">{{ row.hypothesis }}</span>
              <a-tag>{{ t('logs.analysis.confidence', { value: confidenceText(row.confidence) }) }}</a-tag>
            </div>
            <p class="an__evidence">{{ row.evidence }}</p>
          </li>
        </ul>
      </div>

      <div class="an__block">
        <h3 class="an__label">{{ t('logs.analysis.actionsBlock') }}</h3>
        <a-empty v-if="!actions.length" :description="t('logs.analysis.actionsEmpty')" />
        <ul v-else class="an__list">
          <li v-for="(row, index) in actions" :key="`ac:${index}`" class="an__row">
            <div class="an__row-head">
              <span class="an__text">{{ row.title }}</span>
              <a-tag :color="riskLevel(row.risk) === 'bad' ? 'red' : riskLevel(row.risk) === 'warn' ? 'orange' : 'green'">
                {{ row.risk }}
              </a-tag>
            </div>
            <p class="an__evidence">{{ row.detail }}</p>
            <p class="an__evidence">{{ t('logs.analysis.expectedEffect', { value: row.expectedEffect }) }}</p>
          </li>
        </ul>
      </div>
    </template>

    <a-empty v-else :description="pending ? t('logs.analysis.analyzing') : t('logs.analysis.notAnalyzed')" />
  </section>
</template>

<style scoped lang="less">
.an {
  background: #171b26;
  border: 1px solid #1c2130;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;

  &__head {
    align-items: center;
    display: flex;
    gap: 10px;
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

  &__fail {
    align-items: center;
    display: flex;
    gap: 10px;
  }

  &__sent {
    color: #c8cede;
    font-size: 12px;
    margin: 0;
  }

  &__block {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__label {
    color: #8b93a7;
    font-size: 12px;
    font-weight: 600;
    margin: 0;
  }

  &__list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    list-style: none;
    margin: 0;
    padding: 0;
  }

  &__row {
    border-left: 2px solid #2a3145;
    padding-left: 8px;
  }

  &__row-head {
    align-items: center;
    display: flex;
    gap: 8px;
    justify-content: space-between;
  }

  &__sig {
    color: #f59e0b;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
  }

  &__text {
    font-size: 13px;
  }

  &__evidence {
    color: #8b93a7;
    font-size: 12px;
    margin: 2px 0 0;
  }

  &__sample {
    background: #12151f;
    border-radius: 4px;
    font-size: 12px;
    margin: 0;
    padding: 8px;
    white-space: pre-wrap;
  }
}
</style>
