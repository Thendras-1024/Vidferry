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
const getWorkflowFailureMessageKey = (job) => `workflow-failed:${job.id}`
const getWorkflowAbnormalMessageKey = (job) => `workflow-abnormal:${job.id}`
const getPublishUploadPausedMessageKey = (job) => `publish-upload-paused:${job.id}`

const platformResolveUrls = {
  抖音: 'https://creator.douyin.com/creator-micro/content/upload',
  B站: 'https://member.bilibili.com/platform/upload/video/frame',
  bilibili: 'https://member.bilibili.com/platform/upload/video/frame'
}

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

const buildWorkflowFailureMessage = (job) => {
  const now = Date.now()
  const title = job.title || job.videoTitle || job.videoId || '未命名任务'
  const message = job.message || '任务执行失败，请在工作流任务中查看具体原因。'

  return {
    id: getWorkflowFailureMessageKey(job),
    key: getWorkflowFailureMessageKey(job),
    type: 'workflow-failed',
    title: '工作流任务失败',
    content: `${title} 执行失败：${message}`,
    jobId: job.id,
    videoId: job.videoId,
    createdAt: now,
    updatedAt: now,
    acknowledged: false,
    acknowledgedAt: null
  }
}

const getPublishUploadPausedPlatform = (job) => {
  const message = `${job?.message || ''} ${job?.errorReason || ''} ${job?.publishCommand || ''}`.toLowerCase()
  if (message.includes('douyin') || message.includes('抖音')) return '抖音'
  if (message.includes('bilibili') || message.includes('b站')) return 'B站'
  return job?.publishToDouyin ? '抖音' : '发布平台'
}

const isPublishUploadPausedJob = (job) => {
  const message = `${job?.message || ''} ${job?.errorCode || ''} ${job?.errorReason || ''}`
  return job?.status === 'failed' && (
    message.includes('VF-PUBLISH-UPLOAD-PAUSED') ||
    message.includes('上传已暂停') ||
    message.includes('暂停传输') ||
    message.includes('继续上传')
  )
}

const buildPublishUploadPausedMessage = (job) => {
  const now = Date.now()
  const title = job.title || job.videoTitle || job.videoId || '未命名视频'
  const platform = getPublishUploadPausedPlatform(job)

  return {
    id: getPublishUploadPausedMessageKey(job),
    key: getPublishUploadPausedMessageKey(job),
    type: 'publish-upload-paused',
    title: '视频上传已暂停',
    content: `你有一个视频在${platform}暂停上传了：${title}。可能是在发布过程中手动点击了暂停传输，请进入平台页面恢复上传，或回到发布中心重新发起发布。`,
    jobId: job.id,
    videoId: job.videoId,
    platform,
    actionLabel: '去解决',
    actionUrl: platformResolveUrls[platform] || '',
    createdAt: now,
    updatedAt: now,
    acknowledged: false,
    acknowledgedAt: null
  }
}

const buildWorkflowAbnormalMessage = (job) => {
  const now = Date.now()
  const title = job.title || job.videoTitle || job.videoId || '未命名任务'
  const errorCode = job.errorCode || 'VF-WF-ABNORMAL'
  const errorType = job.errorType || 'WORKFLOW_ABNORMAL'
  const reason = job.errorReason || job.message || '任务被系统标记为异常，请检查后端服务或文件状态。'

  return {
    id: getWorkflowAbnormalMessageKey(job),
    key: getWorkflowAbnormalMessageKey(job),
    type: 'workflow-abnormal',
    title: '工作流任务异常',
    content: `${title} 异常中断：${errorCode} / ${errorType}，${reason}`,
    jobId: job.id,
    videoId: job.videoId,
    errorCode,
    errorType,
    createdAt: now,
    updatedAt: now,
    acknowledged: false,
    acknowledgedAt: null
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
    if (!isBrowser) return

    const abnormalMessages = messages.value.filter(message => message.type === 'account-abnormal' && !message.acknowledged)
    if (abnormalMessages.length === 0) return

    const lastPopupAt = Number(window.localStorage.getItem(POPUP_STORAGE_KEY) || 0)
    const now = Date.now()
    if (now - lastPopupAt < POPUP_THROTTLE_MS) return

    window.localStorage.setItem(POPUP_STORAGE_KEY, String(now))

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

    handledKeys.value = handledKeys.value.filter(key => !key.startsWith('account-abnormal:') || abnormalKeys.has(key))

    const accountMessages = abnormalAccounts
      .filter(account => !handledKeys.value.includes(getAccountMessageKey(account)))
      .map(account => buildAccountMessage(account, previousMessages.get(getAccountMessageKey(account))))
    const otherMessages = messages.value.filter(message => message.type !== 'account-abnormal')

    messages.value = [...otherMessages, ...accountMessages]

    persist()
    maybeShowAccountPopup()
  }

  const addWorkflowFailureMessage = (job) => {
    if (!job?.id) return

    const key = getWorkflowFailureMessageKey(job)
    if (handledKeys.value.includes(key)) return
    if (messages.value.some(message => message.key === key)) return

    const message = buildWorkflowFailureMessage(job)
    messages.value.unshift(message)
    persist()

    ElNotification({
      title: message.title,
      message: message.content,
      type: 'error',
      position: 'top-right',
      duration: 6000
    })
  }

  const addPublishUploadPausedMessage = (job) => {
    if (!job?.id || !isPublishUploadPausedJob(job)) return false

    const key = getPublishUploadPausedMessageKey(job)
    if (handledKeys.value.includes(key)) return true
    if (messages.value.some(message => message.key === key)) return true

    const message = buildPublishUploadPausedMessage(job)
    messages.value.unshift(message)
    persist()

    ElNotification({
      title: message.title,
      message: message.content,
      type: 'warning',
      position: 'top-right',
      duration: 8000
    })

    return true
  }

  const addWorkflowAbnormalMessage = (job) => {
    if (!job?.id) return

    const key = getWorkflowAbnormalMessageKey(job)
    if (handledKeys.value.includes(key)) return
    if (messages.value.some(message => message.key === key)) return

    const message = buildWorkflowAbnormalMessage(job)
    messages.value.unshift(message)
    persist()

    ElNotification({
      title: message.title,
      message: message.content,
      type: 'warning',
      position: 'top-right',
      duration: 7000
    })
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
    addWorkflowFailureMessage,
    addPublishUploadPausedMessage,
    addWorkflowAbnormalMessage,
    acknowledgeMessage,
    resolveMessage
  }
})
