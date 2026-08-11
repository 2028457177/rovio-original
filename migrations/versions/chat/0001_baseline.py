"""chat baseline: conversations + messages + feedback + logs + plans + steps + memories + artifacts

Revision ID: chat_0001
Revises:
Create Date: 2026-08-03
"""
from alembic import op

revision = "chat_0001"
down_revision = None
branch_labels = ("chat",)
depends_on = None


def upgrade() -> None:
    # conversations（含软删除 / 置顶 / 收藏 / 文件夹 / 分支）
    op.execute("""
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
    # messages（含 extra_json：plan 持久化）
    op.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            conversation_id VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            extra_json TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_conv_created (conversation_id, created_at),
            INDEX idx_msg_content (content(100))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    op.execute("""
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
    op.execute("""
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
    op.execute("""
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
    # DeepAgent: plans / plan_steps
    op.execute("""
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
    op.execute("""
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
    # DeepAgent: 结构化记忆
    op.execute("""
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
    # DeepAgent: Artifact 一等公民
    op.execute("""
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS artifacts")
    op.execute("DROP TABLE IF EXISTS user_memories")
    op.execute("DROP TABLE IF EXISTS plan_steps")
    op.execute("DROP TABLE IF EXISTS plans")
    op.execute("DROP TABLE IF EXISTS tool_call_logs")
    op.execute("DROP TABLE IF EXISTS api_call_logs")
    op.execute("DROP TABLE IF EXISTS message_feedback")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
