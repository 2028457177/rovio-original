"""admin_service FastAPI 入口。

路由（管理员，均经 get_admin_user 鉴权）：
- GET  /api/admin/users                          用户列表（auth + user 资料合并）
- GET  /api/admin/users/{user_id}/conversations  查看某用户会话（调 chat_service）
- POST /api/admin/users/{user_id}/delete         注销用户（调 user_service 级联清理）
- POST /api/admin/users/{user_id}/reset-password 重置密码（调 auth_service）
- GET  /api/admin/stats/overview                 看板概览
- GET  /api/admin/stats/trends?days=30           趋势图
- GET  /api/admin/stats/tools?days=30            工具分布 + 错误率
- GET  /api/admin/stats/top?days=30&limit=10     Top 用户 + Top 提问

跨服务调用时透传当前请求的 JWT token，被调服务自行验证身份。
"""
from __future__ import annotations

import asyncio
import threading
from decimal import Decimal
from datetime import date, datetime

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import (
    create_app, get_admin_user, call_service, logger,
)
from core.events import (
    subscribe_events, CHANNEL_CHAT_COMPLETED, CHANNEL_TOOL_CALLED, CHANNEL_RATE_LIMITED,
)
import models

# 事件订阅停止信号（lifespan 关闭时 set）
stop_event = threading.Event()


def _json_safe(obj):
    """递归把 Decimal / date / datetime 等 JSON 不可序列化类型转为可序列化类型。"""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


# ==================== 事件落库回调 ====================

def on_chat_completed(payload: dict) -> None:
    """chat.completed 事件 → 写入 api_call_logs"""
    try:
        models.log_api_call(
            user_id=payload.get("user_id", 0),
            session_id=payload.get("session_id", ""),
            ip=payload.get("ip", ""),
            endpoint=payload.get("endpoint", "chat"),
            duration_ms=payload.get("duration_ms", 0),
            prompt_tokens=payload.get("prompt_tokens", 0),
            completion_tokens=payload.get("completion_tokens", 0),
            is_success=payload.get("is_success", True),
            error_msg=payload.get("error_msg", ""),
        )
    except Exception as e:
        logger.error(f"[admin] 落库 chat.completed 事件失败: {e}")


def on_tool_called(payload: dict) -> None:
    """tool.called 事件 → 写入 tool_call_logs"""
    try:
        models.log_tool_call(
            user_id=payload.get("user_id", 0),
            session_id=payload.get("session_id", ""),
            tool_name=payload.get("tool_name", ""),
            duration_ms=payload.get("duration_ms", 0),
            is_success=payload.get("is_success", True),
            error_msg=payload.get("error_msg", ""),
        )
    except Exception as e:
        logger.error(f"[admin] 落库 tool.called 事件失败: {e}")


def on_rate_limited(payload: dict) -> None:
    """rate.limited 事件 → 写入 rate_limit_events"""
    try:
        models.log_rate_limit_event(
            user_id=payload.get("user_id", 0),
            ip=payload.get("ip", ""),
            limit_type=payload.get("limit_type", "chat"),
            identifier=payload.get("identifier", ""),
        )
    except Exception as e:
        logger.error(f"[admin] 落库 rate.limited 事件失败: {e}")


async def on_startup() -> None:
    """服务启动时订阅三个事件频道（chat 完成/工具调用/限流）。"""
    stop_event.clear()
    subscribe_events(CHANNEL_CHAT_COMPLETED, on_chat_completed, stop_event)
    subscribe_events(CHANNEL_TOOL_CALLED, on_tool_called, stop_event)
    subscribe_events(CHANNEL_RATE_LIMITED, on_rate_limited, stop_event)
    logger.info("[admin] 事件订阅已注册")


async def on_shutdown() -> None:
    """服务关闭时通知事件订阅循环退出。"""
    stop_event.set()
    logger.info("[admin] 已请求停止事件订阅")


app = create_app("admin_service", version="1.0.0",
                 on_startup=on_startup, on_shutdown=on_shutdown)


# ==================== 请求体 ====================

class ResetPasswordRequest(BaseModel):
    password: str = "123456789"


# ==================== 跨服务调用辅助 ====================

def _extract_token(request: Request) -> str:
    """从请求头提取 JWT token，用于透传给被调服务"""
    return request.headers.get("Authorization", "").replace("Bearer ", "")


async def _fetch_auth_users(token: str) -> list:
    """调用 auth_service 获取全部用户列表（含 id / username / role / created_at）"""
    result = await call_service("auth", "GET", "/internal/auth/users", token=token)
    if "error" in result:
        logger.warning(f"[admin] 拉取 auth 用户列表失败: {result.get('error')}")
        return []
    return result.get("users", [])


# ==================== 管理员 API：用户管理 ====================

@app.get("/api/admin/users")
async def admin_get_users(request: Request, admin: dict = Depends(get_admin_user)):
    """管理员获取所有用户列表（auth 信息 + user_service 资料合并）"""
    token = _extract_token(request)
    auth_result = await call_service("auth", "GET", "/internal/auth/users", token=token)
    if "error" in auth_result:
        return JSONResponse(status_code=502, content=auth_result)
    users = auth_result.get("users", [])

    # 批量调 user_service 补全 display_name / avatar_url / email
    async def _fill(u: dict):
        """为单个用户补全 display_name / avatar_url / email 资料字段。"""
        uid = u.get("id")
        r = await call_service("user", "GET", f"/internal/user/profile?user_id={uid}", token=token)
        if "error" in r:
            u.setdefault("display_name", "")
            u.setdefault("avatar_url", "")
            u.setdefault("email", "")
        else:
            p = r.get("profile", {})
            u["display_name"] = p.get("display_name", "")
            u["avatar_url"] = p.get("avatar_url", "")
            u["email"] = p.get("email", "")

    await asyncio.gather(*[_fill(u) for u in users])
    return JSONResponse(content={"users": users})


@app.get("/api/admin/users/{user_id}/conversations")
async def admin_get_user_conversations(user_id: int, request: Request,
                                       admin: dict = Depends(get_admin_user)):
    """管理员查看任意用户的会话列表（调 chat_service 内部接口）"""
    token = _extract_token(request)
    result = await call_service(
        "chat", "GET", f"/internal/chat/users/{user_id}/conversations", token=token
    )
    if "error" in result:
        return JSONResponse(status_code=502, content=result)
    return JSONResponse(content={"conversations": result.get("conversations", [])})


@app.post("/api/admin/users/{user_id}/delete")
async def admin_delete_user(user_id: int, request: Request,
                            admin: dict = Depends(get_admin_user)):
    """管理员注销用户（级联清理 user + chat + auth 三服务的数据）

    顺序：user_service 清资料 → chat_service 清会话 → auth_service 删认证记录
    auth_service.delete_user 会拦截 admin 账号，不允许删除管理员。
    """
    token = _extract_token(request)
    # 1. user_service：清理资料 + 课表 + 物理文件
    user_result = await call_service("user", "DELETE", f"/internal/user/{user_id}", token=token)
    if "error" in user_result:
        return JSONResponse(status_code=400, content=user_result)
    # 2. chat_service：清理会话 + 消息 + 反馈 + 日志
    chat_result = await call_service("chat", "DELETE", f"/internal/chat/users/{user_id}/cleanup", token=token)
    if "error" in chat_result:
        logger.warning(f"[admin] 清理 chat 数据失败: {chat_result}")
    # 3. auth_service：删除认证记录 + 登录设备（拦截 admin）
    auth_result = await call_service("auth", "POST", f"/internal/auth/users/{user_id}/delete", token=token)
    if "error" in auth_result:
        return JSONResponse(status_code=400, content=auth_result)
    return JSONResponse(content={"status": "ok"})


@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_user_password(user_id: int, req: ResetPasswordRequest,
                                    request: Request, admin: dict = Depends(get_admin_user)):
    """管理员重置用户密码（调 auth_service）"""
    if len(req.password) < 6:
        return JSONResponse(status_code=400, content={"error": "密码长度不能少于 6 个字符"})
    token = _extract_token(request)
    result = await call_service(
        "auth", "POST", f"/internal/auth/users/{user_id}/reset-password",
        token=token, json={"password": req.password}
    )
    if "error" in result:
        return JSONResponse(status_code=400, content=result)
    return JSONResponse(content={"status": "ok"})


# ==================== 管理员 API：数据统计看板 ====================

@app.get("/api/admin/stats/overview")
async def admin_stats_overview(request: Request, admin: dict = Depends(get_admin_user)):
    """数据看板概览：DAU / WAU / MAU / 新增用户 / 次日留存"""
    token = _extract_token(request)
    # 概览的新增用户 / 总用户数 / 留存依赖 users 表（属 auth_service）
    users = await _fetch_auth_users(token)
    data = await asyncio.get_event_loop().run_in_executor(
        None, models.get_dashboard_overview, users
    )
    return JSONResponse(content=_json_safe(data))


@app.get("/api/admin/stats/trends")
async def admin_stats_trends(days: int = 30, admin: dict = Depends(get_admin_user)):
    """趋势图：每日调用量 / Token 消耗 / 平均响应时长"""
    if days < 1 or days > 365:
        days = 30
    data = await asyncio.get_event_loop().run_in_executor(
        None, models.get_dashboard_trends, int(days)
    )
    return JSONResponse(content=_json_safe(data))


@app.get("/api/admin/stats/tools")
async def admin_stats_tools(days: int = 30, admin: dict = Depends(get_admin_user)):
    """工具调用分布 + 错误率 + 限流触发次数"""
    if days < 1 or days > 365:
        days = 30
    tools = await asyncio.get_event_loop().run_in_executor(
        None, models.get_dashboard_tool_distribution, int(days)
    )
    errors = await asyncio.get_event_loop().run_in_executor(
        None, models.get_dashboard_error_stats, int(days)
    )
    return JSONResponse(content=_json_safe({"tools": tools, "errors": errors}))


@app.get("/api/admin/stats/top")
async def admin_stats_top(days: int = 30, limit: int = 10,
                          request: Request = None, admin: dict = Depends(get_admin_user)):
    """Top 用户 + Top 提问（top_users 的用户名由 auth_service 补全）"""
    if days < 1 or days > 365:
        days = 30
    if limit < 1 or limit > 100:
        limit = 10

    top_users = await asyncio.get_event_loop().run_in_executor(
        None, models.get_dashboard_top_users, int(days), int(limit)
    )
    questions = await asyncio.get_event_loop().run_in_executor(
        None, models.get_dashboard_top_questions, int(days), int(limit)
    )

    # 补全 top_users 的 username / display_name
    if top_users:
        token = _extract_token(request)
        auth_users = await _fetch_auth_users(token)
        id_map = {u.get("id"): u for u in auth_users}
        for tu in top_users:
            au = id_map.get(tu.get("user_id"))
            username = (au or {}).get("username") or f"用户{tu.get('user_id')}"
            tu["username"] = username
            tu["display_name"] = username

    return JSONResponse(content=_json_safe({"top_users": top_users, "top_questions": questions}))


if __name__ == "__main__":
    import uvicorn
    from core.config import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
