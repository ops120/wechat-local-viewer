import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ThemeName = 'light' | 'grunge'

const THEME_KEY = 'wcviewer_theme_v1'

/** 每个皮肤对应挂在 <html> 上的类名（light 不加类，保持默认工具类原样） */
const THEME_CLASS: Record<ThemeName, string> = {
  light: '',
  grunge: 'theme-grunge',
}

const ALL_THEME_CLASSES = Object.values(THEME_CLASS).filter(Boolean)

export const THEME_LABELS: Record<ThemeName, { name: string; icon: string; hint: string }> = {
  light: { name: '原版', icon: '☀️', hint: '默认浅色皮肤' },
  grunge: { name: '垃圾摇滚', icon: '🎸', hint: '1990s Seattle 影印志风格' },
}

function isThemeName(v: unknown): v is ThemeName {
  return v === 'light' || v === 'grunge'
}

export function readStoredTheme(): ThemeName {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return isThemeName(v) ? v : 'light'
  } catch {
    return 'light'
  }
}

/** 支持用 ?theme=grunge / ?theme=light 覆盖（方便分享链接或做截图比对），优先级高于本地记忆 */
export function readInitialTheme(): ThemeName {
  try {
    const q = new URLSearchParams(window.location.search).get('theme')
    if (isThemeName(q)) return q
  } catch {
    /* ignore */
  }
  return readStoredTheme()
}

/** 直接操作 <html>，独立于 Pinia，便于在 app.mount 之前调用（避免首屏闪烁） */
export function applyTheme(name: ThemeName): void {
  const root = document.documentElement
  for (const cls of ALL_THEME_CLASSES) {
    root.classList.toggle(cls, cls === THEME_CLASS[name])
  }
  root.setAttribute('data-theme', name)
}

export const useThemeStore = defineStore('theme', () => {
  const theme = ref<ThemeName>(readInitialTheme())

  function setTheme(name: ThemeName) {
    theme.value = name
    applyTheme(name)
    try {
      localStorage.setItem(THEME_KEY, name)
    } catch (e) {
      console.warn('持久化主题失败', e)
    }
  }

  /** 在原版与垃圾摇滚皮肤之间来回切（快捷键用） */
  function toggleTheme() {
    setTheme(theme.value === 'light' ? 'grunge' : 'light')
  }

  function syncTheme() {
    applyTheme(theme.value)
  }

  return { theme, setTheme, toggleTheme, syncTheme }
})
