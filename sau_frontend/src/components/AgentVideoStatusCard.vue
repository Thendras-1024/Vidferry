<template>
  <section class="agent-video-status-card">
    <header>
      <div>
        <strong>{{ card.title }}</strong>
        <span>{{ card.count || 0 }} 条</span>
      </div>
      <small>第 {{ card.page || 1 }} / {{ card.pageCount || 1 }} 页</small>
    </header>

    <div v-if="card.items?.length" class="video-list">
      <label v-for="video in card.items" :key="video.id" class="video-row">
        <el-checkbox :model-value="isSelected(video.id)" @change="checked => toggle(video.id, checked)" />
        <el-image v-if="video.thumbnail" :src="video.thumbnail" fit="cover" class="video-cover" />
        <div class="video-copy">
          <strong :title="video.originalTitle || video.title">{{ video.title || '未命名视频' }}</strong>
          <small v-if="video.shortCode" class="video-code">编号 {{ video.shortCode }}</small>
          <span>{{ video.detail }}</span>
          <small v-if="video.processVersion">处理版本 {{ video.processVersion }}</small>
          <small v-if="video.latestJob?.status">最近任务 {{ video.latestJob.status }}{{ video.latestJob.step ? ` · ${video.latestJob.step}` : '' }}</small>
          <small v-if="video.latestJob?.message">{{ video.latestJob.message }}</small>
          <small v-if="video.publishedPlatforms?.length">已发布 {{ video.publishedPlatforms.map(item => item.platform).join('、') }}</small>
          <small v-else-if="video.hasPublishDraft">已有本地发布稿</small>
          <small>{{ formatBeijingTime(video.updatedAt) }}</small>
        </div>
      </label>
    </div>
    <p v-else class="empty">当前快照中没有可展示的视频。</p>

    <footer>
      <el-button text size="small" :disabled="(card.page || 1) <= 1 || loading" @click="$emit('page', (card.page || 1) - 1)">上一页</el-button>
      <span>已选 {{ selection.length }} 条</span>
      <el-button text size="small" :disabled="(card.page || 1) >= (card.pageCount || 1) || loading" @click="$emit('page', (card.page || 1) + 1)">下一页</el-button>
    </footer>
  </section>
</template>

<script setup>
import { formatBeijingTime } from '@/utils/time'

const props = defineProps({
  card: { type: Object, required: true },
  selection: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false }
})
const emit = defineEmits(['update:selection', 'page'])

const isSelected = videoId => props.selection.includes(videoId)

const toggle = (videoId, checked) => {
  const next = new Set(props.selection)
  if (checked) next.add(videoId)
  else next.delete(videoId)
  emit('update:selection', [...next], props.card.cardId)
}
</script>

<style scoped>
.agent-video-status-card {
  display: grid;
  gap: 8px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

header,
header > div,
footer,
.video-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

header,
footer {
  justify-content: space-between;
}

header span,
header small,
footer span,
.video-copy span,
.video-copy small,
.empty {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.video-list {
  display: grid;
  gap: 6px;
}

.video-row {
  min-width: 0;
  padding: 7px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 5px;
  cursor: pointer;
}

.video-cover {
  width: 76px;
  height: 52px;
  flex: 0 0 auto;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.video-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.video-copy strong,
.video-copy span,
.video-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.video-code {
  font-family: Consolas, 'Courier New', monospace;
}

.empty {
  margin: 0;
}

@media (max-width: 520px) {
  .video-cover {
    display: none;
  }
}
</style>
