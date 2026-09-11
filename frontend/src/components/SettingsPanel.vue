<template>
  <div class="fixed inset-0 bg-black bg-opacity-50 z-40" @click="close">
    <div
      class="panel-sheet absolute top-20 right-4 w-[500px] max-w-[90vw] bg-white rounded-lg shadow-xl"
      @click.stop
    >
      <!-- 设置头部 -->
      <div class="p-4 border-b border-gray-200 flex items-center justify-between">
        <h3 class="font-semibold text-gray-800">设置</h3>
        <button
          @click="close"
          class="text-gray-400 hover:text-gray-600"
        >
          ✕
        </button>
      </div>

      <!-- LLM 配置 -->
      <div class="p-4 space-y-4">
        <h4 class="text-sm font-medium text-gray-700">LLM 配置</h4>

        <div>
          <label class="block text-xs text-gray-500 mb-1">Base URL</label>
          <input
            v-model="localConfig.base_url"
            type="text"
            placeholder="例如: http://localhost:11434/v1"
            class="w-full px-3 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
          <p class="text-xs text-gray-400 mt-1">支持 OpenAI / DeepSeek / Ollama 等兼容协议</p>
        </div>

        <div>
          <label class="block text-xs text-gray-500 mb-1">API Key</label>
          <input
            v-model="localConfig.api_key"
            type="password"
            placeholder="输入 API Key"
            class="w-full px-3 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </div>

        <div>
          <label class="block text-xs text-gray-500 mb-1">Model</label>
          <input
            v-model="localConfig.model"
            type="text"
            placeholder="例如: qwen2.5:7b / gpt-4o-mini"
            class="w-full px-3 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </div>

        <!-- 常见配置示例 -->
        <div class="bg-gray-50 rounded-lg p-3 space-y-2">
          <p class="text-xs font-medium text-gray-600">常见配置示例：</p>
          <div class="text-xs text-gray-500 space-y-1">
            <p>Ollama: http://localhost:11434/v1 / ollama / qwen2.5:7b</p>
            <p>DeepSeek: https://api.deepseek.com/v1 / your-key / deepseek-chat</p>
            <p>OpenAI: https://api.openai.com/v1 / your-key / gpt-4o-mini</p>
          </div>
        </div>

        <!-- 保存按钮 -->
        <div class="flex justify-end space-x-2 pt-4">
          <button
            @click="close"
            class="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm"
          >
            取消
          </button>
          <button
            @click="saveConfig"
            class="px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg text-sm font-medium"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../stores/settings'
import type { LLMConfig } from '../api/types'

const settingsStore = useSettingsStore()
const localConfig = ref<LLMConfig>({
  base_url: '',
  api_key: '',
  model: ''
})

onMounted(() => {
  localConfig.value = { ...settingsStore.llmConfig }
})

function saveConfig() {
  settingsStore.saveLLMConfig(localConfig.value)
  close()
}

function close() {
  settingsStore.showSettings = false
}
</script>