<template>
  <div id="app">
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
            <el-menu-item index="/account-management">
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
            <el-menu-item index="/workflow-statistics">
              <el-icon><DataAnalysis /></el-icon>
              <span>处理统计</span>
            </el-menu-item>
            <el-menu-item index="/about">
              <el-icon><DataAnalysis /></el-icon>
              <span>关于</span>
            </el-menu-item>
          </el-menu>
          <div class="sidebar-settings">
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
              <el-popover
                placement="bottom-end"
                trigger="click"
                width="380"
                popper-class="message-popover"
              >
                <template #reference>
                  <el-badge
                    :value="notificationStore.unreadCount"
                    :hidden="!notificationStore.hasUnread"
                    :max="99"
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
                    <el-tag v-if="notificationStore.hasUnread" size="small" type="danger">
                      {{ notificationStore.unreadCount }} 未读
                    </el-tag>
                  </div>

                  <el-empty
                    v-if="notificationStore.visibleMessages.length === 0"
                    description="暂无消息"
                    :image-size="72"
                  />

                  <div v-else class="message-list">
                    <div
                      v-for="message in notificationStore.visibleMessages"
                      :key="message.id"
                      class="message-item"
                      :class="{ 'is-read': message.acknowledged }"
                    >
                      <div class="message-item-title">
                        <span>{{ message.title }}</span>
                        <el-tag size="small" :type="message.acknowledged ? 'info' : 'danger'">
                          {{ message.acknowledged ? '已知晓' : '异常' }}
                        </el-tag>
                      </div>
                      <div class="message-item-content">{{ message.content }}</div>
                      <div class="message-item-time">{{ formatMessageTime(message.updatedAt) }}</div>
                      <div class="message-item-actions">
                        <el-button
                          v-if="message.actionUrl"
                          size="small"
                          type="warning"
                          link
                          @click="handleMessageAction(message)"
                        >
                          {{ message.actionLabel || '去解决' }}
                        </el-button>
                        <el-button
                          size="small"
                          type="primary"
                          link
                          :disabled="message.acknowledged"
                          @click="notificationStore.acknowledgeMessage(message.id)"
                        >
                          已知晓
                        </el-button>
                        <el-button
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
    >
      <template #header>
        <div class="agent-drawer-header">
          <div>
            <span class="agent-drawer-kicker">PROJECT AGENT</span>
            <strong>Vidferry Agent</strong>
          </div>
          <el-tag size="small" effect="plain" :type="agentConfigWarning ? 'warning' : 'success'">
            只读
          </el-tag>
        </div>
      </template>
      <div class="agent-panel">
        <div class="agent-context-card">
          <div class="agent-avatar">
            <el-icon><ChatDotRound /></el-icon>
          </div>
          <div class="agent-context-copy">
            <strong>只读项目管家</strong>
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
        <div class="agent-messages">
          <div
            v-for="message in agentMessages"
            :key="message.id"
            class="agent-message"
            :class="`is-${message.role}`"
          >
            <div class="agent-message-role">{{ message.role === 'user' ? '你' : 'Agent' }}</div>
            <div class="agent-message-content">{{ message.content }}</div>
          </div>
          <div v-if="agentMessages.length === 0" class="agent-empty">
            <el-icon><ChatDotRound /></el-icon>
            <strong>还没有对话</strong>
            <span>从一个快捷问题开始。</span>
          </div>
        </div>
        <div class="agent-input">
          <el-input
            v-model="agentInput"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="例如：已处理但还没发布的视频有哪些？"
            @keydown.ctrl.enter.prevent="sendAgentMessage()"
          />
          <el-button type="primary" :loading="agentLoading" @click="sendAgentMessage()">
            发送
          </el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElNotification } from 'element-plus'
import {
  HomeFilled, User, DataAnalysis,
  Fold, Picture, Upload, Search, Bell, Setting, ChatDotRound
} from '@element-plus/icons-vue'
import { accountApi } from '@/api/account'
import { agentApi } from '@/api/agent'
import { commonApi } from '@/api/common'
import { useAccountStore } from '@/stores/account'
import { useNotificationStore } from '@/stores/notification'

const route = useRoute()
const router = useRouter()
const accountStore = useAccountStore()
const notificationStore = useNotificationStore()
const ACCOUNT_CHECK_INTERVAL_MS = 3 * 60 * 1000
let accountCheckTimer = null
const llmConfigWarning = ref('')
const agentConfigWarning = ref('')
const agentDrawerVisible = ref(false)
const agentLoading = ref(false)
const agentInput = ref('')
const agentSessionId = ref(localStorage.getItem('vidferry:agent-session-id') || '')
const agentMessages = ref([])
let agentMessageId = 1

const agentQuickQuestions = [
  '完整流程现在有哪些步骤？',
  '现在待处理的视频有哪些？',
  '已处理但还没发布的视频有哪些？',
  '已发布的视频有哪些？',
  '最近失败的任务是什么原因？',
  '账号状态怎么样？'
]

const agentRouteLabels = {
  '/': '首页',
  '/youtube-research': '视频采集处理',
  '/account-management': '账号管理',
  '/material-management': '视频素材管理',
  '/publish-center': '发布中心',
  '/workflow-statistics': '处理统计',
  '/about': '关于'
}

// 当前激活的菜单项
const activeMenu = computed(() => {
  return route.path
})

// 侧边栏折叠状态
const isCollapse = ref(false)

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
      notificationStore.syncAccountAbnormalMessages(accountStore.accounts)
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

const pushAgentMessage = (role, content) => {
  agentMessages.value.push({
    id: agentMessageId++,
    role,
    content: String(content || '')
  })
}

const sendAgentMessage = async (presetMessage = '', extraContext = {}) => {
  const message = String(presetMessage || agentInput.value || '').trim()
  if (!message || agentLoading.value) return
  agentDrawerVisible.value = true
  agentInput.value = ''
  pushAgentMessage('user', message)
  agentLoading.value = true
  try {
    const res = await agentApi.chat({
      message,
      sessionId: agentSessionId.value,
      context: {
        ...currentAgentContext.value,
        ...extraContext
      }
    })
    const data = res?.data || {}
    if (data.sessionId) {
      agentSessionId.value = data.sessionId
      localStorage.setItem('vidferry:agent-session-id', data.sessionId)
    }
    pushAgentMessage('assistant', data.answer || '我暂时没有查到结果。')
  } catch (error) {
    pushAgentMessage('assistant', error.message || 'Agent 暂时不可用，请稍后再试。')
    ElMessage.error(error.message || 'Agent 暂时不可用')
  } finally {
    agentLoading.value = false
  }
}

const handleAskAgentEvent = (event) => {
  const detail = event?.detail || {}
  const message = detail.message || ''
  agentDrawerVisible.value = true
  if (message) {
    sendAgentMessage(message, detail.context || {})
  }
}

const refreshRuntimeConfigStatus = async () => {
  try {
    const res = await commonApi.getRuntimeConfigStatus()
    const llm = res?.data?.llm
    if (!llm || llm.ready) {
      llmConfigWarning.value = ''
    }
    if (llm && !llm.ready) {
      const missingText = Array.isArray(llm.missing) && llm.missing.length
        ? ` 缺失：${llm.missing.join('、')}`
        : ''
      llmConfigWarning.value = `${llm.message || 'LLM 不可用，请检查配置并重启后端。'}${missingText}`

      ElNotification({
        title: 'LLM 配置不可用',
        message: llmConfigWarning.value,
        type: 'error',
        position: 'top-right',
        duration: 10000
      })
    }

    const agent = res?.data?.agent
    agentConfigWarning.value = agent?.enabled && agent?.requirePrepublishCheck && !agent?.visionModelConfigured
      ? 'Agent 发布前质检已启用，但 AGENT_VISION_MODEL 未配置；发布会被关键帧审核阻断。'
      : ''
  } catch (error) {
    console.error('运行时配置状态检查失败:', error)
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

const handleMessageAction = (message) => {
  if (!message?.actionUrl) return
  window.open(message.actionUrl, '_blank', 'noopener,noreferrer')
  notificationStore.acknowledgeMessage(message.id)
}

onMounted(() => {
  refreshRuntimeConfigStatus()
  refreshGlobalAccountMessages()
  accountCheckTimer = window.setInterval(refreshGlobalAccountMessages, ACCOUNT_CHECK_INTERVAL_MS)
  window.addEventListener('vidferry:ask-agent', handleAskAgentEvent)
})

onBeforeUnmount(() => {
  if (accountCheckTimer) {
    window.clearInterval(accountCheckTimer)
    accountCheckTimer = null
  }
  window.removeEventListener('vidferry:ask-agent', handleAskAgentEvent)
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

:global(.agent-drawer) {
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
