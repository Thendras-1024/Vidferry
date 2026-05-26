<template>
  <div class="publish-center">
    <section class="page-hero">
      <div>
        <span class="eyebrow">PUBLISH DESK</span>
        <h1>发布中心</h1>
        <p>按批次准备素材、账号、平台、标题话题和定时发布策略，支持多批次连续发布。</p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="addTab">
          <el-icon><Plus /></el-icon>
          <span>新增批次</span>
        </el-button>
        <el-button type="success" :loading="batchPublishing" @click="batchPublish">批量发布</el-button>
      </div>
    </section>

    <div class="publish-workbench">
      <aside class="batch-panel">
        <div class="panel-title">
          <span class="panel-kicker">BATCHES</span>
          <h2>发布批次</h2>
        </div>
        <div class="batch-list">
          <button
            v-for="tab in tabs"
            :key="tab.name"
            type="button"
            class="batch-item"
            :class="{ active: activeTab === tab.name }"
            @click="activeTab = tab.name"
          >
            <span>{{ tab.label }}</span>
            <small>{{ tab.fileList.length }} 个素材 · {{ tab.selectedAccounts.length }} 个账号</small>
            <el-icon v-if="tabs.length > 1" class="close-icon" @click.stop="removeTab(tab.name)"><Close /></el-icon>
          </button>
        </div>
      </aside>

      <main class="compose-panel">
        <div v-for="tab in tabs" :key="tab.name" v-show="activeTab === tab.name" class="compose-content">
          <el-alert v-if="tab.publishStatus" :title="tab.publishStatus.message" :type="tab.publishStatus.type" :closable="false" show-icon />

          <section class="form-section">
            <div class="section-heading">
              <span class="step-index">1</span>
              <div>
                <h3>视频素材</h3>
                <p>仅支持选择已完成处理的视频，避免误发布原始下载素材。</p>
              </div>
              <el-button type="primary" @click="selectMaterialLibrary(tab)">
                <el-icon><Folder /></el-icon>
                <span>选择处理后视频</span>
              </el-button>
            </div>
            <div v-if="tab.fileList.length > 0" class="file-list">
              <div v-for="(file, index) in tab.fileList" :key="index" class="file-item">
                <div class="selected-video-main">
                  <el-link :href="file.url" target="_blank" type="primary">{{ file.displayTitle || file.name }}</el-link>
                  <div class="selected-video-meta">
                    <span>{{ file.channel || '未知博主' }}</span>
                    <span>{{ file.processType || '处理后视频' }}</span>
                    <span>{{ file.subtitleLanguageLabel || '字幕语言未知' }}</span>
                    <span>{{ formatFileSize(file.size) }}</span>
                  </div>
                </div>
                <el-button type="danger" size="small" text @click="removeFile(tab, index)">删除</el-button>
              </div>
            </div>
            <el-empty v-else description="暂无视频素材" :image-size="72" />
          </section>

          <section class="form-section split-section">
            <div class="sub-panel">
              <div class="section-heading compact">
                <span class="step-index">2</span>
                <div>
                  <h3>账号</h3>
                  <p>选择当前平台可用账号。</p>
                </div>
              </div>
              <div class="tag-cloud">
                <el-tag v-for="(account, index) in tab.selectedAccounts" :key="index" closable @close="removeAccount(tab, index)">
                  {{ getAccountDisplayName(account) }}
                </el-tag>
                <el-button type="primary" plain @click="openAccountDialog(tab)">选择账号</el-button>
              </div>
            </div>

            <div class="sub-panel">
              <div class="section-heading compact">
                <span class="step-index">3</span>
                <div>
                  <h3>平台</h3>
                  <p>确定本批次发布目标。</p>
                </div>
              </div>
              <el-radio-group v-model="tab.selectedPlatform" class="platform-radios">
                <el-radio-button v-for="platform in platforms" :key="platform.key" :label="platform.key">
                  {{ platform.name }}
                </el-radio-button>
              </el-radio-group>
            </div>
          </section>

          <section class="form-section">
            <div class="section-heading compact">
              <span class="step-index">4</span>
              <div>
                <h3>发布内容</h3>
                <p>优先读取视频绑定的已保存发布稿，可在这里继续修改并保存回视频。</p>
              </div>
              <el-button size="small" type="primary" plain :disabled="tab.fileList.length === 0" @click="saveTabPublishDraft(tab)">保存发布稿</el-button>
            </div>
            <el-input v-model="tab.title" type="textarea" :rows="3" placeholder="选择素材后自动填充标题，可修改后保存" maxlength="100" show-word-limit />
            <el-input v-model="tab.description" type="textarea" :rows="4" placeholder="选择素材后自动填充文案，可修改后保存" maxlength="800" show-word-limit />
            <div class="tag-cloud topic-cloud">
              <el-tag v-for="(topic, index) in tab.selectedTopics" :key="index">#{{ topic }}</el-tag>
              <el-tag v-if="tab.selectedTopics.length === 0" type="info" effect="plain">暂无已保存话题</el-tag>
            </div>
            <div v-if="tab.selectedPlatform === 3" class="two-col">
              <el-input v-model="tab.productTitle" placeholder="商品名称" maxlength="200" />
              <el-input v-model="tab.productLink" placeholder="商品链接" maxlength="200" />
            </div>
            <div class="inline-options">
              <el-checkbox v-model="tab.isOriginal" label="声明原创" />
              <el-checkbox v-if="tab.selectedPlatform === 2" v-model="tab.isDraft" label="视频号仅保存草稿" />
            </div>
          </section>

          <section class="form-section">
            <div class="section-heading compact">
              <span class="step-index">5</span>
              <div>
                <h3>发布时间</h3>
                <p>立即发布或设置批量排期。</p>
              </div>
            </div>
            <div class="schedule-controls">
              <el-switch v-model="tab.scheduleEnabled" active-text="定时发布" inactive-text="立即发布" />
              <div v-if="tab.scheduleEnabled" class="schedule-settings">
                <div class="schedule-item">
                  <span>每天发布视频数</span>
                  <el-select v-model="tab.videosPerDay" placeholder="选择发布数量">
                    <el-option v-for="num in 55" :key="num" :label="num" :value="num" />
                  </el-select>
                </div>
                <div class="schedule-item wide">
                  <span>每天发布时间</span>
                  <div class="time-list">
                    <el-time-select v-for="(time, index) in tab.dailyTimes" :key="index" v-model="tab.dailyTimes[index]" start="00:00" step="00:30" end="23:30" placeholder="选择时间" />
                    <el-button v-if="tab.dailyTimes.length < tab.videosPerDay" type="primary" size="small" @click="tab.dailyTimes.push('10:00')">添加时间</el-button>
                  </div>
                </div>
                <div class="schedule-item">
                  <span>开始天数</span>
                  <el-select v-model="tab.startDays" placeholder="选择开始天数">
                    <el-option label="明天" :value="0" />
                    <el-option label="后天" :value="1" />
                  </el-select>
                </div>
              </div>
            </div>
          </section>

          <div class="submit-bar">
            <el-button @click="cancelPublish(tab)">取消</el-button>
            <el-button type="primary" @click="confirmPublish(tab)" :loading="tab.publishing || false">
              {{ tab.publishing ? '发布中...' : '发布' }}
            </el-button>
          </div>
        </div>
      </main>
    </div>

    <section class="published-panel">
      <div class="panel-heading-row">
        <div>
          <span class="panel-kicker">PUBLISHED</span>
          <h2>已发布视频</h2>
          <p>汇总已经提交到国内平台的处理后视频，方便从发布中心追踪结果。</p>
        </div>
        <el-button :loading="publishedLoading" @click="loadPublishedVideos">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </div>

      <div class="published-summary">
        <div class="summary-tile">
          <span>已发布</span>
          <strong>{{ publishedVideos.length }}</strong>
        </div>
        <div class="summary-tile">
          <span>抖音任务</span>
          <strong>{{ publishedPlatformStats.douyin }}</strong>
        </div>
        <div class="summary-tile">
          <span>B站任务</span>
          <strong>{{ publishedPlatformStats.bilibili }}</strong>
        </div>
        <div class="summary-tile">
          <span>处理后素材</span>
          <strong>{{ publishedMaterialCount }}</strong>
        </div>
      </div>

      <div v-if="publishedVideos.length > 0" class="published-list">
        <article v-for="video in publishedVideos" :key="video.id" class="published-card">
          <div class="published-cover">
            <img v-if="video.thumbnail" :src="video.thumbnail" :alt="video.title" />
            <span v-else>VIDEO</span>
          </div>
          <div class="published-body">
            <div class="published-title-row">
              <h3>{{ video.title || '未命名视频' }}</h3>
              <el-tag size="small" type="success">已发布</el-tag>
            </div>
            <div class="published-meta">
              <span>{{ video.channel || '未知博主' }}</span>
              <span>{{ video.subscribers || '粉丝未知' }}</span>
              <span>{{ video.publishedAt || '原发布时间未知' }}</span>
              <span>{{ video.duration || '-' }}</span>
            </div>
            <div class="published-tags">
              <el-tag v-for="tag in publishedPlatforms(video)" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
              <el-tag size="small" type="warning" effect="light">{{ video.processVersionLabel || '处理版本未知' }}</el-tag>
              <el-tag size="small" type="success" effect="plain">{{ video.subtitleLanguageLabel || '字幕语言未知' }}</el-tag>
              <span>{{ video.processedFileSizeLabel || '素材大小未知' }}</span>
            </div>
            <div class="published-actions">
              <el-link v-if="video.url" :href="video.url" target="_blank" type="primary">打开原链接</el-link>
              <el-link v-if="video.processedPreviewUrl" :href="video.processedPreviewUrl" target="_blank" type="success">预览处理后视频</el-link>
              <span>{{ video.publishedLabel }}</span>
            </div>
          </div>
        </article>
      </div>
      <el-empty v-else description="暂无已发布视频，发布成功后会在这里汇总展示。" :image-size="84" />
    </section>

    <el-dialog v-model="batchPublishDialogVisible" title="批量发布进度" width="500px" :close-on-click-modal="false" :close-on-press-escape="false" :show-close="false">
      <div class="publish-progress">
        <el-progress :percentage="publishProgress" :status="publishProgress === 100 ? 'success' : ''" />
        <div v-if="currentPublishingTab" class="current-publishing">正在发布：{{ currentPublishingTab.label }}</div>
        <div class="publish-results" v-if="publishResults.length > 0">
          <div v-for="(result, index) in publishResults" :key="index" :class="['result-item', result.status]">
            <span class="label">{{ result.label }}</span>
            <span class="message">{{ result.message }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="cancelBatchPublish" :disabled="publishProgress === 100">取消发布</el-button>
          <el-button type="primary" @click="batchPublishDialogVisible = false" v-if="publishProgress === 100">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="materialLibraryVisible"
      title="选择处理后视频"
      width="min(960px, calc(100vw - 32px))"
      top="6vh"
      class="material-library-dialog"
    >
      <el-alert
        title="发布中心只显示已经完成字幕、作者信息和兼容转码的处理后视频。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-checkbox-group v-model="selectedMaterials">
        <div v-if="publishableMaterials.length > 0" class="material-list publishable-list">
          <div v-for="material in publishableMaterials" :key="material.id" class="material-item publishable-item">
            <el-checkbox :label="material.id">
              <div class="material-info">
                <div class="material-name">{{ material.displayTitle || material.filename }}</div>
                <div class="material-details">
                  <span>{{ material.displayChannel || '未知博主' }}</span>
                  <span>{{ material.displaySubscribers || '粉丝未知' }}</span>
                  <span>{{ material.displayPublishedAt || '发布时间未知' }}</span>
                </div>
                <div class="material-publish-draft">
                  <span class="draft-label">发布标题</span>
                  <strong>{{ materialPublishDraft(material).title || '暂无已保存发布标题' }}</strong>
                </div>
                <div class="material-topic-list">
                  <span class="draft-label">话题</span>
                  <el-tag
                    v-for="tag in materialPublishDraft(material).tags"
                    :key="tag"
                    size="small"
                    type="success"
                    effect="plain"
                  >
                    #{{ tag }}
                  </el-tag>
                  <span v-if="materialPublishDraft(material).tags.length === 0" class="empty-topic">暂无话题</span>
                </div>
                <div class="material-badges">
                  <el-tag size="small" type="warning" effect="light">{{ material.processType || '处理后视频' }}</el-tag>
                  <el-tag size="small" type="success" effect="plain">{{ material.subtitleLanguageLabel || '字幕语言未知' }}</el-tag>
                  <el-tag size="small" effect="plain">{{ processVersionLabel(material.processVersion) }}</el-tag>
                  <span>{{ material.duration || '-' }}</span>
                  <span>{{ material.filesize }} MB</span>
                </div>
              </div>
            </el-checkbox>
          </div>
        </div>
        <el-empty v-else description="暂无可发布的处理后视频，请先在视频采集处理页完成处理。" />
      </el-checkbox-group>
      <template #footer><div class="dialog-footer"><el-button @click="materialLibraryVisible = false">取消</el-button><el-button type="primary" @click="confirmMaterialSelection">确定</el-button></div></template>
    </el-dialog>

    <el-dialog v-model="accountDialogVisible" title="选择账号" width="600px" class="account-dialog">
      <el-checkbox-group v-model="tempSelectedAccounts">
        <div class="account-list">
          <el-checkbox v-for="account in availableAccounts" :key="account.id" :label="account.id" class="account-item">
            <span>{{ account.name }}</span>
          </el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer><div class="dialog-footer"><el-button @click="accountDialogVisible = false">取消</el-button><el-button type="primary" @click="confirmAccountSelection">确定</el-button></div></template>
    </el-dialog>

    <el-dialog v-model="topicDialogVisible" title="添加话题" width="600px" class="topic-dialog">
      <div class="custom-topic-input">
        <el-input v-model="customTopic" placeholder="输入自定义话题"><template #prepend>#</template></el-input>
        <el-button type="primary" @click="addCustomTopic">添加</el-button>
      </div>
      <div class="recommended-topics">
        <h4>推荐话题</h4>
        <div class="topic-grid">
          <el-button v-for="topic in recommendedTopics" :key="topic" :type="currentTab?.selectedTopics?.includes(topic) ? 'primary' : 'default'" @click="toggleRecommendedTopic(topic)">{{ topic }}</el-button>
        </div>
      </div>
      <template #footer><div class="dialog-footer"><el-button @click="topicDialogVisible = false">取消</el-button><el-button type="primary" @click="confirmTopicSelection">确定</el-button></div></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { Plus, Close, Folder, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAccountStore } from '@/stores/account'
import { useAppStore } from '@/stores/app'
import { materialApi } from '@/api/material'
import { youtubeApi } from '@/api/youtube'
import { http } from '@/utils/request'

// 当前激活的tab
const activeTab = ref('tab1')

// tab计数器
let tabCounter = 1

const PUBLISH_DRAFT_STORAGE_KEY = 'vidferry:publish-center:draft:v1'

// 获取应用状态管理
const appStore = useAppStore()
const accountStore = useAccountStore()

// 上传相关状态
const materialLibraryVisible = ref(false)
const currentUploadTab = ref(null)
const selectedMaterials = ref([])
const materials = computed(() => appStore.materials)
const publishableMaterials = computed(() => {
  return materials.value.filter(material => material.source_type === 'youtube_processed')
})
const publishedLoading = ref(false)
const publishedVideos = ref([])

// 批量发布相关状态
const batchPublishing = ref(false)
const batchPublishMessage = ref('')
const batchPublishType = ref('info')

// 平台列表 - 对应后端type字段
const platforms = [
  { key: 3, name: '抖音' },
  { key: 5, name: 'B站' },
  { key: 4, name: '快手' },
  { key: 2, name: '视频号' },
  { key: 1, name: '小红书' }
]

const platformNameByKey = platforms.reduce((map, platform) => {
  map[platform.key] = platform.name
  return map
}, {})

const defaultTabInit = {
  name: 'tab1',
  label: '发布1',
  fileList: [], // 后端返回的文件名列表
  displayFileList: [], // 用于显示的文件列表
  selectedAccounts: [], // 选中的账号ID列表
  selectedPlatform: 1, // 选中的平台（单选）
  title: '',
  description: '',
  productLink: '', // 商品链接
  productTitle: '', // 商品名称
  selectedTopics: [], // 话题列表（不带#号）
  contentLocked: false,
  scheduleEnabled: false, // 定时发布开关
  videosPerDay: 1, // 每天发布视频数量
  dailyTimes: ['10:00'], // 每天发布时间点列表
  startDays: 0, // 从今天开始计算的发布天数，0表示明天，1表示后天
  publishStatus: null, // 发布状态，包含message和type
  publishing: false, // 发布状态，用于控制按钮loading效果
  isDraft: false, // 是否保存为草稿，仅视频号平台可见
  isOriginal: false // 是否标记为原创
}

// helper to create a fresh deep-copied tab from defaultTabInit
const makeNewTab = () => {
  // prefer structuredClone when available (newer browsers/node), fallback to JSON
  try {
    return typeof structuredClone === 'function' ? structuredClone(defaultTabInit) : JSON.parse(JSON.stringify(defaultTabInit))
  } catch (e) {
    return JSON.parse(JSON.stringify(defaultTabInit))
  }
}

const normalizeSelectedAccounts = (accounts = []) => {
  const existingAccountIds = new Set(accountStore.accounts.map(account => String(account.id)))
  const seen = new Set()
  return (Array.isArray(accounts) ? accounts : [])
    .filter(accountId => existingAccountIds.has(String(accountId)))
    .filter(accountId => {
      const key = String(accountId)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

const readPublishDraft = () => {
  try {
    const raw = localStorage.getItem(PUBLISH_DRAFT_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed?.tabs) ? parsed : null
  } catch (error) {
    console.warn('读取发布中心草稿失败:', error)
    return null
  }
}

const normalizePublishTab = (tab, index) => {
  const nextTab = makeNewTab()
  Object.assign(nextTab, {
    ...tab,
    name: tab?.name || `tab${index + 1}`,
    label: tab?.label || `发布${index + 1}`,
    fileList: Array.isArray(tab?.fileList) ? tab.fileList : [],
    selectedAccounts: normalizeSelectedAccounts(tab?.selectedAccounts),
    selectedTopics: Array.isArray(tab?.selectedTopics) ? tab.selectedTopics : [],
    dailyTimes: Array.isArray(tab?.dailyTimes) && tab.dailyTimes.length > 0 ? tab.dailyTimes : ['10:00'],
    publishStatus: null,
    publishing: false
  })
  nextTab.displayFileList = nextTab.fileList.map(item => ({
    name: item.name,
    url: item.url
  }))
  return nextTab
}

const serializePublishTab = (tab) => ({
  name: tab.name,
  label: tab.label,
  fileList: tab.fileList,
  displayFileList: tab.displayFileList,
  selectedAccounts: normalizeSelectedAccounts(tab.selectedAccounts),
  selectedPlatform: tab.selectedPlatform,
  title: tab.title,
  description: tab.description,
  productLink: tab.productLink,
  productTitle: tab.productTitle,
  selectedTopics: tab.selectedTopics,
  contentLocked: Boolean(tab.contentLocked),
  scheduleEnabled: tab.scheduleEnabled,
  videosPerDay: tab.videosPerDay,
  dailyTimes: tab.dailyTimes,
  startDays: tab.startDays,
  isDraft: tab.isDraft,
  isOriginal: tab.isOriginal
})

const savePublishDraft = () => {
  try {
    localStorage.setItem(PUBLISH_DRAFT_STORAGE_KEY, JSON.stringify({
      activeTab: activeTab.value,
      tabCounter,
      tabs: tabs.map(serializePublishTab)
    }))
  } catch (error) {
    console.warn('保存发布中心草稿失败:', error)
  }
}

const restoredDraft = readPublishDraft()
const restoredTabs = restoredDraft?.tabs?.length
  ? restoredDraft.tabs.map(normalizePublishTab)
  : [makeNewTab()]

if (restoredDraft?.activeTab && restoredTabs.some(tab => tab.name === restoredDraft.activeTab)) {
  activeTab.value = restoredDraft.activeTab
}

tabCounter = Math.max(
  Number(restoredDraft?.tabCounter || 1),
  ...restoredTabs.map(tab => Number(String(tab.name).replace('tab', '')) || 1)
)

// tab页数据 - 默认只有一个tab (use deep copy to avoid shared refs)
const tabs = reactive(restoredTabs)

watch(activeTab, savePublishDraft)
watch(tabs, savePublishDraft, { deep: true })

// 账号相关状态
const accountDialogVisible = ref(false)
const tempSelectedAccounts = ref([])
const currentTab = ref(null)

// 根据选择的平台获取可用账号列表
const availableAccounts = computed(() => {
  const platformMap = {
    3: '抖音',
    5: 'B站',
    2: '视频号',
    1: '小红书',
    4: '快手'
  }
  const currentPlatform = currentTab.value ? platformMap[currentTab.value.selectedPlatform] : null
  return currentPlatform ? accountStore.accounts.filter(acc => acc.platform === currentPlatform) : []
})

// 话题相关状态
const topicDialogVisible = ref(false)
const customTopic = ref('')

// 推荐话题列表
const recommendedTopics = [
  '游戏', '电影', '音乐', '美食', '旅行', '文化',
  '科技', '生活', '娱乐', '体育', '教育', '艺术',
  '健康', '时尚', '美妆', '摄影', '宠物', '汽车'
]

// 添加新tab
const addTab = () => {
  tabCounter++
  const newTab = makeNewTab()
  newTab.name = `tab${tabCounter}`
  newTab.label = `发布${tabCounter}`
  tabs.push(newTab)
  activeTab.value = newTab.name
}

// 删除tab
const removeTab = (tabName) => {
  const index = tabs.findIndex(tab => tab.name === tabName)
  if (index > -1) {
    tabs.splice(index, 1)
    // 如果删除的是当前激活的tab，切换到第一个tab
    if (activeTab.value === tabName && tabs.length > 0) {
      activeTab.value = tabs[0].name
    }
  }
}

// 删除已上传文件
const removeFile = (tab, index) => {
  // 从文件列表中删除
  tab.fileList.splice(index, 1)
  
  // 更新显示列表
  tab.displayFileList = [...tab.fileList.map(item => ({
    name: item.name,
    url: item.url
  }))]
  
  ElMessage.success('文件删除成功')
}

const normalizeAnalysisTags = (tags = []) => {
  return Array.isArray(tags)
    ? tags.map(tag => String(tag || '').trim().replace(/^#/, '')).filter(Boolean)
    : []
}

const normalizePublishDraft = (material) => {
  const draft = material?.publishDraft || {}
  if (draft && Object.keys(draft).length > 0) {
    return {
      title: draft.title || '',
      description: draft.description || '',
      tags: normalizeAnalysisTags(draft.tags),
      fromSavedDraft: true
    }
  }

  const result = material?.analysisResult || {}
  const titleOptions = Array.isArray(result.title_options) ? result.title_options.filter(Boolean) : []
  return {
    title: titleOptions[0] || '',
    description: result.publish_copy || '',
    tags: normalizeAnalysisTags(result.tags),
    fromSavedDraft: false
  }
}

const materialPublishDraft = (material) => normalizePublishDraft(material)

const applyPublishDraftToPublishTab = (tab, drafts = []) => {
  const firstDraft = drafts.find(draft => draft && (draft.title || draft.description || draft.tags.length > 0))
  if (!firstDraft) return

  tab.title = firstDraft.title || ''
  tab.description = firstDraft.description || ''
  tab.selectedTopics = firstDraft.tags || []
  tab.contentLocked = true

  if (!firstDraft.fromSavedDraft) {
    ElMessage.warning('该素材还没有保存发布稿，已用 LLM 原稿临时填充；修改后请点击保存发布稿。')
  }
}

const saveTabPublishDraft = async (tab) => {
  const targetFile = tab.fileList.find(file => file.videoId)
  if (!targetFile) {
    ElMessage.warning('当前批次没有绑定视频线索的素材，无法保存发布稿')
    return
  }
  try {
    const response = await youtubeApi.updatePublishDraft(targetFile.videoId, {
      title: tab.title,
      description: tab.description,
      tags: tab.selectedTopics
    })
    const savedDraft = response.data?.draft || {
      title: tab.title,
      description: tab.description,
      tags: tab.selectedTopics
    }
    tab.fileList.forEach(file => {
      if (file.videoId === targetFile.videoId) {
        file.publishDraft = savedDraft
      }
    })
    const material = appStore.materials.find(item => String(item.id) === String(targetFile.materialId))
    if (material) {
      material.publishDraft = savedDraft
    }
    tab.contentLocked = true
    ElMessage.success('发布稿已保存到视频')
  } catch (error) {
    console.error('保存发布稿失败:', error)
    ElMessage.error('保存发布稿失败')
  }
}

// 话题相关方法
// 打开添加话题弹窗
const openTopicDialog = (tab) => {
  currentTab.value = tab
  topicDialogVisible.value = true
}

// 添加自定义话题
const addCustomTopic = () => {
  if (!customTopic.value.trim()) {
    ElMessage.warning('请输入话题内容')
    return
  }
  if (currentTab.value && !currentTab.value.selectedTopics.includes(customTopic.value.trim())) {
    currentTab.value.selectedTopics.push(customTopic.value.trim())
    customTopic.value = ''
    ElMessage.success('话题添加成功')
  } else {
    ElMessage.warning('话题已存在')
  }
}

// 切换推荐话题
const toggleRecommendedTopic = (topic) => {
  if (!currentTab.value) return
  
  const index = currentTab.value.selectedTopics.indexOf(topic)
  if (index > -1) {
    currentTab.value.selectedTopics.splice(index, 1)
  } else {
    currentTab.value.selectedTopics.push(topic)
  }
}

// 删除话题
const removeTopic = (tab, index) => {
  if (tab.contentLocked) {
    ElMessage.info('发布内容需在视频采集处理页修改并保存')
    return
  }
  tab.selectedTopics.splice(index, 1)
}

// 确认添加话题
const confirmTopicSelection = () => {
  topicDialogVisible.value = false
  customTopic.value = ''
  currentTab.value = null
  ElMessage.success('添加话题完成')
}

// 账号选择相关方法
// 打开账号选择弹窗
const openAccountDialog = (tab) => {
  currentTab.value = tab
  tempSelectedAccounts.value = [...tab.selectedAccounts]
  accountDialogVisible.value = true
}

// 确认账号选择
const confirmAccountSelection = () => {
  if (currentTab.value) {
    currentTab.value.selectedAccounts = normalizeSelectedAccounts(tempSelectedAccounts.value)
  }
  accountDialogVisible.value = false
  currentTab.value = null
  ElMessage.success('账号选择完成')
}

// 删除选中的账号
const removeAccount = (tab, index) => {
  tab.selectedAccounts.splice(index, 1)
  tab.selectedAccounts = normalizeSelectedAccounts(tab.selectedAccounts)
  savePublishDraft()
}

// 获取账号显示名称
const getAccountDisplayName = (accountId) => {
  const account = accountStore.accounts.find(acc => acc.id === accountId)
  return account ? account.name : accountId
}

const processVersionLabel = (value) => {
  const labelMap = {
    translation_v1: '处理版本一',
    editing_v1: '处理版本二'
  }
  return labelMap[value] || value || '处理版本未知'
}

const formatFileSize = (size) => {
  const bytes = Number(size || 0)
  if (!bytes) return '-'
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

const formatMaterialSizeMb = (size) => {
  const mb = Number(size || 0)
  if (!mb) return ''
  return `${mb.toFixed(2)} MB`
}

const materialByVideoId = computed(() => {
  const map = new Map()
  publishableMaterials.value.forEach(material => {
    const videoId = material.source_video_id || material.metadata?.videoId
    if (!videoId) return
    const existing = map.get(videoId)
    if (!existing || Number(material.id || 0) > Number(existing.id || 0)) {
      map.set(videoId, material)
    }
  })
  return map
})

const publishedMaterialCount = computed(() => {
  return publishedVideos.value.filter(video => Boolean(video.processedFilePath)).length
})

const publishedPlatformStats = computed(() => {
  return publishedVideos.value.reduce((stats, video) => {
    if (video.publishToDouyin) stats.douyin += 1
    if (video.publishToBilibili) stats.bilibili += 1
    return stats
  }, { douyin: 0, bilibili: 0 })
})

const publishedPlatforms = (video) => {
  const tags = []
  if (video.publishToDouyin) tags.push(platformNameByKey[3])
  if (video.publishToBilibili) tags.push('B站')
  if (tags.length === 0) tags.push('发布中心')
  return tags
}

const loadPublishedVideos = async () => {
  publishedLoading.value = true
  try {
    const [videoResponse, materialResponse] = await Promise.all([
      youtubeApi.list(),
      materialApi.getAllMaterials()
    ])
    if (materialResponse?.code === 200) {
      appStore.setMaterials(materialResponse.data || [])
    }
    const sourceItems = videoResponse?.data?.items || []
    publishedVideos.value = sourceItems
      .filter(item => item.publishStatus === 1)
      .map(item => {
        const material = materialByVideoId.value.get(item.id)
        return {
          ...item,
          processVersionLabel: material ? processVersionLabel(material.processVersion) : processVersionLabel(item.processVersion),
          subtitleLanguageLabel: material?.subtitleLanguageLabel || item.subtitleLanguageLabel || '字幕语言未知',
          processedFilePath: material?.file_path || item.processedFilePath || '',
          processedPreviewUrl: material?.file_path ? materialApi.getMaterialPreviewUrl(material.file_path.split('/').pop()) : '',
          processedFileSizeLabel: material ? formatMaterialSizeMb(material.filesize) : '',
          publishedLabel: item.updatedAt ? `状态更新时间 ${item.updatedAt}` : '已提交发布'
        }
      })
  } catch (error) {
    console.error('加载已发布视频失败:', error)
    ElMessage.error('加载已发布视频失败')
  } finally {
    publishedLoading.value = false
  }
}

// 取消发布
const cancelPublish = (tab) => {
  ElMessage.info('已取消发布')
}

// 确认发布
const confirmPublish = async (tab) => {
  // 防止重复点击
  if (tab.publishing) {
    throw new Error('正在发布中，请稍候...')
  }

  tab.publishing = true // 设置发布状态为进行中

  // 数据验证
  if (tab.fileList.length === 0) {
    ElMessage.error('请先选择处理后视频')
    tab.publishing = false
    throw new Error('请先选择处理后视频')
  }
  const invalidFiles = tab.fileList.filter(file => file.sourceType !== 'youtube_processed')
  if (invalidFiles.length > 0) {
    ElMessage.error('发布中心只支持处理后视频，请重新选择素材')
    tab.publishing = false
    throw new Error('发布中心只支持处理后视频')
  }
  if (!tab.title.trim()) {
    ElMessage.error('发布标题为空，请回到视频采集处理页保存发布稿')
    tab.publishing = false
    throw new Error('发布标题为空')
  }
  if (!tab.selectedPlatform) {
    ElMessage.error('请选择发布平台')
    tab.publishing = false
    throw new Error('请选择发布平台')
  }
  if (tab.selectedAccounts.length === 0) {
    ElMessage.error('请选择发布账号')
    tab.publishing = false
    throw new Error('请选择发布账号')
  }
  const normalizedAccounts = normalizeSelectedAccounts(tab.selectedAccounts)
  if (normalizedAccounts.length === 0) {
    ElMessage.error('已选账号不存在或已被移除，请重新选择账号')
    tab.publishing = false
    throw new Error('已选账号不存在')
  }
  tab.selectedAccounts = normalizedAccounts

  // 构造发布数据，符合后端API格式
  const publishData = {
    type: tab.selectedPlatform,
    title: tab.title,
    description: tab.description,
    tags: tab.selectedTopics, // 不带#号的话题列表
    fileList: tab.fileList.map(file => file.path), // 只发送文件路径
    accountList: normalizedAccounts.map(accountId => {
      const account = accountStore.accounts.find(acc => acc.id === accountId)
      return account ? account.filePath : accountId
    }).filter(Boolean), // 发送当前保留账号的文件路径
    enableTimer: tab.scheduleEnabled ? 1 : 0,
    videosPerDay: tab.scheduleEnabled ? tab.videosPerDay || 1 : 1,
    dailyTimes: tab.scheduleEnabled ? tab.dailyTimes || ['10:00'] : ['10:00'],
    startDays: tab.scheduleEnabled ? tab.startDays || 0 : 0,
    category: tab.isOriginal ? 1 : 0, // 1表示原创，0表示非原创
    productLink: tab.productLink.trim() || '',
    productTitle: tab.productTitle.trim() || '',
    isDraft: tab.isDraft
  }

  // 调用后端发布API（使用统一的http封装）
  try {
    const data = await http.post('/postVideo', publishData)
    await loadPublishedVideos()
    tab.publishStatus = {
      message: '发布成功',
      type: 'success'
    }
    // 清空当前tab的数据
    tab.fileList = []
    tab.displayFileList = []
    tab.title = ''
    tab.description = ''
    tab.selectedTopics = []
    tab.contentLocked = false
    tab.selectedAccounts = []
    tab.scheduleEnabled = false
  } catch (error) {
    console.error('发布错误:', error)
    tab.publishStatus = {
      message: `发布失败：${error.message || '请检查网络连接'}`,
      type: 'error'
    }
    throw error
  } finally {
    tab.publishing = false
  }
}

// 选择素材库
const selectMaterialLibrary = async (tab) => {
  currentUploadTab.value = tab

  try {
    const response = await materialApi.getAllMaterials()
    if (response.code === 200) {
      appStore.setMaterials(response.data)
    } else {
      ElMessage.error('获取素材列表失败')
      return
    }
  } catch (error) {
    console.error('获取素材列表出错:', error)
    ElMessage.error('获取素材列表失败')
    return
  }
  
  selectedMaterials.value = []
  materialLibraryVisible.value = true
}

// 确认素材选择
const confirmMaterialSelection = () => {
  if (selectedMaterials.value.length === 0) {
    ElMessage.warning('请选择至少一个素材')
    return
  }
  
  if (currentUploadTab.value) {
    // 将选中的素材添加到当前tab的文件列表
    const selectedPublishDrafts = []
    selectedMaterials.value.forEach(materialId => {
      const material = publishableMaterials.value.find(m => m.id === materialId)
      if (material) {
        selectedPublishDrafts.push(normalizePublishDraft(material))
        const fileInfo = {
          name: material.displayTitle || material.filename,
          displayTitle: material.displayTitle || material.filename,
          channel: material.displayChannel || '',
          processType: material.processType || '处理后视频',
          processVersion: material.processVersion || '',
          processVersionLabel: processVersionLabel(material.processVersion),
          subtitleLanguage: material.subtitleLanguage || '',
          subtitleLanguageLabel: material.subtitleLanguageLabel || '',
          sourceType: material.source_type,
          analysisResult: material.analysisResult || {},
          publishDraft: material.publishDraft || {},
          videoId: material.source_video_id || material.metadata?.videoId || '',
          materialId: material.id,
          url: materialApi.getMaterialPreviewUrl(material.file_path.split('/').pop()),
          path: material.file_path,
          size: material.filesize * 1024 * 1024, // 转换为字节
          type: 'video/mp4'
        }
        
        // 检查是否已存在相同文件
        const exists = currentUploadTab.value.fileList.some(file => file.path === fileInfo.path)
        if (!exists) {
          currentUploadTab.value.fileList.push(fileInfo)
        }
      }
    })

    applyPublishDraftToPublishTab(currentUploadTab.value, selectedPublishDrafts)
    
    // 更新显示列表
    currentUploadTab.value.displayFileList = [...currentUploadTab.value.fileList.map(item => ({
      name: item.name,
      url: item.url
    }))]
  }
  
  const addedCount = selectedMaterials.value.length
  materialLibraryVisible.value = false
  selectedMaterials.value = []
  currentUploadTab.value = null
  ElMessage.success(`已添加 ${addedCount} 个处理后视频`)
}

// 批量发布对话框状态
const batchPublishDialogVisible = ref(false)
const currentPublishingTab = ref(null)
const publishProgress = ref(0)
const publishResults = ref([])
const isCancelled = ref(false)

// 取消批量发布
const cancelBatchPublish = () => {
  isCancelled.value = true
  ElMessage.info('正在取消发布...')
}

// 批量发布方法
const batchPublish = async () => {
  if (batchPublishing.value) return
  
  batchPublishing.value = true
  currentPublishingTab.value = null
  publishProgress.value = 0
  publishResults.value = []
  isCancelled.value = false
  batchPublishDialogVisible.value = true
  
  try {
    for (let i = 0; i < tabs.length; i++) {
      if (isCancelled.value) {
        publishResults.value.push({
          label: tabs[i].label,
          status: 'cancelled',
          message: '已取消'
        })
        continue
      }

      const tab = tabs[i]
      currentPublishingTab.value = tab
      publishProgress.value = Math.floor((i / tabs.length) * 100)
      
      try {
        await confirmPublish(tab)
        publishResults.value.push({
          label: tab.label,
          status: 'success',
          message: '发布成功'
        })
      } catch (error) {
        publishResults.value.push({
          label: tab.label,
          status: 'error',
          message: error.message
        })
        // 不立即返回，继续显示发布结果
      }
    }
    
    publishProgress.value = 100
    
    // 统计发布结果
    const successCount = publishResults.value.filter(r => r.status === 'success').length
    const failCount = publishResults.value.filter(r => r.status === 'error').length
    const cancelCount = publishResults.value.filter(r => r.status === 'cancelled').length
    
    if (isCancelled.value) {
      ElMessage.warning(`发布已取消：${successCount}个成功，${failCount}个失败，${cancelCount}个未执行`)
    } else if (failCount > 0) {
      ElMessage.error(`发布完成：${successCount}个成功，${failCount}个失败`)
    } else {
      ElMessage.success('所有Tab发布成功')
      setTimeout(() => {
        batchPublishDialogVisible.value = false
      }, 1000)
    }
    
  } catch (error) {
    console.error('批量发布出错:', error)
    ElMessage.error('批量发布出错，请重试')
  } finally {
    batchPublishing.value = false
    isCancelled.value = false
  }
}

onMounted(() => {
  loadPublishedVideos()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

$panel-border: #dce6f2;
$panel-shadow: 0 12px 28px rgba(28, 55, 90, 0.08);
$accent-blue: #2563eb;
$ink-strong: #172033;

.publish-center {
  display: grid;
  gap: 16px;
}

.page-hero,
.batch-panel,
.compose-panel {
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: #fff;
  box-shadow: $panel-shadow;
}

.page-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.1), rgba(15, 159, 143, 0.08) 42%, rgba(255, 255, 255, 0.94)), #fff;

  h1 { margin: 4px 0 8px; color: $ink-strong; font-size: 25px; line-height: 1.25; font-weight: 700; }
  p { margin: 0; color: #5b667a; font-size: 14px; line-height: 1.7; }
}

.eyebrow,
.panel-kicker { color: $accent-blue; font-size: 12px; font-weight: 700; letter-spacing: 0; }

.hero-actions { display: flex; gap: 10px; flex-wrap: wrap; }

.publish-workbench { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 16px; align-items: start; }

.published-panel {
  display: grid;
  gap: 14px;
  padding: 16px;
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: #fff;
  box-shadow: $panel-shadow;
}

.panel-heading-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  h2 { margin: 2px 0 6px; color: $ink-strong; font-size: 18px; }
  p { margin: 0; color: $text-secondary; font-size: 13px; line-height: 1.6; }
}

.published-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.summary-tile {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: #f8fbff;

  span { color: $text-secondary; font-size: 12px; }
  strong { color: $ink-strong; font-size: 22px; line-height: 1.1; }
}

.published-list {
  display: grid;
  gap: 10px;
}

.published-card {
  display: grid;
  grid-template-columns: 138px minmax(0, 1fr);
  gap: 12px;
  padding: 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: #fff;
}

.published-cover {
  display: grid;
  place-items: center;
  aspect-ratio: 16 / 9;
  min-height: 78px;
  overflow: hidden;
  border-radius: 8px;
  background: #eef4fb;
  color: $accent-blue;
  font-size: 12px;
  font-weight: 700;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
}

.published-body {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.published-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;

  h3 {
    margin: 0;
    color: $ink-strong;
    font-size: 15px;
    line-height: 1.45;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
}

.published-meta,
.published-tags,
.published-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: $text-secondary;
  font-size: 12px;
}

.published-actions {
  justify-content: space-between;
}

.batch-panel { padding: 14px; position: sticky; top: 12px; }
.panel-title h2 { margin: 2px 0 12px; color: $ink-strong; font-size: 18px; }
.batch-list { display: grid; gap: 8px; }
.batch-item { position: relative; display: grid; gap: 4px; width: 100%; padding: 12px 34px 12px 12px; border: 1px solid $border-lighter; border-radius: 8px; background: #f8fbff; text-align: left; cursor: pointer; }
.batch-item.active { border-color: rgba(37, 99, 235, 0.42); background: rgba(37, 99, 235, 0.08); }
.batch-item span { color: $ink-strong; font-weight: 650; }
.batch-item small { color: $text-secondary; }
.close-icon { position: absolute; right: 10px; top: 12px; }

.compose-panel { padding: 16px; }
.compose-content { display: grid; gap: 14px; }
.form-section { display: grid; gap: 12px; padding: 14px; border: 1px solid $border-lighter; border-radius: 8px; background: #fff; }
.split-section { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.sub-panel { display: grid; gap: 12px; min-width: 0; }
.section-heading { display: flex; align-items: center; gap: 10px; justify-content: space-between; }
.section-heading.compact { justify-content: flex-start; }
.section-heading h3 { margin: 0; color: $ink-strong; font-size: 16px; }
.section-heading p { margin: 3px 0 0; color: $text-secondary; font-size: 12px; }
.step-index { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; color: $accent-blue; background: rgba(37, 99, 235, 0.1); font-weight: 700; flex: 0 0 auto; }

.file-list,
.material-list,
.account-list { display: grid; gap: 8px; max-height: 360px; overflow: auto; }
.file-item,
.material-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid $border-lighter; border-radius: 8px; background: #f8fbff; }
.selected-video-main { display: grid; gap: 5px; min-width: 0; margin-right: auto; }
.selected-video-main .el-link { justify-content: flex-start; max-width: 640px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-video-meta,
.material-details,
.material-badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: $text-secondary; font-size: 12px; }

.material-publish-draft,
.material-topic-list {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  color: #435168;
  font-size: 12px;
}

.material-publish-draft strong {
  min-width: 0;
  color: $ink-strong;
  font-size: 13px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.draft-label {
  flex: 0 0 auto;
  color: $accent-blue;
  font-weight: 650;
}

.material-topic-list {
  flex-wrap: wrap;
}

.empty-topic {
  color: $text-secondary;
}

.tag-cloud { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-height: 32px; }
.topic-cloud { margin-top: 4px; }
.platform-radios { display: flex; flex-wrap: wrap; gap: 8px; }
.two-col { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.inline-options { display: flex; gap: 16px; flex-wrap: wrap; }
.schedule-controls { display: grid; gap: 12px; }
.schedule-settings { display: grid; gap: 12px; padding: 12px; border-radius: 8px; background: #f8fbff; }
.schedule-item { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: center; }
.schedule-item > span { color: $text-secondary; font-size: 13px; }
.time-list { display: flex; gap: 8px; flex-wrap: wrap; }
.submit-bar { display: flex; justify-content: flex-end; gap: 10px; padding-top: 2px; }
.option-grid { display: grid; gap: 12px; }
.option-btn { width: 100%; height: 46px; }
.custom-topic-input { display: flex; gap: 10px; margin-bottom: 18px; }
.topic-grid { display: flex; flex-wrap: wrap; gap: 10px; }
:global(.material-library-dialog) {
  width: min(960px, calc(100vw - 32px));
  max-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
}
:global(.material-library-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.material-library-dialog :deep(.el-alert) { margin-bottom: 12px; }
.publishable-list {
  max-height: min(62vh, 620px);
  padding-right: 4px;
}
.publishable-item { align-items: flex-start; min-height: 92px; }
.publishable-item :deep(.el-checkbox) { width: 100%; align-items: flex-start; height: auto; }
.publishable-item :deep(.el-checkbox__input) { margin-top: 3px; }
.publishable-item :deep(.el-checkbox__label) {
  min-width: 0;
  flex: 1;
  line-height: 1.45;
  white-space: normal;
}
.material-info { display: grid; gap: 7px; min-width: 0; width: 100%; }
.material-name {
  color: $ink-strong;
  font-weight: 650;
  line-height: 1.45;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.publish-progress { display: grid; gap: 14px; padding: 12px; }
.result-item { display: flex; gap: 10px; padding: 8px 0; color: $text-secondary; }
.result-item.success { color: $success-color; }
.result-item.error { color: $danger-color; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 10px; }
.video-upload { width: 100%; }
.video-upload :deep(.el-upload-dragger) { width: 100%; }

@media (max-width: 1100px) {
  .publish-workbench { grid-template-columns: 1fr; }
  .published-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .batch-panel { position: static; }
  .split-section { grid-template-columns: 1fr; }
}

@media (max-width: 760px) {
  .page-hero { align-items: flex-start; flex-direction: column; }
  .panel-heading-row { align-items: flex-start; flex-direction: column; }
  .published-summary,
  .published-card { grid-template-columns: 1fr; }
  .section-heading { align-items: flex-start; flex-direction: column; }
  .two-col,
  .schedule-item { grid-template-columns: 1fr; }
}
</style>
