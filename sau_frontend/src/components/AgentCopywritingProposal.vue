<template>
  <section v-if="proposal" class="copywriting-proposal">
    <div class="copywriting-proposal-header">
      <div>
        <span>{{ heading }}</span>
        <strong v-if="proposal.status === 'selecting_video'">{{ proposal.candidates?.length || 0 }}</strong>
      </div>
      <small v-if="proposal.status !== 'confirmed'">{{ expiryLabel }}</small>
    </div>

    <template v-if="proposal.status === 'selecting_video'">
      <el-radio-group v-model="selectedVideoId" class="video-choice-list">
        <el-radio
          v-for="video in proposal.candidates || []"
          :key="video.id"
          :value="video.id"
          class="video-choice"
        >
          <el-image v-if="video.thumbnail" :src="video.thumbnail" fit="cover" class="video-choice-cover" />
          <div class="video-choice-copy">
            <strong>{{ video.title || '未命名视频' }}</strong>
            <span>{{ [video.channel, video.duration, video.processedAt].filter(Boolean).join(' · ') }}</span>
            <dl>
              <template v-for="item in videoDetails(video)" :key="item.label">
                <dt>{{ item.label }}</dt><dd>{{ item.value }}</dd>
              </template>
            </dl>
            <details>
              <summary>完整视频信息</summary>
              <p v-if="video.analysis?.summary">{{ video.analysis.summary }}</p>
              <p v-if="video.analysis?.chinaViewAngle">{{ video.analysis.chinaViewAngle }}</p>
              <p v-if="video.analysis?.titleOptions?.length">原分析标题：{{ video.analysis.titleOptions.join(' / ') }}</p>
              <p v-if="video.analysis?.publishCopy">原分析文案：{{ video.analysis.publishCopy }}</p>
              <p v-if="video.analysis?.riskNotes?.length">风险提示：{{ video.analysis.riskNotes.join('；') }}</p>
              <p v-if="video.publishDraft?.title">当前标题：{{ video.publishDraft.title }}</p>
              <p v-if="video.publishDraft?.description">当前正文：{{ video.publishDraft.description }}</p>
              <p v-if="topicLabel(video.publishDraft?.tags, video.publishDraft?.customTags)">当前话题：{{ topicLabel(video.publishDraft?.tags, video.publishDraft?.customTags) }}</p>
            </details>
          </div>
        </el-radio>
      </el-radio-group>
      <el-input v-model="copywritingRequest" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="补充文案方向" :disabled="readonly || generating" />
      <el-button type="primary" size="small" :loading="generating" :disabled="!selectedVideoId || readonly" @click="generateCandidates">
        生成 3 版文案
      </el-button>
    </template>

    <template v-else-if="proposal.status === 'ready'">
      <div v-if="proposal.video" class="selected-video">
        <strong>{{ proposal.video.title || '当前视频' }}</strong>
        <span>{{ [proposal.video.channel, proposal.video.processedAt].filter(Boolean).join(' · ') }}</span>
      </div>
      <div class="copywriting-option-list">
        <article
          v-for="entry in draftEntries"
          :key="`${proposal.proposalId}-${entry.key}`"
          class="copywriting-option"
          :class="{ 'is-selected': selectedDraftKey === entry.key }"
          @click="selectDraft(entry.key)"
        >
          <div class="copywriting-option-header">
            <el-radio v-model="selectedDraftKey" :value="entry.key" :aria-label="`选择${entry.label}`" @click.stop />
            <strong>{{ entry.label }}</strong>
            <span>{{ entry.draft.reason || (entry.kind === 'manual' ? '从当前待发布稿开始编辑' : '') }}</span>
          </div>
          <template v-if="selectedDraftKey === entry.key">
            <el-input v-model="draftForm(entry.key).title" maxlength="120" show-word-limit aria-label="发布标题" @click.stop />
            <el-input v-model="draftForm(entry.key).description" type="textarea" :rows="5" maxlength="500" show-word-limit aria-label="发布正文" @click.stop />
            <div class="draft-tag-editor" @click.stop>
              <el-tag v-for="tag in draftForm(entry.key).tags" :key="tag" closable @close="removeTag(entry.key, tag)">#{{ tag }}</el-tag>
              <el-input v-model="draftForm(entry.key).newTag" size="small" placeholder="添加话题" @keyup.enter.prevent="addTag(entry.key)">
                <template #append>
                  <el-tooltip content="添加话题" placement="bottom">
                    <el-button :icon="Plus" aria-label="添加话题" @click="addTag(entry.key)" />
                  </el-tooltip>
                </template>
              </el-input>
            </div>
          </template>
          <template v-else>
            <p>{{ entry.draft.title }}</p>
            <p class="copywriting-option-description">{{ entry.draft.description }}</p>
            <span class="copywriting-option-tags">{{ topicLabel(entry.draft.tags) }}</span>
          </template>
        </article>
      </div>
      <el-button type="primary" size="small" :loading="saving" :disabled="readonly" @click="saveDraft">
        保存为待发布稿
      </el-button>
    </template>

    <p v-else-if="proposal.status === 'confirmed'" class="copywriting-result">{{ proposal.resultMessage || '待发布稿已保存。' }}</p>
    <p v-else class="copywriting-result">{{ proposal.message || proposal.resultMessage || '文案提案暂不可用。' }}</p>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { agentApi } from '@/api/agent'
import { cleanTopicList } from '@/utils/publishDraft'
import { formatBeijingTime } from '@/utils/time'

const props = defineProps({
  proposal: { type: Object, default: null },
  sessionId: { type: String, default: '' },
  readonly: { type: Boolean, default: false }
})
const emit = defineEmits(['update', 'saved'])

const selectedVideoId = ref('')
const selectedDraftKey = ref('llm-0')
const copywritingRequest = ref('')
const generating = ref(false)
const saving = ref(false)
const forms = reactive({})

const heading = computed(() => {
  if (props.proposal?.status === 'selecting_video') return '确认改写视频'
  if (props.proposal?.status === 'ready') return '选择发布稿版本'
  return '文案提案'
})

const expiryLabel = computed(() => props.proposal?.expiresAt ? '15 分钟内有效' : '')

const resetForms = () => {
  selectedVideoId.value = props.proposal?.selectedVideoId || ''
  selectedDraftKey.value = props.proposal?.selectedDraftKey || `llm-${Number(props.proposal?.selectedDraftIndex || 0)}`
  copywritingRequest.value = props.proposal?.request || ''
  Object.keys(forms).forEach(key => delete forms[key])
}

watch(() => [props.proposal?.proposalId, props.proposal?.status, props.proposal?.drafts, props.proposal?.manualDraft], resetForms, { immediate: true })

const draftEntries = computed(() => [
  ...(props.proposal?.drafts || []).map((draft, index) => ({ key: `llm-${index}`, kind: 'llm', index, label: `LLM 版本 ${index + 1}`, draft })),
  { key: 'manual', kind: 'manual', index: null, label: '自定义稿', draft: props.proposal?.manualDraft || {} }
])

const draftForm = key => {
  if (!forms[key]) {
    const entry = draftEntries.value.find(item => item.key === key)
    const draft = entry?.draft || {}
    forms[key] = {
      title: draft.title || '',
      description: draft.description || '',
      tags: cleanTopicList(draft.tags),
      newTag: ''
    }
  }
  return forms[key]
}

const selectDraft = key => {
  selectedDraftKey.value = key
  draftForm(key)
}

const topicLabel = (...lists) => cleanTopicList(lists.flat()).map(tag => `#${tag}`).join(' ')

const videoDetails = video => [
  { label: '状态', value: video.status || '已处理未发布' },
  { label: '原视频发布时间', value: formatBeijingTime(video.publishedAt) || '未记录' },
  { label: '检索主题', value: video.query || '未记录' },
  { label: '内容摘要', value: video.analysis?.summary || '未生成' }
]

const addTag = key => {
  const form = draftForm(key)
  const tag = cleanTopicList(form.newTag)[0] || ''
  if (!tag) return
  if (!form.tags.includes(tag)) form.tags.push(tag)
  form.newTag = ''
}

const removeTag = (key, tag) => {
  const form = draftForm(key)
  form.tags = form.tags.filter(item => item !== tag)
}

const generateCandidates = async () => {
  if (!props.proposal?.proposalId || !props.sessionId || !selectedVideoId.value) return
  generating.value = true
  try {
    const response = await agentApi.generateCopywritingProposal(props.proposal.proposalId, {
      sessionId: props.sessionId,
      videoId: selectedVideoId.value,
      request: copywritingRequest.value.trim()
    })
    emit('update', response?.data || null)
  } catch (error) {
    ElMessage.error(error?.message || '文案候选生成失败')
  } finally {
    generating.value = false
  }
}

const saveDraft = async () => {
  if (!props.proposal?.proposalId || !props.sessionId) return
  const entry = draftEntries.value.find(item => item.key === selectedDraftKey.value)
  if (!entry) return
  const form = draftForm(entry.key)
  if (!String(form.title || '').trim()) {
    ElMessage.warning('发布标题不能为空')
    return
  }
  try {
    await ElMessageBox.confirm('将覆盖当前待发布稿，封面标题保持不变。', '确认保存', {
      confirmButtonText: '保存为待发布稿',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  saving.value = true
  try {
    const response = await agentApi.applyCopywritingProposal(props.proposal.proposalId, {
      sessionId: props.sessionId,
      draftKind: entry.kind,
      draftIndex: entry.index,
      title: String(form.title || '').trim(),
      description: String(form.description || '').trim(),
      tags: cleanTopicList(form.tags)
    })
    const result = response?.data || {}
    emit('update', result.proposal || { ...props.proposal, status: 'confirmed', resultMessage: result.message })
    emit('saved', result)
    ElMessage.success(result.message || '待发布稿已保存')
  } catch (error) {
    ElMessage.error(error?.message || '待发布稿保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.copywriting-proposal {
  display: grid;
  gap: 10px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.copywriting-proposal-header,
.copywriting-proposal-header > div,
.copywriting-option-header,
.selected-video {
  display: flex;
  align-items: center;
  gap: 8px;
}

.copywriting-proposal-header {
  justify-content: space-between;
  font-size: 13px;
}

.copywriting-proposal-header small,
.selected-video span,
.copywriting-option-header span,
.copywriting-option-tags,
.copywriting-result {
  color: var(--el-text-color-secondary);
}

.video-choice-list,
.copywriting-option-list {
  display: grid;
  gap: 8px;
}

.video-choice {
  display: grid;
  grid-template-columns: auto 72px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  min-width: 0;
  margin-right: 0;
  padding: 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.video-choice :deep(.el-radio__input) {
  margin-top: 4px;
}

.video-choice-cover {
  width: 72px;
  height: 52px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.video-choice-copy,
.video-choice-copy dl {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.video-choice-copy > strong,
.video-choice-copy > span,
.video-choice-copy dd,
.copywriting-option-description {
  overflow: hidden;
  text-overflow: ellipsis;
}

.video-choice-copy dl {
  grid-template-columns: max-content minmax(0, 1fr);
  margin: 2px 0 0;
  font-size: 12px;
}

.video-choice-copy dt {
  color: var(--el-text-color-secondary);
}

.video-choice-copy dd,
.video-choice-copy p {
  margin: 0;
}

.video-choice-copy details {
  margin-top: 2px;
  font-size: 12px;
}

.copywriting-option {
  display: grid;
  gap: 8px;
  padding: 9px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  cursor: pointer;
}

.copywriting-option.is-selected {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.copywriting-option-header span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.copywriting-option p {
  margin: 0;
}

.copywriting-option-description {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.draft-tag-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.draft-tag-editor .el-input {
  width: min(220px, 100%);
}

.copywriting-result {
  margin: 0;
  font-size: 12px;
}

@media (max-width: 560px) {
  .video-choice {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .video-choice-cover {
    display: none;
  }
}
</style>
