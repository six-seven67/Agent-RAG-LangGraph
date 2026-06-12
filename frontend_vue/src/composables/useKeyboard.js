/**
 * Global keyboard shortcuts
 * — Ctrl+K / Cmd+K: toggle command palette
 * — / : focus chat input (when not already focused)
 * — Escape: close modals / blur
 */
import { ref, onMounted, onUnmounted } from 'vue'

export const showCommandPalette = ref(false)
export const chatInputFocus = ref(0) // increment to trigger focus

export function useKeyboard() {
  function handler(e) {
    // Ctrl+K / Cmd+K → command palette
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault()
      showCommandPalette.value = !showCommandPalette.value
      return
    }

    // Escape → close palette
    if (e.key === 'Escape') {
      if (showCommandPalette.value) {
        showCommandPalette.value = false
        return
      }
    }

    // / → focus chat input (only if no input/textarea focused and not in an input)
    if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
      const tag = document.activeElement?.tagName?.toLowerCase()
      if (tag !== 'input' && tag !== 'textarea' && !document.activeElement?.isContentEditable) {
        e.preventDefault()
        chatInputFocus.value++
      }
    }
  }

  onMounted(() => document.addEventListener('keydown', handler))
  onUnmounted(() => document.removeEventListener('keydown', handler))
}
