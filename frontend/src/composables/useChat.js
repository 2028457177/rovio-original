import { ref, computed, reactive, markRaw } from 'vue'
import {
  sendChatMessage,
  generateSessionId,
  loadConversationsApi,
  saveConversationApi,
  deleteConversationApi,
  saveMessageFeedbackApi,
  updateConversationMetaApi,
  searchConversationsApi,
  branchConversationApi
} from '@/api/chat.js'

// ==================== 模块级单例状态 ====================
// 关键：将这些 ref 放到模块作用域，使其在 ChatView 路由切换（mount/unmount）时
// 不会被销毁。否则在 AI 流式生成过程中切到“我的知识库 / 账号设置”再返回时，
// pendingStreams 与 conversations 会丢失，导致对话内容消失。
const conversations = ref([])
const currentConversationId = ref(null)
const pendingStreams = ref(new Map())  // sessionId -> { controller, streamingContent, thinkingContent, isThinking, isStreaming }
const error = ref('')
const errorInfo = ref(null)  // { hint, canRetry, retryFn }
const geoLocation = ref(null)  // { latitude, longitude }

// 搜索 / 置顶 / 收藏 / 文件夹
const searchKeyword = ref('')
const searchResults = ref([])        // 搜索结果（独立列表，命中时显示）
const isSearching = ref(false)

const defaultSessionId = ref(generateSessionId())
let conversationsLoaded = false
// 任务队列执行期间保持欢迎页（消息照常累积但不切换到对话视图）
const keepWelcome = ref(false)

// 联网搜索开关（模块级单例，localStorage 持久化，默认开启）
// 关闭后后端 Planner 不会选择 search 子代理
let _initialSearchEnabled = true
try {
  _initialSearchEnabled = localStorage.getItem('searchEnabled') !== '0'
} catch {}
const searchEnabled = ref(_initialSearchEnabled)

function toggleSearch() {
  searchEnabled.value = !searchEnabled.value
  try {
    localStorage.setItem('searchEnabled', searchEnabled.value ? '1' : '0')
  } catch {}
}

export function useChat() {
  const currentConversation = computed(() => {
    if (!currentConversationId.value) return null
    return conversations.value.find(c => c.id === currentConversationId.value) || null
  })

  const messages = computed(() => {
    const conv = currentConversation.value
    return conv ? conv.messages : []
  })

  const sessionId = computed(() => {
    return currentConversation.value ? currentConversation.value.id : defaultSessionId.value
  })

  const isStreaming = computed(() => {
    const conv = currentConversation.value
    if (!conv) return false
    const pending = pendingStreams.value.get(conv.id)
    return !!pending && pending.isStreaming
  })

  const streamingContent = computed(() => {
    const conv = currentConversation.value
    if (!conv) return ''
    const pending = pendingStreams.value.get(conv.id)
    return pending ? pending.streamingContent : ''
  })

  const thinkingContent = computed(() => {
    const conv = currentConversation.value
    if (!conv) return ''
    const pending = pendingStreams.value.get(conv.id)
    return pending ? pending.thinkingContent : ''
  })

  const isThinking = computed(() => {
    const conv = currentConversation.value
    if (!conv) return false
    const pending = pendingStreams.value.get(conv.id)
    return !!pending && pending.isThinking
  })

  const showWelcome = computed(() => messages.value.length === 0 || keepWelcome.value)

  /**
   * 排序后的会话列表：置顶 → 收藏 → 普通会话，组内按更新时间倒序。
   * 当处于搜索态时返回 searchResults。
   */
  const visibleConversations = computed(() => {
    if (searchKeyword.value.trim() && searchResults.value.length >= 0) {
      // 仅在有搜索词时返回搜索结果（包括空结果）
      if (searchKeyword.value.trim()) return searchResults.value
    }
    const list = [...conversations.value]
    list.sort((a, b) => {
      const pa = a.pinned ? 0 : (a.starred ? 1 : 2)
      const pb = b.pinned ? 0 : (b.starred ? 1 : 2)
      if (pa !== pb) return pa - pb
      // 时间倒序：这里用字符串比较不够稳，但 time 仅为 HH:MM；改为使用 updatedAt 时间戳
      return (b._sortTs || 0) - (a._sortTs || 0)
    })
    return list
  })

  function getOrCreateConversation(id) {
    let conv = conversations.value.find(c => c.id === id)
    if (!conv) {
      conv = {
        id,
        title: '新对话',
        messages: [],
        time: formatTime(),
        titleCustomized: false,
        pinned: false,
        starred: false,
        folder: '',
        parentConversationId: '',
        branchPointMessageId: 0,
        _sortTs: Date.now()
      }
      conversations.value.unshift(conv)
    }
    return conv
  }

  function updateTitleFromMessages(conv) {
    if (conv.titleCustomized) return
    const firstUserMsg = conv.messages.find(m => m.role === 'user')
    if (firstUserMsg) {
      conv.title = firstUserMsg.content.slice(0, 30) + (firstUserMsg.content.length > 30 ? '...' : '')
    }
  }

  function bumpConversation(conv) {
    conv.time = formatTime()
    conv._sortTs = Date.now()
    const idx = conversations.value.indexOf(conv)
    if (idx > 0) {
      conversations.value.splice(idx, 1)
      conversations.value.unshift(conv)
    }
  }

  function setError(message, opts = {}) {
    error.value = message
    errorInfo.value = opts?.canRetry ? opts : null
  }

  /**
   * 发送消息核心入口。
   * options:
   *  - uploadedFilePath: 上传文件路径
   *  - onDone: 完成回调
   *  - isRegenerate: 是否为重新生成（不再 push user 消息）
   *  - replaceAssistantId: 重新生成时要替换的 assistant 消息 id（旧路径兼容，新流程由调用方自行截断）
   *  - messageText: 重新生成 / 编辑重发时显式指定的用户消息文本（覆盖默认推断）
   *  - truncateTo: 重新生成 / 编辑重发时，告知后端把会话历史回滚到保留最早的 N 条
   */
  async function sendMessage(message, uploadedFilePath = '', options = {}) {
    const { isRegenerate = false, replaceAssistantId = null, onDone = null, onError = null, onAbort = null, messageText: explicitText = null, truncateTo = null, sessionIdOverride = null } = options

    if (!isRegenerate && !message.trim() && !uploadedFilePath) return

    const requestSessionId = sessionIdOverride || sessionId.value
    if (pendingStreams.value.has(requestSessionId)) return

    error.value = ''
    errorInfo.value = null
    const conv = getOrCreateConversation(requestSessionId)
    if (!currentConversationId.value) {
      currentConversationId.value = requestSessionId
    }

    let userMsg = null
    if (!isRegenerate) {
      userMsg = {
        id: Date.now(),
        role: 'user',
        content: message,
        time: formatTime()
      }
      conv.messages.push(userMsg)
      updateTitleFromMessages(conv)
      bumpConversation(conv)
    }

    // 重新生成：移除旧的 assistant 消息
    if (isRegenerate && replaceAssistantId != null) {
      const idx = conv.messages.findIndex(m => m.id === replaceAssistantId)
      if (idx > -1) conv.messages.splice(idx, 1)
    }

    const assistantMsg = reactive({
      id: Date.now() + 1,
      role: 'assistant',
      content: '',
      time: formatTime(),
      streaming: true,
      feedback: '',
      // DeepAgent plan 可视化：流式中由 onEvent 实时更新
      plan: null,        // { goal, steps: [...], status }
      steps: {}          // step_idx -> { status, subagent, description, thinking, output, error }
    })
    conv.messages.push(assistantMsg)

    const controller = markRaw(new AbortController())
    const pending = reactive({
      controller,
      streamingContent: '',
      thinkingContent: '',
      isThinking: true,
      isStreaming: true,
      lastError: null
    })
    pendingStreams.value.set(requestSessionId, pending)

    if (geoLocation.value === null) {
      try {
        const pos = await new Promise((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 600000
          })
        })
        geoLocation.value = { latitude: pos.coords.latitude, longitude: pos.coords.longitude }
      } catch {
        geoLocation.value = false
      }
    }

    const lat = geoLocation.value ? geoLocation.value.latitude : null
    const lng = geoLocation.value ? geoLocation.value.longitude : null

    // 取实际要发送的文本：
    //  - 重新生成 / 编辑重发：优先用调用方显式传入的 messageText（确保是目标 user 消息，而非最后一条）
    //  - 兜底：重新生成时取最后一条 user 消息
    const messageText = explicitText
      || (isRegenerate ? (getLastUserMessage(conv)?.content || '') : message)

    try {
      await sendChatMessage(
        messageText,
        requestSessionId,
        lat,
        lng,
        (thinkingContent) => {
          pending.isThinking = true
          pending.streamingContent = ''
          pending.thinkingContent += thinkingContent
        },
        (_delta, fullOutput) => {
          pending.isThinking = false
          pending.streamingContent = fullOutput
          assistantMsg.content = fullOutput
        },
        () => {
          // thinking_end
        },
        (err) => {
          pending.lastError = err
          if (currentConversationId.value === requestSessionId) {
            // 区分错误类型：网络/超时 / 401 / 5xx
            const hint = classifyError(err)
            setError(err, {
              hint: hint.hint,
              canRetry: hint.canRetry,
              retryFn: () => {
                dismissError()
                if (isRegenerate) {
                  regenerateFromLastUser()
                } else {
                  sendMessage(message, uploadedFilePath, options)
                }
              }
            })
          }
          if (onError) try { onError(typeof err === 'string' ? err : (err?.message || String(err))) } catch {}
        },
        (finalContent) => {
          assistantMsg.content = finalContent
          assistantMsg.streaming = false
          const finalConv = getOrCreateConversation(requestSessionId)
          updateTitleFromMessages(finalConv)
          bumpConversation(finalConv)
          saveConversationApi(finalConv).catch(() => {})
          pendingStreams.value.delete(requestSessionId)
          if (onDone) try { onDone(finalContent) } catch {}
        },
        uploadedFilePath,
        controller.signal,
        truncateTo,
        (ids) => {
          // 后端回传真实消息 id，存入 dbId 字段供分支/反馈使用。
          // 注意：不能覆盖 msg.id，否则 v-for :key 会变化导致组件重新挂载，
          // 造成流式结束后内容短暂消失再出现的闪烁。
          if (ids.user_message_id && userMsg) {
            userMsg.dbId = ids.user_message_id
          }
          if (ids.assistant_message_id) {
            assistantMsg.dbId = ids.assistant_message_id
          }
        },
        // DeepAgent plan/step 事件 → 实时更新 assistantMsg.plan / steps
        (event) => {
          const t = event.type
          if (t === 'plan_created' || t === 'plan_revised' || t === 'plan_completed') {
            assistantMsg.plan = event.plan
            // 初始化 steps 状态（plan.steps 是静态结构，状态靠 step_* 事件更新）
            if (event.plan && event.plan.steps) {
              for (const s of event.plan.steps) {
                if (!assistantMsg.steps[s.step_idx]) {
                  assistantMsg.steps[s.step_idx] = {
                    status: 'pending',
                    subagent: s.subagent || '',
                    description: s.description || '',
                    thinking: '',
                    output: '',
                    error: ''
                  }
                }
              }
            }
          } else if (t === 'step_started') {
            const idx = event.step_idx
            if (!assistantMsg.steps[idx]) assistantMsg.steps[idx] = { thinking: '', output: '', error: '' }
            assistantMsg.steps[idx].status = 'running'
            assistantMsg.steps[idx].subagent = event.subagent || ''
            assistantMsg.steps[idx].description = event.description || ''
          } else if (t === 'step_thinking') {
            const idx = event.step_idx
            if (!assistantMsg.steps[idx]) assistantMsg.steps[idx] = { thinking: '', output: '', error: '' }
            assistantMsg.steps[idx].thinking = (assistantMsg.steps[idx].thinking || '') + (event.content || '')
          } else if (t === 'step_output') {
            const idx = event.step_idx
            if (!assistantMsg.steps[idx]) assistantMsg.steps[idx] = { thinking: '', output: '', error: '' }
            assistantMsg.steps[idx].output = (assistantMsg.steps[idx].output || '') + (event.content || '')
          } else if (t === 'step_completed') {
            const idx = event.step_idx
            if (!assistantMsg.steps[idx]) assistantMsg.steps[idx] = {}
            assistantMsg.steps[idx].status = 'done'
          } else if (t === 'step_failed') {
            const idx = event.step_idx
            if (!assistantMsg.steps[idx]) assistantMsg.steps[idx] = {}
            assistantMsg.steps[idx].status = 'failed'
            assistantMsg.steps[idx].error = event.error || ''
          }
        },
        // 联网搜索开关：false 时后端 Planner 不选 search 子代理
        searchEnabled.value
      )
    } catch (e) {
      assistantMsg.streaming = false
      if (!assistantMsg.content) {
        const failedConv = getOrCreateConversation(requestSessionId)
        const idx = failedConv.messages.indexOf(assistantMsg)
        if (idx > -1) failedConv.messages.splice(idx, 1)
      }
      pendingStreams.value.delete(requestSessionId)

      // 中止（用户主动停止）不算错误
      if (e?.name === 'AbortError') {
        // 保留已生成内容
        if (onAbort) try { onAbort() } catch {}
        return
      }

      const hint = classifyError(e.message || String(e))
      setError(e.message || '发送失败', {
        hint: hint.hint,
        canRetry: hint.canRetry,
        retryFn: () => {
          dismissError()
          if (isRegenerate) {
            regenerateFromLastUser()
          } else {
            sendMessage(message, uploadedFilePath, options)
          }
        }
      })
      if (onError) try { onError(e.message || String(e)) } catch {}
    }
  }

  function getLastUserMessage(conv) {
    for (let i = conv.messages.length - 1; i >= 0; i--) {
      if (conv.messages[i].role === 'user') return conv.messages[i]
    }
    return null
  }

  /**
   * 停止当前会话的流式生成
   */
  function stopStreaming() {
    const conv = currentConversation.value
    if (!conv) return
    const pending = pendingStreams.value.get(conv.id)
    if (pending && pending.controller) {
      try { pending.controller.abort() } catch {}
      pending.isStreaming = false
      pendingStreams.value.delete(conv.id)
      // 收尾 assistant 消息
      const lastMsg = conv.messages[conv.messages.length - 1]
      if (lastMsg && lastMsg.role === 'assistant') {
        lastMsg.streaming = false
        if (!lastMsg.content) {
          lastMsg.content = '（已停止生成）'
        }
      }
    }
  }

  /**
   * 重新生成指定 assistant 消息。
   *
   * 关键：必须找到该 assistant 前面最近的 user 消息作为"要重新回答的问题"，
   * 而不是简单取最后一条 user 消息——否则在 [U1, A1, U2, A2] 里重新生成 A1 时
   * 会错误地把 U2 当成问题发给 AI。
   * 同时把本地消息截断到该 user 消息之后（丢弃其后的旧回复 / 后续对话），
   * 并通过 truncateTo 让后端同步回滚历史，保持前后端上下文一致。
   */
  function regenerateMessage(assistantMsg) {
    const conv = currentConversation.value
    if (!conv) return
    if (pendingStreams.value.has(conv.id)) return
    const ai = conv.messages.findIndex(m => m.id === assistantMsg.id)
    if (ai === -1) return
    // 向前找最近的 user 消息
    let ui = -1
    for (let i = ai - 1; i >= 0; i--) {
      if (conv.messages[i].role === 'user') { ui = i; break }
    }
    if (ui === -1) return
    regenerateFromUserIndex(ui)
  }

  /**
   * 基于会话最后一条 user 消息重新生成（用于失败重试）。
   * 无论上一次失败时是否已把空 assistant 移除，都能从当前状态正确恢复。
   */
  function regenerateFromLastUser() {
    const conv = currentConversation.value
    if (!conv) return
    if (pendingStreams.value.has(conv.id)) return
    let ui = -1
    for (let i = conv.messages.length - 1; i >= 0; i--) {
      if (conv.messages[i].role === 'user') { ui = i; break }
    }
    if (ui === -1) return
    regenerateFromUserIndex(ui)
  }

  /**
   * 内部公共逻辑：以 conv.messages[ui] 作为"要回答的 user 消息"重新生成。
   *  - 本地截断：保留 [0..ui]，丢弃 ui 之后的所有消息（旧 assistant 及后续对话）
   *  - 发送：messageText = 该 user 消息内容，truncateTo = ui（后端据此回滚历史）
   */
  function regenerateFromUserIndex(ui) {
    const conv = currentConversation.value
    if (!conv) return
    const userText = conv.messages[ui]?.content || ''
    const truncateTo = ui
    conv.messages.splice(ui + 1)
    sendMessage('', '', {
      isRegenerate: true,
      messageText: userText,
      truncateTo
    })
  }

  /**
   * 编辑用户消息后重发：替换原消息 + 触发新一轮生成。
   * 同样通过 truncateTo 让后端回滚到该 user 消息之前，避免历史污染。
   */
  function editAndResend(userMsg, newContent) {
    const conv = currentConversation.value
    if (!conv) return
    if (pendingStreams.value.has(conv.id)) return
    // 找到该用户消息位置
    const idx = conv.messages.findIndex(m => m.id === userMsg.id)
    if (idx === -1) return
    // 替换内容
    conv.messages[idx].content = newContent
    // 移除该消息之后的所有内容（包括对应的 assistant 回复）
    conv.messages.splice(idx + 1)
    // 重新生成：显式指定文本 + 后端回滚到该 user 消息之前
    sendMessage('', '', {
      isRegenerate: true,
      messageText: newContent,
      truncateTo: idx
    })
  }

  /**
   * 在指定消息处分叉出新会话（非破坏性）。
   * 调用后端 branch 接口复制该消息及之前的所有内容到新会话，
   * 然后切换到新会话，用户可在分支上继续探索不同方向。
   */
  async function branchFromMessage(message) {
    const conv = currentConversation.value
    if (!conv) return
    if (pendingStreams.value.has(conv.id)) return
    try {
      const result = await branchConversationApi(conv.id, message.dbId || message.id)
      const newConv = {
        id: result.id,
        title: result.title,
        messages: (result.messages || []).map((m, i) => ({
          id: m.id || `loaded_${result.id}_${i}`,
          role: m.role,
          content: m.content,
          time: m.time || '',
          feedback: m.feedback || ''
        })),
        time: formatTime(),
        titleCustomized: true,
        pinned: false,
        starred: false,
        folder: '',
        parentConversationId: result.parent_conversation_id || conv.id,
        branchPointMessageId: result.branch_point_message_id || message.dbId || message.id,
        _sortTs: Date.now()
      }
      conversations.value.unshift(newConv)
      currentConversationId.value = newConv.id
      error.value = ''
      errorInfo.value = null
      return newConv
    } catch (e) {
      const hint = classifyError(e.message || String(e))
      setError(e.message || '分叉失败', {
        hint: hint.hint,
        canRetry: hint.canRetry,
        retryFn: () => {
          dismissError()
          branchFromMessage(message)
        }
      })
    }
  }

  /**
   * 消息反馈（点赞/踩）
   */
  function setMessageFeedback(message, feedback) {
    const conv = currentConversation.value
    if (!conv) return
    const target = conv.messages.find(m => m.id === message.id)
    if (target) {
      target.feedback = feedback
    }
    saveMessageFeedbackApi({
      conversation_id: conv.id,
      message_id: message.dbId || message.id,
      message_role: message.role,
      message_content: message.content,
      feedback
    }).catch(() => {})
  }

  function saveCurrentConversation() {
    const conv = currentConversation.value
    if (!conv || conv.messages.length === 0) return
    saveConversationApi(conv).catch(() => {})
  }

  function renameConversation(conversationId, newTitle) {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv) return
    const title = (newTitle || '').trim()
    if (!title) return
    conv.title = title
    conv.titleCustomized = true
    saveConversationApi(conv).catch(() => {})
    updateConversationMetaApi(conv.id, { title }).catch(() => {})
  }

  function togglePin(conversationId) {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv) return
    conv.pinned = !conv.pinned
    updateConversationMetaApi(conv.id, { pinned: conv.pinned ? 1 : 0 }).catch(() => {})
  }

  function toggleStar(conversationId) {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv) return
    conv.starred = !conv.starred
    updateConversationMetaApi(conv.id, { starred: conv.starred ? 1 : 0 }).catch(() => {})
  }

  function setFolder(conversationId, folder) {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv) return
    conv.folder = folder || ''
    updateConversationMetaApi(conv.id, { folder: conv.folder }).catch(() => {})
  }

  /**
   * 会话搜索：本地优先，远程兜底
   */
  async function searchConversations(keyword) {
    const kw = (keyword || '').trim()
    searchKeyword.value = kw
    if (!kw) {
      searchResults.value = []
      isSearching.value = false
      return
    }
    isSearching.value = true
    try {
      // 本地搜索（标题 + 消息内容）
      const lower = kw.toLowerCase()
      const local = conversations.value.filter(c => {
        if (c.title && c.title.toLowerCase().includes(lower)) return true
        return (c.messages || []).some(m => (m.content || '').toLowerCase().includes(lower))
      })
      searchResults.value = local
      // 同时向远程发起请求（覆盖本地未加载的会话）
      try {
        const remote = await searchConversationsApi(kw)
        // 合并去重
        const localIds = new Set(local.map(c => c.id))
        for (const r of remote) {
          if (!localIds.has(r.id)) searchResults.value.push(r)
        }
      } catch {}
    } finally {
      isSearching.value = false
    }
  }

  function clearSearch() {
    searchKeyword.value = ''
    searchResults.value = []
    isSearching.value = false
  }

  /**
   * 导出会话：默认导出 Markdown
   * format: 'markdown' | 'json' | 'text'
   */
  function exportConversation(conversationId, format = 'markdown') {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv) return null
    if (format === 'json') {
      return {
        filename: `${sanitizeFilename(conv.title)}.json`,
        mime: 'application/json',
        content: JSON.stringify({
          id: conv.id,
          title: conv.title,
          time: conv.time,
          messages: conv.messages
        }, null, 2)
      }
    }
    if (format === 'text') {
      const lines = [`# ${conv.title}`, ``, `会话时间：${conv.time}`, ``]
      for (const m of conv.messages) {
        lines.push(`${m.role === 'user' ? '我' : 'Rovio'}：`)
        lines.push(m.content || '')
        lines.push('')
      }
      return {
        filename: `${sanitizeFilename(conv.title)}.txt`,
        mime: 'text/plain',
        content: lines.join('\n')
      }
    }
    // markdown
    const md = [`# ${conv.title}`, ``, `> 导出时间：${new Date().toLocaleString()}`, ``]
    for (const m of conv.messages) {
      md.push(`## ${m.role === 'user' ? '🧑 我' : '🤖 Rovio'}`)
      md.push('')
      md.push(m.content || '')
      md.push('')
    }
    return {
      filename: `${sanitizeFilename(conv.title)}.md`,
      mime: 'text/markdown',
      content: md.join('\n')
    }
  }

  function newChat() {
    saveCurrentConversation()
    currentConversationId.value = null
    defaultSessionId.value = generateSessionId()
    error.value = ''
    errorInfo.value = null
  }

  function switchToConversation(conversationId) {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv) return
    // 注：不强制停止其他会话的流式生成 —— 支持多会话切换不丢失未完成生成
    saveCurrentConversation()
    currentConversationId.value = conversationId
    error.value = ''
    errorInfo.value = null
    keepWelcome.value = false  // 切换会话时显示对话内容
  }

  async function loadConversations(force = false) {
    // 单例保护：已加载过则不再重复请求，避免 ChatView 重新挂载时
    // 用后端旧数据覆盖本地正在流式生成的会话内容。
    if (conversationsLoaded && !force) return
    try {
      const data = await loadConversationsApi()
      // 保留正在流式生成的会话（这些会话尚未保存到后端，会被覆盖丢失）
      const activeStreamIds = new Set(pendingStreams.value.keys())
      const localActiveConvs = conversations.value.filter(c => activeStreamIds.has(c.id))

      conversations.value = (data || []).map(conv => ({
        id: conv.id,
        title: conv.title || '新对话',
        time: conv.time || formatTime(),
        titleCustomized: true,
        pinned: !!conv.pinned,
        starred: !!conv.starred,
        folder: conv.folder || '',
        parentConversationId: conv.parent_conversation_id || '',
        branchPointMessageId: conv.branch_point_message_id || 0,
        _sortTs: conv.updated_at ? new Date(conv.updated_at).getTime() : Date.now(),
        messages: (conv.messages || []).map((m, i) => ({
          id: m.id || `loaded_${conv.id}_${i}`,
          role: m.role,
          content: m.content,
          time: m.time || '',
          feedback: m.feedback || '',
          // DeepAgent plan 持久化：从后端加载时恢复 plan/steps 字段
          plan: m.plan || null,
          steps: m.steps || {}
        }))
      }))

      // 把正在流式生成的本地会话重新合并回去（以后端版本为基准，本地流式版本覆盖）
      for (const localConv of localActiveConvs) {
        const idx = conversations.value.findIndex(c => c.id === localConv.id)
        if (idx === -1) {
          conversations.value.unshift(localConv)
        } else {
          conversations.value[idx] = localConv
        }
      }
    } catch {
      conversations.value = []
    } finally {
      conversationsLoaded = true
    }
  }

  async function removeConversation(conversationId) {
    conversations.value = conversations.value.filter(c => c.id !== conversationId)
    if (currentConversationId.value === conversationId) {
      currentConversationId.value = null
      defaultSessionId.value = generateSessionId()
    }
    deleteConversationApi(conversationId).catch(() => {})
  }

  function clearChat() {
    const conv = currentConversation.value
    if (conv) {
      conv.messages = []
    }
    error.value = ''
    errorInfo.value = null
  }

  function dismissError() {
    error.value = ''
    errorInfo.value = null
  }

  return {
    // state
    messages,
    sessionId,
    isStreaming,
    isThinking,
    error,
    errorInfo,
    streamingContent,
    thinkingContent,
    showWelcome,
    keepWelcome,
    conversations,
    visibleConversations,
    currentConversationId,
    currentConversation,
    searchKeyword,
    searchResults,
    isSearching,
    pendingStreams,
    searchEnabled,
    // actions
    sendMessage,
    stopStreaming,
    toggleSearch,
    regenerateMessage,
    editAndResend,
    branchFromMessage,
    setMessageFeedback,
    newChat,
    loadConversations,
    switchToConversation,
    removeConversation,
    renameConversation,
    togglePin,
    toggleStar,
    setFolder,
    searchConversations,
    clearSearch,
    exportConversation,
    clearChat,
    dismissError
  }
}

/**
 * 重置聊天单例状态：用户登出 / 注销账号时调用，避免下一个登录用户看到上一个用户的会话。
 * 会中止所有正在进行的流式生成。
 */
export function resetChatState() {
  // 中止所有正在进行的流式生成
  for (const pending of pendingStreams.value.values()) {
    if (pending.controller) {
      try { pending.controller.abort() } catch {}
    }
  }
  pendingStreams.value = new Map()
  conversations.value = []
  currentConversationId.value = null
  error.value = ''
  errorInfo.value = null
  geoLocation.value = null
  searchKeyword.value = ''
  searchResults.value = []
  isSearching.value = false
  defaultSessionId.value = generateSessionId()
  conversationsLoaded = false
}

function formatTime() {
  const now = new Date()
  const hours = String(now.getHours()).padStart(2, '0')
  const minutes = String(now.getMinutes()).padStart(2, '0')
  return `${hours}:${minutes}`
}

function sanitizeFilename(name) {
  return (name || '会话').replace(/[\\/:*?"<>|]/g, '_').slice(0, 60)
}

/**
 * 错误分类：根据错误信息推断原因，返回提示文案与是否可重试
 */
function classifyError(errMsg) {
  const msg = (errMsg || '').toLowerCase()
  if (msg.includes('abort')) {
    return { hint: '已停止生成', canRetry: false }
  }
  if (msg.includes('failed to fetch') || msg.includes('network') || msg.includes('网络')) {
    return { hint: '网络连接异常，请检查后重试', canRetry: true }
  }
  if (msg.includes('timeout') || msg.includes('超时')) {
    return { hint: '请求超时，请重试', canRetry: true }
  }
  if (msg.includes('401') || msg.includes('unauthorized') || msg.includes('登录')) {
    return { hint: '登录已失效，请重新登录', canRetry: false }
  }
  if (msg.includes('429') || msg.includes('frequent') || msg.includes('频繁')) {
    return { hint: '请求过于频繁，请稍后重试', canRetry: true }
  }
  if (msg.includes('500') || msg.includes('502') || msg.includes('503') || msg.includes('504') || msg.includes('服务器')) {
    return { hint: '服务器暂时不可用，请稍后重试', canRetry: true }
  }
  return { hint: '发生未知错误，请重试', canRetry: true }
}
