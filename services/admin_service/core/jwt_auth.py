"""JWT 认证模块（本服务独立副本）。

所有微服务使用相同的 JWT_SECRET_KEY，因此任一服务都能独立验证 token，
无需在每次请求时回调 auth_service。这是微服务鉴权的标准模式。

device_token 的活跃刷新由 auth_service 负责（登录设备是 auth 的职责），
其他服务只解码 token 不写库，避免跨服务写。
"""
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_TOKEN_EXPIRE_HOURS, ADMIN_ALLOWED_IPS

_security = HTTPBearer(auto_error=False)

# 登录态 HttpOnly Cookie 名称（auth_service 登录/注册时下发，浏览器自动携带）
TOKEN_COOKIE_NAME = "lc_auth_token"


def get_client_ip(request: Request) -> str:
    """从请求中提取客户端真实 IP（nginx 代理后从 header 读取）"""
    return (
        request.headers.get("X-Real-IP")
        or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        or (request.client.host if request.client else None)
        or "unknown"
    )


def create_access_token(user_id: int, username: str, role: str = "user",
                        device_token: str = None) -> str:
    """生成 JWT access token（仅 auth_service 调用）"""
    if not device_token:
        device_token = secrets.token_hex(16)
    expire = datetime.utcnow() + timedelta(hours=JWT_TOKEN_EXPIRE_HOURS)
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "device_token": device_token,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT，失败抛 HTTPException"""
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的认证令牌")


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """从 JWT 解析当前用户身份。

    微服务模式下，不在此处查库验证用户是否存在（避免每服务都依赖 auth DB）。
    如需校验用户仍然存在，由具体服务通过 ServiceClient 调 auth_service 确认。
    大多数业务场景下，JWT 有效即视为可信（短期 token + Redis 黑名单可选）。
    """
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # 从 HttpOnly Cookie 读取浏览器登录态（JS 不可见，防 XSS 窃取）
        token = request.cookies.get(TOKEN_COOKIE_NAME)
    if not token:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    payload = decode_token(token)
    return {
        "id": payload["user_id"],
        "username": payload.get("username", ""),
        "role": payload.get("role", "user"),
        "device_token": payload.get("device_token", ""),
    }


async def get_admin_user(
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """验证当前用户是管理员，并检查 IP 白名单"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if ADMIN_ALLOWED_IPS:
        client_ip = get_client_ip(request)
        if client_ip not in ADMIN_ALLOWED_IPS:
            raise HTTPException(status_code=403, detail="无权访问管理后台")
    return user
