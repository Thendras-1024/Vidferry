import { http } from '@/utils/request'

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL
const apiBaseUrl = configuredApiBaseUrl && configuredApiBaseUrl !== '/'
  ? configuredApiBaseUrl.replace(/\/$/, '')
  : ''

const fileUrl = (filename) => `${apiBaseUrl}/getFile?filename=${encodeURIComponent(filename)}`

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

  deletePublishTargetRecord: (id) => {
    return http.delete(`/publish/target-records/${id}`)
  },
  
  // 下载素材
  downloadMaterial: (filePath) => {
    return fileUrl(filePath)
  },
  
  // 获取素材预览URL
  getMaterialPreviewUrl: (filename) => {
    return fileUrl(filename)
  }
}
