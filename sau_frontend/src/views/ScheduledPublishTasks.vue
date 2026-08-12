<template>
  <div class="scheduled-tasks-page">
    <header class="page-heading">
      <div>
        <span class="eyebrow">SCHEDULE QUEUE</span>
        <h1>定时发布任务列表</h1>
        <p>按计划时间跟踪视频及各平台账号的执行结果。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
    </header>

    <section class="queue-summary" aria-label="定时任务汇总">
      <button
        v-for="item in summaryItems"
        :key="item.value"
        type="button"
        :class="{ active: filter.status === item.value }"
        @click="selectStatus(item.value)"
      >
        <span>{{ item.label }}</span>
        <strong>{{ item.count }}</strong>
      </button>
    </section>

    <section class="task-panel">
      <div class="panel-toolbar">
        <el-input
          v-model="filter.keyword"
          :prefix-icon="Search"
          clearable
          placeholder="搜索视频标题或视频 ID"
          @keyup.enter="applyKeyword"
          @clear="applyKeyword"
        />
        <el-button type="primary" @click="applyKeyword">查询</el-button>
      </div>

      <el-table v-loading="loading" :data="tasks" row-key="id" empty-text="暂无定时发布任务">
        <el-table-column type="expand" width="48">
          <template #default="{ row }">
            <div class="target-list">
              <div v-for="target in row.targets" :key="target.id" class="target-row">
                <div>
                  <strong>{{ target.platformName }}</strong>
                  <span>{{ target.accountName || '账号已删除' }}</span>
                </div>
                <el-tag size="small" :type="statusType(target.status)" effect="plain">
                  {{ statusLabel(target.status) }}
                </el-tag>
                <span>{{ formatDuration(target.durationMs) }}</span>
                <p>{{ target.message || '等待执行' }}</p>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="计划时间" width="190">
          <template #default="{ row }">
            <div class="time-cell">
              <strong>{{ formatTime(row.scheduledAt) }}</strong>
              <el-tag v-if="row.overdue" size="small" type="warning" effect="plain">逾期补发</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="视频" min-width="300">
          <template #default="{ row }">
            <div class="video-cell">
              <img v-if="row.thumbnail" :src="row.thumbnail" alt="">
              <div>
                <strong>{{ row.title }}</strong>
                <span>{{ row.videoId }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="平台结果" width="180">
          <template #default="{ row }">
            <div class="result-summary">
              <span class="success">成功 {{ row.summary?.success || 0 }}</span>
              <span class="failed">失败 {{ row.summary?.failed || 0 }}</span>
              <span>共 {{ row.summary?.total || 0 }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="实际执行" width="180">
          <template #default="{ row }">{{ formatTime(row.startedAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" size="small" type="danger" plain @click="cancelTask(row)">
              取消任务
            </el-button>
            <span v-else class="muted">不可取消</span>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > filter.pageSize"
        v-model:current-page="filter.page"
        :page-size="filter.pageSize"
        :total="total"
        layout="total, prev, pager, next"
        background
        @current-change="loadTasks"
      />
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { materialApi } from '@/api/material'
import { youtubeApi } from '@/api/youtube'

const tasks = ref([])
const total = ref(0)
const loading = ref(false)
const summary = ref({})
const filter = reactive({ status: 'all', keyword: '', page: 1, pageSize: 20 })
let pollTimer = null

const summaryItems = computed(() => [
  { label: '全部', value: 'all', count: summary.value.all || 0 },
  { label: '未执行', value: 'pending', count: summary.value.pending || 0 },
  { label: '排队中', value: 'queued', count: summary.value.queued || 0 },
  { label: '平台已排期', value: 'scheduled', count: summary.value.scheduled || 0 },
  { label: '执行中', value: 'running', count: summary.value.running || 0 },
  { label: '已完成', value: 'success', count: summary.value.success || 0 },
  { label: '执行失败', value: 'failed', count: summary.value.failed || 0 },
  { label: '已取消', value: 'canceled', count: summary.value.canceled || 0 }
])

const statusLabel = (status) => ({
  pending: '未执行', queued: '排队中', running: '执行中', success: '已完成', partial: '部分失败',
  failed: '执行失败', timeout: '执行超时', unknown: '待核验', canceled: '已取消',
  scheduled: '已提交平台定时'
}[status] || status || '-')

const statusType = (status) => ({
  pending: 'info', queued: 'primary', running: 'primary', success: 'success', partial: 'warning',
  failed: 'danger', timeout: 'danger', unknown: 'warning', canceled: 'info', scheduled: 'primary'
}[status] || 'info')

const formatTime = (value) => value ? String(value).replace('T', ' ').slice(0, 16) : '-'
const formatDuration = (value) => Number(value || 0) > 0 ? `${(Number(value) / 1000).toFixed(1)} 秒` : '-'

const workflowScheduledTask = (job) => {
  const workflowStatus = job.status === 'failed' || job.status === 'abnormal'
    ? 'failed'
    : ['queued', 'running', 'waiting_confirmation', 'waiting_publish'].includes(job.status) ? 'running' : 'scheduled'
  const targetSpecs = [
    [3, '抖音', 'account'], [5, 'B站', 'bilibiliAccount'], [1, '小红书', 'xiaohongshuAccount'],
    [4, '快手', 'kuaishouAccount'], [2, '视频号', 'tencentAccount']
  ]
  const targets = targetSpecs
    .filter(([, , accountKey]) => job[accountKey])
    .map(([platformType, platformName, accountKey]) => ({
      id: `${job.id}-${platformType}`,
      platformType,
      platformName,
      accountName: job[accountKey],
      status: workflowStatus,
      message: workflowStatus === 'scheduled' ? '已提交平台定时发布' : (job.errorReason || job.message || '工作流处理中'),
      durationMs: 0
    }))
  return {
    id: `workflow-${job.id}`,
    source: 'workflow',
    videoId: job.videoId,
    title: job.title || '未命名视频',
    thumbnail: '',
    scheduledAt: job.schedule,
    status: workflowStatus,
    overdue: false,
    message: job.errorReason || job.message || (workflowStatus === 'scheduled' ? '已提交平台定时发布' : '工作流处理中'),
    summary: { success: 0, failed: workflowStatus === 'failed' ? targets.length : 0, total: targets.length },
    targets,
    startedAt: '',
    createdAt: job.createdAt || ''
  }
}

const loadTasks = async () => {
  loading.value = true
  try {
    const [response, workflowResponse] = await Promise.all([
      materialApi.getScheduledPublishTasks(filter),
      youtubeApi.listWorkflowJobs({ page: 1, pageSize: 100, hasSchedule: true })
    ])
    const localTasks = response.data?.items || []
    const workflowTasks = (workflowResponse.data?.items || []).map(workflowScheduledTask)
      .filter(task => !filter.keyword || task.title.includes(filter.keyword) || task.videoId.includes(filter.keyword))
    const mergedTasks = [...localTasks, ...workflowTasks]
      .sort((left, right) => String(right.scheduledAt || '').localeCompare(String(left.scheduledAt || '')))
    tasks.value = filter.status === 'all' ? mergedTasks : mergedTasks.filter(task => task.status === filter.status)
    total.value = tasks.value.length
    const localSummary = response.data?.summary || {}
    summary.value = {
      ...localSummary,
      all: Number(localSummary.all || 0) + workflowTasks.length,
      scheduled: workflowTasks.filter(task => task.status === 'scheduled').length,
      running: Number(localSummary.running || 0) + workflowTasks.filter(task => task.status === 'running').length,
      failed: Number(localSummary.failed || 0) + workflowTasks.filter(task => task.status === 'failed').length
    }
  } catch (error) {
    ElMessage.error(error.message || '读取定时发布任务失败')
  } finally {
    loading.value = false
  }
}

const selectStatus = (status) => {
  filter.status = status
  filter.page = 1
  loadTasks()
}

const applyKeyword = () => {
  filter.page = 1
  loadTasks()
}

const cancelTask = async (task) => {
  if (task.source === 'workflow') {
    ElMessage.info('该任务已提交到平台的定时发布队列，当前不能在此页面取消。')
    return
  }
  try {
    await ElMessageBox.confirm(`确定取消「${task.title}」的全部平台定时发布吗？`, '取消定时任务', {
      confirmButtonText: '取消任务', cancelButtonText: '返回', type: 'warning'
    })
    await materialApi.cancelScheduledPublishTask(task.id)
    ElMessage.success('定时发布任务已取消')
    await loadTasks()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message || '取消定时发布任务失败')
  }
}

onMounted(() => {
  loadTasks()
  pollTimer = window.setInterval(() => {
    if ((summary.value.pending || 0) + (summary.value.queued || 0) + (summary.value.running || 0) > 0) loadTasks()
  }, 10000)
})

onBeforeUnmount(() => window.clearInterval(pollTimer))
</script>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.scheduled-tasks-page { display: grid; gap: 16px; }
.page-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px; border: 1px solid var(--vf-border); border-radius: 8px; background: var(--vf-surface); }
.page-heading h1 { margin: 4px 0 6px; color: var(--vf-text-primary); font-size: 24px; }
.page-heading p { margin: 0; color: var(--vf-text-regular); font-size: 14px; }
.eyebrow { color: var(--vf-primary); font-size: 12px; font-weight: 700; }
.queue-summary { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); border: 1px solid var(--vf-border); border-radius: 8px; overflow: hidden; background: var(--vf-surface); }
.queue-summary button { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 58px; padding: 12px 14px; border: 0; border-right: 1px solid var(--vf-border-light); background: var(--vf-surface); color: var(--vf-text-regular); cursor: pointer; }
.queue-summary button:last-child { border-right: 0; }
.queue-summary button.active { background: var(--vf-surface-hover); color: var(--vf-primary); box-shadow: inset 0 -2px var(--vf-primary); }
.queue-summary strong { color: var(--vf-text-primary); font-size: 20px; }
.task-panel { display: grid; gap: 14px; padding: 16px; border: 1px solid var(--vf-border); border-radius: 8px; background: var(--vf-surface); }
.panel-toolbar { display: flex; gap: 10px; }
.panel-toolbar .el-input { width: min(360px, 100%); }
.video-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.video-cell img { width: 72px; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 4px; }
.video-cell div { display: grid; gap: 4px; min-width: 0; }
.video-cell strong { overflow: hidden; color: var(--vf-text-primary); text-overflow: ellipsis; white-space: nowrap; }
.video-cell span, .muted { color: var(--vf-text-secondary); font-size: 12px; }
.time-cell { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.result-summary { display: flex; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.result-summary .success { color: #15803d; }
.result-summary .failed { color: #dc2626; }
.target-list { margin: 0 20px; border-top: 1px solid #e6edf6; }
.target-row { display: grid; grid-template-columns: 150px 100px 90px minmax(0, 1fr); align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid #eef2f7; }
.target-row div { display: grid; gap: 2px; }
.target-row span, .target-row p { margin: 0; color: var(--vf-text-regular); font-size: 12px; }
.el-pagination { justify-content: flex-end; }

@media (max-width: 900px) {
  .queue-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .queue-summary button:nth-child(3) { border-right: 0; }
  .target-row { grid-template-columns: 1fr auto; }
  .target-row p { grid-column: 1 / -1; }
}

@media (max-width: 640px) {
  .page-heading { align-items: flex-start; flex-direction: column; }
  .queue-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .queue-summary button:nth-child(3) { border-right: 1px solid #e6edf6; }
  .queue-summary button:nth-child(2n) { border-right: 0; }
  .panel-toolbar { flex-direction: column; }
}
</style>
