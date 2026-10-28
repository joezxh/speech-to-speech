import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

// 导出这张表本身：`router.spec.ts`（Task 20 Step 20）用 `createMemoryHistory`
// 建一个不进浏览器的同构实例来断言 matched 链，不依赖 DOM。
export const routes: RouteRecordRaw[] = [
  {
    path: '/console/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue')
  },
  {
    // 一个外壳统一导航：`/`（对话）与 `/console/*` 同属 `ConsoleLayout`，
    // 共用一套侧栏菜单与顶栏控件。对话页也纳入登录门禁，行为与 console 面一致。
    path: '/',
    component: () => import('@/layouts/ConsoleLayout.vue'),
    children: [
      {
        path: '',
        name: 'voice',
        component: () => import('@/views/VoiceView.vue'),
        meta: { face: 'voice', requiresAuth: true, navGroup: 'front', navKey: 'nav.voice', navIcon: 'target', navOrder: 10 }
      },
      {
        // 无组件记录只是命名空间：`hasRoute` 与 `addRoute` 需要一个挂点。
        // `meta` 会被子路由继承。导航从各子路由的 `navGroup/navKey/navIcon/navOrder` 派生。
        path: 'console',
        name: 'console',
        meta: { face: 'console', requiresAuth: true },
        children: [
          { path: '', redirect: { name: 'overview' } },
          // lb 段
          { path: 'overview', name: 'overview', component: () => import('@/views/OverviewView.vue'),
            meta: { navGroup: 'lb', navKey: 'nav.overview', navIcon: 'layers', navOrder: 10 } },
          { path: 'traffic', name: 'traffic', component: () => import('@/views/TrafficView.vue'),
            meta: { navGroup: 'lb', navKey: 'nav.traffic', navIcon: 'signal', navOrder: 20 } },
          // ops 段
          { path: 'machines', name: 'machines', component: () => import('@/views/InstancesView.vue'),
            meta: { navGroup: 'ops', navKey: 'nav.machines', navIcon: 'server', navOrder: 10 } },
          { path: 'deploy', name: 'deploy', component: () => import('@/views/ParamsView.vue'),
            meta: { navGroup: 'ops', navKey: 'nav.deploy', navIcon: 'cpu', navOrder: 20 } },
          { path: 'session-update', name: 'session-update', component: () => import('@/views/SessionsView.vue'),
            meta: { navGroup: 'ops', navKey: 'nav.sessionUpdate', navIcon: 'sliders', navOrder: 30 } },
          { path: 'voices', name: 'voices', component: () => import('@/views/VoicesView.vue'),
            meta: { navGroup: 'ops', navKey: 'nav.voices', navIcon: 'wave', navOrder: 40 } },
          { path: 'release', name: 'release', component: () => import('@/views/VersionsView.vue'),
            meta: { navGroup: 'ops', navKey: 'nav.release', navIcon: 'check', navOrder: 50 } },
          { path: 'audit', name: 'audit', component: () => import('@/views/AuditView.vue'),
            meta: { navGroup: 'ops', navKey: 'nav.audit', navIcon: 'history', navOrder: 60 } },
          // 旧路径 redirect（永久保留；name 只有新名）
          { path: 'params', redirect: { name: 'deploy' } },
          { path: 'instances', redirect: { name: 'machines' } },
          { path: 'instances/trends', redirect: { name: 'traffic' } },
          { path: 'versions', redirect: { name: 'release' } },
          { path: 'sessions', redirect: { name: 'session-update' } }
        ]
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const auth = useAuthStore(pinia)
  // 只看合并后的 `requiresAuth`：对话面与运维面都已上锁，未登录统一拦到登录页。
  if (to.meta.requiresAuth && !auth.signedIn) {
    return { name: 'login', query: { next: to.fullPath } }
  }
  if (to.name === 'login' && auth.signedIn) {
    return { path: '/console' }
  }
  return true
})

export default router
