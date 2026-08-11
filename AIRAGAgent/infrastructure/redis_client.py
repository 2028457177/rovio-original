import redis
from redis import ConnectionPool
from AIRAGAgent.utils.config_handler import redis_conf
from AIRAGAgent.utils.logger_handler import logger

_pool = None


def _get_pool():
    """按配置创建并返回全局Redis连接池（懒加载单例）。"""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            host=redis_conf.get("host", "localhost"),
            port=int(redis_conf.get("port", 6379)),
            password=redis_conf.get("password", "") or None,
            db=int(redis_conf.get("db", 0)),
            decode_responses=redis_conf.get("decode_responses", True),
            socket_timeout=float(redis_conf.get("socket_timeout", 5)),
            socket_connect_timeout=float(redis_conf.get("socket_connect_timeout", 5)),
            max_connections=int(redis_conf.get("max_connections", 20)),
        )
    return _pool


def get_redis_client():
    """基于全局连接池创建一个Redis客户端并返回。"""
    return redis.Redis(connection_pool=_get_pool())


def is_redis_available():
    """探测 Redis 是否可用（ping 通即返回 True，否则记录警告并返回 False）。"""
    try:
        client = get_redis_client()
        client.ping()
        return True
    except Exception:
        logger.warning("Redis 服务不可用，将跳过 Redis 相关功能")
        return False


def close_redis():
    """关闭并释放全局Redis连接池。"""
    global _pool
    if _pool is not None:
        _pool.disconnect()
        _pool = None
        logger.info("Redis 连接池已关闭")
