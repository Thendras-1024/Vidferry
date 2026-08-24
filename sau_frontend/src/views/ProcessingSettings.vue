<template>
  <div class="processing-settings" v-loading="loading">
    <header class="settings-header">
      <div>
        <span class="settings-kicker">WORKFLOW DEFAULTS</span>
        <h1>处理配置</h1>
        <p>设置新建任务使用的默认处理方案。</p>
      </div>
      <div class="settings-actions">
        <el-button @click="router.push('/youtube-research')">
          <el-icon><Back /></el-icon><span>返回采集与处理</span>
        </el-button>
        <el-button type="primary" :loading="saving" @click="saveSettings">
          <el-icon><Check /></el-icon><span>保存配置</span>
        </el-button>
      </div>
    </header>

    <el-alert v-if="loadError" type="error" show-icon :closable="false" :title="loadError" />

    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="处理方案" name="processing">
        <section class="settings-section">
          <div class="section-heading"><h2>默认方案</h2><p>选择字幕语言、处理链路和高光片段数量。</p></div>
          <div class="settings-grid">
            <label class="setting-field">
              <span>字幕语言</span>
              <el-select v-model="form.subtitleLanguage">
                <el-option v-for="item in subtitleLanguages" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </label>
            <label class="setting-field">
              <span>处理版本</span>
              <el-select v-model="form.processVersion">
                <el-option v-for="item in processVersions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </label>
            <div class="setting-note settings-span-full">{{ currentProcessVersion.description }}</div>
            <label v-if="form.processVersion === 'editing_v1'" class="setting-field">
              <span>高光片段条数</span>
              <el-select v-model="form.highlightCount">
                <el-option v-for="count in [1, 2, 3]" :key="count" :label="`${count} 条`" :value="count" />
              </el-select>
            </label>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="字幕与输出" name="output">
        <section class="settings-section">
          <div class="section-heading"><h2>字幕与输出</h2><p>控制烧录兼容性、清晰度和字幕视觉尺寸。</p></div>
          <div class="settings-grid">
            <label class="setting-field">
              <span>烧录预设</span>
              <el-select v-model="form.burnProfile">
                <el-option v-for="item in burnProfiles" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </label>
            <label class="setting-field">
              <span>字幕字号</span>
              <el-select v-model="form.subtitleSize">
                <el-option v-for="item in subtitleSizes" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </label>
            <label class="setting-field settings-span-full">
              <span>翻译署名</span>
              <el-input v-model="form.translatorLabel" maxlength="20" show-word-limit :disabled="form.subtitleMode === 'original'" />
            </label>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="翻译与拼接" name="assembly">
        <section class="settings-section">
          <div class="section-heading"><h2>翻译与拼接</h2><p>启用或关闭处理链路中的可选步骤。</p></div>
          <div class="switch-list">
            <div class="switch-row subtitle-mode-row"><div><strong>字幕模式</strong><span>自动模式检测到非中文原字幕时默认遮挡后烧制；中文原字幕保留，无原字幕时直接烧制。</span></div><el-radio-group v-model="form.subtitleMode"><el-radio-button value="auto" :disabled="!subtitleMaskAvailable">自动适配</el-radio-button><el-radio-button value="force_burn">强制烧制</el-radio-button><el-radio-button value="original">原字幕</el-radio-button></el-radio-group></div>
            <div class="switch-row"><div><strong>广告风险审查</strong><span>ASR 后检测连续站外推广内容。</span></div><el-switch v-model="form.contentSafetyReviewEnabled" /></div>
            <div class="switch-row"><div><strong>拼接高光片段</strong><span>处理版本二在正片前加入高光片段。</span></div><el-switch v-model="form.highlightIntroEnabled" /></div>
            <div class="switch-row"><div><strong>拼接封面图片</strong><span>处理版本二在正片前加入封面片头。</span></div><el-switch v-model="form.coverIntroEnabled" /></div>
            <div class="switch-row"><div><strong>烧制评论</strong><span>{{ commentBurnAvailable ? '筛选并翻译热门评论后烧制。' : '当前自定义字幕命令不支持评论烧制。' }}</span></div><el-switch v-model="form.commentBurnEnabled" :disabled="form.processVersion !== 'editing_v1' || !commentBurnAvailable" /></div>
            <div v-if="form.subtitleMode === 'force_burn'" class="switch-row"><div><strong>遮挡原视频字幕</strong><span>{{ subtitleMaskAvailable ? '固定遮挡底部字幕区并用强模糊细颗粒马赛克覆盖，新字幕位于上层。' : '当前自定义字幕命令不支持字幕遮挡。' }}</span></div><el-switch v-model="form.subtitleMaskEnabled" :disabled="!subtitleMaskAvailable" /></div>
            <div v-if="form.commentBurnEnabled" class="inline-settings">
              <label class="setting-field"><span>评论数量</span><el-select v-model="form.commentBurnCount"><el-option v-for="count in commentBurnCounts" :key="count" :label="`${count} 条`" :value="count" /></el-select></label>
              <label class="setting-field"><span>评论翻译</span><el-radio-group v-model="form.commentTranslationMode"><el-radio-button value="google_llm">Google + LLM</el-radio-button><el-radio-button value="google">Google</el-radio-button></el-radio-group></label>
            </div>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="封面片头" name="cover">
        <section class="settings-section">
          <div class="section-heading"><h2>封面片头</h2><p>设置处理版本二封面片头中的品牌署名。</p></div>
          <label class="setting-field compact-field"><span>封面署名</span><el-input v-model="form.coverSignature" maxlength="24" show-word-limit /></label>
          <div class="signature-preview">{{ form.coverSignature || 'Vidferry' }}</div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="水印标识" name="watermark">
        <section class="settings-section">
          <div class="section-heading"><h2>水印标识</h2><p>控制整段视频右上角的持续水印。</p></div>
          <div class="switch-row"><div><strong>启用水印</strong><span>在整段视频右上角显示固定文字。</span></div><el-switch v-model="form.watermarkEnabled" /></div>
          <label class="setting-field compact-field"><span>水印内容</span><el-input v-model="form.watermarkText" :disabled="!form.watermarkEnabled" minlength="2" maxlength="16" show-word-limit placeholder="Vidferry" /></label>
          <div class="watermark-preview" :class="{ 'is-disabled': !form.watermarkEnabled }"><span>{{ form.watermarkText || 'Vidferry' }}</span></div>
        </section>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back, Check } from '@element-plus/icons-vue'
import { youtubeApi } from '@/api/youtube'

const router = useRouter()
const activeTab = ref('processing')
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const commentBurnAvailable = ref(true)
const subtitleMaskAvailable = ref(true)
const commentBurnCounts = [20, 25, 30, 35, 40, 45, 50]
const form = reactive({
  processVersion: 'translation_v1', subtitleLanguage: 'zh-CN', burnProfile: 'stable', subtitleSize: 'large',
  translatorLabel: 'Vidferry', coverSignature: 'Vidferry', watermarkEnabled: false, watermarkText: '', highlightCount: 3,
  subtitleMode: 'auto', translationEnabled: true, highlightIntroEnabled: true, coverIntroEnabled: true, commentBurnEnabled: false, subtitleMaskEnabled: false,
  commentBurnCount: 30, commentTranslationMode: 'google_llm', contentSafetyReviewEnabled: false
})

const subtitleLanguages = [
  ['zh-CN', '中文'], ['en', '英文'], ['ja', '日文'], ['ko', '韩文'], ['es', '西班牙语'], ['fr', '法语'], ['de', '德语'], ['ru', '俄语']
].map(([value, label]) => ({ value, label }))
const processVersions = [
  { value: 'translation_v1', label: '处理版本一：翻译', description: '生成目标语言字幕，并保留原作者信息。' },
  { value: 'editing_v1', label: '处理版本二：剪辑', description: '保留字幕链路，并在正片前拼接封面与高光片段。' }
]
const burnProfiles = [
  { value: 'stable', label: '标准 1080p（推荐）' }, { value: 'fast', label: '快速 1080p' }, { value: '2k', label: '2K 高画质（需 2K 原片）' }
]
const subtitleSizes = [
  { value: 'standard', label: '标准' }, { value: 'large', label: '大号（推荐）' }, { value: 'douyin', label: '超大号' }
]
const currentProcessVersion = computed(() => processVersions.find(item => item.value === form.processVersion) || processVersions[0])

watch(() => form.processVersion, value => {
  if (value !== 'editing_v1') form.commentBurnEnabled = false
})

watch(() => form.subtitleMode, value => {
  form.translationEnabled = value !== 'original'
  if (value !== 'force_burn') form.subtitleMaskEnabled = false
})

const loadSettings = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const response = await youtubeApi.getWorkflowSettings()
    const data = response?.data || response || {}
    Object.keys(form).forEach(key => {
      if (data[key] !== undefined) form[key] = data[key]
    })
    commentBurnAvailable.value = data.commentBurnAvailable !== false
    subtitleMaskAvailable.value = data.subtitleMaskAvailable !== false
    if (!subtitleMaskAvailable.value && form.subtitleMode === 'auto') form.subtitleMode = 'force_burn'
  } catch (error) {
    loadError.value = error?.message || '读取处理配置失败'
  } finally {
    loading.value = false
  }
}

const saveSettings = async () => {
  if (form.watermarkEnabled && String(form.watermarkText || '').trim().length === 1) {
    ElMessage.warning('水印内容至少需要 2 个字符')
    activeTab.value = 'watermark'
    return
  }
  saving.value = true
  try {
    const response = await youtubeApi.updateWorkflowSettings({ ...form })
    const data = response?.data || response || {}
    Object.keys(form).forEach(key => {
      if (data[key] !== undefined) form[key] = data[key]
    })
    localStorage.setItem('vidferry.youtube.workflowSettings', JSON.stringify(form))
    ElMessage.success('处理配置已保存')
  } catch (error) {
    ElMessage.error(error?.message || '保存处理配置失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped lang="scss">
.processing-settings { max-width: 1080px; margin: 0 auto; color: var(--vf-text-primary); }
.settings-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.settings-header h1 { margin: 4px 0; font-size: 26px; letter-spacing: 0; }
.settings-header p, .section-heading p { margin: 0; color: var(--vf-text-secondary); line-height: 1.6; }
.settings-kicker { color: var(--vf-primary); font: 700 11px/1 Inter, system-ui, sans-serif; letter-spacing: 0; }
.settings-actions { display: flex; gap: 8px; }
.settings-actions .el-button + .el-button { margin-left: 0; }
.settings-tabs { padding: 0 22px 24px; border: 1px solid var(--vf-border); border-radius: 8px; background: var(--vf-surface); }
.settings-section { padding-top: 10px; }
.section-heading { margin-bottom: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--vf-border-light); }
.section-heading h2 { margin: 0 0 4px; font-size: 18px; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.settings-span-full { grid-column: 1 / -1; }
.setting-field { min-width: 0; display: grid; gap: 7px; color: var(--vf-text-regular); font-size: 13px; font-weight: 600; }
.setting-note { padding: 12px 14px; color: var(--vf-text-regular); background: var(--vf-surface-hover); border-left: 3px solid var(--vf-primary); line-height: 1.6; }
.switch-list { display: grid; }
.switch-row { min-height: 66px; display: flex; align-items: center; justify-content: space-between; gap: 20px; border-bottom: 1px solid var(--vf-border-light); }
.switch-row > div { display: grid; gap: 4px; }
.switch-row strong { font-size: 14px; }
.switch-row span { color: var(--vf-text-secondary); font-size: 12px; line-height: 1.5; }
.subtitle-mode-row .el-radio-group { display: inline-flex; flex: 0 0 auto; flex-wrap: nowrap; width: auto; }
.inline-settings { display: grid; grid-template-columns: minmax(180px, .6fr) minmax(280px, 1fr); gap: 18px; padding: 16px; background: var(--vf-surface-hover); }
.compact-field { max-width: 460px; margin-top: 18px; }
.signature-preview { margin-top: 24px; padding: 30px; color: #fff; background: #17212b; font-size: 28px; font-weight: 700; text-align: center; }
.watermark-preview { position: relative; width: min(680px, 100%); aspect-ratio: 16 / 7; margin-top: 24px; background: var(--vf-border); }
.watermark-preview span { position: absolute; top: 18px; right: 18px; padding: 5px 8px; color: #fff; background: rgba(23, 33, 43, .68); font-size: 13px; }
.watermark-preview.is-disabled { opacity: .42; }
@media (max-width: 720px) {
  .settings-header { align-items: stretch; flex-direction: column; }
  .settings-actions, .settings-grid, .inline-settings { grid-template-columns: 1fr; }
  .settings-actions { display: grid; }
  .settings-span-full { grid-column: auto; }
}
</style>
