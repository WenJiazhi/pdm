"""
日志模块：统一管理应用日志输出
无控制台窗口时日志写入文件，开发模式下同时输出到控制台
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.expanduser("~"), ".pdm", "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

_logger = None


def get_logger(name: str = "bduss") -> logging.Logger:
    """获取应用 Logger（单例）"""
    global _logger
    if _logger is not None:
        return _logger

    os.makedirs(LOG_DIR, exist_ok=True)

    _logger = logging.getLogger(name)
    _logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件日志（始终写入，自动轮转 5MB × 3）
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    _logger.addHandler(fh)

    # 控制台日志（仅在有控制台时输出）
    if sys.stderr is not None and hasattr(sys.stderr, "write"):
        try:
            ch = logging.StreamHandler(sys.stderr)
            ch.setLevel(logging.INFO)
            ch.setFormatter(fmt)
            _logger.addHandler(ch)
        except Exception:
            pass

    return _logger
