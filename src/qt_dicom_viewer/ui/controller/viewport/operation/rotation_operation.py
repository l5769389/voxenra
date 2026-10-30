"""Rotate the displayed image using screen coordinates, without changing its plane."""
from math import atan2, degrees, hypot, isfinite

from qt_dicom_viewer.model import DragUpdateEvent, Point, PointerPosition
from qt_dicom_viewer.model.interaction import (
    OperationStartContext, RotationChange, RotationContext,
)


class RotationOperation:
    def __init__(self) -> None:
        self._center: Point | None = None
        self._previous_angle: float | None = None
        self._previous_position: Point | None = None
        self._degrees = 0.0

    def begin(self, position: PointerPosition, context: OperationStartContext | None) -> None:
        if not isinstance(context, RotationContext):
            raise TypeError("RotationOperation requires RotationContext")
        self._center = context.center
        self._degrees = context.current_degrees
        self._previous_angle = self._angle(position.viewport)
        self._previous_position = position.viewport

    def _angle(self, point: Point) -> float | None:
        if self._center is None:
            return None
        dx, dy = point.x - self._center.x, point.y - self._center.y
        # The center has no stable polar angle. Rebase after leaving this area
        # instead of suddenly flipping the image when crossing the pivot.
        if not isfinite(dx) or not isfinite(dy) or hypot(dx, dy) < 8.0:
            return None
        return degrees(atan2(dy, dx))

    def update(self, event: DragUpdateEvent) -> RotationChange | None:
        point = event.current_position.viewport
        current = self._angle(point)
        previous = self._previous_angle
        previous_point = self._previous_position
        self._previous_angle = current
        self._previous_position = point
        if current is None or previous is None:
            return None
        # Fast motion may cross the pivot without delivering an event inside
        # the dead zone. Check the segment too, then rebase on the far side.
        if previous_point is not None and self._center is not None:
            dx, dy = point.x - previous_point.x, point.y - previous_point.y
            length_squared = dx * dx + dy * dy
            if length_squared > 0:
                px = previous_point.x - self._center.x
                py = previous_point.y - self._center.y
                t = max(0.0, min(1.0, -(px * dx + py * dy) / length_squared))
                if hypot(px + t * dx, py + t * dy) < 8.0:
                    return None
        delta = (current - previous + 180.0) % 360.0 - 180.0
        self._degrees = (self._degrees + delta) % 360.0
        return RotationChange(self._degrees)

    def end(self, position: PointerPosition) -> None:
        self.cancel()

    def cancel(self) -> None:
        self._center = None
        self._previous_angle = None
        self._previous_position = None
