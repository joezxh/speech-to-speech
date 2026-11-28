<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { TemplateRow } from '@/api/templates'
import { sceneBykey } from '@/views/scenesProto'

const props = defineProps<{ open: boolean; template: TemplateRow | null }>()
const emit = defineEmits<{ close: [] }>()
const { t, locale } = useI18n()

const scene = computed(() => (props.template ? sceneBykey(props.template.scene) : null))
const isZh = computed(() => locale.value.startsWith('zh'))
const bi = (value: { zh: string; en: string } | undefined) =>
  value ? (isZh.value ? value.zh : value.en) : ''

const effectTag = computed(() =>
  props.template ? t(`templates.effect.${props.template.effect}`) : ''
)
const statusTag = computed(() =>
  props.template ? t(`templates.status.${props.template.status}`) : ''
)
</script>

<template>
  <a-modal
    :open="open"
    :title="template ? `${t('templates.view.title')} · ${template.name}` : t('templates.view.title')"
    :footer="null"
    width="880px"
    @cancel="emit('close')"
  >
    <template v-if="template">
      <p class="tvm__desc">{{ template.desc || '—' }}</p>
      <div class="tvm__meta">
        <span>{{ t('templates.col.effect') }}: <a-tag :color="template.effect === 'runtime' ? 'cyan' : 'orange'">{{ effectTag }}</a-tag></span>
        <span>{{ t('templates.col.platform') }}: <a-tag>{{ t(`templates.platform.${template.platform}`) }}</a-tag></span>
        <span>{{ t('templates.col.status') }}: <a-tag>{{ statusTag }}</a-tag></span>
        <span>{{ t('templates.col.vram') }}: <b>{{ template.minVramGb ? `${template.minVramGb} GB` : '—' }}</b></span>
        <span>{{ t('templates.col.fields') }}: <b>{{ template.fields.length }}</b></span>
        <span>{{ t('templates.col.scene') }}: <b>{{ template.scene ? t(`templates.scene.${template.scene}`) : t('templates.scene.none') }}</b></span>
      </div>

      <h4 class="tvm__section">{{ t('templates.view.sceneTitle') }}</h4>
      <template v-if="scene">
        <p class="tvm__note">{{ t('templates.view.sceneNote') }} · {{ bi(scene.note) }}</p>
        <p v-if="scene.cross" class="tvm__cross">{{ t('templates.view.cross') }}</p>
        <p class="tvm__note">{{ t('templates.view.recCount', { n: scene.items.length }) }}</p>
        <div v-for="item in scene.items" :key="item.p" class="tvm__rec">
          <div class="tvm__rec-top">
            <code>{{ item.p }}</code>
            <span>→ <b>{{ item.v }}</b></span>
            <span class="tvm__ref">{{ t('templates.view.ref') }} · {{ item.ref }}</span>
          </div>
          <div class="tvm__grid">
            <div><span class="k">{{ t('templates.view.why') }}</span>{{ bi(item.why) }}</div>
            <div><span class="k">{{ t('templates.view.gain') }}</span>{{ bi(item.gain) }}</div>
            <div><span class="k">{{ t('templates.view.cost') }}</span>{{ bi(item.cost) }}</div>
          </div>
          <div class="tvm__risk">{{ t('templates.view.risk') }} · {{ bi(item.risk) }}</div>
        </div>
      </template>
      <p v-else class="tvm__note">{{ t('templates.view.noScene') }}</p>

      <p class="tvm__readonly">{{ t('templates.view.readonly') }}</p>
    </template>
  </a-modal>
</template>

<style scoped lang="less">
.tvm {
  &__desc {
    color: var(--muted);
    margin-bottom: 8px;
  }
  &__meta {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 20px;
    margin-bottom: 12px;
  }
  &__section {
    margin: 12px 0 8px;
  }
  &__note,
  &__cross,
  &__readonly {
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 6px;
  }
  &__cross,
  &__risk {
    color: var(--warn-text);
  }
  &__readonly {
    margin-top: 10px;
  }
  &__rec {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 10px;
    font-size: 13px;
  }
  &__rec-top {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 14px;
    align-items: baseline;
    margin-bottom: 6px;
    code {
      font-weight: 600;
    }
  }
  &__ref {
    color: var(--muted);
    font-size: 12px;
  }
  &__grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    .k {
      display: inline-block;
      color: var(--muted);
      margin-right: 6px;
      font-size: 12px;
    }
  }
}
</style>
