import { defineStore } from 'pinia'
import { ref } from 'vue'
import { userApi } from '@/api/user'
import { clearAuthSession, setCsrfToken } from '@/auth/session'

export const useUserStore = defineStore('user', () => {
  const userInfo = ref(null)
  const isLoggedIn = ref(false)
  const initialized = ref(false)

  const setSession = (info, csrfToken) => {
    userInfo.value = info
    isLoggedIn.value = Boolean(info)
    setCsrfToken(csrfToken)
  }

  const restore = async () => {
    if (initialized.value) return isLoggedIn.value
    try {
      const response = await userApi.me()
      setSession(response.data.user, response.data.csrfToken)
    } catch {
      setSession(null, '')
    } finally {
      initialized.value = true
    }
    return isLoggedIn.value
  }

  const login = async credentials => {
    const response = await userApi.login(credentials)
    setSession(response.data.user, response.data.csrfToken)
    initialized.value = true
    return response.data.user
  }

  const phoneLogin = async credentials => {
    const response = await userApi.phoneLogin(credentials)
    setSession(response.data.user, response.data.csrfToken)
    initialized.value = true
    return response.data.user
  }

  const logout = async () => {
    try {
      if (isLoggedIn.value) await userApi.logout()
    } finally {
      userInfo.value = null
      isLoggedIn.value = false
      initialized.value = true
      clearAuthSession()
    }
  }

  return {
    userInfo,
    isLoggedIn,
    initialized,
    isAdmin: () => userInfo.value?.role === 'admin',
    restore,
    login,
    phoneLogin,
    logout
  }
})
