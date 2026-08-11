"""chat_service 测试 DB 桩：用 core.db.get_db() 在 lc_chat_test 上执行真实 SQL。

用法（在测试中）::

    from tests.chat_service.db_stubs import install
    install(monkeypatch)  # 把 AIRAGAgent.database.* 替换为真实 DB 实现

之后所有 main.py 端点中 `from AIRAGAgent.database import xxx` 都会拿到这里的真实实现，
端到端验证 SQL 持久化 + 检索 + 软删除 + 分叉等逻辑。
"""
import json
import secrets
import time as _time
from typing import Optional

# 注意：core 在 conftest._load_service_main 中已被加入 sys.path（指向 chat_service 目录）
from core.db import get_db


# ==================== 会话 CRUD ====================

def save_conversation_full(user_id: int, conversation_id: str, title: str, messages: list) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE title=VALUES(title), updated_at=CURRENT_TIMESTAMP",
            (conversation_id, user_id, title),
        )
        for m in (messages or []):
            db_id = m.get("dbId")
            if not db_id:
                continue
            extra = {}
            if m.get("plan"):
                extra["plan"] = m["plan"]
            if m.get("steps"):
                extra["steps"] = m["steps"]
            if extra:
                cur.execute(
                    "UPDATE messages SET extra_json=%s WHERE id=%s AND conversation_id=%s",
                    (json.dumps(extra, ensure_ascii=False), db_id, conversation_id),
                )
        conn.commit()


def get_conversations(user_id: int) -> list:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, created_at, updated_at, pinned, starred, folder, "
            "parent_conversation_id, branch_point_message_id "
            "FROM conversations WHERE user_id=%s AND is_deleted=0 "
            "ORDER BY pinned DESC, updated_at DESC",
            (user_id,),
        )
        rows = cur.fetchall()
    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "title": row["title"],
            "time": row["updated_at"].strftime("%H:%M") if row["updated_at"] else "",
            "updated_at": row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if row["updated_at"] else "",
            "pinned": bool(row.get("pinned", 0)),
            "starred": bool(row.get("starred", 0)),
            "folder": row.get("folder", ""),
            "parent_conversation_id": row.get("parent_conversation_id", ""),
            "branch_point_message_id": row.get("branch_point_message_id", 0),
        })
    return result


def delete_conversation(user_id: int, conversation_id: str) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE conversations SET is_deleted=1 WHERE id=%s AND user_id=%s",
            (conversation_id, user_id),
        )
        conn.commit()


def update_conversation_meta(user_id: int, conversation_id: str, meta: dict) -> bool:
    if not meta:
        return False
    fields = []
    values = []
    for k in ("title", "pinned", "starred", "folder"):
        if k in meta:
            fields.append(f"{k}=%s")
            values.append(meta[k])
    if not fields:
        return False
    values.extend([conversation_id, user_id])
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE conversations SET {', '.join(fields)}, updated_at=CURRENT_TIMESTAMP "
            f"WHERE id=%s AND user_id=%s AND is_deleted=0",
            tuple(values),
        )
        conn.commit()
        return cur.rowcount > 0


def search_conversations(user_id: int, keyword: str, limit: int = 50) -> list:
    kw = f"%{keyword}%"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT c.id, c.title, c.updated_at "
            "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id "
            "WHERE c.user_id=%s AND c.is_deleted=0 "
            "AND (c.title LIKE %s OR m.content LIKE %s) "
            "ORDER BY c.updated_at DESC LIMIT %s",
            (user_id, kw, kw, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "updated_at": r["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if r["updated_at"] else "",
        }
        for r in rows
    ]


def branch_conversation(user_id: int, source_conversation_id: str, branch_from_message_id: int) -> Optional[dict]:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title FROM conversations WHERE id=%s AND user_id=%s AND is_deleted=0",
            (source_conversation_id, user_id),
        )
        src = cur.fetchone()
        if not src:
            return None
        cur.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id=%s AND id <= %s ORDER BY created_at ASC, id ASC",
            (source_conversation_id, branch_from_message_id),
        )
        msgs = cur.fetchall()
        if not msgs:
            return None
        new_id = f"session_{int(_time.time() * 1000)}_{secrets.token_hex(4)}"
        new_title = (src["title"] or "新对话") + " (分支)"
        cur.execute(
            "INSERT INTO conversations (id, user_id, title, parent_conversation_id, branch_point_message_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (new_id, user_id, new_title[:255], source_conversation_id, int(branch_from_message_id)),
        )
        cur.executemany(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            [(new_id, m["role"], m["content"]) for m in msgs],
        )
        conn.commit()
        cur.execute(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id=%s "
            "ORDER BY created_at ASC, id ASC",
            (new_id,),
        )
        new_msgs = cur.fetchall()
        return {
            "id": new_id,
            "title": new_title,
            "parent_conversation_id": source_conversation_id,
            "branch_point_message_id": int(branch_from_message_id),
            "copied_message_count": len(msgs),
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "content": m["content"],
                    "time": m["created_at"].strftime("%H:%M") if m["created_at"] else "",
                }
                for m in new_msgs
            ],
        }


# ==================== 消息反馈 ====================

def save_message_feedback(user_id: int, conversation_id: str, message_role: str,
                          message_content: str, feedback: str, message_id: Optional[int] = None) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO message_feedback (user_id, conversation_id, message_id, message_role, message_content, feedback) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE feedback=VALUES(feedback), message_content=VALUES(message_content)",
            (user_id, conversation_id, message_id, message_role, message_content, feedback),
        )
        conn.commit()
        return True


# ==================== 内部接口 ====================

def get_user_conversations_admin(target_user_id: int) -> list:
    """管理员视角：返回任意用户的会话（含已删除），最近 30 天。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, created_at, updated_at, is_deleted FROM conversations "
            "WHERE user_id=%s AND updated_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) "
            "ORDER BY updated_at DESC",
            (target_user_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else "",
            "updated_at": r["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if r["updated_at"] else "",
            "is_deleted": bool(r["is_deleted"]),
        }
        for r in rows
    ]


# ==================== 安装器 ====================

def install(monkeypatch):
    """把上述真实 DB 实现注入 AIRAGAgent.database（MagicMock）的对应属性。

    main.py 端点中 `from AIRAGAgent.database import xxx as db_xxx` 会拿到这些实现。
    """
    import sys
    db_mod = sys.modules["AIRAGAgent.database"]
    monkeypatch.setattr(db_mod, "save_conversation_full", save_conversation_full)
    monkeypatch.setattr(db_mod, "get_conversations", get_conversations)
    monkeypatch.setattr(db_mod, "delete_conversation", delete_conversation)
    monkeypatch.setattr(db_mod, "update_conversation_meta", update_conversation_meta)
    monkeypatch.setattr(db_mod, "search_conversations", search_conversations)
    monkeypatch.setattr(db_mod, "branch_conversation", branch_conversation)
    monkeypatch.setattr(db_mod, "save_message_feedback", save_message_feedback)
    monkeypatch.setattr(db_mod, "get_user_conversations_admin", get_user_conversations_admin)


# ==================== 辅助：直接写消息（用于测试前置数据）====================

def insert_message(conversation_id: str, role: str, content: str) -> int:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conversation_id, role, content),
        )
        conn.commit()
        return cur.lastrowid


def insert_conversation(user_id: int, conversation_id: str, title: str = "测试会话") -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)",
            (conversation_id, user_id, title),
        )
        conn.commit()
