import { logout } from './auth.js'

const API_BASE = '/api'

function authHeaders(extra = {}) {
  // JWT 存于 HttpOnly Cookie，同源请求自动携带
  return { ...extra }
}

/** 列出 AI 工作区目录内容 */
export async function listWorkspace(path = '') {
  const url = `${API_BASE}/file/list${path ? `?path=${encodeURIComponent(path)}` : ''}`
  const res = await fetch(url, { headers: authHeaders() })
  if (res.status === 401) {
    logout()
    throw new Error('未登录或登录已过期')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.error || `请求失败 (${res.status})`)
  }
  return res.json()
}

/** 触发文件下载（浏览器直接下载到本地） */
export function downloadWorkspaceFile(path) {
  const url = `${API_BASE}/file/download?path=${encodeURIComponent(path)}`
  // fetch 带 cookie 拿 blob（HttpOnly Cookie 自动携带），再触发下载
  fetch(url, { headers: authHeaders() })
    .then(r => {
      if (!r.ok) throw new Error(`下载失败 (${r.status})`)
      return r.blob()
    })
    .then(blob => {
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      // 文件名取 path 最后一段
      a.download = path.split('/').pop() || 'download'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objUrl)
    })
    .catch(err => {
      console.error('[downloadWorkspaceFile]', err)
      alert(err.message)
    })
}

/** 获取文件预览 URL（图片/文本可直接 <img src> 或 fetch） */
export function previewWorkspaceFileUrl(path) {
  const url = `${API_BASE}/file/preview?path=${encodeURIComponent(path)}`
  // 预览也需要带 token，用 fetch+blob 方式由调用方处理；这里只返回 URL 用于不需要鉴权的环境
  return url
}

/** 带 token 获取文件 blob（用于 <img> 显示需要鉴权的图片） */
export async function fetchWorkspaceFileBlob(path) {
  const url = `${API_BASE}/file/preview?path=${encodeURIComponent(path)}`
  const res = await fetch(url, { headers: authHeaders() })
  if (res.status === 401) {
    logout()
    throw new Error('未登录或登录已过期')
  }
  if (!res.ok) {
    throw new Error(`加载失败 (${res.status})`)
  }
  return res.blob()
}
