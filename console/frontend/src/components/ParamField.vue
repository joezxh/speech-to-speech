<script setup lang="ts">
import { computed } from 'vue'

import EffectBadge from '@/components/EffectBadge.vue'
import ExposureTag from '@/components/ExposureTag.vue'
import FixedField from '@/components/FixedField.vue'
import type { CatalogEntry } from '@/types/catalog'
import { isReadOnlyRow } from '@/utils/catalog-view'

const props = defineProps<{
  entry: CatalogEntry
  modelValue: unknown
  masked: boolean
  /** 该键已在草稿里：详情里多一个小标记，免得运维分不清「默认」与「自己改过」（§6.1）。 */
  inDraft?: boolean
  disabled?: boolean
  /** advanced 层级的建议值；不传则不显示「建议」。 */
  suggested?: unknown
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
  reset: []
}>()

const control = computed(() => {
  if (props.masked) return 'secret'
  if (props.entry.type === 'bool' || props.entry.type === 'boolean') return 'bool'
  if (props.entry.choices.length > 0) return 'choice'
  if (['int', 'integer', 'float', 'number'].includes(props.entry.type)) return 'number'
  return 'text'
})

const isFixed = computed(() => isReadOnlyRow(props.entry))

const IMPACT_LABEL: Record<string, string> = {
  process: '进程',
  pipeline: 'pipeline',
  session: '会话',
  container: '容器'
}

const COST_LABEL: Record<string, string> = {
  seconds: '秒级',
  restart: '重启',
  minutes: '分钟级'
}

const impactLabel = computed(() => IMPACT_LABEL[props.entry.impact] ?? props.entry.impact)
const changeCostLabel = computed(() => COST_LABEL[props.entry.change_cost] ?? props.entry.change_cost)

/** `ops` 必须把 risk 归到三类之一（§7.2）；完整文案进 `title`，不把长句塞进标签。 */
const riskCategory = computed(() => {
  const risk = props.entry.risk ?? ''
  for (const tag of ['安全', '隐私', '环境绑定']) if (risk.includes(tag)) return tag
  return risk ? '其他' : ''
})

function formatDefault(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : '[]'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** 不写 `effect`：它由 `EffectBadge` 承担，两处同时写会给出两个互相矛盾的说法。 */
const hint = computed(() => {
  // advanced 带建议值：同一个值不再用「默认」和「建议」各说一遍。
  const lead =
    props.suggested === undefined
      ? `默认 ${formatDefault(props.entry.default)}`
      : `建议 ${formatDefault(props.suggested)}`
  return [lead, impactLabel.value, changeCostLabel.value].join(' · ')
})

function onInput(event: Event): void {
  emit('update:modelValue', (event.target as HTMLInputElement).value)
}

function onNumber(value: number | string | null): void {
  emit('update:modelValue', value === null || value === '' ? null : Number(value))
}
</script>

<template>
  <FixedField v-if="isFixed" :entry="entry" />

  <div
    v-else
    class="param-field"
    :class="{ 'param-field--expert': entry.exposure === 'expert', 'param-field--in-draft': inDraft }"
  >
    <div class="param-field__head">
      <span class="param-field__name" :title="entry.key">{{ entry.name }}</span>
      <ExposureTag :exposure="entry.exposure" />
      <EffectBadge :entry="entry" />
      <a-tag color="default">{{ impactLabel }}</a-tag>
      <a-tag color="default">{{ changeCostLabel }}</a-tag>
      <a-tag v-if="entry.exposure === 'ops' && riskCategory" color="red" :title="entry.risk ?? ''">
        {{ riskCategory }}
      </a-tag>
      <a-tag v-if="inDraft" color="purple">草稿</a-tag>
      <span class="param-field__spacer" />
      <a-button
        type="link"
        size="small"
        :disabled="disabled"
        :title="`默认 ${formatDefault(entry.default)}`"
        @click="emit('reset')"
      >
        恢复默认
      </a-button>
    </div>

    <a-select
      v-if="control === 'choice'"
      :value="modelValue"
      :options="entry.choices.map((value) => ({ value, label: String(value) }))"
      :disabled="disabled"
      class="param-field__control"
      @change="(value: unknown) => emit('update:modelValue', value)"
    />

    <a-switch
      v-else-if="control === 'bool'"
      :checked="Boolean(modelValue)"
      :disabled="disabled"
      @change="(checked: unknown) => emit('update:modelValue', checked)"
    />

    <a-input-number
      v-else-if="control === 'number'"
      :value="typeof modelValue === 'number' ? modelValue : null"
      :disabled="disabled"
      class="param-field__control"
      @change="onNumber"
    />

    <a-input-password
      v-else-if="control === 'secret'"
      :value="modelValue"
      :disabled="disabled"
      class="param-field__control"
      @input="onInput"
    />

    <a-input
      v-else
      :value="modelValue === null || modelValue === undefined ? '' : String(modelValue)"
      :disabled="disabled"
      class="param-field__control"
      @input="onInput"
    />

    <p v-if="entry.exposure === 'expert'" class="param-field__warn">
      expert：改错会让 pipeline 起不来，先存草稿、再审 diff 后发布。
    </p>
    <p class="param-field__hint">{{ hint }}</p>

    <!-- 人设类字段的第二个动作：「热更存量连接」+「重启改未来连接」（§5.4）。 -->
    <slot name="dualAction" />
  </div>
</template>

<style scoped lang="less">
.param-field {
  border-bottom: 1px solid #1e2742;
  padding: 12px 0;

  &__head {
    align-items: center;
    display: flex;
    gap: 8px;
    margin-bottom: 6px;
  }

  &__name {
    color: #e6e8f0;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
  }

  &__spacer {
    flex: 1;
  }

  &__control {
    max-width: 320px;
  }

  &__hint {
    color: #8b93a7;
    font-size: 12px;
    margin: 6px 0 0;
  }

  &__warn {
    color: #d89614;
    font-size: 12px;
    margin: 6px 0 0;
  }

  &--expert {
    background: rgba(216, 150, 20, 0.05);
    padding-left: 8px;
  }

  &--in-draft {
    border-left: 2px solid #9254de;
    padding-left: 8px;
  }
}
</style>
