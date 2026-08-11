import { createRouter, createWebHistory } from 'vue-router'
import { getUser, logout } from '@/api/auth.js'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { guest: true },
  },
  {
    path: '/',
    name: 'Chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { requiresAuth: true, role: 'user' },
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('@/views/AdminView.vue'),
    meta: { requiresAuth: true, role: 'admin' },
  },
  {
    path: '/admin/kb',
    name: 'AdminKb',
    component: () => import('@/views/AdminKbView.vue'),
    meta: { requiresAuth: true, role: 'admin' },
  },
  {
    path: '/kb',
    name: 'UserKb',
    component: () => import('@/views/UserKbView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 并发去重：同一时刻只发起一次 /api/auth/me 探测登录态
// JWT 存于 HttpOnly Cookie，前端无法读 token，只能通过 me 接口判断是否已登录
let verifyPromise = null

function verifyToken() {
  if (!verifyPromise) {
    verifyPromise = fetch('/api/auth/me', { credentials: 'include' })
      .then((response) => {
        if (!response.ok) {
          if (response.status === 401) logout()
          return false
        }
        return true
      })
      .catch(() => true) // 网络异常放行，避免离线时被卡在登录页
      .finally(() => { verifyPromise = null })
  }
  return verifyPromise
}

router.beforeEach(async (to, from, next) => {
  const user = getUser()

  if (to.meta.requiresAuth) {
    const valid = await verifyToken()
    if (!valid) {
      next({ name: 'Login', query: { redirect: to.fullPath } })
      return
    }
  }

  if (to.meta.guest) {
    const logged = await verifyToken()
    if (logged) {
      if (user && user.role === 'admin') {
        next({ name: 'Admin' })
      } else {
        next({ name: 'Chat' })
      }
      return
    }
  }

  if (to.meta.role && user) {
    if (to.meta.role === 'admin' && user.role !== 'admin') {
      next({ name: 'Chat' })
      return
    }
    if (to.meta.role === 'user' && user.role === 'admin') {
      next({ name: 'Admin' })
      return
    }
  }

  next()
})

export default router
