"""Redis 客户端（本服务独立副本，配置来自环境变量）。

所有微服务共享同一个 Redis 实例，用于：
- 跨服务 pub/sub 事件总线（chat → admin 的埋点事件）
- 限流计数
- 会话缓存
- 任务队列
"""
import redis
from redis import ConnectionPool

from .config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB, REDIS_MAX_CONNECTIONS
from .logger import logger

_pool = None


def _get_pool():
    """按配置创建并返回全局Redis连接池（懒加载单例）。"""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            db=REDIS_DB,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            max_connections=REDIS_MAX_CONNECTIONS,
        )
    return _pool


def get_redis_client() -> redis.Redis:
    """获取基于连接池的 Redis 客户端实例。"""
    return redis.Redis(connection_pool=_get_pool())


def is_redis_available() -> bool:
    """探测 Redis 是否可用（ping 成功返回 True，失败记日志返回 False）。"""
    try:
        get_redis_client().ping()
        return True
    except Exception:
        logger.warning("Redis 服务不可用，将跳过 Redis 相关功能")
        return False


def close_redis():
    """关闭 Redis 连接池并清空缓存引用。"""
    global _pool
    if _pool is not None:
        _pool.disconnect()
        _pool = None
        logger.info("Redis 连接池已关闭")
