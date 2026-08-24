<template>
  <el-dialog v-model="visible" class="publish-retry-dialog" title="重发失败项" width="min(680px, calc(100vw - 32px))">
    <template #header>
      <div class="retry-dialog-title">
        <span>发布重试</span>
        <strong>重发失败项</strong>
      </div>
    </template>

    <template v-if="task">
      <section class="retry-summary">
        <span class="retry-summary-label">发布任务</span>
        <strong>{{ task.chineseTitle || '未命名发布任务' }}</strong>
        <span>{{ task.assetId || '未记录成片素材' }}</span>
      </section>

      <div class="retry-notice" role="note">
        <span>仅重新提交以下失败平台</span>
        <small>已成功的平台不会再次提交，平台和账号保持不变。</small>
      </div>

      <div class="retry-targets-heading">
        <strong>选择重发平台</strong>
        <span>{{ selectedTargetIds.length }} / {{ task.retryTargets?.length || 0 }} 已选择</span>
      </div>

      <el-checkbox-group v-model="selectedTargetIds" class="retry-targets">
        <el-checkbox v-for="target in task.retryTargets || []" :key="target.id" :value="target.id" class="retry-target">
          <span class="retry-target-content">
            <span class="retry-target-topline">
              <strong>{{ target.platform }}</strong>
              <em>失败待重发</em>
            </span>
            <span class="retry-target-account">{{ target.accountName || target.accountFile || '原账号缺失' }}</span>
            <span class="retry-target-detail">{{ target.message || '未记录失败原因' }}</span>
            <time>{{ formatBeijingTime(target.updatedAt || target.publishedAt) || '-' }}</time>
          </span>
        </el-checkbox>
      </el-checkbox-group>
    </template>

    <template #footer>
      <div class="retry-dialog-actions">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :disabled="selectedTargetIds.length === 0" :loading="submitting" @click="submit">
          重发 {{ selectedTargetIds.length }} 个失败平台
        </el-button>
      </div>
    </template>
  </el-dialog>

  <el-dialog
    v-model="riskConfirmationVisible"
    class="publish-risk-confirm-dialog"
    width="min(520px, calc(100vw - 32px))"
    append-to-body
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
  >
    <template #header>
      <div class="risk-confirm-title">
        <span>风险提示</span>
        <strong>发布前内容确认</strong>
      </div>
    </template>

    <div class="risk-confirm-content">
      <el-alert
        :title="riskConfirmationMessage"
        type="warning"
        :closable="false"
        show-icon
      />
      <p>确认后将继续重发当前选中的失败平台。</p>
    </div>

    <template #footer>
      <div class="risk-confirm-actions">
        <el-button :disabled="submitting" @click="riskConfirmationVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="confirmRiskAndRetry">继续重发</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { materialApi } from '@/api/material'
import { formatBeijingTime } from '@/utils/time'

const props = defineProps({ modelValue: Boolean, task: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue', 'completed'])
const submitting = ref(false)
const selectedTargetIds = ref([])
const riskConfirmationVisible = ref(false)
const riskConfirmationMessage = ref('检测到转写中含明确粗口，中文字幕已打码，但原声及原音识别文本可能仍含风险。是否继续重发？')
const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })

watch(() => [props.modelValue, props.task], ([isVisible]) => {
  if (isVisible) {
    selectedTargetIds.value = (props.task?.retryTargets || []).map(target => target.id)
  } else {
    riskConfirmationVisible.value = false
  }
}, { immediate: true })

const submitRetry = async (riskOverride = {}) => {
  return materialApi.retryFailedPublishTask(
    props.task.taskId,
    selectedTargetIds.value,
    riskOverride,
    { silentError: true }
  )
}

const requiresSourceContentConfirmation = (error) => {
  const data = error?.response?.data || {}
  return Number(error?.response?.status) === 409
    && data?.data?.errorCode === 'VF-AGENT-REQUIRES-CONFIRMATION'
    && data?.data?.guard?.requiresSourceContentConfirmation
}

const showRiskConfirmation = (error) => {
  const data = error?.response?.data || {}
  riskConfirmationMessage.value = data?.data?.guard?.message || data?.msg || '检测到内容风险，请确认后继续重发。'
  riskConfirmationVisible.value = true
}

const completeRetry = (response) => {
  riskConfirmationVisible.value = false
  ElMessage.success(response.msg || '失败平台已重发')
  visible.value = false
  emit('completed', response.data)
}

const submit = async () => {
  if (!props.task?.taskId || !selectedTargetIds.value.length || submitting.value) return
  submitting.value = true
  try {
    try {
      const response = await submitRetry()
      completeRetry(response)
    } catch (error) {
      if (requiresSourceContentConfirmation(error)) {
        showRiskConfirmation(error)
        return
      }
      throw error
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.msg || error.message || '重发失败')
  } finally {
    submitting.value = false
  }
}

const confirmRiskAndRetry = async () => {
  if (!riskConfirmationVisible.value || submitting.value) return
  submitting.value = true
  try {
    const response = await submitRetry({ sourceContentConfirmed: true })
    completeRetry(response)
  } catch (error) {
    riskConfirmationVisible.value = false
    ElMessage.error(error?.response?.data?.msg || error.message || '重发失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.retry-dialog-title { display: grid; gap: 3px; padding-right: 28px; }
.retry-dialog-title span, .retry-summary-label { color: var(--el-color-primary); font-size: 12px; font-weight: 600; }
.retry-dialog-title strong { color: var(--el-text-color-primary); font-size: 20px; line-height: 1.25; }
.retry-summary { display: grid; gap: 5px; border-bottom: 1px solid var(--el-border-color-lighter); padding-bottom: 16px; }
.retry-summary > strong { color: var(--el-text-color-primary); font-size: 16px; line-height: 1.45; overflow-wrap: anywhere; }
.retry-summary > span:last-child, .retry-target-account, .retry-target-detail, .retry-target time { color: var(--el-text-color-secondary); font-size: 13px; overflow-wrap: anywhere; }
.retry-notice { display: grid; gap: 3px; border-left: 3px solid var(--el-color-warning); margin-top: 16px; padding: 9px 12px; background: var(--el-color-warning-light-9); }
.retry-notice span { color: var(--el-text-color-primary); font-size: 13px; font-weight: 600; }
.retry-notice small { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; }
.retry-targets-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin: 20px 0 10px; }
.retry-targets-heading strong { color: var(--el-text-color-primary); font-size: 14px; }
.retry-targets-heading span { color: var(--el-color-primary); font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.retry-targets { display: grid; gap: 8px; }
.retry-target.el-checkbox { display: flex; box-sizing: border-box; width: 100%; max-width: 100%; min-width: 0; height: auto; min-height: 108px; align-items: flex-start; margin: 0; border: 1px solid var(--el-border-color); border-left: 3px solid var(--el-color-danger); padding: 13px 14px; background: var(--el-fill-color-light); white-space: normal; transition: border-color .16s ease, background-color .16s ease; }
.retry-target:hover { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.retry-target.is-checked { border-color: var(--el-color-primary); border-left-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.retry-target :deep(.el-checkbox__input) { flex: 0 0 auto; margin-top: 3px; }
.retry-target :deep(.el-checkbox__label) { display: block; flex: 1; min-width: 0; padding-left: 12px; }
.retry-target-content { display: grid; gap: 5px; min-width: 0; }
.retry-target-topline { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.retry-target-topline strong { color: var(--el-text-color-primary); font-size: 15px; }
.retry-target-topline em { border: 1px solid var(--el-color-danger-light-5); padding: 1px 6px; color: var(--el-color-danger); font-size: 11px; font-style: normal; line-height: 1.5; white-space: nowrap; }
.retry-target-detail { line-height: 1.5; }
.retry-target time { font-variant-numeric: tabular-nums; }
.retry-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.retry-dialog-actions :deep(.el-button) { min-width: 82px; }
.retry-dialog-actions :deep(.el-button--primary) { min-width: 168px; }
.risk-confirm-title { display: grid; gap: 3px; padding-right: 28px; }
.risk-confirm-title span { color: var(--el-color-warning-dark-2); font-size: 12px; font-weight: 600; }
.risk-confirm-title strong { color: var(--el-text-color-primary); font-size: 20px; line-height: 1.25; }
.risk-confirm-content { display: grid; gap: 14px; }
.risk-confirm-content p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.6; }
.risk-confirm-actions { display: flex; justify-content: flex-end; gap: 8px; }
.risk-confirm-actions :deep(.el-button) { min-width: 82px; }
.risk-confirm-actions :deep(.el-button--primary) { min-width: 112px; }

@media (max-width: 560px) {
  .retry-dialog-title strong { font-size: 18px; }
  .retry-target { padding: 12px; }
  .retry-target-topline { align-items: flex-start; flex-direction: column; gap: 5px; }
  .retry-dialog-actions { flex-direction: column-reverse; }
  .retry-dialog-actions :deep(.el-button), .retry-dialog-actions :deep(.el-button--primary) { width: 100%; margin: 0; }
  .risk-confirm-actions { flex-direction: column-reverse; }
  .risk-confirm-actions :deep(.el-button) { width: 100%; margin: 0; }
}
</style>
