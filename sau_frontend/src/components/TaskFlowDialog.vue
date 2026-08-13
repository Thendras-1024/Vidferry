<template>
  <el-dialog v-model="dialogVisible" class="task-flow-dialog" width="min(1240px, calc(100vw - 28px))" append-to-body destroy-on-close>
    <template #header>
      <div class="flow-dialog-heading">
        <div class="flow-dialog-title">
          <strong :title="chineseTitle">{{ chineseTitle }}</strong>
          <small class="flow-dialog-english" :title="englishTitle">{{ englishTitle }}</small>
          <span>{{ detail?.task?.typeLabel }} · {{ detail?.task?.statusLabel }}</span>
        </div>
        <div class="flow-dialog-summary">
          <span class="flow-dialog-progress">{{ detail?.task?.progress || 0 }}%</span>
          <span>开始 {{ formatTime(detail?.task?.startedAt) }}</span>
          <span>{{ detail?.task?.finishedAt ? `完成 ${formatTime(detail.task.finishedAt)}` : '进行中' }}</span>
          <span>总耗时 {{ taskDuration }}</span>
        </div>
      </div>
    </template>
    <div v-if="detail?.downloadOnly" class="download-task-summary">
      <div class="download-summary-mark" :class="`is-${detail.task.status}`">!</div>
      <div><strong>下载任务{{ detail.task.statusLabel }}</strong><p>{{ detail.message }}</p><small>下载任务不进入处理流程图。</small></div>
    </div>
    <div v-else-if="detail?.graph" class="task-flow-scroll">
      <div class="task-flow-canvas" :style="canvasStyle">
        <svg class="task-flow-edges" :width="canvasWidth" :height="canvasHeight" aria-hidden="true">
          <path v-for="edge in detail.graph.edges" :key="`${edge.from}-${edge.to}`" :d="edgePath(edge)" :class="`edge-${edge.status}`" />
        </svg>
        <div v-for="(lane, index) in detail.graph.lanes" :key="lane.id" class="flow-lane-label" :style="laneStyle(index)">{{ lane.label }}</div>
        <el-tooltip v-for="node in detail.graph.nodes" :key="node.id" placement="top" effect="light">
          <template #content><div class="dependency-tooltip"><strong>时间</strong><span>开始：{{ formatTime(node.startedAt) }}</span><span>结束：{{ formatTime(node.endedAt) }}</span><template v-if="node.dependencySummary"><strong>依赖状态</strong><span v-if="node.dependencySummary.completed.length">已完成：{{ node.dependencySummary.completed.join('、') }}</span><span v-if="node.dependencySummary.reused.length">已复用：{{ node.dependencySummary.reused.join('、') }}</span><span v-if="node.dependencySummary.running.length">进行中：{{ node.dependencySummary.running.join('、') }}</span><span v-if="node.dependencySummary.pending.length">未开始：{{ node.dependencySummary.pending.join('、') }}</span><span v-if="node.dependencySummary.blocked.length">异常阻塞：{{ node.dependencySummary.blocked.join('、') }}</span></template></div></template>
          <button class="flow-node" :class="`node-${node.status}`" :style="nodeStyle(node)" :aria-label="`${node.label} ${node.statusLabel}`" @click="selectedNode = node">
            <span class="flow-node-status" />
            <strong>{{ node.label }}</strong>
            <small>{{ node.statusLabel }}</small>
            <small class="flow-node-duration">{{ nodeDuration(node) }}</small>
          </button>
        </el-tooltip>
      </div>
    </div>
    <div v-if="selectedNode" class="flow-node-detail">
      <div class="flow-node-detail-title"><strong>{{ selectedNode.label }}</strong><el-tag size="small" :type="tagType(selectedNode.status)">{{ selectedNode.statusLabel }}</el-tag></div>
      <div class="flow-node-detail-grid"><span>开始时间</span><b>{{ selectedNode.startedAt || '未开始' }}</b><span>结束时间</span><b>{{ selectedNode.endedAt || '进行中' }}</b><span>耗时</span><b>{{ duration(selectedNode.durationSeconds) }}</b></div>
      <p v-if="selectedNode.message">{{ selectedNode.message }}</p>
      <p v-if="selectedNode.fallbackReason" class="flow-warning">继续原因：{{ selectedNode.fallbackReason }}</p>
      <p v-if="selectedNode.errorReason" class="flow-error">异常原因：{{ selectedNode.errorReason }}</p>
      <p v-if="selectedNode.inferred" class="flow-inferred">依赖关系由阶段规则推导</p>
    </div>
    <el-empty v-else-if="!detail" description="暂无任务详情" />
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({ visible: Boolean, detail: { type: Object, default: null } })
const emit = defineEmits(['update:visible'])
const dialogVisible = computed({ get: () => props.visible, set: value => emit('update:visible', value) })
const selectedNode = ref(null)
const chineseTitle = computed(() => props.detail?.task?.chineseTitle || '原题中文翻译未生成')
const englishTitle = computed(() => props.detail?.task?.englishTitle || props.detail?.task?.title || '')
const laneIndexes = computed(() => Object.fromEntries((props.detail?.graph?.lanes || []).map((lane, index) => [lane.id, index])))
const visualColumn = node => Number(node.column || 0) + (node.id === 'highlight' && (props.detail?.graph?.nodes || []).some(item => item.id === 'cover') ? 1 : 0)
const maxColumn = computed(() => Math.max(1, ...(props.detail?.graph?.nodes || []).map(visualColumn)))
const canvasWidth = computed(() => 100 + (maxColumn.value + 1) * 102 + 60)
const canvasHeight = computed(() => Math.max(250, (props.detail?.graph?.lanes?.length || 1) * 86 + 42))
const canvasStyle = computed(() => ({ width: `${canvasWidth.value}px`, height: `${canvasHeight.value}px` }))
const taskDuration = computed(() => durationBetween(props.detail?.task?.startedAt, props.detail?.task?.finishedAt))

watch(() => props.detail, () => { selectedNode.value = null })
const laneStyle = index => ({ top: `${32 + index * 86}px` })
const nodeStyle = node => ({ left: `${100 + visualColumn(node) * 102}px`, top: `${10 + (laneIndexes.value[node.laneId] || 0) * 86}px` })
const nodeById = id => (props.detail?.graph?.nodes || []).find(node => node.id === id)
const edgePath = edge => {
  const from = nodeById(edge.from)
  const to = nodeById(edge.to)
  if (!from || !to) return ''
  const fromX = 100 + visualColumn(from) * 102 + 54
  const toX = 100 + visualColumn(to) * 102 + 34
  const fromY = 32 + (laneIndexes.value[from.laneId] || 0) * 86
  const toY = 32 + (laneIndexes.value[to.laneId] || 0) * 86
  const bend = Math.max(32, Math.abs(toX - fromX) / 2)
  return `M ${fromX} ${fromY} C ${fromX + bend} ${fromY}, ${toX - bend} ${toY}, ${toX} ${toY}`
}
const tagType = status => ({ success: 'success', confirmed: 'success', reused: 'info', partial: 'warning', uncertain: 'warning', needs_verification: 'warning', waiting_existing: 'warning', cancelled: 'info', failed: 'danger', abnormal: 'danger', warning: 'warning', running: '', waiting: 'warning' }[status] || 'info')
const formatTime = value => {
  if (!value) return '未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}
const duration = seconds => `${Math.max(0, Math.round(Number(seconds) || 0))} 秒`
const taskDurationText = seconds => {
  const total = Math.max(0, Math.round(Number(seconds) || 0))
  return `${Math.floor(total / 3600)}时${Math.floor(total % 3600 / 60)}分${total % 60}秒`
}
const durationBetween = (startedAt, endedAt) => {
  if (!startedAt) return '—'
  const started = new Date(startedAt).getTime()
  const ended = new Date(endedAt || Date.now()).getTime()
  return Number.isNaN(started) || Number.isNaN(ended) ? '—' : taskDurationText((ended - started) / 1000)
}
const nodeDuration = node => node.status === 'pending' || node.status === 'waiting' || !node.startedAt ? '—' : node.status === 'running' && !node.endedAt ? '进行中' : duration(node.durationSeconds)
</script>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;
.flow-dialog-heading { display: flex; gap: 18px; align-items: center; padding-right: 20px; }
.flow-dialog-title { min-width: 0; flex: 1; }.flow-dialog-title strong, .flow-dialog-english { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.flow-dialog-title strong { color: $text-primary; font-size: 16px; }.flow-dialog-english { margin-top: 3px; color: $text-secondary !important; font-size: 11px !important; }.flow-dialog-title > span { display: block; margin-top: 3px; color: $text-secondary; font-size: 12px; }
.flow-dialog-summary { display: grid; flex: 0 0 auto; grid-template-columns: auto auto; column-gap: 10px; align-items: center; color: $text-secondary; font-size: 11px; font-variant-numeric: tabular-nums; }.flow-dialog-summary .flow-dialog-progress { grid-row: span 2; margin: 0; color: $primary-color; font-size: 20px; }.flow-dialog-summary span { white-space: nowrap; }
.download-task-summary { display: flex; gap: 14px; align-items: flex-start; padding: 28px 8px 34px; border-top: 1px solid $border-lighter; }
.download-summary-mark { display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center; border-radius: 50%; background: $danger-color; color: #fff; font-weight: 700; }
.download-summary-mark.is-success { background: $success-color; }.download-summary-mark.is-running { background: $primary-color; }.download-summary-mark.is-queued { background: #aeb6c2; }
.download-task-summary strong { display: block; color: $text-primary; font-size: 14px; }.download-task-summary p { margin: 8px 0 5px; color: $danger-color; font-size: 13px; line-height: 1.5; }.download-task-summary small { color: $text-secondary; font-size: 12px; }
.task-flow-scroll { overflow-x: auto; padding: 2px 0 10px; }
.task-flow-canvas { position: relative; min-width: 760px; background: repeating-linear-gradient(to bottom, transparent 0, transparent 85px, $border-extra-light 86px); }
.task-flow-edges { position: absolute; inset: 0; overflow: visible; }
.task-flow-edges path { fill: none; stroke-width: 2.5; }
.edge-success { stroke: $success-color; }.edge-running { stroke: $primary-color; }.edge-warning { stroke: $warning-color; }.edge-failed { stroke: $danger-color; }.edge-pending { stroke: #c0c4cc; stroke-dasharray: 6 5; }
.flow-lane-label { position: absolute; left: 0; width: 90px; color: $text-secondary; font-size: 10px; font-weight: 600; text-align: right; }
.flow-node { position: absolute; z-index: 1; display: flex; width: 88px; height: 68px; flex-direction: column; align-items: center; padding: 0; border: 0; background: transparent; color: $text-primary; cursor: pointer; text-align: center; }
.flow-node:hover, .flow-node:focus-visible { outline: 0; }.flow-node:hover .flow-node-status, .flow-node:focus-visible .flow-node-status { outline: 3px solid rgba(64, 158, 255, 0.24); outline-offset: 2px; }
.flow-node strong { overflow: hidden; width: 88px; margin-top: 5px; font-size: 10px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.flow-node small { margin-top: 1px; color: $text-secondary; font-size: 9px; }.flow-node-duration { font-variant-numeric: tabular-nums; }.flow-node-status { display: block; width: 22px; height: 22px; flex: 0 0 22px; border: 3px solid var(--vf-surface); border-radius: 50%; background: #c0c4cc; box-shadow: 0 1px 4px rgba(15, 35, 60, 0.16); }.node-success .flow-node-status, .node-confirmed .flow-node-status { background: $success-color; }.node-running .flow-node-status { background: $primary-color; }.node-warning .flow-node-status, .node-partial .flow-node-status, .node-uncertain .flow-node-status, .node-needs_verification .flow-node-status, .node-waiting_existing .flow-node-status, .node-cancelled .flow-node-status { background: $warning-color; }.node-failed .flow-node-status, .node-abnormal .flow-node-status { background: $danger-color; }.node-waiting .flow-node-status { background: $warning-color; }.node-reused .flow-node-status { background: #9aa5b1; }.node-reused strong, .node-reused small { color: #7d8792; }
.flow-node-detail { margin-top: 12px; padding: 12px 14px; border-top: 1px solid $border-lighter; background: var(--vf-surface-hover); }.flow-node-detail-title { display: flex; gap: 8px; align-items: center; }.flow-node-detail-grid { display: grid; grid-template-columns: 72px 1fr 72px 1fr 40px 1fr; gap: 6px 10px; margin-top: 10px; font-size: 12px; }.flow-node-detail-grid span { color: $text-secondary; }.flow-node-detail-grid b { color: $text-primary; font-weight: 500; }.flow-node-detail p { margin: 8px 0 0; color: $text-regular; font-size: 12px; line-height: 1.5; }.flow-warning { color: $warning-color !important; }.flow-error { color: $danger-color !important; }.flow-inferred { color: $text-secondary !important; }
.dependency-tooltip { display: grid; gap: 4px; max-width: 260px; font-size: 11px; }.dependency-tooltip strong { margin-top: 3px; font-size: 12px; }.dependency-tooltip strong:first-child { margin-top: 0; }
@media (max-width: 680px) { .flow-dialog-heading { flex-wrap: wrap; padding-right: 4px; }.flow-dialog-title { flex-basis: 100%; }.flow-dialog-summary { grid-template-columns: auto auto auto; }.flow-dialog-summary .flow-dialog-progress { grid-row: span 1; }.flow-node-detail-grid { grid-template-columns: 64px 1fr 64px 1fr; }.flow-node-detail-grid span:nth-of-type(3) { grid-column: 1; }.flow-node-detail-grid b:nth-of-type(3) { grid-column: 2; } }
@media (prefers-reduced-motion: reduce) { .flow-node, .task-flow-edges path { transition: none !important; animation: none !important; } }
</style>
