"""Shortcut preferences and focused recording; never installs OS-wide hotkeys."""
from PySide6.QtCore import QObject, Property, Signal, Slot, QEvent, Qt, QCoreApplication
from PySide6.QtGui import QKeySequence, QGuiApplication
from qt_dicom_viewer.settings.shortcuts import DEFAULT_BINDINGS, BINDINGS, MENU_LABELS, FIXED, menu_scopes

class ShortcutController(QObject):
    changed = Signal()
    recordingChanged = Signal()
    focusWindowChanged = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._recording = ''
        self._recording_window = None
        if isinstance(QCoreApplication.instance(), QGuiApplication):
            QGuiApplication.instance().focusWindowChanged.connect(self.focusWindowChanged)
        settings.sectionChanged.connect(self._settings_changed)

    def _settings_changed(self, section):
        if section == 'shortcuts': self.changed.emit()

    @Property('QVariantList', notify=changed)
    def bindings(self):
        values = dict(DEFAULT_BINDINGS, **self.settings.section('shortcuts')['bindings'])
        return [dict(action=action, labelId=label, menu=menu, menus=list(menu_scopes(menu)), menuLabelId=MENU_LABELS[menu],
                     listIndex=int(action.split('-')[1]) - 1 if menu == 'preset-lists' else -1,
                     sequence=values[action], display=QKeySequence(values[action]).toString(QKeySequence.NativeText))
                for action, (menu, _, label) in BINDINGS.items()]

    @Property('QVariantList', constant=True)
    def fixedBindings(self):
        return [dict(action=k, labelId=v[0], display=QKeySequence(v[1]).toString(QKeySequence.NativeText)) for k,v in FIXED.items()]

    @Slot(str, result=str)
    def fixedSequence(self, action): return FIXED[action][1]

    @Slot(str, result=str)
    def hint(self, action):
        if action in FIXED:
            return QKeySequence(FIXED[action][1]).toString(QKeySequence.NativeText)
        return next((b['display'] for b in self.bindings if b['action']==action), '')

    @Property(QObject, notify=focusWindowChanged)
    def focusWindow(self):
        return QGuiApplication.focusWindow()

    @Property(str, notify=recordingChanged)
    def recordingAction(self): return self._recording

    @Slot(str)
    def beginRecording(self, action):
        if action not in DEFAULT_BINDINGS: return
        self._recording_window = QGuiApplication.focusWindow()
        self._recording = action
        QCoreApplication.instance().installEventFilter(self)
        self.recordingChanged.emit()

    @Slot()
    def cancelRecording(self):
        QCoreApplication.instance().removeEventFilter(self)
        if self._recording:
            self._recording = ''
            self._recording_window = None
            self.recordingChanged.emit()

    @Slot(str, str, result=bool)
    def assign(self, action, sequence):
        if action not in DEFAULT_BINDINGS: return False
        raw = dict(self.settings.section('shortcuts')['bindings'], **{action:sequence})
        return self.settings.setValue('shortcuts', 'bindings', raw)

    def eventFilter(self, watched, event):
        # Qt can deliver a final event while the Python wrapper is being torn down.
        if not getattr(self, '_recording', ''): return False
        if event.type() in (QEvent.ApplicationDeactivate, QEvent.WindowDeactivate):
            self.cancelRecording()
            return False
        if event.type() in (QEvent.MouseButtonPress, QEvent.TouchBegin, QEvent.TabletPress):
            # End recording even on non-focusable blank space; let the original
            # click reach its control (including starting a different binding).
            self.cancelRecording()
            return False
        if QGuiApplication.focusWindow() != self._recording_window: return False
        if event.type() == QEvent.ShortcutOverride:
            event.accept()
            return True
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:
                self.cancelRecording()
            elif key not in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta) and not event.isAutoRepeat():
                value = QKeySequence(event.keyCombination()).toString(QKeySequence.PortableText)
                if self.assign(self._recording, value): self.cancelRecording()
            event.accept()
            return True
        return False

    @Slot(result=bool)
    def pointerIdle(self):
        return QGuiApplication.mouseButtons() == Qt.NoButton

    @Slot(str, QObject, result=str)
    def primaryToolFor(self, action, tools):
        """Resolve primary selection; its window decides how to present the tool."""
        if (tools is None or action not in BINDINGS or BINDINGS[action][0] or action == 'play'
                or not self.pointerIdle()):
            return ''
        entries = tools.tools
        target = 'ct-window' if action == 'window' and not any(t['toolType'] == 'window' for t in entries) else action
        return target if any(t['toolType'] == target and t.get('available', True) and t.get('enabled', True)
                             for t in entries) else ''

    @Slot(str, QObject, QObject, str, result=bool)
    def activate(self, action, tools, tab, visible_menu=None):
        if tools is None or tab is None or not self.pointerIdle(): return False
        if action not in BINDINGS:
            return False
        menu = BINDINGS[action][0]
        if menu and (tools.activePanel not in menu_scopes(menu)
                     or (visible_menu is not None and visible_menu != tools.activePanel)
                     or tab.playing):
            return False
        if action == 'view-reset':
            if tools.activeTool != tools.activePanel or not tools.canResetActiveTool:
                return False
            tools.resetActiveTool()
            return True
        if menu == 'scroll':
            view = tab.activeViewport
            if view is None or view.sliceIndex < 0:
                return False
            target = {'scroll-prev': view.sliceIndex - 1, 'scroll-next': view.sliceIndex + 1,
                      'scroll-first': 0, 'scroll-last': view.sliceCount - 1}[action]
            if not 0 <= target < view.sliceCount:
                return False
            view.setSliceIndex(target)
            return True
        if menu == 'zoom':
            view = tab.activeViewport
            if view is None or (getattr(view, 'loadState', '') != 'ready' and getattr(view, 'sliceCount', 0) <= 0):
                return False
            view.setZoom(int(action.removeprefix('zoom-')))
            return True
        if menu == 'measure':
            view = tab.activeViewport
            if not getattr(view, 'hasPhysicalSpacing', False) or getattr(view, 'viewportRole', '') == 'curved':
                return False
            tools.selectInteraction(action)
            return tools.activeInteraction == action
        if menu == 'segmentation':
            voi = getattr(tab, 'voiController', None)
            if voi is None:
                return False
            voi.setEditMode(action)
            return voi.editMode == action
        if menu == 'cpr-path':
            cpr = getattr(tab, 'cprController', None)
            if cpr is None or not cpr.referencesReady or cpr.sourceMismatch:
                return False
            if action == 'cpr-new':
                cpr.startPath()
                return cpr.drawing
            if action == 'cpr-edit':
                cpr.setPathEditing(True)
                return cpr.pathEditing and not cpr.drawing
            if not cpr.selectedPathId or cpr.drawing:
                return False
            if action in ('cpr-start', 'cpr-end'):
                if not cpr.intervalPositionReady or cpr.activeViewport.historicalPlane:
                    return False
                cpr.setParameter('rangeStart' if action == 'cpr-start' else 'rangeEnd', cpr.positionMm)
            elif action in ('cpr-prev', 'cpr-next'):
                cpr.stepPosition(-1 if action == 'cpr-prev' else 1)
            elif action == 'cpr-view':
                if cpr.pathEditing or cpr.finishing:
                    return False
                cpr.setReferenceBrowsing(cpr.resultView)
            return True
        if action == 'play':
            target = tab.playbackShortcutTool
            mode = 'phase' if tab.temporalPlayback and target == 'play' else 'slice'
            if not any(t['toolType'] == target and t.get('available', True) and t.get('enabled', True) for t in tools.tools):
                return False
            tab.togglePlaybackMode(mode)
            return True
        target = self.primaryToolFor(action, tools)
        if not target:
            return False
        tools.activateTool(target)
        return tools.activeTool == target
