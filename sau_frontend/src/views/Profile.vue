<template>
  <section class="profile-page">
    <div class="profile-panel">
      <header>
        <el-avatar :size="56" :src="userStore.userInfo?.avatarUrl || '/vidferry-icon.svg'">{{ initial }}</el-avatar>
        <div><h1>个人资料</h1><p>头像将在后续版本支持自定义。</p></div>
      </header>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <el-form-item label="昵称" prop="displayName"><el-input v-model.trim="form.displayName" maxlength="32" show-word-limit /></el-form-item>
        <div class="actions"><el-button @click="$router.back()">取消</el-button><el-button type="primary" native-type="submit" :loading="loading">保存资料</el-button></div>
      </el-form>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const formRef = ref(null)
const loading = ref(false)
const form = reactive({ displayName: userStore.userInfo?.displayName || '' })
const initial = computed(() => String(userStore.userInfo?.displayName || 'U').slice(0, 1).toUpperCase())
const rules = { displayName: [{ required: true, message: '请输入昵称', trigger: 'blur' }, { min: 2, max: 32, message: '昵称长度须为 2 到 32 个字符', trigger: 'blur' }] }

const submit = async () => {
  await formRef.value?.validate()
  loading.value = true
  try {
    await userStore.updateProfile({ displayName: form.displayName })
    ElMessage.success('资料已更新')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.profile-page { max-width: 560px; margin: 24px auto; }
.profile-panel { padding: 28px; border: 1px solid var(--vf-border); border-radius: 8px; background: var(--vf-surface); }
header { display: flex; align-items: center; gap: 16px; margin-bottom: 28px; }
h1 { margin: 0 0 4px; font-size: 22px; letter-spacing: 0; }
p { margin: 0; color: var(--vf-text-secondary); font-size: 14px; }
.actions { display: flex; justify-content: flex-end; gap: 10px; }
</style>
