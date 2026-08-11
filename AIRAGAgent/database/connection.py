import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager

from AIRAGAgent.utils.config_handler import mysql_conf


def _get_db_config():
    """从配置读取 MySQL 连接参数，组装成 pymysql 连接配置字典。"""
    return {
        "host": mysql_conf.get("host", "localhost"),
        "port": int(mysql_conf.get("port", 3306)),
        "user": mysql_conf.get("user", "root"),
        "password": mysql_conf.get("password", ""),
        "database": mysql_conf.get("database", "agent_records"),
        "charset": mysql_conf.get("charset", "utf8mb4"),
        "cursorclass": DictCursor,
        "autocommit": True,
    }


def get_connection():
    """创建一个新的 MySQL 数据库连接。"""
    return pymysql.connect(**_get_db_config())


@contextmanager
def get_db():
    """上下文管理器：获取一个数据库连接，退出时自动关闭。"""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """初始化数据库：创建缺失的表，并给历史表补充缺失的列和索引。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id VARCHAR(100) PRIMARY KEY,
                user_id BIGINT NOT NULL DEFAULT 0,
                title VARCHAR(255) NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_conv_user (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # 迁移：给已有的 conversations 表补充 user_id 列
        _safe_add_column(cursor, "conversations", "user_id", "BIGINT NOT NULL DEFAULT 0")
        _safe_add_index(cursor, "conversations", "idx_conv_user", "user_id")
        # 迁移：软删除标记
        _safe_add_column(cursor, "conversations", "is_deleted", "TINYINT NOT NULL DEFAULT 0")
        # 迁移：置顶 / 收藏 / 文件夹（自助管理增强）
        _safe_add_column(cursor, "conversations", "pinned", "TINYINT NOT NULL DEFAULT 0")
        _safe_add_column(cursor, "conversations", "starred", "TINYINT NOT NULL DEFAULT 0")
        _safe_add_column(cursor, "conversations", "folder", "VARCHAR(100) NOT NULL DEFAULT ''")
        _safe_add_index(cursor, "conversations", "idx_conv_user_pinned", "user_id, pinned")
        # 迁移：对话分支功能 —— 记录父会话与分叉点消息
        _safe_add_column(cursor, "conversations", "parent_conversation_id", "VARCHAR(100) NOT NULL DEFAULT ''")
        _safe_add_column(cursor, "conversations", "branch_point_message_id", "BIGINT NOT NULL DEFAULT 0")
        _safe_add_index(cursor, "conversations", "idx_conv_parent", "parent_conversation_id")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                conversation_id VARCHAR(100) NOT NULL,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_conv_created (conversation_id, created_at),
                INDEX idx_msg_content (content(100)),
                CONSTRAINT fk_messages_conversation
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # DeepAgent plan 持久化：存 {plan, steps} JSON，让 Plan 面板刷新后仍能显示
        _safe_add_column(cursor, "messages", "extra_json", "TEXT NULL")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(100) NOT NULL DEFAULT '',
                role VARCHAR(20) NOT NULL DEFAULT 'user',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_users_username (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # 迁移：给已有的 users 表补充 role 列
        _safe_add_column(cursor, "users", "role", "VARCHAR(20) NOT NULL DEFAULT 'user'")
        # 迁移：用户自助功能所需字段
        _safe_add_column(cursor, "users", "avatar_url", "VARCHAR(255) NOT NULL DEFAULT ''")
        _safe_add_column(cursor, "users", "email", "VARCHAR(100) NOT NULL DEFAULT ''")
        _safe_add_column(cursor, "users", "security_question", "VARCHAR(200) NOT NULL DEFAULT ''")
        _safe_add_column(cursor, "users", "security_answer_hash", "VARCHAR(255) NOT NULL DEFAULT ''")
        _safe_add_column(cursor, "users", "last_password_changed", "DATETIME NULL")
        # 迁移：课表设置（按用户隔离）
        _safe_add_column(cursor, "users", "schedule_file", "VARCHAR(255) NOT NULL DEFAULT ''")
        _safe_add_column(cursor, "users", "schedule_start_date", "DATE NULL")
        _safe_add_column(cursor, "users", "schedule_uploaded_at", "DATETIME NULL")

        # 登录设备表
        cursor.execute("""
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
                INDEX idx_login_user (user_id, is_revoked),
                CONSTRAINT fk_login_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # 消息反馈表
        cursor.execute("""
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

        # 知识库表：多知识库隔离（全局 / 个人）
        cursor.execute("""
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

        # 知识库文档表：来源 / 版本 / 上传人 / 状态记录
        cursor.execute("""
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

        # ===== 数据统计埋点表 =====
        # API 调用日志：记录每次 /api/chat 调用
        cursor.execute("""
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

        # 工具调用日志：记录每次工具调用
        cursor.execute("""
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

        # 限流事件日志
        cursor.execute("""
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

        # ===== DeepAgent 架构：Plan / Plan Step =====
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id VARCHAR(64) PRIMARY KEY,
                user_id BIGINT NOT NULL DEFAULT 0,
                session_id VARCHAR(100) NOT NULL DEFAULT '',
                goal TEXT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'planning',
                final_answer TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_plan_user (user_id),
                INDEX idx_plan_session (session_id),
                INDEX idx_plan_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plan_steps (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                plan_id VARCHAR(64) NOT NULL,
                step_idx INT NOT NULL,
                description TEXT NOT NULL,
                subagent VARCHAR(50) NOT NULL DEFAULT '',
                depends_on VARCHAR(255) NOT NULL DEFAULT '',
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                result TEXT,
                attempts INT NOT NULL DEFAULT 0,
                error_msg TEXT,
                started_at DATETIME NULL,
                finished_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_step_plan (plan_id),
                INDEX idx_step_status (status),
                CONSTRAINT fk_step_plan
                    FOREIGN KEY (plan_id) REFERENCES plans(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # ===== DeepAgent 架构：结构化记忆 =====
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                memory_type VARCHAR(30) NOT NULL DEFAULT 'fact',
                key_name VARCHAR(200) NOT NULL DEFAULT '',
                value TEXT NOT NULL,
                source VARCHAR(100) NOT NULL DEFAULT 'agent',
                confidence DECIMAL(3,2) NOT NULL DEFAULT 1.00,
                is_active TINYINT NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_user_key (user_id, key_name),
                INDEX idx_mem_user (user_id, is_active),
                INDEX idx_mem_type (memory_type),
                INDEX idx_mem_key (user_id, key_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # 迁移：为已有表补 UNIQUE 索引（若已存在则跳过）
        try:
            cursor.execute("CREATE UNIQUE INDEX uk_user_key ON user_memories (user_id, key_name)")
        except Exception:
            pass

        # ===== DeepAgent 架构：Artifact 一等公民 =====
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id VARCHAR(64) PRIMARY KEY,
                user_id BIGINT NOT NULL,
                session_id VARCHAR(100) NOT NULL DEFAULT '',
                plan_id VARCHAR(64) NOT NULL DEFAULT '',
                step_idx INT NULL,
                type VARCHAR(30) NOT NULL DEFAULT 'doc',
                title VARCHAR(255) NOT NULL DEFAULT '',
                content_ref VARCHAR(500) NOT NULL DEFAULT '',
                mime_type VARCHAR(100) NOT NULL DEFAULT '',
                version INT NOT NULL DEFAULT 1,
                parent_id VARCHAR(64) NOT NULL DEFAULT '',
                meta JSON NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_art_user (user_id),
                INDEX idx_art_session (session_id),
                INDEX idx_art_plan (plan_id),
                INDEX idx_art_type (type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.commit()

        # 创建默认管理员账号 admin/admin123
        _seed_admin_user(cursor, conn)


def _safe_add_column(cursor, table: str, column: str, definition: str):
    """安全添加列：如果列已存在则跳过"""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except Exception:
        pass  # 列已存在，跳过


def _safe_add_index(cursor, table: str, index_name: str, columns: str):
    """安全添加索引：如果索引已存在则跳过"""
    try:
        cursor.execute(f"CREATE INDEX {index_name} ON {table} ({columns})")
    except Exception:
        pass  # 索引已存在，跳过


def _seed_admin_user(cursor, conn):
    """创建默认管理员账号 admin/admin123（如果不存在）"""
    import hashlib
    import os
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    if cursor.fetchone():
        return
    # 使用与 models.py 相同的密码哈希方式
    salt = os.urandom(32)
    hash_obj = hashlib.pbkdf2_hmac("sha256", "admin123".encode("utf-8"), salt, 100000)
    password_hash = salt.hex() + ":" + hash_obj.hex()
    cursor.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (%s, %s, %s, %s)",
        ("admin", password_hash, "系统管理员", "admin")
    )
    conn.commit()


def close_pool():
    """关闭数据库连接池（当前为空实现，预留接口）。"""
    pass
