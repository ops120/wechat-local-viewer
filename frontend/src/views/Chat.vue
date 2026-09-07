<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- 聊天头部 -->
    <div class="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
      <div v-if="sessionStore.currentSession" class="flex items-center space-x-3 flex-1 min-w-0">
        <div class="w-10 h-10 bg-green-500 rounded-lg flex items-center justify-center text-white font-bold shrink-0">
          {{ (sessionStore.currentSession.display_name || '?').charAt(0) }}
        </div>
        <div class="min-w-0">
          <h2 class="font-semibold text-gray-800 truncate">{{ sessionStore.currentSession.display_name }}</h2>
          <p class="text-xs text-gray-500">
            {{ sessionStore.currentSession.message_count || 0 }} 条消息
            <span v-if="sessionStore.totalMessages && sessionStore.totalMessages !== sessionStore.currentSession.message_count">
              (已加载 {{ sessionStore.totalMessages }})
            </span>
          </p>
        </div>
      </div>
      <div v-else class="text-gray-400 py-2 flex-1">
        请选择会话
      </div>

      <button
        v-if="sessionStore.currentSession"
        @click="showExport = !showExport"
        class="ml-2 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded text-sm shrink-0"
      >
        📥 导出
      </button>
    </div>

    <!-- 导出面板 -->
    <div v-if="showExport" class="bg-white border-b border-gray-200 p-3 space-y-2 shrink-0">
      <div class="flex items-center gap-2 text-sm">
        <label class="text-gray-600">日期：</label>
        <input v-model="exportDate" type="date"
          class="px-2 py-1 border border-gray-300 rounded text-sm" />
        <span class="text-gray-400">~</span>
        <input v-model="exportToDate" type="date"
          class="px-2 py-1 border border-gray-300 rounded text-sm" />
        <span class="text-gray-400 text-xs">(留空=同一天)</span>
      </div>
      <div class="flex items-center gap-2 text-sm">
        <label class="text-gray-600">格式：</label>
        <select v-model="exportFormat" class="px-2 py-1 border border-gray-300 rounded text-sm">
          <option value="txt">TXT（人类可读）</option>
          <option value="csv">CSV（Excel 可开）</option>
          <option value="json">JSON（嵌套结构）</option>
          <option value="ndjson">NDJSON（每行一条）</option>
        </select>
        <label class="text-gray-600 ml-2">系统消息：</label>
        <select v-model="exportSystem" class="px-2 py-1 border border-gray-300 rounded text-sm">
          <option value="1">包含</option>
          <option value="0">排除</option>
        </select>
        <button @click="doExport" class="ml-auto px-3 py-1 bg-green-500 text-white rounded text-sm hover:bg-green-600">
          下载
        </button>
        <button @click="showExport = false" class="px-3 py-1 bg-gray-100 rounded text-sm">取消</button>
      </div>
    </div>

    <!-- 消息列表 -->
    <MessageList v-if="sessionStore.currentSession" />

    <!-- LLM 流式面板 -->
    <LLMStream v-if="sessionStore.currentSession" />

    <!-- 空状态 -->
    <div v-if="!sessionStore.currentSession" class="flex-1 flex items-center justify-center">
      <div class="text-center text-gray-400">
        <p class="text-4xl mb-4">💬</p>
        <p>选择一个会话开始浏览</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import MessageList from '../components/MessageList.vue'
import LLMStream from '../components/LLMStream.vue'
import { useSessionStore } from '../stores/session'

const sessionStore = useSessionStore()

// 导出
const showExport = ref(false)
const exportDate = ref(new Date().toISOString().slice(0, 10))
const exportToDate = ref('')
const exportFormat = ref<'json' | 'ndjson' | 'txt' | 'csv'>('txt')
const exportSystem = ref('1')

function doExport() {
  if (!sessionStore.currentSession) return
  const params = new URLSearchParams()
  params.set('session', sessionStore.currentSession.username)
  if (exportToDate.value) {
    params.set('from_date', exportDate.value)
    params.set('to_date', exportToDate.value)
  } else {
    params.set('date', exportDate.value)
  }
  params.set('format', exportFormat.value)
  params.set('include_system', exportSystem.value)
  const url = '/api/export?' + params.toString()
  // 触发下载
  const a = document.createElement('a')
  a.href = url
  a.download = ''  // 用后端 Content-Disposition
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  showExport.value = false
}
</script>