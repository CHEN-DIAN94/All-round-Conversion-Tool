"""
logging_config.py — 全局日志配置

提供：
- get_logger(name) — 获取带文件+控制台 handler 的 logger
- 自动创建 logs/ 目录和按日期滚动的日志文件
- 统一格式：[timestamp] [level] module: message
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path


_LOG_DIR = Path(__file__).resolve().parent / 'logs'
_configured = False


def _setup_root_logger() -> None:
    """一次性配置根 logger：控制台 + 文件双 handler。"""
    global _configured
    if _configured:
        return
    _configured = True

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_format = '[%(asctime)s] [%(levelname)s] %(name)s: %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # 根 logger，级别 DEBUG
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 控制台 handler（INFO 级别）
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件 handler（DEBUG 级别，按天命名）
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = _LOG_DIR / f'{today}.log'
    file_handler = logging.FileHandler(
        str(log_file), encoding='utf-8', delay=True,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    获取一个命名 logger。

    模块内使用::

        from logging_config import get_logger
        logger = get_logger(__name__)
        logger.info('转换开始')

    Args:
        name: logger 名称，通常传 __name__

    Returns:
        配置好的 logging.Logger 实例
    """
    _setup_root_logger()
    return logging.getLogger(name)
