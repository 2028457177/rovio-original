"""记忆向量存储层：Qdrant + OpenAI 兼容嵌入。

设计要点：
1. 懒初始化：首次调用才连接 Qdrant + 探测维度 + 创建 collection，
   避免服务启动时因 Qdrant 未就绪而崩溃。
2. 单例：模块级 `memory_store` 实例，Qdrant client 线程安全。
3. 用户隔离：所有操作按 user_id payload 过滤。
4. 嵌入复用：直接用 kb/embedding.py 的 get_kb_embeddings()，
   与 KB 共享同一嵌入模型，保证向量空间一致。
5. 软失败：Qdrant 不可用时 search 返回空列表，add 静默失败并记日志，
   不影响主对话流程。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Dict, Optional

from AIRAGAgent.utils.config_handler import memory_conf
from AIRAGAgent.utils.logger_handler import logger


class MemoryVectorStore:
    """Qdrant 记忆向量库封装。"""

    def __init__(self):
        """初始化记忆存储实例，读取集合名、距离度量、向量维度等配置。"""
        self._client = None
        self._embeddings = None
        self._collection: str = str(memory_conf.get("qdrant_collection", "user_memories"))
        self._distance: str = str(memory_conf.get("distance", "Cosine"))
        self._dim: int = int(memory_conf.get("vector_dim", 0) or 0)
        self._initialized: bool = False

    # ── 懒初始化 ──────────────────────────────

    def _ensure_initialized(self) -> bool:
        """首次使用时连接 Qdrant + 探测维度 + 建 collection。失败返回 False。"""
        if self._initialized:
            return True
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qm
            from AIRAGAgent.kb.embedding import get_kb_embeddings, probe_embeddings

            url = str(memory_conf.get("qdrant_url", "http://127.0.0.1:6333"))
            self._client = QdrantClient(url=url, timeout=10)
            self._embeddings = get_kb_embeddings()

            # 探测向量维度
            if self._dim <= 0:
                probe = probe_embeddings(self._embeddings)
                if not probe.get("ok"):
                    logger.warning(f"[memory] 嵌入探测失败，记忆功能暂不可用: {probe.get('error', '')}")
                    self._client = None
                    return False
                self._dim = int(probe["dim"])
                logger.info(f"[memory] 嵌入维度探测成功: dim={self._dim}")

            # 距离度量映射
            dist_map = {
                "Cosine": qm.Distance.COSINE,
                "Dot": qm.Distance.DOT,
                "Euclid": qm.Distance.EUCLID,
            }
            distance = dist_map.get(self._distance, qm.Distance.COSINE)

            # collection 不存在则创建
            collections = self._client.get_collections().collections
            names = {c.name for c in collections}
            if self._collection not in names:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=qm.VectorParams(size=self._dim, distance=distance),
                )
                logger.info(f"[memory] Qdrant collection '{self._collection}' 已创建 (dim={self._dim}, distance={self._distance})")

            self._initialized = True
            return True
        except Exception as e:
            logger.warning(f"[memory] Qdrant 初始化失败（记忆功能暂不可用）: {e}")
            self._client = None
            return False

    # ── 写入 ──────────────────────────────

    def add_memory(self, user_id: int, memory_type: str, content: str,
                   source: str = "auto", confidence: float = 1.0) -> Optional[str]:
        """写入一条记忆。返回 point_id，失败返回 None。"""
        if not self._ensure_initialized():
            return None
        try:
            from qdrant_client.http import models as qm
            vec = self._embeddings.embed_query(content)
            point_id = uuid.uuid4().hex
            now = datetime.utcnow().isoformat()
            self._client.upsert(
                collection_name=self._collection,
                points=[qm.PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={
                        "user_id": int(user_id),
                        "memory_type": str(memory_type)[:30],
                        "content": str(content)[:65000],
                        "source": str(source)[:100],
                        "confidence": float(confidence),
                        "created_at": now,
                        "updated_at": now,
                    },
                )],
            )
            logger.info(f"[memory] 写入 user={user_id} type={memory_type} content={content[:40]}")
            return point_id
        except Exception as e:
            logger.warning(f"[memory] 写入失败 user={user_id}: {e}")
            return None

    # ── 召回 ──────────────────────────────

    def search_memories(self, user_id: int, query: str, top_k: int = 5,
                        score_threshold: float = 0.0) -> List[Dict]:
        """按 query 向量召回用户相关记忆。返回按相似度降序的列表。

        返回字段：id, memory_type, content, source, confidence, score, updated_at
        """
        if not self._ensure_initialized():
            return []
        try:
            vec = self._embeddings.embed_query(query)
            from qdrant_client.http import models as qm
            resp = self._client.query_points(
                collection_name=self._collection,
                query=vec,
                query_filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="user_id",
                            match=qm.MatchValue(value=int(user_id)),
                        )
                    ]
                ),
                limit=int(top_k),
                score_threshold=float(score_threshold) if score_threshold > 0 else None,
                with_payload=True,
            )
            out = []
            for r in resp.points:
                p = r.payload or {}
                out.append({
                    "id": r.id,
                    "memory_type": p.get("memory_type", "fact"),
                    "content": p.get("content", ""),
                    "source": p.get("source", ""),
                    "confidence": p.get("confidence", 1.0),
                    "score": float(r.score),
                    "updated_at": p.get("updated_at", ""),
                })
            return out
        except Exception as e:
            logger.warning(f"[memory] 召回失败 user={user_id}: {e}")
            return []

    # ── 删除 ──────────────────────────────

    def delete_memory(self, user_id: int, point_id: str) -> bool:
        """按 point_id 删除单条记忆。point_id 是随机 uuid，用户无法构造他人 id。"""
        if not self._ensure_initialized():
            return False
        try:
            self._client.delete(
                collection_name=self._collection,
                points_selector=[point_id],
            )
            return True
        except Exception as e:
            logger.warning(f"[memory] 删除失败 user={user_id} id={point_id}: {e}")
            return False

    def delete_all_user_memories(self, user_id: int) -> int:
        """删除某用户全部记忆（按 user_id 过滤）。返回删除条数（近似）。"""
        if not self._ensure_initialized():
            return 0
        try:
            from qdrant_client.http import models as qm
            self._client.delete(
                collection_name=self._collection,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        must=[qm.FieldCondition(key="user_id", match=qm.MatchValue(value=int(user_id)))]
                    )
                ),
            )
            logger.info(f"[memory] 已清空用户 {user_id} 的全部记忆")
            return 1
        except Exception as e:
            logger.warning(f"[memory] 清空用户记忆失败 user={user_id}: {e}")
            return 0

    # ── 诊断 ──────────────────────────────

    def status(self) -> dict:
        """诊断用：返回 Qdrant 连接 + collection 状态。"""
        if not self._ensure_initialized():
            return {"ok": False, "error": "Qdrant 未初始化"}
        try:
            info = self._client.get_collection(self._collection)
            return {
                "ok": True,
                "collection": self._collection,
                "dim": self._dim,
                "distance": self._distance,
                "points_count": getattr(info, "points_count", 0) or 0,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}


# 模块级单例
memory_store = MemoryVectorStore()
