<template>
  <main class="bgm-admin"><header class="page-header"><div><span class="eyebrow">ADMIN MUSIC LIBRARY</span><h1>短视频 BGM 管理</h1><p>上架前确认音乐的可用范围和授权信息。</p></div></header>
    <section class="panel"><el-form label-position="top" @submit.prevent="upload"><el-form-item label="音频文件"><input type="file" accept="audio/*" @change="event => form.file = event.target.files?.[0]" /></el-form-item><el-form-item label="曲名"><el-input v-model.trim="form.title" /></el-form-item><el-form-item label="作者或来源"><el-input v-model.trim="form.artist" /></el-form-item><el-form-item label="来源 URL"><el-input v-model.trim="form.sourceUrl" /></el-form-item><el-form-item label="许可证或授权说明"><el-input v-model.trim="form.licenseNote" type="textarea" /></el-form-item><el-button type="primary" :loading="uploading" @click="upload">上传并上架</el-button></el-form></section>
    <section class="panel"><el-table :data="tracks"><el-table-column prop="title" label="曲名" /><el-table-column prop="artist" label="作者" /><el-table-column prop="source_url" label="来源" show-overflow-tooltip /><el-table-column prop="license_note" label="授权说明" show-overflow-tooltip /><el-table-column label="状态" width="180"><template #default="{ row }"><el-switch :model-value="row.enabled" active-text="上架" inactive-text="下架" @change="value => setEnabled(row, value)" /><el-button link type="danger" @click="removeTrack(row)">删除</el-button></template></el-table-column></el-table></section>
    <section class="panel"><h2>授权频道白名单</h2><el-form inline><el-form-item><el-input v-model.trim="channelForm.channel" placeholder="YouTube 频道名称" /></el-form-item><el-form-item><el-input v-model.trim="channelForm.note" placeholder="授权说明" /></el-form-item><el-button type="primary" @click="addChannel">新增频道</el-button></el-form><el-table :data="channels"><el-table-column prop="channel" label="频道" /><el-table-column prop="note" label="授权说明" /><el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="danger" @click="removeChannel(row)">删除</el-button></template></el-table-column></el-table></section>
  </main>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { shortVideoApi } from '@/api/shortVideo'
const tracks = ref([]), channels = ref([]), uploading = ref(false), form = reactive({ file: null, title: '', artist: '', sourceUrl: '', licenseNote: '' }), channelForm = reactive({ channel: '', note: '' })
const load = async () => { const [trackResult, channelResult] = await Promise.all([shortVideoApi.listAdminBgm(), shortVideoApi.listChannels()]); tracks.value = trackResult.data || []; channels.value = channelResult.data || [] }
const upload = async () => { if (!form.file || !form.title || !form.artist || !form.sourceUrl || !form.licenseNote) return ElMessage.warning('请完整填写 BGM 授权资料'); uploading.value = true; try { const data = new FormData(); Object.entries(form).forEach(([key, value]) => data.append(key, value)); await shortVideoApi.uploadBgm(data); Object.assign(form, { file: null, title: '', artist: '', sourceUrl: '', licenseNote: '' }); await load(); ElMessage.success('BGM 已上架') } finally { uploading.value = false } }
const setEnabled = async (track, enabled) => { await shortVideoApi.updateBgm(track.id, { enabled }); await load() }
const removeTrack = async track => { await shortVideoApi.deleteBgm(track.id); await load(); ElMessage.success('BGM 已删除') }
const addChannel = async () => { if (!channelForm.channel) return ElMessage.warning('请输入频道名称'); await shortVideoApi.addChannel(channelForm); Object.assign(channelForm, { channel: '', note: '' }); await load() }
const removeChannel = async channel => { await shortVideoApi.deleteChannel(channel.id); await load() }
onMounted(load)
</script>
<style scoped>.bgm-admin{max-width:1100px;margin:auto;padding:24px}.page-header{margin-bottom:20px}.page-header h1{margin:4px 0}.page-header p{color:var(--el-text-color-secondary)}.eyebrow{font-size:12px;color:var(--el-color-primary);font-weight:700}.panel{padding:18px;margin-bottom:16px;border:1px solid var(--el-border-color);border-radius:6px}.panel :deep(.el-form){max-width:640px}</style>
