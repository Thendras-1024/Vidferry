import request from '@/utils/request'

export const subtitleAuditApi = {
  list(params = {}) {
    return request.get('/subtitle-audits', { params })
  },
  detail(jobId) {
    return request.get(`/subtitle-audits/${jobId}`)
  },
  remove(jobIds) {
    return request.delete('/subtitle-audits', { data: { jobIds } })
  }
}
