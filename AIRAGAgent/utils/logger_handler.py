import os
import re

import logging
from coloredlogs import DEFAULT_LOG_FORMAT
from datetime import datetime, timedelta

from AIRAGAgent.utils.path_tool import get_abs_path

# 日志保存的根目录
L0G_R00T = get_abs_path("logs")

# 确保日志目录存在
os.makedirs(L0G_R00T, exist_ok=True)

# 日志保留天数
LOG_RETENTION_DAYS = 7


def cleanup_old_logs(retention_days: int = LOG_RETENTION_DAYS):
    """
    清理超过 retention_days 天的旧日志文件。
    日志文件名格式: {name}_YYYYMMDD.log
    """
    if not os.path.isdir(L0G_R00T):
        return

    cutoff_date = datetime.now() - timedelta(days=retention_days)
    log_pattern = re.compile(r"^.+_(\d{8})\.log$")

    for filename in os.listdir(L0G_R00T):
        match = log_pattern.match(filename)
        if not match:
            continue

        try:
            file_date = datetime.strptime(match.group(1), "%Y%m%d")
        except ValueError:
            continue

        if file_date < cutoff_date:
            filepath = os.path.join(L0G_R00T, filename)
            try:
                os.remove(filepath)
                logging.getLogger(__name__).info(f"已清理过期日志: {filename}")
            except OSError:
                logging.getLogger(__name__).warning(f"无法删除日志文件: {filename}")


cleanup_old_logs()

#日志的格式配置 error info debug
DEFAULT_LOG_FORMAT = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)

def get_logger(
        name: str = "agent",
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
        log_file = None
) -> logging.Logger:
    """获取或创建指定名称的日志器，同时输出到控制台和日志文件并返回该日志器。"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 防止日志传播到 root logger 被二次输出

    #避免重复添加Handler
    if logger.handlers:
        return logger

    #控制台Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(console_handler)

    #文件Handler
    if not log_file:
        log_file = os.path.join(L0G_R00T, f"{name}_{datetime.now().strftime('%Y%m%d')}.log")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(file_handler)

    return logger


#快捷获取日志器
logger = get_logger()

if __name__ == '__main__':
    logger.info("信息日志")
    logger.warning("警告日志")
    logger.error("错误日志")
    logger.debug("调试日志")
