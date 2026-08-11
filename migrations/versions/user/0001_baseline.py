"""user baseline: user_profiles + user_schedules + user_models

Revision ID: user_0001
Revises:
Create Date: 2026-08-03
"""
from alembic import op

revision = "user_0001"
down_revision = None
branch_labels = ("user",)
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id BIGINT PRIMARY KEY,
            display_name VARCHAR(100) NOT NULL DEFAULT '',
            email VARCHAR(100) NOT NULL DEFAULT '',
            avatar_url VARCHAR(255) NOT NULL DEFAULT '',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_schedules (
            user_id BIGINT PRIMARY KEY,
            file_path VARCHAR(255) NOT NULL DEFAULT '',
            start_date DATE NULL,
            uploaded_at DATETIME NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_models (
            user_id BIGINT PRIMARY KEY,
            base_url VARCHAR(500) NOT NULL DEFAULT '',
            api_key VARCHAR(500) NOT NULL DEFAULT '',
            model_name VARCHAR(200) NOT NULL DEFAULT '',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_models")
    op.execute("DROP TABLE IF EXISTS user_schedules")
    op.execute("DROP TABLE IF EXISTS user_profiles")
