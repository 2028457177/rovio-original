<template>
  <div
    class="kb-manager"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onMainDrop"
  >
    <!-- ============ 左侧：知识库列表 ============ -->
    <aside class="kb-side glass-strong">
      <div class="side-header">
        <div class="side-title-block">
          <h2 class="serif">{{ scope === 'admin' ? '全局知识库' : '我的知识库' }}</h2>
          <p class="side-sub">
            <template v-if="scope === 'admin'">共 {{ adminTotals.kbs }} 库 · {{ adminTotals.docs }} 文档 · {{ adminTotals.chunks }} 分块</template>
            <template v-else>{{ kbs.length }} 个知识库</template>
          </p>
        </div>
        <button class="btn-create" @click="openCreateKb" title="新建知识库">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          新建
        </button>
      </div>

      <div v-if="kbs.length > 0" class="side-search">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <input v-model="kbFilter" type="text" placeholder="搜索知识库…" />
      </div>

      <div v-if="loadingKbs" class="side-loading"><span class="spinner"></span>加载中…</div>

      <div v-else-if="kbs.length === 0" class="side-empty">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" opacity="0.3">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
        </svg>
        <p class="serif side-empty-title">暂无知识库</p>
        <p class="side-empty-tip">{{ scope === 'admin' ? '按业务线 / 课程创建隔离的全局知识库' : '创建你的第一个个人知识库，上传课件后 AI 回答更贴合' }}</p>
        <button class="btn-create side-empty-cta" @click="openCreateKb">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          立即新建
        </button>
      </div>

      <div v-else-if="filteredKbs.length === 0" class="side-empty">
        <p class="side-empty-tip">没有匹配「{{ kbFilter }}」的知识库</p>
      </div>

      <ul v-else class="kb-list">
        <li
          v-for="kb in filteredKbs"
          :key="kb.id"
          class="kb-item"
          :class="{ active: selectedKb?.id === kb.id, disabled: !kb.is_enabled }"
          @click="selectKb(kb)"
        >
          <span class="kb-tile serif">{{ (kb.name || '库').charAt(0) }}</span>
          <div class="kb-item-main">
            <div class="kb-item-name">
              <span class="kb-name-text" :title="kb.name">{{ kb.name }}</span>
              <span v-if="kb.is_default" class="tag tag-default">默认</span>
              <span v-if="!kb.is_enabled" class="tag tag-off">已停用</span>
            </div>
            <div class="kb-item-meta">
              <span v-if="kb.biz_line" class="tag tag-biz">{{ kb.biz_line }}</span>
              <span>{{ kb.doc_count }} 文档 · {{ kb.chunk_count }} 分块</span>
            </div>
          </div>
        </li>
      </ul>

      <!-- 用户模式：全局库只读信息 -->
      <template v-if="scope === 'user' && globalKbs.length > 0">
        <div class="side-section-title serif">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="2" y1="12" x2="22" y2="12"></line>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
          </svg>
          全局知识库
        </div>
        <ul class="kb-list kb-list-global">
          <li v-for="kb in globalKbs" :key="'g' + kb.id" class="kb-item kb-item-global" :title="kb.description || kb.name">
            <span class="kb-tile kb-tile-global">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="2" y1="12" x2="22" y2="12"></line>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
              </svg>
            </span>
            <div class="kb-item-main">
              <div class="kb-item-name">
                <span class="kb-name-text">{{ kb.name }}</span>
                <span v-if="kb.is_default" class="tag tag-default">默认</span>
              </div>
              <div class="kb-item-meta">
                <span v-if="kb.biz_line" class="tag tag-biz">{{ kb.biz_line }}</span>
                <span>{{ kb.doc_count }} 文档 · 只读</span>
              </div>
            </div>
          </li>
        </ul>
      </template>
    </aside>

    <!-- ============ 右侧：主操作区 ============ -->
    <main class="kb-main glass-strong">
      <div v-if="!selectedKb" class="main-empty">
        <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="0.9" stroke-linecap="round" stroke-linejoin="round" opacity="0.28">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
          <polyline points="17 8 12 3 7 8"></polyline>
          <line x1="12" y1="3" x2="12" y2="15"></line>
        </svg>
        <p class="serif main-empty-title">选择左侧知识库开始管理</p>
        <p class="main-empty-tip">上传文档后系统会自动分块并建立向量索引</p>
      </div>

      <template v-else>
        <!-- 库信息头 -->
        <div class="kb-head">
          <div class="kb-head-info">
            <div class="kb-head-title-row">
              <h3 class="serif">{{ selectedKb.name }}</h3>
              <span v-if="selectedKb.is_default" class="tag tag-default">默认库</span>
              <span v-if="selectedKb.biz_line" class="tag tag-biz">{{ selectedKb.biz_line }}</span>
              <span v-if="selectedKb.created_by_name" class="kb-head-creator">由 {{ selectedKb.created_by_name }} 创建</span>
            </div>
            <p v-if="selectedKb.description" class="kb-head-desc">{{ selectedKb.description }}</p>
          </div>
          <div class="kb-head-actions">
            <label class="switch-wrap" :title="selectedKb.is_enabled ? '停用后不参与检索' : '启用后参与检索'">
              <span class="switch">
                <input type="checkbox" :checked="selectedKb.is_enabled" @change="toggleKbEnabled" />
                <span class="switch-slider"></span>
              </span>
              <span class="switch-label">{{ selectedKb.is_enabled ? '检索中' : '已停用' }}</span>
            </label>
            <button v-if="scope === 'admin'" class="btn-ghost" title="嵌入模型诊断" @click="openEmbeddingStatus">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
              </svg>
              嵌入诊断
            </button>
            <button class="btn-ghost" @click="openEditKb">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                <path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
              </svg>
              编辑
            </button>
            <button class="btn-ghost" :disabled="acting" @click="onRebuildKb" title="清空并重建全部文档索引">
              <span v-if="rebuilding" class="spinner small"></span>
              <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"></polyline>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
              </svg>
              重建索引
            </button>
            <button v-if="!selectedKb.is_default" class="btn-ghost danger" :disabled="acting" @click="showDeleteKb = true">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
              删除
            </button>
          </div>
        </div>

        <!-- 统计条 -->
        <div class="stat-strip">
          <div class="stat-cell">
            <span class="stat-num serif">{{ selectedKb.doc_count }}</span>
            <span class="stat-label">文档</span>
          </div>
          <div class="stat-cell">
            <span class="stat-num serif">{{ selectedKb.chunk_count }}</span>
            <span class="stat-label">向量分块</span>
          </div>
          <div class="stat-cell">
            <span class="stat-num serif">
              {{ docStats.ready }}<span class="stat-num-sub"> / {{ docStats.total }}</span>
            </span>
            <span class="stat-label">
              索引就绪
              <span v-if="docStats.busy > 0" class="stat-hint">{{ docStats.busy }} 索引中</span>
              <span v-else-if="docStats.failed > 0" class="stat-hint stat-hint-danger">{{ docStats.failed }} 失败</span>
            </span>
          </div>
          <div class="stat-cell">
            <span class="stat-num stat-num-time serif">{{ selectedKb.updated_at || '—' }}</span>
            <span class="stat-label">最近更新</span>
          </div>
        </div>

        <!-- 页签 -->
        <div class="kb-tabs">
          <button class="kb-tab" :class="{ active: activeTab === 'docs' }" @click="activeTab = 'docs'">文档管理</button>
          <button class="kb-tab" :class="{ active: activeTab === 'play' }" @click="activeTab = 'play'">检索测试</button>
        </div>

        <!-- ======== 页签一：文档管理 ======== -->
        <div v-show="activeTab === 'docs'" class="tab-body">
          <!-- 拖拽上传区 -->
          <div
            class="dropzone"
            :class="{ dragging: dragDepth > 0, disabled: uploading }"
            @click="openPicker"
          >
            <input
              ref="fileInputRef"
              type="file"
              multiple
              :accept="acceptExts"
              style="display: none"
              @change="onPickFiles"
            />
            <span class="dropzone-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
            </span>
            <p class="dropzone-text serif">拖拽文件到面板任意位置，或点击选择（可多选）</p>
            <p class="dropzone-tip">支持 PDF / TXT / XLS / XLSX · 单文件 ≤ 20MB · 上传后自动建立索引</p>
          </div>

          <!-- 上传队列 -->
          <div v-if="uploadQueue.length > 0" class="upload-queue">
            <div class="uq-head">
              <span class="uq-title">
                上传队列
                <template v-if="!uploading"> · {{ queueSummary.ok }}/{{ queueSummary.total }} 成功</template>
                <template v-else-if="uploadPercent >= 1"> · 服务器处理中…</template>
                <template v-else> · 传输中 {{ Math.round(uploadPercent * 100) }}%</template>
              </span>
              <span v-if="queueSummary.bad > 0" class="uq-bad">{{ queueSummary.bad }} 个失败</span>
              <button class="uq-clear" :disabled="uploading" @click="clearQueue">清空</button>
            </div>
            <div v-if="uploading" class="uq-progress">
              <div class="uq-progress-fill" :class="{ indeterminate: uploadPercent >= 1 }" :style="{ width: Math.round(uploadPercent * 100) + '%' }"></div>
            </div>
            <div class="uq-body">
              <div v-for="item in uploadQueue" :key="item.id" class="uq-item">
                <span class="ext-tile">{{ item.ext || '?' }}</span>
                <span class="uq-name" :title="item.name">{{ item.name }}</span>
                <span class="uq-size">{{ fmtSize(item.size) }}</span>
                <span class="uq-status" :class="'uq-' + item.status" :title="item.error || ''">
                  <span v-if="item.status === 'uploading'" class="spinner tiny"></span>
                  <svg v-else-if="item.status === 'success'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </svg>
                  <svg v-else-if="item.status === 'failed' || item.status === 'invalid'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round">
                    <line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>
                  </svg>
                  {{ queueStatusText(item) }}
                </span>
              </div>
            </div>
          </div>

          <!-- 工具条 -->
          <div class="doc-toolbar">
            <div class="doc-search">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
              <input v-model="docFilter" type="text" placeholder="搜索文档名…" />
            </div>
            <label class="check-all">
              <input type="checkbox" :checked="allChecked" @change="toggleCheckAll" />
              <span>全选</span>
            </label>
            <span v-if="checkedIds.size > 0" class="checked-count">已选 {{ checkedIds.size }} 项</span>
            <button
              v-if="checkedIds.size > 0"
              class="btn-ghost danger small"
              :disabled="acting"
              @click="showBatchDelete = true"
            >批量删除</button>
            <button class="btn-ghost small refresh" :disabled="loadingDocs" @click="loadDocuments">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: loadingDocs }">
                <polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
              刷新
            </button>
          </div>

          <!-- 文档表格 -->
          <div v-if="loadingDocs && documents.length === 0" class="table-loading"><span class="spinner"></span>加载中…</div>

          <div v-else-if="documents.length === 0" class="table-empty">
            <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" opacity="0.28">
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
              <polyline points="13 2 13 9 20 9"></polyline>
            </svg>
            <p class="serif table-empty-title">还没有文档</p>
            <p class="table-empty-tip">上传 {{ scope === 'admin' ? '课程资料' : '你的课件、笔记' }}，系统将自动分块并建立索引</p>
            <button class="btn-primary table-empty-cta" @click="openPicker">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
              选择文件上传
            </button>
          </div>

          <div v-else-if="filteredDocs.length === 0" class="table-empty">
            <p class="table-empty-tip">没有匹配「{{ docFilter }}」的文档</p>
          </div>

          <div v-else class="doc-table-wrap">
            <table class="doc-table">
              <thead>
                <tr>
                  <th class="col-check"></th>
                  <th>文件名</th>
                  <th>大小</th>
                  <th>版本</th>
                  <th>分块</th>
                  <th>状态</th>
                  <th>来源 / 上传人</th>
                  <th>更新时间</th>
                  <th class="col-ops">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="doc in filteredDocs" :key="doc.id">
                  <td class="col-check">
                    <input type="checkbox" :checked="checkedIds.has(doc.id)" @change="toggleCheck(doc.id)" />
                  </td>
                  <td class="col-name" :title="doc.filename">
                    <span class="ext-tile">{{ doc.file_ext }}</span>
                    <span class="doc-name">{{ doc.filename }}</span>
                  </td>
                  <td>{{ fmtSize(doc.file_size) }}</td>
                  <td>v{{ doc.version }}</td>
                  <td>{{ doc.status === 'ready' ? doc.chunk_count : '—' }}</td>
                  <td>
                    <span class="st-badge" :class="'st-' + doc.status" :title="doc.error_msg || ''">
                      <span class="st-dot"></span>
                      {{ statusText(doc.status) }}
                    </span>
                  </td>
                  <td class="col-src">
                    <span class="tag" :class="doc.source === 'system' ? 'tag-default' : 'tag-biz'">
                      {{ doc.source === 'system' ? '系统' : '上传' }}
                    </span>
                    {{ doc.uploader_name || '—' }}
                  </td>
                  <td class="col-time">{{ doc.updated_at }}</td>
                  <td class="col-ops">
                    <button class="op-btn" title="分块预览" @click="openChunks(doc)">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                    </button>
                    <button class="op-btn" title="替换文件（版本+1）" @click="openReplace(doc)">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path></svg>
                    </button>
                    <button class="op-btn" title="重建该文档索引" :disabled="acting" @click="onReindexDoc(doc)">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
                    </button>
                    <button class="op-btn danger" title="删除文档" :disabled="acting" @click="askDeleteDoc(doc)">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- ======== 页签二：检索测试 ======== -->
        <div v-show="activeTab === 'play'" class="tab-body">
          <div class="play-panel">
            <div class="play-input-row">
              <input
                v-model="playQuery"
                class="play-input"
                type="text"
                placeholder="输入测试问题，回车查看召回的分块与相似度…"
                @keyup.enter="runSearchTest"
              />
              <select v-model.number="playTopK" class="play-topk" title="返回分块数">
                <option :value="3">Top 3</option>
                <option :value="5">Top 5</option>
                <option :value="10">Top 10</option>
              </select>
              <button class="btn-primary" :disabled="playLoading || !playQuery.trim()" @click="runSearchTest">
                <span v-if="playLoading" class="spinner small light"></span>
                <span v-else>测试</span>
              </button>
            </div>

            <div class="play-scope">
              <span class="play-scope-label">检索范围：</span>
              <label
                v-for="kb in playScopeKbs"
                :key="kb.id"
                class="scope-chip"
                :class="{ on: playKbIds.has(kb.id) }"
              >
                <input type="checkbox" :checked="playKbIds.has(kb.id)" @change="togglePlayKb(kb.id)" />
                {{ kb.name }}
              </label>
              <span class="play-scope-tip">（不勾选 = 默认全部可用库）</span>
            </div>

            <div v-if="playError" class="play-error">{{ playError }}</div>

            <div v-if="playResults !== null" class="play-results">
              <div v-if="playResults.length === 0" class="table-empty">
                未召回到相关分块 —— 试试换个问法，或先上传文档
              </div>
              <div v-for="r in playResults" :key="r.rank" class="play-card">
                <div class="play-card-head">
                  <span class="play-rank">#{{ r.rank }}</span>
                  <div class="play-score">
                    <div class="play-score-bar">
                      <div class="play-score-fill" :style="{ width: Math.round(r.score * 100) + '%' }"></div>
                    </div>
                    <span class="play-score-num">{{ (r.score * 100).toFixed(1) }}%</span>
                  </div>
                  <span class="play-src" :title="r.filename">
                    {{ r.kb_name }} · {{ r.filename }}<template v-if="r.chunk_index !== null && r.chunk_index !== undefined"> · 块 {{ r.chunk_index }}</template>
                  </span>
                </div>
                <div class="play-content">{{ r.content }}</div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 全局拖拽提示遮罩 -->
      <Transition name="fade">
        <div v-if="dragDepth > 0" class="drag-overlay">
          <div class="drag-overlay-inner">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            <p class="serif drag-overlay-title">松开鼠标，上传到「{{ selectedKb?.name }}」</p>
            <span class="drag-overlay-tip">支持 PDF / TXT / XLS / XLSX · 单文件 ≤ 20MB</span>
          </div>
        </div>
      </Transition>
    </main>

    <!-- ============ 分块预览抽屉 ============ -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="chunkDoc" class="drawer-overlay" @click.self="chunkDoc = null">
          <div class="drawer glass-strong">
            <div class="drawer-head">
              <div>
                <h3 class="serif">分块预览</h3>
                <p class="drawer-sub">{{ chunkDoc.filename }} · 共 {{ chunkTotal }} 块</p>
              </div>
              <button class="drawer-close" @click="chunkDoc = null">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
            </div>
            <div class="drawer-body">
              <div v-if="loadingChunks" class="table-loading"><span class="spinner"></span>加载中…</div>
              <template v-else>
                <div v-if="chunks.length === 0" class="table-empty">该文档暂无分块（可能索引中或索引失败）</div>
                <div v-for="c in chunks" :key="c.chunk_index" class="chunk-card">
                  <div class="chunk-head">
                    <span class="chunk-idx">块 {{ c.chunk_index }}</span>
                    <span class="chunk-size">{{ c.char_count }} 字符</span>
                  </div>
                  <div class="chunk-content">{{ c.content }}</div>
                </div>
              </template>
            </div>
            <div class="drawer-foot">
              <button class="btn-ghost small" :disabled="chunkOffset === 0 || loadingChunks" @click="loadChunks(chunkOffset - chunkLimit)">上一页</button>
              <span class="drawer-page">{{ chunkOffset + 1 }}–{{ Math.min(chunkOffset + chunkLimit, chunkTotal) }} / {{ chunkTotal }}</span>
              <button class="btn-ghost small" :disabled="chunkOffset + chunkLimit >= chunkTotal || loadingChunks" @click="loadChunks(chunkOffset + chunkLimit)">下一页</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ============ 新建 / 编辑知识库弹窗 ============ -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showKbForm" class="modal-overlay" @click.self="showKbForm = false">
          <div class="modal-card">
            <h3 class="modal-title serif">{{ editingKb ? '编辑知识库' : '新建知识库' }}</h3>
            <div class="modal-form">
              <label class="form-label">名称 *</label>
              <input v-model="kbForm.name" class="form-input" placeholder="如：混凝土结构设计原理" maxlength="100" />
              <label class="form-label">{{ scope === 'admin' ? '业务线 / 课程' : '分类标签' }}</label>
              <input v-model="kbForm.biz_line" class="form-input" :placeholder="scope === 'admin' ? '如：土木工程系 / 24级课程' : '如：学习资料'" maxlength="100" />
              <label class="form-label">描述</label>
              <textarea v-model="kbForm.description" class="form-input form-textarea" placeholder="知识库用途说明（可选）" maxlength="500" rows="3"></textarea>
            </div>
            <div v-if="kbFormError" class="form-error">{{ kbFormError }}</div>
            <div class="modal-actions">
              <button class="modal-btn modal-btn-cancel" @click="showKbForm = false" :disabled="acting">取消</button>
              <button class="modal-btn modal-btn-primary" @click="submitKbForm" :disabled="acting || !kbForm.name.trim()">
                <span v-if="acting" class="btn-spinner"></span><span v-else>{{ editingKb ? '保存' : '创建' }}</span>
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ============ 替换文档弹窗 ============ -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="replaceDoc" class="modal-overlay" @click.self="replaceDoc = null">
          <div class="modal-card">
            <h3 class="modal-title serif">替换文档</h3>
            <p class="modal-desc">
              为 <strong>{{ replaceDoc.filename }}</strong> 选择新文件，替换后版本号 +1 并自动重建索引。
            </p>
            <div class="modal-form">
              <input ref="replaceInputRef" type="file" :accept="acceptExts" @change="onReplaceFilePicked" />
            </div>
            <div v-if="replaceError" class="form-error">{{ replaceError }}</div>
            <div class="modal-actions">
              <button class="modal-btn modal-btn-cancel" @click="replaceDoc = null" :disabled="acting">取消</button>
              <button class="modal-btn modal-btn-primary" @click="submitReplace" :disabled="acting || !replaceFile">
                <span v-if="acting" class="btn-spinner"></span><span v-else>确认替换</span>
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ============ 删除确认弹窗 ============ -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showDeleteKb" class="modal-overlay" @click.self="showDeleteKb = false">
          <div class="modal-card">
            <h3 class="modal-title serif">删除知识库</h3>
            <p class="modal-desc">
              即将删除知识库 <strong>{{ selectedKb?.name }}</strong> 及其全部 {{ selectedKb?.doc_count }} 个文档、{{ selectedKb?.chunk_count }} 个向量分块，此操作不可撤销。
            </p>
            <div class="modal-actions">
              <button class="modal-btn modal-btn-cancel" @click="showDeleteKb = false" :disabled="acting">取消</button>
              <button class="modal-btn modal-btn-danger" @click="confirmDeleteKb" :disabled="acting">
                <span v-if="acting" class="btn-spinner"></span><span v-else>确认删除</span>
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <Teleport to="body">
      <Transition name="modal">
        <div v-if="deleteDocTarget" class="modal-overlay" @click.self="deleteDocTarget = null">
          <div class="modal-card">
            <h3 class="modal-title serif">删除文档</h3>
            <p class="modal-desc">
              即将删除 <strong>{{ deleteDocTarget.filename }}</strong>（含其 {{ deleteDocTarget.chunk_count }} 个向量分块），此操作不可撤销。
            </p>
            <div class="modal-actions">
              <button class="modal-btn modal-btn-cancel" @click="deleteDocTarget = null" :disabled="acting">取消</button>
              <button class="modal-btn modal-btn-danger" @click="confirmDeleteDoc" :disabled="acting">
                <span v-if="acting" class="btn-spinner"></span><span v-else>确认删除</span>
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showBatchDelete" class="modal-overlay" @click.self="showBatchDelete = false">
          <div class="modal-card">
            <h3 class="modal-title serif">批量删除文档</h3>
            <p class="modal-desc">即将删除选中的 <strong>{{ checkedIds.size }}</strong> 个文档及其向量分块，此操作不可撤销。</p>
            <div class="modal-actions">
              <button class="modal-btn modal-btn-cancel" @click="showBatchDelete = false" :disabled="acting">取消</button>
              <button class="modal-btn modal-btn-danger" @click="confirmBatchDelete" :disabled="acting">
                <span v-if="acting" class="btn-spinner"></span><span v-else>确认删除</span>
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ============ 嵌入诊断弹窗（管理端） ============ -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="embStatus" class="modal-overlay" @click.self="embStatus = null">
          <div class="modal-card">
            <h3 class="modal-title serif">嵌入模型诊断</h3>
            <div class="emb-grid">
              <span class="emb-label">提供者</span><span class="emb-value">{{ embStatus.provider }}</span>
              <span class="emb-label">模型</span><span class="emb-value">{{ embStatus.model }}</span>
              <span class="emb-label">向量维度</span><span class="emb-value">{{ embStatus.dim || '—' }}</span>
              <span class="emb-label">状态</span>
              <span class="emb-value" :style="{ color: embStatus.ok ? 'inherit' : 'var(--danger)' }">
                {{ embStatus.ok ? '可用' : '不可用' }}（{{ embStatus.latency_ms }}ms）
              </span>
              <template v-if="embStatus.error">
                <span class="emb-label">错误</span><span class="emb-value emb-error">{{ embStatus.error }}</span>
              </template>
            </div>
            <p class="modal-desc" style="margin-top:0.8rem;">
              配置位于 <code>config/chroma.yml</code> 的 <code>embedding_provider</code>（ollama / dashscope）。
              切换提供者后系统会自动清空并重建全部索引。
            </p>
            <div class="modal-actions">
              <button class="modal-btn modal-btn-cancel" @click="embStatus = null">关闭</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 轻提示 -->
    <Teleport to="body">
      <Transition name="toast">
        <div v-if="toast" class="kb-toast glass-strong">{{ toast }}</div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import * as kbApi from '@/api/kb.js'

const props = defineProps({
  scope: { type: String, default: 'admin' }, // 'admin' | 'user'
})

const acceptExts = '.pdf,.txt,.xls,.xlsx'
const ALLOWED_EXTS = ['pdf', 'txt', 'xls', 'xlsx']
const MAX_SIZE = 20 * 1024 * 1024 // 20MB，与后端限制保持一致

// ---------- 知识库 ----------
const kbs = ref([])
const globalKbs = ref([])
const loadingKbs = ref(false)
const selectedKb = ref(null)
const kbFilter = ref('')

const filteredKbs = computed(() => {
  const kw = kbFilter.value.trim().toLowerCase()
  if (!kw) return kbs.value
  return kbs.value.filter(k =>
    (k.name || '').toLowerCase().includes(kw) ||
    (k.biz_line || '').toLowerCase().includes(kw)
  )
})

const adminTotals = computed(() => ({
  kbs: kbs.value.length,
  docs: kbs.value.reduce((s, k) => s + (k.doc_count || 0), 0),
  chunks: kbs.value.reduce((s, k) => s + (k.chunk_count || 0), 0),
}))

async function loadKbs(keepSelection = true) {
  loadingKbs.value = true
  try {
    const data = await kbApi.listKbs(props.scope)
    kbs.value = data.kbs || []
    globalKbs.value = data.global_kbs || []
    if (keepSelection && selectedKb.value) {
      const still = kbs.value.find(k => k.id === selectedKb.value.id)
      selectedKb.value = still || null
    }
    if (!selectedKb.value && kbs.value.length > 0) {
      selectKb(kbs.value[0])
    } else if (selectedKb.value) {
      loadDocuments()
    }
  } catch (e) {
    showToast(e.message)
  } finally {
    loadingKbs.value = false
  }
}

function selectKb(kb) {
  selectedKb.value = kb
  checkedIds.value = new Set()
  docFilter.value = ''
  clearQueue()
  playResults.value = null
  loadDocuments()
}

// ---------- 文档 ----------
const documents = ref([])
const loadingDocs = ref(false)
const acting = ref(false)
const docFilter = ref('')
let pollTimer = null

const filteredDocs = computed(() => {
  const kw = docFilter.value.trim().toLowerCase()
  if (!kw) return documents.value
  return documents.value.filter(d => (d.filename || '').toLowerCase().includes(kw))
})

const docStats = computed(() => ({
  total: documents.value.length,
  ready: documents.value.filter(d => d.status === 'ready').length,
  busy: documents.value.filter(d => d.status === 'pending' || d.status === 'processing').length,
  failed: documents.value.filter(d => d.status === 'failed').length,
}))

async function loadDocuments() {
  if (!selectedKb.value) return
  loadingDocs.value = true
  try {
    const data = await kbApi.listDocuments(props.scope, selectedKb.value.id)
    documents.value = data.documents || []
    if (data.kb) selectedKb.value = data.kb
    schedulePolling()
  } catch (e) {
    showToast(e.message)
  } finally {
    loadingDocs.value = false
  }
}

// 有 pending/processing 文档时轮询状态
function schedulePolling() {
  stopPolling()
  const hasPending = documents.value.some(d => d.status === 'pending' || d.status === 'processing')
  if (hasPending) {
    pollTimer = setTimeout(loadDocuments, 2000)
  }
}
function stopPolling() {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
}
onBeforeUnmount(stopPolling)

// ---------- 上传 ----------
const dragDepth = ref(0)
const uploading = ref(false)
const uploadPercent = ref(0)
const uploadQueue = ref([]) // {id,name,size,ext,status,error,file}
const fileInputRef = ref(null)
let queueTimer = null
let queueSeq = 0

const queueSummary = computed(() => ({
  total: uploadQueue.value.length,
  ok: uploadQueue.value.filter(i => i.status === 'success').length,
  bad: uploadQueue.value.filter(i => i.status === 'failed' || i.status === 'invalid').length,
}))

function queueStatusText(item) {
  if (item.status === 'failed' || item.status === 'invalid') return item.error || '失败'
  return { waiting: '排队中', uploading: '上传中', success: '已上传' }[item.status] || item.status
}

function hasDragFiles(e) {
  return e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files')
}

function onDragEnter(e) {
  if (activeTab.value !== 'docs' || !selectedKb.value || uploading.value) return
  if (!hasDragFiles(e)) return
  dragDepth.value++
}

function onDragLeave() {
  dragDepth.value = Math.max(0, dragDepth.value - 1)
}

function onMainDrop(e) {
  dragDepth.value = 0
  if (activeTab.value !== 'docs' || !selectedKb.value || uploading.value) return
  const files = [...(e.dataTransfer?.files || [])]
  if (files.length) enqueueFiles(files)
}

function openPicker() {
  if (uploading.value || !selectedKb.value) return
  fileInputRef.value?.click()
}

function onPickFiles(e) {
  const files = [...(e.target.files || [])]
  if (files.length) enqueueFiles(files)
  e.target.value = ''
}

function validateFile(f) {
  const ext = (f.name.split('.').pop() || '').toLowerCase()
  if (!ALLOWED_EXTS.includes(ext)) return { ext, error: '不支持的格式' }
  if (f.size > MAX_SIZE) return { ext, error: '超过 20MB 限制' }
  return { ext, error: '' }
}

// 入队并发起上传：先做客户端预校验，不合格文件直接标记不上送
function enqueueFiles(files) {
  if (!selectedKb.value || uploading.value) return
  clearTimeout(queueTimer)
  const items = files.map((f) => {
    const { ext, error } = validateFile(f)
    return {
      id: `${Date.now()}_${queueSeq++}`,
      name: f.name,
      size: f.size,
      ext,
      status: error ? 'invalid' : 'waiting',
      error,
      file: f,
    }
  })
  uploadQueue.value = items
  const valid = items.filter(it => it.status === 'waiting')
  if (valid.length === 0) return
  runUpload(valid)
}

async function runUpload(validItems) {
  uploading.value = true
  uploadPercent.value = 0
  validItems.forEach(it => { it.status = 'uploading' })
  try {
    const data = await kbApi.uploadDocumentsWithProgress(
      props.scope,
      selectedKb.value.id,
      validItems.map(it => it.file),
      (p) => { uploadPercent.value = p },
    )
    const results = data.results || []
    const byName = new Map()
    for (const r of results) {
      if (!byName.has(r.filename)) byName.set(r.filename, r)
    }
    let okCount = 0
    let failCount = 0
    validItems.forEach(it => {
      const r = byName.get(it.name)
      if (r && r.ok) {
        it.status = 'success'
        okCount++
      } else {
        it.status = 'failed'
        it.error = r?.error || '上传失败'
        failCount++
      }
    })
    const skipped = uploadQueue.value.filter(i => i.status === 'invalid').length
    if (failCount === 0 && skipped === 0) {
      showToast(`${okCount} 个文件上传成功，索引建立中…`)
      queueTimer = setTimeout(() => { uploadQueue.value = [] }, 6000)
    } else {
      showToast(`上传完成：成功 ${okCount}，失败 / 跳过 ${failCount + skipped}`)
    }
    await loadDocuments()
    loadKbs()
  } catch (e) {
    validItems.forEach(it => {
      if (it.status === 'uploading') {
        it.status = 'failed'
        it.error = e.message
      }
    })
    showToast(e.message)
  } finally {
    uploading.value = false
  }
}

function clearQueue() {
  clearTimeout(queueTimer)
  uploadQueue.value = []
}

// ---------- 勾选 / 批量 ----------
const checkedIds = ref(new Set())
const allChecked = computed(() =>
  filteredDocs.value.length > 0 &&
  filteredDocs.value.every(d => checkedIds.value.has(d.id))
)

function toggleCheck(id) {
  const s = new Set(checkedIds.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  checkedIds.value = s
}
function toggleCheckAll() {
  if (allChecked.value) checkedIds.value = new Set()
  else checkedIds.value = new Set(filteredDocs.value.map(d => d.id))
}

const showBatchDelete = ref(false)
async function confirmBatchDelete() {
  acting.value = true
  try {
    const data = await kbApi.batchDeleteDocuments(props.scope, selectedKb.value.id, [...checkedIds.value])
    showToast(`已删除 ${data.deleted} 个文档`)
    checkedIds.value = new Set()
    showBatchDelete.value = false
    await loadDocuments()
    loadKbs()
  } catch (e) {
    showToast(e.message)
  } finally {
    acting.value = false
  }
}

// ---------- 文档操作 ----------
const deleteDocTarget = ref(null)
function askDeleteDoc(doc) { deleteDocTarget.value = doc }

async function confirmDeleteDoc() {
  acting.value = true
  try {
    await kbApi.deleteDocument(props.scope, selectedKb.value.id, deleteDocTarget.value.id)
    showToast('文档已删除')
    deleteDocTarget.value = null
    await loadDocuments()
    loadKbs()
  } catch (e) {
    showToast(e.message)
  } finally {
    acting.value = false
  }
}

async function onReindexDoc(doc) {
  acting.value = true
  try {
    await kbApi.reindexDocument(props.scope, selectedKb.value.id, doc.id)
    showToast(`「${doc.filename}」重建索引中…`)
    await loadDocuments()
  } catch (e) {
    showToast(e.message)
  } finally {
    acting.value = false
  }
}

// ---------- 替换 ----------
const replaceDoc = ref(null)
const replaceFile = ref(null)
const replaceError = ref('')

function openReplace(doc) {
  replaceDoc.value = doc
  replaceFile.value = null
  replaceError.value = ''
}
function onReplaceFilePicked(e) {
  replaceFile.value = e.target.files?.[0] || null
}
async function submitReplace() {
  if (!replaceFile.value) return
  acting.value = true
  replaceError.value = ''
  try {
    await kbApi.replaceDocument(props.scope, selectedKb.value.id, replaceDoc.value.id, replaceFile.value)
    showToast('替换成功，重建索引中…')
    replaceDoc.value = null
    await loadDocuments()
    loadKbs()
  } catch (e) {
    replaceError.value = e.message
  } finally {
    acting.value = false
  }
}

// ---------- 分块预览 ----------
const chunkDoc = ref(null)
const chunks = ref([])
const chunkTotal = ref(0)
const chunkOffset = ref(0)
const chunkLimit = 20
const loadingChunks = ref(false)

function openChunks(doc) {
  chunkDoc.value = doc
  chunkOffset.value = 0
  loadChunks(0)
}
async function loadChunks(offset) {
  loadingChunks.value = true
  try {
    const data = await kbApi.previewChunks(props.scope, selectedKb.value.id, chunkDoc.value.id, Math.max(0, offset), chunkLimit)
    chunks.value = data.chunks || []
    chunkTotal.value = data.total || 0
    chunkOffset.value = Math.max(0, offset)
  } catch (e) {
    showToast(e.message)
  } finally {
    loadingChunks.value = false
  }
}

// ---------- 知识库表单 ----------
const showKbForm = ref(false)
const editingKb = ref(null)
const kbForm = ref({ name: '', biz_line: '', description: '' })
const kbFormError = ref('')

function openCreateKb() {
  editingKb.value = null
  kbForm.value = { name: '', biz_line: '', description: '' }
  kbFormError.value = ''
  showKbForm.value = true
}
function openEditKb() {
  editingKb.value = selectedKb.value
  kbForm.value = {
    name: selectedKb.value.name,
    biz_line: selectedKb.value.biz_line,
    description: selectedKb.value.description,
  }
  kbFormError.value = ''
  showKbForm.value = true
}
async function submitKbForm() {
  acting.value = true
  kbFormError.value = ''
  try {
    if (editingKb.value) {
      await kbApi.updateKb(props.scope, editingKb.value.id, kbForm.value)
      showToast('知识库已更新')
    } else {
      await kbApi.createKb(props.scope, kbForm.value)
      showToast('知识库已创建')
    }
    showKbForm.value = false
    await loadKbs()
  } catch (e) {
    kbFormError.value = e.message
  } finally {
    acting.value = false
  }
}

async function toggleKbEnabled() {
  const target = !selectedKb.value.is_enabled
  try {
    await kbApi.updateKb(props.scope, selectedKb.value.id, { is_enabled: target })
    selectedKb.value.is_enabled = target
    showToast(target ? '已启用，参与检索' : '已停用，不再参与检索')
    loadKbs()
  } catch (e) {
    showToast(e.message)
  }
}

// ---------- 删除知识库 ----------
const showDeleteKb = ref(false)
async function confirmDeleteKb() {
  acting.value = true
  try {
    await kbApi.deleteKb(props.scope, selectedKb.value.id)
    showToast('知识库已删除')
    showDeleteKb.value = false
    selectedKb.value = null
    documents.value = []
    await loadKbs(false)
  } catch (e) {
    showToast(e.message)
  } finally {
    acting.value = false
  }
}

// ---------- 重建索引 ----------
const rebuilding = ref(false)
async function onRebuildKb() {
  rebuilding.value = true
  try {
    await kbApi.rebuildKb(props.scope, selectedKb.value.id)
    showToast('重建任务已开始，后台执行中…')
    setTimeout(loadDocuments, 1500)
  } catch (e) {
    showToast(e.message)
  } finally {
    rebuilding.value = false
  }
}

// ---------- 检索测试 ----------
const activeTab = ref('docs')
const playQuery = ref('')
const playTopK = ref(3)
const playKbIds = ref(new Set())
const playResults = ref(null)
const playLoading = ref(false)
const playError = ref('')

const playScopeKbs = computed(() => {
  // 管理端：全部全局库；用户端：我的库 + 全局启用库
  return props.scope === 'admin' ? kbs.value : [...kbs.value, ...globalKbs.value]
})

function togglePlayKb(id) {
  const s = new Set(playKbIds.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  playKbIds.value = s
}

async function runSearchTest() {
  if (!playQuery.value.trim()) return
  playLoading.value = true
  playError.value = ''
  try {
    const ids = playKbIds.value.size > 0 ? [...playKbIds.value] : null
    const data = await kbApi.searchTest(props.scope, { query: playQuery.value.trim(), kbIds: ids, topK: playTopK.value })
    playResults.value = data.results || []
  } catch (e) {
    playError.value = e.message
    playResults.value = null
  } finally {
    playLoading.value = false
  }
}

// ---------- 嵌入诊断（管理端） ----------
const embStatus = ref(null)
async function openEmbeddingStatus() {
  try {
    embStatus.value = await kbApi.embeddingStatus()
  } catch (e) {
    showToast(e.message)
  }
}

// ---------- 工具 ----------
function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

function statusText(s) {
  return { pending: '待索引', processing: '索引中', ready: '已就绪', failed: '失败' }[s] || s
}

const toast = ref('')
let toastTimer = null
function showToast(msg) {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2600)
}

watch(() => props.scope, () => {
  selectedKb.value = null
  documents.value = []
  kbFilter.value = ''
  docFilter.value = ''
  clearQueue()
  loadKbs(false)
})

onMounted(() => loadKbs(false))
</script>

<style scoped>
.kb-manager {
  display: flex;
  gap: 1.25rem;
  flex: 1;
  min-height: 0;
  width: 100%;
  position: relative;
}

/* ---------- 左侧 ---------- */
.kb-side {
  width: 300px;
  flex-shrink: 0;
  border-radius: var(--radius);
  border: 1px solid var(--border-light);
  padding: 1.1rem;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.side-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 0.8rem;
}
.side-title-block h2 { font-size: 1.05rem; font-weight: 600; }
.side-sub { font-size: 0.7rem; color: var(--text-muted); margin-top: 0.25rem; }

.btn-create {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.34rem 0.75rem;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: 0.78rem;
  cursor: pointer;
  transition: background var(--transition), transform var(--spring-fast);
  flex-shrink: 0;
}
.btn-create:hover { background: var(--accent-hover); transform: translateY(-1px); }

.side-search {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.4rem 0.7rem;
  margin-bottom: 0.7rem;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-pill);
  color: var(--text-muted);
  background: var(--glass-light);
  transition: border-color var(--transition);
}
.side-search:focus-within { border-color: var(--accent); color: var(--text-secondary); }
.side-search input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  outline: none;
  font-size: 0.8rem;
  color: var(--text);
  font-family: inherit;
}
.side-search input::placeholder { color: var(--text-muted); }

.side-loading {
  padding: 2rem 0.5rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.85rem;
}
.side-empty {
  padding: 2rem 0.75rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.55rem;
  text-align: center;
  color: var(--text-muted);
}
.side-empty-title { font-size: 0.95rem; color: var(--text-secondary); }
.side-empty-tip { font-size: 0.75rem; line-height: 1.7; }
.side-empty-cta { margin-top: 0.4rem; }

.side-section-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  color: var(--text-muted);
  margin: 1.1rem 0 0.5rem;
  padding-top: 0.9rem;
  border-top: 1px solid var(--border-light);
}

.kb-list { list-style: none; display: flex; flex-direction: column; gap: 0.4rem; }

.kb-item {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.6rem 0.7rem;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--transition);
}
.kb-item:hover { background: var(--hover); }
.kb-item.active {
  background: var(--accent-light);
  border-color: var(--border);
}
.kb-item.disabled .kb-name-text { color: var(--text-muted); }
.kb-item-global { cursor: default; opacity: 0.85; }
.kb-item-global:hover { background: transparent; }

.kb-tile {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  border: 1px solid var(--border-light);
  background: var(--accent-light);
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-secondary);
  transition: all var(--transition);
}
.kb-item.active .kb-tile {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-contrast);
}
.kb-tile-global { background: transparent; color: var(--text-muted); }

.kb-item-main { flex: 1; min-width: 0; }
.kb-item-name {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.88rem;
  font-weight: 500;
}
.kb-name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 130px;
}
.kb-item-meta {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.3rem;
  font-size: 0.72rem;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
}

/* ---------- 标签 ---------- */
.tag {
  display: inline-flex;
  align-items: center;
  padding: 0.08rem 0.45rem;
  border-radius: var(--radius-pill);
  font-size: 0.68rem;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  flex-shrink: 0;
}
.tag-default { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
.tag-biz { background: transparent; }
.tag-off { color: var(--text-muted); border-style: dashed; }

/* ---------- 右侧 ---------- */
.kb-main {
  flex: 1;
  min-width: 0;
  border-radius: var(--radius);
  border: 1px solid var(--border-light);
  padding: 1.25rem 1.4rem;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  position: relative;
}

.main-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.7rem;
  color: var(--text-muted);
}
.main-empty-title { font-size: 1.05rem; color: var(--text-secondary); }
.main-empty-tip { font-size: 0.78rem; }

.kb-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}
.kb-head-title-row { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.kb-head-title-row h3 { font-size: 1.2rem; font-weight: 600; }
.kb-head-creator { font-size: 0.72rem; color: var(--text-muted); }
.kb-head-desc { font-size: 0.82rem; color: var(--text-secondary); margin-top: 0.4rem; line-height: 1.6; }

.kb-head-actions { display: flex; align-items: center; gap: 0.45rem; flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; }

/* 开关 */
.switch-wrap {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
  margin-right: 0.15rem;
}
.switch { position: relative; width: 36px; height: 20px; display: inline-block; }
.switch input { display: none; }
.switch-slider {
  position: absolute; inset: 0;
  background: var(--accent-soft);
  border-radius: var(--radius-pill);
  transition: background var(--transition);
  cursor: pointer;
}
.switch-slider::before {
  content: '';
  position: absolute;
  width: 14px; height: 14px;
  left: 3px; top: 3px;
  background: var(--panel);
  border-radius: 50%;
  transition: transform var(--transition);
  box-shadow: 0 1px 3px var(--shadow-sm);
}
.switch input:checked + .switch-slider { background: var(--accent); }
.switch input:checked + .switch-slider::before { transform: translateX(16px); }
.switch-label { font-size: 0.75rem; color: var(--text-secondary); user-select: none; }

/* ---------- 统计条 ---------- */
.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin-top: 1rem;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--glass-light);
  overflow: hidden;
}
.stat-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
  padding: 0.7rem 0.5rem;
}
.stat-cell + .stat-cell { border-left: 1px solid var(--border-light); }
.stat-num { font-size: 1.25rem; font-weight: 600; line-height: 1.1; }
.stat-num-sub { font-size: 0.8rem; color: var(--text-muted); font-weight: 400; }
.stat-num-time { font-size: 0.88rem; }
.stat-label {
  font-size: 0.68rem;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}
.stat-hint { color: var(--text-secondary); }
.stat-hint-danger { color: var(--danger); }

/* 页签 */
.kb-tabs {
  display: flex;
  gap: 0.25rem;
  margin: 1rem 0 0.9rem;
  border-bottom: 1px solid var(--border-light);
}
.kb-tab {
  padding: 0.5rem 1rem;
  border: none;
  background: none;
  font-size: 0.88rem;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all var(--transition);
}
.kb-tab:hover { color: var(--text); }
.kb-tab.active { color: var(--text); border-bottom-color: var(--accent); font-weight: 500; }

.tab-body { flex: 1; display: flex; flex-direction: column; min-height: 0; }

/* ---------- 拖拽上传 ---------- */
.dropzone {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  border: 1.5px dashed var(--border);
  border-radius: var(--radius-sm);
  padding: 0.9rem 1.1rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition);
}
.dropzone:hover { border-color: var(--accent); background: var(--hover); }
.dropzone.dragging { border-color: var(--accent); background: var(--accent-light); }
.dropzone.disabled { opacity: 0.55; cursor: not-allowed; }

.dropzone-icon {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid var(--border-light);
  background: var(--accent-light);
  color: var(--text);
}
.dropzone-text { font-size: 0.88rem; flex-shrink: 0; }
.dropzone-tip { font-size: 0.7rem; color: var(--text-muted); margin-left: auto; text-align: right; }

/* ---------- 上传队列 ---------- */
.upload-queue {
  margin-top: 0.75rem;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  overflow: hidden;
  animation: fadeUp 0.3s var(--ease-out-expo);
}
.uq-head {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.45rem 0.8rem;
  background: var(--accent-light);
  font-size: 0.78rem;
  color: var(--text-secondary);
}
.uq-title { font-weight: 500; }
.uq-bad { color: var(--danger); font-size: 0.74rem; }
.uq-clear {
  margin-left: auto;
  border: none;
  background: none;
  font-size: 0.74rem;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0.1rem 0.3rem;
}
.uq-clear:hover { color: var(--text); }
.uq-clear:disabled { opacity: 0.4; cursor: not-allowed; }

.uq-progress { height: 3px; background: var(--accent-soft); overflow: hidden; }
.uq-progress-fill { height: 100%; background: var(--accent); transition: width 0.3s ease; }
.uq-progress-fill.indeterminate {
  background: linear-gradient(90deg, var(--accent-soft), var(--accent), var(--accent-soft));
  background-size: 200% 100%;
  animation: uq-shimmer 1.2s linear infinite;
}
@keyframes uq-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.uq-body { max-height: 180px; overflow-y: auto; }
.uq-item {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.5rem 0.8rem;
  border-top: 1px solid var(--border-light);
  font-size: 0.8rem;
}
.uq-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.uq-size { color: var(--text-muted); font-size: 0.74rem; flex-shrink: 0; }
.uq-status {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.74rem;
  flex-shrink: 0;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.uq-waiting { color: var(--text-muted); }
.uq-uploading { color: var(--text-secondary); }
.uq-success { color: var(--text); }
.uq-failed, .uq-invalid { color: var(--danger); }

/* ---------- 扩展名瓦片 ---------- */
.ext-tile {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  height: 22px;
  padding: 0 0.3rem;
  border-radius: 6px;
  border: 1px solid var(--border-light);
  background: var(--accent-light);
  font-size: 0.64rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--text-secondary);
  flex-shrink: 0;
}

/* ---------- 工具条 ---------- */
.doc-toolbar {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  margin: 0.9rem 0 0.55rem;
  font-size: 0.8rem;
  flex-wrap: wrap;
}
.doc-search {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.32rem 0.7rem;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-pill);
  color: var(--text-muted);
  transition: border-color var(--transition);
  min-width: 170px;
}
.doc-search:focus-within { border-color: var(--accent); color: var(--text-secondary); }
.doc-search input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 0.78rem;
  color: var(--text);
  font-family: inherit;
  width: 100%;
}
.doc-search input::placeholder { color: var(--text-muted); }

.check-all { display: flex; align-items: center; gap: 0.35rem; cursor: pointer; color: var(--text-secondary); }
.checked-count { color: var(--text-muted); }
.doc-toolbar .refresh { margin-left: auto; }

/* ---------- 表格 ---------- */
.table-loading {
  padding: 2.5rem 0;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.85rem;
}
.table-empty {
  padding: 2.2rem 0 2.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.85rem;
}
.table-empty-title { font-size: 0.95rem; color: var(--text-secondary); }
.table-empty-tip { font-size: 0.76rem; line-height: 1.7; }
.table-empty-cta { margin-top: 0.5rem; padding: 0.45rem 1.2rem; font-size: 0.82rem; }

.doc-table-wrap { overflow-x: auto; border: 1px solid var(--border-light); border-radius: var(--radius-sm); }
.doc-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.doc-table th {
  text-align: left;
  padding: 0.55rem 0.7rem;
  background: var(--accent-light);
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
}
.doc-table td {
  padding: 0.55rem 0.7rem;
  border-top: 1px solid var(--border-light);
  vertical-align: middle;
  white-space: nowrap;
}
.doc-table tr:hover td { background: var(--hover); }
.col-check { width: 30px; }
.col-name { max-width: 240px; }
.doc-name {
  display: inline-block;
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  margin-left: 0.45rem;
}
.col-time { color: var(--text-muted); font-size: 0.75rem; }
.col-src { color: var(--text-secondary); font-size: 0.75rem; }
.col-ops { width: 130px; }

/* ---------- 状态徽章 ---------- */
.st-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.14rem 0.6rem;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border-light);
  font-size: 0.72rem;
}
.st-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.st-ready { color: var(--text); }
.st-pending, .st-processing { color: var(--text-muted); }
.st-pending .st-dot, .st-processing .st-dot { animation: st-pulse 1.3s ease-in-out infinite; }
.st-failed { color: var(--danger); border-color: var(--danger-border); }
@keyframes st-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.3; transform: scale(0.75); }
}

.op-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px; height: 26px;
  margin-right: 0.25rem;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition);
}
.op-btn:hover { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
.op-btn.danger:hover { background: var(--danger); border-color: var(--danger); color: #fff; }
.op-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ---------- 按钮 ---------- */
.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.38rem 0.85rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all var(--transition);
}
.btn-ghost:hover { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
.btn-ghost.danger { color: var(--danger); border-color: var(--danger-border); }
.btn-ghost.danger:hover { background: var(--danger); color: #fff; border-color: var(--danger); }
.btn-ghost.small { padding: 0.26rem 0.7rem; font-size: 0.75rem; }
.btn-ghost:disabled { opacity: 0.45; cursor: not-allowed; }

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.55rem 1.4rem;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: 0.88rem;
  cursor: pointer;
  transition: background var(--transition);
}
.btn-primary:hover { background: var(--accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

/* ---------- 全局拖拽遮罩 ---------- */
.drag-overlay {
  position: absolute;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius);
  background: var(--glass-strong);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  pointer-events: none;
}
.drag-overlay-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.55rem;
  padding: 2rem 2.8rem;
  border: 1.5px dashed var(--accent);
  border-radius: var(--radius);
  background: var(--accent-light);
  color: var(--text);
}
.drag-overlay-title { font-size: 1rem; font-weight: 600; }
.drag-overlay-tip { font-size: 0.74rem; color: var(--text-muted); }

/* ---------- 检索测试 ---------- */
.play-panel { display: flex; flex-direction: column; gap: 0.8rem; }
.play-input-row { display: flex; gap: 0.6rem; }
.play-input {
  flex: 1;
  padding: 0.6rem 1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--panel);
  color: var(--text);
  font-size: 0.88rem;
  outline: none;
  transition: border-color var(--transition);
}
.play-input:focus { border-color: var(--accent); }
.play-topk {
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--panel);
  color: var(--text);
  padding: 0 0.7rem;
  font-size: 0.82rem;
  cursor: pointer;
}

.play-scope { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; font-size: 0.78rem; }
.play-scope-label { color: var(--text-muted); }
.scope-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.24rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  cursor: pointer;
  color: var(--text-secondary);
  transition: all var(--transition);
  user-select: none;
}
.scope-chip input { display: none; }
.scope-chip.on { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
.play-scope-tip { color: var(--text-muted); font-size: 0.72rem; }
.play-error { color: var(--danger); font-size: 0.82rem; }

.play-results { display: flex; flex-direction: column; gap: 0.6rem; }
.play-card {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 0.75rem 0.9rem;
  animation: fadeUp 0.3s var(--ease-out-expo);
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.play-card-head { display: flex; align-items: center; gap: 0.7rem; margin-bottom: 0.45rem; }
.play-rank { font-family: var(--font-display); font-weight: 600; font-size: 0.9rem; }
.play-score { display: flex; align-items: center; gap: 0.4rem; flex: 0 0 150px; }
.play-score-bar {
  flex: 1; height: 5px;
  background: var(--accent-soft);
  border-radius: 3px;
  overflow: hidden;
}
.play-score-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.5s var(--ease-out-expo); }
.play-score-num { font-size: 0.75rem; color: var(--text-secondary); min-width: 38px; text-align: right; }
.play-src {
  font-size: 0.72rem;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.play-content {
  font-size: 0.82rem;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 160px;
  overflow-y: auto;
}

/* ---------- 抽屉 ---------- */
.drawer-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.28);
  z-index: 9050;
  display: flex;
  justify-content: flex-end;
}
.drawer {
  width: min(560px, 92vw);
  height: 100%;
  padding: 1.4rem;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border-light);
}
.drawer-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; }
.drawer-head h3 { font-size: 1.05rem; }
.drawer-sub { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.3rem; word-break: break-all; }
.drawer-close {
  border: none; background: none; cursor: pointer;
  color: var(--text-muted); padding: 0.3rem;
}
.drawer-close:hover { color: var(--text); }
.drawer-body { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 0.6rem; }
.drawer-foot {
  display: flex; align-items: center; justify-content: center; gap: 1rem;
  padding-top: 0.9rem;
  border-top: 1px solid var(--border-light);
  font-size: 0.78rem;
  color: var(--text-muted);
}

.chunk-card { border: 1px solid var(--border-light); border-radius: var(--radius-sm); padding: 0.65rem 0.8rem; }
.chunk-head { display: flex; justify-content: space-between; margin-bottom: 0.35rem; font-size: 0.72rem; }
.chunk-idx { font-weight: 600; }
.chunk-size { color: var(--text-muted); }
.chunk-content {
  font-size: 0.8rem;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- 弹窗 ---------- */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.28);
  backdrop-filter: blur(4px);
  z-index: 9100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.modal-card {
  width: min(440px, 100%);
  background: var(--panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: 1.6rem;
  box-shadow: 0 20px 60px var(--shadow);
}
.modal-title { font-size: 1.1rem; margin-bottom: 0.9rem; }
.modal-desc { font-size: 0.85rem; color: var(--text-secondary); line-height: 1.7; margin-bottom: 0.9rem; }
.modal-form { display: flex; flex-direction: column; gap: 0.4rem; margin-bottom: 0.6rem; }
.form-label { font-size: 0.78rem; color: var(--text-secondary); margin-top: 0.4rem; }
.form-input {
  padding: 0.55rem 0.85rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text);
  font-size: 0.86rem;
  outline: none;
  font-family: inherit;
}
.form-input:focus { border-color: var(--accent); }
.form-textarea { resize: vertical; }
.form-error { color: var(--danger); font-size: 0.8rem; margin-bottom: 0.5rem; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.6rem; margin-top: 1rem; }
.modal-btn {
  padding: 0.5rem 1.2rem;
  border-radius: var(--radius-pill);
  font-size: 0.85rem;
  cursor: pointer;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  transition: all var(--transition);
}
.modal-btn-primary { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
.modal-btn-primary:hover { background: var(--accent-hover); }
.modal-btn-danger { background: var(--danger); color: #fff; border-color: var(--danger); }
.modal-btn-danger:hover { background: var(--danger-hover); }
.modal-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ---------- 嵌入诊断 ---------- */
.emb-grid {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 0.45rem 0.9rem;
  font-size: 0.84rem;
  margin-bottom: 0.4rem;
}
.emb-label { color: var(--text-muted); }
.emb-value { word-break: break-all; }
.emb-error { color: var(--danger); font-size: 0.78rem; }
.modal-desc code {
  padding: 0.05rem 0.35rem;
  background: var(--accent-light);
  border-radius: 4px;
  font-size: 0.78rem;
}

/* ---------- 轻提示 ---------- */
.kb-toast {
  position: fixed;
  bottom: 2rem;
  left: 50%;
  transform: translateX(-50%);
  padding: 0.6rem 1.4rem;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border-light);
  font-size: 0.82rem;
  z-index: 9200;
  box-shadow: 0 8px 30px var(--shadow-sm);
}

/* ---------- 加载 ---------- */
.spinner {
  display: inline-block;
  width: 16px; height: 16px;
  border: 2px solid var(--accent-soft);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: rot 0.8s linear infinite;
  vertical-align: -3px;
  margin-right: 0.4rem;
}
.spinner.small { width: 12px; height: 12px; border-width: 1.5px; }
.spinner.tiny { width: 10px; height: 10px; border-width: 1.5px; margin-right: 0; }
.spinner.light { border-color: rgba(255,255,255,0.35); border-top-color: #fff; }
@keyframes rot { to { transform: rotate(360deg); } }
.spin { animation: rot 1s linear infinite; }

.btn-spinner {
  display: inline-block;
  width: 13px; height: 13px;
  border: 2px solid rgba(255,255,255,0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: rot 0.8s linear infinite;
}

/* ---------- 过渡 ---------- */
.modal-enter-active, .modal-leave-active { transition: opacity 0.22s ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.drawer-enter-active, .drawer-leave-active { transition: all 0.3s var(--ease-out-expo); }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-active .drawer, .drawer-leave-active .drawer { transition: transform 0.3s var(--ease-out-expo); }
.drawer-enter-from .drawer, .drawer-leave-to .drawer { transform: translateX(40px); }
.toast-enter-active, .toast-leave-active { transition: all 0.25s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 8px); }
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.serif { font-family: var(--font-display); }

/* ---------- 响应式 ---------- */
@media (max-width: 900px) {
  .kb-manager { flex-direction: column; overflow-y: auto; }
  .kb-side { width: 100%; max-height: 280px; }
  .kb-main { overflow-y: visible; }
  .kb-head { flex-direction: column; }
  .kb-head-actions { justify-content: flex-start; }
  .stat-strip { grid-template-columns: repeat(2, 1fr); }
  .stat-cell:nth-child(3) { border-left: none; }
  .stat-cell:nth-child(n+3) { border-top: 1px solid var(--border-light); }
  .dropzone { flex-direction: column; text-align: center; gap: 0.45rem; }
  .dropzone-tip { margin-left: 0; text-align: center; }
  .dropzone-text { flex-shrink: 1; }
  .doc-search { min-width: 0; flex: 1; }
}
</style>
