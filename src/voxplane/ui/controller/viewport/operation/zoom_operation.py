import math
from dataclasses import dataclass

from voxplane.model import Point, DragUpdateEvent, PointerPosition
from voxplane.model.interaction import (
    InteractionResult,
    OperationStartContext,
    ZoomChange,
    ZoomContext,
)
from voxplane.ui.controller.viewport.operation.drag_operation import (
    DragOperation,
)


@dataclass(frozen=True, slots=True)
class ZoomInteractionConfig:
    minimum_zoom: float = 0.1
    maximum_zoom: float = 20.0
    doublings_per_viewport: float = 2.0
    sensitivity: float = 1.0


DEFAULT_ZOOM_CONFIG = ZoomInteractionConfig()


class ZoomOperation(DragOperation):
    def __init__(
        self,
        config: ZoomInteractionConfig = DEFAULT_ZOOM_CONFIG,
    ) -> None:
        self._config = config
        self._start_zoom: float | None = None
        self._viewport_height = 1.0

    def begin(
        self,
        position: PointerPosition,
        context: OperationStartContext | None,
    ) -> None:
        if not isinstance(context, ZoomContext):
            raise TypeError(
                "ZoomOperation requires ZoomContext"
            )

        self._start_zoom = max(
            context.current_zoom,
            self._config.minimum_zoom,
        )

        _, viewport_height = context.viewport_size

        self._viewport_height = max(
            float(viewport_height),
            1.0,
        )

    def update(
        self,
        drag_event: DragUpdateEvent,
    ) -> InteractionResult | None:
        start_zoom = self._start_zoom

        if start_zoom is None:
            return None

        config = self._config

        # 转换为相对于 viewport 高度的拖动比例
        normalized_drag = (
            -drag_event.total_offset.y
            / self._viewport_height
        )

        exponent = (
            normalized_drag
            * config.doublings_per_viewport
            * config.sensitivity
        )

        # 提前限制指数，避免极端拖动产生过大浮点数
        minimum_exponent = math.log2(
            config.minimum_zoom / start_zoom
        )
        maximum_exponent = math.log2(
            config.maximum_zoom / start_zoom
        )

        exponent = max(
            minimum_exponent,
            min(exponent, maximum_exponent),
        )

        zoom = start_zoom * (2.0 ** exponent)

        return ZoomChange(
            zoom=round(zoom, 4)
        )

    def end(self, position: Point) -> None:
        self._reset()

    def cancel(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._start_zoom = None
        self._viewport_height = 1.0