"""chat_service DeepAgent Plan 接口测试。

覆盖：
- POST /api/plan       plan 执行入口（stream / background）
- GET  /api/plans      plan 列表
- GET  /api/plans/{id} plan 详情（含权限校验）
"""
import json
from unittest.mock import MagicMock

import pytest

from tests.chat_service.conftest import chat_main


class _FakePlan:
    """模拟 AIRAGAgent.agent.plan.Plan 的最小实现。"""

    def __init__(self, plan_id, user_id, goal="测试目标", status="completed",
                 steps=None, session_id="sess_1", final_answer=""):
        self.id = plan_id
        self.user_id = user_id
        self.session_id = session_id
        self.goal = goal
        self.status = status
        self.final_answer = final_answer
        self.steps = steps or []
        self.created_at = 1700000000.0

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "goal": self.goal,
            "status": self.status,
            "final_answer": self.final_answer,
            "steps": self.steps,
            "created_at": self.created_at,
        }


def _make_stream(*chunks):
    async def _gen(*a, **kw):
        for c in chunks:
            yield c
    return _gen


@pytest.fixture
def allow_rate_limit(monkeypatch):
    limiter = MagicMock()
    limiter.is_allowed.return_value = (True, 30)
    limiter.max_requests = 30
    limiter.window_seconds = 60
    monkeypatch.setattr(chat_main, "get_chat_rate_limiter", lambda: limiter)


# ==================== POST /api/plan ====================

def test_plan_stream_default(client, user_headers, allow_rate_limit, monkeypatch):
    """默认 stream 模式：返回 SSE 流"""
    monkeypatch.setattr(
        chat_main.agent_service, "stream_response",
        _make_stream({"type": "plan_created", "plan_id": "p1"}, {"type": "output", "content": "done"}),
    )
    resp = client.post("/api/plan", headers=user_headers, json={
        "message": "调研 AI 编程工具",
        "session_id": "sess_plan_1",
    })
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = [l.strip()[6:] for l in resp.text.split("\n") if l.strip().startswith("data: ")]
    assert events[-1] == "[DONE]"
    payloads = [json.loads(e) for e in events[:-1]]
    assert payloads[0]["plan_id"] == "p1"


def test_plan_background_returns_task_id(client, user_headers, allow_rate_limit, monkeypatch):
    """mode=background：立即返回 task_id"""
    monkeypatch.setattr(
        chat_main.agent_service, "enqueue_plan_background",
        lambda *a, **kw: "task_abc123",
    )
    resp = client.post("/api/plan", headers=user_headers, json={
        "message": "长任务",
        "mode": "background",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "task_abc123"
    assert body["status"] == "pending"


def test_plan_background_redis_unavailable(client, user_headers, allow_rate_limit, monkeypatch):
    """enqueue_plan_background 返回 None → 503"""
    monkeypatch.setattr(
        chat_main.agent_service, "enqueue_plan_background",
        lambda *a, **kw: None,
    )
    resp = client.post("/api/plan", headers=user_headers, json={
        "message": "x", "mode": "background",
    })
    assert resp.status_code == 503
    assert "Redis" in resp.json()["error"]


def test_plan_no_auth(client):
    resp = client.post("/api/plan", json={"message": "x"})
    assert resp.status_code == 401


def test_plan_missing_message(client, user_headers, allow_rate_limit):
    resp = client.post("/api/plan", headers=user_headers, json={})
    assert resp.status_code == 422


# ==================== GET /api/plans ====================

def test_list_plans_empty(client, user_headers, monkeypatch):
    monkeypatch.setattr(
        sys_modules_plan(), "list_user_plans", lambda uid, limit=20: [],
    )
    resp = client.get("/api/plans", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == {"plans": []}


def test_list_plans_returns_user_own(client, user_headers, monkeypatch):
    plans_data = [
        {"id": "p1", "session_id": "s1", "goal": "任务A", "status": "completed",
         "created_at": "2026-08-01 10:00:00", "updated_at": "2026-08-01 11:00:00"},
        {"id": "p2", "session_id": "s2", "goal": "任务B", "status": "executing",
         "created_at": "2026-08-02 10:00:00", "updated_at": "2026-08-02 12:00:00"},
    ]
    captured = {}

    def _stub(uid, limit=20):
        captured["uid"] = uid
        return plans_data

    monkeypatch.setattr(sys_modules_plan(), "list_user_plans", _stub)
    resp = client.get("/api/plans", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["plans"] == plans_data
    assert captured["uid"] == 4001


def test_list_plans_no_auth(client):
    resp = client.get("/api/plans")
    assert resp.status_code == 401


# ==================== GET /api/plans/{plan_id} ====================

def test_get_plan_detail_success(client, user_headers, monkeypatch):
    plan = _FakePlan("p_detail", 4001, goal="详情测试", status="completed")
    monkeypatch.setattr(sys_modules_plan(), "load_plan", lambda pid: plan)
    resp = client.get("/api/plans/p_detail", headers=user_headers)
    assert resp.status_code == 200
    body = resp.json()["plan"]
    assert body["id"] == "p_detail"
    assert body["goal"] == "详情测试"
    assert body["user_id"] == 4001


def test_get_plan_detail_not_found(client, user_headers, monkeypatch):
    monkeypatch.setattr(sys_modules_plan(), "load_plan", lambda pid: None)
    resp = client.get("/api/plans/no_such", headers=user_headers)
    assert resp.status_code == 404
    assert "不存在" in resp.json()["error"]


def test_get_plan_detail_other_user_forbidden(client, user_headers, monkeypatch):
    """别人的 plan 应 403"""
    plan = _FakePlan("p_other", 9999, goal="别人的")
    monkeypatch.setattr(sys_modules_plan(), "load_plan", lambda pid: plan)
    resp = client.get("/api/plans/p_other", headers=user_headers)
    assert resp.status_code == 403
    assert "无权" in resp.json()["error"]


def test_get_plan_detail_no_auth(client):
    resp = client.get("/api/plans/anything")
    assert resp.status_code == 401


# ==================== 辅助 ====================

def sys_modules_plan():
    import sys
    return sys.modules["AIRAGAgent.agent.plan"]
