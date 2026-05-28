<template>
  <div class="dashboard">
    <section class="workspace-hero">
      <div class="hero-copy">
        <span class="eyebrow">VIDFERRY OPS</span>
        <h1>运营工作台</h1>
        <p>集中查看账号、素材和发布入口，快速进入视频采集、处理、素材管理与多平台发布流程。</p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="navigateTo('/youtube-research')">
          <el-icon><Search /></el-icon>
          <span>视频采集处理</span>
        </el-button>
        <el-button @click="fetchDashboardData" :loading="loading">
          <el-icon><Refresh /></el-icon>
          <span>刷新数据</span>
        </el-button>
      </div>
    </section>

    <section class="metric-grid">
      <button class="metric-card" type="button" @click="navigateTo('/account-management')">
        <span>账号总数</span>
        <strong>{{ accountStats.total }}</strong>
        <small>正常 {{ accountStats.normal }} / 异常 {{ accountStats.abnormal }}</small>
      </button>
      <button class="metric-card" type="button" @click="navigateTo('/account-management')">
        <span>已接入平台</span>
        <strong>{{ platformStats.total }}</strong>
        <small>抖音 {{ platformStats.douyin }} · B站 {{ platformStats.bilibili }} · 快手 {{ platformStats.kuaishou }} · 小红书 {{ platformStats.xiaohongshu }}</small>
      </button>
      <button class="metric-card" type="button" @click="navigateTo('/material-management')">
        <span>素材总数</span>
        <strong>{{ contentStats.total }}</strong>
        <small>视频 {{ contentStats.videos }} / 图片 {{ contentStats.images }} / 其他 {{ contentStats.others }}</small>
      </button>
    </section>

    <section class="quick-grid" aria-label="快捷入口">
      <button
        v-for="action in quickActions"
        :key="action.path"
        class="action-card"
        type="button"
        @click="navigateTo(action.path)"
      >
        <span class="action-icon">
          <el-icon><component :is="action.icon" /></el-icon>
        </span>
        <strong>{{ action.title }}</strong>
        <small>{{ action.desc }}</small>
      </button>
    </section>

    <el-card class="data-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <div>
            <span class="panel-kicker">PUBLISH TASKS</span>
            <h2>发布任务完成情况</h2>
          </div>
          <el-button text type="primary" @click="navigateTo('/publish-center')">查看发布中心</el-button>
        </div>
      </template>

      <el-table
        :data="recentPublishTasks"
        style="width: 100%"
        v-loading="loading"
        empty-text="暂无发布任务记录"
      >
        <el-table-column type="expand" width="44">
          <template #default="{ row }">
            <div class="target-records">
              <div class="target-help">
                删除只会清理本地发布记录和平台占用状态，不会删除平台上已经发布的视频。
              </div>
              <div
                v-for="target in row.targets"
                :key="target.id"
                class="target-row"
              >
                <div class="target-platform">
                  <el-tag size="small" effect="plain">{{ target.platform || platformTypeLabel(target.platformType) }}</el-tag>
                  <span>{{ target.accountName || target.accountFile || '未记录账号' }}</span>
                </div>
                <el-tag size="small" :type="publishStatusTag(target.status)" effect="plain">
                  {{ publishStatusText(target.status) }}
                </el-tag>
                <span class="target-meta">耗时 {{ formatDurationMs(target.durationMs) }}</span>
                <span class="target-meta">{{ target.updatedAt || target.publishedAt || '-' }}</span>
                <span class="target-message">{{ target.message || '-' }}</span>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :disabled="isTargetRecordLocked(target)"
                  @click="deletePublishRecord(row, target)"
                >
                  删除记录
                </el-button>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="发布任务" min-width="360">
          <template #default="{ row }">
            <div class="material-cell">
              <strong>{{ row.chineseTitle || '未命名发布任务' }}</strong>
              <span>{{ row.englishTitle || row.sourceUrl || '暂无英文标题' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ row.filesize }} MB</template>
        </el-table-column>
        <el-table-column prop="publishedAt" label="任务时间" width="180" />
        <el-table-column label="总体状态" width="120">
          <template #default="{ row }">
            <el-tag :type="publishStatusTag(row.overallStatus)" effect="plain" size="small">
              {{ publishStatusText(row.overallStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="平台情况" width="170">
          <template #default="{ row }">
            <div class="status-summary">
              <span class="success">成功 {{ row.summary?.success || 0 }}</span>
              <span class="failed">失败 {{ (row.summary?.failed || 0) + (row.summary?.timeout || 0) }}</span>
              <span>共 {{ row.summary?.total || 0 }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-link
              v-if="publishedPreviewUrl(row)"
              :href="publishedPreviewUrl(row)"
              target="_blank"
              type="primary"
            >
              预览视频
            </el-link>
            <span v-else class="muted-text">无预览</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  User, Upload, Timer, DataAnalysis, Search, Refresh, Picture
} from '@element-plus/icons-vue'
import { accountApi } from '@/api/account'
import { materialApi } from '@/api/material'
import { useAccountStore } from '@/stores/account'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const accountStore = useAccountStore()
const appStore = useAppStore()
const loading = ref(false)
const materialSummary = ref({ total: 0, processed: 0, downloaded: 0, other: 0 })

const quickActions = [
  { title: '视频采集处理', desc: '查找线索、下载、翻译和烧录', path: '/youtube-research', icon: Search },
  { title: '账号管理', desc: '维护平台账号和 Cookie 状态', path: '/account-management', icon: User },
  { title: '素材管理', desc: '查看原视频与处理后视频', path: '/material-management', icon: Picture },
  { title: '发布中心', desc: '配置多平台发布任务', path: '/publish-center', icon: Upload },
  { title: '处理统计', desc: '查看阶段耗时与模型成本', path: '/workflow-statistics', icon: DataAnalysis },
  { title: '关于系统', desc: '查看能力和技术栈', path: '/about', icon: Timer }
]

const accountStats = computed(() => {
  const accounts = accountStore.accounts
  const normal = accounts.filter(a => a.status === '正常').length
  const abnormal = accounts.filter(a => a.status !== '正常' && a.status !== '验证中').length
  return { total: accounts.length, normal, abnormal }
})

const platformStats = computed(() => {
  const accounts = accountStore.accounts
  const kuaishou = accounts.filter(a => a.platform === '快手').length
  const douyin = accounts.filter(a => a.platform === '抖音').length
  const bilibili = accounts.filter(a => a.platform === 'B站').length
  const channels = accounts.filter(a => a.platform === '视频号').length
  const xiaohongshu = accounts.filter(a => a.platform === '小红书').length
  const total = [kuaishou, douyin, bilibili, channels, xiaohongshu].filter(n => n > 0).length
  return { total, kuaishou, douyin, bilibili, channels, xiaohongshu }
})

const videoExtensions = ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv']
const imageExtensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']

const contentStats = computed(() => {
  const summary = materialSummary.value || {}
  if (Number(summary.total || 0) > 0) {
    const videos = Number(summary.videos ?? (Number(summary.processed || 0) + Number(summary.downloaded || 0)))
    const images = Number(summary.images || 0)
    return {
      total: Number(summary.total || 0),
      videos,
      images,
      others: Math.max(0, Number(summary.total || 0) - videos - images)
    }
  }
  const materials = appStore.materials
  const videos = materials.filter(m => videoExtensions.some(ext => m.filename.toLowerCase().endsWith(ext))).length
  const images = materials.filter(m => imageExtensions.some(ext => m.filename.toLowerCase().endsWith(ext))).length
  return { total: materials.length, videos, images, others: materials.length - videos - images }
})

const recentPublishTasks = computed(() => {
  return [...appStore.publishTasks]
    .sort((a, b) => new Date(b.publishedAt) - new Date(a.publishedAt))
    .slice(0, 6)
})

const publishedPreviewUrl = (row) => {
  if (!row.filePath) return ''
  return materialApi.getMaterialPreviewUrl(row.filePath)
}

const navigateTo = (path) => {
  router.push(path)
}

const platformTypeLabel = (type) => {
  return {
    1: '小红书',
    2: '快手',
    3: '抖音',
    4: '视频号',
    5: 'B站'
  }[Number(type)] || '未知平台'
}

const publishStatusText = (status = '') => {
  return {
    pending: '等待发布',
    running: '发布中',
    success: '发布成功',
    failed: '发布失败',
    timeout: '发布超时',
    partial: '部分成功'
  }[status || 'success'] || '未知'
}

const publishStatusTag = (status = '') => {
  return {
    pending: 'warning',
    running: 'primary',
    success: 'success',
    failed: 'danger',
    timeout: 'danger',
    partial: 'warning'
  }[status || 'success'] || 'info'
}

const formatDurationMs = (value) => {
  const ms = Number(value || 0)
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${seconds % 60}s`
}

const isTargetRecordLocked = (target) => ['pending', 'running'].includes(target.status)

const deletePublishRecord = async (task, target) => {
  void task
  try {
    await ElMessageBox.confirm(
      `确认删除「${target.platform || platformTypeLabel(target.platformType)}」的本地发布记录？此操作不会删除平台上已经发布的视频，但会释放该平台状态，允许后续重新发布。`,
      '删除本地发布记录',
      {
        confirmButtonText: '删除记录',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    const res = await materialApi.deletePublishTargetRecord(target.id)
    if (res.code !== 200) {
      throw new Error(res.msg || '删除失败')
    }
    ElMessage.success(res.msg || '已删除本地发布记录')
    await fetchDashboardData()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message || '删除发布记录失败')
  }
}

const fetchDashboardData = async () => {
  loading.value = true
  try {
    const [accountRes, materialRes, publishTasksRes] = await Promise.allSettled([
      accountApi.getAccounts(),
      materialApi.getAllMaterials({ page: 1, pageSize: 20 }),
      materialApi.getPublishTasks({ limit: 20 })
    ])

    if (accountRes.status === 'fulfilled' && accountRes.value.code === 200) {
      accountStore.setAccounts(accountRes.value.data)
    }
    if (materialRes.status === 'fulfilled' && materialRes.value.code === 200) {
      appStore.setMaterials(materialRes.value.data?.items || [])
      materialSummary.value = materialRes.value.data?.summary || materialSummary.value
    }
    if (publishTasksRes.status === 'fulfilled' && publishTasksRes.value.code === 200) {
      appStore.setPublishTasks(publishTasksRes.value.data || [])
    }
  } catch (error) {
    console.error('获取仪表盘数据失败:', error)
  } finally {
    loading.value = false
  }
}

onMounted(fetchDashboardData)
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

$panel-border: #dce6f2;
$panel-shadow: 0 12px 28px rgba(28, 55, 90, 0.08);
$accent-blue: #2563eb;
$accent-teal: #0f9f8f;
$ink-strong: #172033;

.dashboard {
  display: grid;
  gap: 16px;

  :deep(.el-card) {
    border: 1px solid $panel-border;
    border-radius: 8px;
    box-shadow: $panel-shadow;
  }

  :deep(.el-card__header) {
    padding: 14px 16px;
  }

  :deep(.el-table th.el-table__cell) {
    background: #f8fbff;
    color: #5c6678;
    font-weight: 600;
  }
}

.workspace-hero {
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
}

.hero-copy {
  h1 {
    margin: 4px 0 8px;
    color: $ink-strong;
    font-size: 25px;
    line-height: 1.25;
    font-weight: 700;
  }

  p {
    max-width: 720px;
    margin: 0;
    color: #5b667a;
    font-size: 14px;
    line-height: 1.7;
  }
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.metric-card,
.action-card {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 8px;
  background: #fff;
  text-align: left;
  box-shadow: 0 8px 18px rgba(28, 55, 90, 0.05);
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;

  &:hover {
    border-color: rgba(37, 99, 235, 0.38);
    transform: translateY(-1px);
    box-shadow: 0 10px 22px rgba(37, 99, 235, 0.1);
  }

  span,
  small {
    color: $text-secondary;
    font-size: 13px;
  }

  strong {
    color: $ink-strong;
    font-size: 24px;
    line-height: 1.15;
  }
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.action-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  color: $accent-blue;
  background: rgba(37, 99, 235, 0.1);
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

.material-cell {
  display: grid;
  gap: 4px;
  min-width: 0;

  strong,
  span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: $ink-strong;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

.target-records {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  background: #f8fbff;
}

.target-help {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.6;
}

.target-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.2fr) 90px 90px 170px minmax(180px, 1fr) 88px;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #dce6f2;
  border-radius: 8px;
  background: #fff;
}

.target-platform {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;

  span:last-child {
    min-width: 0;
    overflow: hidden;
    color: #4b5563;
    font-size: 13px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.target-meta {
  color: #6b7280;
  font-size: 12px;
}

.target-message {
  min-width: 0;
  overflow: hidden;
  color: #334155;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 12px;

  .success {
    color: #059669;
  }

  .failed {
    color: #dc2626;
  }
}

@media (max-width: 1200px) {
  .quick-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .target-row {
    grid-template-columns: 1fr 90px 80px;
  }
}

@media (max-width: 860px) {
  .workspace-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-grid,
  .quick-grid {
    grid-template-columns: 1fr;
  }

  .target-row {
    grid-template-columns: 1fr;
  }
}
</style>
