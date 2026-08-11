"""chat_service 会话 CRUD / 搜索 / 分叉 / 元数据测试。"""
import pytest

from tests.chat_service.conftest import chat_main, make_headers
from tests.chat_service.db_stubs import (
    install, insert_conversation, insert_message,
)


@pytest.fixture(autouse=True)
def real_db(monkeypatch):
    """每个测试用真实 DB 桩替换 AIRAGAgent.database 的 MagicMock。"""
    install(monkeypatch)


# ==================== 列表 ====================

def test_list_empty(client, user_headers):
    resp = client.get("/api/conversations", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_list_returns_user_own_only(client, user_headers, make_token):
    # user 4001 有一条会话
    insert_conversation(4001, "conv_a", "会话A")
    # user 4002 的会话不应被 4001 看到
    insert_conversation(4002, "conv_b", "会话B")
    resp = client.get("/api/conversations", headers=user_headers)
    assert resp.status_code == 200
    convs = resp.json()["conversations"]
    assert len(convs) == 1
    assert convs[0]["id"] == "conv_a"
    assert convs[0]["title"] == "会话A"


def test_list_excludes_deleted(client, user_headers):
    insert_conversation(4001, "alive", "存活会话")
    insert_conversation(4001, "dead", "已删会话")
    # 直接 SQL 软删除
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE conversations SET is_deleted=1 WHERE id=%s", ("dead",))
        conn.commit()
    resp = client.get("/api/conversations", headers=user_headers)
    convs = resp.json()["conversations"]
    assert len(convs) == 1
    assert convs[0]["id"] == "alive"


def test_list_pinned_first(client, user_headers):
    insert_conversation(4001, "later", "后建普通")
    insert_conversation(4001, "pinned_one", "置顶会话")
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE conversations SET pinned=1 WHERE id=%s", ("pinned_one",))
        conn.commit()
    resp = client.get("/api/conversations", headers=user_headers)
    convs = resp.json()["conversations"]
    assert convs[0]["id"] == "pinned_one"
    assert convs[0]["pinned"] is True


# ==================== 保存 ====================

def test_save_new_conversation(client, user_headers):
    resp = client.post("/api/conversations", headers=user_headers, json={
        "id": "new_conv_1",
        "title": "我的新会话",
        "messages": [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么可以帮你？"},
        ],
        "time": "12:00",
    })
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # 验证落库
    resp2 = client.get("/api/conversations", headers=user_headers)
    convs = resp2.json()["conversations"]
    assert any(c["id"] == "new_conv_1" and c["title"] == "我的新会话" for c in convs)


def test_save_upsert_title(client, user_headers):
    # 先建一条
    client.post("/api/conversations", headers=user_headers, json={
        "id": "upsert_conv", "title": "原标题", "messages": [],
    })
    # 改标题再保存
    client.post("/api/conversations", headers=user_headers, json={
        "id": "upsert_conv", "title": "新标题", "messages": [],
    })
    resp = client.get("/api/conversations", headers=user_headers)
    convs = resp.json()["conversations"]
    assert len(convs) == 1
    assert convs[0]["title"] == "新标题"


def test_save_with_plan_extra(client, user_headers):
    """带 plan/steps 附属数据的消息保存（extra_json 落库）"""
    # 先插一条 assistant 消息拿 dbId
    insert_conversation(4001, "plan_conv", "Plan 会话")
    msg_id = insert_message("plan_conv", "assistant", "Plan 结果")
    resp = client.post("/api/conversations", headers=user_headers, json={
        "id": "plan_conv",
        "title": "Plan 会话",
        "messages": [
            {"dbId": msg_id, "plan": {"goal": "测试"}, "steps": {"0": {"status": "done"}}},
        ],
    })
    assert resp.status_code == 200
    # 验证 extra_json 写入
    from core.db import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT extra_json FROM messages WHERE id=%s", (msg_id,))
        row = cur.fetchone()
    assert row is not None
    assert row["extra_json"]


def test_save_invalid_body(client, user_headers):
    """缺字段应 422"""
    resp = client.post("/api/conversations", headers=user_headers, json={"id": "x"})
    assert resp.status_code == 422


# ==================== 删除 ====================

def test_delete_conversation(client, user_headers):
    insert_conversation(4001, "to_delete", "待删除")
    resp = client.delete("/api/conversations/to_delete", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # 列表中不再出现
    resp2 = client.get("/api/conversations", headers=user_headers)
    assert all(c["id"] != "to_delete" for c in resp2.json()["conversations"])


def test_delete_other_users_conversation(client, user_headers, make_token):
    """删别人的会话不应影响对方（user_id 限定）"""
    insert_conversation(4002, "other_conv", "别人的")
    resp = client.delete("/api/conversations/other_conv", headers=user_headers)
    assert resp.status_code == 200  # 软删除不报错
    # 但用 4002 token 查仍能看到
    other_headers = make_headers(make_token(4002, "other"))
    resp2 = client.get("/api/conversations", headers=other_headers)
    assert any(c["id"] == "other_conv" for c in resp2.json()["conversations"])


def test_delete_nonexistent(client, user_headers):
    resp = client.delete("/api/conversations/no_such_conv", headers=user_headers)
    assert resp.status_code == 200  # 软删除幂等


# ==================== 元数据更新 ====================

def test_update_meta_title(client, user_headers):
    insert_conversation(4001, "meta_conv", "原标题")
    resp = client.patch("/api/conversations/meta_conv/meta", headers=user_headers, json={
        "title": "改后标题",
    })
    assert resp.status_code == 200
    resp2 = client.get("/api/conversations", headers=user_headers)
    conv = next(c for c in resp2.json()["conversations"] if c["id"] == "meta_conv")
    assert conv["title"] == "改后标题"


def test_update_meta_pinned(client, user_headers):
    insert_conversation(4001, "pin_conv", "测试")
    resp = client.patch("/api/conversations/pin_conv/meta", headers=user_headers, json={
        "pinned": 1,
    })
    assert resp.status_code == 200
    resp2 = client.get("/api/conversations", headers=user_headers)
    conv = next(c for c in resp2.json()["conversations"] if c["id"] == "pin_conv")
    assert conv["pinned"] is True


def test_update_meta_empty_body(client, user_headers):
    insert_conversation(4001, "empty_meta", "测试")
    resp = client.patch("/api/conversations/empty_meta/meta", headers=user_headers, json={})
    assert resp.status_code == 400
    assert "无可更新" in resp.json()["error"]


def test_update_meta_nonexistent(client, user_headers):
    resp = client.patch("/api/conversations/no_such/meta", headers=user_headers, json={"title": "x"})
    assert resp.status_code == 404


def test_update_meta_other_user(client, user_headers):
    """改别人的会话元数据应 404"""
    insert_conversation(4002, "other_meta", "别人的")
    resp = client.patch("/api/conversations/other_meta/meta", headers=user_headers, json={"title": "hacked"})
    assert resp.status_code == 404


# ==================== 搜索 ====================

def test_search_empty_keyword(client, user_headers):
    resp = client.get("/api/conversations/search?q=", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_search_by_title(client, user_headers):
    insert_conversation(4001, "s1", "Python 学习笔记")
    insert_conversation(4001, "s2", "Java 入门")
    resp = client.get("/api/conversations/search?q=Python", headers=user_headers)
    assert resp.status_code == 200
    results = resp.json()["conversations"]
    assert len(results) == 1
    assert results[0]["id"] == "s1"


def test_search_by_message_content(client, user_headers):
    insert_conversation(4001, "m1", "会话1")
    insert_message("m1", "user", "今天聊一下 FastAPI 框架")
    insert_conversation(4001, "m2", "会话2")
    insert_message("m2", "user", "其他无关内容")
    resp = client.get("/api/conversations/search?q=FastAPI", headers=user_headers)
    results = resp.json()["conversations"]
    assert len(results) == 1
    assert results[0]["id"] == "m1"


def test_search_too_long_keyword(client, user_headers):
    resp = client.get("/api/conversations/search?q=" + "a" * 101, headers=user_headers)
    assert resp.status_code == 400
    assert "过长" in resp.json()["error"]


def test_search_user_isolation(client, user_headers, make_token):
    insert_conversation(4002, "other_s", "别人搜索词unique_xyz")
    insert_conversation(4001, "my_s", "我的搜索词unique_xyz")
    resp = client.get("/api/conversations/search?q=unique_xyz", headers=user_headers)
    results = resp.json()["conversations"]
    assert len(results) == 1
    assert results[0]["id"] == "my_s"


# ==================== 分叉 ====================

def test_branch_success(client, user_headers):
    insert_conversation(4001, "src_conv", "源会话")
    msg1 = insert_message("src_conv", "user", "问题1")
    msg2 = insert_message("src_conv", "assistant", "回答1")
    msg3 = insert_message("src_conv", "user", "问题2")
    insert_message("src_conv", "assistant", "回答2")
    # 在 msg2 处分叉
    resp = client.post("/api/conversations/src_conv/branch", headers=user_headers, json={
        "branch_from_message_id": msg2,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["parent_conversation_id"] == "src_conv"
    assert body["branch_point_message_id"] == msg2
    assert body["copied_message_count"] == 2  # msg1, msg2
    assert len(body["messages"]) == 2
    # 验证新会话出现在列表中
    resp2 = client.get("/api/conversations", headers=user_headers)
    new_conv = next(c for c in resp2.json()["conversations"] if c["id"] == body["id"])
    assert new_conv["parent_conversation_id"] == "src_conv"
    assert "分支" in new_conv["title"]


def test_branch_invalid_message_id(client, user_headers):
    insert_conversation(4001, "bad_branch", "测试")
    resp = client.post("/api/conversations/bad_branch/branch", headers=user_headers, json={
        "branch_from_message_id": 0,
    })
    assert resp.status_code == 400
    assert "非法" in resp.json()["error"]


def test_branch_nonexistent_conversation(client, user_headers):
    resp = client.post("/api/conversations/no_such/branch", headers=user_headers, json={
        "branch_from_message_id": 1,
    })
    assert resp.status_code == 404


def test_branch_no_messages(client, user_headers):
    insert_conversation(4001, "empty_conv", "空会话")
    resp = client.post("/api/conversations/empty_conv/branch", headers=user_headers, json={
        "branch_from_message_id": 1,
    })
    assert resp.status_code == 404


def test_branch_other_user_conversation(client, user_headers):
    insert_conversation(4002, "other_branch", "别人的")
    msg = insert_message("other_branch", "user", "x")
    resp = client.post("/api/conversations/other_branch/branch", headers=user_headers, json={
        "branch_from_message_id": msg,
    })
    assert resp.status_code == 404
