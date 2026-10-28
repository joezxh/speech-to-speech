<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import EffectBadge from '@/components/EffectBadge.vue'
import ExposureTag from '@/components/ExposureTag.vue'
import VoiceCreateDialog from '@/components/VoiceCreateDialog.vue'
import { useVoicesStore } from '@/stores/voices'
import type { CatalogEntry } from '@/types/catalog'
import type { VoiceRow, VoiceSource } from '@/types/voice-library'
import { bindPatch, bindings, selectable, voiceIdIn, voiceSlot, type Values } from '@/utils/voice-refs'
import { sourceLabel } from '@/utils/voice-text'

const props = defineProps<{
  /** 该控件位在 catalog 里的代表条目（`qwen3_tts_speaker` / `qwen3_tts_ref_audio` / `qwen3_tts_instruct` …）。 */
  entry: CatalogEntry
  backend: string
  /** 库里所有音色（本组件自己按后端与来源过滤）。 */
  voices: VoiceRow[]
  /** 当前值：音色 id（`/voices/<id>/…` 反查出来）或内置音色名。 */
  current: unknown
  /** `qwen3_tts_ref_cache_dir` 的值，用来拼 `<dir>/<id>/spk.npy`。 */
  cacheDir: string
  disabled?: boolean
  inDraft?: boolean
}>()

/** patch 的键是不带 stage 的字段名，由父组件补前缀（见 `ParamsView.applyVoicePatch`）。 */
const emit = defineEmits<{ 'update:modelValue': [patch: Values] }>()

const store = useVoicesStore()
const { t } = useI18n()
const dialogOpen = ref(false)

const slot = computed(() => voiceSlot(props.entry.name))
const source = computed<VoiceSource | null>(() => (slot.value === 'builtin' ? 'builtin' : slot.value))
const fields = computed(() => (source.value ? bindings(source.value, props.backend) : null))

/** 只列该后端、该来源、且 `ready` 的音色（A.18：未 ready 不可选）。 */
const options = computed(() => {
  if (source.value === null) return []
  return selectable(props.voices, props.backend)
    .filter((row) => row.source === source.value)
    .map((row) => ({
      // 内置槽位写进字段的是「音色名」：选项值也必须是名字，写 ULID 会让 qwen3
      // 收到一串不存在的 speaker。克隆 / 指令式写的才是路径与 id。
      value: slot.value === 'builtin' ? row.name : row.id,
      label: `${row.name}${row.language ? ` · ${row.language}` : ''}`
    }))
})

const selectedId = computed(() => voiceIdIn(props.current))
const textValue = computed(() => (typeof props.current === 'string' && !selectedId.value ? props.current : ''))

const emptyHint = computed(() => {
  if (slot.value === 'builtin') return t('voices.picker.builtinHint')
  if (slot.value === 'clone') return t('voices.picker.cloneEmpty')
  return t('voices.picker.designEmpty')
})

function pickVoice(id: unknown): void {
  const row = props.voices.find((item) => item.id === String(id))
  if (!row || !fields.value) return
  emit('update:modelValue', bindPatch(row, fields.value, props.cacheDir))
}

function pickBuiltin(value: string): void {
  const speaker = fields.value?.speaker
  if (!speaker) return
  emit('update:modelValue', { [speaker]: value })
}

function onCreated(row: VoiceRow): void {
  dialogOpen.value = false
  if (!fields.value) return
  emit('update:modelValue', bindPatch(row, fields.value, props.cacheDir))
}
</script>

<template>
  <div class="voice-picker" :class="{ 'voice-picker--in-draft': inDraft }">
    <div class="voice-picker__head">
      <span class="voice-picker__name" :title="entry.key">{{ entry.name }}</span>
      <ExposureTag :exposure="entry.exposure" />
      <EffectBadge :entry="entry" />
      <a-tag color="purple">{{ slot === 'builtin' ? t('voices.picker.builtinTag') : sourceLabel(slot ?? 'clone') }}</a-tag>
      <a-tag v-if="inDraft" color="purple">{{ t('voices.picker.draftTag') }}</a-tag>
      <span class="voice-picker__spacer" />
      <span class="voice-picker__current">
        {{ selectedId ? t('voices.picker.voiceLabel', { id: selectedId }) : textValue || t('voices.picker.none') }}
      </span>
    </div>

    <div class="voice-picker__controls">
      <a-auto-complete
        v-if="slot === 'builtin'"
        :value="textValue"
        :options="options"
        :disabled="disabled"
        class="voice-picker__control"
        :placeholder="t('voices.picker.builtinPlaceholder')"
        @search="pickBuiltin"
        @change="pickBuiltin"
      />

      <a-select
        v-else
        :value="selectedId ?? undefined"
        :options="options"
        :disabled="disabled"
        :placeholder="emptyHint"
        allow-clear
        class="voice-picker__control"
        @change="pickVoice"
      />

      <a-button v-if="slot !== null && slot !== 'builtin'" :disabled="disabled" @click="dialogOpen = true">
        {{ t('voices.picker.create') }}
      </a-button>
      <router-link v-if="slot !== 'builtin'" to="/console/voices" class="voice-picker__link">{{ t('voices.picker.library') }}</router-link>
    </div>

    <p class="voice-picker__hint">
      {{ t('voices.picker.hint', { fields: slot === 'clone' ? 'ref_spk / ref_rvq / ref_text' : slot === 'design' ? 'instruct' : 'speaker' }) }}
    </p>

    <VoiceCreateDialog
      v-if="source"
      :open="dialogOpen"
      :backend="backend"
      :sources="[source]"
      @update:open="(open: boolean) => (dialogOpen = open)"
      @created="onCreated"
    />

    <a-alert
      v-if="store.error"
      type="warning"
      show-icon
      :message="store.error.message"
      class="voice-picker__error"
    />
  </div>
</template>

<style scoped lang="less">
.voice-picker {
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

  &__current {
    color: #8b93a7;
    font-size: 12px;
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__controls {
    align-items: center;
    display: flex;
    gap: 8px;
  }

  &__control {
    max-width: 320px;
    min-width: 220px;
  }

  &__link {
    font-size: 12px;
  }

  &__hint {
    color: #6f7891;
    font-size: 12px;
    margin: 6px 0 0;
  }

  &__error {
    margin-top: 8px;
  }

  &--in-draft {
    border-left: 2px solid #9254de;
    padding-left: 8px;
  }
}
</style>
