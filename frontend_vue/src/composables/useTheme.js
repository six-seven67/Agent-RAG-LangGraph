/**
 * Dark/Light theme composable
 * — Persists to localStorage
 * — Defaults to system preference
 * — Applies data-theme attribute to <html>
 */
import { ref, watchEffect } from 'vue'

const THEME_KEY = 'rag_theme'
const theme = ref(localStorage.getItem(THEME_KEY) || 'auto')

function resolveTheme() {
  if (theme.value === 'dark') return 'dark'
  if (theme.value === 'light') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyTheme() {
  document.documentElement.setAttribute('data-theme', resolveTheme())
}

export function useTheme() {
  // Apply immediately + on change
  watchEffect(applyTheme)

  // Listen for system changes when in auto mode
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (theme.value === 'auto') applyTheme()
  })

  /** Cycle: auto → dark → light → auto */
  function toggle() {
    const map = { auto: 'dark', dark: 'light', light: 'auto' }
    theme.value = map[theme.value] || 'auto'
    localStorage.setItem(THEME_KEY, theme.value)
  }

  /** Set explicit theme */
  function setTheme(t) {
    theme.value = t
    localStorage.setItem(THEME_KEY, t)
  }

  return { theme, resolvedTheme: () => resolveTheme(), toggle, setTheme }
}
