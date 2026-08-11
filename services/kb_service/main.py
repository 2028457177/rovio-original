"""kb_service FastAPI 入口。

核心思路：复用 AIRAGAgent.kb 模块的业务逻辑，但把数据库重定向到 kb_service 的
独立库 lc_kb。AIRAGAgent.kb.models 通过 AIRAGAgent.database.connection.get_db()
访问数据库，get_db() 在调用时读取 mysql_conf["database"]，故在 import 前原地修改
该字典即可生效，无需改动 AIRAGAgent 源码。

路由：
- 管理端 /api/admin/kb/...  全局知识库（需管理员权限）
- 用户端  /api/kb/...        个人知识库（需登录）
- 内部    /internal/kb/search  供 chat_service 的 RAG 检索调用
"""
from __future__ import annotations
import asyncio
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import create_app, get_current_user, get_admin_user
from core.config import DB_NAME

# 数据库重定向：复用 AIRAGAgent.kb 业务逻辑，但把 DB 指向 kb_service 独立库
# AIRAGAgent.kb.models -> AIRAGAgent.database.connection.get_db() -> _get_db_config()
# 在调用时读取 mysql_conf["database"]，此处 in-place 修改即可生效
import AIRAGAgent.database.connection as _conn
_conn.mysql_conf["database"] = DB_NAME  # 默认 lc_kb，支持 KB_DB 环境变量覆盖

from AIRAGAgent.kb import models as kb_models
from AIRAGAgent.kb import service as kb_service
from AIRAGAgent.utils.logger_handler import logger
from AIRAGAgent.utils.paths import UPLOAD_DIR, PROJECT_ROOT


async def _on_startup():
    """启动时播种默认知识库（在 executor 中跑，避免阻塞事件循环）"""
    loop = asyncio.get_event_loop()

    def _seed():
        """在后台线程中执行默认知识库数据播种。"""
        from AIRAGAgent.kb.service import seed_default_kb
        seed_default_kb()

    await loop.run_in_executor(None, _seed)


app = create_app("kb_service", version="1.0.0", on_startup=_on_startup)

router = APIRouter()

MAX_FILE_SIZE = 20 * 1024 * 1024  # 单文件 20MB


# ==================== 公共工具 ====================

def _err(status: int, msg: str) -> JSONResponse:
    """构造统一的 JSON 错误响应体。"""
    return JSONResponse(status_code=status, content={"error": msg})


def _safe_ext(filename: str) -> str:
    """提取文件名后缀并转小写（去掉前导点），无后缀返回空字符串。"""
    return os.path.splitext(filename or "")[1].lstrip(".").lower()


def _kb_file_rel_path(kb_id: int, md5: str, ext: str) -> str:
    """拼接知识库文件在 uploads 目录下的相对存储路径。"""
    return f"uploads/kb/{kb_id}/{md5}.{ext}"


def _abs_from_rel(rel_path: str) -> str:
    """将相对路径转换为基于项目根目录的绝对路径。"""
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(str(PROJECT_ROOT), rel_path)


def _delete_physical_file(stored_path: str) -> None:
    """删除 uploads/kb 下的物理文件（仅允许该目录内，防误删）"""
    try:
        if not stored_path:
            return
        abs_path = _abs_from_rel(stored_path)
        kb_root = str(UPLOAD_DIR / "kb")
        if os.path.commonpath([os.path.abspath(abs_path), os.path.abspath(kb_root)]) != os.path.abspath(kb_root):
            return  # 非 uploads/kb 目录文件（如 data/ 系统文件）不删
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except Exception as e:
        logger.warning(f"[KB] 删除物理文件失败 {stored_path}: {e}")


async def _read_and_validate(file: UploadFile):
    """读取上传文件并校验类型/大小，返回 (content, ext, error_msg)。error_msg 为 None 表示通过。"""
    ext = _safe_ext(file.filename)
    if ext not in kb_service.allowed_file_types():
        return None, ext, f"文件「{file.filename}」类型不支持，仅允许：{'/'.join(kb_service.allowed_file_types())}"
    content = await file.read()
    if not content:
        return None, ext, f"文件「{file.filename}」内容为空"
    if len(content) > MAX_FILE_SIZE:
        return None, ext, f"文件「{file.filename}」超过 20MB 限制"
    return content, ext, None


def _save_upload(kb_id: int, content: bytes, ext: str):
    """保存文件到 uploads/kb/{kb_id}/{md5}.{ext}，返回 (rel_path, md5)"""
    import hashlib
    md5 = hashlib.md5(content).hexdigest()
    rel_path = _kb_file_rel_path(kb_id, md5, ext)
    abs_path = _abs_from_rel(rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    if not os.path.isfile(abs_path):
        with open(abs_path, "wb") as f:
            f.write(content)
    return rel_path, md5


def _do_upload(kb_id: int, file: UploadFile, content: bytes, ext: str,
               uploader_id: int, uploader_name: str) -> dict:
    """单文件上传入库：去重 → 存盘 → 建档 → 异步索引"""
    rel_path, md5 = _save_upload(kb_id, content, ext)
    dup = kb_models.find_document_by_md5(kb_id, md5)
    if dup:
        return {"filename": file.filename, "ok": False,
                "error": f"与现有文档「{dup['filename']}」内容重复，已跳过"}
    doc = kb_models.create_document(
        kb_id=kb_id, filename=file.filename or f"unnamed.{ext}",
        stored_path=rel_path, file_ext=ext, file_size=len(content),
        file_md5=md5, source="upload",
        uploader_id=uploader_id, uploader_name=uploader_name,
    )
    kb_service.index_document_async(doc["id"])
    return {"filename": file.filename, "ok": True, "document": doc}


def _do_replace(kb_id: int, doc_id: int, file: UploadFile, content: bytes, ext: str,
                uploader_id: int, uploader_name: str):
    """替换文档文件：版本+1 → 异步重索引，返回 error_response 或 None"""
    doc = kb_models.get_document(doc_id)
    if not doc or doc["kb_id"] != kb_id:
        return _err(404, "文档不存在")
    rel_path, md5 = _save_upload(kb_id, content, ext)
    if md5 == doc["file_md5"]:
        return _err(400, "新文件与当前版本内容完全相同，无需替换")
    old_path = doc["stored_path"]
    kb_models.update_document_file(
        doc_id, file.filename or doc["filename"], rel_path, ext,
        len(content), md5, uploader_id, uploader_name,
    )
    if old_path != rel_path:
        _delete_physical_file(old_path)
    kb_service.index_document_async(doc_id)
    return None


def _do_delete_doc(kb_id: int, doc_id: int) -> bool:
    """删除知识库文档：先清向量、再删记录与物理文件，成功返回 True。"""
    doc = kb_models.get_document(doc_id)
    if not doc or doc["kb_id"] != kb_id:
        return False
    kb_service.delete_document_vectors(doc_id)
    kb_models.delete_document(doc_id)
    _delete_physical_file(doc["stored_path"])
    return True


def _get_kb_or_404(kb_id: int, scope: str = "global"):
    """按ID查询指定作用域的知识库，不存在或作用域不符返回 None。"""
    kb = kb_models.get_kb(kb_id)
    if not kb or kb["scope"] != scope:
        return None
    return kb


def _search_test(query: str, kb_ids: Optional[List[int]], top_k: int,
                 allowed_ids: list[int]) -> JSONResponse:
    """检索测试 playground 公共逻辑：allowed_ids 为调用方可用的库集合"""
    query = (query or "").strip()
    if not query:
        return _err(400, "请输入测试问题")
    if kb_ids:
        ids = [i for i in kb_ids if i in set(allowed_ids)]
        if not ids:
            return _err(403, "所选知识库不可用")
    else:
        ids = allowed_ids
    if not ids:
        return JSONResponse(content={"query": query, "results": [], "kb_ids": []})

    top_k = max(1, min(int(top_k or 3), 20))
    scored = kb_service.search_with_scores(query, ids, top_k=top_k)

    # 补充库名/文档名
    kb_name_map = {k["id"]: k["name"] for k in kb_models.list_kbs()}
    results = []
    for rank, (doc, score) in enumerate(scored, 1):
        meta = doc.metadata or {}
        results.append({
            "rank": rank,
            "score": round(float(score), 4),
            "content": doc.page_content,
            "char_count": len(doc.page_content or ""),
            "kb_id": meta.get("kb_id"),
            "kb_name": kb_name_map.get(meta.get("kb_id"), ""),
            "doc_id": meta.get("doc_id"),
            "filename": meta.get("filename", ""),
            "chunk_index": meta.get("chunk_index"),
        })
    return JSONResponse(content={"query": query, "results": results, "kb_ids": ids})


# ==================== 请求体 ====================

class KbCreateRequest(BaseModel):
    name: str
    biz_line: str = ""
    description: str = ""


class KbUpdateRequest(BaseModel):
    name: Optional[str] = None
    biz_line: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None


class BatchDeleteRequest(BaseModel):
    doc_ids: List[int]


class SearchTestRequest(BaseModel):
    query: str
    kb_ids: Optional[List[int]] = None
    top_k: Optional[int] = None


# ==================== 管理端：全局知识库 ====================

@router.get("/api/admin/kb/list")
async def admin_list_kbs(admin: dict = Depends(get_admin_user)):
    """管理员：列出全部全局知识库"""
    kbs = kb_models.list_kbs(scope="global")
    return JSONResponse(content={"kbs": kbs})


@router.post("/api/admin/kb/create")
async def admin_create_kb(req: KbCreateRequest, admin: dict = Depends(get_admin_user)):
    """管理员：创建全局知识库（按业务线/课程隔离）"""
    name = (req.name or "").strip()
    if not name:
        return _err(400, "知识库名称不能为空")
    kb = kb_models.create_kb(
        name=name, scope="global", owner_user_id=None,
        biz_line=req.biz_line.strip(), description=req.description.strip(),
        created_by=admin["id"], created_by_name=admin.get("username", ""),
    )
    return JSONResponse(content={"status": "ok", "kb": kb})


@router.patch("/api/admin/kb/{kb_id}")
async def admin_update_kb(kb_id: int, req: KbUpdateRequest, admin: dict = Depends(get_admin_user)):
    """管理员：更新知识库信息 / 启用停用"""
    kb = _get_kb_or_404(kb_id, "global")
    if not kb:
        return _err(404, "知识库不存在")
    fields = {k: v for k, v in req.dict().items() if v is not None}
    if not fields:
        return _err(400, "无可更新字段")
    kb_models.update_kb(kb_id, fields)
    if "is_enabled" in fields:
        kb_service._invalidate_cache()
    return JSONResponse(content={"status": "ok", "kb": kb_models.get_kb(kb_id)})


@router.delete("/api/admin/kb/{kb_id}")
async def admin_delete_kb(kb_id: int, admin: dict = Depends(get_admin_user)):
    """管理员：删除知识库（向量 + 文档记录 + 物理文件）"""
    kb_service.delete_kb_vectors(kb_id)
    result = kb_models.delete_kb(kb_id)
    if result is None:
        return _err(404, "知识库不存在")
    if result.get("is_default_protected"):
        return _err(400, "默认知识库不可删除")
    for doc in result["documents"]:
        _delete_physical_file(doc["stored_path"])
    return JSONResponse(content={"status": "ok"})


@router.get("/api/admin/kb/{kb_id}/documents")
async def admin_list_documents(kb_id: int, admin: dict = Depends(get_admin_user)):
    """管理员：列出指定全局知识库下的全部文档。"""
    kb = _get_kb_or_404(kb_id, "global")
    if not kb:
        return _err(404, "知识库不存在")
    docs = kb_models.list_documents(kb_id)
    return JSONResponse(content={"kb": kb, "documents": docs})


@router.post("/api/admin/kb/{kb_id}/documents")
async def admin_upload_documents(kb_id: int, files: List[UploadFile] = File(...),
                                 admin: dict = Depends(get_admin_user)):
    """管理员：批量上传文档（支持拖拽多文件）"""
    kb = _get_kb_or_404(kb_id, "global")
    if not kb:
        return _err(404, "知识库不存在")
    if not files:
        return _err(400, "未接收到文件")
    results = []
    for file in files:
        content, ext, err = await _read_and_validate(file)
        if err is not None:
            results.append({"filename": file.filename, "ok": False, "error": err})
            continue
        results.append(_do_upload(kb_id, file, content, ext, admin["id"], admin.get("username", "")))
    ok_count = sum(1 for r in results if r.get("ok"))
    return JSONResponse(content={"status": "ok", "uploaded": ok_count,
                                 "total": len(files), "results": results})


@router.post("/api/admin/kb/{kb_id}/documents/batch-delete")
async def admin_batch_delete_documents(kb_id: int, req: BatchDeleteRequest,
                                       admin: dict = Depends(get_admin_user)):
    """管理员：批量删除文档"""
    kb = _get_kb_or_404(kb_id, "global")
    if not kb:
        return _err(404, "知识库不存在")
    deleted = 0
    for doc_id in req.doc_ids:
        if _do_delete_doc(kb_id, doc_id):
            deleted += 1
    return JSONResponse(content={"status": "ok", "deleted": deleted})


@router.delete("/api/admin/kb/{kb_id}/documents/{doc_id}")
async def admin_delete_document(kb_id: int, doc_id: int, admin: dict = Depends(get_admin_user)):
    """管理员：删除指定知识库下的单个文档。"""
    if not _do_delete_doc(kb_id, doc_id):
        return _err(404, "文档不存在")
    return JSONResponse(content={"status": "ok"})


@router.post("/api/admin/kb/{kb_id}/documents/{doc_id}/replace")
async def admin_replace_document(kb_id: int, doc_id: int, file: UploadFile = File(...),
                                 admin: dict = Depends(get_admin_user)):
    """管理员：替换文档（版本+1，自动重建该文档索引）"""
    kb = _get_kb_or_404(kb_id, "global")
    if not kb:
        return _err(404, "知识库不存在")
    content, ext, err = await _read_and_validate(file)
    if err is not None:
        return _err(400, err)
    replace_err = _do_replace(kb_id, doc_id, file, content, ext, admin["id"], admin.get("username", ""))
    if replace_err is not None:
        return replace_err
    return JSONResponse(content={"status": "ok", "document": kb_models.get_document(doc_id)})


@router.post("/api/admin/kb/{kb_id}/documents/{doc_id}/reindex")
async def admin_reindex_document(kb_id: int, doc_id: int, admin: dict = Depends(get_admin_user)):
    """管理员：增量更新（重建单个文档索引）"""
    doc = kb_models.get_document(doc_id)
    if not doc or doc["kb_id"] != kb_id:
        return _err(404, "文档不存在")
    kb_service.index_document_async(doc_id)
    return JSONResponse(content={"status": "ok"})


@router.get("/api/admin/kb/{kb_id}/documents/{doc_id}/chunks")
async def admin_preview_chunks(kb_id: int, doc_id: int, offset: int = 0, limit: int = 20,
                               admin: dict = Depends(get_admin_user)):
    """管理员：分块预览"""
    doc = kb_models.get_document(doc_id)
    if not doc or doc["kb_id"] != kb_id:
        return _err(404, "文档不存在")
    limit = max(1, min(limit, 100))
    data = kb_service.preview_chunks(doc_id, offset=offset, limit=limit)
    data["document"] = doc
    return JSONResponse(content=data)


@router.post("/api/admin/kb/{kb_id}/rebuild")
async def admin_rebuild_kb(kb_id: int, admin: dict = Depends(get_admin_user)):
    """管理员：重建整个知识库索引（后台异步执行）"""
    kb = _get_kb_or_404(kb_id, "global")
    if not kb:
        return _err(404, "知识库不存在")
    kb_service.rebuild_kb_async(kb_id)
    return JSONResponse(content={"status": "ok"})


@router.post("/api/admin/kb/search-test")
async def admin_search_test(req: SearchTestRequest, admin: dict = Depends(get_admin_user)):
    """管理员：检索测试 playground（管理员可测全部全局库，含停用库）"""
    all_global = [k["id"] for k in kb_models.list_kbs(scope="global")]
    return _search_test(req.query, req.kb_ids, req.top_k or 3, all_global)


@router.get("/api/admin/kb/embedding-status")
async def admin_embedding_status(admin: dict = Depends(get_admin_user)):
    """管理员：嵌入模型诊断（提供者 / 模型 / 维度 / 可用性 / 耗时）"""
    from AIRAGAgent.kb.embedding import embedding_status
    result = embedding_status()
    return JSONResponse(content=result)


# ==================== 用户端：个人知识库 ====================

@router.get("/api/kb/mine")
async def user_list_mine(user: dict = Depends(get_current_user)):
    """用户：我的个人知识库列表 + 可用的全局库（供检索测试选择）"""
    mine = kb_models.list_kbs(scope="personal", owner_user_id=user["id"])
    global_kbs = [k for k in kb_models.list_kbs(scope="global") if k["is_enabled"]]
    return JSONResponse(content={"kbs": mine, "global_kbs": global_kbs})


@router.post("/api/kb/mine")
async def user_create_kb(req: KbCreateRequest, user: dict = Depends(get_current_user)):
    """用户：创建个人知识库"""
    name = (req.name or "").strip()
    if not name:
        return _err(400, "知识库名称不能为空")
    mine = kb_models.list_kbs(scope="personal", owner_user_id=user["id"])
    if len(mine) >= 20:
        return _err(400, "个人知识库数量已达上限（20 个）")
    kb = kb_models.create_kb(
        name=name, scope="personal", owner_user_id=user["id"],
        biz_line=req.biz_line.strip(), description=req.description.strip(),
        created_by=user["id"], created_by_name=user.get("username", ""),
    )
    return JSONResponse(content={"status": "ok", "kb": kb})


def _user_kb_or_403(user: dict, kb_id: int):
    """校验用户是否为该个人知识库的所有者，通过则返回知识库信息。"""
    if not kb_models.user_owns_kb(user["id"], kb_id):
        return None
    return kb_models.get_kb(kb_id)


@router.patch("/api/kb/mine/{kb_id}")
async def user_update_kb(kb_id: int, req: KbUpdateRequest, user: dict = Depends(get_current_user)):
    """用户：更新个人知识库 / 启用停用（停用后不参与我的 RAG 检索）"""
    if not _user_kb_or_403(user, kb_id):
        return _err(404, "知识库不存在")
    fields = {k: v for k, v in req.dict().items() if v is not None}
    if not fields:
        return _err(400, "无可更新字段")
    kb_models.update_kb(kb_id, fields)
    if "is_enabled" in fields:
        kb_service._invalidate_cache()
    return JSONResponse(content={"status": "ok", "kb": kb_models.get_kb(kb_id)})


@router.delete("/api/kb/mine/{kb_id}")
async def user_delete_kb(kb_id: int, user: dict = Depends(get_current_user)):
    """用户：删除个人知识库"""
    if not _user_kb_or_403(user, kb_id):
        return _err(404, "知识库不存在")
    kb_service.delete_kb_vectors(kb_id)
    result = kb_models.delete_kb(kb_id)
    if result and not result.get("is_default_protected"):
        for doc in result["documents"]:
            _delete_physical_file(doc["stored_path"])
    return JSONResponse(content={"status": "ok"})


@router.get("/api/kb/mine/{kb_id}/documents")
async def user_list_documents(kb_id: int, user: dict = Depends(get_current_user)):
    """用户：列出个人知识库下的全部文档记录。"""
    kb = _user_kb_or_403(user, kb_id)
    if not kb:
        return _err(404, "知识库不存在")
    docs = kb_models.list_documents(kb_id)
    return JSONResponse(content={"kb": kb, "documents": docs})


@router.post("/api/kb/mine/{kb_id}/documents")
async def user_upload_documents(kb_id: int, files: List[UploadFile] = File(...),
                                user: dict = Depends(get_current_user)):
    """用户：批量上传文档到个人知识库"""
    kb = _user_kb_or_403(user, kb_id)
    if not kb:
        return _err(404, "知识库不存在")
    if not files:
        return _err(400, "未接收到文件")
    if len(files) > 20:
        return _err(400, "单次最多上传 20 个文件")
    results = []
    for file in files:
        content, ext, err = await _read_and_validate(file)
        if err is not None:
            results.append({"filename": file.filename, "ok": False, "error": err})
            continue
        results.append(_do_upload(kb_id, file, content, ext, user["id"], user.get("username", "")))
    ok_count = sum(1 for r in results if r.get("ok"))
    return JSONResponse(content={"status": "ok", "uploaded": ok_count,
                        "total": len(files), "results": results})


@router.post("/api/kb/mine/{kb_id}/documents/batch-delete")
async def user_batch_delete_documents(kb_id: int, req: BatchDeleteRequest,
                                      user: dict = Depends(get_current_user)):
    """用户：批量删除个人知识库中的文档。"""
    if not _user_kb_or_403(user, kb_id):
        return _err(404, "知识库不存在")
    deleted = 0
    for doc_id in req.doc_ids:
        if _do_delete_doc(kb_id, doc_id):
            deleted += 1
    return JSONResponse(content={"status": "ok", "deleted": deleted})


@router.delete("/api/kb/mine/{kb_id}/documents/{doc_id}")
async def user_delete_document(kb_id: int, doc_id: int, user: dict = Depends(get_current_user)):
    """用户：删除个人知识库中的单个文档。"""
    if not _user_kb_or_403(user, kb_id):
        return _err(404, "知识库不存在")
    if not _do_delete_doc(kb_id, doc_id):
        return _err(404, "文档不存在")
    return JSONResponse(content={"status": "ok"})


@router.post("/api/kb/mine/{kb_id}/documents/{doc_id}/replace")
async def user_replace_document(kb_id: int, doc_id: int, file: UploadFile = File(...),
                                user: dict = Depends(get_current_user)):
    """用户：替换个人库文档"""
    kb = _user_kb_or_403(user, kb_id)
    if not kb:
        return _err(404, "知识库不存在")
    content, ext, err = await _read_and_validate(file)
    if err is not None:
        return _err(400, err)
    replace_err = _do_replace(kb_id, doc_id, file, content, ext, user["id"], user.get("username", ""))
    if replace_err is not None:
        return replace_err
    return JSONResponse(content={"status": "ok", "document": kb_models.get_document(doc_id)})


@router.post("/api/kb/mine/{kb_id}/documents/{doc_id}/reindex")
async def user_reindex_document(kb_id: int, doc_id: int, user: dict = Depends(get_current_user)):
    """用户：增量更新（重建单个文档索引）"""
    if not _user_kb_or_403(user, kb_id):
        return _err(404, "知识库不存在")
    doc = kb_models.get_document(doc_id)
    if not doc:
        return _err(404, "文档不存在")
    kb_service.index_document_async(doc_id)
    return JSONResponse(content={"status": "ok"})


@router.get("/api/kb/mine/{kb_id}/documents/{doc_id}/chunks")
async def user_preview_chunks(kb_id: int, doc_id: int, offset: int = 0, limit: int = 20,
                              user: dict = Depends(get_current_user)):
    """用户：分块预览"""
    if not _user_kb_or_403(user, kb_id):
        return _err(404, "知识库不存在")
    doc = kb_models.get_document(doc_id)
    if not doc:
        return _err(404, "文档不存在")
    limit = max(1, min(limit, 100))
    data = kb_service.preview_chunks(doc_id, offset=offset, limit=limit)
    data["document"] = doc
    return JSONResponse(content=data)


@router.post("/api/kb/mine/{kb_id}/rebuild")
async def user_rebuild_kb(kb_id: int, user: dict = Depends(get_current_user)):
    """用户：重建个人知识库索引"""
    if not _user_kb_or_403(user, kb_id):
        return _err(404, "知识库不存在")
    kb_service.rebuild_kb_async(kb_id)
    return JSONResponse(content={"status": "ok"})


@router.post("/api/kb/search-test")
async def user_search_test(req: SearchTestRequest, user: dict = Depends(get_current_user)):
    """用户：检索测试（默认全局启用库 + 我的启用库）"""
    allowed = kb_models.list_accessible_kb_ids(user["id"])
    return _search_test(req.query, req.kb_ids, req.top_k or 3, allowed)


app.include_router(router)


# ==================== 内部接口（供 chat_service 的 RAG 检索调用） ====================

@app.get("/internal/kb/search")
async def internal_search(q: str, user_id: int, top_k: int = 5):
    """供 chat_service 的 RAG 调用：返回用户可访问知识库的检索结果"""
    allowed_ids = kb_models.list_accessible_kb_ids(user_id)
    if not allowed_ids:
        return JSONResponse(content={"results": []})
    docs = kb_service.search_with_scores(q, allowed_ids, top_k=top_k)
    results = []
    for doc, score in docs:
        meta = doc.metadata or {}
        results.append({
            "content": doc.page_content,
            "score": float(score),
            "kb_id": meta.get("kb_id"),
            "filename": meta.get("filename", ""),
        })
    return JSONResponse(content={"results": results})


if __name__ == "__main__":
    import uvicorn
    from core.config import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
