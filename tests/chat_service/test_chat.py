"""chat_service /api/chat 聊天接口测试。

重点：
- JWT 鉴权
- 限流（429）
- 流式 SSE 响应格式
- 非流式响应格式
- 上传文件路径注入
"""
import json
from unittest.mock import MagicMock, AsyncMock

import pytest

from tests.chat_service.conftest import chat_main


def _make_stream(*chunks):
    """构造一个异步生成器桩，按序产出 chunks。"""
    async def _gen(*a, **kw):
        for c in chunks:
            yield c
    return _gen


@pytest.fixture
def allow_rate_limit(monkeypatch):
    """默认放行所有限流。"""
    limiter = MagicMock()
    limiter.is_allowed.return_value = (True, 30)
    limiter.max_requests = 30
    limiter.window_seconds = 60
    monkeypatch.setattr(chat_main, "get_chat_rate_limiter", lambda: limiter)
    return limiter


# ==================== 鉴权 ====================

def test_chat_no_token(client):
    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_chat_invalid_token(client):
    resp = client.post(
        "/api/chat",
        json={"message": "hi"},
        headers={"Authorization": "Bearer bad.token"},
    )
    assert resp.status_code == 401


def test_chat_missing_message(client, user_headers, allow_rate_limit):
    """缺 message 字段应 422"""
    resp = client.post("/api/chat", json={}, headers=user_headers)
    assert resp.status_code == 422


# ==================== 限流 ====================

def test_chat_rate_limited(client, user_headers, monkeypatch):
    """限流命中返回 429 + JSON 错误体"""
    limiter = MagicMock()
    limiter.is_allowed.return_value = (False, 0)
    limiter.max_requests = 30
    limiter.window_seconds = 60
    monkeypatch.setattr(chat_main, "get_chat_rate_limiter", lambda: limiter)
    # publish_event 已在 conftest 全局 mock 为 no-op

    resp = client.post("/api/chat", json={"message": "hi"}, headers=user_headers)
    assert resp.status_code == 429
    body = resp.json()
    assert "频繁" in body["error"]
    assert "30" in body["detail"]


def test_chat_rate_limit_headers(client, user_headers, allow_rate_limit, monkeypatch):
    """流式响应带 X-RateLimit-* 头"""
    monkeypatch.setattr(
        chat_main.agent_service, "stream_response",
        _make_stream("hello", " world"),
    )
    resp = client.post("/api/chat", json={"message": "hi", "stream": True}, headers=user_headers)
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == "30"
    assert resp.headers["X-RateLimit-Remaining"] == "30"


# ==================== 流式响应 ====================

def test_chat_stream_text_chunks(client, user_headers, allow_rate_limit, monkeypatch):
    """纯文本 chunk 包装为 {"type":"output","content":...}"""
    monkeypatch.setattr(
        chat_main.agent_service, "stream_response",
        _make_stream("你好", "世界"),
    )
    resp = client.post("/api/chat", json={"message": "hi", "stream": True}, headers=user_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(line[6:])
    # 2 个文本 chunk + [DONE]
    assert events[-1] == "[DONE]"
    payloads = [json.loads(e) for e in events[:-1]]
    assert all(p["type"] == "output" for p in payloads)
    assert payloads[0]["content"] == "你好"
    assert payloads[1]["content"] == "世界"


def test_chat_stream_dict_chunks(client, user_headers, allow_rate_limit, monkeypatch):
    """dict chunk（如 plan 事件）原样序列化"""
    chunks = [
        {"type": "plan_created", "plan_id": "p1"},
        {"type": "step_started", "step_idx": 0},
        {"type": "output", "content": "结果"},
    ]
    monkeypatch.setattr(
        chat_main.agent_service, "stream_response",
        _make_stream(*chunks),
    )
    resp = client.post("/api/chat", json={"message": "hi"}, headers=user_headers)
    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(line[6:])
    assert events[-1] == "[DONE]"
    payloads = [json.loads(e) for e in events[:-1]]
    assert payloads[0]["plan_id"] == "p1"
    assert payloads[2]["content"] == "结果"


def test_chat_stream_empty_chunks_filtered(client, user_headers, allow_rate_limit, monkeypatch):
    """空白 chunk 不应输出"""
    monkeypatch.setattr(
        chat_main.agent_service, "stream_response",
        _make_stream("", "   ", "real"),
    )
    resp = client.post("/api/chat", json={"message": "hi"}, headers=user_headers)
    events = [line.strip()[6:] for line in resp.text.split("\n")
              if line.strip().startswith("data: ")]
    payloads = [json.loads(e) for e in events if e != "[DONE]"]
    assert len(payloads) == 1
    assert payloads[0]["content"] == "real"


# ==================== 非流式 ====================

def test_chat_non_stream(client, user_headers, allow_rate_limit, monkeypatch):
    """stream=False 返回 JSON {"content":...,"session_id":...}"""
    monkeypatch.setattr(
        chat_main.agent_service, "stream_response",
        _make_stream("hello", " ", "world"),
    )
    resp = client.post(
        "/api/chat",
        json={"message": "hi", "stream": False, "session_id": "sess_123"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    # 非流式路径对文本 chunk 调 .strip()，" " 被过滤为空
    assert body["content"] == "helloworld"
    assert body["session_id"] == "sess_123"


def test_chat_non_stream_dict_output(client, user_headers, allow_rate_limit, monkeypatch):
    """非流式模式 dict chunk 的 content 被拼接"""
    monkeypatch.setattr(
        chat_main.agent_service, "stream_response",
        _make_stream({"type": "output", "content": "Foo"}, {"type": "output", "content": "Bar"}),
    )
    resp = client.post("/api/chat", json={"message": "hi", "stream": False}, headers=user_headers)
    assert resp.json()["content"] == "FooBar"


# ==================== 上传文件路径注入 ====================

def test_chat_uploaded_file_path_injected(client, user_headers, allow_rate_limit, monkeypatch):
    """uploaded_file_path 应被注入到 message 前缀"""
    captured = {}

    async def _spy_stream(user_id, message, session_id=None, truncate_to=None):
        captured["message"] = message
        captured["user_id"] = user_id
        if False:  # 让它成为 async generator
            yield

    monkeypatch.setattr(chat_main.agent_service, "stream_response", _spy_stream)
    client.post(
        "/api/chat",
        json={"message": "总结一下", "uploaded_file_path": "/data/uploads/x.docx"},
        headers=user_headers,
    )
    assert "/data/uploads/x.docx" in captured["message"]
    assert "总结一下" in captured["message"]
    assert captured["user_id"] == 4001


# ==================== ContextVar 设置 ====================

def test_chat_sets_user_context_vars(client, user_headers, allow_rate_limit, monkeypatch):
    """端点应设置 user_ip_var / user_lat_var / user_lon_var / user_id_var

    ContextVar 在请求上下文内有效，请求结束即销毁，故在 stream_response 内捕获。
    """
    from AIRAGAgent.agent.tools.agent_tools import (
        user_ip_var, user_lat_var, user_lon_var, user_id_var,
    )
    captured = {}

    async def _capture_stream(*a, **kw):
        captured["ip"] = user_ip_var.get()
        captured["lat"] = user_lat_var.get()
        captured["lon"] = user_lon_var.get()
        captured["uid"] = user_id_var.get()
        if False:
            yield

    monkeypatch.setattr(chat_main.agent_service, "stream_response", _capture_stream)
    client.post(
        "/api/chat",
        json={"message": "hi", "latitude": 39.9, "longitude": 116.4},
        headers={**user_headers, "X-Real-IP": "1.2.3.4"},
    )
    assert captured["ip"] == "1.2.3.4"
    assert captured["lat"] == 39.9
    assert captured["lon"] == 116.4
    assert captured["uid"] == 4001


def test_chat_client_ip_from_forwarded_for(client, user_headers, allow_rate_limit, monkeypatch):
    """X-Forwarded-For 头解析客户端 IP"""
    from AIRAGAgent.agent.tools.agent_tools import user_ip_var
    captured = {}

    async def _capture(*a, **kw):
        captured["ip"] = user_ip_var.get()
        if False:
            yield

    monkeypatch.setattr(chat_main.agent_service, "stream_response", _capture)
    client.post(
        "/api/chat",
        json={"message": "hi"},
        headers={**user_headers, "X-Forwarded-For": "10.0.0.1, 192.168.1.1"},
    )
    assert captured["ip"] == "10.0.0.1"
