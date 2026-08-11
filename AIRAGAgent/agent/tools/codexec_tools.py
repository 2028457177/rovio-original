"""代码执行工具（SubAgent codexec）。

在本地 subprocess 中执行 Python 代码或 shell 命令，带超时与输出截断。
- run_python_code：独立 python 进程执行，stdin 传代码，AST 检查危险调用并告警
- run_shell_command：执行 shell 命令，高危命令黑名单可开关（由 sandbox_config 控制）
- install_package：用 uv/pip 安装 Python 依赖到当前 venv，AI 缺包时可自动补装

权限：
- shell_dangerous_enabled=true  → 任意命令都执行（仅记录日志）
- shell_dangerous_enabled=false → 黑名单拦截（rm -rf / format / shutdown 等）

超时上限由 sandbox_config.CODE_TIMEOUT_MAX 控制，用户传入的 timeout 不能超过此值。
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import tool

from AIRAGAgent.utils.logger_handler import logger
from AIRAGAgent.utils.paths import get_daily_workspace
from AIRAGAgent.agent.tools.agent_tools import user_id_var
from AIRAGAgent.agent.tools.artifact_tools import current_plan_id_var
from AIRAGAgent.agent.tools.sandbox_config import (
    SHELL_DANGEROUS_ENABLED,
    CODE_TIMEOUT_MAX,
    PYPI_MIRROR,
)

# 危险调用黑名单（仅告警，不阻止执行）
_PYTHON_DANGER_PATTERNS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "run"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("shutil", "rmtree"),
}

# shell 高危命令黑名单（默认拦截；shell_dangerous_enabled=true 时跳过）
_SHELL_DANGER_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+-fr\b",
    r"\bdel\s+/s\b",
    r"\bdel\s+/q\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\bmkfs\b",
    r":\(\)\s*\{",  # fork bomb
]

# 输出截断上限
_MAX_OUTPUT_CHARS = 5000


def _exec_cwd() -> str:
    """子进程工作目录：当前计划专属目录 workspace/{user_id}/YYYYMMDD/tasks/<plan_id>/。

    按用户 → 日期 → 计划三级隔离，不同计划之间文件互不可见，从结构上避免
    跨任务文件污染（如汇总步骤误读其他任务目录里的旧文件）；
    无计划上下文（如控制台直接调用工具）时回退到用户当天工作区。
    """
    try:
        base = get_daily_workspace(user_id_var.get())
        plan_id = current_plan_id_var.get() or ""
        if plan_id:
            d = Path(base) / "tasks" / plan_id
            d.mkdir(parents=True, exist_ok=True)
            return str(d)
    except Exception as e:
        logger.warning(f"[codexec] 任务目录创建失败，回退到当天工作区: {e}")
    return str(get_daily_workspace(user_id_var.get()))


def _clamp_timeout(timeout: int) -> int:
    """把用户传入的 timeout 限制在 [1, CODE_TIMEOUT_MAX] 区间。"""
    try:
        t = int(timeout)
    except (TypeError, ValueError):
        t = 10
    if t < 1:
        t = 1
    if t > CODE_TIMEOUT_MAX:
        t = CODE_TIMEOUT_MAX
    return t


def _scan_python_dangers(code: str) -> List[str]:
    """AST 扫描代码中的危险调用，返回告警信息列表。"""
    warnings: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        # 语法错误不阻止，交给子进程报错；仅记录
        return [f"代码存在语法错误：{e}"]

    for node in ast.walk(tree):
        # 形如 os.system(...) / subprocess.Popen(...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            value = func.value
            if isinstance(value, ast.Name):
                key = (value.id, func.attr)
                if key in _PYTHON_DANGER_PATTERNS:
                    warnings.append(f"{value.id}.{func.attr}(...) 被检测到，可能产生副作用")
        # import subprocess / os / shutil
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"subprocess", "os", "shutil"}:
                    warnings.append(f"检测到 import {alias.name}，请留意其调用是否安全")
    return warnings


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    """截断过长的文本，保留开头与结尾并提示省略。"""
    if len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half]
        + f"\n\n... [输出已截断，共 {len(text)} 字符，省略中间部分] ...\n\n"
        + text[-half:]
    )


@tool(description="执行一段 Python 代码并返回 stdout+stderr。适用于需要计算、数据处理、验证逻辑等场景。不要用于访问文件系统或网络（有专门工具）。超时上限由配置决定。")
def run_python_code(code: str, timeout: int = 10) -> str:
    """执行一段 Python 代码，返回 stdout 和 stderr 合并结果。

    Args:
        code: 要执行的 Python 源代码（多行整段传入）
        timeout: 最大执行秒数，超时自动 kill 子进程，默认 10，上限由配置决定
    """
    timeout = _clamp_timeout(timeout)

    # 危险调用检查：仅告警
    dangers = _scan_python_dangers(code)
    for d in dangers:
        logger.warning(f"[codexec] run_python_code 危险调用告警: {d}")

    kwargs = {
        "input": code,
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": timeout,
        # 子进程工作目录设为当前计划专属目录（workspace/{user_id}/YYYYMMDD/tasks/<plan_id>/），
        # AI 代码里用相对路径写文件时自然落到本计划目录，与其他计划/任务隔离。
        "cwd": _exec_cwd(),
    }
    # Windows 下独立进程组，便于超时时整组 kill
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        # 通过 stdin 传代码（python - 从 stdin 读），避免临时文件
        proc = subprocess.run([sys.executable, "-"], **kwargs)
        out = (proc.stdout or "") + (proc.stderr or "")
        if dangers:
            out = "[安全告警] " + "; ".join(dangers) + "\n" + out
        return _truncate(out)
    except subprocess.TimeoutExpired:
        return f"[执行超时] 代码运行超过 {timeout} 秒已被终止。请优化代码或增大 timeout。"
    except Exception as e:
        return f"[执行失败] {type(e).__name__}: {e}"


@tool(description="执行一条 shell 命令并返回输出。适用于查看系统状态、运行脚本、调用 CLI 工具等。高危命令（rm -rf / format / shutdown 等）默认会被拦截，可在配置中开启 shell_dangerous_enabled 解禁。")
def run_shell_command(command: str, timeout: int = 10) -> str:
    """执行 shell 命令（Windows 用 cmd，Linux 用 bash），返回 stdout+stderr。

    Args:
        command: 单条 shell 命令字符串
        timeout: 最大执行秒数，默认 10，上限由配置决定
    """
    timeout = _clamp_timeout(timeout)

    # 高危命令黑名单：仅在 shell_dangerous_enabled=false 时拦截
    if not SHELL_DANGEROUS_ENABLED:
        for pattern in _SHELL_DANGER_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                logger.warning(f"[codexec] run_shell_command 拒绝高危命令: {command}")
                return (
                    f"[拒绝执行] 命令匹配高危黑名单 ({pattern})，已拦截：{command}\n"
                    f"如需执行，请在 AIRAGAgent/config/agent.yml 设置 sandbox.shell_dangerous_enabled=true"
                )
    else:
        # 解禁模式：仅记录，不拦截
        logger.warning(f"[codexec] shell_dangerous_enabled=true，跳过黑名单，执行命令: {command}")

    kwargs = {
        "shell": True,
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": timeout,
        # 子进程工作目录设为当前计划专属目录（workspace/{user_id}/YYYYMMDD/tasks/<plan_id>/），
        # shell 命令里用相对路径写文件时自然落到本计划目录，与其他计划/任务隔离。
        "cwd": _exec_cwd(),
    }
    if sys.platform == "win32":
        # Windows 默认 shell 为 cmd.exe
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["executable"] = "/bin/bash"

    try:
        proc = subprocess.run(command, **kwargs)
        out = (proc.stdout or "") + (proc.stderr or "")
        return _truncate(out)
    except subprocess.TimeoutExpired:
        return f"[执行超时] 命令运行超过 {timeout} 秒已被终止。"
    except Exception as e:
        return f"[执行失败] {type(e).__name__}: {e}"


# ── 依赖安装工具 ──

# 项目根目录（lc-course/）
# codexec_tools.py 在 AIRAGAgent/agent/tools/ 下，需要回退 4 层
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
# 当前 venv 的 python 解释器
_VENV_PYTHON = sys.executable
# venv 根目录
_VENV_ROOT = Path(_VENV_PYTHON).parent.parent


def _find_uv() -> Optional[str]:
    """查找 uv 可执行文件路径。

    优先级：
    1. PATH 中的 uv（shutil.which）
    2. ~/.local/bin/uv（uv 默认安装位置）
    3. venv 内的 uv（uv pip install 装到 venv 时会放这里）
    """
    # 1. PATH
    uv_in_path = shutil.which("uv")
    if uv_in_path:
        return uv_in_path

    # 2. ~/.local/bin
    home_local = Path.home() / ".local" / "bin"
    if sys.platform == "win32":
        uv_candidate = home_local / "uv.exe"
    else:
        uv_candidate = home_local / "uv"
    if uv_candidate.exists():
        return str(uv_candidate)

    # 3. venv
    venv_bin = Path(_VENV_PYTHON).parent
    if sys.platform == "win32":
        uv_candidate = venv_bin / "uv.exe"
    else:
        uv_candidate = venv_bin / "uv"
    if uv_candidate.exists():
        return str(uv_candidate)

    return None


@tool(description="安装 Python 依赖包到当前项目虚拟环境。当 run_python_code 因 ModuleNotFoundError 失败时，先用本工具装包再重试。支持 PyPI 包名或 git URL。")
def install_package(package: str, timeout: int = 60) -> str:
    """安装 Python 包到当前 venv。

    自动检测并使用 uv（优先）或 pip。安装完成后包立即生效，可被 run_python_code 导入。

    Args:
        package: 包名（如 "requests"）、带版本（如 "pandas>=2.0"）、
                 或 git URL（如 "git+https://github.com/xxx/yyy.git"）
        timeout: 安装超时秒数，默认 60，上限由配置决定
    """
    timeout = _clamp_timeout(timeout)
    # 安装可能较慢，允许更大超时（最多 120s）
    timeout = min(timeout, 120)

    if not package or not package.strip():
        return "[参数错误] package 不能为空"

    package = package.strip()

    # 优先用 uv（速度快，且本项目用 uv 管理 venv）
    uv_path = _find_uv()
    if uv_path:
        # uv pip install 需要在项目根目录执行（找 pyproject.toml）
        cmd = [uv_path, "pip", "install", package]
        # 加 PyPI 镜像源（uv 用 --index-url 参数）
        if PYPI_MIRROR:
            cmd.extend(["--index-url", PYPI_MIRROR])
        cwd = str(_PROJECT_ROOT)
        logger.info(f"[codexec] install_package 用 uv: {cmd} (cwd={cwd})")
    else:
        # 回退到 venv 内的 pip（如果存在）
        venv_bin = Path(_VENV_PYTHON).parent
        if sys.platform == "win32":
            pip_path = venv_bin / "pip.exe"
        else:
            pip_path = venv_bin / "pip"
        if pip_path.exists():
            cmd = [str(pip_path), "install", package]
            if PYPI_MIRROR:
                cmd.extend(["-i", PYPI_MIRROR])
            cwd = None
            logger.info(f"[codexec] install_package 用 pip: {cmd}")
        else:
            # 最后回退：python -m pip
            cmd = [_VENV_PYTHON, "-m", "pip", "install", package]
            if PYPI_MIRROR:
                cmd.extend(["-i", PYPI_MIRROR])
            cwd = None
            logger.info(f"[codexec] install_package 用 python -m pip: {cmd}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            cwd=cwd,
        )
        out = (proc.stdout or "") + (proc.stderr or "")

        # 判定成功/失败
        if proc.returncode == 0:
            # uv 成功时输出可能为空，给个明确提示
            if not out.strip():
                out = f"成功安装 {package}"
            result = f"[安装成功] {package}\n{out}"
        else:
            result = f"[安装失败] 返回码 {proc.returncode}\n{out}"

        logger.info(f"[codexec] install_package {package} 返回码={proc.returncode}")
        return _truncate(result)
    except subprocess.TimeoutExpired:
        return f"[安装超时] {package} 安装超过 {timeout} 秒被终止。可尝试增大 timeout 或检查网络。"
    except Exception as e:
        return f"[安装失败] {type(e).__name__}: {e}"


@tool(description="列出当前虚拟环境已安装的 Python 包。当不确定某个包是否已装时先查一下，避免重复安装。")
def list_packages() -> str:
    """列出当前 venv 已安装的包。"""
    uv_path = _find_uv()
    if uv_path:
        cmd = [uv_path, "pip", "list"]
    else:
        cmd = [_VENV_PYTHON, "-m", "pip", "list"]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return _truncate(out) if out else "[无输出]"
    except Exception as e:
        return f"[查询失败] {type(e).__name__}: {e}"


CODEXEC_TOOLS = [run_python_code, run_shell_command, install_package, list_packages]
