<script setup lang="ts">
// 前台「设置」独立页（原型 front·settings）：机器条 + 对话态热更 + 智能设置。
// 语音/设备偏好的设置浮层保留在对话页（§3.2.4 浮层快捷入口），这里不重复。
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import HotUpdateSettings from '@/components/proto/HotUpdateSettings.vue'
import SmartSettingsPanel from '@/components/proto/SmartSettingsPanel.vue'
import PDot from '@/components/proto/PDot.vue'
import { useMachineStore } from '@/stores/machine'
import { hotParamByName } from '@/utils/hotParams'

const { t } = useI18n()
const route = useRoute()
const machinesStore = useMachineStore()

const selectedMachine = ref(String(route.query.machine ?? ''))
const machine = computed(
  () => machinesStore.machines.find((item) => item.machineId === selectedMachine.value) ?? null
)
const hotRef = ref<InstanceType<typeof HotUpdateSettings> | null>(null)

async function load(): Promise<void> {
  await machinesStore.fetch()
  if (!selectedMachine.value && machinesStore.machines.length) {
    selectedMachine.value = machinesStore.machines[0].machineId
  }
}

watch(
  () => route.query.machine,
  (value) => {
    if (!value) return
    selectedMachine.value = String(value)
    void load()
  }
)

/** 智能推荐 → 写进热更表，由人确认后统一下发（不自动下发，避免误操作）。 */
function applySmart(key: string, value: string): void {
  if (!hotParamByName(key)) return
  hotRef.value?.setValue(key, value)
}

onMounted(load)
</script>

<template>
  <section class="sv">
    <header class="card">
      <h1>{{ t('settings.title') }}</h1>
      <p class="hint">{{ t('settings.desc') }}</p>
      <div class="sv__machines">
        <button
          v-for="item in machinesStore.machines"
          :key="item.machineId"
          class="sv__chip"
          :class="{ active: selectedMachine === item.machineId }"
          @click="selectedMachine = item.machineId"
        >
          <PDot :state="item.state === 'ok' ? 'ok' : item.state === 'draining' ? 'draining' : 'bad'" />
          {{ item.machineId }}
          <small class="hint">{{ t(`templates.platform.${item.platform || 'gpu'}`) }}</small>
        </button>
      </div>
    </header>

    <div class="card">
      <HotUpdateSettings ref="hotRef" :machine-id="selectedMachine" />
    </div>

    <div v-if="machine" class="card">
      <SmartSettingsPanel :machine-id="machine.machineId" mode="live" @apply="applySmart" />
    </div>
  </section>
</template>

<style scoped lang="less">
.sv { display: grid; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.hint { color: var(--muted); font-size: 12px; }
.sv__machines { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.sv__chip {
  border: 1px solid var(--border);
  background: transparent;
  border-radius: 999px;
  padding: 4px 12px;
  cursor: pointer;
  &.active { background: var(--accent); color: var(--surface); }
}
</style>
