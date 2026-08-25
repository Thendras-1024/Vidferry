import { http } from '@/utils/request'

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL
const apiBaseUrl = configuredApiBaseUrl && configuredApiBaseUrl !== '/'
  ? configuredApiBaseUrl.replace(/\/$/, '')
  : (import.meta.env.DEV ? '/api' : '')

const fileUrl = (assetId, download = false) => {
  const suffix = download ? '?download=1' : ''
  return `${apiBaseUrl}/assets/${encodeURIComponent(assetId)}/content${suffix}`
}

// 素材管理API
export const materialApi = {
  // 获取所有素材
  getAllMaterials: (params = {}) => {
    return http.get('/getFiles', params)
  },
  
  // 上传素材
  uploadMaterial: (formData, onUploadProgress) => {
    // 使用http.upload方法，它已经配置了正确的Content-Type
    return http.upload('/uploadSave', formData, onUploadProgress)
  },
  
  // 删除素材
  deleteMaterial: (id) => {
    return http.delete('/deleteFile', { id })
  },

  deleteMaterials: (ids) => {
    return http.post('/deleteFiles', { ids })
  },

  getPublishedMaterials: (params = {}) => {
    return http.get('/published-materials', params)
  },

  getPublishTasks: (params = {}) => {
    return http.get('/publish/tasks', params)
  },

  getPublishTask: (taskId) => {
    return http.get(`/publish/tasks/${encodeURIComponent(taskId)}`, undefined, { silentError: true })
  },

  retryFailedPublishTask: (taskId, targetRecordIds, riskOverride = {}, config = {}) => {
    return http.post(`/publish/tasks/${encodeURIComponent(taskId)}/retry-failed`, { targetRecordIds, riskOverride }, config)
  },

  getScheduledPublishTasks: (params = {}) => {
    return http.get('/publish/scheduled-tasks', params)
  },

  cancelScheduledPublishTask: (taskId) => {
    return http.post(`/publish/scheduled-tasks/${taskId}/cancel`)
  },

  deletePublishTargetRecord: (id) => {
    return http.delete(`/publish/target-records/${id}`)
  },

  releaseUnknownPublishRecord: (id, reason = '') => {
    return http.post(`/publish/target-records/${id}/release-unknown`, { confirmed: true, reason })
  },
  
  // 下载素材
  downloadMaterial: (assetId) => {
    return fileUrl(assetId, true)
  },
  
  // 获取素材预览URL
  getMaterialPreviewUrl: (assetId) => {
    return fileUrl(assetId)
  }
}
