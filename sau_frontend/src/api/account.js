import { http, streamSse } from '@/utils/request'

// 账号管理相关API
export const accountApi = {
  // 获取有效账号列表（带验证）
  getValidAccounts() {
    return http.get('/getValidAccounts')
  },

  // 获取账号列表（不带验证，快速加载）
  getAccounts() {
    return http.get('/getAccounts')
  },

  checkCookies(data = {}) {
    return http.post('/accounts/check-cookies', data)
  },

  importCookie(formData) {
    return http.upload('/accounts/import-cookie', formData, undefined, { silentError: true })
  },

  // 添加账号
  addAccount(data) {
    return http.post('/account', data)
  },

  // 更新账号
  updateAccount(data) {
    return http.post('/updateUserinfo', data)
  },

  // 删除账号
  deleteAccount(id) {
    return http.delete('/deleteAccount', { id })
  },

  getPublishAccountGroups() {
    return http.get('/publish/account-groups')
  },

  createPublishAccountGroup(data) {
    return http.post('/publish/account-groups', data)
  },

  updatePublishAccountGroup(id, data) {
    return http.patch(`/publish/account-groups/${id}`, data)
  },

  deletePublishAccountGroup(id) {
    return http.delete(`/publish/account-groups/${id}`)
  },

  loginStream(params, onMessage, signal) {
    return streamSse(`/login?${new URLSearchParams(params).toString()}`, onMessage, signal)
  }
}
