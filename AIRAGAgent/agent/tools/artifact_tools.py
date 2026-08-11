"""DeepAgent Artifact 工具：让 Agent 把生成物（文档/代码/数据/笔记）注册为一等公民。

Artifact 与普通输出的区别：
- 持久化到 DB（artifacts 表），跨会话可引用
- 有版本、有 parent（衍生关系）
- 前端可单独展示和管理（类似 TraeWork 的产物面板）

支持类型：doc / code / sheet / file / note
"""
import os
import uuid
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool

from AIRAGAgent.utils.logger_handler import logger
from AIRAGAgent.utils.paths import UPLOAD_DIR
from AIRAGAgent.agent.tools.agent_tools import user_id_var

# plan_id 和 session_id 在执行期由 Orchestrator 通过 ContextVar 注入
# 这里用模块级 ContextVar，避免改动 agent_tools 太多
import contextvars
current_plan_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('current_plan_id', default="")
current_session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('current_session_id', default="")
current_step_idx_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar('current_step_idx', default=None)

ARTIFACT_DIR = UPLOAD_DIR / "artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _uid() -> int:
    """获取当前请求的用户 ID，未设置时抛异常。"""
    uid = user_id_var.get()
    if uid is None:
        raise RuntimeError("当前请求未设置 user_id_var，无法创建 artifact")
    return int(uid)


def _save_artifact_file(content: str, art_id: str, ext: str) -> str:
    """把内容写到磁盘，返回相对 content_ref（供下载）。"""
    filename = f"{art_id}.{ext}"
    filepath = ARTIFACT_DIR / filename
    filepath.write_text(content, encoding="utf-8")
    # content_ref 存相对路径，下载时拼接 UPLOAD_DIR
    return f"artifacts/{filename}"


@tool(description="""把一段内容注册为 Artifact（一等公民产物）。

适用场景：
- 生成了文档/报告/方案 → type=doc
- 写了一段代码/脚本 → type=code
- 整理了表格数据 → type=sheet
- 把笔记/总结归档 → type=note
- 用户上传的文件被处理过 → type=file

Artifact 会持久化，后续可通过 list_artifacts / get_artifact 引用，前端会展示在产物面板。""")
def create_artifact(title: str, content: str, type: str = "doc",
                    mime_type: str = "") -> str:
    """
    Args:
        title: 产物标题，简短描述这是什么（如"Q3 工作报告"、"数据清洗脚本"）
        content: 产物正文（文本内容）。代码就传代码，文档就传 markdown/纯文本。
        type: doc / code / sheet / note / file，默认 doc
        mime_type: 可选，如 text/markdown、text/x-python
    """
    try:
        from AIRAGAgent.database import create_artifact as _db_create, get_artifact as _db_get
        uid = _uid()
        session_id = current_session_id_var.get() or ""
        plan_id = current_plan_id_var.get() or ""
        step_idx = current_step_idx_var.get()

        # 生成 art_id（与 DB 行一致）
        art_id = f"art_{uuid.uuid4().hex[:16]}"
        ext_map = {"doc": "md", "code": "txt", "sheet": "csv", "note": "md", "file": "txt"}
        ext = ext_map.get(type, "txt")
        content_ref = _save_artifact_file(content, art_id, ext)

        # 直接调用 DB 函数（用我们生成的 art_id）
        import pymysql
        from AIRAGAgent.database.connection import get_db
        import json as _json
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO artifacts
                   (id, user_id, session_id, plan_id, step_idx, type, title,
                    content_ref, mime_type, parent_id, meta)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (art_id, uid, session_id, plan_id, step_idx,
                 type[:30], title[:255], content_ref, mime_type[:100],
                 "", _json.dumps({"size": len(content)}, ensure_ascii=False))
            )
            conn.commit()

        logger.info(f"[artifact] created id={art_id} type={type} title={title} user={uid}")
        download_url = f"/api/artifacts/{art_id}/download"
        return (
            f"已创建 Artifact：\n"
            f"- id: {art_id}\n"
            f"- 标题: {title}\n"
            f"- 类型: {type}\n"
            f"- 下载: {download_url}\n"
            f"- 内容预览: {content[:200]}{'...' if len(content) > 200 else ''}"
        )
    except Exception as e:
        logger.error(f"[artifact] 创建失败: {e}")
        return f"创建 Artifact 失败：{e}"


@tool(description="列出当前用户的 Artifact。可按会话或类型过滤。返回最近的产物列表。")
def list_artifacts(session_id: str = "", type: str = "", limit: int = 20) -> str:
    """
    Args:
        session_id: 限定某会话内的 artifact。空字符串表示不限。
        type: 限定类型：doc / code / sheet / note / file。空字符串表示不限。
        limit: 最多返回几条，默认 20
    """
    try:
        from AIRAGAgent.database import list_artifacts as _db_list
        uid = _uid()
        rows = _db_list(uid, session_id=session_id or None, art_type=type or None, limit=int(limit))
        if not rows:
            return "暂无 Artifact"
        lines = [f"共 {len(rows)} 个 Artifact："]
        for r in rows:
            lines.append(f"- [{r['type']}] {r['title']} (id={r['id']}, 版本={r['version']}, 创建={r['created_at']})")
        return "\n".join(lines)
    except Exception as e:
        return f"查询失败：{e}"


@tool(description="读取一个 Artifact 的完整内容（按 id）。用于在后续步骤中引用之前的产物。")
def get_artifact(artifact_id: str) -> str:
    """Args: artifact_id: Artifact 的 id（以 art_ 开头）"""
    try:
        from AIRAGAgent.database import get_artifact as _db_get
        uid = _uid()
        art = _db_get(uid, artifact_id)
        if not art:
            return f"未找到 Artifact: {artifact_id}"
        # 读取磁盘内容
        content_ref = art["content_ref"]
        filepath = UPLOAD_DIR / content_ref
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
        else:
            content = f"[内容文件缺失: {content_ref}]"
        return (
            f"Artifact: {art['title']}\n"
            f"类型: {art['type']} | 版本: {art['version']} | 创建: {art['created_at']}\n"
            f"---\n{content}"
        )
    except Exception as e:
        return f"读取失败：{e}"


ARTIFACT_TOOLS = [create_artifact, list_artifacts, get_artifact]
