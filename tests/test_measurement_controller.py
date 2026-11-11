from dataclasses import replace

import numpy as np
import pytest

from voxplane.model import (
    DragUpdateEvent,
    EditTargetKind,
    ImageGeometryMeta,
    ImagePoint,
    MeasureContext,
    MeasurementKind,
    Offset,
    PixelSpacing,
    Point,
    PointerPosition,
)
from voxplane.ui.controller.viewport.controller.measure.measure_controller import (
    MeasurementController,
)


def _context() -> MeasureContext:
    return MeasureContext(
        measurement_kind=MeasurementKind.LENGTH,
        series_uid="series-1",
        sop_instance_uid="instance-1",
        slice_index=3,
        geometry=ImageGeometryMeta(
            rows=512,
            columns=512,
            pixel_spacing=PixelSpacing(
                row=1.0,
                column=1.0,
            ),
            image_position_patient=None,
            image_orientation_patient=None,
        ),
        endpoint_tolerance=3.0,
        line_tolerance=2.0,
    )


def _position(column: float, row: float) -> PointerPosition:
    return PointerPosition(
        viewport=Point(x=column, y=row),
        image=ImagePoint(column=column, row=row),
    )


def _drag(
    start: PointerPosition,
    current: PointerPosition,
) -> DragUpdateEvent:
    return DragUpdateEvent(
        start_position=start,
        current_position=current,
        step_offset=Offset(
            x=current.viewport.x - start.viewport.x,
            y=current.viewport.y - start.viewport.y,
        ),
        total_offset=Offset(
            x=current.viewport.x - start.viewport.x,
            y=current.viewport.y - start.viewport.y,
        ),
    )


def _create_length(
    controller: MeasurementController,
) -> str:
    start = _position(0.0, 0.0)
    end = _position(10.0, 0.0)

    controller.begin(start, _context())
    controller.update(_drag(start, end))
    controller.end(end)

    items = controller.measurementItems
    assert len(items) == 1
    assert items[0]["label"] == "10.00 mm"
    return items[0]["measurementId"]


def test_create_transaction_commits_and_remains_selected() -> None:
    controller = MeasurementController()

    measurement_id = _create_length(controller)

    assert controller.activeTransaction == {}
    assert controller.selectedMeasurementId == measurement_id


def test_edit_transaction_hides_original_and_overwrites_on_commit() -> None:
    controller = MeasurementController()
    measurement_id = _create_length(controller)

    start = _position(10.0, 0.0)
    end = _position(15.0, 0.0)

    controller.begin(start, _context())

    assert controller.measurementItems == []
    assert (
        controller.activeTransaction["measurementId"]
        == measurement_id
    )

    controller.update(_drag(start, end))
    controller.end(end)

    assert controller.measurementItems[0]["label"] == "15.00 mm"
    assert controller.selectedMeasurementId == measurement_id


def test_cancel_edit_discards_draft_and_preserves_committed_data() -> None:
    controller = MeasurementController()
    measurement_id = _create_length(controller)

    start = _position(10.0, 0.0)
    end = _position(20.0, 0.0)

    controller.begin(start, _context())
    controller.update(_drag(start, end))
    controller.cancel_transaction()

    assert controller.activeTransaction == {}
    assert controller.measurementItems[0]["label"] == "10.00 mm"
    assert controller.selectedMeasurementId == measurement_id


def test_tap_empty_space_clears_selection() -> None:
    controller = MeasurementController()
    _create_length(controller)

    controller.tap_at(
        ImagePoint(column=100.0, row=100.0),
        slice_index=3,
        endpoint_tolerance=3.0,
        line_tolerance=2.0,
    )

    assert controller.selectedMeasurementId == ""


def _tap(controller, point, context):
    controller.tap_at(point, slice_index=context.slice_index,
                      endpoint_tolerance=context.endpoint_tolerance,
                      line_tolerance=context.line_tolerance, context=context)


def test_angle_three_clicks_with_hover_and_edit():
    controller = MeasurementController()
    context = replace(_context(), measurement_kind=MeasurementKind.ANGLE)
    _tap(controller, ImagePoint(20, 0), context)
    controller.preview_at(ImagePoint(0, 0))
    assert controller.measurementItems == []
    assert "顶点" in controller.instruction
    _tap(controller, ImagePoint(0, 0), context)
    controller.preview_at(ImagePoint(0, 20))
    assert controller.activeTransaction["label"] == "90.00°"
    _tap(controller, ImagePoint(0, 20), context)
    assert controller.measurementItems[0]["label"] == "90.00°"
    assert controller.activeTransaction == {}
    controller.begin(_position(0, 20), context)
    controller.end(_position(20, 20))
    assert controller.measurementItems[0]["label"] == "45.00°"


def test_angle_two_drags_commit_only_after_second_release():
    controller = MeasurementController()
    context = replace(_context(), measurement_kind=MeasurementKind.ANGLE)
    controller.begin(_position(20, 0), context)
    controller.end(_position(0, 0))
    assert controller.measurementItems == []
    assert "终点" in controller.instruction
    controller.begin(_position(0, 0), context)
    controller.end(_position(0, 20))
    assert controller.measurementItems[0]["type"] == "angle"
    assert controller.measurementItems[0]["label"] == "90.00°"


def test_angle_repeated_vertex_does_not_commit_degenerate_angle():
    controller = MeasurementController()
    context = replace(_context(), measurement_kind=MeasurementKind.ANGLE)
    for point in [ImagePoint(20, 0), ImagePoint(0, 0), ImagePoint(0, 0)]:
        _tap(controller, point, context)
    assert controller.measurementItems == []
    assert controller.has_active_transaction
    controller.cancel_transaction()
    assert controller.activeTransaction == {}


def test_angle_invalid_spacing_is_not_committed_as_zero_degrees():
    controller = MeasurementController()
    context = replace(_context(), measurement_kind=MeasurementKind.ANGLE,
                      geometry=replace(_context().geometry, pixel_spacing=PixelSpacing(0, 1)))
    for point in [ImagePoint(20, 0), ImagePoint(0, 0), ImagePoint(0, 20)]:
        _tap(controller, point, context)
    assert controller.measurementItems == []
    assert controller.activeTransaction["label"] == "—°"


@pytest.mark.parametrize("kind", [MeasurementKind.RECT, MeasurementKind.ELLIPSE])
def test_roi_create_resize_move_cancel_and_delete(kind):
    controller = MeasurementController()
    context = replace(_context(), measurement_kind=kind, modality_pixels=np.arange(1600).reshape(40, 40))
    controller.begin(_position(0, 0), context)
    controller.end(_position(10, 20))
    original = controller.measurementItems[0]
    assert original["type"] == kind.value
    assert original["metrics"]["area_mm2"] == pytest.approx(200 if kind == MeasurementKind.RECT else 50 * np.pi)
    # 右上角不是保存的对角点之一，也应支持调整。
    controller.begin(_position(10, 0), context)
    controller.end(_position(20, -5))
    resized = controller.measurementItems[0]
    assert resized["metrics"]["width_mm"] == 20
    assert resized["metrics"]["height_mm"] == 25
    # 下边中点同时处于矩形和椭圆轮廓上；多次更新按拖动起点计算。
    controller.begin(_position(10, 20), context)
    controller.update(_drag(_position(10, 20), _position(12, 22)))
    controller.update(_drag(_position(10, 20), _position(15, 25)))
    controller.end(_position(15, 25))
    moved = controller.measurementItems[0]
    assert moved["metrics"]["width_mm"] == 20
    assert moved["metrics"]["height_mm"] == 25
    assert min(p["column"] for p in moved["points"]) == 5
    controller.begin(_position(15, 25), context)
    controller.update(_drag(_position(15, 25), _position(20, 30)))
    controller.cancel_transaction()
    assert controller.measurementItems[0] == moved
    controller.delete_selected()
    assert controller.measurementItems == []


def test_end_uses_release_position_and_line_body_translation_does_not_accumulate():
    controller = MeasurementController()
    context = _context()
    controller.begin(_position(0, 0), context)
    controller.update(_drag(_position(0, 0), _position(10, 0)))
    controller.end(_position(20, 0))
    assert controller.measurementItems[0]["label"] == "20.00 mm"
    controller.begin(_position(10, 0), context)
    controller.update(_drag(_position(10, 0), _position(11, 2)))
    controller.update(_drag(_position(10, 0), _position(12, 3)))
    controller.end(_position(12, 3))
    item = controller.measurementItems[0]
    assert (item["startColumn"], item["startRow"], item["endColumn"], item["endRow"]) == (2, 3, 22, 3)


def test_ellipse_hit_test_ignores_diagonal_and_bounding_rectangle_edges():
    controller = MeasurementController()
    context = replace(_context(), measurement_kind=MeasurementKind.ELLIPSE)
    controller.begin(_position(0, 0), context)
    controller.end(_position(100, 100))
    # 中心属于 INTERIOR，不是连接两个对角点形成的 OUTLINE；无需预先选中。
    controller.clear_selection()
    assert controller.hit_test(ImagePoint(50, 50), slice_index=3,
                               endpoint_tolerance=1, line_tolerance=1).target.kind == EditTargetKind.INTERIOR
    assert controller.hit_test(ImagePoint(10, 0), slice_index=3,
                               endpoint_tolerance=1, line_tolerance=1) is None
    assert controller.hit_test(ImagePoint(50, 0), slice_index=3,
                               endpoint_tolerance=1, line_tolerance=1) is not None


def test_selection_click_is_draft_style_without_an_edit_transaction():
    controller = MeasurementController()
    uid = _create_length(controller)
    original = controller.measurementItems
    assert controller.selectedMeasurementState == "completed"
    for _ in range(2):
        _tap(controller, ImagePoint(5, 0), _context())
        assert controller.selectedMeasurementId == uid
        assert controller.selectedMeasurementState == "draft"
        assert not controller.has_active_transaction
        assert controller.measurementItems == original
        controller.clear_selection()
        assert controller.selectedMeasurementState == "none"
    _tap(controller, ImagePoint(5, 0), _context())
    controller.begin(_position(10, 0), _context())
    controller.update(_drag(_position(10, 0), _position(20, 0)))
    controller.cancel_transaction()
    assert controller.selectedMeasurementState == "draft"
    assert controller.measurementItems == original
    controller.begin(_position(10, 0), _context())
    controller.end(_position(20, 0))
    assert controller.selectedMeasurementState == "completed"
    assert controller.measurementItems[0]["label"] == "20.00 mm"
    controller.set_current_slice(4)
    assert controller.selectedMeasurementState == "none"
