"""Portable window presets; files contain data only and are loaded atomically."""
from copy import deepcopy
import json
from math import isfinite
import re

from PySide6.QtCore import QSaveFile, QIODevice
from qt_dicom_viewer.preset import CT_WINDOW_PRESETS

BUILTIN_IDS = frozenset(p.preset_id for p in CT_WINDOW_PRESETS)
MAX_BYTES = 1024 * 1024
CATALOG_VERSION = 2
ORIGINAL_IDS = frozenset(('ct-brain', 'ct-lung', 'ct-bone', 'ct-soft-tissue'))


def upgraded_defaults(entries, payload):
    """Append newly shipped presets once, preserving user values/order/deletions."""
    version = json.loads(payload.decode('utf-8-sig')).get('catalogVersion', 1)
    if type(version) is not int or version != 1:
        return None
    identifiers = {p['presetId'] for p in entries}
    # An empty or wholly custom file is intentional; do not populate it.
    if not identifiers & ORIGINAL_IDS:
        return None
    additions = [dict(presetId=p.preset_id, label='', width=p.width, center=p.center, enabled=True)
                 for p in CT_WINDOW_PRESETS if p.preset_id not in ORIGINAL_IDS | identifiers]
    if len(entries) + len(additions) > 100:
        return None
    return deepcopy(entries) + additions


def from_legacy(settings):
    return [dict(presetId=p.preset_id, label='', width=p.width, center=p.center,
                 enabled=p.preset_id not in settings['hidden']) for p in CT_WINDOW_PRESETS] + deepcopy(settings['custom'])


def legacy_view(entries):
    enabled = {p['presetId'] for p in entries if p['enabled']}
    return dict(hidden=[p.preset_id for p in CT_WINDOW_PRESETS if p.preset_id not in enabled],
                custom=[deepcopy(p) for p in entries if p['presetId'] not in BUILTIN_IDS])


def validate_document(document):
    if not isinstance(document, dict) or type(document.get('schemaVersion')) is not int or document.get('schemaVersion') != 1:
        raise ValueError('Expected schemaVersion: 1')
    entries = document.get('presets')
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError('presets must be a list of at most 100 entries')
    identifiers, names, result = set(), set(), []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f'presets[{index}]: expected an object')
        identifier, label = entry.get('presetId'), entry.get('label', '')
        if (not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', identifier)
                or identifier in identifiers):
            raise ValueError(f'presets[{index}]: invalid or duplicate presetId')
        if not isinstance(label, str) or len(label.strip()) > 40 or (not label.strip() and identifier not in BUILTIN_IDS):
            raise ValueError(f'{identifier}: label must contain 1–40 characters (empty only for default names)')
        label = label.strip()
        if label and label.casefold() in names:
            raise ValueError(f'{identifier}: duplicate label')
        width, center, enabled = entry.get('width'), entry.get('center'), entry.get('enabled', True)
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in (width, center))
                or not 1 <= width <= 1000000 or not -1000000 <= center <= 1000000):
            raise ValueError(f'{identifier}: width must be 1…1000000; center must be −1000000…1000000')
        if not isinstance(enabled, bool):
            raise ValueError(f'{identifier}: enabled must be true or false')
        identifiers.add(identifier)
        if label:
            names.add(label.casefold())
        result.append(dict(presetId=identifier, label=label, width=float(width), center=float(center), enabled=enabled))
    return result


def read_document(path):
    with path.open('rb') as stream:
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError('File exceeds 1 MiB')
    return validate_document(json.loads(payload.decode('utf-8-sig'))), payload


def write_document(path, entries):
    payload = (json.dumps(dict(schemaVersion=1, catalogVersion=CATALOG_VERSION, presets=entries), ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    target = QSaveFile(str(path))
    if not target.open(QIODevice.WriteOnly) or target.write(payload) != len(payload) or not target.commit():
        raise OSError('Cannot save window presets')
    return payload
