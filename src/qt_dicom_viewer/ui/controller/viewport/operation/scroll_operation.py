import math
from dataclasses import dataclass

from qt_dicom_viewer.model import Point, DragUpdateEvent
from qt_dicom_viewer.model.interaction import SliceIndexChange, ScrollContext, OperationStartContext
from qt_dicom_viewer.ui.controller.viewport.operation.drag_operation import DragOperation


@dataclass(frozen=True, slots=True)
class ScrollInteractionConfig:
    swap_direction: bool = False
    wheel_threshold: float = 120
    touch_threshold: float = 60
    pixel_wheel_threshold: float = 60


DEFAULT_SCROLL_CONFIG = ScrollInteractionConfig()


class ScrollOperation(DragOperation):

    def __init__(self, config: ScrollInteractionConfig = DEFAULT_SCROLL_CONFIG) -> None:
        super().__init__()
        self._config = config
        self._accumulator = 0.0
        self._wheel_unit = None
        self._start_slice = 0
        self._slice_count  = 0

    def handle_wheel(
            self,
            *,
            angle_delta_y: float,
            pixel_delta_y: float = 0,
            current_index: int,
            slice_count: int,
    ) -> SliceIndexChange | None:
        if slice_count <= 0:
            return None

        # Retain conventional wheel behavior when both values are supplied.
        # Pixel-only touchpad events have their own units and accumulation.
        if angle_delta_y != 0:
            delta, threshold, unit = angle_delta_y, self._config.wheel_threshold, "angle"
        else:
            delta, threshold, unit = pixel_delta_y, self._config.pixel_wheel_threshold, "pixel"
        if not math.isfinite(delta) or delta == 0:
            return None
        if unit != self._wheel_unit:
            self._accumulator = 0.0
            self._wheel_unit = unit

        # 滚动方向改变时清理之前的残余量。
        if (
                self._accumulator != 0
                and self._accumulator
                * delta < 0
        ):
            self._accumulator = 0.0

        self._accumulator += delta

        steps = math.trunc(
            self._accumulator / threshold
        )

        if steps == 0:
            return None

        self._accumulator -= (
                steps * threshold
        )
        if self._config.swap_direction:
            next_index = current_index + steps
        else:
            next_index = current_index - steps

        next_index = max(
            0,
            min(next_index, slice_count - 1),
        )

        if next_index == current_index:
            return None

        return SliceIndexChange(slice_index=next_index)

    def begin(self, position: Point, context: OperationStartContext) -> None:
        if not isinstance(context, ScrollContext):
            raise TypeError(
                "WindowLevelOperation requires WindowLevelContext"
            )
        self._start_slice = context.slice_index
        self._slice_count = context.slice_count
        self.reset()

    def update(self, drag_event: DragUpdateEvent) -> SliceIndexChange:
        delta = math.trunc(drag_event.total_offset.y / self._config.touch_threshold)
        direction = -1 if self._config.swap_direction else 1
        next_index = self._start_slice + direction * delta
        slice_count = self._slice_count
        next_index = max(
            0,
            min(next_index, slice_count - 1),
        )
        return SliceIndexChange(slice_index=next_index)

    def end(self, position: Point) -> None:
        pass

    def reset(self) -> None:
        self._accumulator = 0.0
        self._wheel_unit = None
