import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'
import { notificationApi } from '@/api/notification'

const shownLlmCapabilityWarnings = new Set()

export const useNotificationStore = defineStore('notification', () => {
  const messages = ref([])
  const historyMessages = ref([])
  const summary = ref({ activeCount: 0, unreadCount: 0, badgeCount: 0 })
  const loading = ref(false)
  const historyLoaded = ref(false)

  const activeMessages = computed(() => messages.value.filter(message => message.status === 'active'))
  const acknowledgedMessages = computed(() => messages.value.filter(message => message.status === 'acknowledged'))
  const visibleMessages = computed(() => [...activeMessages.value, ...acknowledgedMessages.value])
  const unreadCount = computed(() => Number(summary.value.unreadCount || 0))
  const badgeCount = computed(() => Number(summary.value.badgeCount || 0))
  const hasUnread = computed(() => unreadCount.value > 0)

  const refresh = async ({ includeHistory = false } = {}) => {
    if (loading.value) return
    loading.value = true
    try {
      const active = await notificationApi.list({ state: 'active', page: 1, pageSize: 50 })
      messages.value = active?.data?.items || []
      summary.value = active?.data?.summary || summary.value
      messages.value
        .filter(message => message.type === 'llm-thinking-enabled' && !message.acknowledgedAt)
        .forEach(message => {
          if (shownLlmCapabilityWarnings.has(message.aggregateKey)) return
          shownLlmCapabilityWarnings.add(message.aggregateKey)
          ElNotification({ title: message.title, message: message.content, type: 'warning', duration: 3000, position: 'top-right' })
        })
      if (includeHistory) {
        const history = await notificationApi.list({ state: 'history', page: 1, pageSize: 50 })
        historyMessages.value = history?.data?.items || []
        historyLoaded.value = true
      }
    } finally {
      loading.value = false
    }
  }

  const refreshSummary = async () => {
    const response = await notificationApi.summary()
    summary.value = response?.data || summary.value
  }

  const updateState = async (id, state) => {
    await notificationApi.update(id, { state })
    await refresh({ includeHistory: historyLoaded.value })
  }

  const acknowledgeMessage = (id) => updateState(id, 'acknowledged')
  const resolveMessage = (id) => updateState(id, 'resolved')

  // 兼容现有页面调用：通知来源已迁移到后端对账，前端仅请求最新投影。
  const refreshFromSource = () => refresh()

  const addDirectPublishFailureMessage = async (payload) => {
    await notificationApi.createDirectPublishFailure(payload)
    await refresh()
  }

  return {
    messages,
    historyMessages,
    summary,
    loading,
    historyLoaded,
    activeMessages,
    acknowledgedMessages,
    visibleMessages,
    unreadCount,
    badgeCount,
    hasUnread,
    refresh,
    refreshSummary,
    acknowledgeMessage,
    resolveMessage,
    syncAccountAbnormalMessages: refreshFromSource,
    syncWorkflowActionMessages: refreshFromSource,
    syncPublishConfirmationMessages: refreshFromSource,
    syncLlmUnavailableMessage: refreshFromSource,
    syncRuntimeConfigMessages: refreshFromSource,
    addWorkflowFailureMessage: refreshFromSource,
    addPublishUploadPausedMessage: refreshFromSource,
    addWorkflowAbnormalMessage: refreshFromSource,
    addSearchFailureMessage: refreshFromSource,
    addDirectPublishFailureMessage,
  }
})
