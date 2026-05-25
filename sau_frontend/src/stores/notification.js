import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'

const MESSAGE_STORAGE_KEY = 'sau_notification_messages'
const HANDLED_STORAGE_KEY = 'sau_notification_handled_keys'
const POPUP_STORAGE_KEY = 'sau_account_abnormal_popup_at'
const POPUP_THROTTLE_MS = 3 * 60 * 1000

const isBrowser = typeof window !== 'undefined'

const readStorage = (key, fallback) => {
  if (!isBrowser) return fallback

  try {
    const value = window.localStorage.getItem(key)
    return value ? JSON.parse(value) : fallback
  } catch (error) {
    console.warn(`读取本地消息缓存失败: ${key}`, error)
    return fallback
  }
}

const writeStorage = (key, value) => {
  if (!isBrowser) return

  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch (error) {
    console.warn(`写入本地消息缓存失败: ${key}`, error)
  }
}

const getAccountMessageKey = (account) => `account-abnormal:${account.id}`

const buildAccountMessage = (account, previousMessage) => {
  const now = Date.now()

  return {
    id: getAccountMessageKey(account),
    key: getAccountMessageKey(account),
    type: 'account-abnormal',
    title: '账号状态异常',
    content: `${account.platform}-${account.name} 当前状态异常，请在账号管理中手动重新连接。`,
    accountId: account.id,
    accountName: account.name,
    platform: account.platform,
    createdAt: previousMessage?.createdAt || now,
    updatedAt: now,
    acknowledged: previousMessage?.acknowledged || false,
    acknowledgedAt: previousMessage?.acknowledgedAt || null
  }
}

export const useNotificationStore = defineStore('notification', () => {
  const messages = ref(readStorage(MESSAGE_STORAGE_KEY, []))
  const handledKeys = ref(readStorage(HANDLED_STORAGE_KEY, []))

  const visibleMessages = computed(() => {
    return [...messages.value].sort((a, b) => b.updatedAt - a.updatedAt)
  })

  const unreadCount = computed(() => {
    return messages.value.filter(message => !message.acknowledged).length
  })

  const hasUnread = computed(() => unreadCount.value > 0)

  const persist = () => {
    writeStorage(MESSAGE_STORAGE_KEY, messages.value)
    writeStorage(HANDLED_STORAGE_KEY, handledKeys.value)
  }

  const maybeShowAccountPopup = () => {
    if (!isBrowser || unreadCount.value === 0) return

    const lastPopupAt = Number(window.localStorage.getItem(POPUP_STORAGE_KEY) || 0)
    const now = Date.now()
    if (now - lastPopupAt < POPUP_THROTTLE_MS) return

    window.localStorage.setItem(POPUP_STORAGE_KEY, String(now))

    const abnormalMessages = messages.value.filter(message => !message.acknowledged)
    const names = abnormalMessages
      .slice(0, 5)
      .map(message => `${message.platform}-${message.accountName}`)
      .join('、')
    const suffix = abnormalMessages.length > 5 ? ` 等 ${abnormalMessages.length} 个账号` : ''

    ElNotification({
      title: '账号状态异常',
      message: `${names}${suffix} 已异常，请在右上角消息中查看。`,
      type: 'warning',
      position: 'top-right',
      duration: 6000
    })
  }

  const syncAccountAbnormalMessages = (accounts = []) => {
    const abnormalAccounts = accounts.filter(account => account.status === '异常')
    const abnormalKeys = new Set(abnormalAccounts.map(getAccountMessageKey))
    const previousMessages = new Map(messages.value.map(message => [message.key, message]))

    handledKeys.value = handledKeys.value.filter(key => abnormalKeys.has(key))

    messages.value = abnormalAccounts
      .filter(account => !handledKeys.value.includes(getAccountMessageKey(account)))
      .map(account => buildAccountMessage(account, previousMessages.get(getAccountMessageKey(account))))

    persist()
    maybeShowAccountPopup()
  }

  const acknowledgeMessage = (id) => {
    const message = messages.value.find(item => item.id === id)
    if (!message) return

    message.acknowledged = true
    message.acknowledgedAt = Date.now()
    persist()
  }

  const resolveMessage = (id) => {
    const message = messages.value.find(item => item.id === id)
    if (!message) return

    if (!handledKeys.value.includes(message.key)) {
      handledKeys.value.push(message.key)
    }

    messages.value = messages.value.filter(item => item.id !== id)
    persist()
  }

  return {
    messages,
    visibleMessages,
    unreadCount,
    hasUnread,
    syncAccountAbnormalMessages,
    acknowledgeMessage,
    resolveMessage
  }
})
