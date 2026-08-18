import request from '@/utils/request'

export const userApi = {
  login(data) { return request.post('/auth/login', data, { silentError: true }) },
  authPublicConfig() { return request.get('/auth/public-config', { silentError: true }) },
  sendPhoneCode(data) { return request.post('/auth/phone/send-code', data, { silentError: true }) },
  phoneLogin(data) { return request.post('/auth/phone/login', data, { silentError: true }) },
  me() { return request.get('/auth/me', { silentError: true }) },
  updateProfile(data) { return request.patch('/auth/profile', data, { silentError: true }) },
  logout() { return request.post('/auth/logout') },
  logoutAll() { return request.post('/auth/logout-all') },
  changePassword(data) { return request.post('/auth/change-password', data) },
  listUsers(params) { return request.get('/admin/users', { params }) },
  createUser(data) { return request.post('/admin/users', data) },
  updateUser(id, data) { return request.patch(`/admin/users/${id}`, data) },
  resetPassword(id, password) { return request.post(`/admin/users/${id}/reset-password`, { password }) },
  unlockUser(id) { return request.post(`/admin/users/${id}/unlock`) },
  revokeSessions(id) { return request.post(`/admin/users/${id}/revoke-sessions`) },
  listAuditLogs(params) { return request.get('/admin/audit-logs', { params }) }
}
