import request, { http } from '@/utils/request'

export const shortVideoApi = {
  listProjects: () => request.get('/short-video/projects'),
  createProject: data => request.post('/short-video/projects', data),
  getProject: id => request.get(`/short-video/projects/${id}`, { silentError: true }),
  search: id => request.post(`/short-video/projects/${id}/search`),
  saveCandidates: (id, candidates) => request.put(`/short-video/projects/${id}/candidates`, { candidates }),
  reviewCandidate: (projectId, candidateId) => request.post(`/short-video/projects/${projectId}/candidates/${candidateId}/review`),
  render: (id, data) => request.post(`/short-video/projects/${id}/render`, data),
  listBgm: () => request.get('/short-video/bgm'),
  listAdminBgm: () => request.get('/admin/short-video/bgm'),
  uploadBgm: form => http.upload('/admin/short-video/bgm', form),
  updateBgm: (id, data) => request.patch(`/admin/short-video/bgm/${id}`, data),
  deleteBgm: id => request.delete(`/admin/short-video/bgm/${id}`),
  addChannel: data => request.post('/admin/short-video/channels', data),
  listChannels: () => request.get('/admin/short-video/channels'),
  deleteChannel: id => request.delete(`/admin/short-video/channels/${id}`)
}
