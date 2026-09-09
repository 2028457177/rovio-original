import hashlib
import os
import secrets
from datetime import datetime
from typing import Optional
from AIRAGAgent.database.connection import get_db
from AIRAGAgent.utils.logger_handler import logger


def save_conversation_full(user_id: int, conversation_id: str, title: str, messages: list) -> None:
    """保存会话：更新标题，并把每条消息的 extra_json（含 DeepAgent plan/steps）upsert 进去。

    消息正文已由 save_message() 在流式对话时逐条持久化，此处只补写 plan/steps 等附属数据。
    前端传入的 messages 里若含 plan/steps 字段，则序列化为 extra_json 存入。
    """
    import json as _json
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO conversations (id, user_id, title)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE title = VALUES(title), updated_at = CURRENT_TIMESTAMP
            """,
            (conversation_id, user_id, title)
        )
        # 补写每条 assistant 消息的 extra_json（plan/steps）
        # 用 dbId（后端真实 id）定位；前端没 dbId 的消息跳过
        for m in (messages or []):
            db_id = m.get("dbId")
            if not db_id:
                continue
            plan = m.get("plan")
            steps = m.get("steps")
            if not plan and not steps:
                continue
            extra = {}
            if plan:
                extra["plan"] = plan
            if steps:
                # steps 是 {idx: {...}} 的对象，转存
                extra["steps"] = steps
            try:
                cursor.execute(
                    "UPDATE messages SET extra_json = %s WHERE id = %s AND conversation_id = %s",
                    (_json.dumps(extra, ensure_ascii=False), db_id, conversation_id)
                )
            except Exception:
                pass
        conn.commit()


def get_conversations(user_id: int) -> list:
    """查询指定用户的全部会话（含各会话消息），按置顶和更新时间降序返回。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at, c.pinned, c.starred, c.folder,
                   c.parent_conversation_id, c.branch_point_message_id
            FROM conversations c
            WHERE c.user_id = %s AND c.is_deleted = 0
            ORDER BY c.pinned DESC, c.updated_at DESC
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            conv = {
                "id": row["id"],
                "title": row["title"],
                "time": row["updated_at"].strftime("%H:%M") if row["updated_at"] else "",
                "updated_at": row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if row["updated_at"] else "",
                "pinned": bool(row.get("pinned", 0)),
                "starred": bool(row.get("starred", 0)),
                "folder": row.get("folder", "") or "",
                "parent_conversation_id": row.get("parent_conversation_id", "") or "",
                "branch_point_message_id": int(row.get("branch_point_message_id", 0) or 0),
                "messages": [],
            }
            cursor.execute(
                "SELECT id, role, content, created_at, extra_json FROM messages WHERE conversation_id = %s ORDER BY created_at ASC",
                (row["id"],)
            )
            messages = cursor.fetchall()
            for msg in messages:
                entry = {
                    "id": msg["id"],
                    "role": msg["role"],
                    "content": msg["content"],
                    "time": msg["created_at"].strftime("%H:%M") if msg["created_at"] else "",
                }
                # 反序列化 extra_json（DeepAgent plan/steps）
                raw_extra = msg.get("extra_json")
                if raw_extra:
                    try:
                        import json as _json
                        extra = _json.loads(raw_extra)
                        if isinstance(extra, dict):
                            if extra.get("plan"):
                                entry["plan"] = extra["plan"]
                            if extra.get("steps"):
                                entry["steps"] = extra["steps"]
                    except Exception:
                        pass
                conv["messages"].append(entry)
            result.append(conv)
        return result


def delete_user_admin(target_user_id: int) -> bool:
    """管理员注销用户（级联删除其会话和消息）"""
    with get_db() as conn:
        cursor = conn.cursor()
        # 不允许删除管理员
        cursor.execute("SELECT role FROM users WHERE id = %s", (target_user_id,))
        row = cursor.fetchone()
        if not row or row["role"] == "admin":
            return False
        # 级联：先删消息，再删会话，最后删用户
        cursor.execute(
            "DELETE m FROM messages m JOIN conversations c ON m.conversation_id = c.id WHERE c.user_id = %s",
            (target_user_id,)
        )
        cursor.execute("DELETE FROM conversations WHERE user_id = %s", (target_user_id,))
        cursor.execute("DELETE FROM login_devices WHERE user_id = %s", (target_user_id,))
        cursor.execute("DELETE FROM message_feedback WHERE user_id = %s", (target_user_id,))
        cursor.execute("DELETE FROM users WHERE id = %s", (target_user_id,))
        conn.commit()
        return cursor.rowcount > 0


def reset_user_password(target_user_id: int, new_password: str) -> bool:
    """管理员重置用户密码"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, role FROM users WHERE id = %s", (target_user_id,))
        row = cursor.fetchone()
        if not row or row["role"] == "admin":
            return False
        password_hash = _hash_password(new_password)
        cursor.execute(
            "UPDATE users SET password_hash = %s, last_password_changed = CURRENT_TIMESTAMP WHERE id = %s",
            (password_hash, target_user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_conversation(user_id: int, conversation_id: str) -> Optional[dict]:
    """按用户ID和会话ID查询未删除的会话（含消息列表）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title FROM conversations WHERE id = %s AND user_id = %s AND is_deleted = 0",
            (conversation_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return None
        conv = {"id": row["id"], "title": row["title"], "messages": []}
        cursor.execute(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = %s ORDER BY created_at ASC",
            (conversation_id,)
        )
        for msg in cursor.fetchall():
            conv["messages"].append({
                "id": msg["id"],
                "role": msg["role"],
                "content": msg["content"],
                "time": msg["created_at"].strftime("%H:%M") if msg["created_at"] else "",
            })
        return conv


def delete_conversation(user_id: int, conversation_id: str) -> None:
    """软删除：标记 is_deleted=1，管理员仍可查看"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE conversations SET is_deleted = 1 WHERE id = %s AND user_id = %s",
            (conversation_id, user_id)
        )


def _generate_title(content: str) -> str:
    """从消息内容生成标题：取前30个字符，超出则加省略号"""
    return content[:30] + "..." if len(content) > 30 else content


def save_message(user_id: int, conversation_id: str, role: str, content: str) -> int:
    """保存一条消息，返回新消息的自增 id（用于前端分支定位等场景）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM conversations WHERE id = %s", (conversation_id,))
        row = cursor.fetchone()

        if row is None:
            # 新会话，从首条消息自动生成标题
            title = _generate_title(content)
            cursor.execute(
                "INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)",
                (conversation_id, user_id, title)
            )
        else:
            cursor.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP, is_deleted = 0 WHERE id = %s",
                (conversation_id,)
            )

        cursor.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conversation_id, role, content)
        )
        new_id = cursor.lastrowid
        conn.commit()
        return int(new_id) if new_id else 0


def get_messages_by_conversation(user_id: int, conversation_id: str) -> list:
    """查询指定会话的全部消息（按时间升序），会话不存在时返回空列表。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id)
        )
        if not cursor.fetchone():
            return []
        cursor.execute(
            "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY created_at ASC",
            (conversation_id,)
        )
        return [{"role": row["role"], "content": row["content"]} for row in cursor.fetchall()]


def get_session_messages(user_id: int, session_id: str) -> list:
    """获取指定会话的全部消息列表。"""
    return get_messages_by_conversation(user_id, session_id)


def clear_session(user_id: int, session_id: str) -> None:
    """删除指定会话的全部消息。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM messages WHERE conversation_id = %s",
            (session_id,)
        )


def truncate_session_messages(user_id: int, conversation_id: str, keep_count: int) -> None:
    """保留会话中最早的 keep_count 条消息，删除其余。

    用于"重新生成 / 编辑后重发"时把后端历史回滚到指定位置，避免历史被污染。
    按 (created_at, id) 升序取前 keep_count 条作为保留集，保证消息顺序稳定。
    """
    from AIRAGAgent.infrastructure.session_cache import invalidate_session

    if keep_count < 0:
        keep_count = 0
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM messages WHERE conversation_id = %s ORDER BY created_at ASC, id ASC LIMIT %s",
            (conversation_id, keep_count)
        )
        keep_ids = [row["id"] for row in cursor.fetchall()]
        if keep_ids:
            placeholders = ",".join(["%s"] * len(keep_ids))
            cursor.execute(
                f"DELETE FROM messages WHERE conversation_id = %s AND id NOT IN ({placeholders})",
                [conversation_id] + keep_ids
            )
        else:
            cursor.execute("DELETE FROM messages WHERE conversation_id = %s", (conversation_id,))
        conn.commit()
    invalidate_session(user_id, conversation_id)


# ==================== 会话元数据：置顶 / 收藏 / 文件夹 / 搜索 ====================

def update_conversation_meta(user_id: int, conversation_id: str, meta: dict) -> bool:
    """更新会话元数据：title / pinned / starred / folder"""
    with get_db() as conn:
        cursor = conn.cursor()
        # 验证会话属于该用户
        cursor.execute(
            "SELECT id FROM conversations WHERE id = %s AND user_id = %s AND is_deleted = 0",
            (conversation_id, user_id)
        )
        if not cursor.fetchone():
            return False

        sets = []
        params = []
        if "title" in meta:
            sets.append("title = %s")
            params.append(meta["title"][:255])
        if "pinned" in meta:
            sets.append("pinned = %s")
            params.append(1 if meta["pinned"] else 0)
        if "starred" in meta:
            sets.append("starred = %s")
            params.append(1 if meta["starred"] else 0)
        if "folder" in meta:
            sets.append("folder = %s")
            params.append((meta["folder"] or "")[:100])

        if not sets:
            return False

        params.append(conversation_id)
        params.append(user_id)
        cursor.execute(
            f"UPDATE conversations SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP "
            f"WHERE id = %s AND user_id = %s",
            tuple(params)
        )
        conn.commit()
        return cursor.rowcount > 0


def search_conversations(user_id: int, keyword: str, limit: int = 50) -> list:
    """会话全文检索：标题 + 消息内容"""
    with get_db() as conn:
        cursor = conn.cursor()
        like = f"%{keyword}%"
        # 通过 messages 表的内容反查会话，或直接匹配标题
        cursor.execute(
            """
            SELECT DISTINCT c.id, c.title, c.created_at, c.updated_at, c.pinned, c.starred, c.folder,
                   c.parent_conversation_id, c.branch_point_message_id
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.user_id = %s AND c.is_deleted = 0
              AND (c.title LIKE %s OR m.content LIKE %s)
            ORDER BY c.pinned DESC, c.updated_at DESC
            LIMIT %s
            """,
            (user_id, like, like, limit)
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            # 取最近一条消息做预览
            cursor.execute(
                "SELECT role, content, created_at FROM messages WHERE conversation_id = %s ORDER BY created_at DESC LIMIT 1",
                (row["id"],)
            )
            last = cursor.fetchone()
            result.append({
                "id": row["id"],
                "title": row["title"],
                "time": row["updated_at"].strftime("%H:%M") if row["updated_at"] else "",
                "updated_at": row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if row["updated_at"] else "",
                "pinned": bool(row.get("pinned", 0)),
                "starred": bool(row.get("starred", 0)),
                "folder": row.get("folder", "") or "",
                "parent_conversation_id": row.get("parent_conversation_id", "") or "",
                "branch_point_message_id": int(row.get("branch_point_message_id", 0) or 0),
                "preview": (last["content"][:100] + "...") if last and len(last["content"]) > 100 else (last["content"] if last else ""),
                "messages": []
            })
        return result


# ==================== 对话分支 ====================

def branch_conversation(user_id: int, source_conversation_id: str, branch_from_message_id: int) -> Optional[dict]:
    """在指定消息处分叉出一条新会话。

    将源会话中 branch_from_message_id 及之前的所有消息复制到新会话，
    新会话记录 parent_conversation_id 和 branch_point_message_id 以便前端展示来源。

    Args:
        user_id: 当前用户 ID
        source_conversation_id: 源会话 ID
        branch_from_message_id: 分叉点的消息 ID（该消息及之前的内容会被复制）

    Returns:
        新会话信息字典；失败返回 None
    """
    import time as _time
    with get_db() as conn:
        cursor = conn.cursor()
        # 1. 校验源会话归属
        cursor.execute(
            "SELECT id, title FROM conversations WHERE id = %s AND user_id = %s AND is_deleted = 0",
            (source_conversation_id, user_id)
        )
        src = cursor.fetchone()
        if not src:
            return None

        # 2. 取分叉点及之前的消息（按 created_at, id 升序）
        cursor.execute(
            """
            SELECT id, role, content, created_at FROM messages
            WHERE conversation_id = %s AND id <= %s
            ORDER BY created_at ASC, id ASC
            """,
            (source_conversation_id, branch_from_message_id)
        )
        msgs_to_copy = cursor.fetchall()
        if not msgs_to_copy:
            return None

        # 3. 生成新会话 ID
        new_conv_id = f"session_{int(_time.time() * 1000)}_{secrets.token_hex(4)}"
        new_title = (src["title"] or "新对话") + " (分支)"

        # 4. 创建新会话
        cursor.execute(
            """
            INSERT INTO conversations (id, user_id, title, parent_conversation_id, branch_point_message_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (new_conv_id, user_id, new_title[:255], source_conversation_id, int(branch_from_message_id))
        )

        # 5. 批量复制消息到新会话（保留原 role/content/相对时间顺序）
        # 使用 executemany 批量插入
        copy_rows = [(new_conv_id, m["role"], m["content"]) for m in msgs_to_copy]
        cursor.executemany(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            copy_rows
        )
        conn.commit()

        # 6. 读取新会话的消息（含新生成的 id），回传给前端免二次请求
        cursor.execute(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = %s ORDER BY created_at ASC, id ASC",
            (new_conv_id,)
        )
        new_msgs = cursor.fetchall()
        return {
            "id": new_conv_id,
            "title": new_title,
            "parent_conversation_id": source_conversation_id,
            "branch_point_message_id": int(branch_from_message_id),
            "copied_message_count": len(msgs_to_copy),
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
    """保存用户对 AI 消息的反馈（like / dislike / 空=取消）"""
    with get_db() as conn:
        cursor = conn.cursor()
        if not feedback:
            # 取消反馈：删除已有记录
            cursor.execute(
                "DELETE FROM message_feedback WHERE user_id = %s AND conversation_id = %s AND message_role = %s",
                (user_id, conversation_id, message_role)
            )
            conn.commit()
            return True
        cursor.execute(
            """
            INSERT INTO message_feedback (user_id, conversation_id, message_id, message_role, message_content, feedback)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE feedback = VALUES(feedback), created_at = CURRENT_TIMESTAMP
            """,
            (user_id, conversation_id, message_id, message_role, message_content[:5000], feedback)
        )
        conn.commit()
        return True


def get_feedback_stats() -> dict:
    """获取反馈统计（管理员视图）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT feedback, COUNT(*) AS cnt
            FROM message_feedback
            GROUP BY feedback
            """
        )
        return {row["feedback"]: row["cnt"] for row in cursor.fetchall()}


# ==================== 用户认证相关 ====================

def _hash_password(password: str) -> str:
    """SHA-256 加盐哈希密码"""
    salt = os.urandom(32)
    hash_obj = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt.hex() + ":" + hash_obj.hex()


def _hash_security_answer(answer: str) -> str:
    """密保答案哈希（与密码同样的算法，便于不可逆存储）"""
    return _hash_password(answer.strip().lower())


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码是否匹配"""
    try:
        salt_hex, hash_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        hash_obj = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return hash_obj.hex() == hash_hex
    except Exception:
        return False


def verify_security_answer(answer: str, stored_hash: str) -> bool:
    """校验密保答案是否与已存储的哈希匹配。"""
    return verify_password(answer.strip().lower(), stored_hash)


def create_user(username: str, password: str, display_name: str = "") -> Optional[dict]:
    """创建用户，返回用户信息字典；用户名已存在时返回 None"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            return None

        password_hash = _hash_password(password)
        cursor.execute(
            "INSERT INTO users (username, password_hash, display_name) VALUES (%s, %s, %s)",
            (username, password_hash, display_name or username)
        )
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "username": username,
            "display_name": display_name or username,
        }


def get_user_by_username(username: str) -> Optional[dict]:
    """按用户名查询用户完整信息（含密码哈希），不存在返回 None。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, password_hash, display_name, role, created_at,
                   avatar_url, email, security_question, security_answer_hash,
                   last_password_changed
            FROM users WHERE username = %s
            """,
            (username,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "password_hash": row["password_hash"],
            "display_name": row["display_name"],
            "role": row["role"],
            "created_at": row["created_at"],
            "avatar_url": row.get("avatar_url") or "",
            "email": row.get("email") or "",
            "security_question": row.get("security_question") or "",
            "security_answer_hash": row.get("security_answer_hash") or "",
            "last_password_changed": row["last_password_changed"].strftime("%Y-%m-%d %H:%M:%S") if row.get("last_password_changed") else "",
        }


def get_user_by_id(user_id: int) -> Optional[dict]:
    """按用户ID查询用户信息，不存在返回 None。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, display_name, role, created_at,
                   avatar_url, email, security_question, last_password_changed
            FROM users WHERE id = %s
            """,
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row["created_at"] else "",
            "avatar_url": row.get("avatar_url") or "",
            "email": row.get("email") or "",
            "security_question": row.get("security_question") or "",
            "has_security_question": bool(row.get("security_question")),
            "last_password_changed": row["last_password_changed"].strftime("%Y-%m-%d %H:%M:%S") if row.get("last_password_changed") else "",
        }


# ==================== 用户自助：密码 / 资料 / 头像 ====================

def change_password(user_id: int, old_password: str, new_password: str) -> bool:
    """修改密码：校验旧密码"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        if not verify_password(old_password, row["password_hash"]):
            return False
        new_hash = _hash_password(new_password)
        cursor.execute(
            "UPDATE users SET password_hash = %s, last_password_changed = CURRENT_TIMESTAMP WHERE id = %s",
            (new_hash, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def update_user_profile(user_id: int, display_name: Optional[str] = None, email: Optional[str] = None) -> Optional[dict]:
    """更新昵称 / 邮箱"""
    with get_db() as conn:
        cursor = conn.cursor()
        sets = []
        params = []
        if display_name is not None:
            if not display_name.strip():
                return None
            sets.append("display_name = %s")
            params.append(display_name.strip()[:100])
        if email is not None:
            sets.append("email = %s")
            params.append(email.strip()[:100])
        if not sets:
            return get_user_by_id(user_id)
        params.append(user_id)
        cursor.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE id = %s",
            tuple(params)
        )
        conn.commit()
        return get_user_by_id(user_id)


def update_avatar_url(user_id: int, avatar_url: str) -> bool:
    """更新用户头像 URL，返回是否更新成功。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET avatar_url = %s WHERE id = %s",
            (avatar_url, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


# ==================== 课表设置（按用户隔离） ====================

def update_schedule(user_id: int, file_path: str, start_date: Optional[str]) -> bool:
    """更新用户课表：写入文件相对路径 + 开学日期 + 上传时间。
    file_path: 相对 UPLOAD_DIR 的路径，如 'schedules/schedule_42.xlsx'
    start_date: 'YYYY-MM-DD' 字符串或 None
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET schedule_file = %s, schedule_start_date = %s, "
            "schedule_uploaded_at = CURRENT_TIMESTAMP WHERE id = %s",
            (file_path, start_date, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def update_schedule_start_date(user_id: int, start_date: Optional[str]) -> bool:
    """仅修改开学日期（不重传文件）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET schedule_start_date = %s WHERE id = %s",
            (start_date, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def clear_schedule(user_id: int) -> Optional[str]:
    """清除用户课表设置，返回被清除的旧文件相对路径（供调用方删物理文件）。
    返回 None 表示原本就没上传过。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT schedule_file FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        old_path = (row.get("schedule_file") if row else "") or ""
        cursor.execute(
            "UPDATE users SET schedule_file = '', schedule_start_date = NULL, "
            "schedule_uploaded_at = NULL WHERE id = %s",
            (user_id,)
        )
        conn.commit()
        return old_path or None


def get_schedule_settings(user_id: int) -> dict:
    """读取当前用户的课表设置，供前端回显和 agent_tools 内部使用。

    数据源：user_service 独立库 lc_user.user_schedules（前端上传课表写入的位置）。
    读取失败时回退旧版 AIRAGAgent 库 users 表（兼容历史数据）。

    返回:
        {
            uploaded: bool,
            file_path: str | None,        # 相对 UPLOAD_DIR 的路径
            start_date: str | None,       # 'YYYY-MM-DD'
            uploaded_at: str | None,      # 'YYYY-MM-DD HH:MM:SS'
            schedule_url: str | None,     # 前端下载用的 URL
            parsed: dict | None,          # 上传时预解析的课表 {星期: [课程条目]}，查询免读 Excel
        }
    """
    # 1. 优先从 lc_user.user_schedules 读取（与上传端一致）
    try:
        import json
        import os
        import pymysql
        svc_conn = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("USER_DB", "lc_user"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        with svc_conn.cursor() as cursor:
            cursor.execute(
                "SELECT file_path, start_date, uploaded_at, parsed_courses "
                "FROM user_schedules WHERE user_id = %s",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                file_path = (row.get("file_path") or "").strip()
                uploaded = bool(file_path)
                schedule_url = f"/api/schedules/{file_path.split('/')[-1]}" if uploaded else None
                raw_parsed = row.get("parsed_courses")
                if isinstance(raw_parsed, str):
                    try:
                        raw_parsed = json.loads(raw_parsed)
                    except (TypeError, ValueError):
                        raw_parsed = None
                return {
                    "uploaded": uploaded,
                    "file_path": file_path or None,
                    "start_date": row["start_date"].strftime("%Y-%m-%d") if row.get("start_date") else None,
                    "uploaded_at": row["uploaded_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("uploaded_at") else None,
                    "schedule_url": schedule_url,
                    "parsed": raw_parsed or None,
                }
    except Exception as e:
        logger.warning(f"[get_schedule_settings] 从 lc_user.user_schedules 读取失败，回退旧表：{e}")

    # 2. 回退：旧版 AIRAGAgent 库 users 表（含 schedule_file 列时）
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT schedule_file, schedule_start_date, schedule_uploaded_at "
            "FROM users WHERE id = %s",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"uploaded": False, "file_path": None, "start_date": None,
                    "uploaded_at": None, "schedule_url": None, "parsed": None}
        file_path = (row.get("schedule_file") or "").strip()
        uploaded = bool(file_path)
        # file_path 形如 'schedules/schedule_42.xlsx' → 提取文件名拼下载 URL
        schedule_url = f"/api/schedules/{file_path.split('/')[-1]}" if uploaded else None
        return {
            "uploaded": uploaded,
            "file_path": file_path or None,
            "start_date": row["schedule_start_date"].strftime("%Y-%m-%d") if row.get("schedule_start_date") else None,
            "uploaded_at": row["schedule_uploaded_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("schedule_uploaded_at") else None,
            "schedule_url": schedule_url,
            "parsed": None,
        }


# ==================== 密保 / 找回密码 ====================

def set_security_question(user_id: int, question: str, answer: str) -> bool:
    """设置 / 修改密保问题"""
    if not question.strip() or not answer.strip():
        return False
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET security_question = %s, security_answer_hash = %s WHERE id = %s",
            (question.strip()[:200], _hash_security_answer(answer), user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_security_question_by_username(username: str) -> Optional[dict]:
    """找回密码第一步：返回密保问题（不含答案）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, security_question, security_answer_hash FROM users WHERE username = %s AND role != 'admin'",
            (username,)
        )
        row = cursor.fetchone()
        if not row or not row["security_question"] or not row["security_answer_hash"]:
            return None
        return {
            "user_id": row["id"],
            "username": row["username"],
            "question": row["security_question"]
        }


def reset_password_by_security_answer(username: str, answer: str, new_password: str) -> bool:
    """找回密码第二步：校验密保答案后重置密码"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, security_answer_hash FROM users WHERE username = %s AND role != 'admin'",
            (username,)
        )
        row = cursor.fetchone()
        if not row or not row["security_answer_hash"]:
            return False
        if not verify_security_answer(answer, row["security_answer_hash"]):
            return False
        new_hash = _hash_password(new_password)
        cursor.execute(
            "UPDATE users SET password_hash = %s, last_password_changed = CURRENT_TIMESTAMP WHERE id = %s",
            (new_hash, row["id"])
        )
        conn.commit()
        return cursor.rowcount > 0


# ==================== 登录设备管理 ====================

def create_login_device(user_id: int, device_token: str, user_agent: str, ip: str) -> None:
    """登录时记录设备信息"""
    with get_db() as conn:
        cursor = conn.cursor()
        # 解析设备类型
        ua = (user_agent or "").lower()
        if "mobile" in ua or "android" in ua or "iphone" in ua:
            device_type = "mobile"
        elif "ipad" in ua or "tablet" in ua:
            device_type = "tablet"
        else:
            device_type = "desktop"
        # 简化 OS / 浏览器提取
        os_name = _parse_os(user_agent)
        browser = _parse_browser(user_agent)
        cursor.execute(
            """
            INSERT INTO login_devices (device_token, user_id, device_type, os, browser, ip, user_agent, last_active_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE ip = VALUES(ip), user_agent = VALUES(user_agent),
                                    last_active_at = CURRENT_TIMESTAMP, is_revoked = 0
            """,
            (device_token, user_id, device_type, os_name, browser, ip, (user_agent or "")[:500])
        )
        conn.commit()


def touch_login_device(device_token: str, ip: Optional[str] = None) -> None:
    """刷新设备活跃时间"""
    with get_db() as conn:
        cursor = conn.cursor()
        if ip:
            cursor.execute(
                "UPDATE login_devices SET last_active_at = CURRENT_TIMESTAMP, ip = %s WHERE device_token = %s AND is_revoked = 0",
                (ip, device_token)
            )
        else:
            cursor.execute(
                "UPDATE login_devices SET last_active_at = CURRENT_TIMESTAMP WHERE device_token = %s AND is_revoked = 0",
                (device_token,)
            )
        conn.commit()


def get_login_devices(user_id: int) -> list:
    """获取用户所有有效登录设备"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, device_token, device_type, os, browser, ip, last_active_at, created_at, is_revoked, user_agent
            FROM login_devices
            WHERE user_id = %s
            ORDER BY last_active_at DESC
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "device_token": row["device_token"],
                "device_type": row["device_type"],
                "os": row["os"],
                "browser": row["browser"],
                "ip": row["ip"],
                "last_active_at": row["last_active_at"].strftime("%Y-%m-%d %H:%M:%S") if row["last_active_at"] else "",
                "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row["created_at"] else "",
                "is_revoked": bool(row["is_revoked"]),
                "is_current": False,  # 由调用方根据当前 token 标记
            }
            for row in rows
        ]


def revoke_login_device(user_id: int, device_id: int) -> bool:
    """下线指定设备"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE login_devices SET is_revoked = 1 WHERE id = %s AND user_id = %s",
            (device_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def revoke_all_other_devices(user_id: int, keep_token: str) -> int:
    """一键下线除当前设备外的所有设备"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE login_devices SET is_revoked = 1 WHERE user_id = %s AND device_token != %s",
            (user_id, keep_token)
        )
        conn.commit()
        return cursor.rowcount


def _parse_os(user_agent: str) -> str:
    """从 User-Agent 字符串中解析出操作系统名称。"""
    ua = user_agent or ""
    if "Windows NT 10" in ua: return "Windows 10/11"
    if "Windows NT" in ua: return "Windows"
    if "Mac OS X" in ua or "Macintosh" in ua: return "macOS"
    if "Android" in ua: return "Android"
    if "iPhone" in ua or "iPad" in ua: return "iOS"
    if "Linux" in ua: return "Linux"
    return "Unknown"


def _parse_browser(user_agent: str) -> str:
    """从 User-Agent 字符串中识别浏览器类型（Edge/Chrome/Firefox 等）。"""
    ua = user_agent or ""
    if "Edg/" in ua: return "Edge"
    if "Chrome/" in ua and "Chromium" not in ua: return "Chrome"
    if "Firefox/" in ua: return "Firefox"
    if "Safari/" in ua and "Chrome" not in ua: return "Safari"
    if "MSIE" in ua or "Trident/" in ua: return "IE"
    return "Unknown"


# ==================== 注销账号 ====================

def delete_user_self(user_id: int, password: str) -> bool:
    """用户自助注销账号（需校验密码）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role, password_hash FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        if row["role"] == "admin":
            return False  # 管理员不允许自助注销
        if not verify_password(password, row["password_hash"]):
            return False
        # 级联清理
        cursor.execute(
            "DELETE m FROM messages m JOIN conversations c ON m.conversation_id = c.id WHERE c.user_id = %s",
            (user_id,)
        )
        cursor.execute("DELETE FROM conversations WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM login_devices WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM message_feedback WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


# ==================== 管理员相关 ====================

def get_all_users() -> list:
    """查询全部非管理员用户的列表（供管理后台展示）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, display_name, role, created_at, avatar_url, email, last_password_changed
            FROM users WHERE role != 'admin' ORDER BY id ASC
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "role": row["role"],
                "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row["created_at"] else "",
                "avatar_url": row.get("avatar_url") or "",
                "email": row.get("email") or "",
                "last_password_changed": row["last_password_changed"].strftime("%Y-%m-%d %H:%M:%S") if row.get("last_password_changed") else "",
            }
            for row in rows
        ]


def get_user_conversations_admin(target_user_id: int) -> list:
    """管理员查看任意用户的会话列表（仅显示最近30天）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at
            FROM conversations c
            WHERE c.user_id = %s AND c.created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            ORDER BY c.updated_at DESC
            """,
            (target_user_id,)
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            conv = {
                "id": row["id"],
                "title": row["title"],
                "time": row["updated_at"].strftime("%H:%M") if row["updated_at"] else "",
                "messages": [],
            }
            cursor.execute(
                "SELECT id, role, content, created_at, extra_json FROM messages WHERE conversation_id = %s ORDER BY created_at ASC",
                (row["id"],)
            )
            messages = cursor.fetchall()
            for msg in messages:
                entry = {
                    "id": msg["id"],
                    "role": msg["role"],
                    "content": msg["content"],
                    "time": msg["created_at"].strftime("%H:%M") if msg["created_at"] else "",
                }
                # 反序列化 extra_json（DeepAgent plan/steps）
                raw_extra = msg.get("extra_json")
                if raw_extra:
                    try:
                        import json as _json
                        extra = _json.loads(raw_extra)
                        if isinstance(extra, dict):
                            if extra.get("plan"):
                                entry["plan"] = extra["plan"]
                            if extra.get("steps"):
                                entry["steps"] = extra["steps"]
                    except Exception:
                        pass
                conv["messages"].append(entry)
            result.append(conv)
        return result


def cleanup_old_conversations(days: int = 30) -> int:
    """物理删除超过指定天数的会话及其消息，返回删除的会话数"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE m FROM messages m JOIN conversations c ON m.conversation_id = c.id WHERE c.created_at < DATE_SUB(NOW(), INTERVAL %s DAY)",
            (days,)
        )
        cursor.execute(
            "DELETE FROM conversations WHERE created_at < DATE_SUB(NOW(), INTERVAL %s DAY)",
            (days,)
        )
        deleted = cursor.rowcount
        conn.commit()
        return deleted


# ==================== 数据统计：埋点写入 ====================

def log_api_call(user_id: int, session_id: str, ip: str, endpoint: str,
                 duration_ms: int, prompt_tokens: int = 0, completion_tokens: int = 0,
                 is_success: bool = True, error_msg: str = "") -> None:
    """记录一次 API 调用（用于统计调用量 / Token / 响应时长 / 错误率）"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO api_call_logs
                    (user_id, session_id, ip, endpoint, duration_ms,
                     prompt_tokens, completion_tokens, total_tokens, is_success, error_msg)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, session_id or "", ip or "", endpoint or "chat", int(duration_ms or 0),
                 int(prompt_tokens or 0), int(completion_tokens or 0),
                 int(prompt_tokens or 0) + int(completion_tokens or 0),
                 1 if is_success else 0, (error_msg or "")[:1000])
            )
            conn.commit()
    except Exception:
        # 埋点失败不影响主流程
        pass


def log_tool_call(user_id: int, session_id: str, tool_name: str,
                  duration_ms: int, is_success: bool = True, error_msg: str = "") -> None:
    """记录一次工具调用（用于工具分布统计）"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tool_call_logs
                    (user_id, session_id, tool_name, duration_ms, is_success, error_msg)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, session_id or "", tool_name or "", int(duration_ms or 0),
                 1 if is_success else 0, (error_msg or "")[:1000])
            )
            conn.commit()
    except Exception:
        pass


def log_rate_limit_event(user_id: int, ip: str, limit_type: str, identifier: str) -> None:
    """记录一次限流触发事件"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO rate_limit_events (user_id, ip, limit_type, identifier)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id or 0, ip or "", limit_type or "chat", (identifier or "")[:200])
            )
            conn.commit()
    except Exception:
        pass


# ==================== 数据统计：看板查询 ====================

def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文约 1 字=1 token，英文约 4 字符=1 token"""
    if not text:
        return 0
    chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_count = len(text) - chinese_count
    return chinese_count + other_count // 4


def get_dashboard_overview() -> dict:
    """看板概览：DAU / WAU / MAU / 新增用户 / 次日留存"""
    with get_db() as conn:
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")

        # DAU：今日活跃用户（去重 user_id，排除 admin）
        cursor.execute(
            "SELECT COUNT(DISTINCT user_id) AS cnt FROM api_call_logs "
            "WHERE DATE(created_at) = %s AND user_id > 0",
            (today,)
        )
        dau = cursor.fetchone()["cnt"]

        # WAU：近 7 天活跃
        cursor.execute(
            "SELECT COUNT(DISTINCT user_id) AS cnt FROM api_call_logs "
            "WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND user_id > 0"
        )
        wau = cursor.fetchone()["cnt"]

        # MAU：近 30 天活跃
        cursor.execute(
            "SELECT COUNT(DISTINCT user_id) AS cnt FROM api_call_logs "
            "WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) AND user_id > 0"
        )
        mau = cursor.fetchone()["cnt"]

        # 今日新增用户（排除 admin）
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE DATE(created_at) = %s AND role != 'admin'",
            (today,)
        )
        new_users_today = cursor.fetchone()["cnt"]

        # 近 7 天新增用户
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM users "
            "WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND role != 'admin'"
        )
        new_users_week = cursor.fetchone()["cnt"]

        # 总用户数
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE role != 'admin'")
        total_users = cursor.fetchone()["cnt"]

        # 次日留存：昨日新增用户中，今日有调用的用户数占比
        cursor.execute(
            """
            SELECT DISTINCT u.id FROM users u
            WHERE DATE(u.created_at) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)
              AND u.role != 'admin'
            """
        )
        yesterday_new = [row["id"] for row in cursor.fetchall()]
        if yesterday_new:
            placeholders = ",".join(["%s"] * len(yesterday_new))
            cursor.execute(
                f"SELECT COUNT(DISTINCT user_id) AS cnt FROM api_call_logs "
                f"WHERE DATE(created_at) = %s AND user_id IN ({placeholders})",
                [today] + yesterday_new
            )
            retained = cursor.fetchone()["cnt"]
            retention_rate = round(retained / len(yesterday_new) * 100, 2)
        else:
            retention_rate = 0.0

        return {
            "dau": dau,
            "wau": wau,
            "mau": mau,
            "new_users_today": new_users_today,
            "new_users_week": new_users_week,
            "total_users": total_users,
            "retention_rate": retention_rate,
        }


def get_dashboard_trends(days: int = 30) -> dict:
    """趋势图：每日调用量 / Token 消耗 / 平均响应时长"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                DATE(created_at) AS date,
                COUNT(*) AS call_count,
                SUM(prompt_tokens) AS prompt_tokens,
                SUM(completion_tokens) AS completion_tokens,
                SUM(total_tokens) AS total_tokens,
                AVG(duration_ms) AS avg_duration_ms
            FROM api_call_logs
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at) ASC
            """,
            (int(days),)
        )
        rows = cursor.fetchall()
        dates = []
        call_counts = []
        prompt_tokens = []
        completion_tokens = []
        total_tokens = []
        avg_durations = []
        for row in rows:
            d = row["date"]
            dates.append(d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d))
            call_counts.append(row["call_count"])
            prompt_tokens.append(int(row["prompt_tokens"] or 0))
            completion_tokens.append(int(row["completion_tokens"] or 0))
            total_tokens.append(int(row["total_tokens"] or 0))
            avg_durations.append(round(float(row["avg_duration_ms"] or 0), 2))
        return {
            "dates": dates,
            "call_counts": call_counts,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "avg_durations": avg_durations,
        }


def get_dashboard_tool_distribution(days: int = 30) -> list:
    """工具调用分布：哪个工具最常用"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT tool_name, COUNT(*) AS cnt, SUM(is_success) AS success_cnt
            FROM tool_call_logs
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY tool_name
            ORDER BY cnt DESC
            """,
            (int(days),)
        )
        return [
            {
                "tool_name": row["tool_name"],
                "count": row["cnt"],
                "success_count": int(row["success_cnt"] or 0),
                "success_rate": round(int(row["success_cnt"] or 0) / row["cnt"] * 100, 2) if row["cnt"] else 0,
            }
            for row in cursor.fetchall()
        ]


def get_dashboard_error_stats(days: int = 30) -> dict:
    """错误率 + 限流触发次数"""
    with get_db() as conn:
        cursor = conn.cursor()
        # API 错误率
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_success = 0 THEN 1 ELSE 0 END) AS errors
            FROM api_call_logs
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """,
            (int(days),)
        )
        row = cursor.fetchone()
        total_calls = row["total"] or 0
        error_calls = row["errors"] or 0
        error_rate = round(error_calls / total_calls * 100, 2) if total_calls else 0.0

        # 工具调用错误率
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_success = 0 THEN 1 ELSE 0 END) AS errors
            FROM tool_call_logs
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """,
            (int(days),)
        )
        trow = cursor.fetchone()
        t_total = trow["total"] or 0
        t_errors = trow["errors"] or 0
        tool_error_rate = round(t_errors / t_total * 100, 2) if t_total else 0.0

        # 限流触发次数
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM rate_limit_events "
            "WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)",
            (int(days),)
        )
        rate_limit_count = cursor.fetchone()["cnt"]

        # 按日分组的限流事件
        cursor.execute(
            """
            SELECT DATE(created_at) AS date, COUNT(*) AS cnt
            FROM rate_limit_events
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at) ASC
            """,
            (int(days),)
        )
        rl_trend = [
            {
                "date": (row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])),
                "count": row["cnt"],
            }
            for row in cursor.fetchall()
        ]

        return {
            "total_calls": total_calls,
            "error_calls": error_calls,
            "error_rate": error_rate,
            "tool_total_calls": t_total,
            "tool_error_calls": t_errors,
            "tool_error_rate": tool_error_rate,
            "rate_limit_count": rate_limit_count,
            "rate_limit_trend": rl_trend,
        }


def get_dashboard_top_users(days: int = 30, limit: int = 10) -> list:
    """Top 用户：按调用量排序"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                a.user_id,
                u.username,
                u.display_name,
                COUNT(*) AS call_count,
                SUM(a.total_tokens) AS total_tokens,
                AVG(a.duration_ms) AS avg_duration_ms
            FROM api_call_logs a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
              AND a.user_id > 0
            GROUP BY a.user_id, u.username, u.display_name
            ORDER BY call_count DESC
            LIMIT %s
            """,
            (int(days), int(limit))
        )
        return [
            {
                "user_id": row["user_id"],
                "username": row["username"] or f"用户{row['user_id']}",
                "display_name": row["display_name"] or row["username"] or f"用户{row['user_id']}",
                "call_count": row["call_count"],
                "total_tokens": int(row["total_tokens"] or 0),
                "avg_duration_ms": round(float(row["avg_duration_ms"] or 0), 2),
            }
            for row in cursor.fetchall()
        ]


def get_dashboard_top_questions(days: int = 30, limit: int = 10) -> list:
    """Top 提问：按用户提问频次排序（从 messages 表统计）"""
    with get_db() as conn:
        cursor = conn.cursor()
        # 取近 N 天的高频用户提问（按内容前 50 字符分组，避免完全相同的少数问题占满）
        cursor.execute(
            """
            SELECT LEFT(m.content, 50) AS question,
                   COUNT(*) AS cnt,
                   COUNT(DISTINCT m.conversation_id) AS conv_cnt
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.role = 'user'
              AND m.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY LEFT(m.content, 50)
            ORDER BY cnt DESC
            LIMIT %s
            """,
            (int(days), int(limit))
        )
        return [
            {
                "question": row["question"],
                "count": row["cnt"],
                "conversation_count": row["conv_cnt"],
            }
            for row in cursor.fetchall()
        ]


# ==================== DeepAgent：结构化记忆 ====================

def save_memory(user_id: int, memory_type: str, key_name: str, value: str,
                source: str = "agent", confidence: float = 1.0) -> int:
    """写入或更新一条结构化记忆（同 user+type+key 覆盖）。返回记忆 id。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO user_memories (user_id, memory_type, key_name, value, source, confidence)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   value = VALUES(value), source = VALUES(source),
                   confidence = VALUES(confidence), is_active = 1,
                   updated_at = CURRENT_TIMESTAMP""",
            (user_id, memory_type, key_name[:200], value[:65000], source[:100], float(confidence))
        )
        new_id = cursor.lastrowid
        conn.commit()
        return int(new_id) if new_id else 0


def recall_memories(user_id: int, memory_type: str = None, keyword: str = None,
                    limit: int = 20) -> list:
    """按类型 / 关键词召回用户记忆。无过滤条件则返回最近的所有记忆。"""
    with get_db() as conn:
        cursor = conn.cursor()
        sql = "SELECT id, memory_type, key_name, value, source, confidence, updated_at FROM user_memories WHERE user_id = %s AND is_active = 1"
        params: list = [user_id]
        if memory_type:
            sql += " AND memory_type = %s"
            params.append(memory_type)
        if keyword:
            sql += " AND (key_name LIKE %s OR value LIKE %s)"
            like = f"%{keyword}%"
            params.extend([like, like])
        sql += " ORDER BY updated_at DESC LIMIT %s"
        params.append(int(limit))
        cursor.execute(sql, tuple(params))
        return [
            {
                "id": r["id"],
                "type": r["memory_type"],
                "key": r["key_name"],
                "value": r["value"],
                "source": r.get("source", ""),
                "confidence": float(r.get("confidence", 1.0)),
                "updated_at": r["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("updated_at") else "",
            }
            for r in cursor.fetchall()
        ]


def get_memory(user_id: int, key_name: str) -> Optional[str]:
    """精确读取一条记忆的 value。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM user_memories WHERE user_id = %s AND key_name = %s AND is_active = 1",
            (user_id, key_name[:200])
        )
        row = cursor.fetchone()
        return row["value"] if row else None


def deactivate_memory(user_id: int, key_name: str = None, memory_id: int = None) -> int:
    """软删除记忆（标记 is_active=0）。返回受影响行数。"""
    with get_db() as conn:
        cursor = conn.cursor()
        if memory_id:
            cursor.execute(
                "UPDATE user_memories SET is_active = 0 WHERE id = %s AND user_id = %s",
                (memory_id, user_id)
            )
        elif key_name:
            cursor.execute(
                "UPDATE user_memories SET is_active = 0 WHERE user_id = %s AND key_name = %s",
                (user_id, key_name[:200])
            )
        affected = cursor.rowcount
        conn.commit()
        return affected


# ==================== DeepAgent：Artifact 一等公民 ====================

def create_artifact(user_id: int, session_id: str, plan_id: str, art_type: str,
                    title: str, content_ref: str, mime_type: str = "",
                    step_idx: Optional[int] = None, parent_id: str = "",
                    meta: dict = None) -> str:
    """注册一个 Artifact，返回 artifact id。"""
    import uuid as _uuid
    art_id = f"art_{_uuid.uuid4().hex[:16]}"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO artifacts
               (id, user_id, session_id, plan_id, step_idx, type, title,
                content_ref, mime_type, parent_id, meta)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (art_id, user_id, session_id or "", plan_id or "", step_idx,
             art_type[:30], title[:255], content_ref[:500], mime_type[:100],
             parent_id or "",
             __import__("json").dumps(meta or {}, ensure_ascii=False))
        )
        conn.commit()
    return art_id


def list_artifacts(user_id: int, session_id: str = None, art_type: str = None,
                   limit: int = 50) -> list:
    """按会话 / 类型筛选查询用户的 Artifact 列表（按创建时间倒序）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        sql = "SELECT id, session_id, plan_id, type, title, content_ref, mime_type, version, parent_id, meta, created_at FROM artifacts WHERE user_id = %s"
        params: list = [user_id]
        if session_id:
            sql += " AND session_id = %s"
            params.append(session_id)
        if art_type:
            sql += " AND type = %s"
            params.append(art_type)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(int(limit))
        cursor.execute(sql, tuple(params))
        return [
            {
                "id": r["id"],
                "session_id": r.get("session_id", "") or "",
                "plan_id": r.get("plan_id", "") or "",
                "type": r["type"],
                "title": r["title"],
                "content_ref": r["content_ref"],
                "mime_type": r.get("mime_type", "") or "",
                "version": r.get("version", 1),
                "parent_id": r.get("parent_id", "") or "",
                "meta": r.get("meta"),
                "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("created_at") else "",
            }
            for r in cursor.fetchall()
        ]


def get_artifact(user_id: int, artifact_id: str) -> Optional[dict]:
    """按 ID 查询单个 Artifact 详情，不存在时返回 None。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM artifacts WHERE id = %s AND user_id = %s",
            (artifact_id, user_id)
        )
        r = cursor.fetchone()
        if not r:
            return None
        return {
            "id": r["id"],
            "user_id": r["user_id"],
            "session_id": r.get("session_id", "") or "",
            "plan_id": r.get("plan_id", "") or "",
            "step_idx": r.get("step_idx"),
            "type": r["type"],
            "title": r["title"],
            "content_ref": r["content_ref"],
            "mime_type": r.get("mime_type", "") or "",
            "version": r.get("version", 1),
            "parent_id": r.get("parent_id", "") or "",
            "meta": r.get("meta"),
            "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("created_at") else "",
        }


def bump_artifact_version(artifact_id: str) -> int:
    """递增 artifact 版本（同 parent_id 链路上的新版本）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE artifacts SET version = version + 1 WHERE id = %s",
            (artifact_id,)
        )
        conn.commit()
        return cursor.rowcount
