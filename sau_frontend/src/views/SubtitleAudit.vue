<template>
  <div class="subtitle-audit">
    <section class="audit-heading">
      <div>
        <span class="kicker">LOCAL ADMIN</span>
        <h1>字幕审查与模型诊断</h1>
        <p>按处理批次查看 Google 初译、LLM 修订原文及契约失败诊断。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadList">刷新</el-button>
    </section>

    <section class="audit-filters">
      <el-input v-model="filters.keyword" clearable placeholder="视频标题、视频 ID 或任务 ID" @keyup.enter="search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="filters.status" clearable placeholder="审查状态" @change="search">
        <el-option label="修订成功" value="success" />
        <el-option label="部分回退" value="partial_fallback" />
        <el-option label="LLM 已关闭" value="disabled" />
        <el-option label="LLM 不可用" value="unavailable" />
      </el-select>
      <el-button type="primary" @click="search">查询</el-button>
      <el-button :icon="Download" :disabled="!selectedRows.length || exporting" :loading="exporting" @click="exportSelected">导出 {{ selectedRows.length || '' }}</el-button>
      <el-button :icon="Delete" type="danger" plain :disabled="!selectedRows.length || deleting" :loading="deleting" @click="deleteSelected">删除 {{ selectedRows.length || '' }}</el-button>
    </section>

    <section class="audit-table-wrap">
      <el-table ref="auditTable" v-loading="loading" :data="items" row-key="jobId" @selection-change="handleSelectionChange" @row-click="openDetail">
        <el-table-column type="selection" width="46" />
        <el-table-column prop="title" label="视频 / 任务" min-width="280">
          <template #default="{ row }">
            <strong class="title">{{ row.title }}</strong>
            <span class="muted">{{ row.videoId }} · {{ row.jobId }}</span>
          </template>
        </el-table-column>
        <el-table-column label="任务状态" width="110">
          <template #default="{ row }"><el-tag size="small" :type="jobType(row.jobStatus)">{{ jobLabel(row.jobStatus) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="审查状态" min-width="130"><template #default="{ row }">{{ reviewLabel(row.reviewStatus) }}</template></el-table-column>
        <el-table-column label="回退段数" width="100"><template #default="{ row }">{{ row.fallbackSegmentCount || 0 }}</template></el-table-column>
        <el-table-column label="保存时间" width="175"><template #default="{ row }">{{ formatTime(row.savedAt) }}</template></el-table-column>
        <el-table-column label="查看" width="74" fixed="right"><template #default="{ row }"><el-button link type="primary" @click.stop="openDetail(row)">详情</el-button></template></el-table-column>
      </el-table>
      <el-empty v-if="!loading && !items.length" description="暂无审查记录；历史任务不会从旧字幕反推。" :image-size="82" />
      <div v-if="total > pageSize" class="pager"><el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="loadList" /></div>
    </section>

    <el-drawer v-model="drawerVisible" title="字幕审查详情" direction="rtl" size="min(920px, 92vw)" append-to-body>
      <template v-if="detailLoading"><div class="detail-loading"><el-icon class="is-loading"><Loading /></el-icon>正在读取完整字幕</div></template>
      <template v-else-if="detail">
        <span ref="detailTop" class="detail-top-anchor" />
        <div class="detail-meta">
          <div><strong>{{ detail.title }}</strong><span>{{ detail.videoId }} · {{ detail.jobId }}</span></div>
          <el-tag :type="reviewType(detail)">{{ reviewLabel(detail.reviewStatus) }}</el-tag>
        </div>
        <el-alert v-if="reviewNote(detail)" :type="reviewType(detail)" :closable="false" show-icon :title="reviewNote(detail)" />
        <div v-if="retriedBatches.length || fallbackBatches.length" class="issue-jump">
          <el-tooltip content="回到详情顶部" placement="bottom">
            <el-button class="issue-jump-top" size="small" circle plain :icon="Top" aria-label="回到详情顶部" @click="scrollToDetailTop" />
          </el-tooltip>
          <span class="issue-jump-label">问题定位</span>
          <span class="issue-jump-divider" aria-hidden="true" />
          <el-button v-if="retriedBatches.length" size="small" type="warning" plain :icon="WarningFilled" @click="jumpToBatch('retried')">首次失败后重试成功 {{ retriedBatches.length }}</el-button>
          <el-button v-if="fallbackBatches.length" size="small" type="danger" plain :icon="CircleCloseFilled" @click="jumpToBatch('fallback')">回退初译 {{ fallbackBatches.length }}</el-button>
        </div>
        <el-tabs v-model="activeTab">
          <el-tab-pane label="字幕对照" name="subtitles">
            <section v-for="batch in reviewBatches" :id="`review-batch-${batch.key}`" :key="batch.key" class="review-batch" :class="{ 'is-fallback': batchState(batch) === 'fallback', 'is-retried': batchState(batch) === 'retried' }">
              <div class="batch-heading">
                <div><strong>第 {{ batch.number }} 批</strong><span>{{ batch.range }} · {{ batch.items.length }} 段</span></div>
                <el-tag size="small" :type="batchTagType(batch)">{{ batchLabel(batch) }}</el-tag>
              </div>
              <el-alert v-if="batchState(batch) !== 'success'" :type="batchState(batch) === 'fallback' ? 'error' : 'warning'" :closable="false" :title="batchReason(batch)" />
              <div class="batch-columns"><span>英文原文 / Google 初译</span><span>LLM 修订结果</span></div>
              <div v-for="item in batch.items" :key="item.key" class="batch-segment">
                <time>{{ formatRange(item.initial) }}</time>
                <div><p class="source">{{ item.initial.text || '—' }}</p><p>{{ item.initial.subtitle || '—' }}</p></div>
                <div>{{ item.reviewed.subtitle || (batch.status === 'fallback' ? '已回退 Google 初译' : '—') }}</div>
              </div>
            </section>
            <el-empty v-if="!reviewBatches.length" description="该任务没有可审查的中文字幕段落。" :image-size="72" />
          </el-tab-pane>
          <el-tab-pane v-if="detail.diagnostics?.length" label="模型诊断" name="diagnostics">
            <section v-for="(item, index) in detail.diagnostics" :key="`${item.createdAt}-${index}`" class="diagnostic">
              <div class="diagnostic-meta"><strong>{{ item.operation || '模型请求' }}</strong><span>{{ item.model }} · 第 {{ item.attempt }} 次 · {{ formatTime(item.createdAt) }}</span></div>
              <div class="violations"><el-tag v-for="violation in item.violations" :key="violation" type="warning" size="small">{{ violation }}</el-tag></div>
              <div class="diagnostic-stats">{{ item.promptTokens }} 输入 / {{ item.completionTokens }} 输出 / {{ item.totalTokens }} Token · {{ Math.round(item.latencyMs) }} ms · {{ item.category || 'contract_validation' }}</div>
              <pre>{{ formatJson(item.rawOutput) }}</pre>
            </section>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCloseFilled, Delete, Download, Loading, Refresh, Search, Top, WarningFilled } from '@element-plus/icons-vue'
import { subtitleAuditApi } from '@/api/subtitleAudit'

const loading = ref(false); const detailLoading = ref(false); const items = ref([]); const total = ref(0)
const page = ref(1); const pageSize = 20; const filters = ref({ keyword: '', status: '' })
const drawerVisible = ref(false); const detail = ref(null); const detailTop = ref(null); const activeTab = ref('subtitles')
const auditTable = ref(null); const selectedRows = ref([]); const exporting = ref(false); const deleting = ref(false)
const loadList = async () => { loading.value = true; try { const res = await subtitleAuditApi.list({ ...filters.value, page: page.value, pageSize }); const data = res?.data || {}; items.value = data.items || []; total.value = data.total || 0; selectedRows.value = []; auditTable.value?.clearSelection() } catch (error) { ElMessage.error(error?.message || '读取审查记录失败') } finally { loading.value = false } }
const search = () => { page.value = 1; loadList() }
const handleSelectionChange = rows => { selectedRows.value = rows }
const openDetail = async (row, column) => { if (column?.type === 'selection') return; drawerVisible.value = true; detail.value = null; activeTab.value = 'subtitles'; detailLoading.value = true; try { const res = await subtitleAuditApi.detail(row.jobId); detail.value = res?.data || null } catch (error) { ElMessage.error(error?.message || '读取审查详情失败') } finally { detailLoading.value = false } }
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const formatRange = item => `${Number(item?.start || 0).toFixed(1)}s - ${Number(item?.end || 0).toFixed(1)}s`
const failedAttempts = batch => (batch?.attempts || []).filter(item => ['contract_failed', 'failed'].includes(item?.status))
const batchState = batch => batch?.status === 'fallback' ? 'fallback' : failedAttempts(batch).length ? 'retried' : 'success'
const batchTagType = batch => ({ fallback: 'danger', retried: 'warning', success: 'success' }[batchState(batch)])
const batchLabel = batch => ({ fallback: '修订失败，已回退初译', retried: '首次失败，重试成功', success: '修订完成' }[batchState(batch)])
const batchReason = batch => {
  const reasons = failedAttempts(batch).map(item => `第 ${item.attempt || '—'} 次：${item.reason || item.category || '未返回原因'}`)
  if (reasons.length) return reasons.join('；')
  return batch?.reason || '该批修订失败，已回退 Google 初译。'
}
const reviewBatches = computed(() => {
  const initial = detail.value?.initialSegments || []; const reviewed = detail.value?.reviewedSegments || []
  const batches = detail.value?.reviewBatches || []
  if (!batches.length && initial.length) return [{ number: 1, indexes: initial.map((_, index) => index), status: detail.value?.reviewStatus === 'partial_fallback' ? 'fallback' : 'success', reason: detail.value?.reviewStatus === 'partial_fallback' ? '历史任务未保存批次失败原因。' : '', key: 'legacy-1' }]
  return batches.slice().sort((a, b) => Number(a.number || 0) - Number(b.number || 0)).map((batch, batchIndex) => {
    const indexes = (batch.indexes || []).map(Number).filter(index => index >= 0 && index < initial.length)
    const items = indexes.map(index => ({ initial: initial[index], reviewed: reviewed[index] || {}, key: `${batch.number}-${index}` }))
    return { ...batch, indexes, items, key: `${batch.number}-${batchIndex}`, range: items.length ? `${formatRange(items[0].initial).split(' - ')[0]} - ${formatRange(items[items.length - 1].initial).split(' - ')[1]}` : '时间未知' }
  })
})
const retriedBatches = computed(() => reviewBatches.value.filter(batch => batchState(batch) === 'retried'))
const fallbackBatches = computed(() => reviewBatches.value.filter(batch => batchState(batch) === 'fallback'))
const jumpPositions = { retried: 0, fallback: 0 }
const scrollToDetailTop = () => detailTop.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
const jumpToBatch = async state => {
  const batches = state === 'retried' ? retriedBatches.value : fallbackBatches.value
  if (!batches.length) return
  activeTab.value = 'subtitles'; await nextTick()
  const index = jumpPositions[state] % batches.length; jumpPositions[state] += 1
  const batch = batches[index]; document.getElementById(`review-batch-${batch.key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  ElMessage.info(`已定位第 ${batch.number} 批（${index + 1}/${batches.length}）`)
}
const formatJson = value => { try { return JSON.stringify(JSON.parse(value), null, 2) } catch (_) { return value || '—' } }
const jobLabel = value => ({ success: '成功', failed: '失败', processing: '处理中', waiting_confirmation: '待确认' }[value] || value || '—')
const jobType = value => ({ success: 'success', failed: 'danger', processing: 'warning', waiting_confirmation: 'warning' }[value] || 'info')
const reviewLabel = value => ({ success: 'LLM 修订成功', partial_fallback: '部分回退初译', disabled: 'LLM 已关闭', unavailable: 'LLM 不可用', empty: '无字幕段落' }[value] || '审查状态未知')
const reviewType = value => {
  const batches = value?.reviewBatches || []
  if (batches.some(item => batchState(item) === 'fallback')) return 'error'
  if (batches.some(item => batchState(item) === 'retried')) return 'warning'
  return value?.reviewStatus === 'success' ? 'success' : value?.reviewStatus === 'partial_fallback' ? 'warning' : 'info'
}
const reviewNote = value => {
  const failed = (value.reviewBatches || []).filter(item => item.status === 'fallback')
  if (failed.length) return `有 ${failed.length} 批修订失败，已回退 Google 初译。失败原因：${failed.map(batchReason).join('；')}`
  const retried = (value.reviewBatches || []).filter(item => batchState(item) === 'retried')
  if (retried.length) return `有 ${retried.length} 批首次失败后重试成功。失败原因：${retried.map(batchReason).join('；')}`
  if (value.reviewStatus === 'partial_fallback') return '有 1 批修订失败，已回退 Google 初译。失败原因：历史任务未保存批次失败原因。'
  return value.reviewStatus === 'success' ? '' : '本批次未完成 LLM 修订，右侧内容为 Google 初译或原始输出。'
}
const escapeMarkdown = value => String(value || '—').replace(/([\\`*_{}\[\]<>])/g, '\\$1')
const truncate = (value, limit = 6000) => { const text = String(value || ''); return text.length > limit ? `${text.slice(0, limit)}\n\n[内容已截断，仅保留前 ${limit} 个字符]` : text }
const batchEntries = audit => {
  const initial = audit.initialSegments || []; const reviewed = audit.reviewedSegments || []
  const batches = audit.reviewBatches?.length ? audit.reviewBatches : [{ number: 1, indexes: initial.map((_, index) => index), status: audit.reviewStatus === 'partial_fallback' ? 'fallback' : 'success', reason: audit.reviewStatus === 'partial_fallback' ? '历史任务未保存批次失败原因。' : '' }]
  return batches.slice().sort((a, b) => Number(a.number || 0) - Number(b.number || 0)).map(batch => ({ ...batch, items: (batch.indexes || []).map(Number).filter(index => index >= 0 && index < initial.length).map(index => ({ initial: initial[index], reviewed: reviewed[index] || {} })) }))
}
const auditMarkdown = audits => [
  '# Vidferry 字幕审查导出', '', `导出时间：${formatTime(new Date().toISOString())}`, `记录数：${audits.length}`, '',
  ...audits.flatMap((audit, auditIndex) => {
    const batches = batchEntries(audit)
    const header = [`## ${auditIndex + 1}. ${escapeMarkdown(audit.title)}`, '', `- 视频 ID：${escapeMarkdown(audit.videoId)}`, `- 任务 ID：${escapeMarkdown(audit.jobId)}`, `- 任务状态：${escapeMarkdown(jobLabel(audit.jobStatus))}`, `- 审查状态：${escapeMarkdown(reviewLabel(audit.reviewStatus))}`, `- 回退段数：${audit.fallbackSegmentCount || 0}`, `- 保存时间：${formatTime(audit.savedAt)}`, '', '### 修订批次与字幕对照', '']
    const subtitle = batches.flatMap(batch => [`#### 第 ${batch.number || '—'} 批（${batch.status === 'fallback' ? '修订失败，已回退 Google 初译' : '修订完成'}）`, batch.status === 'fallback' ? `失败原因：${escapeMarkdown(batch.reason || '未返回原因')}` : '', ...batch.items.flatMap(item => [`- 时间：${formatRange(item.initial)}`, `  - 英文：${escapeMarkdown(item.initial.text)}`, `  - Google 初译：${escapeMarkdown(item.initial.subtitle)}`, `  - LLM 修订：${escapeMarkdown(item.reviewed.subtitle || (batch.status === 'fallback' ? item.initial.subtitle : '—'))}`]), ''])
    const diagnostics = (audit.diagnostics || []).flatMap((item, index) => [`#### 诊断 ${index + 1}`, `- 操作：${escapeMarkdown(item.operation)}`, `- 模型：${escapeMarkdown(item.model)}`, `- 第 ${item.attempt || 1} 次，耗时 ${Math.round(item.latencyMs || 0)} ms，分类：${escapeMarkdown(item.category || 'contract_validation')}`, `- 违反项：${(item.violations || []).map(escapeMarkdown).join('、') || '—'}`, '', '```text', truncate(item.rawOutput), '```', ''])
    return [...header, ...subtitle, ...(diagnostics.length ? ['### 模型诊断', '', ...diagnostics] : []), '---', '']
  })
].join('\n')
const exportSelected = async () => {
  exporting.value = true
  try {
    const audits = await Promise.all(selectedRows.value.map(async row => (await subtitleAuditApi.detail(row.jobId))?.data))
    const blob = new Blob([auditMarkdown(audits.filter(Boolean))], { type: 'text/markdown;charset=utf-8' }); const url = URL.createObjectURL(blob); const link = document.createElement('a')
    link.href = url; link.download = `vidferry_subtitle_audit_${new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, '')}.md`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${audits.filter(Boolean).length} 条审查记录`)
  } catch (error) { ElMessage.error(error?.message || '导出审查记录失败') } finally { exporting.value = false }
}
const deleteSelected = async () => {
  const selectedJobIds = selectedRows.value.map(row => row.jobId); const count = selectedJobIds.length
  try { await ElMessageBox.confirm(`将删除 ${count} 条字幕审查快照。原视频、处理任务和字幕文件不会被删除。`, '确认删除', { type: 'warning', confirmButtonText: '删除审查快照', cancelButtonText: '取消' }) } catch (_) { return }
  deleting.value = true
  try { const res = await subtitleAuditApi.remove(selectedJobIds); ElMessage.success(`已删除 ${res?.data?.deletedCount || 0} 条审查记录`); if (drawerVisible.value && detail.value && selectedJobIds.includes(detail.value.jobId)) drawerVisible.value = false; await loadList() } catch (error) { ElMessage.error(error?.message || '删除审查记录失败') } finally { deleting.value = false }
}
onMounted(loadList)
</script>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;
.subtitle-audit { max-width: 1440px; margin: 0 auto; }
.audit-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; padding:4px 0 18px; } .kicker { color:#0f9f8f; font-size:11px; font-weight:700; } h1 { margin:4px 0 6px; font-size:22px; } .audit-heading p,.muted,.detail-meta span { color:$text-secondary; font-size:12px; } .audit-filters { display:flex; gap:10px; margin-bottom:14px; } .audit-filters .el-input { max-width:380px; } .audit-filters .el-select { width:150px; }
.audit-table-wrap { overflow:hidden; border:1px solid $border-light; border-radius:8px; background:#fff; } .title { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .muted { display:block; margin-top:5px; } .pager { display:flex; justify-content:flex-end; padding:12px 16px; border-top:1px solid $border-lighter; }
.detail-loading { display:flex; align-items:center; gap:8px; color:$text-secondary; } .detail-top-anchor { display:block; height:0; } .detail-meta { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:14px; } .detail-meta div { display:grid; gap:4px; min-width:0; } .detail-meta strong,.detail-meta span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.issue-jump { position:sticky; top:0; z-index:2; display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:12px 0 4px; padding:8px 10px; border:1px solid #dfe7ef; border-radius:6px; box-shadow:0 5px 14px rgba(15, 23, 42, .08); background:rgba(255, 255, 255, .97); color:$text-secondary; font-size:12px; } .issue-jump-top { color:#475569; } .issue-jump-label { color:$text-regular; font-weight:700; } .issue-jump-divider { width:1px; height:20px; margin:0 2px; background:#dfe7ef; }
.review-batch { margin-bottom:12px; border:1px solid $border-light; border-radius:8px; overflow:hidden; } .review-batch.is-retried { border-color:#f0b429; background:#fffdf4; } .review-batch.is-fallback { border-color:#f2b8b5; background:#fffafa; } .batch-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:10px 12px; background:#f5f8fc; } .is-retried .batch-heading { background:#fff7d6; } .is-fallback .batch-heading { background:#fff1f0; } .batch-heading div { display:flex; align-items:baseline; gap:8px; min-width:0; } .batch-heading span { color:$text-secondary; font-size:12px; } .review-batch :deep(.el-alert) { margin:10px 12px 0; } .batch-columns,.batch-segment { display:grid; grid-template-columns:125px minmax(0, 1fr) minmax(0, 1fr); gap:16px; } .batch-columns { padding:10px 12px; color:$text-secondary; font-size:12px; } .batch-columns span:first-child { grid-column:2; } .batch-segment { padding:12px; border-top:1px solid $border-lighter; line-height:1.65; font-size:13px; } .batch-segment time { color:$text-secondary; font-variant-numeric:tabular-nums; } .batch-segment p { margin:0 0 7px; white-space:pre-wrap; } .batch-segment .source { color:$text-regular; }
.diagnostic { padding:14px 0; border-bottom:1px solid $border-lighter; } .diagnostic-meta { display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px; } .diagnostic-meta span,.diagnostic-stats { color:$text-secondary; font-size:12px; } .violations { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0; } pre { max-height:360px; overflow:auto; margin:10px 0 0; padding:12px; border-radius:6px; background:#101828; color:#d0d5dd; font-size:12px; line-height:1.55; white-space:pre-wrap; }
@media (max-width: 760px) { .audit-heading,.audit-filters { align-items:stretch; flex-direction:column; } .audit-filters .el-input,.audit-filters .el-select { max-width:none; width:100%; } .batch-columns { display:none; } .batch-segment { grid-template-columns:1fr; gap:8px; } }
</style>
