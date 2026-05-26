<template>
  <div class="account-management">
    <section class="page-hero">
      <div>
        <span class="eyebrow">ACCOUNT CONTROL</span>
        <h1>账号管理</h1>
        <p>集中维护抖音、B站、快手、视频号、小红书账号，异常账号可在当前页面手动重新连接。</p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
        <el-button @click="fetchAccounts" :loading="appStore.isAccountRefreshing">
          <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
          <span>刷新状态</span>
        </el-button>
      </div>
    </section>

    <section class="metric-grid">
      <button class="metric-card" type="button" @click="activeTab = 'all'">
        <span>账号总数</span>
        <strong>{{ accountSummary.total }}</strong>
        <small>当前接入账号</small>
      </button>
      <button class="metric-card" type="button" @click="activeTab = 'normal'">
        <span>正常账号</span>
        <strong>{{ accountSummary.normal }}</strong>
        <small>可用于发布</small>
      </button>
      <button class="metric-card tone-danger" type="button" @click="activeTab = 'abnormal'">
        <span>异常账号</span>
        <strong>{{ accountSummary.abnormal }}</strong>
        <small>需要手动重新连接</small>
      </button>
      <button class="metric-card" type="button" @click="activeTab = 'all'">
        <span>验证中</span>
        <strong>{{ accountSummary.verifying }}</strong>
        <small>等待平台登录结果</small>
      </button>
    </section>

    <el-card class="account-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <div>
            <span class="panel-kicker">ACCOUNT LIST</span>
            <h2>账号列表</h2>
          </div>
          <div class="panel-tools">
            <el-input
              v-model="searchKeyword"
              placeholder="搜索账号名称"
              prefix-icon="Search"
              clearable
              @clear="handleSearch"
              @input="handleSearch"
            />
            <el-segmented v-model="activeTab" :options="accountFilterOptions" />
          </div>
        </div>
      </template>

      <el-table :data="visibleAccounts" style="width: 100%" empty-text="暂无账号数据">
        <el-table-column label="账号" min-width="260">
          <template #default="{ row }">
            <div class="account-cell">
              <el-avatar :src="getDefaultAvatar(row.name)" :size="40" />
              <div>
                <strong>{{ row.name }}</strong>
                <span>{{ row.filePath || '未显示 Cookie 路径' }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="平台" width="110">
          <template #default="{ row }">
            <el-tag :type="getPlatformTagType(row.platform)" effect="plain">{{ row.platform }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag
              :type="getStatusTagType(row.status)"
              effect="light"
              :class="{ 'clickable-status': isStatusClickable(row.status) }"
              @click="handleStatusClick(row)"
            >
              <el-icon :class="row.status === '验证中' ? 'is-loading' : ''" v-if="row.status === '验证中'">
                <Loading />
              </el-icon>
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="360">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button size="small" @click="handleEdit(row)">编辑</el-button>
              <el-button v-if="row.status === '异常'" size="small" type="warning" @click="handleManualReconnect(row)">重新连接</el-button>
              <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(row)">下载Cookie</el-button>
              <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(row)">上传Cookie</el-button>
              <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogType === 'add' ? '添加账号' : (dialogType === 'relogin' ? '重新连接账号' : '编辑账号')"
      width="500px"
      :close-on-click-modal="false"
      :close-on-press-escape="!sseConnecting"
      :show-close="!sseConnecting"
    >
      <el-form :model="accountForm" label-width="80px" :rules="rules" ref="accountFormRef">
        <el-form-item label="平台" prop="platform">
          <el-select
            v-model="accountForm.platform"
            placeholder="请选择平台"
            style="width: 100%"
            :disabled="dialogType === 'edit' || dialogType === 'relogin' || sseConnecting"
          >
            <el-option label="快手" value="快手" />
            <el-option label="抖音" value="抖音" />
            <el-option label="B站" value="B站" />
            <el-option label="视频号" value="视频号" />
            <el-option label="小红书" value="小红书" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="accountForm.name" placeholder="请输入账号名称" :disabled="sseConnecting" />
        </el-form-item>

        <div v-if="sseConnecting" class="qrcode-container">
          <div v-if="qrCodeData && !loginStatus" class="qrcode-wrapper">
            <p class="qrcode-tip">请使用对应平台 APP 扫描二维码登录</p>
            <img :src="qrCodeData" alt="登录二维码" class="qrcode-image" />
          </div>
          <div v-else-if="!qrCodeData && !loginStatus" class="loading-wrapper">
            <el-icon class="is-loading"><Refresh /></el-icon>
            <span>请求中...</span>
          </div>
          <div v-else-if="loginStatus === '200'" class="success-wrapper">
            <el-icon><CircleCheckFilled /></el-icon>
            <span>{{ dialogType === 'relogin' ? '重新连接成功' : '添加成功' }}</span>
          </div>
          <div v-else-if="loginStatus === '500'" class="error-wrapper">
            <el-icon><CircleCloseFilled /></el-icon>
            <span>{{ loginErrorMessage || (dialogType === 'relogin' ? '重新连接失败，请稍后再试' : '添加失败，请稍后再试') }}</span>
          </div>
        </div>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="submitAccountForm" :loading="sseConnecting" :disabled="sseConnecting">
            {{ sseConnecting ? '请求中' : '确认' }}
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { Refresh, CircleCheckFilled, CircleCloseFilled, Download, Upload, Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi } from '@/api/account'
import { useAccountStore } from '@/stores/account'
import { useAppStore } from '@/stores/app'
import { useNotificationStore } from '@/stores/notification'
import { http } from '@/utils/request'

// 获取账号状态管理
const accountStore = useAccountStore()
// 获取应用状态管理
const appStore = useAppStore()
const notificationStore = useNotificationStore()

// 当前激活的标签页
const activeTab = ref('all')

// 搜索关键词
const searchKeyword = ref('')

const accountFilterOptions = [
  { label: '全部', value: 'all' },
  { label: '正常', value: 'normal' },
  { label: '异常', value: 'abnormal' },
  { label: '验证中', value: 'verifying' },
  { label: '抖音', value: 'douyin' },
  { label: 'B站', value: 'bilibili' },
  { label: '快手', value: 'kuaishou' },
  { label: '视频号', value: 'channels' },
  { label: '小红书', value: 'xiaohongshu' }
]

// 获取账号数据（只读取当前状态，不验证、不重连）
const fetchAccountsQuick = async () => {
  try {
    const res = await accountApi.getAccounts()
    if (res.code === 200 && res.data) {
      accountStore.setAccounts(res.data)
      notificationStore.syncAccountAbnormalMessages(accountStore.accounts)
    }
  } catch (error) {
    console.error('快速获取账号数据失败:', error)
  }
}

// 获取账号数据（只刷新当前状态，不验证、不重连）
const fetchAccounts = async () => {
  if (appStore.isAccountRefreshing) return

  appStore.setAccountRefreshing(true)

  try {
    const res = await accountApi.getAccounts()
    if (res.code === 200 && res.data) {
      accountStore.setAccounts(res.data)
      notificationStore.syncAccountAbnormalMessages(accountStore.accounts)
      ElMessage.success('账号数据已刷新')
      // 标记为已访问
      if (appStore.isFirstTimeAccountManagement) {
        appStore.setAccountManagementVisited()
      }
    } else {
      ElMessage.error('获取账号数据失败')
    }
  } catch (error) {
    console.error('获取账号数据失败:', error)
    ElMessage.error('获取账号数据失败')
  } finally {
    appStore.setAccountRefreshing(false)
  }
}

// 页面加载时获取账号数据
onMounted(() => {
  fetchAccountsQuick()
})

// 获取平台标签类型
const getPlatformTagType = (platform) => {
  const typeMap = {
    '快手': 'success',
    '抖音': 'danger',
    'B站': 'primary',
    '视频号': 'warning',
    '小红书': 'info'
  }
  return typeMap[platform] || 'info'
}

// 判断状态是否可点击（异常状态可点击）
const isStatusClickable = (status) => {
  return status === '异常'; // 只有异常状态可点击，验证中不可点击
}

// 获取状态标签类型
const getStatusTagType = (status) => {
  if (status === '验证中') {
    return 'info'; // 验证中使用灰色
  } else if (status === '正常') {
    return 'success'; // 正常使用绿色
  } else {
    return 'danger'; // 无效使用红色
  }
}

// 处理状态点击事件
const handleStatusClick = (row) => {
  if (isStatusClickable(row.status)) {
    notificationStore.syncAccountAbnormalMessages(accountStore.accounts)
    ElMessage.warning('账号异常信息已同步到右上角消息中心，请手动点击“重新连接”处理')
  }
}

// 过滤后的账号列表
const filteredAccounts = computed(() => {
  if (!searchKeyword.value) return accountStore.accounts
  return accountStore.accounts.filter(account =>
    account.name.includes(searchKeyword.value)
  )
})

// 按平台过滤的账号列表
const filteredKuaishouAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '快手')
})

const filteredDouyinAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '抖音')
})

const filteredBilibiliAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === 'B站')
})

const filteredChannelsAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '视频号')
})

const filteredXiaohongshuAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '小红书')
})

const accountSummary = computed(() => {
  const accounts = accountStore.accounts
  return {
    total: accounts.length,
    normal: accounts.filter(account => account.status === '正常').length,
    abnormal: accounts.filter(account => account.status !== '正常' && account.status !== '验证中').length,
    verifying: accounts.filter(account => account.status === '验证中').length
  }
})

const visibleAccounts = computed(() => {
  const status = activeTab.value
  if (status === 'normal') return filteredAccounts.value.filter(account => account.status === '正常')
  if (status === 'abnormal') return filteredAccounts.value.filter(account => account.status !== '正常' && account.status !== '验证中')
  if (status === 'verifying') return filteredAccounts.value.filter(account => account.status === '验证中')
  if (status === 'douyin') return filteredDouyinAccounts.value
  if (status === 'bilibili') return filteredBilibiliAccounts.value
  if (status === 'kuaishou') return filteredKuaishouAccounts.value
  if (status === 'channels') return filteredChannelsAccounts.value
  if (status === 'xiaohongshu') return filteredXiaohongshuAccounts.value
  return filteredAccounts.value
})

// 搜索处理
const handleSearch = () => {
  // 搜索逻辑已通过计算属性实现
}

// 对话框相关
const dialogVisible = ref(false)
const dialogType = ref('add') // 'add' 或 'edit'
const accountFormRef = ref(null)

// 账号表单
const accountForm = reactive({
  id: null,
  name: '',
  platform: '',
  status: '正常'
})

// 表单验证规则
const rules = {
  platform: [{ required: true, message: '请选择平台', trigger: 'change' }],
  name: [{ required: true, message: '请输入账号名称', trigger: 'blur' }]
}

// SSE连接状态
const sseConnecting = ref(false)
const qrCodeData = ref('')
const loginStatus = ref('')
const loginErrorMessage = ref('')

// 添加账号
const handleAddAccount = () => {
  dialogType.value = 'add'
  Object.assign(accountForm, {
    id: null,
    name: '',
    platform: '',
    status: '正常'
  })
  // 重置SSE状态
  sseConnecting.value = false
  qrCodeData.value = ''
  loginStatus.value = ''
  dialogVisible.value = true
}

// 编辑账号
const handleEdit = (row) => {
  dialogType.value = 'edit'
  Object.assign(accountForm, {
    id: row.id,
    name: row.name,
    platform: row.platform,
    status: row.status
  })
  dialogVisible.value = true
}

// 删除账号
const handleDelete = (row) => {
  ElMessageBox.confirm(
    `确定要删除账号 ${row.name} 吗？`,
    '警告',
    {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    }
  )
    .then(async () => {
      try {
        // 调用API删除账号
        const response = await accountApi.deleteAccount(row.id)

        if (response.code === 200) {
          // 从状态管理中删除账号
          accountStore.deleteAccount(row.id)
          notificationStore.syncAccountAbnormalMessages(accountStore.accounts)
          ElMessage({
            type: 'success',
            message: '删除成功',
          })
        } else {
          ElMessage.error(response.msg || '删除失败')
        }
      } catch (error) {
        console.error('删除账号失败:', error)
        ElMessage.error('删除账号失败')
      }
    })
    .catch(() => {
      // 取消删除
    })
}

// 下载Cookie文件
const handleDownloadCookie = (row) => {
  // 从后端获取Cookie文件
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5409'
  const downloadUrl = `${baseUrl}/downloadCookie?filePath=${encodeURIComponent(row.filePath)}`

  // 创建一个隐藏的链接来触发下载
  const link = document.createElement('a')
  link.href = downloadUrl
  link.download = `${row.name}_cookie.json`
  link.target = '_blank'
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

// 上传Cookie文件
const handleUploadCookie = (row) => {
  // 创建一个隐藏的文件输入框
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.style.display = 'none'
  document.body.appendChild(input)

  input.onchange = async (event) => {
    const file = event.target.files[0]
    if (!file) {
      document.body.removeChild(input)
      return
    }

    // 检查文件类型
    if (!file.name.endsWith('.json')) {
      ElMessage.error('请选择JSON格式的Cookie文件')
      document.body.removeChild(input)
      return
    }

    try {
      // 创建FormData对象
      const formData = new FormData()
      formData.append('file', file)
      formData.append('id', row.id)
      formData.append('platform', row.platform)

      // 使用统一的http封装发送上传请求
      const result = await http.upload('/uploadCookie', formData)

      ElMessage.success('Cookie文件上传成功')
      // 刷新账号列表以显示更新
      fetchAccounts()
    } catch (error) {
      ElMessage.error('Cookie文件上传失败')
    } finally {
      document.body.removeChild(input)
    }
  }

  input.click()
}

// 用户手动重新连接账号
const handleManualReconnect = (row) => {
  // 设置表单信息
  dialogType.value = 'relogin'
  Object.assign(accountForm, {
    id: row.id,
    name: row.name,
    platform: row.platform,
    status: row.status
  })

  // 重置SSE状态
  sseConnecting.value = false
  qrCodeData.value = ''
  loginStatus.value = ''

  // 显示对话框
  dialogVisible.value = true
}

// 获取默认头像
const getDefaultAvatar = (name) => {
  // 使用简单的默认头像，可以基于用户名生成不同的颜色
  return `https://ui-avatars.com/api/?name=${encodeURIComponent(name)}&background=random`
}

// SSE事件源对象
let eventSource = null

// 关闭SSE连接
const closeSSEConnection = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

// 建立SSE连接
const connectSSE = (platform, name, accountId = null) => {
  // 关闭可能存在的连接
  closeSSEConnection()

  // 设置连接状态
  sseConnecting.value = true
  qrCodeData.value = ''
  loginStatus.value = ''
  loginErrorMessage.value = ''

  // 获取平台类型编号
  const platformTypeMap = {
    '小红书': '1',
    '视频号': '2',
    '抖音': '3',
    '快手': '4',
    'B站': '5'
  }

  const type = platformTypeMap[platform] || '1'

  // 创建SSE连接
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5409'
  const params = new URLSearchParams({
    type,
    id: name
  })
  if (accountId) {
    params.set('accountId', accountId)
  }
  const url = `${baseUrl}/login?${params.toString()}`

  eventSource = new EventSource(url)

  // 监听消息
  eventSource.onmessage = (event) => {
    const data = event.data

    if (data.startsWith('ERROR::')) {
      loginErrorMessage.value = data.slice('ERROR::'.length) || '登录失败'
      return
    }

    // 如果还没有二维码数据，且收到图片数据，显示二维码
    if (!qrCodeData.value && (data.startsWith('data:image') || data.length > 100)) {
      try {
        if (data.startsWith('data:image')) {
          qrCodeData.value = data
        } else {
          qrCodeData.value = `data:image/png;base64,${data}`
        }
      } catch (error) {
        // 处理二维码数据出错
      }
    }
    // 如果收到状态码
    else if (data === '200' || data === '500') {
      loginStatus.value = data

      // 如果登录成功
      if (data === '200') {
        setTimeout(() => {
          // 关闭连接
          closeSSEConnection()

          // 1秒后关闭对话框并开始刷新
          setTimeout(() => {
            dialogVisible.value = false
            sseConnecting.value = false

            // 根据是否是重新登录显示不同提示
            ElMessage.success(dialogType.value === 'relogin' ? '重新连接成功' : '账号添加成功')

            // 显示更新账号信息提示
            ElMessage({
              type: 'info',
              message: '正在同步账号信息...',
              duration: 0
            })

            // 触发刷新操作
            fetchAccounts().then(() => {
              // 刷新完成后关闭提示
              ElMessage.closeAll()
              ElMessage.success('账号信息已更新')
            })
          }, 1000)
        }, 1000)
      } else {
        // 登录失败，关闭连接
        closeSSEConnection()
        ElMessage.error(loginErrorMessage.value || '二维码获取或登录失败，请检查平台页面是否可访问后重试')

        // 2秒后重置状态，允许重试
        setTimeout(() => {
          sseConnecting.value = false
          qrCodeData.value = ''
          loginStatus.value = ''
          loginErrorMessage.value = ''
        }, 2000)
      }
    }
  }

  // 监听错误
  eventSource.onerror = (error) => {
    if (loginStatus.value === '200' || loginStatus.value === '500') {
      closeSSEConnection()
      return
    }
    console.error('SSE连接错误:', error)
    ElMessage.error('连接服务器失败，请稍后再试')
    closeSSEConnection()
    sseConnecting.value = false
  }
}

// 提交账号表单
const submitAccountForm = () => {
  accountFormRef.value.validate(async (valid) => {
    if (valid) {
      if (dialogType.value === 'add') {
        // 建立SSE连接
        connectSSE(accountForm.platform, accountForm.name)
      } else if (dialogType.value === 'relogin') {
        // 只有用户确认后才重新连接
        connectSSE(accountForm.platform, accountForm.name, accountForm.id)
      } else {
        // 编辑账号逻辑
        try {
          // 将平台名称转换为类型数字
          const platformTypeMap = {
            '小红书': 1,
            '视频号': 2,
            '抖音': 3,
            '快手': 4,
            'B站': 5
          };
          const type = platformTypeMap[accountForm.platform] || 1;

          const res = await accountApi.updateAccount({
            id: accountForm.id,
            type: type,
            userName: accountForm.name
          })
          if (res.code === 200) {
            // 更新状态管理中的账号
            const updatedAccount = {
              id: accountForm.id,
              name: accountForm.name,
              platform: accountForm.platform,
              status: accountForm.status // Keep the existing status
            };
            accountStore.updateAccount(accountForm.id, updatedAccount)
            ElMessage.success('更新成功')
            dialogVisible.value = false
            // 刷新账号列表
            fetchAccounts()
          } else {
            ElMessage.error(res.msg || '更新账号失败')
          }
        } catch (error) {
          console.error('更新账号失败:', error)
          ElMessage.error('更新账号失败')
        }
      }
    } else {
      return false
    }
  })
}

// 组件卸载前关闭SSE连接
onBeforeUnmount(() => {
  closeSSEConnection()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

$panel-border: #dce6f2;
$panel-shadow: 0 12px 28px rgba(28, 55, 90, 0.08);
$accent-blue: #2563eb;
$ink-strong: #172033;

.account-management {
  display: grid;
  gap: 16px;

  :deep(.el-card) {
    border: 1px solid $panel-border;
    border-radius: 8px;
    box-shadow: $panel-shadow;
  }

  :deep(.el-card__header) {
    padding: 14px 16px;
  }

  :deep(.el-table th.el-table__cell) {
    background: #f8fbff;
    color: #5c6678;
    font-weight: 600;
  }
}

.page-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.1), rgba(15, 159, 143, 0.08) 42%, rgba(255, 255, 255, 0.94)), #fff;
  box-shadow: $panel-shadow;

  h1 {
    margin: 4px 0 8px;
    color: $ink-strong;
    font-size: 25px;
    line-height: 1.25;
    font-weight: 700;
  }

  p {
    margin: 0;
    color: #5b667a;
    font-size: 14px;
    line-height: 1.7;
  }
}

.eyebrow,
.panel-kicker {
  color: $accent-blue;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
}

.hero-actions,
.table-actions,
.panel-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-card {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 8px;
  background: #fff;
  text-align: left;
  box-shadow: 0 8px 18px rgba(28, 55, 90, 0.05);
  cursor: pointer;

  span,
  small {
    color: $text-secondary;
    font-size: 13px;
  }

  strong {
    color: $ink-strong;
    font-size: 24px;
    line-height: 1;
  }

  &.tone-danger {
    border-color: rgba(239, 68, 68, 0.22);
  }
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  h2 {
    margin: 2px 0 0;
    color: $ink-strong;
    font-size: 18px;
    line-height: 1.3;
  }
}

.panel-tools {
  justify-content: flex-end;

  .el-input {
    width: 240px;
  }
}

.account-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;

  > div {
    display: grid;
    gap: 4px;
    min-width: 0;
  }

  strong,
  span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: $ink-strong;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

.clickable-status {
  cursor: pointer;
}

.is-loading {
  animation: rotate 1s linear infinite;
}

.qrcode-container {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 250px;
}

.qrcode-wrapper,
.loading-wrapper,
.success-wrapper,
.error-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  text-align: center;
}

.qrcode-tip {
  margin: 0;
  color: $text-secondary;
}

.qrcode-image {
  max-width: 220px;
  max-height: 220px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background-color: #000;
}

.success-wrapper .el-icon {
  color: #67c23a;
  font-size: 48px;
}

.error-wrapper .el-icon,
.loading-wrapper .el-icon {
  color: #f56c6c;
  font-size: 48px;
}

.dialog-footer {
  display: inline-flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 1100px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .panel-header {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 760px) {
  .page-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }

  .panel-tools,
  .panel-tools .el-input {
    width: 100%;
  }
}
</style>
