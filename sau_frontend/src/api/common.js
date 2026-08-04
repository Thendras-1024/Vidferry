import request from '@/utils/request'

export const commonApi = {
  getRuntimeConfigStatus() {
    return request.get('/runtime/config-status', { silentError: true })
  },

  getFeishuRobotStatus() {
    return request.get('/feishu/robot-status', { silentError: true })
  }
}
