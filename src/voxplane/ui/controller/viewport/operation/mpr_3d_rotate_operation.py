from math import atan2, isfinite, pi

from voxplane.model import (
    DragUpdateEvent,
    Mpr3DRotationChange,
    Mpr3DRotationContext,
    PointerPosition,
)
from voxplane.model.interaction import OperationStartContext
from voxplane.ui.controller.viewport.operation.drag_operation import (
    DragOperation,
)


class Mpr3DRotateOperation(DragOperation):
    """把绕当前视图中心的拖动转换为绕切面法向的三维旋转。"""

    def __init__(self) -> None:
        self._context: Mpr3DRotationContext | None = None
        self._last_angle: float | None = None

    def begin(
        self,
        position: PointerPosition,
        context: OperationStartContext | None,
    ) -> None:
        if not isinstance(context, Mpr3DRotationContext):
            raise TypeError(
                "Mpr3DRotateOperation requires Mpr3DRotationContext"
            )
        if min(context.row_spacing, context.column_spacing) <= 0:
            raise ValueError("Pixel spacing must be positive")
        self._context = context
        self._last_angle = self._pointer_angle(position)

    def update(
        self,
        drag_event: DragUpdateEvent,
    ) -> Mpr3DRotationChange | None:
        context = self._context
        if context is None:
            return None

        current_angle = self._pointer_angle(
            drag_event.current_position
        )
        if current_angle is None or self._last_angle is None:
            self._last_angle = current_angle
            return None

        angle = current_angle - self._last_angle
        angle = (angle + pi) % (2.0 * pi) - pi
        self._last_angle = current_angle
        if not isfinite(angle) or abs(angle) <= 1e-12:
            return None
        return Mpr3DRotationChange(
            axis_patient=context.normal_direction_patient,
            angle_delta_radians=angle,
        )

    def end(self, position: PointerPosition) -> None:
        self._context = None
        self._last_angle = None

    def _pointer_angle(
        self,
        position: PointerPosition,
    ) -> float | None:
        context = self._context
        point = position.image
        if context is None or point is None:
            return None

        # 在物理毫米空间中计算绕中心的角度，避免非正方形像素
        # 将用户画出的圆形拖动扭曲为错误角度。
        x = (
            point.column - context.center.column
        ) * context.column_spacing
        y = (
            point.row - context.center.row
        ) * context.row_spacing
        if x * x + y * y <= 1e-12:
            return None
        return atan2(y, x)
