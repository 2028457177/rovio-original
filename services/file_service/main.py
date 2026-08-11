"""file_service FastAPI 入口。

路由：
- POST /api/upload-word       上传 Word 文件
- GET  /api/download/{filename}   下载 Word 文件
- GET  /api/file/list         列 AI 工作区目录内容
- GET  /api/file/download     下载 AI 工作区文件
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse

from core import create_app, logger
from core.jwt_auth import get_current_user
from core.paths import UPLOAD_DIR, WORKSPACE_DIR

app = create_app("file_service", version="1.0.0")

# 上传目录确保存在
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _user_workspace_root(user_id: int) -> str:
    """当前用户的 AI 工作区根目录 workspace/{user_id}（自动创建）。"""
    root = os.path.join(WORKSPACE_DIR, str(user_id))
    os.makedirs(root, exist_ok=True)
    return root

# 允许的 Word 文件后缀
ALLOWED_EXTS = (".docx", ".doc")
# Word 下载的 media_type
WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# AI 工作区文件浏览器要隐藏的子目录（playwright 浏览器二进制等系统目录）
# plan_results 是计划执行中的步骤结果中间产物（完整数据已存 DB），对用户无价值，一律不展示
_HIDDEN_ENTRIES = {".playwright", "plan_results"}


@app.post("/api/upload-word")
async def upload_word(file: UploadFile = File(...)):
    """上传 Word 文件到服务器"""
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTS):
        return JSONResponse(status_code=400, content={"error": "仅支持 .docx 和 .doc 格式的文件"})

    # 生成唯一文件名，保留原始扩展名
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(f"[file_service] 文件已上传: {file.filename} -> {file_path}")
    return JSONResponse(content={
        "success": True,
        "filename": unique_name,
        "original_name": file.filename,
        "server_path": file_path,
    })


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """下载 Word 文件"""
    # 防路径穿越：只取文件名，并校验解析后的真实路径在 UPLOAD_DIR 内
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename:
        return JSONResponse(status_code=400, content={"error": "非法的文件名"})

    file_path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.realpath(file_path).startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
        return JSONResponse(status_code=400, content={"error": "非法的文件名"})

    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"error": "文件不存在"})

    return FileResponse(
        path=file_path,
        filename=safe_name,
        media_type=WORD_MEDIA_TYPE,
    )


# ─────────────────────────────────────────────────────────
# AI 工作区文件浏览（/api/file/*）
# ─────────────────────────────────────────────────────────

# 可预览的图片扩展名（前端直接 <img> 显示）
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
# 可在线预览的文本扩展名
_TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".log", ".yml", ".yaml", ".py", ".js", ".ts", ".html", ".css", ".xml", ".ini"}


def _resolve_workspace_path(rel_path: str, user_id: int) -> Path | None:
    """把相对当前用户工作区（workspace/{user_id}）的子路径解析为绝对路径，并做路径穿越防护。

    返回 None 表示非法（穿越或不存在）。
    """
    if not rel_path:
        rel_path = ""
    # 规范化：去掉首尾分隔符和 . / ..
    rel_path = rel_path.strip().replace("\\", "/").lstrip("/")
    # 拒绝 .. 穿越
    if ".." in rel_path.split("/"):
        return None

    root = Path(_user_workspace_root(user_id)).resolve()
    target = (root / rel_path).resolve() if rel_path else root

    # 必须在当前用户工作区内
    try:
        target.relative_to(root)
    except ValueError:
        return None

    if not target.exists():
        return None
    return target


def _entry_info(p: Path, base: Path) -> dict:
    """构造单个文件/目录的元信息。"""
    rel = str(p.relative_to(base)).replace("\\", "/")
    is_dir = p.is_dir()
    ext = p.suffix.lower() if not is_dir else ""
    info = {
        "name": p.name,
        "path": rel,                       # 相对 workspace 根的路径
        "is_dir": is_dir,
        "ext": ext,
        "size": p.stat().st_size if not is_dir else 0,
        "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        "is_image": ext in _IMAGE_EXTS,
        "is_text": ext in _TEXT_EXTS,
    }
    return info


@app.get("/api/file/list")
async def list_workspace(path: str = Query(default="", description="相对当前用户工作区的子路径，空表示根目录"), user: dict = Depends(get_current_user)):
    """列出当前登录用户 AI 工作区指定目录的内容（目录优先，再按名字排序）。

    返回结构：
    {
      "path": "screenshots",          # 当前目录相对路径
      "parent": "",                   # 上一级路径（根目录时为空）
      "entries": [
        {"name": "...", "path": "...", "is_dir": bool, "ext": "...", "size": int, "mtime": "...", "is_image": bool, "is_text": bool},
        ...
      ]
    }
    """
    target = _resolve_workspace_path(path, user["id"])
    if target is None:
        return JSONResponse(status_code=400, content={"error": "非法或不存在的工作区路径"})

    if not target.is_dir():
        return JSONResponse(status_code=400, content={"error": "目标路径不是目录"})

    base = Path(_user_workspace_root(user["id"])).resolve()
    current_rel = str(target.relative_to(base)).replace("\\", "/")
    parent_rel = str(Path(current_rel).parent).replace("\\", "/") if current_rel else ""

    entries = []
    for p in target.iterdir():
        # 隐藏 .playwright 等系统目录
        if p.name in _HIDDEN_ENTRIES or p.name.startswith("."):
            continue
        try:
            entries.append(_entry_info(p, base))
        except OSError:
            continue

    # 排序：目录优先，再按名字
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))

    return {
        "path": current_rel,
        "parent": parent_rel,
        "entries": entries,
    }


@app.get("/api/file/download")
async def download_workspace_file(path: str = Query(..., description="相对当前用户工作区的文件路径"), user: dict = Depends(get_current_user)):
    """下载当前登录用户 AI 工作区内的文件（支持任意类型，自动判定 media_type）。"""
    target = _resolve_workspace_path(path, user["id"])
    if target is None:
        return JSONResponse(status_code=404, content={"error": "文件不存在或路径非法"})
    if not target.is_file():
        return JSONResponse(status_code=400, content={"error": "目标路径不是文件"})

    # 按扩展名判定 media_type（让浏览器能直接预览图片/文本）
    ext = target.suffix.lower()
    if ext in _IMAGE_EXTS:
        media_type = f"image/{ext[1:]}" if ext != ".jpg" else "image/jpeg"
    elif ext in _TEXT_EXTS:
        media_type = "text/plain; charset=utf-8"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type=media_type,
    )


@app.get("/api/file/preview")
async def preview_workspace_file(path: str = Query(..., description="相对当前用户工作区的文件路径，inline 预览"), user: dict = Depends(get_current_user)):
    """inline 方式返回当前登录用户工作区文件，让浏览器直接预览（图片/文本）。"""
    target = _resolve_workspace_path(path, user["id"])
    if target is None:
        return JSONResponse(status_code=404, content={"error": "文件不存在或路径非法"})
    if not target.is_file():
        return JSONResponse(status_code=400, content={"error": "目标路径不是文件"})

    ext = target.suffix.lower()
    if ext in _IMAGE_EXTS:
        media_type = f"image/{ext[1:]}" if ext != ".jpg" else "image/jpeg"
    elif ext in _TEXT_EXTS:
        media_type = "text/plain; charset=utf-8"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type=media_type,
        content_disposition_type="inline",
    )


if __name__ == "__main__":
    import uvicorn
    from core.config import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
