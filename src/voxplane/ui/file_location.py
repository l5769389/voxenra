"""Open export folders, or select an exported file in the system file manager."""
from pathlib import Path
import sys

from PySide6.QtCore import QDir, QProcess, QUrl
from PySide6.QtGui import QDesktopServices


def reveal_path(path: str) -> bool:
    if not path:
        return False
    try:
        target = Path(path).resolve()
        if target.is_dir():
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        if not target.is_file():
            return False
        if sys.platform == "darwin":
            started, _ = QProcess.startDetached("/usr/bin/open", ["-R", str(target)])
            return started
        if sys.platform == "win32":
            started, _ = QProcess.startDetached("explorer.exe", ["/select,", QDir.toNativeSeparators(str(target))])
            return started
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))
    except (OSError, RuntimeError):
        return False
