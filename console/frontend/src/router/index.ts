import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'voice', component: () => import('@/views/PlaceholderView.vue') },
    { path: '/console/:pathMatch(.*)*', name: 'console', component: () => import('@/views/PlaceholderView.vue') }
  ]
})
