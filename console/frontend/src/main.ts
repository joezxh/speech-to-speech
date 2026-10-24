import Antd from 'ant-design-vue'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

import 'ant-design-vue/dist/reset.css'
import './styles/index.less'

// `reset.css` 是 antd 的亮色基线，必须排在 `index.less` 之前；
// 真正的深色不在这里，而在 App.vue 的 <a-config-provider :theme="themeConfig">。
createApp(App).use(createPinia()).use(Antd).use(router).mount('#app')
