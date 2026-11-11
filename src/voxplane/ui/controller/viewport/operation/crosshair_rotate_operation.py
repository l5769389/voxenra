from math import atan2, isfinite, pi

from voxplane.model import (
    CrosshairRotationChange,
    CrosshairRotationContext,
    DragUpdateEvent,
    PointerPosition,
)
from voxplane.model.interaction import OperationStartContext
from voxplane.ui.controller.viewport.operation.drag_operation import (
    DragOperation,
)


class CrosshairRotateOperation(DragOperation):
    """把绕十字线中心的指针运动转换为连续角度增量。"""

    def __init__(self) -> None:
        self._context: CrosshairRotationContext | None = None
        self._last_angle: float | None = None

    def begin(
        self,
        position: PointerPosition,
        context: OperationStartContext | None,
    ) -> None:
        if not isinstance(context, CrosshairRotationContext):
            raise TypeError(
                "CrosshairRotateOperation requires "
                "CrosshairRotationContext"
            )
        self._context = context
        self._last_angle = self._pointer_angle(position)

    def update(
        self,
        drag_event: DragUpdateEvent,
    ) -> CrosshairRotationChange | None:
        current_angle = self._pointer_angle(
            drag_event.current_position
        )
        if current_angle is None or self._last_angle is None:
            self._last_angle = current_angle
            return None

        delta = current_angle - self._last_angle
        delta = (delta + pi) % (2.0 * pi) - pi
        self._last_angle = current_angle
        if not isfinite(delta) or abs(delta) <= 1e-12:
            return None
        return CrosshairRotationChange(delta)

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

        # 使用毫米而不是像素计算角度，避免非正方形像素造成角度畸变。
        x = (
            point.column - context.center.column
        ) * context.column_spacing
        y = (
            point.row - context.center.row
        ) * context.row_spacing
        if x * x + y * y <= 1e-12:
            return None
        return atan2(y, x)
