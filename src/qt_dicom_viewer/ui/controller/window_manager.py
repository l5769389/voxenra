"""Own window presentations without moving or rebuilding loaded tab controllers."""
import logging
import math
from contextlib import contextmanager
from importlib.resources import files

from PySide6.QtCore import Property, QObject, QPointF, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlComponent, qmlEngine
from shiboken6 import isValid

from .window_workspace_controller import WindowWorkspaceController

logger = logging.getLogger(__name__)


class WindowManager(QObject):
    windowsChanged = Signal()
    dragChanged = Signal()
    operationFailed = Signal(str)

    def __init__(self, app, registry):
        super().__init__(app)
        self.app, self.registry = app, registry
        self.sessions = {"main": WindowWorkspaceController(self, "main")}
        self.windows, self.bars = {}, {}
        self._window_geometry = {}
        self._serial = 0
        self._focused = self._opening = "main"
        self._component = None
        self._changing = 0
        self._closed = False
        self._retired = []
        self._transfers = {}
        self._press = None
        self._dragging = False
        self._point = QPointF()
        self._target = ""
        registry.tabsChanged.connect(self._sync_tabs)
        registry.showDocumentRequested.connect(self._show_document)
        registry._window_manager = self

    @Property(QObject, constant=True)
    def mainWorkspace(self):
        return self.sessions["main"]

    @Property(str, notify=windowsChanged)
    def focusedWindowId(self):
        return self._focused

    @Property(bool, notify=dragChanged)
    def dragging(self):
        return self._dragging

    @Property(str, notify=dragChanged)
    def dragSource(self):
        return self._press[0] if self._press else ""

    @Property(str, notify=dragChanged)
    def dragTabId(self):
        return self._press[1] if self._press else ""

    @Property(str, notify=dragChanged)
    def dragLabel(self):
        from qt_dicom_viewer.i18n.messages import localize
        tab = self.registry._tab_dict.get(self.dragTabId)
        return localize(self.registry.tab_presentation(tab)["tabLabel"]) if tab else ""

    @Property(float, notify=dragChanged)
    def dragX(self):
        return self._point.x()

    @Property(float, notify=dragChanged)
    def dragY(self):
        return self._point.y()

    @contextmanager
    def changing(self):
        self._changing += 1
        try:
            yield
        finally:
            self._changing -= 1

    def owner(self, tab_id):
        return next((session for session in self.sessions.values() if tab_id in session._ids), None)

    def ordered_tabs(self):
        return [self.registry._tab_dict[key] for session in self.sessions.values()
                for key in session._ids if key in self.registry._tab_dict]

    def _sync_tabs(self):
        if self._press and self.dragTabId not in self.registry._tab_dict:
            self.cancelDrag()
        for key in list(self._transfers):
            if key not in self.registry._tab_dict:
                self._transfers.pop(key)
        for session in list(self.sessions.values()):
            for key in list(session._ids):
                if key not in self.registry._tab_dict:
                    session._remove(key)
        target = self.sessions.get(self._opening, self.mainWorkspace)
        added = False
        for key in self.registry._tab_dict:
            if self.owner(key) is None:
                added = True
                target._ids.append(key)
                target.tabsChanged.emit()
        if added:
            # A new source may disambiguate an existing tab in another window.
            # Notify after ownership has settled, without rebuilding the target twice.
            for session in self.sessions.values():
                if session is not target:
                    session._i18n_tabs.emit()
        self.focusWindow(self._focused)
        if not self._changing:
            QTimer.singleShot(0, self._close_empty_windows)

    def _publish_order(self):
        self.registry._tab_dict = {tab.tab_config.tab_id: tab for tab in self.ordered_tabs()}
        self.registry.tabsChanged.emit()

    def open_in(self, session, function, *args):
        previous, self._opening = self._opening, session.windowId
        try:
            return function(*args)
        finally:
            self._opening = previous

    def activate_tab(self, tab_id, *, raise_window=True):
        session = self.owner(tab_id)
        if session is None:
            return
        previous = session.activeTabId
        session._select(tab_id)
        if previous != tab_id and previous in self._transfers:
            # Switching away can cancel the destination Loader's incubation;
            # an inactive page needs no native presentation until it is selected.
            self.pageReady(session.windowId, previous, True)
        self.focusWindow(session.windowId)
        window = self.windows.get(session.windowId)
        if raise_window and window and isValid(window):
            if window.visibility() == QWindow.Minimized:
                window.showNormal()
            elif not window.isVisible():
                # Re-showing a visible QQuickWindow can reset its window state.
                window.show()
            window.raise_()
            window.requestActivate()

    @Slot(str)
    def focusWindow(self, window_id):
        session = self.sessions.get(window_id)
        if session:
            changed = self._focused != window_id
            self._focused = window_id
            self.registry._activate_tab(session.activeTabId, pause_previous=False)
            if changed:
                self.windowsChanged.emit()

    @Slot(str, QObject)
    def registerWindow(self, window_id, window):
        if window_id in self.sessions and isinstance(window, QWindow):
            self.windows[window_id] = window
            from qt_dicom_viewer.ui.window_geometry import WindowGeometry
            self._window_geometry[window_id] = WindowGeometry(window)
            self.windowsChanged.emit()

    @Slot(str, QObject)
    def registerTabBar(self, window_id, bar):
        if window_id in self.sessions:
            self.bars[window_id] = bar

    @Slot()
    def showMainWindow(self):
        window = self.windows.get("main")
        if window and isValid(window):
            if window.visibility() == QWindow.Minimized:
                window.showNormal()
            elif not window.isVisible():
                # Re-showing a visible QQuickWindow can reset its window state.
                window.show()
            window.raise_()
            window.requestActivate()

    def _show_document(self):
        self.sessions.get(self._focused, self.mainWorkspace).showDocumentRequested.emit()

    def _visible_windows(self):
        return [key for key, window in self.windows.items() if isValid(window) and window.isVisible()]

    def _retire(self, window_id):
        if window_id == "main":
            return
        self.bars.pop(window_id, None)
        window = self.windows.pop(window_id, None)
        geometry = self._window_geometry.pop(window_id, None)
        if geometry:
            geometry.shutdown()
        session = self.sessions.pop(window_id, None)
        if window and isValid(window):
            window.hide()
            window.deleteLater()
        if session:
            # A report may still be writing its immutable snapshot after its window closes.
            self._retired.append(session)
            self._collect_retired()
        if self._focused == window_id:
            self.focusWindow(next(iter(self._visible_windows()), "main"))
        self.windowsChanged.emit()

    def _collect_retired(self):
        for session in list(self._retired):
            export = session._export
            if export and (export.busy or export.measurementReport.busy or export.dicomResults.busy):
                continue
            session.shutdown()
            session.deleteLater()
            self._retired.remove(session)
        if self._retired and not self._closed:
            QTimer.singleShot(200, self._collect_retired)

    def _close_empty_windows(self):
        if self._closed or self._changing:
            return
        for key, session in list(self.sessions.items()):
            if key != "main" and not session._ids and not any(previous[0] == key for previous in self._transfers.values()):
                if self._visible_windows() == [key]:
                    self.showMainWindow()
                self._retire(key)

    @Slot(str, result=bool)
    def requestCloseWindow(self, window_id):
        if self._closed:
            return True
        session = self.sessions.get(window_id)
        if session is None:
            return True
        if len(self._visible_windows()) <= 1:
            # Keep all tabs alive for the save/cancel decision and the final save snapshot.
            return self.app.workspaceDocumentController.requestClose()
        self.cancelDrag()
        with self.changing():
            if not self.registry.close_tabs(list(session._ids)):
                return False
        if window_id != "main":
            QTimer.singleShot(0, lambda: self._retire(window_id))
        self.windowsChanged.emit()
        return True

    def close_tabs(self, session, ids):
        if not ids:
            return
        if session.detached and set(ids) == set(session._ids) and self._visible_windows() == [session.windowId]:
            window = self.windows[session.windowId]
            window.close()
            return
        with self.changing():
            if not self.registry.close_tabs(ids):
                return False
        self._close_empty_windows()
        return True

    @Slot(str, result=bool)
    def canMoveTab(self, tab_id):
        owner = self.owner(tab_id)
        document = getattr(self.app, "workspaceDocumentController", None)
        return bool(owner and tab_id not in self._transfers and not (document and document.restoring)
                    and not (owner._export and owner._export._png_context is not None))

    @Slot(str, str, int, result=bool)
    def moveTab(self, tab_id, window_id, index):
        source, target = self.owner(tab_id), self.sessions.get(window_id)
        if not source or not target or not self.canMoveTab(tab_id):
            return False
        old_index, old_active = source._ids.index(tab_id), source.activeTabId
        index = max(0, min(index, len(target._ids)))
        if source is target:
            if index > old_index:
                index -= 1
            if index == old_index:
                return True
            source._ids.pop(old_index)
            source._ids.insert(index, tab_id)
            source.tabsChanged.emit()
        else:
            self._transfers[tab_id] = (source.windowId, old_index, old_active)
            with self.changing():
                # Source Loader releases its QWindow before the destination can attach it.
                source._remove(tab_id)
                target._ids.insert(index, tab_id)
                target.tabsChanged.emit()
                self.activate_tab(tab_id)
        self._publish_order()
        return True

    @Slot(str, str, bool)
    def pageReady(self, window_id, tab_id, success):
        if self.owner(tab_id) is not self.sessions.get(window_id):
            return
        previous = self._transfers.pop(tab_id, None)
        if previous is None:
            return
        if not success:
            source_id, index, active = previous
            source, target = self.sessions.get(source_id), self.sessions.get(window_id)
            if source and target:
                with self.changing():
                    target._remove(tab_id)
                    source._ids.insert(index, tab_id)
                    source.tabsChanged.emit()
                    self.activate_tab(active if active in source._ids else tab_id)
                self._publish_order()
            from qt_dicom_viewer.i18n import message
            self.operationFailed.emit(str(message("tabs.moveFailed")))
        self._close_empty_windows()

    @Slot(str, result=bool)
    def detachTab(self, tab_id):
        source = self.owner(tab_id)
        window = self.windows.get(source.windowId) if source else None
        point = QPointF(window.x() + 48, window.y() + 48) if window else QPointF(80, 80)
        return self.detach_at(tab_id, point)

    def detach_at(self, tab_id, point):
        main = self.windows.get("main")
        if not main or not self.canMoveTab(tab_id):
            return False
        engine = qmlEngine(main)
        if engine is None:
            return False
        if self._component is None:
            url = QUrl.fromLocalFile(str(files("qt_dicom_viewer").joinpath("qml/Main.qml")))
            self._component = QQmlComponent(engine, url, self)
        self._serial += 1
        key = f"window-{self._serial}"
        session = WindowWorkspaceController(self, key)
        self.sessions[key] = session
        window = self._component.createWithInitialProperties({"windowWorkspace": session, "detached": True})
        if window is None:
            logger.error("Could not create detached window: %s", self._component.errors())
            self._retire(key)
            self.operationFailed.emit("tabs.moveFailed")
            return False
        # QQmlApplicationEngine owns load() roots, but not windows created by
        # QQmlComponent. Tie QObject lifetime to the engine (not a visual parent)
        # so no retired window can retain QML contexts after engine destruction.
        QObject.setParent(window, engine)
        self.windows[key] = window
        screen = (QGuiApplication.screenAt(point.toPoint())
                  or QGuiApplication.screenAt(main.position()) or QGuiApplication.primaryScreen())
        window.setScreen(screen)
        self._window_geometry[key].initialize(point.toPoint())
        if not self.moveTab(tab_id, key, 0):
            self._retire(key)
            return False
        window.show()
        window.raise_()
        window.requestActivate()
        return True

    @Slot(str)
    def moveToMain(self, tab_id):
        self.showMainWindow()
        self.moveTab(tab_id, "main", len(self.mainWorkspace._ids))

    def restore_to_main(self):
        self.cancelDrag()
        with self.changing():
            for session in self.sessions.values():
                session._ids = []
                session._mru = []
                session._select("")
                session.tabsChanged.emit()
            self.mainWorkspace._ids = list(self.registry._tab_dict)
            self.mainWorkspace.tabsChanged.emit()
        self._opening = self._focused = "main"
        self._transfers.clear()
        self.showMainWindow()
        self._close_empty_windows()

    @Slot(str, str, float, float)
    def beginDrag(self, window_id, tab_id, x, y):
        self.cancelDrag()
        source = self.owner(tab_id)
        if source and source.windowId == window_id and self.canMoveTab(tab_id):
            self._press = (window_id, tab_id, QPointF(x, y))
            self._point = QPointF(x, y)

    @Slot(float, float)
    def updateDrag(self, x, y):
        if self._press is None or not all(math.isfinite(v) for v in (x, y)):
            return
        self._point = QPointF(x, y)
        if not self._dragging:
            if (self._point - self._press[2]).manhattanLength() < QGuiApplication.styleHints().startDragDistance():
                return
            self._dragging = True
            self.dragChanged.emit()  # Expose the empty main window's drop zone before hit testing.
        self._target = ""
        for bar in self.bars.values():
            if isValid(bar):
                bar.setProperty("dropPosition", -1.)
        top = QGuiApplication.topLevelAt(self._point.toPoint())
        candidates = ([key for key, window in self.windows.items() if window is top]
                      if top in self.windows.values() else list(reversed(self.windows)))
        for key in candidates:
            window, bar = self.windows.get(key), self.bars.get(key)
            if window and isValid(window) and window.isVisible() and bar and isValid(bar) and bar.isVisible():
                local = bar.mapFromGlobal(self._point)
                if 0 <= local.x() <= bar.width() and 0 <= local.y() <= bar.height():
                    self._target = key
                    bar.setProperty("dropPosition", local.x())
                    break
        self.dragChanged.emit()

    @Slot(float, float, result=bool)
    def finishDrag(self, x, y):
        if self._press is None:
            return False
        self.updateDrag(x, y)
        moved, tab_id, target, point = self._dragging, self.dragTabId, self._target, QPointF(self._point)
        index = int(self.bars[target].property("dropIndex")) if target else 0
        outside = not any(isValid(window) and window.isVisible() and window.frameGeometry().contains(point.toPoint())
                          for window in self.windows.values())
        self.cancelDrag()
        if moved:
            if target:
                self.moveTab(tab_id, target, index)
            elif outside:
                self.detach_at(tab_id, point)
        return moved

    @Slot()
    def cancelDrag(self):
        self._press, self._dragging, self._target = None, False, ""
        for bar in self.bars.values():
            if isValid(bar):
                bar.setProperty("dropPosition", -1.)
        self.dragChanged.emit()

    def shutdown(self):
        self._closed = True
        self.cancelDrag()
        for geometry in self._window_geometry.values():
            geometry.shutdown()
        self._window_geometry.clear()
        for session in [*self.sessions.values(), *self._retired]:
            session.shutdown()
        for key, window in list(self.windows.items()):
            if key != "main" and isValid(window):
                window.hide()
                window.deleteLater()
