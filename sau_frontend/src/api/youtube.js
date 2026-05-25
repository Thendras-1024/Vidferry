import request from '@/utils/request'

export const youtubeApi = {
  search(params = {}) {
    return request.get('/youtube/search', { params })
  },

  list() {
    return request.get('/youtube/videos')
  },

  updateStatus(videoId, data) {
    return request.patch(`/youtube/videos/${videoId}/status`, data)
  },

  deleteVideo(videoId) {
    return request.delete(`/youtube/videos/${videoId}`)
  },

  createWorkflowJob(data) {
    return request.post('/youtube/workflow/jobs', data)
  },

  createDownloadJob(data) {
    return request.post('/youtube/download/jobs', data)
  },

  createTranslateJob(data) {
    return request.post('/youtube/translate/jobs', data)
  },

  listWorkflowJobs(params = {}) {
    return request.get('/youtube/workflow/jobs', { params })
  },

  getWorkflowJob(jobId) {
    return request.get(`/youtube/workflow/jobs/${jobId}`)
  }
}
