<template>
  <el-dialog v-model="visible" title="重发失败项" width="min(680px, calc(100vw - 32px))">
    <template v-if="task">
      <div class="retry-summary">
        <strong>{{ task.chineseTitle || '未命名发布任务' }}</strong>
        <span>{{ task.filePath || '未记录成片路径' }}</span>
      </div>
      <el-alert title="确认后只重发以下失败平台，已成功的平台不会再次提交。平台和账号沿用原任务且不可修改。" type="warning" :closable="false" show-icon />
      <div class="retry-targets">
        <div v-for="target in task.retryTargets || []" :key="target.id" class="retry-target">
          <strong>{{ target.platform }}</strong>
          <span>{{ target.accountName || target.accountFile || '原账号缺失' }}</span>
          <span>{{ target.updatedAt || target.publishedAt || '-' }}</span>
          <p>{{ target.message || '未记录失败原因' }}</p>
        </div>
      </div>
    </template>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认重发</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { materialApi } from '@/api/material'

const props = defineProps({ modelValue: Boolean, task: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue', 'completed'])
const submitting = ref(false)
const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })

const submit = async () => {
  if (!props.task?.taskId || submitting.value) return
  submitting.value = true
  try {
    const response = await materialApi.retryFailedPublishTask(props.task.taskId)
    ElMessage.success(response.msg || '失败平台已重发')
    visible.value = false
    emit('completed', response.data)
  } catch (error) {
    ElMessage.error(error?.response?.data?.msg || error.message || '重发失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.retry-summary, .retry-target { display: grid; gap: 4px; }
.retry-summary { margin-bottom: 14px; }
.retry-summary span, .retry-target span, .retry-target p { color: var(--el-text-color-secondary); font-size: 13px; overflow-wrap: anywhere; }
.retry-targets { display: grid; gap: 10px; margin-top: 14px; }
.retry-target { border-left: 3px solid var(--el-color-danger); padding: 8px 12px; background: var(--el-fill-color-lighter); }
.retry-target p { margin: 2px 0 0; }
</style>
