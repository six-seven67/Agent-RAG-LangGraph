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
      onDone(fullAnswer) {
        hideTypingIndicator(aiMsgIndex);
        messages[aiMsgIndex].content = fullAnswer;
        updateMessageBubble(aiMsgIndex, fullAnswer);
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
    };
    return labels[toolName] || `⚙️ 正在执行: ${toolName}...`;
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

    // Build message HTML rows, interleaving tool statuses where they
    // appear chronologically (right before the assistant message)
    let html = '';

    for (let i = 0; i < messages.length; i++) {
      const m = messages[i];
      const time = m.created_at ? formatTime(m.created_at) : '';
      const roleIcon = m.role === 'user' ? '👤' : '🤖';

      html += `
        <div class="message-row ${m.role}">
          <div class="message-avatar ${m.role}">${roleIcon}</div>
          <div>
            <div class="message-bubble" id="msg-${i}">${m.content ? escapeHtml(m.content) : '<span class="typing-indicator"><span></span><span></span><span></span></span>'}</div>
            ${time ? `<div class="message-time">${time}</div>` : ''}
          </div>
        </div>
      `;

      // After each assistant message, show tool statuses that belong here
      // (tool statuses interleave chronologically — show them after the
      //  AI message that triggered them)
      if (m.role === 'assistant' && i === messages.length - 1 && toolStatuses.length > 0 && isStreaming) {
        for (const ts of toolStatuses) {
          const cls = ts.type === 'tool_start' ? 'tool-start' : 'tool-end';
          const icon = ts.type === 'tool_start' ? '⏳' : '✅';
          const label = ts.type === 'tool_start' ? ts.label : `已完成: ${getToolLabel(ts.name).replace('正在', '')}`;
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
  }

  function updateMessageBubble(index, content) {
    const bubble = document.getElementById(`msg-${index}`);
    if (bubble) {
      bubble.textContent = content;
    }
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
      bubble.textContent = '';
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
