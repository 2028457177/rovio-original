"""微服务日志（本服务独立副本）。

每个服务进程独立写日志到 LOG_DIR，文件名带服务名前缀。
LOG_DIR 可通过环境变量覆盖（生产环境指向共享日志目录）。
"""
import os
import logging
import logging.handlers
from datetime import datetime

from .paths import LOG_DIR

os.makedirs(LOG_DIR, exist_ok=True)

# 当前服务名，由各服务启动时设置
_current_service = "service"


def set_service_name(name: str):
    """设置当前服务名（用于日志器命名与日志文件名）。"""
    global _current_service
    _current_service = name


def _build_logger() -> logging.Logger:
    """构建并返回 Logger：输出到按天滚动的日志文件与控制台。"""
    log = logging.getLogger(f"lc_course.{_current_service}")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)

    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(LOG_DIR, f"{_current_service}_{today}.log")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler，按天滚动，保留 7 天
    try:
        fh = logging.handlers.TimedRotatingFileHandler(
            log_file, when="midnight", backupCount=7, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        pass

    # 控制台 handler
    try:
        import coloredlogs
        coloredlogs.install(level="INFO", logger=log, fmt="%(asctime)s [%(levelname)s] %(message)s")
    except Exception:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        log.addHandler(ch)

    return log


logger = _build_logger()
