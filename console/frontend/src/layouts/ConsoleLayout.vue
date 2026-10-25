<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { navGroupFor, navItemsFor, type NavItem } from '@/router/nav'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore } from '@/stores/console'
import { DRAWER_BREAKPOINT, useShellStore } from '@/stores/shell'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const consoleStore = useConsoleStore()
const shell = useShellStore()

/** 一个外壳两个面：面由子路由声明，外壳不猜。 */
const face = computed<'console' | 'voice'>(() => (route.meta.face === 'voice' ? 'voice' : 'console'))

// `hasRoute` 让菜单在 Task 12/13 逐个建视图的过程中保持诚实。
const items = computed(() =>
  navItemsFor(face.value).filter((item) => !item.name || router.hasRoute(item.name))
)
/** 分组标题与菜单同源，折叠态由 CSS 隐藏。 */
const groupLabel = computed(() => navGroupFor(face.value)?.label ?? '')

function keyOf(item: NavItem): string {
  return item.name ?? `overlay:${item.action}`
}

/** 只有路由项能「当前」：浮层项是动作，打开即关闭，没有停留的位置。 */
function isCurrent(item: NavItem): boolean {
  return Boolean(item.name) && route.name === item.name
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

// 状态轮询只属于运维面：对话页匿名可用，不该去打 JWT 接口（否则顶栏挂一条 401）。
watch(
  face,
  (value) => (value === 'console' ? consoleStore.startPolling() : consoleStore.stopPolling()),
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

function onNavClick(item: NavItem): void {
  if (item.name) void router.push({ name: item.name })
  else if (item.action) shell.openOverlay(item.action)
  shell.closeDrawer()
}

function signOut(): void {
  auth.logout()
  void router.replace({ name: 'login' })
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

      <span class="shell__brand">{{ face === 'console' ? 'S2S 控制台' : 'S2S' }}</span>

      <template v-if="face === 'console'">
        <a-select
          :value="consoleStore.profile"
          :options="profileOptions"
          size="small"
          class="shell__profile"
          @change="(value: unknown) => consoleStore.selectProfile(String(value))"
        />
        <a-badge :status="pipelineBadge" :text="pipelineText" />
      </template>

      <span class="shell__spacer" />

      <!-- 对话页把账号 chip 与工具 / 历史 / 设置三枚按钮 Teleport 到这里（§3.2.4），
           所以它没有自己的顶栏，也无法盖住外壳。运维面这里是空的。 -->
      <div v-if="face === 'voice'" id="shell-actions" class="shell__actions" />

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

      <template v-if="face === 'console'">
        <span class="shell__user">{{ auth.user?.username }} · {{ auth.user?.role }}</span>
        <a-button type="link" size="small" @click="signOut">退出</a-button>
      </template>
    </header>

    <div class="shell__body">
      <nav id="shell-nav" class="shell__nav" :class="{ 'is-open': shell.drawerOpen }" aria-label="主导航">
        <div class="shell__nav-label">{{ groupLabel }}</div>

        <!-- 原生纽而非 `a-menu`：折叠后 `.nav` 只剩图标，geometry 与
             console-preview.html 的侧栏一致（图标 + 文字 / 居中图标）。 -->
        <button
          v-for="item in items"
          :key="keyOf(item)"
          class="nav"
          type="button"
          :aria-current="isCurrent(item) ? 'true' : undefined"
          :title="item.label"
          @click="onNavClick(item)"
        >
          <svg class="nav__icon" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
            <use :href="`#i-${item.icon}`" />
          </svg>
          <span>{{ item.label }}</span>
        </button>

        <router-link v-if="face === 'voice'" class="shell__link" :to="{ name: 'console' }" title="运维控制台">
          运维控制台 ↗
        </router-link>
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
  background: #0b1020;
  color: #e6e8f0;

  &__top {
    align-items: center;
    background: #141a2e;
    border-bottom: 1px solid #1f2740;
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
    color: #8b93a7;
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
    color: #8b93a7;
    cursor: pointer;
    flex: none;
    font-size: 14px;
    line-height: 1;
    padding: 4px 8px;
    border-radius: 6px;

    &:hover {
      background: #1d2742;
      color: #e6e8f0;
    }
  }

  &__user {
    color: #8b93a7;
    font-size: 12px;
  }

  &__body {
    display: flex;
    flex: 1 1 auto;
    min-height: 0;
    position: relative;
  }

  &__nav {
    background: #0f1424;
    border-right: 1px solid #1f2740;
    flex: 0 0 200px;
    min-width: 0;
    overflow: auto;
    transition: flex-basis 160ms ease, width 160ms ease;
    width: 200px;
  }

  &__link {
    color: #8b93a7;
    display: block;
    font-size: 12px;
    margin: 10px 8px 12px;
    padding: 8px 10px;
  }

  // 分组标题：11px 全大写小标，折叠后没有宽度可容，直接隐藏。
  &__nav-label {
    color: #6b7285;
    font-size: 11px;
    letter-spacing: 0.6px;
    padding: 10px 18px 6px;
    text-transform: uppercase;
    white-space: nowrap;
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
  color: #8b93a7;
  cursor: pointer;
  display: flex;
  gap: 9px;
  margin: 0 8px 2px;
  padding: 8px 10px;
  text-align: left;
  transition: background 0.15s, color 0.15s;
  width: calc(100% - 16px);

  &:hover {
    background: #1b2338;
    color: #e6e8f0;
  }

  &[aria-current='true'] {
    background: #1d2a4a;
    color: #e6e8f0;
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
