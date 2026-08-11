<template>
  <div class="chat-input-area" :class="{ 'center-mode': centerMode }">
    <div class="input-glow" :class="{ active: isFocused }"></div>
    <div class="chat-input-wrapper">
      <div class="chat-input-box" :class="{ focused: isFocused, streaming: isStreaming, 'has-file': uploadedFileName }" @mousemove="onSpotlightMove">
        <!-- 已上传文件提示 -->
        <Transition name="file-tag">
          <div v-if="uploadedFileName" class="uploaded-file-tag">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            <span>{{ uploadedFileName }}</span>
            <button class="file-remove-btn" @click="removeUploadedFile" title="移除文件">&times;</button>
          </div>
        </Transition>
        <!-- 文件上传按钮 -->
        <input
          ref="fileInputRef"
          type="file"
          accept=".docx,.doc"
          class="file-input-hidden"
          @change="handleFileSelected"
        />
        <button
          class="attach-btn"
          :class="{ uploading: isUploading }"
          :disabled="disabled || isUploading"
          @click="triggerFileSelect"
          title="上传Word文件"
        >
          <svg v-if="!isUploading" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
          </svg>
          <span v-else class="mini-spinner"></span>
        </button>
        <textarea
          ref="inputRef"
          v-model="inputText"
          :disabled="disabled"
          placeholder="输入你的问题…"
          rows="1"
          @input="autoResize"
          @keydown="handleKeydown"
          @focus="isFocused = true"
          @blur="isFocused = false"
        ></textarea>
        <button
          v-if="!isStreaming"
          class="send-btn"
          :class="{ disabled: disabled || (!inputText.trim() && !uploadedFilePath) }"
          :disabled="disabled || (!inputText.trim() && !uploadedFilePath)"
          @click="handleSend"
          title="发送消息"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="19" x2="12" y2="5"></line>
            <polyline points="5 12 12 5 19 12"></polyline>
          </svg>
        </button>
        <button
          v-else
          class="send-btn stop"
          @click="handleStop"
          title="停止生成"
        >
          <svg viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="6" width="12" height="12" rx="2"></rect>
          </svg>
        </button>
      </div>
    </div>

    <!-- 底部工具行：左侧联网搜索开关，右侧快捷键提示 -->
    <div class="chat-input-tools">
      <button
        type="button"
        class="search-toggle"
        :class="{ on: searchEnabled }"
        @click="emit('toggleSearch')"
        title="联网搜索开关：关闭后 AI 不再上网检索"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <span>{{ searchEnabled ? '联网搜索已开启' : '联网搜索已关闭' }}</span>
        <span class="toggle-knob" aria-hidden="true"><span class="knob-dot"></span></span>
      </button>
      <span class="input-hints" aria-hidden="true">Enter 发送 · Shift+Enter 换行</span>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch, onUnmounted } from 'vue'
import { uploadWordFile } from '@/api/chat.js'

const props = defineProps({
  disabled: {
    type: Boolean,
    default: false
  },
  centerMode: {
    type: Boolean,
    default: false
  },
  isStreaming: {
    type: Boolean,
    default: false
  },
  searchEnabled: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['send', 'stop', 'toggleSearch'])

const inputText = ref('')
const inputRef = ref(null)
const fileInputRef = ref(null)
const isFocused = ref(false)

watch(isFocused, (focused) => {
  document.body.classList.toggle('input-focused', focused)
})

onUnmounted(() => {
  document.body.classList.remove('input-focused')
})

const isUploading = ref(false)
const uploadedFileName = ref('')
const uploadedFilePath = ref('')

function autoResize() {
  nextTick(() => {
    const el = inputRef.value
    if (el) {
      const baseHeight = props.centerMode ? 84 : 48
      el.style.height = baseHeight + 'px'
      el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    }
  })
}

function onSpotlightMove(e) {
  const box = e.currentTarget
  const rect = box.getBoundingClientRect()
  const x = ((e.clientX - rect.left) / rect.width) * 100
  const y = ((e.clientY - rect.top) / rect.height) * 100
  box.style.setProperty('--sx', `${x}%`)
  box.style.setProperty('--sy', `${y}%`)
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function triggerFileSelect() {
  fileInputRef.value?.click()
}

async function handleFileSelected(e) {
  const file = e.target.files?.[0]
  if (!file) return

  isUploading.value = true
  try {
    const result = await uploadWordFile(file)
    uploadedFileName.value = result.original_name
    uploadedFilePath.value = result.server_path
  } catch (err) {
    alert('文件上传失败：' + err.message)
  } finally {
    isUploading.value = false
    // 重置 input 以便可以重复上传同一文件
    if (fileInputRef.value) {
      fileInputRef.value.value = ''
    }
  }
}

function removeUploadedFile() {
  uploadedFileName.value = ''
  uploadedFilePath.value = ''
}

function handleSend() {
  const text = inputText.value.trim()
  if ((!text && !uploadedFilePath.value) || props.disabled) return

  emit('send', text, uploadedFilePath.value)
  inputText.value = ''
  uploadedFileName.value = ''
  uploadedFilePath.value = ''
  nextTick(() => {
    if (inputRef.value) {
      const baseHeight = props.centerMode ? 84 : 48
      inputRef.value.style.height = baseHeight + 'px'
    }
  })
}

function handleStop() {
  emit('stop')
}
</script>

<style scoped>
.chat-input-area {
  padding: 18px 24px 20px;
  background: linear-gradient(180deg, transparent, var(--panel) 30%);
  border-top: 1px solid var(--border-light);
  flex-shrink: 0;
  position: relative;
}

.input-glow {
  position: absolute;
  top: -1px;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  transition: width 0.5s var(--ease-out-expo);
}

.input-glow.active {
  width: 56%;
}

.chat-input-wrapper {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.chat-input-box {
  flex: 1;
  position: relative;
  border-radius: var(--radius);
  transition: border-color var(--transition), box-shadow var(--transition), transform var(--transition), background var(--transition);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: 0 2px 12px var(--shadow-sm);
  overflow: hidden;
}

/* 鼠标跟随墨晕 */
.chat-input-box::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  background: radial-gradient(
    420px circle at var(--sx, 50%) var(--sy, 50%),
    rgba(var(--accent-rgb), 0.05),
    transparent 45%
  );
  transition: opacity 0.3s ease;
}

/* 已挂载文件：边框微微提亮 */
.chat-input-box.has-file {
  border-color: rgba(var(--accent-rgb), 0.3);
}

/* 流式生成中：顶部墨线扫过 + 边框轻染 */
.chat-input-box.streaming {
  border-color: rgba(var(--accent-rgb), 0.22);
}

.chat-input-box.streaming::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 60%;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(var(--accent-rgb), 0.55), transparent);
  animation: input-streaming 1.5s var(--ease-out-expo) infinite;
  pointer-events: none;
}

@keyframes input-streaming {
  0% { transform: translateX(-40%); opacity: 0; }
  15% { opacity: 1; }
  85% { opacity: 1; }
  100% { transform: translateX(240%); opacity: 0; }
}

.chat-input-box.focused::before {
  opacity: 1;
}

.chat-input-box.focused {
  border-color: rgba(var(--accent-rgb), 0.5);
  box-shadow:
    0 0 0 3px rgba(var(--accent-rgb), 0.07),
    0 12px 34px var(--shadow-sm);
}

.chat-input-box textarea {
  width: 100%;
  border: none;
  background: transparent;
  padding: 16px 60px 16px 50px;
  font-size: 14.5px;
  font-family: inherit;
  resize: none;
  outline: none;
  color: var(--text);
  line-height: 1.6;
  min-height: 50px;
  max-height: 200px;
}

.chat-input-box textarea::placeholder {
  color: var(--text-muted);
}

.chat-input-box textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* —— 发送按钮：墨色圆钮，整框唯一重色 —— */
.send-btn {
  position: absolute;
  right: 9px;
  bottom: 9px;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  color: var(--accent-contrast);
  background: linear-gradient(180deg, var(--accent-hover), var(--accent));
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform var(--spring-fast), box-shadow var(--spring-fast), filter var(--transition), background var(--transition), opacity var(--transition);
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(var(--accent-rgb), 0.28);
  z-index: 2;
  overflow: hidden;
}

.send-btn svg {
  width: 17px;
  height: 17px;
  transition: transform var(--spring-fast);
}

.send-btn:hover:not(.disabled) {
  transform: translateY(-2px) scale(1.06);
  box-shadow: 0 9px 26px rgba(var(--accent-rgb), 0.48);
  filter: brightness(1.06);
}

.send-btn:hover:not(.disabled) svg {
  transform: translateY(-2px);
}

.send-btn:active:not(.disabled) {
  transform: scale(0.92);
}

.send-btn.disabled {
  background: var(--accent-soft);
  box-shadow: none;
  cursor: not-allowed;
  opacity: 0.55;
  color: var(--text-muted);
}

/* —— 停止按钮（流式时替换发送键） —— */
.send-btn.stop {
  background: linear-gradient(180deg, #ff6b6b, #ee5253);
  box-shadow: 0 5px 16px rgba(220, 50, 50, 0.35);
}

.send-btn.stop:hover {
  transform: translateY(-2px) scale(1.06);
  box-shadow: 0 9px 26px rgba(220, 50, 50, 0.48);
  filter: brightness(1.06);
}

.send-btn.stop svg {
  width: 14px;
  height: 14px;
}

.send-btn.stop:active {
  transform: scale(0.92);
}

/* —— 附件按钮：无边框图标，hover 浮现墨圈 —— */
.file-input-hidden {
  display: none;
}

.attach-btn {
  position: absolute;
  left: 8px;
  bottom: 8px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  color: var(--text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color var(--transition), background var(--transition), transform var(--spring-fast);
  flex-shrink: 0;
  z-index: 2;
}

.attach-btn:hover:not(:disabled) {
  color: var(--text);
  background: var(--accent-light);
  transform: scale(1.08);
}

.attach-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.attach-btn.uploading {
  color: var(--accent);
}

.mini-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent-soft);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* —— 文件标签 —— */
.uploaded-file-tag {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  margin: 10px 10px 0;
  background: var(--accent-light);
  border: 1px solid rgba(var(--accent-rgb), 0.22);
  border-radius: var(--radius-pill);
  font-size: 11.5px;
  font-weight: 600;
  color: var(--accent-hover);
  max-width: fit-content;
}

[data-theme="dark"] .uploaded-file-tag {
  color: var(--accent);
}

.uploaded-file-tag svg {
  flex-shrink: 0;
}

.uploaded-file-tag span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-remove-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  padding: 0 2px;
  color: var(--text-muted);
  flex-shrink: 0;
  transition: color var(--transition), transform var(--spring-fast);
}

.file-remove-btn:hover {
  color: var(--danger);
  transform: scale(1.2);
}

.file-tag-enter-active,
.file-tag-leave-active {
  transition: opacity 0.25s ease, transform 0.3s var(--ease-out-expo);
}

.file-tag-enter-from,
.file-tag-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.94);
}

/* —— 底部工具行 —— */
.chat-input-tools {
  max-width: 860px;
  margin: 0 auto;
  padding-top: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.input-hints {
  font-size: 11px;
  color: var(--text-muted);
  letter-spacing: 0.4px;
  white-space: nowrap;
  user-select: none;
  opacity: 0.85;
}

.search-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: color var(--transition), border-color var(--transition), background var(--transition);
}

.search-toggle:hover {
  color: var(--accent);
  border-color: rgba(var(--accent-rgb), 0.4);
}

.search-toggle.on {
  color: var(--accent);
  border-color: rgba(var(--accent-rgb), 0.4);
  background: var(--accent-light);
}

.toggle-knob {
  width: 26px;
  height: 15px;
  border-radius: 10px;
  background: var(--border-strong, var(--border));
  position: relative;
  transition: background var(--transition);
  flex-shrink: 0;
}

.search-toggle.on .toggle-knob {
  background: var(--accent);
}

.knob-dot {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: #fff;
  transition: transform var(--spring-fast);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
}

.search-toggle.on .knob-dot {
  transform: translateX(11px);
}

/* —— 居中模式（欢迎页） —— */
.chat-input-area.center-mode {
  padding: 0;
  background: transparent;
  border-top: none;
}

.chat-input-area.center-mode .chat-input-box {
  border-radius: var(--radius-lg);
  box-shadow: 0 10px 36px var(--shadow-sm);
}

.chat-input-area.center-mode .chat-input-box textarea {
  min-height: 84px;
}

.chat-input-area.center-mode .chat-input-box.focused {
  box-shadow:
    0 0 0 3.5px rgba(var(--accent-rgb), 0.1),
    0 16px 48px var(--shadow);
}

.chat-input-area.center-mode .chat-input-tools {
  justify-content: flex-end;
}

.chat-input-area.center-mode .input-hints {
  display: none;
}

@media (max-width: 767px) {
  .chat-input-area {
    padding: 10px 12px;
    padding-bottom: calc(10px + var(--safe-bottom));
    background: var(--panel);
    border-top: 0.5px solid var(--border-light);
  }

  .input-glow {
    display: none;
  }

  .chat-input-wrapper {
    max-width: 100%;
  }

  .chat-input-box {
    border-radius: 18px;
    border: 1px solid var(--border);
    background: var(--panel);
    box-shadow: none;
  }

  .chat-input-box.focused {
    border-color: rgba(var(--accent-rgb), 0.5);
    background: var(--panel);
    box-shadow: 0 0 0 2.5px rgba(var(--accent-rgb), 0.12);
  }

  .chat-input-box textarea {
    padding: 11px 48px 11px 46px;
    font-size: 15px;
    min-height: 42px;
    line-height: 1.4;
  }

  .send-btn {
    width: 32px;
    height: 32px;
    right: 6px;
    bottom: 6px;
  }

  .send-btn svg {
    width: 15px;
    height: 15px;
  }

  .attach-btn {
    width: 32px;
    height: 32px;
    left: 7px;
    bottom: 7px;
  }

  .chat-input-area.center-mode {
    padding: 0 12px;
    background: transparent;
    border: none;
  }

  .chat-input-area.center-mode .chat-input-box {
    border-radius: 24px;
    background: var(--panel);
    border: 1px solid var(--border);
    box-shadow: 0 2px 10px var(--shadow-sm);
  }

  .chat-input-area.center-mode .chat-input-box textarea {
    min-height: 46px;
    padding: 11px 48px 11px 46px;
    font-size: 15px;
  }
}
</style>
