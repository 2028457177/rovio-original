"""user_service 数据访问层（lc_user 数据库）。"""
from typing import Optional

from core.db import get_db


# ==================== 用户资料 ====================

def get_profile(user_id: int) -> dict:
    """读取用户资料。不存在时返回默认值。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, display_name, email, avatar_url "
            "FROM user_profiles WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return {
                "user_id": user_id,
                "display_name": "",
                "email": "",
                "avatar_url": "",
            }
        return {
            "user_id": row["user_id"],
            "display_name": row["display_name"] or "",
            "email": row["email"] or "",
            "avatar_url": row["avatar_url"] or "",
        }


def upsert_profile(user_id: int, display_name: Optional[str] = None,
                   email: Optional[str] = None) -> Optional[dict]:
    """更新昵称 / 邮箱。display_name 空字符串返回 None。不存在则 INSERT。"""
    # display_name 传了空字符串则拒绝
    if display_name is not None and not display_name.strip():
        return None

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM user_profiles WHERE user_id = %s", (user_id,))
        exists = cur.fetchone() is not None

        if not exists:
            # 不存在则 INSERT（None 字段用空字符串占位）
            dn = display_name.strip()[:100] if display_name is not None else ""
            em = email.strip()[:100] if email is not None else ""
            cur.execute(
                "INSERT INTO user_profiles (user_id, display_name, email, avatar_url) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, dn, em, "")
            )
            conn.commit()
        else:
            sets = []
            params = []
            if display_name is not None:
                sets.append("display_name = %s")
                params.append(display_name.strip()[:100])
            if email is not None:
                sets.append("email = %s")
                params.append(email.strip()[:100])
            if sets:
                sets.append("updated_at = CURRENT_TIMESTAMP")
                params.append(user_id)
                cur.execute(
                    f"UPDATE user_profiles SET {', '.join(sets)} WHERE user_id = %s",
                    tuple(params)
                )
                conn.commit()

    return get_profile(user_id)


def update_avatar_url(user_id: int, avatar_url: str) -> bool:
    """更新头像 URL，若 profile 不存在先 INSERT。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_profiles (user_id, display_name, email, avatar_url) "
            "VALUES (%s, '', '', %s) "
            "ON DUPLICATE KEY UPDATE avatar_url = VALUES(avatar_url), updated_at = CURRENT_TIMESTAMP",
            (user_id, avatar_url)
        )
        conn.commit()
        return cur.rowcount > 0


def ensure_profile(user_id: int, display_name: str = "") -> bool:
    """INSERT IGNORE 方式确保 user_profiles 记录存在（注册时由 auth_service 调用）。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT IGNORE INTO user_profiles (user_id, display_name, email, avatar_url) "
            "VALUES (%s, %s, '', '')",
            (user_id, (display_name or "")[:100])
        )
        conn.commit()
        return cur.rowcount > 0


# ==================== 课表设置 ====================

def get_schedule_settings(user_id: int) -> dict:
    """读取当前用户的课表设置。

    返回:
        {
            uploaded: bool,
            file_path: str | None,        # 相对 UPLOAD_DIR 的路径
            start_date: str | None,       # 'YYYY-MM-DD'
            uploaded_at: str | None,      # 'YYYY-MM-DD HH:MM:SS'
            schedule_url: str | None,     # 前端下载用的 URL
        }
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT file_path, start_date, uploaded_at "
            "FROM user_schedules WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return {"uploaded": False, "file_path": None, "start_date": None,
                    "uploaded_at": None, "schedule_url": None}
        file_path = (row["file_path"] or "").strip()
        uploaded = bool(file_path)
        # file_path 形如 'schedules/schedule_42.xlsx' → 提取文件名拼下载 URL
        schedule_url = f"/api/schedules/{file_path.split('/')[-1]}" if uploaded else None
        return {
            "uploaded": uploaded,
            "file_path": file_path or None,
            "start_date": row["start_date"].strftime("%Y-%m-%d") if row.get("start_date") else None,
            "uploaded_at": row["uploaded_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("uploaded_at") else None,
            "schedule_url": schedule_url,
        }


def update_schedule(user_id: int, file_path: str, start_date: Optional[str],
                    parsed_courses: Optional[str] = None) -> bool:
    """更新用户课表：写入文件相对路径 + 开学日期 + 上传时间 + 预解析结果。

    file_path: 相对 UPLOAD_DIR 的路径，如 'schedules/schedule_42.xlsx'
    start_date: 'YYYY-MM-DD' 字符串或 None
    parsed_courses: 预解析课表 JSON 字符串（schedule_parser.parse_schedule_df 的输出），
                    None 时存 NULL（查询侧回退旧 Excel 解析）
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_schedules (user_id, file_path, start_date, parsed_courses, uploaded_at) "
            "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP) "
            "ON DUPLICATE KEY UPDATE file_path = VALUES(file_path), "
            "start_date = VALUES(start_date), parsed_courses = VALUES(parsed_courses), "
            "uploaded_at = CURRENT_TIMESTAMP",
            (user_id, file_path, start_date, parsed_courses)
        )
        conn.commit()
        return cur.rowcount > 0


def update_schedule_start_date(user_id: int, start_date: Optional[str]) -> bool:
    """仅修改开学日期（不重传文件）。

    允许尚未上传课表时先保存日期：无记录则插入（file_path 为空），
    之后上传课表时再由 update_schedule 覆盖。
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_schedules (user_id, file_path, start_date, uploaded_at) "
            "VALUES (%s, '', %s, CURRENT_TIMESTAMP) "
            "ON DUPLICATE KEY UPDATE start_date = VALUES(start_date)",
            (user_id, start_date)
        )
        conn.commit()
        return cur.rowcount > 0


def clear_schedule(user_id: int) -> Optional[str]:
    """清除用户课表设置，返回被清除的旧文件相对路径（供调用方删物理文件）。
    返回 None 表示原本就没上传过。
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM user_schedules WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        old_path = (row["file_path"] if row else "") or ""
        cur.execute(
            "UPDATE user_schedules SET file_path = '', start_date = NULL, "
            "parsed_courses = NULL, uploaded_at = NULL "
            "WHERE user_id = %s",
            (user_id,)
        )
        conn.commit()
        return old_path or None


# ==================== 模型设置（用户自配 OpenAI 兼容模型） ====================

def _mask_api_key(api_key: str) -> str:
    """脱敏 API Key：只保留前 4 位和后 4 位，如 'sk-abcd****wxyz'。"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}****{api_key[-4:]}"


def get_model_settings(user_id: int) -> dict:
    """读取当前用户的模型配置（api_key 脱敏后返回）。

    返回:
        {
            configured: bool,   # 是否已配置完整（base_url + model_name + api_key 均非空）
            base_url: str,
            api_key: str,       # 脱敏
            model_name: str,
        }
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT base_url, api_key, model_name FROM user_models WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return {"configured": False, "base_url": "", "api_key": "", "model_name": ""}
        base_url = (row["base_url"] or "").strip()
        api_key = (row["api_key"] or "").strip()
        model_name = (row["model_name"] or "").strip()
        return {
            "configured": bool(base_url and api_key and model_name),
            "base_url": base_url,
            "api_key": _mask_api_key(api_key),
            "model_name": model_name,
        }


def save_model_settings(user_id: int, base_url: str, api_key: str, model_name: str) -> bool:
    """保存 / 更新用户模型配置（upsert）。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_models (user_id, base_url, api_key, model_name) "
            "VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE base_url = VALUES(base_url), "
            "api_key = VALUES(api_key), model_name = VALUES(model_name), "
            "updated_at = CURRENT_TIMESTAMP",
            (user_id, (base_url or "").strip()[:500],
             (api_key or "").strip()[:500], (model_name or "").strip()[:200])
        )
        conn.commit()
        return cur.rowcount > 0


def clear_model_settings(user_id: int) -> bool:
    """清除用户模型配置（恢复系统默认模型）。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_models WHERE user_id = %s", (user_id,))
        conn.commit()
        return cur.rowcount > 0


def get_model_config_raw(user_id: int) -> Optional[dict]:
    """读取完整模型配置（内部接口用，api_key 不脱敏）。

    返回 None 表示未配置或配置不完整。
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT base_url, api_key, model_name FROM user_models WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        base_url = (row["base_url"] or "").strip()
        api_key = (row["api_key"] or "").strip()
        model_name = (row["model_name"] or "").strip()
        if not (base_url and api_key and model_name):
            return None
        return {
            "base_url": base_url,
            "api_key": api_key,
            "model_name": model_name,
        }


# ==================== 注销清理 ====================

def delete_user_data(user_id: int) -> bool:
    """注销账号时清理 user_profiles + user_schedules + user_models。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_profiles WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM user_schedules WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM user_models WHERE user_id = %s", (user_id,))
        conn.commit()
        return True
