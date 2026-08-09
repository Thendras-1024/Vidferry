<template>
  <section class="password-page">
    <div class="password-panel">
      <h1>{{ required ? '首次登录修改密码' : '修改密码' }}</h1>
      <p v-if="required">管理员分配的是临时密码，继续使用前需要设置新密码。</p>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="当前密码" prop="currentPassword"><el-input v-model="form.currentPassword" type="password" show-password autocomplete="current-password" /></el-form-item>
        <el-form-item label="新密码" prop="newPassword"><el-input v-model="form.newPassword" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword"><el-input v-model="form.confirmPassword" type="password" show-password autocomplete="new-password" /></el-form-item>
        <div class="actions">
          <el-button v-if="!required" @click="$router.back()">取消</el-button>
          <el-button type="primary" :loading="loading" @click="submit">保存并重新登录</el-button>
        </div>
      </el-form>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { userApi } from '@/api/user'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const required = computed(() => Boolean(userStore.userInfo?.mustChangePassword))
const formRef = ref(null)
const loading = ref(false)
const form = reactive({ currentPassword: '', newPassword: '', confirmPassword: '' })
const validateConfirm = (_rule, value, callback) => callback(value === form.newPassword ? undefined : new Error('两次输入的新密码不一致'))
const rules = {
  currentPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [{ required: true, message: '请输入新密码', trigger: 'blur' }, { min: 12, max: 128, message: '密码长度须为 12 到 128 个字符', trigger: 'blur' }],
  confirmPassword: [{ validator: validateConfirm, trigger: 'blur' }]
}

const submit = async () => {
  await formRef.value?.validate()
  loading.value = true
  try {
    await userApi.changePassword({ currentPassword: form.currentPassword, newPassword: form.newPassword })
    ElMessage.success('密码已修改，请重新登录')
    window.location.hash = '#/login'
    window.location.reload()
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.password-page { max-width: 560px; margin: 24px auto; }
.password-panel { padding: 28px; border: 1px solid var(--vf-border); border-radius: 8px; background: var(--vf-surface); }
h1 { margin: 0 0 8px; font-size: 22px; letter-spacing: 0; }
p { margin: 0 0 24px; color: var(--vf-text-regular); }
.actions { display: flex; justify-content: flex-end; gap: 10px; }
</style>
