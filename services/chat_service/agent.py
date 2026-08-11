"""chat_service Agent 封装（DeepAgent 架构）。

改造点：
- 复用 AIRAGAgent.agent.Orchestrator（Planner/Executor/Reflector/Finalizer）
- 会话持久化通过 AIRAGAgent.database（已重定向到 lc_chat）
- log_api_call 写 lc_chat + 发布 chat.completed Redis 事件供 admin_service 聚合
- 支持 plan 后台异步执行（通过 task_queue）
"""
import asyncio
import contextvars
import time

from core.logger import logger
from core.events import publish_event, CHANNEL_CHAT_COMPLETED

# 必须在 import AIRAGAgent 之前完成 DB 重定向
import db_patch
db_patch.apply_db_redirect()

from AIRAGAgent.agent.orchestrator import get_orchestrator
from AIRAGAgent.database import (
    save_message, get_session_messages, clear_session, truncate_session_messages,
    log_api_call,
)
from AIRAGAgent.infrastructure.session_cache import (
    cache_session_messages, get_cached_session, invalidate_session,
)
from AIRAGAgent.infrastructure.task_queue import enqueue_task, TaskType
from AIRAGAgent.agent.tools.agent_tools import user_ip_var


def _estimate_tokens(text: str) -> int:
    """粗略估算文本的 token 数（中文按 1 字 1 token，其他字符按 4 个算 1 token）。"""
    if not text:
        return 0
    chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_count = len(text) - chinese_count
    return chinese_count + other_count // 4


class AgentService:
    """Agent 服务：DeepAgent 流式输出 + 会话持久化 + 埋点统计 + 后台执行"""

    def __init__(self):
        # 复用 Orchestrator 单例（内部触发 SubAgent 注册）
        self.agent = get_orchestrator()

    @staticmethod
    def _get_session_messages_with_cache(user_id: int, session_id: str) -> list:
        """带缓存读取会话消息：先查缓存，未命中再查库并回填缓存。"""
        if not session_id:
            return None
        cached = get_cached_session(user_id, session_id)
        if cached is not None:
            return cached
        messages = get_session_messages(user_id, session_id)
        if messages:
            cache_session_messages(user_id, session_id, messages)
        return messages

    @staticmethod
    def _save_session_messages_with_cache(user_id: int, session_id: str,
                                          user_message: str, assistant_message: str):
        """把用户与助手消息写入数据库并刷新该会话的 Redis 缓存，返回两条消息ID。"""
        user_msg_id = save_message(user_id, session_id, "user", user_message)
        assistant_msg_id = save_message(user_id, session_id, "assistant", assistant_message)
        full_messages = get_session_messages(user_id, session_id)
        cache_session_messages(user_id, session_id, full_messages)
        return user_msg_id, assistant_msg_id

    async def stream_response(self, user_id: int, message: str,
                             session_id: str = None, truncate_to: int = None):
        """流式输出（DeepAgent Orchestrator，产出 plan_* / step_* / thinking / output 事件）"""
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()
        ctx = contextvars.copy_context()
        _start_ts = time.time()
        _collected_output: list = []

        def sync_producer():
            """在后台线程中执行 Agent 流式输出，把事件块塞进队列供异步消费者转发。"""
            try:
                logger.debug(f"[chat] 开始流式输出: {message[:30]}...")
                if truncate_to is not None and session_id:
                    try:
                        truncate_session_messages(user_id, session_id, int(truncate_to))
                    except Exception as te:
                        logger.warning(f"[chat] 历史回滚失败: {te}")
                chat_history = self._get_session_messages_with_cache(user_id, session_id)
                full_response_parts = []

                # Orchestrator.execute_stream 签名：(query, chat_history, user_id, session_id)
                for chunk in self.agent.execute_stream(
                    message, chat_history, user_id=user_id, session_id=session_id or ""
                ):
                    if isinstance(chunk, dict):
                        if chunk.get("type") == "output":
                            full_response_parts.append(chunk.get("content", ""))
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
                    else:
                        content = chunk.strip()
                        if content:
                            full_response_parts.append(content)
                            loop.call_soon_threadsafe(queue.put_nowait, content)

                if session_id:
                    full_response = "".join(full_response_parts)
                    _msg_ids = self._save_session_messages_with_cache(
                        user_id, session_id, message, full_response
                    )
                    loop.call_soon_threadsafe(queue.put_nowait, {
                        "type": "message_ids",
                        "user_message_id": _msg_ids[0],
                        "assistant_message_id": _msg_ids[1],
                    })
                loop.call_soon_threadsafe(_collected_output.extend, full_response_parts)
            except Exception as e:
                logger.error(f"[chat] 流式响应失败: {e}", exc_info=True)
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

        loop.run_in_executor(None, lambda: ctx.run(sync_producer))

        _has_error = False
        _error_msg = ""
        try:
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    break
                if isinstance(item, Exception):
                    _has_error = True
                    _error_msg = str(item)
                    raise item
                yield item
        finally:
            # 埋点：写 lc_chat + 发布 Redis 事件
            try:
                duration_ms = int((time.time() - _start_ts) * 1000)
                full_response_str = "".join(_collected_output)
                prompt_tokens = _estimate_tokens(message)
                try:
                    chat_history = self._get_session_messages_with_cache(user_id, session_id)
                    if chat_history:
                        history_text = " ".join(m.get("content", "") for m in chat_history)
                        prompt_tokens += _estimate_tokens(history_text)
                except Exception:
                    pass
                completion_tokens = _estimate_tokens(full_response_str)

                log_api_call(
                    user_id=user_id,
                    session_id=session_id or "",
                    ip=user_ip_var.get() or "",
                    endpoint="chat",
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    is_success=not _has_error,
                    error_msg=_error_msg,
                )

                # 发布 chat.completed 事件供 admin_service 聚合
                publish_event(CHANNEL_CHAT_COMPLETED, {
                    "user_id": user_id,
                    "session_id": session_id or "",
                    "ip": user_ip_var.get() or "",
                    "endpoint": "chat",
                    "duration_ms": duration_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "is_success": not _has_error,
                    "error_msg": _error_msg,
                })
            except Exception as log_e:
                logger.debug(f"[chat] 埋点/事件发布失败: {log_e}")

            # 自动记忆抽取：流式完成后异步触发（fire-and-forget，不阻塞响应）
            # Qdrant/嵌入不可用时静默放弃，不影响主流程
            try:
                if not _has_error and message:
                    full_resp_for_mem = "".join(_collected_output)
                    if full_resp_for_mem:
                        from AIRAGAgent.agent.memory.extractor import extract_memories_async
                        loop.run_in_executor(None, lambda: ctx.run(
                            extract_memories_async, user_id, message, full_resp_for_mem
                        ))
            except Exception as mem_e:
                logger.debug(f"[chat] 记忆抽取投递失败: {mem_e}")

    def enqueue_plan_background(self, user_id: int, message: str,
                                session_id: str = None,
                                search_enabled: bool = True) -> str | None:
        """把 plan 投递到 task_queue 后台执行（不阻塞，返回 task_id 供轮询）。

        适用于长耗时任务（生成大报告、批量操作），用户通过 /api/tasks/{task_id} 查询进度。
        """
        chat_history = self._get_session_messages_with_cache(user_id, session_id) if session_id else []
        params = {
            "query": message,
            "chat_history": chat_history or [],
            "user_id": user_id,
            "session_id": session_id or "",
            "search_enabled": search_enabled,
        }
        return enqueue_task(TaskType.PLAN_EXECUTE, params, priority=1)

    async def clear_session(self, user_id: int, session_id: str) -> None:
        """清除指定会话的消息记录并使其缓存失效，失败时抛出异常。"""
        try:
            clear_session(user_id, session_id)
            invalidate_session(user_id, session_id)
        except Exception as e:
            logger.error(f"[chat] 清除会话失败: {e}", exc_info=True)
            raise
