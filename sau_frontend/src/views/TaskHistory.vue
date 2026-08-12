<template>
  <div class="task-center-page">
    <section class="task-center-header">
      <div>
        <span class="section-kicker">WORKFLOW LEDGER</span>
        <h1>任务中心</h1>
        <p>统一查看下载、处理、编辑和发布任务。</p>
      </div>
      <el-button :loading="loading" @click="loadTasks">
        <el-icon><Refresh /></el-icon><span>刷新</span>
      </el-button>
    </section>

    <section class="task-summary-grid" aria-label="任务汇总">
      <button v-for="item in summaryItems" :key="item.key" class="task-summary" :class="{ 'is-selected': filters.status === item.status }" @click="applyStatus(item.status)">
        <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
      </button>
    </section>

    <section class="task-filter-panel" aria-label="任务筛选">
      <el-input v-model="filters.keyword" clearable placeholder="搜索标题、视频 ID、任务 ID 或错误信息" :prefix-icon="Search" @keyup.enter="applyFilters" @clear="applyFilters" />
      <el-select v-model="filters.type" placeholder="任务类型" @change="applyFilters">
        <el-option label="全部类型" value="all" /><el-option label="下载" value="download" />
        <el-option label="视频处理" value="processing" /><el-option label="编辑/封面刷新" value="editing" />
        <el-option label="发布" value="publish" />
      </el-select>
      <el-select v-model="filters.status" placeholder="任务状态" @change="applyFilters">
        <el-option label="全部状态" value="all" /><el-option label="进行中" value="active" />
        <el-option label="等待确认" value="waiting_confirmation" /><el-option label="成功" value="success" />
        <el-option label="失败/异常" value="problem" /><el-option label="失败" value="failed" /><el-option label="异常" value="abnormal" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <el-date-picker v-model="filters.updatedRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" unlink-panels @change="applyFilters" />
      <el-select v-if="isAdmin" v-model="filters.owner" placeholder="任务归属" @change="applyFilters">
        <el-option label="全部用户" value="all" /><el-option label="我的任务" value="mine" />
      </el-select>
      <el-select v-model="filters.sort" placeholder="排序方式" @change="applyFilters">
        <el-option label="最近更新" value="updated_desc" /><el-option label="最近创建" value="created_desc" />
        <el-option label="最近完成" value="finished_desc" />
      </el-select>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <section class="task-table-panel">
      <div class="task-table-heading"><div><span class="section-kicker">ALL WORKFLOW TASKS</span><h2>任务记录</h2></div><span>{{ total }} 条</span></div>
      <el-table :data="items" v-loading="loading" empty-text="暂无符合当前筛选条件的任务" row-key="taskKey">
        <el-table-column label="任务" min-width="270" show-overflow-tooltip>
          <template #default="{ row }"><div class="task-name" :class="`is-${row.status}`"><strong>{{ row.chineseTitle || row.englishTitle }}</strong><span>{{ row.videoId || row.jobId }}</span></div></template>
        </el-table-column>
        <el-table-column label="类型" width="120"><template #default="{ row }">{{ row.typeLabel }}</template></el-table-column>
        <el-table-column label="状态" width="116"><template #default="{ row }"><el-tag size="small" :type="tagType(row.status)">{{ row.statusLabel }}</el-tag></template></el-table-column>
        <el-table-column label="进度 / 阶段" min-width="165">
          <template #default="{ row }"><div class="task-progress"><span>{{ row.currentStage }}</span><el-progress :percentage="row.progress" :show-text="false" :stroke-width="4" :status="progressType(row.status)" /></div></template>
        </el-table-column>
        <el-table-column v-if="isAdmin && filters.owner === 'all'" label="创建者" width="120" show-overflow-tooltip><template #default="{ row }">{{ row.ownerDisplayName || '未归属任务' }}</template></el-table-column>
        <el-table-column label="最后更新" width="170"><template #default="{ row }">{{ formatTime(row.updatedAt) }}</template></el-table-column>
        <el-table-column label="错误信息" min-width="220" show-overflow-tooltip><template #default="{ row }"><span class="task-error">{{ row.errorReason || '—' }}</span></template></el-table-column>
        <el-table-column width="132" fixed="right">
          <template #default="{ row }"><el-button text type="primary" size="small" @click="openDetail(row)">详情</el-button><el-button v-if="row.canRetry" text type="primary" size="small" @click="openRetryDialog(row)">重试</el-button></template>
        </el-table-column>
      </el-table>
      <div v-if="total > pageSize" class="task-pagination"><el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next, jumper" background @current-change="loadTasks" /></div>
    </section>

    <TaskFlowDialog v-model:visible="detailVisible" :detail="detail" />
    <PublishRetryDialog v-model="retryDialogVisible" :task="retryTask" @completed="loadTasks" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import { taskCenterApi } from '@/api/taskCenter'
import TaskFlowDialog from '@/components/TaskFlowDialog.vue'
import PublishRetryDialog from '@/components/PublishRetryDialog.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.userInfo?.role === 'admin')
const pageSize = 20
const loading = ref(false)
const items = ref([])
const total = ref(0)
const summary = ref({})
const page = ref(Number(route.query.page || 1))
const detailVisible = ref(false)
const detail = ref(null)
const retryDialogVisible = ref(false)
const retryTask = ref(null)
const filters = reactive({
  keyword: String(route.query.keyword || ''), type: String(route.query.type || 'all'), status: String(route.query.status || 'active'),
  updatedRange: route.query.updatedFrom && route.query.updatedTo ? [route.query.updatedFrom, route.query.updatedTo] : [],
  owner: String(route.query.owner || 'all'), sort: String(route.query.sort || 'updated_desc'),
})
const summaryItems = computed(() => [
  { key: 'total', label: '全部', value: summary.value.total || 0, status: 'all' },
  { key: 'active', label: '进行中', value: summary.value.active || 0, status: 'active' },
  { key: 'waiting', label: '待确认', value: summary.value.waitingConfirmation || 0, status: 'waiting_confirmation' },
  { key: 'success', label: '成功', value: summary.value.success || 0, status: 'success' },
  { key: 'problem', label: '失败/异常', value: (summary.value.failed || 0) + (summary.value.abnormal || 0), status: 'problem' },
  { key: 'cancelled', label: '已取消', value: summary.value.cancelled || 0, status: 'cancelled' },
])

const tagType = status => ({ success: 'success', failed: 'danger', abnormal: 'danger', cancelled: 'info', waiting_confirmation: 'warning', waiting_publish: 'warning' }[status] || '')
const progressType = status => status === 'failed' || status === 'abnormal' ? 'exception' : status === 'success' ? 'success' : undefined
const formatTime = value => {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value || '时间未知' : date.toLocaleString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}
const queryParams = () => {
  const query = { page: String(page.value) }
  for (const [key, value] of Object.entries({ keyword: filters.keyword, type: filters.type, status: filters.status, owner: filters.owner, sort: filters.sort })) {
    if (value && value !== 'all' && value !== 'updated_desc') query[key] = value
  }
  if (filters.updatedRange?.length === 2) {
    query.updatedFrom = filters.updatedRange[0]
    query.updatedTo = filters.updatedRange[1]
  }
  return query
}
const syncQuery = () => router.replace({ query: queryParams() })
const loadTasks = async () => {
  loading.value = true
  try {
    const response = await taskCenterApi.all({
      page: page.value, pageSize, keyword: filters.keyword.trim(), type: filters.type, status: filters.status,
      owner: filters.owner, sort: filters.sort, updatedFrom: filters.updatedRange?.[0] || '', updatedTo: filters.updatedRange?.[1] || '',
    })
    const data = response?.data || {}
    items.value = data.items || []
    total.value = Number(data.total || 0)
    summary.value = data.summary || {}
    page.value = Number(data.page || page.value)
    await syncQuery()
  } catch (error) {
    ElMessage.error(error.message || '读取任务中心失败')
  } finally {
    loading.value = false
  }
}
const applyFilters = () => { page.value = 1; void loadTasks() }
const applyStatus = status => { filters.status = status; applyFilters() }
const resetFilters = () => {
  Object.assign(filters, { keyword: '', type: 'all', status: 'active', updatedRange: [], owner: 'all', sort: 'updated_desc' })
  applyFilters()
}
const openDetail = async item => {
  try {
    const response = await taskCenterApi.detail(item.taskKey)
    detail.value = response?.data || null
    detailVisible.value = true
  } catch (error) {
    ElMessage.error(error.message || '读取任务详情失败')
  }
}
const openRetryDialog = item => { retryTask.value = { ...item, taskId: item.publishTaskId }; retryDialogVisible.value = true }

onMounted(loadTasks)
</script>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;
.task-center-page { display: grid; gap: 18px; max-width: 1480px; margin: 0 auto; padding: 4px 0 24px; }
.task-center-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; padding: 8px 2px; }.section-kicker { display: block; color: $primary-color; font-size: 11px; font-weight: 700; letter-spacing: 0; }
.task-center-header h1, .task-table-heading h2 { margin: 5px 0 0; color: $text-primary; letter-spacing: 0; }.task-center-header h1 { font-size: 26px; line-height: 1.2; }.task-center-header p { margin: 7px 0 0; color: $text-secondary; font-size: 13px; }
.task-summary-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); border: 1px solid $border-lighter; border-radius: 6px; background: $bg-color; overflow: hidden; }.task-summary { min-height: 74px; padding: 12px 14px; border: 0; border-right: 1px solid $border-lighter; background: transparent; color: $text-secondary; cursor: pointer; text-align: left; }.task-summary:last-child { border-right: 0; }.task-summary:hover, .task-summary.is-selected { background: $bg-color-page; color: $primary-color; }.task-summary span, .task-summary strong { display: block; }.task-summary span { font-size: 12px; }.task-summary strong { margin-top: 6px; color: $text-primary; font-size: 22px; font-variant-numeric: tabular-nums; }
.task-filter-panel { display: grid; grid-template-columns: minmax(220px, 1.5fr) repeat(2, minmax(128px, 1fr)) minmax(220px, 1.2fr) repeat(2, minmax(128px, 1fr)) auto; gap: 10px; padding: 12px; border: 1px solid $border-lighter; border-radius: 6px; background: $bg-color; }.task-filter-panel :deep(.el-date-editor) { width: 100%; }
.task-table-panel { overflow: hidden; border: 1px solid $border-lighter; border-radius: 6px; background: $bg-color; }.task-table-heading { display: flex; align-items: end; justify-content: space-between; padding: 16px 18px 13px; border-bottom: 1px solid $border-lighter; }.task-table-heading h2 { font-size: 17px; }.task-table-heading > span { color: $text-secondary; font-size: 12px; }
.task-name { position: relative; display: grid; min-width: 0; gap: 4px; padding-left: 11px; }.task-name::before { position: absolute; top: 2px; bottom: 2px; left: 0; width: 3px; border-radius: 2px; background: #aeb6c2; content: ''; }.task-name.is-success::before { background: $success-color; }.task-name.is-failed::before, .task-name.is-abnormal::before { background: $danger-color; }.task-name strong, .task-name span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.task-name strong { color: $text-primary; font-size: 13px; }.task-name span { color: $text-secondary; font-size: 11px; }
.task-progress { display: grid; gap: 5px; min-width: 110px; color: $text-secondary; font-size: 12px; }.task-error { color: $danger-color; }.task-pagination { display: flex; justify-content: flex-end; padding: 16px 18px; }
@media (max-width: 1100px) { .task-summary-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.task-summary:nth-child(3) { border-right: 0; }.task-summary:nth-child(-n + 3) { border-bottom: 1px solid $border-lighter; }.task-filter-panel { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 720px) { .task-center-header { align-items: flex-start; flex-direction: column; }.task-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.task-summary:nth-child(3) { border-right: 1px solid $border-lighter; }.task-summary:nth-child(2n) { border-right: 0; }.task-summary:nth-child(-n + 4) { border-bottom: 1px solid $border-lighter; }.task-filter-panel { grid-template-columns: 1fr; }.task-pagination { justify-content: center; } }
</style>
