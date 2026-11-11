from voxplane.model import DragUpdateEvent, PointerPosition, ImagePoint
from voxplane.model.interaction import (
    CrosshairCenterChange,
    CrosshairMoveContext,
    OperationStartContext,
)
from voxplane.ui.controller.viewport.operation.drag_operation import DragOperation


class CrosshairMoveOperation(DragOperation):
    def __init__(
            self,
    ) -> None:
        super().__init__()

    def begin(self, position: PointerPosition, context: OperationStartContext | None) -> None:
        if not isinstance(context, CrosshairMoveContext):
            raise TypeError("CrosshairMoveOperation required CrosshairMoveContext")
        return None

    def update(self, drag_event: DragUpdateEvent) -> CrosshairCenterChange | None:
        image_position = drag_event.current_position.image
        if image_position is None:
            return None
        return CrosshairCenterChange(
            position=ImagePoint(
                column=image_position.column,
                row=image_position.row,
            )
        )

    def end(self, position: PointerPosition) -> None:
        return None

