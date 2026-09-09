"""user_schedules 增加 parsed_courses 列：上传时预解析的课表 JSON

课表查询（agent get_schedule）原先每次都 pd.read_excel 重新读文件并正则解析，
现改为上传时解析一次存入该列，查询时直接读 DB 过滤；列为 NULL 时回退旧 Excel 解析。

Revision ID: user_0002
Revises: user_0001
Create Date: 2026-09-09
"""
from alembic import op

revision = "user_0002"
down_revision = "user_0001"
branch_labels = ("user",)
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE user_schedules
            ADD COLUMN parsed_courses JSON NULL AFTER start_date
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE user_schedules DROP COLUMN parsed_courses
    """)
