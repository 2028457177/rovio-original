"""Redis pub/sub 事件总线（本服务独立副本）。

用于跨服务异步事件通信，典型场景：
- chat_service 完成一次对话 → 发布 chat.completed 事件（含耗时/Token/工具调用）
- admin_service 订阅 → 聚合到自己的统计库
- chat_service 触发限流 → 发布 rate.limited 事件
- admin_service 订阅 → 写入 rate_limit_events 表

相比同步 HTTP 调用，事件总线解耦且不阻塞主流程。
失败不影响业务（事件丢失可接受，统计略有偏差）。
"""
import json
import threading
import time
from typing import Callable

from .redis_client import get_redis_client, is_redis_available
from .logger import logger

# 事件频道命名
CHANNEL_CHAT_COMPLETED = "events:chat.completed"
CHANNEL_RATE_LIMITED = "events:rate.limited"
CHANNEL_TOOL_CALLED = "events:tool.called"


def publish_event(channel: str, payload: dict) -> bool:
    """发布事件到 Redis 频道。

    非阻塞、失败不抛异常（仅记日志）。
    Redis 不可用时静默跳过，业务继续。
    """
    if not is_redis_available():
        return False
    try:
        data = json.dumps(payload, ensure_ascii=False)
        client = get_redis_client()
        client.publish(channel, data)
        return True
    except Exception as e:
        logger.debug(f"[events] 发布 {channel} 失败: {e}")
        return False


def subscribe_events(channel: str, handler: Callable[[dict], None], stop_event: threading.Event):
    """在后台线程订阅事件频道，收到消息时调用 handler。

    handler 是同步函数（在订阅线程中执行），应快速返回。
    stop_event 用于优雅停止订阅。
    """
    if not is_redis_available():
        logger.warning(f"[events] Redis 不可用，无法订阅 {channel}")
        return

    def _run():
        """后台线程主循环：监听频道消息并调用 handler 处理，stop_event 置位后退出。"""
        try:
            client = get_redis_client()
            pubsub = client.pubsub()
            pubsub.subscribe(channel)
            logger.info(f"[events] 已订阅频道 {channel}")
            for message in pubsub.listen():
                if stop_event.is_set():
                    break
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    handler(payload)
                except Exception as e:
                    logger.error(f"[events] 处理 {channel} 事件失败: {e}")
            pubsub.unsubscribe(channel)
            pubsub.close()
            logger.info(f"[events] 已停止订阅 {channel}")
        except Exception as e:
            logger.error(f"[events] 订阅 {channel} 异常: {e}")

    t = threading.Thread(target=_run, name=f"sub-{channel}", daemon=True)
    t.start()
    return t
