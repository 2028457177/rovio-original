/**
 * 知识库管理 API 客户端
 * - admin 前缀：/api/admin/kb/...（全局知识库，管理员）
 * - user  前缀：/api/kb/...      （个人知识库，登录用户）
 */
function headers(extra = {}) {
  // JWT 存于 HttpOnly Cookie，同源请求自动携带
  return { ...extra }
}

async function parse(response) {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || data.detail || `请求失败（${response.status}）`)
  }
  return data
}

function base(scope) {
  return scope === 'admin' ? '/api/admin/kb' : '/api/kb'
}

// ==================== 知识库 ====================

/** 知识库列表。admin: {kbs}; user: {kbs(个人), global_kbs} */
export async function listKbs(scope) {
  const url = scope === 'admin' ? `${base(scope)}/list` : `${base(scope)}/mine`
  const res = await fetch(url, { headers: headers() })
  return parse(res)
}

export async function createKb(scope, { name, biz_line = '', description = '' }) {
  const url = scope === 'admin' ? `${base(scope)}/create` : `${base(scope)}/mine`
  const res = await fetch(url, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name, biz_line, description }),
  })
  return parse(res)
}

export async function updateKb(scope, kbId, fields) {
  const url = scope === 'admin' ? `${base(scope)}/${kbId}` : `${base(scope)}/mine/${kbId}`
  const res = await fetch(url, {
    method: 'PATCH',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(fields),
  })
  return parse(res)
}

export async function deleteKb(scope, kbId) {
  const url = scope === 'admin' ? `${base(scope)}/${kbId}` : `${base(scope)}/mine/${kbId}`
  const res = await fetch(url, { method: 'DELETE', headers: headers() })
  return parse(res)
}

// ==================== 文档 ====================

export async function listDocuments(scope, kbId) {
  const url = scope === 'admin' ? `${base(scope)}/${kbId}/documents` : `${base(scope)}/mine/${kbId}/documents`
  const res = await fetch(url, { headers: headers() })
  return parse(res)
}

/** 批量上传（拖拽多文件）。files: File[] */
export async function uploadDocuments(scope, kbId, files) {
  const formData = new FormData()
  for (const f of files) formData.append('files', f)
  const url = scope === 'admin' ? `${base(scope)}/${kbId}/documents` : `${base(scope)}/mine/${kbId}/documents`
  const res = await fetch(url, { method: 'POST', headers: headers(), body: formData })
  return parse(res)
}

/**
 * 批量上传（带传输进度回调，基于 XHR）。
 * onProgress: (ratio: 0~1) => void，仅表示字节传输进度；
 * 到达 1 后服务器仍在写入 / 触发索引，需等待响应返回。
 */
export function uploadDocumentsWithProgress(scope, kbId, files, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData()
    for (const f of files) formData.append('files', f)
    const url = scope === 'admin' ? `${base(scope)}/${kbId}/documents` : `${base(scope)}/mine/${kbId}/documents`
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && typeof onProgress === 'function') {
        onProgress(Math.min(1, e.loaded / e.total))
      }
    })
    xhr.onload = () => {
      let data = {}
      try { data = JSON.parse(xhr.responseText || '{}') } catch { /* 忽略非 JSON 响应 */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data)
      else reject(new Error(data.error || data.detail || `请求失败（${xhr.status}）`))
    }
    xhr.onerror = () => reject(new Error('网络异常，上传失败'))
    xhr.ontimeout = () => reject(new Error('上传超时，请重试'))
    xhr.send(formData)
  })
}

export async function deleteDocument(scope, kbId, docId) {
  const url = scope === 'admin'
    ? `${base(scope)}/${kbId}/documents/${docId}`
    : `${base(scope)}/mine/${kbId}/documents/${docId}`
  const res = await fetch(url, { method: 'DELETE', headers: headers() })
  return parse(res)
}

export async function batchDeleteDocuments(scope, kbId, docIds) {
  const url = scope === 'admin'
    ? `${base(scope)}/${kbId}/documents/batch-delete`
    : `${base(scope)}/mine/${kbId}/documents/batch-delete`
  const res = await fetch(url, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ doc_ids: docIds }),
  })
  return parse(res)
}

/** 替换文档文件（版本+1，自动重索引） */
export async function replaceDocument(scope, kbId, docId, file) {
  const formData = new FormData()
  formData.append('file', file)
  const url = scope === 'admin'
    ? `${base(scope)}/${kbId}/documents/${docId}/replace`
    : `${base(scope)}/mine/${kbId}/documents/${docId}/replace`
  const res = await fetch(url, { method: 'POST', headers: headers(), body: formData })
  return parse(res)
}

/** 增量更新：重建单个文档索引 */
export async function reindexDocument(scope, kbId, docId) {
  const url = scope === 'admin'
    ? `${base(scope)}/${kbId}/documents/${docId}/reindex`
    : `${base(scope)}/mine/${kbId}/documents/${docId}/reindex`
  const res = await fetch(url, { method: 'POST', headers: headers() })
  return parse(res)
}

/** 分块预览 */
export async function previewChunks(scope, kbId, docId, offset = 0, limit = 20) {
  const url = scope === 'admin'
    ? `${base(scope)}/${kbId}/documents/${docId}/chunks?offset=${offset}&limit=${limit}`
    : `${base(scope)}/mine/${kbId}/documents/${docId}/chunks?offset=${offset}&limit=${limit}`
  const res = await fetch(url, { headers: headers() })
  return parse(res)
}

/** 重建整个知识库索引 */
export async function rebuildKb(scope, kbId) {
  const url = scope === 'admin' ? `${base(scope)}/${kbId}/rebuild` : `${base(scope)}/mine/${kbId}/rebuild`
  const res = await fetch(url, { method: 'POST', headers: headers() })
  return parse(res)
}

/** 检索测试 playground */
export async function searchTest(scope, { query, kbIds = null, topK = 3 }) {
  const res = await fetch(`${base(scope)}/search-test`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ query, kb_ids: kbIds, top_k: topK }),
  })
  return parse(res)
}

/** 嵌入模型诊断（仅管理端）：提供者 / 模型 / 维度 / 可用性 */
export async function embeddingStatus() {
  const res = await fetch('/api/admin/kb/embedding-status', { headers: headers() })
  return parse(res)
}
