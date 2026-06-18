import { createRouter, createWebHashHistory } from 'vue-router'
import { isAuthenticated, initAuth, getAccessToken } from '../api/index.js'

import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import ChatView from '../views/ChatView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import ProfileView from '../views/ProfileView.vue'

const routes = [
  { path: '/login', name: 'Login', component: LoginView, meta: { guest: true } },
  { path: '/register', name: 'Register', component: RegisterView, meta: { guest: true } },
  { path: '/chat', name: 'Chat', component: ChatView, meta: { auth: true } },
  { path: '/knowledge', name: 'Knowledge', component: KnowledgeView, meta: { auth: true } },
  { path: '/profile', name: 'Profile', component: ProfileView, meta: { auth: true } },
  // 根路径：根据登录状态决定跳转目标
  { path: '/', redirect: to => {
    return isAuthenticated() ? '/chat' : '/login'
  }},
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

/**
 * 异步路由守卫：在首次导航前尝试恢复会话（用 refresh_token 换 access_token）。
 *
 * 这样页面刷新后不会因为 accessToken 在内存中丢失而陷入"假登录"状态：
 * - refresh_token 有效 → 拿到新 access_token → 正常进入页面
 * - refresh_token 无效 → 清除 token → 跳转到登录页
 */
let _authInitialized = false

router.beforeEach(async (to, _from, next) => {
  // 首次导航时尝试恢复 token（后续导航跳过）
  if (!_authInitialized) {
    await initAuth()
    _authInitialized = true
  }

  const authed = !!getAccessToken()  // 只以 access_token 为准（已通过 initAuth 恢复）

  if (to.meta.auth && !authed) return next('/login')
  if (to.meta.guest && authed) return next('/chat')
  next()
})

export default router
