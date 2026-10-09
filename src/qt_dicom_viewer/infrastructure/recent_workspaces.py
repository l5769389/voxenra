"""Small local history of successful workspace opens/saves, separate from documents."""
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path

from qt_dicom_viewer.core.workspace_state import atomic_write

logger = logging.getLogger(__name__)
LIMIT = 5


class RecentWorkspaces:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self._items = []
        if self.path is None:
            return
        try:
            if self.path.stat().st_size > 65536:
                return
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('items'), list):
                return
            seen = set()
            for item in data['items'][:100]:
                if not isinstance(item, dict):
                    continue
                name, stamp = item.get('path'), item.get('lastUsed')
                if not isinstance(name, str) or not name or '\x00' in name or not Path(name).is_absolute():
                    continue
                if not isinstance(stamp, str):
                    continue
                try:
                    datetime.fromisoformat(stamp)
                except ValueError:
                    continue
                name = os.path.abspath(name)
                key = os.path.normcase(name)
                if key in seen:
                    continue
                seen.add(key)
                self._items.append({'path': name, 'lastUsed': stamp})
                if len(self._items) == LIMIT:
                    break
        except (OSError, ValueError):
            pass

    @property
    def items(self):
        return [dict(item, name=Path(item['path']).stem,
                     date=datetime.fromisoformat(item['lastUsed']).astimezone().strftime('%Y-%m-%d'),
                     missing=not Path(item['path']).is_file()) for item in self._items]

    def remember(self, path):
        path = os.path.abspath(path)
        self._items = [item for item in self._items if os.path.normcase(item['path']) != os.path.normcase(path)]
        self._items.insert(0, {'path': path, 'lastUsed': datetime.now(timezone.utc).isoformat()})
        del self._items[LIMIT:]
        self._save()

    def remove(self, path):
        remaining = [item for item in self._items if item['path'] != path]
        if len(remaining) == len(self._items):
            return False
        self._items = remaining
        self._save()
        return True

    def clear(self):
        if self.path is not None:
            atomic_write(self.path, json.dumps({'version': 1, 'items': []}).encode('utf-8'))
        self._items = []

    def _save(self):
        if self.path is not None:
            try:
                atomic_write(self.path, json.dumps({'version': 1, 'items': self._items}, ensure_ascii=False).encode('utf-8'))
            except OSError:
                # History is optional; never turn a successful workspace save into a failure.
                logger.warning('Could not save recent workspace history', exc_info=True)
