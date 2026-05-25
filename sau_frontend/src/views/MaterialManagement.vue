<template>
  <div class="material-management">
    <section class="page-header">
      <div>
        <span class="eyebrow">MATERIAL LIBRARY</span>
        <h1>素材管理</h1>
        <p>优先按视频线索信息管理素材，技术字段收纳到详情中。</p>
      </div>
      <div class="summary-strip">
        <div class="summary-item">
          <span>处理后视频</span>
          <strong>{{ processedMaterials.length }}</strong>
        </div>
        <div class="summary-item">
          <span>下载原视频</span>
          <strong>{{ downloadedMaterials.length }}</strong>
        </div>
        <div class="summary-item">
          <span>其他素材</span>
          <strong>{{ otherMaterials.length }}</strong>
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
      <div class="action-buttons">
        <el-button type="primary" @click="handleUploadMaterial">上传素材</el-button>
        <el-button type="info" @click="fetchMaterials" :loading="isRefreshing">
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
        <span class="section-count">{{ processedMaterials.length }} 条</span>
      </div>

      <el-table
        v-if="processedMaterials.length > 0"
        :data="processedMaterials"
        class="material-table"
        style="width: 100%"
      >
        <el-table-column label="视频信息" min-width="420">
          <template #default="{ row }">
            <MaterialIdentity :material="row" />
          </template>
        </el-table-column>
        <el-table-column label="处理类型" width="150">
          <template #default="{ row }">
            <el-tag type="warning" effect="light">{{ row.processType || '字幕翻译/信息烧录' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="字幕语言" width="120">
          <template #default="{ row }">
            <el-tag type="success" effect="plain">{{ row.subtitleLanguageLabel || languageLabel(row.subtitleLanguage) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ row.filesize }} MB</template>
        </el-table-column>
        <el-table-column prop="upload_time" label="入库时间" width="170" />
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button size="small" @click="handlePreview(row)">预览</el-button>
              <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无处理后视频" />
    </section>

    <section class="material-section">
      <div class="section-header">
        <div>
          <span class="section-kicker">原始素材</span>
          <h2>下载原视频</h2>
        </div>
        <span class="section-count">{{ downloadedMaterials.length }} 条</span>
      </div>

      <el-table
        v-if="downloadedMaterials.length > 0"
        :data="downloadedMaterials"
        class="material-table"
        style="width: 100%"
      >
        <el-table-column label="视频信息" min-width="420">
          <template #default="{ row }">
            <MaterialIdentity :material="row" />
          </template>
        </el-table-column>
        <el-table-column label="素材类型" width="130">
          <template #default>
            <el-tag type="info" effect="light">原视频下载</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ row.filesize }} MB</template>
        </el-table-column>
        <el-table-column prop="upload_time" label="入库时间" width="170" />
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
    </section>

    <section v-if="otherMaterials.length > 0" class="material-section">
      <div class="section-header">
        <div>
          <span class="section-kicker">补充素材</span>
          <h2>其他素材</h2>
        </div>
        <span class="section-count">{{ otherMaterials.length }} 条</span>
      </div>

      <el-table :data="otherMaterials" class="material-table" style="width: 100%">
        <el-table-column label="素材信息" min-width="420">
          <template #default="{ row }">
            <MaterialIdentity :material="row" />
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ row.filesize }} MB</template>
        </el-table-column>
        <el-table-column prop="upload_time" label="入库时间" width="170" />
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
      title="上传素材"
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
      :title="currentMaterial ? materialTitle(currentMaterial) : '素材预览'"
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
          <p>文件大小: {{ currentMaterial.filesize }} MB</p>
          <p>入库时间: {{ currentMaterial.upload_time }}</p>
          <el-button type="primary" @click="downloadFile(currentMaterial)">下载文件</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { InfoFilled, Refresh, Upload, VideoCamera } from '@element-plus/icons-vue'
import { ElButton, ElIcon, ElMessage, ElMessageBox, ElPopover } from 'element-plus'
import { materialApi } from '@/api/material'
import { useAppStore } from '@/stores/app'

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
const isRefreshing = ref(false)
const isUploading = ref(false)
const uploadDialogVisible = ref(false)
const previewDialogVisible = ref(false)
const currentMaterial = ref(null)
const previewVideoRef = ref(null)
const fileList = ref([])
const customFilename = ref('')
const customFilenameDisabled = computed(() => fileList.value.length > 1)
const uploadProgress = ref({})

const materialTitle = (material) => {
  return material?.displayTitle || material?.metadata?.title || material?.original_filename || material?.filename || '未命名素材'
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

const searchableText = (material) => {
  return [
    materialTitle(material),
    materialUrl(material),
    material.displayChannel,
    material.displaySubscribers,
    material.displayPublishedAt,
    material.filename,
    material.original_filename,
    material.uuid,
    material.source_video_id
  ].filter(Boolean).join(' ').toLowerCase()
}

const filteredMaterials = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  if (!keyword) return appStore.materials
  return appStore.materials.filter(material => searchableText(material).includes(keyword))
})

const processedMaterials = computed(() => {
  return filteredMaterials.value.filter(material => material.source_type === 'youtube_processed')
})

const downloadedMaterials = computed(() => {
  return filteredMaterials.value.filter(material => material.source_type === 'youtube_download')
})

const otherMaterials = computed(() => {
  return filteredMaterials.value.filter(material => !['youtube_processed', 'youtube_download'].includes(material.source_type))
})

const MaterialIdentity = defineComponent({
  name: 'MaterialIdentity',
  props: {
    material: {
      type: Object,
      required: true
    }
  },
  setup(props) {
    const infoRows = computed(() => [
      ['素材ID', props.material.id],
      ['UUID', props.material.uuid],
      ['文件名', props.material.filename],
      ['原始文件名', props.material.original_filename],
      ['存储路径', props.material.file_path],
      ['存储Key', props.material.storage_key],
      ['来源类型', props.material.source_type],
      ['视频ID', props.material.source_video_id],
      ['处理版本', props.material.processVersion],
      ['状态', props.material.status]
    ].filter(([, value]) => value !== undefined && value !== null && value !== ''))

    return () => h('div', { class: 'material-identity' }, [
      props.material.displayThumbnail
        ? h('img', { class: 'material-thumb', src: props.material.displayThumbnail, alt: '' })
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
            trigger: 'click'
          }, {
            reference: () => h(ElButton, {
              class: 'info-button',
              text: true,
              circle: true,
              'aria-label': '查看隐藏技术信息'
            }, { default: () => h(ElIcon, null, { default: () => h(InfoFilled) }) }),
            default: () => h('div', { class: 'technical-popover' }, [
              h('strong', '隐藏技术信息'),
              h('dl', { class: 'technical-list' }, infoRows.value.flatMap(([label, value]) => [
                h('dt', label),
                h('dd', String(value))
              ]))
            ])
          })
        ]),
        h('div', { class: 'identity-meta' }, [
          h('span', materialChannel(props.material) || '未知博主'),
          h('span', materialSubscribers(props.material) || '粉丝数未知'),
          h('span', materialPublishedAt(props.material) || '发布时间未知')
        ]),
        props.material.displayUrl
          ? h('span', { class: 'identity-url' }, props.material.displayUrl)
          : h('span', { class: 'identity-url is-muted' }, '无关联链接')
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

const fetchMaterials = async () => {
  isRefreshing.value = true
  try {
    const response = await materialApi.getAllMaterials()
    if (response.code === 200) {
      appStore.setMaterials(response.data)
      ElMessage.success('刷新成功')
    } else {
      ElMessage.error('获取素材列表失败')
    }
  } catch (error) {
    console.error('获取素材列表出错:', error)
    ElMessage.error('获取素材列表失败')
  } finally {
    isRefreshing.value = false
  }
}

const handleSearch = () => {}

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
  await fetchMaterials()
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
    `确定要删除素材「${materialTitle(material)}」吗？`,
    '删除素材',
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
          ElMessage.success('删除成功')
        } else {
          ElMessage.error(response.msg || '删除失败')
        }
      } catch (error) {
        console.error('删除素材出错:', error)
        ElMessage.error('删除失败')
      }
    })
    .catch(() => {})
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

$panel-border: #dce6f2;
$panel-shadow: 0 12px 28px rgba(28, 55, 90, 0.08);
$accent-blue: #2563eb;
$accent-teal: #0f9f8f;
$ink-strong: #172033;

.material-management {
  display: grid;
  gap: 16px;

  :deep(.el-table th.el-table__cell) {
    background: #f8fbff;
    color: #5c6678;
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
    margin: 0;
    color: #5b667a;
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
  background: rgba(255, 255, 255, 0.82);

  span {
    color: #5b667a;
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
  background: #fff;
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

:deep(.technical-popover) {
  display: grid;
  gap: 10px;

  strong {
    color: $ink-strong;
    font-size: 14px;
  }
}

:deep(.technical-list) {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 8px 10px;
  margin: 0;
  color: #4b5565;
  font-size: 12px;

  dt {
    color: #7b8798;
  }

  dd {
    min-width: 0;
    margin: 0;
    overflow-wrap: anywhere;
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
    color: #303133;
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
  color: #303133 !important;
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
