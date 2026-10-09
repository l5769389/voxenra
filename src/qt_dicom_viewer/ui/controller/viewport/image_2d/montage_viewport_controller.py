from __future__ import annotations

from qt_dicom_viewer.ui.controller.viewport.mouse_bindings import drag_interaction
from qt_dicom_viewer.i18n.messages import error_message
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
from qt_dicom_viewer.i18n.qt import translated_model_data
from PySide6.QtCore import Signal

import logging
import numpy as np
import uuid
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.color_maps import apply_color_map
from dataclasses import replace
from math import isfinite

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPointF,
    Property,
    Qt,
    Signal,
    Slot,
)

from qt_dicom_viewer.model import (
    DragUpdateEvent,
    InteractionType,
    MontageRenderRequest,
    MontageRenderResult,
    Offset,
    PanChange,
    PanContext,
    Point,
    PointerPosition,
    RenderFailure,
    ToolType,
    TwoDViewType,
    ViewportConfig,
    ViewportState,
    ViewportDisplaySettings,
    ViewportTransformAction,
    WindowLevel,
    WindowLevelChange,
    WindowLevelContext,
    ZoomChange,
    ZoomContext,
)
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.controller.viewport.operation.drag_operation import (
    DragOperation,
)
from qt_dicom_viewer.ui.controller.viewport.operation.pan_operation import (
    PanOperation,
)
from qt_dicom_viewer.ui.controller.viewport.operation.window_level_operation import (
    WindowLevelInteractionConfig,
    MR_WINDOW_LEVEL_CONFIG,
    WindowLevelOperation,
)
from qt_dicom_viewer.ui.controller.viewport.operation.zoom_operation import (
    ZoomOperation,
)
from qt_dicom_viewer.ui.controller.viewport.viewport_controller import (
    ViewportController,
)

from qt_dicom_viewer.core.color_maps import COLOR_MAPS
from qt_dicom_viewer.core.pseudocolor import color_map_options
from qt_dicom_viewer.model import DisplayStyle

logger = logging.getLogger(__name__)


class MontageSliceModel(QAbstractListModel):
    SliceIndexRole = Qt.UserRole + 1
    ImageSourceRole = Qt.UserRole + 2
    LoadStateRole = Qt.UserRole + 3
    ErrorTextRole = Qt.UserRole + 4

    def __init__(self, slice_count: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items = [
            {
                "sliceIndex": index,
                "imageSource": "",
                "loadState": "empty",
                "errorText": "",
            }
            for index in range(max(0, int(slice_count)))
        ]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.SliceIndexRole: b"sliceIndex",
            self.ImageSourceRole: b"imageSource",
            self.LoadStateRole: b"loadState",
            self.ErrorTextRole: b"errorText",
        }

    @translated_model_data
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        role_name = self.roleNames().get(role)
        if role_name is None:
            return None
        return item[role_name.decode()]

    def item(self, slice_index: int) -> dict:
        return dict(self._items[slice_index])

    def update(
        self,
        slice_index: int,
        *,
        image_source: str | None = None,
        load_state: str | None = None,
        error_text: str | None = None,
    ) -> None:
        if not 0 <= slice_index < len(self._items):
            return
        item = self._items[slice_index]
        changed_roles: list[int] = []
        values = (
            ("imageSource", image_source, self.ImageSourceRole),
            ("loadState", load_state, self.LoadStateRole),
            ("errorText", error_text, self.ErrorTextRole),
        )
        for key, value, role in values:
            if value is not None and item[key] != value:
                item[key] = value
                changed_roles.append(role)
        if changed_roles:
            model_index = self.index(slice_index, 0)
            self.dataChanged.emit(model_index, model_index, changed_roles)

    def clear_image(self, slice_index: int) -> str:
        item = self._items[slice_index]
        source = item["imageSource"]
        self.update(
            slice_index,
            image_source="",
            load_state="empty",
            error_text="",
        )
        return source


class MontageViewportController(ViewportController):
    exportReadinessChanged = Signal()

    @Property(bool, notify=exportReadinessChanged)
    def exportReady(self):
        return bool(self._visible_indices) and all(
            self._slice_model.item(index)["loadState"] == "ready"
            for index in self._visible_indices
        )
    _i18n_colorMapOptions = Signal()
    _i18n_descriptionSummary = Signal()
    _i18n_patientName = Signal()
    _i18n_patientSummary = Signal()
    _i18n_seriesDescription = Signal()


    columnCountChanged = Signal()
    detailsExpandedChanged = Signal()
    displayStateChanged = Signal()
    transformChanged = Signal()
    activeInteractionChanged = Signal()
    imageRemovalRequested = Signal(str)
    sliceOpenRequested = Signal(str, int, float, float, bool)

    def __init__(
        self,
        viewport_config: ViewportConfig,
        tool_controller: ToolController,
        parent: QObject | None = None,
    ) -> None:
        if viewport_config.viewport_type != TwoDViewType.MONTAGE:
            raise ValueError(
                "MontageViewportController requires a montage viewport config"
            )
        super().__init__(viewport_config, parent)
        slice_count = viewport_config.series_meta.slice_count
        self._state = ViewportState(
            slice_index=None,
            slice_count=slice_count,
        )
        self._slice_model = MontageSliceModel(slice_count, self)
        self._slice_model.dataChanged.connect(self.exportReadinessChanged)
        self._tool_controller = tool_controller
        self._state = replace(self._state, display_settings=ViewportDisplaySettings(hide_sensitive_info=self.settingsController.section("privacy")["hideIdentity"]))
        self._set_default_color_map()
        self.settingsController.sectionChanged.connect(self._preferences_changed)
        self._column_count = 4
        self._details_expanded = True
        self._baseline_window: WindowLevel | None = None
        self._automatic_window: WindowLevel | None = None
        self._visible_indices: set[int] = set()
        self._retained_indices: set[int] = set()
        self._dirty_indices: set[int] = set()
        self._active_request: tuple[str, int, int] | None = None
        self._display_revision = 0
        self._image_revisions: dict[int, int] = {}
        self._display_samples: dict[int, np.ndarray] = {}
        self._display_polarities: dict[int, bool] = {}
        self._display_palettes: dict[int, np.ndarray | None] = {}
        self._display_values: dict[int, np.ndarray] = {}
        self._display_frames: dict[int, object] = {}
        self._disposed = False

        self._active_drag_operation: DragOperation | None = None
        self._active_drag_start: PointerPosition | None = None
        self._interaction_width = 1.0
        self._interaction_height = 1.0
        self._window_operation = WindowLevelOperation(
            replace(MR_WINDOW_LEVEL_CONFIG, allow_inversion=False) if self.isMrViewport
            else WindowLevelInteractionConfig(allow_inversion=False)
        )
        self._pan_operation = PanOperation()
        self._zoom_operation = ZoomOperation()
        self._tool_controller.activeInteractionChanged.connect(
            self.activeInteractionChanged.emit
        )

    def _set_default_color_map(self):
        category = "pet" if self.modality.upper() in ("PT", "PET") else "gray"
        name = self.settingsController.section("colormap")[category]
        self._state = replace(self._state, display_style=DisplayStyle(name, COLOR_MAPS[name][1][0]))

    def _preferences_changed(self, section):
        if section == "colormap":
            before = self._state.display_style
            self._set_default_color_map()
            if before != self._state.display_style:
                self.displayStateChanged.emit()
                self.request_render()

    @_TextProperty('QVariantList', notify=_i18n_colorMapOptions, notify_name='_i18n_colorMapOptions')
    def colorMapOptions(self):
        return color_map_options()

    @Property(str, notify=displayStateChanged)
    def activeColorMap(self):
        return self._state.display_style.color_map

    @Slot(str)
    def applyColorMap(self, name):
        if name not in COLOR_MAPS or self._disposed or name == self.activeColorMap:
            return
        self._state = replace(self._state, display_style=DisplayStyle(name, COLOR_MAPS[name][1][0]))
        self.displayStateChanged.emit()
        self.request_render()

    @Property(bool, constant=True)
    def supportsCtWindow(self):
        return self.modality.upper() == "CT" and self.viewport_config.series_meta.supports_ct_analysis

    @Property(bool, constant=True)
    def isMrViewport(self):
        return self.modality.upper() == "MR"

    @Property(bool, constant=True)
    def supportsGrayscaleWindow(self):
        return self.modality.upper() in ("CT", "MR")

    @Property(float, constant=True)
    def minimumWindowWidth(self):
        return 0.001 if self.isMrViewport else 1.0

    @Slot()
    def autoWindow(self):
        if self.isMrViewport and self._automatic_window is not None and not self._disposed:
            self._set_window(self._automatic_window)

    @Slot()
    def toggleInverted(self):
        if not self._disposed and self.hasWindow and self.supportsGrayscaleWindow:
            self._state = replace(self._state, inverted=not self.inverted)
            self.displayStateChanged.emit()
            self.request_render()

    @Property(QObject, constant=True)
    def sliceModel(self) -> QObject:
        return self._slice_model

    @Property(str, constant=True)
    def seriesUid(self) -> str:
        return self.viewport_config.series_uid

    @_TextProperty(str, notify=_i18n_seriesDescription, notify_name='_i18n_seriesDescription')
    def seriesDescription(self) -> str:
        return self.viewport_config.series_meta.series_description

    @_TextProperty(str, notify=_i18n_patientName, notify_name='_i18n_patientName', source_notify='transformChanged')
    def patientName(self) -> str:
        return "—" if self._state.display_settings.hide_sensitive_info else self.viewport_config.series_meta.patient_name or "—"

    @_TextProperty(str, notify=_i18n_patientSummary, notify_name='_i18n_patientSummary', source_notify='transformChanged')
    def patientSummary(self) -> str:
        if self._state.display_settings.hide_sensitive_info: return "—"
        meta = self.viewport_config.series_meta
        values = [meta.patient_id.strip()]
        sex = {
            "M": _msg('text.0598'),
            "F": _msg('text.0599'),
            "O": _msg('text.0600'),
        }.get(meta.patient_sex.strip().upper(), meta.patient_sex.strip())
        if sex:
            values.append(sex)
        age = meta.patient_age.strip()
        if len(age) == 4 and age[:3].isdigit():
            amount = str(int(age[:3]))
            unit = {
                "Y": _msg('text.0601'),
                "M": _msg('text.0602'),
                "W": _msg('text.0603'),
                "D": _msg('text.0604'),
            }.get(age[3].upper(), age[3])
            age = f"{amount}{unit}"
        if age:
            values.append(age)
        return " / ".join(value for value in values if value) or "—"

    @_TextProperty(str, notify=_i18n_descriptionSummary, notify_name='_i18n_descriptionSummary')
    def descriptionSummary(self) -> str:
        meta = self.viewport_config.series_meta
        series_description = meta.series_description.strip()
        if meta.series_number is not None:
            series_description = (
                f"Series {meta.series_number}"
                + (f" · {series_description}" if series_description else "")
            )
        return " / ".join(
            value
            for value in (
                meta.study_description.strip(),
                series_description,
            )
            if value
        ) or "—"

    @Property(str, constant=True)
    def scanParameters(self) -> str:
        meta = self.viewport_config.series_meta
        if self.isMrViewport:
            from qt_dicom_viewer.core.mr import format_mr_parameters
            return format_mr_parameters(meta.mr_parameters) or "—"
        values: list[str] = []
        if meta.kvp is not None:
            values.append(f"{self._format_number(meta.kvp)} kV")
        if meta.tube_current_ma is not None:
            values.append(
                f"{self._format_number(meta.tube_current_ma)} mA"
            )
        return " / ".join(values) or "—"

    @Property(str, constant=True)
    def acquisitionDateTime(self) -> str:
        return (
            self.viewport_config.series_meta.acquisition_datetime
            or "—"
        )

    @Property(str, constant=True)
    def sliceThickness(self) -> str:
        thickness = self.viewport_config.series_meta.slice_thickness
        if thickness is None:
            return "—"
        return f"{self._format_number(thickness)} mm"

    @staticmethod
    def _format_number(value: float) -> str:
        return f"{float(value):.3f}".rstrip("0").rstrip(".")

    @Property(str, constant=True)
    def modality(self) -> str:
        return self.viewport_config.series_meta.modality

    @Property(int, constant=True)
    def sliceCount(self) -> int:
        return self._state.slice_count or 0

    @Property(bool, notify=detailsExpandedChanged)
    def detailsExpanded(self):
        return self._details_expanded

    @Slot()
    def toggleDetails(self):
        self._details_expanded = not self._details_expanded
        self.detailsExpandedChanged.emit()

    @Property(int, notify=columnCountChanged)
    def columnCount(self) -> int:
        return self._column_count

    @Slot(int)
    def setColumnCount(self, count: int) -> None:
        count = max(2, min(int(count), 6))
        if count == self._column_count:
            return
        self._column_count = count
        self.columnCountChanged.emit()

    @Property(bool, notify=displayStateChanged)
    def hasWindow(self) -> bool:
        return self._state.window is not None

    @Property(float, notify=displayStateChanged)
    def windowCenter(self) -> float:
        return 0.0 if self._state.window is None else self._state.window.center

    @Property(float, notify=displayStateChanged)
    def windowWidth(self) -> float:
        return 0.0 if self._state.window is None else self._state.window.width

    @Property(bool, notify=displayStateChanged)
    def inverted(self) -> bool:
        return self._state.inverted

    @Property(QObject, constant=True)
    def settingsController(self):
        return self._tool_controller.settingsController

    @Property(float, notify=transformChanged)
    def panX(self) -> float:
        """Horizontal pan as a fraction of the tile width."""
        return self._state.pan_x

    @Property(float, notify=transformChanged)
    def panY(self) -> float:
        """Vertical pan as a fraction of the tile height."""
        return self._state.pan_y

    @Property(float, notify=transformChanged)
    def zoom(self) -> float:
        return self._state.zoom

    @Property(float, notify=transformChanged)
    def rotationDegrees(self) -> float:
        return self._state.rotation_degrees

    @Property(bool, notify=transformChanged)
    def horizontalFlip(self) -> bool:
        return self._state.horizontal_flip

    @Property(bool, notify=transformChanged)
    def verticalFlip(self) -> bool:
        return self._state.vertical_flip

    @Property(float, constant=True)
    def imageAspectRatio(self) -> float:
        meta = self.viewport_config.series_meta
        rows = meta.rows or 0
        columns = meta.columns or 0
        if rows <= 0 or columns <= 0:
            return 1.0
        row_spacing = meta.pixel_spacing.row if meta.pixel_spacing else 1.0
        column_spacing = meta.pixel_spacing.column if meta.pixel_spacing else 1.0
        ratio = columns * column_spacing / max(rows * row_spacing, 1e-6)
        return max(0.5, min(float(ratio), 2.0))

    @Property(str, notify=activeInteractionChanged)
    def activeInteraction(self) -> str:
        return self._tool_controller.activeInteraction

    @property
    def viewport_state(self) -> ViewportState:
        return self._state

    def request_first_loader(self) -> None:
        if self.sliceCount <= 0 or self._disposed:
            return
        self._dirty_indices.add(0)
        self._start_next_request()

    def request_render(self) -> None:
        if self._disposed:
            return
        self._display_revision += 1
        if self._state.window is not None:
            for index, pixels in self._display_samples.items():
                from qt_dicom_viewer.core.display_mapping import map_display
                frame = self._display_frames[index]
                gray = DicomLoader.apply_window(pixels, self._state.window,
                    self.inverted ^ self._display_polarities.get(index, False), self.minimumWindowWidth)
                image = map_display(gray, self._display_values[index], frame.pixel_value_meta,
                    frame.supplemental_overlay, frame.source_palette, self._state.display_mapping, self.activeColorMap)
                self.imageUpdateRequested.emit(self.image_key(index), image)
                self._publish_slice(index)
        self._dirty_indices.update(self._retained_indices)
        self._start_next_request()

    @Slot(int, int)
    def setVisibleRange(self, first: int, last: int) -> None:
        if self.sliceCount <= 0 or self._disposed:
            return
        first = max(0, min(int(first), self.sliceCount - 1))
        last = max(first, min(int(last), self.sliceCount - 1))
        visible = set(range(first, last + 1))
        retained_first = max(0, first - self._column_count)
        retained_last = min(
            self.sliceCount - 1,
            last + self._column_count,
        )
        retained = set(range(retained_first, retained_last + 1))

        for slice_index in self._retained_indices - retained:
            self._display_samples.pop(slice_index, None)
            self._display_polarities.pop(slice_index, None)
            self._display_palettes.pop(slice_index, None)
            self._display_values.pop(slice_index, None)
            self._display_frames.pop(slice_index, None)
            self._dirty_indices.discard(slice_index)
            source = self._slice_model.clear_image(slice_index)
            if source:
                self.imageRemovalRequested.emit(self.image_key(slice_index))

        self._visible_indices = visible
        self.exportReadinessChanged.emit()
        self._retained_indices = retained
        for slice_index in retained:
            item = self._slice_model.item(slice_index)
            if item["loadState"] == "empty":
                self._dirty_indices.add(slice_index)
        self._start_next_request()

    @Slot(int)
    def retrySlice(self, slice_index: int) -> None:
        if not 0 <= slice_index < self.sliceCount or self._disposed:
            return
        self._slice_model.update(
            slice_index,
            load_state="empty",
            error_text="",
        )
        self._dirty_indices.add(slice_index)
        self._start_next_request()

    def _next_dirty_index(self) -> int | None:
        if self._baseline_window is None:
            if 0 in self._dirty_indices:
                return 0
            visible = sorted(self._dirty_indices & self._visible_indices)
            if visible:
                return visible[0]
            retained = sorted(self._dirty_indices & self._retained_indices)
            return retained[0] if retained else None
        visible = sorted(self._dirty_indices & self._visible_indices)
        if visible:
            return visible[0]
        retained = sorted(self._dirty_indices & self._retained_indices)
        return retained[0] if retained else None

    def _start_next_request(self) -> None:
        if self._active_request is not None or self._disposed:
            return
        slice_index = self._next_dirty_index()
        if slice_index is None:
            return
        self._dirty_indices.discard(slice_index)
        request = MontageRenderRequest(
            request_id=str(uuid.uuid4()),
            viewport_id=self.viewport_config.viewport_id,
            series_uid=self.viewport_config.series_uid,
            slice_index=slice_index,
            window=self._state.window if self._baseline_window else None,
            inverted=self.inverted,
            color_map=self.activeColorMap,
            display_mapping=self._state.display_mapping,
        )
        self._active_request = (
            request.request_id,
            slice_index,
            self._display_revision,
        )
        if not self._slice_model.item(slice_index)["imageSource"]:
            self._slice_model.update(
                slice_index,
                load_state="loading",
                error_text="",
            )
        self.renderRequested.emit(request)

    def accepts_result(self, result: MontageRenderResult) -> bool:
        active = self._active_request
        if (
            not isinstance(result, MontageRenderResult)
            or active is None
            or result.response_id != active[0]
            or result.slice_index != active[1]
        ):
            return False

        _, slice_index, request_revision = active
        bootstrap = self._baseline_window is None
        if (
            request_revision != self._display_revision
            or (not bootstrap and slice_index not in self._retained_indices)
        ):
            self._active_request = None
            if slice_index not in self._retained_indices:
                self._slice_model.clear_image(slice_index)
            if slice_index in self._retained_indices or bootstrap:
                self._dirty_indices.add(slice_index)
            self._start_next_request()
            return False
        return True

    def handleRenderResult(self, result: MontageRenderResult) -> None:
        if not isinstance(result, MontageRenderResult):
            raise TypeError(
                "MontageViewportController requires MontageRenderResult"
            )
        active = self._active_request
        if active is None or result.response_id != active[0]:
            return
        self._active_request = None

        if self._baseline_window is None:
            self._baseline_window = result.frame_meta.window
            self._automatic_window = result.frame_meta.automatic_window
            self._state = replace(
                self._state,
                window=self._baseline_window,
                inverted=False,
            )
            self.displayStateChanged.emit()
            self._dirty_indices.update(
                self._retained_indices - {result.slice_index}
            )

        slice_index = result.slice_index
        if slice_index in self._retained_indices:
            if result.modality_pixel is not None:
                self._display_samples[slice_index] = result.frame_meta.window_pixels if result.frame_meta.window_pixels is not None else result.modality_pixel
                self._display_palettes[slice_index] = result.frame_meta.supplemental_overlay
                self._display_values[slice_index] = result.modality_pixel
                self._display_frames[slice_index] = result.frame_meta
                self.accept_mapping_frame(result.frame_meta)
                self._display_polarities[slice_index] = (self.isMrViewport and
                    result.frame_meta.instance_meta.photometric_interpretation == "MONOCHROME1")
            self._publish_slice(slice_index)
        else:
            # The initial slice can finish before the asynchronous grid exists.
            # A discarded image is empty, not still loading; the future visible
            # range must be able to request it again.
            self._slice_model.clear_image(slice_index)
            self.imageRemovalRequested.emit(result.image_key)
        self._start_next_request()

    def _publish_slice(self, slice_index):
        revision = self._image_revisions.get(slice_index, 0) + 1
        self._image_revisions[slice_index] = revision
        self._slice_model.update(slice_index,
            image_source=f"image://dicom/{self.image_key(slice_index)}/{revision}",
            load_state="ready", error_text="")

    def handleRenderFailure(self, failure: RenderFailure) -> None:
        active = self._active_request
        if active is None or failure.request_id != active[0]:
            return
        _, slice_index, request_revision = active
        self._active_request = None
        if (
            request_revision != self._display_revision
            and (slice_index in self._retained_indices or self._baseline_window is None)
        ):
            self._dirty_indices.add(slice_index)
        elif slice_index in self._retained_indices:
            self._slice_model.update(
                slice_index,
                load_state="error",
                error_text=error_message(failure.error) or _msg('text.0605'),
            )
        else:
            self._slice_model.clear_image(slice_index)
        self._start_next_request()

    @staticmethod
    def image_key_for(viewport_id: str, slice_index: int) -> str:
        return f"{viewport_id}:slice:{slice_index}"

    def image_key(self, slice_index: int) -> str:
        return self.image_key_for(self.viewportId, slice_index)

    @Slot(float, float, int, float, float)
    def beginInteraction(
        self,
        x: float,
        y: float,
        buttons: int,
        viewport_width: float,
        viewport_height: float,
    ) -> None:
        self._active_drag_operation = None
        self._active_drag_start = PointerPosition(Point(x, y), None)
        self._interaction_width = max(float(viewport_width), 1.0)
        self._interaction_height = max(float(viewport_height), 1.0)
        context = None

        match drag_interaction(self._tool_controller.active_interaction, buttons, self.settingsController.section("input")):
            case InteractionType.WINDOW if self._state.window is not None:
                mapping_window = self.mapping_drag_window(self._state.window)
                if mapping_window is None:
                    return
                self._active_drag_operation = self._window_operation
                context = WindowLevelContext(
                    viewport_size=(
                        self._interaction_width,
                        self._interaction_height,
                    ),
                    inverted=False,
                    current_window=mapping_window,
                )
            case InteractionType.PAN:
                self._active_drag_operation = self._pan_operation
                context = PanContext(
                    current_pan_x=(
                        self._state.pan_x * self._interaction_width
                    ),
                    current_pan_y=(
                        self._state.pan_y * self._interaction_height
                    ),
                )
            case InteractionType.ZOOM:
                self._active_drag_operation = self._zoom_operation
                context = ZoomContext(
                    viewport_size=(
                        self._interaction_width,
                        self._interaction_height,
                    ),
                    current_zoom=self._state.zoom,
                )
        if self._active_drag_operation is not None and context is not None:
            self._active_drag_operation.begin(self._active_drag_start, context)

    @Slot(QPointF, QPointF, QPointF, QPointF)
    def updateInteraction(
        self,
        start_point: QPointF,
        current_point: QPointF,
        step_offset: QPointF,
        total_offset: QPointF,
    ) -> None:
        del start_point
        operation = self._active_drag_operation
        start = self._active_drag_start
        if operation is None or start is None:
            return
        current = PointerPosition(
            Point(current_point.x(), current_point.y()),
            None,
        )
        preferences = self.settingsController.section("input")
        factor = preferences["zoomSensitivity"] if operation is self._zoom_operation else (
            preferences["windowSensitivity"] if isinstance(operation, WindowLevelOperation) else 1.0)
        step_offset = QPointF(step_offset.x() * factor, step_offset.y() * factor)
        total_offset = QPointF(total_offset.x() * factor, total_offset.y() * factor)
        result = operation.update(
            DragUpdateEvent(
                start_position=start,
                current_position=current,
                step_offset=Offset(step_offset.x(), step_offset.y()),
                total_offset=Offset(total_offset.x(), total_offset.y()),
            )
        )
        self._apply_interaction_result(result)

    @Slot(float, float)
    def endInteraction(self, x: float, y: float) -> None:
        operation = self._active_drag_operation
        self._active_drag_operation = None
        self._active_drag_start = None
        if operation is None:
            return
        result = operation.end(Point(x, y))
        self._apply_interaction_result(result)

    def _apply_interaction_result(self, result) -> None:
        match result:
            case WindowLevelChange(window=window):
                if not self.apply_mapping_drag(window):
                    self._set_window(window)
            case PanChange(offset_x=x, offset_y=y):
                self.apply_pan(x, y)
            case ZoomChange(zoom=zoom):
                self.apply_zoom(zoom)
            case _:
                return

    def _set_window(self, window: WindowLevel) -> None:
        if self._baseline_window is None:
            return
        window = WindowLevel(
            center=float(window.center),
            width=max(float(window.width), self.minimumWindowWidth),
        )
        if self._state.window == window:
            return
        self._state = replace(self._state, window=window)
        self.displayStateChanged.emit()
        self.request_render()

    @Slot(float, float)
    def applyWindowPreset(self, center: float, width: float) -> None:
        if not isfinite(center) or not isfinite(width):
            return
        self._set_window(WindowLevel(center=center, width=width))

    def apply_pan(self, x: float, y: float) -> None:
        normalized_x = float(x) / self._interaction_width
        normalized_y = float(y) / self._interaction_height
        if (
            abs(normalized_x - self._state.pan_x) < 1e-6
            and abs(normalized_y - self._state.pan_y) < 1e-6
        ):
            return
        self._state = replace(
            self._state,
            pan_x=normalized_x,
            pan_y=normalized_y,
        )
        self.transformChanged.emit()

    @Slot(float)
    def setZoom(self, zoom: float) -> None:
        """Set an absolute multiple of the default fitted view."""
        self.apply_zoom(zoom)

    def apply_zoom(self, zoom: float) -> None:
        if not isfinite(zoom):
            return
        zoom = max(0.1, min(float(zoom), 20.0))
        if abs(zoom - self._state.zoom) < 0.0001:
            return
        self._state = replace(self._state, zoom=zoom)
        self.transformChanged.emit()

    @Slot(str)
    def applyTransformAction(self, action: str) -> None:
        try:
            transform = ViewportTransformAction(action)
        except ValueError:
            logger.warning("Unsupported montage transform: %s", action)
            return
        state = self._state
        match transform:
            case ViewportTransformAction.ROTATE_CLOCKWISE_90:
                next_state = replace(
                    state,
                    rotation_degrees=(state.rotation_degrees + 90.0) % 360.0,
                )
            case ViewportTransformAction.ROTATE_COUNTERCLOCKWISE_90:
                next_state = replace(
                    state,
                    rotation_degrees=(state.rotation_degrees - 90.0) % 360.0,
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
        if next_state != state:
            self._state = next_state
            self.transformChanged.emit()

    def reset_tool_state(self, tool_type: ToolType) -> None:
        state = self._state
        match tool_type:
            case ToolType.WINDOW:
                if self.displayMapping["customRange"]:
                    self.setDisplayMappingMode("source")
                    return
                if self._baseline_window is not None:
                    changed = state.window != self._baseline_window or state.inverted
                    self._state = replace(state, window=self._baseline_window, inverted=False)
                    if changed:
                        self.displayStateChanged.emit()
                        self.request_render()
            case ToolType.PSEUDOCOLOR:
                self._set_default_color_map()
                if self._state.display_style != state.display_style:
                    self.displayStateChanged.emit()
                    self.request_render()
            case ToolType.PAN:
                if state.pan_x or state.pan_y:
                    self._state = replace(state, pan_x=0.0, pan_y=0.0)
                    self.transformChanged.emit()
            case ToolType.ZOOM:
                if state.zoom != 1.0:
                    self._state = replace(state, zoom=1.0)
                    self.transformChanged.emit()
            case ToolType.ROTATE:
                if (
                    state.rotation_degrees
                    or state.horizontal_flip
                    or state.vertical_flip
                ):
                    self._state = replace(
                        state,
                        rotation_degrees=0.0,
                        horizontal_flip=False,
                        vertical_flip=False,
                    )
                    self.transformChanged.emit()

    def reset_all_view_state(self) -> None:
        from qt_dicom_viewer.model.display_mapping import DisplayMappingIntent
        mapping_changed = self._state.display_mapping.mode != "source"
        self._state = replace(self._state, display_mapping=DisplayMappingIntent())
        self.displayMappingChanged.emit()
        state = self._state
        window_changed = (
            self._baseline_window is not None
            and state.window != self._baseline_window
        )
        window_changed = window_changed or state.inverted or mapping_changed
        self._set_default_color_map()
        default_style = self._state.display_style
        window_changed = window_changed or default_style != state.display_style
        transform_changed = any((
            state.pan_x,
            state.pan_y,
            state.zoom != 1.0,
            state.rotation_degrees,
            state.horizontal_flip,
            state.vertical_flip,
        ))
        self._state = replace(
            state,
            window=self._baseline_window or state.window,
            display_style=default_style,
            inverted=False,
            pan_x=0.0,
            pan_y=0.0,
            zoom=1.0,
            rotation_degrees=0.0,
            horizontal_flip=False,
            vertical_flip=False,
        )
        if transform_changed:
            self.transformChanged.emit()
        if window_changed:
            self.displayStateChanged.emit()
            self.request_render()

    @Slot(int)
    def openSlice(self, slice_index: int) -> None:
        if not 0 <= slice_index < self.sliceCount or self._state.window is None:
            return
        self.sliceOpenRequested.emit(
            self.seriesUid,
            slice_index,
            self._state.window.center,
            self._state.window.width,
            self.inverted,
        )

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._display_samples.clear()
        self._display_polarities.clear()
        self._display_palettes.clear()
        self._display_values.clear()
        self._display_frames.clear()
        self._dirty_indices.clear()
        self._active_request = None
        for slice_index in range(self.sliceCount):
            source = self._slice_model.item(slice_index)["imageSource"]
            if source:
                self.imageRemovalRequested.emit(self.image_key(slice_index))
                self._slice_model.clear_image(slice_index)
