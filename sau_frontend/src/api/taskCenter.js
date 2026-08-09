import request from '@/utils/request'

export const taskCenterApi = {
  list(params = {}) {
    return request.get('/task-center', { params, silentError: true })
  },

  detail(taskKey) {
    return request.get(`/task-center/${encodeURIComponent(taskKey)}`, { silentError: true })
  },

  acknowledge(taskKey) {
    return request.post(`/task-center/${encodeURIComponent(taskKey)}/acknowledge`, {}, { silentError: true })
  },
}
