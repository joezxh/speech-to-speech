import Antd from 'ant-design-vue'
import { createApp } from 'vue'

import App from './App.vue'
import i18n from './i18n'
import router from './router'
import { pinia } from './stores'

import 'ant-design-vue/dist/reset.css'
import './styles/index.less'

// `reset.css` 是 antd 的亮色基线，必须排在 `index.less` 之前；真正的深色不在这里，
// 而在 App.vue 的 <a-config-provider :theme="themeConfig">——`/` 对话页不经过
// `ConsoleLayout`，主题下沉会把那里所有 AntD 控件打回亮色。
createApp(App).use(pinia).use(i18n).use(Antd).use(router).mount('#app')
