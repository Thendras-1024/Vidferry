<template>
  <main class="short-video-studio">
    <header class="page-header">
      <div><span class="eyebrow">SHORT VIDEO COMPILATION</span><h1>短视频拼接</h1><p>仅筛选可复用的原生竖屏 YouTube 素材，经人工确认后生成无字幕成片。</p></div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建项目</el-button>
    </header>
    <section class="workspace-grid">
      <aside class="project-list"><div class="section-title"><h2>我的项目</h2><el-button text :icon="Refresh" :loading="loading" @click="loadProjects" /></div>
        <button v-for="item in projects" :key="item.id" class="project-item" :class="{ active: item.id === project?.id }" @click="openProject(item.id)"><strong>{{ item.topic }}</strong><span>{{ statusLabel(item.status) }} · {{ item.targetDurationSeconds }} 秒</span></button>
        <el-empty v-if="!loading && !projects.length" description="尚未创建项目" :image-size="64" />
      </aside>
      <section v-if="project" class="project-workspace">
        <div class="project-head"><div><h2>{{ project.topic }}</h2><p>{{ project.message || '等待检索' }}</p></div><el-tag :type="statusType(project.status)">{{ statusLabel(project.status) }}</el-tag></div>
        <el-alert type="info" :closable="false" show-icon title="候选仅保留 Creative Commons 或授权频道白名单中的原生竖屏视频；系统评分仅供辅助，最终去留由你确认。" />
        <div class="actions"><el-button type="primary" :loading="project.status === 'searching'" @click="startSearch">检索候选</el-button><el-button :disabled="!project.candidates?.length" @click="saveSelection">保存选择和顺序</el-button></div>
        <div v-if="project.candidates?.length" class="candidate-list">
          <article v-for="candidate in project.candidates" :key="candidate.id" class="candidate-card" :class="{ removed: !candidate.selected }">
            <img :src="candidate.thumbnail" alt="" class="thumb"><div class="candidate-copy"><div class="candidate-title"><strong>{{ selectedIndex(candidate) + 1 }}. {{ candidate.title }}</strong><el-switch v-model="candidate.selected" active-text="保留" inactive-text="移除" /></div>
              <p>{{ candidate.channel }} · {{ candidate.durationSeconds.toFixed(1) }} 秒 · {{ candidate.width }} × {{ candidate.height }}</p>
              <el-tag size="small" type="success">{{ candidate.licenseBasis }}</el-tag><el-tag size="small" :type="candidate.analysisStatus === 'success' ? 'primary' : 'info'">{{ reviewLabel(candidate.analysisStatus) }}{{ candidate.analysisStatus === 'success' ? ` · ${candidate.analysisScore} 分` : '' }}</el-tag>
              <p class="reason">{{ candidate.analysisReason || '尚未运行视觉复核' }}</p><video v-if="candidate.previewPath" :src="candidatePreviewUrl(candidate)" controls class="candidate-preview" /><div v-if="candidate.keyframes?.length" class="keyframes"><img v-for="(_, frameIndex) in candidate.keyframes" :key="frameIndex" :src="candidateFrameUrl(candidate, frameIndex + 1)" alt="候选关键帧" /></div>
              <div class="candidate-controls"><el-input-number v-model="candidate.clipDurationSeconds" :disabled="!candidate.selected" :min="1" :max="Math.floor(candidate.durationSeconds)" size="small" /><span>秒</span><el-select v-model="candidate.transitionType" :disabled="!candidate.selected" clearable placeholder="使用全片转场" size="small"><el-option v-for="option in transitions" :key="option.value" :label="option.label" :value="option.value" /></el-select><el-button size="small" :loading="reviewing === candidate.id" @click="review(candidate)">关键帧复核</el-button><el-button size="small" :disabled="selectedIndex(candidate) < 1" :icon="ArrowUp" @click="move(candidate, -1)" /><el-button size="small" :disabled="selectedIndex(candidate) < 0 || selectedIndex(candidate) === selectedCandidates.length - 1" :icon="ArrowDown" @click="move(candidate, 1)" /></div>
            </div></article>
        </div>
          <section v-if="project.candidates?.length" class="render-panel"><h3>合成设置</h3><el-form inline><el-form-item label="全片转场"><el-select v-model="renderForm.transitionType"><el-option v-for="option in transitions" :key="option.value" :label="option.label" :value="option.value" /></el-select></el-form-item><el-form-item label="BGM"><el-select v-model="renderForm.bgmTrackId" clearable placeholder="不使用 BGM"><el-option v-for="track in bgmTracks" :key="track.id" :label="`${track.title} · ${track.artist}`" :value="track.id" /></el-select></el-form-item><el-form-item><el-switch v-model="renderForm.keepOriginalAudio" active-text="保留原声" /></el-form-item><el-button type="success" :disabled="selectedCandidates.length < 2" :loading="project.status === 'queued' || project.status === 'rendering'" @click="render">生成成片</el-button></el-form><video v-if="project.outputFilePath" :src="previewUrl(project.id)" controls class="output-preview" /></section>
      </section>
      <el-empty v-else description="选择或创建一个短视频项目" />
    </section>
    <el-dialog v-model="createVisible" title="新建短视频拼接项目" width="440px"><el-form label-position="top"><el-form-item label="主题"><el-input v-model.trim="createForm.topic" placeholder="例如：搞笑宠物反应" /></el-form-item><el-button text @click="advancedVisible = !advancedVisible">{{ advancedVisible ? '收起默认设置' : '修改默认设置' }}</el-button><div v-if="advancedVisible"><el-form-item label="检索素材数"><el-input-number v-model="createForm.targetCount" :min="2" :max="12" /></el-form-item><el-form-item label="目标成片时长"><el-input-number v-model="createForm.targetDurationSeconds" :min="15" :max="90" /> 秒</el-form-item></div></el-form><template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" :loading="creating" @click="createProject">创建</el-button></template></el-dialog>
  </main>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ArrowDown, ArrowUp, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { shortVideoApi } from '@/api/shortVideo'
const projects = ref([]), project = ref(null), loading = ref(false), creating = ref(false), createVisible = ref(false), advancedVisible = ref(false), reviewing = ref('')
const createForm = reactive({ topic: '', targetCount: 10, targetDurationSeconds: 45 })
const renderForm = reactive({ transitionType: 'cut', bgmTrackId: null, keepOriginalAudio: false })
const bgmTracks = ref([]), transitions = [{ value: 'cut', label: '硬切' }, { value: 'fade', label: '淡入淡出' }, { value: 'slideleft', label: '横向滑动' }, { value: 'zoomin', label: '缩放' }]
let pollTimer = null
const openCreate = () => { Object.assign(createForm, { topic: '', targetCount: 10, targetDurationSeconds: 45 }); advancedVisible.value = false; createVisible.value = true }
const selectedCandidates = computed(() => (project.value?.candidates || []).filter(item => item.selected))
const statusLabel = status => ({ draft: '草稿', reviewing: '审核中', ready: '可合成', queued: '已排队', rendering: '渲染中', success: '已完成', failed: '失败' }[status] || status)
const statusType = status => ({ success: 'success', failed: 'danger', rendering: 'warning', queued: 'warning', ready: 'primary' }[status] || 'info')
const reviewLabel = status => ({ success: '视觉复核完成', degraded: '文本初筛降级', pending: '未复核' }[status] || status)
const previewUrl = id => `/short-video/projects/${encodeURIComponent(id)}/output`
const candidatePreviewUrl = candidate => `/short-video/projects/${encodeURIComponent(project.value.id)}/candidates/${encodeURIComponent(candidate.id)}/preview`
const candidateFrameUrl = (candidate, frame) => `/short-video/projects/${encodeURIComponent(project.value.id)}/candidates/${encodeURIComponent(candidate.id)}/frame?frame=${frame}`
const loadProjects = async () => { loading.value = true; try { projects.value = (await shortVideoApi.listProjects()).data || [] } finally { loading.value = false } }
const openProject = async id => { project.value = (await shortVideoApi.getProject(id)).data; Object.assign(renderForm, { transitionType: project.value.transitionType || 'cut', bgmTrackId: project.value.bgmTrackId || null, keepOriginalAudio: project.value.keepOriginalAudio }) }
const refreshProject = async () => { if (project.value) await openProject(project.value.id); await loadProjects() }
const createProject = async () => { if (!createForm.topic) return ElMessage.warning('请输入主题'); creating.value = true; try { const result = await shortVideoApi.createProject(createForm); createVisible.value = false; await loadProjects(); await openProject(result.data.id) } finally { creating.value = false } }
const startSearch = async () => { await shortVideoApi.search(project.value.id); await refreshProject(); ElMessage.success('候选检索已提交') }
const review = async candidate => { reviewing.value = candidate.id; try { await shortVideoApi.reviewCandidate(project.value.id, candidate.id); ElMessage.success('关键帧复核已提交') } finally { reviewing.value = '' } }
const selectedIndex = candidate => selectedCandidates.value.indexOf(candidate)
const move = (candidate, direction) => { const list = selectedCandidates.value; const index = list.indexOf(candidate); const next = index + direction; if (index < 0 || next < 0 || next >= list.length) return; [list[index], list[next]] = [list[next], list[index]]; project.value.candidates = [...list, ...(project.value.candidates || []).filter(item => !item.selected)] }
const saveSelection = async () => { const total = selectedCandidates.value.reduce((sum, item) => sum + Number(item.clipDurationSeconds || 0), 0); if (total < 15 || total > 90) return ElMessage.warning('选段总时长需在 15 至 90 秒之间'); await shortVideoApi.saveCandidates(project.value.id, selectedCandidates.value); await refreshProject(); ElMessage.success('已保存') }
const render = async () => { await saveSelection(); await shortVideoApi.render(project.value.id, renderForm); await refreshProject(); ElMessage.success('合成任务已提交') }
onMounted(async () => { await Promise.all([loadProjects(), shortVideoApi.listBgm().then(res => { bgmTracks.value = res.data || [] })]); if (projects.value[0]) await openProject(projects.value[0].id); pollTimer = window.setInterval(refreshProject, 5000) })
onBeforeUnmount(() => { if (pollTimer) window.clearInterval(pollTimer) })
</script>
<style scoped>
.short-video-studio{max-width:1440px;margin:0 auto;padding:24px}.page-header,.project-head,.section-title,.candidate-title,.candidate-controls{display:flex;align-items:center;justify-content:space-between;gap:12px}.page-header{margin-bottom:20px}.page-header h1{margin:4px 0}.page-header p,.project-head p,.candidate-copy p{color:var(--el-text-color-secondary);margin:4px 0}.eyebrow{color:var(--el-color-primary);font-size:12px;font-weight:700}.workspace-grid{display:grid;grid-template-columns:250px minmax(0,1fr);gap:16px}.project-list,.project-workspace,.render-panel{border:1px solid var(--el-border-color);padding:16px;border-radius:6px;background:var(--el-bg-color)}.project-item{display:flex;width:100%;border:0;border-bottom:1px solid var(--el-border-color-lighter);background:none;padding:12px 4px;text-align:left;flex-direction:column;gap:4px;cursor:pointer}.project-item.active{color:var(--el-color-primary)}.project-item span{font-size:12px;color:var(--el-text-color-secondary)}.actions{display:flex;gap:8px;margin:16px 0}.candidate-list{display:grid;gap:10px}.candidate-card{display:grid;grid-template-columns:150px minmax(0,1fr);gap:12px;padding:12px;border:1px solid var(--el-border-color-lighter);border-radius:4px}.candidate-card.removed{opacity:.58}.thumb{width:150px;height:190px;object-fit:cover;background:#20252b}.reason{font-size:13px}.candidate-preview{width:180px;max-height:300px;background:#000}.keyframes{display:flex;gap:6px;overflow:auto;margin:8px 0}.keyframes img{width:76px;height:110px;object-fit:cover}.candidate-controls{justify-content:flex-start;flex-wrap:wrap;margin-top:8px}.render-panel{margin-top:16px}.output-preview{width:270px;max-height:480px;background:#000}@media(max-width:800px){.workspace-grid{grid-template-columns:1fr}.candidate-card{grid-template-columns:100px minmax(0,1fr)}.thumb{width:100px;height:130px}.short-video-studio{padding:14px}}
</style>
