import time
from typing import Optional, Tuple
from AIRAGAgent.infrastructure.redis_client import get_redis_client, is_redis_available
from AIRAGAgent.utils.config_handler import redis_conf
from AIRAGAgent.utils.logger_handler import logger

RATE_LIMIT_CONFIG = redis_conf.get("rate_limit", {})
RATE_LIMIT_PREFIX = "rate_limit:"


class RateLimiter:
    def __init__(self, key_prefix: str, max_requests: int, window_seconds: int):
        """初始化限流器：记录前缀、窗口内最大请求数与窗口时长。"""
        self.key_prefix = key_prefix
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def is_allowed(self, identifier: str) -> Tuple[bool, int]:
        """判断指定标识符是否允许请求，返回 (是否放行, 剩余配额)。"""
        if not is_redis_available():
            return True, self.max_requests

        now = int(time.time())
        window_start = now - self.window_seconds
        key = f"{RATE_LIMIT_PREFIX}{self.key_prefix}:{identifier}"

        try:
            client = get_redis_client()
            pipe = client.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            _, current_count = pipe.execute()

            if current_count < self.max_requests:
                pipe = client.pipeline()
                pipe.zadd(key, {str(now): now})
                pipe.expire(key, self.window_seconds + 1)
                pipe.execute()
                remaining = self.max_requests - current_count - 1
                return True, remaining

            return False, 0
        except Exception as e:
            logger.warning(f"限流检查异常: {e}")
            return True, self.max_requests

    def reset(self, identifier: str):
        """清除指定标识符的限流记录。"""
        if not is_redis_available():
            return
        try:
            client = get_redis_client()
            key = f"{RATE_LIMIT_PREFIX}{self.key_prefix}:{identifier}"
            client.delete(key)
        except Exception as e:
            logger.warning(f"限流重置失败: {e}")


class RateLimiterFactory:
    _instances: dict[str, RateLimiter] = {}

    @classmethod
    def get(cls, name: str) -> RateLimiter:
        """按名称获取限流器实例（未创建则按配置新建并缓存）。"""
        if name not in cls._instances:
            config = RATE_LIMIT_CONFIG.get(name, {})
            max_requests = int(config.get("max_requests", 30))
            window_seconds = int(config.get("window_seconds", 60))
            cls._instances[name] = RateLimiter(
                key_prefix=name,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
        return cls._instances[name]


def get_chat_rate_limiter() -> RateLimiter:
    """获取对话场景（chat）的限流器实例。"""
    return RateLimiterFactory.get("chat")


def get_tool_rate_limiter() -> RateLimiter:
    """获取工具调用场景的限流器实例。"""
    return RateLimiterFactory.get("tool")
