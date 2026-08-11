"""Redis pub/sub 事件落库回调（on_chat_completed / on_tool_called / on_rate_limited）。

直接调用 main 中的回调函数，验证事件 payload 正确写入 lc_admin_test 三张表。
"""
import os
import unittest.mock as um
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import pymysql
import pymysql.cursors


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


def _count(table):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
            return cur.fetchone()[0]
    finally:
        conn.close()


def _fetch_all(table):
    conn = _connect()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(f"SELECT * FROM {table} ORDER BY id")
            return cur.fetchall()
    finally:
        conn.close()


# ==================== on_chat_completed ====================

def test_chat_completed_writes_api_call_log(admin_main_mod):
    """完整 payload → api_call_logs 写入一行，含 token / duration / success。"""
    admin_main_mod.on_chat_completed({
        "user_id": 2,
        "session_id": "sess-abc",
        "ip": "1.2.3.4",
        "endpoint": "chat",
        "duration_ms": 1234,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "is_success": True,
        "error_msg": "",
    })
    assert _count("api_call_logs") == 1
    rows = _fetch_all("api_call_logs")
    row = rows[0]
    assert row["user_id"] == 2
    assert row["session_id"] == "sess-abc"
    assert row["ip"] == "1.2.3.4"
    assert row["endpoint"] == "chat"
    assert row["duration_ms"] == 1234
    assert row["prompt_tokens"] == 100
    assert row["completion_tokens"] == 50
    assert row["total_tokens"] == 150
    assert row["is_success"] == 1
    assert row["error_msg"] == ""


def test_chat_completed_failed_call(admin_main_mod):
    """失败对话：is_success=False + error_msg 写入。"""
    admin_main_mod.on_chat_completed({
        "user_id": 3,
        "session_id": "sess-fail",
        "ip": "",
        "endpoint": "chat",
        "duration_ms": 500,
        "prompt_tokens": 10,
        "completion_tokens": 0,
        "is_success": False,
        "error_msg": "LLM timeout",
    })
    rows = _fetch_all("api_call_logs")
    assert len(rows) == 1
    assert rows[0]["is_success"] == 0
    assert rows[0]["error_msg"] == "LLM timeout"
    assert rows[0]["total_tokens"] == 10


def test_chat_completed_missing_fields_use_defaults(admin_main_mod):
    """缺字段 → 用默认值（user_id=0, endpoint=chat, is_success=True）。"""
    admin_main_mod.on_chat_completed({})  # 空 payload
    rows = _fetch_all("api_call_logs")
    assert len(rows) == 1
    assert rows[0]["user_id"] == 0
    assert rows[0]["endpoint"] == "chat"
    assert rows[0]["is_success"] == 1


def test_chat_completed_db_error_silent(admin_main_mod, models_mod):
    """落库异常不抛出（埋点失败不影响主流程）。"""
    @contextmanager
    def _bad_db():
        raise RuntimeError("DB down")

    with um.patch.object(models_mod, "get_db", _bad_db):
        # 不应抛异常
        admin_main_mod.on_chat_completed({"user_id": 1})
    # 未写入
    assert _count("api_call_logs") == 0


# ==================== on_tool_called ====================

def test_tool_called_writes_log(admin_main_mod):
    admin_main_mod.on_tool_called({
        "user_id": 2,
        "session_id": "s1",
        "tool_name": "search",
        "duration_ms": 200,
        "is_success": True,
        "error_msg": "",
    })
    assert _count("tool_call_logs") == 1
    row = _fetch_all("tool_call_logs")[0]
    assert row["tool_name"] == "search"
    assert row["duration_ms"] == 200
    assert row["is_success"] == 1


def test_tool_called_failed(admin_main_mod):
    admin_main_mod.on_tool_called({
        "user_id": 3,
        "session_id": "",
        "tool_name": "browser",
        "duration_ms": 5000,
        "is_success": False,
        "error_msg": "navigation timeout",
    })
    row = _fetch_all("tool_call_logs")[0]
    assert row["is_success"] == 0
    assert row["error_msg"] == "navigation timeout"


def test_tool_called_missing_fields_default(admin_main_mod):
    admin_main_mod.on_tool_called({})
    row = _fetch_all("tool_call_logs")[0]
    assert row["user_id"] == 0
    assert row["tool_name"] == ""
    assert row["is_success"] == 1


# ==================== on_rate_limited ====================

def test_rate_limited_writes_event(admin_main_mod):
    admin_main_mod.on_rate_limited({
        "user_id": 2,
        "ip": "1.2.3.4",
        "limit_type": "chat",
        "identifier": "user:2",
    })
    assert _count("rate_limit_events") == 1
    row = _fetch_all("rate_limit_events")[0]
    assert row["user_id"] == 2
    assert row["ip"] == "1.2.3.4"
    assert row["limit_type"] == "chat"
    assert row["identifier"] == "user:2"


def test_rate_limited_missing_fields_default(admin_main_mod):
    admin_main_mod.on_rate_limited({})
    row = _fetch_all("rate_limit_events")[0]
    assert row["user_id"] == 0
    assert row["ip"] == ""
    assert row["limit_type"] == "chat"  # 默认值
    assert row["identifier"] == ""


def test_rate_limited_long_identifier_truncated(admin_main_mod):
    """identifier > 200 字符 → 截断到 200。"""
    long_id = "x" * 300
    admin_main_mod.on_rate_limited({
        "user_id": 1,
        "ip": "",
        "limit_type": "tool",
        "identifier": long_id,
    })
    row = _fetch_all("rate_limit_events")[0]
    assert len(row["identifier"]) == 200


# ==================== _json_safe 辅助函数 ====================

def test_json_safe_decimal_and_datetime(admin_main_mod):
    """_json_safe 把 Decimal/datetime/date 转为可序列化类型。"""
    out = admin_main_mod._json_safe({
        "d": Decimal("3.14"),
        "dt": datetime(2026, 8, 4, 10, 0, 0),
        "date": date(2026, 8, 4),
        "list": [Decimal("1"), Decimal("2")],
        "nested": {"x": Decimal("9.99")},
    })
    assert out["d"] == 3.14
    assert out["dt"] == "2026-08-04T10:00:00"
    assert out["date"] == "2026-08-04"
    assert out["list"] == [1.0, 2.0]
    assert out["nested"]["x"] == 9.99


def test_json_safe_passthrough_primitives(admin_main_mod):
    """字符串/数字/None 原样返回。"""
    out = admin_main_mod._json_safe({"s": "abc", "n": 42, "none": None, "b": True})
    assert out == {"s": "abc", "n": 42, "none": None, "b": True}
