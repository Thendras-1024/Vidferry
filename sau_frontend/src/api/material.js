import { http } from '@/utils/request'

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
    return http.get(`/deleteFile?id=${id}`)
  },

  deleteMaterials: (ids) => {
    return http.post('/deleteFiles', { ids })
  },

  getPublishedMaterials: (params = {}) => {
    return http.get('/published-materials', params)
  },
  
  // 下载素材
  downloadMaterial: (filePath) => {
    return `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:5409'}/download/${encodeURIComponent(filePath)}`
  },
  
  // 获取素材预览URL
  getMaterialPreviewUrl: (filename) => {
    return `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:5409'}/getFile?filename=${encodeURIComponent(filename)}`
  }
}
