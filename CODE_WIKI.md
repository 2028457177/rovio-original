# lc-course (Rovio) Code Wiki

> 面向开发者/维护者的代码级 wiki。涵盖整体架构、模块职责、关键类与函数、依赖关系、数据模型与运行方式。
> 本文档基于仓库实际代码编写，与 [README.md](README.md)（对外总览）和 [项目结构介绍.md](项目结构介绍.md)（目录级说明）互补，本文侧重**代码级**细节。

---

## 1. 项目概览

**项目名**：Rovio（pyproject 包名）／lc-course（仓库名）
**定位**：多智能体协同的自动化办公助手。用户一句话 → 「规划 → 多 Agent 并行执行 → 反思修订 → 汇总」全流程，集成 RAG 知识库、联网搜索、代码沙箱、网页抓取、Word 文档生成/填充、产物管理、长期记忆、课表/天气查询，全程 SSE 流式可观测。

**形态**：
- 后端：6 个独立 FastAPI 微服务（各自独立 MySQL 库、自带 `core/` 库，**绝对解耦**）
- 智能体引擎：`AIRAGAgent/` 包（Planner → Executor → Reflector → Finalizer 四阶段编排）
- 前端：Vue 3 + Vite（SSE 流式聊天、知识库管理、计划可观测面板、管理后台）
- 通信：前端→Nginx(URL 前缀)→微服务；微服务间 HTTP + JWT 透传；事件流 Redis Pub/Sub

**架构演进**：旧版 Streamlit + `SupervisorAgent`/`ReactAgent` 两层单体已废弃；现为微服务 + Orchestrator 四阶段范式。

---

## 2. 整体架构

### 2.1 服务拓扑

```
                         ┌───────────────────────────────────────┐
                         │  前端 Vue3+Vite  ChatView/KbManager/... │
                         └───────────────────┬───────────────────┘
                                             │ /api/*  (SSE 流式)
                                             ▼
                                       ┌───────────┐
                                       │  Nginx    │  按 URL 前缀路由
                                       └─────┬─────┘
        ┌────────────────────────────────────┼────────────────────────────────────┐
        ▼                                    ▼                                     ▼
┌──────────────┐                     ┌──────────────┐                    ┌──────────────┐
│ auth_service │                     │ chat_service │                    │ kb_service   │
│    :8001     │                     │    :8003     │                    │    :8004     │
│ JWT 签发/校验 │                     │ /api/chat SSE │                    │ 多知识库 RAG │
│ 注册/登录/找回│                     │ Orchestrator  │                    │ 文档索引/检索 │
│ 设备管理      │                     │  Supervisor  │                    └──────┬───────┘
└──────┬───────┘                     └──────┬───────┘                           │
       │                                    │                                   ▼
       │  HTTP+JWT                     ┌────┴────────┐                    ┌────────────┐
       ▼                                ▼            ▼                    │ ChromaDB   │
┌──────────────┐                ┌─────────────┐  ┌──────────────┐        │ kb_store  │
│ user_service │                │ AIRAGAgent  │  │ admin_service│        └────────────┘
│    :8002     │                │ 引擎(进程内) │  │   :8005      │◀──Redis Pub/Sub
│ 档案/课表/   │                └─────────────┘  │ 统计/审计/限流│
│ 模型设置/注销│                                  └──────────────┘
└──────────────┘
                                      ┌──────────────┐
                                      │ file_service │
                                      │   :8006      │  文件系统即存储
                                      └──────────────┘

  ── 每服务独立 MySQL 库: lc_auth / lc_user / lc_chat / lc_kb / lc_admin ──
```

### 2.2 Supervisor-Worker 多智能体编排（chat_service 进程内）

```
POST /api/chat ──→ Orchestrator.execute_stream(query, chat_history, user_id, session_id)

 ① Planner 规划器 (_plan_stream)      # 流式 reasoning_content → 纯文本 JSON → PlanSpec
    - 召回长期记忆 (Qdrant 向量) + 知识库命中预检 (_kb_route_hint) 注入上下文
    - 输出 Plan → 持久化 plans + plan_steps 表
    - 闲聊 1 步无 SubAgent；独立子任务并行(depends_on 留空)；有依赖加 depends_on

 ② Executor + Reflector 主循环      # while not plan.is_all_done()
    - get_ready_steps() 依赖感知调度
    - 单 ready → _execute_step 串行（subagent 空→Orchestrator LLM 直接答；非空→SubAgentRunner）
    - 多 ready → _execute_steps_parallel (ThreadPoolExecutor max=5, ContextVar 按线程 copy)
    - Reflector.action: accept | retry(≤1) | revise(≤2) | ask_user
    - 每步结果落盘 tasks/<plan_id>/plan_results/step_<idx>.md（跨步骤交接断点）
    - 下游 step 任务描述注入前序步骤文件路径 + 200 字摘要

 ③ Finalizer 汇总器 (_finalize)
    - 单步(无 subagent)直接复用 step.result；多步 LLM 整合
    - 完成后 _promote_plan_outputs 整理工作区：删 plan_results、最终文件提升到当天目录

SSE 事件: thinking / plan_created / step_* / plan_reflecting / plan_revised / plan_completed / ask_user
```

### 2.3 数据流 / 调用链

- **认证**：auth_service 签发 JWT（HS256，含 user_id/username/role/device_token）→ 各服务 `get_current_user` 本地解码，不回源查库。
- **知识库**：kb_service 管理 `knowledge_bases`/`kb_documents`（lc_kb 库）+ Chroma 集合 `kb_store` 向量。chat_service 内 Orchestrator 查知识库**直连 lc_kb**（`_kb_accessible_ids` 用 pymysql 连 KB_DB，不能走被 db_patch 重定向的 get_db）。
- **统计审计**：chat_service 每次对话结束发 Redis 事件 `events:chat.completed`（含耗时/Token）→ admin_service 后台线程订阅落库 `api_call_logs`；限流超限发 `events:rate.limited` → `rate_limit_events`。
- **管理操作**：admin_service 通过 ServiceClient 调 auth/user/chat 服务的 `/internal/*` 接口，透传当前请求 JWT。
- **注销级联**：user_service 注销 → 调 auth_service 删 users + chat_service `/internal/chat/users/{id}/cleanup` 删会话消息。

---

## 3. 技术栈

| 层级 | 技术 | 版本/说明 |
|------|------|-----------|
| 后端框架 | FastAPI + Uvicorn | async + SSE 流式；每服务独立启动 |
| 智能体编排 | LangGraph + LangChain | `create_agent` + 中间件链（ToolCallLimit/监控/提示词切换）；`stream_mode="messages"` |
| LLM | DeepSeek (thinking 模式) | 流式 `reasoning_content` 作为思考过程；`request_timeout=240, max_retries=1` |
| 向量库 | ChromaDB | 集合 `kb_store`，持久化目录 `chroma_ab/` |
| 记忆向量 | Qdrant | 长期记忆向量检索（`memory_store.search_memories`，不可用时静默降级） |
| 嵌入 | Ollama / DashScope / OpenAI 兼容端点 | chroma.yml 可热切换 |
| 数据库 | MySQL 8（每服务独立库） | pymysql + DictCursor + autocommit |
| 缓存/事件 | Redis 7 | 会话消息缓存、限流计数、Pub/Sub 事件总线 |
| 鉴权 | JWT (HS256) | 所有服务同一 `JWT_SECRET_KEY` |
| 代码沙箱 | subprocess + AST 检查 | 危险调用告警 + 命令黑名单 + 超时 + 输出截断 5000 字 |
| 浏览器自动化 | Playwright 1.61 | stealth 反检测；二进制存 `workspace/.playwright/` |
| 搜索 | Tavily Search API | `search` 工具 |
| 前端 | Vue 3.5 + Vite 8 + vue-router 4 | markdown-it 渲染、vue-virtual-scroller 虚拟滚动 |
| 包管理 | uv + uv.lock | 依赖锁定；Python ≥ 3.13 |
| 部署 | paramiko SFTP + systemd | 目标服务器 81.70.100.57 |

---

## 4. 目录结构总览

```
lc-course/
├── AIRAGAgent/               # 智能体引擎包（被 chat_service/kb_service 复用）
│   ├── agent/                # 编排核心
│   │   ├── orchestrator.py   #   Orchestrator 主循环（Planner/Executor/Reflector/Finalizer）
│   │   ├── plan.py           #   Plan/PlanStep 数据模型 + 持久化 CRUD
│   │   ├── sub_agent.py      #   SubAgent 定义 / Registry / Runner / 并行执行器
│   │   ├── sub_agents/builtin.py  # 内置 SubAgent 注册（10 个）
│   │   ├── memory/           #   长期记忆：extractor + vector_store(Qdrant) + migrate_legacy
│   │   └── tools/            #   agent/file/search/codexec/browser/memory/artifact/wordgen/middleware/sandbox_config
│   ├── kb/                   # 多知识库 RAG 服务层（service/embedding/models）
│   ├── rag/                  # 向量存储 + RAG 检索（vector_store/rag_service）
│   ├── model/factory.py      # ChatModelFactory / EmbeddingsFactory + 单例
│   ├── database/             # connection.py(pymysql+init_db建表) / models.py(会话消息等 CRUD)
│   ├── infrastructure/       # redis_client/session_cache/rag_cache/rate_limiter/task_queue
│   ├── config/               # agent/chroma/rag/mysql/redis/prompts.yml
│   ├── prompts/              # identity/main/tools/rag_summarize/report_prompt.txt
│   ├── skills/               # 技能扩展框架（兼容层保留）
│   └── utils/                # paths/config_handler/file_handler/logger_handler/prompt_loader/path_tool
├── services/                 # 6 个微服务（各带独立 core/ 库）
│   ├── auth_service/  :8001  # 注册/登录/JWT/找回/密保/设备
│   ├── user_service/  :8002  # 档案/课表/头像/模型设置/注销
│   ├── chat_service/  :8003  # /api/chat SSE → Orchestrator（核心）
│   ├── kb_service/    :8004  # 多知识库 CRUD + 文档索引/检索（28 路由）
│   ├── admin_service/ :8005  # 统计/审计/限流（Redis 订阅聚合）
│   └── file_service/  :8006  # workspace 文件浏览/下载/预览（无 DB）
├── frontend/                 # Vue 3 + Vite
│   └── src/
│       ├── api/              #   auth/chat/kb/file.js
│       ├── components/       #   ChatInput/MessageBubble/PlanPanel/PlanHistory/KbManager/SideDrawer/TaskQueue...
│       ├── composables/      #   useChat.js / useTheme.js
│       ├── router/           #   index.js（beforeEach 校验 token）
│       ├── views/            #   ChatView/Login/AdminView/AdminKbView/UserKbView/SettingsView
│       └── utils/markdown.js
├── tests/                    # pytest（auth/user/chat/kb/admin/file/agent_core 各服务测试）
├── deploy/                   # 部署脚本 + nginx 配置 + .env 模板
├── migrations/               # Alembic（versions/{admin,auth,chat,kb,user}/0001_baseline.py）
├── workspace/                # AI 工作区 {user_id}/{YYYYMMDD}/tasks/<plan_id>/（gitignore）
├── uploads/                  # avatars/ kb/{kb_id}/{md5}.{ext} screenshots/（gitignore）
├── chroma_ab/                # ChromaDB 持久化（gitignore）
├── pyproject.toml            # uv 依赖（Rovio, Python ≥3.13）
├── docker-compose.yml        # MySQL/Redis/Qdrant 容器编排
└── 项目手册.md / 项目结构介绍.md
```

---

## 5. 微服务层详解（services/）

### 5.1 通用 core/ 库（每服务独立副本，代码一致）

| 文件 | 关键类/函数 | 说明 |
|------|-------------|------|
| `core/config.py` | `PORT`/`DB_NAME`/`MYSQL_*`/`REDIS_*`/`JWT_*`/`ADMIN_ALLOWED_IPS`/`get_mysql_config()` | 纯环境变量驱动，兼容旧变量名（如 `CHAT_PORT`→`PORT`）；`get_service_url(name)` 推导跨服务地址（优先 `*_SERVICE_URL`，其次 `INTERNAL_HOST`+`*_PORT`） |
| `core/base_app.py` | `create_app(service_name, version, on_startup, on_shutdown)` | FastAPI 工厂：lifespan 管理、CORS(`*`)、自动 `GET /api/health`（返回 status/service/redis connected） |
| `core/db.py` | `get_connection()` / `get_db()` / `ensure_database_exists()` | pymysql + DictCursor + autocommit 上下文管理器 |
| `core/jwt_auth.py` | `create_access_token()` / `decode_token()` / `get_current_user()` / `get_admin_user()` / `get_client_ip()` | HS256；支持 `Authorization: Bearer` 与 `?token=` 两种方式；admin 需 role=admin + IP 白名单 |
| `core/http_client.py` | `ServiceClient(name)` / `call_service(name, method, path, ...)` | httpx.AsyncClient 封装，目标地址来自 `get_service_url` |
| `core/redis_client.py` | `get_redis_client()` / `is_redis_available()` / `close_redis()` | 连接池 |
| `core/events.py` | `CHANNEL_CHAT_COMPLETED` / `CHANNEL_RATE_LIMITED` / `CHANNEL_TOOL_CALLED`；`publish_event()` / `subscribe_events()` | Redis Pub/Sub 事件总线（chat/admin 用） |
| `core/logger.py` / `core/paths.py` | `set_service_name()` / `LOG_DIR`/`UPLOAD_DIR`/`WORKSPACE_DIR` | 日志与路径常量 |

### 5.2 auth_service (:8001, DB: lc_auth)

**职责**：认证中枢。JWT 签发/校验、注册/登录/找回密码、密保问题、登录设备管理（多端登录）。

**关键路由**（`main.py`）：
- 对外：`POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/me`、`GET /api/auth/recover/question`、`POST /api/auth/recover/reset`；`PUT /api/user/password`、`PUT /api/user/security-question`、`GET /api/user/devices`、`DELETE /api/user/devices/{id}`、`POST /api/user/devices/revoke-all-others`
- 内部：`GET /internal/auth/user/{id}`、`GET /internal/auth/users`、`POST /internal/auth/users/{id}/delete`、`POST /internal/auth/users/{id}/reset-password`、`GET /internal/auth/users/{id}/role`

**关键函数**（`models.py`）：`create_user` / `get_user_by_username` / `get_user_by_id` / `verify_password` / `create_login_device` / `touch_login_device` / `get_login_devices` / `revoke_login_device` / `revoke_all_other_devices` / `reset_password_by_security_answer`。密码用 `_hash_password`（加盐哈希），密保答案 `_hash_security_answer`。

### 5.3 user_service (:8002, DB: lc_user)

**职责**：用户档案、头像、课表设置、模型设置、账号注销。

**关键路由**（`main.py`，前缀 `/api/user/*`）：`/profile`、`/avatar`、`/schedule`、`/model`、`/account`（注销，级联调 auth/chat 内部接口）；静态 `/api/avatars/*`、`/api/schedules/*`。

**关键函数**（`models.py`）：`get_profile` / `upsert_profile` / `update_avatar_url` / `ensure_profile`；课表与模型设置 CRUD。

### 5.4 chat_service (:8003, DB: lc_chat) ★ 核心

**职责**：DeepAgent 入口。`/api/chat` SSE 流式 → `AgentService` → `Orchestrator`；会话/反馈/计划历史/任务队列。

**启动顺序关键点**：`agent.py` 在 **import AIRAGAgent 之前** 执行 `db_patch.apply_db_redirect()`，把 AIRAGAgent 的 `mysql_conf["database"]` 重定向到 `lc_chat`。

**关键路由**（`main.py`）：
- `POST /api/chat`：JWT 鉴权 → IP 提取 → ContextVar 注入（user_id/ip/lat/lon/search_enabled）→ 限流（Redis，超限 429 + 发 `events:rate.limited`）→ SSE `StreamingResponse`（`X-Accel-Buffering: no`）
- `POST /api/plan`：mode=stream（SSE）/ background（task_queue 后台执行返回 task_id）
- `GET /api/plans`、`GET /api/plans/{plan_id}`、`GET /api/tasks/{task_id}`、`GET /api/subagents`
- 会话：`GET/POST /api/conversations`、`DELETE /api/conversations/{id}`、`PATCH /api/conversations/{id}/meta`、`GET /api/conversations/search`、`POST /api/conversations/{id}/branch`
- `POST /api/feedback`
- 内部：`GET /internal/chat/users/{id}/conversations`、`DELETE /internal/chat/users/{id}/cleanup`

**AgentService**（`agent.py`）：
- `stream_response(user_id, message, session_id, truncate_to)`：异步 SSE 桥接。`asyncio.Queue` + `contextvars.copy_context()`，`sync_producer` 在 `loop.run_in_executor` 中跑 `Orchestrator.execute_stream`，`loop.call_soon_threadsafe(queue.put_nowait, chunk)` 回传。生成前先 `save_message(user, ...)` 防丢失，结束后 try/finally 落库 assistant + 发 `message_ids` 事件。finally 埋点：`log_api_call` + `publish_event(CHANNEL_CHAT_COMPLETED)`；再异步 fire-and-forget 触发 `extract_memories_async`。
- `enqueue_plan_background()`：投递 `TaskType.PLAN_EXECUTE` 到 task_queue。

### 5.5 kb_service (:8004, DB: lc_kb)

**职责**：多知识库管理（管理端 + 用户端）+ 文档索引/检索 + 检索测试。模块加载时 patch `mysql_conf["database"] = lc_kb` 重定向 kb_models；启动钩子 `_on_startup` 调 `seed_default_kb()` 播种默认库。

**路由分组**（`main.py`，共 28 个）：
- 管理端 `/api/admin/kb/*`：`list/create/patch/delete`、documents 上传/批量删除/替换/重索引、chunks 预览、rebuild、search-test、embedding-status
- 用户端 `/api/kb/*`：`mine`/创建/更新/删除、documents CRUD（`_user_kb_or_403` 归属校验）、search-test
- 内部：`GET /internal/kb/search`（无鉴权，按 user_id 解析可访问库，供 Orchestrator 调用）

**核心辅助**：`_kb_file_rel_path`（`kb/{kb_id}/{md5}.{ext}` 内容寻址去重）、`_do_upload`/`_do_replace`（上传→后台线程异步索引）、`_search_test`（带分数检索）。

### 5.6 admin_service (:8005, DB: lc_admin)

**职责**：统计/审计/限流看板。启动时 `subscribe_events` 三个 Redis 频道后台线程订阅落库：
- `on_chat_completed` → `api_call_logs`
- `on_tool_called` → `tool_call_logs`
- `on_rate_limited` → `rate_limit_events`

**关键路由**：`GET /api/admin/users`（auth+user 资料合并）、`GET /api/admin/users/{id}/conversations`、`POST /api/admin/users/{id}/delete`、`POST /api/admin/users/{id}/reset-password`、`GET /api/admin/stats/{overview,trends,tools,top}`。跨服务调用透传 JWT（`_extract_token` + `call_service`）。

**关键函数**（`models.py`）：`get_dashboard_overview` / `get_dashboard_trends` / `get_dashboard_tool_distribution` / `get_dashboard_error_stats` / `get_dashboard_top_users` / `get_dashboard_top_questions`。

### 5.7 file_service (:8006, 无 DB)

**职责**：AI 工作区文件访问。`GET /api/file/list`（相对当前用户工作区浏览，过滤 `.playwright`）、`GET /api/file/download`、`GET /api/file/preview`。全部 `Depends(get_current_user)` 按 `user["id"]` 限定根目录到 `workspace/{user_id}/`（`_resolve_workspace_path` 防路径穿越）。另有 `POST /api/upload-word`、`GET /api/download`（Word 模板下载）。

---

## 6. AI Agent 引擎详解（AIRAGAgent/）

### 6.1 Orchestrator（[orchestrator.py](AIRAGAgent/agent/orchestrator.py)）★

**结构化 Schema**（Pydantic）：
- `StepSpec`：`description` / `subagent`（空串=Orchestrator 直接回答）/ `depends_on: List[int]`
- `PlanSpec`：`goal` + `steps: List[StepSpec]`
- `Reflection`：`action`（accept/retry/revise/ask_user）+ `feedback`

**类** `Orchestrator`：
- 常量：`MAX_REVISIONS = 2`、`MAX_RETRIES = 1`
- `__init__`：触发 `register_all_subagents()`，持有 `SubAgentRegistry` 单例 + 默认 `chat_model`
- `_llm_for(user_id)`：用户自配模型优先，否则系统默认（`get_user_chat_model`）
- `_format_history`：最近 6 条、每条截 200 字
- `_get_subagent_menu`：生成 Planner 菜单，搜索关闭时排除 `search`
- 知识库路由：`_kb_hit_threshold()`（默认 0.5）、`_kb_accessible_ids()`（**直连 KB_DB**，见上）、`_kb_precheck()`、`_kb_route_hint()`（注入 Planner 命中提示）、`_kb_retrieve_context()`（直接回答路径注入引用内容）
- `_recall_relevant_memory()`：Qdrant 按 user_id 向量召回 top-k（不可用静默降级）
- **Planner**：`_plan()`（一次性）/ `_plan_stream()`（流式，yield `thinking` 事件推送 `reasoning_content`）。纯文本 JSON 输出 + `_extract_json` 解析（DeepSeek thinking 模式不支持 function calling）。失败回退单步直接回答
- **Executor**：`_execute_step()`（串行流式，subagent 空→LLM 直接答；非空→`SubAgentRunner.execute_stream`；注入 artifact ContextVar；结束 `_save_step_result` 落盘）/ `_execute_steps_parallel()`（ThreadPool 并行，`run_steps_parallel`）
- 交接机制：`_plan_dir()`（`workspace/{uid}/{date}/tasks/<plan_id>/`，codexec cwd）、`_plan_results_dir()`、`_save_step_result()`（写 `plan_results/step_<idx>.md`）、`_build_step_context()`（下游注入文件路径+200 字摘要）、`_promote_plan_outputs()`（完成清理中间产物）
- **Reflector**：`_reflect()`（子代理步才反思；失败步按重试次数 retry 否则 accept；LLM 纯文本 JSON 输出解析，失败默认 accept）/ `_revise_plan()`（`replace_plan_steps` 整体替换）
- **Finalizer**：`_finalize()`（单步无子代理直接复用 result；多步 LLM 整合流式输出；全失败给兜底文案）
- **主循环** `execute_stream(query, chat_history, user_id, session_id)`：规划→`while not plan.is_all_done()`（get_ready_steps→串行/并行执行+反思）→finalize→`_promote_plan_outputs`→`plan_completed`
- 单例：`get_orchestrator()`（模块级 `_orchestrator`）

**SSE 事件协议**（完整清单见 [orchestrator.py](AIRAGAgent/agent/orchestrator.py#L14-L28) 头部 docstring）：
`thinking` / `thinking_end` / `output` / `plan_created` / `step_started` / `step_thinking` / `step_output` / `step_completed` / `step_failed` / `plan_reflecting` / `plan_revised` / `plan_completed` / `ask_user`

### 6.2 Plan 数据模型与持久化（[plan.py](AIRAGAgent/agent/plan.py)）

- `PlanStatus`：planning / executing / reflecting / completed / failed / revised / cancelled
- `StepStatus`：pending / ready / running / completed / failed / skipped / blocked
- `PlanStep`（dataclass）：`step_idx` / `description` / `subagent` / `depends_on: List[int]` / `status` / `result` / `attempts` / `error_msg` / `started_at` / `finished_at`；`to_dict()` / `from_row()`
- `Plan`：`get_step()` / `get_ready_steps()`（依赖完成才 ready；依赖失败置 blocked）/ `is_all_done()` / `has_failure()`
- CRUD：`create_plan`（`plan_{毫秒}_{uuid6}`）/ `load_plan` / `update_step_status` / `replace_plan_steps`（修订整体替换）/ `update_plan_status` / `get_session_plan` / `list_user_plans`

### 6.3 SubAgent 体系（[sub_agent.py](AIRAGAgent/agent/sub_agent.py)）

- `SubAgent`（dataclass）：`name` / `description` / `tools` / `system_prompt` / `workflow_hint` / `max_tool_calls=20` / `category`（builtin/domain/memory/artifact/system）；`build_agent(llm)` 用 `create_agent` + 中间件链 `[ToolCallLimitMiddleware, skill_aware_monitor, log_before_model, smart_prompt_switch]`
- `SubAgentRunner`：`execute_stream()` 流式执行（`stream_mode="messages"`，注入 `active_skills=[name]`，产出 thinking/output 事件，兜底输出工具结果）；`execute()` 同步聚合 output
- `SubAgentRegistry`（单例）：`register` / `get` / `all` / `by_category` / `descriptions_for_planner` / `find_by_tool` / `get_all_tools`
- `run_steps_parallel(step_specs, chat_history, max_workers=5, llm)`：`contextvars.copy_context()` 父快照 + 每 worker `parent_ctx.copy()` 再 `run`，避免 "already entered"

### 6.4 内置 SubAgent 清单（[builtin.py](AIRAGAgent/agent/sub_agents/builtin.py)，`register_all_subagents()`）

| category | name | 能力 | 工具链 |
|----------|------|------|--------|
| domain | weather | 天气查询 | get_user_location → get_city_code → get_weather |
| domain | schedule | 课表/日程 | get_current_month → get_schedule |
| domain | report | 工作报告 | fill_context_for_report → fetch_external_data → create_artifact |
| domain | knowledge | 知识库检索 | rag_summarize |
| domain | document | Word 填充 | auto_fill_word |
| domain | search | 联网搜索 | search (Tavily) |
| builtin | codexec | 代码沙箱 | run_python_code / run_shell_command / install_package / list_packages |
| builtin | browser | 网页抓取 | fetch_url / fetch_url_rendered / extract_links / read_page_main_text / screenshot_url |
| memory | memory | 长期记忆 | remember / recall / recall_one / forget |
| artifact | artifact | 产物管理 | create_artifact / list_artifacts / get_artifact |

### 6.5 工具集（agent/tools/）

| 文件 | 关键函数 | 说明 |
|------|----------|------|
| `agent_tools.py` | `rag_summarize` / `get_weather` / `get_user_location` / `get_city_code` / `get_current_month` / `fetch_external_data` / `get_schedule` / `get_user_id` / `fill_context_for_report` | 领域工具 + ContextVar（`user_id_var`/`user_ip_var`/`user_lat_var`/`user_lon_var`/`search_enabled_var`） |
| `codexec_tools.py` | `run_python_code` / `run_shell_command` / `install_package` / `list_packages` | 沙箱；`_exec_cwd()` = `workspace/{uid}/{date}/tasks/<plan_id>/`；`_scan_python_dangers` AST 检查；黑名单命令；`_clamp_timeout`（上限 `CODE_TIMEOUT_MAX`）；输出截断 5000 字；PyPI 清华镜像 |
| `browser_tools.py` | `fetch_url` / `fetch_url_rendered` / `extract_links` / `read_page_main_text` / `screenshot_url` | 完整 Chrome 头 + Session Cookie + 随机延迟 1-3s + 自动重试；`_launch_stealth_browser` Playwright stealth（抹 webdriver/伪装 UA）；403 自动回退 |
| `file_tools.py` | `auto_fill_word` | Word `{标签}` 占位符填充（字体/字号/加粗/批注/表格） |
| `wordgen_tools.py` + `wordgen_helper.py` | `run_word_code` / `WordDoc` | 生成 Word 文档（样式、表格、页脚页码） |
| `memory_tools.py` | `remember` / `recall` / `recall_one` / `forget` | 长期记忆 KV 工具 |
| `artifact_tools.py` | `create_artifact` / `list_artifacts` / `get_artifact` | 产物落盘 + DB 记录；`current_plan_id_var`/`current_session_id_var`/`current_step_idx_var` ContextVar 关联 |
| `search_tools.py` | `search(content)` | Tavily |
| `middleware.py` | `skill_aware_monitor` / `log_before_model` / `smart_prompt_switch` / `monitor_tool` | LangChain 中间件（工具监控埋点、模型调用日志、按上下文切提示词） |
| `sandbox_config.py` | `check_path_permission` / `is_desktop_available` | 沙箱路径权限（读/写白名单）、桌面 GUI 可用性 |

### 6.6 长期记忆（agent/memory/）

- `extractor.py`：`extract_and_save()` / `extract_memories_async()` —— 对话完成后异步抽取事实/偏好/项目记忆，LLM 结构化抽取 + 0.92 去重阈值
- `vector_store.py`：`memory_store`（Qdrant，按 user_id 过滤，`search_memories`）
- `migrate_legacy.py`：旧 KV 记忆迁移

### 6.7 知识库 RAG（kb/ + rag/）

- `kb/service.py`：`seed_default_kb()`、`create_kb`/`list_kbs`/`update_kb`/`delete_kb`、`upload_document`/`index_document`（后台线程分块+嵌入+元数据）、`delete_document`/`replace_document`/`rebuild_kb`、`preview_chunks`、`search_with_scores`（带分数检索）、`embedding_status`。Chroma 集合 `kb_store`，按 `kb_id/doc_id` 元数据隔离；Chroma 与嵌入模型懒加载
- `kb/models.py`：`knowledge_bases`（scope=global/personal、biz_line、is_default 保护、owner_user_id、is_enabled）+ `kb_documents`（filename/md5/version/status=pending|processing|ready|failed/chunk_count）
- `rag/vector_store.py`：Chroma 初始化、`RecursiveCharacterTextSplitter` 分块、PDF/TXT/Excel 多格式加载、MD5 增量
- `rag/rag_service.py`：检索→拼接→LLM 总结；按用户解析可访问库，缓存键含用户与库签名
- `kb/embedding.py`：Ollama HTTP 直连嵌入（兼容 DashScope）

### 6.8 模型工厂（model/factory.py）

- `ChatModelFactory`（DeepSeek/通义千问，`request_timeout=240, max_retries=1`）、`EmbeddingsFactory`（DashScope）；导出单例 `chat_model` / `embed_model`；`get_user_chat_model(user_id)` 解析用户自配模型

### 6.9 基础设施（infrastructure/）

- `redis_client.py`：连接池
- `session_cache.py`：会话消息 Redis 缓存（键含用户+会话）
- `rag_cache.py`：RAG 检索缓存（用户与库签名失效）
- `rate_limiter.py`：`get_chat_rate_limiter()`（Redis 计数，窗口+配额）
- `task_queue.py`：`enqueue_task(TaskType.PLAN_EXECUTE, params)` / `register_default_handlers()` / `get_task_status(task_id)`（后台长任务执行）

### 6.10 数据库层（database/）

- `connection.py`：`get_db()`（pymysql 上下文管理器）、`init_db()` 建 **14 张表**：conversations / messages / users / login_devices / message_feedback / knowledge_bases / kb_documents / api_call_logs / tool_call_logs / rate_limit_events / plans / plan_steps / user_memories / artifacts；`mysql_conf` 字典运行时可被 patch 重定向（chat_service `db_patch` 指向 lc_chat、kb_service 指向 lc_kb）
- `models.py`：会话/消息/用户/记忆/产物/统计等全部 CRUD（100+ 函数，见 [models.py](AIRAGAgent/database/models.py)）

---

## 7. 前端架构（frontend/）

**入口**：`src/main.js`（createApp + router + `initTheme()`）；路由 `src/router/index.js` 6 条（/login、/、/admin、/admin/kb、/kb、/settings），`beforeEach` 守卫调 `/api/auth/me` 校验 token（`verifyToken` 单次缓存，401 自动 logout）。

**API 层**（`src/api/`）：
- `auth.js`：token 存取、登录/注册/me、logout、getUser
- `chat.js`：**核心 `sendChatMessage()`** —— fetch + `response.body.getReader()` 流式解析 SSE（`data: {json}` 与 `[DONE]`），分发 `onThinking/onOutput/onThinkingEnd/onDone/onMessageIds/onEvent` 回调；`onEvent` 透传 `plan_*`/`step_*` DeepAgent 事件；还提供会话 CRUD / search / branch / feedback / plans / plan detail / uploadWordFile
- `kb.js` / `file.js`：知识库与文件 API（file.js 带 token）

**状态管理**（`src/composables/useChat.js`）：消息列表、会话切换、流式状态（thinking/output 分离）、思考过程、历史加载/保存/删除、会话搜索/分叉；**防丢失**：push userMsg 后立即 fire-and-forget `saveConversationApi`。

**组件**：
- `ChatView.vue`：主视图，挂载 MessageBubble / ChatInput / WelcomeScreen / SideDrawer / PlanPanel / FileBrowser / TaskQueue
- `MessageBubble.vue`：markdown-it 渲染（50ms 流式节流，`src/utils/markdown.js`）
- `PlanPanel.vue`：计划执行可观测面板（step 状态/思考/反思）
- `PlanHistory.vue` / `AgentCapabilities.vue`：计划历史 + Agent 能力抽屉（按需加载 step 明细）
- `kb/KbManager.vue`：知识库管理（拖拽批量上传、文档表格、分块预览、检索测试 playground）；`SettingsPanel.vue` / `FileBrowser.vue` 均用 `defineAsyncComponent` 懒加载
- `TaskQueue.vue`：任务清单（编辑式栏注风格）
- `SideDrawer.vue`：侧边抽屉容器；`LineChart.vue`/`StackedAreaChart.vue`：admin 图表
- `views/AdminView.vue` / `AdminKbView.vue` / `UserKbView.vue` / `SettingsView.vue` / `Login.vue`

**构建**（`vite.config.js`）：未设 `VITE_API_TARGET` 时按 URL 前缀代理到 8001-8006（`microserviceProxy()` 表）；`@` 别名；`manualChunks` 拆 `vue-vendor`；产物 `dist/`。

---

## 8. 数据库 Schema（汇总）

| 库 | 主要表 | 归属服务 |
|----|--------|----------|
| lc_auth | users / security_questions / login_devices | auth_service |
| lc_user | user_profiles / schedules / user_model_settings 等 | user_service |
| lc_chat | conversations / messages / message_feedback / plans / plan_steps / api_call_logs / tool_call_logs / rate_limit_events / user_memories / artifacts | chat_service（AIRAGAgent 重定向） |
| lc_kb | knowledge_bases / kb_documents | kb_service |
| lc_admin | api_call_logs / tool_call_logs / rate_limit_events / dashboard 聚合 | admin_service |

**关键表字段**：
- `plans`：id(`plan_{ts}_{uuid6}`) / user_id / session_id / goal / status / final_answer / created_at / updated_at
- `plan_steps`：plan_id / step_idx / description / subagent / depends_on(逗号串) / status / result / attempts / error_msg / started_at / finished_at
- `conversations`：id / user_id / title / pinned / starred / folder / messages(JSON) / created_at / updated_at
- `messages`：id / conversation_id / user_id / role / content / created_at
- `user_memories`：id / user_id / memory_type / key_name / value / active / created_at（长期记忆 KV）
- `artifacts`：id / user_id / session_id / plan_id / art_type / title / content / file_path / version（产物）
- `knowledge_bases`：id / name / scope(global|personal) / biz_line / is_default / is_enabled / owner_user_id / created_by
- `kb_documents`：id / kb_id / filename / md5 / file_path / version / status / chunk_count

---

## 9. 依赖关系

### 9.1 服务依赖图

```
                       ┌──────────────┐
 前端 ──→ Nginx ──→    │ 各微服务      │
                       └──────────────┘
auth_service  ←──HTTP+JWT── admin_service（取用户列表/删用户/重置密码）
user_service  ←──HTTP+JWT── admin_service（档案/注销）
chat_service  ←──HTTP+JWT── admin_service（查看用户会话）
chat_service  ──→ AIRAGAgent 引擎（进程内）──→ user_service（USER_SERVICE_URL，档案/课表）
chat_service  ──→ kb_service（_kb_accessible_ids 直连 lc_kb 库查知识库；/internal/kb/search）
chat_service  ──Redis Pub/Sub──→ admin_service（chat.completed / tool.called / rate.limited）
auth_service  ──→ user_service（注册时建档案 ensure_profile）
file_service  独立（文件系统）；kb_service 独立（lc_kb + ChromaDB）
```

### 9.2 服务间调用目标（core/config.py `get_service_url`）

各服务只声明**自己依赖**的目标：
- auth_service → user_service（`USER_SERVICE_URL` 或 `INTERNAL_HOST`+`USER_PORT`）
- user_service → auth_service、chat_service（注销级联）
- admin_service → auth_service、user_service、chat_service
- chat_service → user_service（AIRAGAgent 引擎经 `USER_SERVICE_URL` 直连）
- kb_service → 无 HTTP 依赖

### 9.3 关键代码依赖（模块 → 被依赖模块）

```
chat_service/main.py ──→ agent.py ──→ db_patch.py（先重定向 DB）→ AIRAGAgent.*
AIRAGAgent/agent/orchestrator.py ──→ plan.py / sub_agent.py / model.factory / utils.paths / agent.tools.artifact_tools / agent.tools.agent_tools
AIRAGAgent/agent/sub_agent.py ──→ model.factory / utils.prompt_loader / agent.tools.middleware
AIRAGAgent/agent/tools/* ──→ database（会话/记忆/产物 CRUD）/ infrastructure（缓存/限流）/ kb（RAG）
kb_service/main.py ──→ AIRAGAgent.kb.service / AIRAGAgent.rag / model.factory（嵌入）
admin_service/main.py ──→ core.events（Redis 订阅）/ models（统计 CRUD）
前端 chat.js ──→ auth.js（token）；ChatView ──→ useChat ──→ chat.js
```

### 9.4 三方依赖（pyproject.toml 关键项）

`langchain>=1.2` + `langchain-deepseek` + `langchain-chroma` + `langchain-tavily` + `langgraph` / `chromadb` / `qdrant-client` / `fastapi`+`uvicorn` / `pymysql` / `PyJWT` / `redis[hiredis]` / `python-docx`+`openpyxl` / `playwright==1.61` / `httpx` / `paramiko`（部署）/ `pandas`+`numpy`（分析）。前端：`vue` / `vue-router` / `markdown-it` / `vue-virtual-scroller`。

---

## 10. 关键流程时序

### 10.1 一次聊天请求（SSE）

```
前端 sendChatMessage ──POST /api/chat──→ chat_service
  → get_current_user 解码 JWT → 限流检查 → ContextVar 注入
  → StreamingResponse(generate_sse_stream) → AgentService.stream_response
    → executor 线程 run Orchestrator.execute_stream
      → Planner 流式 thinking → plan_created → Executor（step_* 事件）→ Reflector → Finalizer → plan_completed
  → 落库 user/assistant 消息 → message_ids 事件 → [DONE]
  → log_api_call + publish chat.completed → admin_service 订阅落库
  → 异步 extract_memories_async（长期记忆抽取）
```

### 10.2 跨步骤数据交接

```
step_i 完成 → _save_step_result 写 workspace/{uid}/{date}/tasks/<plan_id>/plan_results/step_i.md
下游 step_j 执行 → _build_step_context 在 task_desc 注入前序文件相对路径 + 200 字摘要
codexec 子进程 cwd = tasks/<plan_id>/，可直接 open("plan_results/step_i.md")
计划完成 → _promote_plan_outputs：删 plan_results、最终文件提升到当天工作区根目录
```

### 10.3 反射修订

```
_execute_step 完成 → _reflect（仅 subagent 步）→
  accept：继续
  retry(≤1)：重跑本步带反馈
  revise(≤2)：_revise_plan → 重新 Planner → replace_plan_steps 整体替换 → 回到执行循环
  ask_user：发 ask_user 事件，plan 置 completed(final_answer=需补充)
```

---

## 11. 项目运行方式

### 11.1 前置依赖

Python ≥ 3.13、Node.js ≥ 18、MySQL 8、Redis 7；可选 Ollama（本地嵌入 `nomic-embed-text`）、DashScope/DeepSeek/Tavily/高德 API Key。

### 11.2 后端配置

```powershell
Copy-Item deploy\backend\.env.example deploy\backend\.env
# 编辑 .env：MYSQL_PASSWORD / JWT_SECRET_KEY / DEEPSEEK_API_KEY / EMBEDDING_API_KEY / USER_SERVICE_URL 等
```

关键环境变量（各服务 `core/config.py` 读取）：
- 通用：`PORT`(或 `*_PORT`)、`DB_NAME`(或 `*_DB`)、`MYSQL_HOST/PORT/USER/PASSWORD`、`REDIS_*`、`JWT_SECRET_KEY`（**所有服务必须一致**）、`JWT_TOKEN_EXPIRE_HOURS`、`INTERNAL_HOST`、`LOG_DIR`/`UPLOAD_DIR`/`WORKSPACE_DIR`
- 跨服务：`*_SERVICE_URL`（显式覆盖，如 `USER_SERVICE_URL`）或 `INTERNAL_HOST`+`*_PORT` 推导
- 管理后台：`ADMIN_ALLOWED_IPS`（IP 白名单，逗号分隔）
- 引擎：`DEEPSEEK_API_KEY`、`EMBEDDING_API_KEY`（DashScope）、`TAVILY_API_KEY`、`GAODE_API_KEY`、`KB_DB`/`KB_DATABASE`（默认 lc_kb）、`AGENT_HOME`（AIRAGAgent 根）

### 11.3 本地启动

```powershell
# 安装依赖
uv sync                                    # 后端（清华镜像）
cd frontend; npm install; cd ..            # 前端

# 方式 A：服务自带脚本（独立目录模式）
cd services\auth_service ; .\start.bat     # 逐个启动
# ... user/chat/kb/admin/file 同理；chat/kb 需 PYTHONPATH 指向项目根

# 方式 B：前端 dev server（内置微服务直连代理，无需 nginx）
cd frontend; npm run dev                   # http://localhost:5173
```

> 注意：`start_microservices.bat` 为 UTF-8 编码，cmd 按 GBK 解析会乱码导致失败；本地建议用 PowerShell 加载 `deploy/backend/.env` 后逐个 `Start-Process` 启动 uvicorn（详见 project_memory 经验）。

### 11.4 验证

```powershell
foreach ($p in 8001..8006) { Invoke-RestMethod "http://localhost:$p/api/health" }
# 期望 {"status":"ok","service":"...","redis":"connected"}
```

### 11.5 生产部署（81.70.100.57）

- 后端：`python deploy/deploy_to_server.py`（paramiko SFTP 上传 + systemd 重启）；或 `deploy/incremental_upload.py`（增量）
- 前端：`cd frontend; npm run build` 产物 → 上传覆盖 `/var/www/lc-course-frontend/`
- systemd 必须独立目录模式：`WorkingDirectory=services/<svc>` + `ExecStart=...uvicorn main:app --app-dir ...`；chat/kb 需 `Environment=PYTHONPATH=项目根` + `AGENT_HOME`
- nginx：`deploy/frontend/nginx.conf`（gzip/brotli、`dist/assets/*` immutable 缓存、`index.html` no-cache、按前缀代理微服务）；Docker 版见 `deploy/docker/nginx.conf` + `microservice_proxy.conf`

### 11.6 Docker（可选）

`docker-compose.yml` 编排 MySQL/Redis/Qdrant；`deploy/qdrant/` 为 Qdrant 独立容器配置；`deploy/docker/init-db.sql` 初始化；`.env.docker.example` 模板。

---

## 12. 测试体系（tests/）

- 框架：pytest（`addopts = "-p no:langsmith"` 规避插件冲突）
- 目录：`tests/{auth_service,user_service,chat_service,kb_service,admin_service,file_service,agent_core}/`，各服务独立 `conftest.py`
- 隔离：独立测试库（如 `lc_auth_test`），session 自动建表、每测自动清理
- 运行：
  ```powershell
  pytest tests/ -v
  pytest tests/chat_service/ -v
  pytest --cov --cov-report=term-missing tests/
  ```

---

## 13. 常见改动入口速查（Developer Cheat Sheet）

| 想改什么 | 改哪里 |
|----------|--------|
| 编排主循环 / 反思策略 / 交接机制 | [orchestrator.py](AIRAGAgent/agent/orchestrator.py) |
| 新增/调整 SubAgent | [builtin.py](AIRAGAgent/agent/sub_agents/builtin.py) + [sub_agent.py](AIRAGAgent/agent/sub_agent.py) |
| 新增工具 | `AIRAGAgent/agent/tools/` 新文件 + 挂到 builtin.py 某 SubAgent |
| 聊天 SSE 路由 / 会话接口 | [services/chat_service/main.py](services/chat_service/main.py) |
| 流式持久化 / 埋点 | [services/chat_service/agent.py](services/chat_service/agent.py) |
| 知识库接口 / 文档索引 | [services/kb_service/main.py](services/kb_service/main.py) + [kb/service.py](AIRAGAgent/kb/service.py) |
| 统计看板 / 事件聚合 | [services/admin_service/main.py](services/admin_service/main.py) + [models.py](services/admin_service/models.py) |
| 认证 / 设备管理 | [services/auth_service/main.py](services/auth_service/main.py) |
| 前端流式聊天 | `frontend/src/composables/useChat.js` + `api/chat.js` |
| 计划面板 / 历史 | `frontend/src/components/PlanPanel.vue` / `PlanHistory.vue` |
| 环境变量 | `deploy/backend/.env`（本地）+ 服务器 `/opt/lc-course/backend/services/*/.env` |

---

*文档维护提示：本文档与代码保持同步更新；新增表/路由/工具时请同步更新 §5、§6、§8、§13。*
