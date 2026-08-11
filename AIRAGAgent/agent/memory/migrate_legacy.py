"""旧 user_memories 表数据迁移到 Qdrant 向量库。

用法：
    cd 项目根
    python -m AIRAGAgent.agent.memory.migrate_legacy

迁移逻辑：
1. 从 MySQL user_memories 表读取所有 is_active=1 的记忆
2. 对每条记忆用嵌入模型生成向量
3. 写入 Qdrant 的 user_memories 集合（payload 含 user_id/memory_type/content/source/confidence）

注意：
- 迁移是幂等的：重复运行会写入重复 point（不同 point_id），但 _dedupe_and_save 阶段
  会按相似度去重，所以后续自动抽取不会产生重复。如需完全去重，迁移前先清空 Qdrant 集合。
- 迁移后旧表保留（不删除），可手动 DROP TABLE user_memories 确认无误后清理。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from AIRAGAgent.utils.logger_handler import logger
from AIRAGAgent.utils.config_handler import memory_conf


def migrate():
    """读取旧表数据，写入 Qdrant。"""
    # 先确保 Qdrant 初始化（建集合 + 探测维度）
    from AIRAGAgent.agent.memory.vector_store import memory_store
    if not memory_store._ensure_initialized():
        logger.error("[migrate] Qdrant 不可用，迁移终止。请先启动 Qdrant（deploy/qdrant）")
        return 0

    # 读旧表
    from AIRAGAgent.database import recall_memories
    # recall_memories 按 user_id 查，迁移需要全量。直接用裸 SQL。
    from AIRAGAgent.database.connection import get_db
    rows = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id, memory_type, key_name, value, source, confidence, updated_at "
                "FROM user_memories WHERE is_active = 1"
            )
            rows = list(cursor.fetchall())
    except Exception as e:
        logger.error(f"[migrate] 读旧表失败: {e}")
        return 0

    if not rows:
        logger.info("[migrate] 旧表无数据，无需迁移")
        return 0

    logger.info(f"[migrate] 读到 {len(rows)} 条旧记忆，开始写入 Qdrant...")

    # 嵌入复用 memory_store 的 embeddings 实例
    embeddings = memory_store._embeddings
    client = memory_store._client
    collection = memory_store._collection

    # 把 key_name + value 拼成 content，保留 key_name 在 payload
    texts = []
    payloads = []
    for r in rows:
        key = r.get("key_name", "")
        val = r.get("value", "")
        content = f"{key}: {val}" if key and key != val else val
        content = (content or "").strip()
        if not content:
            continue
        texts.append(content)
        payloads.append({
            "user_id": int(r["user_id"]),
            "memory_type": str(r.get("memory_type", "fact"))[:30],
            "content": content[:65000],
            "source": f"legacy:{r.get('source', 'agent')}"[:100],
            "confidence": float(r.get("confidence", 1.0)),
            "legacy_key": str(key)[:200],
            "created_at": r.get("updated_at") or datetime.utcnow().isoformat(),
            "updated_at": r.get("updated_at") or datetime.utcnow().isoformat(),
        })

    if not texts:
        logger.info("[migrate] 过滤后无有效内容，跳过")
        return 0

    # 批量嵌入（OpenAICompatEmbeddings 支持 batch）
    try:
        vectors = embeddings.embed_documents(texts)
    except Exception as e:
        logger.error(f"[migrate] 批量嵌入失败: {e}")
        return 0

    # 批量 upsert（用 PointStruct，新版 qdrant-client 不接受裸 dict）
    from qdrant_client.http import models as qm
    points = []
    for vec, payload in zip(vectors, payloads):
        points.append(qm.PointStruct(
            id=uuid.uuid4().hex,
            vector=vec,
            payload=payload,
        ))

    try:
        client.upsert(collection_name=collection, points=points)
        logger.info(f"[migrate] 成功写入 {len(points)} 条记忆到 Qdrant 集合 '{collection}'")
        return len(points)
    except Exception as e:
        logger.error(f"[migrate] Qdrant upsert 失败: {e}")
        return 0


if __name__ == "__main__":
    count = migrate()
    print(f"\n迁移完成：共写入 {count} 条记忆到 Qdrant")
    # 打印当前 Qdrant 状态
    from AIRAGAgent.agent.memory.vector_store import memory_store
    print(f"Qdrant 状态: {memory_store.status()}")
