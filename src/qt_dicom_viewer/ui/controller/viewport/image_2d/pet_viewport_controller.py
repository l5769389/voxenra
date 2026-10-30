from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from dataclasses import replace
from math import atan2

import numpy as np
from PySide6.QtCore import Property, Signal, Slot, QPointF, QObject

from qt_dicom_viewer.model import (MprPlane, WindowLevel, ImagePoint, InteractionType,
                                  CrosshairTargetKind, PointerPosition, Point, ToolType)
from qt_dicom_viewer.model.interaction import WindowLevelContext
from qt_dicom_viewer.ui.controller.viewport.operation.window_level_operation import WindowLevelOperation, WindowLevelInteractionConfig
from qt_dicom_viewer.model.render_models import PetMipRenderResult
from qt_dicom_viewer.core.mpr_rotation import axis_angle_rotation_matrix
from qt_dicom_viewer.core.color_maps import COLOR_MAPS
from .image_2d_viewport_controller import (Image2DViewportController, PET_SUV_WINDOW_LEVEL_CONFIG,
                                         PET_NATIVE_WINDOW_LEVEL_CONFIG)
from .mpr_viewport_controller import MprViewportController, _CROSSHAIR_STYLES
from qt_dicom_viewer.model.ui_models import CrosshairStyle


def _compact_locator_style(style):
    # Keep the central gap and grab geometry, with a screen-space stroke and
    # dark halo that remain legible over both high uptake and CT bone.
    style.update(centerGap=8, armLength=8, outlineWidth=1, outlineColor="#e6000000")
    for axis in ("horizontal", "vertical"):
        style[axis + "Width"] = max(2, style.get(axis + "Width", style["lineWidth"]))
        color = style[axis + "Color"]
        style[axis + "Color"] = {
            "#ff0000": "#ff6060", "#008000": "#4ee08a", "#0000ff": "#668cff",
        }.get(color.lower(), color)
    return style


def _begin_fusion_window(view, x, y, buttons, valid, column, row):
    """Latch the chosen modality at pointer-down, including in the fused pane."""
    view._fusion_window_target = None
    if (not buttons & 1 or not view.owner.isFusion
            or view._tool_controller.active_interaction != InteractionType.WINDOW):
        return False
    view._active_drag_operation = view._active_drag_start_position = None
    view.cancelMeasurement()
    target = "ct" if view._tool_controller.activeTool == ToolType.CT_WINDOW else "pet"
    eligible = ("ct", "fusion") if target == "ct" else ("pet", "fusion", "mip")
    if view.viewportRole not in eligible or not valid:
        return True
    view._fusion_window_target = target
    window = view.owner._ct_window if target == "ct" else view.owner.pet_display.target.window
    config = (WindowLevelInteractionConfig(allow_inversion=False) if target == "ct" else
              PET_SUV_WINDOW_LEVEL_CONFIG if view.owner.pet_display.target.meta.is_suv else PET_NATIVE_WINDOW_LEVEL_CONFIG)
    position = PointerPosition(Point(x, y), ImagePoint(column, row))
    view._active_drag_operation = WindowLevelOperation(config)
    view._active_drag_start_position = position
    view._active_drag_operation.begin(position, WindowLevelContext(view.viewport_size, False, window))
    return True


class LinkedPetViewport(MprViewportController):
    # PySide needs a local notifier here: a grandparent Signal descriptor
    # produces an invalid meta-object signal index when QML wraps this class.
    _i18n_secondaryCursorText = Signal()

    linkedOverlayChanged = Signal()
    def __init__(self, config, tools, owner):
        self.owner = owner
        self._registration_drag = None
        self._fusion_window_target = None
        self._locator_drag = None
        self._locator_press = None
        self._press_captured = False
        self._starting_nonlocator_drag = False
        self._ct_pixels = None
        super().__init__(config, tools, owner)
        if config.role == "fusion":
            self._state = replace(self._state, display_settings=replace(
                self._state.display_settings, show_color_bar=True))
        self._pet_display = owner.pet_display
        self._pet_display.changed.connect(self.petDisplayChanged.emit)
        self._pet_display.changed.connect(self.overlayChanged.emit)
        self.transformChanged.connect(lambda: owner.synchronize_view(self))
        self.overlayChanged.connect(self.linkedOverlayChanged.emit)
        owner.settingsChanged.connect(self.displayStyleChanged.emit)
        # Some QML paths expose the inherited viewport type. Notify both its
        # overlay property and the derived one via the existing signal bridge.
        owner.settingsChanged.connect(self.overlayChanged.emit)
        owner.settingsChanged.connect(self.preferencesChanged.emit)

    def request_render(self):
        self.owner.request_render()

    def _preferences_changed(self, section):
        # The owner commits one palette change for all linked PET views.
        if section == "colormap":
            return
        super()._preferences_changed(section)

    @Slot(str)
    def applyColorMap(self, color_map):
        if self.viewportRole == "ct":
            return
        elif self.viewportRole == "fusion":
            self.owner.setFusionColorMap(color_map)
        else:
            self.owner.setPetColorMap(color_map)

    @Property(str, notify=linkedOverlayChanged)
    def activeColorMap(self):
        if self.viewportRole == "ct":
            return "grayscale"
        return self.owner.fusionColorMap if self.viewportRole == "fusion" else self.owner.petColorMap

    @Property(str, notify=linkedOverlayChanged)
    def canvasBackgroundColor(self):
        if self.viewportRole not in ("ct", "fusion"):
            return COLOR_MAPS[self.owner.petColorMap][1][0]
        return Image2DViewportController.canvasBackgroundColor.fget(self)

    @Property('QVariantMap', notify=Image2DViewportController.preferencesChanged)
    def crosshairStyle(self):
        style = MprViewportController.crosshairStyle.fget(self)
        if self.owner.compactCrosshair:
            return _compact_locator_style(style)
        return style

    def _crosshair_hit_test(self, position, center_tolerance, line_tolerance):
        if not self.showLocalizer or self._plane_geometry is None:
            return None
        # The shared MPR hit test handles pixel-to-mm conversion. Preserve the
        # larger target for the compact locator without converting twice.
        target = super()._crosshair_hit_test(position, center_tolerance *
            (2 if self.owner.compactCrosshair else 1), line_tolerance)
        if self._starting_nonlocator_drag and target == CrosshairTargetKind.CENTER:
            return None
        if self.owner.compactCrosshair and target != CrosshairTargetKind.CENTER:
            return None
        return target

    @Slot(bool, float, float, float, float, float, float)
    def selectMeasurementAt(self, valid, column, row, endpoint_tolerance, line_tolerance, *args):
        if (valid and not self.owner.registrationActive and self._plane_geometry
                and self._tool_controller.active_interaction in
                (InteractionType.WINDOW, InteractionType.SCROLL, InteractionType.PAN,
                 InteractionType.ZOOM, InteractionType.NONE)):
            self._apply_crosshair_move(ImagePoint(column, row))
            return
        super().selectMeasurementAt(valid, column, row, endpoint_tolerance, line_tolerance, *args)

    def set_plane(self, plane):
        self.viewport_config = replace(self.viewport_config, viewport_type=plane)
        self._crosshair_style = CrosshairStyle(_CROSSHAIR_STYLES[plane])
        self._plane_geometry = None
        self.viewportTypeChanged.emit()
        self.directionLabelsChanged.emit()
        self.crosshairImagePositionChanged.emit()

    def apply_window_level(self, result):
        if self._fusion_window_target == "ct" or self.viewportRole == "ct":
            self.owner.set_ct_window(result.window)
        else:
            super().apply_window_level(result)

    @Slot(float, float)
    def applyWindowPreset(self, center, width):
        if self.viewportRole == "ct":
            self.owner.set_ct_window(WindowLevel(center, max(1., width)))
        else:
            self.setPetDisplayUpper(center + width / 2)

    @_TextProperty('QVariantMap', notify=MprViewportController._i18n_overlayInfo, notify_name='_i18n_overlayInfo', source_notify='linkedOverlayChanged')
    def overlayInfo(self):
        info = Image2DViewportController.overlayInfo.fget(self)
        from qt_dicom_viewer.ui.reading_identity import format_study_date
        info.update(ctStudyDate=format_study_date(self.owner.ct_series.study_date) or "--" if self.owner.ct_series else "",
                    petStudyDate=format_study_date(self.owner.pet_series.study_date) or "--")
        info.update(viewRole=self.viewportRole,
                    fusionWarning=self.owner.warning,
                    ctSeries=self.owner.ct_series.series_description if self.owner.ct_series else "",
                    petSeries=self.owner.pet_series.series_description)
        if self.owner._ct_window:
            info.update(ctWindowCenter=f"{self.owner._ct_window.center:g}",
                        ctWindowWidth=f"{self.owner._ct_window.width:g}")
        info["compactOverlay"] = self.owner.compactOverlay
        info["suppressIdentifiers"] = self.owner.isFusion
        # These planes are resampled in CT space. Their navigation index is not
        # a PET source-instance number; show physical location and source count.
        series = self.owner.ct_series if self.viewportRole == "ct" else self.owner.pet_series
        info["sourceSliceCount"] = str(series.dicom_file_count)
        return info

    @_TextProperty(str, notify=_i18n_secondaryCursorText, notify_name='_i18n_secondaryCursorText', source_notify='linkedOverlayChanged')
    def secondaryCursorText(self):
        p = self.cursorController._pointer_meta
        if self.viewportRole != "fusion" or self._ct_pixels is None or p is None:
            return ""
        row, col = int(p.pointer_y), int(p.pointer_x)
        if 0 <= row < self._ct_pixels.shape[0] and 0 <= col < self._ct_pixels.shape[1]:
            value = self._ct_pixels[row, col]
            return f"CT: {value:.1f} HU" if np.isfinite(value) else "CT: -- HU"
        return "CT: -- HU"

    @Slot(float, float, int, bool, float, float, float, float)
    def beginInteraction(self, x, y, buttons, image_valid, column, row, endpoint_tolerance, line_tolerance):
        if not self._press_captured:
            self.captureLocatorPress(x, y, buttons, image_valid, column, row, endpoint_tolerance, line_tolerance)
        locator = self._locator_press
        self._locator_press, self._press_captured = None, False
        if locator is not None:
            self.cancelMeasurement()
            self._active_drag_operation = None
            self._annotation_drag_active = False
            self._registration_drag = None
            self._locator_drag = locator
            self.owner.begin_locator_drag()
            return
        if (self.owner.registrationActive and self.viewportRole in ("pet", "fusion")
                and self._plane_geometry and image_valid and buttons & 3):
            self.cancelMeasurement()
            self.owner.begin_registration_drag()
            self._registration_drag = (np.array([column, row]), self.owner.matrix.copy(), buttons,
                                       self._plane_geometry, self.owner.pivot.copy())
            return
        if _begin_fusion_window(self, x, y, buttons, image_valid, column, row):
            return
        # A later reconstruction may move the marker under the press position.
        # Only the original pointer-down decision may start a locator drag.
        self._starting_nonlocator_drag = True
        try:
            super().beginInteraction(x, y, buttons, image_valid, column, row, endpoint_tolerance, line_tolerance)
        finally:
            self._starting_nonlocator_drag = False

    @Slot(float, float, int, bool, float, float, float, float, result=bool)
    def captureLocatorPress(self, x, y, buttons, valid, column, row, point_tolerance, line_tolerance):
        self._press_captured = True
        self._locator_press = None
        position = PointerPosition(Point(x, y), ImagePoint(column, row))
        if self.activeInteraction == "rotate":
            return False
        if buttons & 1 and self._crosshair_hit_test(position, point_tolerance, line_tolerance) == CrosshairTargetKind.CENTER:
            center = self._crosshair_image_position
            self._locator_press = (self._plane_geometry, center.column-column, center.row-row)
        return self._locator_press is not None

    @Slot()
    def clearLocatorPress(self):
        self._locator_press, self._press_captured = None, False

    @Slot(float, float, result=bool)
    def updateRegistrationDrag(self, column, row):
        if self._locator_drag is not None:
            if np.isfinite([column, row]).all():
                geometry, dx, dy = self._locator_drag
                self.owner.move_center(geometry.image_point_to_patient(column=column+dx, row=row+dy))
            return True
        if self._registration_drag is None:
            return False
        start, initial, buttons, g, pivot = self._registration_drag
        if g is None or not np.isfinite([column, row]).all():
            return True
        step = np.eye(4)
        if buttons & 2:
            index = g.patient_to_image_index @ np.array([*pivot, 1])
            center = np.array([index[2], index[1]])
            a = (start-center) * [g.column_spacing, g.row_spacing]
            b = (np.array([column, row])-center) * [g.column_spacing, g.row_spacing]
            if np.linalg.norm(a) < 1e-6 or np.linalg.norm(b) < 1e-6:
                return True
            angle = atan2(b[1], b[0]) - atan2(a[1], a[0])
            rotation = axis_angle_rotation_matrix(tuple(np.cross(g.column_direction_patient,
                                                                 g.row_direction_patient)), angle)
            step[:3, :3] = rotation
            step[:3, 3] = pivot - rotation @ pivot
        else:
            delta = np.array([column, row]) - start
            step[:3, 3] = (delta[0] * g.column_spacing * np.asarray(g.column_direction_patient)
                           + delta[1] * g.row_spacing * np.asarray(g.row_direction_patient))
        self.owner.set_registration(step @ initial, preview=True)
        return True

    @Slot(float, float, bool, float, float)
    def endInteraction(self, *args):
        self.clearLocatorPress()
        if self._locator_drag is not None:
            self.updateRegistrationDrag(args[3], args[4])
            self._locator_drag = None
            self.owner.finish_locator_drag()
            return
        if self._registration_drag is not None:
            self.updateRegistrationDrag(args[3], args[4])
            self._registration_drag = None
            self.owner.finishRegistrationPreview()
            return
        super().endInteraction(*args)


class PetMipViewport(Image2DViewportController):


    def __init__(self, config, tools, owner):
        self.owner = owner
        self._mip_result = None
        self._fusion_window_target = None
        self._locator_press = self._locator_drag = None
        self._press_captured = False
        self._locator_hover = False
        super().__init__(config, tools, owner)
        self._pet_display = owner.pet_display
        self._pet_display.changed.connect(self.petDisplayChanged.emit)
        self._pet_display.changed.connect(self.overlayChanged.emit)
        owner.settingsChanged.connect(self.displayStyleChanged.emit)
        owner.settingsChanged.connect(self.overlayChanged.emit)
        owner.settingsChanged.connect(self.preferencesChanged.emit)

    def _preferences_changed(self, section):
        if section != "colormap":
            super()._preferences_changed(section)

    @Slot(str)
    def applyColorMap(self, color_map):
        self.owner.setPetColorMap(color_map)

    @Property(str, notify=Image2DViewportController.displayStyleChanged)
    def activeColorMap(self):
        return self.owner.petColorMap

    @Property(str, notify=Image2DViewportController.displayStyleChanged)
    def canvasBackgroundColor(self):
        return COLOR_MAPS[self.owner.petColorMap][1][0]

    @Property(int, notify=Image2DViewportController.sliceChanged)
    def sliceCount(self):
        return 0

    def request_render(self):
        self.owner.request_render()

    def apply_window_level(self, result):
        if self._fusion_window_target == "ct":
            self.owner.set_ct_window(result.window)
        else:
            super().apply_window_level(result)

    def _validate_render_result(self, result):
        if not isinstance(result, PetMipRenderResult):
            raise TypeError("Expected PET MIP result")

    def _apply_specific_render_result(self, result):
        self._mip_result = result
        self.crosshairImagePositionChanged.emit()

    def apply_slice_index(self, index):
        pass

    def _measurement_context(self, *args):
        return None

    @Slot(bool, float, float, float, float, float, float)
    def selectMeasurementAt(self, valid, column, row, *args):
        result = self._mip_result
        if (not valid or result is None or result.preview
                or self.owner.registrationActive or self.activeInteraction == "rotate"):
            return
        self._move_to_peak(result, column, row)

    def _move_to_peak(self, result, column, row):
        if not np.isfinite([column, row]).all():
            return
        r, c = int(round(row)), int(round(column))
        if 0 <= r < result.peak_positions.shape[0] and 0 <= c < result.peak_positions.shape[1]:
            point = result.peak_positions[r, c]
            if np.isfinite(point).all():
                self.owner.move_center(tuple(float(x) for x in point))

    def _locator_hit(self, column, row, tolerance):
        if not self.showLocalizer or self._mip_result is None or self._mip_result.preview:
            return False
        g, center = self._mip_result.plane_geometry, self.crosshairImagePosition
        distance = np.hypot((column-center.x())*g.column_spacing, (row-center.y())*g.row_spacing)
        return bool(distance <= tolerance*min(g.column_spacing, g.row_spacing)*2)

    def _handle_specific_pointer_hover(self, context):
        point = context.position.image
        hit = bool(self.activeInteraction != "rotate" and point
                   and self._locator_hit(point.column, point.row, context.point_tolerance))
        if hit != self._locator_hover:
            self._locator_hover = hit
            self.crosshairHoverTargetChanged.emit()

    @Property(str, notify=Image2DViewportController.crosshairHoverTargetChanged)
    def crosshairHoverTarget(self):
        return "center" if self._locator_hover else ""

    @Slot(float, float, int, bool, float, float, float, float, result=bool)
    def captureLocatorPress(self, x, y, buttons, valid, column, row, point_tolerance, line_tolerance):
        self._press_captured = True
        self._locator_press = None
        if self.activeInteraction == "rotate":
            return False
        if buttons & 1 and self._locator_hit(column, row, point_tolerance):
            center = self.crosshairImagePosition
            self._locator_press = (self._mip_result, center.x()-column, center.y()-row)
        return self._locator_press is not None

    @Slot()
    def clearLocatorPress(self):
        self._locator_press, self._press_captured = None, False

    @Slot(float, float, int, bool, float, float, float, float)
    def beginInteraction(self, x, y, buttons, valid, column, row, point_tolerance, line_tolerance):
        if not self._press_captured:
            self.captureLocatorPress(x, y, buttons, valid, column, row, point_tolerance, line_tolerance)
        self._locator_drag = self._locator_press
        self.clearLocatorPress()
        if self._locator_drag is not None:
            self.cancelMeasurement()
            self._active_drag_operation = None
            self._annotation_drag_active = False
            self.owner.begin_locator_drag()
            return
        if not _begin_fusion_window(self, x, y, buttons, valid, column, row):
            super().beginInteraction(x, y, buttons, valid, column, row, point_tolerance, line_tolerance)

    @Slot(float, float, result=bool)
    def updateRegistrationDrag(self, column, row):
        if self._locator_drag is None:
            return False
        result, dx, dy = self._locator_drag
        self._move_to_peak(result, column+dx, row+dy)
        return True

    @Slot(float, float, bool, float, float)
    def endInteraction(self, *args):
        self.clearLocatorPress()
        if self._locator_drag is not None:
            self.updateRegistrationDrag(args[3], args[4])
            self._locator_drag = None
            self.owner.finish_locator_drag()
            return
        super().endInteraction(*args)

    @_TextProperty('QVariantMap', notify=Image2DViewportController._i18n_overlayInfo, notify_name='_i18n_overlayInfo', source_notify='Image2DViewportController.overlayChanged')
    def overlayInfo(self):
        info = Image2DViewportController.overlayInfo.fget(self)
        info.update(viewRole="mip", viewType="PET MIP",
                    compactOverlay=self.owner.compactOverlay, suppressIdentifiers=self.owner.isFusion)
        if self._mip_result is not None and self._mip_result.preview:
            info.update(viewType="PET MIP · Preview", registrationPreview=True)
        return info

    @Property(bool, constant=True)
    def hasCrosshair(self):
        return True

    @Property('QVariantMap', notify=Image2DViewportController.overlayChanged)
    def crosshairStyle(self):
        style = {"centerGap": 8, "lineWidth": 1, "horizontalColor": "#ff5555", "verticalColor": "#5577ff"}
        if self.owner.compactCrosshair:
            return _compact_locator_style(style)
        return style

    @Property(QPointF, notify=Image2DViewportController.crosshairImagePositionChanged)
    def crosshairImagePosition(self):
        if self._mip_result is None or self.owner._target_mpr_state is None:
            return QPointF(-1, -1)
        p = self._mip_result.plane_geometry.patient_to_image_index @ np.array(
            [*self.owner._target_mpr_state.frame.center_patient, 1])
        return QPointF(float(p[2]), float(p[1]))
