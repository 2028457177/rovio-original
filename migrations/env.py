"""Alembic 多库 env。

通过 `-x target=<auth|user|chat|kb|admin>` 切换目标库：
- 动态设置 sqlalchemy.url（按 target 选 AUTH_DB / USER_DB / ...）
- version_table = alembic_version_<target>（各库独立版本表）
- version_locations = versions/<target>（各库独立迁移链，相对 script_location=migrations）

本项目无 ORM，migration 文件用 op.execute() 写 raw SQL。

用法：
    alembic -x target=auth upgrade head
    alembic -x target=chat upgrade head
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ===== 解析 target =====
_xargs = context.get_x_argument(as_dictionary=True)
TARGET = _xargs.get("target", os.getenv("ALEMBIC_TARGET", "chat")).strip().lower()
_VALID = {"auth", "user", "chat", "kb", "admin"}
if TARGET not in _VALID:
    raise RuntimeError(f"unknown alembic target: {TARGET!r}, must be one of {_VALID}")

_DB_ENV = {
    "auth": "AUTH_DB",
    "user": "USER_DB",
    "chat": "CHAT_DB",
    "kb": "KB_DB",
    "admin": "ADMIN_DB",
}
_DB_DEFAULT = {
    "auth": "lc_auth",
    "user": "lc_user",
    "chat": "lc_chat",
    "kb": "lc_kb",
    "admin": "lc_admin",
}

db_name = os.getenv(_DB_ENV[TARGET], _DB_DEFAULT[TARGET])
mysql_user = os.getenv("MYSQL_USER", "root")
mysql_pwd = os.getenv("MYSQL_PASSWORD", "")
mysql_host = os.getenv("MYSQL_HOST", "localhost")
mysql_port = os.getenv("MYSQL_PORT", "3306")
# 密码里特殊字符做 URL 编码（pymysql url 要求）
from urllib.parse import quote_plus
_pwd_enc = quote_plus(mysql_pwd) if mysql_pwd else ""
_url = f"mysql+pymysql://{mysql_user}:{_pwd_enc}@{mysql_host}:{mysql_port}/{db_name}?charset=utf8mb4"

_VERSION_TABLE = f"alembic_version_{TARGET}"
_VERSION_LOCATIONS = f"migrations/versions/{TARGET}"

config.set_main_option("sqlalchemy.url", _url)


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本，不连库。"""
    context.configure(
        url=_url,
        version_table=_VERSION_TABLE,
        version_locations=_VERSION_LOCATIONS,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连库执行。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            version_table=_VERSION_TABLE,
            version_locations=_VERSION_LOCATIONS,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
