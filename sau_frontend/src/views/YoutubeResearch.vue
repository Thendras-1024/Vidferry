<template>
  <div class="youtube-research">
    <div class="page-header">
      <div>
        <h1>YouTube 视频线索查询</h1>
        <p>查询视频链接，按行下载到本地素材库，后续可继续字幕处理和发布。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="jobsLoading" @click="loadJobs">
          <el-icon><Refresh /></el-icon>
          <span>刷新任务</span>
        </el-button>
        <el-button type="primary" :loading="loading" @click="handleSearch">
          <el-icon><Search /></el-icon>
          <span>开始查询</span>
        </el-button>
      </div>
    </div>

    <el-card class="query-card" shadow="never">
      <el-form :inline="true" :model="form" class="query-form">
        <el-form-item label="关键词">
          <el-input
            v-model="form.query"
            class="query-input"
            clearable
            placeholder="foreigner China travel vlog first time in China"
          />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="form.limit" :min="1" :max="30" controls-position="right" />
        </el-form-item>
        <el-form-item label="发抖音">
          <el-switch v-model="workflowForm.publishToDouyin" />
        </el-form-item>
        <el-form-item label="抖音账号" v-if="workflowForm.publishToDouyin">
          <el-input v-model="workflowForm.account" class="account-input" clearable placeholder="creator" />
        </el-form-item>
        <el-form-item label="发B站">
          <el-switch v-model="workflowForm.publishToBilibili" />
        </el-form-item>
        <el-form-item label="B站账号" v-if="workflowForm.publishToBilibili">
          <el-input v-model="workflowForm.bilibiliAccount" class="account-input" clearable placeholder="creator" />
        </el-form-item>
        <el-form-item label="B站分区" v-if="workflowForm.publishToBilibili">
          <el-input-number v-model="workflowForm.bilibiliTid" :min="1" :max="999" controls-position="right" />
        </el-form-item>
        <el-form-item label="默认话题">
          <el-input v-model="workflowForm.tags" class="tag-input" clearable placeholder="中国旅行,外国人在中国" />
        </el-form-item>
      </el-form>
      <div class="query-meta" v-if="lastResult">
        <span>查询来源：{{ lastResult.source }}</span>
        <span>查询时间：{{ lastResult.searchedAt }}</span>
        <span>本次入库/更新：{{ lastResult.total }}</span>
      </div>
    </el-card>

    <el-card class="result-card" shadow="never">
      <el-table :data="items" v-loading="loading" empty-text="暂无视频记录，点击开始查询获取视频链接" style="width: 100%">
        <el-table-column label="视频" min-width="360">
          <template #default="{ row }">
            <div class="video-cell">
              <img v-if="row.thumbnail" :src="row.thumbnail" alt="" class="thumbnail">
              <div class="video-info">
                <a :href="row.url" target="_blank" rel="noopener noreferrer" class="video-title">
                  {{ row.title || '未获取到标题' }}
                </a>
                <span class="video-url">{{ row.url }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="channel" label="博主名称" width="180" />
        <el-table-column label="博主粉丝数" width="160">
          <template #default="{ row }">
            {{ row.subscribers || '未获取到' }}
          </template>
        </el-table-column>
        <el-table-column label="发布时间" width="160">
          <template #default="{ row }">
            {{ row.publishedAt || '未获取到' }}
          </template>
        </el-table-column>
        <el-table-column prop="duration" label="时长" width="100" />
        <el-table-column label="下载状态" width="130">
          <template #default="{ row }">
            <el-tag :type="row.downloadStatus === 1 ? 'success' : 'info'" effect="plain">
              {{ row.downloadStatus === 1 ? '已下载' : '未下载' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="翻译状态" width="130">
          <template #default="{ row }">
            <el-tag :type="row.translateStatus === 1 ? 'success' : 'info'" effect="plain">
              {{ row.translateStatus === 1 ? '已翻译' : '未翻译' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="发布状态" width="130">
          <template #default="{ row }">
            <el-tag :type="row.publishStatus === 1 ? 'success' : 'info'" effect="plain">
              {{ row.publishStatus === 1 ? '已发布' : '未发布' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="420" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="copyUrl(row.url)">
              <el-icon><DocumentCopy /></el-icon>
              <span>复制</span>
            </el-button>
            <el-button
              text
              type="primary"
              :disabled="row.downloadStatus === 1"
              :loading="downloadingId === row.id"
              @click="downloadVideo(row)"
            >
              <el-icon><Download /></el-icon>
              <span>下载</span>
            </el-button>
            <el-button
              text
              type="warning"
              :disabled="row.downloadStatus !== 1"
              :loading="translatingId === row.id"
              @click="translateVideo(row)"
            >
              <el-icon><VideoCamera /></el-icon>
              <span>翻译</span>
            </el-button>
            <el-button text type="success" :loading="creatingJobId === row.id" @click="createJob(row)">
              <el-icon><VideoPlay /></el-icon>
              <span>一键处理</span>
            </el-button>
            <el-button text type="danger" :loading="deletingId === row.id" @click="deleteVideo(row)">
              <el-icon><Delete /></el-icon>
              <span>删除</span>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="job-card" shadow="never">
      <template #header>
        <div class="job-card-header">
          <span>工作流任务</span>
          <el-button text type="primary" :loading="jobsLoading" @click="loadJobs">刷新</el-button>
        </div>
      </template>
      <el-table :data="jobs" v-loading="jobsLoading" empty-text="暂无任务" style="width: 100%">
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="account" label="抖音账号" width="120" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="jobStatusType(row.status)">{{ jobStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="step" label="步骤" width="110" />
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <el-progress :percentage="Number(row.progress || 0)" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="速率" width="120">
          <template #default="{ row }">
            {{ row.speed || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="剩余" width="90">
          <template #default="{ row }">
            {{ row.eta || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="message" label="消息" min-width="220" show-overflow-tooltip />
        <el-table-column prop="updatedAt" label="更新时间" width="170" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentCopy, Download, Refresh, Search, VideoCamera, VideoPlay } from '@element-plus/icons-vue'
import { youtubeApi } from '@/api/youtube'

const loading = ref(false)
const jobsLoading = ref(false)
const downloadingId = ref('')
const translatingId = ref('')
const creatingJobId = ref('')
const deletingId = ref('')
const items = ref([])
const jobs = ref([])
const lastResult = ref(null)
let jobsTimer = null

const form = reactive({
  query: 'foreigner China travel vlog first time in China',
  limit: 12
})

const workflowForm = reactive({
  publishToDouyin: true,
  account: 'creator',
  publishToBilibili: false,
  bilibiliAccount: 'creator',
  bilibiliTid: 249,
  tags: '中国旅行,外国人在中国'
})

const handleSearch = async () => {
  loading.value = true
  try {
    const res = await youtubeApi.search({
      query: form.query,
      limit: form.limit
    })
    lastResult.value = res.data
    await loadVideos(false)
    ElMessage.success(`查询完成，入库/更新 ${res.data.total} 条视频`)
  } catch (error) {
  } finally {
    loading.value = false
  }
}

const loadVideos = async (showLoading = true) => {
  if (showLoading) loading.value = true
  try {
    const res = await youtubeApi.list()
    items.value = res.data.items || []
  } finally {
    if (showLoading) loading.value = false
  }
}

const loadJobs = async () => {
  jobsLoading.value = true
  try {
    const res = await youtubeApi.listWorkflowJobs({ limit: 50 })
    jobs.value = res.data.items || []
  } finally {
    jobsLoading.value = false
  }
}

const startJobsPolling = () => {
  if (jobsTimer) return
  jobsTimer = window.setInterval(() => {
    if (jobs.value.some(job => job.status === 'queued' || job.status === 'running')) {
      loadJobs()
      loadVideos(false)
    }
  }, 1500)
}

const createJob = async (row) => {
  creatingJobId.value = row.id
  try {
    const res = await youtubeApi.createWorkflowJob({
      videoId: row.id,
      url: row.url,
      account: workflowForm.account.trim(),
      publishToDouyin: workflowForm.publishToDouyin,
      publishToBilibili: workflowForm.publishToBilibili,
      bilibiliAccount: workflowForm.bilibiliAccount.trim(),
      bilibiliTid: workflowForm.bilibiliTid,
      channel: row.channel,
      subscribers: row.subscribers,
      publishedAt: row.publishedAt,
      title: row.title || 'YouTube 视频',
      description: '',
      tags: workflowForm.tags,
      schedule: ''
    })
    jobs.value.unshift(res.data)
    ElMessage.success('工作流任务已创建')
    startJobsPolling()
  } finally {
    creatingJobId.value = ''
  }
}

const downloadVideo = async (row) => {
  if (row.downloadStatus === 1) {
    ElMessage.info('该视频已下载')
    return
  }
  downloadingId.value = row.id
  try {
    const res = await youtubeApi.createDownloadJob({
      videoId: row.id,
      url: row.url,
      channel: row.channel,
      subscribers: row.subscribers,
      publishedAt: row.publishedAt,
      title: row.title || 'YouTube 视频'
    })
    jobs.value.unshift(res.data)
    ElMessage.success('下载任务已创建')
    startJobsPolling()
    setTimeout(() => {
      loadJobs()
      loadVideos(false)
    }, 1500)
  } finally {
    downloadingId.value = ''
  }
}

const deleteVideo = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定删除视频线索「${row.title || row.url}」吗？已下载的素材文件不会被删除。`,
      '删除视频线索',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch (error) {
    return
  }

  deletingId.value = row.id
  try {
    await youtubeApi.deleteVideo(row.id)
    items.value = items.value.filter(item => item.id !== row.id)
    ElMessage.success('视频线索已删除')
  } finally {
    deletingId.value = ''
  }
}

const translateVideo = async (row) => {
  if (row.downloadStatus !== 1) {
    ElMessage.warning('请先下载视频，再进行翻译')
    return
  }
  translatingId.value = row.id
  try {
    const res = await youtubeApi.createTranslateJob({
      videoId: row.id,
      url: row.url,
      channel: row.channel,
      subscribers: row.subscribers,
      publishedAt: row.publishedAt,
      title: row.title || 'YouTube 视频',
      tags: workflowForm.tags
    })
    jobs.value.unshift(res.data)
    ElMessage.success('翻译任务已创建')
    startJobsPolling()
    setTimeout(() => {
      loadJobs()
      loadVideos(false)
    }, 1500)
  } finally {
    translatingId.value = ''
  }
}

const jobStatusText = (status) => {
  const map = {
    queued: '排队中',
    running: '执行中',
    success: '成功',
    failed: '失败'
  }
  return map[status] || status || '-'
}

const jobStatusType = (status) => {
  const map = {
    queued: 'info',
    running: 'warning',
    success: 'success',
    failed: 'danger'
  }
  return map[status] || 'info'
}

const copyUrl = async (url) => {
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('链接已复制')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

onMounted(() => {
  loadVideos()
  loadJobs()
  startJobsPolling()
})

onBeforeUnmount(() => {
  if (jobsTimer) {
    window.clearInterval(jobsTimer)
    jobsTimer = null
  }
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.youtube-research {
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;

    h1 {
      margin: 0;
      font-size: 24px;
      color: $text-primary;
    }

    p {
      margin: 8px 0 0;
      color: $text-secondary;
      font-size: 14px;
    }
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .query-card {
    margin-bottom: 16px;
    border-radius: 6px;
  }

  .query-form {
    display: flex;
    align-items: center;
    flex-wrap: wrap;

    :deep(.el-form-item) {
      margin-bottom: 0;
    }
  }

  .query-input {
    width: min(520px, 60vw);
  }

  .account-input {
    width: 160px;
  }

  .tag-input {
    width: 260px;
  }

  .query-meta {
    display: flex;
    gap: 18px;
    flex-wrap: wrap;
    margin-top: 14px;
    color: $text-secondary;
    font-size: 13px;
  }

  .result-card {
    margin-bottom: 16px;
    border-radius: 6px;
  }

  .job-card {
    border-radius: 6px;
  }

  .job-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .video-cell {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }

  .thumbnail {
    width: 112px;
    height: 63px;
    object-fit: cover;
    border-radius: 4px;
    background: $border-extra-light;
    flex: 0 0 auto;
  }

  .video-info {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .video-title {
    color: $text-primary;
    font-weight: 600;
    line-height: 1.4;
    text-decoration: none;

    &:hover {
      color: $primary-color;
    }
  }

  .video-url {
    color: $text-secondary;
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 560px;
  }
}

@media (max-width: 760px) {
  .youtube-research {
    .page-header {
      align-items: flex-start;
      flex-direction: column;
    }

    .query-input {
      width: 100%;
    }

    .video-url {
      max-width: 240px;
    }
  }
}
</style>
