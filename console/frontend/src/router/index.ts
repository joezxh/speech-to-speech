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
    // 一个外壳两个面（§3.2.4）：`/` 与 `/console/*` 是同一个 `ConsoleLayout` 的
    // 子路由。只有 console 面要求登录；对话页匿名可开，与旧页一致。
    path: '/',
    component: () => import('@/layouts/ConsoleLayout.vue'),
    children: [
      {
        path: '',
        name: 'voice',
        component: () => import('@/views/VoiceView.vue'),
        meta: { face: 'voice' }
      },
      {
        // 无组件记录只是命名空间：`hasRoute` 与 `addRoute` 需要一个挂点，
        // 其余子路由由 Task 13 注册进来。`meta` 会被子路由继承。
        path: 'console',
        name: 'console',
        meta: { face: 'console', requiresAuth: true },
        children: [
          { path: '', redirect: { name: 'params' } },
          { path: 'params', name: 'params', component: () => import('@/views/ParamsView.vue') },
          { path: 'voices', name: 'voices', component: () => import('@/views/VoicesView.vue') },
          { path: 'versions', name: 'versions', component: () => import('@/views/VersionsView.vue') },
          { path: 'audit', name: 'audit', component: () => import('@/views/AuditView.vue') },
          { path: 'instances', name: 'instances', component: () => import('@/views/InstancesView.vue') },
          { path: 'sessions', name: 'sessions', component: () => import('@/views/SessionsView.vue') }
        ]
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const auth = useAuthStore(pinia)
  // 只看合并后的 `requiresAuth`：外壳自己不上锁，否则对话页也被拦在登录页外。
  if (to.meta.requiresAuth && !auth.signedIn) {
    return { name: 'login', query: { next: to.fullPath } }
  }
  if (to.name === 'login' && auth.signedIn) {
    return { path: '/console' }
  }
  return true
})

export default router
