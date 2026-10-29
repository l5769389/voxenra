"""A window's ordered tab selection; tab objects belong to the shared registry."""
from PySide6.QtCore import QObject, Property, Signal, Slot

from qt_dicom_viewer.i18n.qt import translated_property


class WindowWorkspaceController(QObject):
    tabsChanged = Signal()
    activeTabChanged = Signal()
    activeViewportChanged = Signal()
    loadingStatesChanged = Signal()
    showDocumentRequested = Signal()
    _i18n_tabs = Signal()

    def __init__(self, manager, window_id):
        super().__init__(manager)
        self.manager, self.registry = manager, manager.registry
        self._window_id = window_id
        self._ids, self._mru, self._active = [], [], ""
        self._export = None
        self.registry.tabPresentationChanged.connect(self._presentation_changed)
        self.registry.loadingStatesChanged.connect(self._loading_changed)
        self.registry.activeViewportChanged.connect(self._viewport_changed)

    @Slot()
    def _presentation_changed(self):
        self._i18n_tabs.emit()

    @Slot()
    def _loading_changed(self):
        self.loadingStatesChanged.emit()

    @Slot()
    def _viewport_changed(self):
        self.activeViewportChanged.emit()

    @Property(str, constant=True)
    def windowId(self):
        return self._window_id

    @Property(bool, constant=True)
    def detached(self):
        return self._window_id != "main"

    @Property(QObject, constant=True)
    def windowManager(self):
        return self.manager

    @Property(QObject, constant=True)
    def exportController(self):
        if self._export is None:
            from .export_controller import ExportController
            self._export = ExportController(self, self.registry._series_catalog, self)
        return self._export

    @translated_property('QVariantList', notify=_i18n_tabs, notify_name='_i18n_tabs', source_notify='tabsChanged')
    def tabs(self):
        return [self.registry.tab_presentation(tab)
                for key in self._ids if (tab := self.registry._tab_dict.get(key)) is not None]

    @Property(str, notify=activeTabChanged)
    def activeTabId(self):
        return self._active

    @Property(QObject, notify=activeTabChanged)
    def activeTab(self):
        return self.registry._tab_dict.get(self._active)

    @Property(str, notify=activeTabChanged)
    def activeTabType(self):
        return self.activeTab.tab_config.tab_type.value if self.activeTab else ""

    @Property(QObject, notify=activeViewportChanged)
    def activeViewport(self):
        return self.activeTab.activeViewport if self.activeTab else None

    @Property('QVariantList', notify=activeTabChanged)
    def currentTabAllViewports(self):
        return list(self.activeTab.viewports_by_id.values()) if self.activeTab else []

    @Property(QObject, notify=activeTabChanged)
    def activeLoadState(self):
        return self.registry._load_states.get(self._active)

    @Property('QVariantMap', notify=loadingStatesChanged)
    def loadingStates(self):
        return {key: value for key, value in self.registry.loadingStates.items() if key in self._ids}

    @Property(QObject, notify=tabsChanged)
    def manualController(self):
        return self.registry.manualController

    def all_tabs(self):
        return self.manager.ordered_tabs()

    @Slot(result=str)
    def toolbarProfileForEditing(self):
        """Use this window's latest image, even while a utility page is active."""
        for key in self._mru:
            tab = self.registry._tab_dict.get(key) if key in self._ids else None
            if tab is None or tab.tab_config.tab_type.value not in (
                    '2d', 'mpr', 'cpr', '3d', 'montage', '4d', 'compare2d', 'comparempr', 'petctfusion'):
                continue
            tool = getattr(tab, 'activeToolController', None) or tab.toolController
            return tool.toolbarProfile
        return ''

    def _select(self, tab_id):
        if tab_id == self._active:
            return
        if self.activeTab:
            self.activeTab.pausePlayback()
        self._active = tab_id
        if tab_id:
            self._mru = [tab_id] + [key for key in self._mru if key != tab_id]
        self.activeTabChanged.emit()
        self.activeViewportChanged.emit()

    def _remove(self, tab_id):
        if tab_id not in self._ids:
            return
        self._ids.remove(tab_id)
        self._mru = [key for key in self._mru if key != tab_id]
        if self._active == tab_id:
            self._select(next((key for key in self._mru if key in self._ids), self._ids[0] if self._ids else ""))
        self.tabsChanged.emit()

    @Slot(str)
    def activateTabId(self, tab_id):
        self.manager.activate_tab(tab_id)

    @Slot(int)
    def cycleTab(self, direction):
        if self._ids:
            index = self._ids.index(self._active) if self._active in self._ids else 0
            self.activateTabId(self._ids[(index + direction) % len(self._ids)])

    @Slot(str)
    def closeTab(self, tab_id):
        if tab_id in self._ids:
            self.manager.close_tabs(self, [tab_id])

    @Slot(str, str)
    def closeTabs(self, tab_id, mode):
        if tab_id not in self._ids:
            return
        ids = ([key for key in self._ids if key != tab_id] if mode == "others" else
               self._ids[self._ids.index(tab_id) + 1:] if mode == "right" else
               list(self._ids) if mode == "all" else [tab_id])
        self.manager.close_tabs(self, ids)

    @Slot(str, int)
    def moveTab(self, tab_id, index):
        self.manager.moveTab(tab_id, self.windowId, index)

    @Slot()
    def retryActiveTab(self):
        self.manager.focusWindow(self.windowId)
        self.registry.retryActiveTab()

    @Slot()
    def openSettings(self):
        self.manager.open_in(self, self.registry.openSettings)

    @Slot()
    def openDataSources(self):
        self.manager.open_in(self, self.registry.openDataSources)

    @Slot()
    def openPacs(self):
        self.manager.open_in(self, self.registry.openPacs)

    @Slot()
    @Slot(str)
    def openManual(self, chapter=""):
        self.manager.open_in(self, self.registry.openManual, chapter)

    @Slot(str, str, str)
    def createTab(self, uid, label, kind):
        self.manager.open_in(self, self.registry.createTab, uid, label, kind)

    @Slot(str, str)
    def activeWorkspace(self, uid, kind):
        self.manager.open_in(self, self.registry.activeWorkspace, uid, kind)

    @Slot(str, str)
    def createCompareTab(self, first_uid, second_uid):
        self.manager.open_in(self, self.registry.createCompareTab, first_uid, second_uid)

    @Slot(str, str)
    def createFusionTab(self, ct_uid, pet_uid):
        self.manager.open_in(self, self.registry.createFusionTab, ct_uid, pet_uid)

    def shutdown(self):
        if self._export:
            self._export.shutdown()
