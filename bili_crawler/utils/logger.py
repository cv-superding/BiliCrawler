"""日志工具：提供统一的、线程安全的 logger 实例。"""

from __future__ import annotations

import logging
import sys

_CONFIGURED: dict[str, logging.Logger] = {}


def get_logger(name: str = "bili_crawler") -> logging.Logger:
    """返回命名 logger；同一名称仅配置一次 handler，避免重复输出。

    Args:
        name: logger 名称，默认 ``bili_crawler``。

    Returns:
        logging.Logger: 配置好的 logger。
    """
    if name in _CONFIGURED:
        return _CONFIGURED[name]

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%H:%M:%S"
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    _CONFIGURED[name] = logger
    return logger
