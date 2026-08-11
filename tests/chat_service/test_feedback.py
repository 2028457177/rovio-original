"""chat_service /api/feedback 消息反馈测试。"""
import pytest

from tests.chat_service.conftest import chat_main
from tests.chat_service.db_stubs import install, insert_conversation


@pytest.fixture(autouse=True)
def real_db(monkeypatch):
    install(monkeypatch)


def test_feedback_like(client, user_headers):
    insert_conversation(4001, "fb_conv", "测试")
    resp = client.post("/api/feedback", headers=user_headers, json={
        "conversation_id": "fb_conv",
        "message_role": "assistant",
        "message_content": "好的回答",
        "feedback": "like",
    })
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # 验证落库
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT feedback, message_content FROM message_feedback WHERE user_id=4001")
        row = cur.fetchone()
    assert row["feedback"] == "like"
    assert row["message_content"] == "好的回答"


def test_feedback_dislike(client, user_headers):
    resp = client.post("/api/feedback", headers=user_headers, json={
        "conversation_id": "fb1",
        "message_role": "assistant",
        "message_content": "差的回答",
        "feedback": "dislike",
    })
    assert resp.status_code == 200
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT feedback FROM message_feedback WHERE conversation_id=%s", ("fb1",))
        row = cur.fetchone()
    assert row["feedback"] == "dislike"


def test_feedback_cancel_with_empty_string(client, user_headers):
    """空字符串表示取消反馈"""
    # 先 like
    client.post("/api/feedback", headers=user_headers, json={
        "conversation_id": "fb_cancel", "message_role": "assistant",
        "message_content": "x", "feedback": "like",
    })
    # 再取消
    resp = client.post("/api/feedback", headers=user_headers, json={
        "conversation_id": "fb_cancel", "message_role": "assistant",
        "message_content": "x", "feedback": "",
    })
    assert resp.status_code == 200
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT feedback FROM message_feedback WHERE conversation_id=%s", ("fb_cancel",))
        row = cur.fetchone()
    assert row["feedback"] == ""


def test_feedback_invalid_value(client, user_headers):
    resp = client.post("/api/feedback", headers=user_headers, json={
        "conversation_id": "x", "message_role": "assistant",
        "message_content": "x", "feedback": "invalid",
    })
    assert resp.status_code == 400
    assert "非法" in resp.json()["error"]


def test_feedback_upsert(client, user_headers):
    """同一 user+conv+role 反馈被 upsert（不新增行）"""
    for fb in ("like", "dislike", "like"):
        client.post("/api/feedback", headers=user_headers, json={
            "conversation_id": "fb_up", "message_role": "assistant",
            "message_content": "x", "feedback": fb,
        })
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM message_feedback WHERE conversation_id=%s", ("fb_up",))
        cnt = cur.fetchone()["cnt"]
        cur.execute("SELECT feedback FROM message_feedback WHERE conversation_id=%s", ("fb_up",))
        fb = cur.fetchone()["feedback"]
    assert cnt == 1
    assert fb == "like"


def test_feedback_with_message_id(client, user_headers):
    """带 message_id 的反馈"""
    resp = client.post("/api/feedback", headers=user_headers, json={
        "conversation_id": "fb_mid",
        "message_id": 12345,
        "message_role": "assistant",
        "message_content": "内容",
        "feedback": "like",
    })
    assert resp.status_code == 200
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT message_id FROM message_feedback WHERE conversation_id=%s", ("fb_mid",))
        row = cur.fetchone()
    assert row["message_id"] == 12345


def test_feedback_user_isolation(client, user_headers, make_token):
    """不同用户的反馈互不影响"""
    other_headers = {"Authorization": f"Bearer {make_token(4002, 'other')}"}
    client.post("/api/feedback", headers=user_headers, json={
        "conversation_id": "fb_iso", "message_role": "assistant",
        "message_content": "x", "feedback": "like",
    })
    client.post("/api/feedback", headers=other_headers, json={
        "conversation_id": "fb_iso", "message_role": "assistant",
        "message_content": "x", "feedback": "dislike",
    })
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, feedback FROM message_feedback WHERE conversation_id=%s ORDER BY user_id", ("fb_iso",))
        rows = cur.fetchall()
    assert len(rows) == 2
    assert {r["user_id"] for r in rows} == {4001, 4002}


def test_feedback_no_auth(client):
    resp = client.post("/api/feedback", json={
        "conversation_id": "x", "message_role": "assistant",
        "message_content": "x", "feedback": "like",
    })
    assert resp.status_code == 401


def test_feedback_missing_field(client, user_headers):
    resp = client.post("/api/feedback", headers=user_headers, json={
        "conversation_id": "x",
        # 缺 feedback / message_role / message_content
    })
    assert resp.status_code == 422
