import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'

const MESSAGE_STORAGE_KEY = 'sau_notification_messages'
const HANDLED_STORAGE_KEY = 'sau_notification_handled_keys'
const ACKNOWLEDGED_STORAGE_KEY = 'sau_notification_acknowledged_keys'
const ISSUE_STATE_STORAGE_KEY = 'sau_notification_issue_states'
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
const getPublishConfirmationMessageKey = (job) => `publish-confirmation:${job.id}`
const getSearchFailureMessageKey = (job) => `search-failed:${job.jobId || job.id}`
const getDirectPublishFailureMessageKey = (payload) => `direct-publish-failed:${payload.publishTaskId || payload.tabName || payload.createdAt}`
const LLM_UNAVAILABLE_MESSAGE_KEY = 'llm-unavailable'

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
    actionRoute: { path: '/account-management' },
    actionLabel: '去账号管理',
    severity: 'warning',
    createdAt: previousMessage?.createdAt || now,
    updatedAt: now,
    acknowledged: previousMessage?.acknowledged || false,
    acknowledgedAt: previousMessage?.acknowledgedAt || null,
    state: previousMessage?.state || (previousMessage?.acknowledged ? 'acknowledged' : 'new')
  }
}

const buildWorkflowFailureMessage = (job, acknowledged = false) => {
  const now = Date.now()
  const title = job.title || job.videoTitle || job.videoId || '未命名任务'
  const message = job.errorReason || job.message || '任务执行失败，请在工作流任务中查看具体原因。'
  const errorCode = job.errorCode ? `（${job.errorCode}）` : ''

  return {
    id: getWorkflowFailureMessageKey(job),
    key: getWorkflowFailureMessageKey(job),
    type: 'workflow-failed',
    title: '工作流任务失败',
    content: `${title} 执行失败${errorCode}：${message}`,
    jobId: job.id,
    videoId: job.videoId,
    actionRoute: { path: '/youtube-research', query: { focusJob: job.id, focusAction: 'error' } },
    actionLabel: '查看任务',
    severity: 'danger',
    createdAt: now,
    updatedAt: now,
    acknowledged,
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

const buildPublishUploadPausedMessage = (job, acknowledged = false) => {
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
    severity: 'warning',
    createdAt: now,
    updatedAt: now,
    acknowledged,
    acknowledgedAt: null
  }
}

const buildWorkflowAbnormalMessage = (job, acknowledged = false) => {
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
    actionRoute: { path: '/youtube-research', query: { focusJob: job.id, focusAction: 'error' } },
    actionLabel: '查看任务',
    severity: 'warning',
    createdAt: now,
    updatedAt: now,
    acknowledged,
    acknowledgedAt: null
  }
}

const buildPublishConfirmationMessage = (job, acknowledged = false) => {
  const now = Date.now()
  const title = job.title || job.videoTitle || job.videoId || '未命名视频'
  return {
    id: getPublishConfirmationMessageKey(job),
    key: getPublishConfirmationMessageKey(job),
    type: 'publish-confirmation',
    title: '发布前等待确认',
    content: `${title} 检测到内容风险，视频已处理完成。请确认是否继续发布。`,
    jobId: job.id,
    videoId: job.videoId,
    actionRoute: { path: '/youtube-research', query: { focusJob: job.id, focusAction: 'confirm' } },
    actionLabel: '查看并确认',
    severity: 'warning',
    createdAt: now,
    updatedAt: now,
    acknowledged,
    acknowledgedAt: null
  }
}

const buildSearchFailureMessage = (job, acknowledged = false) => {
  const now = Date.now()
  return {
    id: getSearchFailureMessageKey(job),
    key: getSearchFailureMessageKey(job),
    type: 'search-failed',
    title: '关键词查询失败',
    content: job.message || '关键词查询失败，请检查网络、关键词或数据源后重试。',
    actionRoute: { path: '/youtube-research' },
    actionLabel: '查看查询',
    severity: 'danger',
    createdAt: now,
    updatedAt: now,
    acknowledged,
    acknowledgedAt: null
  }
}

const buildDirectPublishFailureMessage = (payload, acknowledged = false) => {
  const now = Date.now()
  const failedPlatforms = (payload.failedPlatforms || []).filter(Boolean).join('、')
  return {
    id: getDirectPublishFailureMessageKey(payload),
    key: getDirectPublishFailureMessageKey(payload),
    type: 'direct-publish-failed',
    title: '发布未完成',
    content: `${payload.title || '当前视频'}${failedPlatforms ? ` 在 ${failedPlatforms}` : ''} 发布失败：${payload.reason || '请查看发布中心的结果后重试。'}`,
    actionRoute: { path: '/publish-center' },
    actionLabel: '查看发布结果',
    severity: 'danger',
    createdAt: now,
    updatedAt: now,
    acknowledged,
    acknowledgedAt: null
  }
}

const buildLlmUnavailableMessage = (llm, acknowledged = false) => {
  const now = Date.now()
  const missingText = Array.isArray(llm?.missing) && llm.missing.length ? ` 缺失：${llm.missing.join('、')}` : ''
  return {
    id: LLM_UNAVAILABLE_MESSAGE_KEY,
    key: LLM_UNAVAILABLE_MESSAGE_KEY,
    type: 'llm-unavailable',
    title: 'AI 功能不可用',
    content: `${llm?.message || 'LLM 不可用，请检查配置并重启后端。'}${missingText}`,
    actionType: 'copy',
    actionLabel: '复制诊断',
    severity: 'danger',
    createdAt: now,
    updatedAt: now,
    acknowledged,
    acknowledgedAt: null
  }
}

export const useNotificationStore = defineStore('notification', () => {
  const messages = ref(readStorage(MESSAGE_STORAGE_KEY, []))
  const handledKeys = ref(readStorage(HANDLED_STORAGE_KEY, []))
  const acknowledgedKeys = ref([...new Set([
    ...readStorage(ACKNOWLEDGED_STORAGE_KEY, []),
    ...messages.value.filter(message => message.acknowledged).map(message => message.key),
  ])])
  const issueStates = ref({
    ...Object.fromEntries(acknowledgedKeys.value.map(key => [key, { state: 'acknowledged' }])),
    ...Object.fromEntries(handledKeys.value.map(key => [key, { state: 'dismissed' }])),
    ...readStorage(ISSUE_STATE_STORAGE_KEY, {})
  })

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
    writeStorage(ACKNOWLEDGED_STORAGE_KEY, acknowledgedKeys.value)
    writeStorage(ISSUE_STATE_STORAGE_KEY, issueStates.value)
  }

  const addActionMessage = (message, { popup = true, duration = 6000 } = {}) => {
    if (!message?.key || issueStates.value[message.key]?.state === 'dismissed') return false

    const index = messages.value.findIndex(item => item.key === message.key)
    const existing = index >= 0 ? messages.value[index] : null
    const state = issueStates.value[message.key]?.state || existing?.state || (existing?.acknowledged || acknowledgedKeys.value.includes(message.key) ? 'acknowledged' : 'new')
    const nextMessage = {
      ...message,
      createdAt: existing?.createdAt || message.createdAt || Date.now(),
      updatedAt: Date.now(),
      acknowledged: state === 'acknowledged',
      acknowledgedAt: existing?.acknowledgedAt || null,
      state,
    }
    if (existing) {
      messages.value[index] = nextMessage
      issueStates.value[message.key] = { state, updatedAt: nextMessage.updatedAt }
      persist()
      return false
    }

    messages.value.unshift(nextMessage)
    issueStates.value[message.key] = { state, updatedAt: nextMessage.updatedAt }
    persist()
    if (popup) {
      ElNotification({
        title: nextMessage.title,
        message: nextMessage.content,
        type: nextMessage.severity === 'danger' ? 'error' : 'warning',
        position: 'top-right',
        duration,
      })
    }
    return true
  }

  const removeMessagesByKeys = (keys) => {
    const keySet = new Set(keys)
    if (keySet.size === 0) return
    messages.value = messages.value.filter(message => !keySet.has(message.key))
    handledKeys.value = handledKeys.value.filter(key => !keySet.has(key))
    acknowledgedKeys.value = acknowledgedKeys.value.filter(key => !keySet.has(key))
    keySet.forEach(key => delete issueStates.value[key])
    persist()
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
    acknowledgedKeys.value = acknowledgedKeys.value.filter(key => !key.startsWith('account-abnormal:') || abnormalKeys.has(key))
    Object.keys(issueStates.value)
      .filter(key => key.startsWith('account-abnormal:') && !abnormalKeys.has(key))
      .forEach(key => delete issueStates.value[key])

    const accountMessages = abnormalAccounts
      .filter(account => !handledKeys.value.includes(getAccountMessageKey(account)))
      .map(account => buildAccountMessage(account, {
        ...previousMessages.get(getAccountMessageKey(account)),
        acknowledged: acknowledgedKeys.value.includes(getAccountMessageKey(account)),
      }))
    const otherMessages = messages.value.filter(message => message.type !== 'account-abnormal')

    messages.value = [...otherMessages, ...accountMessages]

    persist()
    maybeShowAccountPopup()
  }

  const addWorkflowFailureMessage = (job, options) => {
    if (!job?.id) return
    const key = getWorkflowFailureMessageKey(job)
    addActionMessage(buildWorkflowFailureMessage(job, acknowledgedKeys.value.includes(key)), options)
  }

  const addPublishUploadPausedMessage = (job, options) => {
    if (!job?.id || !isPublishUploadPausedJob(job)) return false
    const key = getPublishUploadPausedMessageKey(job)
    addActionMessage(buildPublishUploadPausedMessage(job, acknowledgedKeys.value.includes(key)), { duration: 8000, ...options })
    return true
  }

  const addWorkflowAbnormalMessage = (job, options) => {
    if (!job?.id) return
    const key = getWorkflowAbnormalMessageKey(job)
    addActionMessage(buildWorkflowAbnormalMessage(job, acknowledgedKeys.value.includes(key)), { duration: 7000, ...options })
  }

  const syncPublishConfirmationMessages = (jobs = []) => {
    const pendingJobs = jobs.filter(job => job?.status === 'waiting_confirmation' && job.publishConfirmationRequired)
    const pendingKeys = new Set(pendingJobs.map(getPublishConfirmationMessageKey))
    const staleKeys = Object.keys(issueStates.value)
      .filter(key => key.startsWith('publish-confirmation:') && !pendingKeys.has(key))
    removeMessagesByKeys(staleKeys)
    pendingJobs.forEach(job => {
      const key = getPublishConfirmationMessageKey(job)
      addActionMessage(buildPublishConfirmationMessage(job, acknowledgedKeys.value.includes(key)), { popup: false })
    })
  }

  const syncWorkflowActionMessages = (jobs = []) => {
    jobs.forEach(job => {
      if (job?.status === 'failed') {
        const handledAsUploadPaused = addPublishUploadPausedMessage(job, { popup: false })
        if (!handledAsUploadPaused) addWorkflowFailureMessage(job, { popup: false })
      }
      if (job?.status === 'abnormal') addWorkflowAbnormalMessage(job, { popup: false })
    })
    syncPublishConfirmationMessages(jobs)
  }

  const syncLlmUnavailableMessage = (llm) => {
    if (!llm || llm.ready) {
      removeMessagesByKeys([LLM_UNAVAILABLE_MESSAGE_KEY])
      return
    }
    addActionMessage(buildLlmUnavailableMessage(llm, acknowledgedKeys.value.includes(LLM_UNAVAILABLE_MESSAGE_KEY)), { duration: 10000 })
  }

  const addSearchFailureMessage = (job) => {
    if (!job || job.status !== 'failed') return
    const key = getSearchFailureMessageKey(job)
    addActionMessage(buildSearchFailureMessage(job, acknowledgedKeys.value.includes(key)))
  }

  const addDirectPublishFailureMessage = (payload) => {
    if (!payload) return
    const key = getDirectPublishFailureMessageKey(payload)
    addActionMessage(buildDirectPublishFailureMessage(payload, acknowledgedKeys.value.includes(key)))
  }

  const acknowledgeMessage = (id) => {
    const message = messages.value.find(item => item.id === id)
    if (!message) return

    message.acknowledged = true
    message.acknowledgedAt = Date.now()
    message.state = 'acknowledged'
    if (!acknowledgedKeys.value.includes(message.key)) {
      acknowledgedKeys.value.push(message.key)
    }
    issueStates.value[message.key] = { state: 'acknowledged', updatedAt: message.acknowledgedAt }
    persist()
  }

  const resolveMessage = (id) => {
    const message = messages.value.find(item => item.id === id)
    if (!message) return

    if (!handledKeys.value.includes(message.key)) {
      handledKeys.value.push(message.key)
    }
    issueStates.value[message.key] = { state: 'dismissed', updatedAt: Date.now() }

    messages.value = messages.value.filter(item => item.id !== id)
    persist()
  }

  return {
    messages,
    issueStates,
    visibleMessages,
    unreadCount,
    hasUnread,
    syncAccountAbnormalMessages,
    addWorkflowFailureMessage,
    addPublishUploadPausedMessage,
    addWorkflowAbnormalMessage,
    syncPublishConfirmationMessages,
    syncWorkflowActionMessages,
    syncLlmUnavailableMessage,
    addSearchFailureMessage,
    addDirectPublishFailureMessage,
    acknowledgeMessage,
    resolveMessage
  }
})
