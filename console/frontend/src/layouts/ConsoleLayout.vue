<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { frontOverlays, type NavIcon, type NavMeta, type VoiceOverlay } from '@/router/nav'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore } from '@/stores/console'
import { useLocaleStore } from '@/stores/locale'
import { DRAWER_BREAKPOINT, useShellStore } from '@/stores/shell'
import { useVoiceStore } from '@/stores/voice'
import AccountWidget from '@/features/voice/components/AccountWidget.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const consoleStore = useConsoleStore()
const shell = useShellStore()
const voice = useVoiceStore()
const localeStore = useLocaleStore()
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

// 面包屑（demo `#crumb`）：`分组名 › 页面名`，无导航元数据的页面不渲染。
const crumb = computed<{ group: string; label: string } | null>(() => {
  const m = route.meta as unknown as Partial<NavMeta>
  if (!m.navGroup || !m.navKey) return null
  return { group: t(`nav.group.${m.navGroup}`), label: t(m.navKey) }
})

const narrow = ref(false)
let mql: MediaQueryList | null = null

function syncNarrow(event: MediaQueryList | MediaQueryListEvent): void {
  narrow.value = event.matches
  if (!narrow.value) shell.closeDrawer()
}

const profileOptions = ['prod', 'dev'].map((value) => ({ value, label: value }))

function onProfileChange(event: Event): void {
  const select = event.target as HTMLSelectElement
  consoleStore.selectProfile(select.value)
}

// 健康胶囊（demo `#health-pill`）：未连接 = warn，pipeline 非 ok = bad，否则 ok。
const healthDot = computed<'ok' | 'warn' | 'bad'>(() => {
  const status = consoleStore.status
  if (!status) return 'warn'
  return status.pipeline === 'ok' ? 'ok' : 'bad'
})

const healthText = computed(() => {
  const status = consoleStore.status
  if (!status) return consoleStore.statusError || t('shell.notConnected')
  return status.pipeline === 'ok' ? t('shell.healthOk') : t('shell.pipelineUnreachable')
})

// 版本胶囊（demo `.pill.mono` 的 v1.4.2）：真实数据来自 status.version；
// 尚未发布时先占位 v1.0.0，版本号接入真实实现后再改回。
const versionText = computed(() => {
  const version = consoleStore.status?.version
  return version === null || version === undefined ? 'v1.0.0' : `v${version}`
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

/** 顶栏语言切换：两态直接互切，对齐 demo `#lang-btn`（非下拉）。 */
function toggleLocale(): void {
  localeStore.setLocale(localeStore.locale === 'zh-CN' ? 'en-US' : 'zh-CN')
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
    <!-- demo `.app`：侧栏是整高的左列，品牌在其顶部（= 页面左上角）；
         顶栏与内容区同处右列，顶栏左缘与内容区对齐。 -->
    <nav id="shell-nav" class="shell__nav" :class="{ 'is-open': shell.drawerOpen }" :aria-label="t('shell.mainNav')">
      <!-- 品牌区：demo 的 `.brand` 在侧栏顶部左上角，不在顶栏。 -->
      <div class="shell__brand">
        <span class="shell__brand-mark" aria-hidden="true">S2S</span>
        <span class="shell__brand-text">
          <span class="shell__brand-name">{{ t('shell.brandName') }}</span>
          <span class="shell__brand-sub">{{ t('shell.brandSub') }}</span>
        </span>
      </div>

      <template v-for="(group, gi) in groups" :key="group.key">
        <div class="shell__nav-label" :class="{ 'is-first': gi === 0 }">{{ t(`nav.group.${group.key}`) }}</div>

        <!-- 原生纽而非 `a-menu`：折叠后 `.nav` 只剩图标（图标 + 文字 / 居中图标）。 -->
        <button
          v-for="row in group.rows"
          :key="row.key"
          class="nav"
          type="button"
          :aria-current="isCurrent(row) ? 'true' : undefined"
          :title="t(row.labelKey)"
          @click="onNavClick(row)"
        >
          <svg class="nav__icon" width="17" height="17" viewBox="0 0 24 24" aria-hidden="true">
            <use :href="`#i-${row.icon}`" />
          </svg>
          <span>{{ t(row.labelKey) }}</span>
        </button>
      </template>

      <!-- 侧栏脚注（demo `.side-foot`）：margin-top auto 锚在底部。 -->
      <div class="shell__side-foot">{{ t('shell.sideFoot') }}</div>
    </nav>

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

      <!-- 面包屑（demo `.crumb`）：分组 › 当前页，粗体段是当前页。 -->
      <span v-if="crumb" class="shell__crumb">{{ crumb.group }} › <b>{{ crumb.label }}</b></span>

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

      <!-- 集群胶囊（demo `#cluster-pill`）：S1 的集群即 profile 权宜映射，
           换成 demo 的原生 select 胶囊样式。 -->
      <label class="shell__pill">
        <span>{{ t('shell.cluster') }}</span>
        <select :value="consoleStore.profile" :aria-label="t('shell.cluster')" @change="onProfileChange">
          <option v-for="opt in profileOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
      </label>

      <!-- 健康胶囊（demo `#health-pill`）：状态点 + 文案。 -->
      <span class="shell__pill">
        <span class="shell__dot" :class="`is-${healthDot}`" aria-hidden="true" />
        <span>{{ healthText }}</span>
      </span>

      <!-- 版本胶囊（demo `.pill.mono`）。 -->
      <span class="shell__pill shell__pill--mono">{{ versionText }}</span>

      <!-- 两个面共用同一枚折叠纽：`aria-pressed` 给出状态，<980px 由 CSS 隐藏
           （那时侧栏是抽屉，用左侧的汉堡纽）。 -->
      <button
        class="shell__collapse"
        type="button"
        aria-label="Toggle sidebar"
        :aria-pressed="shell.siderCollapsed ? 'true' : 'false'"
        :title="shell.siderCollapsed ? t('shell.expandSider') : t('shell.collapseSider')"
        @click="shell.toggleSider()"
      >
        {{ shell.siderCollapsed ? '»' : '«' }}
      </button>

      <button
        class="shell__pill shell__lang"
        type="button"
        :aria-label="t('shell.language')"
        :title="t('shell.language')"
        @click="toggleLocale"
      >
        {{ localeStore.locale === 'zh-CN' ? 'English' : '中文' }}
      </button>

      <span class="shell__user">{{ auth.user?.username }} · {{ auth.user?.role }}</span>
      <a-button type="link" size="small" @click="signOut">{{ t('shell.signOut') }}</a-button>
    </header>

    <main class="shell__content">
      <router-view v-slot="{ Component }">
        <component :is="Component" v-if="Component" />
        <a-empty v-else :description="t('shell.selectMenuPrompt')" />
      </router-view>
    </main>

    <div v-if="shell.drawerOpen" class="shell__scrim" @click="shell.closeDrawer()" />
  </div>
</template>

<style scoped lang="less">
.shell {
  background: var(--s2s-color-bg);
  color: var(--s2s-color-text);
  // demo `.app`：侧栏整高在左（品牌 = 页面左上角），顶栏与内容同处右列；
  // 网格区域把顶栏钉在 nav 右侧，左缘天然与内容区对齐。
  display: grid;
  grid-template-areas:
    'nav top'
    'nav content';
  grid-template-columns: 236px minmax(0, 1fr);
  grid-template-rows: 56px minmax(0, 1fr);
  height: 100%;
  overflow: hidden;
  position: relative;
  transition: grid-template-columns 160ms ease;

  &__top {
    align-items: center;
    background: var(--s2s-color-surface);
    border-bottom: 1px solid var(--s2s-color-border);
    display: flex;
    gap: 12px; // demo `.topbar`：gap 12px，高度 56px 与 padding 完全对齐
    grid-area: top;
    height: 56px;
    padding: 0 20px;
    position: relative;
    z-index: 20;
  }

  // demo `.crumb`：弱色单行，省略号截断，粗体段是当前页。
  &__crumb {
    color: var(--s2s-color-muted);
    font-size: 13px;
    max-width: 30vw;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;

    b {
      color: var(--s2s-color-text);
      font-weight: 600;
    }
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

  // demo `.brand`：侧栏顶部左上角，padding 18/16/12。
  &__brand {
    align-items: center;
    display: flex;
    flex: none;
    gap: 10px;
    padding: 18px 16px 12px;
    white-space: nowrap;
  }

  // demo `.brand-mark`：30px 渐变胶囊，蓝→紫（token 化的 accent/purple）。
  &__brand-mark {
    align-items: center;
    background: linear-gradient(135deg, var(--s2s-color-accent), var(--s2s-color-purple));
    border-radius: 8px;
    color: #fff;
    display: flex;
    flex: none;
    font-size: 13px;
    font-weight: 700;
    height: 30px;
    justify-content: center;
    width: 30px;
  }

  &__brand-text {
    display: flex;
    flex-direction: column;
    // ant-design-vue 的全局 reset 把 body 行高压成 1.15；demo 是 normal。
    // 在品牌文字块上显式还原，两行行盒 19+15px，整栏高度与 demo `.brand` 的 64px 一致。
    line-height: normal;
  }

  &__brand-name {
    font-size: 14px;
    font-weight: 650;
    letter-spacing: 0.02em;
  }

  &__brand-sub {
    color: var(--s2s-color-muted);
    font-size: 11px;
  }

  // demo `.pill`：小圆胶囊，surface-2 底 + border-strong 描边。
  &__pill {
    align-items: center;
    background: var(--s2s-color-surface-2);
    border: 1px solid var(--s2s-color-border-strong);
    border-radius: 999px;
    color: var(--s2s-color-muted);
    cursor: default;
    display: inline-flex;
    flex: none;
    font-size: 12px;
    gap: 6px;
    padding: 4px 10px;

    // demo `.pill select`：原生 select 去框，文字用主文本色。
    select {
      background: transparent;
      border: 0;
      color: var(--s2s-color-text);
      cursor: pointer;
      font: inherit;
      outline: none;

      // 下拉弹层是系统白底，选项文字改用深色 token（hex 禁令不允许裸 hex）。
      option {
        color: var(--s2s-color-bg);
      }
    }

    &--mono {
      font-family: var(--s2s-font-mono);
    }
  }

  // demo `.dot`：8px 状态点，颜色全部走语义 token。
  &__dot {
    border-radius: 50%;
    flex: none;
    height: 8px;
    width: 8px;

    &.is-ok {
      background: var(--s2s-color-success);
    }

    &.is-warn {
      background: var(--s2s-color-warning);
    }

    &.is-bad {
      background: var(--s2s-color-danger);
    }
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

  // demo `#lang-btn`：胶囊态、主文本色可点击，悬停描边与文字变 accent。
  &__lang {
    cursor: pointer;
    color: var(--s2s-color-text);
    font-weight: 600;
    transition: border-color 0.15s, color 0.15s;

    &:hover {
      border-color: var(--s2s-color-accent);
      color: var(--s2s-color-accent);
    }
  }

  // demo `.sidebar`：整高左列，列布局让 `.side-foot` 锚底，整栏自滚。
  &__nav {
    background: var(--s2s-color-surface);
    border-right: 1px solid var(--s2s-color-border);
    display: flex;
    flex-direction: column;
    grid-area: nav;
    min-width: 0;
    overflow: auto;
  }

  &__link {
    color: var(--s2s-color-muted);
    display: block;
    font-size: 12px;
    margin: 10px 8px 12px;
    padding: 8px 10px;
  }

  // demo `.nav-title`：11px 全大写小标，.12em 字距；折叠后没有宽度可容，直接隐藏。
  &__nav-label {
    color: var(--s2s-color-faint);
    flex: none;
    font-size: 11px;
    letter-spacing: 0.12em;
    padding: 6px 10px 4px;
    text-transform: uppercase;
    white-space: nowrap;

    // demo `.nav-group` 不留分隔线，组间只用间距（非首组 = 10px 组间距 + 标题自身 6px）。
    &:not(.is-first) {
      margin-top: 10px;
    }

    // 首组：demo 品牌栏下 padding 12px 之外还有 `.nav-group` 的 10px 顶间距，
    // 6px 标题内边距 + 10px = 16px，与 demo 首组菜单上方的留白一致。
    &.is-first {
      padding-top: 16px;
    }
  }

  // demo `.side-foot`：底部细线 + 11px faint 双行说明。
  &__side-foot {
    border-top: 1px solid var(--s2s-color-border);
    color: var(--s2s-color-faint);
    flex: none;
    font-size: 11px;
    line-height: 1.7;
    margin-top: auto;
    padding: 12px 16px;
    white-space: pre-line;
  }

  &__content {
    grid-area: content;
    min-height: 0;
    min-width: 0;
    overflow: auto;
  }

  &__scrim {
    display: none;
  }
}

/* 折叠态：左列收窄成 56px 图标条（网格列宽随 `.shell` 过渡）。 */
.shell.is-collapsed {
  grid-template-columns: 56px minmax(0, 1fr);
}

/* 折叠态：分组标题、品牌文字与脚注都让位给图标。 */
.shell.is-collapsed .shell__nav-label,
.shell.is-collapsed .shell__link,
.shell.is-collapsed .shell__brand-text,
.shell.is-collapsed .shell__side-foot,
.shell.is-collapsed .shell__nav .nav span {
  display: none;
}

.shell.is-collapsed .shell__brand {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.shell.is-collapsed .shell__nav .nav {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

/* 侧栏项：demo `.nav-item`（图标 + 文字，padding 9/10，gap 10，radius-sm）；
   当前页用 accent-soft 底 + accent 文字，`aria-current` 是当前页。 */
.shell__nav .nav {
  align-items: center;
  background: none;
  border: 0;
  border-radius: var(--s2s-radius-sm);
  color: var(--s2s-color-muted);
  cursor: pointer;
  display: flex;
  flex: none;
  gap: 10px;
  margin: 0 8px 2px;
  padding: 9px 10px;
  text-align: left;
  transition: background 0.15s, color 0.15s;
  width: calc(100% - 16px);

  &:hover {
    background: var(--s2s-color-surface-2);
    color: var(--s2s-color-text);
  }

  &[aria-current='true'] {
    background: var(--s2s-color-accent-soft);
    color: var(--s2s-color-accent);
  }

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

/* demo `.nav-item svg`：17px 图标，固定不伸缩。 */
.shell__nav .nav__icon {
  flex: 0 0 17px;
  height: 17px;
  width: 17px;
}

/* 两个面的内容区边距不同：运维台用 demo `.content` 的 22/26/60，对话页要一整块舞台。 */
.shell[data-face='console'] .shell__content {
  padding: 22px 26px 60px;
}

.shell[data-face='voice'] .shell__content {
  /* 舞台高度由 `.v-page { height: 100% }` 自己管，外壳不再给 100vh。
     滚动只发生在历史抽屉里，页面本身不滚。 */
  overflow: hidden;
  padding: 0;
}

@media (max-width: 979px) {
  /* 小屏：左列抽离成覆盖式抽屉，右列占满整宽。 */
  .shell {
    grid-template-areas:
      'top'
      'content';
    grid-template-columns: minmax(0, 1fr);
  }

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
    left: 0;
    position: absolute;
    top: 0;
    transform: translateX(-100%);
    transition: transform 160ms ease;
    width: 236px;
    z-index: 30;
  }

  .shell__nav.is-open {
    box-shadow: 24px 0 40px rgba(0, 0, 0, 0.45);
    transform: none;
  }

  /* 抽屉态忽略折叠：56px 的图标条在触屏上没有意义。 */
  .shell.is-collapsed {
    grid-template-columns: minmax(0, 1fr);
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
