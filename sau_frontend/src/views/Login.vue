<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="brand">
        <img src="/vidferry-icon.svg" alt="Vidferry">
        <div><h1>Vidferry</h1><p>视频工作台</p></div>
      </div>
      <el-tabs v-model="loginMode" stretch>
        <el-tab-pane label="用户名密码" name="password">
          <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-position="top" @submit.prevent="submitPassword">
            <el-form-item label="用户名" prop="username">
              <el-input v-model.trim="passwordForm.username" autocomplete="username" autofocus />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="passwordForm.password" type="password" show-password autocomplete="current-password" @keyup.enter="submitPassword" />
            </el-form-item>
            <el-checkbox v-model="passwordForm.remember">记住登录（7 天）</el-checkbox>
            <el-button class="login-button" type="primary" native-type="submit" :loading="loading">登录</el-button>
          </el-form>
        </el-tab-pane>
        <el-tab-pane v-if="phoneLoginEnabled" :label="phoneAutoRegisterEnabled ? '手机号登录 / 注册' : '手机号登录'" name="phone">
          <el-form ref="phoneFormRef" :model="phoneForm" :rules="phoneRules" label-position="top" @submit.prevent="submitPhone">
            <p v-if="phoneAutoRegisterEnabled" class="phone-hint">首次验证手机号将自动注册。</p>
            <el-form-item label="手机号" prop="phone">
              <el-input v-model.trim="phoneForm.phone" inputmode="numeric" autocomplete="tel" />
            </el-form-item>
            <el-form-item label="短信验证码" prop="code">
              <div class="code-input">
                <el-input v-model.trim="phoneForm.code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" @keyup.enter="submitPhone" />
                <el-button :disabled="codeCooldown > 0" :loading="sendingCode" @click="sendCode">{{ codeCooldown ? `${codeCooldown}s` : '获取验证码' }}</el-button>
              </div>
            </el-form-item>
            <el-checkbox v-model="phoneForm.remember">记住登录（7 天）</el-checkbox>
            <el-button class="login-button" type="primary" native-type="submit" :loading="loading">{{ phoneAutoRegisterEnabled ? '登录 / 注册' : '登录' }}</el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </section>
  </main>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { userApi } from '@/api/user'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const userStore = useUserStore()
const passwordFormRef = ref(null)
const phoneFormRef = ref(null)
const loginMode = ref('password')
const loading = ref(false)
const sendingCode = ref(false)
const phoneLoginEnabled = ref(false)
const phoneAutoRegisterEnabled = ref(false)
const captchaAppId = ref('')
const passwordCaptchaRequired = ref(false)
const codeCooldown = ref(0)
let cooldownTimer = null

const passwordForm = reactive({ username: '', password: '', remember: false })
const phoneForm = reactive({ phone: '', code: '', challengeId: '', remember: false, idempotencyKey: '' })
const passwordRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}
const phoneRules = {
  phone: [{ required: true, message: '请输入手机号', trigger: 'blur' }],
  code: [{ required: true, message: '请输入验证码', trigger: 'blur' }]
}

const errorMessage = error => error.response?.data?.msg || error.message || '登录失败'
const errorCode = error => error.response?.data?.data?.errorCode || ''

const createIdempotencyKey = () => {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  window.crypto.getRandomValues(bytes)
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

const loadCaptchaScript = () => new Promise((resolve, reject) => {
  if (window.TencentCaptcha) return resolve()
  const current = document.getElementById('tencent-captcha-script')
  if (current) {
    current.addEventListener('load', resolve, { once: true })
    current.addEventListener('error', reject, { once: true })
    return
  }
  const script = document.createElement('script')
  script.id = 'tencent-captcha-script'
  script.src = 'https://turing.captcha.qcloud.com/TJCaptcha.js'
  script.async = true
  script.onload = resolve
  script.onerror = () => reject(new Error('人机验证加载失败'))
  document.head.appendChild(script)
})

const requestCaptcha = async () => {
  if (!captchaAppId.value) throw new Error('人机验证暂不可用')
  await loadCaptchaScript()
  return new Promise((resolve, reject) => {
    const captcha = new window.TencentCaptcha(captchaAppId.value, result => {
      if (result?.ret === 0 && result.ticket && result.randstr) resolve({ captchaTicket: result.ticket, captchaRandstr: result.randstr })
      else reject(new Error('人机验证未完成'))
    })
    captcha.show()
  })
}

const finishLogin = user => {
  const target = user.mustChangePassword ? '/change-password' : String(route.query.redirect || '/')
  window.location.hash = `#${target}`
  window.location.reload()
}

const submitPassword = async () => {
  await passwordFormRef.value?.validate()
  loading.value = true
  try {
    const captcha = passwordCaptchaRequired.value ? await requestCaptcha() : {}
    finishLogin(await userStore.login({ ...passwordForm, ...captcha }))
  } catch (error) {
    if (errorCode(error) === 'CAPTCHA_REQUIRED' || error.response?.data?.data?.captchaRequired) passwordCaptchaRequired.value = true
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

const startCooldown = () => {
  codeCooldown.value = 60
  cooldownTimer = window.setInterval(() => {
    codeCooldown.value -= 1
    if (codeCooldown.value <= 0) {
      window.clearInterval(cooldownTimer)
      cooldownTimer = null
    }
  }, 1000)
}

const sendCode = async () => {
  await phoneFormRef.value?.validateField('phone')
  sendingCode.value = true
  try {
    const captcha = await requestCaptcha()
    phoneForm.idempotencyKey ||= createIdempotencyKey()
    const response = await userApi.sendPhoneCode({ phone: phoneForm.phone, idempotencyKey: phoneForm.idempotencyKey, ...captcha })
    phoneForm.challengeId = response.data.challengeId
    phoneForm.idempotencyKey = ''
    startCooldown()
    ElMessage.success('验证码已发送')
  } catch (error) {
    if (error.response) phoneForm.idempotencyKey = ''
    ElMessage.error(errorMessage(error))
  } finally {
    sendingCode.value = false
  }
}

const submitPhone = async () => {
  await phoneFormRef.value?.validate()
  loading.value = true
  try {
    const user = await userStore.phoneLogin(phoneForm)
    if (user.isNewUser) ElMessage.success('注册成功，欢迎使用 Vidferry')
    finishLogin(user)
  } catch (error) {
    if (errorCode(error) !== 'CAPTCHA_REQUIRED') {
      ElMessage.error(errorMessage(error))
      return
    }
    try {
      const captcha = await requestCaptcha()
      const user = await userStore.phoneLogin({ ...phoneForm, ...captcha })
      if (user.isNewUser) ElMessage.success('注册成功，欢迎使用 Vidferry')
      finishLogin(user)
    } catch (captchaError) {
      ElMessage.error(errorMessage(captchaError))
    }
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    const response = await userApi.authPublicConfig()
    phoneLoginEnabled.value = Boolean(response.data.phoneLoginEnabled)
    phoneAutoRegisterEnabled.value = Boolean(response.data.phoneAutoRegisterEnabled)
    captchaAppId.value = response.data.captchaAppId || ''
  } catch {
    phoneLoginEnabled.value = false
    phoneAutoRegisterEnabled.value = false
  }
})

onUnmounted(() => { if (cooldownTimer) window.clearInterval(cooldownTimer) })
</script>

<style scoped lang="scss">
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: var(--vf-page-bg); }
.login-panel { width: min(100%, 380px); padding: 32px; border: 1px solid var(--vf-border); border-radius: 8px; background: var(--vf-surface); box-shadow: var(--vf-shadow-md); }
.brand { display: flex; align-items: center; gap: 14px; margin-bottom: 20px; }
.brand img { width: 44px; height: 44px; }
.brand h1 { margin: 0; color: var(--vf-text-primary); font-size: 24px; letter-spacing: 0; }
.brand p { margin: 3px 0 0; color: var(--vf-text-secondary); font-size: 14px; }
.login-button { width: 100%; margin-top: 14px; }
.code-input { display: grid; grid-template-columns: minmax(0, 1fr) 108px; gap: 8px; width: 100%; }
.phone-hint { margin: 0 0 16px; color: var(--vf-text-secondary); font-size: 13px; }
</style>
