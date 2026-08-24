<template>
  <div class="agent-soul-settings" v-loading="loading">
    <header class="settings-header">
      <div>
        <span class="settings-kicker">AGENT SETTINGS</span>
        <h1>Agent 设置</h1>
      </div>
      <div class="settings-actions">
        <span class="save-status" :class="{ 'is-error': saveError }">{{ saveStatus }}</span>
        <el-button type="primary" :loading="saving" @click="saveSoul">
          <el-icon><Check /></el-icon><span>立即保存</span>
        </el-button>
      </div>
    </header>

    <el-alert v-if="loadError" type="error" show-icon :closable="false" :title="loadError" />

    <section class="settings-section">
      <div class="section-heading"><h2>soul.md</h2></div>
      <el-input
        v-model="content"
        class="soul-editor"
        type="textarea"
        :rows="22"
        maxlength="131072"
        show-word-limit
        spellcheck="false"
      />
    </section>

    <section class="settings-section maintenance-section">
      <div class="section-heading"><h2>维护</h2></div>
      <el-button :loading="backfilling" @click="backfillHistoricalTitles">补齐历史标题</el-button>
    </section>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import { agentApi } from '@/api/agent'
import { youtubeApi } from '@/api/youtube'

const content = ref('')
const loading = ref(false)
const saving = ref(false)
const backfilling = ref(false)
const loadError = ref('')
const saveError = ref(false)
const saveStatus = ref('')
let saveTimer = null
let loaded = false

const saveSoul = async () => {
  if (!loaded || saving.value) return
  if (saveTimer) {
    window.clearTimeout(saveTimer)
    saveTimer = null
  }
  saving.value = true
  saveError.value = false
  try {
    const response = await agentApi.updateSoul(content.value)
    content.value = response?.data?.content ?? content.value
    saveStatus.value = '已同步'
  } catch (error) {
    saveError.value = true
    saveStatus.value = error?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

watch(content, () => {
  if (!loaded) return
  saveStatus.value = '正在编辑'
  saveError.value = false
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(saveSoul, 600)
})

const loadSoul = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const response = await agentApi.getSoul()
    content.value = response?.data?.content || ''
    loaded = true
    saveStatus.value = '已同步'
  } catch (error) {
    loadError.value = error?.message || '读取 soul.md 失败'
  } finally {
    loading.value = false
  }
}

const backfillHistoricalTitles = async () => {
  backfilling.value = true
  try {
    const response = await youtubeApi.backfillHistoricalTitles()
    ElMessage.success(`已排队 ${response?.data?.queued || 0} 条历史标题`)
  } catch (error) {
    ElMessage.error(error?.message || '历史标题补齐任务提交失败')
  } finally {
    backfilling.value = false
  }
}

onMounted(loadSoul)
onBeforeUnmount(() => {
  if (saveTimer) window.clearTimeout(saveTimer)
})
</script>

<style scoped lang="scss">
.agent-soul-settings { max-width: 1080px; margin: 0 auto; color: var(--vf-text-primary); }
.settings-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.settings-header h1 { margin: 4px 0; font-size: 26px; letter-spacing: 0; }
.settings-kicker { color: var(--vf-primary); font: 700 11px/1 Inter, system-ui, sans-serif; letter-spacing: 0; }
.settings-actions { display: flex; align-items: center; gap: 12px; }
.save-status { color: var(--vf-text-secondary); font-size: 13px; }
.save-status.is-error { color: var(--el-color-danger); }
.settings-section { padding: 20px 22px 24px; border: 1px solid var(--vf-border); border-radius: 8px; background: var(--vf-surface); }
.maintenance-section { display: flex; align-items: center; justify-content: space-between; margin-top: 16px; padding-block: 16px; }
.section-heading h2 { margin: 0; font-size: 18px; }
.soul-editor :deep(textarea) { min-height: 460px; resize: vertical; font-family: Consolas, 'Courier New', monospace; line-height: 1.6; }
@media (max-width: 720px) {
  .settings-header { align-items: stretch; flex-direction: column; }
  .settings-actions { justify-content: space-between; }
}
</style>
