import request from '@/utils/request'
import { getCsrfToken } from '@/auth/session'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL && import.meta.env.VITE_API_BASE_URL !== '/'
  ? import.meta.env.VITE_API_BASE_URL
  : (import.meta.env.DEV ? '/api' : '')

const parseSse = async (response, onEvent) => {
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.msg || 'Agent 流式响应不可用')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let event = 'message'
  let data = ''
  const dispatch = () => {
    if (!data) return
    let payload
    try {
      payload = JSON.parse(data)
    } catch (error) {
      console.warn('解析 Agent SSE 事件失败:', error)
      event = 'message'
      data = ''
      return
    }
    onEvent(event, payload)
    event = 'message'
    data = ''
  }
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const lines = buffer.split(/\r?\n/)
    buffer = done ? '' : lines.pop()
    lines.forEach(line => {
      if (!line) return dispatch()
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) data += line.slice(5).trim()
    })
    if (done) {
      dispatch()
      return
    }
  }
}

export const agentApi = {
  status() {
    return request.get('/agents/status')
  },

  chat(data) {
    return request.post('/agents/chat', data, { silentError: true })
  },

  async chatStream(data, onEvent) {
    const response = await fetch(`${apiBaseUrl}/agents/chat/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCsrfToken()
      },
      body: JSON.stringify(data)
    })
    return parseSse(response, onEvent)
  },

  getMessages(sessionId, limit = 12, beforeId = null) {
    return request.get(`/agents/sessions/${encodeURIComponent(sessionId)}/messages`, {
      limit,
      ...(beforeId ? { beforeId } : {})
    })
  },

  getSessions(params = {}) {
    return request.get('/agents/sessions', params)
  },

  getSession(sessionId) {
    return request.get(`/agents/sessions/${encodeURIComponent(sessionId)}`)
  },

  deleteSession(sessionId) {
    return request.delete(`/agents/sessions/${encodeURIComponent(sessionId)}`)
  },

  compactSession(sessionId) {
    return request.post(`/agents/sessions/${encodeURIComponent(sessionId)}/compact`, {})
  },

  getSessionContext(sessionId) {
    return request.get(`/agents/sessions/${encodeURIComponent(sessionId)}/context`)
  },

  async compactSessionStream(sessionId, onEvent) {
    const response = await fetch(`${apiBaseUrl}/agents/sessions/${encodeURIComponent(sessionId)}/compact/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRF-Token': getCsrfToken() }
    })
    return parseSse(response, onEvent)
  },

  prepublishCheck(data) {
    return request.post('/agents/prepublish-check', data, { silentError: true })
  },

  latestPrepublishCheck(data) {
    return request.post('/agents/prepublish-check/latest', data, { silentError: true })
  },

  getRun(runId) {
    return request.get(`/agents/runs/${runId}`)
  }
}
