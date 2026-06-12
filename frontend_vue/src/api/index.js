/* ============================================================
   API Client — JWT Token 管理 + 自动刷新 + 请求封装
   ============================================================ */

const BASE_URL = ''  // Vite proxy handles /api → localhost:8000

// Token 存储（access_token 用内存变量，refresh_token 持久化到 localStorage）
let accessToken = null
const REFRESH_KEY = 'rag_refresh_token'

function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY)
}
function setRefreshToken(token) {
  if (token) localStorage.setItem(REFRESH_KEY, token)
  else localStorage.removeItem(REFRESH_KEY)
}
function getAccessToken() {
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
export function isAuthenticated() {
  return !!(accessToken || getRefreshToken())
}

async function refreshAccessToken() {
  const rt = getRefreshToken()
  if (!rt) return null
  try {
    const res = await fetch(`${BASE_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
    if (!res.ok) { clearTokens(); return null }
    const data = await res.json()
    setTokens(data.access_token, data.refresh_token)
    return data.access_token
  } catch {
    return null
  }
}

async function request(url, options = {}) {
  const opts = { ...options }
  opts.headers = { ...opts.headers }

  const noAuthPaths = ['/api/auth/login', '/api/auth/register', '/api/auth/refresh', '/health']
  const path = new URL(url, window.location.origin).pathname
  if (!noAuthPaths.includes(path) && accessToken) {
    opts.headers['Authorization'] = `Bearer ${accessToken}`
  }

  let res = await fetch(`${BASE_URL}${url}`, opts)

  if (res.status === 401 && accessToken) {
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
  const data = await requestJSON('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  setTokens(data.access_token, data.refresh_token)
  return data
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
  try { await requestJSON('/api/auth/logout', { method: 'POST' }) } catch { /* ignore */ }
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
  const { onToken, onToolStart, onToolEnd, onSummarize, onSessionEnd, onThinking, onDone, onError } = callbacks

  const params = new URLSearchParams({ query })
  if (sessionId) params.append('session_id', sessionId)

  const url = `${BASE_URL}/api/chat/stream?${params}`
  const headers = { 'Accept': 'text/event-stream' }
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`

  let response = await fetch(url, { method: 'POST', headers })

  if (response.status === 401 && accessToken) {
    const newToken = await refreshAccessToken()
    if (newToken) {
      headers['Authorization'] = `Bearer ${newToken}`
      response = await fetch(url, { method: 'POST', headers })
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
