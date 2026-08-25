<template>
  <router-view v-if="route.meta.public" />
  <div v-else id="app">
    <el-container>
      <el-aside class="workspace-aside" :width="isCollapse ? '72px' : '292px'">
        <div class="sidebar workspace-sidebar">
          <div class="logo">
            <img v-show="isCollapse" src="/vidferry-icon.svg" alt="Vidferry" class="logo-img">
            <div v-show="!isCollapse" class="logo-copy">
              <strong>Vidferry</strong>
              <span>视频采集与发布工作台</span>
            </div>
          </div>
          <section class="workspace-nav" aria-label="业务导航">
            <el-button class="new-conversation-button" :circle="isCollapse" @click="startAgentConversation">
              <el-icon><Plus /></el-icon>
              <span v-show="!isCollapse">新建对话</span>
            </el-button>
            <el-menu :router="true" :default-active="activeMenu" :collapse="isCollapse" class="sidebar-menu">
              <el-menu-item index="/youtube-research">
                <el-icon><Search /></el-icon><span>视频采集与处理</span>
              </el-menu-item>
              <el-menu-item index="/short-video-studio">
                <el-icon><VideoPlay /></el-icon><span>短视频拼接</span>
              </el-menu-item>
              <el-menu-item index="/account-management">
                <el-icon><User /></el-icon><span>账号连接</span>
              </el-menu-item>
              <el-menu-item index="/material-management">
                <el-icon><Picture /></el-icon><span>视频素材</span>
              </el-menu-item>
              <el-menu-item index="/publish-center">
                <el-icon><Upload /></el-icon><span>发布中心</span>
              </el-menu-item>
              <el-menu-item index="/scheduled-publish-tasks">
                <el-icon><Clock /></el-icon><span>自动化任务</span>
              </el-menu-item>
            </el-menu>
          </section>

          <section v-show="!isCollapse" class="workspace-sessions" aria-label="Agent 会话">
            <div class="session-toolbar">
              <span>会话</span>
              <div>
                <el-button text circle title="搜索会话" aria-label="搜索会话" @click="agentFiltersVisible = !agentFiltersVisible">
                  <el-icon><Search /></el-icon>
                </el-button>
                <el-button text circle title="刷新会话" aria-label="刷新会话" :loading="agentHistoryLoading" @click="loadAgentHistory">
                  <el-icon><RefreshRight /></el-icon>
                </el-button>
              </div>
            </div>
            <div v-if="agentFiltersVisible" class="session-filters">
              <el-input v-model="agentHistoryQuery" clearable placeholder="搜索会话" @keyup.enter="loadAgentHistory" @clear="loadAgentHistory">
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
              <el-radio-group v-model="agentHistorySource" size="small" @change="loadAgentHistory">
                <el-radio-button value="">全部</el-radio-button>
                <el-radio-button value="web">本地</el-radio-button>
                <el-radio-button value="feishu">手机</el-radio-button>
              </el-radio-group>
            </div>
            <div v-if="!agentHistoryLoading && sortedAgentHistory.length === 0" class="agent-session-empty">暂无会话</div>
            <div class="workspace-session-list">
              <button
                v-for="session in sortedAgentHistory"
                :key="session.id"
                class="workspace-session-item"
                :class="{ 'is-current': session.id === agentSessionId }"
                type="button"
                @click="selectAgentSession(session)"
              >
                <span class="session-pin" :class="{ 'is-visible': session.isPinned }"><el-icon><Top /></el-icon></span>
                <span class="session-copy">
                  <strong>{{ session.title || session.preview || 'Vidferry Agent' }}</strong>
                  <small>{{ session.source === 'feishu' ? '飞书' : formatAgentSessionTime(session.updatedAt) }}</small>
                </span>
                <el-dropdown trigger="click" @command="command => handleAgentSessionCommand(command, session)">
                  <el-button class="session-more" text circle aria-label="会话操作" title="会话操作" @click.stop>
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item :command="session.isPinned ? 'unpin' : 'pin'">{{ session.isPinned ? '取消置顶' : '置顶' }}</el-dropdown-item>
                      <el-dropdown-item command="rename">重命名</el-dropdown-item>
                      <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </button>
            </div>
          </section>

          <section class="user-dock">
            <div class="user-dock-row">
              <el-dropdown trigger="click" placement="top-start" @command="handleUserCommand">
                <button class="user-dock-profile" type="button">
                  <el-avatar :size="36" :src="userStore.userInfo?.avatarUrl || '/vidferry-icon.svg'">{{ userInitial }}</el-avatar>
                  <span v-show="!isCollapse" class="user-dock-copy">
                    <strong>{{ userStore.userInfo?.displayName || userStore.userInfo?.username }}</strong>
                    <small>{{ isAdmin ? '管理员' : '已登录' }}</small>
                  </span>
                  <el-icon v-show="!isCollapse"><ArrowDown /></el-icon>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="profile">个人资料</el-dropdown-item>
                    <el-dropdown-item command="password">修改密码</el-dropdown-item>
                    <el-dropdown-item command="about">帮助与版本</el-dropdown-item>
                    <el-dropdown-item v-if="isAdmin" command="users" divided>用户与安全</el-dropdown-item>
                    <el-dropdown-item command="statistics">处理统计</el-dropdown-item>
                    <el-dropdown-item command="audit">字幕审计与诊断</el-dropdown-item>
                    <el-dropdown-item v-if="isAdmin" command="shortVideoBgm">短视频 BGM 管理</el-dropdown-item>
                    <el-dropdown-item command="agentSettings">Agent 设置</el-dropdown-item>
                    <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <div v-show="!isCollapse" class="user-dock-actions">
                <TaskCenter />
                <el-popover placement="right-end" trigger="click" width="380" popper-class="message-popover">
                  <template #reference>
                    <el-badge :value="notificationStore.badgeCount" :hidden="!notificationStore.hasUnread" :max="9">
                      <el-button class="dock-icon-button" text circle :icon="Bell" aria-label="消息" title="消息" />
                    </el-badge>
                  </template>
                  <div class="message-panel">
                    <div class="message-panel-header">
                      <span>消息</span>
                      <el-button size="small" link @click="toggleNotificationHistory">{{ showNotificationHistory ? '待处理' : '历史' }}</el-button>
                    </div>
                    <el-empty v-if="notificationMessages.length === 0" :description="showNotificationHistory ? '暂无历史消息' : '暂无待处理消息'" :image-size="72" />
                    <div v-else class="message-list">
                      <div v-for="message in notificationMessages" :key="message.id" class="message-item" :class="{ 'is-read': message.status !== 'active' }">
                        <div class="message-item-title"><span>{{ message.title }}</span></div>
                        <div class="message-item-content">{{ message.content }}</div>
                        <div class="message-item-time">{{ formatMessageTime(message.updatedAt) }}</div>
                        <div class="message-item-actions">
                          <el-button v-if="message.actionRoute?.path" size="small" type="warning" link @click="handleMessageAction(message)">查看详情</el-button>
                          <el-button v-if="message.status === 'active'" size="small" type="primary" link @click="notificationStore.acknowledgeMessage(message.id)">已知晓</el-button>
                          <el-button v-if="message.status !== 'resolved'" size="small" type="success" link @click="notificationStore.resolveMessage(message.id)">已处理</el-button>
                        </div>
                      </div>
                    </div>
                  </div>
                </el-popover>
                <el-tooltip :content="feishuRobotStatus.message" placement="top">
                  <div class="feishu-robot-entry" :aria-label="feishuRobotStatus.message" role="status">
                    <el-icon><Cpu /></el-icon>
                    <span class="feishu-robot-status-dot" :class="`is-${feishuRobotStatus.status}`" />
                  </div>
                </el-tooltip>
              </div>
            </div>
          </section>
        </div>
      </el-aside>
      <el-container>
        <el-header>
          <div class="header-content">
            <div class="header-left">
              <el-icon class="toggle-sidebar" @click="toggleSidebar"><Fold /></el-icon>
              <div class="workspace-heading">
                <span>VIDFERRY WORKSPACE</span>
                <strong>{{ workspaceTitle }}</strong>
              </div>
            </div>
            <div class="workspace-header-actions">
              <el-button v-if="route.path === '/youtube-research'" plain @click="router.push('/workflow-settings')">
                <el-icon><Setting /></el-icon><span>处理配置</span>
              </el-button>
              <el-tooltip :content="isDarkTheme ? '切换浅色模式' : '切换深色模式'" placement="bottom">
                <el-button
                  class="theme-toggle-button"
                  text
                  circle
                  :aria-label="isDarkTheme ? '切换浅色模式' : '切换深色模式'"
                  @click="toggleTheme"
                >
                  <el-icon><Sunny v-if="isDarkTheme" /><Moon v-else /></el-icon>
                </el-button>
              </el-tooltip>
            </div>
            <div v-if="false" class="header-right">
              <el-tooltip content="打开内容安全审查与模型诊断" placement="bottom">
                <el-button
                  class="audit-open-button"
                  circle
                  :icon="DocumentChecked"
                  aria-label="打开内容安全审查与模型诊断"
                  @click="router.push('/subtitle-audit')"
                />
              </el-tooltip>
              <el-tooltip content="打开 Vidferry Agent" placement="bottom">
                <div class="agent-entry">
                  <el-button
                    class="agent-open-button"
                    circle
                    :icon="ChatDotRound"
                    aria-label="打开 Vidferry Agent"
                    @click="agentDrawerVisible = true"
                  />
                  <span
                    class="agent-status-dot"
                    :class="{ 'is-warning': agentConfigWarning }"
                  />
                </div>
              </el-tooltip>
              <TaskCenter />
              <el-tooltip :content="feishuRobotStatus.message" placement="bottom">
                <div class="feishu-robot-entry" :aria-label="feishuRobotStatus.message" role="status">
                  <el-icon><Cpu /></el-icon>
                  <span class="feishu-robot-status-dot" :class="`is-${feishuRobotStatus.status}`" />
                </div>
              </el-tooltip>
              <el-popover
                placement="bottom-end"
                trigger="click"
                width="380"
                popper-class="message-popover"
              >
                <template #reference>
                  <el-badge
                    :value="notificationStore.badgeCount"
                    :hidden="!notificationStore.hasUnread"
                    :max="9"
                    class="message-badge"
                  >
                    <el-button
                      class="message-button"
                      circle
                      :icon="Bell"
                      aria-label="消息"
                    />
                  </el-badge>
                </template>

                <div class="message-panel">
                  <div class="message-panel-header">
                    <span>消息</span>
                    <el-button size="small" link @click="toggleNotificationHistory">
                      {{ showNotificationHistory ? '待处理' : '历史' }}
                    </el-button>
                    <el-tag v-if="notificationStore.hasUnread" size="small" type="danger">
                      {{ notificationStore.unreadCount > 9 ? '9+' : notificationStore.unreadCount }} 待知晓
                    </el-tag>
                  </div>

                  <el-empty
                    v-if="notificationMessages.length === 0"
                    :description="showNotificationHistory ? '暂无历史消息' : '暂无待处理消息'"
                    :image-size="72"
                  />

                  <div v-else class="message-list">
                    <div
                      v-for="message in notificationMessages"
                      :key="message.id"
                      class="message-item"
                      :class="{ 'is-read': message.status !== 'active' }"
                    >
                      <div class="message-item-title">
                        <span>{{ message.title }}</span>
                        <el-tag size="small" :type="message.status === 'resolved' || message.status === 'acknowledged' ? 'info' : (message.severity === 'danger' ? 'danger' : 'warning')">
                          {{ message.status === 'resolved' ? '已处理' : (message.status === 'acknowledged' ? '已知晓' : '待处理') }}
                        </el-tag>
                      </div>
                      <div class="message-item-content">{{ message.content }}</div>
                      <div class="message-item-time">{{ formatMessageTime(message.updatedAt) }}</div>
                      <div class="message-item-actions">
                        <el-button
                          v-if="message.actionRoute?.path"
                          size="small"
                          type="warning"
                          link
                          @click="handleMessageAction(message)"
                        >
                          查看详情
                        </el-button>
                        <el-button
                          size="small"
                          type="primary"
                          link
                          v-if="message.status === 'active'"
                          @click="notificationStore.acknowledgeMessage(message.id)"
                        >
                          已知晓
                        </el-button>
                        <el-button
                          v-if="message.status !== 'resolved'"
                          size="small"
                          type="success"
                          link
                          @click="notificationStore.resolveMessage(message.id)"
                        >
                          已处理
                        </el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </el-popover>
              <el-dropdown trigger="click" @command="handleUserCommand">
                <div class="user-dropdown">
                  <el-avatar :size="32" :src="userStore.userInfo?.avatarUrl || '/vidferry-icon.svg'">{{ userInitial }}</el-avatar>
                  <span class="username">{{ userStore.userInfo?.displayName }}</span>
                  <el-icon><ArrowDown /></el-icon>
                </div>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="profile">个人资料</el-dropdown-item>
                    <el-dropdown-item v-if="isAdmin" command="users">用户与安全</el-dropdown-item>
                    <el-dropdown-item command="password">修改密码</el-dropdown-item>
                    <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </el-header>
        <el-main :class="{ 'is-agent-workspace': route.path === '/' }">
          <el-alert
            v-if="llmConfigWarning"
            class="runtime-config-alert"
            type="error"
            show-icon
            :closable="false"
            :title="llmConfigWarning"
          />
          <el-alert
            v-if="agentConfigWarning"
            class="runtime-config-alert"
            type="warning"
            show-icon
            :closable="false"
            :title="agentConfigWarning"
          />
          <el-alert
            v-if="asrConfigWarning"
            class="runtime-config-alert"
            type="error"
            show-icon
            :closable="false"
            :title="asrConfigWarning"
          />
          <AgentWorkspace
            :workspace="agentWorkspace"
            :show-page="route.path === '/'"
            :agent-config-warning="agentConfigWarning"
            :format-agent-session-time="formatAgentSessionTime"
          />
          <router-view v-if="route.path !== '/'" />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>
<script setup>
import { ref, computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElNotification } from 'element-plus'
import {
  HomeFilled, User, DataAnalysis, ArrowDown,
  Fold, Picture, Upload, Search, Bell, Setting, ChatDotRound, DocumentCopy, Loading, Plus, RefreshRight, Clock, Delete, DocumentChecked, Cpu, Moon, Sunny,
  MoreFilled, Top, Promotion, VideoPlay
} from '@element-plus/icons-vue'
import { accountApi } from '@/api/account'
import { commonApi } from '@/api/common'
import { materialApi } from '@/api/material'
import { formatBeijingTime } from '@/utils/time'
import { useAccountStore } from '@/stores/account'
import { useAppStore } from '@/stores/app'
import { useNotificationStore } from '@/stores/notification'
import { useUserStore } from '@/stores/user'
import TaskCenter from '@/components/TaskCenter.vue'
import AgentWorkspace from '@/components/AgentWorkspace.vue'
import { useAgentWorkspace } from '@/composables/useAgentWorkspace'
const route = useRoute()
const router = useRouter()
const accountStore = useAccountStore()
const appStore = useAppStore()
const notificationStore = useNotificationStore()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.userInfo?.role === 'admin')
const userInitial = computed(() => String(userStore.userInfo?.displayName || userStore.userInfo?.username || 'U').slice(0, 1).toUpperCase())
const THEME_STORAGE_KEY = 'vidferry:theme'
const themeMode = ref(localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light')
const isDarkTheme = computed(() => themeMode.value === 'dark')
const applyTheme = (mode) => {
  const nextTheme = mode === 'dark' ? 'dark' : 'light'
  document.documentElement.dataset.theme = nextTheme
  document.documentElement.style.colorScheme = nextTheme
}
const toggleTheme = () => {
  themeMode.value = isDarkTheme.value ? 'light' : 'dark'
  localStorage.setItem(THEME_STORAGE_KEY, themeMode.value)
  applyTheme(themeMode.value)
}
applyTheme(themeMode.value)
const ACCOUNT_CHECK_INTERVAL_MS = 3 * 60 * 1000
const NOTIFICATION_SYNC_INTERVAL_MS = 10 * 1000
const FEISHU_STATUS_POLL_INTERVAL_MS = 10 * 1000
const PUBLISH_TASK_POLL_INTERVAL_MS = 3000
const ACTIVE_PUBLISH_TASK_STATUSES = new Set(['queued', 'running', 'waiting_existing'])
const TERMINAL_PUBLISH_TASK_STATUSES = new Set(['confirmed', 'reused', 'partial', 'failed', 'uncertain', 'cancelled'])
let accountCheckTimer = null
let notificationSyncTimer = null
let feishuRobotStatusTimer = null
let publishTaskTrackingTimer = null
let publishTaskTrackingInFlight = false
let authenticatedWorkspaceStarted = false
const llmConfigWarning = ref('')
const agentConfigWarning = ref('')
const asrConfigWarning = ref('')
const feishuRobotStatus = ref({ status: 'connecting', message: '正在读取飞书机器人状态。', updatedAt: '' })
const showNotificationHistory = ref(false)
const notificationMessages = computed(() => (
  showNotificationHistory.value ? notificationStore.historyMessages : notificationStore.visibleMessages
))
const agentWorkspace = useAgentWorkspace({ route, router })
const {
  agentDrawerVisible, agentLoading, agentInput, agentSessionId, agentMessages, agentMessagesRef,
  agentOlderMessagesLoading, agentHasOlderMessages, agentMessagesBeforeId, agentSessionRestoreLoading,
  agentInputRef, agentRetryContext, agentVideoContext, agentIncludeVideoContext, agentHistoryVisible,
  agentHistoryLoading, agentHistory, agentHistoryRange, agentHistorySource, agentHistoryQuery,
  agentFiltersVisible, agentCurrentSession, agentSessionSource, agentSessionSourceLabel, agentSessionReadonly,
  agentQuickQuestions, workspaceTitle, currentAgentTitle, sortedAgentHistory, agentContextLabel,
  handleAgentMessagesScroll, newAgentConversation, startAgentConversation, sendAgentMessage, showAgentMessageTools, copyAgentMessage, loadAgentHistory,
  openAgentHistory, openAgentWorkbench, selectAgentSession, handleAgentSessionCommand,
  removeAgentSession, prepareAgentRetry, handleAgentInputKeydown, confirmAgentAction, handleAskAgentEvent, activateAgentWorkspace, clearAgentWorkspace
} = agentWorkspace
const activeMenu = computed(() => {
  return route.path
})

// 侧边栏折叠状态
const mobileSidebarQuery = window.matchMedia('(max-width: 980px)')
const isCollapse = ref(mobileSidebarQuery.matches)
const syncMobileSidebar = event => {
  isCollapse.value = event.matches
}

// 切换侧边栏折叠状态
const toggleSidebar = () => {
  isCollapse.value = !isCollapse.value
}

const openProcessSettings = () => {
  router.push('/workflow-settings')
}

const refreshGlobalAccountMessages = async () => {
  try {
    const res = await accountApi.getAccounts()
    if (res.code === 200 && res.data) {
      accountStore.setAccounts(res.data)
    }
  } catch (error) {
    console.error('全局账号状态检查失败:', error)
  }
}

const refreshRuntimeConfigStatus = async () => {
  try {
    const res = await commonApi.getRuntimeConfigStatus()
    const llm = res?.data?.llm
    const textStatus = llm?.text
    if (!textStatus || textStatus.ready) {
      llmConfigWarning.value = ''
    }
    if (textStatus && !textStatus.ready) {
      llmConfigWarning.value = textStatus.message || '文本模型不可用，请检查配置并重启后端。'
    }
    const asrStatus = res?.data?.runtime?.whisper
    asrConfigWarning.value = asrStatus && !asrStatus.ready
      ? (asrStatus.message || 'Whisper 不可用，请检查模型与运行配置。')
      : ''
    const agent = res?.data?.agent
    const agentLlmStatus = llm?.agent
    const agentWarnings = []
    if (agent?.enabled && agentLlmStatus && !agentLlmStatus.ready) {
      agentWarnings.push(agentLlmStatus.message || 'Agent 模型不可用，请检查配置并重启后端。')
    }
    if (agent?.enabled && agent?.requirePrepublishCheck && !agent?.multimodalModelConfigured) {
      agentWarnings.push('Agent 发布前质检已启用，但多模态模型未配置；发布会被关键帧审核阻断。')
    }
    agentConfigWarning.value = agentWarnings.join(' ')
  } catch (error) {
    console.error('运行时配置状态检查失败:', error)
  }
}

const refreshFeishuRobotStatus = async () => {
  try {
    const status = (await commonApi.getFeishuRobotStatus())?.data
    if (!['disabled', 'connecting', 'connected', 'error'].includes(status?.status)) throw new Error('invalid status')
    feishuRobotStatus.value = status
  } catch (_) {
    feishuRobotStatus.value = {
      status: 'error',
      message: '无法读取飞书机器人状态，请检查后端是否可用。',
      updatedAt: ''
    }
  }
}

const formatMessageTime = (timestamp) => {
  if (!timestamp) return ''

  return formatBeijingTime(timestamp, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const formatAgentSessionTime = (timestamp) => {
  if (!timestamp) return ''
  return formatBeijingTime(timestamp, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const handleMessageAction = (message) => {
  if (!message) return
  if (message.actionRoute?.path) {
    router.push(message.actionRoute)
  }
  notificationStore.acknowledgeMessage(message.id)
}

const handleUserCommand = async command => {
  if (command === 'profile') return router.push('/profile')
  if (command === 'users') return router.push('/user-management')
  if (command === 'statistics') return router.push('/workflow-statistics')
  if (command === 'audit') return router.push('/subtitle-audit')
  if (command === 'shortVideoBgm') return router.push('/short-video-bgm')
  if (command === 'agentSettings') return router.push('/agent-settings')
  if (command === 'about') return router.push('/about')
  if (command === 'password') return router.push('/change-password')
  if (command === 'logout') {
    clearAgentWorkspace()
    appStore.resetUserWorkspace()
    accountStore.resetUserWorkspace()
    notificationStore.resetUserWorkspace()
    await userStore.logout()
    window.location.hash = '#/login'
    window.location.reload()
  }
}

const toggleNotificationHistory = async () => {
  showNotificationHistory.value = !showNotificationHistory.value
  if (showNotificationHistory.value) await notificationStore.refresh({ includeHistory: true })
}

const refreshNotifications = () => notificationStore.refresh({ includeHistory: showNotificationHistory.value })

const pollTrackedPublishTasks = async () => {
  if (publishTaskTrackingInFlight || !userStore.isLoggedIn) return
  const trackedTasks = appStore.trackedPublishTasks
  if (!trackedTasks.length) return

  publishTaskTrackingInFlight = true
  try {
    const results = await Promise.all(trackedTasks.map(async trackedTask => {
      try {
        const response = await materialApi.getPublishTask(trackedTask.publishTaskId)
        return { trackedTask, response }
      } catch (error) {
        return { trackedTask, error }
      }
    }))
    results.forEach(({ trackedTask, response, error }) => {
      if (error) {
        if (Number(error?.response?.status) === 404) {
          appStore.untrackPublishTask(trackedTask.publishTaskId)
        }
        return
      }
      const status = String(response?.data?.status || '').trim()
      if (ACTIVE_PUBLISH_TASK_STATUSES.has(status)) return
      if (TERMINAL_PUBLISH_TASK_STATUSES.has(status)) {
        appStore.untrackPublishTask(trackedTask.publishTaskId)
        appStore.invalidatePublishRecords(trackedTask.videoId)
      }
    })
  } finally {
    publishTaskTrackingInFlight = false
  }
}

const initializeAuthenticatedWorkspace = () => {
  if (authenticatedWorkspaceStarted || !userStore.isLoggedIn) return
  authenticatedWorkspaceStarted = true
  activateAgentWorkspace(userStore.userInfo?.id)
  void openAgentWorkbench()
  refreshRuntimeConfigStatus()
  refreshFeishuRobotStatus()
  refreshGlobalAccountMessages()
  refreshNotifications()
  accountCheckTimer = window.setInterval(() => {
    refreshGlobalAccountMessages()
  }, ACCOUNT_CHECK_INTERVAL_MS)
  notificationSyncTimer = window.setInterval(refreshNotifications, NOTIFICATION_SYNC_INTERVAL_MS)
  feishuRobotStatusTimer = window.setInterval(refreshFeishuRobotStatus, FEISHU_STATUS_POLL_INTERVAL_MS)
  window.addEventListener('focus', refreshNotifications)
  window.addEventListener('focus', refreshFeishuRobotStatus)
}

watch(() => userStore.userInfo?.id || 0, (userId, previousUserId) => {
  if (previousUserId && previousUserId !== userId) {
    clearAgentWorkspace()
    appStore.resetUserWorkspace()
    accountStore.resetUserWorkspace()
    notificationStore.resetUserWorkspace()
    authenticatedWorkspaceStarted = false
  }
  initializeAuthenticatedWorkspace()
})

onMounted(() => {
  window.addEventListener('vidferry:ask-agent', handleAskAgentEvent)
  mobileSidebarQuery.addEventListener('change', syncMobileSidebar)
  initializeAuthenticatedWorkspace()
  publishTaskTrackingTimer = window.setInterval(pollTrackedPublishTasks, PUBLISH_TASK_POLL_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (accountCheckTimer) {
    window.clearInterval(accountCheckTimer)
    accountCheckTimer = null
  }
  if (notificationSyncTimer) {
    window.clearInterval(notificationSyncTimer)
    notificationSyncTimer = null
  }
  if (feishuRobotStatusTimer) {
    window.clearInterval(feishuRobotStatusTimer)
    feishuRobotStatusTimer = null
  }
  if (publishTaskTrackingTimer) {
    window.clearInterval(publishTaskTrackingTimer)
    publishTaskTrackingTimer = null
  }
  window.removeEventListener('focus', refreshNotifications)
  window.removeEventListener('vidferry:ask-agent', handleAskAgentEvent)
  window.removeEventListener('focus', refreshFeishuRobotStatus)
  mobileSidebarQuery.removeEventListener('change', syncMobileSidebar)
})
</script>

<style lang="scss" src="@/styles/app-shell.scss"></style>
