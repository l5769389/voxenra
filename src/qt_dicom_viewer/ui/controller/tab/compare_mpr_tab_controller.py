"""Two MPR groups share a tab, never an implicit anatomical registration.

Each group owns its existing reslicer scheduler, window and measurement state.
Only explicit changes in the target geometry propagate when linking is enabled.
"""
from dataclasses import replace
import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

from qt_dicom_viewer.model import TabConfig, TabType, WindowLevelChange
from qt_dicom_viewer.model.dicom_core import MprFrame, MprViewRolls
from qt_dicom_viewer.core.mpr_rotation import move_mpr_state_center
from qt_dicom_viewer.core.compare_mpr import plane_intersects_volume, matched_zooms
from .tab_controller import TabController


class CompareMprGroup(TabController):
    geometryEdited = Signal(object, object)
    windowEdited = Signal(object)

    def __init__(self, config, workspace_tab):
        self._workspace_tab = workspace_tab
        super().__init__(config, workspace_tab, enable_mpr_layout=False)
        # Navigation, measurement and projection use MPR tools. Segmentation and
        # VOI remain in the dedicated single-series MPR workspace.
        self.toolController._tab_type = TabType.COMPARE_MPR

    def _set_mpr_window(self, change, *, render=True):
        before = self._linked_mpr_window
        super()._set_mpr_window(change, render=render)
        if before is not None and self._linked_mpr_window is not None and before.window != self._linked_mpr_window.window:
            self.windowEdited.emit(self._linked_mpr_window)

    def _set_target_mpr_state(self, state):
        before = self._target_mpr_state
        super()._set_target_mpr_state(state)
        if before is not None and before != state:
            self.geometryEdited.emit(before, state)


class CompareMprTabController(TabController):
    settingsChanged = Signal()
    persistenceChanged = Signal()
    readinessChanged = Signal()
    rangeChanged = Signal()

    def __init__(self, config, parent=None):
        if len(config.series_metas) != 2 or config.series_metas[0].series_uid == config.series_metas[1].series_uid:
            raise ValueError("MPR comparison requires two distinct series")
        self.groups = []
        self._owners = {}
        self._display_rotations = {}
        self._display_zooms = {}
        self._fit_scales = {}
        self._zoom_scales = {}
        self._render_slabs = {}
        self._out_of_range = {}
        self._window_linked = self._zoom_linked = False
        self._zoom_limited = False
        self._syncing = False
        self._position_linked = self._rotation_linked = False
        self._pair_plane = ""
        super().__init__(config, parent)
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._apply_zoom_scales)

    @Property('QVariantList', constant=True)
    def comparisonViews(self):
        return list(self._viewport_dict.values())

    @Property('QStringList', constant=True)
    def groupLabels(self):
        return [" · ".join(str(value) for value in (meta.modality, meta.series_description,
                meta.acquisition_datetime, meta.patient_name) if value) for meta in self.tab_config.series_metas]

    @Property(bool, constant=True)
    def mprCompare(self):
        return True

    @Property(QObject, notify=TabController.activeViewportChanged)
    def activeToolController(self):
        group = self._owners.get(self._active_viewport_id)
        return group.toolController if group is not None else self.toolController

    @Property(str, notify=settingsChanged)
    def pairPlane(self):
        return self._pair_plane

    @Property(bool, notify=settingsChanged)
    def positionLinked(self):
        return self._position_linked

    @Property(bool, notify=settingsChanged)
    def rotationLinked(self):
        return self._rotation_linked

    @Property('QVariantMap', notify=settingsChanged)
    def linkStates(self):
        return dict(position=self._position_linked, rotation=self._rotation_linked,
                    window=self._window_linked, zoom=self._zoom_linked)

    @Property(bool, constant=True)
    def windowLinkAvailable(self):
        return all(meta.modality.upper() == "CT" for meta in self.tab_config.series_metas)

    @Property(bool, notify=settingsChanged)
    def zoomLimitReached(self):
        return self._zoom_limited

    @Property('QVariantMap', notify=rangeChanged)
    def outOfRangeViewports(self):
        return dict(self._out_of_range)

    @Property(bool, notify=readinessChanged)
    def ready(self):
        return all(g._target_mpr_state is not None for g in self.groups)

    @Slot(str, bool)
    def setLink(self, kind, enabled):
        if kind not in ("position", "rotation", "window", "zoom") or not self.ready:
            return
        if kind == "window" and enabled and not self.windowLinkAvailable:
            return
        if getattr(self, "_" + kind + "_linked") == bool(enabled):
            return
        setattr(self, "_" + kind + "_linked", bool(enabled))
        if kind == "window" and enabled:
            source = self._owners[self._active_viewport_id]
            self._sync_window(source, source._linked_mpr_window)
        if kind == "zoom" and enabled:
            self._zoom_limited = False
            for view in self._owners[self._active_viewport_id].viewports_by_id.values():
                self._zoom_scales[view.viewportType] = self._fit_scale(view) * view.zoom
            self._apply_zoom_scales()
        # Capture no absolute alignment: turning a link on does not move either
        # independently positioned series. Subsequent deltas are synchronized.
        self.settingsChanged.emit()

    @Slot(str)
    def setPairPlane(self, plane):
        if plane not in ("", "axial", "coronal", "sagittal"):
            return
        if plane:
            group = self._owners.get(self._active_viewport_id, self.groups[0])
            view = next(v for v in group.viewports_by_id.values() if v.viewportType == plane)
            self.activateViewport(view.viewportId)
        self._pair_plane = plane
        self.settingsChanged.emit()
        self.viewLayoutChanged.emit()

    @Slot(str)
    def focusSingleViewport(self, viewport_id):
        view = self._viewport_dict.get(viewport_id)
        self.setPairPlane(view.viewportType if view is not None else "")

    @Slot(str)
    def togglePair(self, viewport_id):
        view = self._viewport_dict.get(viewport_id)
        if view is not None:
            self.activateViewport(viewport_id)
            self.setPairPlane("" if self._pair_plane == view.viewportType else view.viewportType)

    @Slot()
    def resetActiveOrientation(self):
        group = self._owners.get(self._active_viewport_id)
        if group is None or group._initial_mpr_state is None:
            return
        current, initial = group._target_mpr_state, group._initial_mpr_state
        group._set_target_mpr_state(replace(current,
            frame=replace(initial.frame, center_patient=current.frame.center_patient),
            view_rolls=initial.view_rolls))
        group._mpr_3d_reset_state = group._target_mpr_state
        group._dirty_mpr_viewport_ids.update(group._mpr_viewport_ids())
        group._try_start_next_mpr_render()

    def _create_viewport_dict(self):
        for index, meta in enumerate(self.tab_config.series_metas):
            group = CompareMprGroup(TabConfig(self.tab_config.tab_id, meta.series_description,
                                             TabType.MPR, (meta,)), self)
            self.groups.append(group)
            for view in group.viewports_by_id.values():
                view.viewport_config = replace(view.viewport_config, role="a" if index == 0 else "b")
                self._viewport_dict[view.viewportId] = view
                self._owners[view.viewportId] = group
                self._display_zooms[view.viewportId] = view.zoom
                self._display_rotations[view.viewportId] = view.rotationDegrees
                view.transformChanged.connect(lambda source=view: self._sync_display_transform(source))
            group.windowEdited.connect(lambda change, source=group: self._sync_window(source, change))
            group.imageUpdateRequested.connect(self.imageUpdateRequested.emit)
            group.renderRequested.connect(self._forward_request)
            group.imageRemovalRequested.connect(self.imageRemovalRequested.emit)
            group.geometryEdited.connect(lambda before, after, source=group: self._sync_geometry(source, before, after))
        self._active_viewport_id = self.groups[0].activeViewport.viewportId

    @Slot(object)
    def _forward_request(self, request):
        self._render_slabs[request.request_id] = request.slab_thickness_mm if request.projection_mode is not None else 0.
        self._active_mpr_requests[request.request_id] = request.viewport_id
        self.renderRequested.emit(request)

    @Slot(str)
    def activateViewport(self, viewport_id):
        group = self._owners.get(viewport_id)
        if group is None:
            return
        group.activateViewport(viewport_id)
        if self._active_viewport_id != viewport_id:
            self._active_viewport_id = viewport_id
            self.activeViewportChanged.emit()

    def init_render(self):
        for group in self.groups:
            group.init_render()

    def retry_initial_load(self):
        for group in self.groups:
            group.retry_initial_load()

    def accepts_render_result(self, result):
        group = self._owners.get(result.viewport_id)
        return group is not None and group.accepts_render_result(result)

    def discard_stale_mpr_window_result(self, result):
        group = self._owners.get(result.viewport_id)
        discarded = group is not None and group.discard_stale_mpr_window_result(result)
        if discarded:
            self._render_slabs.pop(result.response_id, None)
            self._active_mpr_requests.pop(result.response_id, None)
        return discarded

    def handleRenderResult(self, result):
        group = self._owners.get(result.viewport_id)
        if group is not None:
            was_ready = self.ready
            group.handleRenderResult(result)
            slab = self._render_slabs.pop(result.response_id, 0.)
            if result.volume is not None and result.plane_geometry is not None:
                outside = not plane_intersects_volume(result.volume.geometry, result.plane_geometry, slab)
                if self._out_of_range.get(result.viewport_id, False) != outside:
                    self._out_of_range[result.viewport_id] = outside
                    self.rangeChanged.emit()
            self._active_mpr_requests.pop(result.response_id, None)
            if self.ready != was_ready:
                self.readinessChanged.emit()

    def handleRenderFailure(self, failure):
        group = self._owners.get(failure.viewport_id)
        if group is not None:
            group.handleRenderFailure(failure)
            self._render_slabs.pop(failure.request_id, None)
            self._active_mpr_requests.pop(failure.request_id, None)

    def _sync_geometry(self, source, before, after):
        self.persistenceChanged.emit()
        if self._syncing:
            return
        target = next(g for g in self.groups if g is not source)
        state = target._target_mpr_state
        if state is None:
            return
        updated = state
        if self._position_linked:
            delta = np.asarray(after.frame.center_patient) - before.frame.center_patient
            if np.any(delta):
                updated = move_mpr_state_center(updated, tuple(np.asarray(state.frame.center_patient) + delta))
        if self._rotation_linked:
            old_basis, new_basis = before.frame.mpr_to_patient[:3, :3], after.frame.mpr_to_patient[:3, :3]
            if not np.allclose(old_basis, new_basis) or before.view_rolls != after.view_rolls:
                basis = new_basis @ old_basis.T @ state.frame.mpr_to_patient[:3, :3]
                rolls = {name: getattr(state.view_rolls, name) + getattr(after.view_rolls, name) - getattr(before.view_rolls, name)
                         for name in ("axial_radians", "coronal_radians", "sagittal_radians")}
                updated = replace(updated, frame=MprFrame(updated.frame.center_patient,
                    *(tuple(basis[:, i]) for i in range(3))), view_rolls=MprViewRolls(**rolls))
        if updated == state:
            return
        self._syncing = True
        try:
            target._set_target_mpr_state(updated)
            target._mpr_3d_reset_state = updated
            target._dirty_mpr_viewport_ids.update(target._mpr_viewport_ids())
            target._try_start_next_mpr_render()
        finally:
            self._syncing = False

    def _sync_display_transform(self, source):
        # A reset can change rotation and zoom together. Consume the rotation
        # delta before scale matching can emit a nested transform notification.
        self._sync_display_rotation(source)
        self._sync_zoom(source)

    def _sync_display_rotation(self, source):
        previous = self._display_rotations[source.viewportId]
        self._display_rotations[source.viewportId] = source.rotationDegrees
        delta = source.rotationDegrees - previous
        if self._syncing or not self._rotation_linked or not delta:
            return
        target = next(view for view in self._viewport_dict.values()
                      if view.viewportType == source.viewportType and view is not source)
        self._syncing = True
        try:
            target._state = replace(target._state, rotation_degrees=(target.rotationDegrees + delta) % 360)
            target.transformChanged.emit()
            target.directionLabelsChanged.emit()
            target.overlayChanged.emit()
        finally:
            self._syncing = False

    def _sync_window(self, source, change):
        if self._syncing or not self._window_linked or change is None:
            return
        target = next(group for group in self.groups if group is not source)
        self._syncing = True
        try:
            target._set_mpr_window(WindowLevelChange(change.window, target.activeViewport.inverted))
        finally:
            self._syncing = False

    def _fit_scale(self, view):
        if view.viewportId in self._fit_scales:
            return self._fit_scales[view.viewportId]
        if not view.fitToWindow or not view.imageColumns or not view.imageRows:
            return 1.
        return min(view._state.width / (view.imageColumns * view.imageColumnSpacing),
                   view._state.height / (view.imageRows * view.imageRowSpacing)) or 1.

    @Slot(str, float)
    def updateViewportFitScale(self, viewport_id, scale):
        if viewport_id not in self._owners or not np.isfinite(scale) or scale <= 0:
            return
        if self._fit_scales.get(viewport_id) == scale:
            return
        self._fit_scales[viewport_id] = scale
        if self._zoom_linked:
            self._zoom_timer.start(0)

    def _sync_zoom(self, source):
        previous = self._display_zooms[source.viewportId]
        self._display_zooms[source.viewportId] = source.zoom
        if self._syncing or not self._zoom_linked or previous == source.zoom:
            return
        self._zoom_scales[source.viewportType] = self._fit_scale(source) * source.zoom
        self._apply_zoom_scales()

    @Slot()
    def _apply_zoom_scales(self):
        if not self._zoom_linked:
            return
        plans = []
        for plane, scale in list(self._zoom_scales.items()):
            first, second = (view for view in self._viewport_dict.values() if view.viewportType == plane)
            fits = self._fit_scale(first), self._fit_scale(second)
            zooms = matched_zooms(*fits, scale)
            if zooms is None:
                self._zoom_linked = False
                self._zoom_limited = True
                self.settingsChanged.emit()
                return
            plans.append((plane, first, second, fits[0], zooms))
        self._syncing = True
        try:
            for plane, first, second, first_fit, zooms in plans:
                for view, zoom in zip((first, second), zooms):
                    view.setZoom(zoom)
                self._zoom_scales[plane] = first_fit * zooms[0]
        finally:
            self._syncing = False

    @Slot(str)
    def recenterSeries(self, viewport_id):
        group = self._owners.get(viewport_id)
        if group is None or group._initial_mpr_state is None:
            return
        # Recovery targets this series; keep the other independently located series in place.
        self._syncing = True
        try:
            state = move_mpr_state_center(group._target_mpr_state, group._initial_mpr_state.frame.center_patient)
            group._set_target_mpr_state(state)
            group._mpr_3d_reset_state = state
            group._dirty_mpr_viewport_ids.update(group._mpr_viewport_ids())
            group._try_start_next_mpr_render()
        finally:
            self._syncing = False

    def comparison_snapshot(self):
        from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot
        return dict(pairPlane=self._pair_plane, positionLinked=self._position_linked,
                    rotationLinked=self._rotation_linked, windowLinked=self._window_linked,
                    zoomLinked=self._zoom_linked, zoomScales=dict(self._zoom_scales),
                    groups=[tab_snapshot(g) for g in self.groups])

    def restore_comparison(self, record):
        from qt_dicom_viewer.ui.workspace_snapshot import apply_tab_snapshot
        self._syncing = True
        try:
            for group, saved in zip(self.groups, record["groups"]):
                apply_tab_snapshot(group, saved)
            self._pair_plane = record.get("pairPlane", "")
            self._position_linked = record.get("positionLinked", False)
            self._rotation_linked = record.get("rotationLinked", False)
            self._window_linked = record.get("windowLinked", False) and self.windowLinkAvailable
            self._zoom_linked = record.get("zoomLinked", False)
            self._zoom_scales = dict(record.get("zoomScales", {}))
            self._zoom_limited = False
        finally:
            self._syncing = False
        self.settingsChanged.emit()
        self.viewLayoutChanged.emit()

    def dispose(self):
        self._zoom_timer.stop()
        self._render_slabs.clear()
        if getattr(self, "_edit_history", None) is not None:
            self._edit_history.dispose()
        for group in self.groups:
            group.dispose()
            group._active_mpr_requests.clear()
            group._dirty_mpr_viewport_ids.clear()
            group._mpr_request_phase_identifiers.clear()
            group._mpr_request_window_revisions.clear()
        self._active_mpr_requests.clear()
        self.pausePlayback()
