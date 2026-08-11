"""自动记忆抽取器：从每轮对话中提取长期事实并写入向量库。

触发时机：chat_service.stream_response 流式完成后，在 finally 块用
run_in_executor 异步触发，不阻塞前端响应。

抽取策略：
1. 用 LLM 对 (user_message, assistant_message) 抽取 JSON 记忆列表
2. 对每条记忆先向量检索同用户已有记忆，相似度 > 阈值则跳过（去重）
3. 新记忆写入 Qdrant

软失败：任何异常静默记日志，不影响主对话流程。
"""
from __future__ import annotations

import json
import re
from typing import List, Dict

from AIRAGAgent.utils.config_handler import memory_conf
from AIRAGAgent.utils.logger_handler import logger
from AIRAGAgent.agent.memory.vector_store import memory_store


EXTRACTION_SYSTEM_PROMPT = """你是一个记忆抽取器。从用户与助手的单轮对话中，提取值得长期记住的用户信息。

只提取以下类型的信息：
- fact（事实）：用户的身份、职业、技能、所在城市、拥有的设备/账号等客观事实
- preference（偏好）：用户对回答风格、语言、格式、工具的明确偏好
- project（项目）：用户正在做的项目、任务、目标及其状态
- schedule（日程）：用户提到的固定日程、周期性事件、明确的未来计划

不要提取：
- 一次性的临时问题（"今天天气""现在几点"）
- 对话中助手给出的答案内容（那是知识不是用户信息）
- 推测而非用户明确表达的信息
- 闲聊寒暄（"你好""谢谢"）

输出格式：严格的 JSON 数组，无多余文字。每条：
{"type": "fact|preference|project|schedule", "content": "用第三人称描述这条用户信息，如：用户是 Python 开发者"}

如果没有值得记忆的信息，输出 []"""


def _build_extraction_user_msg(user_message: str, assistant_message: str) -> str:
    """构造发送给 LLM 的抽取提示词，拼接用户消息和助手回复。"""
    return f"""请从以下对话中提取值得长期记住的用户信息。

用户消息：
{user_message[:3000]}

助手回复：
{assistant_message[:3000]}

提取 JSON 数组（仅含长期用户信息，无则 []）："""


def _parse_extraction_response(text: str) -> List[Dict]:
    """从 LLM 响应中解析 JSON 数组，兼容被 ```json 包裹的情况。"""
    text = text.strip()
    # 去掉 ```json ... ``` 包裹
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # 截取第一个 [ 到最后一个 ]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
        if not isinstance(data, list):
            return []
        valid = []
        valid_types = {"fact", "preference", "project", "schedule"}
        for item in data:
            if not isinstance(item, dict):
                continue
            t = str(item.get("type", "fact")).strip()
            c = str(item.get("content", "")).strip()
            if t not in valid_types:
                t = "fact"
            if not c:
                continue
            valid.append({"type": t, "content": c[:2000]})
        return valid
    except Exception:
        return []


def _dedupe_and_save(user_id: int, memories: List[Dict], dedupe_threshold: float = 0.92) -> int:
    """对每条记忆去重后写入。返回实际写入条数。"""
    saved = 0
    max_memories = int(memory_conf.get("extraction_max_memories", 5))
    for m in memories[:max_memories]:
        try:
            # 先查同用户是否已有高度相似记忆
            existing = memory_store.search_memories(
                user_id, m["content"], top_k=1, score_threshold=dedupe_threshold
            )
            if existing:
                logger.debug(f"[memory] 跳过重复记忆: {m['content'][:40]} (score={existing[0].get('score', 0):.2f})")
                continue
            pid = memory_store.add_memory(
                user_id, m["type"], m["content"], source="auto", confidence=0.85
            )
            if pid:
                saved += 1
        except Exception as e:
            logger.debug(f"[memory] 单条写入失败: {e}")
    return saved


def extract_and_save(user_id: int, user_message: str, assistant_message: str) -> int:
    """同步抽取并保存记忆。返回写入条数。失败返回 0。

    供 chat_service 用线程池异步调用。
    """
    if not memory_conf.get("extraction_enabled", True):
        return 0
    min_len = int(memory_conf.get("extraction_min_user_msg_len", 6))
    if not user_message or len(user_message.encode("utf-8")) < min_len:
        return 0
    try:
        use_user_model = memory_conf.get("extraction_use_user_model", True)
        if use_user_model:
            from AIRAGAgent.model.factory import get_user_chat_model
            llm = get_user_chat_model(user_id)
        else:
            from AIRAGAgent.model.factory import chat_model
            llm = chat_model

        from langchain_core.messages import SystemMessage, HumanMessage
        resp = llm.invoke([
            SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
            HumanMessage(content=_build_extraction_user_msg(user_message, assistant_message)),
        ])
        text = resp.content if hasattr(resp, "content") else str(resp)
        memories = _parse_extraction_response(text)
        if not memories:
            return 0
        logger.info(f"[memory] 用户 {user_id} 抽取到 {len(memories)} 条候选记忆")
        return _dedupe_and_save(user_id, memories)
    except Exception as e:
        logger.warning(f"[memory] 抽取失败 user={user_id}: {e}")
        return 0


def extract_memories_async(user_id: int, user_message: str, assistant_message: str):
    """供 chat_service 在 finally 块用 run_in_executor 调用的同步入口。

    签名与 extract_and_save 一致；超时由 LLM 的 request_timeout 兜底
    （抽取 prompt 短，实际通常 2-5s 完成）。fire-and-forget，调用方无需 await。
    """
    return extract_and_save(user_id, user_message, assistant_message)
