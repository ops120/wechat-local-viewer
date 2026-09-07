<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- 搜索框 -->
    <div class="p-3 border-b border-gray-200">
      <input
        v-model="sessionStore.searchKeyword"
        @input="handleSearch"
        type="text"
        placeholder="搜索会话..."
        class="w-full px-3 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
      />
      <select
        v-model="sessionStore.sessionType"
        @change="handleSearch"
        class="mt-2 w-full px-3 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none"
      >
        <option value="">全部类型 ({{ stats.total || 0 }})</option>
        <option value="c2c">单聊 ({{ stats.c2c || 0 }})</option>
        <option value="room">群聊 ({{ stats.room || 0 }})</option>
        <option value="gh">公众号 ({{ stats.gh || 0 }})</option>
        <option value="notify">系统通知 ({{ stats.notify || 0 }})</option>
      </select>
    </div>

    <!-- 会话列表 -->
    <div class="flex-1 overflow-y-auto">
      <div v-if="searchResults" class="px-3 py-1 text-xs text-gray-500 bg-blue-50">
        🔍 搜索结果 第 {{ searchOffset + 1 }}-{{ searchOffset + searchResults.length }} 条 / 共 {{ searchTotal }} 个
        <button @click="clearSearch" class="ml-2 text-blue-600 hover:underline">清除</button>
      </div>
      <SessionItem
        v-for="session in displaySessions"
        :key="session.username"
        :session="session"
        :active="sessionStore.currentSession?.username === session.username"
        @click="selectSession(session)"
      />

      <div v-if="searchResults !== null && searchOffset + searchResults.length < searchTotal" class="text-center pb-3">
        <button
          @click="loadMoreSearch"
          :disabled="searchLoading"
          class="px-4 py-1.5 bg-gray-100 hover:bg-gray-200 rounded text-xs text-gray-600"
        >
          {{ searchLoading ? '加载中...' : `加载更多（还有 ${searchTotal - searchOffset - searchResults.length} 个）` }}
        </button>
      </div>

      <div v-if="sessionStore.loading" class="text-center py-4 text-gray-500">
        加载中...
      </div>

      <div v-if="!sessionStore.loading && searchResults === null && sessionStore.sessions.length === 0" class="text-center py-8 text-gray-400">
        暂无会话数据
      </div>

      <div v-if="searchResults !== null && searchResults.length === 0" class="text-center py-8 text-gray-400">
        没有匹配的结果
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import SessionItem from '../components/SessionItem.vue'
import { useSessionStore } from '../stores/session'
import type { Session } from '../api/types'

const router = useRouter()
const sessionStore = useSessionStore()
const stats = ref<Record<string, number>>({})
const searchResults = ref<Session[] | null>(null)
const searchTotal = ref(0)
const searchOffset = ref(0)
const searchLoading = ref(false)
const SEARCH_PAGE_SIZE = 50
let searchTimeout: number

async function loadStats() {
  const r = await fetch('/api/sessions/stats')
  if (r.ok) stats.value = await r.json()
}

async function fetchSearchPage(page: number) {
  const kw = sessionStore.searchKeyword.trim()
  if (!kw) return
  searchLoading.value = true
  try {
    const r = await fetch(`/api/sessions/search?q=${encodeURIComponent(kw)}&page=${page}&size=${SEARCH_PAGE_SIZE}`)
    if (r.ok) {
      const d = await r.json()
      searchTotal.value = d.total ?? d.items.length
      searchOffset.value = (page - 1) * SEARCH_PAGE_SIZE
      if (page === 1) {
        searchResults.value = d.items
      } else {
        searchResults.value = [...(searchResults.value || []), ...d.items]
      }
    }
  } finally {
    searchLoading.value = false
  }
}

function handleSearch() {
  clearTimeout(searchTimeout)
  searchTimeout = window.setTimeout(async () => {
    if (!sessionStore.searchKeyword.trim()) {
      searchResults.value = null
      searchTotal.value = 0
      // 无关键词时按当前类型筛选重新加载会话列表（否则类型下拉切了也不生效）
      await sessionStore.loadSessions(1)
      return
    }
    await fetchSearchPage(1)
  }, 300)
}

async function loadMoreSearch() {
  await fetchSearchPage(Math.floor(searchOffset.value / SEARCH_PAGE_SIZE) + 2)
}

function clearSearch() {
  searchResults.value = null
  searchTotal.value = 0
  sessionStore.searchKeyword = ''
}

const displaySessions = computed(() =>
  searchResults.value !== null ? searchResults.value : sessionStore.sessions
)

async function selectSession(session: Session) {
  sessionStore.setCurrentSession(session)
  await sessionStore.loadMessages(session.username)
  clearSearch()
  router.push(`/c/${session.username}`)
}

onMounted(async () => {
  await loadStats()
})
</script>