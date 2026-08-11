<template>
  <div class="admin-page">
    <div class="animated-bg">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
      <div class="orb orb-4"></div>
    </div>

    <header class="admin-header glass">
      <div class="header-left">
        <div class="admin-logo">
          <img src="/favicon.png" alt="Rovio" />
        </div>
        <h1 class="header-title serif">数据看板</h1>
        <span class="header-badge">管理员</span>
      </div>
      <div class="header-right">
        <span class="admin-name">{{ adminName }}</span>
        <!-- 时间范围切换 -->
        <div class="range-switch">
          <button v-for="r in ranges" :key="r.value"
            class="range-btn"
            :class="{ active: range === r.value }"
            @click="setRange(r.value)">
            {{ r.label }}
          </button>
        </div>
        <button class="btn-refresh-main" @click="loadAll" :disabled="loading" title="刷新数据">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            :class="{ spinning: loading }">
            <polyline points="23 4 23 10 17 10"></polyline>
            <polyline points="1 20 1 14 7 14"></polyline>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
        </button>
        <button class="btn-settings" @click="goKbAdmin" title="知识库管理">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
          </svg>
        </button>
        <button class="btn-settings" @click="goSettings" title="账号设置">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
        </button>
        <button class="btn-logout" @click="onLogout">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
          退出
        </button>
      </div>
    </header>

    <div class="admin-body" v-if="overview">
      <!-- ===== 概览卡片：DAU/WAU/MAU/新增/留存 ===== -->
      <section class="metric-grid">
        <div class="metric-card glass-strong" v-for="m in metricCards" :key="m.key">
          <div class="metric-icon" :style="{ background: m.iconBg, color: m.iconColor }">
            <span v-html="m.icon"></span>
          </div>
          <div class="metric-body">
            <div class="metric-label">{{ m.label }}</div>
            <div class="metric-value">{{ m.value }}</div>
            <div class="metric-sub" v-if="m.sub">{{ m.sub }}</div>
          </div>
        </div>
      </section>

      <!-- ===== 图表区：调用量趋势 + 平均响应时长 ===== -->
      <section class="chart-row">
        <div class="chart-card glass-strong">
          <div class="chart-header">
            <h3 class="serif">调用量趋势</h3>
            <span class="chart-sub">近 {{ range }} 天每日 API 调用数</span>
          </div>
          <LineChart
            :labels="trends.dates"
            :series="[{ name: '调用量', data: trends.call_counts, color: '#6366f1' }]"
            :height="260"
          />
        </div>
        <div class="chart-card glass-strong">
          <div class="chart-header">
            <h3 class="serif">平均响应时长</h3>
            <span class="chart-sub">单位：毫秒 (ms)</span>
          </div>
          <LineChart
            :labels="trends.dates"
            :series="[{ name: '平均耗时', data: trends.avg_durations, color: '#22c55e' }]"
            :height="260"
          />
        </div>
      </section>

      <!-- ===== 图表区：Token 消耗堆叠 ===== -->
      <section class="chart-row single">
        <div class="chart-card glass-strong">
          <div class="chart-header">
            <h3 class="serif">Token 消耗趋势</h3>
            <span class="chart-sub">Prompt / Completion 每日堆叠</span>
          </div>
          <StackedAreaChart
            :labels="trends.dates"
            :series="[
              { name: 'Prompt', data: trends.prompt_tokens, color: '#6366f1' },
              { name: 'Completion', data: trends.completion_tokens, color: '#22c55e' },
            ]"
            :height="260"
          />
        </div>
      </section>

      <!-- ===== 工具分布 + 错误统计 ===== -->
      <section class="chart-row">
        <div class="chart-card glass-strong">
          <div class="chart-header">
            <h3 class="serif">工具调用分布</h3>
            <span class="chart-sub">哪个工具最常用</span>
          </div>
          <div class="tool-bars" v-if="tools.length">
            <div class="tool-row" v-for="(t, i) in tools.slice(0, 10)" :key="t.tool_name">
              <div class="tool-name" :title="t.tool_name">
                <span class="tool-rank">{{ i + 1 }}</span>
                {{ t.tool_name }}
              </div>
              <div class="tool-bar-track">
                <div class="tool-bar-fill" :style="{ width: toolBarWidth(t.count), background: toolColor(i) }"></div>
              </div>
              <div class="tool-count">{{ t.count }} 次</div>
              <div class="tool-success" :class="{ low: t.success_rate < 90 }">
                {{ t.success_rate }}%
              </div>
            </div>
          </div>
          <div v-else class="empty-block">暂无工具调用数据</div>
        </div>

        <div class="chart-card glass-strong">
          <div class="chart-header">
            <h3 class="serif">错误与限流</h3>
            <span class="chart-sub">近 {{ range }} 天</span>
          </div>
          <div class="error-grid">
            <div class="error-cell">
              <div class="error-label">API 错误率</div>
              <div class="error-value" :class="{ bad: errorStats.error_rate > 5 }">
                {{ errorStats.error_rate }}%
              </div>
              <div class="error-detail">{{ errorStats.error_calls }} / {{ errorStats.total_calls }} 次</div>
            </div>
            <div class="error-cell">
              <div class="error-label">工具错误率</div>
              <div class="error-value" :class="{ bad: errorStats.tool_error_rate > 10 }">
                {{ errorStats.tool_error_rate }}%
              </div>
              <div class="error-detail">{{ errorStats.tool_error_calls }} / {{ errorStats.tool_total_calls }} 次</div>
            </div>
            <div class="error-cell">
              <div class="error-label">限流触发</div>
              <div class="error-value" :class="{ bad: errorStats.rate_limit_count > 50 }">
                {{ errorStats.rate_limit_count }}
              </div>
              <div class="error-detail">次</div>
            </div>
          </div>
        </div>
      </section>

      <!-- ===== Top 用户 + Top 提问 ===== -->
      <section class="chart-row">
        <div class="chart-card glass-strong">
          <div class="chart-header">
            <h3 class="serif">Top 用户</h3>
            <span class="chart-sub">按调用量排序</span>
          </div>
          <div class="top-list" v-if="topUsers.length">
            <div class="top-row" v-for="(u, i) in topUsers" :key="u.user_id">
              <div class="top-rank" :class="`rank-${i + 1}`">{{ i + 1 }}</div>
              <div class="top-info">
                <div class="top-name">{{ u.display_name }}</div>
                <div class="top-meta">@{{ u.username }} · {{ u.call_count }} 次调用</div>
              </div>
              <div class="top-tokens">{{ formatTokens(u.total_tokens) }} tokens</div>
              <div class="top-duration">{{ u.avg_duration_ms }} ms</div>
            </div>
          </div>
          <div v-else class="empty-block">暂无数据</div>
        </div>

        <div class="chart-card glass-strong">
          <div class="chart-header">
            <h3 class="serif">Top 提问</h3>
            <span class="chart-sub">高频问题 Top 10</span>
          </div>
          <div class="top-list" v-if="topQuestions.length">
            <div class="question-row" v-for="(q, i) in topQuestions" :key="i">
              <div class="top-rank" :class="`rank-${i + 1}`">{{ i + 1 }}</div>
              <div class="question-body">
                <div class="question-text">{{ q.question }}{{ q.question && q.question.length >= 50 ? '...' : '' }}</div>
                <div class="question-meta">{{ q.count }} 次 · {{ q.conversation_count }} 个会话</div>
              </div>
            </div>
          </div>
          <div v-else class="empty-block">暂无数据</div>
        </div>
      </section>
    </div>

    <!-- 加载占位 -->
    <div v-else class="loading-block glass-strong">
      <span class="loading-spinner"></span>正在加载数据统计…
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getUser, logout } from '@/api/auth.js'
import LineChart from '@/components/LineChart.vue'
import StackedAreaChart from '@/components/StackedAreaChart.vue'

const router = useRouter()
const API_BASE = '/api'

const adminName = ref('')
const loading = ref(false)
const range = ref(30)
const ranges = [
  { label: '7天', value: 7 },
  { label: '30天', value: 30 },
  { label: '90天', value: 90 },
]

const overview = ref(null)
const trends = ref({ dates: [], call_counts: [], prompt_tokens: [], completion_tokens: [], total_tokens: [], avg_durations: [] })
const tools = ref([])
const errorStats = ref({ total_calls: 0, error_calls: 0, error_rate: 0, tool_total_calls: 0, tool_error_calls: 0, tool_error_rate: 0, rate_limit_count: 0, rate_limit_trend: [] })
const topUsers = ref([])
const topQuestions = ref([])

const currentUser = getUser()
adminName.value = currentUser?.display_name || currentUser?.username || '管理员'

const metricCards = computed(() => {
  const o = overview.value || {}
  return [
    {
      key: 'dau', label: '日活 (DAU)', value: o.dau ?? 0, sub: '今日活跃用户',
      iconBg: 'rgba(99,102,241,0.15)', iconColor: '#6366f1',
      icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
    },
    {
      key: 'wau', label: '周活 (WAU)', value: o.wau ?? 0, sub: '近 7 天活跃',
      iconBg: 'rgba(34,197,94,0.15)', iconColor: '#22c55e',
      icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    },
    {
      key: 'mau', label: '月活 (MAU)', value: o.mau ?? 0, sub: '近 30 天活跃',
      iconBg: 'rgba(245,158,11,0.15)', iconColor: '#f59e0b',
      icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    },
    {
      key: 'new_today', label: '今日新增', value: o.new_users_today ?? 0, sub: `本周新增 ${o.new_users_week ?? 0}`,
      iconBg: 'rgba(236,72,153,0.15)', iconColor: '#ec4899',
      icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/></svg>',
    },
    {
      key: 'total', label: '总用户', value: o.total_users ?? 0, sub: '累计注册用户',
      iconBg: 'rgba(14,165,233,0.15)', iconColor: '#0ea5e9',
      icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    },
    {
      key: 'retention', label: '次日留存', value: (o.retention_rate ?? 0) + '%', sub: '昨日新增今日活跃',
      iconBg: 'rgba(139,92,246,0.15)', iconColor: '#8b5cf6',
      icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 6-6"/></svg>',
    },
  ]
})

async function apiFetch(url) {
  // JWT 存于 HttpOnly Cookie，同源请求自动携带
  const res = await fetch(url)
  if (res.status === 401) {
    logout()
    router.push('/login')
    throw new Error('未授权')
  }
  if (res.status === 403) {
    router.push('/')
    throw new Error('无权限')
  }
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || '请求失败')
  return data
}

function setRange(r) {
  range.value = r
  loadAll()
}

async function loadAll() {
  loading.value = true
  try {
    const [ov, tr, tl, tp] = await Promise.all([
      apiFetch(`${API_BASE}/admin/stats/overview`),
      apiFetch(`${API_BASE}/admin/stats/trends?days=${range.value}`),
      apiFetch(`${API_BASE}/admin/stats/tools?days=${range.value}`),
      apiFetch(`${API_BASE}/admin/stats/top?days=${range.value}&limit=10`),
    ])
    overview.value = ov
    trends.value = tr
    tools.value = tl.tools || []
    errorStats.value = tl.errors || {}
    topUsers.value = tp.top_users || []
    topQuestions.value = tp.top_questions || []
  } catch (e) {
    console.error('加载统计数据失败:', e)
  } finally {
    loading.value = false
  }
}

const toolColors = ['#6366f1', '#22c55e', '#f59e0b', '#ec4899', '#0ea5e9', '#8b5cf6', '#14b8a6', '#f43f5e', '#84cc16', '#a855f7']
function toolColor(i) { return toolColors[i % toolColors.length] }
function toolBarWidth(count) {
  const max = Math.max(...(tools.value.map(t => t.count) || [1]), 1)
  return Math.max(4, Math.round((count / max) * 100)) + '%'
}
function formatTokens(n) {
  if (!n) return '0'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return n
}

function onLogout() {
  logout()
  router.push('/login')
}
function goSettings() { router.push('/settings') }
function goKbAdmin() { router.push('/admin/kb') }

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.admin-page {
  width: 100%;
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
  overflow-y: auto;
}

/* ===== Header ===== */
.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 26px;
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
  border-radius: 0;
  position: sticky;
  top: 0;
  z-index: 10;
  animation: header-in 0.5s var(--ease-out-expo) both;
}

@keyframes header-in {
  from { opacity: 0; transform: translateY(-12px); }
  to { opacity: 1; transform: translateY(0); }
}

.header-left { display: flex; align-items: center; gap: 12px; }

.admin-logo {
  width: 34px; height: 34px;
  border-radius: 50%;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(var(--accent-rgb), 0.25);
}
.admin-logo img { width: 100%; height: 100%; object-fit: cover; }

.header-title {
  font-size: 19px;
  font-weight: 900;
  letter-spacing: 1px;
  color: var(--text);
  margin: 0;
}

.header-badge {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1px;
  padding: 4px 12px;
  border-radius: var(--radius-pill);
  background: var(--accent-light);
  border: 1px solid rgba(var(--accent-rgb), 0.25);
  color: var(--accent);
}

.header-right { display: flex; align-items: center; gap: 12px; }
.admin-name { font-size: 13px; font-weight: 600; color: var(--text-secondary); }

.range-switch {
  display: flex;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 3px;
  gap: 2px;
}
.range-btn {
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-pill);
  transition: all var(--transition);
  font-family: inherit;
}
.range-btn:hover { color: var(--text); }
.range-btn.active {
  background: var(--accent);
  color: var(--accent-contrast);
  box-shadow: 0 2px 8px rgba(var(--accent-rgb), 0.3);
}

.btn-refresh-main {
  width: 36px; height: 36px;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: var(--panel);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color var(--transition), border-color var(--transition), transform var(--spring-fast);
}
.btn-refresh-main:hover {
  color: var(--accent);
  border-color: rgba(var(--accent-rgb), 0.4);
  transform: rotate(40deg);
}

.spinning { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.btn-logout {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--panel);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition);
  font-family: inherit;
}
.btn-logout:hover {
  border-color: var(--danger-border);
  color: var(--danger);
  transform: translateY(-1px);
}

.btn-settings {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px; height: 36px;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: var(--panel);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition);
}
.btn-settings:hover {
  color: var(--accent);
  border-color: rgba(var(--accent-rgb), 0.4);
  transform: translateY(-1px) rotate(18deg);
}

/* ===== Body ===== */
.admin-body {
  flex: 1;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}

/* ===== 概览卡片 ===== */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  border-radius: var(--radius-lg);
  animation: panel-in 0.5s var(--ease-out-expo) both;
  transition: transform var(--spring-fast), box-shadow var(--transition);
}
.metric-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px var(--shadow-sm);
}

@keyframes panel-in {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

.metric-icon {
  width: 44px; height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.metric-body { flex: 1; min-width: 0; }
.metric-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.5px;
}
.metric-value {
  font-size: 24px;
  font-weight: 900;
  color: var(--text);
  line-height: 1.2;
  margin-top: 2px;
}
.metric-sub {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* ===== 图表卡片 ===== */
.chart-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  animation: panel-in 0.55s var(--ease-out-expo) both;
}
.chart-row.single { grid-template-columns: 1fr; }

.chart-card {
  padding: 20px 22px;
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chart-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.chart-header h3 {
  font-size: 16px;
  font-weight: 900;
  color: var(--text);
  margin: 0;
  letter-spacing: 0.5px;
}
.chart-sub {
  font-size: 12px;
  color: var(--text-muted);
}

/* ===== 工具分布条形 ===== */
.tool-bars {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 320px;
  overflow-y: auto;
  padding: 4px 2px;
}
.tool-row {
  display: grid;
  grid-template-columns: 160px 1fr 80px 60px;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
}
.tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-rank {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px; height: 22px;
  border-radius: 50%;
  background: var(--accent-light);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.tool-bar-track {
  height: 10px;
  background: var(--hover);
  border-radius: var(--radius-pill);
  overflow: hidden;
}
.tool-bar-fill {
  height: 100%;
  border-radius: var(--radius-pill);
  transition: width 0.6s var(--ease-out-expo);
}
.tool-count {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-align: right;
}
.tool-success {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent);
  text-align: right;
}
.tool-success.low { color: var(--danger); }

/* ===== 错误统计 ===== */
.error-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 14px;
  padding: 8px 0;
}
.error-cell {
  background: var(--bg);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: 16px 14px;
  text-align: center;
}
.error-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.error-value {
  font-size: 26px;
  font-weight: 900;
  color: var(--accent);
  line-height: 1;
}
.error-value.bad { color: var(--danger); }
.error-detail {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
}

/* ===== Top 列表 ===== */
.top-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 380px;
  overflow-y: auto;
  padding: 4px 2px;
}
.top-row {
  display: grid;
  grid-template-columns: 36px 1fr auto auto;
  align-items: center;
  gap: 12px;
  padding: 10px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  transition: background var(--transition), border-color var(--transition);
}
.top-row:hover {
  background: var(--hover);
  border-color: var(--border-light);
}
.top-rank {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px; height: 28px;
  border-radius: 50%;
  background: var(--accent-light);
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
}
.top-rank.rank-1 { background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #fff; }
.top-rank.rank-2 { background: linear-gradient(135deg, #cbd5e1, #94a3b8); color: #fff; }
.top-rank.rank-3 { background: linear-gradient(135deg, #f97316, #ea580c); color: #fff; }

.top-info { min-width: 0; }
.top-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.top-meta {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.top-tokens {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent);
  white-space: nowrap;
}
.top-duration {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

.question-row {
  display: grid;
  grid-template-columns: 36px 1fr;
  gap: 12px;
  padding: 10px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  transition: background var(--transition), border-color var(--transition);
}
.question-row:hover {
  background: var(--hover);
  border-color: var(--border-light);
}
.question-body { min-width: 0; }
.question-text {
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.question-meta {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.empty-block {
  padding: 32px 0;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}

.loading-block {
  margin: 22px;
  padding: 40px;
  text-align: center;
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.loading-spinner {
  width: 14px; height: 14px;
  border: 2px solid var(--accent-soft);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@media (max-width: 1100px) {
  .chart-row { grid-template-columns: 1fr; }
  .error-grid { grid-template-columns: 1fr; }
}

@media (max-width: 700px) {
  .header-right .admin-name { display: none; }
  .range-switch { order: -1; }
  .metric-grid { grid-template-columns: 1fr 1fr; }
  .tool-row { grid-template-columns: 120px 1fr 60px; }
  .tool-success { display: none; }
  .top-row { grid-template-columns: 28px 1fr auto; }
  .top-duration { display: none; }
}
</style>
