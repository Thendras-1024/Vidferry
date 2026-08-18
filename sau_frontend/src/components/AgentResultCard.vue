<template>
  <section class="agent-result-card">
    <div class="agent-result-card-title"><span>{{ card.title }}</span><strong>{{ card.count }}</strong></div>
    <article v-for="item in card.items || []" :key="item.id || `${item.title}-${item.detail || item.status}`" class="agent-result-card-item">
      <img v-if="item.thumbnail" :src="item.thumbnail" :alt="item.title || '视频封面'" class="agent-result-card-cover">
      <div class="agent-result-card-copy">
        <strong>{{ item.title }}</strong>
        <span v-if="item.draftTitle" class="agent-result-card-draft">{{ item.draftTitle }}</span>
        <span v-if="item.detail || item.channel || item.status">{{ item.detail || item.channel || item.status }}</span>
        <p v-if="item.description">{{ item.description }}</p>
        <div v-if="item.tags?.length" class="agent-result-card-tags">
          <el-tag v-for="tag in item.tags" :key="tag" size="small" effect="plain">#{{ tag }}</el-tag>
        </div>
        <el-button v-if="item.videoContext?.videoId" text type="primary" size="small" @click="$emit('select-video', item.videoContext)">选择此视频</el-button>
      </div>
    </article>
  </section>
</template>

<script setup>
defineProps({
  card: { type: Object, required: true }
})

defineEmits(['select-video'])
</script>

<style scoped>
.agent-result-card {
  display: grid;
  gap: 7px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.agent-result-card-title,
.agent-result-card-item,
.agent-result-card-tags {
  display: flex;
}

.agent-result-card-title {
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.agent-result-card-item {
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  padding-top: 7px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.agent-result-card-cover {
  width: 72px;
  height: 52px;
  flex: 0 0 auto;
  border-radius: 4px;
  object-fit: cover;
  background: var(--el-fill-color-light);
}

.agent-result-card-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
  font-size: 12px;
}

.agent-result-card-copy > strong,
.agent-result-card-copy > span,
.agent-result-card-copy p {
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-result-card-copy > strong,
.agent-result-card-draft {
  white-space: nowrap;
}

.agent-result-card-copy > span,
.agent-result-card-copy p {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.agent-result-card-copy p {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.agent-result-card-tags {
  flex-wrap: wrap;
  gap: 4px;
}

.agent-result-card-copy :deep(.el-button) {
  justify-self: start;
  height: 24px;
  padding: 0;
}

@media (max-width: 560px) {
  .agent-result-card-cover {
    display: none;
  }
}
</style>
