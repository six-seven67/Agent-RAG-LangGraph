/* ============================================================
   API Client — JWT Token 管理 + 自动刷新 + 请求封装
   ============================================================ */

const API = (() => {
  const BASE_URL = 'http://localhost:8000';

  // Token 存储（access_token 用内存变量，refresh_token 持久化到 localStorage）
  let accessToken = null;
  const REFRESH_KEY = 'rag_refresh_token';

  function getRefreshToken() {
    return localStorage.getItem(REFRESH_KEY);
  }
  function setRefreshToken(token) {
    if (token) localStorage.setItem(REFRESH_KEY, token);
    else localStorage.removeItem(REFRESH_KEY);
  }
  function getAccessToken() {
    return accessToken;
  }
  function setTokens(access, refresh) {
    accessToken = access;
    if (refresh) setRefreshToken(refresh);
  }
  function clearTokens() {
    accessToken = null;
    setRefreshToken(null);
  }

  /**
   * 用 refresh_token 换新的一对 token
   * 返回新的 access_token，失败返回 null
   */
  async function refreshAccessToken() {
    const rt = getRefreshToken();
    if (!rt) return null;
    try {
      const res = await fetch(`${BASE_URL}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) { clearTokens(); return null; }
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      return data.access_token;
    } catch {
      return null;
    }
  }

  /**
   * 核心请求方法 — 自动附加 token，401 时自动刷新并重试一次
   */
  async function request(url, options = {}) {
    const opts = { ...options };
    opts.headers = { ...opts.headers };

    // 自动附加 token（白名单：不需要 token 的接口）
    const noAuthPaths = ['/api/auth/login', '/api/auth/register', '/api/auth/refresh', '/health'];
    const path = new URL(url, BASE_URL).pathname;
    if (!noAuthPaths.includes(path) && accessToken) {
      opts.headers['Authorization'] = `Bearer ${accessToken}`;
    }

    let res = await fetch(`${BASE_URL}${url}`, opts);

    // 401 → 尝试 refresh → 重试一次
    if (res.status === 401 && accessToken) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        opts.headers['Authorization'] = `Bearer ${newToken}`;
        res = await fetch(`${BASE_URL}${url}`, opts);
      }
    }

    return res;
  }

  /**
   * 请求 + 自动解析 JSON，非 2xx 抛出错误
   */
  async function requestJSON(url, options = {}) {
    const res = await request(url, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.detail || `请求失败 (${res.status})`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  /* ========== Auth API ========== */
  async function login(username, password) {
    const data = await requestJSON('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    setTokens(data.access_token, data.refresh_token);
    return data;
  }

  async function register(username, password, email) {
    const data = await requestJSON('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, email: email || undefined }),
    });
    setTokens(data.access_token, data.refresh_token);
    return data;
  }

  async function logout() {
    try {
      await requestJSON('/api/auth/logout', { method: 'POST' });
    } catch { /* 即使失败也清除本地 token */ }
    clearTokens();
  }

  async function getMe() {
    return requestJSON('/api/auth/me');
  }

  /* ========== Chat API ========== */
  async function getSessions() {
    return requestJSON('/api/chat/sessions');
  }

  async function getHistory(sessionId) {
    return requestJSON(`/api/chat/history/${sessionId}`);
  }

  async function deleteSession(sessionId) {
    return requestJSON(`/api/chat/history/${sessionId}`, { method: 'DELETE' });
  }

  /**
   * 发送消息（非流式）
   */
  async function sendMessage(query, sessionId) {
    const params = new URLSearchParams({ query });
    if (sessionId) params.append('session_id', sessionId);
    return requestJSON(`/api/chat/?${params}`, { method: 'POST' });
  }

  /**
   * 发送消息（SSE 流式）— 支持 Agent 工具事件
   *
   * 回调:
   *   onToken(token, fullAnswer)    — 逐字 token
   *   onToolStart({tools})          — Agent 开始调用工具
   *   onToolEnd({tool, result})     — 工具执行完成
   *   onSummarize()                 — 对话历史已自动总结
   *   onSessionEnd()                — 会话结束总结已生成
   *   onThinking()                  — Agent 思考中
   *   onDone(fullAnswer)            — 流结束
   *   onError(err)                  — 发生错误
   */
  async function sendMessageStream(query, sessionId, { onToken, onToolStart, onToolEnd, onSummarize, onSessionEnd, onThinking, onDone, onError } = {}) {
    const params = new URLSearchParams({ query });
    if (sessionId) params.append('session_id', sessionId);

    // 构造完整 URL（需手动拼接 token，因为用了 fetch 但 SSE 不走 request() 的自动重试逻辑）
    const url = `${BASE_URL}/api/chat/stream?${params}`;
    const headers = {
      'Accept': 'text/event-stream',
    };
    if (accessToken) {
      headers['Authorization'] = `Bearer ${accessToken}`;
    }

    let response = await fetch(url, { method: 'POST', headers });

    // 401 → 尝试刷新 → 重试
    if (response.status === 401 && accessToken) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        headers['Authorization'] = `Bearer ${newToken}`;
        response = await fetch(url, { method: 'POST', headers });
      }
    }

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      const err = new Error(errData.detail || `请求失败 (${response.status})`);
      if (onError) onError(err);
      return null;
    }

    // 读取 SSE 流
    const reader = response.body
      .pipeThrough(new TextDecoderStream())
      .getReader();

    let partialLine = '';   // 跨 chunk 的不完整行缓冲区
    let eventType = '';     // 当前 SSE event 类型（跨 chunk 保持）
    let fullAnswer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // SSE 数据可能跨 chunk，用简单的行解析
        const lines = (partialLine + value).split('\n');
        // 最后一行可能不完整，保留给下一次
        partialLine = lines.pop() || '';

        for (const line of lines) {
          // 空行 = SSE 事件边界，重置 eventType
          if (line.trim() === '') {
            eventType = '';
            continue;
          }
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (eventType === 'done' || data === '[DONE]') {
              if (onDone) onDone(fullAnswer);
              return fullAnswer;
            }
            if (eventType === 'token' || !eventType) {
              fullAnswer += data;
              if (onToken) onToken(data, fullAnswer);
            } else if (eventType === 'tool_start') {
              try {
                const toolData = JSON.parse(data);
                if (onToolStart) onToolStart(toolData);
              } catch { /* ignore parse errors */ }
            } else if (eventType === 'tool_end') {
              try {
                const toolData = JSON.parse(data);
                if (onToolEnd) onToolEnd(toolData);
              } catch { /* ignore parse errors */ }
            } else if (eventType === 'summarize') {
              if (onSummarize) onSummarize();
            } else if (eventType === 'session_end') {
              if (onSessionEnd) onSessionEnd();
            } else if (eventType === 'thinking') {
              if (onThinking) onThinking();
            }
          }
        }
      }
    } catch (e) {
      if (onError) onError(e);
      return fullAnswer || null;
    }

    if (onDone) onDone(fullAnswer);
    return fullAnswer;
  }

  /* ========== Knowledge API ========== */
  async function uploadDocument(file) {
    const formData = new FormData();
    formData.append('file', file);
    return requestJSON('/api/knowledge/upload', {
      method: 'POST',
      body: formData,
      // 不设置 Content-Type，让浏览器自动设置 multipart/form-data + boundary
    });
  }

  async function getDocuments() {
    return requestJSON('/api/knowledge/documents');
  }

  async function deleteDocument(docId) {
    return requestJSON(`/api/knowledge/documents/${docId}`, { method: 'DELETE' });
  }

  /* ========== User API ========== */
  async function getProfile() {
    return requestJSON('/api/user/profile');
  }

  async function updateProfile(email) {
    const params = new URLSearchParams();
    if (email) params.append('email', email);
    return requestJSON(`/api/user/profile?${params}`, { method: 'PUT' });
  }

  async function changePassword(oldPassword, newPassword) {
    return requestJSON('/api/user/password', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    });
  }

  /* ========== Health ========== */
  async function healthCheck() {
    return requestJSON('/health');
  }

  // 公开 API
  return {
    getAccessToken,
    getRefreshToken,
    setTokens,
    clearTokens,
    refreshAccessToken,
    request,
    requestJSON,
    // Auth
    login,
    register,
    logout,
    getMe,
    // Chat
    getSessions,
    getHistory,
    deleteSession,
    sendMessage,
    sendMessageStream,
    // Knowledge
    uploadDocument,
    getDocuments,
    deleteDocument,
    // User
    getProfile,
    updateProfile,
    changePassword,
    // Health
    healthCheck,
  };
})();
