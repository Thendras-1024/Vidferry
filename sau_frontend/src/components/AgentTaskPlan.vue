<template>
  <section v-if="taskPlan?.steps?.length" class="agent-task-plan" :class="`is-${taskPlan.status || 'running'}`">
    <div class="agent-task-plan-header">
      <strong>{{ taskPlan.title || '任务计划' }}</strong>
      <el-tag size="small" effect="plain" :type="planTagType">{{ planStatusLabel }}</el-tag>
    </div>
    <ol class="agent-task-plan-steps">
      <li v-for="step in taskPlan.steps" :key="step.id" :class="`is-${step.status || 'pending'}`">
        <span class="agent-task-plan-marker" aria-hidden="true" />
        <div>
          <strong>{{ step.title }}</strong>
          <small v-if="step.detail">{{ step.detail }}</small>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  taskPlan: { type: Object, default: null }
})

const planStatusLabel = computed(() => ({
  completed: '已完成',
  waiting_user: '等待选择',
  failed: '未完成',
  blocked: '已拦截',
  running: '进行中'
}[props.taskPlan?.status] || '进行中'))

const planTagType = computed(() => ({
  completed: 'success',
  waiting_user: 'warning',
  failed: 'danger',
  blocked: 'danger'
}[props.taskPlan?.status] || 'info'))
</script>

<style scoped>
.agent-task-plan {
  display: grid;
  gap: 8px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-left: 3px solid var(--el-color-primary);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.agent-task-plan.is-waiting_user {
  border-left-color: var(--el-color-warning);
}

.agent-task-plan.is-failed,
.agent-task-plan.is-blocked {
  border-left-color: var(--el-color-danger);
}

.agent-task-plan.is-completed {
  border-left-color: var(--el-color-success);
}

.agent-task-plan-header,
.agent-task-plan-steps li,
.agent-task-plan-steps li > div {
  display: flex;
}

.agent-task-plan-header {
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.agent-task-plan-steps {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.agent-task-plan-steps li {
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  font-size: 12px;
}

.agent-task-plan-steps li > div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.agent-task-plan-steps strong {
  font-weight: 500;
}

.agent-task-plan-steps small {
  color: var(--el-text-color-secondary);
}

.agent-task-plan-marker {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  margin-top: 3px;
  border: 1px solid var(--el-border-color);
  border-radius: 50%;
  background: var(--el-fill-color-light);
}

.agent-task-plan-steps .is-active .agent-task-plan-marker {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  box-shadow: 0 0 0 3px var(--el-color-primary-light-8);
}

.agent-task-plan-steps .is-waiting_user .agent-task-plan-marker {
  border-color: var(--el-color-warning);
  background: var(--el-color-warning);
}

.agent-task-plan-steps .is-completed .agent-task-plan-marker {
  border-color: var(--el-color-success);
  background: var(--el-color-success);
}

.agent-task-plan-steps .is-failed .agent-task-plan-marker {
  border-color: var(--el-color-danger);
  background: var(--el-color-danger);
}
</style>
