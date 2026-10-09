"""Bounded per-tab undo history of completed edits, never of render jobs."""
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer
from PySide6.QtGui import QKeySequence

from qt_dicom_viewer.core.workspace_state import dumps, loads
from qt_dicom_viewer.ui.workspace_snapshot import editable_state, edit_signature, apply_edits


class EditHistoryController(QObject):
    changed = Signal()

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self._undo, self._redo = [], []
        self._restoring = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.capture)
        self.reset()
        for view in tab.viewports_by_id.values():
            self.watch_view(view)
        voi = getattr(tab, "_voi_controller", None)
        if voi is not None:
            voi.editsChanged.connect(self.schedule)
        if hasattr(tab, "snapshotCommitted"):
            tab.snapshotCommitted.connect(self.schedule)

    def watch_view(self, view):
        for name, signal in (("_measure_controller", "measurementsChanged"),
                             ("_text_annotation_controller", "annotationsChanged")):
            owner = getattr(view, name, None)
            if owner is not None:
                getattr(owner, signal).connect(self.schedule)
        if hasattr(view, "maskChanged"):
            view.maskChanged.connect(self.schedule)

    @Property(bool, notify=changed)
    def canUndo(self):
        return bool(self._undo)

    @Property(str, constant=True)
    def undoShortcutText(self):
        return QKeySequence.keyBindings(QKeySequence.StandardKey.Undo)[0].toString(QKeySequence.SequenceFormat.NativeText)

    @Property(str, constant=True)
    def redoShortcutText(self):
        return QKeySequence.keyBindings(QKeySequence.StandardKey.Redo)[0].toString(QKeySequence.SequenceFormat.NativeText)

    @Property(bool, notify=changed)
    def canRedo(self):
        return bool(self._redo)

    def reset(self):
        self._timer.stop()
        self._undo.clear()
        self._redo.clear()
        state = editable_state(self.tab)
        self._current = dumps(state)
        self._signature = edit_signature(state)
        self.changed.emit()

    # Keep these receivers in the class metaobject. Dynamic per-instance slots
    # leave QML property caches referring to transient PySide metaobjects when
    # tabs/engines are destroyed and another history controller is exposed.
    @Slot()
    @Slot(object)
    def schedule(self, *args):
        if not self._restoring:
            self._timer.start()

    @Slot()
    def capture(self):
        self._timer.stop()
        if self._restoring or getattr(self.tab, "_registration_dragging", False):
            return
        state = editable_state(self.tab)
        signature = edit_signature(state)
        if signature == self._signature:
            return
        snapshot = dumps(state)
        self._undo.append(self._current)
        self._redo.clear()
        self._current, self._signature = snapshot, signature
        while len(self._undo) > 100 or sum(map(len, self._undo)) > 64 * 1024**2:
            self._undo.pop(0)
        self.changed.emit()

    def _apply(self, source, destination):
        self.capture()
        if not source:
            return
        before, target = self._current, source[-1]
        self._restoring = True
        try:
            state = loads(target)
            apply_edits(self.tab, state)
            source.pop()
            destination.append(before)
            self._current, self._signature = target, edit_signature(state)
        finally:
            self._restoring = False
            self._timer.stop()
            self.changed.emit()

    @Slot()
    def undo(self):
        if self._native_editor("undo"):
            return
        self._apply(self._undo, self._redo)

    @Slot()
    def redo(self):
        if self._native_editor("redo"):
            return
        self._apply(self._redo, self._undo)

    @staticmethod
    def _native_editor(action):
        from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QPlainTextEdit
        editor = QApplication.focusWidget()
        if isinstance(editor, (QLineEdit, QTextEdit, QPlainTextEdit)):
            getattr(editor, action)()
            return True
        return QApplication.activeModalWidget() is not None

    def dispose(self):
        self._restoring = True
        self._timer.stop()
        self._undo.clear()
        self._redo.clear()
