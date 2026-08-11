import { logout } from './auth.js'

const API_BASE = '/api'

function authHeaders(extra = {}) {
  // JWT 存于 HttpOnly Cookie，同源请求自动携带
  return { ...extra }
}

export async function uploadWordFile(file) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE}/upload-word`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.error || `上传失败: ${response.status}`)
  }

  return response.json()
}

export async function sendChatMessage(message, sessionId, latitude, longitude, onThinking, onOutput, onThinkingEnd, onError, onDone, uploadedFilePath = '', signal = null, truncateTo = null, onMessageIds = null, onEvent = null, searchEnabled = true) {
  try {
    const body = {
      message,
      session_id: sessionId,
      stream: true,
      search_enabled: searchEnabled
    }
    if (latitude != null && longitude != null) {
      body.latitude = latitude
      body.longitude = longitude
    }
    if (uploadedFilePath) {
      body.uploaded_file_path = uploadedFilePath
    }
    if (truncateTo != null && Number.isFinite(truncateTo)) {
      body.truncate_to = truncateTo
    }

    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal
    })

    if (!response.ok) {
      if (response.status === 401) {
        logout()
        window.location.href = '/login'
        return ''
      }
      if (response.status === 429) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.error || '请求过于频繁，请稍后再试')
      }
      // 提取后端错误信息
      let errMsg = `请求失败: ${response.status}`
      try {
        const errData = await response.json()
        if (errData && errData.error) errMsg = errData.error
      } catch {}
      throw new Error(errMsg)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let fullOutput = ''
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.substring(6).trim()
          if (data === '[DONE]') continue

          try {
            const parsed = JSON.parse(data)
            if (parsed.type === 'thinking' && parsed.content) {
              onThinking(parsed.content)
            } else if (parsed.type === 'thinking_end') {
              onThinkingEnd()
            } else if (parsed.type === 'output' && parsed.content) {
              fullOutput += parsed.content
              onOutput(parsed.content, fullOutput)
            } else if (parsed.type === 'message_ids') {
              onMessageIds && onMessageIds(parsed)
            }

            // DeepAgent 事件透传：plan_created / step_started / step_output / plan_completed 等
            // 调用方未传 onEvent 时静默忽略，保证旧调用方零改动兼容
            if (onEvent && parsed.type && (
              parsed.type.startsWith('plan_') || parsed.type.startsWith('step_')
            )) {
              onEvent(parsed)
            }

            if (parsed.error) {
              onError(parsed.error)
            }
          } catch {
            if (data) {
              fullOutput += data
              onOutput(data, fullOutput)
            }
          }
        }
      }
    }

    onDone(fullOutput)
    return fullOutput
  } catch (error) {
    if (error.name === 'AbortError') {
      throw error
    }
    // 网络错误（fetch 抛出 TypeError: Failed to fetch）
    const msg = error.message || '发送失败'
    onError(msg)
    throw error
  }
}

export function generateSessionId() {
  return 'session_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9)
}

export async function loadConversationsApi() {
  const response = await fetch(`${API_BASE}/conversations`, {
    headers: authHeaders(),
  })
  if (!response.ok) throw new Error(`加载对话失败: ${response.status}`)
  const data = await response.json()
  return data.conversations || []
}

export async function saveConversationApi(conversation) {
  await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(conversation)
  })
}

export async function deleteConversationApi(conversationId) {
  await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
}

/**
 * 更新会话元数据（标题/置顶/收藏/文件夹）
 */
export async function updateConversationMetaApi(conversationId, meta) {
  try {
    await fetch(`${API_BASE}/conversations/${conversationId}/meta`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(meta)
    })
  } catch {}
}

/**
 * 会话全文检索
 */
export async function searchConversationsApi(keyword) {
  try {
    const response = await fetch(`${API_BASE}/conversations/search?q=${encodeURIComponent(keyword)}`, {
      headers: authHeaders(),
    })
    if (!response.ok) return []
    const data = await response.json()
    return data.conversations || []
  } catch {
    return []
  }
}

/**
 * 对话分支：在指定消息处分叉出新会话（非破坏性）
 */
export async function branchConversationApi(conversationId, branchFromMessageId) {
  const response = await fetch(`${API_BASE}/conversations/${conversationId}/branch`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ branch_from_message_id: branchFromMessageId })
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.error || `分叉失败: ${response.status}`)
  }
  return response.json()
}

/**
 * 消息反馈（点赞/踩）
 */
export async function saveMessageFeedbackApi(payload) {
  try {
    await fetch(`${API_BASE}/feedback`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload)
    })
  } catch {}
}

/**
 * 计划历史列表（AI 长任务执行记录，轻量：不含步骤明细）
 */
export async function fetchPlansApi() {
  const response = await fetch(`${API_BASE}/plans`, { headers: authHeaders() })
  if (!response.ok) throw new Error(`加载计划历史失败: ${response.status}`)
  const data = await response.json()
  return data.plans || []
}

/**
 * 计划详情（含步骤结构、最终回答）
 */
export async function fetchPlanDetailApi(planId) {
  const response = await fetch(`${API_BASE}/plans/${planId}`, { headers: authHeaders() })
  if (!response.ok) throw new Error(`加载计划详情失败: ${response.status}`)
  const data = await response.json()
  return data.plan || null
}
