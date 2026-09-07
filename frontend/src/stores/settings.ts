import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LLMConfig } from '../api/types'

const LLM_KEY = 'wcviewer_llm_config_v1'

const DEFAULT_LLM: LLMConfig = {
  base_url: '',
  api_key: '',
  model: '',
}

function loadLLMConfig(): LLMConfig {
  try {
    const raw = localStorage.getItem(LLM_KEY)
    if (!raw) return { ...DEFAULT_LLM }
    return { ...DEFAULT_LLM, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_LLM }
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const showSearch = ref(false)
  const showSettings = ref(false)
  const showContacts = ref(false)
  const llmConfig = ref<LLMConfig>(loadLLMConfig())

  function toggleSearch() {
    showSearch.value = !showSearch.value
    if (showSearch.value) {
      showSettings.value = false
      showContacts.value = false
    }
  }

  function toggleSettings() {
    showSettings.value = !showSettings.value
    if (showSettings.value) {
      showSearch.value = false
      showContacts.value = false
    }
  }

  function toggleContacts() {
    showContacts.value = !showContacts.value
    if (showContacts.value) {
      showSearch.value = false
      showSettings.value = false
    }
  }

  function saveLLMConfig(cfg: LLMConfig) {
    llmConfig.value = { ...cfg }
    try {
      localStorage.setItem(LLM_KEY, JSON.stringify(cfg))
    } catch (e) {
      console.warn('saveLLMConfig failed', e)
    }
  }

  return { showSearch, showSettings, showContacts, llmConfig, toggleSearch, toggleSettings, toggleContacts, saveLLMConfig }
})