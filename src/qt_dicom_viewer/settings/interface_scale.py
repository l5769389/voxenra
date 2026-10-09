"""Apply application-only Qt DPI scaling before QApplication is constructed."""
import json
import os
from pathlib import Path
from math import isfinite
from PySide6.QtCore import QStandardPaths


def apply_interface_scale(path=None, environ=None):
    env = os.environ if environ is None else environ
    path = Path(path) if path else Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)) / 'display-settings.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))['appearance']['interfaceScale']
        if type(value) is not int or value not in (100, 115, 130): value = 100
    except (OSError, ValueError, TypeError, KeyError):
        value = 100
    # A restart launched by the updater may inherit our already scaled environment.
    # Keep the original user/system override so repeated launches do not multiply it.
    original = env.setdefault('VOXENRA_BASE_QT_SCALE_FACTOR', env.get('QT_SCALE_FACTOR', ''))
    try:
        baseline = float(original or '1')
        if not isfinite(baseline) or baseline <= 0: baseline = 1
    except ValueError:
        baseline = 1
    if value != 100 or original:
        env['QT_SCALE_FACTOR'] = str(baseline * value / 100)
    else:
        env.pop('QT_SCALE_FACTOR', None)
    env['VOXENRA_APPLIED_UI_SCALE'] = str(value)
    return value
