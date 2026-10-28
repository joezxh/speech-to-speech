<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { frontOverlays, type NavIcon, type NavMeta, type VoiceOverlay } from '@/router/nav'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore } from '@/stores/console'
import { DRAWER_BREAKPOINT, useShellStore } from '@/stores/shell'
import { useVoiceStore } from '@/stores/voice'
import AccountWidget from '@/features/voice/components/AccountWidget.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const consoleStore = useConsoleStore()
const shell = useShellStore()
const voice = useVoiceStore()
const { t } = useI18n()

/** 面仅用于样式与对话页顶栏动作；菜单与顶栏已统一，不再按面切换。 */
const face = computed<'console' | 'voice'>(() => (route.meta.face === 'voice' ? 'voice' : 'console'))

// 对话页顶栏动作（账号 chip + 工具 / 历史 / 设置）由本布局直接渲染，
// 不再由 VoiceView 用 Teleport 注入——那个跨组件 Teleport 会被 block 树打坏锚点。
const showActions = computed(() => face.value === 'voice')
const showAccount = computed(() => voice.me.enabled)
// 布尔化的未读：抽屉关闭期间来了新内容才亮，点开后由 `voice.openHistory()` 清掉
// （demo 的 `_markUnread` / `_openPanel`）。直接用 `voice.unread` 而不是「有没有条目」：
// 后者在纯手动的抽屉上没有任何信息量，且会让顶栏随每条转写重渲染。

// 侧栏导航从路由表 `meta` 派生（spec §6.1）：`navGroup` 分桶、`navOrder` 排序，
// 路由项受 `hasRoute` 约束；front 段额外拼上三个非路由的 overlay。
interface Row { key: string; icon: NavIcon; labelKey: string; to?: string; overlay?: VoiceOverlay }
interface Group { key: 'lb' | 'front' | 'ops'; rows: Row[] }

const GROUP_ORDER: Array<Group['key']> = ['lb', 'front', 'ops']

const groups = computed<Group[]>(() => {
  const buckets: Record<Group['key'], Array<{ row: Row; order: number }>> = { lb: [], front: [], ops: [] }
  for (const rec of router.getRoutes()) {
    const m = rec.meta as unknown as NavMeta
    if (!m.navKey || !m.navGroup) continue
    if (rec.name && !router.hasRoute(rec.name)) continue
    buckets[m.navGroup].push({
      row: { key: String(rec.name), icon: m.navIcon, labelKey: m.navKey, to: String(rec.name) },
      order: m.navOrder
    })
  }
  for (const ov of frontOverlays) {
    buckets.front.push({
      row: { key: `overlay:${ov.overlay}`, icon: ov.navIcon, labelKey: ov.navKey, overlay: ov.overlay },
      order: ov.navOrder
    })
  }
  return GROUP_ORDER.map((key) => ({
    key,
    rows: buckets[key].sort((a, b) => a.order - b.order).map((entry) => entry.row)
  })).filter((group) => group.rows.length > 0)
})

/** 当前路由项高亮：对话页时 `voice`，其余页面对应路由；浮层项不参与。 */
function isCurrent(row: Row): boolean {
  return row.to !== undefined && route.name === row.to
}

const narrow = ref(false)
let mql: MediaQueryList | null = null

function syncNarrow(event: MediaQueryList | MediaQueryListEvent): void {
  narrow.value = event.matches
  if (!narrow.value) shell.closeDrawer()
}

const profileOptions = ['prod', 'dev'].map((value) => ({ value, label: value }))

const pipelineText = computed(() => {
  const status = consoleStore.status
  if (!status) return consoleStore.statusError || '未连接'
  const version = status.version === null ? '未发布' : `v${status.version}`
  return status.pipeline === 'ok' ? `pipeline ok · ${version}` : 'pipeline 不可达'
})

const pipelineBadge = computed(() => {
  if (!consoleStore.status) return 'error'
  return consoleStore.status.pipeline === 'ok' ? 'success' : 'error'
})

// 两个面都已纳入登录态，顶栏统一展示 pipeline 状态 → 全程轮询。
watch(
  face,
  () => consoleStore.startPolling(),
  { immediate: true }
)

onMounted(() => {
  // 与 `console.less` / `DRAWER_BREAKPOINT` 同值：小屏侧栏变抽屉，舞台不被挤压。
  mql = window.matchMedia(`(max-width: ${DRAWER_BREAKPOINT - 1}px)`)
  syncNarrow(mql)
  mql.addEventListener('change', syncNarrow)
})

onBeforeUnmount(() => {
  mql?.removeEventListener('change', syncNarrow)
  consoleStore.stopPolling()
})

function onNavClick(row: Row): void {
  if (row.to) {
    void router.push({ name: row.to })
  } else if (row.overlay) {
    // 先写待处理的浮层，再导航到对话页；VoiceView 的 `immediate` watch 会接手开启。
    // 已在对话页时，openOverlay 触发 watch 变更 → 直接开浮层。
    shell.openOverlay(row.overlay)
    if (route.name !== 'voice') void router.push({ name: 'voice' })
  }
  shell.closeDrawer()
}

function signOut(): void {
  auth.logout()
  void router.replace({ name: 'login' })
}

/**
 * 顶栏的会话按钮是开合切换（demo chat.js:83），不是只会打开。抽屉的开合存在
 * `voice.historyOpen`（而不是页面本地），因为徽标与开关分属外壳与 `VoiceView`。
 * 这枚按钮只在对话面渲染（`showActions`），所以 `historyOpen` 就是抽屉的真实状态。
 */
function onHistoryClick(): void {
  if (voice.historyOpen) voice.closeHistory()
  else shell.openOverlay('history')
}
</script>

<template>
  <div class="shell" :data-face="face" :class="{ 'is-collapsed': shell.siderCollapsed }">
    <header class="shell__top">
      <button
        class="shell__burger"
        type="button"
        aria-label="Toggle navigation"
        aria-controls="shell-nav"
        :aria-expanded="shell.drawerOpen"
        @click="shell.drawerOpen = !shell.drawerOpen"
      >
        <span /><span /><span />
      </button>

      <span class="shell__brand">S2S 控制台</span>

      <a-select
        :value="consoleStore.profile"
        :options="profileOptions"
        size="small"
        class="shell__profile"
        @change="(value: unknown) => consoleStore.selectProfile(String(value))"
      />
      <a-badge :status="pipelineBadge" :text="pipelineText" />

      <span class="shell__spacer" />

      <!-- 对话页的账号 chip 与工具 / 历史 / 设置三枚按钮由本布局直接渲染（不再 Teleport）；
           其余页面这里是空的。 -->
      <div v-if="showActions" id="shell-actions" class="shell__actions">
        <AccountWidget v-if="showAccount" :me="voice.me" @limit="shell.openLimit()" />
        <button class="v-icon" title="Tools" aria-label="Tools" @click="shell.openOverlay('tools')">
          <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-wrench" /></svg>
        </button>
        <button
          class="v-icon"
          title="Conversation history"
          aria-label="Conversation history"
          :aria-expanded="voice.historyOpen"
          @click="onHistoryClick()"
        >
          <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-chat" /></svg>
          <span v-if="voice.unread" class="v-badge" aria-hidden="true" />
        </button>
        <button class="v-icon" title="Settings" aria-label="Settings" @click="shell.openOverlay('settings')">
          <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-gear" /></svg>
        </button>
      </div>

      <!-- 两个面共用同一枚折叠纽：`aria-pressed` 给出状态，<980px 由 CSS 隐藏
           （那时侧栏是抽屉，用左侧的汉堡纽）。 -->
      <button
        class="shell__collapse"
        type="button"
        aria-label="Toggle sidebar"
        :aria-pressed="shell.siderCollapsed ? 'true' : 'false'"
        :title="shell.siderCollapsed ? '展开侧栏' : '折叠侧栏'"
        @click="shell.toggleSider()"
      >
        {{ shell.siderCollapsed ? '»' : '«' }}
      </button>

      <span class="shell__user">{{ auth.user?.username }} · {{ auth.user?.role }}</span>
      <a-button type="link" size="small" @click="signOut">退出</a-button>
    </header>

    <div class="shell__body">
      <nav id="shell-nav" class="shell__nav" :class="{ 'is-open': shell.drawerOpen }" aria-label="主导航">
        <template v-for="(group, gi) in groups" :key="group.key">
          <div class="shell__nav-label" :class="{ 'is-first': gi === 0 }">{{ t(`nav.group.${group.key}`) }}</div>

          <!-- 原生纽而非 `a-menu`：折叠后 `.nav` 只剩图标，geometry 与
               console-preview.html 的侧栏一致（图标 + 文字 / 居中图标）。 -->
          <button
            v-for="row in group.rows"
            :key="row.key"
            class="nav"
            type="button"
            :aria-current="isCurrent(row) ? 'true' : undefined"
            :title="t(row.labelKey)"
            @click="onNavClick(row)"
          >
            <svg class="nav__icon" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
              <use :href="`#i-${row.icon}`" />
            </svg>
            <span>{{ t(row.labelKey) }}</span>
          </button>
        </template>
      </nav>

      <div v-if="shell.drawerOpen" class="shell__scrim" @click="shell.closeDrawer()" />

      <main class="shell__content">
        <router-view v-slot="{ Component }">
          <component :is="Component" v-if="Component" />
          <a-empty v-else description="选择左侧菜单开始" />
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped lang="less">
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--s2s-color-bg);
  color: var(--s2s-color-text);

  &__top {
    align-items: center;
    background: var(--s2s-color-surface);
    border-bottom: 1px solid var(--s2s-color-border);
    display: flex;
    flex: 0 0 56px;
    gap: 16px;
    height: 56px;
    padding: 0 20px;
    position: relative;
    z-index: 20;
  }

  &__burger {
    align-items: center;
    background: transparent;
    border: 0;
    color: var(--s2s-color-muted);
    cursor: pointer;
    display: none;
    flex-direction: column;
    gap: 4px;
    padding: 6px 4px;

    span {
      background: currentColor;
      display: block;
      height: 2px;
      width: 18px;
    }
  }

  &__brand {
    font-weight: 600;
    white-space: nowrap;
  }

  &__profile {
    width: 120px;
  }

  &__spacer {
    flex: 1;
  }

  // Teleport 的落点：对话页的四个圆钮就长在这里。
  &__actions {
    align-items: center;
    display: flex;
    gap: 8px;
    min-height: 32px;
  }

  &__collapse {
    background: transparent;
    border: 0;
    color: var(--s2s-color-muted);
    cursor: pointer;
    flex: none;
    font-size: 14px;
    line-height: 1;
    padding: 4px 8px;
    border-radius: 6px;

    &:hover {
      background: var(--s2s-color-surface-2);
      color: var(--s2s-color-text);
    }
  }

  &__user {
    color: var(--s2s-color-muted);
    font-size: 12px;
  }

  &__body {
    display: flex;
    flex: 1 1 auto;
    min-height: 0;
    position: relative;
  }

  &__nav {
    background: var(--s2s-color-surface);
    border-right: 1px solid var(--s2s-color-border);
    flex: 0 0 200px;
    min-width: 0;
    overflow: auto;
    transition: flex-basis 160ms ease, width 160ms ease;
    width: 200px;
  }

  &__link {
    color: var(--s2s-color-muted);
    display: block;
    font-size: 12px;
    margin: 10px 8px 12px;
    padding: 8px 10px;
  }

  // 分组标题：11px 全大写小标，折叠后没有宽度可容，直接隐藏。
  &__nav-label {
    color: var(--s2s-color-faint);
    font-size: 11px;
    letter-spacing: 0.6px;
    padding: 10px 18px 6px;
    text-transform: uppercase;
    white-space: nowrap;

    // 第二组起：顶部细线 + 间距把两个菜单组分开（对齐 preview 的组间留白）。
    &:not(.is-first) {
      border-top: 1px solid var(--s2s-color-border);
      margin-top: 10px;
      padding-top: 14px;
    }
  }

  &__content {
    flex: 1 1 auto;
    min-height: 0;
    min-width: 0;
    overflow: auto;
  }

  &__scrim {
    display: none;
  }
}

.shell.is-collapsed .shell__nav {
  flex-basis: 56px;
  width: 56px;
}

/* 折叠态：分组标题与文字都让位给图标（console-preview.html:161-164）。 */
.shell.is-collapsed .shell__nav-label,
.shell.is-collapsed .shell__link,
.shell.is-collapsed .shell__nav .nav span {
  display: none;
}

.shell.is-collapsed .shell__nav .nav {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

/* 侧栏项：图标 + 文字，`aria-current` 是当前页。 */
.shell__nav .nav {
  align-items: center;
  background: none;
  border: 0;
  border-radius: 6px;
  color: var(--s2s-color-muted);
  cursor: pointer;
  display: flex;
  gap: 9px;
  margin: 0 8px 2px;
  padding: 8px 10px;
  text-align: left;
  transition: background 0.15s, color 0.15s;
  width: calc(100% - 16px);

  &:hover {
    background: var(--s2s-color-surface-2);
    color: var(--s2s-color-text);
  }

  &[aria-current='true'] {
    background: var(--s2s-color-surface-2);
    color: var(--s2s-color-text);
    font-weight: 500;
  }

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.shell__nav .nav__icon {
  flex: none;
  opacity: 0.85;
}

/* 两个面的内容区边距不同：运维台要内边距，对话页要一整块舞台。 */
.shell[data-face='console'] .shell__content {
  padding: 20px;
}

.shell[data-face='voice'] .shell__content {
  /* 舞台高度由 `.v-page { height: 100% }` 自己管，外壳不再给 100vh。
     滚动只发生在历史抽屉里，页面本身不滚。 */
  overflow: hidden;
  padding: 0;
}

@media (max-width: 979px) {
  /* 小屏：侧栏变抽屉，舞台宽度不被挤压（§3.2.4）。 */
  .shell__burger {
    display: inline-flex;
  }

  /* 抽屉态没有「折叠」这个概念：56px 的图标条在触屏上点不中。 */
  .shell__collapse {
    display: none;
  }

  .shell__nav {
    bottom: 0;
    flex-basis: 200px;
    left: 0;
    position: absolute;
    top: 0;
    transform: translateX(-100%);
    transition: transform 160ms ease;
    width: 200px;
    z-index: 30;
  }

  .shell__nav.is-open {
    box-shadow: 24px 0 40px rgba(0, 0, 0, 0.45);
    transform: none;
  }

  /* 抽屉态忽略折叠：56px 的图标条在触屏上没有意义。 */
  .shell.is-collapsed .shell__nav {
    flex-basis: 200px;
    width: 200px;
  }

  .shell__scrim {
    background: rgba(4, 6, 12, 0.55);
    display: block;
    inset: 0;
    position: absolute;
    z-index: 25;
  }
}
</style>
