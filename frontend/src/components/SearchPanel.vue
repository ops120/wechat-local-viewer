<template>
  <div class="fixed inset-0 bg-black bg-opacity-50 z-40" @click="close">
    <div
      class="panel-sheet absolute top-20 left-1/2 -translate-x-1/2 w-[600px] max-w-[90vw] bg-white rounded-lg shadow-xl"
      @click.stop
    >
      <!-- 搜索输入 -->
      <div class="p-4 border-b border-gray-200">
        <input
          v-model="searchStore.keyword"
          @input="handleSearch"
          @keydown.enter="handleSearch"
          type="text"
          placeholder="搜索消息内容..."
          class="w-full px-4 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          autofocus
        />
      </div>

      <!-- 搜索结果 -->
      <div class="max-h-[60vh] overflow-y-auto">
        <div v-if="searchStore.searching" class="text-center py-8 text-gray-500">
          搜索中...
        </div>

        <div v-else-if="searchStore.searchResults.length === 0 && searchStore.keyword" class="text-center py-8 text-gray-400">
          没有找到相关消息
        </div>

        <div
          v-for="result in searchStore.searchResults"
          :key="result.id"
          class="px-4 py-3 hover:bg-gray-50 cursor-pointer border-b border-gray-100"
          @click="jumpToMessage(result)"
        >
          <div class="flex items-center justify-between mb-1">
            <span class="text-xs text-gray-500">{{ result.sender_display_name || '未知' }}</span>
            <span class="text-xs text-gray-400">{{ formatTime(result.create_time) }}</span>
          </div>
          <p class="text-sm text-gray-700 line-clamp-2">{{ result.snippet || result.content }}</p>
        </div>
      </div>

      <!-- 关闭按钮 -->
      <div class="p-3 border-t border-gray-200 text-right">
        <button
          @click="close"
          class="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm"
        >
          关闭
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useSearchStore } from '../stores/search'
import { useSettingsStore } from '../stores/settings'
import { useSessionStore } from '../stores/session'
import type { SearchHit } from '../api/types'

const searchStore = useSearchStore()
const settingsStore = useSettingsStore()
const sessionStore = useSessionStore()

let searchTimeout: number

function handleSearch() {
  clearTimeout(searchTimeout)
  searchTimeout = window.setTimeout(() => {
    searchStore.doSearch()
  }, 300)
}

function close() {
  settingsStore.toggleSearch()
  searchStore.keyword = ''
  searchStore.searchResults = []
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

async function jumpToMessage(result: SearchHit) {
  close()

  // 切换到对应会话
  if (sessionStore.currentSession?.username !== result.session_username) {
    const session = sessionStore.sessions.find(s => s.username === result.session_username)
    if (session) {
      sessionStore.setCurrentSession(session)
      await sessionStore.loadMessages(result.session_username)
    }
  }

  console.log('跳转到消息:', result.id)
}
</script>