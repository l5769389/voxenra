from dataclasses import dataclass
from typing import TYPE_CHECKING

from voxplane.model import Point, WindowLevel, DragUpdateEvent, PointerPosition
from voxplane.model.interaction import WindowLevelChange, WindowLevelContext, OperationStartContext
from voxplane.ui.controller.viewport.operation.drag_operation import DragOperation

if TYPE_CHECKING:
    from voxplane.ui.controller.viewport.viewport_controller import (
        ViewportController,
    )


@dataclass(frozen=True, slots=True)
class WindowLevelInteractionConfig:
    swap_axes: bool = False    # 水平调窗宽，垂直调窗位
    width_direction: float = 1.0   # 向右增大窗宽
    center_direction: float = -1.0   # 屏幕 Y 向下，所以向上提高窗位
    width_sensitivity: float = 1.0
    center_sensitivity: float = 1.0
    minimum_width: float = 1
    minimum_width_control_range: float = 100.0
    max_width_control_range: float = 1000.0
    minimum_center_control_range: float = 100.0
    max_center_control_range: float = 1000.0
    allow_inversion: bool = True
    fixed_lower_bound: float | None = None
    precision: int = 2


DEFAULT_WINDOW_LEVEL_CONFIG = WindowLevelInteractionConfig()
MR_WINDOW_LEVEL_CONFIG = WindowLevelInteractionConfig(
    minimum_width=0.001, minimum_width_control_range=0.001,
    max_width_control_range=float("inf"), minimum_center_control_range=0.001,
    max_center_control_range=float("inf"), precision=3,
)


class WindowLevelOperation(DragOperation):
    def __init__(
        self,
        config: WindowLevelInteractionConfig = DEFAULT_WINDOW_LEVEL_CONFIG,
    ) -> None:
        super().__init__()

        self._config = config
        self._start_window: WindowLevel | None = None
        self._viewport_width = 1.0
        self._viewport_height = 1.0
        self._start_inverted = False

    def begin(self, position: PointerPosition,
                    context:OperationStartContext | None) -> None:
        if not isinstance(context, WindowLevelContext):
            raise TypeError(
                "WindowLevelOperation requires WindowLevelContext"
            )

        self._start_window = context.current_window
        self._start_inverted = context.inverted

        width, height = context.viewport_size
        self._viewport_width = max(width, 1.0)
        self._viewport_height = max(height, 1.0)

    def update(
            self,
            drag_event: DragUpdateEvent,
    ) -> WindowLevelChange | None:
        if self._start_window is None:
            return None

        config = self._config
        start = self._start_window

        if config.swap_axes:
            width_delta = drag_event.total_offset.y
            center_delta = drag_event.total_offset.x
            width_axis_size = self._viewport_height
            center_axis_size = self._viewport_width
        else:
            width_delta = drag_event.total_offset.x
            center_delta = drag_event.total_offset.y
            width_axis_size = self._viewport_width
            center_axis_size = self._viewport_height

        width_control_range = min(
            max(start.width, config.minimum_width_control_range),
            config.max_width_control_range,
        )

        center_control_range = min(
            max(start.width, config.minimum_center_control_range),
            config.max_center_control_range,
        )

        if config.fixed_lower_bound is not None:
            lower = config.fixed_lower_bound
            start_upper = start.center + start.width / 2.0
            horizontal_change = (
                width_delta / width_axis_size * width_control_range
            )
            vertical_change = (
                -center_delta / center_axis_size * center_control_range
            )
            upper = round(
                max(
                    lower + config.minimum_width,
                    start_upper + horizontal_change + vertical_change,
                ),
                3,
            )
            return WindowLevelChange(
                window=WindowLevel(
                    center=(lower + upper) / 2.0,
                    width=upper - lower,
                ),
                inverted=False,
            )

        # 100 / 视口的宽度 * 灵敏度
        width_step = (
                width_control_range
                / width_axis_size
                * config.width_sensitivity
                * config.width_direction
        )

        center_step = (
                center_control_range
                / center_axis_size
                * config.center_sensitivity
                * config.center_direction
        )

        if config.allow_inversion:
            # 把拖动开始时的 width 恢复为有符号值。
            start_signed_width = (
                -start.width
                if self._start_inverted
                else start.width
            )
            signed_width = start_signed_width + width_delta * width_step
            inverted = signed_width < 0
            resolved_width = abs(signed_width)
        else:
            resolved_width = start.width + width_delta * width_step
            inverted = self._start_inverted

        window = WindowLevel(
            width=round(
                max(
                    config.minimum_width,
                    resolved_width,
                ),
                config.precision,
            ),
            center=round(
                start.center
                + center_delta * center_step,
                config.precision,
            ),
        )

        result = WindowLevelChange(
            window=window,
            inverted=inverted,
        )
        return result


    def end(self, position: Point) -> None:
        self._start_window = None

    def cancel(self) -> None:
        self._start_window = None
