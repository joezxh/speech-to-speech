<script setup lang="ts">
import { computed } from 'vue'

import type { InstanceSnapshot } from '@/types/api'
import { describeAlert } from '@/utils/error'
import { formatTime } from '@/utils/format'

const props = defineProps<{ snapshot: InstanceSnapshot | null; error: string }>()

const container = computed(() => props.snapshot?.container ?? null)
const pool = computed(() => props.snapshot?.pool ?? null)
</script>

<template>
  <div class="instance-card">
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-alert
      v-for="alert in snapshot?.alerts ?? []"
      :key="alert"
      type="warning"
      show-icon
      :message="describeAlert(alert)"
    />

    <a-descriptions v-if="container" title="进程" size="small" bordered :column="3">
      <a-descriptions-item label="program">{{ container.name }}</a-descriptions-item>
      <a-descriptions-item label="状态">
        <a-tag :color="container.status === 'running' ? 'green' : 'red'">{{ container.status }}</a-tag>
      </a-descriptions-item>
      <a-descriptions-item label="pid">{{ container.pid ?? '—' }}</a-descriptions-item>
      <a-descriptions-item label="镜像">{{ container.image || '—' }}</a-descriptions-item>
      <a-descriptions-item label="启动时间">{{ formatTime(container.startedAt) }}</a-descriptions-item>
      <a-descriptions-item label="详情">{{ container.detail || '—' }}</a-descriptions-item>
    </a-descriptions>

    <a-descriptions v-if="pool" title="会话池" size="small" bordered :column="2">
      <a-descriptions-item label="大小">{{ pool.size }}</a-descriptions-item>
      <a-descriptions-item label="占用">{{ pool.inUse }}</a-descriptions-item>
    </a-descriptions>
    <a-alert v-else-if="snapshot" type="warning" show-icon message="会话池不可达（/v1/pool 无响应）" />

    <a-table
      v-if="pool && pool.units.length"
      size="small"
      :pagination="false"
      :data-source="pool.units"
      :columns="[
        { title: '#', dataIndex: 'index', key: 'index', width: 60 },
        { title: '状态', dataIndex: 'state', key: 'state', width: 110 },
        { title: '会话', dataIndex: 'sessionId', key: 'sessionId' }
      ]"
      row-key="index"
    />

    <pre v-if="snapshot?.usage" class="instance-card__usage">{{ JSON.stringify(snapshot.usage, null, 2) }}</pre>
  </div>
</template>

<style scoped lang="less">
.instance-card {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__usage {
    background: #141a2e;
    border-radius: 10px;
    color: #8b93a7;
    font-size: 12px;
    margin: 0;
    padding: 12px;
  }
}
</style>
