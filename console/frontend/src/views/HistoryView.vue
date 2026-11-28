<script setup lang="ts">
// 历史记录页：对齐原型 console-refactor-demo.html#/history（renderHistory）。
// KPI 四卡（总数/正常/失败/平均TTFT）→ 筛选卡（关键词/状态/实例/时间范围）→
// 11 列会话表（摘录/消息数/操作）→ 分页 → 行下页内展开消息面板（消息级删除/清空）。
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import PBadge from '@/components/proto/PBadge.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useSessionRecordsStore } from '@/stores/sessionRecords'
import type { SessionMessageRow } from '@/api/sessionRecords'

const { t } = useI18n()
const store = useSessionRecordsStore()
const { open, title, content, ask, answer } = useConfirm()

const selected = ref<Set<number>>(new Set())
const stateOptions = computed(() => [
  { value: '', label: t('sessions.filterAllStates') },
  { value: 'done', label: 'done' },
  { value: 'failed', label: 'failed' }
])
const rangeOptions = computed(() => [
  { value: '', label: t('sessions.hist.filter.all') },
  { value: 'today', label: t('sessions.hist.range.today') },
  { value: '24h', label: t('sessions.hist.range.24h') },
  { value: '7d', label: t('sessions.hist.range.7d') }
])

// 页内展开的消息面板：null = 收起；行点击切换。
const openId = ref<number | null>(null)
const panelKw = ref('')

const pageTotal = computed(() => Math.max(1, Math.ceil(store.total / store.pageSize)))

const allChecked = computed(
  () => store.rows.length > 0 && store.rows.every((row) => selected.value.has(row.id))
)

// 面板内消息本地过滤：匹配消息序号/角色/类型/内容（原型 hist.msg.kw 行为）。
const panelMessages = computed<SessionMessageRow[]>(() => {
  const kw = panelKw.value.trim().toLowerCase()
  const list = store.detail?.messages ?? []
  if (!kw) return list
  return list.filter((m) =>
    `m${m.ordinal + 1} ${m.role} ${m.type} ${m.content}`.toLowerCase().includes(kw)
  )
})

watch(openId, (id) => {
  if (id != null) void store.openDetail(id)
  else {
    store.closeDetail()
    panelKw.value = ''
  }
})

function toggle(rowId: number): void {
  const next = new Set(selected.value)
  if (next.has(rowId)) next.delete(rowId)
  else next.add(rowId)
  selected.value = next
}

function toggleAll(): void {
  selected.value = allChecked.value ? new Set() : new Set(store.rows.map((row) => row.id))
}

function togglePanel(rowId: number): void {
  openId.value = openId.value === rowId ? null : rowId
}

function fmtDuration(ms: number): string {
  if (ms <= 0) return '—'
  const totalSec = Math.round(ms / 1000)
  if (totalSec < 60) return `${totalSec}s`
  return `${Math.floor(totalSec / 60)}m${totalSec % 60}s`
}

function fmtTtfa(ttfaMs: number | null): string {
  return ttfaMs == null ? '—' : `${ttfaMs}ms`
}

function routeCell(instanceId: string, node: string): string {
  if (instanceId && node) return `${instanceId} · ${node}`
  return instanceId || node || '—'
}

function roleLabel(m: SessionMessageRow): string {
  if (m.role === 'user') return t('sessions.hist.role.caller')
  if (m.role === 'assistant') return t('sessions.hist.role.bot')
  return m.role
}

function typeLabel(m: SessionMessageRow): string {
  if (m.role === 'user') return t('sessions.hist.type.asr')
  if (m.role === 'assistant') return t('sessions.hist.type.reply')
  return m.type
}

async function batchDelete(): Promise<void> {
  const ids = [...selected.value]
  if (!ids.length) return
  if (
    !(await ask({
      title: t('sessions.batchDeleteTitle'),
      content: t('sessions.batchDeleteBody', { n: ids.length })
    }))
  )
    return
  await store.removeMany(ids)
  if (openId.value != null && ids.includes(openId.value)) openId.value = null
  selected.value = new Set()
}

async function deleteOne(rowId: number): Promise<void> {
  if (!(await ask({ title: t('sessions.deleteTitle'), content: t('sessions.deleteBody') }))) return
  await store.remove(rowId)
  if (openId.value === rowId) openId.value = null
}

async function deleteMessage(m: SessionMessageRow): Promise<void> {
  if (openId.value == null) return
  if (!(await ask({ title: t('sessions.deleteMsgTitle'), content: t('sessions.deleteMsgBody') }))) return
  await store.removeMessage(openId.value, m.id)
  store.load()
}

async function clearAll(): Promise<void> {
  if (openId.value == null) return
  if (
    !(await ask({
      title: t('sessions.clearTitle'),
      content: t('sessions.clearBody')
    }))
  )
    return
  await store.clearMessages(openId.value)
  store.load()
}

function search(): void {
  store.resetAndLoad()
}

function reset(): void {
  store.filters.q = ''
  store.filters.state = ''
  store.filters.inst = ''
  store.filters.range = ''
  store.filters.from = ''
  store.filters.to = ''
  store.resetAndLoad()
}

onMounted(() => {
  store.resetAndLoad()
  store.loadInstances()
})
</script>

<template>
  <section class="hv">
    <header class="hv__head">
      <div>
        <h1>{{ t('sessions.hist.title') }}</h1>
        <p class="hv__sub">{{ t('sessions.historyDesc') }}</p>
      </div>
      <button type="button" class="btn sm" @click="store.resetAndLoad()">{{ t('common.refresh') }}</button>
    </header>

    <!-- KPI 卡（原型 grid g4 + .kpi）：总数 / 正常 / 失败 / 平均 TTFT -->
    <div class="grid g4 hv__kpis">
      <div class="kpi hv__kpi">
        <div class="label">{{ t('sessions.hist.kpi.total') }}</div>
        <div class="value">{{ store.stats?.total ?? '—' }}</div>
        <div class="sub">{{ t('sessions.hist.kpi.sub') }}</div>
      </div>
      <div class="kpi hv__kpi">
        <div class="label">{{ t('sessions.hist.kpi.done') }}</div>
        <div class="value">{{ store.stats?.done ?? '—' }}</div>
        <div class="sub">{{ t('sessions.hist.kpi.sub') }}</div>
      </div>
      <div class="kpi hv__kpi">
        <div class="label">{{ t('sessions.hist.kpi.failed') }}</div>
        <div class="value" :style="store.stats?.failed ? 'color:var(--s2s-color-danger)' : ''">
          {{ store.stats?.failed ?? '—' }}
        </div>
        <div class="sub">{{ t('sessions.hist.kpi.sub') }}</div>
      </div>
      <div class="kpi hv__kpi">
        <div class="label">{{ t('sessions.hist.kpi.avgTtfa') }}</div>
        <div class="value">{{ store.stats ? `${store.stats.avgTtfaMs}ms` : '—' }}</div>
        <div class="sub">{{ t('sessions.hist.kpi.sub') }}</div>
      </div>
    </div>

    <!-- 筛选卡（原型 filter-grid 12 列）：一行 4 个检索框，动作行在下 -->
    <div class="card">
      <h3>{{ t('sessions.hist.filter.title') }}</h3>
      <form class="filter-grid" @submit.prevent="search">
        <div class="fbar wide">
          <label for="hist-kw">{{ t('sessions.hist.filter.kw') }}</label>
          <input
            id="hist-kw"
            v-model="store.filters.q"
            type="search"
            class="fin"
            :placeholder="t('sessions.hist.filter.kwPh')"
            autocomplete="off"
          />
        </div>
        <div class="fbar n2">
          <label for="hist-state">{{ t('sessions.hist.filter.state') }}</label>
          <select id="hist-state" v-model="store.filters.state" class="fin">
            <option v-for="option in stateOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>
        <div class="fbar n2">
          <label for="hist-inst">{{ t('sessions.hist.filter.inst') }}</label>
          <select id="hist-inst" v-model="store.filters.inst" class="fin">
            <option value="">{{ t('sessions.hist.filter.all') }}</option>
            <option v-for="item in store.instances" :key="`${item.instanceId}|${item.node}`" :value="item.instanceId">
              {{ routeCell(item.instanceId, item.node) }}
            </option>
          </select>
        </div>
        <div class="fbar n2">
          <label for="hist-range">{{ t('sessions.hist.filter.range') }}</label>
          <select id="hist-range" v-model="store.filters.range" class="fin">
            <option v-for="option in rangeOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>
        <div class="fbar-actions">
          <button type="submit" class="btn primary sm">{{ t('sessions.hist.query') }}</button>
          <button type="button" class="btn sm" @click="reset">{{ t('sessions.hist.reset') }}</button>
          <span class="spacer"></span>
          <span class="muted">{{ t('sessions.hist.count', { n: store.total }) }}</span>
          <span v-if="selected.size" class="hv__selbar">
            <span class="muted">{{ t('sessions.hist.sel.count', { n: selected.size }) }}</span>
            <button type="button" class="btn sm danger" @click="batchDelete">
              {{ t('sessions.hist.deleteSelected') }}
            </button>
          </span>
        </div>
      </form>
    </div>

    <p v-if="store.error" class="hv__error">{{ store.error }}</p>

    <!-- 会话表：11 列 -->
    <div class="card">
      <h3>
        {{ t('sessions.hist.title') }}
        <span class="hint">{{ t('sessions.hist.count', { n: store.total }) }}</span>
      </h3>
      <div class="hv__tablebox">
        <table class="hv__tbl">
          <thead>
            <tr>
              <th style="width: 36px">
                <input type="checkbox" :checked="allChecked" @change="toggleAll" />
              </th>
              <th>{{ t('sessions.hist.col.id') }}</th>
              <th>{{ t('sessions.hist.col.start') }}</th>
              <th>{{ t('sessions.hist.col.route') }}</th>
              <th>{{ t('sessions.hist.col.excerpt') }}</th>
              <th>{{ t('sessions.hist.col.turns') }}</th>
              <th>{{ t('sessions.hist.col.msgs') }}</th>
              <th>{{ t('sessions.hist.col.dur') }}</th>
              <th>{{ t('sessions.hist.col.ttft') }}</th>
              <th>{{ t('sessions.col.state') }}</th>
              <th>{{ t('sessions.hist.col.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in store.rows"
              :key="row.id"
              class="clickable"
              :class="{ sel: openId === row.id }"
              @click="togglePanel(row.id)"
            >
              <td @click.stop><input type="checkbox" :checked="selected.has(row.id)" @change="toggle(row.id)" /></td>
              <td class="mono">#{{ row.id }}</td>
              <td class="mono">{{ row.createdAt }}</td>
              <td class="mono">{{ routeCell(row.instanceId, row.node) }}</td>
              <td class="hv__excerpt" :title="row.excerpt">{{ row.excerpt || '—' }}</td>
              <td class="num mono">{{ row.turns }}</td>
              <td class="num mono">{{ row.messageCount }}</td>
              <td class="num mono">{{ fmtDuration(row.durationMs) }}</td>
              <td class="num mono">{{ fmtTtfa(row.ttfaMs) }}</td>
              <td><PBadge :kind="row.state === 'failed' ? 'bad' : 'ok'" :text="row.state" /></td>
              <td class="acts" @click.stop>
                <button type="button" class="btn sm" @click="togglePanel(row.id)">
                  {{ t('sessions.hist.viewMessages') }}
                </button>
                <button type="button" class="btn sm danger" @click="deleteOne(row.id)">
                  {{ t('sessions.deleteRecord') }}
                </button>
              </td>
            </tr>
            <tr v-if="!store.loading && !store.rows.length">
              <td colspan="11" class="hv__empty">{{ t('sessions.hist.empty') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="hv__pager">
        <button type="button" class="btn sm" :disabled="store.page <= 1" @click="store.page--; store.load()">
          ‹ {{ t('sessions.hist.prev') }}
        </button>
        <span class="mono">{{ t('sessions.hist.pageOf', { n: store.page, m: pageTotal }) }}</span>
        <button type="button" class="btn sm" :disabled="store.page >= pageTotal" @click="store.page++; store.load()">
          {{ t('sessions.hist.next') }} ›
        </button>
      </div>
    </div>

    <!-- 页内展开：会话消息面板 -->
    <div v-if="openId != null && store.detail" class="card hv__panel">
      <h3>
        {{ t('sessions.hist.msg.title') }}
        <span class="hint">{{ store.detail.id }} · {{ t('sessions.hist.msg.count', { n: panelMessages.length }) }}</span>
        <span class="spacer"></span>
        <button type="button" class="btn sm danger" @click="clearAll">
          {{ t('sessions.hist.msg.clear') }}
        </button>
      </h3>
      <div class="hv__panelfilter">
        <input
          v-model="panelKw"
          type="search"
          class="fin"
          :placeholder="t('sessions.hist.msg.kw')"
          autocomplete="off"
        />
      </div>
      <div class="hv__tablebox">
        <table class="hv__tbl">
          <thead>
            <tr>
              <th>{{ t('sessions.hist.midCol') }}</th>
              <th>{{ t('sessions.hist.roleCol') }}</th>
              <th>{{ t('sessions.hist.typeCol') }}</th>
              <th>{{ t('sessions.hist.contentCol') }}</th>
              <th>{{ t('sessions.hist.atCol') }}</th>
              <th>{{ t('sessions.hist.statusCol') }}</th>
              <th>{{ t('sessions.hist.col.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in panelMessages" :key="m.id">
              <td class="mono">m{{ m.ordinal + 1 }}</td>
              <td>{{ roleLabel(m) }}</td>
              <td>{{ typeLabel(m) }}</td>
              <td class="cell-clip" :title="m.content">{{ m.content || '—' }}</td>
              <td class="mono">{{ m.createdAt }}</td>
              <td>
                <PBadge :kind="m.status === 'fail' ? 'bad' : 'ok'" :text="t(`sessions.hist.flag.${m.status}`)" />
              </td>
              <td class="acts">
                <button type="button" class="btn sm danger" @click="deleteMessage(m)">
                  {{ t('sessions.deleteRecord') }}
                </button>
              </td>
            </tr>
            <tr v-if="!panelMessages.length">
              <td colspan="7" class="hv__empty">{{ t('sessions.hist.msg.noMatch') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <ConfirmDialog
      :open="open"
      :title="title"
      :content="content"
      danger
      @answer="answer"
    />
  </section>
</template>

<style scoped lang="less">
.hv {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 20px;

  &__head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    /* 原型 .page-head：h1 20px 粗体 + 13px muted 副标题。 */
    h1 {
      margin: 0 0 6px;
      font-size: 20px;
      font-weight: 700;
    }
  }
  &__sub {
    margin: 0;
    color: var(--s2s-color-muted);
    font-size: 13px;
  }
  &__kpis {
    margin-bottom: 2px;
  }
  /* 原型 filter-grid（12 列栅格）：一行 4 个检索框，动作行 span 12。 */
  .filter-grid {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 12px;
  }
  .fbar {
    grid-column: span 3;
    min-width: 0;
    label {
      display: block;
      font-size: 12px;
      color: var(--s2s-color-muted);
      margin-bottom: 6px;
    }
    .fin {
      margin: 0;
    }
  }
  .fbar.wide {
    grid-column: span 6;
  }
  .fbar.n2 {
    grid-column: span 2;
  }
  .fbar-actions {
    grid-column: span 12;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    .muted {
      font-size: 12px;
    }
  }
  &__excerpt {
    white-space: normal;
    word-break: break-word;
    min-width: 260px;
    max-width: 480px;
  }
  &__selbar {
    display: inline-flex;
    gap: 8px;
    align-items: center;
  }
  &__error {
    color: var(--danger-text);
    font-size: 13px;
    margin: 0;
  }
  &__tablebox {
    overflow-x: auto;
  }
  &__tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    th,
    td {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    th.num,
    td.num {
      text-align: right;
    }
    .cell-clip {
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    tr.clickable {
      cursor: pointer;
    }
    tr.sel td {
      background: var(--surface);
    }
    .acts {
      white-space: nowrap;
    }
  }
  &__empty {
    color: var(--muted);
    text-align: center;
    padding: 16px 0;
  }
  &__pager {
    display: flex;
    gap: 10px;
    align-items: center;
    justify-content: flex-end;
    padding-top: 10px;
  }
  &__panelfilter {
    margin-bottom: 10px;
    .fin {
      min-width: 260px;
    }
  }
  .spacer {
    flex: 1;
  }
  .hint {
    color: var(--muted);
    font-size: 11px;
    margin-left: 8px;
  }
}
</style>
