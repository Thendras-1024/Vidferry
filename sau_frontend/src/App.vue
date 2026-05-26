<template>
  <div id="app">
    <el-container>
      <el-aside :width="isCollapse ? '64px' : '200px'">
        <div class="sidebar">
          <div class="logo">
            <img v-show="isCollapse" src="/vite.svg" alt="Logo" class="logo-img">
            <h2 v-show="!isCollapse">Vidferry V1.0</h2>
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
              <span>素材管理</span>
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
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  HomeFilled, User, DataAnalysis,
  Fold, Picture, Upload, Search, Bell, Setting
} from '@element-plus/icons-vue'
import { accountApi } from '@/api/account'
import { useAccountStore } from '@/stores/account'
import { useNotificationStore } from '@/stores/notification'

const route = useRoute()
const router = useRouter()
const accountStore = useAccountStore()
const notificationStore = useNotificationStore()
const ACCOUNT_CHECK_INTERVAL_MS = 3 * 60 * 1000
let accountCheckTimer = null

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

const formatMessageTime = (timestamp) => {
  if (!timestamp) return ''

  return new Date(timestamp).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

onMounted(() => {
  refreshGlobalAccountMessages()
  accountCheckTimer = window.setInterval(refreshGlobalAccountMessages, ACCOUNT_CHECK_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (accountCheckTimer) {
    window.clearInterval(accountCheckTimer)
    accountCheckTimer = null
  }
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
