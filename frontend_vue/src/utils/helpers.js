export function escapeHtml(str) {
  if (!str) return ''
  const div = document.createElement('div')
  div.textContent = String(str)
  return div.innerHTML
}

export function escapeAttr(str) {
  if (!str) return ''
  return str.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function formatDate(isoString) {
  try {
    const d = new Date(isoString)
    return d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return '-' }
}

export function formatTime(isoString) {
  try {
    const d = new Date(isoString)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

export function formatRelativeTime(isoString) {
  try {
    const d = new Date(isoString)
    const now = new Date()
    const diffMin = Math.floor((now - d) / 60000)
    if (diffMin < 1) return '刚刚'
    if (diffMin < 60) return `${diffMin}分钟前`
    const diffHour = Math.floor(diffMin / 60)
    if (diffHour < 24) return `${diffHour}小时前`
    const diffDay = Math.floor(diffHour / 24)
    if (diffDay < 7) return `${diffDay}天前`
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch { return '' }
}

export function getSessionIcon(title) {
  const t = (title || '').toLowerCase()
  if (t.includes('洗') || t.includes('养') || t.includes('护')) return '🧺'
  if (t.includes('颜色') || t.includes('搭配') || t.includes('穿')) return '🎨'
  if (t.includes('尺码') || t.includes('大小') || t.includes('号')) return '📏'
  if (t.includes('你好') || t.includes('帮助')) return '👋'
  if (t.includes('退') || t.includes('换') || t.includes('投诉')) return '📋'
  return '💬'
}

export function getToolLabel(toolName) {
  const labels = {
    'search_knowledge_base': '🔍 正在检索知识库...',
    'lookup_faq': '📋 正在查找常见问题...',
    'escalate_to_human': '👨‍💼 正在转接人工客服...',
    'web_search': '🌐 正在联网搜索...',
  }
  return labels[toolName] || `⚙️ 正在执行: ${toolName}...`
}

export function getToolDoneLabel(toolName) {
  const labels = {
    'search_knowledge_base': '🔍 检索知识库完成',
    'lookup_faq': '📋 常见问题查找完成',
    'escalate_to_human': '👨‍💼 已转接人工客服',
    'web_search': '🌐 联网搜索完成',
  }
  return labels[toolName] || `✅ 已完成: ${toolName}`
}

export function copyToClipboard(text) {
  return navigator.clipboard.writeText(text).catch(() => {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select()
    document.execCommand('copy'); document.body.removeChild(ta)
  })
}

export const SUPPORTED_EXTS = ['.txt', '.pdf', '.docx', '.xlsx']

export function checkFileExt(filename) {
  const ext = filename.toLowerCase().slice(filename.lastIndexOf('.'))
  return SUPPORTED_EXTS.includes(ext)
}
