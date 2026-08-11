"""长期记忆模块：向量检索 + 自动抽取。

替代旧的结构化 KV 记忆（user_memories 表 + memory SubAgent 工具）：
- 存储：Qdrant 向量库（payload 含 user_id 做用户隔离）
- 嵌入：复用 chroma.yml 的 OpenAI 兼容嵌入（与 KB 同源，维度一致）
- 写入：自动抽取器从每轮对话中提取长期事实，无需用户/Agent 主动调用
- 召回：Planner 阶段按 query 向量召回 top-k 注入上下文
"""
from AIRAGAgent.agent.memory.vector_store import memory_store, MemoryVectorStore
from AIRAGAgent.agent.memory.extractor import extract_memories_async

__all__ = ["memory_store", "MemoryVectorStore", "extract_memories_async"]
