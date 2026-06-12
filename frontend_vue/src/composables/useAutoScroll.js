/**
 * Intelligent auto-scroll for chat containers.
 * — Auto-scrolls when user is near the bottom
 * — Shows "scroll to bottom" button when scrolled up
 * — Resumes auto-scroll when user scrolls back to bottom
 */
import { ref, nextTick } from 'vue'

export function useAutoScroll(containerRef) {
  const isNearBottom = ref(true)
  const showScrollBtn = ref(false)

  function onScroll() {
    const el = containerRef.value
    if (!el) return
    const threshold = 120
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight
    isNearBottom.value = dist < threshold
    showScrollBtn.value = dist > threshold
  }

  async function scrollToBottom(force = false) {
    if (!force && !isNearBottom.value) return
    await nextTick()
    const el = containerRef.value
    if (el) el.scrollTop = el.scrollHeight
    showScrollBtn.value = false
  }

  return { isNearBottom, showScrollBtn, onScroll, scrollToBottom }
}
