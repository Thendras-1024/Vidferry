import { computed, nextTick, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agentApi } from '@/api/agent'
import { mergeAndSortAgentSessions } from '@/utils/agentSessions'

const AGENT_MESSAGE_PAGE_SIZE = 12
const AGENT_SESSION_META_KEY = 'vidferry:agent-session-meta'
const PAGE_TITLES = {
  '/': 'Agent 工作台',
  '/youtube-research': '视频采集与处理',
  '/workflow-settings': '处理配置',
  '/account-management': '账号连接',
  '/user-management': '用户与安全',
  '/material-management': '视频素材',
  '/publish-center': '发布中心',
  '/scheduled-publish-tasks': '自动化任务',
  '/workflow-statistics': '处理统计',
  '/about': '关于'
}

const readSessionMeta = () => {
  try {
    return JSON.parse(localStorage.getItem(AGENT_SESSION_META_KEY) || '{}')
  } catch {
    return {}
  }
}

export function useAgentWorkspace({ route, router }) {
  const agentDrawerVisible = ref(false)
  const agentLoading = ref(false)
  const agentInput = ref('')
  const agentSessionId = ref(localStorage.getItem('vidferry:agent-session-id') || '')
  const agentMessages = ref([])
  const agentMessagesRef = ref(null)
  const agentOlderMessagesLoading = ref(false)
  const agentHasOlderMessages = ref(false)
  const agentMessagesBeforeId = ref(null)
  const agentSessionRestoreLoading = ref(false)
  const agentInputRef = ref(null)
  const agentRetryContext = ref(null)
  const agentVideoContext = ref(null)
  const agentIncludeVideoContext = ref(false)
  const agentHistoryVisible = ref(false)
  const agentHistoryLoading = ref(false)
  const agentHistory = ref([])
  const agentHistoryRange = ref([])
  const agentHistorySource = ref('')
  const agentHistoryQuery = ref('')
  const agentFiltersVisible = ref(false)
  const agentCurrentSession = ref(null)
  const agentContextStats = ref(null)
  const agentContextDetailsVisible = ref(false)
  const agentCompaction = ref({ state: 'idle', message: '', startedAt: 0, durationMs: 0 })
  const agentCompactionTick = ref(Date.now())
  const agentSessionMeta = ref(readSessionMeta())

  const agentSessionSource = computed(() => agentCurrentSession.value?.source || 'web')
  const agentSessionSourceLabel = computed(() => agentSessionSource.value === 'feishu' ? '手机端' : '本地 Agent')
  const agentSessionReadonly = computed(() => agentSessionSource.value === 'feishu' || Boolean(agentSessionId.value && !agentCurrentSession.value))
  const agentQuickQuestions = [
    '完整流程现在有哪些步骤？',
    '现在待处理的视频有哪些？',
    '已处理但还没发布的视频有哪些？',
    '已发布的视频有哪些？',
    '最近失败的任务是什么原因？',
    '账号状态怎么样？'
  ]
  const workspaceTitle = computed(() => PAGE_TITLES[route.path] || route.meta?.title || route.name || 'Vidferry')
  const currentAgentTitle = computed(() => (
    agentCurrentSession.value?.title || agentSessionMeta.value[agentSessionId.value]?.title || (agentSessionId.value ? '当前对话' : '新对话')
  ))
  const sortedAgentHistory = computed(() => mergeAndSortAgentSessions(agentHistory.value, agentSessionMeta.value))
  const agentContextLabel = computed(() => PAGE_TITLES[route.path] || route.meta?.title || route.name || route.path)
  const agentContextUsageLabel = computed(() => {
    const stats = agentContextStats.value
    if (!stats) return '上下文待加载'
    return `上下文 ${formatTokenCount(stats.estimatedInputTokens)} / ${formatTokenCount(stats.contextWindowTokens)}`
  })
  const agentCompactionElapsedSeconds = computed(() => {
    const value = agentCompaction.value
    const elapsed = value.state === 'running' ? Date.now() - value.startedAt : value.durationMs
    void agentCompactionTick.value
    return Math.max(0, Math.ceil(elapsed / 1000))
  })

  let nextMessageId = 1
  let restoredSessionId = ''
  let restoringSessionId = ''
  let restoreSequence = 0
  let agentCompactionTimer = null

  const formatTokenCount = value => {
    const amount = Number(value || 0)
    return amount >= 1000 ? `${(amount / 1000).toFixed(amount >= 100000 ? 0 : 1)}k` : String(amount)
  }

  const setAgentCompaction = payload => {
    const running = payload?.state === 'running'
    agentCompaction.value = {
      state: payload?.state || 'idle',
      message: payload?.message || '',
      startedAt: running ? Date.now() : agentCompaction.value.startedAt,
      durationMs: Number(payload?.durationMs || (running ? 0 : agentCompaction.value.durationMs) || 0)
    }
    if (running && !agentCompactionTimer) {
      agentCompactionTimer = window.setInterval(() => { agentCompactionTick.value = Date.now() }, 250)
    }
    if (!running && agentCompactionTimer) {
      window.clearInterval(agentCompactionTimer)
      agentCompactionTimer = null
    }
  }

  const refreshAgentSession = async sessionId => {
    if (!sessionId) return
    const response = await agentApi.getSession(sessionId)
    if (sessionId !== agentSessionId.value || !response?.data) return
    agentCurrentSession.value = response.data
    agentContextStats.value = response.data.contextStats || null
  }

  const currentAgentContext = computed(() => ({
    path: route.path,
    query: route.query,
    pageTitle: PAGE_TITLES[route.path] || route.meta?.title || route.name || route.path
  }))

  const scrollAgentMessages = async () => {
    await nextTick()
    if (agentMessagesRef.value) agentMessagesRef.value.scrollTop = agentMessagesRef.value.scrollHeight
  }

  const mapAgentHistoryMessage = message => ({
    id: `history-${message.id}`,
    historyId: Number(message.id),
    role: message.role,
    content: message.content || '',
    context: message.context || {},
    cards: message.context?.cards || [],
    actions: message.context?.actions || []
  })

  const pushAgentMessage = (role, content, options = {}) => {
    const message = { id: nextMessageId++, role, content: String(content || ''), ...options }
    agentMessages.value.push(message)
    void scrollAgentMessages()
    return agentMessages.value[agentMessages.value.length - 1]
  }

  const saveAgentSessionId = sessionId => {
    if (!sessionId) return
    agentSessionId.value = sessionId
    localStorage.setItem('vidferry:agent-session-id', sessionId)
  }

  const restoreAgentMessages = async ({ allowExternal = false } = {}) => {
    const sessionId = agentSessionId.value
    if (!sessionId || restoredSessionId === sessionId || agentLoading.value || (agentSessionRestoreLoading.value && restoringSessionId === sessionId)) return
    const sequence = ++restoreSequence
    restoringSessionId = sessionId
    agentSessionRestoreLoading.value = true
    try {
      const [messagesResponse, sessionResponse] = await Promise.all([
        agentApi.getMessages(sessionId, AGENT_MESSAGE_PAGE_SIZE),
        agentApi.getSession(sessionId)
      ])
      if (sequence !== restoreSequence || sessionId !== agentSessionId.value) return
      if (!allowExternal && sessionResponse?.data?.source === 'feishu') {
        newAgentConversation()
        return
      }
      agentCurrentSession.value = sessionResponse?.data || agentCurrentSession.value
      agentContextStats.value = sessionResponse?.data?.contextStats || null
      agentMessages.value = (messagesResponse?.data?.items || []).map(mapAgentHistoryMessage)
      agentHasOlderMessages.value = Boolean(messagesResponse?.data?.hasMore)
      agentMessagesBeforeId.value = messagesResponse?.data?.nextBeforeId || null
      restoredSessionId = sessionId
      await scrollAgentMessages()
    } catch (error) {
      if (sequence === restoreSequence) console.warn('恢复 Agent 会话失败:', error)
    } finally {
      if (sequence === restoreSequence) {
        agentSessionRestoreLoading.value = false
        restoringSessionId = ''
      }
    }
  }

  const loadOlderAgentMessages = async () => {
    const sessionId = agentSessionId.value
    const beforeId = agentMessagesBeforeId.value
    const messageContainer = agentMessagesRef.value
    if (!sessionId || !beforeId || !messageContainer || !agentHasOlderMessages.value || agentOlderMessagesLoading.value || agentLoading.value) return
    const previousHeight = messageContainer.scrollHeight
    agentOlderMessagesLoading.value = true
    try {
      const response = await agentApi.getMessages(sessionId, AGENT_MESSAGE_PAGE_SIZE, beforeId)
      if (sessionId !== agentSessionId.value) return
      const existingIds = new Set(agentMessages.value.map(message => message.historyId).filter(Number.isFinite))
      const olderMessages = (response?.data?.items || [])
        .map(mapAgentHistoryMessage)
        .filter(message => !existingIds.has(message.historyId))
      agentMessages.value = [...olderMessages, ...agentMessages.value]
      agentHasOlderMessages.value = Boolean(response?.data?.hasMore)
      agentMessagesBeforeId.value = response?.data?.nextBeforeId || null
    } catch (error) {
      console.warn('加载更早 Agent 消息失败:', error)
      ElMessage.error(error?.message || '加载更早消息失败')
    } finally {
      agentOlderMessagesLoading.value = false
      await nextTick()
      if (sessionId === agentSessionId.value && agentMessagesRef.value) {
        agentMessagesRef.value.scrollTop = Math.max(0, agentMessagesRef.value.scrollHeight - previousHeight)
      }
    }
  }

  const handleAgentMessagesScroll = event => {
    if (event.currentTarget.scrollTop <= 8) void loadOlderAgentMessages()
  }

  const newAgentConversation = () => {
    agentSessionId.value = ''
    restoreSequence += 1
    agentSessionRestoreLoading.value = false
    restoringSessionId = ''
    restoredSessionId = ''
    agentMessages.value = []
    agentOlderMessagesLoading.value = false
    agentHasOlderMessages.value = false
    agentMessagesBeforeId.value = null
    agentRetryContext.value = null
    agentVideoContext.value = null
    agentIncludeVideoContext.value = false
    agentCurrentSession.value = null
    agentContextStats.value = null
    agentContextDetailsVisible.value = false
    setAgentCompaction({ state: 'idle' })
    localStorage.removeItem('vidferry:agent-session-id')
  }

  const startAgentConversation = async () => {
    newAgentConversation()
    if (route.path !== '/') await router.push('/')
    await nextTick()
    agentInputRef.value?.focus()
  }

  const persistAgentSessionMeta = () => localStorage.setItem(AGENT_SESSION_META_KEY, JSON.stringify(agentSessionMeta.value))
  const updateAgentSessionMeta = (sessionId, changes) => {
    agentSessionMeta.value = { ...agentSessionMeta.value, [sessionId]: { ...agentSessionMeta.value[sessionId], ...changes } }
    persistAgentSessionMeta()
  }

  const sendAgentMessage = async (content = '', extraContext = {}) => {
    const message = String(content || agentInput.value || '').trim()
    if (!message || agentLoading.value || agentSessionReadonly.value) return
    if (route.path !== '/') await router.push('/')
    agentInput.value = ''
    const context = { ...currentAgentContext.value, ...(content ? {} : agentRetryContext.value || {}), ...extraContext }
    if (agentVideoContext.value && agentIncludeVideoContext.value) context.videoContext = agentVideoContext.value
    else delete context.videoContext
    agentRetryContext.value = null
    pushAgentMessage('user', message, { context })
    const responseMessage = pushAgentMessage('assistant', '', { thinking: true, statusMessage: '正在理解你的问题', retryMessage: message })
    agentLoading.value = true
    let hasResult = false
    try {
      await agentApi.chatStream({ message, sessionId: agentSessionId.value, context }, (type, payload) => {
        if (type === 'status') responseMessage.statusMessage = payload.message || '正在思考'
        if (type === 'context_compaction') setAgentCompaction(payload)
        if (type === 'delta') {
          responseMessage.thinking = false
          responseMessage.content += payload.content || ''
        }
        if (type === 'result') {
          hasResult = true
          responseMessage.thinking = false
          responseMessage.error = false
          responseMessage.content = payload.answer || responseMessage.content || '我暂时没有查到结果。'
          responseMessage.cards = payload.cards || []
          responseMessage.actions = payload.actions || []
          saveAgentSessionId(payload.sessionId)
          agentCurrentSession.value = { id: payload.sessionId, source: 'web' }
        }
        if (type === 'error') throw new Error(payload.message || 'Agent 暂时不可用')
        void scrollAgentMessages()
      })
      if (!hasResult) throw new Error('Agent 响应中断，请重试。')
    } catch (error) {
      responseMessage.thinking = false
      responseMessage.error = true
      responseMessage.content = error.message || 'Agent 暂时不可用，请稍后再试。'
      ElMessage.error(error.message || 'Agent 暂时不可用')
    } finally {
      agentLoading.value = false
      void loadAgentHistory()
      void refreshAgentSession(agentSessionId.value)
      window.setTimeout(() => { void refreshAgentSession(agentSessionId.value) }, 1200)
    }
  }

  const showAgentMessageTools = message => Boolean(message?.content && (message.role === 'user' || (message.role === 'assistant' && !message.thinking && !message.error)))
  const copyAgentMessage = async message => {
    try {
      await navigator.clipboard.writeText(message.content)
      ElMessage.success('已复制')
    } catch {
      ElMessage.error('复制失败')
    }
  }

  const loadAgentHistory = async () => {
    agentHistoryLoading.value = true
    try {
      const [from = '', to = ''] = agentHistoryRange.value || []
      const response = await agentApi.getSessions({ page: 1, pageSize: 50, from, to, source: agentHistorySource.value, q: agentHistoryQuery.value.trim() })
      agentHistory.value = response?.data?.items || []
    } catch (error) {
      console.warn('读取 Agent 历史会话失败:', error)
    } finally {
      agentHistoryLoading.value = false
    }
  }

  const openAgentHistory = async () => {
    agentHistoryVisible.value = true
    await loadAgentHistory()
  }
  const openAgentWorkbench = async () => Promise.all([restoreAgentMessages(), loadAgentHistory()])
  const selectAgentSession = async session => {
    if (!session?.id || agentLoading.value) return
    saveAgentSessionId(session.id)
    agentCurrentSession.value = session
    agentContextStats.value = session.contextStats || null
    restoredSessionId = ''
    agentMessages.value = []
    agentOlderMessagesLoading.value = false
    agentHasOlderMessages.value = false
    agentMessagesBeforeId.value = null
    agentRetryContext.value = null
    agentVideoContext.value = null
    agentIncludeVideoContext.value = false
    if (route.path !== '/') await router.push('/')
    await restoreAgentMessages({ allowExternal: true })
  }

  const compactCurrentAgentSession = async () => {
    const sessionId = agentSessionId.value
    if (!sessionId || agentLoading.value || agentSessionReadonly.value) return
    try {
      await agentApi.compactSessionStream(sessionId, (type, payload) => {
        if (type === 'context_compaction') setAgentCompaction(payload)
        if (type === 'error') throw new Error(payload.message || '压缩失败')
      })
      await refreshAgentSession(sessionId)
    } catch (error) {
      setAgentCompaction({ state: 'failed', message: error.message || '压缩失败' })
      ElMessage.error(error.message || '压缩会话失败')
    }
  }

  const removeAgentSession = async session => {
    if (!session?.id || agentLoading.value) return
    try {
      await ElMessageBox.confirm(`删除“${session.title || session.preview || '该会话'}”后，消息和会话摘要将无法恢复。`, '确认删除会话', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' })
      await agentApi.deleteSession(session.id)
      if (session.id === agentSessionId.value) newAgentConversation()
      await loadAgentHistory()
      ElMessage.success('会话已删除')
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') ElMessage.error(error?.message || '删除会话失败')
    }
  }

  const handleAgentSessionCommand = async (command, session) => {
    if (!session?.id) return
    if (command === 'pin' || command === 'unpin') {
      updateAgentSessionMeta(session.id, { isPinned: command === 'pin', pinnedAt: command === 'pin' ? new Date().toISOString() : null })
      return
    }
    if (command === 'rename') {
      try {
        const { value } = await ElMessageBox.prompt('输入会话名称', '重命名会话', { inputValue: session.title || session.preview || '', inputPattern: /\S/, inputErrorMessage: '会话名称不能为空', inputValidator: value => String(value || '').trim().length <= 40 || '会话名称不能超过 40 个字符', confirmButtonText: '保存', cancelButtonText: '取消' })
        const title = String(value || '').trim()
        updateAgentSessionMeta(session.id, { title })
        if (agentCurrentSession.value?.id === session.id) agentCurrentSession.value = { ...agentCurrentSession.value, title }
      } catch (error) {
        if (error !== 'cancel' && error !== 'close') ElMessage.error('重命名会话失败')
      }
      return
    }
    if (command === 'delete') await removeAgentSession(session)
  }

  const prepareAgentRetry = async message => {
    if (agentLoading.value || !message?.content) return
    agentInput.value = message.content
    agentRetryContext.value = message.context || {}
    await nextTick()
    agentInputRef.value?.focus()
  }
  const handleAgentInputKeydown = event => {
    if (event.key !== 'Enter' || event.isComposing || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    void sendAgentMessage()
  }
  const confirmAgentAction = async action => {
    if (action?.type === 'ask' && action.message) {
      await sendAgentMessage(action.message, { selectedAgentAction: action.label || '' })
      return
    }
    if (action?.type !== 'navigate' || !['/youtube-research', '/account-management'].includes(action.path)) return
    try {
      await ElMessageBox.confirm(`将打开“${action.label}”。`, '确认查看', { confirmButtonText: '打开', cancelButtonText: '取消', type: 'info' })
      await router.push({ path: action.path, query: action.query || {} })
      agentDrawerVisible.value = false
    } catch (_) {
      // 用户取消导航不需要提示。
    }
  }
  const handleAskAgentEvent = async event => {
    const detail = event?.detail || {}
    agentVideoContext.value = detail.videoContext || null
    agentIncludeVideoContext.value = Boolean(agentVideoContext.value)
    if (route.path !== '/') await router.push('/')
    await nextTick()
    if (detail.message) {
      await sendAgentMessage(detail.message, { selectedAgentAction: detail.selectedAgentAction || '' })
      return
    }
    agentInputRef.value?.focus()
  }

  return {
    agentDrawerVisible, agentLoading, agentInput, agentSessionId, agentMessages, agentMessagesRef,
    agentOlderMessagesLoading, agentHasOlderMessages, agentMessagesBeforeId, agentSessionRestoreLoading,
    agentInputRef, agentRetryContext, agentVideoContext, agentIncludeVideoContext, agentHistoryVisible,
    agentHistoryLoading, agentHistory, agentHistoryRange, agentHistorySource, agentHistoryQuery,
    agentFiltersVisible, agentCurrentSession, agentContextStats, agentContextDetailsVisible, agentCompaction, agentContextUsageLabel, agentCompactionElapsedSeconds, agentSessionSource, agentSessionSourceLabel, agentSessionReadonly,
    agentQuickQuestions, workspaceTitle, currentAgentTitle, sortedAgentHistory, agentContextLabel, currentAgentContext,
    scrollAgentMessages, loadOlderAgentMessages, handleAgentMessagesScroll, newAgentConversation, startAgentConversation,
    sendAgentMessage, showAgentMessageTools, copyAgentMessage, loadAgentHistory, openAgentHistory, openAgentWorkbench,
    selectAgentSession, compactCurrentAgentSession, handleAgentSessionCommand, removeAgentSession, prepareAgentRetry, handleAgentInputKeydown,
    confirmAgentAction, handleAskAgentEvent
  }
}
