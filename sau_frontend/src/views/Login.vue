<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="brand">
        <img src="/vidferry-icon.svg" alt="Vidferry">
        <div><h1>Vidferry</h1><p>视频工作台</p></div>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名" prop="username">
          <el-input v-model.trim="form.username" autocomplete="username" autofocus />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" @keyup.enter="submit" />
        </el-form-item>
        <el-checkbox v-model="form.remember">记住登录（7 天）</el-checkbox>
        <el-button class="login-button" type="primary" native-type="submit" :loading="loading">登录</el-button>
      </el-form>
    </section>
  </main>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const userStore = useUserStore()
const formRef = ref(null)
const loading = ref(false)
const form = reactive({ username: '', password: '', remember: false })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const submit = async () => {
  await formRef.value?.validate()
  loading.value = true
  try {
    const user = await userStore.login(form)
    const target = user.mustChangePassword ? '/change-password' : String(route.query.redirect || '/')
    window.location.hash = `#${target}`
    window.location.reload()
  } catch (error) {
    ElMessage.error(error.response?.data?.msg || error.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped lang="scss">
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f3f5f7; }
.login-panel { width: min(100%, 380px); padding: 32px; border: 1px solid #dcdfe6; border-radius: 8px; background: #fff; box-shadow: 0 12px 32px rgba(31, 45, 61, .08); }
.brand { display: flex; align-items: center; gap: 14px; margin-bottom: 28px; }
.brand img { width: 44px; height: 44px; }
.brand h1 { margin: 0; color: #172033; font-size: 24px; letter-spacing: 0; }
.brand p { margin: 3px 0 0; color: #687386; font-size: 14px; }
.login-button { width: 100%; margin-top: 6px; }
</style>
