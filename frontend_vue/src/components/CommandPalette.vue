<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="showCommandPalette" class="cmd-overlay" @click.self="showCommandPalette = false">
        <div class="cmd-palette">
          <input ref="searchInput" v-model="query" placeholder="输入命令..." @keydown="onKeydown">
          <div class="cmd-list" v-if="filtered.length > 0">
            <div v-for="(item, i) in filtered" :key="item.id"
                 class="cmd-item" :class="{ active: i === activeIdx }"
                 @click="run(item)" @mouseenter="activeIdx = i">
              <span class="cmd-icon">{{ item.icon }}</span>
              <span class="cmd-label">{{ item.label }}</span>
              <span v-if="item.shortcut" class="cmd-shortcut">{{ item.shortcut }}</span>
            </div>
          </div>
          <div v-else class="cmd-list" style="text-align:center;padding:2rem;color:var(--color-text-muted);font-size:0.85rem">
            无匹配命令
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showCommandPalette } from '../composables/useKeyboard.js'
import { useTheme } from '../composables/useTheme.js'

const router = useRouter()
const { toggle: toggleTheme } = useTheme()

const query = ref('')
const activeIdx = ref(0)
const searchInput = ref(null)

const commands = [
  { id: 'chat', icon: '💬', label: '前往对话', shortcut: 'G C', action: () => router.push('/chat') },
  { id: 'knowledge', icon: '📚', label: '前往知识库', shortcut: 'G K', action: () => router.push('/knowledge') },
  { id: 'profile', icon: '👤', label: '前往个人中心', shortcut: 'G P', action: () => router.push('/profile') },
  { id: 'theme', icon: '🎨', label: '切换主题', shortcut: 'T', action: () => toggleTheme() },
  { id: 'new-chat', icon: '➕', label: '新建对话', action: () => { router.push('/chat'); setTimeout(() => window.__startNewChat?.(), 100) } },
]

const filtered = computed(() => {
  const q = query.value.toLowerCase()
  if (!q) return commands
  return commands.filter(c => c.label.toLowerCase().includes(q))
})

watch(showCommandPalette, (v) => {
  if (v) {
    query.value = ''
    activeIdx.value = 0
    setTimeout(() => searchInput.value?.focus(), 50)
  }
})

function onKeydown(e) {
  if (e.key === 'Escape') { showCommandPalette.value = false; return }
  if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx.value = Math.min(activeIdx.value + 1, filtered.value.length - 1); return }
  if (e.key === 'ArrowUp') { e.preventDefault(); activeIdx.value = Math.max(activeIdx.value - 1, 0); return }
  if (e.key === 'Enter') {
    const item = filtered.value[activeIdx.value]
    if (item) run(item)
  }
}

function run(item) {
  showCommandPalette.value = false
  item.action()
}
</script>

<style scoped>
.fade-enter-active { animation: fadeIn .15s ease; }
.fade-leave-active { animation: fadeIn .15s ease reverse; }
</style>
