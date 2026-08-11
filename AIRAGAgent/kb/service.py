"""知识库服务层：向量索引、检索、分块预览、索引重建、默认库播种。

设计要点：
- 独立 Chroma 集合 ``kb_store``，与旧版 ``agent`` 集合物理共存于同一持久化目录，
  通过 chunk 元数据 kb_id / doc_id 实现多知识库隔离；
- Chroma / 嵌入模型等重依赖**懒加载**（首次使用时才初始化），
  保证各微服务 import 本模块零负担；
- 文档索引入库走后台线程，状态机：pending → processing → ready / failed；
- 任何索引内容变更后调用 invalidate_rag_cache()，避免检索缓存脏读。
"""
import os
import threading
from pathlib import Path
from typing import Optional

from langchain_core.documents import Document

from AIRAGAgent.kb import models as kb_models
from AIRAGAgent.utils.config_handler import chroma_conf
from AIRAGAgent.utils.logger_handler import logger
from AIRAGAgent.utils.path_tool import get_abs_path
from AIRAGAgent.utils.paths import PROJECT_ROOT

KB_COLLECTION_NAME = "kb_store"

# 文档状态
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

_vector_store = None
_store_lock = threading.Lock()
_init_lock = threading.Lock()


def _get_persist_dir() -> str:
    """解析 Chroma 持久化目录为绝对路径（与 CWD 无关）。"""
    raw = str(chroma_conf.get("persist_directory", "chroma_ab"))
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / raw
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _get_vector_store():
    """懒加载 Chroma 向量库（首次调用时才初始化嵌入模型）。

    初始化时探测嵌入维度并与集合元数据比对：
    若嵌入提供者/维度发生变更，自动清空 kb_store 并后台重建全部知识库（自愈合）。
    """
    global _vector_store
    if _vector_store is not None:
        return _vector_store
    with _init_lock:
        if _vector_store is not None:
            return _vector_store
        from langchain_chroma import Chroma
        from AIRAGAgent.kb.embedding import get_kb_embeddings, get_embedding_provider, probe_embeddings

        embeddings = get_kb_embeddings()
        store = Chroma(
            collection_name=KB_COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=_get_persist_dir(),
        )
        logger.info(f"[KB] 向量库已初始化 collection={KB_COLLECTION_NAME} dir={_get_persist_dir()}")

        # 嵌入提供者/维度变更检测与自愈合
        try:
            probe = probe_embeddings(embeddings)
            provider = get_embedding_provider()
            meta = dict(store._collection.metadata or {})
            old_sig = f"{meta.get('kb_embed_provider')}:{meta.get('kb_embed_dim')}"
            new_sig = f"{provider}:{probe['dim']}"
            if not probe["ok"]:
                logger.error(f"[KB] 嵌入模型探测失败: {probe['error']}")
            elif meta.get("kb_embed_dim") and old_sig != new_sig:
                logger.warning(
                    f"[KB] 嵌入配置已变更（{old_sig} → {new_sig}），"
                    f"清空 kb_store 并触发全量重建"
                )
                _wipe_collection(store)
                store._collection.modify(metadata={"kb_embed_provider": provider, "kb_embed_dim": probe["dim"]})
                threading.Thread(target=_rebuild_all_kbs, daemon=True, name="kb-rebuild-all").start()
            elif not meta.get("kb_embed_dim"):
                store._collection.modify(metadata={"kb_embed_provider": provider, "kb_embed_dim": probe["dim"]})
        except Exception as e:
            logger.warning(f"[KB] 嵌入维度检测异常（不影响使用）: {e}")

        _vector_store = store
        return _vector_store


def _wipe_collection(store) -> None:
    """清空 kb_store 集合的全部向量"""
    data = store._collection.get(include=[])
    ids = data.get("ids") or []
    if ids:
        store._collection.delete(ids=ids)
        logger.info(f"[KB] 已清空 kb_store（{len(ids)} 条向量）")


def _rebuild_all_kbs() -> None:
    """后台重建所有知识库（嵌入维度变更后的自愈合）"""
    try:
        for kb in kb_models.list_kbs():
            if kb["doc_count"] > 0:
                rebuild_kb(kb["id"])
    except Exception as e:
        logger.error(f"[KB] 全量重建异常: {e}", exc_info=True)


def _get_splitter():
    """按 chroma.yml 分块配置创建递归字符文本分割器并返回。"""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(
        chunk_size=chroma_conf["chunk_size"],
        chunk_overlap=chroma_conf["chunk_overlap"],
        separators=chroma_conf["separators"],
        length_function=len,
    )


def allowed_file_types() -> tuple:
    """返回知识库允许上传的文件扩展名元组（来自配置）。"""
    return tuple(chroma_conf.get("allow_knowledge_file_type", ["pdf", "txt", "xls", "xlsx"]))


def _load_file_documents(abs_path: str) -> list[Document]:
    """按扩展名加载文件为 Document 列表"""
    from AIRAGAgent.utils.file_handler import pdf_loader, txt_loader, excel_loader
    lower = abs_path.lower()
    if lower.endswith(".txt"):
        return txt_loader(abs_path)
    if lower.endswith(".pdf"):
        return pdf_loader(abs_path)
    if lower.endswith((".xls", ".xlsx")):
        return excel_loader(abs_path)
    return []


def _invalidate_cache():
    """清除 RAG 缓存（知识库变更后调用，保证检索结果不过期）。"""
    try:
        from AIRAGAgent.infrastructure.rag_cache import invalidate_rag_cache
        invalidate_rag_cache()
    except Exception as e:
        logger.warning(f"[KB] 清除 RAG 缓存失败: {e}")


# ==================== 索引 ====================

def index_document(doc_id: int) -> bool:
    """索引单个文档：加载文件 → 分块 → 写入向量库 → 更新状态。同步执行。"""
    doc = kb_models.get_document(doc_id)
    if not doc:
        logger.warning(f"[KB] 索引失败：文档 {doc_id} 不存在")
        return False

    kb_models.update_document_status(doc_id, STATUS_PROCESSING)
    try:
        abs_path = doc["stored_path"]
        if not os.path.isabs(abs_path):
            abs_path = os.path.join(str(PROJECT_ROOT), abs_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"文件不存在: {abs_path}")

        raw_docs = _load_file_documents(abs_path)
        if not raw_docs:
            raise ValueError("文件没有可提取的文本内容")

        chunks = _get_splitter().split_documents(raw_docs)
        if not chunks:
            raise ValueError("分块后没有有效文本")

        # 注入隔离与溯源元数据
        for i, chunk in enumerate(chunks):
            chunk.metadata = {
                **(chunk.metadata or {}),
                "kb_id": doc["kb_id"],
                "doc_id": doc["id"],
                "filename": doc["filename"],
                "version": doc["version"],
                "chunk_index": i,
            }

        store = _get_vector_store()
        with _store_lock:
            # 先清掉该文档的旧向量（替换/重建场景），再写入新向量
            store.delete(where={"doc_id": doc["id"]})
            store.add_documents(chunks)

        kb_models.update_document_status(doc_id, STATUS_READY, chunk_count=len(chunks))
        logger.info(f"[KB] 文档索引完成 doc_id={doc_id} chunks={len(chunks)}")
        _invalidate_cache()
        return True
    except Exception as e:
        logger.error(f"[KB] 文档索引失败 doc_id={doc_id}: {e}", exc_info=True)
        kb_models.update_document_status(doc_id, STATUS_FAILED, chunk_count=0, error_msg=str(e))
        return False


def index_document_async(doc_id: int) -> None:
    """后台线程索引（上传/替换后立即返回，前端轮询状态）"""
    t = threading.Thread(target=index_document, args=(doc_id,), daemon=True,
                         name=f"kb-index-{doc_id}")
    t.start()


def delete_document_vectors(doc_id: int) -> None:
    """仅从向量库删除指定文档的全部分块"""
    try:
        store = _get_vector_store()
        with _store_lock:
            store.delete(where={"doc_id": doc_id})
        _invalidate_cache()
    except Exception as e:
        logger.warning(f"[KB] 删除文档向量失败 doc_id={doc_id}: {e}")


def delete_kb_vectors(kb_id: int) -> None:
    """删除整个知识库的向量"""
    try:
        store = _get_vector_store()
        with _store_lock:
            store.delete(where={"kb_id": kb_id})
        _invalidate_cache()
    except Exception as e:
        logger.warning(f"[KB] 删除知识库向量失败 kb_id={kb_id}: {e}")


def rebuild_kb(kb_id: int) -> int:
    """重建整个知识库索引：清空向量后重索引全部文档。返回成功文档数。"""
    logger.info(f"[KB] 开始重建知识库 kb_id={kb_id}")
    delete_kb_vectors(kb_id)
    docs = kb_models.list_documents(kb_id)
    ok = 0
    for doc in docs:
        if index_document(doc["id"]):
            ok += 1
    logger.info(f"[KB] 知识库重建完成 kb_id={kb_id} 成功 {ok}/{len(docs)}")
    return ok


def rebuild_kb_async(kb_id: int) -> None:
    """在后台线程中重建指定知识库索引，调用后立即返回。"""
    t = threading.Thread(target=rebuild_kb, args=(kb_id,), daemon=True,
                         name=f"kb-rebuild-{kb_id}")
    t.start()


# ==================== 检索 ====================

def search(query: str, kb_ids: list[int], top_k: Optional[int] = None) -> list[Document]:
    """在指定知识库集合内检索（无分数）"""
    return [doc for doc, _ in search_with_scores(query, kb_ids, top_k)]


def search_with_scores(query: str, kb_ids: list[int], top_k: Optional[int] = None) -> list[tuple[Document, float]]:
    """在指定知识库集合内检索，返回 (Document, relevance_score) 列表。

    relevance_score 为 0~1 的相似度（越高越相关），由 langchain_chroma 归一化。
    """
    if not query or not kb_ids:
        return []
    k = int(top_k or chroma_conf.get("k", 3))
    store = _get_vector_store()
    where = {"kb_id": kb_ids[0]} if len(kb_ids) == 1 else {"kb_id": {"$in": list(kb_ids)}}
    try:
        results = store.similarity_search_with_relevance_scores(query, k=k, filter=where)
    except Exception as e:
        logger.error(f"[KB] 检索失败: {e}", exc_info=True)
        return []
    # 归一化分数到 [0,1]，防止极端距离值出现负数
    return [(doc, max(0.0, min(1.0, float(score)))) for doc, score in results]


def preview_chunks(doc_id: int, offset: int = 0, limit: int = 20) -> dict:
    """分块预览：按 chunk_index 排序后分页返回"""
    store = _get_vector_store()
    try:
        data = store.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
    except Exception as e:
        logger.error(f"[KB] 分块预览失败 doc_id={doc_id}: {e}", exc_info=True)
        return {"total": 0, "chunks": []}

    docs = data.get("documents") or []
    metas = data.get("metadatas") or []
    pairs = []
    for content, meta in zip(docs, metas):
        meta = meta or {}
        pairs.append({
            "chunk_index": int(meta.get("chunk_index", 0)),
            "content": content,
            "char_count": len(content or ""),
            "version": meta.get("version", 1),
        })
    pairs.sort(key=lambda x: x["chunk_index"])
    total = len(pairs)
    return {"total": total, "chunks": pairs[offset:offset + limit]}


def kb_stats(kb_id: int) -> dict:
    """知识库向量统计（实际向量数）"""
    store = _get_vector_store()
    try:
        data = store.get(where={"kb_id": kb_id}, include=[])
        ids = data.get("ids") or []
        return {"vector_count": len(ids)}
    except Exception:
        return {"vector_count": 0}


# ==================== 默认库播种 ====================

def seed_default_kb() -> None:
    """确保默认全局知识库存在，并把 data/ 目录的知识文件登记入库（MD5 去重）。

    幂等：已登记（同 MD5）的文件跳过；新文件同步索引。
    替代旧版 VectorStoreService.load_document + md5.txt 的职责。
    """
    try:
        kb = kb_models.get_default_kb()
        if kb is None:
            kb = kb_models.create_kb(
                name="默认知识库", scope="global", owner_user_id=None,
                biz_line="通用", description="系统默认知识库（data 目录文件自动导入）",
                created_by=None, created_by_name="system", is_default=True,
            )
            logger.info(f"[KB] 默认知识库已创建 id={kb['id']}")

        kb_id = kb["id"]
        data_dir = get_abs_path(chroma_conf["data_path"])
        if not os.path.isdir(data_dir):
            logger.warning(f"[KB] 数据目录不存在，跳过播种: {data_dir}")
            return

        from AIRAGAgent.utils.file_handler import get_file_md5_hex
        allow = allowed_file_types()
        for fname in sorted(os.listdir(data_dir)):
            fpath = os.path.join(data_dir, fname)
            if not os.path.isfile(fpath) or not fname.lower().endswith(allow):
                continue
            md5 = get_file_md5_hex(fpath)
            if not md5:
                continue
            existing = kb_models.find_document_by_md5(kb_id, md5)
            if existing:
                continue
            doc = kb_models.create_document(
                kb_id=kb_id, filename=fname, stored_path=fpath,
                file_ext=os.path.splitext(fname)[1].lstrip(".").lower(),
                file_size=os.path.getsize(fpath), file_md5=md5,
                source="system", uploader_id=None, uploader_name="system",
            )
            logger.info(f"[KB] 默认库收录文件: {fname} (doc_id={doc['id']})")
            index_document(doc["id"])
    except Exception as e:
        # 播种失败不阻断服务启动
        logger.error(f"[KB] 默认知识库播种失败: {e}", exc_info=True)
