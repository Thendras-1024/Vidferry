<template>
  <div class="workflow-statistics">
    <section class="statistics-toolbar">
      <div>
        <span class="section-kicker">PROCESS LEDGER</span>
        <h1>视频处理与模型用量</h1>
      </div>
      <div class="toolbar-actions">
        <el-button-group aria-label="时间范围快捷选择">
          <el-button :type="rangePreset === 'day' ? 'primary' : 'default'" @click="setRangePreset('day')">近 24 小时</el-button>
          <el-button :type="rangePreset === 'week' ? 'primary' : 'default'" @click="setRangePreset('week')">近 7 天</el-button>
          <el-button :type="rangePreset === 'month' ? 'primary' : 'default'" @click="setRangePreset('month')">近 30 天</el-button>
        </el-button-group>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          unlink-panels
          aria-label="统计时间范围"
          @change="handleCustomRangeChange"
        />
        <el-radio-group v-model="granularity" aria-label="时间聚合粒度" @change="refreshForFilter">
          <el-radio-button label="auto">自动</el-radio-button>
          <el-radio-button label="hour">按小时</el-radio-button>
          <el-radio-button label="day">按天</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="loading" @click="fetchStatistics">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </div>
    </section>

    <section class="metric-grid" aria-label="统计汇总">
      <div class="metric-card is-duration">
        <span>视频任务</span>
        <strong>{{ summary.jobCount || 0 }}</strong>
        <small>处理总历时 {{ formatDuration(summary.totalDurationSeconds) }}</small>
      </div>
      <div class="metric-card is-input">
        <span>输入 Token</span>
        <strong>{{ formatNumber(summary.promptTokens) }}</strong>
        <small>模型发送内容</small>
      </div>
      <div class="metric-card is-output">
        <span>输出 Token</span>
        <strong>{{ formatNumber(summary.completionTokens) }}</strong>
        <small>模型生成内容</small>
      </div>
      <div class="metric-card is-total">
        <span>总 Token</span>
        <strong>{{ formatNumber(summary.totalTokens) }}</strong>
        <small>{{ models.length }} 个模型</small>
      </div>
      <div class="metric-card is-request">
        <span>模型请求</span>
        <strong>{{ formatNumber(summary.cloudCallCount) }}</strong>
        <small>平均 {{ formatMs(summary.avgCloudLatencyMs) }}</small>
      </div>
    </section>

    <section class="chart-grid">
      <div class="data-panel trend-panel">
        <div class="panel-heading">
          <div>
            <span class="section-kicker">TOKEN FLOW</span>
            <h2>Token 使用趋势</h2>
          </div>
          <span class="panel-note">{{ granularityLabel }}</span>
        </div>
        <div ref="trendChartRef" class="chart-canvas" aria-label="Token 使用趋势图" />
      </div>

      <div class="data-panel model-panel">
        <div class="panel-heading">
          <div>
            <span class="section-kicker">MODEL MIX</span>
            <h2>模型分布</h2>
          </div>
          <span class="panel-note">按总 Token</span>
        </div>
        <div class="model-content">
          <div ref="modelChartRef" class="model-chart" aria-label="模型 Token 分布图" />
          <div class="model-list">
            <div v-for="model in models.slice(0, 4)" :key="model.model" class="model-list-row">
              <span>{{ model.model }}</span>
              <strong>{{ formatNumber(model.totalTokens) }}</strong>
            </div>
            <el-empty v-if="models.length === 0" :image-size="48" description="暂无模型请求" />
          </div>
        </div>
      </div>
    </section>

    <section class="data-panel model-table-panel">
      <div class="panel-heading">
        <div>
          <span class="section-kicker">MODEL SUMMARY</span>
          <h2>各模型消耗</h2>
        </div>
      </div>
      <el-table :data="models" v-loading="loading" empty-text="暂无模型统计" style="width: 100%">
        <el-table-column prop="model" label="模型" min-width="180" />
        <el-table-column label="请求次数" width="110" align="right">
          <template #default="{ row }">{{ formatNumber(row.requestCount) }}</template>
        </el-table-column>
        <el-table-column label="输入 Token" width="130" align="right">
          <template #default="{ row }">{{ formatNumber(row.promptTokens) }}</template>
        </el-table-column>
        <el-table-column label="输出 Token" width="130" align="right">
          <template #default="{ row }">{{ formatNumber(row.completionTokens) }}</template>
        </el-table-column>
        <el-table-column label="总 Token" width="130" align="right">
          <template #default="{ row }"><strong class="token-total">{{ formatNumber(row.totalTokens) }}</strong></template>
        </el-table-column>
        <el-table-column label="平均响应" width="130" align="right">
          <template #default="{ row }">{{ formatMs(row.avgLatencyMs) }}</template>
        </el-table-column>
      </el-table>
    </section>

    <section class="data-panel task-panel">
      <div class="panel-heading">
        <div>
          <span class="section-kicker">TASK RECORDS</span>
          <h2>视频处理任务</h2>
        </div>
        <span class="panel-note">{{ taskTotal }} 条</span>
      </div>
      <el-table
        :data="tasks"
        row-key="jobId"
        :expand-row-keys="expandedTaskIds"
        v-loading="loading"
        empty-text="当前时间范围暂无处理任务"
        @expand-change="handleTaskExpand"
      >
        <el-table-column type="expand" width="48">
          <template #default="{ row }">
            <div class="task-detail" v-loading="detailLoadingIds.includes(row.jobId)">
              <template v-if="taskDetails[row.jobId]">
                <div class="detail-heading">阶段耗时</div>
                <div class="stage-timeline">
                  <div v-for="stage in taskDetails[row.jobId].stages" :key="stage.id" class="stage-row">
                    <span class="stage-marker" :class="`is-${stage.status}`" />
                    <div class="stage-main">
                      <strong>{{ stage.stageLabel }}</strong>
                      <span>{{ stage.message || stage.startedAt }}</span>
                    </div>
                    <span>{{ formatDuration(stage.durationSeconds) }}</span>
                    <span>{{ formatModels(stage.models) }}</span>
                    <div class="stage-token-usage">
                      <span v-for="usage in stage.modelUsage" :key="usage.model">
                        <strong>{{ usage.model }}</strong>
                        {{ formatTokenUsage(usage) }}
                      </span>
                      <span v-if="!stage.modelUsage?.length">{{ formatTokenUsage(stage) }}</span>
                    </div>
                    <span>{{ formatNumber(stage.requestCount) }} 次请求</span>
                  </div>
                </div>

                <div class="detail-heading">模型请求</div>
                <el-table :data="taskDetails[row.jobId].requests" size="small" empty-text="该任务没有可记录的模型请求">
                  <el-table-column prop="createdAt" label="调用时间" width="165" />
                  <el-table-column prop="stageLabel" label="阶段" width="125" />
                  <el-table-column prop="operation" label="操作" min-width="155" />
                  <el-table-column prop="model" label="模型" min-width="145" />
                  <el-table-column label="状态 / 原因" min-width="240">
                    <template #default="{ row: requestRow }">
                      <div class="request-status">
                        <el-tag size="small" :type="requestStatusType(requestRow.status)">{{ requestStatusText(requestRow.status) }}</el-tag>
                        <el-tooltip v-if="requestFailureReason(requestRow)" :content="requestFailureReason(requestRow)" placement="top" :show-after="250">
                          <span class="request-status-reason">{{ requestFailureReason(requestRow) }}</span>
                        </el-tooltip>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="输入 / 输出 / 总计" width="180" align="right">
                    <template #default="{ row: requestRow }">{{ formatTokenUsage(requestRow) }}</template>
                  </el-table-column>
                  <el-table-column label="响应" width="105" align="right">
                    <template #default="{ row: requestRow }">{{ formatMs(requestRow.latencyMs) }}</template>
                  </el-table-column>
                  <el-table-column label="尝试" width="82" align="right">
                    <template #default="{ row: requestRow }">{{ requestRow.attempt }}</template>
                  </el-table-column>
                </el-table>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="视频 / 任务" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="task-name">
              <strong>{{ row.title }}</strong>
              <span>{{ row.videoId || row.jobId }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }"><el-tag size="small" :type="taskStatusType(row.status)">{{ taskStatusText(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="开始时间" width="165">
          <template #default="{ row }">{{ formatDate(row.startedAt) }}</template>
        </el-table-column>
        <el-table-column label="总历时" width="110" align="right">
          <template #default="{ row }">{{ formatDuration(row.durationSeconds) }}</template>
        </el-table-column>
        <el-table-column label="阶段" width="80" align="right">
          <template #default="{ row }">{{ row.stageCount }}</template>
        </el-table-column>
        <el-table-column label="模型" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ formatModels(row.models) }}</template>
        </el-table-column>
        <el-table-column label="输入 / 输出 / 总计" width="190" align="right">
          <template #default="{ row }">{{ formatTokenUsage(row) }}</template>
        </el-table-column>
        <el-table-column label="请求" width="82" align="right">
          <template #default="{ row }">{{ formatNumber(row.requestCount) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="taskTotal > pagination.pageSize" class="table-pagination">
        <el-pagination
          v-model:current-page="pagination.page"
          :page-size="pagination.pageSize"
          :total="taskTotal"
          layout="total, prev, pager, next, jumper"
          background
          @current-change="fetchStatistics"
        />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { youtubeApi } from '@/api/youtube'

const loading = ref(false)
const rangePreset = ref('week')
const dateRange = ref(defaultRange(7))
const granularity = ref('auto')
const stats = ref({ summary: {}, trend: [], models: [], tasks: [], range: {} })
const taskTotal = ref(0)
const pagination = reactive({ page: 1, pageSize: 20 })
const taskDetails = reactive({})
const detailLoadingIds = ref([])
const expandedTaskIds = ref([])
const trendChartRef = ref(null)
const modelChartRef = ref(null)
let trendChart = null
let modelChart = null

const summary = computed(() => stats.value.summary || {})
const trend = computed(() => stats.value.trend || [])
const models = computed(() => stats.value.models || [])
const tasks = computed(() => stats.value.tasks || [])
const granularityLabel = computed(() => stats.value.range?.granularity === 'hour' ? '按小时' : '按天')

function defaultRange(days) {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - days + 1)
  return [formatDateInput(start), formatDateInput(end)]
}

function formatDateInput(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function setRangePreset(preset) {
  rangePreset.value = preset
  dateRange.value = defaultRange(preset === 'day' ? 1 : preset === 'month' ? 30 : 7)
  pagination.page = 1
  fetchStatistics()
}

function handleCustomRangeChange(value) {
  rangePreset.value = 'custom'
  if (Array.isArray(value) && value.length === 2 && value[0] && value[1]) {
    refreshForFilter()
  }
}

function refreshForFilter() {
  pagination.page = 1
  fetchStatistics()
}

async function fetchStatistics() {
  loading.value = true
  try {
    const response = await youtubeApi.getWorkflowStatistics({
      page: pagination.page,
      pageSize: pagination.pageSize,
      dateFrom: dateRange.value?.[0] || '',
      dateTo: dateRange.value?.[1] || '',
      granularity: granularity.value,
    })
    stats.value = response.data || {}
    taskTotal.value = Number(response.data?.tasksTotal || 0)
    pagination.page = Number(response.data?.tasksPage || pagination.page)
    expandedTaskIds.value = []
    await nextTick()
    renderCharts()
  } catch (error) {
    ElMessage.error('获取处理统计失败')
  } finally {
    loading.value = false
  }
}

async function handleTaskExpand(row, expandedRows) {
  const expanded = expandedRows.some(item => item.jobId === row.jobId)
  expandedTaskIds.value = expandedRows.map(item => item.jobId)
  if (!expanded || taskDetails[row.jobId] || detailLoadingIds.value.includes(row.jobId)) return
  detailLoadingIds.value = [...detailLoadingIds.value, row.jobId]
  try {
    const response = await youtubeApi.getWorkflowTaskStatistics(row.jobId)
    taskDetails[row.jobId] = response.data || { stages: [], requests: [] }
  } catch (error) {
    ElMessage.error('获取任务详情失败')
  } finally {
    detailLoadingIds.value = detailLoadingIds.value.filter(id => id !== row.jobId)
  }
}

function renderCharts() {
  renderTrendChart()
  renderModelChart()
}

function renderTrendChart() {
  if (!trendChartRef.value) return
  trendChart ||= echarts.init(trendChartRef.value)
  const labels = trend.value.map(item => item.bucket)
  trendChart.setOption({
    animationDuration: 280,
    color: ['#2f80ed', '#14b8a6', '#f59e0b', '#7c5cff'],
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 2, data: ['输入 Token', '输出 Token', '总 Token', '请求次数'] },
    grid: { left: 58, right: 56, top: 44, bottom: 38 },
    xAxis: { type: 'category', data: labels, axisLabel: { color: '#64748b', rotate: labels.length > 8 ? 30 : 0 }, axisLine: { lineStyle: { color: '#dbe4ee' } } },
    yAxis: [
      { type: 'value', axisLabel: { color: '#64748b', formatter: value => formatChartNumber(value) }, splitLine: { lineStyle: { color: '#edf2f7' } } },
      { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { show: false } },
    ],
    series: [
      { name: '输入 Token', type: 'bar', stack: 'tokens', barMaxWidth: 28, data: trend.value.map(item => item.promptTokens) },
      { name: '输出 Token', type: 'bar', stack: 'tokens', barMaxWidth: 28, data: trend.value.map(item => item.completionTokens) },
      { name: '总 Token', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6, data: trend.value.map(item => item.totalTokens) },
      { name: '请求次数', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'none', lineStyle: { type: 'dashed' }, data: trend.value.map(item => item.requestCount) },
    ],
  }, true)
}

function renderModelChart() {
  if (!modelChartRef.value) return
  modelChart ||= echarts.init(modelChartRef.value)
  modelChart.setOption({
    animationDuration: 280,
    color: ['#2f80ed', '#14b8a6', '#f59e0b', '#7c5cff', '#ef476f', '#64748b'],
    tooltip: { trigger: 'item', formatter: item => `${item.name}<br/>${formatNumber(item.value)} Token` },
    series: [{
      type: 'pie',
      radius: ['52%', '76%'],
      center: ['50%', '50%'],
      label: { show: false },
      emphasis: { scale: false },
      data: models.value.map(item => ({ name: item.model, value: item.totalTokens })),
    }],
  }, true)
}

function handleResize() {
  trendChart?.resize()
  modelChart?.resize()
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatChartNumber(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`
  return value
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remain = total % 60
  if (hours) return `${hours}h ${minutes}m`
  if (minutes) return `${minutes}m ${remain}s`
  return `${remain}s`
}

function formatMs(value) {
  const milliseconds = Number(value || 0)
  return milliseconds ? `${milliseconds.toFixed(0)} ms` : '-'
}

function formatTokenUsage(row) {
  const prompt = Number(row?.promptTokens || 0)
  const completion = Number(row?.completionTokens || 0)
  const total = Number(row?.totalTokens || 0)
  return prompt || completion || total ? `${formatNumber(prompt)} / ${formatNumber(completion)} / ${formatNumber(total)}` : '-'
}

function formatModels(value) {
  return Array.isArray(value) && value.length ? value.join('、') : '-'
}

function formatDate(value) {
  return String(value || '').replace('T', ' ').slice(0, 19) || '-'
}

function taskStatusText(status) {
  return ({ queued: '排队中', running: '处理中', success: '成功', failed: '失败', waiting_confirmation: '待确认' })[status] || status || '-'
}

function taskStatusType(status) {
  return ({ queued: 'info', running: 'warning', success: 'success', failed: 'danger', waiting_confirmation: 'warning' })[status] || 'info'
}

function requestStatusText(status) {
  return ({ success: '成功', failed: '失败', contract_failed: '契约校验失败', soft_warning: '校验警告' })[status] || status || '-'
}

function requestStatusType(status) {
  return ({ success: 'success', failed: 'danger', contract_failed: 'warning', soft_warning: 'warning' })[status] || 'info'
}

function requestFailureReason(row) {
  return String(row?.errorMessage || '').trim()
}

watch([trend, models], () => nextTick(renderCharts), { deep: true })

onMounted(() => {
  fetchStatistics()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart?.dispose()
  modelChart?.dispose()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

$ink: #162235;
$muted: #64748b;
$line: #dbe4ee;
$panel: #ffffff;

.workflow-statistics {
  display: grid;
  gap: 16px;
}

.statistics-toolbar,
.data-panel,
.metric-card {
  border: 1px solid $line;
  border-radius: 8px;
  background: $panel;
  box-shadow: 0 8px 20px rgba(26, 51, 79, 0.06);
}

.statistics-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 16px 18px;

  h1 {
    margin: 3px 0 0;
    color: $ink;
    font-size: 22px;
    line-height: 1.25;
  }
}

.section-kicker {
  color: #0f9f8f;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.metric-card {
  position: relative;
  display: grid;
  gap: 7px;
  min-height: 112px;
  padding: 15px;
  overflow: hidden;

  &::before {
    position: absolute;
    top: 0;
    left: 0;
    width: 4px;
    height: 100%;
    content: '';
    background: #2f80ed;
  }

  &.is-input::before { background: #14b8a6; }
  &.is-output::before { background: #f59e0b; }
  &.is-total::before { background: #7c5cff; }
  &.is-request::before { background: #ef476f; }

  span,
  small { color: $muted; }

  span { font-size: 13px; }

  strong {
    color: $ink;
    font-size: 24px;
    line-height: 1;
  }

  small { font-size: 12px; }
}

.chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(320px, 1fr);
  gap: 16px;
}

.data-panel {
  overflow: hidden;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 64px;
  padding: 13px 16px;
  border-bottom: 1px solid $line;

  h2 {
    margin: 3px 0 0;
    color: $ink;
    font-size: 16px;
    line-height: 1.35;
  }
}

.panel-note {
  color: $muted;
  font-size: 12px;
}

.chart-canvas { height: 300px; }

.model-content {
  display: grid;
  grid-template-columns: minmax(160px, 0.9fr) minmax(130px, 1fr);
  align-items: center;
  min-height: 300px;
  padding: 4px 12px 8px;
}

.model-chart { width: 100%; height: 252px; }

.model-list {
  display: grid;
  gap: 2px;
}

.model-list-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  padding: 9px 0;
  border-bottom: 1px solid #edf2f7;
  color: $muted;
  font-size: 12px;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong { color: $ink; font-variant-numeric: tabular-nums; }
}

.token-total { color: #0f9f8f; }

.task-name {
  display: grid;
  gap: 4px;
  min-width: 0;

  strong {
    overflow: hidden;
    color: $ink;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  span { color: $muted; font-size: 12px; }
}

.task-detail {
  padding: 10px 18px 18px 66px;
  background: #fbfdff;
}

.detail-heading {
  margin: 12px 0 8px;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.stage-timeline {
  margin-bottom: 18px;
  border: 1px solid #e6edf5;
  border-radius: 6px;
  background: #fff;
}

.stage-row {
  display: grid;
  grid-template-columns: 10px minmax(150px, 1.6fr) 100px minmax(130px, 1fr) minmax(250px, 1.3fr) 100px;
  align-items: center;
  gap: 10px;
  min-height: 52px;
  padding: 8px 12px;
  border-bottom: 1px solid #edf2f7;
  color: #475569;
  font-size: 12px;

  &:last-child { border-bottom: 0; }
}

.stage-marker {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;

  &.is-success { background: #16a34a; }
  &.is-failed { background: #e11d48; }
  &.is-running { background: #f59e0b; }
}

.stage-main {
  display: grid;
  gap: 3px;
  min-width: 0;

  strong { color: $ink; }

  span {
    overflow: hidden;
    color: $muted;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.stage-token-usage {
  display: grid;
  gap: 3px;
  min-width: 0;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong { color: $ink; font-weight: 600; }
}

.request-status {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.request-status-reason {
  overflow: hidden;
  color: #b45309;
  cursor: help;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 1px solid $line;
}

:deep(.el-table th.el-table__cell) {
  background: #f6f9fc;
  color: #526176;
  font-weight: 600;
}

:deep(.el-table .cell) { font-variant-numeric: tabular-nums; }

@media (max-width: 1320px) {
  .statistics-toolbar { align-items: flex-start; flex-direction: column; }
  .toolbar-actions { justify-content: flex-start; }
  .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .chart-grid { grid-template-columns: 1fr; }
}

@media (max-width: 760px) {
  .metric-grid { grid-template-columns: 1fr; }
  .toolbar-actions { align-items: stretch; flex-direction: column; width: 100%; }
  .toolbar-actions :deep(.el-date-editor),
  .toolbar-actions :deep(.el-radio-group),
  .toolbar-actions :deep(.el-button-group) { width: 100%; }
  .toolbar-actions :deep(.el-button-group .el-button) { flex: 1; }
  .model-content { grid-template-columns: 1fr; }
  .model-chart { height: 190px; }
  .model-list { padding: 0 10px 14px; }
  .task-detail { padding: 8px; overflow-x: auto; }
  .stage-timeline { min-width: 700px; }
}
</style>
