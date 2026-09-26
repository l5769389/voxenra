from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from qt_dicom_viewer.i18n.messages import error_message
import logging
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from dataclasses import replace
from math import isfinite

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot, Property, QPointF, Qt

from qt_dicom_viewer.ui.controller.viewport.mouse_bindings import drag_interaction

from qt_dicom_viewer.core.color_maps import COLOR_MAPS, apply_color_map
from qt_dicom_viewer.core.patient_orientation import (
    displayed_image_edge_labels,
)
from qt_dicom_viewer.model import ViewportState, ViewportConfig, RenderRequest, RenderResult, \
    WindowLevel, FrameDisplayMeta, InteractionType, Point, Offset, DragUpdateEvent, \
    DisplayStyle, ViewportDisplaySettings, ViewportTransformAction, PointerPosition, ImagePoint, MeasurementKind, OperationStartContext, ToolType, \
    PointerHoverContext
from qt_dicom_viewer.model.interaction import InteractionResult, SliceIndexChange, WindowLevelChange, PanChange, \
    ZoomChange, WindowLevelContext, ScrollContext, PanContext, ZoomContext, MeasureContext
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.controller.viewport.controller.cursor_controller import CursorController
from qt_dicom_viewer.ui.controller.viewport.controller.measure.measure_controller import MeasurementController
from qt_dicom_viewer.ui.controller.viewport.controller.overlay_presenter import OverlayPresenter
from qt_dicom_viewer.ui.controller.viewport.controller.text_annotation_controller import (
    TextAnnotationController,
)
from qt_dicom_viewer.core.pseudocolor import (
    COLOR_MAP_SPECS,
    color_map_options,
)
from qt_dicom_viewer.ui.controller.viewport.operation.drag_operation import DragOperation
from qt_dicom_viewer.ui.controller.viewport.operation.pan_operation import PanOperation
from qt_dicom_viewer.ui.controller.viewport.operation.scroll_operation import ScrollOperation
from qt_dicom_viewer.ui.controller.viewport.operation.window_level_operation import (
    WindowLevelInteractionConfig,
    MR_WINDOW_LEVEL_CONFIG,
    WindowLevelOperation,
)
from qt_dicom_viewer.ui.controller.viewport.operation.zoom_operation import ZoomOperation
from qt_dicom_viewer.ui.controller.viewport.viewport_controller import ViewportController

from qt_dicom_viewer.ui.controller.viewport.controller.pet_display_controller import PetDisplayController

logger = logging.getLogger(__name__)

MEASUREMENT_KINDS = {
    InteractionType.MEASURE_LENGTH: MeasurementKind.LENGTH,
    InteractionType.ANNOTATE_ARROW: MeasurementKind.ARROW,
    InteractionType.MEASURE_ANGLE: MeasurementKind.ANGLE,
    InteractionType.MEASURE_RECT: MeasurementKind.RECT,
    InteractionType.MEASURE_ELLIPSE: MeasurementKind.ELLIPSE,
    InteractionType.MEASURE_CURVE: MeasurementKind.CURVE,
    InteractionType.MEASURE_FREEHAND: MeasurementKind.FREEHAND,
}

DISPLAY_STYLES = {
    color_map: DisplayStyle(
        color_map=color_map,
        no_data_color="#{:02x}{:02x}{:02x}".format(*stops[0][1]),
    )
    for color_map, (_, stops) in COLOR_MAP_SPECS.items()
}

COLOR_MAP_OPTIONS = color_map_options()

VIEWPORT_SETTING_FIELDS = {
    "window-annotations": "show_window_annotations",
    "hide-sensitive-info": "hide_sensitive_info",
    "scale-bar": "show_scale_bar",
    "color-bar": "show_color_bar",
    "dicom-overlay": "show_dicom_overlay",
    "localizer": "show_localizer",
    "fit-to-window": "fit_to_window",
}

PET_SUV_WINDOW_LEVEL_CONFIG = WindowLevelInteractionConfig(
    minimum_width=0.01,
    minimum_width_control_range=1.0,
    max_width_control_range=1_000_000_000.0,
    minimum_center_control_range=1.0,
    max_center_control_range=1_000_000_000.0,
    fixed_lower_bound=0.0,
)

PET_NATIVE_WINDOW_LEVEL_CONFIG = WindowLevelInteractionConfig(
    minimum_width=0.001,
    minimum_width_control_range=1.0,
    max_width_control_range=1_000_000_000.0,
    minimum_center_control_range=1.0,
    max_center_control_range=1_000_000_000.0,
    fixed_lower_bound=0.0,
)


def _make_pointer_position(
        viewport_x: float,
        viewport_y: float,
        image_valid: bool,
        column: float,
        row: float,
        *,
        include_outside_image: bool = False,
) -> PointerPosition:
    image_point = None

    if (
            (image_valid or include_outside_image)
            and isfinite(column)
            and isfinite(row)
    ):
        image_point = ImagePoint(
            column=column,
            row=row,
        )

    return PointerPosition(
        viewport=Point(
            x=viewport_x,
            y=viewport_y,
        ),
        image=image_point,
    )


class Image2DViewportController(ViewportController):
    _i18n_colorMapOptions = Signal()
    _i18n_errorMessage = Signal()
    _i18n_overlayInfo = Signal()
    _i18n_petActiveUnitLabel = Signal()
    _i18n_petControlUpperOptions = Signal()
    _i18n_petUnitOptions = Signal()
    _i18n_quantificationWarning = Signal()
    _i18n_windowPresets = Signal()


    imageSourceChanged = Signal()
    overlayChanged = Signal()
    imageDimensionChanged = Signal()
    sliceChanged = Signal()
    transformChanged = Signal()
    displayStyleChanged = Signal()
    viewportSettingsChanged = Signal()
    preferencesChanged = Signal()
    crosshairImagePositionChanged = Signal()
    crosshairHoverTargetChanged = Signal()
    regionCursorKindChanged = Signal()
    activeInteractionChanged = Signal()
    directionLabelsChanged = Signal()
    windowPresetsChanged = Signal()
    loadStateChanged = Signal()
    petDisplayChanged = Signal()
    hit_tolerance = 6

    def __init__(self, viewport_config: ViewportConfig, tool_controller: ToolController, parent=None):
        super().__init__(viewport_config=viewport_config, parent=parent)
        self._modality_pixel: np.ndarray | None = None
        self._state = ViewportState(
            slice_index=self._initial_slice_index(),
            slice_count=None,
        )
        self._image_revision = 0
        self._latest_request_id: str | None = None
        self.render_pending = False
        self._has_image = False
        self._load_state = "idle"
        self._error_message = ""
        self._frame_meta: FrameDisplayMeta | None = None
        self._baseline_window: WindowLevel | None = None
        self._baseline_slice_index: int | None = None
        self._tool_controller = tool_controller
        self._settings_controller = tool_controller.settingsController
        self._measure_controller = MeasurementController(self)
        self._text_annotation_controller = TextAnnotationController(self)
        self._mtf_controller = None
        self._fwhm_controller = None
        self._qa_controller = None
        self._set_default_color_map()
        annotation_style = self._settings_controller.section("measurement")
        self._annotation_style_defaults = dict(color=annotation_style["annotationColor"], font_size=annotation_style["fontSize"])
        self._text_annotation_controller.applyStyleDefaults(**self._annotation_style_defaults)
        self._settings_controller.sectionChanged.connect(self._preferences_changed)
        self._tool_controller.windowPresetsChanged.connect(self.windowPresetsChanged.emit)
        self._tool_controller.activeInteractionChanged.connect(
            self._handle_active_interaction_changed
        )
        self._scroll_operation = ScrollOperation()
        self._pan_operation = PanOperation()
        self._zoom_operation = ZoomOperation()
        self._cursor_controller = CursorController(viewport_config=self.viewport_config, parent=self)
        self._overlay_presenter = OverlayPresenter()
        self._active_drag_operation: DragOperation | None = None
        self._window_level_operation = WindowLevelOperation()
        self._window_config_mode = "default"
        self._pet_display = PetDisplayController(self)
        self._pet_display.changed.connect(self.petDisplayChanged.emit)
        self._pet_display.changed.connect(self.overlayChanged.emit)
        self._pet_display.invalidated.connect(self._pet_display_invalidated)
        self._latest_request_id = None
        self._content_key = None
        self._active_drag_start_position: PointerPosition | None = None
        self._annotation_drag_active = False
        self._clipboard_payload = None
        self._clipboard_pastes = 0
        self.transformChanged.connect(self._measure_controller.clearHover)

    @Property(QObject, constant=True)
    def settingsController(self):
        return self._settings_controller

    @Slot(bool)
    def setAnnotationMode(self, with_text):
        self._tool_controller.selectInteraction(
            InteractionType.ANNOTATE_TEXT.value if with_text else InteractionType.ANNOTATE_ARROW.value
        )

    @Property(str, notify=displayStyleChanged)
    def colorMap(self):
        return self._state.display_style.color_map

    def _set_default_color_map(self):
        category = "pet" if self.viewport_config.series_meta.modality.upper() in ("PT", "PET") else "gray"
        name = self._settings_controller.section("colormap")[category]
        self._state = replace(self._state, display_style=DisplayStyle(name, COLOR_MAPS[name][1][0]))

    def _preferences_changed(self, section):
        if section == "measurement":
            style = self._settings_controller.section("measurement")
            defaults = dict(color=style["annotationColor"], font_size=style["fontSize"])
            changed = {key: value for key, value in defaults.items() if value != self._annotation_style_defaults[key]}
            self._text_annotation_controller.applyStyleDefaults(**changed)
            self._annotation_style_defaults = defaults
        if section == "colormap":
            before = self._state.display_style
            self._set_default_color_map()
            if before != self._state.display_style:
                self.displayStyleChanged.emit()
                self.request_render()
        self.viewportSettingsChanged.emit()
        self.preferencesChanged.emit()
        self.overlayChanged.emit()

    @Property(bool, notify=imageDimensionChanged)
    def hasPhysicalSpacing(self):
        spacing = self._frame_meta.instance_meta.pixel_spacing if self._frame_meta else None
        return bool(spacing and len(spacing) == 2 and all(isfinite(v) and v > 0 for v in spacing))

    def _initial_slice_index(self) -> int | None:
        return None

    def _build_render_request(self, *, initial: bool) -> RenderRequest:
        raise NotImplementedError

    def _validate_render_result(self, result: RenderResult) -> None:
        raise NotImplementedError

    def _apply_specific_render_result(self, result: RenderResult) -> None:
        raise NotImplementedError

    def apply_slice_index(self, index: int) -> None:
        raise NotImplementedError

    def _prepare_slice_index_change(self, index: int) -> bool:
        if index == self._state.slice_index:
            return False

        self._measure_controller.set_current_slice(index)
        self.cancelMeasurement()
        if self._mtf_controller is not None:
            self._mtf_controller.set_current_slice(index)
        if self._fwhm_controller is not None:
            self._fwhm_controller.set_current_slice(index)
        if self._qa_controller is not None:
            self._qa_controller.set_current_slice(index)
        self._state = replace(
            self._state,
            slice_index=index,
        )
        self._text_annotation_controller.set_current_slice(index)
        self.sliceChanged.emit()
        return True

    def _begin_specific_interaction(
            self,
            position: PointerPosition,
            endpoint_tolerance: float,
            line_tolerance: float
    ) -> tuple[DragOperation, OperationStartContext] | None:
        return None

    def _apply_specific_interaction_result(
            self,
            result: InteractionResult,
    ) -> bool:
        return False

    def _handle_specific_pointer_hover(
            self,
            context: PointerHoverContext,
    ) -> None:
        """处理具体二维视图特有的指针 hover 状态。"""
        return None

    @Property(QObject, constant=True)
    def cursorController(self):
        return self._cursor_controller

    @Property(str, notify=activeInteractionChanged)
    def activeInteraction(self) -> str:
        return self._tool_controller.activeInteraction


    def _handle_active_interaction_changed(self) -> None:
        self.cancelMeasurement()
        self.clearInteractionHover()
        if self._tool_controller.active_interaction != InteractionType.ANNOTATE_TEXT:
            self._text_annotation_controller.clearSelection()
        self._measure_controller.clear_selection()
        self._measure_controller.clearHover()
        if self._mtf_controller is not None:
            self._mtf_controller.roiController.clear_selection()
            self._mtf_controller.roiController.clearHover()
        if self._fwhm_controller is not None:
            self._fwhm_controller.roiController.clear_selection()
            self._fwhm_controller.roiController.clearHover()
        self.activeInteractionChanged.emit()


    def request_first_loader(self) -> None:
        self._set_load_state("loading")
        request = self._build_render_request(initial=True)
        self._latest_request_id = request.request_id
        self.render_pending = True
        logger.debug(
            "Render started: request_id=%s viewport_id=%s",
            request.request_id,
            request.viewport_id,
        )
        self.renderRequested.emit(request)

    def request_render(self) -> None:
        request = self._build_render_request(initial=False)
        self._latest_request_id = request.request_id
        self.render_pending = True
        logger.debug(
            "Render started: request_id=%s viewport_id=%s window=%r",
            request.request_id,
            request.viewport_id,
            request.window
        )
        self.renderRequested.emit(request)

    def accepts_result(self, result: RenderResult) -> bool:
        return (
            result.viewport_id == self.viewport_config.viewport_id
            and (self._latest_request_id is None or result.response_id == self._latest_request_id)
        )

    @Slot(float, float)
    def setViewportSize(
            self,
            width: float,
            height: float,
    ) -> None:
        if width <= 0 or height <= 0:
            return

        if (
                width == self._state.width
                and height == self._state.height
        ):
            return

        self._state = replace(
            self._state,
            width=width,
            height=height,
        )

    @Slot(object)
    def handleRenderResult(self, result: RenderResult) -> None:
        if (
                result.viewport_id
                != self.viewport_config.viewport_id
        ):
            return
        if not self.accepts_result(result):
            return
        self.render_pending = False
        self._validate_render_result(result)
        content_key = getattr(result, "content_key", None)
        if content_key is not None and content_key == self._content_key:
            # Geometry's frame/anchor may follow the locator while its physical
            # sample grid stays fixed. Keep annotations/ROI/textures untouched.
            self._frame_meta = result.frame_meta
            self._apply_specific_render_result(result)
            self._set_load_state("ready")
            return
        self._content_key = content_key
        previous_value_meta = (
            self._frame_meta.pixel_value_meta
            if self._frame_meta is not None
            else None
        )
        if self._baseline_window is None:
            self._baseline_window = result.frame_meta.window
        if self._baseline_slice_index is None:
            self._baseline_slice_index = result.frame_meta.slice_index
        self._frame_meta = result.frame_meta
        is_pet = self.isPetViewport
        config_mode = (
            "pet-suv"
            if is_pet and result.frame_meta.pixel_value_meta.is_suv
            else "pet-native"
            if is_pet
            else "mr" if self.isMrViewport or not self.viewport_config.series_meta.supports_ct_analysis
            else "default"
        )
        if config_mode != self._window_config_mode:
            self._window_level_operation.cancel()
            self._window_level_operation = WindowLevelOperation(
                PET_SUV_WINDOW_LEVEL_CONFIG
                if config_mode == "pet-suv"
                else PET_NATIVE_WINDOW_LEVEL_CONFIG
                if config_mode == "pet-native"
                else MR_WINDOW_LEVEL_CONFIG if config_mode == "mr"
                else WindowLevelInteractionConfig()
            )
            self._window_config_mode = config_mode
        self._cursor_controller.set_pixel_value_meta(
            result.frame_meta.pixel_value_meta
        )
        slice_changed = (
            self._state.slice_index != result.frame_meta.slice_index
            or self._state.slice_count != result.frame_meta.slice_count
        )
        self._state = replace(
            self._state,
            slice_index=result.frame_meta.slice_index,
            slice_count=result.frame_meta.slice_count,
            window=result.frame_meta.window,
            inverted=result.frame_meta.inverted,
        )
        self._text_annotation_controller.set_current_slice(
            result.frame_meta.slice_index
        )
        if is_pet:
            self._pet_display.accept(result.frame_meta.pixel_value_meta, result.frame_meta.window)
        if slice_changed:
            self.sliceChanged.emit()
        self._modality_pixel = result.modality_pixel
        self.accept_mapping_frame(result.frame_meta)
        source_context = ()
        projection = getattr(result, "projection_mode", None)
        if projection is not None or self.viewportRole == "mip":
            source_context = ("projection", str(projection or "mip"),
                              getattr(result, "slab_thickness_mm", 0.0))
        phase_identifier = getattr(result, "phase_identifier", None)
        if phase_identifier is not None:
            source_context += ("phase", phase_identifier)
        source = dict(getattr(self, "_measurement_requests", {}).get(result.response_id, {}))
        if source and (result.modality_pixel is not None or result.frame_meta.pixel_value_meta.quantification == "color"):
            import hashlib
            fingerprint_pixels = result.image if result.frame_meta.pixel_value_meta.quantification == "color" else result.modality_pixel
            source["pixelFingerprint"] = hashlib.blake2b(
                np.ascontiguousarray(fingerprint_pixels).view(np.uint8), digest_size=16).hexdigest()
            if source.get("kind") == "mpr" and getattr(result, "mpr_frame", None) is not None:
                source["parameters"] = dict(source["parameters"], mpr_frame=result.mpr_frame)
                if source.get("navigation") is None:
                    from qt_dicom_viewer.model.dicom_core import MprState, MprViewAnchors
                    source["navigation"] = MprState(frame=result.mpr_frame, view_grids=result.mpr_view_grids,
                        view_anchors=MprViewAnchors.centered(result.mpr_view_grids) if result.mpr_view_grids else None)
        self._measure_controller.current_source = source
        self._measure_controller.set_frame(result.series_uid, result.frame_meta,
                                           source_context=source_context)
        self._text_annotation_controller.set_frame(
            result.series_uid,
            result.frame_meta,
        )
        if self.isPetViewport:
            self._measure_controller.refresh_roi_metrics(result.modality_pixel, result.frame_meta)
        self._cursor_controller.resample(result.modality_pixel)
        self._apply_specific_render_result(result)
        self._set_load_state("ready")
        if previous_value_meta != result.frame_meta.pixel_value_meta:
            self.windowPresetsChanged.emit()
        if is_pet:
            self.petDisplayChanged.emit()

        self.overlayChanged.emit()
        self.imageDimensionChanged.emit()
        self.directionLabelsChanged.emit()
        if result.image is None:
            return

        self._has_image = True
        self._image_revision += 1
        self.imageSourceChanged.emit()
        logger.debug(
            "Viewport image updated: "
            "viewport_id=%s revision=%d",
            result.viewport_id,
            self._image_revision,
        )

    @Slot(object)
    def handleRenderFailure(self, failure) -> None:
        if failure.viewport_id != self.viewport_config.viewport_id:
            return
        if self._latest_request_id and failure.request_id != self._latest_request_id:
            return
        self.render_pending = False
        self._pet_display.fail()
        if self.isPetViewport:
            self.refresh_window_image()
        self._set_load_state("ready" if self.isPetViewport and self._has_image else "error",
                             error_message(failure.error))

    def _set_load_state(self, state: str, message: str = "") -> None:
        if state == self._load_state and message == self._error_message:
            return
        self._load_state = state
        self._error_message = message
        self.loadStateChanged.emit()

    @Property(str, notify=loadStateChanged)
    def loadState(self) -> str:
        return self._load_state

    @_TextProperty(str, notify=_i18n_errorMessage, notify_name='_i18n_errorMessage', source_notify='loadStateChanged')
    def errorMessage(self) -> str:
        return self._error_message

    @_TextProperty(str, notify=_i18n_quantificationWarning, notify_name='_i18n_quantificationWarning', source_notify='overlayChanged')
    def quantificationWarning(self) -> str:
        if self._frame_meta is None:
            return ""
        return self._frame_meta.pixel_value_meta.warning or ""

    @Property(bool, constant=True)
    def isPetViewport(self) -> bool:
        return (
            self.viewport_config.series_meta.modality.strip().upper() == "PT"
        )

    @property
    def pet_active_unit_id(self) -> str:
        target = self._pet_display.target
        return target.meta.unit_id if target else ""

    @Property(bool, notify=petDisplayChanged)
    def petUnitPending(self):
        return self._pet_display.pending

    @Property(str, notify=petDisplayChanged)
    def petActiveUnitId(self):
        visible = self._pet_display.visible
        return visible.meta.unit_id if visible else ""

    @_TextProperty(str, notify=_i18n_petActiveUnitLabel, notify_name='_i18n_petActiveUnitLabel', source_notify='petDisplayChanged')
    def petActiveUnitLabel(self):
        visible = self._pet_display.visible
        if visible is None:
            return ""
        return next((o.label for o in visible.meta.unit_options
                     if o.unit_id == visible.meta.unit_id), visible.meta.unit)

    @Property(float, notify=petDisplayChanged)
    def petDisplayUpper(self):
        visible = self._pet_display.visible
        return visible.upper if visible else 0.0

    @Property(float, notify=petDisplayChanged)
    def petMinimumUpper(self):
        visible = self._pet_display.visible
        return visible.minimum if visible else 0.001

    @Property(float, notify=petDisplayChanged)
    def petControlUpper(self):
        visible = self._pet_display.visible
        return visible.control if visible else 30.0

    @_TextProperty('QVariantList', notify=_i18n_petControlUpperOptions, notify_name='_i18n_petControlUpperOptions', source_notify='petDisplayChanged')
    def petControlUpperOptions(self):
        visible = self._pet_display.visible
        if visible is None:
            return []
        values = list(visible.presets)
        if not any(np.isclose(visible.control, p, rtol=0, atol=1e-7) for p in values):
            values.append(visible.control)
        return sorted(values)

    @_TextProperty('QVariantList', notify=_i18n_petUnitOptions, notify_name='_i18n_petUnitOptions', source_notify='petDisplayChanged')
    def petUnitOptions(self):
        visible = self._pet_display.visible
        return [] if visible is None else [
            dict(unitId=o.unit_id, label=o.label, unit=o.unit,
                 enabled=o.available, warning=o.warning or "",
                 active=o.unit_id == visible.meta.unit_id)
            for o in visible.meta.unit_options
        ]

    @Slot(float)
    def setPetDisplayUpper(self, value):
        if self.isPetViewport:
            self._pet_display.set_upper(value)

    @Slot(float)
    def setPetControlUpper(self, value):
        if self.isPetViewport:
            self._pet_display.set_control(value)

    @Slot(str)
    def setPetUnit(self, unit_id):
        if self.isPetViewport:
            self.cancelMeasurement()
            self._pet_display.set_unit(unit_id)

    @Slot()
    def resetPetDisplay(self):
        if self.isPetViewport:
            self.cancelMeasurement()
            self._pet_display.reset()

    @_TextProperty(list, notify=_i18n_windowPresets, notify_name='_i18n_windowPresets', source_notify='windowPresetsChanged')
    def windowPresets(self) -> list[dict]:
        if self.isPetViewport:
            return []
        return self._tool_controller.windowPresets

    @property
    def viewport_state(self) -> ViewportState:
        return self._state

    @Property(QObject, constant=True)
    def textAnnotationController(self) -> QObject:
        return self._text_annotation_controller

    @_TextProperty('QVariantList', notify=_i18n_colorMapOptions, notify_name='_i18n_colorMapOptions')
    def colorMapOptions(self) -> list[dict]:
        return COLOR_MAP_OPTIONS

    @Property(str, notify=displayStyleChanged)
    def activeColorMap(self) -> str:
        return self._state.display_style.color_map

    @Property('QVariantList', notify=displayStyleChanged)
    def activeColorMapStops(self) -> list[dict]:
        return next(
            (
                option["stops"]
                for option in COLOR_MAP_OPTIONS
                if option["colorMap"] == self.activeColorMap
            ),
            [],
        )

    @Property(str, notify=imageSourceChanged)
    def imageSource(self) -> str:
        if not self._has_image:
            return ""

        return (
            f"image://dicom/"
            f"{self.viewport_config.viewport_id}/"
            f"{self._image_revision}"
        )

    @_TextProperty('QVariantMap', notify=_i18n_overlayInfo, notify_name='_i18n_overlayInfo', source_notify='overlayChanged')
    def overlayInfo(self) -> dict:
        series = self.viewport_config.series_meta
        frame = self._frame_meta
        if frame is not None and self.current_window is not None:
            # Geometry still belongs to the displayed slice; window labels
            # follow its live display intent, not the last worker response.
            frame = replace(frame, window=self.current_window, inverted=self.inverted)

        return self._overlay_presenter.build(
            viewport_config=self.viewport_config,
            series=series,
            frame=frame,
            state=self._state,
        )

    @Slot(float, float, int, bool, float, float, float, float)
    def beginInteraction(
            self,
            x: float,
            y: float,
            buttons: int,
            image_valid: bool,
            column: float,
            row: float,
            endpoint_tolerance: float,
            line_tolerance: float,
    ) -> None:
        logger.debug(f'beginInteraction,x:{x},y:{y},btn:{buttons}, col:{column}, row:{row}')
        position = _make_pointer_position(
            viewport_x=x,
            viewport_y=y,
            image_valid=image_valid,
            column=column,
            row=row,
            include_outside_image=True,
        )
        self._active_drag_operation = None
        self._active_drag_start_position = None
        self._annotation_drag_active = False
        interaction = drag_interaction(self._tool_controller.active_interaction, buttons)
        if interaction == InteractionType.NONE:
            return
        if interaction == InteractionType.ANNOTATE_TEXT:
            if (
                image_valid
                and buttons & Qt.MouseButton.LeftButton.value
            ):
                self._annotation_drag_active = self._text_annotation_controller.beginAnnotation(column, row)
            return None
        context: OperationStartContext | None = None
        # Crosshair and region handles use the primary button; a right drag
        # remains zoom even when it starts over a handle.
        specific_interaction = None
        if buttons & (Qt.MouseButton.LeftButton.value | Qt.MouseButton.MiddleButton.value):
            specific_interaction = self._begin_specific_interaction(
                position, endpoint_tolerance, line_tolerance
            )
        if specific_interaction is not None:
            self._active_drag_operation, context = specific_interaction
        else:
            if interaction == InteractionType.SERVICE_QA:
                if self._qa_controller is not None and buttons & Qt.MouseButton.LeftButton.value:
                    self._qa_controller.begin_drag(column, row)
                    if self._qa_controller.dragging:
                        return
                # QA only claims its existing ROI handles, not empty canvas.
                interaction = InteractionType.WINDOW
            match interaction:
                case InteractionType.WINDOW:
                    mapping_window = self.mapping_drag_window(self.current_window)
                    if mapping_window is None:
                        return
                    self._active_drag_operation = self._window_level_operation
                    context = WindowLevelContext(
                        viewport_size=self.viewport_size,
                        inverted=self.inverted,
                        current_window=mapping_window,
                    )
                case InteractionType.SCROLL:
                    if self._state.slice_index is not None and self._state.slice_count is not None:
                        self._active_drag_operation = self._scroll_operation
                        context = ScrollContext(
                            slice_index=self._state.slice_index,
                            slice_count=self._state.slice_count,
                        )
                case InteractionType.PAN:
                    self._active_drag_operation = self._pan_operation
                    context = PanContext(
                        current_pan_x=self._state.pan_x,
                        current_pan_y=self._state.pan_y,
                    )
                case InteractionType.ZOOM:
                    self._active_drag_operation = self._zoom_operation
                    context = ZoomContext(
                        viewport_size=self.viewport_size,
                        current_zoom=self._state.zoom,
                    )
                case (InteractionType.MEASURE_LENGTH | InteractionType.MEASURE_ANGLE
                      | InteractionType.MEASURE_RECT | InteractionType.MEASURE_ELLIPSE | InteractionType.MEASURE_FREEHAND | InteractionType.MEASURE_CURVE
                      | InteractionType.SERVICE_MTF | InteractionType.SERVICE_FWHM | InteractionType.ANNOTATE_ARROW):
                    if self._frame_meta is None:
                        logger.error(
                            "Cannot measure before an image is loaded"
                        )
                        return

                    # 测量使用无限延伸的图像坐标系。即使指针位于图像矩形外，
                    # 只要仍在视口画布内，也保留换算后的连续图像坐标。
                    position = _make_pointer_position(
                        viewport_x=x,
                        viewport_y=y,
                        image_valid=image_valid,
                        column=column,
                        row=row,
                        include_outside_image=True,
                    )

                    context = self._measurement_context(endpoint_tolerance, line_tolerance)
                    if context is not None:
                        self._active_drag_operation = self.activeAnnotationController
                case _:
                    context = None
        if self._active_drag_operation is None or context is None:
            return None
        # A temporary right-button zoom may be used between angle points.
        # Keep the draft and the selected tool; primary-button actions retain
        # their existing cancellation policy.
        temporary_zoom = (buttons & Qt.MouseButton.RightButton.value
                          and not buttons & Qt.MouseButton.LeftButton.value)
        if not isinstance(self._active_drag_operation, MeasurementController) and not temporary_zoom:
            self.cancelMeasurement()
        self._active_drag_start_position = position
        result = self._active_drag_operation.begin(
            position,
            context,
        )
        if result is not None:
            self._apply_interaction_result(result)
        return None

    @Slot(
        QPointF,
        QPointF,
        QPointF,
        QPointF,
        bool,
        float,
        float,
    )
    def updateInteraction(
            self,
            start_point: QPointF,
            current_point: QPointF,
            step_offset: QPointF,
            total_offset: QPointF,
            image_valid: bool,
            column: float,
            row: float,
    ) -> None:
        if self._annotation_drag_active:
            self._text_annotation_controller.updateAnnotation(column, row)
            return
        if self._qa_controller is not None and self._qa_controller.dragging:
            self._qa_controller.update_drag(column, row)
            return
        operation = self._active_drag_operation
        start_position = self._active_drag_start_position

        if operation is None or start_position is None:
            return

        current_position = _make_pointer_position(
            viewport_x=current_point.x(),
            viewport_y=current_point.y(),
            image_valid=image_valid,
            column=column,
            row=row,
            include_outside_image=True,
        )

        event = DragUpdateEvent(
            start_position=start_position,
            current_position=current_position,
            step_offset=Offset(
                x=step_offset.x(),
                y=step_offset.y(),
            ),
            total_offset=Offset(
                x=total_offset.x(),
                y=total_offset.y(),
            ),
        )

        result = operation.update(event)
        self._apply_interaction_result(result)

    @Slot(float, float, bool, float, float)
    def endInteraction(
            self,
            x: float,
            y: float,
            image_valid: bool,
            column: float,
            row: float,
    ) -> None:
        if self._annotation_drag_active:
            self._annotation_drag_active = False
            self._text_annotation_controller.finishAnnotation(column, row)
            return
        if self._qa_controller is not None and self._qa_controller.dragging:
            self._qa_controller.end_drag(column, row)
            return
        operation = self._active_drag_operation

        self._active_drag_operation = None
        self._active_drag_start_position = None

        if operation is None:
            return

        position = _make_pointer_position(
            viewport_x=x,
            viewport_y=y,
            image_valid=image_valid,
            column=column,
            row=row,
            include_outside_image=True,
        )

        result = operation.end(position)
        self._apply_interaction_result(result)

    @Slot(float,float,float, float, float, float, bool, float, float)
    def updateCursorPosition(
            self,
            x: float,
            y: float,
            column: float,
            row: float,
            clipColumn: float,
            clipRow: float,
            image_valid: bool,
            point_tolerance: float,
            line_tolerance: float,
    ) -> None:
        # UI 已拦截按住鼠标的 hover；这里再防御拖动期间的晚到事件。
        if self._active_drag_operation is not None or (self._qa_controller is not None and self._qa_controller.dragging):
            return
        if self._tool_controller.active_interaction in (InteractionType.MEASURE_ANGLE, InteractionType.MEASURE_FREEHAND, InteractionType.MEASURE_CURVE):
            preview = ImagePoint(column, row) if isfinite(column) and isfinite(row) else None
            self._measure_controller.preview_at(preview)
        self.refreshInteractionHover(x, y, column, row, point_tolerance, line_tolerance)

        if self._modality_pixel is None or not image_valid:
            self._cursor_controller.clearPosition()
            return

        pixel_value = self._modality_pixel[int(clipRow)][int(clipColumn)]
        if not np.isfinite(pixel_value) and self.viewportRole != "fusion":
            self._cursor_controller.clearPosition()
            return
        self._cursor_controller.updatePosition(clipColumn, clipRow, pixel_value)

    @Property(str, notify=regionCursorKindChanged)
    def regionCursorKind(self):
        return getattr(self, "_region_cursor_kind", "")

    @Slot()
    def clearInteractionHover(self):
        self._region_cursor_kind = ""
        self.regionCursorKindChanged.emit()
        self._crosshair_hover_target = None
        self.crosshairHoverTargetChanged.emit()
        self.activeAnnotationController.clearHover()
        if self._qa_controller is not None:
            self._qa_controller.clearHover()

    @Slot(float, float, float, float, float, float)
    def refreshInteractionHover(self, x, y, column, row, point_tolerance, line_tolerance):
        """Resolve operation targets without sampling pixels (press/release/tool changes)."""
        if self._active_drag_operation is not None:
            return
        pointer_position = _make_pointer_position(
            viewport_x=x,
            viewport_y=y,
            image_valid=True,
            column=column,
            row=row,
            include_outside_image=True,
        )
        self._handle_specific_pointer_hover(
            PointerHoverContext(
                position=pointer_position,
                point_tolerance=point_tolerance,
                line_tolerance=line_tolerance,
            )
        )

        self.updateMeasurementHover(x, y, column, row, point_tolerance, line_tolerance)

    @Slot(float, float, float, float, float, float)
    def updateMeasurementHover(self, x: float, y: float, column: float, row: float,
                               point_tolerance: float, line_tolerance: float) -> None:
        """只刷新测量命中；点击或拖动结束后使用它，不额外触发 XY/CT 采样。"""
        if self._active_drag_operation is not None:
            return
        if self._tool_controller.active_interaction == InteractionType.SERVICE_QA and self._qa_controller is not None:
            self._qa_controller.update_hover(column, row)
            return
        context = self._measurement_context(point_tolerance, line_tolerance)
        if context is None:
            self.activeAnnotationController.clearHover()
            return
        # 测量可以在图像之外的画布绘制，不能用 image_valid 拦截其悬停命中。
        point = ImagePoint(column, row) if isfinite(column) and isfinite(row) else None
        self.activeAnnotationController.update_hover(
            point, slice_index=context.slice_index,
            endpoint_tolerance=point_tolerance, line_tolerance=line_tolerance,
            viewport_point=Point(x, y),
        )


    @Slot(float, float, float, float, int)
    def handleWheel(
            self,
            angle_delta_y: float,
            pixel_delta_y: float,
            x: float,
            y: float,
            modifiers: int,
    ) -> None:
        if self._state.slice_index is not None and self._state.slice_count is not None:
            slice_change = self._scroll_operation.handle_wheel(
                angle_delta_y=angle_delta_y,
                current_index=self._state.slice_index,
                slice_count=self._state.slice_count,
            )
            self._apply_interaction_result(slice_change)

    def _apply_interaction_result(
            self,
            result: InteractionResult | None,
    ) -> None:
        match result:
            case SliceIndexChange(slice_index=index):
                self.apply_slice_index(index)

            case WindowLevelChange(window=window, inverted=inverted):
                if self.apply_mapping_drag(window):
                    return
                self.apply_window_level(
                    WindowLevelChange(
                        window=window,
                        inverted=inverted,
                    )
                )

            case PanChange(offset_x=x, offset_y=y):
                self.apply_pan(x, y)

            case ZoomChange(zoom=zoom):
                self.apply_zoom(zoom)

            case None:
                return

            case _ if self._apply_specific_interaction_result(result):
                return

    @property
    def current_window(self) -> WindowLevel | None:
        if self.isPetViewport and self._pet_display.visible is not None:
            return self._pet_display.visible.window
        return self._state.window

    @property
    def viewport_size(self) -> tuple[float, float]:
        return self._state.width, self._state.height

    @Property(bool, notify=overlayChanged)
    def inverted(self) -> bool:
        return self._state.inverted

    @Property(float, notify=overlayChanged)
    def windowCenter(self):
        return self.current_window.center if self.current_window is not None else float("nan")

    @Property(float, notify=overlayChanged)
    def windowWidth(self):
        return self.current_window.width if self.current_window is not None else float("nan")

    @Property(bool, constant=True)
    def supportsCtWindow(self):
        return (not self.viewport_config.series_meta.is_color and self.viewport_config.series_meta.modality.strip().upper() == "CT"
                and self.viewport_config.series_meta.supports_ct_analysis)

    @Property(bool, constant=True)
    def isMrViewport(self):
        return self.viewport_config.series_meta.modality.strip().upper() == "MR"

    @Property(bool, constant=True)
    def supportsGrayscaleWindow(self):
        return not self.viewport_config.series_meta.is_color and self.viewport_config.series_meta.modality.strip().upper() in ("CT", "MR")

    @Property(float, constant=True)
    def minimumWindowWidth(self):
        return 0.001 if self.isMrViewport else 1.0

    @Slot()
    def autoWindow(self):
        if self.isMrViewport and self._modality_pixel is not None:
            from qt_dicom_viewer.core.mr import automatic_mr_window
            self.apply_window_level(WindowLevelChange(automatic_mr_window(self._modality_pixel), self.inverted))

    @Slot()
    def toggleInverted(self):
        if self.supportsGrayscaleWindow and self._state.window is not None:
            self.apply_window_level(WindowLevelChange(self._state.window, not self.inverted))

    def present_display_image(self, pixels) -> None:
        """Repaint cached samples without changing slice geometry or measurements."""
        self.imageUpdateRequested.emit(self.viewportId, pixels)
        # A later render with the previous key must not leave a preview on screen.
        self._content_key = None
        self._has_image = True
        self._image_revision += 1
        self.imageSourceChanged.emit()

    def refresh_window_image(self) -> None:
        pixels, window = self._modality_pixel, self._state.window
        if self._frame_meta is not None and self._frame_meta.window_pixels is not None:
            pixels = self._frame_meta.window_pixels
        if pixels is None or pixels.ndim != 2 or window is None:
            return
        minimum = self.minimumWindowWidth
        source_inverted = (self.isMrViewport and self._frame_meta is not None
                           and self._frame_meta.instance_meta.photometric_interpretation == "MONOCHROME1")
        if self.isPetViewport:
            target = self._pet_display.target
            # A unit switch needs newly converted samples; never relabel old data.
            if target is None or self._frame_meta.pixel_value_meta.unit_id != target.meta.unit_id:
                return
            window, minimum = target.window, target.minimum
        from qt_dicom_viewer.core.display_mapping import map_display
        gray = DicomLoader.apply_window(pixels, window, self.inverted ^ source_inverted, minimum)
        overlay = self._frame_meta.supplemental_overlay if self._frame_meta else None
        frame = self._frame_meta
        self.present_display_image(map_display(gray, self._modality_pixel, frame.pixel_value_meta,
            overlay, frame.source_palette, self._state.display_mapping, self.activeColorMap))

    def _pet_display_invalidated(self):
        self.refresh_window_image()
        self.request_render()

    def set_window_state(self, result: WindowLevelChange) -> bool:
        """Update display state without scheduling; linked views commit as a batch."""
        if self.viewport_config.series_meta.is_color:
            return False
        if result.window == self._state.window and result.inverted == self.inverted:
            return False
        self._state = replace(self._state, window=result.window, inverted=result.inverted)
        self.refresh_window_image()
        self.overlayChanged.emit()
        return True

    def apply_window_level(self, result: WindowLevelChange) -> None:
        if self.isPetViewport:
            self._pet_display.set_upper(result.window.center + result.window.width / 2.0)
            return
        if self.set_window_state(result):
            self.request_render()

    @Property(QObject, constant=True)
    def measurementController(self) -> QObject:
        return self._measure_controller

    @Property(QObject, constant=True)
    def mtfController(self):
        return self._mtf_controller

    @Property(QObject, constant=True)
    def fwhmController(self):
        return self._fwhm_controller

    @Property(QObject, notify=activeInteractionChanged)
    def activeProfileController(self):
        return (self._fwhm_controller if self._tool_controller.activeService == "service:fwhm"
                else self._mtf_controller if self._tool_controller.activeService == "service:mtf" else None)

    @Property(QObject, constant=True)
    def qaController(self):
        return self._qa_controller

    @Property(QObject, notify=activeInteractionChanged)
    def activeAnnotationController(self):
        if (self._mtf_controller is not None
                and self._tool_controller.active_interaction == InteractionType.SERVICE_MTF):
            return self._mtf_controller.roiController
        if (self._fwhm_controller is not None
                and self._tool_controller.active_interaction == InteractionType.SERVICE_FWHM):
            return self._fwhm_controller.roiController
        return self._measure_controller

    def shutdown(self):
        if self._mtf_controller is not None:
            self._mtf_controller.shutdown()
        if self._fwhm_controller is not None:
            self._fwhm_controller.shutdown()
        if self._qa_controller is not None:
            self._qa_controller.shutdown()

    @Property(int, notify=imageDimensionChanged)
    def imageColumns(self) -> int:
        if self._frame_meta is None:
            return 0

        columns = self._frame_meta.instance_meta.columns
        return columns or 0

    @Property(int, notify=imageDimensionChanged)
    def imageRows(self) -> int:
        if self._frame_meta is None:
            return 0

        rows = self._frame_meta.instance_meta.rows
        return rows or 0

    @Property(int, notify=sliceChanged)
    def sliceIndex(self) -> int:
        """返回从 0 开始的当前切片索引；尚未加载时返回 -1。"""
        index = self._state.slice_index
        return -1 if index is None else index

    @Property(int, notify=sliceChanged)
    def sliceCount(self) -> int:
        """返回当前序列的切片总数；尚未加载时返回 0。"""
        count = self._state.slice_count
        return 0 if count is None else count

    @Slot(int)
    def setSliceIndex(self, index: int) -> None:
        """从界面设置切片，并将越界值限制到有效范围。"""
        count = self._state.slice_count
        if count is None or count <= 0:
            return

        clamped_index = max(0, min(int(index), count - 1))
        self.apply_slice_index(clamped_index)

    @Property(float, notify=imageDimensionChanged)
    def imageRowSpacing(self) -> float:
        """返回图像行方向的物理间距，单位为 mm。"""
        if self._frame_meta is None:
            return 1.0

        spacing = self._frame_meta.geometry.pixel_spacing.row
        if not isfinite(spacing) or spacing <= 0:
            return 1.0
        return spacing

    @Property(float, notify=imageDimensionChanged)
    def imageColumnSpacing(self) -> float:
        """返回图像列方向的物理间距，单位为 mm。"""
        if self._frame_meta is None:
            return 1.0

        spacing = self._frame_meta.geometry.pixel_spacing.column
        if not isfinite(spacing) or spacing <= 0:
            return 1.0
        return spacing

    @Property(float, notify=transformChanged)
    def zoom(self) -> float:
        return self._state.zoom

    @Property(float, notify=transformChanged)
    def panX(self) -> float:
        return self._state.pan_x

    @Property(float, notify=transformChanged)
    def panY(self) -> float:
        return self._state.pan_y

    @Property(float, notify=transformChanged)
    def rotationDegrees(self) -> float:
        return self._state.rotation_degrees

    @Property(bool, notify=transformChanged)
    def horizontalFlip(self) -> bool:
        return self._state.horizontal_flip

    @Property(bool, notify=transformChanged)
    def verticalFlip(self) -> bool:
        return self._state.vertical_flip

    def apply_pan(self, x, y):
        self._state = replace(self._state,
                              pan_x=x,
                              pan_y=y
                              )
        self.transformChanged.emit()

    @Slot(float)
    def setZoom(self, zoom: float) -> None:
        """Set an absolute multiple of the default fitted view."""
        self.apply_zoom(zoom)

    def apply_zoom(self, zoom: float) -> None:
        if not isfinite(zoom):
            return

        zoom = max(0.1, min(zoom, 20.0))

        if abs(zoom - self._state.zoom) < 0.0001:
            return

        self._state = replace(
            self._state,
            zoom=zoom,
        )

        self.transformChanged.emit()

        # overlayInfo 中显示了 zoom，因此也要更新
        self.overlayChanged.emit()

    def reset_tool_state(self, tool_type: ToolType) -> None:
        """只重置一个一级工具负责的当前视口状态。"""
        state = self._state

        match tool_type:
            case ToolType.WINDOW:
                if self.displayMapping["customRange"]:
                    self.setDisplayMappingMode("source")
                    return
                if self.isPetViewport:
                    self.resetPetDisplay()
                    return
                if (
                    self._baseline_window is None
                    or (state.window == self._baseline_window and not state.inverted)
                ):
                    return
                self.apply_window_level(WindowLevelChange(self._baseline_window, False))

            case ToolType.SCROLL:
                if self._baseline_slice_index is not None:
                    self.apply_slice_index(self._baseline_slice_index)

            case ToolType.PAN:
                if state.pan_x == 0.0 and state.pan_y == 0.0:
                    return
                self._state = replace(state, pan_x=0.0, pan_y=0.0)
                self.transformChanged.emit()

            case ToolType.ZOOM:
                if state.zoom == 1.0:
                    return
                self._state = replace(state, zoom=1.0)
                self.transformChanged.emit()
                self.overlayChanged.emit()

            case ToolType.ROTATE:
                if (
                    state.rotation_degrees == 0.0
                    and not state.horizontal_flip
                    and not state.vertical_flip
                ):
                    return
                self._state = replace(
                    state,
                    rotation_degrees=0.0,
                    horizontal_flip=False,
                    vertical_flip=False,
                )
                self.transformChanged.emit()
                self.directionLabelsChanged.emit()
                self.overlayChanged.emit()

            case ToolType.MEASURE:
                self._measure_controller.clear_kind(arrows=False)
            case ToolType.ANNOTATE:
                self._text_annotation_controller.clearAll()
                self._measure_controller.clear_kind(arrows=True)
            case ToolType.PSEUDOCOLOR:
                self.applyColorMap("grayscale")
            case ToolType.VIEWPORT_SETTINGS:
                settings = ViewportDisplaySettings()
                if state.display_settings == settings:
                    return
                self._state = replace(state, display_settings=settings)
                self.viewportSettingsChanged.emit()
            case ToolType.SERVICE:
                if self._mtf_controller is not None and self._tool_controller.activeService == "service:mtf":
                    self._mtf_controller.reset()
                elif self._fwhm_controller is not None and self._tool_controller.activeService == "service:fwhm":
                    self._fwhm_controller.reset()
                elif self._qa_controller is not None and self._tool_controller.activeService == "service:qa":
                    self._qa_controller.reset()

            case _:
                return

    def reset_all_view_state(self, *, reset_slice: bool = True) -> None:
        """重置当前视口的全部局部显示状态。"""
        from qt_dicom_viewer.model.display_mapping import DisplayMappingIntent
        mapping_changed = self._state.display_mapping.mode != "source"
        self._state = replace(self._state, display_mapping=DisplayMappingIntent())
        if mapping_changed:
            self.displayMappingChanged.emit()
            self.request_render()
        state = self._state
        window = self._baseline_window or state.window
        transform_changed = any(
            (
                state.pan_x != 0.0,
                state.pan_y != 0.0,
                state.zoom != 1.0,
                state.rotation_degrees != 0.0,
                state.horizontal_flip,
                state.vertical_flip,
            )
        )
        window_changed = window != state.window or state.inverted
        direction_changed = (
            state.rotation_degrees != 0.0
            or state.horizontal_flip
            or state.vertical_flip
        )
        display_style_changed = state.display_style != DisplayStyle()
        display_settings_changed = (
            state.display_settings != ViewportDisplaySettings()
        )

        self._state = replace(
            state,
            window=window,
            inverted=False,
            pan_x=0.0,
            pan_y=0.0,
            zoom=1.0,
            rotation_degrees=0.0,
            horizontal_flip=False,
            vertical_flip=False,
            display_style=DisplayStyle(),
            display_settings=ViewportDisplaySettings(),
        )
        self._measure_controller.clear_all()
        self._text_annotation_controller.clearAll()
        if self._mtf_controller is not None:
            self._mtf_controller.reset()
        if self._fwhm_controller is not None:
            self._fwhm_controller.reset()

        if self._qa_controller is not None:
            self._qa_controller.reset()

        if transform_changed:
            self.transformChanged.emit()
            self.overlayChanged.emit()
        if direction_changed:
            self.directionLabelsChanged.emit()
        if display_style_changed:
            self.displayStyleChanged.emit()
        if display_settings_changed:
            self.viewportSettingsChanged.emit()

        slice_changed = (
            reset_slice
            and self._baseline_slice_index is not None
            and self._baseline_slice_index != state.slice_index
        )
        if slice_changed and self._baseline_slice_index is not None:
            self.apply_slice_index(self._baseline_slice_index)
        elif window_changed or display_style_changed:
            self.request_render()

    @Slot(str)
    def applyTransformAction(self, action: str) -> None:
        try:
            transform_action = ViewportTransformAction(action)
        except ValueError:
            logger.warning(
                "Unsupported viewport transform action: %s",
                action,
            )
            return

        state = self._state

        match transform_action:
            case ViewportTransformAction.ROTATE_CLOCKWISE_90:
                next_state = replace(
                    state,
                    rotation_degrees=(
                                             state.rotation_degrees + 90.0
                                     ) % 360.0,
                )

            case ViewportTransformAction.ROTATE_COUNTERCLOCKWISE_90:
                next_state = replace(
                    state,
                    rotation_degrees=(
                                             state.rotation_degrees - 90.0
                                     ) % 360.0,
                )

            case ViewportTransformAction.MIRROR_HORIZONTAL:
                next_state = replace(
                    state,
                    horizontal_flip=not state.horizontal_flip,
                )

            case ViewportTransformAction.MIRROR_VERTICAL:
                next_state = replace(
                    state,
                    vertical_flip=not state.vertical_flip,
                )

        if next_state == state:
            return

        self._state = next_state
        self.transformChanged.emit()
        self.directionLabelsChanged.emit()
        self.overlayChanged.emit()

    @Property(str, notify=displayStyleChanged)
    def canvasBackgroundColor(self) -> str:
        return self._state.display_style.no_data_color

    @Property(bool, notify=viewportSettingsChanged)
    def showWindowAnnotations(self) -> bool:
        return self._state.display_settings.show_window_annotations and self._settings_controller.section("corners")["enabled"]

    @Property(bool, notify=viewportSettingsChanged)
    def hideSensitiveInfo(self) -> bool:
        return self._state.display_settings.hide_sensitive_info

    @Property(bool, notify=viewportSettingsChanged)
    def showScaleBar(self) -> bool:
        return (not self.viewport_config.series_meta.is_color or self.viewport_config.series_meta.color_calibrated) and self._state.display_settings.show_scale_bar and self._settings_controller.section("scale")["enabled"]

    @Property(bool, notify=viewportSettingsChanged)
    def showColorBar(self) -> bool:
        return self._state.display_settings.show_color_bar

    @Property(bool, notify=viewportSettingsChanged)
    def showDicomOverlay(self) -> bool:
        return self._state.display_settings.show_dicom_overlay

    @Property(bool, notify=viewportSettingsChanged)
    def showLocalizer(self) -> bool:
        return self._state.display_settings.show_localizer

    @Property(bool, notify=viewportSettingsChanged)
    def fitToWindow(self) -> bool:
        return self._state.display_settings.fit_to_window

    @Property(float, notify=overlayChanged)
    def displayRangeMinimum(self) -> float:
        window = self._state.window
        return 0.0 if window is None else window.center - window.width / 2.0

    @Property(float, notify=overlayChanged)
    def displayRangeMaximum(self) -> float:
        window = self._state.window
        return 255.0 if window is None else window.center + window.width / 2.0

    @Slot(str)
    def applyColorMap(self, color_map: str) -> None:
        style = DISPLAY_STYLES.get(color_map)
        if style is None:
            logger.warning("Unknown color map: %s", color_map)
            return
        if style == self._state.display_style:
            return
        self._state = replace(self._state, display_style=style)
        self.displayStyleChanged.emit()
        if self._frame_meta is not None:
            self.request_render()

    @Slot(str, bool)
    def setViewportSetting(self, setting: str, enabled: bool) -> None:
        field_name = VIEWPORT_SETTING_FIELDS.get(setting)
        if field_name is None:
            logger.warning("Unknown viewport setting: %s", setting)
            return
        settings = replace(
            self._state.display_settings,
            **{field_name: bool(enabled)},
        )
        if settings == self._state.display_settings:
            return
        self._state = replace(self._state, display_settings=settings)
        self.viewportSettingsChanged.emit()

    @Slot(float, float)
    def applyWindowPreset(
            self,
            center: float,
            width: float,
    ) -> None:
        if not isfinite(center) or not isfinite(width) or width < self.minimumWindowWidth:
            return
        self.apply_window_level(WindowLevelChange(WindowLevel(center=center, width=width), self.inverted))

    @Slot(bool, float, float, float, float)
    @Slot(bool, float, float, float, float, float, float)
    def selectMeasurementAt(
            self,
            image_valid: bool,
            column: float,
            row: float,
            endpoint_tolerance: float,
            line_tolerance: float,
            viewport_x: float | None = None,
            viewport_y: float | None = None,
    ) -> None:
        if self._tool_controller.active_interaction == InteractionType.ANNOTATE_TEXT:
            if image_valid:
                self._text_annotation_controller.selectAnnotationAt(
                    column,
                    row,
                    max(endpoint_tolerance, line_tolerance),
                )
            else:
                self._text_annotation_controller.clearSelection()
            return
        context = self._measurement_context(endpoint_tolerance, line_tolerance)
        if context is None:
            return

        point = None
        # 点击位置已经受 InteractionLayer 的画布范围约束；测量命中测试
        # 可以使用图像矩形外的连续坐标。
        if isfinite(column) and isfinite(row):
            point = ImagePoint(column=column, row=row)
        if self._state.slice_index is not None:
            self.activeAnnotationController.tap_at(
                point,
                slice_index=self._state.slice_index,
                endpoint_tolerance=endpoint_tolerance,
                line_tolerance=line_tolerance,
                context=context,
                viewport_point=Point(viewport_x, viewport_y)
                    if viewport_x is not None and viewport_y is not None else None,
            )
            if viewport_x is not None and viewport_y is not None:
                self.updateMeasurementHover(viewport_x, viewport_y, column, row,
                                            endpoint_tolerance, line_tolerance)

    def _measurement_context(self, endpoint_tolerance: float,
                             line_tolerance: float, *, kind: MeasurementKind | None = None) -> MeasureContext | None:
        frame = self._frame_meta
        is_profile = kind is None and self._tool_controller.active_interaction in (InteractionType.SERVICE_MTF, InteractionType.SERVICE_FWHM)
        kind = kind or MEASUREMENT_KINDS.get(self._tool_controller.active_interaction)
        if is_profile and self.activeProfileController is not None:
            kind = MeasurementKind.RECT
        # 翻页但新图尚未返回时，不把旧像素误当成新切片的统计数据。
        if frame is None or kind is None or frame.slice_index != self._state.slice_index:
            return None
        return MeasureContext(
            measurement_kind=kind, series_uid=self.viewport_config.series_uid,
            sop_instance_uid=frame.instance_meta.sop_instance_uid or "",
            slice_index=frame.slice_index, geometry=frame.geometry,
            endpoint_tolerance=endpoint_tolerance, line_tolerance=line_tolerance,
            modality_pixels=None if is_profile else self._modality_pixel,
            pixel_unit=(
                frame.pixel_value_meta.unit
                or (
                    "HU"
                    if self.viewport_config.series_meta.modality.upper() == "CT"
                    else ""
                )
            ),
        )

    def _clipboard_ready(self):
        return (self._frame_meta is not None and self._load_state == "ready"
                and self._frame_meta.slice_index == self._state.slice_index
                and self._active_drag_operation is None and not self._annotation_drag_active
                and not self._measure_controller.has_active_transaction
                and not self._text_annotation_controller._draft_id)

    @Slot(result=bool)
    def copySelectedAnnotation(self) -> bool:
        if not self._clipboard_ready():
            return False
        from qt_dicom_viewer.ui.annotation_clipboard import write_annotation
        payload = (self._text_annotation_controller.selected_copy()
                   or self._measure_controller.selected_copy())
        if payload is None:
            return False
        write_annotation(payload)
        self._clipboard_payload = None
        self._clipboard_pastes = 0
        return True

    @Slot(result=bool)
    def pasteAnnotation(self) -> bool:
        if not self._clipboard_ready():
            return False
        from qt_dicom_viewer.ui.annotation_clipboard import read_annotation
        payload = read_annotation()
        if payload is None:
            return False
        count = self._clipboard_pastes + 1 if payload == self._clipboard_payload else 1
        # Keep copies distinct without changing geometry dimensions; values are recomputed below.
        offset = 10 * count
        points = [[p[0] + offset, p[1] + offset] for p in payload["points"]]
        kind = payload["kind"]
        if kind == "text":
            uid = self._text_annotation_controller.paste_copy(payload, points)
            if not uid:
                return False
            self._tool_controller.selectInteraction("annotate:text")
            self._text_annotation_controller.selectAnnotation(uid)
        else:
            context = self._measurement_context(0, 0, kind=MeasurementKind(kind))
            if context is None:
                return False
            uid = self._measure_controller.paste_points([ImagePoint(*p) for p in points], context, smooth=payload.get("smooth", False))
            if not uid:
                return False
            self._tool_controller.selectInteraction(("annotate:" if kind == "arrow" else "measure:") + kind)
            self._measure_controller.select_completed(uid)
        self._clipboard_payload, self._clipboard_pastes = payload, count
        return True

    @Slot(result=bool)
    def finishMeasurement(self):
        return self._measure_controller.finish_path()

    @Slot()
    def cancelMeasurement(self) -> None:
        if self._annotation_drag_active:
            self._annotation_drag_active = False
            self._text_annotation_controller.cancelDraft()
        self._measure_controller.cancel_transaction()
        if self._qa_controller is not None:
            self._qa_controller.cancel_drag()
            self._qa_controller.clearHover()
        if self._mtf_controller is not None:
            self._mtf_controller.roiController.cancel_transaction()
        if self._fwhm_controller is not None:
            self._fwhm_controller.roiController.cancel_transaction()
        if isinstance(self._active_drag_operation, MeasurementController):
            self._active_drag_operation = None
            self._active_drag_start_position = None

    @Slot()
    def deleteSelectedMeasurement(self) -> None:
        self.cancelMeasurement()
        if self._tool_controller.active_interaction == InteractionType.SERVICE_QA:
            if self._qa_controller is not None:
                self._qa_controller.delete_selected()
            return
        if self._tool_controller.active_interaction == InteractionType.ANNOTATE_TEXT:
            self._text_annotation_controller.deleteSelected()
            return
        if self._measurement_context(0, 0) is not None:
            self.activeAnnotationController.delete_selected()

    @Property('QVariantMap', notify=preferencesChanged)
    def crosshairStyle(self) -> dict:
        return {
            "centerGap": 0,
            "lineWidth": 0,
            "horizontalColor": "transparent",
            "verticalColor": "transparent",
        }

    @Property(QPointF, notify=crosshairImagePositionChanged)
    def crosshairImagePosition(self) -> QPointF:
        return QPointF(-1.0, -1.0)

    @Property(bool, notify=crosshairImagePositionChanged)
    def hasCrosshair(self) -> bool:
        return False

    @Property(str, notify=crosshairHoverTargetChanged)
    def crosshairHoverTarget(self) -> str:
        return ""

    @Property(float, notify=crosshairImagePositionChanged)
    def crosshairRotationDegrees(self) -> float:
        return 0.0

    @Property('QVariantMap', notify=directionLabelsChanged)
    def directionLabels(self) -> dict:
        if self._frame_meta is None:
            return self._empty_direction_labels()

        orientation = (
            self._frame_meta
            .geometry
            .image_orientation_patient
        )

        if orientation is None:
            return self._empty_direction_labels()

        return displayed_image_edge_labels(
            image_orientation_patient=orientation,
            rotation_degrees=self._state.rotation_degrees,
            horizontal_flip=self._state.horizontal_flip,
            vertical_flip=self._state.vertical_flip,
        ).as_dict()

    @staticmethod
    def _empty_direction_labels() -> dict[str, str]:
        return {
            "top": "",
            "right": "",
            "bottom": "",
            "left": "",
        }
