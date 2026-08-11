"""kb baseline: knowledge_bases + kb_documents

Revision ID: kb_0001
Revises:
Create Date: 2026-08-03
"""
from alembic import op

revision = "kb_0001"
down_revision = None
branch_labels = ("kb",)
depends_on = None


def upgrade() -> None:
    op.execute("""
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
    op.execute("""
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kb_documents")
    op.execute("DROP TABLE IF EXISTS knowledge_bases")
