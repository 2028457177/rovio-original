"""chat_service 数据库重定向 + 事件桥接。

在 import AIRAGAgent 之前调用 apply_db_redirect()，把 AIRAGAgent.database 的
连接配置重定向到 lc_chat 数据库，并替换 log_rate_limit_event 为 Redis 事件发布。

这样 AIRAGAgent.agent / middleware / rag 等模块中所有 get_db() 调用
都会落到 lc_chat，无需改动原有代码。
"""
import time as _time


_DB_PATCHED = False


def apply_db_redirect():
    """把 AIRAGAgent.database 重定向到 lc_chat + 桥接事件发布。

    幂等，重复调用无副作用。
    """
    global _DB_PATCHED
    if _DB_PATCHED:
        return

    import AIRAGAgent.database.connection as _conn
    from core.config import DB_NAME
    from core.logger import logger

    # 1. 重定向数据库
    new_db = DB_NAME
    old_db = _conn.mysql_conf.get("database", "agent_records")
    _conn.mysql_conf["database"] = new_db
    logger.info(f"[chat_service] AIRAGAgent.database 重定向: {old_db} → {new_db}")

    # 2. 替换 log_rate_limit_event：rate_limit_events 表在 lc_admin，不在 lc_chat
    #    改为发布 Redis 事件，由 admin_service 订阅落库
    import AIRAGAgent.database as _db
    from core.events import publish_event, CHANNEL_RATE_LIMITED

    def _log_rate_limit_event_via_redis(user_id, ip, limit_type, identifier):
        """以发布 Redis 事件的方式上报限流记录（替代原直写数据库）。"""
        try:
            publish_event(CHANNEL_RATE_LIMITED, {
                "user_id": user_id,
                "ip": ip,
                "limit_type": limit_type,
                "identifier": identifier,
            })
        except Exception as e:
            logger.debug(f"[chat_service] 发布 rate.limited 事件失败: {e}")

    _db.log_rate_limit_event = _log_rate_limit_event_via_redis

    # 3. 包装 log_tool_call：写 lc_chat + 发布 Redis 事件供 admin 聚合
    from core.events import publish_event as _pub, CHANNEL_TOOL_CALLED as _CH_TOOL
    _orig_log_tool_call = _db.log_tool_call

    def _log_tool_call_with_event(user_id, session_id, tool_name, duration_ms, is_success, error_msg):
        """写工具调用日志到 lc_chat 库，并同时发布 Redis 事件供 admin 聚合。"""
        try:
            _orig_log_tool_call(user_id, session_id, tool_name, duration_ms, is_success, error_msg)
        except Exception as e:
            logger.debug(f"[chat_service] log_tool_call 写库失败: {e}")
        try:
            _pub(_CH_TOOL, {
                "user_id": user_id,
                "session_id": session_id,
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "is_success": is_success,
                "error_msg": error_msg or "",
            })
        except Exception:
            pass

    _db.log_tool_call = _log_tool_call_with_event

    _DB_PATCHED = True
    logger.info("[chat_service] DB 重定向 + 事件桥接完成")
