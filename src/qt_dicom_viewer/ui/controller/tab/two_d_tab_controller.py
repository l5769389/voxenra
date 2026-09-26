"""Independent 2D scene cells, with cached original and orthogonal views."""
from dataclasses import replace
import uuid

from PySide6.QtCore import QObject, Property, Signal, Slot
from qt_dicom_viewer.model import MprPlane, TwoDViewType, ViewportConfig
from qt_dicom_viewer.ui.controller.viewport.image_2d.stack_viewport_controller import StackViewportController
from qt_dicom_viewer.ui.controller.viewport.image_2d.mpr_viewport_controller import MprViewportController
from qt_dicom_viewer.ui.controller.viewport.image_2d.image_2d_viewport_controller import Image2DViewportController
from qt_dicom_viewer.model.ui_models import ViewportDisplaySettings
from qt_dicom_viewer.ui.controller.viewport.image_2d.image_2d_viewport_controller import VIEWPORT_SETTING_FIELDS
from .tab_controller import TabController
from qt_dicom_viewer.core.scene_layout import PRESETS, MODES, placements


class PlaneViewportController(MprViewportController):
    """Use the existing reslicer and 2D operations without a shared MPR locator."""
    def __init__(self, *args, **kwargs):
        self.slice_frame = None
        super().__init__(*args, **kwargs)
        self.crosshairCenterChangeRequested.connect(self._move_center)

    def _move_center(self, center):
        if self.slice_frame is not None:
            self.slice_frame = replace(self.slice_frame, center_patient=center)
            self.request_render()

    def _build_render_request(self, *, initial):
        request = self.build_mpr_render_request(mpr_frame=self.slice_frame, initial=initial)
        return replace(request, value_unit=self.pet_active_unit_id or None,
                       window=self._pet_display.target.window if not initial and self.isPetViewport
                           and self._pet_display.target else request.window)

    request_render = Image2DViewportController.request_render

    def _apply_specific_render_result(self, result):
        self.slice_frame = result.mpr_frame
        super()._apply_specific_render_result(result)
        self._crosshair_image_position = None
        self.crosshairImagePositionChanged.emit()

    def _crosshair_hit_test(self, *args, **kwargs):
        return None


class TwoDLayoutController(QObject):
    changed = Signal()
    cellsChanged = Signal()
    activeChanged = Signal()
    settingsChanged = Signal()
    settingsEdited = Signal()

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self._layout, self._rows, self._columns = "1x1", 1, 1
        first = next(iter(tab.viewports_by_id.values()))
        self._cells = [dict(uid=first.viewport_config.series_uid, mode="stack", views={"stack": first})]
        self._active_cell = 0
        self._settings_scope = "current"
        self._display_defaults = first._state.display_settings
        first.viewportSettingsChanged.connect(self.settingsChanged.emit)
        self.cellsChanged.connect(self.settingsChanged.emit)
        self.activeChanged.connect(self.settingsChanged.emit)

    @Property(str, notify=settingsChanged)
    def settingsScope(self):
        return self._settings_scope

    @Slot(str)
    def setSettingsScope(self, scope):
        if scope in ("current", "tab") and scope != self._settings_scope:
            self._settings_scope = scope
            self.settingsChanged.emit()

    def _cell_display(self, cell):
        view = cell["views"].get(cell["mode"])
        return view._state.display_settings if view is not None else cell.get("display", self._display_defaults)

    @Property("QVariantMap", notify=settingsChanged)
    def viewportSettingStates(self):
        cells = self._cells if self._settings_scope == "tab" else [self._cells[self._active_cell]]
        states = [self._cell_display(cell) for cell in cells]
        return {key: 2 if all(getattr(s, field) for s in states) else
                1 if any(getattr(s, field) for s in states) else 0
                for key, field in VIEWPORT_SETTING_FIELDS.items()}

    @Slot(str, bool)
    def setViewportSetting(self, code, enabled):
        field = VIEWPORT_SETTING_FIELDS.get(code)
        if field is None or code == "localizer":
            return
        cells = self._cells if self._settings_scope == "tab" else [self._cells[self._active_cell]]
        if self._settings_scope == "tab":
            self._display_defaults = replace(self._display_defaults, **{field: bool(enabled)})
        for cell in cells:
            cell["display"] = replace(self._cell_display(cell), **{field: bool(enabled)})
            for view in cell["views"].values():
                view.setViewportSetting(code, enabled)
        self.settingsChanged.emit()
        self.settingsEdited.emit()

    @Property(str, notify=changed)
    def layout(self):
        return self._layout

    @Property(int, notify=changed)
    def rows(self):
        return self._rows

    @Property(int, notify=changed)
    def columns(self):
        return self._columns

    @Property("QVariantList", constant=True)
    def options(self):
        return [dict(id=key, rows=placements(key)[0], columns=placements(key)[1],
                     cells=placements(key)[2]) for key in PRESETS]

    @Property("QVariantList", notify=cellsChanged)
    def cells(self):
        positions = placements(self._layout, self._rows, self._columns)[2]
        return [dict(index=i, mode=cell["mode"], viewport=cell["views"].get(cell["mode"]),
                     seriesUid=cell["uid"], label=(next(iter(cell["views"].values())).viewport_config.series_meta.series_description or cell["uid"])
                     if cell["views"] else "", **position)
                for i, (cell, position) in enumerate(zip(self._cells, positions))]

    @Property(int, notify=activeChanged)
    def activeCell(self):
        return self._active_cell

    @Slot(str)
    def setLayout(self, key):
        if key not in PRESETS:
            return
        self._set_layout(key, *placements(key)[:2])

    @Slot(int, int)
    def setCustomLayout(self, rows, columns):
        self._set_layout("custom", max(1, min(6, rows)), max(1, min(6, columns)))

    def _set_layout(self, key, rows, columns):
        count = len(placements(key, rows, columns)[2])
        while len(self._cells) < count:
            self._cells.append(dict(uid="", mode="stack", views={}, display=self._display_defaults))
        self._layout, self._rows, self._columns = key, rows, columns
        self.tab.focusSingleViewport("")
        self.activateCell(min(self._active_cell, count-1))
        self.changed.emit()
        self.cellsChanged.emit()

    @Slot(int)
    def activateCell(self, index):
        if not 0 <= index < len(self.cells):
            return
        self._active_cell = index
        view = self._cells[index]["views"].get(self._cells[index]["mode"])
        if view is not None:
            self.tab.activateViewport(view.viewportId)
        else:
            self.tab._active_viewport_id = ""
            self.tab.activeViewportChanged.emit()
        self.activeChanged.emit()

    def _new_view(self, index, mode, meta):
        kind = TwoDViewType.STACK if mode == "stack" else MprPlane(mode)
        # Keep the first Stack's legacy key so older workspaces remain readable.
        role = "image" if index == 0 else "cell-" + str(index)
        view = (StackViewportController if mode == "stack" else PlaneViewportController)(
            ViewportConfig(str(uuid.uuid4()), self.tab.tab_config.tab_id, kind, meta.series_uid, meta, role=role),
            self.tab.toolController, parent=self.tab)
        view._state = replace(view._state, display_settings=self._cell_display(self._cells[index]))
        view.viewportSettingsChanged.connect(self.settingsChanged.emit)
        self.tab._viewport_dict[view.viewportId] = view
        self.tab.connect_signal(view)
        history = getattr(self.tab, "_edit_history", None)
        if history is not None:
            history.watch_view(view)
        return view

    @Slot(int, str, result=bool)
    def loadSeries(self, index, uid):
        if not 0 <= index < len(self.cells):
            return False
        catalog = self.tab.parent()._series_catalog
        meta = catalog.get_series_display_meta(uid)
        if meta is None:
            return False
        cell = self._cells[index]
        if cell["uid"] != uid:
            display = self._cell_display(cell)
            for old in cell["views"].values():
                self.tab._viewport_dict.pop(old.viewportId, None)
                old.shutdown()
                self.tab.imageRemovalRequested.emit(old.viewportId)
                old.deleteLater()
            self._cells[index] = dict(uid=uid, mode="stack", views={}, display=display)
            view = self._new_view(index, "stack", meta)
            self._cells[index]["views"]["stack"] = view
            self._sync_series()
            self.activateCell(index)
            view.request_first_loader()
        else:
            self.activateCell(index)
        self.cellsChanged.emit()
        return True

    @Slot(int)
    def retryCell(self, index):
        if 0 <= index < len(self.cells):
            cell = self._cells[index]
            view = cell["views"].get(cell["mode"])
            if view is not None:
                view.request_first_loader()

    def _sync_series(self):
        catalog = self.tab.parent()._series_catalog
        uids = dict.fromkeys(c["uid"] for c in self._cells if c["uid"])
        self.tab._tab_config = replace(self.tab.tab_config,
            series_metas=tuple(catalog.get_series_display_meta(uid) for uid in uids))

    @Slot(int, str)
    def setMode(self, index, mode):
        if mode not in MODES or not 0 <= index < len(self.cells):
            return
        cell = self._cells[index]
        if not cell["uid"]:
            return
        previous_view = cell["views"].get(cell["mode"])
        was_focused = previous_view is not None and self.tab.focusedViewportId == previous_view.viewportId
        view = cell["views"].get(mode)
        created = view is None
        if created:
            meta = self.tab.parent()._series_catalog.get_series_display_meta(cell["uid"])
            view = self._new_view(index, mode, meta)
            cell["views"][mode] = view
        cell["mode"] = mode
        self.activateCell(index)
        if was_focused:
            self.tab.focusSingleViewport(view.viewportId)
        self.cellsChanged.emit()
        if created:
            view.request_first_loader()

    def snapshot(self):
        return dict(layout=self._layout, rows=self._rows, columns=self._columns, active=self._active_cell,
                    displayDefaults=self._display_defaults,
                    cells=[dict(uid=c["uid"], mode=c["mode"], modes=list(c["views"]),
                                display=self._cell_display(c)) for c in self._cells])

    def restore(self, record):
        if not record:
            return
        self._display_defaults = record.get("displayDefaults", ViewportDisplaySettings())
        records = record.get("cells", [])[:36]
        while len(self._cells) < len(records):
            self._cells.append(dict(uid="", mode="stack", views={}, display=self._display_defaults))
        catalog = self.tab.parent()._series_catalog
        for i, saved in enumerate(records):
            uid = saved.get("uid", "")
            cell = self._cells[i]
            cell["display"] = saved.get("display", self._display_defaults)
            meta = catalog.get_series_display_meta(uid)
            if meta is None:
                continue
            if cell["uid"] != uid:
                for old in cell["views"].values():
                    self.tab._viewport_dict.pop(old.viewportId, None)
                    old.shutdown()
                    old.deleteLater()
                cell = self._cells[i] = dict(uid=uid, mode="stack", views={}, display=saved.get("display", self._display_defaults))
            for mode in saved.get("modes", ["stack"]):
                if mode in MODES and mode not in cell["views"]:
                    cell["views"][mode] = self._new_view(i, mode, meta)
            cell["mode"] = saved.get("mode") if saved.get("mode") in cell["views"] else "stack"
        self._sync_series()
        key = record.get("layout", "1x1")
        if key == "custom":
            self.setCustomLayout(int(record.get("rows", 1)), int(record.get("columns", 1)))
        else:
            self.setLayout(key)
        self.activateCell(max(0, min(int(record.get("active", 0)), len(self.cells)-1)))


class TwoDTabController(TabController):
    persistenceChanged = Signal()
    def __init__(self, config, parent=None):
        super().__init__(config, parent)
        self._two_d_layout = TwoDLayoutController(self)
        for signal in (self._two_d_layout.changed, self._two_d_layout.cellsChanged, self._two_d_layout.activeChanged, self._two_d_layout.settingsEdited):
            signal.connect(self.persistenceChanged.emit)

    @Property(QObject, constant=True)
    def twoDLayout(self):
        return self._two_d_layout

    def connect_signal(self, view):
        self._connect_playback_viewport(view)
        view.imageUpdateRequested.connect(self.imageUpdateRequested.emit)
        # Each orthogonal cell owns its frame and render identity. Never route
        # its requests through the three linked MPR planes' batch scheduler.
        view.renderRequested.connect(self._handle_render_requested)
        for name in ("transformChanged", "sliceChanged", "displayStyleChanged", "petDisplayChanged"):
            getattr(view, name).connect(self.persistenceChanged.emit)
        view._persisted_window = (view._state.window, view._state.inverted)
        view._persisted_display = view._state.display_settings
        view.viewportSettingsChanged.connect(lambda: self._display_settings_changed(view))
        view.overlayChanged.connect(lambda: self._window_changed(view))

    def _display_settings_changed(self, view):
        if view._state.display_settings != view._persisted_display:
            view._persisted_display = view._state.display_settings
            self.persistenceChanged.emit()

    def _window_changed(self, view):
        # Overlay notifications also announce a language/theme refresh. Only
        # actual intensity changes should dirty the saved workspace.
        state = (view._state.window, view._state.inverted)
        if state != view._persisted_window:
            view._persisted_window = state
            self.persistenceChanged.emit()

    def accepts_render_result(self, result):
        view = self._viewport_dict.get(result.viewport_id)
        return view is not None and view.accepts_result(result)

    def handleRenderResult(self, result):
        view = self._viewport_dict.get(result.viewport_id)
        if view is not None:
            view.handleRenderResult(result)

    def handleRenderFailure(self, failure):
        view = self._viewport_dict.get(failure.viewport_id)
        if view is not None:
            view.handleRenderFailure(failure)

    def _handle_tool_command(self, command):
        if command == "viewport:reset" and isinstance(self.activeViewport, PlaneViewportController):
            self.activeViewport.reset_all_view_state()
            return
        super()._handle_tool_command(command)

    @Slot(str)
    def activateViewport(self, viewport_id):
        view = self._viewport_dict.get(viewport_id)
        if view is None:
            return
        tools = self.toolController
        tools.set_series_capabilities(view.viewport_config.series_meta)
        if isinstance(view, PlaneViewportController) and tools.activeTool == "service":
            tools.activateTool("window")
        super().activateViewport(viewport_id)
        layout = getattr(self, "_two_d_layout", None)
        if layout is not None:
            for i, cell in enumerate(layout._cells):
                mode = next((mode for mode, candidate in cell["views"].items() if candidate is view), None)
                if mode is None:
                    continue
                # Results may belong to a cached plane that is not currently shown.
                if cell["mode"] != mode:
                    cell["mode"] = mode
                    layout.cellsChanged.emit()
                if layout._active_cell != i:
                    layout._active_cell = i
                    layout.activeChanged.emit()
                break
