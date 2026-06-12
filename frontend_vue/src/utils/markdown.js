/* ============================================================
   Markdown → HTML 渲染器 v3.4.0
   — 中文排版清洗
   — 完整 Markdown 渲染（代码块/表格/列表/引用/加粗等）
   — 代码块复制按钮 DOM 生成（copyCodeBlock）
   ============================================================ */

function escapeHtml(str) {
  if (!str) return ''
  const div = document.createElement('div')
  div.textContent = str
  return div.innerHTML
}

function cleanChineseText(text) {
  if (!text) return ''
  // 配对标点内换行合并
  text = text.replace(/《([^》\n]*)\n([^》]*)》/g, '《$1$2》')
  text = text.replace(/（([^）\n]*)\n([^）]*)）/g, '（$1$2）')
  text = text.replace(/"([^"\n]*)\n([^"]*)"/g, '"$1$2"')
  // 中文标点后的非法换行
  text = text.replace(/([，、；：。！？])\s*\n\s*/g, '$1')
  // 中文汉字之间的断行
  text = text.replace(/([一-鿿])\s*\n\s*([一-鿿])/g, '$1$2')
  // 数字/字母断开修复
  text = text.replace(/(\d)\s*\n\s*([一-鿿])/g, '$1$2')
  text = text.replace(/([一-鿿])\s*\n\s*(\d)/g, '$1$2')
  // 冒号后断行
  text = text.replace(/([：:])\s*\n\s*/g, '$1')
  // 清理残留空白
  text = text.replace(/[ \t]{2,}/g, ' ')
  text = text.replace(/^[ \t]+/gm, '')
  text = text.replace(/[ \t]+$/gm, '')
  return text
}

export function formatMarkdown(text) {
  if (!text) return ''

  let html = cleanChineseText(text)
  html = escapeHtml(html)

  // 代码块 — reserve for later (escapeHtml will turn ``` into something safe)
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const langLabel = lang ? `<span class="code-lang">${lang}</span>` : ''
    return `<div class="code-block">${langLabel}<pre><code>${code.trim()}</code></pre></div>`
  })

  // 行内代码
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')

  // 粗体 + 斜体
  html = html.replace(/\*\*([\s\S]*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<em>$1</em>')

  // 表格
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

  // 标题
  html = html.replace(/^######\s?(.+)$/gm, '<h6>$1</h6>')
  html = html.replace(/^#####\s?(.+)$/gm, '<h5>$1</h5>')
  html = html.replace(/^####\s?(.+)$/gm, '<h4>$1</h4>')
  html = html.replace(/^###\s?(.+)$/gm, '<h3>$1</h3>')
  html = html.replace(/^##\s?(.+)$/gm, '<h3>$1</h3>')

  // 列表
  html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>')
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, (match) => {
    if (match.startsWith('<ul>')) return match
    return `<ol>${match}</ol>`
  })

  // 引用块
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote><p>$1</p></blockquote>')
  html = html.replace(/<\/blockquote>\n<blockquote>/g, '\n')

  // 分隔线
  html = html.replace(/^(---|\*\*\*|___)$/gm, '<hr>')

  // URL 自动链接
  html = html.replace(/(https?:\/\/[^\s<>"']+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')

  // 换行 → 段落
  html = html.replace(/\n\n+/g, '</p><p>')
  html = html.replace(/\n/g, '<br>')
  html = '<p>' + html + '</p>'
  html = html.replace(/<p><\/p>/g, '')
  html = html.replace(/<p>(\s*<br>\s*)+<\/p>/g, '')
  html = html.replace(/<ul>\s*<\/ul>/g, '')
  html = html.replace(/<ol>\s*<\/ol>/g, '')

  // 结构化段落包裹
  html = html.replace(
    /<p>【核心结论】([\s\S]*?)(?=<p>【补充提醒】|<p>【信息来源】|$)/,
    '<div class="section-core"><strong>【核心结论】</strong>$1</div>'
  )
  html = html.replace(
    /<p>【补充提醒】([\s\S]*?)(?=<p>【信息来源】|$)/,
    '<div class="section-reminder"><strong>【补充提醒】</strong>$1</div>'
  )
  html = html.replace(
    /<p>【信息来源】([\s\S]*?)$/,
    '<div class="section-source"><strong>【信息来源】</strong>$1</div>'
  )

  return html
}

export function formatAnswerOutput(text) {
  if (!text) return text
  text = text.trim()
  text = text.replace(/【核心结论】\s*/g, '【核心结论】\n')
  text = text.replace(/([。！？\n])([一二三四五六七八九十])、(?=\S)/g, '$1\n\n$2、')
  text = text.replace(/（(\d+)）/g, '\n（$1）')
  text = text.replace(/([。！？\n])(【补充提醒】)/g, '$1\n\n$2')
  text = text.replace(/([。！？\n])(【信息来源】)/g, '$1\n\n$2')
  text = text.replace(/\n{3,}/g, '\n\n')
  return text
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
