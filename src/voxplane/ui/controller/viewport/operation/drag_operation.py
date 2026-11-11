from typing import Protocol

from voxplane.model import DragUpdateEvent, PointerPosition
from voxplane.model.interaction import (
    InteractionResult,
    OperationStartContext,
)


class DragOperation(Protocol):
    def begin(
        self,
        position: PointerPosition,
        context: OperationStartContext | None,
    ) -> InteractionResult | None:
        ...

    def update(
        self,
        drag_event: DragUpdateEvent,
    ) -> InteractionResult | None:
        ...

    def end(
        self,
        position: PointerPosition,
    ) -> InteractionResult | None:
        ...
