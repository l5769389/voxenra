"""Bounded local import history; reading it never probes saved source volumes."""
import json
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

from .favorite_directories import path_key

MAX_RECENT_PATHS = 10


def _valid_path(value):
    return isinstance(value, str) and bool(value) and '\0' not in value and Path(value).is_absolute()


class RecentImagePathsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.items = []
        self.directory = ''
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('version') != 1:
                return
            entries = data.get('items', [])
            if not isinstance(entries, list):
                return
            seen = set()
            for value in entries:
                if _valid_path(value) and path_key(value) not in seen:
                    self.items.append(value)
                    seen.add(path_key(value))
                    if len(self.items) == MAX_RECENT_PATHS:
                        break
            directory = data.get('directory', '')
            if _valid_path(directory):
                self.directory = directory
        except (OSError, ValueError):
            pass

    def save(self, items, directory):
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({'version': 1, 'items': items, 'directory': directory},
                                 ensure_ascii=False, indent=2).encode('utf-8')
            output = QSaveFile(str(self.path))
            if not output.open(QIODevice.WriteOnly):
                raise OSError(output.errorString())
            if output.write(payload) != len(payload):
                output.cancelWriting()
                raise OSError(output.errorString())
            if not output.commit():
                raise OSError(output.errorString())
        self.items = list(items)
        self.directory = directory
