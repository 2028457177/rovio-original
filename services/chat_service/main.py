"""chat_service FastAPI 入口。

路由：
- POST /api/chat                      流式聊天（SSE）
- GET  /api/conversations             会话列表
- POST /api/conversations             保存会话
- DELETE /api/conversations/{id}     删除会话
- PATCH /api/conversations/{id}/meta 更新元数据
- GET  /api/conversations/search      全文搜索
- POST /api/conversations/{id}/branch 会话分叉
- POST /api/feedback                  消息反馈
- GET  /api/tasks/{task_id}           任务状态
- 内部 /internal/chat/users/{id}/conversations  供 admin_service 调用
"""
from __future__ import annotations
import asyncio
import json
import os
import uuid
from typing import List, Optional

from fastapi import Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from datetime import datetime

from core import (
    create_app, get_current_user, get_client_ip, logger,
    publish_event,
)
from core.events import CHANNEL_RATE_LIMITED
from core.paths import UPLOAD_DIR

# DB 重定向在 agent.py 中完成（import 时副作用）
import agent
from AIRAGAgent.infrastructure.rate_limiter import get_chat_rate_limiter
from AIRAGAgent.infrastructure.task_queue import register_default_handlers
from AIRAGAgent.agent.tools.agent_tools import (
    user_ip_var, user_lat_var, user_lon_var, user_id_var, search_enabled_var,
)


async def _on_startup():
    """启动：建表 + 注册任务队列处理器 + 清理过期工作目录"""
    from AIRAGAgent.database.connection import init_db
    await asyncio.get_event_loop().run_in_executor(None, init_db)
    logger.info("[chat_service] 数据库表已就绪")
    await asyncio.get_event_loop().run_in_executor(None, register_default_handlers)
    logger.info("[chat_service] 任务队列处理器已注册")
    # 清理超过 30 天的日期子目录（workspace/YYYYMMDD/）
    from AIRAGAgent.utils.paths import cleanup_old_daily_workspaces
    removed = await asyncio.get_event_loop().run_in_executor(None, cleanup_old_daily_workspaces)
    logger.info(f"[chat_service] 过期工作目录清理完成，删除 {removed} 个")


app = create_app("chat_service", version="1.0.0", on_startup=_on_startup)

agent_service = agent.AgentService()


# ==================== 请求体 ====================

class ChatRequest(BaseModel):
    message: str
    session_id: str = None
    stream: bool = True
    latitude: float | None = None
    longitude: float | None = None
    uploaded_file_path: str | None = None
    truncate_to: int | None = None
    # 联网搜索开关：关闭后 Planner 不会选择 search 子代理
    search_enabled: bool = True


class ConversationSaveRequest(BaseModel):
    id: str
    title: str
    messages: List[dict]
    time: str = ""


class ConversationMetaRequest(BaseModel):
    title: Optional[str] = None
    pinned: Optional[int] = None
    starred: Optional[int] = None
    folder: Optional[str] = None


class BranchRequest(BaseModel):
    branch_from_message_id: int


class FeedbackRequest(BaseModel):
    conversation_id: str
    message_id: Optional[int] = None
    message_role: str = "assistant"
    message_content: str = ""
    feedback: str


class PlanRequest(BaseModel):
    """DeepAgent plan 执行请求。

    mode:
        stream     - 流式同步执行（默认，与 /api/chat 一致，但语义上明确为 plan 模式）
        background - 后台异步执行，立即返回 task_id，用户通过 /api/tasks/{task_id} 查询
    """
    message: str
    session_id: str = None
    mode: str = "stream"
    latitude: float | None = None
    longitude: float | None = None
    # 联网搜索开关：关闭后 Planner 不会选择 search 子代理
    search_enabled: bool = True


# ==================== 聊天 ====================

async def generate_sse_stream(user_id: int, message: str, session_id: str = None, truncate_to: int = None):
    """将 Agent 的流式响应逐块转换为 SSE 事件输出，结束时发送 [DONE] 标记。"""
    async for chunk in agent_service.stream_response(user_id, message, session_id, truncate_to=truncate_to):
        if isinstance(chunk, dict):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        else:
            content = chunk.strip()
            if content:
                yield f"data: {json.dumps({'type': 'output', 'content': content}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/api/chat")
async def chat(chat_req: ChatRequest, req: Request, user: dict = Depends(get_current_user)):
    """处理 /api/chat 聊天请求：限流校验、注入上下文，返回流式(SSE)或非流式回复。"""
    client_ip = (
        req.headers.get("X-Real-IP")
        or (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        or (req.client.host if req.client else None)
        or "unknown"
    )
    user_id = user["id"]
    user_ip_var.set(client_ip)
    user_lat_var.set(chat_req.latitude)
    user_lon_var.set(chat_req.longitude)
    user_id_var.set(user_id)
    search_enabled_var.set(chat_req.search_enabled)

    limiter = get_chat_rate_limiter()
    allowed, remaining = limiter.is_allowed(client_ip)
    if not allowed:
        # 限流事件：发布 Redis 事件（admin_service 订阅落库）
        try:
            publish_event(CHANNEL_RATE_LIMITED, {
                "user_id": user_id,
                "ip": client_ip,
                "limit_type": "chat",
                "identifier": client_ip,
            })
        except Exception:
            pass
        return JSONResponse(
            status_code=429,
            content={"error": "请求过于频繁，请稍后再试",
                     "detail": f"每 {limiter.window_seconds} 秒最多 {limiter.max_requests} 次请求"},
        )

    enhanced_message = chat_req.message
    if chat_req.uploaded_file_path:
        enhanced_message = (
            f"[用户已上传Word文件，服务器路径为：{chat_req.uploaded_file_path}] "
            f"{chat_req.message}"
        )

    if chat_req.stream:
        return StreamingResponse(
            generate_sse_stream(user_id, enhanced_message, chat_req.session_id, truncate_to=chat_req.truncate_to),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-RateLimit-Limit": str(limiter.max_requests),
                "X-RateLimit-Remaining": str(remaining),
            },
        )

    # 非流式
    response_chunks = []
    async for chunk in agent_service.stream_response(user_id, enhanced_message, chat_req.session_id, truncate_to=chat_req.truncate_to):
        if isinstance(chunk, dict):
            if chunk["type"] == "output":
                response_chunks.append(chunk["content"])
        else:
            content = chunk.strip()
            if content:
                response_chunks.append(content)

    return JSONResponse(content={
        "content": "".join(response_chunks),
        "session_id": chat_req.session_id,
    })


# ==================== 会话管理 ====================

@app.get("/api/conversations")
async def get_conversations(user: dict = Depends(get_current_user)):
    """获取当前用户的会话列表并返回。"""
    from AIRAGAgent.database import get_conversations as db_get_conversations
    conversations = await asyncio.get_event_loop().run_in_executor(None, db_get_conversations, user["id"])
    return JSONResponse(content={"conversations": conversations})


@app.post("/api/conversations")
async def save_conversation(request: ConversationSaveRequest, user: dict = Depends(get_current_user)):
    """保存/覆盖一个会话（标题与消息列表），落库后返回 ok。"""
    from AIRAGAgent.database import save_conversation_full as db_save

    def _save():
        """在线程池里同步执行会话保存，避免阻塞事件循环。"""
        db_save(user["id"], request.id, request.title, request.messages)
    await asyncio.get_event_loop().run_in_executor(None, _save)
    return JSONResponse(content={"status": "ok"})


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    """软删除当前用户的指定会话。"""
    from AIRAGAgent.database import delete_conversation as db_delete
    await asyncio.get_event_loop().run_in_executor(None, db_delete, user["id"], conversation_id)
    return JSONResponse(content={"status": "ok"})


@app.patch("/api/conversations/{conversation_id}/meta")
async def update_conversation_meta(conversation_id: str, req: ConversationMetaRequest,
                                   user: dict = Depends(get_current_user)):
    """更新会话的元信息（标题等非空字段），返回更新是否成功。"""
    from AIRAGAgent.database import update_conversation_meta as db_update_meta
    meta = {k: v for k, v in req.dict().items() if v is not None}
    if not meta:
        return JSONResponse(status_code=400, content={"error": "无可更新字段"})
    success = await asyncio.get_event_loop().run_in_executor(
        None, db_update_meta, user["id"], conversation_id, meta
    )
    if not success:
        return JSONResponse(status_code=404, content={"error": "会话不存在"})
    return JSONResponse(content={"status": "ok"})


@app.get("/api/conversations/search")
async def search_conversations(q: str, user: dict = Depends(get_current_user)):
    """按关键词全文搜索当前用户的会话并返回结果列表。"""
    from AIRAGAgent.database import search_conversations as db_search
    keyword = (q or "").strip()
    if not keyword:
        return JSONResponse(content={"conversations": []})
    if len(keyword) > 100:
        return JSONResponse(status_code=400, content={"error": "搜索关键词过长"})
    result = await asyncio.get_event_loop().run_in_executor(None, db_search, user["id"], keyword)
    return JSONResponse(content={"conversations": result})


@app.post("/api/conversations/{conversation_id}/branch")
async def branch_conversation(conversation_id: str, req: BranchRequest,
                              user: dict = Depends(get_current_user)):
    """从指定消息处分叉出新会话，返回新会话信息。"""
    from AIRAGAgent.database import branch_conversation as db_branch
    if req.branch_from_message_id <= 0:
        return JSONResponse(status_code=400, content={"error": "branch_from_message_id 非法"})
    result = await asyncio.get_event_loop().run_in_executor(
        None, db_branch, user["id"], conversation_id, req.branch_from_message_id
    )
    if not result:
        return JSONResponse(status_code=404, content={"error": "会话不存在或无消息可分叉"})
    return JSONResponse(content=result)


# ==================== 消息反馈 ====================

@app.post("/api/feedback")
async def save_feedback(req: FeedbackRequest, user: dict = Depends(get_current_user)):
    """保存用户对某条消息的点赞/点踩反馈。"""
    from AIRAGAgent.database import save_message_feedback as db_save_feedback
    if req.feedback not in ("like", "dislike", ""):
        return JSONResponse(status_code=400, content={"error": "feedback 取值非法"})
    await asyncio.get_event_loop().run_in_executor(
        None, db_save_feedback,
        user["id"], req.conversation_id, req.message_role,
        req.message_content, req.feedback, req.message_id
    )
    return JSONResponse(content={"status": "ok"})


# ==================== DeepAgent Plan 接口 ====================

@app.post("/api/plan")
async def plan(plan_req: PlanRequest, req: Request, user: dict = Depends(get_current_user)):
    """DeepAgent plan 执行入口。

    - mode=stream（默认）：流式 SSE，产出 plan_created / step_started / step_output / plan_completed 等事件
    - mode=background：投递到 task_queue 后台执行，立即返回 task_id
    """
    client_ip = (
        req.headers.get("X-Real-IP")
        or (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        or (req.client.host if req.client else None)
        or "unknown"
    )
    user_id = user["id"]
    user_ip_var.set(client_ip)
    user_lat_var.set(plan_req.latitude)
    user_lon_var.set(plan_req.longitude)
    user_id_var.set(user_id)
    search_enabled_var.set(plan_req.search_enabled)

    if plan_req.mode == "background":
        task_id = agent_service.enqueue_plan_background(user_id, plan_req.message, plan_req.session_id,
                                                        search_enabled=plan_req.search_enabled)
        if task_id is None:
            return JSONResponse(status_code=503, content={"error": "Redis 不可用，无法投递后台任务"})
        return JSONResponse(content={"task_id": task_id, "status": "pending"})

    # 流式模式：复用 generate_sse_stream
    return StreamingResponse(
        generate_sse_stream(user_id, plan_req.message, plan_req.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/plans")
async def list_plans(user: dict = Depends(get_current_user)):
    """列出当前用户的 plan（按更新时间倒序）"""
    from AIRAGAgent.agent.plan import list_user_plans as db_list_plans
    plans = await asyncio.get_event_loop().run_in_executor(None, db_list_plans, user["id"])
    return JSONResponse(content={"plans": plans})


@app.get("/api/plans/{plan_id}")
async def get_plan_detail(plan_id: str, user: dict = Depends(get_current_user)):
    """查询 plan 详情（含所有 step 状态、结果）"""
    from AIRAGAgent.agent.plan import load_plan as db_load_plan
    plan = await asyncio.get_event_loop().run_in_executor(None, db_load_plan, plan_id)
    if plan is None:
        return JSONResponse(status_code=404, content={"error": "plan 不存在"})
    if plan.user_id != user["id"]:
        return JSONResponse(status_code=403, content={"error": "无权访问该 plan"})
    return JSONResponse(content={"plan": plan.to_dict()})


# ==================== 任务状态 ====================

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """查询后台任务（task_id）的执行状态并返回。"""
    from AIRAGAgent.infrastructure.task_queue import get_task_status as queue_get_status
    result = await asyncio.get_event_loop().run_in_executor(None, queue_get_status, task_id)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "任务未找到"})
    return JSONResponse(content=result)


# ==================== 内部接口（供 admin_service 调用） ====================

@app.get("/internal/chat/users/{user_id}/conversations")
async def internal_get_user_conversations(user_id: int):
    """供 admin_service 查看任意用户的会话列表"""
    from AIRAGAgent.database import get_user_conversations_admin as db_get_user_conv
    conversations = await asyncio.get_event_loop().run_in_executor(None, db_get_user_conv, user_id)
    return JSONResponse(content={"conversations": conversations})


@app.delete("/internal/chat/users/{user_id}/cleanup")
async def internal_cleanup_user_data(user_id: int):
    """供 user_service 注销账号时调用：清理该用户的会话 + 消息 + 反馈"""
    from AIRAGAgent.database import delete_user_admin as _db_delete
    # delete_user_admin 会删 messages + conversations，但它也尝试删 users 表
    # 这里不能调它（users 表在 auth_service）。手动删 chat 相关表。
    try:
        from core.db import get_db
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE m FROM messages m JOIN conversations c ON m.conversation_id = c.id WHERE c.user_id = %s",
                (user_id,)
            )
            cur.execute("DELETE FROM conversations WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM message_feedback WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM api_call_logs WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM tool_call_logs WHERE user_id = %s", (user_id,))
            conn.commit()
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        logger.error(f"[chat] 清理用户 {user_id} 数据失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn
    from core.config import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
