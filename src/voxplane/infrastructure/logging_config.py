from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def configure_logging(debug: bool = False) -> Path:
    log_root = Path(
        QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation
        )
    )
    log_directory = log_root / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)

    log_path = log_directory / "voxplane.log"

    level = logging.DEBUG if debug else logging.INFO

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | %(levelname)-8s | "
            "%(threadName)s | %(name)s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [file_handler]
    # Windows 无控制台 EXE 中 stdout/stderr 可能为空，仍保留文件日志。
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=handlers,
        force=True,
    )

    return log_path
