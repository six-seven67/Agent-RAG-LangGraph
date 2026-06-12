<template>
  <nav id="navbar">
    <div class="nav-left">
      <button class="hamburger" @click="$emit('toggleSidebar')" title="菜单">
        <span></span><span></span><span></span>
      </button>
      <span class="nav-brand">🤖 Agent 智能客服</span>
    </div>

    <div class="nav-center">
      <router-link to="/chat" class="nav-link" active-class="active">💬 对话</router-link>
      <router-link to="/knowledge" class="nav-link" active-class="active">📚 知识库</router-link>
      <router-link to="/profile" class="nav-link" active-class="active">👤 个人中心</router-link>
    </div>

    <div class="nav-right">
      <!-- Keyboard shortcut hint -->
      <span class="shortcut-hint" @click="showCommandPalette = true" title="命令面板 (Ctrl+K)">
        <kbd>Ctrl</kbd>+<kbd>K</kbd>
      </span>

      <!-- Theme toggle -->
      <button class="theme-toggle" :title="'主题：' + themeLabel" @click="toggleTheme">
        {{ themeIcon }}
      </button>

      <!-- User menu -->
      <div class="user-menu-wrap" ref="menuWrap">
        <button class="user-menu-btn" @click="menuOpen = !menuOpen">
          <span class="avatar">{{ initial }}</span>
          <span class="user-name">{{ username }}</span>
          <span class="menu-arrow">▾</span>
        </button>
        <div v-if="menuOpen" class="user-dropdown" @mouseleave="menuOpen = false">
          <button class="dropdown-item" @click="goProfile">
            👤 个人中心
          </button>
          <div class="dropdown-divider"></div>
          <button class="dropdown-item danger" @click="handleLogout">
            🚪 退出登录
          </button>
        </div>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToastStore } from '../stores/toast.js'
import { useTheme } from '../composables/useTheme.js'
import { showCommandPalette } from '../composables/useKeyboard.js'
import { logout, getMe } from '../api/index.js'

defineEmits(['toggleSidebar'])

const router = useRouter()
const toast = useToastStore()
const { theme, toggle: toggleTheme } = useTheme()

const menuOpen = ref(false)
const username = ref('')
const menuWrap = ref(null)

const initial = computed(() => (username.value || '我').charAt(0).toUpperCase())

const themeIcon = computed(() => {
  const map = { auto: '🖥️', dark: '🌙', light: '☀️' }
  return map[theme.value] || '🖥️'
})

const themeLabel = computed(() => {
  const map = { auto: '跟随系统', dark: '暗色', light: '亮色' }
  return map[theme.value] || '跟随系统'
})

onMounted(async () => {
  try {
    const data = await getMe()
    username.value = data.username || ''
  } catch { /* ignore */ }
})

function goProfile() {
  menuOpen.value = false
  router.push('/profile')
}

async function handleLogout() {
  menuOpen.value = false
  if (!confirm('确定要退出登录吗？')) return
  try { await logout() } catch { /* ignore */ }
  toast.info('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
.shortcut-hint {
  display: flex; align-items: center; gap: 2px;
  font-size: 0.7rem; color: var(--color-text-muted);
  cursor: pointer; padding: 0.25rem 0.5rem;
  border-radius: var(--radius-xs); transition: all var(--transition);
  user-select: none;
}
.shortcut-hint:hover { background: var(--color-bg); color: var(--color-text-secondary); }
.shortcut-hint kbd {
  font-family: 'SF Mono', Consolas, monospace;
  padding: 0.12rem 0.35rem; border-radius: 3px;
  background: var(--color-bg); border: 1px solid var(--color-border);
  font-size: 0.68rem;
}

.user-name {
  max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.menu-arrow { font-size: 0.6rem; color: var(--color-text-muted); }

@media (max-width: 720px) {
  .shortcut-hint { display: none; }
  .user-name { display: none; }
}
</style>
