import request from '@/utils/request'

export const notificationApi = {
  summary() {
    return request.get('/notifications/summary', { silentError: true })
  },

  list(params = {}) {
    return request.get('/notifications', { params, silentError: true })
  },

  update(notificationId, data) {
    return request.patch(`/notifications/${notificationId}`, data, { silentError: true })
  },

  createDirectPublishFailure(data) {
    return request.post('/notifications/direct-publish-failure', data, { silentError: true })
  }
}
