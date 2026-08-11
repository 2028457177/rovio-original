"""跨服务 HTTP 客户端（本服务独立副本）。

封装 httpx 异步调用，目标地址由本服务 config 提供（环境变量驱动）。
服务间调用时携带原始 JWT token，实现身份透传。
"""
import os
from typing import Any, Optional

import httpx

from .config import get_service_url
from .logger import logger

# 内部调用超时（秒）。chat 流式调用不通过这里，所以默认即可。
DEFAULT_TIMEOUT = 15.0


class ServiceClient:
    """跨服务 HTTP 调用客户端。

    用法::

        async with ServiceClient("user") as client:
            resp = await client.get("/api/user/me", token=user_token)

    服务间调用通过 127.0.0.1:端口 直连，不走 nginx 网关，
    避免网关层增加无谓的转发延迟。
    """

    def __init__(self, service: str, token: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT):
        """初始化客户端：记录目标服务名、base_url、token 与超时时间。"""
        self.service = service
        self.base_url = get_service_url(service)
        self.token = token
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """进入 async with 上下文时创建 httpx 异步客户端并返回自身。"""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._build_headers(),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """退出 async with 上下文时关闭 httpx 异步客户端。"""
        if self._client:
            await self._client.aclose()
        self._client = None

    def _build_headers(self) -> dict:
        """构建请求头：携带 Bearer token 与内部调用标记。"""
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        # 传递内部调用标记，便于鉴权放行
        h["X-Internal-Call"] = "1"
        return h

    async def get(self, path: str, **kwargs) -> httpx.Response:
        """发送 GET 请求并返回响应。"""
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        """发送 POST 请求并返回响应。"""
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> httpx.Response:
        """发送 PUT 请求并返回响应。"""
        return await self._request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs) -> httpx.Response:
        """发送 PATCH 请求并返回响应。"""
        return await self._request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> httpx.Response:
        """发送 DELETE 请求并返回响应。"""
        return await self._request("DELETE", path, **kwargs)

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """通用请求入口，method 由参数指定"""
        return await self._request(method.upper(), path, **kwargs)

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """统一执行 HTTP 请求；调用失败时记录日志并抛出异常。"""
        if not self._client:
            raise RuntimeError("ServiceClient 必须在 async with 上下文中使用")
        try:
            resp = await self._client.request(method, path, **kwargs)
            return resp
        except httpx.RequestError as e:
            logger.error(f"[ServiceClient] 调用 {self.service} {method} {path} 失败: {e}")
            raise


async def call_service(service: str, method: str, path: str,
                       token: Optional[str] = None, **kwargs) -> dict:
    """便捷封装：发起一次跨服务调用并返回 JSON。

    失败时返回 {"error": "..."} 而不抛异常，调用方自行判断。
    """
    try:
        async with ServiceClient(service, token=token) as client:
            resp = await client.request(method, path, **kwargs)
            if resp.status_code >= 400:
                return {"error": f"{service} 返回 {resp.status_code}", "detail": resp.text}
            return resp.json()
    except Exception as e:
        return {"error": f"调用 {service} 失败: {e}"}
