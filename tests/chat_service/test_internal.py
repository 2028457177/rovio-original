"""chat_service 任务状态 + 内部接口测试。

覆盖：
- GET    /api/tasks/{task_id}                    任务状态查询
- GET    /internal/chat/users/{user_id}/conversations  admin 查任意用户会话
- DELETE /internal/chat/users/{user_id}/cleanup        注销时清理用户数据
"""
import pytest

from tests.chat_service.conftest import chat_main
from tests.chat_service.db_stubs import (
    install, insert_conversation, insert_message,
)


# ==================== GET /api/tasks/{task_id} ====================

def test_task_status_pending(monkeypatch, client):
    monkeypatch.setattr(
        sys_modules_task_queue(), "get_task_status",
        lambda tid: {"task_id": tid, "status": "pending", "progress": 0},
    )
    resp = client.get("/api/tasks/task_001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "task_001"
    assert body["status"] == "pending"


def test_task_status_completed(monkeypatch, client):
    monkeypatch.setattr(
        sys_modules_task_queue(), "get_task_status",
        lambda tid: {"task_id": tid, "status": "completed", "result": {"answer": "done"}},
    )
    resp = client.get("/api/tasks/task_done")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["result"]["answer"] == "done"


def test_task_status_not_found(monkeypatch, client):
    monkeypatch.setattr(
        sys_modules_task_queue(), "get_task_status",
        lambda tid: None,
    )
    resp = client.get("/api/tasks/no_such_task")
    assert resp.status_code == 404
    assert "未找到" in resp.json()["error"]


def test_task_status_no_auth_required(client, monkeypatch):
    """/api/tasks/{id} 不需要 JWT（供前端轮询）"""
    monkeypatch.setattr(
        sys_modules_task_queue(), "get_task_status",
        lambda tid: {"task_id": tid, "status": "running"},
    )
    resp = client.get("/api/tasks/t1")
    assert resp.status_code == 200


# ==================== GET /internal/chat/users/{user_id}/conversations ====================

@pytest.fixture(autouse=True)
def real_db(monkeypatch):
    install(monkeypatch)


def test_internal_get_user_conversations(client):
    """admin_service 调用：取任意用户的会话列表"""
    insert_conversation(5500, "int_conv_1", "用户5500会话1")
    insert_conversation(5500, "int_conv_2", "用户5500会话2")
    insert_conversation(6600, "other_conv", "别人的")
    # 内部接口不需要 token（由 admin_service 带内部凭据调用）
    resp = client.get("/internal/chat/users/5500/conversations")
    assert resp.status_code == 200
    convs = resp.json()["conversations"]
    assert len(convs) == 2
    ids = {c["id"] for c in convs}
    assert ids == {"int_conv_1", "int_conv_2"}


def test_internal_get_user_conversations_empty(client):
    resp = client.get("/internal/chat/users/8888/conversations")
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_internal_get_user_conversations_includes_deleted(client):
    """管理员视角能看到已软删除的会话"""
    insert_conversation(5600, "alive", "存活")
    insert_conversation(5600, "deleted", "已删")
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE conversations SET is_deleted=1 WHERE id=%s", ("deleted",))
        conn.commit()
    resp = client.get("/internal/chat/users/5600/conversations")
    convs = resp.json()["conversations"]
    assert len(convs) == 2
    deleted = next(c for c in convs if c["id"] == "deleted")
    assert deleted["is_deleted"] is True


# ==================== DELETE /internal/chat/users/{user_id}/cleanup ====================

def test_internal_cleanup_user_data(client):
    """注销账号时清理 chat 数据"""
    insert_conversation(7700, "to_clean_conv", "待清理")
    insert_message("to_clean_conv", "user", "问题")
    insert_message("to_clean_conv", "assistant", "回答")
    # 反馈数据
    client.post("/api/feedback", headers={
        "Authorization": f"Bearer {create_token(7700)}"
    }, json={
        "conversation_id": "to_clean_conv",
        "message_role": "assistant",
        "message_content": "回答",
        "feedback": "like",
    })

    resp = client.delete("/internal/chat/users/7700/cleanup")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    # 验证所有数据被清理
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM conversations WHERE user_id=7700")
        assert cur.fetchone()["cnt"] == 0
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM messages m JOIN conversations c "
            "ON m.conversation_id=c.id WHERE c.user_id=7700"
        )
        assert cur.fetchone()["cnt"] == 0
        cur.execute("SELECT COUNT(*) AS cnt FROM message_feedback WHERE user_id=7700")
        assert cur.fetchone()["cnt"] == 0


def test_internal_cleanup_idempotent(client):
    """清理不存在的用户不报错"""
    resp = client.delete("/internal/chat/users/99999/cleanup")
    assert resp.status_code == 200


def test_internal_cleanup_preserves_other_users(client):
    """清理用户 A 不影响用户 B"""
    insert_conversation(8800, "a_conv", "A 的会话")
    insert_conversation(8801, "b_conv", "B 的会话")
    insert_message("b_conv", "user", "B 的问题")

    resp = client.delete("/internal/chat/users/8800/cleanup")
    assert resp.status_code == 200

    # B 的数据仍在
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM conversations WHERE user_id=8801")
        assert cur.fetchone()["cnt"] == 1
        cur.execute("SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id='b_conv'")
        assert cur.fetchone()["cnt"] == 1


# ==================== 辅助 ====================

def sys_modules_task_queue():
    import sys
    return sys.modules["AIRAGAgent.infrastructure.task_queue"]


def create_token(user_id):
    from core.jwt_auth import create_access_token
    return create_access_token(user_id, f"user{user_id}", "user")
