import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiClient } from '../api/client'
import type { Session, Message } from '../api/types'

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([])
  const currentSession = ref<Session | null>(null)
  const messages = ref<Message[]>([])
  const loading = ref(false)
  const totalMessages = ref(0)
  const searchKeyword = ref('')
  const sessionType = ref('')

  async function loadSessions(page = 1, size = 50) {
    loading.value = true
    try {
      const resp = await apiClient.listSessions({
        type: sessionType.value || undefined,
        keyword: searchKeyword.value || undefined,
        page,
        size,
      })
      sessions.value = resp.items
    } catch (e) {
      console.error('loadSessions error', e)
      sessions.value = []
    } finally {
      loading.value = false
    }
  }

  function setCurrentSession(s: Session) {
    currentSession.value = s
  }

  async function loadMessages(username: string, page = 1, size = 100) {
    if (!currentSession.value || currentSession.value.username !== username) return
    try {
      const resp = await apiClient.listMessages({ session: username, page, size })
      // 后端按时间倒序返回；统一转成正序（旧→新）存储，消息列表底部即最新
      const asc = [...resp.items].reverse()
      if (page === 1) {
        messages.value = asc
      } else {
        messages.value = [...messages.value, ...asc]
      }
      totalMessages.value = resp.total
    } catch (e) {
      console.error('loadMessages error', e)
    }
  }

  async function loadMoreMessages(username: string, beforeTs: number) {
    try {
      const resp = await apiClient.listMessages({ session: username, before_ts: beforeTs, page: 1, size: 100 })
      if (resp.items.length) {
        const asc = [...resp.items].reverse()
        messages.value = [...asc, ...messages.value]
      }
      totalMessages.value = resp.total
    } catch (e) {
      console.error('loadMoreMessages error', e)
    }
  }

  return {
    sessions,
    currentSession,
    messages,
    loading,
    totalMessages,
    searchKeyword,
    sessionType,
    loadSessions,
    setCurrentSession,
    loadMessages,
    loadMoreMessages,
  }
})