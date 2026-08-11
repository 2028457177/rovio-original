const API_BASE = '/api'
const USER_KEY = 'auth_user'

export function getUser() {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function setUser(user) {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function removeUser() {
  localStorage.removeItem(USER_KEY)
}

export function isAdmin() {
  const user = getUser()
  return user && user.role === 'admin'
}

export async function logout() {
  // JWT 已迁入 HttpOnly Cookie：通知后端清除（keepalive 保证页面跳转前送达），再清本地用户缓存
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
      keepalive: true,
    })
  } catch { /* 网络异常时忽略，本地缓存仍会清除 */ }
  removeUser()
}

function authHeaders(extra = {}) {
  // JWT 存于 HttpOnly Cookie（同源请求自动携带，JS 不可读），无需手动附加头
  return { ...extra }
}

export async function login(username, password) {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ username, password }),
  })

  const data = await response.json()

  if (!response.ok) {
    throw new Error(data.error || '登录失败')
  }

  setUser(data.user)
  return data
}

export async function register(username, password, displayName = '') {
  const response = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ username, password, display_name: displayName }),
  })

  const data = await response.json()

  if (!response.ok) {
    throw new Error(data.error || '注册失败')
  }

  setUser(data.user)
  return data
}

export async function fetchMe() {
  const response = await fetch(`${API_BASE}/auth/me`, { credentials: 'include' })

  if (!response.ok) {
    if (response.status === 401) {
      logout()
    }
    return null
  }

  const data = await response.json()
  setUser(data.user)
  return data.user
}

// ==================== 用户自助 API ====================

/**
 * 修改密码（需登录）
 */
export async function changePassword(oldPassword, newPassword) {
  const response = await fetch(`${API_BASE}/user/password`, {
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '修改密码失败')
  }
  return data
}

/**
 * 修改昵称（需登录）
 */
export async function updateDisplayName(displayName) {
  const response = await fetch(`${API_BASE}/user/profile`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ display_name: displayName })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '修改昵称失败')
  }
  // 同步本地缓存的用户信息
  const u = getUser()
  if (u) {
    setUser({ ...u, display_name: data.user?.display_name || displayName })
  }
  return data
}

/**
 * 上传头像（需登录）
 */
export async function uploadAvatar(file) {
  const formData = new FormData()
  formData.append('avatar', file)
  const response = await fetch(`${API_BASE}/user/avatar`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '头像上传失败')
  }
  const u = getUser()
  if (u && data.avatar_url) {
    setUser({ ...u, avatar_url: data.avatar_url })
  }
  return data
}

// ==================== 课表设置 API（按用户隔离） ====================

/**
 * 获取当前用户的课表设置状态
 * @returns {Promise<{uploaded, file_path, start_date, uploaded_at, schedule_url}>}
 */
export async function getScheduleSettings() {
  const response = await fetch(`${API_BASE}/user/schedule`, {
    headers: authHeaders()
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || '获取课表设置失败')
  return data
}

/**
 * 上传/替换课表 Excel + 开学日期
 * @param {File} file Excel 文件
 * @param {string} startDate 'YYYY-MM-DD'
 */
export async function uploadSchedule(file, startDate) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('start_date', startDate)
  const response = await fetch(`${API_BASE}/user/schedule`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || '课表上传失败')
  return data  // { status, schedule_url, start_date }
}

/**
 * 单独修改开学日期（不重传文件）
 * @param {string|null} startDate 'YYYY-MM-DD' 或 null（清除）
 */
export async function updateScheduleStartDate(startDate) {
  const response = await fetch(`${API_BASE}/user/schedule/start-date`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ start_date: startDate })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || '修改开学日期失败')
  return data
}

/**
 * 删除当前用户的课表
 */
export async function deleteSchedule() {
  const response = await fetch(`${API_BASE}/user/schedule`, {
    method: 'DELETE',
    headers: authHeaders()
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || '删除课表失败')
  return data
}

// ==================== 模型设置 API（用户自配 OpenAI 兼容模型） ====================

/**
 * 获取当前用户的模型配置（api_key 为脱敏显示）
 * @returns {Promise<{configured, base_url, api_key, model_name}>}
 */
export async function getModelSettings() {
  const response = await fetch(`${API_BASE}/user/model`, {
    headers: authHeaders()
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || '获取模型设置失败')
  return data
}

/**
 * 保存当前用户的模型配置（OpenAI 兼容）
 * @param {string} baseUrl API 地址，如 https://api.deepseek.com
 * @param {string} apiKey API Key
 * @param {string} modelName 模型名称，如 deepseek-chat
 */
export async function saveModelSettings(baseUrl, apiKey, modelName) {
  const response = await fetch(`${API_BASE}/user/model`, {
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ base_url: baseUrl, api_key: apiKey, model_name: modelName })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || '保存模型设置失败')
  return data
}

/**
 * 清除当前用户的模型配置，恢复系统默认模型
 */
export async function clearModelSettings() {
  const response = await fetch(`${API_BASE}/user/model`, {
    method: 'DELETE',
    headers: authHeaders()
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || '清除模型设置失败')
  return data
}

/**
 * 设置密保问题（用于找回密码）
 */
export async function setSecurityQuestion(question, answer) {
  const response = await fetch(`${API_BASE}/user/security-question`, {
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ question, answer })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '设置密保失败')
  }
  return data
}

/**
 * 获取登录设备列表（需登录）
 */
export async function getLoginDevices() {
  const response = await fetch(`${API_BASE}/user/devices`, {
    headers: authHeaders()
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '获取设备列表失败')
  }
  return data.devices || []
}

/**
 * 一键下线指定设备
 */
export async function revokeDevice(deviceId) {
  const response = await fetch(`${API_BASE}/user/devices/${deviceId}`, {
    method: 'DELETE',
    headers: authHeaders()
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '下线设备失败')
  }
  return data
}

/**
 * 注销账号（需登录）
 */
export async function deleteAccount(password) {
  const response = await fetch(`${API_BASE}/user/account`, {
    method: 'DELETE',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ password })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '注销账号失败')
  }
  logout()
  return data
}

// ==================== 找回密码（无需登录） ====================

/**
 * 通过用户名查询是否设置了密保问题
 */
export async function getSecurityQuestionByUsername(username) {
  const response = await fetch(`${API_BASE}/auth/recover/question?username=${encodeURIComponent(username)}`)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '该账号未设置密保')
  }
  return data
}

/**
 * 通过密保答案重置密码
 */
export async function recoverPasswordByAnswer(username, answer, newPassword) {
  const response = await fetch(`${API_BASE}/auth/recover/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, answer, new_password: newPassword })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || '找回密码失败')
  }
  return data
}
