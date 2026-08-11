"""auth baseline: users + security_questions + login_devices

Revision ID: auth_0001
Revises:
Create Date: 2026-08-03
"""
from alembic import op

revision = "auth_0001"
down_revision = None
branch_labels = ("auth",)
depends_on = None


def upgrade() -> None:
    op.execute("""
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
    op.execute("""
        CREATE TABLE IF NOT EXISTS security_questions (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL UNIQUE,
            question VARCHAR(200) NOT NULL,
            answer_hash VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_sq_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    op.execute("""
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS login_devices")
    op.execute("DROP TABLE IF EXISTS security_questions")
    op.execute("DROP TABLE IF EXISTS users")
