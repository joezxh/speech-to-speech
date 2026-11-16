<script setup lang="ts">
import { message } from 'ant-design-vue'
import { reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import { clustersApi } from '@/api/clusters'
import type { ClusterRow } from '@/types/api'
import { camel } from '@/utils/error'
import { POLICIES, validateClusterForm, type ClusterFormErrors, type ClusterFormValues } from '@/utils/clusterForm'

/**
 * 新增/编辑集群共用一个弹窗（原型 openClusterForm）。校验失败与服务端失败都
 * 不关窗（spec §5.2-3/4）：服务端 duplicate_name/duplicate_registry 回填到
 * 对应字段的 .ferr，其余错误码走 errors.<camel(code)> 横幅。
 */
const props = defineProps<{ open: boolean; cluster: ClusterRow | null }>()
const emit = defineEmits<{ 'update:open': [open: boolean]; saved: [row: ClusterRow] }>()
const { t } = useI18n()

const form = reactive<ClusterFormValues>({ name: '', registry: '', policy: 'least', note: '' })
const errors = ref<ClusterFormErrors>({})
const banner = ref('')
const saving = ref(false)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.name = props.cluster?.name ?? ''
    form.registry = props.cluster?.registry ?? ''
    form.policy = props.cluster?.policy ?? 'least'
    form.note = props.cluster?.note ?? ''
    errors.value = {}
    banner.value = ''
  }
)

function fail(caught: unknown): void {
  const err = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
  const key = camel(err.code)
  if (err.code === 'duplicate_name') errors.value = { ...errors.value, name: `errors.${key}` }
  else if (err.code === 'duplicate_registry') errors.value = { ...errors.value, registry: `errors.${key}` }
  else banner.value = t(`errors.${key}`)
  // spec §5.3：服务端失败同时给「内联错误条 + toast」双反馈，弹窗不关闭。
  message.error(t('overview.toast.serverError', { message: err.message }))
}

async function save(): Promise<void> {
  errors.value = {}
  banner.value = ''
  const invalid = validateClusterForm(form, props.cluster !== null)
  if (Object.keys(invalid).length) {
    errors.value = invalid
    return
  }
  saving.value = true
  try {
    const row = props.cluster
      ? await clustersApi.update(props.cluster.name, {
          registry: form.registry.trim(),
          policy: form.policy,
          note: form.note
        })
      : await clustersApi.create({
          name: form.name.trim(),
          registry: form.registry.trim(),
          policy: form.policy,
          note: form.note
        })
    emit('saved', row)
    emit('update:open', false)
  } catch (caught) {
    fail(caught)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <a-modal
    :open="props.open"
    :title="props.cluster ? t('overview.form.editTitle') : t('overview.form.createTitle')"
    :ok-text="t('common.confirm')"
    :cancel-text="t('common.cancel')"
    :confirm-loading="saving"
    @ok="save"
    @update:open="(next: boolean) => emit('update:open', next)"
  >
    <a-form layout="vertical" @submit.prevent>
      <a-form-item :label="t('overview.form.name')">
        <a-input v-model:value="form.name" :disabled="props.cluster !== null" data-testid="cluster-name" />
        <p v-if="errors.name" class="ferr">{{ t(errors.name) }}</p>
      </a-form-item>
      <a-form-item :label="t('overview.form.registry')">
        <a-input v-model:value="form.registry" placeholder="consul://host:8500" data-testid="cluster-registry" />
        <p v-if="errors.registry" class="ferr">{{ t(errors.registry) }}</p>
      </a-form-item>
      <a-form-item :label="t('overview.form.policy')">
        <a-select v-model:value="form.policy">
          <a-select-option v-for="policy in POLICIES" :key="policy" :value="policy">
            {{ t(`overview.policy.${policy}`) }}
          </a-select-option>
        </a-select>
        <p v-if="errors.policy" class="ferr">{{ t(errors.policy) }}</p>
      </a-form-item>
      <a-form-item :label="t('overview.form.note')">
        <a-textarea v-model:value="form.note" :rows="2" :maxlength="255" />
        <p v-if="errors.note" class="ferr">{{ t(errors.note) }}</p>
      </a-form-item>
      <p v-if="banner" class="ferr ferr--banner">{{ banner }}</p>
    </a-form>
  </a-modal>
</template>

<style scoped lang="less">
.ferr {
  color: var(--s2s-color-danger);
  font-size: 12px;
  margin: 4px 0 0;

  &--banner {
    background: var(--s2s-color-surface-2);
    border: 1px solid var(--s2s-color-border);
    border-radius: var(--s2s-radius-sm);
    padding: 8px;
  }
}
</style>