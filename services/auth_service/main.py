"""auth_service FastAPI 入口。

路由：
- POST /api/auth/register       注册
- POST /api/auth/login          登录
- GET  /api/auth/me             当前用户（合并 user_service 的 profile）
- GET  /api/auth/recover/question
- POST /api/auth/recover/reset
- PUT  /api/user/password       修改密码
- PUT  /api/user/security-question
- GET  /api/user/devices
- DELETE /api/user/devices/{id}
- POST /api/user/devices/revoke-all-others
- 内部 /internal/auth/user/{id}      供其他服务查询用户认证信息
- 内部 /internal/auth/users          供 admin_service 列表
- 内部 /internal/auth/users/{id}/delete   供 user_service 注销账号时调用
- 内部 /internal/auth/users/{id}/reset-password  供 admin_service 调用
"""
from __future__ import annotations
import asyncio
import os
import secrets as _secrets

from fastapi import Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from core import (
    create_app, get_current_user, get_admin_user, get_client_ip,
    create_access_token, ServiceClient, logger,
)
from core.jwt_auth import TOKEN_COOKIE_NAME
from core.config import ADMIN_ALLOWED_IPS, JWT_TOKEN_EXPIRE_HOURS
import models

app = create_app("auth_service", version="1.0.0")


def _is_https(request: Request) -> bool:
    """判断请求是否走 HTTPS（生产经 nginx 时读 X-Forwarded-Proto）。"""
    return (request.headers.get("X-Forwarded-Proto") or request.url.scheme) == "https"


def _auth_response(content: dict, token: str, request: Request, status_code: int = 200) -> JSONResponse:
    """生成带 HttpOnly 登录态 Cookie 的 JSON 响应（浏览器端自动携带，JS 不可读）。"""
    resp = JSONResponse(content=content, status_code=status_code)
    resp.set_cookie(
        TOKEN_COOKIE_NAME,
        token,
        max_age=JWT_TOKEN_EXPIRE_HOURS * 3600,
        httponly=True,
        secure=_is_https(request),
        samesite="lax",
        path="/",
    )
    return resp


# ==================== 请求体 ====================

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class RecoverResetRequest(BaseModel):
    username: str
    answer: str
    new_password: str


class SecurityQuestionRequest(BaseModel):
    question: str
    answer: str


class ResetPasswordRequest(BaseModel):
    password: str = "123456789"


# ==================== 认证 API ====================

@app.post("/api/auth/register")
async def register(req: RegisterRequest, request: Request):
    """用户注册：创建认证记录、生成 token 并同步创建用户资料。"""
    if not req.username or not req.password:
        return JSONResponse(status_code=400, content={"error": "用户名和密码不能为空"})
    if len(req.username) < 3 or len(req.username) > 50:
        return JSONResponse(status_code=400, content={"error": "用户名长度应为 3-50 个字符"})
    if len(req.password) < 6:
        return JSONResponse(status_code=400, content={"error": "密码长度不能少于 6 个字符"})

    def _create():
        """在线程池里同步创建用户记录（避免阻塞事件循环）。"""
        return models.create_user(req.username, req.password, role="user")
    user = await asyncio.get_event_loop().run_in_executor(None, _create)
    if user is None:
        return JSONResponse(status_code=409, content={"error": "用户名已存在"})

    device_token = _secrets.token_hex(16)
    token = create_access_token(user["id"], user["username"], "user", device_token=device_token)

    # 记录登录设备
    await asyncio.get_event_loop().run_in_executor(
        None, models.create_login_device,
        user["id"], device_token,
        request.headers.get("User-Agent", ""),
        get_client_ip(request)
    )

    # 同步创建 user_profile（调用 user_service）
    display_name = req.display_name or req.username
    await _create_user_profile(user["id"], display_name)

    return _auth_response({
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": display_name,
            "role": "user",
        }
    }, token, request)


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    """用户登录：校验密码（含管理员 IP 白名单）后签发 token 并记录登录设备。"""
    if not req.username or not req.password:
        return JSONResponse(status_code=400, content={"error": "用户名和密码不能为空"})

    user = await asyncio.get_event_loop().run_in_executor(None, models.get_user_by_username, req.username)
    if user is None or not models.verify_password(req.password, user["password_hash"]):
        return JSONResponse(status_code=401, content={"error": "用户名或密码错误"})

    # 管理员 IP 白名单
    if user["role"] == "admin" and ADMIN_ALLOWED_IPS:
        client_ip = get_client_ip(request)
        if client_ip not in ADMIN_ALLOWED_IPS:
            return JSONResponse(status_code=403, content={"error": "无权访问管理后台"})

    device_token = _secrets.token_hex(16)
    token = create_access_token(user["id"], user["username"], user["role"], device_token=device_token)
    await asyncio.get_event_loop().run_in_executor(
        None, models.create_login_device,
        user["id"], device_token,
        request.headers.get("User-Agent", ""),
        get_client_ip(request)
    )

    # 合并 user_service 的 profile 数据（display_name / email / avatar_url）
    profile = await _get_user_profile(user["id"])

    return _auth_response({
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": profile.get("display_name") or user["username"],
            "role": user["role"],
            "avatar_url": profile.get("avatar_url", ""),
            "email": profile.get("email", ""),
        }
    }, token, request)


@app.post("/api/auth/logout")
async def logout(request: Request):
    """登出：清除 HttpOnly 登录态 Cookie。"""
    resp = JSONResponse(content={"status": "ok"})
    resp.delete_cookie(
        TOKEN_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_is_https(request),
        samesite="lax",
    )
    return resp


@app.get("/api/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    """获取当前用户信息（合并 auth + user profile）"""
    full_user = await asyncio.get_event_loop().run_in_executor(None, models.get_user_by_id, user["id"])
    if full_user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    profile = await _get_user_profile(user["id"])
    return JSONResponse(content={
        "user": {
            "id": full_user["id"],
            "username": full_user["username"],
            "role": full_user["role"],
            "created_at": full_user["created_at"],
            "last_password_changed": full_user["last_password_changed"],
            "display_name": profile.get("display_name", ""),
            "email": profile.get("email", ""),
            "avatar_url": profile.get("avatar_url", ""),
            "has_security_question": full_user["has_security_question"],
        }
    })


@app.get("/api/auth/recover/question")
async def recover_get_question(username: str):
    """获取找回密码所需的密保问题。"""
    info = await asyncio.get_event_loop().run_in_executor(None, models.get_security_question_by_username, username)
    if info is None:
        return JSONResponse(status_code=404, content={"error": "该账号未设置密保或不存在"})
    return JSONResponse(content={"username": info["username"], "question": info["question"]})


@app.post("/api/auth/recover/reset")
async def recover_reset_password(req: RecoverResetRequest):
    """通过密保答案验证后重置用户密码。"""
    if len(req.new_password) < 6:
        return JSONResponse(status_code=400, content={"error": "密码长度不能少于 6 个字符"})
    success = await asyncio.get_event_loop().run_in_executor(
        None, models.reset_password_by_security_answer, req.username, req.answer, req.new_password
    )
    if not success:
        return JSONResponse(status_code=400, content={"error": "密保答案错误或账号不可用"})
    return JSONResponse(content={"status": "ok"})


# ==================== 密码 / 密保 ====================

@app.put("/api/user/password")
async def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """修改当前登录用户的密码（需校验原密码）。"""
    if len(req.new_password) < 6:
        return JSONResponse(status_code=400, content={"error": "密码长度不能少于 6 个字符"})
    if req.old_password == req.new_password:
        return JSONResponse(status_code=400, content={"error": "新密码不能与旧密码相同"})
    success = await asyncio.get_event_loop().run_in_executor(
        None, models.change_password, user["id"], req.old_password, req.new_password
    )
    if not success:
        return JSONResponse(status_code=400, content={"error": "原密码错误"})
    return JSONResponse(content={"status": "ok"})


@app.put("/api/user/security-question")
async def set_security_question(req: SecurityQuestionRequest, user: dict = Depends(get_current_user)):
    """设置当前登录用户的密保问题与答案。"""
    if len(req.question.strip()) < 4:
        return JSONResponse(status_code=400, content={"error": "密保问题至少 4 个字符"})
    if len(req.answer.strip()) < 1:
        return JSONResponse(status_code=400, content={"error": "密保答案不能为空"})
    success = await asyncio.get_event_loop().run_in_executor(
        None, models.set_security_question, user["id"], req.question, req.answer
    )
    if not success:
        return JSONResponse(status_code=400, content={"error": "设置失败"})
    return JSONResponse(content={"status": "ok"})


# ==================== 登录设备 ====================

@app.get("/api/user/devices")
async def list_devices(user: dict = Depends(get_current_user)):
    """获取当前用户的登录设备列表（标注当前使用的设备）。"""
    devices = await asyncio.get_event_loop().run_in_executor(None, models.get_login_devices, user["id"])
    current_token = user.get("device_token", "")
    for d in devices:
        d["is_current"] = (d["device_token"] == current_token)
    return JSONResponse(content={"devices": devices})


@app.delete("/api/user/devices/{device_id}")
async def revoke_device(device_id: int, user: dict = Depends(get_current_user)):
    """撤销指定登录设备。"""
    success = await asyncio.get_event_loop().run_in_executor(
        None, models.revoke_login_device, user["id"], device_id
    )
    if not success:
        return JSONResponse(status_code=404, content={"error": "设备不存在"})
    return JSONResponse(content={"status": "ok"})


@app.post("/api/user/devices/revoke-all-others")
async def revoke_all_others(user: dict = Depends(get_current_user)):
    """撤销当前设备以外的所有登录设备。"""
    current_token = user.get("device_token", "")
    if not current_token:
        return JSONResponse(status_code=400, content={"error": "无法识别当前设备"})
    count = await asyncio.get_event_loop().run_in_executor(
        None, models.revoke_all_other_devices, user["id"], current_token
    )
    return JSONResponse(content={"status": "ok", "revoked_count": count})


# ==================== 内部接口（供其他服务调用，不暴露给 nginx） ====================

@app.get("/internal/auth/user/{user_id}")
async def internal_get_user(user_id: int):
    """供其他服务查询用户认证信息（不含密码哈希）"""
    user = await asyncio.get_event_loop().run_in_executor(None, models.get_user_by_id, user_id)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用户不存在"})
    return JSONResponse(content={"user": user})


@app.get("/internal/auth/users")
async def internal_list_users():
    """供 admin_service 获取全部用户认证信息"""
    users = await asyncio.get_event_loop().run_in_executor(None, models.get_all_users)
    return JSONResponse(content={"users": users})


@app.post("/internal/auth/users/{user_id}/delete")
async def internal_delete_user(user_id: int):
    """供 user_service 注销账号时调用（级联删除 auth 相关数据）"""
    success = await asyncio.get_event_loop().run_in_executor(None, models.delete_user, user_id)
    if not success:
        return JSONResponse(status_code=400, content={"error": "用户不存在或无法删除管理员"})
    return JSONResponse(content={"status": "ok"})


@app.post("/internal/auth/users/{user_id}/reset-password")
async def internal_reset_password(user_id: int, req: ResetPasswordRequest):
    """供 admin_service 调用"""
    if len(req.password) < 6:
        return JSONResponse(status_code=400, content={"error": "密码长度不能少于 6 个字符"})
    success = await asyncio.get_event_loop().run_in_executor(
        None, models.reset_user_password, user_id, req.password
    )
    if not success:
        return JSONResponse(status_code=400, content={"error": "用户不存在或无法修改管理员"})
    return JSONResponse(content={"status": "ok"})


@app.get("/internal/auth/users/{user_id}/role")
async def internal_get_role(user_id: int):
    """供其他服务查询用户角色。"""
    role = await asyncio.get_event_loop().run_in_executor(None, models.get_user_role, user_id)
    if role is None:
        return JSONResponse(status_code=404, content={"error": "用户不存在"})
    return JSONResponse(content={"user_id": user_id, "role": role})


# ==================== 跨服务调用辅助 ====================

async def _get_user_profile(user_id: int) -> dict:
    """调用 user_service 获取用户资料"""
    try:
        async with ServiceClient("user") as client:
            resp = await client.get(f"/internal/user/profile?user_id={user_id}")
            if resp.status_code == 200:
                return resp.json().get("profile", {})
    except Exception as e:
        logger.debug(f"[auth] 调用 user_service 获取资料失败: {e}")
    return {}


async def _create_user_profile(user_id: int, display_name: str):
    """注册时调用 user_service 创建资料记录"""
    try:
        async with ServiceClient("user") as client:
            await client.post("/internal/user/profile", json={
                "user_id": user_id,
                "display_name": display_name,
            })
    except Exception as e:
        logger.warning(f"[auth] 创建用户资料失败（可后续补齐）: {e}")


if __name__ == "__main__":
    import uvicorn
    from core.config import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
