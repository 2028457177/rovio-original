import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// 本地开发路由：
//   - 默认无 nginx 时，按 URL 前缀直接代理到 6 个微服务端口（8001-8006）
//   - 设置 VITE_API_TARGET=http://81.70.100.57 可走生产
//   - 设置 VITE_API_TARGET=http://localhost:8000 可走本地 nginx
const API_TARGET = process.env.VITE_API_TARGET || ''

// 微服务直连代理表（仅当未设 VITE_API_TARGET 时生效，替代 nginx 前缀分发）
// vite proxy key 为前缀匹配，按定义顺序匹配；更具体的路径放前面避免被通用前缀先命中
function microserviceProxy() {
  return {
    // ── auth_service :8001 —— 认证 / 密码 / 密保 / 登录设备 ──
    '/api/auth':                              { target: 'http://localhost:8001', changeOrigin: true },
    '/api/user/password':                     { target: 'http://localhost:8001', changeOrigin: true },
    '/api/user/security-question':            { target: 'http://localhost:8001', changeOrigin: true },
    '/api/user/devices':                      { target: 'http://localhost:8001', changeOrigin: true },

    // ── user_service :8002 —— 资料 / 头像 / 课表 / 模型设置 / 注销 ──
    '/api/user/profile':                      { target: 'http://localhost:8002', changeOrigin: true },
    '/api/user/avatar':                       { target: 'http://localhost:8002', changeOrigin: true },
    '/api/user/schedule':                     { target: 'http://localhost:8002', changeOrigin: true },
    '/api/user/model':                        { target: 'http://localhost:8002', changeOrigin: true },
    '/api/user/account':                      { target: 'http://localhost:8002', changeOrigin: true },
    '/api/avatars':                           { target: 'http://localhost:8002', changeOrigin: true },
    '/api/schedules':                         { target: 'http://localhost:8002', changeOrigin: true },

    // ── chat_service :8003 —— 聊天 / 会话 / 反馈 / 任务 / DeepAgent plan ──
    '/api/chat':                              { target: 'http://localhost:8003', changeOrigin: true },
    '/api/conversations':                     { target: 'http://localhost:8003', changeOrigin: true },
    '/api/feedback':                          { target: 'http://localhost:8003', changeOrigin: true },
    '/api/tasks':                             { target: 'http://localhost:8003', changeOrigin: true },
    '/api/plan':                              { target: 'http://localhost:8003', changeOrigin: true },
    '/api/plans':                             { target: 'http://localhost:8003', changeOrigin: true },

    // ── kb_service :8004 —— 知识库 ──
    '/api/admin/kb':                          { target: 'http://localhost:8004', changeOrigin: true },
    '/api/kb':                                { target: 'http://localhost:8004', changeOrigin: true },

    // ── admin_service :8005 —— 管理员 / 数据看板 ──
    '/api/admin/users':                       { target: 'http://localhost:8005', changeOrigin: true },
    '/api/admin/stats':                       { target: 'http://localhost:8005', changeOrigin: true },

    // ── file_service :8006 —— 文件上传下载 ──
    '/api/upload-word':                       { target: 'http://localhost:8006', changeOrigin: true },
    '/api/download':                          { target: 'http://localhost:8006', changeOrigin: true },
    '/api/file':                              { target: 'http://localhost:8006', changeOrigin: true },

    // ── 健康检查 ──
    '/api/health':                            { target: 'http://localhost:8001', changeOrigin: true },
  }
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    proxy: API_TARGET
      ? { '/api': { target: API_TARGET, changeOrigin: true } }
      : microserviceProxy(),
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
