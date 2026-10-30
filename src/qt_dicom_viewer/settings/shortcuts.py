"""Portable, single-stroke reading shortcuts. No global hotkeys are registered."""
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from qt_dicom_viewer.i18n import message as _msg

DEFAULT_BINDINGS = {'window': 'W', 'scroll': 'S', 'pan': 'P', 'zoom': 'Z',
                    'measure': 'M', 'paint': 'B', 'erase': 'E', 'play': 'Space',
                    'cpr-new': 'N', 'cpr-edit': 'R'}
ACTION_LABELS = {'window': 'text.0285', 'scroll': 'input.action.scroll', 'pan': 'input.action.pan',
                 'zoom': 'input.action.zoom', 'measure': 'text.0292', 'paint': 'seg.paint',
                 'erase': 'seg.erase', 'play': 'input.action.play',
                 'cpr-new': 'cpr.new', 'cpr-edit': 'cpr.edit'}
FIXED = {'reopenClosedTab': ('workspace.reopenClosed', 'Ctrl+Shift+T'), 'newWorkspace': ('workspace.new.action', 'Ctrl+N'), 'open': ('input.action.open', 'Ctrl+O'), 'save': ('input.action.save', 'Ctrl+S'),
         'saveAs': ('input.action.saveAs', 'Ctrl+Shift+S'), 'openWorkspace': ('input.action.openWorkspace', 'Ctrl+Shift+O'),
         'undo': ('seg.undo', 'Ctrl+Z'), 'redo': ('seg.redo', 'Ctrl+Shift+Z' if sys.platform == 'darwin' else 'Ctrl+Y'),
         'copy': ('input.action.copy', 'Ctrl+C'), 'paste': ('input.action.paste', 'Ctrl+V'),
         'delete': ('input.action.delete', 'Delete'), 'cancel': ('input.action.cancel', 'Esc'),
         'finish': ('input.action.finish', 'Return'), 'close': ('input.action.close', 'Ctrl+W'),
         'compare': ('input.action.compare', 'Ctrl+D'),
         'maximizeViewport': ('reading.maximizeViewport', 'F12'),
         'nextTab': ('input.action.nextTab', 'Meta+Tab' if sys.platform == 'darwin' else 'Ctrl+Tab'),
         'previousTab': ('input.action.previousTab', 'Meta+Shift+Tab' if sys.platform == 'darwin' else 'Ctrl+Shift+Tab'),
         'fullscreen': ('input.action.fullscreen', 'Ctrl+Meta+F' if sys.platform == 'darwin' else 'F11')}

def canonical(value):
    return QKeySequence(value, QKeySequence.PortableText).toString(QKeySequence.PortableText)


def validate_bindings(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_BINDINGS):
        raise ValueError(_msg('input.invalidShortcut'))
    result = dict(DEFAULT_BINDINGS, **raw)
    # Older settings may already use these letters for another action. Preserve
    # that binding instead of resetting the user's shortcut section on upgrade.
    for action in ('cpr-new', 'cpr-edit'):
        if action not in raw and any(canonical(value) == canonical(result[action])
                                     for value in raw.values() if isinstance(value, str)):
            result[action] = ''
    reserved = {canonical(v[1]) for v in FIXED.values()} | {canonical(v) for v in (
        'Ctrl+A', 'Ctrl+X', 'Ctrl+Q', 'Ctrl+H', 'Ctrl+M', 'Ctrl+N', 'Ctrl+F', 'Ctrl+P',
        'Ctrl+Shift+Z', 'Ctrl+Y', 'Ctrl+,', 'Ctrl+Space', 'Ctrl+Shift+3', 'Ctrl+Shift+4', 'Ctrl+Shift+5', 'F1', 'F11', 'F12')}
    used = {}
    for action, value in result.items():
        if not isinstance(value, str) or len(value) > 50:
            raise ValueError(_msg('input.invalidShortcut'))
        if not value.strip():
            result[action] = ''
            continue
        seq = QKeySequence(value, QKeySequence.PortableText)
        if seq.count() != 1:
            raise ValueError(_msg('input.singleShortcut'))
        combination = seq[0]
        key, modifiers = combination.key(), combination.keyboardModifiers()
        # Exclude text/navigation controls, IME/system modifiers and OS app switching.
        allowed_key = Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_F2 <= key <= Qt.Key_F10 or key == Qt.Key_Space
        if (not allowed_key or modifiers & (Qt.AltModifier | Qt.MetaModifier | Qt.KeypadModifier)
                or canonical(value) in reserved):
            raise ValueError(_msg('input.reservedShortcut'))
        value = seq.toString(QKeySequence.PortableText)
        if value in used:
            raise ValueError(_msg('input.shortcutConflict', value1=_msg(ACTION_LABELS[used[value]])))
        result[action] = value
        used[value] = action
    return result
