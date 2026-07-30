import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import AccountManagement from '../views/AccountManagement.vue'
import MaterialManagement from '../views/MaterialManagement.vue'
import PublishCenter from '../views/PublishCenter.vue'
import YoutubeResearch from '../views/YoutubeResearch.vue'
import WorkflowStatistics from '../views/WorkflowStatistics.vue'
import About from '../views/About.vue'
import SubtitleAudit from '../views/SubtitleAudit.vue'
import ScheduledPublishTasks from '../views/ScheduledPublishTasks.vue'
import Login from '../views/Login.vue'
import ChangePassword from '../views/ChangePassword.vue'
import UserManagement from '../views/UserManagement.vue'
import pinia, { useUserStore } from '../stores'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { public: true }
  },
  {
    path: '/change-password',
    name: 'ChangePassword',
    component: ChangePassword
  },
  {
    path: '/user-management',
    name: 'UserManagement',
    component: UserManagement,
    meta: { requiresAdmin: true }
  },
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard
  },
  {
    path: '/account-management',
    name: 'AccountManagement',
    component: AccountManagement,
    meta: { requiresAdmin: true }
  },
  {
    path: '/material-management',
    name: 'MaterialManagement',
    component: MaterialManagement
  },
  {
    path: '/publish-center',
    name: 'PublishCenter',
    component: PublishCenter
  },
  {
    path: '/scheduled-publish-tasks',
    name: 'ScheduledPublishTasks',
    component: ScheduledPublishTasks
  },
  {
    path: '/workflow-statistics',
    name: 'WorkflowStatistics',
    component: WorkflowStatistics
  },
  {
    path: '/youtube-research',
    name: 'YoutubeResearch',
    component: YoutubeResearch
  },
  {
    path: '/subtitle-audit',
    name: 'SubtitleAudit',
    component: SubtitleAudit
  },
  {
    path: '/about',
    name: 'About',
    component: About
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach(async to => {
  const userStore = useUserStore(pinia)
  await userStore.restore()
  if (to.meta.public) {
    if (!userStore.isLoggedIn) return true
    return userStore.userInfo?.mustChangePassword ? '/change-password' : '/'
  }
  if (!userStore.isLoggedIn) return { path: '/login', query: { redirect: to.fullPath } }
  if (userStore.userInfo?.mustChangePassword && to.path !== '/change-password') return '/change-password'
  if (to.meta.requiresAdmin && userStore.userInfo?.role !== 'admin') return '/'
  return true
})

export default router
