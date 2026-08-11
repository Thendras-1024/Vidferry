<template>
  <div class="material-management">
    <section class="page-header">
      <div>
        <span class="eyebrow">VIDEO MATERIAL LIBRARY</span>
        <h1>视频素材</h1>
        <p>统一查看下载原视频、处理后视频和补充素材。</p>
      </div>
      <div class="summary-strip">
        <div class="summary-item">
          <span>处理后视频</span>
          <strong>{{ processedTotal }}</strong>
        </div>
        <div class="summary-item">
          <span>下载原视频</span>
          <strong>{{ downloadedTotal }}</strong>
        </div>
        <div class="summary-item">
          <span>补充视频素材</span>
          <strong>{{ otherTotal }}</strong>
        </div>
      </div>
    </section>

    <section class="toolbar-card">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索标题、博主、链接、文件名"
        prefix-icon="Search"
        clearable
        @clear="handleSearch"
        @input="handleSearch"
      />
      <VideoGroupSelect v-model="materialGroupId" include-all class="material-group-filter" />
      <div class="action-buttons">
        <el-button type="primary" @click="handleUploadMaterial">上传视频素材</el-button>
        <el-button
          type="danger"
          plain
          :disabled="selectedMaterials.length === 0"
          @click="handleBatchDelete"
        >
          批量删除 {{ selectedMaterials.length || '' }}
        </el-button>
        <el-button type="info" @click="refreshAllMaterials" :loading="isRefreshing">
          <el-icon :class="{ 'is-loading': isRefreshing }"><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </div>
    </section>

    <section class="material-section primary-section">
      <div class="section-header">
        <div>
          <span class="section-kicker">已完成处理</span>
          <h2>处理后视频</h2>
        </div>
        <span class="section-count">第 {{ processedPagination.page }} 页 · {{ processedMaterials.length }} / {{ processedTotal }} 条</span>
      </div>

      <el-table
        v-if="processedMaterials.length > 0"
        :data="processedMaterials"
        class="material-table"
        style="width: 100%"
        @selection-change="handleProcessedSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="视频信息" min-width="420">
          <template #default="{ row }">
            <MaterialIdentity :material="row" />
          </template>
        </el-table-column>
        <el-table-column label="烧录预设" width="130">
          <template #default="{ row }">
            <el-tag :type="burnProfileTagType(row)" effect="light">{{ burnProfileLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="处理版本" width="130">
          <template #default="{ row }">
            <el-tag effect="plain">{{ processVersionLabel(row.processVersion || row.metadata?.processVersion) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="字幕语言" width="120">
          <template #default="{ row }">
            <el-tag type="success" effect="plain">{{ materialSubtitleLanguageLabel(row) || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="内容风险" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.analysisResult?.contentRisk?.requiresPublishConfirmation" type="warning" effect="light">发布需确认</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="时长" width="100">
          <template #default="{ row }">{{ materialDuration(row) }}</template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ row.filesize }} MB</template>
        </el-table-column>
        <el-table-column label="入库时间" width="170">
          <template #default="{ row }">{{ formatMaterialTime(row.upload_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button size="small" @click="handlePreview(row)">预览</el-button>
              <el-button size="small" type="primary" plain @click="handleEditPublishDraft(row)">文案</el-button>
              <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无处理后视频" />
      <div class="table-pagination" v-if="processedTotal > processedPagination.pageSize">
        <el-pagination
          v-model:current-page="processedPagination.page"
          :page-size="processedPagination.pageSize"
          :total="processedTotal"
          layout="total, prev, pager, next, jumper"
          background
        />
      </div>
    </section>

    <section class="material-section">
      <div class="section-header">
        <div>
          <span class="section-kicker">原始视频</span>
          <h2>下载原视频</h2>
        </div>
        <div class="section-header-actions">
          <span class="section-count">第 {{ downloadedPagination.page }} 页 · {{ downloadedMaterials.length }} / {{ downloadedTotal }} 条</span>
          <el-button
            size="small"
            type="danger"
            plain
            :disabled="selectedDownloadedMaterials.length === 0"
            @click="handleBatchDelete('downloaded')"
          >
            批量删除 {{ selectedDownloadedMaterials.length || '' }}
          </el-button>
        </div>
      </div>

      <el-table
        v-if="downloadedMaterials.length > 0"
        :data="downloadedMaterials"
        class="material-table"
        style="width: 100%"
        @selection-change="handleDownloadedSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="视频信息" min-width="420">
          <template #default="{ row }">
            <MaterialIdentity :material="row" />
          </template>
        </el-table-column>
        <el-table-column label="视频类型" width="130">
          <template #default>
            <el-tag type="info" effect="light">原视频下载</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时长" width="100">
          <template #default="{ row }">{{ materialDuration(row) }}</template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ row.filesize }} MB</template>
        </el-table-column>
        <el-table-column label="入库时间" width="170">
          <template #default="{ row }">{{ formatMaterialTime(row.upload_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button size="small" @click="handlePreview(row)">预览</el-button>
              <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无下载原视频" />
      <div class="table-pagination" v-if="downloadedTotal > downloadedPagination.pageSize">
        <el-pagination
          v-model:current-page="downloadedPagination.page"
          :page-size="downloadedPagination.pageSize"
          :total="downloadedTotal"
          layout="total, prev, pager, next, jumper"
          background
        />
      </div>
    </section>

    <section v-if="otherMaterials.length > 0" class="material-section">
      <div class="section-header">
        <div>
          <span class="section-kicker">补充视频素材</span>
          <h2>其他视频素材</h2>
        </div>
        <span class="section-count">{{ otherTotal }} 条</span>
      </div>

      <el-table :data="otherMaterials" class="material-table" style="width: 100%">
        <el-table-column label="视频素材信息" min-width="420">
          <template #default="{ row }">
            <MaterialIdentity :material="row" />
          </template>
        </el-table-column>
        <el-table-column label="时长" width="100">
          <template #default="{ row }">{{ materialDuration(row) }}</template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ row.filesize }} MB</template>
        </el-table-column>
        <el-table-column label="入库时间" width="170">
          <template #default="{ row }">{{ formatMaterialTime(row.upload_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button size="small" @click="handlePreview(row)">预览</el-button>
              <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="uploadDialogVisible"
      title="上传视频素材"
      width="40%"
      @close="handleUploadDialogClose"
    >
      <div class="upload-form">
        <el-form label-width="80px">
          <el-form-item label="文件名称:">
            <el-input
              v-model="customFilename"
              placeholder="选填 (仅单个文件时生效)"
              :disabled="customFilenameDisabled"
              clearable
            />
          </el-form-item>
          <el-form-item label="选择文件">
            <el-upload
              class="upload-demo"
              drag
              multiple
              :auto-upload="false"
              :on-change="handleFileChange"
              :on-remove="handleFileRemove"
              :file-list="fileList"
            >
              <el-icon class="el-icon--upload"><Upload /></el-icon>
              <div class="el-upload__text">
                将文件拖到此处，或<em>点击上传</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">支持视频、图片等格式文件，可一次选择多个文件</div>
              </template>
            </el-upload>
          </el-form-item>
          <el-form-item label="上传列表" v-if="fileList.length > 0">
            <div class="upload-file-list">
              <div v-for="file in fileList" :key="file.uid" class="upload-file-item">
                <span class="file-name">{{ file.name }}</span>
                <el-progress
                  :percentage="uploadProgress[file.uid]?.percentage || 0"
                  :text-inside="true"
                  :stroke-width="20"
                  style="width: 100%; margin-top: 5px;"
                >
                  <span>{{ uploadProgress[file.uid]?.speed || '' }}</span>
                </el-progress>
              </div>
            </div>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="uploadDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="submitUpload" :loading="isUploading">
            {{ isUploading ? '上传中' : '确认上传' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="previewDialogVisible"
      :title="currentMaterial ? materialTitle(currentMaterial) : '视频素材预览'"
      width="56%"
      :top="'8vh'"
      @close="handlePreviewDialogClose"
      @closed="resetPreviewDialog"
    >
      <div class="preview-container" v-if="currentMaterial">
        <video
          v-if="isVideoFile(currentMaterial.filename)"
          ref="previewVideoRef"
          controls
          class="preview-video"
        >
          <source :src="getPreviewUrl(currentMaterial.file_path)" type="video/mp4">
          您的浏览器不支持视频播放
        </video>
        <img
          v-else-if="isImageFile(currentMaterial.filename)"
          :src="getPreviewUrl(currentMaterial.file_path)"
          class="preview-image"
          alt=""
        >
        <div v-else class="file-info">
          <p>标题: {{ materialTitle(currentMaterial) }}</p>
          <p>视频时长: {{ materialDuration(currentMaterial) }}</p>
          <p>文件大小: {{ currentMaterial.filesize }} MB</p>
          <p>入库时间: {{ formatMaterialTime(currentMaterial.upload_time) }}</p>
          <el-button type="primary" @click="downloadFile(currentMaterial)">下载文件</el-button>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="publishDraftDialogVisible" title="编辑发布稿" width="min(760px, calc(100vw - 32px))">
      <el-form label-position="top" class="publish-draft-form">
        <el-form-item label="发布标题">
          <el-input v-model="publishDraftForm.title" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="发布文案">
          <el-input v-model="publishDraftForm.description" type="textarea" :rows="6" maxlength="800" show-word-limit />
        </el-form-item>
        <el-form-item label="话题">
          <el-select v-model="publishDraftForm.tags" multiple filterable allow-create default-first-option placeholder="输入后回车添加话题">
            <el-option v-for="tag in publishDraftForm.tags" :key="tag" :label="tag" :value="tag" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="publishDraftDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingPublishDraft" @click="savePublishDraft">保存</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { InfoFilled, Refresh, Upload, VideoCamera } from '@element-plus/icons-vue'
import { ElButton, ElIcon, ElMessage, ElMessageBox, ElPopover, ElTag } from 'element-plus'
import { materialApi } from '@/api/material'
import { youtubeApi } from '@/api/youtube'
import { useAppStore } from '@/stores/app'
import VideoGroupSelect from '@/components/VideoGroupSelect.vue'

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

const appStore = useAppStore()

const searchKeyword = ref('')
const materialGroupId = ref('')
const isRefreshing = ref(false)
const isPageLoading = ref(false)
const isUploading = ref(false)
const uploadDialogVisible = ref(false)
const previewDialogVisible = ref(false)
const currentMaterial = ref(null)
const previewVideoRef = ref(null)
const fileList = ref([])
const customFilename = ref('')
const customFilenameDisabled = computed(() => fileList.value.length > 1)
const uploadProgress = ref({})
const selectedProcessedMaterials = ref([])
const selectedDownloadedMaterials = ref([])
const selectedMaterials = computed(() => [...selectedProcessedMaterials.value, ...selectedDownloadedMaterials.value])
const publishDraftDialogVisible = ref(false)
const savingPublishDraft = ref(false)
const currentDraftMaterial = ref(null)
const publishDraftForm = ref({
  title: '',
  description: '',
  tags: []
})
const processedMaterials = ref([])
const downloadedMaterials = ref([])
const otherMaterials = ref([])
const processedTotal = ref(0)
const downloadedTotal = ref(0)
const otherTotal = ref(0)
const processedPagination = reactive({ page: 1, pageSize: 10 })
const downloadedPagination = reactive({ page: 1, pageSize: 10 })
let searchTimer = null
let materialPageWatchPaused = false

const materialTitle = (material) => {
  return material?.displayTitle || material?.metadata?.title || material?.original_filename || material?.filename || '未命名视频素材'
}

const materialUrl = (material) => {
  return material?.displayUrl || material?.metadata?.url || ''
}

const materialChannel = (material) => {
  return material?.displayChannel || material?.metadata?.channel || ''
}

const materialSubscribers = (material) => {
  return material?.displaySubscribers || material?.metadata?.subscribers || ''
}

const materialPublishedAt = (material) => {
  return material?.displayPublishedAt || material?.metadata?.publishedAt || ''
}

const languageLabel = (language) => {
  return languageMap[language] || language || '-'
}

const inferSubtitleLanguage = (material) => {
  const explicitLanguage = material?.subtitleLanguage || material?.metadata?.subtitleLanguage
  if (explicitLanguage) return explicitLanguage
  if (material?.source_type !== 'youtube_processed') return ''

  const filename = material?.filename || material?.original_filename || ''
  const match = filename.match(/_([a-z]{2}(?:-[A-Z]{2})?)\.[^.]+$/)
  const suffixMap = {
    zh: 'zh-CN',
    en: 'en',
    ja: 'ja',
    ko: 'ko',
    es: 'es',
    fr: 'fr',
    de: 'de',
    ru: 'ru'
  }
  return match ? (suffixMap[match[1]] || match[1]) : ''
}

const materialSubtitleLanguageLabel = (material) => {
  return material?.subtitleLanguageLabel || material?.metadata?.subtitleLanguageLabel || languageLabel(inferSubtitleLanguage(material))
}

const materialBurnProfile = (material) => {
  return String(
    material?.burnProfile ||
    material?.metadata?.burnProfile ||
    material?.workflowBurnProfile ||
    ''
  ).toLowerCase()
}

const BURN_PROFILE_LABELS = {
  stable: '标准 1080p（推荐）',
  fast: '快速 1080p',
  '2k': '2K 高画质（需 2K 原片）'
}

const burnProfileLabel = (material) => {
  return BURN_PROFILE_LABELS[materialBurnProfile(material)] || BURN_PROFILE_LABELS.stable
}

const burnProfileTagType = (material) => {
  return materialBurnProfile(material) === 'fast' ? 'warning' : 'success'
}

const materialVideoId = (material) => {
  return material?.metadata?.videoId || material?.source_video_id || ''
}

const materialThumbnail = (material) => {
  if (material?.localThumbnailPath) {
    return materialApi.getMaterialPreviewUrl(material.localThumbnailPath)
  }
  const videoId = materialVideoId(material)
  if (videoId) return `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`
  if (material?.displayThumbnail) return material.displayThumbnail
  if (material?.metadata?.thumbnail) return material.metadata.thumbnail
  return ''
}

const materialDuration = (material) => {
  return material?.duration || material?.metadata?.duration || '-'
}

const formatMaterialTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric', month: 'long', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

const cleanTopicList = (topics = []) => {
  const values = Array.isArray(topics) ? topics : String(topics || '').split(/[，,\s]+/)
  return Array.from(new Set(values.map(tag => String(tag || '').trim().replace(/^#+/, '')).filter(Boolean)))
}

const buildPublishDraftFromMaterial = (material) => {
  const savedDraft = material?.publishDraft || {}
  const result = material?.analysisResult || {}
  const titleOptions = Array.isArray(result.title_options) ? result.title_options.filter(Boolean) : []
  return {
    title: savedDraft.title || titleOptions[0] || '',
    description: savedDraft.description || result.publish_copy || '',
    tags: cleanTopicList(savedDraft.tags?.length ? savedDraft.tags : result.tags)
  }
}

const materialVideoIdForDraft = (material) => {
  return material?.source_video_id || material?.metadata?.videoId || ''
}

const workflowStatusText = (status) => {
  const map = {
    queued: '排队中',
    running: '处理中',
    success: '处理成功',
    failed: '处理失败',
    abnormal: '任务异常'
  }
  return map[status] || status || ''
}

const materialWorkflowBadge = (material) => {
  const status = material?.workflowStatus
  if (!status) return null

  const sameVersion = Boolean(material?.workflowSameProcessVersion)
  const versionLabel = processVersionLabel(material?.workflowProcessVersion || material?.processVersion)
  const message = material?.workflowMessage || ''

  if (status === 'queued' || status === 'running') {
    return {
      type: sameVersion ? 'primary' : 'info',
      effect: sameVersion ? 'dark' : 'light',
      text: sameVersion ? '重新处理中' : `${versionLabel}处理中`,
      detail: message || workflowStatusText(status)
    }
  }

  if (status === 'failed' || status === 'abnormal') {
    return {
      type: 'danger',
      effect: 'light',
      text: sameVersion ? '重新处理失败' : `${versionLabel}失败`,
      detail: message || workflowStatusText(status)
    }
  }

  return null
}

const processVersionLabel = (value) => {
  const labelMap = {
    translation_v1: '处理版本一',
    editing_v1: '处理版本二'
  }
  return labelMap[value] || value || '版本未知'
}

const processingSettingsRows = (material) => {
  const settings = material?.processingSettings
  if (!settings || typeof settings !== 'object' || Object.keys(settings).length === 0) {
    return [['处理设置', '历史素材未记录完整任务设置']]
  }
  const enabled = value => value ? '开启' : '关闭'
  const commentMode = settings.commentTranslationMode === 'google' ? 'Google 翻译' : 'Google 翻译 + LLM 修订'
  const analysis = settings.sourceSubtitleAnalysis || {}
  const subtitleMode = { auto: '自动适配', force_burn: '强制烧制', original: '原字幕', legacy: '历史模式' }[settings.subtitleMode] || '历史模式'
  const sourceSubtitle = analysis.status === 'unknown' ? '识别失败' : ({ zh: '中文', non_zh: '非中文', none: '无', unknown: '未识别' }[analysis.classification] || '未识别')
  const finalAction = { original: '原字幕', original_zh: '原字幕', burn: '烧制', mask_and_burn: '遮挡后烧制' }[analysis.decision?.effectiveAction] || (settings.subtitleMaskEnabled ? '遮挡后烧制' : (settings.translationEnabled ? '烧制' : '原字幕'))
  const region = analysis.region
  const regionText = region ? `${Math.round(region.x * 100)}%, ${Math.round(region.y * 100)}%, ${Math.round(region.width * 100)}% × ${Math.round(region.height * 100)}%` : '-'
  return [
    ['处理版本', processVersionLabel(settings.processVersion)],
    ['字幕语言', languageLabel(settings.subtitleLanguage)],
    ['烧录预设', BURN_PROFILE_LABELS[settings.burnProfile] || BURN_PROFILE_LABELS.stable],
    ['字幕字号', settings.subtitleSize || '-'],
    ['字幕翻译', enabled(settings.translationEnabled)],
    ['字幕模式', subtitleMode],
    ['原字幕', sourceSubtitle],
    ['最终处理', finalAction],
    ['遮挡区域', regionText],
    ['翻译署名', settings.translatorLabel || '-'],
    ['水印', settings.watermarkEnabled ? settings.watermarkText || '已开启' : '关闭'],
    ['高光片头', settings.highlightIntroEnabled ? `${settings.highlightCount || 0} 条` : '关闭'],
    ['封面片头', settings.coverIntroEnabled ? settings.coverTitle || '开启' : '关闭'],
    ['评论烧制', settings.commentBurnEnabled ? `${settings.commentBurnCount || 0} 条，${commentMode}` : '关闭'],
    ['字幕遮挡', enabled(settings.subtitleMaskEnabled)],
    ['内容安全审查', enabled(settings.contentSafetyReviewEnabled)]
  ]
}

const MaterialIdentity = defineComponent({
  name: 'MaterialIdentity',
  props: {
    material: {
      type: Object,
      required: true
    }
  },
  setup(props) {
    const thumbFailed = ref(false)
    const workflowBadge = computed(() => materialWorkflowBadge(props.material))
    const infoRows = computed(() => [
      ['视频名称', materialTitle(props.material)],
      ['UUID', props.material.uuid],
      ['存储路径', props.material.file_path],
      ['来源类型', props.material.source_type],
      ['状态', props.material.status],
      ['任务状态', workflowBadge.value ? `${workflowBadge.value.text} ${workflowBadge.value.detail}` : ''],
      ...processingSettingsRows(props.material)
    ].filter(([, value]) => value !== undefined && value !== null && value !== ''))
    const previewSource = computed(() => {
      if (thumbFailed.value) return ''
      if (props.material.source_type === 'youtube_processed' || props.material.source_type === 'youtube_download') {
        return materialThumbnail(props.material)
      }
      return materialThumbnail(props.material) || materialApi.getMaterialPreviewUrl(props.material.file_path)
    })

    return () => h('div', { class: 'material-identity' }, [
      previewSource.value
        ? h('img', {
          class: 'material-thumb',
          src: previewSource.value,
          alt: '',
          onError: () => { thumbFailed.value = true }
        })
        : h('div', { class: 'material-thumb material-thumb-empty' }, [
          h(ElIcon, null, { default: () => h(VideoCamera) })
        ]),
      h('div', { class: 'identity-body' }, [
        h('div', { class: 'identity-title-line' }, [
          props.material.displayUrl
            ? h('a', {
              class: 'identity-title',
              href: props.material.displayUrl,
              target: '_blank',
              rel: 'noopener noreferrer'
            }, materialTitle(props.material))
            : h('span', { class: 'identity-title' }, materialTitle(props.material)),
          h(ElPopover, {
            placement: 'right',
            width: 420,
            trigger: 'click',
            popperClass: 'material-identity-popover'
          }, {
            reference: () => h(ElButton, {
              class: 'info-button',
              text: true,
              circle: true,
              'aria-label': '查看素材与处理设置'
            }, { default: () => h(ElIcon, null, { default: () => h(InfoFilled) }) }),
            default: () => h('div', { class: 'technical-popover' }, [
              h('strong', '素材与处理设置'),
              h('dl', { class: 'technical-list' }, infoRows.value.flatMap(([label, value]) => [
                h('dt', label),
                h('dd', { title: String(value) }, String(value))
              ]))
            ])
          }),
          workflowBadge.value
            ? h(ElTag, {
              class: 'workflow-badge',
              type: workflowBadge.value.type,
              effect: workflowBadge.value.effect,
              size: 'small',
              title: workflowBadge.value.detail
            }, { default: () => workflowBadge.value.text })
            : null,
          props.material.sourceMissing
            ? h(ElTag, { type: 'warning', effect: 'plain', size: 'small' }, { default: () => '来源线索缺失' })
            : (props.material.groupName
                ? h(ElTag, { type: 'info', effect: 'plain', size: 'small' }, { default: () => props.material.groupName })
                : null)
        ]),
        h('div', { class: 'identity-meta' }, [
          h('span', materialChannel(props.material) || '未知博主'),
          h('span', materialSubscribers(props.material) || '粉丝数未知'),
          h('span', materialPublishedAt(props.material) || '发布时间未知')
        ]),
        props.material.displayUrl
          ? h('span', { class: 'identity-url' }, props.material.displayUrl)
          : null
      ])
    ])
  }
})

watch(fileList, (newList) => {
  if (newList.length <= 1) {
    return
  }
  customFilename.value = ''
})

const materialCacheKey = (sourceType, pagination) => `materials:${sourceType}:${materialGroupId.value || 'all'}:${searchKeyword.value.trim()}:${pagination.page}:${pagination.pageSize}`

const applyMaterialPage = (sourceType, payload = {}) => {
  const list = payload.items || []
  if (sourceType === 'youtube_processed') {
    processedMaterials.value = list
    processedTotal.value = Number(payload.total || 0)
    processedPagination.page = Number(payload.page || processedPagination.page)
    processedPagination.pageSize = Number(payload.pageSize || processedPagination.pageSize)
  } else if (sourceType === 'youtube_download') {
    downloadedMaterials.value = list
    downloadedTotal.value = Number(payload.total || 0)
    downloadedPagination.page = Number(payload.page || downloadedPagination.page)
    downloadedPagination.pageSize = Number(payload.pageSize || downloadedPagination.pageSize)
  } else {
    otherMaterials.value = list
    otherTotal.value = Number(payload.total || 0)
  }
}

const loadMaterialPage = async (sourceType, pagination, { force = false } = {}) => {
  const params = {
    sourceType,
    page: pagination.page,
    pageSize: pagination.pageSize,
    keyword: searchKeyword.value.trim()
  }
  if (sourceType !== 'other' && materialGroupId.value) params.groupId = materialGroupId.value
  const cacheKey = materialCacheKey(sourceType, pagination)
  if (!force) {
    const cached = appStore.getListCache(cacheKey)
    if (cached) {
      applyMaterialPage(sourceType, cached)
    }
  }
  const response = await materialApi.getAllMaterials(params)
  const payload = response.data || {}
  applyMaterialPage(sourceType, payload)
  appStore.setListCache(cacheKey, payload)
}

const syncMaterialStoreSnapshot = () => {
  appStore.setMaterials([
    ...processedMaterials.value,
    ...downloadedMaterials.value,
    ...otherMaterials.value
  ])
}

const fetchMaterials = async ({ force = false, successMessage = false, manual = false } = {}) => {
  if (manual) {
    isRefreshing.value = true
  } else {
    isPageLoading.value = true
  }
  try {
    await Promise.all([
      loadMaterialPage('youtube_processed', processedPagination, { force }),
      loadMaterialPage('youtube_download', downloadedPagination, { force }),
      loadMaterialPage('other', { page: 1, pageSize: 10 }, { force })
    ])
    syncMaterialStoreSnapshot()
    if (successMessage) ElMessage.success('刷新成功')
  } catch (error) {
    console.error('获取素材列表出错:', error)
    ElMessage.error('获取视频素材列表失败')
  } finally {
    if (manual) {
      isRefreshing.value = false
    } else {
      isPageLoading.value = false
    }
  }
}

const refreshAllMaterials = () => {
  fetchMaterials({ force: true, successMessage: true, manual: true })
}

const refreshMaterialSection = async (sourceType, pagination, { force = false } = {}) => {
  isPageLoading.value = true
  try {
    await loadMaterialPage(sourceType, pagination, { force })
    syncMaterialStoreSnapshot()
  } catch (error) {
    console.error('获取素材列表出错:', error)
    ElMessage.error('获取视频素材列表失败')
  } finally {
    isPageLoading.value = false
  }
}

const handleSearch = () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(async () => {
    materialPageWatchPaused = true
    processedPagination.page = 1
    downloadedPagination.page = 1
    try {
      await fetchMaterials({ force: true })
    } finally {
      materialPageWatchPaused = false
    }
  }, 300)
}

watch(
  () => processedPagination.page,
  () => {
    if (!materialPageWatchPaused) {
      refreshMaterialSection('youtube_processed', processedPagination)
    }
  }
)

watch(materialGroupId, async () => {
  materialPageWatchPaused = true
  processedPagination.page = 1
  downloadedPagination.page = 1
  selectedProcessedMaterials.value = []
  selectedDownloadedMaterials.value = []
  try {
    await fetchMaterials({ force: true })
  } finally {
    materialPageWatchPaused = false
  }
})

watch(
  () => downloadedPagination.page,
  () => {
    if (!materialPageWatchPaused) {
      refreshMaterialSection('youtube_download', downloadedPagination)
    }
  }
)

const handleProcessedSelectionChange = (rows) => {
  selectedProcessedMaterials.value = rows
}

const handleDownloadedSelectionChange = (rows) => {
  selectedDownloadedMaterials.value = rows
}

const handleUploadMaterial = () => {
  fileList.value = []
  customFilename.value = ''
  uploadProgress.value = {}
  uploadDialogVisible.value = true
}

const handleUploadDialogClose = () => {
  fileList.value = []
  customFilename.value = ''
  uploadProgress.value = {}
}

const handleFileChange = (file, uploadFileList) => {
  fileList.value = uploadFileList
  const newProgress = {}
  for (const item of uploadFileList) {
    newProgress[item.uid] = { percentage: 0, speed: '' }
  }
  uploadProgress.value = newProgress
}

const handleFileRemove = (file, uploadFileList) => {
  fileList.value = uploadFileList
  const newProgress = { ...uploadProgress.value }
  delete newProgress[file.uid]
  uploadProgress.value = newProgress
}

const submitUpload = async () => {
  if (fileList.value.length === 0) {
    ElMessage.warning('请选择要上传的文件')
    return
  }

  isUploading.value = true

  for (const file of fileList.value) {
    try {
      if (!file || !file.raw) {
        ElMessage.warning(`文件 ${file.name} 对象无效，已跳过`)
        continue
      }

      const formData = new FormData()
      formData.append('file', file.raw)

      if (fileList.value.length === 1 && customFilename.value.trim()) {
        formData.append('filename', customFilename.value.trim())
      }

      let lastLoaded = 0
      let lastTime = Date.now()

      const response = await materialApi.uploadMaterial(formData, (progressEvent) => {
        const progressData = uploadProgress.value[file.uid]
        if (!progressData) return

        const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        progressData.percentage = progress

        const currentTime = Date.now()
        const timeDiff = (currentTime - lastTime) / 1000
        const loadedDiff = progressEvent.loaded - lastLoaded

        if (timeDiff > 0.5) {
          const speed = loadedDiff / timeDiff
          progressData.speed = speed > 1024 * 1024
            ? `${(speed / (1024 * 1024)).toFixed(2)} MB/s`
            : `${(speed / 1024).toFixed(2)} KB/s`
          lastLoaded = progressEvent.loaded
          lastTime = currentTime
        }
      })

      if (response.code === 200) {
        ElMessage.success(`文件 ${file.name} 上传成功`)
        const progressData = uploadProgress.value[file.uid]
        if (progressData) progressData.speed = '完成'
      } else {
        ElMessage.error(`文件 ${file.name} 上传失败: ${response.msg || '未知错误'}`)
      }
    } catch (error) {
      console.error(`上传文件 ${file.name} 出错:`, error)
      ElMessage.error(`文件 ${file.name} 上传失败: ${error.message || '未知错误'}`)
    }
  }

  isUploading.value = false
  await fetchMaterials({ force: true })
}

const handlePreview = async (material) => {
  stopPreviewVideo()
  currentMaterial.value = null
  previewDialogVisible.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 100))
    currentMaterial.value = material
  } catch (error) {
    console.error('预览素材出错:', error)
    ElMessage.error('预览加载失败')
    previewDialogVisible.value = false
  }
}

const handleEditPublishDraft = (material) => {
  const videoId = materialVideoIdForDraft(material)
  if (!videoId) {
    ElMessage.warning('该视频素材没有绑定视频线索，无法保存发布稿')
    return
  }
  currentDraftMaterial.value = material
  publishDraftForm.value = buildPublishDraftFromMaterial(material)
  publishDraftDialogVisible.value = true
}

const savePublishDraft = async () => {
  const material = currentDraftMaterial.value
  const videoId = materialVideoIdForDraft(material)
  if (!material || !videoId) return

  savingPublishDraft.value = true
  try {
    const response = await youtubeApi.updatePublishDraft(videoId, {
      title: publishDraftForm.value.title,
      description: publishDraftForm.value.description,
      tags: cleanTopicList(publishDraftForm.value.tags)
    })
    material.publishDraft = response.data?.draft || {
      title: publishDraftForm.value.title,
      description: publishDraftForm.value.description,
      tags: cleanTopicList(publishDraftForm.value.tags)
    }
    publishDraftDialogVisible.value = false
    ElMessage.success('发布稿已保存')
  } catch (error) {
    console.error('保存发布稿失败:', error)
    ElMessage.error('保存发布稿失败')
  } finally {
    savingPublishDraft.value = false
  }
}

const stopPreviewVideo = () => {
  const video = previewVideoRef.value
  if (!video) return

  video.pause()
  video.currentTime = 0
  video.removeAttribute('src')
  video.querySelectorAll('source').forEach(source => {
    source.removeAttribute('src')
  })
  video.load()
}

const handlePreviewDialogClose = () => {
  stopPreviewVideo()
}

const resetPreviewDialog = () => {
  stopPreviewVideo()
  currentMaterial.value = null
}

const handleDelete = (material) => {
  ElMessageBox.confirm(
    `确定要删除视频素材「${materialTitle(material)}」吗？`,
    '删除视频素材',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    }
  )
    .then(async () => {
      try {
        const response = await materialApi.deleteMaterial(material.id)
        if (response.code === 200) {
          appStore.removeMaterial(material.id)
          await fetchMaterials({ force: true })
          ElMessage.success('删除成功')
        } else {
          ElMessage.error(response.msg || '删除失败')
        }
      } catch (error) {
        console.error('删除视频素材出错:', error)
        ElMessage.error('删除失败')
      }
    })
    .catch(() => {})
}

const handleBatchDelete = async (scope = 'all') => {
  const rows = scope === 'downloaded' ? selectedDownloadedMaterials.value : selectedMaterials.value
  if (rows.length === 0) {
    ElMessage.warning('请先选择要删除的视频素材')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${rows.length} 个视频素材吗？对应实际文件也会删除。已发布归档不会被删除。`,
      '批量删除视频素材',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch (error) {
    return
  }

  try {
    const response = await materialApi.deleteMaterials(rows.map(row => row.id))
    const result = response.data || {}
    const successIds = (result.items || [])
      .filter(item => item.success)
      .map(item => item.id)
    appStore.removeMaterials(successIds)
    selectedProcessedMaterials.value = []
    selectedDownloadedMaterials.value = []
    await fetchMaterials({ force: true })
    if (result.failed > 0) {
      ElMessage.warning(`已删除 ${result.success} 个，${result.failed} 个删除失败`)
    } else {
      ElMessage.success(`已删除 ${result.success} 个视频素材`)
    }
  } catch (error) {
    console.error('批量删除视频素材出错:', error)
    ElMessage.error('批量删除失败')
  }
}

const getPreviewUrl = (filePath) => {
  return materialApi.getMaterialPreviewUrl(filePath)
}

const downloadFile = (material) => {
  const url = materialApi.downloadMaterial(material.file_path)
  window.open(url, '_blank')
}

const isVideoFile = (filename = '') => {
  const videoExtensions = ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv']
  return videoExtensions.some(ext => filename.toLowerCase().endsWith(ext))
}

const isImageFile = (filename = '') => {
  const imageExtensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
  return imageExtensions.some(ext => filename.toLowerCase().endsWith(ext))
}

onMounted(() => {
  fetchMaterials()
})

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer)
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

$panel-border: var(--vf-border);
$panel-shadow: var(--vf-shadow-md);
$accent-blue: var(--vf-primary);
$accent-teal: var(--vf-success);
$ink-strong: var(--vf-text-primary);

.material-management {
  display: grid;
  gap: 16px;

  :deep(.el-table th.el-table__cell) {
    background: var(--vf-surface-hover);
    color: var(--vf-text-regular);
    font-weight: 600;
  }
}

.page-header {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(360px, 0.8fr);
  gap: 16px;
  align-items: stretch;
  padding: 18px;
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: var(--vf-surface);
  box-shadow: $panel-shadow;

  h1 {
    margin: 4px 0 8px;
    color: $ink-strong;
    font-size: 25px;
    line-height: 1.25;
    font-weight: 700;
  }

  p {
    margin: 0;
    color: var(--vf-text-regular);
    font-size: 14px;
    line-height: 1.7;
  }
}

.eyebrow,
.section-kicker {
  color: $accent-blue;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.summary-item {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 8px;
  background: var(--vf-surface-hover);

  span {
    color: var(--vf-text-regular);
    font-size: 13px;
  }

  strong {
    color: $ink-strong;
    font-size: 26px;
    line-height: 1;
  }
}

.toolbar-card,
.material-section {
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: var(--vf-surface);
  box-shadow: $panel-shadow;
}

.toolbar-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;

  .el-input {
    max-width: 460px;
  }
}

.material-group-filter {
  width: 180px;
  flex: 0 0 auto;
}

.action-buttons,
.table-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.is-loading {
  animation: rotate 1s linear infinite;
}

.material-section {
  overflow: hidden;
}

.primary-section {
  border-color: rgba(15, 159, 143, 0.24);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid $border-lighter;

  h2 {
    margin: 2px 0 0;
    color: $ink-strong;
    font-size: 18px;
    line-height: 1.3;
  }
}

.section-count {
  color: $text-secondary;
  font-size: 13px;
}

.section-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px 14px;
  border-top: 1px solid $border-lighter;
}

.material-table {
  :deep(td.el-table__cell) {
    padding: 10px 0;
  }
}

:deep(.material-identity) {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

:deep(.material-thumb) {
  width: 116px;
  height: 65px;
  object-fit: cover;
  border-radius: 6px;
  background: $border-extra-light;
  flex: 0 0 auto;
}

:deep(.material-thumb-empty) {
  display: grid;
  place-items: center;
  color: $text-secondary;
  border: 1px dashed $border-base;
}

:deep(.identity-body) {
  display: grid;
  gap: 6px;
  min-width: 0;
}

:deep(.identity-title-line) {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

:deep(.identity-title) {
  min-width: 0;
  color: $ink-strong;
  font-weight: 650;
  line-height: 1.45;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &:hover {
    color: $accent-blue;
  }
}

:deep(.info-button) {
  flex: 0 0 auto;
  color: #7b8798;

  &:hover {
    color: $accent-blue;
  }
}

:deep(.workflow-badge) {
  flex: 0 0 auto;
  max-width: 132px;
  overflow: hidden;
  text-overflow: ellipsis;
}

:deep(.identity-meta) {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  color: #6b7484;
  font-size: 12px;

  span:not(:last-child)::after {
    content: '';
    display: inline-block;
    width: 3px;
    height: 3px;
    margin-left: 8px;
    border-radius: 50%;
    background: #b7c3d6;
    vertical-align: middle;
  }
}

:deep(.identity-url) {
  max-width: 620px;
  color: $text-secondary;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

:deep(.identity-url.is-muted) {
  color: #9aa4b5;
}

:global(.material-identity-popover .technical-popover) {
  display: grid;
  gap: 10px;

  strong {
    color: $ink-strong;
    font-size: 14px;
  }
}

:global(.material-identity-popover .technical-list) {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 8px 10px;
  margin: 0;
  color: #4b5565;
  font-size: 12px;

  dt {
    color: #7b8798;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  dd {
    min-width: 0;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.preview-container {
  display: flex;
  justify-content: center;
  align-items: center;
  flex-direction: column;
  padding: 0 20px;
}

.preview-video,
.preview-image {
  max-width: 100%;
  max-height: 68vh;
}

.file-info {
  text-align: center;
  margin-top: 20px;
}

.upload-form {
  padding: 0 20px;

  .upload-demo {
    width: 100%;
  }
}

.dialog-footer {
  padding: 0 20px;
  display: flex;
  justify-content: flex-end;
}

.upload-file-list {
  width: 100%;
}

.upload-file-item {
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
  background-color: #fafafa;
  transition: box-shadow 0.2s ease;

  &:hover {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }

  .file-name {
    font-size: 14px;
    color: var(--vf-text-primary);
    margin-bottom: 8px;
    display: block;
    font-weight: 500;
  }
}

:deep(.el-dialog__body) {
  padding: 20px 0;
}

:deep(.el-dialog__header) {
  padding-left: 20px;
  padding-right: 20px;
  margin-right: 0;
}

:deep(.el-dialog__footer) {
  padding-top: 10px;
  padding-bottom: 15px;
}

:deep(.el-progress__text) {
  color: var(--vf-text-primary) !important;
  font-size: 12px;
}

:deep(.el-progress--line) {
  margin-bottom: 10px;
}

@media (max-width: 960px) {
  .page-header {
    grid-template-columns: 1fr;
  }

  .toolbar-card {
    align-items: stretch;
    flex-direction: column;

    .el-input {
      max-width: none;
    }
  }

  .material-group-filter {
    width: 100%;
  }

  .action-buttons {
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .summary-strip {
    grid-template-columns: 1fr;
  }

  :deep(.material-identity) {
    align-items: flex-start;
  }

  :deep(.material-thumb) {
    width: 96px;
    height: 54px;
  }
}
</style>
