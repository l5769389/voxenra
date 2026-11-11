import math

from voxplane.model import Point, DragUpdateEvent, PointerPosition
from voxplane.model.interaction import InteractionResult, OperationStartContext, PanContext, PanChange
from voxplane.ui.controller.viewport.operation.drag_operation import DragOperation


class PanOperation(DragOperation):
    def __init__(
            self,
    ) -> None:
        super().__init__()
        self.init_pan_y = None
        self.init_pan_x = None

    def begin(self, position: PointerPosition, context: OperationStartContext | None) -> None:
        if not isinstance(context, PanContext):
            raise TypeError("PanOperation required PanContext")
        self.init_pan_x = context.current_pan_x
        self.init_pan_y = context.current_pan_y
        return None

    def update(self, drag_event: DragUpdateEvent) -> InteractionResult | None:
        return PanChange(
            offset_x=self.init_pan_x + drag_event.total_offset.x,
            offset_y=self.init_pan_y +  drag_event.total_offset.y,
        )

    def end(self, position: Point) -> None:
        pass


