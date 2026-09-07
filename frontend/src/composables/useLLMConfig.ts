import type { LLMConfig } from '../api/types'

const KEY = 'wcviewer_llm_config_v1'

const DEFAULT: LLMConfig = {
  base_url: 'https://api.deepseek.com/v1',
  api_key: '',
  model: 'deepseek-chat',
}

export function useLLMConfig() {
  function getConfig(): LLMConfig {
    try {
      const raw = localStorage.getItem(KEY)
      if (!raw) return { ...DEFAULT }
      return { ...DEFAULT, ...JSON.parse(raw) }
    } catch {
      return { ...DEFAULT }
    }
  }

  function setConfig(cfg: LLMConfig) {
    localStorage.setItem(KEY, JSON.stringify(cfg))
  }

  return { getConfig, setConfig }
}