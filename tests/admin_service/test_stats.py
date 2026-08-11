"""数据统计看板 API（/api/admin/stats/*）。

覆盖：
- overview: DAU/WAU/MAU + 新增/留存（依赖 auth_service users mock）
- trends: 每日调用量/Token/响应时长趋势
- tools: 工具调用分布 + 错误率 + 限流触发次数
- top: Top 用户 + Top 提问（top_users 用户名由 auth_service 补全）
- 参数边界：days 超界自动夹紧
"""
import os
from datetime import datetime, timedelta

import pymysql


def _connect():
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database="lc_admin_test",
        charset="utf8mb4",
        autocommit=True,
    )


def _seed_api_call(rows):
    """插入 api_call_logs。
    rows: list of dict(user_id, session_id, ip, endpoint, duration_ms,
                       prompt_tokens, completion_tokens, is_success, error_msg,
                       created_at_dt)
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """INSERT INTO api_call_logs
                       (user_id, session_id, ip, endpoint, duration_ms,
                        prompt_tokens, completion_tokens, total_tokens,
                        is_success, error_msg, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (r["user_id"], r.get("session_id", ""), r.get("ip", ""),
                     r.get("endpoint", "chat"), r.get("duration_ms", 0),
                     r.get("prompt_tokens", 0), r.get("completion_tokens", 0),
                     r.get("prompt_tokens", 0) + r.get("completion_tokens", 0),
                     1 if r.get("is_success", True) else 0,
                     r.get("error_msg", ""),
                     r["created_at_dt"].strftime("%Y-%m-%d %H:%M:%S"))
                )
    finally:
        conn.close()


def _seed_tool_call(rows):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """INSERT INTO tool_call_logs
                       (user_id, session_id, tool_name, duration_ms,
                        is_success, error_msg, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (r["user_id"], r.get("session_id", ""),
                     r.get("tool_name", ""), r.get("duration_ms", 0),
                     1 if r.get("is_success", True) else 0,
                     r.get("error_msg", ""),
                     r["created_at_dt"].strftime("%Y-%m-%d %H:%M:%S"))
                )
    finally:
        conn.close()


def _seed_rate_limit(rows):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """INSERT INTO rate_limit_events
                       (user_id, ip, limit_type, identifier, created_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (r["user_id"], r.get("ip", ""),
                     r.get("limit_type", "chat"), r.get("identifier", ""),
                     r["created_at_dt"].strftime("%Y-%m-%d %H:%M:%S"))
                )
    finally:
        conn.close()


# ==================== overview ====================

def test_overview_empty(client, admin_headers):
    """空库 → 所有计数为 0，retention_rate 为 0.0。"""
    resp = client.get("/api/admin/stats/overview", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dau"] == 0
    assert body["wau"] == 0
    assert body["mau"] == 0
    # mock users 含 1 个非 admin 用户（alice）
    assert body["total_users"] == 1
    assert body["retention_rate"] == 0.0


def test_overview_with_today_activity(client, admin_headers, mock_service_state):
    """今日有 2 个不同用户调用 → DAU=2。"""
    now = datetime.now()
    _seed_api_call([
        {"user_id": 2, "session_id": "s1", "duration_ms": 100,
         "prompt_tokens": 50, "completion_tokens": 30, "created_at_dt": now},
        {"user_id": 3, "session_id": "s2", "duration_ms": 200,
         "prompt_tokens": 10, "completion_tokens": 5, "created_at_dt": now},
    ])
    resp = client.get("/api/admin/stats/overview", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["dau"] == 2
    assert body["wau"] == 2
    assert body["mau"] == 2


def test_overview_dau_excludes_anonymous(client, admin_headers):
    """user_id <= 0 的匿名调用不计入 DAU。"""
    now = datetime.now()
    _seed_api_call([
        {"user_id": 0, "session_id": "anon", "created_at_dt": now},
        {"user_id": -1, "session_id": "anon2", "created_at_dt": now},
        {"user_id": 2, "session_id": "s1", "created_at_dt": now},
    ])
    resp = client.get("/api/admin/stats/overview", headers=admin_headers)
    assert resp.json()["dau"] == 1


def test_overview_new_users_today(client, admin_headers, mock_service_state):
    """mock users 中 alice created_at=今日 → new_users_today=1。"""
    today_str = datetime.now().strftime("%Y-%m-%d") + " 10:00:00"
    mock_service_state["auth_users"] = (200, {"users": [
        {"id": 1, "username": "admin", "role": "admin",
         "created_at": "2026-07-01 10:00:00"},
        {"id": 2, "username": "alice", "role": "user",
         "created_at": today_str},
    ]})
    resp = client.get("/api/admin/stats/overview", headers=admin_headers)
    body = resp.json()
    assert body["new_users_today"] == 1
    assert body["total_users"] == 1  # 排除 admin


def test_overview_admin_role_excluded_from_total(client, admin_headers, mock_service_state):
    """role=admin 用户不计入 total_users。"""
    mock_service_state["auth_users"] = (200, {"users": [
        {"id": 1, "username": "admin", "role": "admin",
         "created_at": "2026-07-01 10:00:00"},
    ]})
    resp = client.get("/api/admin/stats/overview", headers=admin_headers)
    assert resp.json()["total_users"] == 0


# ==================== trends ====================

def test_trends_empty(client, admin_headers):
    resp = client.get("/api/admin/stats/trends", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["dates"] == []
    assert body["call_counts"] == []
    assert body["total_tokens"] == []


def test_trends_with_data(client, admin_headers):
    """跨 3 天写入 4 条调用 → 返回 3 个日期点。"""
    now = datetime.now()
    _seed_api_call([
        {"user_id": 2, "duration_ms": 100, "prompt_tokens": 50,
         "completion_tokens": 30, "created_at_dt": now - timedelta(days=2)},
        {"user_id": 2, "duration_ms": 200, "prompt_tokens": 10,
         "completion_tokens": 5, "created_at_dt": now - timedelta(days=1)},
        {"user_id": 3, "duration_ms": 50, "prompt_tokens": 0,
         "completion_tokens": 0, "created_at_dt": now},
        {"user_id": 3, "duration_ms": 150, "prompt_tokens": 20,
         "completion_tokens": 10, "created_at_dt": now},
    ])
    resp = client.get("/api/admin/stats/trends?days=30", headers=admin_headers)
    body = resp.json()
    assert len(body["dates"]) == 3
    assert body["call_counts"][-1] == 2  # 今日 2 条
    assert body["total_tokens"][-1] == 30  # 20+10


def test_trends_days_clamped_to_default(client, admin_headers):
    """days=0 → 夹紧为 30；days=1000 → 夹紧为 30。"""
    for bad in (0, 1000):
        resp = client.get(f"/api/admin/stats/trends?days={bad}", headers=admin_headers)
        assert resp.status_code == 200
        # 空库下两种参数返回结构一致
        assert resp.json()["dates"] == []


# ==================== tools ====================

def test_tools_empty(client, admin_headers):
    resp = client.get("/api/admin/stats/tools", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tools"] == []
    assert body["errors"]["total_calls"] == 0
    assert body["errors"]["error_rate"] == 0.0
    assert body["errors"]["rate_limit_count"] == 0


def test_tools_with_data(client, admin_headers):
    """2 个工具：search 调用 3 次全成功，browser 调用 2 次失败 1 次。"""
    now = datetime.now()
    _seed_tool_call([
        {"user_id": 2, "tool_name": "search", "duration_ms": 100,
         "is_success": True, "created_at_dt": now},
        {"user_id": 3, "tool_name": "search", "duration_ms": 200,
         "is_success": True, "created_at_dt": now},
        {"user_id": 2, "tool_name": "search", "duration_ms": 150,
         "is_success": True, "created_at_dt": now},
        {"user_id": 2, "tool_name": "browser", "duration_ms": 5000,
         "is_success": True, "created_at_dt": now},
        {"user_id": 3, "tool_name": "browser", "duration_ms": 3000,
         "is_success": False, "error_msg": "timeout",
         "created_at_dt": now},
    ])
    _seed_api_call([
        {"user_id": 2, "duration_ms": 100, "is_success": True, "created_at_dt": now},
        {"user_id": 3, "duration_ms": 200, "is_success": False,
         "error_msg": "err", "created_at_dt": now},
    ])
    _seed_rate_limit([
        {"user_id": 2, "ip": "1.1.1.1", "limit_type": "chat", "created_at_dt": now},
    ])
    resp = client.get("/api/admin/stats/tools?days=30", headers=admin_headers)
    body = resp.json()

    tools = {t["tool_name"]: t for t in body["tools"]}
    assert tools["search"]["count"] == 3
    assert tools["search"]["success_rate"] == 100.0
    assert tools["browser"]["count"] == 2
    assert tools["browser"]["success_rate"] == 50.0

    errs = body["errors"]
    assert errs["total_calls"] == 2
    assert errs["error_calls"] == 1
    assert errs["error_rate"] == 50.0
    assert errs["tool_total_calls"] == 5
    assert errs["tool_error_calls"] == 1
    assert errs["rate_limit_count"] == 1


def test_tools_days_clamped(client, admin_headers):
    """days 超界 → 夹紧为 30。"""
    for bad in (0, 1000):
        resp = client.get(f"/api/admin/stats/tools?days={bad}", headers=admin_headers)
        assert resp.status_code == 200


# ==================== top ====================

def test_top_empty(client, admin_headers):
    resp = client.get("/api/admin/stats/top", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["top_users"] == []
    # top_questions 始终为空（lc_admin 无 messages 表）
    assert body["top_questions"] == []


def test_top_users_ranked_by_call_count(client, admin_headers, mock_service_state):
    """user 2 调用 3 次、user 3 调用 1 次 → 排序 2 在前。"""
    now = datetime.now()
    _seed_api_call([
        {"user_id": 2, "duration_ms": 100, "prompt_tokens": 50,
         "completion_tokens": 30, "created_at_dt": now},
        {"user_id": 2, "duration_ms": 100, "prompt_tokens": 20,
         "completion_tokens": 10, "created_at_dt": now},
        {"user_id": 2, "duration_ms": 100, "prompt_tokens": 10,
         "completion_tokens": 5, "created_at_dt": now},
        {"user_id": 3, "duration_ms": 100, "prompt_tokens": 100,
         "completion_tokens": 50, "created_at_dt": now},
    ])
    # mock users 含 id=2 (alice)、id=1 (admin)
    mock_service_state["auth_users"] = (200, {"users": [
        {"id": 1, "username": "admin", "role": "admin",
         "created_at": "2026-07-01 10:00:00"},
        {"id": 2, "username": "alice", "role": "user",
         "created_at": "2026-08-01 10:00:00"},
        {"id": 3, "username": "bob", "role": "user",
         "created_at": "2026-08-02 10:00:00"},
    ]})
    resp = client.get("/api/admin/stats/top?days=30&limit=10", headers=admin_headers)
    body = resp.json()
    assert len(body["top_users"]) == 2
    top = body["top_users"][0]
    assert top["user_id"] == 2
    assert top["call_count"] == 3
    assert top["username"] == "alice"  # 由 auth_service 补全
    assert top["total_tokens"] == 125  # (50+30) + (20+10) + (10+5)


def test_top_users_anonymous_excluded(client, admin_headers):
    """user_id <= 0 不计入 top users。"""
    now = datetime.now()
    _seed_api_call([
        {"user_id": 0, "duration_ms": 100, "created_at_dt": now},
        {"user_id": -1, "duration_ms": 100, "created_at_dt": now},
        {"user_id": 2, "duration_ms": 100, "created_at_dt": now},
    ])
    resp = client.get("/api/admin/stats/top", headers=admin_headers)
    body = resp.json()
    assert len(body["top_users"]) == 1
    assert body["top_users"][0]["user_id"] == 2


def test_top_users_fallback_username_when_auth_missing(client, admin_headers, mock_service_state):
    """auth_service 中找不到 user_id → username 回退为「用户{user_id}」。"""
    now = datetime.now()
    _seed_api_call([
        {"user_id": 999, "duration_ms": 100, "created_at_dt": now},
    ])
    # mock users 不含 id=999
    mock_service_state["auth_users"] = (200, {"users": [
        {"id": 1, "username": "admin", "role": "admin",
         "created_at": "2026-07-01 10:00:00"},
    ]})
    resp = client.get("/api/admin/stats/top", headers=admin_headers)
    body = resp.json()
    assert len(body["top_users"]) == 1
    assert body["top_users"][0]["username"] == "用户999"


def test_top_limit_clamped(client, admin_headers):
    """limit=0 → 夹紧为 10；limit=1000 → 夹紧为 10。"""
    for bad in (0, 1000):
        resp = client.get(f"/api/admin/stats/top?limit={bad}", headers=admin_headers)
        assert resp.status_code == 200
