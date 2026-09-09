"""user_service FastAPI 入口。

路由：
- PATCH  /api/user/profile              修改昵称 / 邮箱
- POST   /api/user/avatar               上传头像
- GET    /api/avatars/{filename}        提供头像文件访问
- POST   /api/user/schedule             上传课表 Excel + 开学日期
- PATCH  /api/user/schedule/start-date  仅修改开学日期
- GET    /api/user/schedule             获取课表设置
- DELETE /api/user/schedule             删除课表（DB + 物理文件）
- GET    /api/schedules/{filename}      提供课表文件下载
- DELETE /api/user/account              注销账号
- 内部 GET    /internal/user/profile      供其他服务查询用户资料
- 内部 POST   /internal/user/profile      供 auth_service 注册时创建资料记录
- 内部 POST   /internal/user/delete       供 auth_service 注销时清理 user 数据
- 内部 DELETE /internal/user/{user_id}    同上（DELETE 方式）
"""
from __future__ import annotations
import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, UploadFile, File, Form, Header
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from core import (
    create_app, get_current_user, get_client_ip,
    ServiceClient, logger,
)
from core.paths import UPLOAD_DIR
import models

app = create_app("user_service", version="1.0.0")

UPLOAD_DIR_PATH = Path(UPLOAD_DIR)


# ==================== 请求体 ====================

class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None


class ScheduleStartDateRequest(BaseModel):
    start_date: Optional[str] = None  # None 表示清除


class ModelSettingsRequest(BaseModel):
    base_url: str
    api_key: str = ""
    model_name: str


class DeleteAccountRequest(BaseModel):
    password: str


class InternalProfileRequest(BaseModel):
    user_id: int
    display_name: str = ""


# ==================== 用户资料 API ====================

@app.patch("/api/user/profile")
async def update_profile(req: ProfileUpdateRequest, user: dict = Depends(get_current_user)):
    """修改昵称 / 邮箱"""
    updated = await asyncio.get_event_loop().run_in_executor(
        None, models.upsert_profile, user["id"], req.display_name, req.email
    )
    if updated is None:
        return JSONResponse(status_code=400, content={"error": "昵称不能为空"})
    return JSONResponse(content={"status": "ok", "user": updated})


@app.post("/api/user/avatar")
async def upload_avatar(avatar: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """上传头像"""
    # 校验文件类型
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    content_type = avatar.content_type or ""
    if content_type not in allowed_types and not avatar.filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return JSONResponse(status_code=400, content={"error": "仅支持 JPG / PNG / GIF / WEBP 格式"})

    content = await avatar.read()
    if len(content) > 5 * 1024 * 1024:  # 5MB
        return JSONResponse(status_code=400, content={"error": "头像大小不能超过 5MB"})

    ext = os.path.splitext(avatar.filename)[1] or ".png"
    avatar_name = f"avatar_{user['id']}_{uuid.uuid4().hex[:8]}{ext}"
    avatar_dir = UPLOAD_DIR_PATH / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    avatar_path = avatar_dir / avatar_name
    with open(avatar_path, "wb") as f:
        f.write(content)

    avatar_url = f"/api/avatars/{avatar_name}"
    await asyncio.get_event_loop().run_in_executor(
        None, models.update_avatar_url, user["id"], avatar_url
    )
    return JSONResponse(content={"status": "ok", "avatar_url": avatar_url})


@app.get("/api/avatars/{filename}")
async def serve_avatar(filename: str):
    """提供头像文件访问"""
    # 防止路径穿越
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse(status_code=400, content={"error": "非法文件名"})
    avatar_path = UPLOAD_DIR_PATH / "avatars" / filename
    if not avatar_path.exists():
        return JSONResponse(status_code=404, content={"error": "头像不存在"})
    return FileResponse(path=str(avatar_path))


# ==================== 课表 API ====================

@app.post("/api/user/schedule")
async def upload_schedule(
    file: UploadFile = File(...),
    start_date: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """上传 / 替换课表 Excel + 开学日期

    multipart/form-data:
        file: .xlsx / .xls 课表文件
        start_date: 'YYYY-MM-DD' 开学日期
    """
    # 1. 校验文件后缀。UploadFile.filename 理论上总是字符串，
    #    但客户端可以构造缺失 filename 的 multipart part，不能因此返回 500。
    original_name = (file.filename or "").strip()
    suffix = Path(original_name).suffix.lower()
    if suffix not in (".xlsx", ".xls"):
        return JSONResponse(status_code=400, content={"error": "仅支持 .xlsx / .xls 格式课表"})

    # 2. 校验大小（课表通常很小，限 2MB）
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"error": "课表文件不能超过 2MB"})

    # 3. 校验开学日期格式
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "开学日期格式应为 YYYY-MM-DD"})

    # 4. 用 pandas 预校验 Excel 列名（避免坏文件污染数据），并顺带预解析课程结构
    import io
    import json

    import pandas as pd

    from schedule_parser import parse_schedule_df
    try:
        df = pd.read_excel(io.BytesIO(content), header=2, index_col=0, sheet_name=0)
        required_cols = {"星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期天"}
        actual_cols = {str(c).strip() for c in df.columns}
        if not required_cols.issubset(actual_cols):
            missing = "、".join(sorted(required_cols - actual_cols))
            return JSONResponse(status_code=400, content={
                "error": f"Excel 列名不符合要求，缺少：{missing}（需包含 星期一~星期天）"
            })
        # 上传时解析一次存 DB，查询时免读 Excel；解析失败不阻塞上传（查询侧回退旧逻辑）
        parsed_json = None
        try:
            parsed_json = json.dumps(
                parse_schedule_df(df), ensure_ascii=False, separators=(",", ":")
            )
        except Exception as e:
            logger.warning(f"[upload_schedule] 课表预解析失败（回退查询时解析）：{e}")
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Excel 解析失败：{e}"})

    # 5. 覆盖式保存。保留扩展名，否则上传 .xls 后会被伪装成 .xlsx，
    #    get_schedule 读取时会因引擎/文件格式不匹配而失败。
    schedule_dir = UPLOAD_DIR_PATH / "schedules"
    schedule_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"schedule_{user['id']}{suffix}"
    save_path = schedule_dir / file_name
    with open(save_path, "wb") as f:
        f.write(content)

    rel_path = f"schedules/{file_name}"
    await asyncio.get_event_loop().run_in_executor(
        None, models.update_schedule, user["id"], rel_path, start_date, parsed_json
    )

    # 清理用户此前使用另一种 Excel 扩展名上传时留下的旧文件，避免磁盘
    # 垃圾和删除课表后仍残留可访问文件。
    for old_suffix in (".xlsx", ".xls"):
        if old_suffix != suffix:
            try:
                (schedule_dir / f"schedule_{user['id']}{old_suffix}").unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"[upload_schedule] 清理旧文件失败：{e}")

    return JSONResponse(content={
        "status": "ok",
        "schedule_url": f"/api/schedules/{file_name}",
        "start_date": start_date,
    })


@app.patch("/api/user/schedule/start-date")
async def update_schedule_start_date(req: ScheduleStartDateRequest, user: dict = Depends(get_current_user)):
    """仅修改开学日期（不重传文件）。

    允许尚未上传课表时先保存日期（后续上传课表时再一并覆盖）。
    """
    if req.start_date:
        try:
            datetime.strptime(req.start_date, "%Y-%m-%d")
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "日期格式应为 YYYY-MM-DD"})
    await asyncio.get_event_loop().run_in_executor(
        None, models.update_schedule_start_date, user["id"], req.start_date
    )
    return JSONResponse(content={"status": "ok", "start_date": req.start_date})


@app.get("/api/user/schedule")
async def get_schedule_settings(user: dict = Depends(get_current_user)):
    """获取当前用户的课表设置状态"""
    settings = await asyncio.get_event_loop().run_in_executor(
        None, models.get_schedule_settings, user["id"]
    )
    return JSONResponse(content=settings)


@app.delete("/api/user/schedule")
async def delete_schedule(user: dict = Depends(get_current_user)):
    """删除当前用户的课表（DB 记录 + 物理文件）"""
    old_rel = await asyncio.get_event_loop().run_in_executor(
        None, models.clear_schedule, user["id"]
    )
    if old_rel:
        try:
            (UPLOAD_DIR_PATH / old_rel).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"[delete_schedule] 删除文件 {old_rel} 失败：{e}")
    return JSONResponse(content={"status": "ok"})


@app.get("/api/schedules/{filename}")
async def serve_schedule(filename: str):
    """提供课表文件下载 / 访问"""
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse(status_code=400, content={"error": "非法文件名"})
    schedule_path = UPLOAD_DIR_PATH / "schedules" / filename
    if not schedule_path.exists():
        return JSONResponse(status_code=404, content={"error": "课表不存在"})
    return FileResponse(path=str(schedule_path))


# ==================== 模型设置 API（用户自配 OpenAI 兼容模型） ====================

@app.get("/api/user/model")
async def get_model_settings(user: dict = Depends(get_current_user)):
    """获取当前用户的模型配置（api_key 脱敏返回）"""
    settings = await asyncio.get_event_loop().run_in_executor(
        None, models.get_model_settings, user["id"]
    )
    return JSONResponse(content=settings)


@app.put("/api/user/model")
async def save_model_settings(req: ModelSettingsRequest, user: dict = Depends(get_current_user)):
    """保存当前用户的模型配置（OpenAI 兼容：Base URL + API Key + 模型名）

    配置后 AI 对话将使用该模型；清除后恢复系统默认模型。
    """
    base_url = (req.base_url or "").strip()
    model_name = (req.model_name or "").strip()
    if not base_url.startswith(("http://", "https://")):
        return JSONResponse(status_code=400, content={"error": "Base URL 必须以 http:// 或 https:// 开头"})
    if not model_name:
        return JSONResponse(status_code=400, content={"error": "模型名称不能为空"})
    await asyncio.get_event_loop().run_in_executor(
        None, models.save_model_settings, user["id"], base_url, req.api_key or "", model_name
    )
    settings = await asyncio.get_event_loop().run_in_executor(
        None, models.get_model_settings, user["id"]
    )
    return JSONResponse(content={"status": "ok", "settings": settings})


@app.delete("/api/user/model")
async def clear_model_settings(user: dict = Depends(get_current_user)):
    """清除当前用户的模型配置，恢复系统默认模型"""
    await asyncio.get_event_loop().run_in_executor(
        None, models.clear_model_settings, user["id"]
    )
    return JSONResponse(content={"status": "ok"})


# ==================== 注销账号 ====================

@app.delete("/api/user/account")
async def delete_account(req: DeleteAccountRequest, user: dict = Depends(get_current_user)):
    """注销账号

    流程：
    1. 调用 auth_service 删除用户认证记录（内部校验不能删 admin）
    2. 成功则清理 user 数据 + 删除 schedule 物理文件
    3. 可选：调用 chat_service 清理会话（失败不阻塞）
    """
    user_id = user["id"]

    # 1. 调用 auth_service 删除认证记录
    try:
        async with ServiceClient("auth") as client:
            resp = await client.post(f"/internal/auth/users/{user_id}/delete")
            if resp.status_code != 200:
                detail = resp.json().get("error", "认证服务删除失败")
                return JSONResponse(status_code=400, content={"error": detail})
    except Exception as e:
        logger.error(f"[delete_account] 调用 auth_service 失败: {e}")
        return JSONResponse(status_code=500, content={"error": "认证服务不可用"})

    # 2. 清理 user 数据 + 删除 schedule 物理文件
    await _cleanup_user_data(user_id)

    # 3. 可选：调用 chat_service 清理会话（失败不阻塞）
    try:
        async with ServiceClient("chat") as client:
            await client.delete(f"/internal/chat/users/{user_id}/data")
    except Exception as e:
        logger.warning(f"[delete_account] 清理 chat_service 数据失败（不阻塞）: {e}")

    return JSONResponse(content={"status": "ok"})


# ==================== 内部接口（供其他服务调用，不暴露给 nginx） ====================

@app.get("/internal/user/profile")
async def internal_get_profile(user_id: int):
    """供其他服务查询用户资料"""
    profile = await asyncio.get_event_loop().run_in_executor(
        None, models.get_profile, user_id
    )
    return JSONResponse(content={
        "profile": {
            "display_name": profile["display_name"],
            "email": profile["email"],
            "avatar_url": profile["avatar_url"],
        }
    })


@app.get("/internal/user/model-config")
async def internal_get_model_config(user_id: int, x_internal_call: str = Header(default="")):
    """供 AI 模型层查询用户完整模型配置（api_key 不脱敏）。

    仅接受带 X-Internal-Call 头的内部调用，防止 API Key 被外部访问。
    """
    if x_internal_call != "1":
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    cfg = await asyncio.get_event_loop().run_in_executor(
        None, models.get_model_config_raw, user_id
    )
    return JSONResponse(content={"config": cfg})


@app.post("/internal/user/profile")
async def internal_create_profile(req: InternalProfileRequest):
    """供 auth_service 注册时创建 user_profiles 记录（INSERT IGNORE）"""
    await asyncio.get_event_loop().run_in_executor(
        None, models.ensure_profile, req.user_id, req.display_name
    )
    return JSONResponse(content={"status": "ok"})


@app.post("/internal/user/delete")
async def internal_delete_user(user_id: int):
    """供 auth_service 注销时清理 user 数据（query 参数方式）"""
    await _cleanup_user_data(user_id)
    return JSONResponse(content={"status": "ok"})


@app.delete("/internal/user/{user_id}")
async def internal_delete_user_by_path(user_id: int):
    """供 auth_service 注销时清理 user 数据（路径参数方式）"""
    await _cleanup_user_data(user_id)
    return JSONResponse(content={"status": "ok"})


# ==================== 辅助函数 ====================

async def _cleanup_user_data(user_id: int):
    """清理用户 user 侧数据：课表物理文件 + user_profiles + user_schedules。"""
    # 先取课表文件相对路径，再删 DB 记录，最后删物理文件
    old_rel = await asyncio.get_event_loop().run_in_executor(
        None, models.clear_schedule, user_id
    )
    if old_rel:
        try:
            (UPLOAD_DIR_PATH / old_rel).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"[_cleanup_user_data] 删除课表文件 {old_rel} 失败：{e}")

    await asyncio.get_event_loop().run_in_executor(
        None, models.delete_user_data, user_id
    )


if __name__ == "__main__":
    import uvicorn
    from core.config import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
