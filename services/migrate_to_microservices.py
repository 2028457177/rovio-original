"""微服务数据库迁移脚本。

将原单库 agent_records 拆分为 5 个独立数据库：
- lc_auth:   users(认证列) + login_devices + security_questions(从 users 拆出)
- lc_user:   user_profiles(从 users 拆出) + user_schedules(从 users 拆出)
- lc_chat:   conversations + messages + message_feedback + api_call_logs + tool_call_logs
- lc_kb:     knowledge_bases + kb_documents
- lc_admin:  rate_limit_events

特性：
- 幂等：可重复执行，已存在的库/表/数据会跳过
- 保留原 agent_records 库不动（作为回滚备份）
- 用户 ID 保持不变（迁移时保留原自增 ID）

用法::

    python services/migrate_to_microservices.py          # 迁移
    python services/migrate_to_microservices.py --check   # 仅检查不执行

说明：本脚本完全自包含（不再依赖 services/common），配置读取环境变量，
默认值与各微服务 core/config.py 保持一致。使用前可加载 deploy/backend/.env。
"""
import argparse
import sys
import os
import logging

import pymysql
from pymysql.cursors import DictCursor

# 让脚本能在项目根目录直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ==================== 环境变量配置（与各服务 core/config.py 对齐） ====================
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_CHARSET = os.getenv("MYSQL_CHARSET", "utf8mb4")

_DB_NAMES = {
    "auth": os.getenv("AUTH_DB", "lc_auth"),
    "user": os.getenv("USER_DB", "lc_user"),
    "chat": os.getenv("CHAT_DB", "lc_chat"),
    "kb": os.getenv("KB_DB", "lc_kb"),
    "admin": os.getenv("ADMIN_DB", "lc_admin"),
}


def get_db_name(svc: str) -> str:
    """按服务名返回对应的数据库名（未配置时按 lc_<svc> 兜底）。"""
    return _DB_NAMES.get(svc, f"lc_{svc}")


def get_mysql_config(svc: str = None) -> dict:
    """生成 MySQL 连接配置（可选指定目标库名，svc 为空则不指定库）。"""
    cfg = {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "charset": MYSQL_CHARSET,
    }
    if svc:
        cfg["database"] = get_db_name(svc)
    return cfg


# 简单控制台日志（迁移脚本不写文件）
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate")


def set_service_name(name: str):
    """兼容占位函数：迁移脚本不写文件日志，无需设置服务名。"""
    pass

OLD_DB = "agent_records"


def _admin_connect(database: str = None):
    """连接 MySQL（不指定 database 或指定旧库）"""
    cfg = {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "charset": MYSQL_CHARSET,
        "cursorclass": DictCursor,
        "autocommit": True,
    }
    if database:
        cfg["database"] = database
    return pymysql.connect(**cfg)


def _exec(cursor, sql: str, params=None, log: bool = True):
    """执行 SQL（可选打印调试日志，params 为 SQL 参数）。"""
    if log:
        logger.debug(f"[migrate] {sql[:120]}")
    cursor.execute(sql, params)


def _safe_add_column(cursor, table: str, column: str, definition: str):
    """安全给表添加列：列已存在时静默跳过不报错。"""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except Exception:
        pass


def _safe_add_index(cursor, table: str, index_name: str, columns: str):
    """安全创建索引：索引已存在时静默跳过不报错。"""
    try:
        cursor.execute(f"CREATE INDEX {index_name} ON {table} ({columns})")
    except Exception:
        pass


# ==================== 建库 + 建表 ====================

def create_databases():
    """创建 5 个独立数据库"""
    for svc in ["auth", "user", "chat", "kb", "admin"]:
        db_name = get_db_name(svc)
        conn = _admin_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                    f"CHARACTER SET {MYSQL_CHARSET} COLLATE utf8mb4_unicode_ci"
                )
            conn.commit()
            logger.info(f"[migrate] 数据库 {db_name} 已就绪")
        finally:
            conn.close()


def init_auth_schema():
    """lc_auth: users(认证) + security_questions + login_devices"""
    conn = _admin_connect(get_db_name("auth"))
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'user',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_password_changed DATETIME NULL,
                    INDEX idx_users_username (username)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS security_questions (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL UNIQUE,
                    question VARCHAR(200) NOT NULL,
                    answer_hash VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_sq_user (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS login_devices (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    device_token VARCHAR(100) NOT NULL,
                    user_id BIGINT NOT NULL,
                    device_type VARCHAR(20) NOT NULL DEFAULT 'desktop',
                    os VARCHAR(50) NOT NULL DEFAULT '',
                    browser VARCHAR(50) NOT NULL DEFAULT '',
                    ip VARCHAR(64) NOT NULL DEFAULT '',
                    user_agent VARCHAR(500) NOT NULL DEFAULT '',
                    last_active_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    is_revoked TINYINT NOT NULL DEFAULT 0,
                    UNIQUE KEY uk_device_token (device_token),
                    INDEX idx_login_user (user_id, is_revoked)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        conn.commit()
        logger.info("[migrate] lc_auth 表结构就绪")
    finally:
        conn.close()


def init_user_schema():
    """lc_user: user_profiles + user_schedules（从 users 拆出）"""
    conn = _admin_connect(get_db_name("user"))
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id BIGINT PRIMARY KEY,
                    display_name VARCHAR(100) NOT NULL DEFAULT '',
                    email VARCHAR(100) NOT NULL DEFAULT '',
                    avatar_url VARCHAR(255) NOT NULL DEFAULT '',
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_schedules (
                    user_id BIGINT PRIMARY KEY,
                    file_path VARCHAR(255) NOT NULL DEFAULT '',
                    start_date DATE NULL,
                    uploaded_at DATETIME NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_models (
                    user_id BIGINT PRIMARY KEY,
                    base_url VARCHAR(500) NOT NULL DEFAULT '',
                    api_key VARCHAR(500) NOT NULL DEFAULT '',
                    model_name VARCHAR(200) NOT NULL DEFAULT '',
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        conn.commit()
        logger.info("[migrate] lc_user 表结构就绪")
    finally:
        conn.close()


def init_chat_schema():
    """lc_chat: conversations + messages + message_feedback + api_call_logs + tool_call_logs"""
    conn = _admin_connect(get_db_name("chat"))
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id VARCHAR(100) PRIMARY KEY,
                    user_id BIGINT NOT NULL DEFAULT 0,
                    title VARCHAR(255) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    is_deleted TINYINT NOT NULL DEFAULT 0,
                    pinned TINYINT NOT NULL DEFAULT 0,
                    starred TINYINT NOT NULL DEFAULT 0,
                    folder VARCHAR(100) NOT NULL DEFAULT '',
                    parent_conversation_id VARCHAR(100) NOT NULL DEFAULT '',
                    branch_point_message_id BIGINT NOT NULL DEFAULT 0,
                    INDEX idx_conv_user (user_id),
                    INDEX idx_conv_user_pinned (user_id, pinned),
                    INDEX idx_conv_parent (parent_conversation_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id VARCHAR(100) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_conv_created (conversation_id, created_at),
                    INDEX idx_msg_content (content(100))
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS message_feedback (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    conversation_id VARCHAR(100) NOT NULL,
                    message_id BIGINT NULL,
                    message_role VARCHAR(20) NOT NULL DEFAULT 'assistant',
                    message_content TEXT NOT NULL,
                    feedback VARCHAR(20) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_user_conv_role (user_id, conversation_id, message_role),
                    INDEX idx_feedback_type (feedback),
                    INDEX idx_feedback_user (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_call_logs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL DEFAULT 0,
                    session_id VARCHAR(100) NOT NULL DEFAULT '',
                    ip VARCHAR(64) NOT NULL DEFAULT '',
                    endpoint VARCHAR(50) NOT NULL DEFAULT 'chat',
                    duration_ms INT NOT NULL DEFAULT 0,
                    prompt_tokens INT NOT NULL DEFAULT 0,
                    completion_tokens INT NOT NULL DEFAULT 0,
                    total_tokens INT NOT NULL DEFAULT 0,
                    is_success TINYINT NOT NULL DEFAULT 1,
                    error_msg VARCHAR(1000) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_api_user (user_id),
                    INDEX idx_api_created (created_at),
                    INDEX idx_api_success (is_success)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tool_call_logs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL DEFAULT 0,
                    session_id VARCHAR(100) NOT NULL DEFAULT '',
                    tool_name VARCHAR(100) NOT NULL DEFAULT '',
                    duration_ms INT NOT NULL DEFAULT 0,
                    is_success TINYINT NOT NULL DEFAULT 1,
                    error_msg VARCHAR(1000) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_tool_name (tool_name),
                    INDEX idx_tool_user (user_id),
                    INDEX idx_tool_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        conn.commit()
        logger.info("[migrate] lc_chat 表结构就绪")
    finally:
        conn.close()


def init_kb_schema():
    """lc_kb: knowledge_bases + kb_documents"""
    conn = _admin_connect(get_db_name("kb"))
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    scope VARCHAR(20) NOT NULL DEFAULT 'global',
                    owner_user_id BIGINT NULL,
                    biz_line VARCHAR(100) NOT NULL DEFAULT '',
                    description VARCHAR(500) NOT NULL DEFAULT '',
                    is_enabled TINYINT NOT NULL DEFAULT 1,
                    is_default TINYINT NOT NULL DEFAULT 0,
                    created_by BIGINT NULL,
                    created_by_name VARCHAR(100) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_kb_scope_owner (scope, owner_user_id),
                    INDEX idx_kb_enabled (is_enabled)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kb_documents (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    kb_id BIGINT NOT NULL,
                    filename VARCHAR(255) NOT NULL,
                    stored_path VARCHAR(500) NOT NULL DEFAULT '',
                    file_ext VARCHAR(20) NOT NULL DEFAULT '',
                    file_size BIGINT NOT NULL DEFAULT 0,
                    file_md5 VARCHAR(64) NOT NULL DEFAULT '',
                    version INT NOT NULL DEFAULT 1,
                    source VARCHAR(50) NOT NULL DEFAULT 'upload',
                    uploader_id BIGINT NULL,
                    uploader_name VARCHAR(100) NOT NULL DEFAULT '',
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    chunk_count INT NOT NULL DEFAULT 0,
                    error_msg VARCHAR(1000) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_doc_kb (kb_id),
                    INDEX idx_doc_status (status),
                    INDEX idx_doc_md5 (kb_id, file_md5)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        conn.commit()
        logger.info("[migrate] lc_kb 表结构就绪")
    finally:
        conn.close()


def init_admin_schema():
    """lc_admin: rate_limit_events"""
    conn = _admin_connect(get_db_name("admin"))
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rate_limit_events (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL DEFAULT 0,
                    ip VARCHAR(64) NOT NULL DEFAULT '',
                    limit_type VARCHAR(20) NOT NULL DEFAULT 'chat',
                    identifier VARCHAR(200) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_rl_type (limit_type),
                    INDEX idx_rl_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            # admin 也需要 api_call_logs / tool_call_logs 的副本，
            # 用于聚合统计（chat 通过 Redis 事件推送过来，admin 落库）
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_call_logs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL DEFAULT 0,
                    session_id VARCHAR(100) NOT NULL DEFAULT '',
                    ip VARCHAR(64) NOT NULL DEFAULT '',
                    endpoint VARCHAR(50) NOT NULL DEFAULT 'chat',
                    duration_ms INT NOT NULL DEFAULT 0,
                    prompt_tokens INT NOT NULL DEFAULT 0,
                    completion_tokens INT NOT NULL DEFAULT 0,
                    total_tokens INT NOT NULL DEFAULT 0,
                    is_success TINYINT NOT NULL DEFAULT 1,
                    error_msg VARCHAR(1000) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_api_user (user_id),
                    INDEX idx_api_created (created_at),
                    INDEX idx_api_success (is_success)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tool_call_logs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL DEFAULT 0,
                    session_id VARCHAR(100) NOT NULL DEFAULT '',
                    tool_name VARCHAR(100) NOT NULL DEFAULT '',
                    duration_ms INT NOT NULL DEFAULT 0,
                    is_success TINYINT NOT NULL DEFAULT 1,
                    error_msg VARCHAR(1000) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_tool_name (tool_name),
                    INDEX idx_tool_user (user_id),
                    INDEX idx_tool_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        conn.commit()
        logger.info("[migrate] lc_admin 表结构就绪")
    finally:
        conn.close()


# ==================== 数据迁移 ====================

def _table_has_data(cursor, db: str, table: str) -> bool:
    """检查旧库的表是否有数据"""
    try:
        cursor.execute(f"SELECT COUNT(*) AS c FROM `{db}`.`{table}`")
        return cursor.fetchone()["c"] > 0
    except Exception:
        return False


def _target_has_rows(cursor, db: str, table: str) -> bool:
    """检查目标库的表是否已有数据（避免重复迁移）"""
    try:
        cursor.execute(f"SELECT COUNT(*) AS c FROM `{db}`.`{table}`")
        return cursor.fetchone()["c"] > 0
    except Exception:
        return False


def migrate_users():
    """users 表拆分迁移：
    - 认证列 → lc_auth.users + lc_auth.security_questions
    - 资料列 → lc_user.user_profiles
    - 课表列 → lc_user.user_schedules
    """
    if not _table_has_data(_admin_connect().cursor(), OLD_DB, "users"):
        # 没有旧数据，仅创建默认 admin
        _seed_default_admin()
        return

    src = _admin_connect(OLD_DB)
    try:
        with src.cursor(DictCursor) as cur:
            # 检查目标是否已迁移
            auth_db = get_db_name("auth")
            if not _target_has_rows(_admin_connect(auth_db).cursor(), auth_db, "users"):
                cur.execute("""
                    SELECT id, username, password_hash, role, created_at, last_password_changed,
                           display_name, email, avatar_url,
                           security_question, security_answer_hash,
                           schedule_file, schedule_start_date, schedule_uploaded_at
                    FROM users
                """)
                rows = cur.fetchall()
                logger.info(f"[migrate] 迁移 {len(rows)} 个用户...")

                auth_conn = _admin_connect(auth_db)
                user_db = get_db_name("user")
                user_conn = _admin_connect(user_db)
                try:
                    with auth_conn.cursor() as ac, user_conn.cursor() as uc:
                        for r in rows:
                            # lc_auth.users
                            ac.execute(
                                "INSERT IGNORE INTO users (id, username, password_hash, role, created_at, last_password_changed) "
                                "VALUES (%s, %s, %s, %s, %s, %s)",
                                (r["id"], r["username"], r["password_hash"], r["role"],
                                 r["created_at"], r.get("last_password_changed"))
                            )
                            # lc_auth.security_questions
                            if r.get("security_question") and r.get("security_answer_hash"):
                                ac.execute(
                                    "INSERT IGNORE INTO security_questions (user_id, question, answer_hash) VALUES (%s, %s, %s)",
                                    (r["id"], r["security_question"], r["security_answer_hash"])
                                )
                            # lc_user.user_profiles
                            uc.execute(
                                "INSERT IGNORE INTO user_profiles (user_id, display_name, email, avatar_url) "
                                "VALUES (%s, %s, %s, %s)",
                                (r["id"], r.get("display_name") or "", r.get("email") or "", r.get("avatar_url") or "")
                            )
                            # lc_user.user_schedules
                            uc.execute(
                                "INSERT IGNORE INTO user_schedules (user_id, file_path, start_date, uploaded_at) "
                                "VALUES (%s, %s, %s, %s)",
                                (r["id"], r.get("schedule_file") or "", r.get("schedule_start_date"),
                                 r.get("schedule_uploaded_at"))
                            )
                    auth_conn.commit()
                    user_conn.commit()
                finally:
                    auth_conn.close()
                    user_conn.close()
                logger.info(f"[migrate] 用户数据迁移完成（{len(rows)} 条）")
            else:
                logger.info("[migrate] lc_auth.users 已有数据，跳过用户迁移")
    finally:
        src.close()

    _seed_default_admin()


def _seed_default_admin():
    """确保默认管理员 admin/admin123 存在（迁移后兜底）"""
    import hashlib
    import os as _os
    auth_db = get_db_name("auth")
    conn = _admin_connect(auth_db)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = 'admin'")
            if cur.fetchone():
                return
            salt = _os.urandom(32)
            hash_obj = hashlib.pbkdf2_hmac("sha256", "admin123".encode("utf-8"), salt, 100000)
            password_hash = salt.hex() + ":" + hash_obj.hex()
            # 取一个不冲突的 ID（用 MAX(id)+1）
            cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM users")
            next_id = cur.fetchone()["next_id"]
            cur.execute(
                "INSERT INTO users (id, username, password_hash, role, display_name) VALUES (%s, %s, %s, %s, %s)",
                (next_id, "admin", password_hash, "admin", "系统管理员")
            )
            # 同步 user_profiles
            user_db = get_db_name("user")
            uconn = _admin_connect(user_db)
            try:
                with uconn.cursor() as uc:
                    uc.execute(
                        "INSERT IGNORE INTO user_profiles (user_id, display_name) VALUES (%s, %s)",
                        (next_id, "系统管理员")
                    )
                uconn.commit()
            finally:
                uconn.close()
        conn.commit()
        logger.info("[migrate] 默认管理员 admin/admin123 已创建")
    finally:
        conn.close()


def _migrate_table(src_table: str, dst_db: str, dst_table: str, columns: str = "*"):
    """通用整表迁移：从 OLD_DB.src_table 复制到 dst_db.dst_table"""
    src = _admin_connect(OLD_DB)
    try:
        with src.cursor(DictCursor) as cur:
            if not _table_has_data(cur, OLD_DB, src_table):
                logger.info(f"[migrate] {src_table} 无数据，跳过")
                return
            if _target_has_rows(_admin_connect(dst_db).cursor(), dst_db, dst_table):
                logger.info(f"[migrate] {dst_db}.{dst_table} 已有数据，跳过")
                return
            cur.execute(f"SELECT {columns} FROM `{src_table}`")
            rows = cur.fetchall()
            if not rows:
                return
            cols = list(rows[0].keys())
            placeholders = ", ".join(["%s"] * len(cols))
            col_list = ", ".join(f"`{c}`" for c in cols)
            sql = f"INSERT IGNORE INTO `{dst_table}` ({col_list}) VALUES ({placeholders})"

            dst = _admin_connect(dst_db)
            try:
                with dst.cursor() as dc:
                    for r in rows:
                        dc.execute(sql, tuple(r[c] for c in cols))
                dst.commit()
                logger.info(f"[migrate] {src_table} → {dst_db}.{dst_table}（{len(rows)} 条）")
            finally:
                dst.close()
    finally:
        src.close()


def migrate_all_data():
    """执行全部数据迁移"""
    # 1. 用户拆分迁移
    migrate_users()

    # 2. login_devices → lc_auth
    _migrate_table("login_devices", get_db_name("auth"), "login_devices")

    # 3. chat 相关表 → lc_chat
    _migrate_table("conversations", get_db_name("chat"), "conversations")
    _migrate_table("messages", get_db_name("chat"), "messages")
    _migrate_table("message_feedback", get_db_name("chat"), "message_feedback")
    _migrate_table("api_call_logs", get_db_name("chat"), "api_call_logs")
    _migrate_table("tool_call_logs", get_db_name("chat"), "tool_call_logs")

    # 4. kb 相关表 → lc_kb
    _migrate_table("knowledge_bases", get_db_name("kb"), "knowledge_bases")
    _migrate_table("kb_documents", get_db_name("kb"), "kb_documents")

    # 5. rate_limit_events → lc_admin
    _migrate_table("rate_limit_events", get_db_name("admin"), "rate_limit_events")
    # 历史统计也复制一份到 admin（admin 看板用）
    _migrate_table("api_call_logs", get_db_name("admin"), "api_call_logs")
    _migrate_table("tool_call_logs", get_db_name("admin"), "tool_call_logs")

    logger.info("[migrate] 数据迁移全部完成")


def check_only():
    """仅检查：打印各库表状态，不执行迁移"""
    print("\n========== 微服务数据库检查 ==========\n")
    # 检查旧库
    try:
        conn = _admin_connect(OLD_DB)
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = [r[f"Tables_in_{OLD_DB}"] for r in cur.fetchall()]
            print(f"[旧库 {OLD_DB}] 现有表：{', '.join(tables) or '(空)'}")
            for t in tables:
                cur.execute(f"SELECT COUNT(*) AS c FROM `{t}`")
                print(f"    - {t}: {cur.fetchone()['c']} 行")
        conn.close()
    except Exception as e:
        print(f"[旧库 {OLD_DB}] 连接失败：{e}")

    # 检查新库
    for svc in ["auth", "user", "chat", "kb", "admin"]:
        db = get_db_name(svc)
        try:
            conn = _admin_connect(db)
            with conn.cursor() as cur:
                cur.execute("SHOW TABLES")
                tables = [r[f"Tables_in_{db}"] for r in cur.fetchall()]
                print(f"\n[{svc} → {db}] 现有表：{', '.join(tables) or '(空)'}")
                for t in tables:
                    cur.execute(f"SELECT COUNT(*) AS c FROM `{t}`")
                    print(f"    - {t}: {cur.fetchone()['c']} 行")
            conn.close()
        except Exception as e:
            print(f"\n[{svc} → {db}] 不存在或无法连接：{e}")
    print("\n======================================\n")


def main():
    """脚本入口：解析命令行参数，执行迁移（默认）或仅检查（--check）。"""
    parser = argparse.ArgumentParser(description="微服务数据库迁移")
    parser.add_argument("--check", action="store_true", help="仅检查不执行迁移")
    args = parser.parse_args()

    if args.check:
        check_only()
        return

    logger.info("====== 开始微服务数据库迁移 ======")
    create_databases()
    init_auth_schema()
    init_user_schema()
    init_chat_schema()
    init_kb_schema()
    init_admin_schema()
    migrate_all_data()
    logger.info("====== 微服务数据库迁移完成 ======")
    check_only()


if __name__ == "__main__":
    main()
