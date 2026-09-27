from qt_dicom_viewer.i18n.qt import translated_property as _TextProperty
import uuid
from math import degrees, hypot, radians
from typing import cast

import numpy as np
from PySide6.QtCore import Property, QPointF, Signal, Slot, QObject

from qt_dicom_viewer.model import (
    CrosshairCenterChange,
    CrosshairMoveContext,
    CrosshairRotationChange,
    CrosshairRotationContext,
    ImagePoint,
    InteractionType,
    InteractionResult,
    MprImageGeometry,
    Mpr3DRotationChange,
    Mpr3DRotationContext,
    MprPlane,
    MprProjectionSettings,
    MprRenderRequest,
    MprRenderResult,
    OperationStartContext,
    PointerHoverContext,
    PointerPosition,
    RenderRequest,
    RenderResult,
    Vector3,
    ViewportConfig, MprFrame, MprState,
    CrosshairTargetKind,
)
from qt_dicom_viewer.core.mpr_rotation import resolve_sampling_basis
from qt_dicom_viewer.model.interaction import WindowLevelChange
from qt_dicom_viewer.model.ui_models import CrosshairColor, CrosshairStyle
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from .image_2d_viewport_controller import (
    Image2DViewportController,
)
from qt_dicom_viewer.ui.controller.viewport.operation.crosshair_move_operation import (
    CrosshairMoveOperation,
)
from qt_dicom_viewer.ui.controller.viewport.operation.crosshair_rotate_operation import (
    CrosshairRotateOperation,
)
from qt_dicom_viewer.ui.controller.viewport.operation.mpr_3d_rotate_operation import (
    Mpr3DRotateOperation,
)
from qt_dicom_viewer.ui.controller.viewport.operation.drag_operation import DragOperation

_CROSSHAIR_STYLES = {
    MprPlane.AXIAL: CrosshairColor("green", "blue"),
    MprPlane.CORONAL: CrosshairColor("red", "blue"),
    MprPlane.SAGITTAL: CrosshairColor("red", "green"),
}


class MprViewportController(Image2DViewportController):
    _i18n_voiOverlays = Signal()

    @Slot(float, float)
    def setBrushViewMetrics(self, pixels_per_mm, shortest_side):
        # QML supplies logical pixels for both dimensions, independent of DPR.
        self._brush_view_metrics = (pixels_per_mm, shortest_side)



    voiChanged = Signal()
    voiMasksChanged = Signal()
    crosshairCenterChangeRequested = Signal(object)
    crosshairRotationRequested = Signal(object, float)
    mpr3DRotationRequested = Signal(object, float)
    renderInvalidated = Signal(str)
    linkedWindowChangeRequested = Signal(object)
    mprSlabGuidesChanged = Signal()

    def __init__(
            self,
            viewport_config: ViewportConfig,
            tool_controller: ToolController,
            parent=None,
    ) -> None:
        if not isinstance(viewport_config.viewport_type, MprPlane):
            raise ValueError(
                "MprViewportController requires an MPR plane config"
            )
        super().__init__(viewport_config, tool_controller, parent)
        self.linked_window = False
        self._voi_controller = getattr(parent, "_voi_controller", None)
        self._voi_volume = None
        self._voi_drag_active = False
        if self._voi_controller is not None:
            self._voi_controller.overlaysChanged.connect(self.voiChanged.emit)
            self._voi_controller.masksChanged.connect(self.voiMasksChanged.emit)
        self._plane_geometry: MprImageGeometry | None = None
        self._mpr_state: MprState | None = None
        self._crosshair_image_position: ImagePoint | None = None
        self._crosshair_hover_target: CrosshairTargetKind | None = None
        self._crosshair_operation = CrosshairMoveOperation()
        self._crosshair_rotate_operation = CrosshairRotateOperation()
        self._mpr_3d_rotate_operation = Mpr3DRotateOperation()
        self._crosshair_style = CrosshairStyle(
            _CROSSHAIR_STYLES[viewport_config.viewport_type]
        )
        self.preferencesChanged.connect(self.mprSlabGuidesChanged.emit)
        self._tool_controller.mprProjectionChanged.connect(
            self.mprSlabGuidesChanged.emit
        )

    def build_mpr_render_request(
            self,
            *,
            mpr_frame: MprFrame | None = None,
            view_roll_radians: float = 0.0,
            mpr_state: MprState | None = None,
            phase_identifier: int | None = None,
            initial: bool = False,
    ) -> MprRenderRequest:
        state = self.viewport_state
        if mpr_state is not None:
            mpr_frame = mpr_state.frame
            view_roll_radians = mpr_state.view_rolls.for_plane(
                self.viewport_config.viewport_type
            )
        if isinstance(self.viewport_config.viewport_type, MprPlane):
            projection_mode, slab_thickness_mm = (
                self._tool_controller.mpr_projection_settings
                .effective_projection_for_plane(
                    self.viewport_config.viewport_type
                )
            )
            return MprRenderRequest(
                request_id=str(uuid.uuid4()),
                viewport_id=self.viewport_config.viewport_id,
                series_uid=self.viewport_config.series_uid,
                window=None if initial else state.window,
                inverted=False if initial else state.inverted,
                color_map=state.display_style.color_map,
                plane=self.viewport_config.viewport_type,
                mpr_frame=mpr_frame,
                phase_identifier=phase_identifier,
                view_roll_radians=view_roll_radians,
                mpr_grid=(
                    mpr_state.view_grids.for_plane(
                        self.viewport_config.viewport_type
                    )
                    if (
                        mpr_state is not None
                        and mpr_state.view_grids is not None
                    )
                    else None
                ),
                mpr_grid_anchor=(
                    mpr_state.view_anchors.for_plane(
                        self.viewport_config.viewport_type
                    )
                    if (
                        mpr_state is not None
                        and mpr_state.view_anchors is not None
                    )
                    else None
                ),
                projection_mode=projection_mode,
                slab_thickness_mm=float(slab_thickness_mm),
            )
        raise TypeError("MprViewportController requires MprPlane")

    def _build_render_request(self, *, initial: bool) -> RenderRequest:
        return self.build_mpr_render_request(
            mpr_frame=None,
            initial=initial,
        )

    def apply_window_level(self, result: WindowLevelChange) -> None:
        if self.linked_window:
            self.linkedWindowChangeRequested.emit(result)
        else:
            super().apply_window_level(result)

    def request_render(self) -> None:
        """Report stale local state; TabController decides when to render."""
        self.renderInvalidated.emit(
            self.viewport_config.viewport_id
        )

    def _validate_render_result(self, result: RenderResult) -> None:
        if not isinstance(result, MprRenderResult):
            raise TypeError("MprViewportController requires MprRenderResult")
        if result.view_type != self.viewport_config.viewport_type:
            raise ValueError("MPR render result targets a different plane")

    def _apply_specific_render_result(self, result: RenderResult) -> None:
        mpr_result = cast(MprRenderResult, result)
        geometry = mpr_result.plane_geometry
        if (self._voi_controller is not None and self._voi_controller._draft
                and self._voi_controller._draft["viewport"] is self
                and geometry != self._plane_geometry):
            self._voi_controller.cancel()
        self._plane_geometry = geometry
        self._crosshair_image_position = None

        if geometry is not None:
            anchor = None
            if (
                self._mpr_state is not None
                and self._mpr_state.view_anchors is not None
            ):
                anchor = self._mpr_state.view_anchors.for_plane(
                    self.viewport_config.viewport_type
                )
            if anchor is None:
                column, row = geometry.mpr_point_to_image_point(
                    (0.0, 0.0, 0.0)
                )
            else:
                # 渲染结果可能属于一次较早的合并请求。十字线必须继续
                # 使用最新目标状态的 anchor，不能被旧结果拉回旧位置。
                column, row = anchor.column, anchor.row
            self._crosshair_image_position = ImagePoint(
                column=column,
                row=row,
            )

        self.crosshairImagePositionChanged.emit()
        self.mprSlabGuidesChanged.emit()
        self._voi_volume = mpr_result.volume
        if self._voi_controller is not None:
            self._voi_phase = self._voi_controller.phaseIndex
            self._voi_controller.set_source(mpr_result.volume)
        self.voiChanged.emit()
        self.voiMasksChanged.emit()

    @Property(QObject, constant=True)
    def voiController(self):
        return self._voi_controller

    @_TextProperty('QVariantList', notify=_i18n_voiOverlays, notify_name='_i18n_voiOverlays', source_notify='voiChanged')
    def voiOverlays(self):
        return self._voi_controller.overlays(self) if self._voi_controller else []

    @Property('QVariantList', notify=voiMasksChanged)
    def voiMasks(self):
        return self._voi_controller.masks(self) if self._voi_controller else []

    def _voi_mode(self):
        return self._voi_controller is not None and self.activeInteraction in ("mpr:segmentation", "mpr:voi")

    @Slot(float, float, int, bool, float, float, float, float)
    def beginInteraction(self, x, y, buttons, image_valid, column, row, endpoint_tolerance, line_tolerance):
        if self._voi_mode() and buttons & 1:
            self.cancelMeasurement()
            self._voi_drag_active = True
            if image_valid:
                self._voi_controller.begin(self, column, row, endpoint_tolerance)
            return
        super().beginInteraction(x, y, buttons, image_valid, column, row, endpoint_tolerance, line_tolerance)

    @Slot(QPointF, QPointF, QPointF, QPointF, bool, float, float)
    def updateInteraction(self, start, current, step, total, image_valid, column, row):
        if self._voi_drag_active:
            self._voi_controller.update(self, column, row)
            return
        super().updateInteraction(start, current, step, total, image_valid, column, row)

    @Slot(float, float, bool, float, float)
    def endInteraction(self, x, y, image_valid, column, row):
        if self._voi_drag_active:
            self._voi_drag_active = False
            self._voi_controller.finish(self, column, row)
            return
        super().endInteraction(x, y, image_valid, column, row)

    @Slot()
    def cancelMeasurement(self):
        self._voi_drag_active = False
        if getattr(self, "_voi_controller", None) is not None:
            self._voi_controller.cancel()
        super().cancelMeasurement()

    @Slot()
    def deleteSelectedMeasurement(self):
        if self._voi_mode():
            self._voi_controller.remove(self._voi_controller.selectedId)
            return
        super().deleteSelectedMeasurement()


    def _get_crosshair_operation_context(
            self,
            hit_result: CrosshairTargetKind | None,
    ) -> tuple[DragOperation, OperationStartContext] | None:
        if not hit_result:
            return None
        match hit_result:
            case CrosshairTargetKind.CENTER:
                return self._crosshair_operation, CrosshairMoveContext(
                    current_pan_x=self.viewport_state.pan_x,
                    current_pan_y=self.viewport_state.pan_y,
                )
            case CrosshairTargetKind.HORIZONTAL_LINE:
                return self._crosshair_rotation_context()
            case CrosshairTargetKind.VERTICAL_LINE:
                return self._crosshair_rotation_context()
            case _:
                raise NotImplementedError("Unknown hit type")

    def _begin_specific_interaction(
            self,
            position: PointerPosition,
            endpoint_tolerance: float,
            line_tolerance: float
    ) -> tuple[DragOperation, OperationStartContext] | None:
        # 十字线交互优先于当前选中的全视口工具：中心命中用于移动，
        # 线段命中用于旋转。只有未命中十字线时，3D 旋转才接管拖动。
        hit_result = self._crosshair_hit_test(
            position,
            endpoint_tolerance,
            line_tolerance,
        )
        crosshair_interaction = self._get_crosshair_operation_context(
            hit_result
        )
        if crosshair_interaction is not None:
            return crosshair_interaction

        if (
            self._tool_controller.active_interaction
            == InteractionType.MPR_ROTATE_3D
        ):
            geometry = self._plane_geometry
            center = self._crosshair_image_position
            if geometry is None or center is None:
                return None
            return (
                self._mpr_3d_rotate_operation,
                Mpr3DRotationContext(
                    center=center,
                    row_spacing=geometry.row_spacing,
                    column_spacing=geometry.column_spacing,
                    normal_direction_patient=(
                        geometry.navigation_direction_patient
                    ),
                ),
            )
        return None

    def _apply_specific_interaction_result(
            self,
            result: InteractionResult,
    ) -> bool:
        if isinstance(result, CrosshairCenterChange):
            self._apply_crosshair_move(result.position)
            return True
        if isinstance(result, CrosshairRotationChange):
            plane = self.viewport_config.viewport_type
            state_angle = (
                self._screen_handedness()
                * result.angle_delta_radians
            )
            self.crosshairRotationRequested.emit(plane, state_angle)
            return True
        if isinstance(result, Mpr3DRotationChange):
            self.mpr3DRotationRequested.emit(
                result.axis_patient,
                # 旋转的是采样基轴；影像内容在该基轴中呈现的旋转方向
                # 与基轴自身相反，所以这里需要把屏幕角度取反。
                -self._screen_handedness()
                * result.angle_delta_radians,
            )
            return True
        return False


    def _handle_specific_pointer_hover(
            self,
            context: PointerHoverContext,
    ) -> None:
        kind = ""
        if self._voi_mode():
            kind = "default"
            point = context.position.image
            if self._voi_controller.enabled and point is not None:
                target = self._voi_controller.edit_target(self, point.column, point.row, context.point_tolerance)
                kind = ("pan" if target["mode"] == "move" else "resize") if target else self.activeInteraction.split(":")[1]
                if self.activeInteraction == "mpr:segmentation" and self._voi_controller.editMode in ("paint", "erase"):
                    kind = "segmentation-" + self._voi_controller.editMode
        if kind != self.regionCursorKind:
            self._region_cursor_kind = kind
            self.regionCursorKindChanged.emit()
        target = None if self._voi_mode() else self._crosshair_hit_test(
            position=context.position,
            center_tolerance=context.point_tolerance,
            line_tolerance=context.line_tolerance,
        )
        if target == self._crosshair_hover_target:
            return
        self._crosshair_hover_target = target
        self.crosshairHoverTargetChanged.emit()

    def _crosshair_hit_test(
            self,
            position: PointerPosition,
            center_tolerance: float,
            line_tolerance: float,
    ) -> CrosshairTargetKind | None:
        center = self._crosshair_image_position
        point = position.image

        if center is None or point is None:
            return None

        geometry = self._plane_geometry
        if geometry is None:
            return None

        # 在毫米空间做距离判定，避免非正方形像素扭曲命中区域。
        dx = (
            point.column - center.column
        ) * geometry.column_spacing
        dy = (
            point.row - center.row
        ) * geometry.row_spacing

        # 中心优先，因为两条线在中心相交。
        if hypot(dx, dy) <= center_tolerance:
            return CrosshairTargetKind.CENTER

        angle = radians(self.crosshairRotationDegrees)
        cosine = float(np.cos(angle))
        sine = float(np.sin(angle))
        horizontal_distance = abs(dx * sine - dy * cosine)
        vertical_distance = abs(dx * cosine + dy * sine)

        if (
                horizontal_distance <= line_tolerance
                and horizontal_distance <= vertical_distance
        ):
            return CrosshairTargetKind.HORIZONTAL_LINE

        if vertical_distance <= line_tolerance:
            return CrosshairTargetKind.VERTICAL_LINE

        return None

    def _crosshair_rotation_context(
        self,
    ) -> tuple[DragOperation, OperationStartContext] | None:
        center = self._crosshair_image_position
        geometry = self._plane_geometry
        if center is None or geometry is None:
            return None
        return (
            self._crosshair_rotate_operation,
            CrosshairRotationContext(
                center=center,
                row_spacing=geometry.row_spacing,
                column_spacing=geometry.column_spacing,
            ),
        )

    def _screen_handedness(self) -> float:
        return (
            -1.0
            if self.viewport_config.viewport_type == MprPlane.SAGITTAL
            else 1.0
        )

    def apply_mpr_state(self, state: MprState) -> None:
        """同步共享 MPR 状态；像素是否重采样由 TabController 决定。"""
        if state == self._mpr_state:
            return
        self._mpr_state = state
        if (
            self._plane_geometry is not None
            and state.view_anchors is not None
        ):
            anchor = state.view_anchors.for_plane(
                self.viewport_config.viewport_type
            )
            # anchor 可以立即更新十字线位置，无需等待
            # 后台 Reslicer 完成，因而拖动方向和指针保持同步。
            self._crosshair_image_position = ImagePoint(
                column=anchor.column,
                row=anchor.row,
            )
        self.crosshairImagePositionChanged.emit()
        self.mprSlabGuidesChanged.emit()

    def _apply_crosshair_move(self, position: ImagePoint) -> None:
        geometry = self._plane_geometry
        if geometry is None:
            return
        center_patient: Vector3 = geometry.image_point_to_patient(
            column=position.column,
            row=position.row,
        )
        self.crosshairCenterChangeRequested.emit(center_patient)

    @Property('QVariantMap', notify=Image2DViewportController.preferencesChanged)
    def crosshairStyle(self) -> dict:
        settings = self._settings_controller.section("crosshair")
        horizontal, vertical = {
            MprPlane.AXIAL: ("coronal", "sagittal"),
            MprPlane.CORONAL: ("axial", "sagittal"),
            MprPlane.SAGITTAL: ("axial", "coronal"),
        }[self.viewport_config.viewport_type]
        return {"centerGap": self._crosshair_style.centerGap,
                "lineWidth": self._crosshair_style.lineWidth,
                "horizontalWidth": settings[horizontal + "Width"],
                "verticalWidth": settings[vertical + "Width"],
                "horizontalColor": settings[horizontal + "Color"],
                "verticalColor": settings[vertical + "Color"]}

    @Property(
        QPointF,
        notify=Image2DViewportController.crosshairImagePositionChanged,
    )
    def crosshairImagePosition(self) -> QPointF:
        position = self._crosshair_image_position
        if position is None:
            return QPointF(-1.0, -1.0)
        return QPointF(position.column, position.row)

    @Property(
        bool,
        notify=Image2DViewportController.crosshairImagePositionChanged,
    )
    def hasCrosshair(self) -> bool:
        return self._crosshair_image_position is not None

    @Property(str, notify=Image2DViewportController.crosshairHoverTargetChanged)
    def crosshairHoverTarget(self) -> str:
        target = self._crosshair_hover_target
        return "" if target is None else target.value

    @Property(
        float,
        notify=Image2DViewportController.crosshairImagePositionChanged,
    )
    def crosshairRotationDegrees(self) -> float:
        state = self._mpr_state
        if state is None:
            return 0.0
        plane = self.viewport_config.viewport_type
        return degrees(
            -self._screen_handedness()
            * state.view_rolls.for_plane(plane)
        )

    @Property('QVariantList', notify=mprSlabGuidesChanged)
    def mprSlabGuides(self) -> list[dict]:
        geometry = self._plane_geometry
        state = self._mpr_state
        settings: MprProjectionSettings = (
            self._tool_controller.mpr_projection_settings
        )
        current_plane = self.viewport_config.viewport_type

        if geometry is None or state is None or not settings.enabled:
            return []

        current_normal = np.asarray(
            geometry.navigation_direction_patient,
            dtype=np.float64,
        )
        center = np.asarray(state.frame.center_patient, dtype=np.float64)
        patient_to_image = geometry.patient_to_image_index
        guides: list[dict] = []

        for slab_plane in MprPlane:
            thickness = settings.thickness_for_plane(slab_plane)
            if slab_plane == current_plane or thickness == 0:
                continue

            slab_normal = np.asarray(
                resolve_sampling_basis(
                    state,
                    slab_plane,
                ).navigation_direction_patient,
                dtype=np.float64,
            )
            line_direction = np.cross(current_normal, slab_normal)
            norm = float(np.linalg.norm(line_direction))
            if norm <= 1e-12:
                continue
            line_direction /= norm

            for side in (-1.0, 1.0):
                anchor_patient = (
                    center + side * thickness / 2.0 * slab_normal
                )
                anchor_index = patient_to_image @ np.asarray(
                    [*anchor_patient, 1.0],
                    dtype=np.float64,
                )
                direction_index = patient_to_image @ np.asarray(
                    [*(anchor_patient + line_direction), 1.0],
                    dtype=np.float64,
                )
                guides.append({
                    "plane": slab_plane.value,
                    "color": self._settings_controller.section("crosshair")[slab_plane.value + "Color"],
                    "anchorColumn": float(anchor_index[2]),
                    "anchorRow": float(anchor_index[1]),
                    "directionColumn": float(
                        direction_index[2] - anchor_index[2]
                    ),
                    "directionRow": float(
                        direction_index[1] - anchor_index[1]
                    ),
                })

        return guides

    def apply_slice_index(self, index: int) -> None:
        geometry = self._plane_geometry
        frame_meta = self._frame_meta

        if geometry is None or frame_meta is None:
            return

        rendered_index = frame_meta.slice_index
        index_delta = index - rendered_index

        direction = np.asarray(
            geometry.navigation_direction_patient,
            dtype=np.float64,
        )
        current_center = np.asarray(
            geometry.frame.center_patient,
            dtype=np.float64,
        )

        # The current plane can lie halfway between navigation samples. Using
        # only its rounded slice index accumulates that offset and may repeat
        # or skip frames. Target the actual sample grid, including at wraparound.
        offset = (geometry.navigation_origin_offset + index * geometry.navigation_spacing
                  if geometry.navigation_origin_offset is not None
                  else index_delta * geometry.navigation_spacing)
        next_center = current_center + offset * direction

        if not self._prepare_slice_index_change(index):
            return

        self.crosshairCenterChangeRequested.emit(
            tuple(float(value) for value in next_center)
        )
