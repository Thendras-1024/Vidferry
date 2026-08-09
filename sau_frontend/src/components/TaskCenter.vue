<template>
  <el-tooltip content="任务中心" placement="bottom">
    <el-badge
      :value="summary.abnormalCount ? '!' : summary.badgeCount"
      :hidden="summary.badgeCount === 0"
      :type="summary.abnormalCount ? 'danger' : 'primary'"
      :max="99"
      class="task-center-badge"
    >
      <el-popover
        v-model:visible="panelVisible"
        placement="bottom-end"
        trigger="click"
        width="430"
        popper-class="task-center-popper"
        @show="refresh"
      >
        <template #reference>
          <el-button class="task-center-button" circle :icon="List" aria-label="任务中心" />
        </template>

        <section class="task-center-panel" aria-label="任务中心列表">
          <header class="task-center-header">
            <div>
              <strong>任务中心</strong>
              <span>{{ summary.badgeCount }} 项需要关注</span>
            </div>
            <el-button text circle :icon="RefreshRight" aria-label="刷新任务" title="刷新任务" :loading="loading" @click="refresh" />
          </header>
          <div v-if="loading && !items.length" class="task-center-loading"><el-icon class="is-loading"><Loading /></el-icon> 正在读取任务</div>
          <el-empty v-else-if="!items.length" description="暂无需要关注的任务" :image-size="62" />
          <div v-else class="task-center-groups">
            <section v-for="group in visibleGroups" :key="group.key" v-show="group.items.length" class="task-group">
              <div class="task-group-title"><span>{{ group.label }}</span><em>{{ group.items.length }}</em></div>
              <article v-for="item in group.items" :key="item.taskKey" class="task-item" :class="`is-${item.status}`">
                <div class="task-item-main">
                  <div class="task-item-type" :class="`is-${item.type}`">{{ item.typeLabel }}</div>
                  <div class="task-item-title" :title="item.chineseTitle || item.englishTitle">{{ item.chineseTitle || '原题中文翻译未生成' }}</div>
                  <div class="task-item-english" :title="item.englishTitle">{{ item.englishTitle }}</div>
                  <div class="task-item-meta"><span class="task-status-dot" :class="`is-${item.status}`" />{{ item.currentStage }}</div>
                  <el-progress :percentage="item.progress" :show-text="false" :stroke-width="4" :status="progressStatus(item.status)" />
                  <div class="task-item-time">{{ item.status === 'success' ? `完成于 ${formatTime(item.finishedAt)}` : formatTime(item.updatedAt) }}<span v-if="item.errorReason" class="task-error-summary">{{ item.errorReason }}</span></div>
                </div>
                <div class="task-item-actions">
                  <el-button text type="primary" size="small" @click="openDetail(item)">详情</el-button>
                  <el-button v-if="['failed', 'abnormal'].includes(item.status)" text type="danger" size="small" @click="acknowledge(item)">我知道了</el-button>
                </div>
              </article>
            </section>
          </div>
        </section>
      </el-popover>
    </el-badge>
  </el-tooltip>

  <TaskFlowDialog v-model:visible="detailVisible" :detail="detail" />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { List, Loading, RefreshRight } from '@element-plus/icons-vue'
import { taskCenterApi } from '@/api/taskCenter'
import TaskFlowDialog from './TaskFlowDialog.vue'

const panelVisible = ref(false)
const detailVisible = ref(false)
const loading = ref(false)
const detail = ref(null)
const items = ref([])
const summary = ref({ activeCount: 0, waitingCount: 0, completedCount: 0, abnormalCount: 0, badgeCount: 0 })
let pollTimer = null
const activeStatuses = new Set(['queued', 'running', 'waiting_confirmation'])

const visibleGroups = computed(() => {
  const groups = summary.value.groups || {}
  return [
    { key: 'active', label: '正在进行', items: groups.active || [] },
    { key: 'waitingConfirmation', label: '等待确认', items: groups.waitingConfirmation || [] },
    { key: 'recentCompleted', label: '最近完成', items: groups.recentCompleted || [] },
    { key: 'abnormal', label: '异常任务', items: groups.abnormal || [] },
  ]
})

const formatTime = value => {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const progressStatus = status => status === 'failed' || status === 'abnormal' ? 'exception' : status === 'success' ? 'success' : undefined

const refresh = async ({ activeOnly = false } = {}) => {
  if (loading.value) return
  loading.value = true
  try {
    const response = await taskCenterApi.list(activeOnly ? { activeOnly: 1 } : {})
    const nextItems = response?.data?.items || []
    items.value = activeOnly
      ? [...nextItems, ...items.value.filter(item => !activeStatuses.has(item.status))]
      : nextItems
    const groups = { active: [], waitingConfirmation: [], recentCompleted: [], abnormal: [] }
    for (const item of items.value) {
      if (['queued', 'running'].includes(item.status)) groups.active.push(item)
      else if (item.status === 'waiting_confirmation') groups.waitingConfirmation.push(item)
      else if (item.status === 'success') groups.recentCompleted.push(item)
      else groups.abnormal.push(item)
    }
    summary.value = {
      activeCount: groups.active.length,
      waitingCount: groups.waitingConfirmation.length,
      completedCount: groups.recentCompleted.length,
      abnormalCount: groups.abnormal.length,
      badgeCount: groups.active.length + groups.waitingConfirmation.length + groups.abnormal.length,
      groups,
    }
  } catch (error) {
    console.warn('读取任务中心失败:', error)
  } finally {
    loading.value = false
  }
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

const acknowledge = async item => {
  try {
    await taskCenterApi.acknowledge(item.taskKey)
    items.value = items.value.filter(current => current.taskKey !== item.taskKey)
    await refresh()
  } catch (error) {
    ElMessage.error(error.message || '记录知晓状态失败')
  }
}

const handleFocus = () => { void refresh() }

onMounted(() => {
  void refresh()
  pollTimer = window.setInterval(() => { void refresh({ activeOnly: true }) }, 5000)
  window.addEventListener('focus', handleFocus)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  window.removeEventListener('focus', handleFocus)
})
</script>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;
.task-center-badge { display: inline-flex; }
.task-center-button {
  width: 36px; min-width: 36px; height: 36px; padding: 0; border: none;
  color: $text-regular; background: transparent;
  &:hover, &:focus { color: $primary-color; background: $bg-color-page; }
}
.task-center-panel { color: $text-primary; }
.task-center-header { display: flex; align-items: center; justify-content: space-between; padding-bottom: 12px; border-bottom: 1px solid $border-lighter; }
.task-center-header strong { display: block; font-size: 15px; }
.task-center-header span { color: $text-secondary; font-size: 12px; }
.task-center-loading { display: flex; gap: 8px; justify-content: center; padding: 28px 0; color: $text-secondary; }
.task-group { padding-top: 12px; }
.task-group-title { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; color: $text-secondary; font-size: 12px; font-weight: 600; }
.task-group-title em { min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; background: $bg-color-page; color: $text-secondary; font-style: normal; text-align: center; line-height: 18px; }
.task-item { display: flex; gap: 8px; align-items: flex-start; padding: 10px 0; border-bottom: 1px solid $border-extra-light; }
.task-item:last-child { border-bottom: 0; }
.task-item-main { min-width: 0; flex: 1; }
.task-item-type { display: inline-flex; align-items: center; min-height: 18px; margin-bottom: 3px; padding-left: 6px; border-left: 3px solid $primary-color; color: $primary-color; font-size: 11px; font-weight: 700; letter-spacing: .02em; }
.task-item-type.is-download { border-left-color: var(--vf-text-muted); color: var(--vf-text-secondary); }.task-item-type.is-publish { border-left-color: $success-color; color: $success-color; }
.task-item-title { overflow: hidden; color: $text-primary; font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.task-item-english { overflow: hidden; margin-top: 2px; color: $text-secondary; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.task-item-meta, .task-item-time { display: flex; gap: 5px; align-items: center; min-width: 0; margin-top: 4px; color: $text-secondary; font-size: 11px; }
.task-item-time { justify-content: space-between; }
.task-error-summary { overflow: hidden; color: $danger-color; text-overflow: ellipsis; white-space: nowrap; }
.task-status-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: #aeb6c2; }
.task-status-dot.is-running { background: $primary-color; }
.task-status-dot.is-success { background: $success-color; }
.task-status-dot.is-warning { background: $warning-color; }
.task-status-dot.is-failed, .task-status-dot.is-abnormal { background: $danger-color; }
.task-item-actions { display: flex; flex: 0 0 auto; gap: 1px; padding-top: 16px; }
@media (max-width: 600px) { :global(.task-center-popper) { max-width: calc(100vw - 24px) !important; } }
@media (prefers-reduced-motion: reduce) { .task-center-panel *, .task-center-panel *::before, .task-center-panel *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }
</style>
