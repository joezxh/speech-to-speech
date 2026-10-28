<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import { getTrafficSettings } from '@/api/traffic'
import ErrorBanner from '@/components/ErrorBanner.vue'
import NotImplemented from '@/components/NotImplemented.vue'
import type { TrafficSettings } from '@/types/traffic'
import { DASH } from '@/utils/format'
import InstanceTrendsView from './InstanceTrendsView.vue'
import { trafficViewModel } from './trafficViewModel'

/**
 * 流量与路由（spec §10.2）：全程只读。数据源为 `GET /traffic/settings`（分配器
 * 配置快照）+ 内嵌的实例趋势（既有 `GET /instances/{id}/metrics`）。这里没有写
 * 路径，`allocatorMode='off'` 属于常态而非异常，所以用 info 级状态条说明。
 */
const { t } = useI18n()

const settings = ref<TrafficSettings | null>(null)
const loadError = ref<AppError | null>(null)

const vm = computed(() => (settings.value ? trafficViewModel(settings.value) : null))

const fields = computed(() => {
  const s = settings.value
  if (!s) return []
  return [
    { key: 'allocatorMode', value: s.allocatorMode },
    { key: 'consoleId', value: s.consoleId },
    { key: 'seedConfigured', value: String(s.seedConfigured) },
    { key: 'probeIntervalS', value: String(s.probeIntervalS) },
    { key: 'probeTimeoutS', value: String(s.probeTimeoutS) },
    { key: 'failThreshold', value: String(s.failThreshold) },
    { key: 'recoverThreshold', value: String(s.recoverThreshold) },
    { key: 'grantTtlS', value: String(s.grantTtlS) },
    { key: 'usageIntervalS', value: String(s.usageIntervalS) },
    { key: 'metricRetentionDays', value: String(s.metricRetentionDays) },
    { key: 'queueEnabled', value: String(s.queueEnabled) },
    { key: 'webrtcHangupEnabled', value: String(s.webrtcHangupEnabled) }
  ]
})

async function load(): Promise<void> {
  loadError.value = null
  try {
    settings.value = await getTrafficSettings()
  } catch (caught) {
    settings.value = null
    loadError.value =
      caught instanceof AppError ? caught : new AppError('unknown', t('errors.load.runtime'))
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="traffic">
    <ErrorBanner :error="loadError" />

    <a-alert
      v-if="vm?.showOffBanner"
      data-testid="lb-off-banner"
      type="info"
      show-icon
      :message="t('traffic.banner.off')"
    />

    <a-spin :spinning="!settings && !loadError">
      <section class="traffic__section">
        <h2 class="traffic__title">{{ t('traffic.title.settings') }}</h2>
        <dl class="fields">
          <template v-for="field in fields" :key="field.key">
            <dt class="fields__name">{{ t(`traffic.field.${field.key}`) }}</dt>
            <dd class="fields__value" :data-field="field.key">{{ field.value || DASH }}</dd>
          </template>
        </dl>
      </section>

      <section class="traffic__section">
        <h2 class="traffic__title">{{ t('traffic.title.policy') }}</h2>
        <a-card v-if="settings" size="small">
          <dl class="policy">
            <dt class="policy__name">{{ t('traffic.policy.policy') }}</dt>
            <dd class="policy__row" data-field="policy">{{ settings.scheduling.policy || DASH }}</dd>
            <dt class="policy__name">{{ t('traffic.policy.tieBreaker') }}</dt>
            <dd class="policy__row" data-field="tieBreaker">
              {{ settings.scheduling.tieBreaker || DASH }}
            </dd>
          </dl>
          <p v-if="vm?.policyReadOnly" class="policy__note">{{ t('traffic.policy.readOnlyNote') }}</p>
        </a-card>
      </section>

      <section class="traffic__section">
        <h2 class="traffic__title">{{ t('traffic.title.routing') }}</h2>
        <div class="traffic__features">
          <NotImplemented
            v-for="feature in vm?.features ?? []"
            :key="feature.reasonKey"
            target-subproject="S3"
            :reason-key="feature.reasonKey"
            data-unimplemented="S3"
          />
        </div>
      </section>

      <section class="traffic__section">
        <h2 class="traffic__title">{{ t('traffic.title.trends') }}</h2>
        <InstanceTrendsView />
      </section>
    </a-spin>
  </div>
</template>

<style scoped lang="less">
.traffic {
  display: flex;
  flex-direction: column;
  gap: 16px;

  &__section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__title {
    color: var(--s2s-color-text);
    font-size: 14px;
    margin: 0;
  }

  &__features {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
}

.fields {
  display: grid;
  gap: 4px 16px;
  grid-template-columns: minmax(160px, 220px) auto;
  margin: 0;

  &__name {
    color: var(--s2s-color-muted);
    font-size: 12px;
  }

  &__value {
    color: var(--s2s-color-text);
    font-family: var(--s2s-font-mono);
    font-size: 12px;
    margin: 0;
  }
}

.policy {
  display: grid;
  gap: 2px 12px;
  grid-template-columns: minmax(120px, 160px) auto;
  margin: 0;

  &__name {
    color: var(--s2s-color-muted);
    font-size: 12px;
  }

  &__row {
    color: var(--s2s-color-text);
    font-family: var(--s2s-font-mono);
    font-size: 12px;
    margin: 0;
  }

  &__note {
    color: var(--s2s-color-muted);
    font-size: 12px;
    margin: 8px 0 0;
  }
}
</style>
