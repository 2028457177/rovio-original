"""知识库数据模型层：knowledge_bases / kb_documents 表的 CRUD。

遵循 AIRAGAgent.database.models 的 get_db 模式，所有函数同步阻塞，
由 FastAPI 路由层通过 run_in_executor 调用。
"""
from typing import Optional

from AIRAGAgent.database.connection import get_db


# ==================== 知识库 ====================

def _row_to_kb(row: dict) -> dict:
    """把数据库行记录转换成知识库字典（含文档数/分块数统计字段）。"""
    return {
        "id": row["id"],
        "name": row["name"],
        "scope": row["scope"],
        "owner_user_id": row.get("owner_user_id"),
        "biz_line": row.get("biz_line") or "",
        "description": row.get("description") or "",
        "is_enabled": bool(row.get("is_enabled", 1)),
        "is_default": bool(row.get("is_default", 0)),
        "created_by": row.get("created_by"),
        "created_by_name": row.get("created_by_name") or "",
        "doc_count": int(row.get("doc_count", 0) or 0),
        "chunk_count": int(row.get("chunk_count", 0) or 0),
        "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "",
        "updated_at": row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("updated_at") else "",
    }


_KB_SELECT = """
    SELECT k.*,
           (SELECT COUNT(*) FROM kb_documents d WHERE d.kb_id = k.id) AS doc_count,
           (SELECT COALESCE(SUM(d.chunk_count), 0) FROM kb_documents d WHERE d.kb_id = k.id) AS chunk_count
    FROM knowledge_bases k
"""


def create_kb(name: str, scope: str, owner_user_id: Optional[int], biz_line: str = "",
              description: str = "", created_by: Optional[int] = None,
              created_by_name: str = "", is_default: bool = False) -> dict:
    """创建知识库记录并返回新知识库的完整信息字典。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO knowledge_bases (name, scope, owner_user_id, biz_line, description,
                                         created_by, created_by_name, is_default)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (name[:100], scope, owner_user_id, (biz_line or "")[:100], (description or "")[:500],
             created_by, (created_by_name or "")[:100], 1 if is_default else 0)
        )
        conn.commit()
        return get_kb(cursor.lastrowid)


def get_kb(kb_id: int) -> Optional[dict]:
    """按 ID 查询单个知识库，不存在时返回 None。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(_KB_SELECT + " WHERE k.id = %s", (kb_id,))
        row = cursor.fetchone()
        return _row_to_kb(row) if row else None


def list_kbs(scope: Optional[str] = None, owner_user_id: Optional[int] = None) -> list:
    """按条件列出知识库。scope=None 不过滤；owner_user_id 仅在 scope='personal' 时生效。"""
    sql = _KB_SELECT
    params: list = []
    conds = []
    if scope:
        conds.append("k.scope = %s")
        params.append(scope)
    if scope == "personal" and owner_user_id is not None:
        conds.append("k.owner_user_id = %s")
        params.append(owner_user_id)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY k.is_default DESC, k.id ASC"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        return [_row_to_kb(r) for r in cursor.fetchall()]


def list_accessible_kb_ids(user_id: Optional[int]) -> list[int]:
    """检索用：全局启用库 + 指定用户的个人启用库。user_id=None 时仅全局库。"""
    with get_db() as conn:
        cursor = conn.cursor()
        if user_id is None:
            cursor.execute(
                "SELECT id FROM knowledge_bases WHERE is_enabled = 1 AND scope = 'global' ORDER BY id"
            )
        else:
            cursor.execute(
                """
                SELECT id FROM knowledge_bases
                WHERE is_enabled = 1 AND (scope = 'global' OR (scope = 'personal' AND owner_user_id = %s))
                ORDER BY id
                """,
                (user_id,)
            )
        return [r["id"] for r in cursor.fetchall()]


def update_kb(kb_id: int, fields: dict) -> bool:
    """更新知识库信息：name / biz_line / description / is_enabled"""
    sets, params = [], []
    if "name" in fields and fields["name"] is not None:
        sets.append("name = %s")
        params.append(str(fields["name"])[:100])
    if "biz_line" in fields and fields["biz_line"] is not None:
        sets.append("biz_line = %s")
        params.append(str(fields["biz_line"])[:100])
    if "description" in fields and fields["description"] is not None:
        sets.append("description = %s")
        params.append(str(fields["description"])[:500])
    if "is_enabled" in fields and fields["is_enabled"] is not None:
        sets.append("is_enabled = %s")
        params.append(1 if fields["is_enabled"] else 0)
    if not sets:
        return False
    params.append(kb_id)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id = %s",
            tuple(params)
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_kb(kb_id: int) -> Optional[dict]:
    """删除知识库及其全部文档记录。返回被删 KB 信息（含文档列表）供调用方清理向量与文件；
    默认库不可删除时返回 'default' 标记字典，不存在返回 None。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM knowledge_bases WHERE id = %s", (kb_id,))
        kb = cursor.fetchone()
        if not kb:
            return None
        if kb.get("is_default"):
            return {"is_default_protected": True}
        cursor.execute("SELECT * FROM kb_documents WHERE kb_id = %s", (kb_id,))
        docs = cursor.fetchall()
        cursor.execute("DELETE FROM kb_documents WHERE kb_id = %s", (kb_id,))
        cursor.execute("DELETE FROM knowledge_bases WHERE id = %s", (kb_id,))
        conn.commit()
        return {"kb": _row_to_kb(kb), "documents": [_row_to_doc(d) for d in docs]}


def user_owns_kb(user_id: int, kb_id: int) -> bool:
    """校验个人库归属"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM knowledge_bases WHERE id = %s AND scope = 'personal' AND owner_user_id = %s",
            (kb_id, user_id)
        )
        return cursor.fetchone() is not None


def get_default_kb() -> Optional[dict]:
    """查询系统默认知识库，不存在返回 None。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(_KB_SELECT + " WHERE k.is_default = 1 LIMIT 1")
        row = cursor.fetchone()
        return _row_to_kb(row) if row else None


# ==================== 知识库文档 ====================

def _row_to_doc(row: dict) -> dict:
    """把文档数据库行记录转换成文档信息字典（含格式化时间字段）。"""
    return {
        "id": row["id"],
        "kb_id": row["kb_id"],
        "filename": row["filename"],
        "stored_path": row.get("stored_path") or "",
        "file_ext": row.get("file_ext") or "",
        "file_size": int(row.get("file_size", 0) or 0),
        "file_md5": row.get("file_md5") or "",
        "version": int(row.get("version", 1) or 1),
        "source": row.get("source") or "upload",
        "uploader_id": row.get("uploader_id"),
        "uploader_name": row.get("uploader_name") or "",
        "status": row.get("status") or "pending",
        "chunk_count": int(row.get("chunk_count", 0) or 0),
        "error_msg": row.get("error_msg") or "",
        "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("created_at") else "",
        "updated_at": row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("updated_at") else "",
    }


def create_document(kb_id: int, filename: str, stored_path: str, file_ext: str,
                    file_size: int, file_md5: str, source: str = "upload",
                    uploader_id: Optional[int] = None, uploader_name: str = "",
                    status: str = "pending") -> dict:
    """登记一条知识库文档记录并返回新文档的完整信息字典。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO kb_documents (kb_id, filename, stored_path, file_ext, file_size,
                                      file_md5, source, uploader_id, uploader_name, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (kb_id, filename[:255], stored_path[:500], file_ext[:20], file_size,
             file_md5[:64], source[:50], uploader_id, (uploader_name or "")[:100], status[:20])
        )
        conn.commit()
        return get_document(cursor.lastrowid)


def get_document(doc_id: int) -> Optional[dict]:
    """按文档ID查询文档信息，不存在返回 None。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kb_documents WHERE id = %s", (doc_id,))
        row = cursor.fetchone()
        return _row_to_doc(row) if row else None


def list_documents(kb_id: int) -> list:
    """列出指定知识库下的全部文档记录（按 ID 升序）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM kb_documents WHERE kb_id = %s ORDER BY id ASC", (kb_id,)
        )
        return [_row_to_doc(r) for r in cursor.fetchall()]


def find_document_by_md5(kb_id: int, file_md5: str) -> Optional[dict]:
    """同库内按内容 MD5 查重"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM kb_documents WHERE kb_id = %s AND file_md5 = %s LIMIT 1",
            (kb_id, file_md5)
        )
        row = cursor.fetchone()
        return _row_to_doc(row) if row else None


def update_document_status(doc_id: int, status: str, chunk_count: Optional[int] = None,
                           error_msg: str = "") -> None:
    """更新文档的索引状态，可选同时更新分块数与错误信息。"""
    with get_db() as conn:
        cursor = conn.cursor()
        if chunk_count is not None:
            cursor.execute(
                "UPDATE kb_documents SET status = %s, chunk_count = %s, error_msg = %s WHERE id = %s",
                (status[:20], chunk_count, (error_msg or "")[:1000], doc_id)
            )
        else:
            cursor.execute(
                "UPDATE kb_documents SET status = %s, error_msg = %s WHERE id = %s",
                (status[:20], (error_msg or "")[:1000], doc_id)
            )
        conn.commit()


def update_document_file(doc_id: int, filename: str, stored_path: str, file_ext: str,
                         file_size: int, file_md5: str, uploader_id: Optional[int],
                         uploader_name: str) -> None:
    """替换文档文件：更新文件信息并递增版本号，状态重置为 pending"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE kb_documents
            SET filename = %s, stored_path = %s, file_ext = %s, file_size = %s,
                file_md5 = %s, version = version + 1, uploader_id = %s, uploader_name = %s,
                status = 'pending', chunk_count = 0, error_msg = ''
            WHERE id = %s
            """,
            (filename[:255], stored_path[:500], file_ext[:20], file_size, file_md5[:64],
             uploader_id, (uploader_name or "")[:100], doc_id)
        )
        conn.commit()


def delete_document(doc_id: int) -> Optional[dict]:
    """删除文档记录，返回被删记录供调用方清理向量与文件"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kb_documents WHERE id = %s", (doc_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute("DELETE FROM kb_documents WHERE id = %s", (doc_id,))
        conn.commit()
        return _row_to_doc(row)
