import { createRouter, createWebHashHistory } from 'vue-router'
import { isAuthenticated } from '../api/index.js'

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
  { path: '/', redirect: '/chat' },
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const authed = isAuthenticated()
  if (to.meta.auth && !authed) return next('/login')
  if (to.meta.guest && authed) return next('/chat')
  next()
})

export default router
