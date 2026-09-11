<template>
  <div ref="scrollerRef" class="chat-scroller flex-1 overflow-y-auto bg-gray-100" @scroll="onScroll">
    <div class="py-2">
      <div v-if="loadingMore" class="text-center py-2 text-gray-400 text-xs">加载中...</div>
      <div v-else-if="messages.length < total && messages.length > 0" class="text-center py-2 text-gray-400 text-xs">↑ 滚动加载更多</div>
      <div v-for="m in messages" :key="m.id">
        <MessageBubble :message="m" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MessageBubble from './MessageBubble.vue'
import { useSessionStore } from '../stores/session'

const sessionStore = useSessionStore()
const scrollerRef = ref<HTMLElement>()
const loadingMore = ref(false)

const messages = computed(() => sessionStore.messages)
const total = computed(() => sessionStore.totalMessages)

async function onScroll(e: Event) {
  const el = e.target as HTMLElement
  // 滚到顶部时加载更早消息
  if (el.scrollTop < 50 && !loadingMore.value && sessionStore.currentSession && messages.value.length < total.value) {
    const oldestMessage = messages.value[0]
    if (!oldestMessage) return
    loadingMore.value = true
    try {
      await sessionStore.loadMoreMessages(
        sessionStore.currentSession.username,
        oldestMessage.create_time
      )
    } finally {
      loadingMore.value = false
    }
  }
}

// 切换会话时滚到底部（最新消息）
watch(() => sessionStore.currentSession?.username, () => {
  setTimeout(() => {
    if (scrollerRef.value) scrollerRef.value.scrollTop = scrollerRef.value.scrollHeight
  }, 50)
})
</script>

<style scoped>
.scroller {
  height: 100%;
}
</style>