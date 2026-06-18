/* ============================================================
   Markdown → HTML 渲染器 v4.0.0
   — 标准 Markdown 渲染（标题/列表/代码/表格/引用/加粗等）
   — 中文排版清洗
   — 代码块复制按钮 DOM 生成（copyCodeBlock）
   ============================================================ */

function escapeHtml(str) {
  if (!str) return ''
  const div = document.createElement('div')
  div.textContent = str
  return div.innerHTML
}

// XSS 防护：URL 协议白名单
// 仅允许 http、https、mailto、tel 及相对路径，阻断 javascript: / data: 等危险协议
const SAFE_PROTOCOL_RE = /^(https?|mailto|tel):/i
function sanitizeUrl(url) {
  if (!url) return ''
  // 相对路径 /docs/xxx, #anchor, ./dir, ../dir
  if (/^[\/#.]/.test(url)) return url
  // 协议白名单
  if (SAFE_PROTOCOL_RE.test(url)) return url
  // 危险协议（javascript:, data:, vbscript: 等）→ 阻断
  return ''
}

/**
 * 中文排版清洗：修复 LLM 输出中常见的中文排版问题。
 * 注意：不再删除段落之间的空行，以保持 Markdown 结构完整。
 */
function cleanChineseText(text) {
  if (!text) return ''
  // 配对标点内换行合并（不跨段）
  text = text.replace(/《([^》\n]{1,30})\n([^》]{1,30})》/g, '《$1$2》')
  text = text.replace(/（([^）\n]{1,30})\n([^）]{1,30})）/g, '（$1$2）')
  // 清理行内多余空白
  text = text.replace(/[ \t]{2,}/g, ' ')
  text = text.replace(/^[ \t]+/gm, '')
  text = text.replace(/[ \t]+$/gm, '')
  return text
}

/**
 * 将 Markdown 文本渲染为 HTML。
 */
export function formatMarkdown(text) {
  if (!text) return ''

  let html = cleanChineseText(text)
  html = escapeHtml(html)

  // ---- 代码块（```）----
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const langLabel = lang ? `<span class="code-lang">${lang}</span>` : ''
    return `<div class="code-block">${langLabel}<pre><code>${code.trim()}</code></pre></div>`
  })

  // ---- 行内代码 ----
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')

  // ---- 粗体 + 斜体 ----
  html = html.replace(/\*\*([\s\S]*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<em>$1</em>')

  // ---- 图片 ----
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) =>
    `<img src="${sanitizeUrl(src)}" alt="${alt}">`)

  // ---- 链接 ----
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, text, href) => {
    const safe = sanitizeUrl(href)
    if (!safe) return text  // 危险链接降级为纯文本
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${text}</a>`
  })

  // ---- 表格 ----
  html = html.replace(/\|(.+)\|\n\|[-| :]+\|\n((?:\|.+\|\n?)*)/g, (_, headerRow, bodyRows) => {
    const headers = headerRow.split('|').map(h => h.trim()).filter(Boolean)
    const thHtml = headers.map(h => `<th>${h}</th>`).join('')
    const rows = bodyRows.trim().split('\n')
    const trHtml = rows.map(row => {
      const cells = row.split('|').map(c => c.trim()).filter(Boolean)
      return `<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`
    }).join('')
    return `<div class="table-wrapper"><table><thead><tr>${thHtml}</tr></thead><tbody>${trHtml}</tbody></table></div>`
  })

  // ---- 标题 ----
  // 在聊天气泡中，将标题层级上移以匹配已有 CSS（h3=带底边框节标题, h4=子标题）
  html = html.replace(/^######\s?(.+)$/gm, '<h6>$1</h6>')
  html = html.replace(/^#####\s?(.+)$/gm, '<h5>$1</h5>')
  html = html.replace(/^####\s?(.+)$/gm, '<h4>$1</h4>')
  html = html.replace(/^###\s?(.+)$/gm, '<h4>$1</h4>')
  html = html.replace(/^##\s?(.+)$/gm, '<h3>$1</h3>')
  html = html.replace(/^#\s?(.+)$/gm, '<h3>$1</h3>')

  // ---- 引用块 ----
  html = html.replace(/^&gt;\s?(.+)$/gm, '<blockquote><p>$1</p></blockquote>')
  html = html.replace(/<\/blockquote>\n<blockquote>/g, '\n')

  // ---- 分隔线 ----
  html = html.replace(/^(---|\*\*\*|___)$/gm, '<hr>')

  // ---- 无序列表 ----
  html = html.replace(/^[\-\*]\s(.+)$/gm, '<li>$1</li>')
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')

  // ---- 有序列表 ----
  html = html.replace(/^\d+\.\s(.+)$/gm, '<li>$1</li>')
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, (match) => {
    if (match.startsWith('<ul>')) return match
    return `<ol>${match}</ol>`
  })

  // ---- URL 自动链接（未被 [text](url) 捕获的裸链接）----
  html = html.replace(/(https?:\/\/[^\s<>"']+)/g, (_, url) => {
    const safe = sanitizeUrl(url)
    if (!safe) return url
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a>`
  })

  // ---- 换行 → 段落（不留空行：多换行折叠为单 <br>）----
  html = html.replace(/\n{2,}/g, '\n')
  html = html.replace(/\n/g, '<br>')
  html = '<p>' + html + '</p>'

  // ---- 清理空标签 ----
  html = html.replace(/<p><\/p>/g, '')
  html = html.replace(/<p>(\s*<br>\s*)+<\/p>/g, '')
  html = html.replace(/<ul>\s*<\/ul>/g, '')
  html = html.replace(/<ol>\s*<\/ol>/g, '')

  // ---- 结构化段落包裹 ----
  // 标准 Markdown 格式（## → h3）：匹配从节标题到下一个同级节标题或文末
  html = html.replace(
    /<h3>核心结论<\/h3>([\s\S]*?)(?=<h3>补充提醒<\/h3>|<h3>信息来源<\/h3>|$)/,
    '<div class="section-core"><h3>核心结论</h3>$1</div>'
  )
  html = html.replace(
    /<h3>补充提醒<\/h3>([\s\S]*?)(?=<h3>信息来源<\/h3>|$)/,
    '<div class="section-reminder"><h3>补充提醒</h3>$1</div>'
  )
  html = html.replace(
    /<h3>信息来源<\/h3>([\s\S]*?)$/,
    '<div class="section-source"><h3>信息来源</h3>$1</div>'
  )

  // 向后兼容：【】旧格式
  html = html.replace(
    /<p>(【核心结论】)([\s\S]*?)(?=<p>(【补充提醒】|【信息来源】)|$)/,
    '<div class="section-core"><strong>$1</strong>$2</div>'
  )
  html = html.replace(
    /<p>(【补充提醒】)([\s\S]*?)(?=<p>(【信息来源】)|$)/,
    '<div class="section-reminder"><strong>$1</strong>$2</div>'
  )
  html = html.replace(
    /<p>(【信息来源】)([\s\S]*?)$/,
    '<div class="section-source"><strong>$1</strong>$2</div>'
  )

  // ---- 合并连续同类 section（修复段落拆分导致的碎片）----
  html = html.replace(/<\/div>\s*<div class="section-core">/g, '')
  html = html.replace(/<\/div>\s*<div class="section-reminder">/g, '')
  html = html.replace(/<\/div>\s*<div class="section-source">/g, '')

  return html
}

/**
 * 前端回答后处理：对 LLM 流式输出的完整文本做轻量规范化。
 *
 * v4.0: 标准 Markdown 格式下，仅做空行清理和旧格式兼容转换。
 */
export function formatAnswerOutput(text) {
  if (!text) return text
  let t = text.trim()

  // 兼容旧格式：【】标签前补单空行
  t = t.replace(/([^\n])(【核心结论】)/g, '$1\n$2')
  t = t.replace(/([^\n])(【补充提醒】)/g, '$1\n$2')
  t = t.replace(/([^\n])(【信息来源】)/g, '$1\n$2')

  // Markdown 标题前补单空行（不补双空行，避免渲染后空隙过大）
  t = t.replace(/([^\n])(#{2,3}\s)/g, '$1\n$2')

  // 清理连续多余空行（不留空行）
  t = t.replace(/\n{2,}/g, '\n')

  return t
}

/**
 * Generate a "copy" button for a given code block DOM element.
 * Attaches click handler that copies code text to clipboard.
 * Called from ChatView on stream-end and history-load.
 */
export function copyCodeBlock(blockEl) {
  if (blockEl.querySelector('.copy-btn')) return // already attached
  const code = blockEl.querySelector('code')
  if (!code) return

  const btn = document.createElement('button')
  btn.className = 'copy-btn'
  btn.textContent = '复制'
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(code.textContent)
      btn.textContent = '已复制'
      btn.classList.add('copied')
      setTimeout(() => { btn.textContent = '复制'; btn.classList.remove('copied') }, 2000)
    } catch {
      btn.textContent = '失败'
      setTimeout(() => { btn.textContent = '复制' }, 2000)
    }
  })
  blockEl.appendChild(btn)
}
