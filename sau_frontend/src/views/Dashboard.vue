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
            <span class="panel-kicker">PUBLISHED MATERIALS</span>
            <h2>已发布素材</h2>
          </div>
          <el-button text type="primary" @click="navigateTo('/publish-center')">查看发布中心</el-button>
        </div>
      </template>

      <el-table :data="recentPublishedMaterials" style="width: 100%" v-loading="loading" empty-text="暂无已发布素材">
        <el-table-column label="素材" min-width="320">
          <template #default="{ row }">
            <div class="material-cell">
              <strong>{{ publishedChineseTitle(row) }}</strong>
              <span>{{ publishedEnglishTitle(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="filesize" label="大小" width="110">
          <template #default="{ row }">{{ row.filesize }} MB</template>
        </el-table-column>
        <el-table-column prop="publishedAt" label="发布时间" width="180" />
        <el-table-column label="平台" width="120">
          <template #default="{ row }">
            <el-tag type="success" effect="plain" size="small">
              {{ row.platform || '已发布' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-link
              v-if="publishedPreviewUrl(row)"
              :href="publishedPreviewUrl(row)"
              target="_blank"
              type="primary"
            >
              预览
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
import {
  User, Platform, Document, Upload, Timer, DataAnalysis, Search, Refresh, Picture
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

const recentPublishedMaterials = computed(() => {
  return [...appStore.publishedMaterials]
    .sort((a, b) => new Date(b.publishedAt) - new Date(a.publishedAt))
    .slice(0, 6)
})

const stripPublishTitleMeta = (value = '') => {
  return String(value || '').split('; description=')[0].trim()
}

const publishedChineseTitle = (row) => {
  return stripPublishTitleMeta(row.publishTitle) || row.metadata?.publishTitle || row.title || row.filename || '未命名发布素材'
}

const publishedEnglishTitle = (row) => {
  return row.title || row.filename || row.sourceUrl || '暂无英文标题'
}

const publishedPreviewUrl = (row) => {
  if (!row.filePath) return ''
  return materialApi.getMaterialPreviewUrl(row.filePath)
}

const getFileType = (filename = '') => {
  if (videoExtensions.some(ext => filename.toLowerCase().endsWith(ext))) return '视频'
  if (imageExtensions.some(ext => filename.toLowerCase().endsWith(ext))) return '图片'
  return '其他'
}

const getFileTypeTag = (filename) => {
  const type = getFileType(filename)
  return { 视频: 'success', 图片: 'warning', 其他: 'info' }[type] || 'info'
}

const navigateTo = (path) => {
  router.push(path)
}

const fetchDashboardData = async () => {
  loading.value = true
  try {
    const [accountRes, materialRes, publishedRes] = await Promise.allSettled([
      accountApi.getAccounts(),
      materialApi.getAllMaterials({ page: 1, pageSize: 20 }),
      materialApi.getPublishedMaterials({ limit: 20 })
    ])

    if (accountRes.status === 'fulfilled' && accountRes.value.code === 200) {
      accountStore.setAccounts(accountRes.value.data)
    }
    if (materialRes.status === 'fulfilled' && materialRes.value.code === 200) {
      appStore.setMaterials(materialRes.value.data?.items || [])
      materialSummary.value = materialRes.value.data?.summary || materialSummary.value
    }
    if (publishedRes.status === 'fulfilled' && publishedRes.value.code === 200) {
      appStore.setPublishedMaterials(publishedRes.value.data || [])
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

@media (max-width: 1200px) {
  .quick-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
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
}
</style>
