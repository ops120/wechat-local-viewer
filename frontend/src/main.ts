import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './style.css'
import './grunge.css'
import { readInitialTheme, applyTheme } from './stores/theme'

// 首屏之前先套用主题，避免浅色闪一下再变暗
applyTheme(readInitialTheme())

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
