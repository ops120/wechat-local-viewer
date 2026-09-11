<template>
  <div class="app-shell h-screen w-screen flex flex-col bg-gray-100">
    <!-- 顶部导航栏 -->
    <nav class="app-nav bg-white shadow-sm px-4 py-3 flex items-center justify-between">
      <div class="flex items-center space-x-4">
        <h1 class="app-title text-xl font-semibold text-gray-800">微信本地查看器</h1>
        <span class="app-title-sub hidden sm:inline text-xs text-gray-400">WeChat Local Viewer</span>
      </div>
      <div class="flex items-center space-x-2">
        <!-- 皮肤切换 -->
        <div class="theme-switch" role="group" aria-label="界面皮肤">
          <button
            v-for="opt in themeOptions"
            :key="opt.value"
            type="button"
            class="theme-switch-btn"
            :class="{ 'is-active': themeStore.theme === opt.value }"
            :title="opt.hint"
            :aria-pressed="themeStore.theme === opt.value"
            @click="themeStore.setTheme(opt.value)"
          >
            <span class="theme-switch-icon">{{ opt.icon }}</span>
            <span class="theme-switch-text">{{ opt.name }}</span>
          </button>
        </div>

        <button
          @click="settingsStore.toggleSearch()"
          class="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm"
        >
          🔍 搜索
        </button>
        <button
          @click="settingsStore.toggleContacts()"
          class="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm"
        >
          👥 联系人
        </button>
        <button
          @click="settingsStore.toggleSettings()"
          class="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm"
        >
          ⚙️ 设置
        </button>
      </div>
    </nav>

    <!-- 主内容区域 -->
    <div class="flex-1 flex overflow-hidden">
      <!-- 会话列表 -->
      <div class="app-sidebar w-80 bg-white border-r border-gray-200 flex flex-col">
        <Home />
      </div>

      <!-- 聊天区域 -->
      <div class="app-chat flex-1 flex flex-col">
        <Chat />
      </div>
    </div>

    <!-- 搜索面板 -->
    <SearchPanel v-if="settingsStore.showSearch" />

    <!-- 联系人面板 -->
    <ContactsPanel v-if="settingsStore.showContacts" />

    <!-- 设置面板 -->
    <SettingsPanel v-if="settingsStore.showSettings" />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import Home from './views/Home.vue'
import Chat from './views/Chat.vue'
import SearchPanel from './components/SearchPanel.vue'
import ContactsPanel from './components/ContactsPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import { useSettingsStore } from './stores/settings'
import { useSessionStore } from './stores/session'
import { useThemeStore, THEME_LABELS, type ThemeName } from './stores/theme'

const settingsStore = useSettingsStore()
const sessionStore = useSessionStore()
const themeStore = useThemeStore()

const themeOptions: { value: ThemeName; name: string; icon: string; hint: string }[] = [
  { value: 'light', ...THEME_LABELS.light },
  { value: 'grunge', ...THEME_LABELS.grunge },
]

onMounted(async () => {
  themeStore.syncTheme()
  try {
    await sessionStore.loadSessions()
  } catch (error) {
    console.error('初始化加载会话失败:', error)
  }
})
</script>