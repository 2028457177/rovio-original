import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/global.css'
import { initTheme } from './composables/useTheme.js'

initTheme()

const app = createApp(App)
app.use(router)
app.mount('#app')

// PWA：生产环境注册 Service Worker（离线缓存 / 安装到桌面；HTTPS 下生效）
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((err) => {
      console.warn('[SW] 注册失败:', err)
    })
  })
}
