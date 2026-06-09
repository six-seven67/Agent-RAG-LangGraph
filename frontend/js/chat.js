/* ============================================================
   Chat Page — 会话列表 + 流式对话 + Agent 工具事件
   ============================================================ */

const ChatPage = (() => {
  let currentSessionId = null;
  let messages = [];          // 当前会话的消息列表
  let toolStatuses = [];      // Agent 工具状态消息（tool_start/tool_end）
  let isStreaming = false;

  // DOM 引用（render 后绑定）
  let sessionListEl, messagesEl, inputEl, sendBtn, newChatBtn;

  function render() {
    const container = document.getElementById('page-container');
    document.getElementById('navbar').classList.remove('hidden');

    container.innerHTML = `
      <div class="chat-page">
        <!-- Sidebar -->
        <aside class="chat-sidebar">
          <div class="sidebar-header">
            <button class="btn btn-primary" id="btn-new-chat">➕ 新对话</button>
          </div>
          <div class="session-list" id="session-list">
            <div class="session-list-empty">
              <span class="empty-icon">💬</span>
              加载中...
            </div>
          </div>
        </aside>

        <!-- Main Chat Area -->
        <div class="chat-main">
          <div class="chat-messages" id="chat-messages">
            <div class="chat-welcome">
              <div class="welcome-icon">🤖</div>
              <h2>有什么可以帮您？</h2>
              <p>我是您的 AI 智能助手，可以帮您查询知识库、解答疑问。试试问一个产品相关问题吧！</p>
            </div>
          </div>
          <div class="chat-input-area">
            <div class="chat-input-row">
              <textarea id="chat-input" placeholder="输入您的问题，按 Enter 发送..." rows="1" maxlength="2000"></textarea>
              <button class="btn btn-primary" id="btn-send" disabled>
                <span>发送</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    `;

    // 缓存 DOM
    sessionListEl = document.getElementById('session-list');
    messagesEl = document.getElementById('chat-messages');
    inputEl = document.getElementById('chat-input');
    sendBtn = document.getElementById('btn-send');
    newChatBtn = document.getElementById('btn-new-chat');

    // 事件绑定
    newChatBtn.addEventListener('click', startNewChat);
    sendBtn.addEventListener('click', handleSend);
    inputEl.addEventListener('input', autoResizeInput);
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });

    // 加载会话列表
    loadSessions();
    inputEl.focus();
  }

  /* ---- Auto-resize textarea ---- */
  function autoResizeInput() {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 150) + 'px';
    sendBtn.disabled = !inputEl.value.trim() || isStreaming;
  }

  /* ---- Load Sessions ---- */
  async function loadSessions() {
    try {
      const data = await API.getSessions();
      renderSessionList(data.sessions || []);
    } catch (err) {
      sessionListEl.innerHTML = `<div class="session-list-empty"><span class="empty-icon">⚠️</span>加载失败: ${err.message}</div>`;
    }
  }

  function renderSessionList(sessions) {
    if (!sessions.length) {
      sessionListEl.innerHTML = `<div class="session-list-empty"><span class="empty-icon">💬</span>暂无历史会话<br>开启一段新对话吧 ✨</div>`;
      return;
    }

    sessionListEl.innerHTML = sessions
      .sort((a, b) => new Date(b.last_active) - new Date(a.last_active))
      .map(s => {
        const isActive = s.session_id === currentSessionId;
        // 优先使用 API 返回的 title，否则降级为 session_id 前缀
        const title = s.title || (s.session_id ? s.session_id.substring(0, 8) + '...' : '未知会话');
        const time = formatRelativeTime(s.last_active);
        // 根据 title 内容选择图标
        const icon = getSessionIcon(title);
        return `
          <div class="session-item${isActive ? ' active' : ''}" data-sid="${s.session_id}">
            <span class="session-icon">${icon}</span>
            <span class="session-info">
              <span class="session-title" title="${escapeAttr(title)}">${escapeHtml(title)}</span>
              <span class="session-time">${time}</span>
            </span>
            <button class="session-delete" data-del="${s.session_id}" title="删除">🗑</button>
          </div>
        `;
      }).join('');

    // 点击会话 → 加载历史
    sessionListEl.querySelectorAll('.session-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.classList.contains('session-delete')) return;
        loadSession(item.dataset.sid);
      });
    });

    // 删除按钮
    sessionListEl.querySelectorAll('.session-delete').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const sid = btn.dataset.del;
        if (!confirm('确定删除此会话？')) return;
        try {
          await API.deleteSession(sid);
          if (currentSessionId === sid) startNewChat();
          await loadSessions();
          Toast.success('会话已删除');
        } catch (err) {
          Toast.error(err.message);
        }
      });
    });
  }

  function getSessionIcon(title) {
    const t = title.toLowerCase();
    if (t.includes('洗') || t.includes('养') || t.includes('护')) return '🧺';
    if (t.includes('颜色') || t.includes('搭配') || t.includes('穿')) return '🎨';
    if (t.includes('尺码') || t.includes('大小') || t.includes('号')) return '📏';
    if (t.includes('你好') || t.includes('帮助')) return '👋';
    if (t.includes('退') || t.includes('换') || t.includes('投诉')) return '📋';
    return '💬';
  }

  /* ---- Load Session History ---- */
  async function loadSession(sessionId) {
    currentSessionId = sessionId;
    messages = [];
    toolStatuses = [];
    try {
      const data = await API.getHistory(sessionId);
      messages = data.messages || [];
      renderMessages();
      scrollToBottom();
      // 重新加载会话列表更新活跃状态
      const sessions = await getCurrentSessions();
      renderSessionList(sessions);
    } catch (err) {
      Toast.error(err.message);
    }
  }

  async function getCurrentSessions() {
    try {
      const data = await API.getSessions();
      return data.sessions || [];
    } catch { return []; }
  }

  /* ---- New Chat ---- */
  function startNewChat() {
    currentSessionId = null;
    messages = [];
    toolStatuses = [];
    renderMessages();
    inputEl.value = '';
    sendBtn.disabled = true;
    inputEl.style.height = 'auto';
    inputEl.focus();
    // 更新侧边栏活跃状态
    getCurrentSessions().then(s => renderSessionList(s));
  }

  /* ---- Send Message ---- */
  async function handleSend() {
    const query = inputEl.value.trim();
    if (!query || isStreaming) return;

    // 添加用户消息
    messages.push({ role: 'user', content: query, created_at: new Date().toISOString() });
    inputEl.value = '';
    inputEl.style.height = 'auto';
    sendBtn.disabled = true;
    isStreaming = true;
    toolStatuses = [];
    renderMessages();
    scrollToBottom();

    // AI 消息占位
    messages.push({ role: 'assistant', content: '', created_at: new Date().toISOString() });
    const aiMsgIndex = messages.length - 1;
    renderMessages();
    scrollToBottom();
    showTypingIndicator(aiMsgIndex);

    // 用于聚合 tool_start/tool_end 产生的工具描述
    let toolLines = [];

    await API.sendMessageStream(query, currentSessionId, {
      onToken(token, fullAnswer) {
        hideTypingIndicator(aiMsgIndex);
        messages[aiMsgIndex].content = fullAnswer;
        updateMessageBubble(aiMsgIndex, fullAnswer);
        scrollToBottom();
      },
      onToolStart(toolData) {
        hideTypingIndicator(aiMsgIndex);
        // 为每个工具调用添加状态卡片
        const tools = toolData.tools || [];
        tools.forEach(t => {
          const toolName = t.name || 'unknown';
          const label = getToolLabel(toolName);
          toolStatuses.push({ type: 'tool_start', name: toolName, label: label, time: new Date().toISOString() });
        });
        refreshToolStatuses();
        scrollToBottom();
      },
      onToolEnd(toolData) {
        const toolName = toolData.tool || 'unknown';
        // 查找最后一个匹配的 tool_start 并标记为完成
        for (let i = toolStatuses.length - 1; i >= 0; i--) {
          if (toolStatuses[i].type === 'tool_start' && toolStatuses[i].name === toolName) {
            toolStatuses[i].type = 'tool_end';
            toolStatuses[i].resultPreview = toolData.result_preview || '';
            break;
          }
        }
        refreshToolStatuses();
        scrollToBottom();
      },
      onSummarize() {
        toolStatuses.push({ type: 'summarize', name: 'summarize', time: new Date().toISOString() });
        refreshToolStatuses();
        scrollToBottom();
      },
      onSessionEnd() {
        toolStatuses.push({ type: 'session_end', name: 'session_end', time: new Date().toISOString() });
        refreshToolStatuses();
        scrollToBottom();
      },
      onDone(fullAnswer) {
        hideTypingIndicator(aiMsgIndex);
        // 格式化输出（结构化换行、层级缩进）
        const formatted = formatAnswerOutput(fullAnswer);
        messages[aiMsgIndex].content = formatted;
        updateMessageBubble(aiMsgIndex, formatted);
        isStreaming = false;
        sendBtn.disabled = !inputEl.value.trim();

        if (!currentSessionId) {
          // 新会话首条消息后刷新列表获取 session_id
          loadSessions().then(() => {
            getCurrentSessions().then(sessions => {
              if (sessions.length > 0) {
                currentSessionId = sessions[0].session_id;
                renderSessionList(sessions);
              }
            });
          });
        }
      },
      onError(err) {
        hideTypingIndicator(aiMsgIndex);
        messages[aiMsgIndex].content = `❌ ${err.message}`;
        updateMessageBubble(aiMsgIndex, messages[aiMsgIndex].content);
        isStreaming = false;
        sendBtn.disabled = !inputEl.value.trim();
        Toast.error(err.message);
      },
    });

    scrollToBottom();
  }

  /* ---- Tool status rendering ---- */
  function refreshToolStatuses() {
    // Rerender the message area — keep messages + insert tool status cards
    renderMessages();
  }

  function getToolLabel(toolName) {
    const labels = {
      'search_knowledge_base': '🔍 正在检索知识库...',
      'lookup_faq': '📋 正在查找常见问题...',
      'escalate_to_human': '👨‍💼 正在转接人工客服...',
      'web_search': '🌐 正在联网搜索...',
    };
    return labels[toolName] || `⚙️ 正在执行: ${toolName}...`;
  }

  function getToolDoneLabel(toolName) {
    const labels = {
      'search_knowledge_base': '🔍 检索知识库完成',
      'lookup_faq': '📋 常见问题查找完成',
      'escalate_to_human': '👨‍💼 已转接人工客服',
      'web_search': '🌐 联网搜索完成',
    };
    return labels[toolName] || `✅ 已完成: ${toolName}`;
  }

  /* ---- Render Messages ---- */
  function renderMessages() {
    if (!messages.length && !toolStatuses.length) {
      messagesEl.innerHTML = `
        <div class="chat-welcome">
          <div class="welcome-icon">🤖</div>
          <h2>有什么可以帮您？</h2>
          <p>我是您的 AI 智能助手，可以帮您查询知识库、解答疑问。<br>试试问一个产品相关问题吧！</p>
        </div>
      `;
      return;
    }

    let html = '';

    for (let i = 0; i < messages.length; i++) {
      const m = messages[i];
      const time = m.created_at ? formatTime(m.created_at) : '';
      const roleIcon = m.role === 'user' ? '👤' : '🤖';

      // 用户消息：纯文本转义；AI 消息：Markdown 渲染
      const renderedContent = m.role === 'assistant' && m.content
        ? formatMarkdown(m.content)
        : (m.content ? escapeHtml(m.content) : '');

      html += `
        <div class="message-row ${m.role}">
          <div class="message-avatar ${m.role}">${roleIcon}</div>
          <div>
            <div class="message-bubble" id="msg-${i}">${m.content ? renderedContent : '<span class="typing-indicator"><span></span><span></span><span></span></span>'}</div>
            ${time ? `<div class="message-time">${time}</div>` : ''}
          </div>
        </div>
      `;

      // 在最后一条 AI 消息后插入工具状态卡片
      if (m.role === 'assistant' && i === messages.length - 1 && toolStatuses.length > 0) {
        for (const ts of toolStatuses) {
          // 独立事件类型
          if (ts.type === 'summarize') {
            html += `<div class="tool-status tool-info"><span class="tool-dot"></span><span>📝 对话历史已自动总结</span></div>`;
            continue;
          }
          if (ts.type === 'session_end') {
            html += `<div class="tool-status tool-info"><span class="tool-dot"></span><span>📋 会话总结已生成</span></div>`;
            continue;
          }
          // 工具执行状态
          const cls = ts.type === 'tool_start' ? 'tool-start' : 'tool-end';
          const icon = ts.type === 'tool_start' ? '⏳' : '✅';
          const label = ts.type === 'tool_start' ? ts.label : getToolDoneLabel(ts.name);
          html += `
            <div class="tool-status ${cls}">
              <span class="tool-dot"></span>
              <span>${icon} ${escapeHtml(label)}</span>
            </div>
          `;
        }
      }
    }

    messagesEl.innerHTML = html;

    // 给代码块添加复制按钮
    messagesEl.querySelectorAll('.code-block').forEach(block => {
      if (block.querySelector('.copy-btn')) return;
      const btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.textContent = '📋 复制';
      btn.addEventListener('click', async () => {
        const code = block.querySelector('code');
        const text = code ? code.textContent : '';
        try {
          await navigator.clipboard.writeText(text);
          btn.textContent = '✓ 已复制';
          btn.classList.add('copied');
          setTimeout(() => {
            btn.textContent = '📋 复制';
            btn.classList.remove('copied');
          }, 2000);
        } catch {
          // Fallback for older browsers
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed'; ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          btn.textContent = '✓ 已复制';
          btn.classList.add('copied');
          setTimeout(() => {
            btn.textContent = '📋 复制';
            btn.classList.remove('copied');
          }, 2000);
        }
      });
      block.appendChild(btn);
    });
  }

  function updateMessageBubble(index, content) {
    const bubble = document.getElementById(`msg-${index}`);
    if (bubble) {
      bubble.innerHTML = formatMarkdown(content);
      // 给代码块添加复制按钮（仅流式更新结束后有完整代码块）
      bubble.querySelectorAll('.code-block').forEach(block => {
        if (block.querySelector('.copy-btn')) return;
        const btn = document.createElement('button');
        btn.className = 'copy-btn';
        btn.textContent = '📋 复制';
        btn.addEventListener('click', () => copyCodeBlock(btn, block));
        block.appendChild(btn);
      });
    }
  }

  function copyCodeBlock(btn, block) {
    const code = block.querySelector('code');
    const text = code ? code.textContent : '';
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = '✓ 已复制';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = '📋 复制'; btn.classList.remove('copied'); }, 2000);
    }).catch(() => {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      document.execCommand('copy'); document.body.removeChild(ta);
      btn.textContent = '✓ 已复制';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = '📋 复制'; btn.classList.remove('copied'); }, 2000);
    });
  }

  function showTypingIndicator(index) {
    const bubble = document.getElementById(`msg-${index}`);
    if (bubble && !bubble.querySelector('.typing-indicator')) {
      bubble.innerHTML = '<span class="typing-indicator"><span></span><span></span><span></span></span>';
    }
  }

  function hideTypingIndicator(index) {
    const bubble = document.getElementById(`msg-${index}`);
    if (bubble && bubble.querySelector('.typing-indicator')) {
      bubble.innerHTML = '';
    }
  }

  function scrollToBottom() {
    if (messagesEl) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  /* ---- Helpers ---- */
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /**
   * 轻量 Markdown → HTML 渲染器
   *
   * 支持的语法:
   *   **粗体**  *斜体*  `行内代码`
   *   ### 标题  (h3~h6)
   *   - 无序列表  1. 有序列表
   *   > 引用块
   *   --- 分隔线
   *   | 表格 |
   *   URL 自动链接
   */
  function formatMarkdown(text) {
    if (!text) return '';

    // ---- Pre-phase: 中文排版清理 ----
    // 修复非法换行：中文标点对内部 / 标点与文字之间不应有换行
    let html = cleanChineseText(text);

    // ---- Phase 0: 先转义 HTML（保护用户输入）----
    html = escapeHtml(html);

    // ---- Phase 1: 代码块（``` ... ```）----
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const langLabel = lang ? `<span class="code-lang">${lang}</span>` : '';
      return `<div class="code-block">${langLabel}<pre><code>${code.trim()}</code></pre></div>`;
    });

    // ---- Phase 2: 行内代码（`...`）----
    html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

    // ---- Phase 3: 粗体 + 斜体 ----
    // **粗体** — 允许跨行、前后空格
    html = html.replace(/\*\*([\s\S]*?)\*\*/g, '<strong>$1</strong>');
    // *斜体* — 不匹配 ** 的情况
    html = html.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<em>$1</em>');

    // ---- Phase 4: 表格 ----
    html = html.replace(/\|(.+)\|\n\|[-| :]+\|\n((?:\|.+\|\n?)*)/g, (_, headerRow, bodyRows) => {
      const headers = headerRow.split('|').map(h => h.trim()).filter(Boolean);
      const thHtml = headers.map(h => `<th>${h}</th>`).join('');
      const rows = bodyRows.trim().split('\n');
      const trHtml = rows.map(row => {
        const cells = row.split('|').map(c => c.trim()).filter(Boolean);
        return `<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`;
      }).join('');
      return `<div class="table-wrapper"><table><thead><tr>${thHtml}</tr></thead><tbody>${trHtml}</tbody></table></div>`;
    });

    // ---- Phase 5: 标题（## ~ ######，空格可选）----
    html = html.replace(/^######\s?(.+)$/gm, '<h6>$1</h6>');
    html = html.replace(/^#####\s?(.+)$/gm, '<h5>$1</h5>');
    html = html.replace(/^####\s?(.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^###\s?(.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^##\s?(.+)$/gm, '<h3>$1</h3>');  // ## → h3（统一处理）

    // ---- Phase 6: 无序列表（- 或 *，允许 0~N 空格缩进）----
    html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

    // ---- Phase 7: 有序列表 ----
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, (match) => {
      if (match.startsWith('<ul>')) return match;
      return `<ol>${match}</ol>`;
    });

    // ---- Phase 8: 引用块 ----
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote><p>$1</p></blockquote>');
    html = html.replace(/<\/blockquote>\n<blockquote>/g, '\n');

    // ---- Phase 9: 分隔线 ----
    html = html.replace(/^(---|\*\*\*|___)$/gm, '<hr>');

    // ---- Phase 10: URL 自动链接 ----
    html = html.replace(
      /(https?:\/\/[^\s<>"']+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>'
    );

    // ---- Phase 11: 换行处理 ----
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p><\/p>/g, '');
    html = html.replace(/<p>(\s*<br>\s*)+<\/p>/g, '');
    html = html.replace(/<ul>\s*<\/ul>/g, '');
    html = html.replace(/<ol>\s*<\/ol>/g, '');

    // ---- Phase 12: 结构化段落包裹 ----
    // 将 【核心结论】【补充提醒】【信息来源】 包裹为独立样式块
    // 使用 lookahead 确定每个段落的结束边界
    html = html.replace(
      /<p>【核心结论】([\s\S]*?)(?=<p>【补充提醒】|<p>【信息来源】|$)/,
      '<div class="section-core"><strong>【核心结论】</strong>$1</div>'
    );
    html = html.replace(
      /<p>【补充提醒】([\s\S]*?)(?=<p>【信息来源】|$)/,
      '<div class="section-reminder"><strong>【补充提醒】</strong>$1</div>'
    );
    html = html.replace(
      /<p>【信息来源】([\s\S]*?)$/,
      '<div class="section-source"><strong>【信息来源】</strong>$1</div>'
    );

    return html;
  }

  /**
   * 中文排版清理 — 修复非法换行
   *
   * 处理 AI 输出或检索结果中的中文排版问题。
   * 核心原则：中文段落内不应有换行，只有段落之间才允许。
   */
  function cleanChineseText(text) {
    // ---- Pass 1: 配对标点内换行（《》""（）等）----
    // 匹配 《...》 跨越多行 → 合并为一行
    text = text.replace(/《([^》\n]*)\n([^》]*)》/g, '《$1$2》');
    text = text.replace(/《([^》]*)\n/g, '《$1');
    text = text.replace(/\n([^《]*)》/g, '$1》');

    // （...）跨行
    text = text.replace(/（([^）\n]*)\n([^）]*)）/g, '（$1$2）');
    text = text.replace(/（([^）]*)\n/g, '（$1');
    text = text.replace(/\n([^（]*)）/g, '$1）');

    // "..." 跨行
    text = text.replace(/“([^”\n]*)\n([^”]*)”/g, '“$1$2”');
    text = text.replace(/“([^”]*)\n/g, '“$1');
    text = text.replace(/\n([^“]*)”/g, '$1”');

    // ---- Pass 2: 中文标点附近的非法换行 ----
    // 中文标点后紧跟换行 → 合并（逗号、顿号、分号、冒号、句号后的碎片）
    // 但保留句号/问号/感叹号后接结构化内容时的合理段落分隔：
    //   - 中文章节标题：一、二、三、…十、
    //   - 结构标签：【核心结论】【补充提醒】【信息来源】
    //   - 列表项：- * 1. 或括号标题（
    text = text.replace(/([，、；：。！？])\s*\n\s*/g, '$1');
    text = text.replace(
      /([。！？])\n(?!\s*(?:[-*\d]|（|[A-Z]|[一二三四五六七八九十]、|【))/g,
      '$1'
    );

    // ---- Pass 3: 书名号/括号边界粘连 ----
    text = text.replace(/([^\n\s])\s*\n\s*([《〈「『（("])/g, '$1$2');
    text = text.replace(/([》〉」』）)"'])\s*\n\s*([^\n\s])/g, '$1$2');

    // ---- Pass 4: 中文汉字之间的断行 ----
    // 行末中文字符 + 换行 + 行首中文字符 → 连接（非法断词）
    text = text.replace(/([一-鿿])\s*\n\s*([一-鿿])/g, '$1$2');

    // ---- Pass 5: 数字/字母被断开 ----
    // 数字+换行+中文字符 → 连接（如 "123\n天" → "123天"）
    text = text.replace(/(\d)\s*\n\s*([一-鿿])/g, '$1$2');
    // 中文字符+换行+数字 → 连接
    text = text.replace(/([一-鿿])\s*\n\s*(\d)/g, '$1$2');

    // ---- Pass 6: 标题标记后的断行 ----
    // "依据来源：\n《X》" → "依据来源：《X》"
    text = text.replace(/([：:])\s*\n\s*/g, '$1');

    // ---- Pass 7: 清理残留 ----
    text = text.replace(/[ \t]{2,}/g, ' ');
    text = text.replace(/^[ \t]+/gm, '');
    text = text.replace(/[ \t]+$/gm, '');

    return text;
  }

  /**
   * 对 AI 输出进行结构化格式化后处理。
   *
   * 确保答案遵循统一的四段式结构：
   * 【核心结论】→ 分层详解 → 【补充提醒】→ 【信息来源】
   *
   * 处理策略（按顺序）：
   * 1. 【核心结论】标签规范化
   * 2. 第一层标题（一、二、…十、）前插入空行
   * 3. 第二层标题（（一）（二）…）前换行
   * 4. 第三层要点（1. 2. 3. ...）前换行
   * 5. 【补充提醒】【信息来源】前插入空行
   * 6. 清理多余空行
   */
  function formatAnswerOutput(text) {
    if (!text) return text;

    // ---- Step 1: 预处理 ----
    text = text.trim();

    // ---- Step 2: 【核心结论】规范化 ----
    // 确保 "【核心结论】" 后换行
    text = text.replace(/【核心结论】\s*/g, '【核心结论】\n');
    // 确保 【核心结论】... 段落与后续有空行
    text = text.replace(
      /(【核心结论】\n[^\n]+?)\n?([一二三四五六七八九十]、|（[一二三四五六七八九十\d]+）)/g,
      '$1\n\n$2'
    );

    // ---- Step 3: 第一层标题（一、二、…十、）前空行 ----
    text = text.replace(
      /([。！？\n])([一二三四五六七八九十])、(?=\S)/g,
      '$1\n\n$2、'
    );
    // 行首的 "一、" 前保证有空行
    text = text.replace(/\n([一二三四五六七八九十])、(?=\S)/g, '\n\n$1、');
    // 防止 【核心结论】 后紧跟 "一、"
    text = text.replace(
      /(【核心结论】\n[^\n]+?)\n([一二三四五六七八九十])、/g,
      '$1\n\n$2、'
    );

    // ---- Step 4: 第二层标题（（一）（二）…）前换行 ----
    text = text.replace(/([^（\n])(（[一二三四五六七八九十\d]+）)/g, '$1\n$2');
    text = text.replace(/(?<!\n)(（[一二三四五六七八九十\d]+）)/g, '\n$1');

    // ---- Step 5: 第三层要点（1. 2. 3. ...）前换行 ----
    text = text.replace(/([^0-9\n])(\d+)\.\s*(?=[^\d])/g, '$1\n$2. ');
    text = text.replace(/(?<!\n)(\d+\.\s)/g, '\n$1');

    // ---- Step 6: 【补充提醒】【信息来源】前空行 ----
    text = text.replace(/([。！？\n])(【补充提醒】)/g, '$1\n\n$2');
    text = text.replace(/([。！？\n])(【信息来源】)/g, '$1\n\n$2');
    text = text.replace(/(?<!\n)(【补充提醒】)/g, '\n\n$1');
    text = text.replace(/(?<!\n)(【信息来源】)/g, '\n\n$1');

    // ---- Step 7: 清理多余空行 ----
    text = text.replace(/\n{3,}/g, '\n\n');
    // 移除行首行尾多余空格
    text = text.replace(/^[ \t]+/gm, '');
    text = text.replace(/[ \t]+$/gm, '');

    return text;
  }

  function formatTime(isoString) {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    } catch { return ''; }
  }

  function formatRelativeTime(isoString) {
    try {
      const d = new Date(isoString);
      const now = new Date();
      const diffMs = now - d;
      const diffMin = Math.floor(diffMs / 60000);
      if (diffMin < 1) return '刚刚';
      if (diffMin < 60) return `${diffMin}分钟前`;
      const diffHour = Math.floor(diffMin / 60);
      if (diffHour < 24) return `${diffHour}小时前`;
      const diffDay = Math.floor(diffHour / 24);
      if (diffDay < 7) return `${diffDay}天前`;
      return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    } catch { return ''; }
  }

  return { render };
})();
