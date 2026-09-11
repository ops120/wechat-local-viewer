<template>
  <div
    @click="$emit('click')"
    class="flex items-center px-3 py-3 cursor-pointer transition-colors"
    :class="active ? 'bg-green-50 border-l-4 border-green-500' : 'hover:bg-gray-50'"
    :title="`${session.display_name}\n${session.username}`"
  >
    <!-- 头像 -->
    <div
      class="avatar w-12 h-12 rounded-lg flex items-center justify-center text-white font-bold text-lg shrink-0"
      :class="isRoom ? 'bg-green-500' : isGh ? 'bg-blue-400' : 'bg-gray-300'"
    >
      {{ session.display_name.charAt(0) }}
    </div>

    <!-- 信息 -->
    <div class="ml-3 flex-1 min-w-0">
      <div class="flex items-center justify-between">
        <h3 class="font-medium text-gray-800 truncate">{{ session.display_name }}</h3>
        <span class="text-xs text-gray-400 shrink-0 ml-2">{{ formatTime(session.last_time) }}</span>
      </div>
      <div class="flex items-center justify-between mt-1">
        <p class="text-sm text-gray-500 truncate">
          <span
            v-if="isRoom || isGh"
            class="inline-block align-middle mr-1 px-1.5 py-px rounded text-[10px] leading-4"
            :class="isRoom ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'"
          >{{ isRoom ? '群聊' : '公众号' }}</span>{{ session.last_msg_preview || '暂无消息' }}
        </p>
        <span v-if="session.message_count > 0" class="text-xs text-gray-400 shrink-0 ml-2">
          {{ session.message_count }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { defineProps, defineEmits, computed } from 'vue'
import type { Session } from '../api/types'

const props = defineProps<{
  session: Session
  active: boolean
}>()

defineEmits<{
  click: []
}>()

// 群聊/公众号按 username 后缀判定（与后端口径一致）
const isRoom = computed(() =>
  props.session.type === 'room' ||
  props.session.username.includes('@chatroom') ||
  props.session.username.includes('@openim')
)
const isGh = computed(() =>
  !isRoom.value &&
  (props.session.username.startsWith('gh_') || props.session.username.startsWith('gh.'))
)

function formatTime(timestamp?: number): string {
  if (!timestamp) return ''

  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`

  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>
