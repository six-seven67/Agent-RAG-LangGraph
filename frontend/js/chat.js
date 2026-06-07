/* ============================================================
   Chat Page — 会话列表 + 流式对话
   ============================================================ */

const ChatPage = (() => {
  let currentSessionId = null;
  let messages = [];          // 当前会话的消息列表
  let isStreaming = false;    // 是否正在流式接收中

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
            <button class="btn btn-primary" id="btn-new-chat">+ 新对话</button>
          </div>
          <div class="session-list" id="session-list">
            <div class="session-list-empty">加载中...</div>
          </div>
        </aside>

        <!-- Main Chat Area -->
        <div class="chat-main">
          <div class="chat-messages" id="chat-messages">
            <div class="chat-welcome">
              <h2>🤖 有什么可以帮您？</h2>
              <p>选择一个历史会话或开启新对话</p>
            </div>
          </div>
          <div class="chat-input-area">
            <div class="chat-input-row">
              <textarea id="chat-input" placeholder="输入您的问题..." rows="1" maxlength="2000"></textarea>
              <button class="btn btn-primary" id="btn-send" disabled>发送</button>
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
      sessionListEl.innerHTML = `<div class="session-list-empty">加载失败: ${err.message}</div>`;
    }
  }

  function renderSessionList(sessions) {
    if (!sessions.length) {
      sessionListEl.innerHTML = `<div class="session-list-empty">暂无历史会话<br>开启一段新对话吧 ✨</div>`;
      return;
    }

    sessionListEl.innerHTML = sessions
      .sort((a, b) => new Date(b.last_active) - new Date(a.last_active))
      .map(s => {
        const isActive = s.session_id === currentSessionId;
        const title = s.session_id.substring(0, 8) + '...';
        const time = formatRelativeTime(s.last_active);
        return `
          <div class="session-item${isActive ? ' active' : ''}" data-sid="${s.session_id}">
            <span class="session-title" title="${s.session_id}">📁 ${title}</span>
            <span class="text-sm text-secondary">${time}</span>
            <button class="session-delete" data-del="${s.session_id}" title="删除">🗑</button>
          </div>
        `;
      }).join('');

    // 点击会话 → 加载历史
    sessionListEl.querySelectorAll('.session-item').forEach(item => {
      item.addEventListener('click', (e) => {
        // 如果点击的是删除按钮，不触发
        if (e.target.classList.contains('session-delete')) return;
        const sid = item.dataset.sid;
        loadSession(sid);
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
          if (currentSessionId === sid) {
            startNewChat();
          }
          await loadSessions();
          Toast.success('会话已删除');
        } catch (err) {
          Toast.error(err.message);
        }
      });
    });
  }

  /* ---- Load Session History ---- */
  async function loadSession(sessionId) {
    currentSessionId = sessionId;
    messages = [];
    try {
      const data = await API.getHistory(sessionId);
      messages = data.messages || [];
      renderMessages();
      scrollToBottom();
      renderSessionList(await getCurrentSessions());
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
    renderMessages();
    inputEl.value = '';
    sendBtn.disabled = true;
    inputEl.focus();
    // 更新侧边栏活跃状态
    renderSessionListFromCache();
  }

  async function renderSessionListFromCache() {
    const sessions = await getCurrentSessions();
    renderSessionList(sessions);
  }

  /* ---- Send Message ---- */
  async function handleSend() {
    const query = inputEl.value.trim();
    if (!query || isStreaming) return;

    // 添加用户消息到界面
    messages.push({ role: 'user', content: query, created_at: new Date().toISOString() });
    inputEl.value = '';
    inputEl.style.height = 'auto';
    sendBtn.disabled = true;
    isStreaming = true;
    renderMessages();
    scrollToBottom();

    // 添加 AI 消息占位（用于逐字填充）
    messages.push({ role: 'assistant', content: '', created_at: new Date().toISOString() });
    const aiMsgIndex = messages.length - 1;
    renderMessages();
    scrollToBottom();

    // 显示 typing 指示器
    showTypingIndicator(aiMsgIndex);

    await API.sendMessageStream(query, currentSessionId, {
      onToken(token, fullAnswer) {
        hideTypingIndicator(aiMsgIndex);
        messages[aiMsgIndex].content = fullAnswer;
        updateMessageBubble(aiMsgIndex, fullAnswer);
        scrollToBottom();
      },
      onDone(fullAnswer) {
        hideTypingIndicator(aiMsgIndex);
        messages[aiMsgIndex].content = fullAnswer;
        updateMessageBubble(aiMsgIndex, fullAnswer);
        isStreaming = false;
        sendBtn.disabled = !inputEl.value.trim();

        // 如果是新会话，从 API 响应后获得 session_id
        // 由于 SSE 不返回 session_id，首条消息后重新加载会话列表
        if (!currentSessionId) {
          loadSessions().then(() => {
            // 自动选中最新会话
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
        messages[aiMsgIndex].content = `[错误] ${err.message}`;
        updateMessageBubble(aiMsgIndex, messages[aiMsgIndex].content);
        isStreaming = false;
        sendBtn.disabled = !inputEl.value.trim();
        Toast.error(err.message);
      },
    });

    scrollToBottom();
  }

  /* ---- Render Messages ---- */
  function renderMessages() {
    if (!messages.length) {
      messagesEl.innerHTML = `
        <div class="chat-welcome">
          <h2>🤖 有什么可以帮您？</h2>
          <p>在下方输入您的问题，AI 助手将为您解答</p>
        </div>
      `;
      return;
    }

    messagesEl.innerHTML = messages.map((m, i) => {
      const time = m.created_at ? formatTime(m.created_at) : '';
      const roleIcon = m.role === 'user' ? '👤' : '🤖';
      return `
        <div class="message-row ${m.role}">
          <div class="message-avatar ${m.role}">${roleIcon}</div>
          <div>
            <div class="message-bubble" id="msg-${i}">${escapeHtml(m.content) || '<span class="typing-indicator"><span></span><span></span><span></span></span>'}</div>
            ${time ? `<div class="message-time">${time}</div>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  function updateMessageBubble(index, content) {
    const bubble = document.getElementById(`msg-${index}`);
    if (bubble) {
      bubble.textContent = content;
    }
  }

  function showTypingIndicator(index) {
    const bubble = document.getElementById(`msg-${index}`);
    if (bubble) {
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
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
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
