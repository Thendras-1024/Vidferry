import axios from 'axios'
import { ElMessage } from 'element-plus'
import { clearAuthSession, getCsrfToken } from '@/auth/session'

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL
const apiBaseURL = configuredApiBaseUrl && configuredApiBaseUrl !== '/'
  ? configuredApiBaseUrl
  : (import.meta.env.DEV ? '/api' : '')

// 创建axios实例
const request = axios.create({
  baseURL: apiBaseURL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    const method = String(config.method || 'get').toUpperCase()
    const csrfToken = getCsrfToken()
    if (csrfToken && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      config.headers['X-CSRF-Token'] = csrfToken
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
    if ((Number(data.code) >= 200 && Number(data.code) < 300) || data.success) {
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
          clearAuthSession()
          if (window.location.hash !== '#/login') window.location.hash = '#/login'
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

export const streamSse = async (url, onMessage, signal) => {
  const response = await fetch(`${apiBaseURL}${url}`, {
    credentials: 'include',
    headers: { 'X-CSRF-Token': getCsrfToken() },
    signal
  })
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.msg || `请求失败 : ${response.status}`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split(/\r?\n\r?\n/)
    buffer = events.pop() || ''
    for (const event of events) {
      const data = event.split(/\r?\n/)
        .filter(line => line.startsWith('data:'))
        .map(line => line.slice(5).trimStart())
        .join('\n')
      if (data) onMessage(data)
    }
  }
}

export default request
