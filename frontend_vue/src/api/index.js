/* ============================================================
   API Client — JWT Token 管理 + 自动刷新 + 请求封装
   ============================================================ */

const BASE_URL = ''  // Vite proxy handles /api → localhost:8000

// Token 存储（access_token 用内存变量，refresh_token 持久化到 localStorage）
let accessToken = null
const REFRESH_KEY = 'rag_refresh_token'
let _authReady = false       // initAuth() 是否已完成
let _authReadyResolve = null // 等待 initAuth 完成的 resolve

function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY)
}
function setRefreshToken(token) {
  if (token) localStorage.setItem(REFRESH_KEY, token)
  else localStorage.removeItem(REFRESH_KEY)
}
export function getAccessToken() {
  return accessToken
}
export function setTokens(access, refresh) {
  accessToken = access
  if (refresh !== undefined) setRefreshToken(refresh)
}
export function clearTokens() {
  accessToken = null
  setRefreshToken(null)
}

/**
 * 当前是否处于"已认证"状态。
 *
 * 注意：页面刚加载时 refresh_token 尚在但 access_token 可能尚未恢复；
 * 调用方应等待 initAuth() 完成后再做路由跳转判断。
 */
export function isAuthenticated() {
  return !!(accessToken || getRefreshToken())
}

/**
 * 等待 initAuth() 完成（供路由守卫使用）。
 */
export function whenAuthReady() {
  if (_authReady) return Promise.resolve()
  return new Promise(resolve => { _authReadyResolve = resolve })
}

async function refreshAccessToken() {
  const rt = getRefreshToken()
  if (!rt) { console.log('[auth] refreshAccessToken: 无 refresh_token，跳过'); return null }
  try {
    console.log('[auth] refreshAccessToken: 开始刷新，token 前10字符 =', rt.substring(0, 10) + '...')
    const res = await fetch(`${BASE_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
    if (!res.ok) {
      console.warn('[auth] refreshAccessToken: 刷新失败 HTTP', res.status, '→ 清除本地 token')
      clearTokens()
      return null
    }
    const data = await res.json()
    console.log('[auth] refreshAccessToken: 刷新成功，新 access_token 前10字符 =', data.access_token.substring(0, 10) + '...')
    setTokens(data.access_token, data.refresh_token)
    return data.access_token
  } catch (e) {
    console.error('[auth] refreshAccessToken: 网络错误', e.message)
    return null
  }
}

/**
 * 应用启动时调用：用 localStorage 中的 refresh_token 尝试恢复会话。
 *
 * 返回 true 表示会话恢复成功（已拿到新 access_token）。
 * 返回 false 表示 refresh_token 无效/过期，前端应视为未登录。
 */
export async function initAuth() {
  if (_authReady) { console.log('[auth] initAuth: 已完成，accessToken =', !!accessToken); return !!accessToken }

  const rt = getRefreshToken()
  if (!rt) {
    console.log('[auth] initAuth: localStorage 中无 refresh_token → 未登录')
    _authReady = true
    if (_authReadyResolve) { _authReadyResolve(); _authReadyResolve = null }
    return false
  }

  console.log('[auth] initAuth: 检测到 refresh_token，尝试恢复会话...')
  const newToken = await refreshAccessToken()
  _authReady = true
  if (_authReadyResolve) { _authReadyResolve(); _authReadyResolve = null }
  console.log('[auth] initAuth: 结果 =', !!newToken ? '✅ 会话恢复成功' : '❌ 会话恢复失败')
  return !!newToken
}

async function request(url, options = {}) {
  const opts = { ...options }
  opts.headers = { ...opts.headers }

  const noAuthPaths = ['/api/auth/login', '/api/auth/register', '/api/auth/refresh', '/health']
  const path = new URL(url, window.location.origin).pathname

  if (!noAuthPaths.includes(path)) {
    // 如果还没有 access_token，先尝试用 refresh_token 恢复
    if (!accessToken && getRefreshToken()) {
      await refreshAccessToken()
    }
    if (accessToken) {
      opts.headers['Authorization'] = `Bearer ${accessToken}`
    }
  }

  let res = await fetch(`${BASE_URL}${url}`, opts)

  // 401/403 都可能表示 token 问题 → 尝试刷新
  if ((res.status === 401 || res.status === 403) && getRefreshToken()) {
    const newToken = await refreshAccessToken()
    if (newToken) {
      opts.headers['Authorization'] = `Bearer ${newToken}`
      res = await fetch(`${BASE_URL}${url}`, opts)
    }
  }
  return res
}

async function requestJSON(url, options = {}) {
  const res = await request(url, options)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.detail || `请求失败 (${res.status})`)
    err.status = res.status
    err.data = data
    throw err
  }
  return data
}

/* ========== Auth API ========== */
export async function login(username, password) {
  try {
    const data = await requestJSON('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    console.log('[auth] login: 登录成功，收到 access_token =', !!data.access_token, 'refresh_token =', !!data.refresh_token)
    setTokens(data.access_token, data.refresh_token)
    console.log('[auth] login: token 已存储，accessToken =', !!getAccessToken(), 'localStorage =', !!getRefreshToken())
    return data
  } catch (e) {
    console.error('[auth] login: 登录失败', e.message)
    throw e
  }
}

export async function register(username, password, email) {
  const data = await requestJSON('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, email: email || undefined }),
  })
  setTokens(data.access_token, data.refresh_token)
  return data
}

export async function logout() {
  const rt = getRefreshToken()
  try {
    await requestJSON('/api/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt || undefined }),
    })
  } catch { /* ignore */ }
  clearTokens()
}

export async function getMe() {
  return requestJSON('/api/auth/me')
}

/* ========== Chat API ========== */
export async function getSessions() {
  return requestJSON('/api/chat/sessions')
}

export async function getHistory(sessionId) {
  return requestJSON(`/api/chat/history/${sessionId}`)
}

export async function deleteSession(sessionId) {
  return requestJSON(`/api/chat/history/${sessionId}`, { method: 'DELETE' })
}

export async function sendMessage(query, sessionId) {
  const params = new URLSearchParams({ query })
  if (sessionId) params.append('session_id', sessionId)
  return requestJSON(`/api/chat/?${params}`, { method: 'POST' })
}

export async function sendMessageStream(query, sessionId, callbacks = {}) {
  const { onToken, onToolStart, onToolEnd, onSummarize, onSessionEnd, onThinking, onDone, onError, onHallucination } = callbacks

  const params = new URLSearchParams({ query })
  if (sessionId) params.append('session_id', sessionId)

  const url = `${BASE_URL}/api/chat/stream?${params}`

  async function doFetch() {
    const headers = { 'Accept': 'text/event-stream' }
    if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`
    return await fetch(url, { method: 'POST', headers })
  }

  // 如果还没有 access_token，先尝试用 refresh_token 恢复
  if (!accessToken && getRefreshToken()) {
    await refreshAccessToken()
  }

  let response = await doFetch()

  // 401/403 都可能表示 token 问题 → 尝试刷新后重试
  if ((response.status === 401 || response.status === 403) && getRefreshToken()) {
    const newToken = await refreshAccessToken()
    if (newToken) {
      response = await doFetch()
    }
  }

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}))
    const err = new Error(errData.detail || `请求失败 (${response.status})`)
    if (onError) onError(err)
    return null
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()

  let partialLine = ''
  let eventType = ''
  let fullAnswer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const lines = (partialLine + value).split('\n')
      partialLine = lines.pop() || ''

      for (const line of lines) {
        if (line.trim() === '') { eventType = ''; continue }
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (eventType === 'done' || data === '[DONE]') {
            if (onDone) onDone(fullAnswer)
            return fullAnswer
          }
          if (eventType === 'token' || !eventType) {
            fullAnswer += data
            if (onToken) onToken(data, fullAnswer)
          } else if (eventType === 'tool_start') {
            try { if (onToolStart) onToolStart(JSON.parse(data)) } catch { /* */ }
          } else if (eventType === 'tool_end') {
            try { if (onToolEnd) onToolEnd(JSON.parse(data)) } catch { /* */ }
          } else if (eventType === 'summarize') {
            if (onSummarize) onSummarize()
          } else if (eventType === 'session_end') {
            if (onSessionEnd) onSessionEnd()
          } else if (eventType === 'thinking') {
            if (onThinking) onThinking()
          } else if (eventType === 'hallucination') {
            fullAnswer = ''
            if (onHallucination) onHallucination(data)
          }
        }
      }
    }
  } catch (e) {
    if (onError) onError(e)
    return fullAnswer || null
  }

  if (onDone) onDone(fullAnswer)
  return fullAnswer
}

/* ========== Knowledge API ========== */
export async function uploadDocument(file) {
  const formData = new FormData()
  formData.append('file', file)
  return requestJSON('/api/knowledge/upload', {
    method: 'POST',
    body: formData,
  })
}

export async function getDocuments() {
  return requestJSON('/api/knowledge/documents')
}

export async function deleteDocument(docId) {
  return requestJSON(`/api/knowledge/documents/${docId}`, { method: 'DELETE' })
}

export async function getDocumentPreview(docId) {
  return requestJSON(`/api/knowledge/documents/${docId}/preview`)
}

/* ========== User API ========== */
export async function getProfile() {
  return requestJSON('/api/user/profile')
}

export async function updateProfile(email) {
  const params = new URLSearchParams()
  if (email) params.append('email', email)
  return requestJSON(`/api/user/profile?${params}`, { method: 'PUT' })
}

export async function changePassword(oldPassword, newPassword) {
  return requestJSON('/api/user/password', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  })
}

export default {
  setTokens, clearTokens, isAuthenticated, getAccessToken,
  login, register, logout, getMe,
  getSessions, getHistory, deleteSession, sendMessage, sendMessageStream,
  uploadDocument, getDocuments, deleteDocument, getDocumentPreview,
  getProfile, updateProfile, changePassword,
}
