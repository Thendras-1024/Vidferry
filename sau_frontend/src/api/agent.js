import request from '@/utils/request'

export const agentApi = {
  status() {
    return request.get('/agents/status')
  },

  chat(data) {
    return request.post('/agents/chat', data, { silentError: true })
  },

  prepublishCheck(data) {
    return request.post('/agents/prepublish-check', data, { silentError: true })
  },

  getRun(runId) {
    return request.get(`/agents/runs/${runId}`)
  }
}

