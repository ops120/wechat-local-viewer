<template>
  <div class="message-bubble px-4 py-2" :class="message.is_self === 1 ? 'flex justify-end bubble-self' : 'flex justify-start bubble-other'">
    <!-- 头像 -->
    <div
      v-if="message.is_self !== 1"
      class="avatar w-8 h-8 bg-gray-400 rounded-lg flex items-center justify-center text-white text-sm font-bold shrink-0"
    >
      {{ (message.sender_display_name || '未知').charAt(0) }}
    </div>

    <!-- 消息内容 -->
    <div
      class="bubble max-w-[60%] mx-2 px-3 py-2 rounded-lg shadow-sm"
      :class="message.is_self === 1 ? 'bg-green-200' : 'bg-white'"
    >
      <!-- 发送者名称 -->
      <div v-if="message.is_self !== 1" class="text-xs text-gray-500 mb-1">
        {{ message.sender_display_name || '未知' }}
      </div>

      <!-- 文本消息 -->
      <div v-if="message.local_type === 1" class="text-sm break-words whitespace-pre-wrap">
        {{ message.content }}
      </div>

      <!-- 图片消息 -->
      <div v-else-if="message.local_type === 3 && message.media_md5">
        <img
          v-if="message.media_url"
          :src="message.media_url"
          :alt="message.content || '图片'"
          class="max-w-full rounded-lg cursor-pointer"
          loading="lazy"
          @click="showLightbox = true"
        />
        <div v-else class="bg-gray-100 border border-gray-300 text-gray-500 px-3 py-4 rounded text-center text-xs">
          🖼️ [图片]<br>
          <span class="font-mono text-[10px]">{{ message.media_md5 }}</span><br>
          <span class="text-[10px] text-gray-400">未在 .images 找到本地文件</span>
        </div>
      </div>

      <!-- 语音消息 -->
      <div v-else-if="message.local_type === 34" class="flex items-center space-x-2">
        <span class="text-2xl">🎵</span>
        <span class="text-sm">语音消息</span>
      </div>

      <!-- 视频消息 -->
      <div v-else-if="message.local_type === 43 && message.media_md5">
        <video
          v-if="message.media_url"
          :src="message.media_url"
          controls
          class="max-w-full rounded-lg"
        ></video>
        <div v-else class="bg-gray-100 px-3 py-2 rounded text-sm">🎥 [视频]（未找到本地文件）</div>
      </div>

      <!-- 表情消息 -->
      <div v-else-if="message.local_type === 47 && message.media_md5">
        <img
          v-if="message.media_url"
          :src="message.media_url"
          alt="表情"
          class="max-w-[120px] rounded-lg"
          loading="lazy"
        />
        <div v-else class="bg-gray-100 px-3 py-2 rounded text-sm">😀 [表情]（未找到本地文件）</div>
      </div>

      <!-- 链接/应用消息（ETL 已分类为 "[链接] 标题" 等文本） -->
      <div v-else-if="message.local_type === 49" class="text-sm break-words whitespace-pre-wrap">
        {{ message.content || '🔗 链接消息' }}
      </div>

      <!-- 其他类型：展示 ETL 分类文本（[文件]/[红包]/[引用]...），没有则显示原始类型 -->
      <div v-else class="text-sm text-gray-500 break-words">
        {{ message.content || `[消息类型: ${message.local_type}]` }}
      </div>

      <!-- 时间 -->
      <div class="text-xs text-gray-400 mt-1 text-right">
        {{ formatTime(message.create_time) }}
      </div>
    </div>

    <!-- 自己的头像 -->
    <div
      v-if="message.is_self === 1"
      class="avatar w-8 h-8 bg-green-500 rounded-lg flex items-center justify-center text-white text-sm font-bold shrink-0"
    >
      我
    </div>

    <!-- 图片预览 -->
    <MediaLightbox
      v-if="showLightbox && message.media_url"
      :src="message.media_url"
      @close="showLightbox = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import MediaLightbox from './MediaLightbox.vue'
import type { Message } from '../api/types'

const props = defineProps<{
  message: Message
}>()

const showLightbox = ref(false)

function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>