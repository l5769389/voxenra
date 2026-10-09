"""Shortcut preferences and focused recording; never installs OS-wide hotkeys."""
from PySide6.QtCore import QObject, Property, Signal, Slot, QEvent, Qt, QCoreApplication
from PySide6.QtGui import QKeySequence, QGuiApplication
from qt_dicom_viewer.settings.shortcuts import DEFAULT_BINDINGS, ACTION_LABELS, FIXED

class ShortcutController(QObject):
    changed = Signal()
    recordingChanged = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._recording = ''
        self._recording_window = None
        settings.sectionChanged.connect(self._settings_changed)

    def _settings_changed(self, section):
        if section == 'shortcuts': self.changed.emit()

    @Property('QVariantList', notify=changed)
    def bindings(self):
        values = dict(DEFAULT_BINDINGS, **self.settings.section('shortcuts')['bindings'])
        return [dict(action=k, labelId=ACTION_LABELS[k], sequence=v,
                     display=QKeySequence(v).toString(QKeySequence.NativeText)) for k,v in values.items()]

    @Property('QVariantList', constant=True)
    def fixedBindings(self):
        return [dict(action=k, labelId=v[0], display=QKeySequence(v[1]).toString(QKeySequence.NativeText)) for k,v in FIXED.items()]

    @Slot(str, result=str)
    def fixedSequence(self, action): return FIXED[action][1]

    @Slot(str, result=str)
    def hint(self, action):
        return next((b['display'] for b in self.bindings if b['action']==action), '')

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

    @Slot(str, QObject, QObject, result=bool)
    def activate(self, action, tools, tab):
        if tools is None or tab is None or QGuiApplication.mouseButtons() != Qt.NoButton: return False
        target = 'segmentation' if action in ('paint','erase') else action
        if action == 'window' and not any(t['toolType']=='window' for t in tools.tools):
            target = 'ct-window'
        available = next((t for t in tools.tools if t['toolType']==target and t.get('available', True) and t.get('enabled', True)), None)
        if not available: return False
        # Repeated tool shortcuts select rather than collapse an already open panel.
        if tools.activeTool != target or action == 'play': tools.activateTool(target)
        if action in ('paint','erase'):
            controller = getattr(tab, 'voiController', None)
            if controller is None: return False
            controller.setEditMode(action)
        return True
