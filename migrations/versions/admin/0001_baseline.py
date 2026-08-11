"""admin baseline: rate_limit_events + api_call_logs + tool_call_logs

Revision ID: admin_0001
Revises:
Create Date: 2026-08-03
"""
from alembic import op

revision = "admin_0001"
down_revision = None
branch_labels = ("admin",)
depends_on = None


def upgrade() -> None:
    op.execute("""
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tool_call_logs")
    op.execute("DROP TABLE IF EXISTS api_call_logs")
    op.execute("DROP TABLE IF EXISTS rate_limit_events")
