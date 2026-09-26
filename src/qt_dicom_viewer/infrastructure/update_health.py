"""A local, one-use acknowledgement after the replacement UI has started."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import sys

CHECK_ARGUMENT = "--voxenra-update-check"
STARTUP_STABILITY_MS = 5000


def acknowledge_startup(manifest, *, executable=None, version=None):
    from qt_dicom_viewer import __version__
    from PySide6.QtCore import QSaveFile, QIODevice
    manifest = Path(manifest)
    try:
        if manifest.name != "health.json" or manifest.stat().st_size > 16384:
            return False
        record = json.loads(manifest.read_text(encoding="utf-8"))
        token = record["token"]
        if (not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token)
                or record["version"] != (version or __version__)
                or Path(record["executable"]).resolve() != Path(executable or sys.executable).resolve()):
            return False
        target = QSaveFile(str(manifest.with_name("ready")))
        payload = token.encode("ascii")
        return (target.open(QIODevice.WriteOnly) and target.write(payload) == len(payload)
                and target.commit())
    except (OSError, ValueError, TypeError, KeyError):
        logging.getLogger(__name__).warning("Update startup confirmation was rejected", exc_info=True)
        return False


def arm_startup_confirmation(window, args=None):
    """Only a loaded, visible window with a running event loop can acknowledge startup."""
    from PySide6.QtCore import QTimer
    args = sys.argv if args is None else args
    if args.count(CHECK_ARGUMENT) != 1:
        return
    index = args.index(CHECK_ARGUMENT)
    if index + 1 >= len(args):
        return
    manifest = args[index + 1]
    def confirm():
        if window.isVisible():
            acknowledge_startup(manifest)
    QTimer.singleShot(STARTUP_STABILITY_MS, window, confirm)
