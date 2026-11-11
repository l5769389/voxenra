from voxplane.model import (
    DragUpdateEvent,
    Offset,
    Point,
    PointerPosition,
    WindowLevel,
)
from voxplane.model.interaction import WindowLevelContext
from voxplane.ui.controller.viewport.operation.window_level_operation import (
    WindowLevelInteractionConfig,
    WindowLevelOperation,
)


def _pointer(x: float, y: float) -> PointerPosition:
    return PointerPosition(
        viewport=Point(x=x, y=y),
        image=None,
    )


def test_default_window_level_drag_direction_matches_viewer_convention() -> None:
    """向右增大窗宽，向下减小窗位（即向上增大窗位）。"""
    operation = WindowLevelOperation()
    start = _pointer(50.0, 50.0)
    operation.begin(
        start,
        WindowLevelContext(
            viewport_size=(100.0, 100.0),
            inverted=False,
            current_window=WindowLevel(center=40.0, width=400.0),
        ),
    )

    result = operation.update(
        DragUpdateEvent(
            start_position=start,
            current_position=_pointer(60.0, 60.0),
            step_offset=Offset(x=10.0, y=10.0),
            total_offset=Offset(x=10.0, y=10.0),
        )
    )

    assert result is not None
    assert result.window.width > 400.0
    assert result.window.center < 40.0


def test_montage_window_mode_clamps_width_without_inverting() -> None:
    operation = WindowLevelOperation(
        WindowLevelInteractionConfig(allow_inversion=False)
    )
    start = _pointer(50.0, 50.0)
    operation.begin(
        start,
        WindowLevelContext(
            viewport_size=(100.0, 100.0),
            inverted=False,
            current_window=WindowLevel(center=40.0, width=100.0),
        ),
    )

    result = operation.update(
        DragUpdateEvent(
            start_position=start,
            current_position=_pointer(-500.0, 50.0),
            step_offset=Offset(x=-550.0, y=0.0),
            total_offset=Offset(x=-550.0, y=0.0),
        )
    )

    assert result is not None
    assert result.window.width == 1.0
    assert result.inverted is False


def test_pet_intensity_drag_keeps_zero_lower_bound() -> None:
    operation = WindowLevelOperation(
        WindowLevelInteractionConfig(
            minimum_width=0.01,
            minimum_width_control_range=1,
            max_width_control_range=100,
            minimum_center_control_range=1,
            max_center_control_range=100,
            fixed_lower_bound=0,
        )
    )
    start = _pointer(50, 50)
    operation.begin(
        start,
        WindowLevelContext(
            viewport_size=(100, 100),
            inverted=False,
            current_window=WindowLevel(center=2.5, width=5),
        ),
    )

    result = operation.update(
        DragUpdateEvent(
            start_position=start,
            current_position=_pointer(60, 40),
            step_offset=Offset(x=10, y=-10),
            total_offset=Offset(x=10, y=-10),
        )
    )

    assert result is not None
    assert result.inverted is False
    assert result.window.center - result.window.width / 2 == 0
    assert result.window.center + result.window.width / 2 > 5
