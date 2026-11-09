"""Portable, single-stroke reading shortcuts. No global hotkeys are registered."""
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from qt_dicom_viewer.i18n import message as _msg

# An empty menu denotes a general reading action. The active menu owns a
# shared key while open; the same key becomes available again on exit.
BINDINGS = {
    'window': ('', 'W', 'text.0285'), 'scroll': ('', 'S', 'input.action.scroll'),
    'pan': ('', 'P', 'input.action.pan'), 'zoom': ('', 'Z', 'input.action.zoom'),
    'measure': ('', 'M', 'text.0292'), 'play': ('', 'Space', 'input.action.play'),
    'pseudocolor': ('', 'C', 'text.0309'), 'mpr-layout': ('', 'G', 'layout.title'),
    'annotate': ('', 'A', 'text.0307'), 'export': ('', 'E', 'text.0315'),
    'reset': ('', 'Q', 'tools.resetAll'),
    'view-reset': ('view-tools', 'R', 'input.resetCurrentViewTool'),
    'scroll-prev': ('scroll', 'J', 'input.previousSlice'), 'scroll-next': ('scroll', 'K', 'input.nextSlice'),
    'scroll-first': ('scroll', 'H', 'text.1027'), 'scroll-last': ('scroll', 'L', 'text.1028'),
    **{f'list-{i}': ('preset-lists', str(i), f'input.listSlot{i}') for i in range(1, 10)},
    **{f'zoom-{factor}': ('zoom', str(factor % 10), f'input.zoom{factor}') for factor in range(1, 11)},
    'measure:length': ('measure', 'L', 'text.0321'), 'measure:angle': ('measure', 'A', 'text.0322'),
    'measure:rect': ('measure', 'R', 'text.0323'), 'measure:ellipse': ('measure', 'E', 'text.0324'),
    'measure:curve': ('measure', 'V', 'measurement.curve'), 'measure:freehand': ('measure', 'F', 'measurement.freehand'),
    'annotate:arrow': ('annotate', 'A', 'text.0377'), 'annotate:text': ('annotate', 'T', 'text.0378'),
    'paint': ('segmentation', 'B', 'seg.paint'), 'erase': ('segmentation', 'E', 'seg.erase'),
    'cpr-new': ('cpr-path', 'N', 'cpr.new'), 'cpr-edit': ('cpr-path', 'R', 'cpr.edit'),
    'cpr-start': ('cpr-path', 'S', 'cpr.markStart'), 'cpr-end': ('cpr-path', 'E', 'cpr.markEnd'),
    'cpr-prev': ('cpr-path', 'J', 'cpr.previousSample'), 'cpr-next': ('cpr-path', 'K', 'cpr.nextSample'),
    'cpr-view': ('cpr-path', 'V', 'cpr.toggleViews'),
    'open-view-2d': ('', 'D', 'text.0698'),
    'open-view-mpr': ('', 'X', 'text.0700'),
    'open-view-3d': ('', 'T', 'text.0701'),
    'open-view-cpr': ('', 'Y', 'cpr.title'),
    'open-view-montage': ('', 'O', 'text.0699'),
    'open-view-4d': ('', 'U', 'text.0702'),
    'open-view-tag': ('', 'I', 'text.0703'),
}
DEFAULT_BINDINGS = {action: sequence for action, (_, sequence, _) in BINDINGS.items()}
ACTION_LABELS = {action: label for action, (_, _, label) in BINDINGS.items()}
MENU_LABELS = {'': 'input.generalReading', 'view-tools': 'input.viewToolMenus', 'scroll': 'text.0287',
               'preset-lists': 'input.presetLists', 'zoom': 'input.action.zoom',
               'measure': 'text.0292', 'annotate': 'text.0307', 'segmentation': 'seg.manage', 'cpr-path': 'cpr.title'}
RETIRED_ACTIONS = {'cpr-guides', 'cpr-details', 'cpr-advanced', 'cpr-interval'}

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


def menu_scopes(group: str) -> tuple[str, ...]:
    """Menus that share this setting; never include tools whose reset deletes objects."""
    if group == 'preset-lists':
        return ('window', 'ct-window', 'pseudocolor', 'mpr-layout')
    if group == 'view-tools':
        return ('window', 'ct-window', 'pet-window', 'scroll', 'pan', 'zoom', 'rotate',
                'mpr-rotate-3d', 'volume-rotate', 'volume-direction', 'volume-preset', 'mip',
                'pseudocolor', 'viewport-settings', 'registration', 'fusion-blend', 'mpr-layout')
    return (group,)


def canonical(value):
    return QKeySequence(value, QKeySequence.PortableText).toString(QKeySequence.PortableText)


def _default_in_use(action, bindings):
    menu, sequence, _ = BINDINGS[action]
    for other, value in bindings.items():
        if other == action or other not in BINDINGS or not isinstance(value, str) or canonical(value) != sequence:
            continue
        other_menu = BINDINGS[other][0]
        if not set(menu_scopes(other_menu)).isdisjoint(menu_scopes(menu)):
            return True
        if not other_menu and DEFAULT_BINDINGS[other] != sequence:
            return True
    return False


def migrate_scroll_defaults(bindings):
    for action, previous in (('scroll-first', 'Home'), ('scroll-last', 'End')):
        if bindings.get(action) == previous and not _default_in_use(action, bindings):
            bindings[action] = DEFAULT_BINDINGS[action]


def validate_bindings(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_BINDINGS):
        raise ValueError(_msg('input.invalidShortcut'))
    result = dict(DEFAULT_BINDINGS, **raw)
    # Older settings may already use these letters for another action. Preserve
    # that binding instead of resetting the user's shortcut section on upgrade.
    for action in BINDINGS:
        if action not in raw and _default_in_use(action, raw):
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
        allowed_key = (Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9
                       or Qt.Key_F2 <= key <= Qt.Key_F10 or key in (Qt.Key_Space, Qt.Key_Home, Qt.Key_End))
        if (not allowed_key or modifiers & (Qt.AltModifier | Qt.MetaModifier | Qt.KeypadModifier)
                or canonical(value) in reserved):
            raise ValueError(_msg('input.reservedShortcut'))
        value = seq.toString(QKeySequence.PortableText)
        for menu in menu_scopes(BINDINGS[action][0]):
            scoped_key = (menu, value)
            if scoped_key in used:
                raise ValueError(_msg('input.shortcutConflict', value1=_msg(ACTION_LABELS[used[scoped_key]])))
            used[scoped_key] = action
        result[action] = value
    return result
