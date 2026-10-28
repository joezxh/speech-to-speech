<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, AppError } from '@/api/client'
import ErrorBanner from '@/components/ErrorBanner.vue'
import NotImplemented from '@/components/NotImplemented.vue'
import { useConsoleStore } from '@/stores/console'
import type { InstanceRow, InstanceSnapshot, StatusSnapshot } from '@/types/api'
import { DASH } from '@/utils/format'
import { overviewMetrics } from './overviewMetrics'

/**
 * 集群总览（spec §10.1）：只读，数据全部来自 `GET /status` 与 `GET /instances`。
 * 两个请求各自失败、各自降级——单条告警或半个端点不可用都不能让整页空白。
 * demo 里那些后端还没有来源的指标，一律带子项目标记的空态，不伪造。
 */
const consoleStore = useConsoleStore()
const { t } = useI18n()

const status = ref<StatusSnapshot | null>(null)
const snapshot = ref<InstanceSnapshot | null>(null)
const statusError = ref<AppError | null>(null)
const instancesError = ref<AppError | null>(null)

const metrics = computed(() =>
  status.value && snapshot.value ? overviewMetrics(status.value, snapshot.value) : []
)
const realMetrics = computed(() => metrics.value.filter((m) => !m.unimpl))
const unimplMetrics = computed(() => metrics.value.filter((m) => m.unimpl))
const instances = computed<InstanceRow[]>(() => snapshot.value?.instances ?? [])
const mismatches = computed(() => instances.value.filter((row) => row.declared_mismatch))
const alerts = computed(() => snapshot.value?.alerts ?? [])

async function load(): Promise<void> {
  const params = { profile: consoleStore.profile }
  const [statusResult, instancesResult] = await Promise.allSettled([
    api.get<StatusSnapshot>('/status', { params }),
    api.get<InstanceSnapshot>('/instances', { params })
  ])
  if (statusResult.status === 'fulfilled') {
    status.value = statusResult.value
    statusError.value = null
  } else {
    status.value = null
    statusError.value =
      statusResult.reason instanceof AppError
        ? statusResult.reason
        : new AppError('unknown', t('errors.load.status'))
  }
  if (instancesResult.status === 'fulfilled') {
    snapshot.value = instancesResult.value
    instancesError.value = null
  } else {
    snapshot.value = null
    instancesError.value =
      instancesResult.reason instanceof AppError
        ? instancesResult.reason
        : new AppError('unknown', t('errors.load.instances'))
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="overview">
    <ErrorBanner :error="statusError" />
    <ErrorBanner :error="instancesError" />

    <section v-if="alerts.length" class="overview__alerts">
      <a-alert
        v-for="alert in alerts"
        :key="alert"
        type="warning"
        show-icon
        :message="alert"
      />
    </section>

    <a-alert
      v-if="mismatches.length"
      class="overview__mismatch"
      type="warning"
      show-icon
      :message="`${t('machines.declaredMismatch')} · ${mismatches.map((row) => row.instance_id).join(', ')}`"
    />

    <a-spin :spinning="!status && !statusError">
      <div class="overview__grid">
        <a-card v-for="metric in realMetrics" :key="metric.key" size="small" class="kpi">
          <p class="kpi__label">{{ t(metric.key) }}</p>
          <p class="kpi__value" :data-metric="metric.key">{{ metric.value ?? DASH }}</p>
        </a-card>

        <a-card
          v-for="metric in unimplMetrics"
          :key="metric.key"
          size="small"
          class="kpi kpi--unimpl"
        >
          <p class="kpi__label">{{ t(`overview.kpi.${metric.key.split('.').pop()}`) }}</p>
          <NotImplemented
            :target-subproject="metric.unimpl ?? 'none'"
            :reason-key="metric.key"
            :data-unimplemented="metric.unimpl"
          />
        </a-card>
      </div>
    </a-spin>

    <div class="overview__layers">
      <a-card size="small" :title="t('overview.topology.lbLayer')">
        <p class="layer__note">{{ t('overview.unimpl.stickiness') }}</p>
      </a-card>
      <a-card size="small" :title="t('overview.topology.pipelineLayer')">
        <a-empty v-if="!instances.length" :description="t('machines.trend.empty')" />
        <ul v-else class="layer__list">
          <li v-for="row in instances" :key="row.instance_id" class="layer__row">
            {{ row.instance_id }} · {{ t(`machines.status.${row.status}`) }} ·
            {{ row.in_use ?? DASH }} / {{ row.size ?? DASH }}
          </li>
        </ul>
      </a-card>
      <a-card size="small" :title="t('overview.topology.machineLayer')">
        <NotImplemented target-subproject="S2" reason-key="overview.unimpl.machines" data-unimplemented="S2" />
      </a-card>
    </div>
  </div>
</template>

<style scoped lang="less">
.overview {
  display: flex;
  flex-direction: column;
  gap: 16px;

  &__alerts {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  }

  &__layers {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  }
}

.kpi {
  &__label {
    color: var(--s2s-color-muted);
    font-size: 12px;
    margin: 0 0 4px;
  }

  &__value {
    color: var(--s2s-color-text);
    font-family: var(--s2s-font-mono);
    font-size: 18px;
    margin: 0;
  }

  &--unimpl .kpi__label {
    margin-bottom: 8px;
  }
}

.layer {
  &__note {
    color: var(--s2s-color-muted);
    font-size: 12px;
    margin: 0;
  }

  &__list {
    margin: 0;
    padding-left: 16px;
  }

  &__row {
    color: var(--s2s-color-text);
    font-size: 12px;
  }
}
</style>
