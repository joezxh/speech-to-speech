<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { navItemsFor, type NavItem } from '@/router/nav'
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
const selected = computed(() => [String(route.name ?? '')])

function keyOf(item: NavItem): string {
  return item.name ?? `overlay:${item.action}`
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

function onMenuClick(info: { key: string | number }): void {
  const item = items.value.find((candidate) => keyOf(candidate) === String(info.key))
  if (!item) return
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
        <span class="shell__spacer" />
        <button class="shell__collapse" type="button" aria-label="Toggle sidebar" @click="shell.toggleSider()">
          {{ shell.siderCollapsed ? '»' : '«' }}
        </button>
        <span class="shell__user">{{ auth.user?.username }} · {{ auth.user?.role }}</span>
        <a-button type="link" size="small" @click="signOut">退出</a-button>
      </template>

      <template v-else>
        <span class="shell__spacer" />
        <!-- 对话页把账号 chip 与工具 / 历史 / 设置三枚按钮 Teleport 到这里（§3.2.4），
             所以它没有自己的顶栏，也无法盖住外壳。 -->
        <div id="shell-actions" class="shell__actions" />
      </template>
    </header>

    <div class="shell__body">
      <nav id="shell-nav" class="shell__nav" :class="{ 'is-open': shell.drawerOpen }" aria-label="主导航">
        <a-menu mode="inline" theme="dark" :selected-keys="selected" @click="onMenuClick">
          <a-menu-item v-for="item in items" :key="keyOf(item)">{{ item.label }}</a-menu-item>
        </a-menu>

        <router-link v-if="face === 'voice'" class="shell__link" :to="{ name: 'console' }">运维控制台 ↗</router-link>
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
    font-size: 14px;
    padding: 2px 6px;
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
    padding: 12px 16px;
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
