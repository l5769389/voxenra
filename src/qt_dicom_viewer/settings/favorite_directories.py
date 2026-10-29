"""Ordered, local directory bookmarks; reading never probes bookmarked volumes."""
import json
import os
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

MAX_FAVORITES = 32


def path_key(path):
    return os.path.normcase(os.path.normpath(path))


class FavoriteDirectoriesStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.items = []
        if self.path:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or data.get('version') != 1:
                    return
                entries = data.get('items', [])
                if not isinstance(entries, list):
                    return
                ids, paths = set(), set()
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    identifier, name, folder = (item.get(key) for key in ('id', 'name', 'path'))
                    if not all(isinstance(value, str) and value.strip() and '\0' not in value
                               for value in (identifier, name, folder)):
                        continue
                    if not Path(folder).is_absolute() or identifier in ids or path_key(folder) in paths:
                        continue
                    self.items.append(dict(id=identifier, name=name, path=folder))
                    ids.add(identifier)
                    paths.add(path_key(folder))
                    if len(self.items) == MAX_FAVORITES:
                        break
            except (OSError, ValueError):
                pass

    def save(self, items):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({'version': 1, 'items': items}, ensure_ascii=False, indent=2).encode('utf-8')
            file = QSaveFile(str(self.path))
            if not file.open(QIODevice.WriteOnly):
                raise OSError(file.errorString())
            if file.write(payload) != len(payload):
                file.cancelWriting()
                raise OSError(file.errorString())
            if not file.commit():
                raise OSError(file.errorString())
        self.items = [dict(item) for item in items]
