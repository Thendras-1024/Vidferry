import request from '@/utils/request'

export const subtitleAuditApi = {
  list(params = {}) {
    return request.get('/admin/subtitle-audits', { params })
  },
  detail(jobId) {
    return request.get(`/admin/subtitle-audits/${jobId}`)
  },
  remove(jobIds) {
    return request.delete('/admin/subtitle-audits', { data: { jobIds } })
  }
}
