"""聊天 / Agent 微服务（DeepAgent 架构）。

职责：
- POST /api/chat 流式聊天（SSE，产出 plan_* / step_* / thinking / output 事件）
- POST /api/plan DeepAgent plan 执行（流式 / 后台两种模式）
- GET  /api/plans plan 列表 / 详情查询
- 会话管理（列表 / 保存 / 删除 / 元数据 / 搜索 / 分叉）
- 消息反馈（点赞 / 踩）
- 异步任务状态查询

独立数据库：lc_chat
- conversations, messages, message_feedback
- api_call_logs, tool_call_logs
- plans, plan_steps, user_memories, artifacts（DeepAgent 新增）

设计要点：
- 复用 AIRAGAgent.agent.Orchestrator（Planner/Executor/Reflector/Finalizer）+ SubAgent 体系
- 启动时把 AIRAGAgent.database 重定向到 lc_chat
- log_rate_limit_event 改为发布 Redis 事件（rate_limit_events 表在 lc_admin）
- log_api_call / log_tool_call 写入 lc_chat + 发布 Redis 事件供 admin_service 聚合
- task_queue 支持 PLAN_EXECUTE 类型，plan 可后台异步执行
"""
