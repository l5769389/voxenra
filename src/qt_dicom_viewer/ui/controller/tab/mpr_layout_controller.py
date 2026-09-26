"""Per-tab layouts and a lazy, shared-volume 3D spatial reference view."""
from dataclasses import replace
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty

import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt

from qt_dicom_viewer.core.mpr_layout import MPR_LAYOUTS, layout_items, placements, matrix_quaternion
from qt_dicom_viewer.core.volume_view import ANTERIOR_BASIS, view_basis, camera_parameters
from qt_dicom_viewer.model import TabType, ViewportConfig, ToolType, InteractionType
from qt_dicom_viewer.model.dicom_models import VolumeViewType
from qt_dicom_viewer.model.render_models import VolumeLoadResult
from qt_dicom_viewer.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
from qt_dicom_viewer.ui.controller.viewport.standalone_pet_volume_controller import StandalonePetVolumeController
from .tool_controller import ToolController, build_tool_items, TOOL_ORDER


class ReferenceToolController(ToolController):
    """Reuse 3D navigation/display tools; the reference volume remains read-only."""
    _i18n_referenceTools = Signal()
    ALLOWED = frozenset(("window", "pan", "zoom", "volume-rotate", "volume-preset",
                         "volume-direction", "mpr-layout", "viewport-settings", "export", "reset"))

    @property
    def temporal_playback(self):
        return self.parent().tab.temporalPlayback

    @_TextProperty(str, notify=ToolController._i18n_activeToolLabel,
                   notify_name="_i18n_activeToolLabel", source_notify="activeToolChanged")
    def activeToolLabel(self):
        if self._active_tool == ToolType.PLAY and self.temporal_playback:
            return _msg("playback.fourD")
        return ToolController.activeToolLabel.fget(self)

    @Property(str, notify=ToolController.activeToolChanged)
    def activeToolIcon(self):
        return "cine-4d-play" if self._active_tool == ToolType.PLAY else ToolController.activeToolIcon.fget(self)

    @_TextProperty(list, notify=_i18n_referenceTools, notify_name="_i18n_referenceTools")
    def tools(self):
        items = [item for item in build_tool_items(TabType.THREE_D, self._modality)
                 if item["toolType"] in self.ALLOWED]
        items += [item for item in build_tool_items(TabType.MPR, self._modality)
                  if item["toolType"] in ("mpr-layout", "viewport-settings")]
        if self.temporal_playback:
            items += [item for item in build_tool_items(TabType.FOUR_D, self._modality)
                      if item["toolType"] == "play"]
        return sorted(items, key=lambda item: TOOL_ORDER.index(item["toolType"]))

    @Slot(str)
    def activateTool(self, value):
        if self._locked_tool is not None and value != self._locked_tool:
            return
        if value == "play" and self.temporal_playback:
            self._set_active_tool(ToolType.PLAY)
            self._set_active_interaction(InteractionType.NONE)
            self._set_active_panel(ToolType.PLAY)
        elif value in ("mpr-layout", "viewport-settings"):
            self._set_active_tool(ToolType(value))
            self._set_active_interaction(InteractionType.NONE)
            self._set_active_panel(ToolType(value))
        elif value in self.ALLOWED:
            super().activateTool(value)


class ReferenceVolumeMixin:
    """Navigation uses the existing native host; dragging the marker edits MPR."""
    def request_render(self):
        # The MPR loader owns decoding, phase selection and request cancellation.
        if self.volume is not None:
            self._set_status("ready")
        else:
            self._layout_owner.tab.retry_initial_load()

    def toggleMaximized(self):
        self._layout_owner.toggleMaximized()

    def begin_drag(self, point, size, buttons=Qt.MouseButton.LeftButton.value):
        self._layout_owner.activate()
        self._marker_drag = None
        owner = self._layout_owner
        state = owner.tab._target_mpr_state
        if (buttons & Qt.MouseButton.LeftButton.value and self.volume is not None
                and state is not None and owner.referenceMode != "hidden"):
            camera = camera_parameters(self.volume.geometry, self.state, size)
            basis = view_basis(self.state)
            center = np.asarray(state.frame.center_patient)
            delta = center - camera["focal"]
            scale = max(1, size[1]) / (2 * camera["scale"])
            screen = np.array((size[0]/2 + np.dot(delta, basis[:, 0])*scale,
                               size[1]/2 - np.dot(delta, basis[:, 1])*scale))
            if np.linalg.norm(screen - point) <= 14:
                self._marker_drag = (np.asarray(point), center, basis, scale)
                return
        super().begin_drag(point, size, buttons)

    def update_drag(self, point):
        drag = getattr(self, "_marker_drag", None)
        if drag is not None:
            start, center, basis, scale = drag
            delta = np.asarray(point) - start
            target = center + (delta[0]*basis[:, 0] - delta[1]*basis[:, 1])/scale
            g = self.volume.geometry
            axes = np.column_stack((g.column_index_direction_patient, g.row_index_direction_patient,
                                    g.slice_index_direction_patient))
            extent = ((g.columns-1)*g.column_spacing, (g.rows-1)*g.row_spacing,
                      (g.slice_count-1)*g.slice_spacing)
            target = np.asarray(g.origin_patient) + axes @ np.clip(
                axes.T @ (target - g.origin_patient), 0, extent)
            self._layout_owner.move_center(tuple(float(v) for v in target))
            return
        super().update_drag(point)

    def wheel_zoom(self, angle_delta, pixel_delta):
        self._layout_owner.activate()
        super().wheel_zoom(angle_delta, pixel_delta)

    def cancel_drag(self):
        self._marker_drag = None
        super().cancel_drag()

    def end_drag(self):
        self._marker_drag = None
        super().end_drag()


class MprReferenceVolumeController(ReferenceVolumeMixin, VolumeViewportController):
    referenceChanged = Signal()


class PetMprReferenceVolumeController(ReferenceVolumeMixin, StandalonePetVolumeController):
    referenceChanged = Signal()

    @Slot(str)
    def setPetUnit(self, value):
        # The shared MPR loader owns unit conversion and rejects stale results.
        if not self._disposed:
            self._layout_owner.tab.pet_display.set_unit(value)


class MprLayoutController(QObject):
    changed = Signal()
    preferencesChanged = Signal()
    _i18n_options = Signal()
    activeChanged = Signal()

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self._layout = "right"
        self._preference_error = ""
        self._preference_key = "rememberedFourDLayout" if tab.tab_config.tab_type == TabType.FOUR_D else "rememberedMprLayout"
        self._active = False
        self._reference_mode = "planes"
        self._link_rotation = True
        self._updating = False
        self._last_frame = None
        self._disposed = False
        self._pending_volume = None
        self._pending_pet = {}
        meta = tab.tab_config.series_metas[0]
        self._supports_reference_volume = True
        self._tools = ReferenceToolController(self, tab_type=TabType.THREE_D, modality=meta.modality)
        self._settings = self._tools.settingsController
        # Apply only when creating a tab. Existing tabs retain their own layout.
        self._layout = self._settings.section("layout")[self._preference_key] or "right"
        cls = PetMprReferenceVolumeController if meta.modality.upper() == "PT" else MprReferenceVolumeController
        self._view = cls(ViewportConfig(tab.tab_config.tab_id + ":mpr-reference",
            tab.tab_config.tab_id, VolumeViewType.VOLUME, meta.series_uid, meta), self._tools, tab)
        self._view._layout_owner = self
        self._view.loadStateChanged.connect(self._reference_load_changed)
        self._previous_camera = self._view.state
        self._view.stateChanged.connect(self._camera_changed)
        self._tools.commandRequested.connect(lambda _: self._view.reset_all_view_state())
        self._tools.resetRequested.connect(lambda value: self._view.reset_tool_state(ToolType(value)))
        self._tools.resetRequested.connect(self._reset_viewport_settings)
        tab.toolController.resetRequested.connect(self._reset_viewport_settings)
        self.changed.connect(tab.viewLayoutChanged.emit)
        self._view.displayStateChanged.connect(tab.viewLayoutChanged.emit)
        self._tools.settingsController.sectionChanged.connect(self._settings_changed)

    @Property(bool, notify=activeChanged)
    def active(self): return self._active

    @Slot()
    def activate(self):
        if not self._disposed and self._layout == "quad" and not self._active:
            self.tab.focusSingleViewport("")
            self._active = True
            self.activeChanged.emit()
            self.tab.activeViewportChanged.emit()

    @Slot()
    def toggleMaximized(self):
        if not self._disposed and self._layout == "quad":
            viewport_id = self._view.viewportId
            self.tab.focusSingleViewport("" if self.tab.focusedViewportId == viewport_id else viewport_id)

    def deactivate(self):
        if self._active:
            if self.tab.focusedViewportId == self._view.viewportId:
                self.tab.focusSingleViewport("")
            self._view.cancel_drag()
            self._active = False
            self.activeChanged.emit()
            self.tab.activeViewportChanged.emit()

    @Property(str, notify=changed)
    def layout(self): return self._layout

    @Property(bool, notify=preferencesChanged)
    def rememberLayout(self):
        return bool(self._settings.section("layout")[self._preference_key])

    @Property(str, notify=preferencesChanged)
    def preferenceError(self): return self._preference_error

    def _save_preference(self, value):
        saved = self._settings.setValue("layout", self._preference_key, value)
        self._preference_error = "" if saved else self._settings.message
        self.preferencesChanged.emit()

    @Slot(bool)
    def setRememberLayout(self, enabled):
        if not self._disposed:
            self._save_preference(self._layout if enabled else "")

    @Property(str, notify=changed)
    def referenceMode(self): return self._reference_mode

    @Property(bool, notify=changed)
    def linkRotation(self): return self._link_rotation

    @Property(QObject, constant=True)
    def volumeViewport(self): return self._view

    @Property(QObject, constant=True)
    def volumeTools(self): return self._tools

    @_TextProperty("QVariantList", notify=_i18n_options, notify_name="_i18n_options")
    def options(self):
        return [item for item in layout_items() if self._supports_reference_volume or item["value"] != "quad"]

    @Property("QVariantMap", notify=changed)
    def placements(self): return placements(self._layout)

    @Property(int, notify=changed)
    def rows(self): return MPR_LAYOUTS[self._layout][1]

    @Property(int, notify=changed)
    def columns(self): return MPR_LAYOUTS[self._layout][2]

    @Slot(str)
    def setLayout(self, value):
        self._set_layout(value, remember=True)

    def _set_layout(self, value, *, remember=False):
        if self._disposed or value not in MPR_LAYOUTS or (value == "quad" and not self._supports_reference_volume):
            return
        if remember and self.rememberLayout:
            self._save_preference(value)
        if value != "quad":
            self.deactivate()
        self.tab.focusSingleViewport("")
        if value == self._layout:
            return
        self._layout = value
        if value == "quad" and self._pending_volume is not None:
            self.accept_volume(self._pending_volume)
        if value != "quad":
            self._view.setNativeVisible(False)
        self.changed.emit()

    @Slot(str)
    def setReferenceMode(self, value):
        if not self._disposed and value in ("planes", "point", "hidden") and value != self._reference_mode:
            self._reference_mode = value
            self._view.referenceChanged.emit()
            self.changed.emit()

    @Slot(bool)
    def setLinkRotation(self, enabled):
        if not self._disposed and bool(enabled) != self._link_rotation:
            self._link_rotation = bool(enabled)
            self._previous_camera = self._view.state
            self.changed.emit()

    @Slot(str)
    def _reset_viewport_settings(self, tool):
        if tool == "viewport-settings":
            self.setReferenceMode("planes")
            self.setLinkRotation(True)

    def _settings_changed(self, section):
        if section == "layout":
            self.preferencesChanged.emit()
        if section in ("crosshair", "corners"):
            self._view.referenceChanged.emit()

    @Slot()
    def _reference_load_changed(self):
        if self.tab.temporalPlayback and self._view.loadState == "error":
            self.tab.pausePlayback()
        self.tab.playbackAvailabilityChanged.emit()

    @property
    def awaiting_playback_frame(self):
        host = self._view._host
        # Hidden/slice-only layouts must not wait for a detached GPU surface.
        return (self._layout == "quad" and host is not None and host._active
                and not host.frame_ready and self._view.loadState != "error")

    def accept_volume(self, volume):
        if self._disposed or volume is None:
            return
        self._pending_volume = volume
        if self._layout != "quad" or self._view.volume is volume:
            return
        self._view._request_id = "shared-mpr-volume"
        self._view.handleRenderResult(VolumeLoadResult(response_id="shared-mpr-volume",
            viewport_id=self._view.viewportId, series_uid=self._view.viewport_config.series_uid, volume=volume))
        if isinstance(self._view, StandalonePetVolumeController):
            # Unit ownership stays with PET MPR. Reset must never launch a
            # detached load in the reference view after MPR changes units.
            self._view._initial_unit = volume.pixel_value_meta.unit_id
            self._view._initial_upper = max(.001,
                volume.default_window.center + volume.default_window.width / 2)
            self._restore_pet_parameters()
        self._view.referenceChanged.emit()

    def _restore_pet_parameters(self):
        view, record = self._view, self._pending_pet
        if not record or view.volume is None:
            return
        for key in ("_upper", "_threshold_fraction", "_opacity", "_palette"):
            if key in record and hasattr(view, key):
                value = record[key]
                if key == "_upper" and record.get("scale"):
                    value *= view.volume.pixel_value_meta.scale_from_source / record["scale"]
                setattr(view, key, value)
        self._pending_pet = {}
        view.displayStateChanged.emit()

    def sync_state(self):
        state = self.tab._target_mpr_state
        if self._disposed or state is None:
            return
        previous, self._last_frame = self._last_frame, state.frame
        if self._link_rotation and previous is not None and not self._updating:
            delta = state.frame.mpr_to_patient[:3, :3] @ previous.mpr_to_patient[:3, :3].T
            if not np.allclose(delta, np.eye(3), atol=1e-10):
                self._updating = True
                try:
                    rotation = matrix_quaternion(ANTERIOR_BASIS.T @ delta @ view_basis(self._view.state))
                    self._view._set_state(replace(self._view.state, rotation=rotation))
                finally:
                    self._updating = False
        self._view.referenceChanged.emit()

    def move_center(self, center):
        if self._disposed:
            return
        if hasattr(self.tab, "move_center"):
            self.tab.move_center(center)
        else:
            self.tab._handle_crosshair_center_change_requested(center)

    def _camera_changed(self):
        old, self._previous_camera = self._previous_camera, self._view.state
        if self._disposed:
            return
        self.tab.viewLayoutChanged.emit()
        if self._updating or not self._link_rotation or self.tab._target_mpr_state is None:
            return
        delta = view_basis(self._view.state) @ view_basis(old).T
        q = matrix_quaternion(delta)
        length = np.linalg.norm(q[1:])
        if length < 1e-10:
            return
        self._updating = True
        try:
            axis = tuple(float(v / length) for v in q[1:])
            angle = 2 * np.arctan2(length, q[0])
            if hasattr(self.tab, "_rotate_3d"):
                self.tab._rotate_3d(axis, angle)
            else:
                self.tab._handle_mpr_3d_rotation_requested(axis, angle)
        finally:
            self._updating = False

    def snapshot(self):
        view = self._view
        pet = {key: getattr(view, key) for key in ("_upper", "_threshold_fraction", "_opacity", "_palette")
               if hasattr(view, key)} if view.volume is not None else {}
        if pet:
            pet["scale"] = view.volume.pixel_value_meta.scale_from_source
        return dict(layout=self._layout, reference=self._reference_mode, linked=self._link_rotation,
                    camera=view.state, display=view.display_state,
                    pet=pet, tool=str(self._tools.activeTool), toolSelection=self._tools.persistent_selection())

    def restore(self, record):
        self.setLinkRotation(False)
        # Restoring a workspace must neither use nor overwrite the preference.
        self._set_layout(record.get("layout", "right"))
        self.setReferenceMode(record.get("reference", "planes"))
        self.sync_state()
        if record.get("camera") is not None:
            self._view._set_state(record["camera"])
        if record.get("display") is not None:
            self._view._set_display_state(record["display"])
        self._pending_pet = dict(record.get("pet", {}))
        self._restore_pet_parameters()
        self._view.displayStateChanged.emit()
        self.setLinkRotation(record.get("linked", True))
        self._tools.restore_selection(record.get("toolSelection"), record.get("tool", "volume-rotate"))

    def dispose(self):
        self._disposed = True
        self._pending_volume = None
        self._view.dispose()
