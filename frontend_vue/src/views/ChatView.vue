<template>
  <div class="chat-page">
    <!-- Mobile sidebar overlay -->
    <div class="sidebar-overlay" :class="{ visible: sidebarOpen }" @click="$emit('closeSidebar')"></div>

    <!-- Sidebar -->
    <aside class="chat-sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-header">
        <button class="btn btn-primary" @click="startNewChat">➕ 新对话</button>
      </div>
      <div class="session-list">
        <!-- Skeleton loading -->
        <template v-if="sessionsLoading">
          <div v-for="n in 4" :key="'sk-'+n" class="skeleton-row">
            <div class="skeleton sk-circle"></div>
            <div class="skeleton sk-line"></div>
          </div>
        </template>

        <div v-else-if="sessions.length === 0" class="session-list-empty">
          <span class="empty-icon">💬</span>
          暂无历史会话<br>开启一段新对话吧 ✨
        </div>

        <div v-for="s in sortedSessions" :key="s.session_id"
             class="session-item" :class="{ active: s.session_id === currentSessionId }"
             @click="loadSession(s.session_id)">
          <span class="session-icon">{{ getSessionIcon(s.title || s.session_id) }}</span>
          <span class="session-info">
            <span class="session-title" :title="s.title || s.session_id">
              {{ s.title || (s.session_id ? s.session_id.substring(0, 8) + '...' : '未知会话') }}
            </span>
            <span class="session-time">{{ formatRelativeTime(s.last_active) }}</span>
          </span>
          <button class="session-delete" @click.stop="handleDeleteSession(s.session_id)" title="删除">🗑</button>
        </div>
      </div>
    </aside>

    <!-- Main Chat Area -->
    <div class="chat-main" @click="sidebarOpen && $emit('closeSidebar')">
      <div class="chat-messages" ref="messagesEl" @scroll="autoScroll.onScroll">
        <!-- Welcome / Empty state -->
        <div v-if="messages.length === 0" class="chat-welcome">
          <div class="welcome-icon">🤖</div>
          <h2>有什么可以帮您？</h2>
          <p>我是您的 AI 智能助手，可以帮您查询知识库、解答疑问。试试问一个产品相关问题吧！</p>
          <div class="shortcut-hints">
            <span class="shortcut-kbd">Enter 发送</span>
            <span class="shortcut-kbd">Shift+Enter 换行</span>
            <span class="shortcut-kbd">/ 聚焦输入</span>
            <span class="shortcut-kbd">Ctrl+K 命令面板</span>
          </div>
        </div>

        <template v-for="(m, i) in messages" :key="i">
          <div class="message-row" :class="m.role">
            <div class="message-avatar" :class="m.role">{{ m.role === 'user' ? '👤' : '🤖' }}</div>
            <div style="position:relative;max-width:100%">
              <div class="message-bubble" :id="'msg-' + i" v-html="renderBubble(m, i)"></div>
              <!-- Message actions -->
              <div class="message-actions">
                <button class="msg-action-btn" :class="{ copied: copiedIdx === i }"
                        @click="copyMessage(i, m)" title="复制">
                  {{ copiedIdx === i ? '✓' : '📋' }}
                </button>
              </div>
              <div v-if="m.created_at" class="message-time">{{ formatTime(m.created_at) }}</div>
            </div>
          </div>

          <!-- Tool status cards after latest AI message -->
          <template v-if="m.role === 'assistant' && i === messages.length - 1">
            <div v-for="(ts, ti) in toolStatuses" :key="'ts-' + ti"
                 class="tool-status" :class="ts.cls">
              <span class="tool-dot"></span>
              <span>{{ ts.icon }} {{ ts.label }}</span>
            </div>
          </template>
        </template>

        <!-- Scroll to bottom button -->
        <button v-if="autoScroll.showScrollBtn.value" class="scroll-bottom-btn"
                @click="autoScroll.scrollToBottom(true)" title="回到底部">
          ↓
        </button>
      </div>

      <!-- Input area -->
      <div class="chat-input-area">
        <div class="chat-input-row">
          <textarea v-model="inputText" :placeholder="placeholderText"
                    rows="1" maxlength="2000"
                    @input="onInputResize"
                    @keydown="onInputKeydown"
                    ref="inputEl"></textarea>
          <button class="btn btn-primary" :disabled="!inputText.trim() || isStreaming"
                  @click="handleSend">
            {{ isStreaming ? '…' : '发送' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useToastStore } from '../stores/toast.js'
import { useAutoScroll } from '../composables/useAutoScroll.js'
import { chatInputFocus } from '../composables/useKeyboard.js'
import * as API from '../api/index.js'
import { formatMarkdown, formatAnswerOutput, copyCodeBlock } from '../utils/markdown.js'
import { formatTime, formatRelativeTime, getSessionIcon, getToolLabel, getToolDoneLabel, escapeHtml, copyToClipboard } from '../utils/helpers.js'

const props = defineProps({ sidebarOpen: Boolean })
defineEmits(['closeSidebar'])

const toast = useToastStore()

const currentSessionId = ref(null)
const messages = ref([])
const toolStatuses = ref([])
const sessions = ref([])
const sessionsLoading = ref(true)
const inputText = ref('')
const isStreaming = ref(false)
const copiedIdx = ref(-1)

const messagesEl = ref(null)
const inputEl = ref(null)

const autoScroll = useAutoScroll(messagesEl)

const placeholderText = computed(() => isStreaming.value ? 'AI 正在回复中...' : '输入您的问题，按 Enter 发送...')

const sortedSessions = computed(() =>
  [...sessions.value].sort((a, b) => new Date(b.last_active) - new Date(a.last_active))
)

// Expose startNewChat for command palette
if (typeof window !== 'undefined') window.__startNewChat = startNewChat

onMounted(() => {
  loadSessions()
  inputEl.value?.focus()
})

// Listen for keyboard shortcut to focus input
watch(chatInputFocus, () => {
  inputEl.value?.focus()
})

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const data = await API.getSessions()
    sessions.value = data.sessions || []
  } catch { /* ignore */ }
  finally { sessionsLoading.value = false }
}

function startNewChat() {
  currentSessionId.value = null
  messages.value = []
  toolStatuses.value = []
  inputText.value = ''
  inputEl.value?.focus()
  loadSessions()
}

async function loadSession(sid) {
  currentSessionId.value = sid
  messages.value = []
  toolStatuses.value = []
  try {
    const data = await API.getHistory(sid)
    messages.value = data.messages || []
    await nextTick(); autoScroll.scrollToBottom(true)
    loadSessions()
  } catch (err) {
    toast.error(err.message)
  }
}

async function handleDeleteSession(sid) {
  if (!confirm('确定删除此会话？')) return
  try {
    await API.deleteSession(sid)
    if (currentSessionId.value === sid) startNewChat()
    toast.success('会话已删除')
    loadSessions()
  } catch (err) {
    toast.error(err.message)
  }
}

async function copyMessage(i, m) {
  const text = m.content || ''
  await copyToClipboard(text)
  copiedIdx.value = i
  setTimeout(() => { copiedIdx.value = -1 }, 2000)
}

function renderBubble(m, i) {
  if (m.role === 'user') return m.content ? escapeHtml(m.content) : ''
  if (!m.content) return '<span class="typing-indicator"><span></span><span></span><span></span></span>'
  return formatMarkdown(m.content)
}

function onInputResize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 150) + 'px'
}

function onInputKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

async function handleSend() {
  const query = inputText.value.trim()
  if (!query || isStreaming.value) return

  messages.value.push({ role: 'user', content: query, created_at: new Date().toISOString() })
  inputText.value = ''
  isStreaming.value = true
  toolStatuses.value = []

  messages.value.push({ role: 'assistant', content: '', created_at: new Date().toISOString() })
  const aiIdx = messages.value.length - 1
  autoScroll.scrollToBottom(true)

  await API.sendMessageStream(query, currentSessionId.value, {
    onToken(_token, fullAnswer) {
      messages.value[aiIdx].content = fullAnswer
      autoScroll.scrollToBottom()
    },
    onToolStart(toolData) {
      const tools = toolData.tools || []
      tools.forEach(t => {
        toolStatuses.value.push({
          cls: 'tool-start', icon: '⏳',
          label: getToolLabel(t.name || 'unknown'),
        })
      })
      autoScroll.scrollToBottom()
    },
    onToolEnd(toolData) {
      const name = toolData.tool || 'unknown'
      const idx = toolStatuses.value.findLastIndex(ts => ts.cls === 'tool-start')
      if (idx >= 0) {
        toolStatuses.value[idx] = { cls: 'tool-end', icon: '✅', label: getToolDoneLabel(name) }
      }
      autoScroll.scrollToBottom()
    },
    onSummarize() {
      toolStatuses.value.push({ cls: 'tool-info', icon: '📝', label: '对话历史已自动总结' })
      autoScroll.scrollToBottom()
    },
    onSessionEnd() {
      toolStatuses.value.push({ cls: 'tool-info', icon: '📋', label: '会话总结已生成' })
      autoScroll.scrollToBottom()
    },
    onDone(fullAnswer) {
      messages.value[aiIdx].content = formatAnswerOutput(fullAnswer)
      isStreaming.value = false
      autoScroll.scrollToBottom()
      if (!currentSessionId.value) loadSessions()
      // Attach copy handlers to code blocks in the last message
      nextTick(() => attachCopyButtons())
    },
    onError(err) {
      messages.value[aiIdx].content = `❌ ${err.message}`
      isStreaming.value = false
      toast.error(err.message)
    },
  })
}

/** Attach copy-to-clipboard buttons to code blocks rendered in the DOM */
function attachCopyButtons() {
  const el = messagesEl.value
  if (!el) return
  const blocks = el.querySelectorAll('.code-block:not(.copy-ready)')
  blocks.forEach(block => {
    block.classList.add('copy-ready')
    const btn = document.createElement('button')
    btn.className = 'copy-btn'
    btn.textContent = '复制'
    btn.addEventListener('click', async () => {
      const code = block.querySelector('code')
      if (code) {
        await copyToClipboard(code.textContent)
        btn.textContent = '已复制'
        btn.classList.add('copied')
        setTimeout(() => { btn.textContent = '复制'; btn.classList.remove('copied') }, 2000)
      }
    })
    block.appendChild(btn)
  })
}

// Also attach copy buttons when history is loaded
watch(() => messages.value.length, () => {
  nextTick(() => attachCopyButtons())
})
</script>
