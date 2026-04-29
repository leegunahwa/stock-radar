"""共用 logger 設定模組。

提供統一的 logging 設定,支援 console 與檔案輸出,
日誌等級可由環境變數 LOG_LEVEL 控制。
"""

from __future__ import annotations

import logging
import os
import sys
from logging import Logger
from pathlib import Path

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str = "stock_radar",
    log_file: str | Path | None = None,
    level: str | None = None,
) -> Logger:
    """建立並回傳設定完成的 logger。

    若同名 logger 已設定 handler,則直接回傳避免重複註冊。

    Args:
        name: Logger 名稱,預設為 "stock_radar"。
        log_file: 日誌檔路徑;傳入時會額外加上 FileHandler。
        level: 日誌等級字串(DEBUG/INFO/WARNING/ERROR);
            未指定時讀取環境變數 LOG_LEVEL,預設 INFO。

    Returns:
        已設定完成的 Logger 物件。
    """
    logger = logging.getLogger(name)

    # 已設定過則直接回傳,避免重複加 handler 造成日誌重複輸出
    if logger.handlers:
        return logger

    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logger.setLevel(log_level)

    formatter = logging.Formatter(fmt=_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)

    # === Console handler ===
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # === File handler(選用)===
    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 避免日誌往 root logger 傳遞造成重複輸出
    logger.propagate = False

    return logger


def get_logger(name: str = "stock_radar") -> Logger:
    """取得已設定的 logger;若尚未設定則自動建立。

    Args:
        name: Logger 名稱。

    Returns:
        Logger 物件。
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
