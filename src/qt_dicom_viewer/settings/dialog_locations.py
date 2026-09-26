"""Local chooser history, independent of workspace documents and display defaults."""
import json
import logging
from pathlib import Path
import weakref

from PySide6.QtCore import QIODevice, QSaveFile, QStandardPaths

_current = None
_KEYS = {"images", "workspace", "attachments", "export", "feedback"}


def current_locations():
    return _current() if _current else None


class DialogLocations:
    def __init__(self, path):
        self.path = Path(path) if path else None
        self._directories = {}
        if self.path and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._directories = {key: value for key, value in data.items()
                                         if key in _KEYS and isinstance(value, str)
                                         and "\0" not in value and Path(value).is_absolute()}
            except (OSError, ValueError):
                pass

    def activate(self):
        global _current
        _current = weakref.ref(self)

    def deactivate(self):
        global _current
        if current_locations() is self:
            _current = None

    def directory(self, key, fallback=""):
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        for value in (self._directories.get(key), fallback, documents, str(Path.home())):
            if not value:
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                continue
            # Deleted or disconnected subdirectories fall back to a usable ancestor.
            for folder in (candidate, *candidate.parents):
                if folder.is_dir() and folder != Path(folder.anchor):
                    return str(folder)
        return str(Path.home())

    def remember(self, key, path, *, directory=False):
        if key not in _KEYS or not path:
            return
        selected = Path(path).expanduser().absolute()
        folder = selected if directory else selected.parent
        if self._directories.get(key) == str(folder):
            return
        candidate = dict(self._directories, **{key: str(folder)})
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                file = QSaveFile(str(self.path))
                payload = json.dumps(candidate, ensure_ascii=False, indent=2).encode("utf-8")
                if not file.open(QIODevice.WriteOnly) or file.write(payload) != len(payload) or not file.commit():
                    raise OSError("Cannot save chooser history")
            except OSError:
                logging.getLogger(__name__).warning("Unable to persist file chooser location")
        self._directories = candidate


def location_key(caption):
    """Stable message IDs keep histories shared across application languages."""
    key = getattr(caption, "key", "")
    if key in {"feedback.chooseAttachments", "feedback.saveEmail"}:
        return "feedback"
    if key in {"text.0414", "text.0417"}:
        return "workspace"
    if key in {"seg.chooseFile", "text.0565"}:
        return "attachments"
    if key in {"text.0395", "results.chooseDirectory", "text.0457", "text.0461", "text.0564"}:
        return "export"
    return ""
