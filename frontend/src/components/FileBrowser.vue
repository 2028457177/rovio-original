<template>
  <div class="file-browser">
    <!-- 顶部：面包屑 + 刷新 -->
    <div class="fb-toolbar">
      <div class="fb-breadcrumb">
        <span class="fb-crumb fb-crumb-root" @click="goTo('')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
            <polyline points="9 22 9 12 15 12 15 22"></polyline>
          </svg>
          工作区
        </span>
        <template v-for="(seg, idx) in pathSegments" :key="idx">
          <span class="fb-sep">/</span>
          <span class="fb-crumb" @click="goTo(seg.path)">{{ seg.name }}</span>
        </template>
      </div>
      <button class="fb-btn-refresh" @click="load(currentPath)" :disabled="loading" title="刷新">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" :class="{ spinning: loading }">
          <polyline points="23 4 23 10 17 10"></polyline>
          <polyline points="1 20 1 14 7 14"></polyline>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
        </svg>
      </button>
    </div>

    <!-- 加载 / 空 / 错误 / 列表 -->
    <div class="fb-content">
      <div v-if="loading && entries.length === 0" class="fb-state">
        <div class="fb-spinner"></div>
        <span>加载中...</span>
      </div>

      <div v-else-if="error" class="fb-state fb-error">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <span>{{ error }}</span>
        <button class="fb-btn-retry" @click="load(currentPath)">重试</button>
      </div>

      <div v-else-if="entries.length === 0" class="fb-state fb-empty">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
        </svg>
        <span>空目录</span>
        <span class="fb-hint">AI 生成的文件会自动保存到这里</span>
      </div>

      <ul v-else class="fb-list">
        <!-- 返回上一级 -->
        <li v-if="currentPath" class="fb-item fb-item-up" @click="goTo(parentPath)">
          <span class="fb-icon">📁</span>
          <span class="fb-name">..</span>
        </li>
        <li
          v-for="entry in entries"
          :key="entry.path"
          class="fb-item"
          :class="{ 'fb-item-dir': entry.is_dir, 'fb-item-file': !entry.is_dir }"
          @click="onEntryClick(entry)"
        >
          <span class="fb-icon">{{ entry.is_dir ? '📁' : iconFor(entry) }}</span>
          <div class="fb-meta">
            <span class="fb-name" :title="entry.name">{{ entry.name }}</span>
            <span class="fb-sub" v-if="!entry.is_dir">
              {{ formatSize(entry.size) }} · {{ formatDate(entry.mtime) }}
            </span>
            <span class="fb-sub" v-else>
              {{ formatDate(entry.mtime) }}
            </span>
          </div>
          <button
            v-if="!entry.is_dir"
            class="fb-action"
            @click.stop="onDownload(entry)"
            title="下载"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
          </button>
          <button
            v-if="!entry.is_dir && windowDesktop"
            class="fb-action"
            @click.stop="onSaveLocal(entry)"
            title="保存到本地"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <line x1="22" y1="12" x2="2" y2="12"></line>
              <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>
              <line x1="6" y1="16" x2="6.01" y2="16"></line>
              <line x1="10" y1="16" x2="10.01" y2="16"></line>
            </svg>
          </button>
        </li>
      </ul>
    </div>

    <!-- 图片预览 modal -->
    <Teleport to="body">
      <Transition name="fb-preview-fade">
        <div v-if="previewImage" class="fb-preview-overlay" @click.self="previewImage = null">
          <button class="fb-preview-close" @click="previewImage = null">✕</button>
          <img :src="previewImage.url" :alt="previewImage.name" class="fb-preview-img" />
          <div class="fb-preview-info">
            <span>{{ previewImage.name }}</span>
            <button v-if="windowDesktop" class="fb-preview-dl" @click="onSaveLocal(previewImage.entry)">保存到本地</button>
            <button class="fb-preview-dl" @click="onDownload(previewImage.entry)">下载</button>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 文本预览 modal -->
    <Teleport to="body">
      <Transition name="fb-preview-fade">
        <div v-if="textContent !== null" class="fb-preview-overlay fb-preview-text-overlay" @click.self="textContent = null">
          <div class="fb-preview-text-panel">
            <div class="fb-preview-text-header">
              <span>{{ textContentName }}</span>
              <div>
                <button v-if="windowDesktop" class="fb-preview-dl" @click="onSaveLocal(textContentEntry)">保存到本地</button>
                <button class="fb-preview-dl" @click="onDownload(textContentEntry)">下载</button>
                <button class="fb-preview-close" @click="textContent = null">✕</button>
              </div>
            </div>
            <pre class="fb-preview-text-body">{{ textContent }}</pre>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { listWorkspace, downloadWorkspaceFile, fetchWorkspaceFileBlob } from '@/api/file.js'

const currentPath = ref('')
const parentPath = ref('')
const entries = ref([])
const loading = ref(false)
const error = ref('')

// 图片预览
const previewImage = ref(null)
// 文本预览
const textContent = ref(null)
const textContentName = ref('')
const textContentEntry = ref(null)

// 面包屑分段
const pathSegments = computed(() => {
  if (!currentPath.value) return []
  const parts = currentPath.value.split('/').filter(Boolean)
  const segs = []
  let acc = ''
  for (const p of parts) {
    acc = acc ? `${acc}/${p}` : p
    segs.push({ name: p, path: acc })
  }
  return segs
})

async function load(path = '') {
  loading.value = true
  error.value = ''
  try {
    const data = await listWorkspace(path)
    currentPath.value = data.path || ''
    parentPath.value = data.parent || ''
    entries.value = data.entries || []
  } catch (e) {
    error.value = e.message || '加载失败'
    entries.value = []
  } finally {
    loading.value = false
  }
}

function goTo(path) {
  load(path)
}

function onEntryClick(entry) {
  if (entry.is_dir) {
    load(entry.path)
  } else {
    // 根据类型预览
    if (entry.is_image) {
      previewImageFile(entry)
    } else if (entry.is_text) {
      previewTextFile(entry)
    } else {
      // 其他类型直接下载
      onDownload(entry)
    }
  }
}

async function previewImageFile(entry) {
  try {
    const blob = await fetchWorkspaceFileBlob(entry.path)
    const url = URL.createObjectURL(blob)
    previewImage.value = { url, name: entry.name, entry }
  } catch (e) {
    alert(e.message)
  }
}

async function previewTextFile(entry) {
  try {
    const blob = await fetchWorkspaceFileBlob(entry.path)
    const text = await blob.text()
    textContent.value = text
    textContentName.value = entry.name
    textContentEntry.value = entry
  } catch (e) {
    alert(e.message)
  }
}

function onDownload(entry) {
  downloadWorkspaceFile(entry.path)
}

// 桌面 App 独有能力：把服务器工作区文件一键保存到本地磁盘
const windowDesktop = !!window.desktop?.isDesktop

async function onSaveLocal(entry) {
  if (!window.desktop?.saveFile) return
  try {
    // 走下载接口拿原始字节，支持任意文件类型（含 docx 等）
    const res = await fetch(`/api/file/download?path=${encodeURIComponent(entry.path)}`)
    if (!res.ok) throw new Error(`获取文件失败 (${res.status})`)
    const data = await res.arrayBuffer()
    const result = await window.desktop.saveFile({ defaultName: entry.name, data })
    if (result?.saved) {
      alert(`已保存到：${result.path}`)
    }
  } catch (e) {
    alert(`保存失败：${e.message || e}`)
  }
}

// 工具函数
function iconFor(entry) {
  if (entry.is_dir) return '📁'
  const ext = entry.ext
  if (['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'].includes(ext)) return '🖼️'
  if (['.txt', '.md', '.log'].includes(ext)) return '📄'
  if (['.json', '.csv', '.yml', '.yaml', '.xml', '.ini'].includes(ext)) return '📊'
  if (['.py', '.js', '.ts', '.html', '.css'].includes(ext)) return '💻'
  return '📄'
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const now = new Date()
    const sameDay = d.toDateString() === now.toDateString()
    if (sameDay) {
      return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    }
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  } catch {
    return ''
  }
}

onMounted(() => {
  load('')
})

// 暴露刷新方法给父组件
defineExpose({ refresh: () => load(currentPath.value) })
</script>

<style scoped>
.file-browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 400px;
  background: transparent;
}

/* 顶部工具栏 */
.fb-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(0, 0, 0, 0.03);
}

.fb-breadcrumb {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
  min-width: 0;
  font-size: 13px;
}

.fb-crumb {
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  color: rgba(30, 30, 35, 0.75);
  transition: all 0.15s;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}
.fb-crumb:hover {
  background: rgba(0, 0, 0, 0.06);
  color: rgba(20, 20, 25, 0.95);
}
.fb-crumb-root {
  font-weight: 600;
  color: var(--accent-color, #2563eb);
}
.fb-sep {
  color: rgba(0, 0, 0, 0.3);
  user-select: none;
}

.fb-btn-refresh {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  background: rgba(0, 0, 0, 0.04);
  color: rgba(30, 30, 35, 0.7);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.fb-btn-refresh:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.08);
  color: rgba(20, 20, 25, 0.95);
}
.fb-btn-refresh:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.fb-btn-refresh .spinning {
  animation: fb-spin 1s linear infinite;
}
@keyframes fb-spin {
  to { transform: rotate(360deg); }
}

/* 内容区 */
.fb-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.fb-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 20px;
  color: rgba(80, 80, 90, 0.7);
  text-align: center;
}
.fb-state.fb-error { color: #dc2626; }
.fb-state.fb-empty .fb-hint {
  font-size: 12px;
  opacity: 0.6;
  margin-top: -4px;
}
.fb-btn-retry {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.15);
  background: rgba(0, 0, 0, 0.04);
  color: rgba(30, 30, 35, 0.85);
  cursor: pointer;
}
.fb-btn-retry:hover { background: rgba(0, 0, 0, 0.08); }

.fb-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid rgba(0, 0, 0, 0.15);
  border-top-color: var(--accent-color, #2563eb);
  border-radius: 50%;
  animation: fb-spin 0.8s linear infinite;
}

/* 列表 */
.fb-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.fb-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;
  border: 1px solid transparent;
}
.fb-item:hover {
  background: rgba(0, 0, 0, 0.04);
  border-color: rgba(0, 0, 0, 0.06);
}
.fb-item-up {
  opacity: 0.7;
  font-style: italic;
}

.fb-icon {
  font-size: 18px;
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.fb-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.fb-name {
  font-size: 13px;
  color: rgba(20, 20, 25, 0.95);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fb-sub {
  font-size: 11px;
  color: rgba(80, 80, 90, 0.65);
}

.fb-action {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: rgba(30, 30, 35, 0.6);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.15s;
}
.fb-item:hover .fb-action { opacity: 1; }
.fb-action:hover {
  background: rgba(37, 99, 235, 0.12);
  color: var(--accent-color, #2563eb);
  border-color: rgba(37, 99, 235, 0.3);
}

/* 预览 modal */
.fb-preview-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.88);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 30px;
}
.fb-preview-close {
  position: absolute;
  top: 20px;
  right: 20px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.1);
  color: white;
  font-size: 18px;
  cursor: pointer;
}
.fb-preview-close:hover { background: rgba(255, 255, 255, 0.2); }

.fb-preview-img {
  max-width: 90vw;
  max-height: 80vh;
  object-fit: contain;
  border-radius: 4px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
}

.fb-preview-info {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
}
.fb-preview-dl {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid rgba(91, 141, 239, 0.5);
  background: rgba(91, 141, 239, 0.2);
  color: var(--accent-color, #5b8def);
  cursor: pointer;
  font-size: 13px;
}
.fb-preview-dl:hover { background: rgba(91, 141, 239, 0.3); }

/* 文本预览 */
.fb-preview-text-overlay { padding: 40px; }
.fb-preview-text-panel {
  width: 100%;
  max-width: 900px;
  height: 100%;
  max-height: 80vh;
  background: rgba(30, 30, 35, 0.95);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.fb-preview-text-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  color: white;
  font-size: 14px;
}
.fb-preview-text-header > div {
  display: flex;
  align-items: center;
  gap: 10px;
}
.fb-preview-text-header .fb-preview-close {
  position: static;
  width: 28px;
  height: 28px;
}
.fb-preview-text-body {
  flex: 1;
  overflow: auto;
  margin: 0;
  padding: 16px;
  color: rgba(255, 255, 255, 0.88);
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 过渡动画 */
.fb-preview-fade-enter-active, .fb-preview-fade-leave-active {
  transition: opacity 0.2s;
}
.fb-preview-fade-enter-from, .fb-preview-fade-leave-to {
  opacity: 0;
}
</style>
