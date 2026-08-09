<template>
  <router-view v-if="route.meta.public" />
  <div v-else id="app">
    <el-container>
      <el-aside :width="isCollapse ? '64px' : '200px'">
        <div class="sidebar">
          <div class="logo">
            <img v-show="isCollapse" src="/vidferry-icon.svg" alt="Vidferry" class="logo-img">
            <h2 v-show="!isCollapse">Vidferry V1.1</h2>
          </div>
          <el-menu
            :router="true"
            :default-active="activeMenu"
            :collapse="isCollapse"
            class="sidebar-menu"
            background-color="#001529"
            text-color="#fff"
            active-text-color="#409EFF"
          >
            <el-menu-item index="/">
              <el-icon><HomeFilled /></el-icon>
              <span>首页</span>
            </el-menu-item>
            <el-menu-item index="/youtube-research">
              <el-icon><Search /></el-icon>
              <span>视频采集处理</span>
            </el-menu-item>
            <el-menu-item v-if="isAdmin" index="/account-management">
              <el-icon><User /></el-icon>
              <span>账号管理</span>
            </el-menu-item>
            <el-menu-item index="/material-management">
              <el-icon><Picture /></el-icon>
              <span>视频素材管理</span>
            </el-menu-item>
            <el-menu-item index="/publish-center">
              <el-icon><Upload /></el-icon>
              <span>发布中心</span>
            </el-menu-item>
            <el-menu-item index="/scheduled-publish-tasks">
              <el-icon><Clock /></el-icon>
              <span>定时发布任务列表</span>
            </el-menu-item>
            <el-menu-item index="/workflow-statistics">
              <el-icon><DataAnalysis /></el-icon>
              <span>处理统计</span>
            </el-menu-item>
            <el-menu-item index="/about">
              <el-icon><DataAnalysis /></el-icon>
              <span>关于</span>
            </el-menu-item>
          </el-menu>
          <div v-if="isAdmin" class="sidebar-settings">
            <el-button
              class="sidebar-settings-button"
              type="primary"
              :circle="isCollapse"
              @click="openProcessSettings"
            >
              <el-icon><Setting /></el-icon>
              <span v-show="!isCollapse">设置</span>
            </el-button>
          </div>
        </div>
      </el-aside>
      <el-container>
        <el-header>
          <div class="header-content">
            <div class="header-left">
              <el-icon class="toggle-sidebar" @click="toggleSidebar"><Fold /></el-icon>
            </div>
            <div class="header-right">
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
                  <el-avatar :size="32">{{ userInitial }}</el-avatar>
                  <span class="username">{{ userStore.userInfo?.displayName }}</span>
                  <el-icon><ArrowDown /></el-icon>
                </div>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="isAdmin" command="users">用户与安全</el-dropdown-item>
                    <el-dropdown-item command="password">修改密码</el-dropdown-item>
                    <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </el-header>
        <el-main>
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
          <router-view />
        </el-main>
      </el-container>
    </el-container>
    <el-drawer
      v-model="agentDrawerVisible"
      direction="rtl"
      size="420px"
      class="agent-drawer"
      append-to-body
      @open="restoreAgentMessages"
    >
      <template #header>
        <div class="agent-drawer-header">
          <div>
            <span class="agent-drawer-kicker">PROJECT AGENT</span>
            <strong>Vidferry Agent</strong>
          </div>
          <el-tag size="small" effect="plain" :type="agentConfigWarning ? 'warning' : 'success'">
            操作需确认
          </el-tag>
          <el-tooltip content="历史会话" placement="bottom">
            <el-button text circle title="历史会话" aria-label="历史会话" @click="openAgentHistory">
              <el-icon><Clock /></el-icon>
            </el-button>
          </el-tooltip>
          <el-button text circle title="新建对话" aria-label="新建对话" @click="newAgentConversation">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
      </template>
      <div class="agent-panel">
        <div class="agent-context-card">
          <div class="agent-avatar">
            <el-icon><ChatDotRound /></el-icon>
          </div>
          <div class="agent-context-copy">
            <strong>视频工作流助手</strong>
            <span>{{ agentContextLabel }} · {{ agentConfigWarning ? '等待视觉模型' : '在线' }}</span>
          </div>
        </div>
        <div class="agent-quick-panel">
          <div class="agent-section-title">快捷问题</div>
          <div class="agent-quick-actions">
            <el-button
              v-for="question in agentQuickQuestions"
              :key="question"
              size="small"
              plain
              @click="sendAgentMessage(question)"
            >
              {{ question }}
            </el-button>
          </div>
        </div>
        <div ref="agentMessagesRef" class="agent-messages" @scroll.passive="handleAgentMessagesScroll">
          <div v-if="agentOlderMessagesLoading" class="agent-older-loading" aria-live="polite">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>正在加载更早消息</span>
          </div>
          <div
            v-for="message in agentMessages"
            :key="message.id"
            class="agent-message"
            :class="`is-${message.role}`"
          >
            <div class="agent-message-role">{{ message.role === 'user' ? '你' : 'Agent' }}</div>
            <div class="agent-message-content">
              <div v-if="message.thinking" class="agent-thinking" aria-live="polite">
                <el-icon class="agent-thinking-icon is-loading"><Loading /></el-icon>
                <span>{{ message.statusMessage || '正在思考' }}</span>
              </div>
              <span v-if="message.content">{{ message.content }}</span>
            </div>
            <div v-for="card in message.cards || []" :key="`${message.id}-${card.type}-${card.title}`" class="agent-result-card">
              <div class="agent-card-title"><span>{{ card.title }}</span><strong>{{ card.count }}</strong></div>
              <div v-for="item in card.items || []" :key="`${item.title}-${item.detail || item.status}`" class="agent-card-item">
                <strong>{{ item.title }}</strong>
                <span>{{ item.detail || item.channel || item.status }}</span>
              </div>
            </div>
            <div v-if="message.importProposal" class="agent-import-proposal">
              <div class="agent-card-title">
                <span>待导入线索</span>
                <strong>{{ message.importProposal.items?.length || 0 }}</strong>
              </div>
              <el-checkbox-group v-model="message.selectedCandidateIds" class="agent-import-candidates">
                <div
                  v-for="item in message.importProposal.items || []"
                  :key="`${message.id}-${item.id}`"
                  class="agent-import-candidate"
                >
                  <el-checkbox
                    :label="item.id"
                    :disabled="message.imported || message.importing"
                    :aria-label="`选择 ${item.title || '视频'}`"
                  ><span class="agent-import-checkbox-label" aria-hidden="true"></span></el-checkbox>
                  <div class="agent-import-copy">
                  <span class="agent-import-title">{{ item.title || '未命名视频' }}</span>
                  <span class="agent-import-meta">{{ [item.channel, item.duration, item.publishedAt].filter(Boolean).join(' · ') }}</span>
                  </div>
                </div>
              </el-checkbox-group>
              <el-select
                v-if="message.importProposal.requiresTargets"
                v-model="message.selectedImportAccountIds"
                class="agent-execution-accounts"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择发布账号"
                :disabled="message.imported || message.importing"
                @change="normalizeImportAccountSelection(message)"
              >
                <el-option
                  v-for="account in message.importProposal.availableAccounts || []"
                  :key="`${message.id}-import-${account.id}`"
                  :label="`${account.platformName} · ${account.name}`"
                  :value="account.id"
                />
              </el-select>
              <div v-if="message.imported" class="agent-import-result">{{ message.importResult }}</div>
              <div v-else class="agent-import-actions">
                <el-button size="small" :disabled="message.importing" @click="message.selectedCandidateIds = []">取消选择</el-button>
                <el-button type="primary" size="small" :loading="message.importing" :disabled="!canConfirmAgentImport(message)" @click="confirmAgentImport(message)">
                  确认{{ message.importProposal.actionLabel || '导入' }} {{ (message.selectedCandidateIds || []).length }} 个线索
                </el-button>
              </div>
            </div>
            <div v-if="message.executionProposal" class="agent-execution-proposal">
              <div class="agent-card-title">
                <span>待执行操作</span>
                <strong>{{ message.executionProposal.actionLabel }}</strong>
              </div>
              <div class="agent-execution-video">
                <strong>{{ message.executionProposal.video?.title || '未命名视频' }}</strong>
                <span>{{ [message.executionProposal.video?.channel, executionVideoStatus(message.executionProposal.video)].filter(Boolean).join(' · ') }}</span>
              </div>
              <el-select
                v-if="message.executionProposal.requiresTargets"
                v-model="message.selectedExecutionAccountIds"
                class="agent-execution-accounts"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择发布账号"
                :disabled="message.executed || message.executing"
                @change="normalizeExecutionAccountSelection(message)"
              >
                <el-option
                  v-for="account in message.executionProposal.availableAccounts || []"
                  :key="`${message.id}-${account.id}`"
                  :label="`${account.platformName} · ${account.name}`"
                  :value="account.id"
                />
              </el-select>
              <el-date-picker
                v-if="message.executionProposal.requiresSchedule"
                v-model="message.executionScheduledAt"
                class="agent-execution-schedule"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                format="YYYY-MM-DD HH:mm"
                placeholder="选择发布时间"
                :disabled="message.executed || message.executing"
              />
              <div v-if="message.executed" class="agent-execution-result">{{ message.executionResult }}</div>
              <div v-else class="agent-import-actions">
                <el-button type="primary" size="small" :loading="message.executing" :disabled="!canConfirmAgentExecution(message)" @click="confirmAgentExecution(message)">
                  确认{{ message.executionProposal.actionLabel }}
                </el-button>
              </div>
            </div>
            <div v-if="message.actions?.length" class="agent-actions">
              <el-button v-for="action in message.actions" :key="`${message.id}-${action.label}`" size="small" plain @click="confirmAgentAction(action)">{{ action.label }}</el-button>
            </div>
            <div v-if="showAgentMessageTools(message)" class="agent-message-tools">
              <el-tooltip content="复制" placement="bottom">
                <el-button text circle aria-label="复制消息" @click="copyAgentMessage(message)">
                  <el-icon><DocumentCopy /></el-icon>
                </el-button>
              </el-tooltip>
              <el-tooltip v-if="message.role === 'user' && !agentLoading" content="重试" placement="bottom">
                <el-button text circle aria-label="重试问题" @click="prepareAgentRetry(message)">
                  <el-icon><RefreshRight /></el-icon>
                </el-button>
              </el-tooltip>
            </div>
          </div>
          <div v-if="agentMessages.length === 0" class="agent-empty">
            <el-icon><ChatDotRound /></el-icon>
            <strong>还没有对话</strong>
            <span>从一个快捷问题开始。</span>
          </div>
        </div>
        <div class="agent-input">
          <div
            v-if="agentVideoContext"
            class="agent-video-context"
            :class="{ 'is-disabled': !agentIncludeVideoContext }"
          >
            <el-checkbox v-model="agentIncludeVideoContext">视频上下文</el-checkbox>
            <span :title="agentVideoContext.title">{{ agentVideoContext.title || '未命名视频' }}</span>
            <el-tag size="small" effect="plain">{{ agentVideoContext.publishedPlatforms?.length || 0 }} 个平台</el-tag>
          </div>
          <el-input
            ref="agentInputRef"
            v-model="agentInput"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            :placeholder="agentVideoContext && agentIncludeVideoContext ? '询问这个视频的发布或处理信息' : '例如：已处理但还没发布的视频有哪些？'"
            @keydown="handleAgentInputKeydown"
          />
          <el-button type="primary" :loading="agentLoading" @click="sendAgentMessage()">
            发送
          </el-button>
        </div>
      </div>
    </el-drawer>
    <el-dialog
      v-model="agentHistoryVisible"
      title="历史会话"
      width="min(560px, calc(100vw - 32px))"
      append-to-body
    >
      <div class="agent-history-toolbar">
        <span>{{ agentHistoryLoading ? '正在读取' : `共 ${agentHistory.length} 个会话` }}</span>
        <div class="agent-history-filter">
          <el-date-picker
            v-model="agentHistoryRange"
            type="daterange"
            size="small"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            unlink-panels
            @change="loadAgentHistory"
          />
          <el-button text type="primary" :loading="agentHistoryLoading" @click="loadAgentHistory">刷新</el-button>
        </div>
      </div>
      <el-empty v-if="!agentHistoryLoading && agentHistory.length === 0" description="暂无历史会话" :image-size="72" />
      <el-scrollbar v-else max-height="420px">
        <div class="agent-history-list">
          <div
            v-for="session in agentHistory"
            :key="session.id"
            class="agent-history-item"
            :class="{ 'is-current': session.id === agentSessionId }"
            @click="selectAgentSession(session)"
          >
            <div class="agent-history-item-main">
              <strong>{{ session.title || session.preview || 'Vidferry Agent' }}</strong>
              <span>{{ session.preview || '暂无用户消息' }}</span>
            </div>
            <div class="agent-history-item-meta">
              <span>{{ formatAgentSessionTime(session.updatedAt) }}</span>
              <span>{{ session.messageCount || 0 }} 条消息</span>
            </div>
            <el-button
              text
              circle
              type="danger"
              title="删除会话"
              aria-label="删除会话"
              @click.stop="removeAgentSession(session)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
      </el-scrollbar>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import {
  HomeFilled, User, DataAnalysis, ArrowDown,
  Fold, Picture, Upload, Search, Bell, Setting, ChatDotRound, DocumentCopy, Loading, Plus, RefreshRight, Clock, Delete, DocumentChecked, Cpu
} from '@element-plus/icons-vue'
import { accountApi } from '@/api/account'
import { agentApi } from '@/api/agent'
import { commonApi } from '@/api/common'
import { useAccountStore } from '@/stores/account'
import { useNotificationStore } from '@/stores/notification'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const accountStore = useAccountStore()
const notificationStore = useNotificationStore()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.userInfo?.role === 'admin')
const userInitial = computed(() => String(userStore.userInfo?.displayName || userStore.userInfo?.username || 'U').slice(0, 1).toUpperCase())
const ACCOUNT_CHECK_INTERVAL_MS = 3 * 60 * 1000
const NOTIFICATION_SYNC_INTERVAL_MS = 10 * 1000
const FEISHU_STATUS_POLL_INTERVAL_MS = 10 * 1000
const AGENT_MESSAGE_PAGE_SIZE = 12
let accountCheckTimer = null
let notificationSyncTimer = null
let feishuRobotStatusTimer = null
const llmConfigWarning = ref('')
const agentConfigWarning = ref('')
const feishuRobotStatus = ref({ status: 'connecting', message: '正在读取飞书机器人状态。', updatedAt: '' })
const showNotificationHistory = ref(false)
const notificationMessages = computed(() => (
  showNotificationHistory.value ? notificationStore.historyMessages : notificationStore.visibleMessages
))
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
let agentMessageId = 1
let restoredAgentSessionId = ''
let restoringAgentSessionId = ''
let agentRestoreRequestId = 0

const agentQuickQuestions = [
  '找 5 个关于 AI 效率工具的 YouTube 视频，放入线索列表',
  '现在待处理的视频有哪些？'
]

const agentRouteLabels = {
  '/': '首页',
  '/youtube-research': '视频采集处理',
  '/account-management': '账号管理',
  '/user-management': '用户与安全',
  '/material-management': '视频素材管理',
  '/publish-center': '发布中心',
  '/scheduled-publish-tasks': '定时发布任务列表',
  '/workflow-statistics': '处理统计',
  '/about': '关于'
}

// 当前激活的菜单项
const activeMenu = computed(() => {
  return route.path
})

// 侧边栏折叠状态
const mobileSidebarQuery = window.matchMedia('(max-width: 760px)')
const isCollapse = ref(mobileSidebarQuery.matches)
const syncMobileSidebar = event => {
  isCollapse.value = event.matches
}

// 切换侧边栏折叠状态
const toggleSidebar = () => {
  isCollapse.value = !isCollapse.value
}

const openProcessSettings = () => {
  if (typeof window.__VIDFERRY_OPEN_PROCESS_SETTINGS__ === 'function') {
    window.__VIDFERRY_OPEN_PROCESS_SETTINGS__()
    return
  }
  if (route.path !== '/youtube-research') {
    router.push({ path: '/youtube-research', query: { openSettings: '1' } })
  }
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

const currentAgentContext = computed(() => ({
  path: route.path,
  query: route.query,
  pageTitle: agentRouteLabels[route.path] || route.meta?.title || route.name || route.path
}))

const agentContextLabel = computed(() => currentAgentContext.value.pageTitle || '当前页面')

const scrollAgentMessages = async () => {
  await nextTick()
  const container = agentMessagesRef.value
  if (container) container.scrollTop = container.scrollHeight
}

const mapAgentHistoryMessage = item => ({
  id: `history-${item.id}`,
  historyId: Number(item.id),
  role: item.role,
  content: item.content || '',
  context: item.context || {},
  cards: item.context?.cards || [],
  actions: item.context?.actions || [],
  importProposal: item.context?.importProposal || null,
  selectedCandidateIds: (item.context?.importProposal?.items || []).map(candidate => candidate.id),
  selectedImportAccountIds: defaultImportAccountIds(item.context?.importProposal),
  executionProposal: item.context?.executionProposal || null,
  selectedExecutionAccountIds: [],
  executionScheduledAt: ''
})

const pushAgentMessage = (role, content, extra = {}) => {
  const item = {
    id: agentMessageId++,
    role,
    content: String(content || ''),
    ...extra
  }
  agentMessages.value.push(item)
  scrollAgentMessages()
  return agentMessages.value[agentMessages.value.length - 1]
}

const saveAgentSessionId = (sessionId) => {
  if (!sessionId) return
  agentSessionId.value = sessionId
  localStorage.setItem('vidferry:agent-session-id', sessionId)
}

const restoreAgentMessages = async () => {
  const sessionId = agentSessionId.value
  if (!sessionId || restoredAgentSessionId === sessionId || agentLoading.value) return
  if (agentSessionRestoreLoading.value && restoringAgentSessionId === sessionId) return
  const requestId = ++agentRestoreRequestId
  restoringAgentSessionId = sessionId
  agentSessionRestoreLoading.value = true
  try {
    const res = await agentApi.getMessages(sessionId, AGENT_MESSAGE_PAGE_SIZE)
    if (requestId !== agentRestoreRequestId || sessionId !== agentSessionId.value) return
    agentMessages.value = (res?.data?.items || []).map(mapAgentHistoryMessage)
    agentHasOlderMessages.value = Boolean(res?.data?.hasMore)
    agentMessagesBeforeId.value = res?.data?.nextBeforeId || null
    restoredAgentSessionId = sessionId
    await scrollAgentMessages()
  } catch (error) {
    if (requestId === agentRestoreRequestId) console.warn('恢复 Agent 会话失败:', error)
  } finally {
    if (requestId === agentRestoreRequestId) {
      agentSessionRestoreLoading.value = false
      restoringAgentSessionId = ''
    }
  }
}

const loadOlderAgentMessages = async () => {
  const sessionId = agentSessionId.value
  const beforeId = agentMessagesBeforeId.value
  const container = agentMessagesRef.value
  if (!sessionId || !beforeId || !container || !agentHasOlderMessages.value || agentOlderMessagesLoading.value || agentLoading.value) return

  const previousHeight = container.scrollHeight
  agentOlderMessagesLoading.value = true
  try {
    const res = await agentApi.getMessages(sessionId, AGENT_MESSAGE_PAGE_SIZE, beforeId)
    if (sessionId !== agentSessionId.value) return
    const knownIds = new Set(agentMessages.value.map(item => item.historyId).filter(Number.isFinite))
    const olderMessages = (res?.data?.items || [])
      .map(mapAgentHistoryMessage)
      .filter(item => !knownIds.has(item.historyId))
    agentMessages.value = [...olderMessages, ...agentMessages.value]
    agentHasOlderMessages.value = Boolean(res?.data?.hasMore)
    agentMessagesBeforeId.value = res?.data?.nextBeforeId || null
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
  if (event.currentTarget.scrollTop <= 8) loadOlderAgentMessages()
}

const newAgentConversation = () => {
  agentSessionId.value = ''
  agentRestoreRequestId += 1
  agentSessionRestoreLoading.value = false
  restoringAgentSessionId = ''
  restoredAgentSessionId = ''
  agentMessages.value = []
  agentOlderMessagesLoading.value = false
  agentHasOlderMessages.value = false
  agentMessagesBeforeId.value = null
  agentRetryContext.value = null
  agentVideoContext.value = null
  agentIncludeVideoContext.value = false
  localStorage.removeItem('vidferry:agent-session-id')
}

const sendAgentMessage = async (presetMessage = '', extraContext = {}) => {
  const message = String(presetMessage || agentInput.value || '').trim()
  if (!message || agentLoading.value) return
  agentDrawerVisible.value = true
  agentInput.value = ''
  const messageContext = {
    ...currentAgentContext.value,
    ...(presetMessage ? {} : (agentRetryContext.value || {})),
    ...extraContext
  }
  if (agentVideoContext.value && agentIncludeVideoContext.value) {
    messageContext.videoContext = agentVideoContext.value
  } else {
    delete messageContext.videoContext
  }
  agentRetryContext.value = null
  pushAgentMessage('user', message, { context: messageContext })
  const pending = pushAgentMessage('assistant', '', { thinking: true, statusMessage: '正在理解你的问题', retryMessage: message })
  agentLoading.value = true
  let completed = false
  try {
    await agentApi.chatStream({
      message,
      sessionId: agentSessionId.value,
      context: messageContext
    }, (event, data) => {
      if (event === 'status') {
        pending.statusMessage = data.message || '正在思考'
      } else if (event === 'delta') {
        pending.thinking = false
        pending.content += data.content || ''
      } else if (event === 'result') {
        completed = true
        pending.thinking = false
        pending.error = false
        pending.content = data.answer || pending.content || '我暂时没有查到结果。'
        pending.cards = data.cards || []
        pending.actions = data.actions || []
        pending.importProposal = data.importProposal || null
        pending.selectedCandidateIds = (data.importProposal?.items || []).map(candidate => candidate.id)
        pending.selectedImportAccountIds = defaultImportAccountIds(data.importProposal)
        pending.executionProposal = data.executionProposal || null
        pending.selectedExecutionAccountIds = defaultExecutionAccountIds(data.executionProposal)
        pending.executionScheduledAt = ''
        saveAgentSessionId(data.sessionId)
      } else if (event === 'error') {
        throw new Error(data.message || 'Agent 暂时不可用')
      }
      scrollAgentMessages()
    })
    if (!completed) throw new Error('Agent 响应中断，请重试。')
  } catch (error) {
    pending.thinking = false
    pending.error = true
    pending.content = error.message || 'Agent 暂时不可用，请稍后再试。'
    ElMessage.error(error.message || 'Agent 暂时不可用')
  } finally {
    agentLoading.value = false
  }
}

const showAgentMessageTools = (message) => {
  if (!message?.content) return false
  return message.role === 'user' || (message.role === 'assistant' && !message.thinking && !message.error)
}

const copyAgentMessage = async (message) => {
  try {
    await navigator.clipboard.writeText(message.content)
    ElMessage.success('已复制')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

const loadAgentHistory = async () => {
  agentHistoryLoading.value = true
  try {
    const [from = '', to = ''] = agentHistoryRange.value || []
    const res = await agentApi.getSessions({ page: 1, pageSize: 50, from, to })
    agentHistory.value = res?.data?.items || []
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

const selectAgentSession = async (session) => {
  if (!session?.id || agentLoading.value) return
  saveAgentSessionId(session.id)
  restoredAgentSessionId = ''
  agentMessages.value = []
  agentOlderMessagesLoading.value = false
  agentHasOlderMessages.value = false
  agentMessagesBeforeId.value = null
  agentRetryContext.value = null
  agentVideoContext.value = null
  agentIncludeVideoContext.value = false
  agentHistoryVisible.value = false
  agentDrawerVisible.value = true
  await restoreAgentMessages()
}

const removeAgentSession = async (session) => {
  if (!session?.id || agentLoading.value) return
  try {
    await ElMessageBox.confirm(
      `删除“${session.title || session.preview || '该会话'}”后，消息和会话摘要将无法恢复。`,
      '确认删除会话',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await agentApi.deleteSession(session.id)
    if (session.id === agentSessionId.value) {
      newAgentConversation()
    }
    await loadAgentHistory()
    ElMessage.success('会话已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.message || '删除会话失败')
    }
  }
}

const prepareAgentRetry = async (message) => {
  if (agentLoading.value || !message?.content) return
  agentInput.value = message.content
  agentRetryContext.value = message.context || {}
  await nextTick()
  agentInputRef.value?.focus()
}

const handleAgentInputKeydown = (event) => {
  if (event.key !== 'Enter' || event.isComposing || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  sendAgentMessage()
}

const confirmAgentAction = async (action) => {
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

const defaultImportAccountIds = (proposal) => {
  const hints = new Set(proposal?.platformHints || [])
  if (hints.size === 0) return []
  const selectedPlatforms = new Set()
  return (proposal?.availableAccounts || []).reduce((ids, account) => {
    if (!hints.has(account.platformType) || selectedPlatforms.has(account.platformType)) return ids
    selectedPlatforms.add(account.platformType)
    ids.push(account.id)
    return ids
  }, [])
}

const importTargets = (message) => {
  const selectedIds = new Set((message?.selectedImportAccountIds || []).map(value => Number(value)))
  return (message?.importProposal?.availableAccounts || [])
    .filter(account => selectedIds.has(Number(account.id)))
    .map(account => ({ platformType: account.platformType, accountId: account.id }))
}

const normalizeImportAccountSelection = (message) => {
  const accounts = new Map((message?.importProposal?.availableAccounts || []).map(account => [Number(account.id), account]))
  const selectedPlatforms = new Set()
  message.selectedImportAccountIds = (message.selectedImportAccountIds || [])
    .slice()
    .reverse()
    .filter(accountId => {
      const account = accounts.get(Number(accountId))
      if (!account || selectedPlatforms.has(account.platformType)) return false
      selectedPlatforms.add(account.platformType)
      return true
    })
    .reverse()
}

const canConfirmAgentImport = (message) => {
  const proposal = message?.importProposal
  if (!proposal?.proposalId || message.importing || message.imported || !(message.selectedCandidateIds || []).length) return false
  return !proposal.requiresTargets || importTargets(message).length > 0
}

const importConfirmationText = (proposal, count, targetCount) => {
  if (proposal?.requestedAction === 'workflow_publish') {
    return `将 ${count} 个候选视频存入线索列表，并创建下载、处理和发布任务，目标为 ${targetCount} 个平台账号。`
  }
  if (proposal?.requestedAction === 'workflow_process') {
    return `将 ${count} 个候选视频存入线索列表，并创建下载和处理任务。不会自动发布。`
  }
  if (proposal?.requestedAction === 'download') {
    return `将 ${count} 个候选视频存入线索列表，并创建下载任务。不会开始处理或发布。`
  }
  return `将 ${count} 个候选视频存入线索列表。不会开始下载、处理或发布。`
}

const confirmAgentImport = async (message) => {
  const proposal = message?.importProposal
  const selectedIds = message?.selectedCandidateIds || []
  const targets = importTargets(message)
  if (!canConfirmAgentImport(message) || !agentSessionId.value) return
  try {
    await ElMessageBox.confirm(
      importConfirmationText(proposal, selectedIds.length, targets.length),
      '确认导入线索',
      { confirmButtonText: '确认执行', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (_) {
    return
  }
  message.importing = true
  try {
    const res = await agentApi.confirmImportProposal(proposal.proposalId, {
      sessionId: agentSessionId.value,
      selectedIds,
      targets
    })
    const data = res?.data || {}
    message.imported = true
    message.importResult = `已导入 ${data.createdCount || 0} 个线索，重复 ${data.duplicateCount || 0} 个${data.downloadJobCount ? `，已创建 ${data.downloadJobCount} 个下载任务` : ''}${data.workflowJobCount ? `，已创建 ${data.workflowJobCount} 个${proposal.requestedAction === 'workflow_publish' ? '处理发布' : '处理'}任务` : ''}${data.failedCount ? `，失败 ${data.failedCount} 个` : ''}。`
    ElMessage.success(message.importResult)
    window.dispatchEvent(new CustomEvent('vidferry:youtube-leads-imported'))
  } catch (error) {
    ElMessage.error(error?.message || '导入线索失败')
  } finally {
    message.importing = false
  }
}

const executionVideoStatus = (video = {}) => {
  if (Number(video.publishStatus) === 1) return '已发布'
  if (Number(video.translateStatus) === 1) return '已处理'
  if (Number(video.downloadStatus) === 1) return '已下载'
  return '待下载'
}

const defaultExecutionAccountIds = (proposal) => {
  const hints = new Set(proposal?.platformHints || [])
  if (hints.size === 0) return []
  const selectedPlatforms = new Set()
  return (proposal?.availableAccounts || []).reduce((ids, account) => {
    if (!hints.has(account.platformType) || selectedPlatforms.has(account.platformType)) return ids
    selectedPlatforms.add(account.platformType)
    ids.push(account.id)
    return ids
  }, [])
}

const executionTargets = (message) => {
  const selectedIds = new Set((message?.selectedExecutionAccountIds || []).map(value => Number(value)))
  return (message?.executionProposal?.availableAccounts || [])
    .filter(account => selectedIds.has(Number(account.id)))
    .map(account => ({ platformType: account.platformType, accountId: account.id }))
}

const normalizeExecutionAccountSelection = (message) => {
  const accounts = new Map((message?.executionProposal?.availableAccounts || []).map(account => [Number(account.id), account]))
  const selectedPlatforms = new Set()
  message.selectedExecutionAccountIds = (message.selectedExecutionAccountIds || [])
    .slice()
    .reverse()
    .filter(accountId => {
      const account = accounts.get(Number(accountId))
      if (!account || selectedPlatforms.has(account.platformType)) return false
      selectedPlatforms.add(account.platformType)
      return true
    })
    .reverse()
}

const canConfirmAgentExecution = (message) => {
  const proposal = message?.executionProposal
  if (!proposal?.proposalId || message.executing || message.executed) return false
  if (proposal.requiresTargets && executionTargets(message).length === 0) return false
  return !proposal.requiresSchedule || Boolean(message.executionScheduledAt)
}

const confirmAgentExecution = async (message) => {
  const proposal = message?.executionProposal
  if (!canConfirmAgentExecution(message) || !agentSessionId.value) return
  const targets = executionTargets(message)
  const targetText = targets.length ? `，发布到 ${targets.length} 个平台账号` : ''
  const scheduleText = proposal.requiresSchedule ? `，计划时间为 ${message.executionScheduledAt}` : ''
  try {
    await ElMessageBox.confirm(
      `将对“${proposal.video?.title || '当前视频'}”执行“${proposal.actionLabel}”${targetText}${scheduleText}。确认后会创建实际任务。`,
      '确认执行提案',
      { confirmButtonText: '确认执行', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (_) {
    return
  }
  message.executing = true
  try {
    const res = await agentApi.confirmExecutionProposal(proposal.proposalId, {
      sessionId: agentSessionId.value,
      targets,
      scheduledAt: message.executionScheduledAt || ''
    })
    const data = res?.data || {}
    message.executed = true
    message.executionResult = data.message || `${proposal.actionLabel}任务已创建。`
    ElMessage.success(message.executionResult)
    window.dispatchEvent(new CustomEvent('vidferry:youtube-leads-imported'))
  } catch (error) {
    ElMessage.error(error?.message || '执行提案失败')
  } finally {
    message.executing = false
  }
}

const handleAskAgentEvent = async (event) => {
  const detail = event?.detail || {}
  agentVideoContext.value = detail.videoContext || null
  agentIncludeVideoContext.value = Boolean(agentVideoContext.value)
  agentDrawerVisible.value = true
  await nextTick()
  agentInputRef.value?.focus()
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
    const agent = res?.data?.agent
    agentConfigWarning.value = agent?.enabled && agent?.requirePrepublishCheck && !agent?.multimodalModelConfigured
      ? 'Agent 发布前质检已启用，但多模态模型未配置；发布会被关键帧审核阻断。'
      : ''
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

  return new Date(timestamp).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const formatAgentSessionTime = (timestamp) => {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const handleMessageAction = (message) => {
  if (!message) return
  if (message.actionRoute?.path) {
    router.push(message.actionRoute)
  }
  notificationStore.acknowledgeMessage(message.id)
}

const handleUserCommand = async command => {
  if (command === 'users') return router.push('/user-management')
  if (command === 'password') return router.push('/change-password')
  if (command === 'logout') {
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

onMounted(() => {
  window.addEventListener('vidferry:ask-agent', handleAskAgentEvent)
  mobileSidebarQuery.addEventListener('change', syncMobileSidebar)
  if (!userStore.isLoggedIn) return
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
  window.removeEventListener('focus', refreshNotifications)
  window.removeEventListener('vidferry:ask-agent', handleAskAgentEvent)
  window.removeEventListener('focus', refreshFeishuRobotStatus)
  mobileSidebarQuery.removeEventListener('change', syncMobileSidebar)
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

#app {
  min-height: 100vh;
}

.el-container {
  height: 100vh;
}

.el-aside {
  background-color: #001529;
  color: #fff;
  height: 100vh;
  overflow: hidden;
  transition: width 0.3s;
  
  .sidebar {
    display: flex;
    flex-direction: column;
    height: 100%;
    
    .logo {
      height: 60px;
      padding: 0 16px;
      display: flex;
      align-items: center;
      background-color: #002140;
      overflow: hidden;
      
      .logo-img {
        width: 32px;
        height: 32px;
        margin-right: 12px;
      }
      
      h2 {
        color: #fff;
        font-size: 16px;
        font-weight: 600;
        white-space: nowrap;
        margin: 0;
      }
    }
    
    .sidebar-menu {
      border-right: none;
      flex: 1;
      
      .el-menu-item {
        display: flex;
        align-items: center;
        
        .el-icon {
          margin-right: 10px;
          font-size: 18px;
        }
      }
    }

    .sidebar-settings {
      padding: 12px;
      border-top: 1px solid rgba(255, 255, 255, 0.12);
      background: #001529;
    }

    .sidebar-settings-button {
      width: 100%;
      justify-content: center;
      border: 1px solid rgba(255, 255, 255, 0.14);
      background: linear-gradient(135deg, #2563eb, #0f9f8f);
      box-shadow: 0 8px 18px rgba(0, 0, 0, 0.18);

      .el-icon {
        margin-right: 6px;
      }

      &.is-circle {
        width: 40px;
        height: 40px;
        margin: 0 auto;

        .el-icon {
          margin-right: 0;
        }
      }
    }
  }
}

.el-header {
  background-color: #fff;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
  padding: 0;
  height: 60px;
  
  .header-content {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 100%;
    padding: 0 16px;
    
    .header-left {
      .toggle-sidebar {
        font-size: 20px;
        cursor: pointer;
        color: $text-regular;
        
        &:hover {
          color: $primary-color;
        }
      }
    }
    
    .header-right {
      display: flex;
      align-items: center;
      gap: 12px;

      .message-badge {
        line-height: 1;
      }

      .message-button {
        width: 36px;
        height: 36px;
        border: none;
        color: $text-regular;

        &:hover {
          color: $primary-color;
          background-color: $bg-color-page;
        }
      }

      .user-dropdown {
        display: flex;
        align-items: center;
        cursor: pointer;
        
        .username {
          margin: 0 8px;
          color: $text-regular;
        }
        
        .el-icon {
          font-size: 12px;
          color: $text-secondary;
        }
      }
    }
  }
}

.el-main {
  background-color: $bg-color-page;
  padding: 20px;
  overflow-y: auto;
}

.runtime-config-alert {
  margin-bottom: 16px;
}

.agent-entry {
  position: relative;
  width: 36px;
  height: 36px;
}

.agent-open-button {
  width: 36px;
  min-width: 36px;
  height: 36px;
  padding: 0;
  border: none;
  color: $text-regular;
  background: transparent;

  &:hover,
  &:focus {
    color: $primary-color;
    background-color: $bg-color-page;
  }
}

.audit-open-button {
  width: 36px;
  min-width: 36px;
  height: 36px;
  padding: 0;
  border: none;
  color: $text-regular;
  background: transparent;

  &:hover,
  &:focus {
    color: $primary-color;
    background-color: $bg-color-page;
  }
}

.agent-status-dot {
  position: absolute;
  right: 4px;
  bottom: 5px;
  width: 8px;
  height: 8px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: $success-color;
  pointer-events: none;

  &.is-warning {
    background: $warning-color;
  }
}

.feishu-robot-entry {
  position: relative;
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  color: $text-regular;

  .el-icon {
    font-size: 19px;
  }
}

.feishu-robot-status-dot {
  position: absolute;
  right: 4px;
  bottom: 5px;
  width: 8px;
  height: 8px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: #909399;

  &.is-connecting { background: #409eff; }
  &.is-connected { background: $success-color; }
  &.is-error { background: $danger-color; }
}

:global(.agent-drawer) {
  max-width: 100vw;
  box-shadow: -14px 0 34px rgba(0, 21, 41, 0.12);
}

:global(.agent-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 18px 20px 14px;
  border-bottom: 1px solid $border-lighter;
}

:global(.agent-drawer .el-drawer__body) {
  padding: 0;
}

.agent-drawer-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: $text-primary;

  > div {
    display: grid;
    gap: 3px;
  }

  strong {
    font-size: 16px;
    line-height: 1.2;
  }
}

.agent-drawer-kicker {
  color: $primary-color;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.agent-history-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 10px;
  color: $text-secondary;
  font-size: 12px;
}

.agent-history-filter {
  display: flex;
  align-items: center;
  gap: 6px;
}

.agent-history-filter :deep(.el-date-editor) {
  width: min(320px, 100%);
}

.agent-history-list {
  display: grid;
  gap: 8px;
}

.agent-history-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid $border-lighter;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s;

  &:hover,
  &.is-current {
    border-color: rgba(64, 158, 255, 0.55);
    background: #f6f9ff;
  }
}

.agent-history-item-main {
  min-width: 0;
  display: grid;
  gap: 4px;

  strong,
  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: $text-primary;
    font-size: 13px;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

.agent-history-item-meta {
  display: grid;
  justify-items: end;
  gap: 3px;
  color: $text-secondary;
  font-size: 11px;
  white-space: nowrap;
}

.agent-panel {
  height: 100%;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  background: $bg-color-page;
}

.agent-context-card {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 14px 16px 10px;
  padding: 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: #fff;
}

.agent-avatar {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 8px;
  color: #fff;
  background: linear-gradient(135deg, #2563eb, #0f9f8f);
  box-shadow: 0 8px 18px rgba(64, 158, 255, 0.18);

  .el-icon {
    font-size: 19px;
  }
}

.agent-context-copy {
  min-width: 0;
  display: grid;
  gap: 3px;

  strong {
    color: $text-primary;
    font-size: 14px;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

.agent-quick-panel {
  padding: 0 16px 14px;
  border-bottom: 1px solid $border-light;
}

.agent-section-title {
  margin-bottom: 8px;
  color: $text-secondary;
  font-size: 12px;
  font-weight: 600;
}

.agent-quick-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.agent-quick-actions :deep(.el-button) {
  width: 100%;
  min-height: 32px;
  margin-left: 0;
  justify-content: center;
  border-radius: 6px;
  color: $text-regular;
  background: #fff;
  white-space: normal;
  line-height: 1.3;
  padding: 6px 8px;
}

.agent-messages {
  overflow-y: auto;
  padding: 16px;
  display: grid;
  align-content: start;
  gap: 12px;
}

.agent-older-loading {
  min-height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: $text-secondary;
  font-size: 12px;
}

.agent-message {
  display: grid;
  gap: 6px;
  max-width: 90%;

  &.is-user {
    justify-self: end;

    .agent-message-content {
      background: #2563eb;
      color: #fff;
      border-color: #2563eb;
    }
  }

  &.is-assistant {
    justify-self: start;

    .agent-message-content {
      background: #fff;
      color: $text-primary;
      border: 1px solid $border-light;
    }
  }
}

.agent-message-role {
  color: $text-secondary;
  font-size: 12px;
  line-height: 1;
}

.agent-message-content {
  white-space: pre-wrap;
  line-height: 1.6;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 14px;
  box-shadow: 0 3px 10px rgba(0, 21, 41, 0.04);
}

.agent-thinking {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 22px;
  color: $text-regular;
}

.agent-thinking-icon {
  color: $primary-color;
  font-size: 16px;
}

.agent-result-card {
  overflow: hidden;
  border: 1px solid $border-lighter;
  border-radius: 6px;
  background: #fff;
}

.agent-card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  color: $text-regular;
  background: #f6f9ff;
  font-size: 12px;

  strong {
    color: $primary-color;
    font-size: 14px;
  }
}

.agent-card-item {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  border-top: 1px solid $border-lighter;

  strong {
    overflow: hidden;
    color: $text-primary;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  span {
    overflow: hidden;
    color: $text-secondary;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.agent-import-proposal {
  overflow: hidden;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  background: #fff;
}

.agent-import-candidates {
  display: grid;
}

.agent-import-candidate {
  display: flex;
  width: 100%;
  min-height: 54px;
  align-items: center;
  padding: 9px 10px;
  border-top: 1px solid $border-lighter;
}

.agent-import-candidate :deep(.el-checkbox) {
  flex: 0 0 auto;
  margin: 0;
}

.agent-import-copy {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  gap: 3px;
  padding-left: 10px;
  line-height: 1.35;
}

.agent-import-title,
.agent-import-meta {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-import-title {
  color: $text-primary;
  font-size: 12px;
}

.agent-import-meta,
.agent-import-result {
  color: $text-secondary;
  font-size: 12px;
}

.agent-import-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px;
  border-top: 1px solid $border-lighter;
}

.agent-import-actions :deep(.el-button) {
  margin-left: 0;
}

.agent-import-result {
  padding: 10px;
  border-top: 1px solid $border-lighter;
}

.agent-execution-proposal {
  overflow: hidden;
  border: 1px solid #f6c977;
  border-radius: 6px;
  background: #fffdf7;
}

.agent-execution-video {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-top: 1px solid #f7dfad;
}

.agent-execution-video strong,
.agent-execution-video span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-execution-video strong {
  color: $text-primary;
  font-size: 12px;
}

.agent-execution-video span,
.agent-execution-result {
  color: $text-secondary;
  font-size: 12px;
}

.agent-execution-accounts,
.agent-execution-schedule {
  width: calc(100% - 20px);
  margin: 10px 10px 0;
}

.agent-execution-result {
  padding: 10px;
  border-top: 1px solid #f7dfad;
}

.agent-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.agent-actions :deep(.el-button) {
  margin-left: 0;
}

.agent-message-tools {
  display: flex;
  gap: 2px;
  min-height: 24px;
}

.agent-message-tools :deep(.el-button) {
  width: 24px;
  height: 24px;
  margin-left: 0;
  padding: 0;
  color: $text-secondary;

  &:hover,
  &:focus-visible {
    color: $primary-color;
    background: #eef6ff;
  }
}

.agent-message.is-user .agent-message-tools {
  justify-self: end;
}

.agent-empty {
  align-self: center;
  justify-self: center;
  width: 100%;
  min-height: 220px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  color: $text-secondary;
  text-align: center;

  .el-icon {
    width: 42px;
    height: 42px;
    display: grid;
    place-items: center;
    border-radius: 8px;
    color: $primary-color;
    background: #eef6ff;
    font-size: 22px;
  }

  strong {
    color: $text-regular;
    font-size: 14px;
  }

  span {
    font-size: 12px;
  }
}

.agent-input {
  display: grid;
  gap: 10px;
  padding: 14px 16px 16px;
  border-top: 1px solid $border-light;
  background: #fff;
}

.agent-video-context {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #c6e2ff;
  border-radius: 6px;
  background: #f4f9ff;
  transition: border-color 0.2s, background-color 0.2s, opacity 0.2s;

  > span {
    overflow: hidden;
    color: $text-regular;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &.is-disabled {
    border-color: $border-lighter;
    background: $bg-color-page;
    opacity: 0.68;
  }
}

.agent-input :deep(.el-textarea__inner) {
  border-radius: 6px;
  background: #fbfcff;
}

.agent-input :deep(.el-button) {
  height: 34px;
  border-radius: 6px;
}

:global(.message-popover) {
  padding: 0;
}

.message-panel {
  max-height: 420px;
  overflow: hidden;

  .message-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    border-bottom: 1px solid $border-light;
    font-weight: 600;
    color: $text-primary;
  }

  .message-list {
    max-height: 360px;
    overflow-y: auto;
  }

  .message-item {
    padding: 14px 16px;
    border-bottom: 1px solid $border-lighter;
    background-color: #fff;

    &:last-child {
      border-bottom: none;
    }

    &.is-read {
      background-color: #fafafa;

      .message-item-content,
      .message-item-time {
        color: $text-secondary;
      }
    }
  }

  .message-item-title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 8px;
    color: $text-primary;
    font-weight: 600;
  }

  .message-item-content {
    color: $text-regular;
    font-size: 13px;
    line-height: 1.5;
  }

  .message-item-time {
    margin-top: 8px;
    color: $text-secondary;
    font-size: 12px;
  }

  .message-item-actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 10px;
  }
}
</style>
