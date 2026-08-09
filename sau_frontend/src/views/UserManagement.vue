<template>
  <section class="management-page">
    <header class="page-header">
      <div><h1>用户与安全</h1><p>管理登录用户、会话和安全审计记录。</p></div>
      <el-button type="primary" @click="openCreate">新建用户</el-button>
    </header>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="用户" name="users">
        <div class="toolbar">
          <el-input v-model="keyword" clearable placeholder="搜索用户名或姓名" @keyup.enter="loadUsers" />
          <el-button @click="loadUsers">查询</el-button>
        </div>
        <el-table v-loading="loading" :data="users">
          <el-table-column prop="username" label="用户名" min-width="140" />
          <el-table-column prop="displayName" label="姓名" min-width="140" />
          <el-table-column label="角色" width="110"><template #default="{ row }">{{ row.role === 'admin' ? '管理员' : '普通用户' }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag></template></el-table-column>
          <el-table-column prop="lastLoginAt" label="最近登录" min-width="180" />
          <el-table-column label="操作" width="270" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="editUser(row)">编辑</el-button>
              <el-button link type="warning" @click="resetPassword(row)">重置密码</el-button>
              <el-button link @click="unlock(row)">解锁</el-button>
              <el-button link type="danger" @click="revoke(row)">撤销会话</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination v-model:current-page="userPage" :page-size="50" :total="userTotal" layout="total, prev, pager, next" @current-change="loadUsers" />
      </el-tab-pane>
      <el-tab-pane label="审计日志" name="audit">
        <el-table v-loading="auditLoading" :data="auditLogs">
          <el-table-column prop="createdAt" label="时间" min-width="180" />
          <el-table-column prop="actorUsername" label="操作者" width="140" />
          <el-table-column prop="action" label="动作" min-width="160" />
          <el-table-column prop="targetId" label="目标" min-width="180" show-overflow-tooltip />
          <el-table-column label="结果" width="100"><template #default="{ row }"><el-tag :type="row.result === 'success' ? 'success' : 'danger'">{{ row.result }}</el-tag></template></el-table-column>
          <el-table-column prop="ipAddress" label="IP" min-width="140" />
        </el-table>
        <el-pagination v-model:current-page="auditPage" :page-size="50" :total="auditTotal" layout="total, prev, pager, next" @current-change="loadAudit" />
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="dialogVisible" :title="editingUser ? '编辑用户' : '新建用户'" width="460px">
      <el-form label-position="top">
        <el-form-item v-if="!editingUser" label="用户名"><el-input v-model.trim="form.username" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model.trim="form.displayName" /></el-form-item>
        <el-form-item v-if="!editingUser" label="临时密码"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item label="角色"><el-select v-model="form.role"><el-option label="普通用户" value="user" /><el-option label="管理员" value="admin" /></el-select></el-form-item>
        <el-form-item v-if="editingUser" label="状态"><el-switch v-model="form.active" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveUser">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { userApi } from '@/api/user'

const activeTab = ref('users')
const loading = ref(false), auditLoading = ref(false), saving = ref(false)
const users = ref([]), auditLogs = ref([])
const userPage = ref(1), userTotal = ref(0), auditPage = ref(1), auditTotal = ref(0)
const keyword = ref(''), dialogVisible = ref(false), editingUser = ref(null)
const form = reactive({ username: '', displayName: '', password: '', role: 'user', active: true })

const loadUsers = async () => {
  loading.value = true
  try {
    const result = (await userApi.listUsers({ page: userPage.value, pageSize: 50, keyword: keyword.value })).data
    users.value = result.items
    userTotal.value = result.total
  } finally { loading.value = false }
}
const loadAudit = async () => {
  auditLoading.value = true
  try {
    const result = (await userApi.listAuditLogs({ page: auditPage.value, pageSize: 50 })).data
    auditLogs.value = result.items
    auditTotal.value = result.total
  } finally { auditLoading.value = false }
}
const openCreate = () => {
  editingUser.value = null
  Object.assign(form, { username: '', displayName: '', password: '', role: 'user', active: true })
  dialogVisible.value = true
}
const editUser = row => {
  editingUser.value = row
  Object.assign(form, { displayName: row.displayName, role: row.role, active: row.status === 'active' })
  dialogVisible.value = true
}
const saveUser = async () => {
  saving.value = true
  try {
    if (editingUser.value) await userApi.updateUser(editingUser.value.id, { displayName: form.displayName, role: form.role, status: form.active ? 'active' : 'disabled' })
    else await userApi.createUser({ username: form.username, displayName: form.displayName, password: form.password, role: form.role })
    ElMessage.success(editingUser.value ? '用户已更新' : '用户已创建')
    dialogVisible.value = false
    await loadUsers()
  } finally { saving.value = false }
}
const resetPassword = async row => {
  const result = await ElMessageBox.prompt('输入至少 12 个字符的新临时密码', `重置 ${row.username} 的密码`, { inputType: 'password', inputPattern: /^.{12,128}$/, inputErrorMessage: '密码长度须为 12 到 128 个字符' })
  await userApi.resetPassword(row.id, result.value)
  ElMessage.success('密码已重置')
}
const unlock = async row => { await userApi.unlockUser(row.id); ElMessage.success('用户已解锁'); loadUsers() }
const revoke = async row => {
  await ElMessageBox.confirm(`撤销 ${row.username} 的全部登录会话？`, '撤销会话', { type: 'warning' })
  await userApi.revokeSessions(row.id)
  ElMessage.success('会话已撤销')
}

watch(activeTab, value => { if (value === 'audit') loadAudit() })
onMounted(loadUsers)
</script>

<style scoped>
.management-page { min-width: 0; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 18px; }
h1 { margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }
p { margin: 0; color: var(--vf-text-regular); }
.toolbar { display: flex; gap: 10px; width: min(100%, 440px); margin-bottom: 14px; }
.el-pagination { justify-content: flex-end; margin-top: 16px; }
</style>
