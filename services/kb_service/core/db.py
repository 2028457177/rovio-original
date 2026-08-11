"""MySQL 连接辅助（本服务独立库）。

每个微服务调用 get_db() 拿到自己独立数据库的连接。
"""
from contextlib import contextmanager
import pymysql
from pymysql.cursors import DictCursor

from .config import get_mysql_config
from .logger import logger

# 本服务连接配置缓存
_cfg = None


def _get_config() -> dict:
    """获取本服务的 MySQL 连接配置（带缓存），首次调用时补上游标与自动提交设置。"""
    global _cfg
    if _cfg is None:
        _cfg = get_mysql_config()
        _cfg["cursorclass"] = DictCursor
        _cfg["autocommit"] = True
    return _cfg


def get_connection() -> pymysql.connections.Connection:
    """获取本服务数据库连接"""
    return pymysql.connect(**_get_config())


@contextmanager
def get_db():
    """上下文管理器：自动关闭连接。

    用法::

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ...")
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def ensure_database_exists():
    """确保本服务的数据库已创建。

    连接 MySQL 时不指定 database，CREATE DATABASE IF NOT EXISTS。
    """
    cfg = get_mysql_config()
    admin_cfg = {k: v for k, v in cfg.items() if k != "database"}
    conn = pymysql.connect(**admin_cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` "
                f"CHARACTER SET {cfg.get('charset', 'utf8mb4')} COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        logger.info(f"[db] 确保数据库 {cfg['database']} 存在")
    finally:
        conn.close()
