import request from '@/utils/request'

export const youtubeApi = {
  search(params = {}) {
    return request.get('/youtube/search', { params })
  },

  list() {
    return request.get('/youtube/videos')
  },

  importVideo(data) {
    return request.post('/youtube/videos/import', data)
  },

  updateStatus(videoId, data) {
    return request.patch(`/youtube/videos/${videoId}/status`, data)
  },

  resetProcessing(videoId, data = {}) {
    return request.post(`/youtube/videos/${videoId}/reset-processing`, data)
  },

  deleteVideo(videoId) {
    return request.delete(`/youtube/videos/${videoId}`)
  },

  deleteVideos(videoIds) {
    return request.post('/youtube/videos/batch-delete-items', { videoIds })
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

  createAnalysisJob(data) {
    return request.post('/youtube/analysis/jobs', data)
  },

  getVideoAnalysis(videoId) {
    return request.get(`/youtube/videos/${videoId}/analysis`)
  },

  updateVideoAnalysis(videoId, data) {
    return request.patch(`/youtube/videos/${videoId}/analysis`, data)
  },

  updatePublishDraft(videoId, data) {
    return request.patch(`/youtube/videos/${videoId}/publish-draft`, data)
  },

  listWorkflowJobs(params = {}) {
    return request.get('/youtube/workflow/jobs', { params })
  },

  getWorkflowJob(jobId) {
    return request.get(`/youtube/workflow/jobs/${jobId}`)
  },

  getWorkflowStatistics(params = {}) {
    return request.get('/youtube/workflow/statistics', { params })
  }
}
