import axios from 'axios'
import { ElMessage } from 'element-plus'

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL
const apiBaseURL = configuredApiBaseUrl && configuredApiBaseUrl !== '/'
  ? configuredApiBaseUrl
  : (import.meta.env.DEV ? '/api' : '')

// 创建axios实例
const request = axios.create({
  baseURL: apiBaseURL,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 可以在这里添加token等认证信息
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  (response) => {
    const { data } = response
    
    // 根据后端接口规范处理响应
    if (data.code === 200 || data.success) {
      return data
    } else {
      if (response.config?.silentError) {
        return Promise.reject(new Error(data.msg || data.message || '请求失败'))
      }
      ElMessage.error(data.msg || data.message || '请求失败')
      return Promise.reject(new Error(data.msg || data.message || '请求失败'))
    }
  },
  (error) => {
    console.error('响应错误:', error)
    if (error.config?.silentError) {
      return Promise.reject(error)
    }
    
    // 处理HTTP错误状态码
    if (error.response) {
      const { status } = error.response
      const serverMessage = error.response.data?.msg || error.response.data?.message
      if (serverMessage) {
        if (status === 409) {
          ElMessage.warning(serverMessage)
        } else {
          ElMessage.error(serverMessage)
        }
        return Promise.reject(new Error(serverMessage))
      }
      switch (status) {
        case 401:
          ElMessage.error('未授权，请重新登录')
          // 可以在这里处理登录跳转
          break
        case 403:
          ElMessage.error('拒绝访问')
          break
        case 404:
          ElMessage.error('请求地址不存在')
          break
        case 500:
          ElMessage.error('服务器内部错误')
          break
        default:
          ElMessage.error('网络错误')
      }
    } else {
      ElMessage.error('网络连接失败')
    }
    
    return Promise.reject(error)
  }
)

// 封装常用的请求方法
export const http = {
  get(url, params) {
    return request.get(url, { params })
  },
  
  post(url, data, config = {}) {
    return request.post(url, data, config)
  },
  
  put(url, data, config = {}) {
    return request.put(url, data, config)
  },
  
  delete(url, params) {
    return request.delete(url, { params })
  },
  
  upload(url, formData, onUploadProgress) {
    return request.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      },
      onUploadProgress
    })
  }
}

export default request
