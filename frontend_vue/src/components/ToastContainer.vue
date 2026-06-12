<template>
  <Teleport to="body">
    <div id="toast-container" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="t in toast.toasts" :key="t.id" class="toast" :class="'toast-' + t.type">
          <span class="toast-icon">{{ icon(t.type) }}</span>
          <span>{{ t.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToastStore } from '../stores/toast.js'
const toast = useToastStore()
function icon(type) {
  const map = { success: '✅', error: '❌', info: 'ℹ️' }
  return map[type] || 'ℹ️'
}
</script>
