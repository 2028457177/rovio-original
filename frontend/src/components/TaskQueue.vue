<template>
  <div v-show="visible || isRunning" class="task-queue">
    <div class="tq-panel">
      <header class="tq-header">
        <div class="tq-title-wrap">
          <span class="tq-eyebrow">工作清单</span>
          <span class="tq-head-rule"></span>
        </div>
        <span v-if="tasks.length" class="tq-count serif">{{ String(tasks.length).padStart(2, '0') }}</span>
      </header>

      <!-- 添加任务输入区 -->
      <div class="tq-input-row">
        <input
          ref="inputRef"
          v-model="inputText"
          class="tq-input"
          placeholder="输入一个任务步骤…"
          :disabled="isRunning"
          @keydown.enter.prevent="addTask"
        />
        <button class="tq-add-btn" :disabled="!inputText.trim() || isRunning" @click="addTask" title="添加">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>

      <!-- 任务列表 -->
      <div class="tq-list" v-if="tasks.length">
        <TransitionGroup name="tq-item">
          <div
            v-for="(task, i) in tasks"
            :key="task.id"
            class="tq-item-wrap"
          >
            <div
              class="tq-item"
              :class="{ running: i === currentIdx && isRunning, scheduled: task.status === 'scheduled', done: task.status === 'done', failed: task.status === 'failed' }"
            >
              <span class="tq-idx serif">{{ String(i + 1).padStart(2, '0') }}</span>

              <span class="tq-status-dot">
                <!-- 待执行 -->
                <svg v-if="!task.status || task.status === 'pending'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="9" />
                </svg>
                <!-- 等待定时：时钟 -->
                <svg v-else-if="task.status === 'scheduled'" class="tq-pulse" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                <!-- 执行中：spinner -->
                <svg v-else-if="task.status === 'running'" class="tq-spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
                <!-- 完成 -->
                <svg v-else-if="task.status === 'done'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <!-- 失败 -->
                <svg v-else-if="task.status === 'failed'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </span>

              <div class="tq-text-wrap">
                <span class="tq-text">{{ task.text }}</span>
                <span v-if="task.scheduledTime" class="tq-sched-tag" @click.stop="!isRunning && openScheduler(i)">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                  {{ formatScheduleTime(task.scheduledTime) }}
                </span>
              </div>

              <!-- 操作按钮（非执行中显示） -->
              <div class="tq-actions" v-if="!isRunning">
                <button class="tq-act tq-timer-act" :class="{ active: task.scheduledTime }" title="定时" @click.stop="openScheduler(i)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                </button>
                <button class="tq-act" title="上移" :disabled="i === 0" @click.stop="moveTask(i, -1)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="18 15 12 9 6 15" />
                  </svg>
                </button>
                <button class="tq-act" title="下移" :disabled="i === tasks.length - 1" @click.stop="moveTask(i, 1)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>
                <button class="tq-act tq-del" title="删除" @click.stop="removeTask(i)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            </div>

            <!-- 单任务定时编辑器 -->
            <div class="tq-sched-editor" v-if="editingScheduleIdx === i">
              <input
                type="datetime-local"
                v-model="scheduleInput"
                :min="minDatetime"
                class="tq-dt-input"
              />
              <button class="tq-sched-ok" :disabled="!scheduleInput" @click="confirmSchedule(i)">确定</button>
              <button v-if="task.scheduledTime" class="tq-sched-clear-btn" @click="clearSchedule(i)">清除</button>
              <button class="tq-sched-cancel" @click="closeScheduler">取消</button>
            </div>
          </div>
        </TransitionGroup>
      </div>

      <!-- 空状态 -->
      <div class="tq-empty" v-else>
        <p class="serif tq-empty-lead">把复杂目标拆成小步骤，</p>
        <p>逐条写好后一键执行。</p>
      </div>

      <!-- 底部操作栏 -->
      <footer class="tq-footer" v-if="tasks.length">
        <div class="tq-progress" v-if="isRunning">
          <span class="tq-progress-text">{{ currentIdx + 1 }} / {{ tasks.length }}</span>
        </div>
        <div class="tq-footer-actions">
          <button
            v-if="!isRunning"
            class="tq-run-btn"
            @click="runAll"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
            一键执行
          </button>
          <button
            v-else
            class="tq-stop-btn"
            @click="stopRun"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="1" />
            </svg>
            停止
          </button>
          <button
            v-if="!isRunning && hasAnySchedule"
            class="tq-clear-btn"
            @click="clearAllSchedules"
            title="清除所有定时"
          >
            清除定时
          </button>
          <button
            v-if="!isRunning && tasks.some(t => t.status === 'done' || t.status === 'failed')"
            class="tq-clear-btn"
            @click="clearFinished"
          >
            清除已完成
          </button>
          <button
            v-if="!isRunning && tasks.length"
            class="tq-clear-btn"
            @click="clearAll"
          >
            全部清空
          </button>
        </div>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, computed } from 'vue'

const props = defineProps({
  /** 是否可见（欢迎页时为 true）。执行中强制保持可见以显示进度 */
  visible: { type: Boolean, default: true },
  /** 执行单个任务，返回 Promise，resolve=完成，reject=失败 */
  onExecuteTask: { type: Function, required: true }
})

const emit = defineEmits(['stop', 'start', 'end'])

const STORAGE_KEY = 'lc_task_queue'

const inputText = ref('')
const inputRef = ref(null)
const tasks = ref(loadTasks())
const isRunning = ref(false)
const currentIdx = ref(-1)
// 当前正在编辑定时的任务索引（-1=无）
const editingScheduleIdx = ref(-1)
const scheduleInput = ref('')

// 本地时区当前时间字符串（datetime-local 格式）
function nowLocalStr() {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}
// ref 而非 computed：computed 依赖 new Date()（非响应式）只算一次，
// 会导致 :min 停留在组件首次渲染时刻，用户可借此选到过去时间
const minDatetime = ref(nowLocalStr())

function formatScheduleTime(ts) {
  const d = new Date(ts)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

// 是否有任意任务设了定时
const hasAnySchedule = computed(() => tasks.value.some(t => t.scheduledTime))

// ---- 持久化 ----
function loadTasks() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    // 恢复时清除执行状态（上次可能中途中断），保留 scheduledTime
    return arr.map(t => ({
      id: t.id,
      text: t.text,
      scheduledTime: t.scheduledTime || null,
      status: 'pending'
    }))
  } catch {
    return []
  }
}

function persist() {
  try {
    // 持久化 id + text + scheduledTime，不存运行态
    const data = tasks.value.map(t => ({
      id: t.id,
      text: t.text,
      scheduledTime: t.scheduledTime || null
    }))
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {}
}

watch(tasks, persist, { deep: true })

// ---- 任务操作 ----
function addTask() {
  const text = inputText.value.trim()
  if (!text || isRunning.value) return
  tasks.value.push({
    id: Date.now() + Math.random(),
    text,
    scheduledTime: null,
    status: 'pending'
  })
  inputText.value = ''
  nextTick(() => inputRef.value?.focus())
}

function removeTask(idx) {
  if (isRunning.value) return
  tasks.value.splice(idx, 1)
  if (editingScheduleIdx.value === idx) editingScheduleIdx.value = -1
}

function moveTask(idx, dir) {
  if (isRunning.value) return
  const target = idx + dir
  if (target < 0 || target >= tasks.value.length) return
  const arr = tasks.value
  ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
}

// 单任务定时编辑
function openScheduler(idx) {
  if (isRunning.value) return
  editingScheduleIdx.value = idx
  // 打开时实时刷新最小可选时间，避免 :min 停留在旧值
  minDatetime.value = nowLocalStr()
  // 预填已有定时
  const t = tasks.value[idx]
  if (t.scheduledTime) {
    const d = new Date(t.scheduledTime)
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
    scheduleInput.value = d.toISOString().slice(0, 16)
  } else {
    scheduleInput.value = ''
  }
}

function confirmSchedule(idx) {
  if (!scheduleInput.value) return
  const ts = new Date(scheduleInput.value).getTime()
  if (!ts) return
  // 实时校验：防止用户打开编辑器后停留过久导致所选时间已过期
  if (ts <= Date.now()) {
    alert('定时时间必须晚于当前时间，请重新选择')
    minDatetime.value = nowLocalStr()
    return
  }
  tasks.value[idx].scheduledTime = ts
  editingScheduleIdx.value = -1
  scheduleInput.value = ''
}

function clearSchedule(idx) {
  tasks.value[idx].scheduledTime = null
  editingScheduleIdx.value = -1
  scheduleInput.value = ''
}

function closeScheduler() {
  editingScheduleIdx.value = -1
  scheduleInput.value = ''
}

function clearFinished() {
  tasks.value = tasks.value.filter(t => t.status !== 'done' && t.status !== 'failed')
}

function clearAll() {
  tasks.value = []
  editingScheduleIdx.value = -1
}

// 清除所有定时
function clearAllSchedules() {
  tasks.value.forEach(t => { t.scheduledTime = null })
  editingScheduleIdx.value = -1
}

// ---- 执行 ----
// 等待到指定时间戳，期间每秒检查是否被停止
function waitUntil(timestamp) {
  return new Promise((resolve) => {
    const check = () => {
      if (!isRunning.value) return resolve(false)
      if (Date.now() >= timestamp) return resolve(true)
      setTimeout(check, 500)
    }
    check()
  })
}

// 执行单个任务（与 runAll 解耦，支持并行调用）
async function executeOne(idx) {
  const task = tasks.value[idx]
  currentIdx.value = idx
  task.status = 'running'
  try {
    await props.onExecuteTask(task.text)
    // stopRun 不会改 status，故仍为 running 时才置 done
    if (task.status === 'running') task.status = 'done'
  } catch {
    task.status = 'failed'
    // 失败不影响其他任务
  }
}

async function runAll() {
  if (isRunning.value || !tasks.value.length) return
  isRunning.value = true
  currentIdx.value = -1
  editingScheduleIdx.value = -1
  emit('start')

  // 重置状态（保留 scheduledTime）
  tasks.value.forEach(t => { t.status = 'pending' })

  // 混合调度：非定时任务串行接龙，定时任务到点独立并行执行（抢占）
  // 这样定时任务到点时无需等待前一个未完成的任务，避免被无限延迟
  const allPromises = []
  let serialChain = Promise.resolve()

  for (let i = 0; i < tasks.value.length; i++) {
    if (!isRunning.value) break
    const task = tasks.value[i]
    const idx = i

    if (task.scheduledTime) {
      // 定时任务：到点独立执行（并行抢占）
      allPromises.push((async () => {
        task.status = 'scheduled'
        const ok = await waitUntil(task.scheduledTime)
        if (!isRunning.value || !ok) {
          if (task.status !== 'done') task.status = 'failed'
          return
        }
        await executeOne(idx)
      })())
    } else {
      // 非定时任务：串行接龙，等前一个非定时任务完成
      serialChain = serialChain.then(async () => {
        if (!isRunning.value) return
        await executeOne(idx)
      })
      allPromises.push(serialChain)
    }
  }

  await Promise.all(allPromises)

  isRunning.value = false
  currentIdx.value = -1
  emit('end')
}

function stopRun() {
  isRunning.value = false
  emit('stop')
}
</script>

<style scoped>
/* ============================================================
   工作清单 · 编辑式栏注（marginalia）
   背景与页面同色，仅以左侧细线界定栏位，不浮起、不投影
   ============================================================ */

.task-queue {
  position: fixed;
  top: 22px;
  right: 22px;
  z-index: 800;
  width: 328px;
  max-width: calc(100vw - 44px);
  background: transparent;
}

/* ---- 面板：纸面栏注 ---- */
.tq-panel {
  position: relative;
  padding: 2px 16px 4px 22px;
  /* 与页面背景完全一致 → 完美融入 */
  background: var(--bg);
  /* 左侧栏线：唯一界定，极细 */
  border-left: 1px solid var(--border-light);
  animation: tq-fade-in 0.55s var(--ease-out-expo) both;
}

@keyframes tq-fade-in {
  from { opacity: 0; transform: translateX(10px); }
  to   { opacity: 1; transform: translateX(0); }
}

/* ---- 页眉：刊眉 + 期数 ---- */
.tq-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0 12px;
  border-bottom: 1px solid var(--border-light);
}
.tq-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.tq-eyebrow {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.2em;
  color: var(--text-secondary);
  white-space: nowrap;
}
.tq-head-rule {
  flex: 0 1 38px;
  height: 1px;
  background: var(--border);
}
.tq-count {
  font-size: 13px;
  font-weight: 400;
  color: var(--text-muted);
  letter-spacing: 0.04em;
  font-feature-settings: "lnum";
}

/* ---- 输入区：底线式 ---- */
.tq-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 0 10px;
}
.tq-input {
  flex: 1;
  min-width: 0;
  height: 30px;
  padding: 0 2px;
  border: none;
  border-bottom: 1px solid var(--border-light);
  border-radius: 0;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-family: var(--font-body);
  outline: none;
  transition: border-color 0.25s var(--ease-out-expo);
}
.tq-input::placeholder {
  color: var(--text-muted);
  font-style: italic;
}
.tq-input:focus {
  border-bottom-color: var(--text);
}
.tq-input:disabled {
  opacity: 0.45;
}
.tq-add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.3s var(--ease-out-expo);
}
.tq-add-btn:hover:not(:disabled) {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-contrast);
  transform: rotate(90deg);
}
.tq-add-btn:disabled {
  opacity: 0.25;
  cursor: not-allowed;
}

/* ---- 任务列表：账簿式 ---- */
.tq-list {
  max-height: 360px;
  overflow-y: auto;
  padding: 2px 0 4px;
}
.tq-item-wrap {
  position: relative;
}
.tq-item-wrap + .tq-item-wrap .tq-item {
  border-top: 1px solid var(--border-light);
}
.tq-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 6px 11px 8px;
  border-radius: 0;
  position: relative;
  transition: background 0.2s ease;
}
.tq-item:hover {
  background: var(--accent-light);
}
/* 运行中：左侧墨色栏注条 */
.tq-item.running {
  background: var(--accent-light);
  box-shadow: inset 2px 0 0 var(--accent);
}
.tq-item.scheduled {
  box-shadow: inset 2px 0 0 var(--text-muted);
}
.tq-idx {
  flex-shrink: 0;
  width: 24px;
  text-align: right;
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 400;
  letter-spacing: 0.02em;
  font-feature-settings: "lnum";
}
.tq-status-dot {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  color: var(--text-muted);
}
.tq-item.done .tq-status-dot {
  color: var(--text);
}
.tq-item.done .tq-text {
  text-decoration: line-through;
  text-decoration-thickness: 1px;
  opacity: 0.42;
}
.tq-item.failed .tq-status-dot {
  color: var(--danger);
}
.tq-item.failed .tq-text {
  color: var(--danger);
}
.tq-item.running .tq-status-dot {
  color: var(--text);
}
.tq-item.scheduled .tq-status-dot {
  color: var(--text-secondary);
}
.tq-text-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tq-text {
  font-size: 13px;
  line-height: 1.55;
  color: var(--text);
  word-break: break-word;
}
/* 定时标签 */
.tq-sched-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  width: fit-content;
  padding: 2px 8px;
  border-radius: 2px;
  background: var(--accent-light);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.5;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition: all 0.2s ease;
}
.tq-sched-tag:hover {
  background: var(--accent-soft);
  color: var(--text);
}
.tq-actions {
  display: flex;
  gap: 1px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.2s ease;
}
.tq-item:hover .tq-actions {
  opacity: 1;
}
.tq-act {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s ease;
}
.tq-act:hover:not(:disabled) {
  color: var(--text);
  background: var(--accent-soft);
}
.tq-act:disabled {
  opacity: 0.2;
  cursor: not-allowed;
}
.tq-del:hover:not(:disabled) {
  color: var(--danger);
  background: var(--danger-soft);
}
/* 定时按钮高亮（已设定时） */
.tq-timer-act.active {
  color: var(--text);
  background: var(--accent-soft);
}

/* ---- 单任务定时编辑器 ---- */
.tq-sched-editor {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 4px 0 10px 42px;
  animation: tq-slide-down 0.22s var(--ease-out-expo) both;
}
@keyframes tq-slide-down {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.tq-dt-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 6px;
  border: none;
  border-bottom: 1px solid var(--border);
  border-radius: 0;
  background: transparent;
  color: var(--text);
  font-size: 12px;
  font-family: var(--font-body);
  outline: none;
  transition: border-color 0.2s ease;
}
.tq-dt-input:focus {
  border-bottom-color: var(--text);
}
.tq-sched-ok {
  height: 28px;
  padding: 0 12px;
  border: none;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.tq-sched-ok:hover:not(:disabled) {
  background: var(--accent-hover);
}
.tq-sched-ok:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.tq-sched-clear-btn {
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--danger-border);
  border-radius: 999px;
  background: transparent;
  color: var(--danger);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.tq-sched-clear-btn:hover {
  background: var(--danger-soft);
  border-color: var(--danger);
}
.tq-sched-cancel {
  height: 28px;
  padding: 0 10px;
  border: none;
  background: none;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: color 0.2s ease;
}
.tq-sched-cancel:hover {
  color: var(--text);
}

/* ---- 空状态 ---- */
.tq-empty {
  padding: 28px 4px 24px;
  text-align: left;
}
.tq-empty p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--text-muted);
}
.tq-empty-lead {
  color: var(--text-secondary);
  font-size: 14px;
  letter-spacing: 0.02em;
}

/* ---- 底部操作栏 ---- */
.tq-footer {
  padding: 12px 0 6px;
  border-top: 1px solid var(--border-light);
  margin-top: 2px;
}
.tq-progress {
  text-align: center;
  margin-bottom: 10px;
}
.tq-progress-text {
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--text-muted);
  font-weight: 500;
}
.tq-footer-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.tq-run-btn {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border: none;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: all 0.25s var(--ease-out-expo);
}
.tq-run-btn:hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
}
.tq-stop-btn {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border: none;
  border-radius: 999px;
  background: var(--danger);
  color: #fff;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: all 0.25s var(--ease-out-expo);
}
.tq-stop-btn:hover {
  background: var(--danger-hover);
  transform: translateY(-1px);
}
.tq-clear-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  padding: 0 4px;
  border: none;
  background: none;
  color: var(--text-muted);
  font-size: 11.5px;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition: color 0.2s ease;
}
.tq-clear-btn:hover {
  color: var(--text);
  text-decoration: underline;
  text-underline-offset: 4px;
}

/* ---- spinner / pulse ---- */
.tq-spinner {
  animation: tq-spin 0.8s linear infinite;
}
@keyframes tq-spin {
  to { transform: rotate(360deg); }
}
.tq-pulse {
  animation: tq-pulse 1.8s ease-in-out infinite;
}
@keyframes tq-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ---- 列表动画 ---- */
.tq-item-enter-active,
.tq-item-leave-active {
  transition: all 0.3s var(--ease-out-expo);
}
.tq-item-enter-from {
  opacity: 0;
  transform: translateX(10px);
}
.tq-item-leave-to {
  opacity: 0;
  transform: translateX(-10px);
}
.tq-item-leave-active {
  position: absolute;
}

/* ---- 滚动条 ---- */
.tq-list::-webkit-scrollbar {
  width: 3px;
}
.tq-list::-webkit-scrollbar-track {
  background: transparent;
}
.tq-list::-webkit-scrollbar-thumb {
  background: var(--border-light);
  border-radius: 2px;
}
.tq-list::-webkit-scrollbar-thumb:hover {
  background: var(--border);
}

/* ---- 移动端 ---- */
@media (max-width: 767px) {
  .task-queue {
    top: 14px;
    right: 14px;
    width: calc(100vw - 28px);
    max-width: 320px;
  }
}
</style>
