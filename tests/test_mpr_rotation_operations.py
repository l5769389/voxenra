from math import pi

import numpy as np
import pytest

from voxplane.model import (
    CrosshairRotationContext,
    DragUpdateEvent,
    ImagePoint,
    Mpr3DRotationContext,
    Offset,
    Point,
    PointerPosition,
)
from voxplane.ui.controller.viewport.operation.crosshair_rotate_operation import (
    CrosshairRotateOperation,
)
from voxplane.ui.controller.viewport.operation.mpr_3d_rotate_operation import (
    Mpr3DRotateOperation,
)


def _position(column: float, row: float) -> PointerPosition:
    return PointerPosition(
        viewport=Point(column, row),
        image=ImagePoint(column, row),
    )


def test_crosshair_drag_produces_incremental_screen_angle() -> None:
    operation = CrosshairRotateOperation()
    start = _position(1.0, 0.0)
    current = _position(0.0, 1.0)
    operation.begin(
        start,
        CrosshairRotationContext(
            center=ImagePoint(0.0, 0.0),
            row_spacing=1.0,
            column_spacing=1.0,
        ),
    )

    result = operation.update(
        DragUpdateEvent(
            start_position=start,
            current_position=current,
            step_offset=Offset(-1.0, 1.0),
            total_offset=Offset(-1.0, 1.0),
        )
    )

    assert result is not None
    assert result.angle_delta_radians == pytest.approx(pi / 2.0)


def test_3d_drag_rotates_around_the_displayed_plane_normal() -> None:
    operation = Mpr3DRotateOperation()
    start = _position(1.0, 0.0)
    operation.begin(
        start,
        Mpr3DRotationContext(
            center=ImagePoint(0.0, 0.0),
            row_spacing=1.0,
            column_spacing=1.0,
            normal_direction_patient=(0.0, 0.0, 1.0),
        ),
    )
    result = operation.update(
        DragUpdateEvent(
            start_position=start,
            current_position=_position(0.0, 1.0),
            step_offset=Offset(-1.0, 1.0),
            total_offset=Offset(-1.0, 1.0),
        )
    )

    assert result is not None
    np.testing.assert_allclose(result.axis_patient, (0.0, 0.0, 1.0))
    assert result.angle_delta_radians == pytest.approx(pi / 2.0)
