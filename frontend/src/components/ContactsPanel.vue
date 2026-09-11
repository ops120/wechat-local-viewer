<template>
  <div class="fixed inset-0 bg-black bg-opacity-50 z-40" @click="close">
    <div
      class="panel-sheet absolute top-20 left-1/2 -translate-x-1/2 w-[700px] max-w-[90vw] max-h-[80vh] bg-white rounded-lg shadow-xl flex flex-col"
      @click.stop
    >
      <!-- 头部 -->
      <div class="p-4 border-b border-gray-200 flex items-center justify-between shrink-0">
        <h3 class="font-semibold text-gray-800">联系人</h3>
        <button @click="close" class="text-gray-400 hover:text-gray-600">✕</button>
      </div>

      <!-- 类型 tabs + 搜索 -->
      <div class="p-3 border-b border-gray-200 shrink-0">
        <div class="flex items-center space-x-2 mb-2">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            @click="activeTab = tab.key; page = 1; load()"
            :class="[
              'px-3 py-1.5 rounded text-sm',
              activeTab === tab.key ? 'bg-green-500 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            ]"
          >
            {{ tab.label }} <span class="text-xs opacity-70">({{ stats[tab.key] || 0 }})</span>
          </button>
        </div>
        <input
          v-model="keyword"
          @input="onSearch"
          type="text"
          placeholder="搜索名字/备注/wxid..."
          class="w-full px-3 py-2 bg-gray-100 rounded text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
        />
      </div>

      <!-- 列表 -->
      <div class="flex-1 overflow-y-auto">
        <div v-if="loading" class="text-center py-8 text-gray-500">加载中...</div>
        <div v-else-if="contacts.length === 0" class="text-center py-8 text-gray-400">无结果</div>
        <div
          v-for="c in contacts"
          :key="c.username"
          class="px-4 py-2 hover:bg-gray-50 border-b border-gray-100 flex items-center space-x-3"
        >
          <div class="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold shrink-0"
               :class="avatarColor(c.local_type)">
            {{ (c.display_name || c.username).charAt(0) }}
          </div>
          <div class="flex-1 min-w-0">
            <div class="font-medium text-gray-800 truncate">{{ c.display_name }}</div>
            <div class="text-xs text-gray-400 truncate font-mono">{{ c.username }}</div>
          </div>
          <span class="text-xs px-2 py-0.5 rounded shrink-0"
                :class="typeBadge(c.local_type)">
            {{ typeLabel(c.local_type) }}
          </span>
        </div>
      </div>

      <!-- 分页 -->
      <div class="p-2 border-t border-gray-200 flex items-center justify-between shrink-0">
        <span class="text-xs text-gray-500">共 {{ total }} 个，当前页 {{ page }}</span>
        <div class="space-x-2">
          <button @click="prev" :disabled="page <= 1" class="px-3 py-1 bg-gray-100 rounded text-sm disabled:opacity-50">上一页</button>
          <button @click="next" :disabled="page * size >= total" class="px-3 py-1 bg-gray-100 rounded text-sm disabled:opacity-50">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const emit = defineEmits<{ close: [] }>()

interface Contact {
  username: string
  type: string
  local_type: number
  display_name: string
  nick_name?: string
  remark?: string
}

const tabs = [
  { key: 'all', label: '全部' },
  { key: 'person', label: '👤 好友' },
  { key: 'room', label: '👥 群聊' },
  { key: 'official', label: '📢 公众号' },
  { key: 'other', label: '⋯ 其它' },
]

const activeTab = ref('all')
const keyword = ref('')
const contacts = ref<Contact[]>([])
const stats = ref<Record<string, number>>({})
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const size = 50
let searchTimer: number

function close() {
  emit('close')
}

async function loadStats() {
  const r = await fetch('/api/contacts/contacts/stats')
  if (r.ok) stats.value = await r.json()
}

async function load() {
  loading.value = true
  try {
    const q = new URLSearchParams()
    if (activeTab.value !== 'all') q.set('type', activeTab.value)
    if (keyword.value.trim()) q.set('keyword', keyword.value.trim())
    q.set('page', String(page.value))
    q.set('size', String(size))
    const r = await fetch('/api/contacts/contacts?' + q)
    if (r.ok) {
      const d = await r.json()
      contacts.value = d.items
      total.value = d.total
    }
  } finally {
    loading.value = false
  }
}

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    page.value = 1
    load()
  }, 300)
}

function prev() {
  if (page.value > 1) {
    page.value--
    load()
  }
}

function next() {
  if (page.value * size < total.value) {
    page.value++
    load()
  }
}

function avatarColor(t: number): string {
  if (t === 1 || t === 4) return 'bg-green-500'
  if (t === 2) return 'bg-blue-500'
  if (t === 3) return 'bg-orange-500'
  return 'bg-gray-400'
}

function typeBadge(t: number): string {
  if (t === 1 || t === 4) return 'bg-green-50 text-green-700'
  if (t === 2) return 'bg-blue-50 text-blue-700'
  if (t === 3) return 'bg-orange-50 text-orange-700'
  return 'bg-gray-100 text-gray-600'
}

function typeLabel(t: number): string {
  if (t === 1 || t === 4) return '好友'
  if (t === 2) return '群聊'
  if (t === 3) return '公众号'
  if (t === 5) return '企业'
  if (t === 6) return '群通知'
  return '其它'
}

onMounted(async () => {
  await loadStats()
  await load()
})
</script>