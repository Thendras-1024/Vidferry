<template>
  <div class="workflow-statistics">
    <section class="page-hero">
      <div>
        <span class="eyebrow">PIPELINE METRICS</span>
        <h1>处理统计</h1>
        <p>统计不同大小视频在下载、转写翻译、烧录、发布阶段消耗的时间，并预留云端模型 token 与调用延迟。</p>
      </div>
      <el-button type="primary" :loading="loading" @click="fetchStatistics">
        <el-icon><Refresh /></el-icon>
        <span>刷新统计</span>
      </el-button>
    </section>

    <section class="metric-grid">
      <div class="metric-card">
        <span>阶段记录</span>
        <strong>{{ summary.eventCount }}</strong>
        <small>已记录的处理阶段</small>
      </div>
      <div class="metric-card">
        <span>任务数量</span>
        <strong>{{ summary.jobCount }}</strong>
        <small>最近工作流任务</small>
      </div>
      <div class="metric-card">
        <span>总耗时</span>
        <strong>{{ formatDuration(summary.totalDurationSeconds) }}</strong>
        <small>阶段累计耗时</small>
      </div>
      <div class="metric-card">
        <span>Token 消耗</span>
        <strong>{{ formatNumber(summary.totalTokens) }}</strong>
        <small>输入 {{ formatNumber(summary.promptTokens) }} / 输出 {{ formatNumber(summary.completionTokens) }}</small>
      </div>
      <div class="metric-card">
        <span>云端调用</span>
        <strong>{{ summary.cloudCallCount }}</strong>
        <small>平均延迟 {{ formatMs(summary.avgCloudLatencyMs) }}</small>
      </div>
    </section>

    <el-card class="data-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <div>
            <span class="panel-kicker">阶段聚合</span>
            <h2>各阶段耗时与数据量</h2>
          </div>
          <span class="panel-count">{{ stages.length }} 个阶段</span>
        </div>
      </template>

      <el-table :data="stages" v-loading="loading" empty-text="暂无阶段统计" style="width: 100%">
        <el-table-column prop="stageLabel" label="阶段" min-width="150" />
        <el-table-column prop="count" label="次数" width="90" />
        <el-table-column label="成功/失败" width="110">
          <template #default="{ row }">{{ row.success }} / {{ row.failed }}</template>
        </el-table-column>
        <el-table-column label="总耗时" width="120">
          <template #default="{ row }">{{ formatDuration(row.durationSeconds) }}</template>
        </el-table-column>
        <el-table-column label="平均耗时" width="120">
          <template #default="{ row }">{{ formatDuration(row.avgDurationSeconds) }}</template>
        </el-table-column>
        <el-table-column label="输入大小" width="120">
          <template #default="{ row }">{{ formatMb(row.inputSizeMb) }}</template>
        </el-table-column>
        <el-table-column label="输出大小" width="120">
          <template #default="{ row }">{{ formatMb(row.outputSizeMb) }}</template>
        </el-table-column>
        <el-table-column label="Token 输入/输出/总计" width="170">
          <template #default="{ row }">{{ formatTokenUsage(row) }}</template>
        </el-table-column>
        <el-table-column label="云端延迟" width="120">
          <template #default="{ row }">{{ formatMs(row.avgCloudLatencyMs) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="data-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <div>
            <span class="panel-kicker">明细记录</span>
            <h2>视频处理阶段明细</h2>
          </div>
          <span class="panel-count">第 {{ eventPagination.page }} 页 · {{ events.length }} / {{ eventTotal }} 条</span>
        </div>
      </template>

      <el-table :data="events" v-loading="loading" empty-text="暂无处理明细" style="width: 100%">
        <el-table-column label="视频/任务" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="job-cell">
              <strong>{{ row.title || row.videoId || row.jobId }}</strong>
              <span>{{ row.videoId || '-' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="stageLabel" label="阶段" width="140" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="eventStatusType(row.status)" effect="light">{{ eventStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="110">
          <template #default="{ row }">{{ formatDuration(row.durationSeconds) }}</template>
        </el-table-column>
        <el-table-column label="视频大小" width="130">
          <template #default="{ row }">
            {{ formatMb(row.inputSizeMb || row.outputSizeMb) }}
          </template>
        </el-table-column>
        <el-table-column label="处理配置" width="190">
          <template #default="{ row }">
            {{ processVersionText(row.processVersion) }} / {{ languageText(row.subtitleLanguage) }} / {{ burnProfileText(row.burnProfile) }}
          </template>
        </el-table-column>
        <el-table-column label="Token/延迟" width="210">
          <template #default="{ row }">
            {{ formatTokenUsage(row) }} / {{ formatMs(row.cloudLatencyMs) }}
          </template>
        </el-table-column>
        <el-table-column prop="startedAt" label="开始时间" width="165" />
        <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip />
      </el-table>
      <div class="table-pagination" v-if="eventTotal > eventPagination.pageSize">
        <el-pagination
          v-model:current-page="eventPagination.page"
          :page-size="eventPagination.pageSize"
          :total="eventTotal"
          layout="total, prev, pager, next, jumper"
          background
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { youtubeApi } from '@/api/youtube'

const loading = ref(false)
const stats = ref({
  summary: {},
  stages: [],
  events: [],
  jobs: []
})
const eventPagination = reactive({ page: 1, pageSize: 50 })
const eventTotal = ref(0)

const summary = computed(() => stats.value.summary || {})
const stages = computed(() => stats.value.stages || [])
const events = computed(() => stats.value.events || [])

const languageMap = {
  'zh-CN': '中文',
  en: '英文',
  ja: '日文',
  ko: '韩文',
  es: '西班牙语',
  fr: '法语',
  de: '德语',
  ru: '俄语'
}

const fetchStatistics = async () => {
  loading.value = true
  try {
    const res = await youtubeApi.getWorkflowStatistics({
      limit: 300,
      page: eventPagination.page,
      pageSize: eventPagination.pageSize
    })
    stats.value = res.data || stats.value
    eventTotal.value = Number(res.data?.eventsTotal || stats.value.events?.length || 0)
    eventPagination.page = Number(res.data?.eventsPage || eventPagination.page)
    eventPagination.pageSize = Number(res.data?.eventsPageSize || eventPagination.pageSize)
  } catch (error) {
    ElMessage.error('获取处理统计失败')
  } finally {
    loading.value = false
  }
}

watch(
  () => eventPagination.page,
  () => {
    fetchStatistics()
  }
)

const formatDuration = (seconds) => {
  const safeSeconds = Math.max(0, Math.round(Number(seconds) || 0))
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const remain = safeSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${remain}s`
  return `${remain}s`
}

const formatMb = (value) => {
  const number = Number(value || 0)
  return number > 0 ? `${number.toFixed(number >= 100 ? 0 : 2)} MB` : '-'
}

const formatMs = (value) => {
  const number = Number(value || 0)
  return number > 0 ? `${number.toFixed(0)} ms` : '-'
}

const formatNumber = (value) => {
  const number = Number(value || 0)
  return number > 0 ? number.toLocaleString('zh-CN') : '0'
}

const formatTokenUsage = (row) => {
  const prompt = Number(row?.promptTokens || 0)
  const completion = Number(row?.completionTokens || 0)
  const total = Number(row?.totalTokens || 0)
  if (!prompt && !completion && !total) return '-'
  return `${formatNumber(prompt)} / ${formatNumber(completion)} / ${formatNumber(total)}`
}

const languageText = (value) => languageMap[value] || value || '-'

const processVersionText = (value) => {
  const map = {
    translation_v1: '处理方案一'
  }
  return map[value] || value || '-'
}

const burnProfileText = (value) => {
  const map = {
    stable: '稳定',
    fast: '快速'
  }
  return map[value] || value || '-'
}

const eventStatusText = (status) => {
  const map = {
    running: '执行中',
    success: '成功',
    failed: '失败'
  }
  return map[status] || status || '-'
}

const eventStatusType = (status) => {
  const map = {
    running: 'warning',
    success: 'success',
    failed: 'danger'
  }
  return map[status] || 'info'
}

onMounted(fetchStatistics)
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

$panel-border: #dce6f2;
$panel-shadow: 0 12px 28px rgba(28, 55, 90, 0.08);
$accent-blue: #2563eb;
$accent-teal: #0f9f8f;
$ink-strong: #172033;

.workflow-statistics {
  display: grid;
  gap: 16px;

  :deep(.el-card) {
    border: 1px solid $panel-border;
    border-radius: 8px;
    box-shadow: $panel-shadow;
  }

  :deep(.el-card__header) {
    padding: 14px 16px;
    border-bottom: 1px solid $border-lighter;
  }

  :deep(.el-card__body) {
    padding: 0;
  }

  :deep(.el-table th.el-table__cell) {
    background: #f8fbff;
    color: #5c6678;
    font-weight: 600;
  }
}

.page-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border: 1px solid $panel-border;
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(37, 99, 235, 0.1), rgba(15, 159, 143, 0.08) 42%, rgba(255, 255, 255, 0.94)),
    #fff;
  box-shadow: $panel-shadow;

  h1 {
    margin: 4px 0 8px;
    color: $ink-strong;
    font-size: 25px;
    line-height: 1.25;
    font-weight: 700;
  }

  p {
    max-width: 760px;
    margin: 0;
    color: #5b667a;
    font-size: 14px;
    line-height: 1.7;
  }
}

.eyebrow,
.panel-kicker {
  color: $accent-blue;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.metric-card {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 8px 18px rgba(28, 55, 90, 0.05);

  span {
    color: #5b667a;
    font-size: 13px;
  }

  strong {
    color: $ink-strong;
    font-size: 24px;
    line-height: 1;
  }

  small {
    color: $text-secondary;
    font-size: 12px;
  }
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  h2 {
    margin: 2px 0 0;
    color: $ink-strong;
    font-size: 18px;
    line-height: 1.3;
  }
}

.panel-count {
  color: $text-secondary;
  font-size: 13px;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px 14px;
  border-top: 1px solid $border-lighter;
}

.job-cell {
  display: grid;
  gap: 4px;
  min-width: 0;

  strong {
    min-width: 0;
    color: $ink-strong;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .page-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
