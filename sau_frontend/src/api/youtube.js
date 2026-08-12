import request from '@/utils/request'

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL
const apiBaseUrl = configuredApiBaseUrl && configuredApiBaseUrl !== '/'
  ? configuredApiBaseUrl.replace(/\/$/, '')
  : (import.meta.env.DEV ? '/api' : '')

export const youtubeApi = {
  search(params = {}) {
    return request.get('/youtube/search', { params })
  },

  createSearchJob(data) {
    return request.post('/youtube/search/jobs', data)
  },

  getSearchJob(jobId) {
    return request.get(`/youtube/search/jobs/${jobId}`, { silentError: true })
  },

  list(params = {}) {
    return request.get('/youtube/videos', { params })
  },

  importVideo(data) {
    return request.post('/youtube/videos/import', data)
  },

  getVideoGroups() {
    return request.get('/youtube/video-groups')
  },

  createVideoGroup(data) {
    return request.post('/youtube/video-groups', data)
  },

  renameVideoGroup(groupId, data) {
    return request.patch(`/youtube/video-groups/${groupId}`, data)
  },

  deleteVideoGroup(groupId) {
    return request.delete(`/youtube/video-groups/${groupId}`)
  },

  moveVideosToGroup(data) {
    return request.patch('/youtube/videos/group', data)
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

  createEditingIntroJob(data) {
    return request.post('/youtube/editing/intro/jobs', data)
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

  getWorkflowJob(jobId, config = {}) {
    return request.get(`/youtube/workflow/jobs/${jobId}`, config)
  },

  confirmWorkflowPublish(jobId, confirmed) {
    return request.post(`/youtube/workflow/jobs/${jobId}/publish-confirmation`, { confirmed })
  },

  confirmContentSafety(jobId, data) {
    return request.post(`/youtube/workflow/jobs/${jobId}/content-safety-confirmation`, data)
  },

  getSourcePreviewUrl(jobId) {
    return `${apiBaseUrl}/youtube/workflow/jobs/${encodeURIComponent(jobId)}/source-preview`
  },

  getWorkflowStatistics(params = {}) {
    return request.get('/youtube/workflow/statistics', { params })
  },

  getWorkflowTaskStatistics(jobId) {
    return request.get(`/youtube/workflow/statistics/tasks/${jobId}`)
  },

  getBilibiliCategories() {
    return request.get('/bilibili/categories')
  },

  getWorkflowSettings() {
    return request.get('/youtube/workflow/settings')
  },

  updateWorkflowSettings(data) {
    return request.put('/youtube/workflow/settings', data)
  }
}
