"""One transactional render state for PET MPR and registered PET/CT tabs."""
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from dataclasses import replace
import json
from uuid import uuid4
from time import monotonic
from math import ceil

import numpy as np
from PySide6.QtCore import QObject, Property, Signal, Slot, QSaveFile, QIODevice, QUrl, QTimer, Qt

from qt_dicom_viewer.model import (MprPlane, TabType, ToolType, ViewportConfig,
                                  TwoDViewType, WindowLevel)
from qt_dicom_viewer.model.render_models import PetBatchRenderRequest
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.pet_fusion import blend_pet_ct, pet_rgb
from qt_dicom_viewer.core.mpr_rotation import (move_mpr_state_center, rotate_mpr_state_3d,
                                              rotate_crosshair_state)
from qt_dicom_viewer.core.pet_fusion import (rigid_matrix, registration_from_parameters,
    parameters_from_registration, registration_document, load_registration_document)
from qt_dicom_viewer.ui.controller.viewport.controller.pet_display_controller import PetDisplayController
from qt_dicom_viewer.ui.controller.viewport.image_2d.pet_viewport_controller import LinkedPetViewport, PetMipViewport
from .tab_controller import TabController
from .tool_controller import ToolController
from qt_dicom_viewer.i18n.widgets import QFileDialog


class PetWorkspaceController(TabController):
    _i18n_registrationStatus = Signal()
    _i18n_warning = Signal()
    settingsChanged = Signal()
    volumeViewRequested = Signal()
    snapshotCommitted = Signal(object)
    sourceClosed = Signal()

    def __init__(self, config, ct_series=None, pet_series=None, parent=None):
        self.ct_series, self.pet_series = ct_series, pet_series
        self.matrix = np.eye(4)
        self.pivot = np.zeros(3)
        self._plane = MprPlane.AXIAL
        self._compact_crosshair = True
        self._compact_overlay = True
        self._ct_window = None
        self._ct_inverted = False
        self._opacity = 0.5
        self._pet_color = "grayscale"
        self._fusion_color = "hotIron"
        self._registration_active = False
        self._registration_changed = False
        self._latest = None
        self._last_result = None
        self._requested = None
        self._committed_request = None
        self._warning = ""
        self._error = ""
        self._syncing = False
        self._applying = False
        self._closed = False
        self._registration_interaction_id = ""
        self._registration_dragging = False
        self._locator_interaction_id = ""
        self._locator_dragging = False
        self._locator_submitted_at = 0.
        self._render_revision = 0
        self._presented_revision = -1
        super().__init__(config, parent)
        self._refine_timer = QTimer(self)
        self._refine_timer.setSingleShot(True)
        self._refine_timer.setInterval(180)
        self._refine_timer.timeout.connect(self.finishRegistrationPreview)
        self._locator_timer = QTimer(self)
        self._locator_timer.setSingleShot(True)
        self._locator_timer.setTimerType(Qt.PreciseTimer)
        self._locator_timer.timeout.connect(self._submit_locator)
        settings = self._tool_controller.settingsController
        self._pet_color = "grayscale-inverted" if self.isFusion else settings.section("colormap")["pet"]
        self._default_pet_color = self._pet_color
        settings.sectionChanged.connect(self._preferences_changed)

    def _preferences_changed(self, section):
        if section == "colormap":
            self._pet_color = self._tool_controller.settingsController.section("colormap")["pet"]
            self._default_pet_color = self._pet_color
            self.settingsChanged.emit()
            self.request_render()

    def _create_tool_controller(self):
        self.pet_display = PetDisplayController(self)
        self.pet_display.invalidated.connect(self._window_display_invalidated)
        self._tool_controller = ToolController(
            tab_type=TabType.PETCT_FUSION if self.isFusion else TabType.MPR,
            modality="PT", parent=self)
        self._tool_controller.activeToolChanged.connect(self._sync_registration_tool)
        self._tool_controller.activeToolChanged.connect(self._finish_pointer_interaction)
        self._tool_controller.activeInteractionChanged.connect(self._finish_pointer_interaction)
        self._tool_controller.commandRequested.connect(self._handle_tool_command)
        self._tool_controller.resetRequested.connect(self._handle_tool_reset_requested)

    def _create_viewport_dict(self):
        pet_meta = next(m for m in self._tab_config.series_metas if m.modality.upper() == "PT")
        ct_meta = next((m for m in self._tab_config.series_metas if m.modality.upper() == "CT"), None)
        roles = ("ct", "pet", "fusion", "mip") if ct_meta else ("axial", "coronal", "sagittal")
        for role in roles:
            meta = ct_meta if role == "ct" else pet_meta
            plane = TwoDViewType.PET_MIP if role == "mip" else MprPlane.AXIAL if ct_meta else MprPlane(role)
            config = ViewportConfig(str(uuid4()), self._tab_config.tab_id, plane, meta.series_uid, meta, role)
            viewport = (PetMipViewport(config, self._tool_controller, self) if role == "mip" else
                        LinkedPetViewport(config, self._tool_controller, self))
            if role != "mip":
                viewport.crosshairCenterChangeRequested.connect(self.move_center)
                viewport.crosshairRotationRequested.connect(self._rotate_plane)
                viewport.mpr3DRotationRequested.connect(self._rotate_3d)
            self._connect_playback_viewport(viewport)
            viewport.imageUpdateRequested.connect(self.imageUpdateRequested.emit)
            viewport.cursorController.cursorInfoChanged.connect(viewport.overlayChanged.emit)
            self._viewport_dict[config.viewport_id] = viewport
            if not self._active_viewport_id or role == "fusion":
                self._active_viewport_id = config.viewport_id

    @Property(bool, constant=True)
    def isFusion(self):
        return self.ct_series is not None

    @Property(QObject, constant=True)
    def petController(self):
        return next(v for v in self._viewport_dict.values() if v.viewportRole not in ("ct", "mip"))

    @Property(str, notify=settingsChanged)
    def plane(self):
        return self._plane.value

    @Slot()
    def openVolumeView(self):
        if self.isFusion and self.ready:
            self.volumeViewRequested.emit()

    @Property(bool, notify=settingsChanged)
    def compactCrosshair(self):
        return self._compact_crosshair

    @Slot(bool)
    def setCompactCrosshair(self, compact):
        self._compact_crosshair = bool(compact)
        self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def compactOverlay(self):
        return self._compact_overlay

    @Slot(bool)
    def setCompactOverlay(self, compact):
        self._compact_overlay = bool(compact)
        self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def ctInverted(self):
        return self._ct_inverted

    @Slot()
    def toggleCtInverted(self):
        if self.isFusion and not self._closed and self._ct_window is not None:
            self._ct_inverted = not self._ct_inverted
            self.settingsChanged.emit()
            self._window_display_invalidated()

    @Property(float, notify=settingsChanged)
    def ctCenter(self):
        return self._ct_window.center if self._ct_window else 40.

    @Property(float, notify=settingsChanged)
    def ctWidth(self):
        return self._ct_window.width if self._ct_window else 400.

    @Property(float, notify=settingsChanged)
    def opacity(self):
        return self._opacity

    @Property(str, notify=settingsChanged)
    def petColorMap(self):
        return self._pet_color

    @Property(str, notify=settingsChanged)
    def fusionColorMap(self):
        return self._fusion_color

    @Property(bool, notify=settingsChanged)
    def ready(self):
        return self._last_result is not None

    @_TextProperty(str, notify=_i18n_warning, notify_name='_i18n_warning', source_notify='settingsChanged')
    def warning(self):
        return self._error or self._warning

    @property
    def ct_description(self):
        return _msg('series.sourceLabel', patient=self.ct_series.patient_name,
                    description=self.ct_series.series_description or _msg('text.0559')) if self.ct_series else ""

    @property
    def pet_description(self):
        return _msg('series.sourceLabel', patient=self.pet_series.patient_name,
                    description=self.pet_series.series_description or _msg('text.0560')) if self.pet_series else ""

    @Property(bool, notify=settingsChanged)
    def registrationActive(self):
        return self._registration_active

    @_TextProperty(str, notify=_i18n_registrationStatus, notify_name='_i18n_registrationStatus', source_notify='settingsChanged')
    def registrationStatus(self):
        if not self.isFusion:
            return ""
        if self._registration_changed and self._registration_dragging:
            return _msg('text.0561')
        if self._registration_changed:
            return _msg('text.0562')
        return ""

    @Property('QVariantList', notify=settingsChanged)
    def registrationParameters(self):
        translation, angles = parameters_from_registration(self.matrix, self.pivot)
        return [float(x) for x in (*translation, *angles)]

    def contains_viewport(self, viewport_id):
        return viewport_id == self._tab_config.tab_id or super().contains_viewport(viewport_id)

    def accepts_render_result(self, result):
        if self._closed:
            return False
        if result.response_id == self._latest:
            return True
        request = result.request
        # Only earlier transforms from the same gesture may be presented.
        # Any change of plane, unit, palette, window or tool ends this context.
        return bool(request and request.interaction_id
                    and ((request.preview and request.interaction_id == self._registration_interaction_id)
                         or (request.interaction_kind == "locator"
                             and request.interaction_id == self._locator_interaction_id))
                    and request.revision > self._presented_revision)

    def retry_initial_load(self):
        self.init_render()

    def init_render(self):
        self.request_render()

    def request_render(self, *, preview=False, finish_preview=False, locator=False, locator_final=False):
        if self._closed or self._applying:
            return
        if self._mpr_layout is not None:
            self._mpr_layout.sync_state()
        if not locator:
            self._clear_locator_context()
        if not preview and not finish_preview:
            self._registration_interaction_id = ""
            self._refine_timer.stop()
        elif preview and not self._registration_interaction_id:
            self._registration_interaction_id = str(uuid4())
        self._render_revision += 1
        self._latest = str(uuid4())
        state = self.pet_display.target
        self._requested = PetBatchRenderRequest(
            request_id=self._latest, viewport_id=self._tab_config.tab_id,
            series_uid=self.pet_series.series_instance_uid,
            ct_series_uid=self.ct_series.series_instance_uid if self.ct_series else None,
            viewports=tuple((v.viewportRole, v.viewportId) for v in self._viewport_dict.values()),
            state=self._target_mpr_state, plane=self._plane,
            value_unit=state.meta.unit_id if state else None,
            pet_window=state.window if state else None, ct_window=self._ct_window,
            ct_inverted=self._ct_inverted,
            transform=tuple(self.matrix.ravel()), opacity=self._opacity,
            pet_color_map=self._pet_color, fusion_color_map=self._fusion_color,
            preview=preview, interaction_id=self._registration_interaction_id,
            revision=self._render_revision,
            interaction_kind="locator" if locator else "registration" if self._registration_interaction_id else "",
            interaction_final=locator_final or finish_preview)
        if locator:
            self._requested = replace(self._requested, interaction_id=self._locator_interaction_id)
        self.renderRequested.emit(self._requested)

    def _slice_playback_busy(self, viewport):
        return self._applying or self._requested != self._committed_request

    def handleRenderResult(self, result):
        if not self.accepts_render_result(result):
            return
        self._applying = True
        try:
            request = result.request or self._requested
            self._presented_revision = request.revision
            intermediate = request.preview or (request.interaction_kind == "locator" and not request.interaction_final)
            if not intermediate:
                self._last_result = result
                self._committed_request = request
                self._target_mpr_state = result.state
                if self._mpr_layout is not None:
                    self._mpr_layout.accept_volume(result.pet_volume)
                    self._mpr_layout.sync_state()
                if self._initial_mpr_state is None:
                    self._initial_mpr_state = result.state
                self.pet_display.accept(result.pet_volume.pixel_value_meta, result.pet_window)
                self._ct_window = result.ct_window
                self._warning, self._error = result.warning, ""
            for frame in result.frames:
                v = self._viewport_dict[frame.viewport_id]
                if isinstance(v, LinkedPetViewport):
                    v.apply_mpr_state(self._target_mpr_state or result.state)
                    v._ct_pixels = result.ct_samples if v.viewportRole == "fusion" else None
                    v.measurementController.secondary_pixels = v._ct_pixels
                v.handleRenderResult(frame)
            self._sync_registration_tool()
            self.settingsChanged.emit()
            if not intermediate:
                self.snapshotCommitted.emit(result)
        finally:
            self._applying = False

    def handleRenderFailure(self, failure):
        if failure.request_id != self._latest or self._closed:
            return
        self.pausePlayback()
        self.pet_display.fail()
        self._registration_interaction_id = ""
        self._registration_dragging = False
        self._clear_locator_context()
        self._refine_timer.stop()
        for v in self._viewport_dict.values():
            if isinstance(v, (LinkedPetViewport, PetMipViewport)):
                v._registration_drag = None
        if self._committed_request is not None:
            request = self._committed_request
            self.matrix = np.asarray(request.transform).reshape(4, 4).copy()
            self._registration_changed = not np.allclose(self.matrix, np.eye(4))
            self._plane = request.plane
            self._ct_window = self._last_result.ct_window
            self._ct_inverted = request.ct_inverted
            self._target_mpr_state = self._last_result.state
            self._opacity = request.opacity
            self._pet_color = request.pet_color_map
            self._fusion_color = request.fusion_color_map
            for frame in self._last_result.frames:
                v = self._viewport_dict[frame.viewport_id]
                if isinstance(v, LinkedPetViewport):
                    if self.isFusion:
                        v.set_plane(request.plane)
                    v.apply_mpr_state(self._target_mpr_state)
                    v._ct_pixels = self._last_result.ct_samples if v.viewportRole == "fusion" else None
                    v.measurementController.secondary_pixels = v._ct_pixels
                v.handleRenderResult(frame)
        self._error = error_message(failure.error)
        if self._last_result is None:
            for v in self._viewport_dict.values():
                v._set_load_state("error", self._error)
        else:
            for v in self._viewport_dict.values():
                v._set_load_state("ready", self._error)
        self.settingsChanged.emit()

    def _sync_locator_positions(self):
        if self._mpr_layout is not None:
            self._mpr_layout.sync_state()
        for viewport in self._viewport_dict.values():
            if isinstance(viewport, LinkedPetViewport):
                viewport.apply_mpr_state(self._target_mpr_state)
            else:
                viewport.crosshairImagePositionChanged.emit()

    def _clear_locator_context(self):
        was_dragging = self._locator_dragging
        self._locator_interaction_id = ""
        self._locator_dragging = False
        self._locator_timer.stop()
        if was_dragging:
            for viewport in self._viewport_dict.values():
                viewport._locator_drag = None
                viewport.clearLocatorPress()

    def begin_locator_drag(self):
        self._locator_timer.stop()
        self._locator_interaction_id = str(uuid4())
        self._locator_dragging = True
        self._locator_submitted_at = 0.
        # A result from before the press cannot replace the new target.
        self._latest = None

    def _submit_locator(self):
        if self._locator_dragging:
            self._locator_submitted_at = monotonic()
            self.request_render(locator=True)

    def finish_locator_drag(self):
        self._locator_timer.stop()
        if self._locator_dragging:
            self._locator_dragging = False
            self.request_render(locator=True, locator_final=True)

    def _finish_pointer_interaction(self):
        self.finish_locator_drag()
        for viewport in self._viewport_dict.values():
            viewport._locator_drag = None
            viewport.clearLocatorPress()
            if viewport._active_drag_operation is not None:
                viewport._active_drag_operation.cancel()
            viewport._active_drag_operation = None
            viewport._active_drag_start_position = None
            viewport._fusion_window_target = None

    def move_center(self, center):
        if self._target_mpr_state is None:
            return
        self._target_mpr_state = move_mpr_state_center(self._target_mpr_state, center)
        self._sync_locator_positions()
        if self._locator_dragging:
            remaining = .033 - (monotonic() - self._locator_submitted_at)
            if remaining <= 0:
                self._locator_timer.stop()
                self._submit_locator()
            elif not self._locator_timer.isActive():
                self._locator_timer.start(ceil(remaining * 1000))
        else:
            self.request_render()

    def _rotate_plane(self, plane, angle):
        if self._target_mpr_state:
            self._target_mpr_state = rotate_crosshair_state(self._target_mpr_state, plane, angle)
            self.request_render()

    def _rotate_3d(self, axis, angle):
        if self._target_mpr_state:
            self._target_mpr_state = rotate_mpr_state_3d(self._target_mpr_state, axis, angle)
            self.request_render()

    @Slot(str)
    def setPlane(self, value):
        if not self.isFusion or value not in {p.value for p in MprPlane}:
            return
        self._plane = MprPlane(value)
        for v in self._viewport_dict.values():
            if isinstance(v, LinkedPetViewport):
                v.set_plane(self._plane)
        self.settingsChanged.emit()
        self.request_render()

    @Slot(float, float)
    def setCtWindow(self, center, width):
        if np.isfinite([center, width]).all():
            self.set_ct_window(WindowLevel(center, max(1., width)))

    def _window_display_invalidated(self):
        if self.pet_display.pending:
            self.request_render()
            return
        target = self.pet_display.target
        for view in self._viewport_dict.values():
            pixels = view._modality_pixel
            if pixels is None:
                continue
            if view.viewportRole == "ct":
                image = DicomLoader.apply_window(pixels, self._ct_window, self._ct_inverted)
                view._state = replace(view._state, window=self._ct_window, inverted=self._ct_inverted)
            else:
                if target is None or view._frame_meta.pixel_value_meta.unit_id != target.meta.unit_id:
                    continue
                gray = DicomLoader.apply_window(pixels, target.window, False, target.minimum)
                if view.viewportRole == "fusion":
                    if view._ct_pixels is None:
                        continue
                    ct_gray = DicomLoader.apply_window(view._ct_pixels, self._ct_window, self._ct_inverted)
                    image = blend_pet_ct(ct_gray, gray, pixels, self._opacity, self._fusion_color)
                else:
                    image = gray if self._pet_color == "grayscale" else pet_rgb(gray, self._pet_color)
            view.present_display_image(image)
            view.overlayChanged.emit()
        self.request_render()

    def set_ct_window(self, window):
        self._ct_window = window
        self.settingsChanged.emit()
        self._window_display_invalidated()

    @Slot(float)
    def setOpacity(self, value):
        if np.isfinite(value):
            self._opacity = float(np.clip(value, 0, 1))
            self.settingsChanged.emit()
            self.request_render()

    @Slot(str)
    def setPetColorMap(self, value):
        from qt_dicom_viewer.core.color_maps import COLOR_MAPS
        if value in COLOR_MAPS and value != self._pet_color:
            self._pet_color = value
            self.settingsChanged.emit()
            self.request_render()

    @Slot(str)
    def setFusionColorMap(self, value):
        from qt_dicom_viewer.core.color_maps import COLOR_MAPS
        if value in COLOR_MAPS and value != self._fusion_color:
            self._fusion_color = value
            self.settingsChanged.emit()
            self.request_render()

    def synchronize_view(self, origin):
        if not self.isFusion or self._syncing or self._applying or origin.viewportRole == "mip":
            return
        self._syncing = True
        try:
            fields = ("zoom", "pan_x", "pan_y", "rotation_degrees", "horizontal_flip", "vertical_flip")
            for v in self._viewport_dict.values():
                if v is origin or v.viewportRole == "mip" or v.viewportType != origin.viewportType:
                    continue
                v._state = replace(v._state, **{f: getattr(origin._state, f) for f in fields})
                v.transformChanged.emit()
                v.directionLabelsChanged.emit()
                v.overlayChanged.emit()
        finally:
            self._syncing = False

    @Slot(bool)
    def setRegistrationActive(self, enabled):
        if not self.isFusion or (enabled and not self.ready):
            return
        if enabled:
            self._tool_controller.activateTool(ToolType.REGISTRATION.value)
        elif self._tool_controller.activeTool == ToolType.REGISTRATION:
            self._tool_controller.activateTool(ToolType.CT_WINDOW.value)
        self._sync_registration_tool()

    def _sync_registration_tool(self):
        enabled = bool(self.isFusion and self.ready
                       and self._tool_controller.activeTool == ToolType.REGISTRATION)
        if enabled == self._registration_active:
            return
        if not enabled and self._registration_interaction_id:
            self.finishRegistrationPreview()
        if enabled:
            self.pivot = np.asarray(self._target_mpr_state.frame.center_patient)
        self._registration_active = enabled
        for v in self._viewport_dict.values():
            v.cancelMeasurement()
            if isinstance(v, (LinkedPetViewport, PetMipViewport)):
                v._registration_drag = None
                v._locator_drag = None
                v.clearLocatorPress()
            v.overlayChanged.emit()
        self.settingsChanged.emit()

    def begin_registration_drag(self):
        self._refine_timer.stop()
        self._registration_interaction_id = str(uuid4())
        self._registration_dragging = True

    @Slot()
    def finishRegistrationPreview(self):
        self._refine_timer.stop()
        self._registration_dragging = False
        if self._registration_interaction_id:
            self.request_render(finish_preview=True)

    def set_registration(self, matrix, *, preview=False):
        self.matrix = rigid_matrix(matrix)
        self._registration_changed = True
        self.settingsChanged.emit()
        self.request_render(preview=preview)
        if preview and not self._registration_dragging:
            self._refine_timer.start()

    @Slot(int, float)
    def setRegistrationParameter(self, index, value):
        if not self.isFusion or not self.ready or not 0 <= index < 6 or not np.isfinite(value):
            return
        values = self.registrationParameters
        values[index] = value
        self.set_registration(registration_from_parameters(values[:3], values[3:], self.pivot), preview=True)

    @Slot('QVariantList')
    def setRegistrationParameters(self, values):
        if not self.isFusion or not self.ready or not self.registrationActive or len(values) != 6:
            return
        try:
            parameters = np.asarray(values, dtype=float)
        except (TypeError, ValueError):
            return
        if parameters.shape != (6,) or not np.all(np.isfinite(parameters)) or np.any(np.abs(parameters) > 10000):
            return
        self._refine_timer.stop()
        self.set_registration(registration_from_parameters(parameters[:3], parameters[3:], self.pivot))

    @Slot()
    def centerAlign(self):
        if not self.isFusion or not self.ready:
            return
        result = self._last_result
        matrix = self.matrix.copy()
        matrix[:3, 3] = (np.asarray(result.ct_volume.geometry.center_patient)
                        - matrix[:3, :3] @ result.pet_volume.geometry.center_patient)
        self.set_registration(matrix)

    @Slot()
    def resetRegistration(self):
        self.matrix = np.eye(4)
        self._registration_changed = False
        self.settingsChanged.emit()
        self.request_render()

    def _document(self):
        if not self.isFusion or not self.ready:
            raise ValueError(_msg('text.0563'))
        return registration_document(self._last_result.ct_volume, self._last_result.pet_volume,
            self.ct_series.frame_of_reference_uid, self.pet_series.frame_of_reference_uid,
            self.matrix, self.pivot)

    @Slot()
    def saveRegistration(self):
        path, _ = QFileDialog.getSaveFileName(None, _msg('text.0564'), "petct-registration.json", "JSON (*.json)")
        if path:
            self.save_registration_to(path)

    def save_registration_to(self, path):
        try:
            data = json.dumps(self._document(), ensure_ascii=False, indent=2).encode()
            file = QSaveFile(str(path))
            if not file.open(QIODevice.WriteOnly) or file.write(data) != len(data) or not file.commit():
                raise OSError(file.errorString())
            self._error = ""
        except (ValueError, OSError) as error:
            self._error = error_message(error)
        self.settingsChanged.emit()

    @Slot()
    def loadRegistration(self):
        path, _ = QFileDialog.getOpenFileName(None, _msg('text.0565'), "", "JSON (*.json)")
        if path:
            self.load_registration_from(path)

    def load_registration_from(self, path):
        try:
            with open(path, encoding="utf-8") as stream:
                document = json.load(stream)
            matrix, pivot = load_registration_document(document, self._document())
            self.pivot = pivot
            self._error = ""
            self.set_registration(matrix)
        except (ValueError, OSError, TypeError, AttributeError) as error:
            self._error = error_message(error)
        self.settingsChanged.emit()

    def _handle_tool_command(self, command):
        if command == "viewport:reset":
            self._target_mpr_state = self._initial_mpr_state
            self._ct_inverted = False
            if self._last_result and self._last_result.ct_volume:
                self._ct_window = self._last_result.ct_volume.default_window
            self.settingsChanged.emit()
            self.pet_display.reset()
            for v in self._viewport_dict.values():
                v.reset_all_view_state(reset_slice=False)
            self.request_render()

    def _handle_tool_reset_requested(self, value):
        if value == "registration":
            self.resetRegistration()
        elif value == "ct-window":
            self._ct_inverted = False
            if self._last_result:
                self.set_ct_window(self._last_result.ct_volume.default_window)
        elif value == "pet-window":
            self.pet_display.reset()
        elif value == "viewport-settings":
            self.setCompactCrosshair(True)
            self.setCompactOverlay(True)
            self.activeViewport.reset_tool_state(ToolType.VIEWPORT_SETTINGS)
        elif value == "window":
            self.pet_display.reset()
        elif value == "pseudocolor":
            self._pet_color = self._default_pet_color
            self._fusion_color = "hotIron"
            self.settingsChanged.emit()
            self.request_render()
        elif value == "fusion-blend":
            self.setOpacity(0.5)
        elif value == "mpr-rotate-3d":
            self._target_mpr_state = self._initial_mpr_state
            self.request_render()
        elif self.activeViewport:
            self.activeViewport.reset_tool_state(ToolType(value))

    def dispose(self):
        self._closed = True
        self._clear_locator_context()
        self.sourceClosed.emit()
        self._refine_timer.stop()
        self._locator_timer.stop()
        super().dispose()
