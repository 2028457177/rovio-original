<template>
  <div class="app-layout">
    <div class="animated-bg">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
      <div class="orb orb-4"></div>
    </div>
    <div class="cursor-glow" ref="cursorGlowRef"></div>

    <!-- 移动端遮罩层 -->
    <div
      class="sidebar-overlay"
      :class="{ visible: sidebarOpen }"
      @click="onCloseSidebar"
    ></div>

    <aside class="sidebar glass-strong" :class="{ open: sidebarOpen, collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <div class="sidebar-logo">
          <span class="logo-ring"></span>
          <img src="/favicon.png" alt="头像" class="logo-img" />
        </div>
        <div class="sidebar-brand">
          <div class="sidebar-title serif">Rovio</div>
          <div class="sidebar-subtitle">智能 AI 助手</div>
        </div>
        <button
          class="sidebar-collapse-btn"
          @click="onToggleSidebar"
          aria-label="收起侧边栏"
          title="收起侧边栏"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6"></polyline>
          </svg>
        </button>
      </div>

      <button class="sidebar-new-chat" @click="onMobileNewChat">
        <span class="new-chat-icon">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
        </span>
        新建对话
      </button>

      <!-- 会话搜索 -->
      <div class="sidebar-search">
        <svg class="sidebar-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <input
          v-model="searchInput"
          class="sidebar-search-input"
          type="text"
          placeholder="搜索对话标题或内容…"
          @input="onSearchInput"
        />
        <button v-if="searchInput" class="sidebar-search-clear" @click="clearSearchInput" title="清除">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div class="sidebar-section-title">
        {{ searchKeyword ? `搜索结果（${visibleConversations.length}）` : '历史对话' }}
      </div>
      <ul class="sidebar-chat-list" v-if="visibleConversations.length > 0">
        <li
          class="sidebar-chat-item"
          :class="{
            active: conv.id === currentConversationId,
            editing: editingId === conv.id,
            pinned: conv.pinned,
            starred: conv.starred
          }"
          v-for="(conv, index) in visibleConversations"
          :key="conv.id"
          :style="{ '--i': index }"
          @click="onMobileSwitchConversation(conv.id)"
        >
          <span class="chat-item-dot"></span>
          <span v-if="conv.pinned" class="chat-item-badge" title="已置顶">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/>
            </svg>
          </span>
          <div class="chat-item-main">
            <div class="chat-item-row">
              <span v-if="editingId !== conv.id" class="chat-item-text" :title="conv.title">
                <svg v-if="conv.starred && !conv.pinned" class="star-indicator" width="10" height="10" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
                <span v-if="conv.parentConversationId" class="branch-indicator" title="分支会话">↳</span>
                {{ conv.title }}
              </span>
              <input
                v-else
                class="chat-item-edit-input"
                v-model="editingTitle"
                :ref="setEditInput"
                @keydown.enter="commitRename(conv)"
                @keydown.esc="cancelRename"
                @blur="commitRename(conv)"
                @click.stop
                placeholder="输入新名称"
                maxlength="40"
              />
              <span v-if="editingId !== conv.id" class="chat-item-count">{{ conv.messages.length }}</span>
            </div>
            <div v-if="editingId !== conv.id" class="chat-item-sub">
              <span class="chat-item-preview">{{ lastMessagePreview(conv) }}</span>
              <span class="chat-item-time">{{ conv.time }}</span>
            </div>
          </div>
          <div v-if="editingId !== conv.id" class="chat-item-actions">
            <button class="chat-item-action" @click.stop="onTogglePin(conv.id)" :title="conv.pinned ? '取消置顶' : '置顶'">
              <svg width="13" height="13" viewBox="0 0 24 24" :fill="conv.pinned ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/>
              </svg>
            </button>
            <button class="chat-item-action" @click.stop="onToggleStar(conv.id)" :title="conv.starred ? '取消收藏' : '收藏'">
              <svg width="13" height="13" viewBox="0 0 24 24" :fill="conv.starred ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
              </svg>
            </button>
            <button class="chat-item-action" @click.stop="startRename(conv)" title="重命名">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 20h9"></path>
                <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
              </svg>
            </button>
            <button class="chat-item-action" @click.stop="onExport(conv.id, 'markdown')" title="导出 Markdown">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
            </button>
            <button class="chat-item-action chat-item-delete" @click.stop="requestDelete(conv)" title="删除对话">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
        </li>
      </ul>
      <div v-else class="sidebar-empty-hint">
        <span class="empty-hint-icon">✦</span>
        {{ searchKeyword ? '没有找到匹配的对话' : '暂无对话，从下方开始第一句吧' }}
      </div>
    </aside>

    <!-- 桌面端侧边栏收起后的展开入口 -->
    <button
      v-if="sidebarCollapsed"
      class="sidebar-expand-btn"
      @click="onToggleSidebar"
      aria-label="展开侧边栏"
      title="展开侧边栏"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 18 15 12 9 6"></polyline>
      </svg>
    </button>

    <main class="main-content">

      <Transition name="fade">
        <ErrorBanner
          v-if="error"
          :message="error"
          :hint="errorInfo?.hint"
          :canRetry="errorInfo?.canRetry"
          @dismiss="onDismissError"
          @retry="onRetryError"
        />
      </Transition>

      <div
        class="chat-messages"
        ref="chatContainer"
        @scroll="onChatScroll"
      >
        <div v-if="showWelcome" class="welcome-stage">
          <div class="welcome-backdrop" aria-hidden="true">
            <div class="backdrop-grid"></div>
          </div>

          <div class="welcome-spread">
            <header class="welcome-masthead" style="--d: 0.05s">
              <span class="mast-eyebrow mast-no serif">№ {{ dayIndex }}</span>
              <span class="mast-rule"></span>
              <span class="mast-eyebrow">{{ mastheadLabel }}</span>
            </header>

            <section class="welcome-hero">
              <p class="hero-kicker serif" style="--d: 0.15s">{{ greeting }}，</p>
              <h1 class="hero-title serif">
                <span class="hero-line" style="--d: 0.3s">{{ username || '朋友' }}</span>
              </h1>
            </section>

            <div class="welcome-timestamp" style="--d: 0.65s">
              <span class="ts-date">{{ clockDate }}</span>
              <span class="ts-clock serif">{{ clockTime }}</span>
            </div>

            <ChatInput
              :disabled="false"
              :is-streaming="isStreaming"
              center-mode
              :search-enabled="searchEnabled"
              @toggle-search="toggleSearch"
              @send="onSendMessage"
              @stop="onStopStreaming"
            />

            <nav class="welcome-cues" style="--d: 0.85s" aria-label="快速开始">
              <button
                v-for="(cue, i) in cues"
                :key="i"
                class="cue"
                :style="{ '--cue-i': i }"
                @click="onSendMessage(cue.prompt)"
              >
                <span class="cue-index serif">{{ String(i + 1).padStart(2, '0') }}</span>
                <span class="cue-body">
                  <span class="cue-title">{{ cue.title }}</span>
                  <span class="cue-desc">{{ cue.desc }}</span>
                </span>
                <svg class="cue-arrow" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M5 12h14M13 6l6 6-6 6"/>
                </svg>
              </button>
            </nav>
          </div>
        </div>

        <div v-show="!keepWelcome" class="messages-list" :key="sessionId">
          <TransitionGroup name="message-list" tag="div">
            <MessageBubble
              v-for="(msg, index) in messages"
              :key="msg.id"
              :message="msg"
              :index="index"
              :streaming="!!msg.streaming"
              :thinking-content="msg.streaming ? thinkingContent : ''"
              @copy="onMessageCopy"
              @regenerate="onMessageRegenerate"
              @edit="onMessageEdit"
              @stop="onMessageStop"
              @feedback="onMessageFeedback"
              @branch="onMessageBranch"
            />
          </TransitionGroup>
        </div>
      </div>

      <!-- 滚动到底部按钮 + 新消息提示 -->
      <Transition name="slide-up">
        <div v-if="showScrollBottom" class="scroll-bottom-fab" @click="scrollToBottom(true)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
          <span v-if="newMessageCount > 0" class="new-msg-badge">{{ newMessageCount > 99 ? '99+' : newMessageCount }}</span>
        </div>
      </Transition>
      <Transition name="fade">
        <div v-if="newMessageCount > 0 && !showScrollBottom" class="new-msg-toast" @click="scrollToBottom(true)">
          <span class="new-msg-dot"></span>
          {{ newMessageCount }} 条新消息
        </div>
      </Transition>

      <ChatInput
        v-if="!showWelcome"
        :disabled="isStreaming"
        :is-streaming="isStreaming"
        :search-enabled="searchEnabled"
        @toggle-search="toggleSearch"
        @send="onSendMessage"
        @stop="onStopStreaming"
      />
    </main>

    <!-- 右上角任务清单：仅欢迎页可见，执行中保持可见以显示进度 -->
    <TaskQueue
      :visible="showWelcome"
      :on-execute-task="executeTaskInQueue"
      @start="onTaskQueueStart"
      @end="onTaskQueueEnd"
      @stop="onStopStreaming"
    />

    <!-- 左下角折叠式用户面板 -->
    <div class="user-panel" ref="userPanelRef">
      <Transition name="panel-fade">
        <div v-if="userPanelOpen" class="user-dropdown glass-strong">
          <div class="user-dropdown-header">
            <img src="/user-avatar.jpg" class="user-dropdown-avatar" alt="头像" />
            <div class="user-dropdown-info">
              <div class="user-dropdown-name" :title="username">{{ username }}</div>
              <div class="user-dropdown-role">普通用户</div>
            </div>
          </div>

          <div class="user-dropdown-divider"></div>

          <button class="user-dropdown-item" @click="onOpenKb">
            <span class="user-dropdown-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
              </svg>
            </span>
            <span class="user-dropdown-label">我的知识库</span>
            <span class="user-dropdown-arrow">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </span>
          </button>

          <button class="user-dropdown-item" @click="onOpenWorkspace">
            <span class="user-dropdown-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>
            </span>
            <span class="user-dropdown-label">AI 工作区</span>
            <span class="user-dropdown-arrow">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </span>
          </button>

          <button class="user-dropdown-item" @click="onOpenPlans">
            <span class="user-dropdown-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"></path>
                <rect x="9" y="3" width="6" height="4" rx="1"></rect>
                <line x1="9" y1="12" x2="15" y2="12"></line>
                <line x1="9" y1="16" x2="13" y2="16"></line>
              </svg>
            </span>
            <span class="user-dropdown-label">计划历史</span>
            <span class="user-dropdown-arrow">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </span>
          </button>

          <button class="user-dropdown-item" @click="onOpenSettings">
            <span class="user-dropdown-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="3"></circle>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
              </svg>
            </span>
            <span class="user-dropdown-label">账号设置</span>
            <span class="user-dropdown-arrow">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </span>
          </button>

          <button class="user-dropdown-item" @click="toggleTheme">
            <span class="user-dropdown-icon">
              <svg v-if="theme === 'dark'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="5"></circle>
                <line x1="12" y1="1" x2="12" y2="3"></line>
                <line x1="12" y1="21" x2="12" y2="23"></line>
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                <line x1="1" y1="12" x2="3" y2="12"></line>
                <line x1="21" y1="12" x2="23" y2="12"></line>
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
              </svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
              </svg>
            </span>
            <span class="user-dropdown-label">{{ theme === 'dark' ? '浅色主题' : '深色主题' }}</span>
            <span class="user-dropdown-arrow">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </span>
          </button>

          <div class="user-dropdown-divider"></div>

          <button class="user-dropdown-item user-dropdown-logout" @click="onLogout">
            <span class="user-dropdown-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                <polyline points="16 17 21 12 16 7"></polyline>
                <line x1="21" y1="12" x2="9" y2="12"></line>
              </svg>
            </span>
            <span class="user-dropdown-label">退出登录</span>
          </button>
        </div>
      </Transition>

      <button
        class="user-bar glass-strong"
        :class="{ expanded: userPanelOpen }"
        @click="onToggleUserPanel"
        aria-haspopup="true"
        :aria-expanded="userPanelOpen"
      >
        <img src="/user-avatar.jpg" class="user-bar-avatar" alt="头像" />
        <span class="user-bar-name" :title="username">{{ username }}</span>
        <svg
          class="user-bar-chevron"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
        >
          <polyline points="18 15 12 9 6 15"></polyline>
        </svg>
      </button>
    </div>

    <!-- 删除会话确认弹窗 -->
    <Teleport to="body">
      <Transition name="modal-fade">
        <div v-if="pendingDelete" class="confirm-overlay" @click.self="cancelDelete">
          <div class="confirm-modal glass-strong">
            <div class="confirm-modal-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                <line x1="12" y1="9" x2="12" y2="13"></line>
                <line x1="12" y1="17" x2="12.01" y2="17"></line>
              </svg>
            </div>
            <h3 class="confirm-modal-title serif">删除对话</h3>
            <p class="confirm-modal-text">
              确定要删除「<strong>{{ pendingDelete.title }}</strong>」吗？删除后将无法恢复。
            </p>
            <div class="confirm-modal-actions">
              <button class="confirm-btn cancel" @click="cancelDelete">取消</button>
              <button class="confirm-btn danger" @click="confirmDelete">确认删除</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 我的知识库 抽屉 -->
    <SideDrawer
      v-model="kbDrawerOpen"
      title="我的知识库"
      subtitle="上传课件与笔记，AI 回答时优先参考你的资料"
      width="960px"
    >
      <div class="drawer-kb-wrap">
        <KbManager scope="user" />
      </div>
    </SideDrawer>

    <!-- AI 工作区 抽屉 -->
    <SideDrawer
      v-model="workspaceDrawerOpen"
      title="AI 工作区"
      subtitle="AI 生成的文件（截图、报告、代码等）保存在这里"
      width="780px"
    >
      <div class="drawer-workspace-wrap">
        <FileBrowser ref="fileBrowserRef" />
      </div>
    </SideDrawer>

    <!-- 计划历史 抽屉 -->
    <SideDrawer
      v-model="planDrawerOpen"
      title="计划历史"
      subtitle="AI 长任务执行记录与步骤明细"
      width="880px"
    >
      <PlanHistory />
    </SideDrawer>

    <!-- 账号设置 抽屉 -->
    <SideDrawer
      v-model="settingsDrawerOpen"
      title="账号设置"
      subtitle="管理你的个人资料、密码与课表"
      width="780px"
    >
      <SettingsPanel @account-deleted="onSettingsAccountDeleted" />
    </SideDrawer>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChat, resetChatState } from '@/composables/useChat.js'
import { useTheme } from '@/composables/useTheme.js'
import { getUser, logout } from '@/api/auth.js'
import MessageBubble from '@/components/MessageBubble.vue'
import ChatInput from '@/components/ChatInput.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import SideDrawer from '@/components/SideDrawer.vue'
import KbManager from '@/components/kb/KbManager.vue'
import SettingsPanel from '@/components/SettingsPanel.vue'
import FileBrowser from '@/components/FileBrowser.vue'
import PlanHistory from '@/components/PlanHistory.vue'
import TaskQueue from '@/components/TaskQueue.vue'

const router = useRouter()
const { theme, toggle: toggleTheme } = useTheme()

const {
  messages,
  sessionId,
  isStreaming,
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
  sendMessage,
  stopStreaming,
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
  searchConversations,
  clearSearch,
  exportConversation,
  dismissError,
  searchEnabled,
  toggleSearch
} = useChat()

const chatContainer = ref(null)
const cursorGlowRef = ref(null)
const userPanelRef = ref(null)
const userPanelOpen = ref(false)

// 抽屉弹窗状态
const kbDrawerOpen = ref(false)
const settingsDrawerOpen = ref(false)
const workspaceDrawerOpen = ref(false)
const planDrawerOpen = ref(false)
const fileBrowserRef = ref(null)

// 滚动 / 新消息提示
const showScrollBottom = ref(false)
const newMessageCount = ref(0)
const isAtBottom = ref(true)
let lastMessageCount = 0

// 搜索框
const searchInput = ref('')
let searchDebounce = null

function onSearchInput() {
  clearTimeout(searchDebounce)
  searchDebounce = setTimeout(() => {
    searchConversations(searchInput.value)
  }, 220)
}

function clearSearchInput() {
  searchInput.value = ''
  clearSearch()
}

function onToggleUserPanel() {
  userPanelOpen.value = !userPanelOpen.value
}

function closeUserPanel(e) {
  if (userPanelRef.value && !userPanelRef.value.contains(e.target)) {
    userPanelOpen.value = false
  }
}

function onOpenSettings() {
  userPanelOpen.value = false
  settingsDrawerOpen.value = true
}

function onOpenKb() {
  userPanelOpen.value = false
  kbDrawerOpen.value = true
}

function onOpenWorkspace() {
  userPanelOpen.value = false
  workspaceDrawerOpen.value = true
  // 打开时刷新一下文件列表（让 AI 刚生成的文件能立刻看到）
  nextTick(() => {
    if (fileBrowserRef.value) {
      fileBrowserRef.value.refresh()
    }
  })
}

function onOpenPlans() {
  userPanelOpen.value = false
  planDrawerOpen.value = true
}

function onSettingsAccountDeleted() {
  settingsDrawerOpen.value = false
  resetChatState()
  logout()
  router.push('/login')
}

// 用户信息
const user = getUser()
const username = computed(() => user ? (user.display_name || user.username) : '')

// 实时时钟与个性化问候
const now = ref(new Date())
let clockTimer = null
const clockTime = computed(() => {
  const d = now.value
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})
const clockDate = computed(() => {
  const d = now.value
  const weekdays = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日 · ${weekdays[d.getDay()]}`
})
const greeting = computed(() => {
  const h = now.value.getHours()
  if (h < 5) return '夜深了'
  if (h < 9) return '早上好'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  if (h < 23) return '晚上好'
  return '夜深了'
})

// 编辑式页眉：当年第几天 + 时段札记名
const dayIndex = computed(() => {
  const d = now.value
  const start = new Date(d.getFullYear(), 0, 0)
  const diff = d - start
  return String(Math.floor(diff / 86400000)).padStart(3, '0')
})
const mastheadLabel = computed(() => {
  const h = now.value.getHours()
  if (h < 5) return '夜阑札记'
  if (h < 9) return '晨间札记'
  if (h < 12) return '午前手记'
  if (h < 14) return '午间手记'
  if (h < 18) return '午后手记'
  return '晚间札记'
})

// 快速开始：点击即发送对应提示词
const cues = [
  { title: '生成文档', desc: '上传 Word 模板，AI 填充字段并成稿', prompt: '我上传了一份会议纪要模板，请帮我填充示例内容并生成文档' },
  { title: '知识库检索', desc: '从你的知识库里找答案，引用可溯源', prompt: '在知识库里搜一下项目管理流程，并给出要点' },
  { title: '调研与写作', desc: '联网调研 + 代码执行，产出结构化报告', prompt: '帮我调研主流 AI 编程助手的对比并生成一份报告' },
]

// 侧边栏状态
const isMobile = ref(typeof window !== 'undefined' && window.innerWidth < 768)
const sidebarOpen = ref(false)
const sidebarCollapsed = ref(localStorage.getItem('sidebarCollapsed') === '1')

// 行内重命名状态
const editingId = ref(null)
const editingTitle = ref('')
const editInputEl = ref(null)
function setEditInput(el) {
  editInputEl.value = el
}

// 删除二次确认状态
const pendingDelete = ref(null)

function onLogout() {
  resetChatState()
  logout()
  router.push('/login')
}

function onToggleSidebar() {
  if (isMobile.value) {
    sidebarOpen.value = !sidebarOpen.value
  } else {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('sidebarCollapsed', sidebarCollapsed.value ? '1' : '0')
  }
}

function onCloseSidebar() {
  sidebarOpen.value = false
}

function onResize() {
  isMobile.value = window.innerWidth < 768
  if (!isMobile.value) sidebarOpen.value = false
}

function lastMessagePreview(conv) {
  const msgs = conv && conv.messages
  if (!msgs || msgs.length === 0) return '暂无消息'
  const last = msgs[msgs.length - 1]
  const prefix = last.role === 'user' ? '我' : 'AI'
  const content = (last.content || '').replace(/\s+/g, ' ').trim()
  const text = content.length > 18 ? content.slice(0, 18) + '…' : (content || '…')
  return `${prefix}：${text}`
}

function startRename(conv) {
  editingId.value = conv.id
  editingTitle.value = conv.title
  nextTick(() => {
    if (editInputEl.value) {
      editInputEl.value.focus()
      editInputEl.value.select()
    }
  })
}

function commitRename(conv) {
  if (editingId.value !== conv.id) return
  const title = editingTitle.value.trim()
  if (title && title !== conv.title) {
    renameConversation(conv.id, title)
  }
  editingId.value = null
  editingTitle.value = ''
}

function cancelRename() {
  editingId.value = null
  editingTitle.value = ''
}

function requestDelete(conv) {
  pendingDelete.value = conv
}

function cancelDelete() {
  pendingDelete.value = null
}

function confirmDelete() {
  if (!pendingDelete.value) return
  const id = pendingDelete.value.id
  pendingDelete.value = null
  removeConversation(id)
}

function onTogglePin(id) {
  togglePin(id)
}

function onToggleStar(id) {
  toggleStar(id)
}

function onExport(id, format = 'markdown') {
  const result = exportConversation(id, format)
  if (!result) return
  // 触发文件下载
  const blob = new Blob([result.content], { type: result.mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = result.filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// 消息事件
function onMessageCopy() {
  // 已由 bubble 内部处理 toast
}

function onMessageRegenerate(message) {
  regenerateMessage(message)
}

function onMessageEdit({ message, newContent }) {
  editAndResend(message, newContent)
}

function onMessageStop() {
  stopStreaming()
}

function onMessageFeedback({ message, feedback }) {
  setMessageFeedback(message, feedback)
}

function onMessageBranch(message) {
  branchFromMessage(message).then(() => {
    nextTick(() => scrollToBottom())
  })
}

function onStopStreaming() {
  stopStreaming()
  // 并行任务可能跑在独立会话（tq_ 开头）或任务队列专属会话，
  // 需全部中止，否则其 onExecuteTask Promise 永不 resolve，任务卡在 running
  for (const sid of [...pendingStreams.value.keys()]) {
    if (sid === taskQueueSessionId || (typeof sid === 'string' && sid.startsWith('tq_'))) {
      const pending = pendingStreams.value.get(sid)
      if (pending?.controller) { try { pending.controller.abort() } catch {} }
      pendingStreams.value.delete(sid)
    }
  }
}

// 鼠标光晕
let motionRafId = 0
let lastMoveEvent = null

function updateMotion(e) {
  lastMoveEvent = e
  if (motionRafId) return
  motionRafId = requestAnimationFrame(() => {
    motionRafId = 0
    const ev = lastMoveEvent
    if (!ev || !cursorGlowRef.value) return
    cursorGlowRef.value.style.transform = `translate3d(${ev.clientX}px, ${ev.clientY}px, 0)`
  })
}

// 滚动检测：判断是否在底部，控制“回到底部”按钮和“新消息”提示
function onChatScroll() {
  const el = chatContainer.value
  if (!el) return
  const threshold = 80
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
  isAtBottom.value = atBottom
  showScrollBottom.value = !atBottom
  if (atBottom) {
    newMessageCount.value = 0
  }
}

function scrollToBottom(force = false) {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTo({
        top: chatContainer.value.scrollHeight,
        behavior: force ? 'smooth' : 'auto'
      })
      isAtBottom.value = true
      showScrollBottom.value = false
      newMessageCount.value = 0
    }
  })
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  window.addEventListener('mousemove', updateMotion, { passive: true })
  document.addEventListener('click', closeUserPanel)
  loadConversations()
  clockTimer = setInterval(() => { now.value = new Date() }, 1000)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('mousemove', updateMotion)
  document.removeEventListener('click', closeUserPanel)
  if (motionRafId) cancelAnimationFrame(motionRafId)
  if (clockTimer) clearInterval(clockTimer)
})

// 监听消息变化：自动滚到底（如果在底部）/ 累加新消息提示（如果不在底部）
watch(messages, (newMsgs) => {
  const count = newMsgs.length
  if (count > lastMessageCount) {
    if (isAtBottom.value) {
      scrollToBottom()
    } else {
      newMessageCount.value += (count - lastMessageCount)
    }
  }
  lastMessageCount = count
}, { deep: true })

watch(streamingContent, () => {
  if (isAtBottom.value) scrollToBottom()
})

watch(thinkingContent, () => {
  if (isAtBottom.value) scrollToBottom()
})

watch(isStreaming, (streaming) => {
  document.body.classList.toggle('streaming-active', streaming)
  if (streaming) {
    // 流式开始时确保在底部
    nextTick(() => {
      if (isAtBottom.value) scrollToBottom()
    })
  }
})

// 切换会话时重置滚动状态
watch(currentConversationId, () => {
  lastMessageCount = messages.value.length
  newMessageCount.value = 0
  isAtBottom.value = true
  showScrollBottom.value = false
  nextTick(() => scrollToBottom())
})

onUnmounted(() => {
  document.body.classList.remove('streaming-active')
})

function onSendMessage(message, uploadedFilePath) {
  // 当前会话忙（如任务队列在跑）→ 新建会话，保证用户能立即对话
  if (isStreaming.value) {
    newChat()
  }
  keepWelcome.value = false  // 用户手动发消息 → 切到对话页
  sendMessage(message, uploadedFilePath)
  nextTick(() => scrollToBottom())
}

// 任务清单执行回调：把 sendMessage 包装为 Promise
// 任务队列始终用固定的 sessionId（onTaskQueueStart 时记住），不受用户切换会话影响
let taskQueueSessionId = null
function executeTaskInQueue(taskText) {
  return new Promise((resolve, reject) => {
    // 专属会话正忙（前一个任务还在流式）时，开新会话并行执行；
    // 否则同会话请求会被 sendMessage 的 pendingStreams 去重静默丢弃，任务卡死
    let sid = taskQueueSessionId
    if (sid && pendingStreams.value.has(sid)) {
      sid = 'tq_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
    }
    sendMessage(taskText, '', {
      sessionIdOverride: sid,
      onDone: () => resolve(),
      onError: (err) => reject(err),
      onAbort: () => resolve()
    })
    nextTick(() => scrollToBottom())
  })
}

// 任务队列整体开始/结束钩子
function onTaskQueueStart() {
  taskQueueSessionId = sessionId.value  // 记住任务队列专属会话
  keepWelcome.value = true
}
function onTaskQueueEnd() {
  taskQueueSessionId = null
  // 不重置 keepWelcome —— 任务完成后保持欢迎页，用户手动发消息或切换会话时才离开
}

function onNewChat() {
  newChat()
}

function onMobileNewChat() {
  onNewChat()
  onCloseSidebar()
}

function onSwitchConversation(conversationId) {
  switchToConversation(conversationId)
}

function onMobileSwitchConversation(conversationId) {
  onSwitchConversation(conversationId)
  onCloseSidebar()
}

function onDismissError() {
  dismissError()
}

function onRetryError() {
  if (errorInfo.value && typeof errorInfo.value.retryFn === 'function') {
    errorInfo.value.retryFn()
  } else {
    dismissError()
  }
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  width: 100%;
  position: relative;
  z-index: 1;
}

/* ========== 侧边栏 ========== */
.sidebar {
  width: 280px;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  padding: 22px 18px 96px;
  z-index: 10;
  border-radius: 0;
  border-right: 1px solid var(--border-light);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(246, 246, 246, 0.86)),
    var(--bg);
  transition: background 0.4s ease, border-color 0.4s ease, width 0.35s var(--ease-out-expo), padding 0.35s var(--ease-out-expo);
}

[data-theme="dark"] .sidebar {
  background:
    linear-gradient(180deg, rgba(24, 24, 24, 0.97), rgba(14, 14, 14, 0.94)),
    var(--bg);
}

/* 桌面端折叠：宽度收起为 0，主区域自动撑满 */
@media (min-width: 768px) {
  .sidebar.collapsed {
    width: 0;
    padding: 0;
    border-right: 0;
    overflow: hidden;
  }
}

/* 侧边栏收起后的展开入口按钮：默认隐藏，仅桌面端收起时显示 */
.sidebar-expand-btn {
  display: none;
}

@media (min-width: 768px) {
  .sidebar-expand-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    position: fixed;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    width: 36px;
    height: 36px;
    padding: 0;
    margin: 0;
    border-radius: 10px;
    background: var(--glass);
    border: 1px solid var(--border-light);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    color: var(--text);
    cursor: pointer;
    z-index: 6;
    transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
  }

  .sidebar-expand-btn:hover {
    background: var(--accent-light);
    color: var(--text);
    border-color: var(--border-light);
  }
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 6px 18px;
  border-bottom: 1px solid var(--border-light);
  margin-bottom: 18px;
  animation: side-in 0.6s var(--ease-out-expo) both;
}

/* 侧边栏内收起按钮：仅桌面端显示，贴在 header 右侧 */
.sidebar-collapse-btn {
  display: none;
}

@media (min-width: 768px) {
  .sidebar-collapse-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    margin-left: auto;
    padding: 0;
    border-radius: 8px;
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-muted);
    cursor: pointer;
    transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
  }

  .sidebar-collapse-btn:hover {
    background: var(--accent-light);
    color: var(--text);
    border-color: var(--border-light);
  }
}

.sidebar-logo {
  position: relative;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  flex-shrink: 0;
}

.logo-img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  position: relative;
  z-index: 1;
  box-shadow: 0 6px 18px rgba(var(--accent-rgb), 0.25);
}

.logo-ring {
  position: absolute;
  inset: -3.5px;
  border-radius: 50%;
  background: conic-gradient(
    from 0deg,
    rgba(var(--accent-rgb), 0) 0deg,
    rgba(var(--accent-rgb), 0.6) 100deg,
    rgba(var(--accent-rgb), 0) 200deg,
    rgba(var(--accent-rgb), 0.25) 300deg,
    rgba(var(--accent-rgb), 0) 360deg
  );
  animation: ring-spin 5s linear infinite;
  z-index: 0;
}

@keyframes ring-spin {
  to { transform: rotate(360deg); }
}

.sidebar-title {
  font-size: 19px;
  font-weight: 900;
  letter-spacing: 1px;
  color: var(--text);
}

.sidebar-subtitle {
  font-size: 11.5px;
  letter-spacing: 2px;
  color: var(--text-muted);
  margin-top: 2px;
}

.sidebar-new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 11px 16px;
  background: linear-gradient(180deg, var(--accent-hover), var(--accent));
  border: none;
  border-radius: var(--radius-pill);
  color: var(--accent-contrast);
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 1px;
  transition: transform var(--spring-fast), box-shadow var(--spring-fast), filter var(--transition);
  margin-bottom: 26px;
  width: 100%;
  box-shadow: 0 8px 22px rgba(var(--accent-rgb), 0.3);
  animation: side-in 0.6s var(--ease-out-expo) 0.08s both;
}

.sidebar-new-chat:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 30px rgba(var(--accent-rgb), 0.42);
  filter: brightness(1.05);
}

.sidebar-new-chat:active {
  transform: translateY(0) scale(0.98);
}

.new-chat-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(255, 248, 242, 0.2);
  transition: transform var(--spring-fast);
}

.sidebar-new-chat:hover .new-chat-icon {
  transform: rotate(90deg);
}

.sidebar-section-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: var(--text-muted);
  margin: 0 6px 10px;
  font-weight: 700;
  animation: side-in 0.6s var(--ease-out-expo) 0.14s both;
}

.sidebar-chat-list {
  flex: 1;
  overflow-y: auto;
  list-style: none;
}

.sidebar-chat-item {
  position: relative;
  padding: 11px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
  margin-bottom: 3px;
  transition: background var(--transition), transform var(--spring-fast), box-shadow var(--transition);
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--text-secondary);
  animation: sidebar-item-in 0.5s var(--ease-out-expo) both;
  animation-delay: calc(0.18s + var(--i, 0) * 45ms);
}

@keyframes sidebar-item-in {
  from {
    opacity: 0;
    transform: translateX(-14px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes side-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.chat-item-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-muted);
  opacity: 0.5;
  flex-shrink: 0;
  transition: background var(--transition), transform var(--spring-fast), opacity var(--transition);
}

.sidebar-chat-item:hover {
  background: var(--hover);
  color: var(--text);
}

.sidebar-chat-item:hover .chat-item-dot {
  background: var(--accent);
  opacity: 1;
  transform: scale(1.5);
}

.sidebar-chat-item.active {
  background: var(--accent-light);
  color: var(--text);
  box-shadow: inset 0 0 0 1px rgba(var(--accent-rgb), 0.18);
}

.sidebar-chat-item.active .chat-item-dot {
  background: var(--accent);
  opacity: 1;
  transform: scale(1.5);
}

.chat-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.chat-item-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.chat-item-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.chat-item-count {
  flex-shrink: 0;
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  background: var(--hover);
  color: var(--text-muted);
  font-size: 10.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition), color var(--transition);
}

.sidebar-chat-item.active .chat-item-count {
  background: rgba(var(--accent-rgb), 0.18);
  color: var(--accent);
}

.chat-item-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.chat-item-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11.5px;
  color: var(--text-muted);
}

.chat-item-time {
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.chat-item-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  opacity: 0;
  transform: translateX(4px);
  transition: opacity var(--transition), transform var(--spring-fast);
}

.sidebar-chat-item:hover .chat-item-actions,
.sidebar-chat-item.active .chat-item-actions {
  opacity: 1;
  transform: translateX(0);
}

.chat-item-action {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition), color var(--transition);
}

.chat-item-action:hover {
  background: var(--hover);
  color: var(--text);
}

.chat-item-delete:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.sidebar-chat-item.editing {
  background: var(--accent-light);
  box-shadow: inset 0 0 0 1px rgba(var(--accent-rgb), 0.35);
}

.chat-item-edit-input {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  background: var(--bg);
  border: 1px solid rgba(var(--accent-rgb), 0.55);
  border-radius: 6px;
  padding: 3px 7px;
  outline: none;
}

/* 会话搜索框 */
.sidebar-search {
  position: relative;
  display: flex;
  align-items: center;
  margin: 0 6px 14px;
  background: var(--bg);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-pill);
  padding: 0 12px;
  height: 36px;
  transition: border-color var(--transition), box-shadow var(--transition), background var(--transition);
}

.sidebar-search:focus-within {
  border-color: rgba(var(--accent-rgb), 0.4);
  background: var(--panel);
  box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.08);
}

.sidebar-search-icon {
  color: var(--text-muted);
  flex-shrink: 0;
  margin-right: 8px;
}

.sidebar-search-input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  outline: none;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  height: 100%;
}

.sidebar-search-input::placeholder { color: var(--text-muted); }

.sidebar-search-clear {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: background var(--transition), color var(--transition);
}

.sidebar-search-clear:hover {
  background: var(--accent-light);
  color: var(--text);
}

/* 置顶 / 收藏 视觉标记 */
.sidebar-chat-item.pinned {
  background: rgba(var(--accent-rgb), 0.04);
}

.sidebar-chat-item.pinned .chat-item-text {
  font-weight: 700;
}

.chat-item-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  color: var(--accent);
  opacity: 0.7;
  display: flex;
  align-items: center;
}

.star-indicator {
  display: inline-block;
  vertical-align: -1px;
  margin-right: 4px;
  color: var(--accent);
  opacity: 0.8;
}

.branch-indicator {
  display: inline-block;
  margin-right: 4px;
  color: var(--accent);
  font-weight: 700;
  opacity: 0.85;
}

/* 滚动到底部按钮 */
.scroll-bottom-fab {
  position: absolute;
  bottom: 120px;
  left: 50%;
  transform: translateX(-50%);
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--glass-strong);
  backdrop-filter: blur(12px) saturate(150%);
  -webkit-backdrop-filter: blur(12px) saturate(150%);
  border: 1px solid var(--border);
  box-shadow: 0 8px 26px var(--shadow);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text);
  z-index: 6;
  transition: transform var(--spring-fast), box-shadow var(--transition), color var(--transition);
}

.scroll-bottom-fab:hover {
  transform: translateX(-50%) translateY(-2px);
  box-shadow: 0 12px 32px var(--shadow);
  color: var(--accent);
}

.new-msg-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--danger);
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--bg);
}

/* 新消息提示条（滚在中间时） */
.new-msg-toast {
  position: absolute;
  bottom: 130px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--accent);
  color: var(--accent-contrast);
  padding: 8px 18px;
  border-radius: var(--radius-pill);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  z-index: 6;
  box-shadow: 0 8px 26px rgba(var(--accent-rgb), 0.35);
  display: flex;
  align-items: center;
  gap: 7px;
  transition: transform var(--spring-fast);
  animation: toast-in 0.4s var(--ease-out-expo) both;
}

.new-msg-toast:hover {
  transform: translateX(-50%) translateY(-2px);
}

.new-msg-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-contrast);
  animation: dot-pulse 1.2s ease-in-out infinite;
}

@keyframes toast-in {
  from { opacity: 0; transform: translateX(-50%) translateY(10px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}

.sidebar-empty-hint {
  font-size: 12.5px;
  color: var(--text-muted);
  text-align: center;
  padding: 28px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  animation: side-in 0.6s var(--ease-out-expo) 0.2s both;
}

.empty-hint-icon {
  font-size: 18px;
  color: var(--accent);
  opacity: 0.7;
}

/* ========== 左下角用户面板 ========== */
.user-panel {
  position: fixed;
  bottom: 20px;
  left: 20px;
  z-index: 20;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.user-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 14px 7px 8px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  box-shadow: 0 4px 20px var(--shadow-sm);
  background: var(--glass-strong);
  cursor: pointer;
  font-family: inherit;
  transition: background var(--transition), border-color var(--transition), box-shadow var(--transition), transform var(--spring-fast);
}

.user-bar:hover {
  border-color: rgba(var(--accent-rgb), 0.35);
  box-shadow: 0 8px 26px var(--shadow);
  transform: translateY(-1px);
}

.user-bar-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}

.user-bar-name {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 600;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-bar-chevron {
  color: var(--text-muted);
  flex-shrink: 0;
  transition: transform 0.3s var(--ease-out-expo);
}

.user-bar.expanded .user-bar-chevron {
  transform: rotate(180deg);
}

.user-dropdown {
  width: 248px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  box-shadow: 0 16px 48px var(--shadow);
  overflow: hidden;
  padding: 8px 0;
  background: var(--glass-strong);
  transform-origin: bottom left;
}

.panel-fade-enter-active,
.panel-fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s var(--ease-out-expo);
}

.panel-fade-enter-from,
.panel-fade-leave-to {
  opacity: 0;
  transform: scale(0.95) translateY(10px);
}

.panel-fade-enter-to,
.panel-fade-leave-from {
  opacity: 1;
  transform: scale(1) translateY(0);
}

.user-dropdown-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
}

.user-dropdown-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  box-shadow: 0 4px 12px var(--shadow-sm);
}

.user-dropdown-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-dropdown-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-dropdown-role {
  font-size: 12px;
  color: var(--text-muted);
}

.user-dropdown-divider {
  height: 1px;
  background: var(--border-light);
  margin: 8px 14px;
}

.user-dropdown-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 16px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  font-family: inherit;
  transition: background var(--transition), color var(--transition);
}

.user-dropdown-item:hover {
  background: var(--accent-light);
  color: var(--text);
}

.user-dropdown-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  color: var(--text-muted);
  flex-shrink: 0;
  transition: color var(--transition), transform var(--spring-fast);
}

.user-dropdown-item:hover .user-dropdown-icon {
  color: var(--accent);
  transform: scale(1.1);
}

.user-dropdown-label {
  flex: 1;
  text-align: left;
}

.user-dropdown-arrow {
  display: flex;
  align-items: center;
  color: var(--text-muted);
  flex-shrink: 0;
}

.user-dropdown-logout:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.user-dropdown-logout:hover .user-dropdown-icon {
  color: var(--danger);
}

/* ========== 主内容区 ========== */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}

/* ========== 消息区 ========== */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  position: relative;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 28px;
  max-width: 1120px;
  width: 100%;
  margin: 0 auto;
}

/* ========== 欢迎区 · 编辑式墨韵 ========== */
.welcome-stage {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 36px 24px 56px;
  animation: welcome-fade 0.7s var(--ease-out-expo) both;
}

@keyframes welcome-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 背景：等距几何网格 —— 呼应文档/模板语义 */
.welcome-backdrop {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
  -webkit-mask-image: radial-gradient(ellipse 75% 70% at 35% 45%, #000 30%, transparent 78%);
  mask-image: radial-gradient(ellipse 75% 70% at 35% 45%, #000 30%, transparent 78%);
  animation: grid-fade-in 1.4s var(--ease-out-expo) both;
}

@keyframes grid-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.backdrop-grid {
  position: absolute;
  inset: -2px;
  background-image:
    linear-gradient(to right, rgba(var(--accent-rgb), 0.05) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(var(--accent-rgb), 0.05) 1px, transparent 1px);
  background-size: 44px 44px;
  background-position: -1px -1px;
}

[data-theme="dark"] .backdrop-grid {
  background-image:
    linear-gradient(to right, rgba(255, 255, 255, 0.04) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(255, 255, 255, 0.04) 1px, transparent 1px);
}

.welcome-spread {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 880px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 30px;
}

/* 编辑式页眉：期号 + 细线 + 札记名 */
.welcome-masthead {
  display: flex;
  align-items: baseline;
  gap: 16px;
  animation: hero-line-in 0.9s var(--ease-out-expo) var(--d, 0s) both;
}

.mast-no {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.5px;
  font-feature-settings: "lnum";
}

.mast-rule {
  flex: 0 1 72px;
  height: 1px;
  background: var(--border);
  transform-origin: left;
  animation: rule-grow 0.8s var(--ease-out-expo) 0.4s both;
}

@keyframes rule-grow {
  from { transform: scaleX(0); }
  to { transform: scaleX(1); }
}

.mast-eyebrow {
  font-size: 11.5px;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 600;
  white-space: nowrap;
}

/* 主标题区 */
.welcome-hero {
  position: relative;
}

.hero-kicker {
  font-size: clamp(20px, 2.4vw, 26px);
  font-weight: 400;
  font-style: italic;
  color: var(--text-secondary);
  margin: 0 0 6px;
  letter-spacing: 0.5px;
  animation: hero-line-in 0.9s var(--ease-out-expo) var(--d, 0s) both;
}

.hero-title {
  font-size: clamp(56px, 8.5vw, 108px);
  font-weight: 900;
  line-height: 1.05;
  letter-spacing: -0.01em;
  margin: 0;
}

.hero-line {
  display: block;
  color: var(--text);
  font-family: var(--font-gothic);
  font-weight: 900;
  font-style: normal;
  letter-spacing: 0.5px;
  animation: hero-line-in 1s var(--ease-out-expo) var(--d, 0s) both;
}

/* 时间戳行：日期固定左侧，时钟靠右，互不影响 */
.welcome-timestamp {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 14px;
  padding-top: 18px;
  border-top: 1px solid var(--border-light);
  width: 100%;
  max-width: 460px;
  animation: hero-line-in 0.9s var(--ease-out-expo) var(--d, 0s) both;
}

.ts-clock {
  font-size: 22px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text);
  letter-spacing: 1px;
  min-width: 8.5ch;
  text-align: right;
  white-space: nowrap;
}

.ts-date {
  font-size: 12.5px;
  color: var(--text-muted);
  letter-spacing: 1.5px;
  white-space: nowrap;
}

/* 能力卡片 */
.welcome-cues {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  width: 100%;
  max-width: 720px;
  margin-top: 6px;
  animation: hero-line-in 0.9s var(--ease-out-expo) var(--d, 0s) both;
}

.cue {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 16px 18px;
  text-align: left;
  background: var(--glass-light);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text);
  transition: background 0.25s ease, border-color 0.25s ease, transform 0.25s var(--ease-out-expo), box-shadow 0.25s ease;
  animation: cue-in 0.7s var(--ease-out-expo) both;
  animation-delay: calc(0.95s + var(--cue-i) * 0.08s);
}

.cue:hover {
  background: var(--panel);
  border-color: var(--border);
  transform: translateY(-3px);
  box-shadow: 0 14px 32px var(--shadow-sm);
}

.cue:active {
  transform: translateY(-1px);
}

.cue-index {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-muted);
  line-height: 1;
  flex-shrink: 0;
  transition: color 0.25s ease;
}

.cue:hover .cue-index {
  color: var(--text);
}

.cue-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
  min-width: 0;
}

.cue-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.3px;
}

.cue-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.cue-arrow {
  flex-shrink: 0;
  color: var(--text-muted);
  margin-top: 2px;
  transition: transform 0.3s var(--ease-out-expo), color 0.25s ease;
}

.cue:hover .cue-arrow {
  transform: translateX(4px);
  color: var(--text);
}

@keyframes cue-in {
  from {
    opacity: 0;
    transform: translateY(18px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes hero-line-in {
  from {
    opacity: 0;
    transform: translateY(26px);
    filter: blur(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
    filter: blur(0);
  }
}

@keyframes chip-in {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.chat-input-area.center-mode {
  width: 100%;
  max-width: 720px;
  animation: chip-in 0.7s var(--ease-out-expo) 0.9s both;
}

/* ========== 移动端适配 ========== */
.sidebar-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.38);
  z-index: 9;
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.sidebar-overlay.visible {
  opacity: 1;
  pointer-events: auto;
}

@media (max-width: 767px) {
  .sidebar-overlay {
    display: block;
  }

  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    width: 280px;
    z-index: 10;
    transform: translateX(-100%);
    transition: transform 0.35s var(--ease-out-expo);
    border-radius: 0;
    border-right: 1px solid var(--border);
    padding: calc(var(--safe-top) + 16px) 18px 96px;
  }

  .sidebar.open {
    transform: translateX(0);
    box-shadow: 0 0 40px var(--shadow);
  }

  /* 触屏无 hover，重命名/删除按钮常驻显示 */
  .chat-item-actions {
    opacity: 1;
    transform: none;
  }

  .main-content {
    padding-top: var(--safe-top);
  }

  .chat-messages {
    padding: 10px 10px;
  }

  .messages-list {
    gap: 10px;
  }

  .welcome-stage {
    padding: 20px 18px 32px;
  }

  .welcome-spread {
    gap: 22px;
  }

  .hero-title {
    font-size: 52px;
  }

  .hero-kicker {
    font-size: 19px;
  }

  .ts-clock {
    font-size: 18px;
  }

  .welcome-cues {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .chat-input-area {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }

  .app-layout {
    background: var(--bg);
  }
}

/* 弹窗过渡 */
.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.28s ease;
}

.modal-fade-enter-active .confirm-modal,
.modal-fade-leave-active .confirm-modal {
  transition: transform 0.32s var(--ease-out-expo), opacity 0.28s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

.modal-fade-enter-from .confirm-modal,
.modal-fade-leave-to .confirm-modal {
  opacity: 0;
  transform: scale(0.94) translateY(20px);
}

/* ========== 删除确认弹窗 ========== */
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1001;
  padding: 20px;
}

.confirm-modal {
  width: 100%;
  max-width: 380px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  box-shadow: 0 24px 70px var(--shadow);
  padding: 26px 24px 22px;
  text-align: center;
  background: var(--glass-strong);
}

.confirm-modal-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 14px;
  border-radius: 50%;
  background: var(--danger-soft);
  color: var(--danger);
  display: flex;
  align-items: center;
  justify-content: center;
}

.confirm-modal-title {
  font-size: 18px;
  font-weight: 800;
  color: var(--text);
  margin: 0 0 8px;
}

.confirm-modal-text {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 0 0 22px;
}

.confirm-modal-text strong {
  color: var(--text);
  font-weight: 700;
  word-break: break-all;
}

.confirm-modal-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
}

.confirm-btn {
  flex: 1;
  padding: 10px 18px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text-secondary);
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: background var(--transition), color var(--transition), border-color var(--transition), transform var(--spring-fast), filter var(--transition);
}

.confirm-btn:hover {
  transform: translateY(-1px);
}

.confirm-btn.cancel:hover {
  background: var(--hover);
  color: var(--text);
}

.confirm-btn.danger {
  background: var(--danger);
  border-color: var(--danger);
  color: #fff;
}

.confirm-btn.danger:hover {
  filter: brightness(1.06);
  box-shadow: 0 8px 20px rgba(220, 50, 50, 0.3);
}

/* ========== 抽屉内 KbManager 包装 ========== */
.drawer-kb-wrap {
  flex: 1;
  display: flex;
  min-height: 0;
  padding: 1.25rem;
}
</style>
