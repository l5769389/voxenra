"""验证命中部位、部位编号和优先级，不把“整体移动”误当成一种命中部位。"""

from dataclasses import replace

import pytest

from voxplane.core.measurement_hit_test import (
    hit_test_control_points,
    hit_test_interior,
    hit_test_label,
    hit_test_outline,
)
from voxplane.model import (
    AngleMeasurement,
    EditTargetKind,
    ImagePoint,
    LengthMeasurement,
    MeasurementEditTarget,
    MeasurementHit,
    MeasurementKind,
    MeasurementLabelRegion,
    Point,
    RoiMeasurement,
    RoiMetrics,
)
from voxplane.ui.controller.viewport.controller.measure.measure_controller import MeasurementController


def _line():
    return LengthMeasurement("line", "series", "instance", 0,
                             (ImagePoint(0, 0), ImagePoint(100, 0)), 100)


def _angle():
    return AngleMeasurement("angle", "series", "instance", 0,
                            (ImagePoint(0, 100), ImagePoint(0, 0), ImagePoint(100, 0)), 90)


def _roi(kind):
    return RoiMeasurement(kind.value, "series", "instance", 0, kind,
                          (ImagePoint(0, 0), ImagePoint(100, 100)), RoiMetrics(area_mm2=10000))


def _controller(*measurements, selected=None):
    controller = MeasurementController()
    controller._measurements = {measurement.measurement_id: measurement for measurement in measurements}
    if selected is not None:
        controller.select(MeasurementHit(selected, MeasurementEditTarget(EditTargetKind.OUTLINE), 0))
    return controller


def _query(controller, point, viewport_point=None):
    return controller.hit_test(point, slice_index=0, endpoint_tolerance=1,
                               line_tolerance=1, viewport_point=viewport_point)


def _label_regions(*ids):
    return [dict(measurementId=measurement_id, x=400, y=300, width=200, height=100)
            for measurement_id in ids]


@pytest.mark.parametrize("measurement, point, index", [
    (_line(), ImagePoint(0, 0), 0),
    (_line(), ImagePoint(100, 0), 1),
    (_angle(), ImagePoint(0, 0), 1),
    (_angle(), ImagePoint(100, 0), 2),
    (_roi(MeasurementKind.RECT), ImagePoint(100, 0), 1),
    (_roi(MeasurementKind.ELLIPSE), ImagePoint(0, 100), 3),
])
def test_control_point_identifies_exact_handle(measurement, point, index):
    hit = hit_test_control_points(measurement, point, 1)
    assert hit.measurement_id == measurement.measurement_id
    assert hit.target == MeasurementEditTarget(EditTargetKind.CONTROL_POINT, index)
    assert hit.distance == 0


@pytest.mark.parametrize("measurement, point, index", [
    (_line(), ImagePoint(50, .5), 0),
    (_angle(), ImagePoint(0, 50), 0),
    (_angle(), ImagePoint(50, 0), 1),
    (_roi(MeasurementKind.RECT), ImagePoint(50, 0), 0),
    (_roi(MeasurementKind.RECT), ImagePoint(100, 50), 1),
    (_roi(MeasurementKind.RECT), ImagePoint(50, 100), 2),
    (_roi(MeasurementKind.RECT), ImagePoint(0, 50), 3),
    (_roi(MeasurementKind.ELLIPSE), ImagePoint(100, 50), None),
    (_roi(MeasurementKind.ELLIPSE), ImagePoint(50, 0), None),
])
def test_outline_identifies_real_edge_but_not_ellipse_sampling_index(measurement, point, index):
    hit = hit_test_outline(measurement, point, 1)
    assert hit.target == MeasurementEditTarget(EditTargetKind.OUTLINE, index)
    assert hit.measurement_id == measurement.measurement_id
    assert hit.distance <= 1


def test_line_is_a_finite_segment_and_angle_is_not_a_closed_triangle():
    assert hit_test_outline(_line(), ImagePoint(120, 0), 1) is None
    assert hit_test_outline(_angle(), ImagePoint(50, 50), 1) is None
    assert hit_test_interior(_line(), ImagePoint(50, 0)) is None
    assert hit_test_interior(_angle(), ImagePoint(10, 10)) is None


@pytest.mark.parametrize("kind", [MeasurementKind.RECT, MeasurementKind.ELLIPSE])
def test_interior_is_separate_from_outline_and_reversed_corners(kind):
    measurement = _roi(kind)
    for shape in (measurement, replace(measurement, points=measurement.points[::-1])):
        assert hit_test_outline(shape, ImagePoint(50, 50), 1) is None
        hit = hit_test_interior(shape, ImagePoint(50, 50))
        assert hit.target == MeasurementEditTarget(EditTargetKind.INTERIOR)
        assert hit_test_interior(shape, ImagePoint(0, 50)) is None
        assert hit_test_interior(shape, ImagePoint(-5, 50)) is None


def test_ellipse_interior_is_not_its_bounding_box_and_degenerate_roi_is_safe():
    assert hit_test_interior(_roi(MeasurementKind.ELLIPSE), ImagePoint(10, 10)) is None
    assert hit_test_interior(_roi(MeasurementKind.RECT), ImagePoint(10, 10)) is not None
    collapsed = replace(_roi(MeasurementKind.ELLIPSE), points=(ImagePoint(0, 0), ImagePoint(0, 100)))
    assert hit_test_interior(collapsed, ImagePoint(0, 50)) is None


def test_label_has_no_edge_index_and_uses_actual_viewport_rectangle():
    region = MeasurementLabelRegion("line", 400, 300, 200, 100)
    hit = hit_test_label(region, Point(450, 350))
    assert hit.target == MeasurementEditTarget(EditTargetKind.LABEL)
    assert hit.measurement_id == "line"
    assert hit_test_label(region, Point(399, 350)) is None
    assert hit_test_label(replace(region, width=0), Point(400, 350)) is None
    assert hit_test_label(replace(region, x=float("nan")), Point(400, 350)) is None


def test_priority_is_control_point_then_label_then_outline():
    controller = _controller(_line())
    controller.setLabelHitRegions(_label_regions("line"))
    # 图像坐标与视口坐标刻意不同，防止两种坐标空间混用。
    viewport_point = Point(450, 350)
    assert _query(controller, ImagePoint(0, 0), viewport_point).target.kind == EditTargetKind.CONTROL_POINT
    assert _query(controller, ImagePoint(50, 0), viewport_point).target.kind == EditTargetKind.LABEL
    assert _query(controller, ImagePoint(50, 0), Point(650, 350)).target.kind == EditTargetKind.OUTLINE
    assert _query(controller, ImagePoint(50, 20), viewport_point).target.kind == EditTargetKind.LABEL
    assert _query(controller, ImagePoint(50, 20)) is None


@pytest.mark.parametrize("kind", [MeasurementKind.RECT, MeasurementKind.ELLIPSE])
def test_unselected_roi_also_has_interior_hit_and_other_outlines_take_precedence(kind):
    roi = _roi(kind)
    controller = _controller(roi)
    assert _query(controller, ImagePoint(50, 50)).target.kind == EditTargetKind.INTERIOR
    controller.select(MeasurementHit(roi.measurement_id, MeasurementEditTarget(EditTargetKind.OUTLINE), 0))
    assert _query(controller, ImagePoint(50, 50)).target.kind == EditTargetKind.INTERIOR
    line = replace(_line(), points=(ImagePoint(30, 50), ImagePoint(70, 50)))
    controller._measurements[line.measurement_id] = line
    hit = _query(controller, ImagePoint(50, 50))
    assert hit.target.kind == EditTargetKind.OUTLINE
    assert hit.measurement_id == "line"


def test_ties_follow_selected_then_newest_but_nearest_outline_wins():
    first, second = _line(), replace(_line(), measurement_id="second")
    controller = _controller(first, second)
    assert _query(controller, ImagePoint(50, 0)).measurement_id == "second"
    controller.select(MeasurementHit("line", MeasurementEditTarget(EditTargetKind.OUTLINE), 0))
    assert _query(controller, ImagePoint(50, 0)).measurement_id == "line"
    controller._measurements["second"] = replace(second, points=(ImagePoint(0, .5), ImagePoint(100, .5)))
    assert _query(controller, ImagePoint(50, .5)).measurement_id == "second"
    controller.setLabelHitRegions(_label_regions("second", "line"))
    assert _query(controller, ImagePoint(50, 20), Point(450, 350)).measurement_id == "line"


def test_hidden_slice_plane_deleted_and_stale_labels_do_not_hit():
    controller = _controller(replace(_line(), slice_index=1))
    controller.setLabelHitRegions(_label_regions("line", "missing"))
    assert _query(controller, ImagePoint(50, 20), Point(450, 350)) is None
    controller._measurements["line"] = _line()
    controller._measurement_frames["line"] = ("different-plane",)
    assert _query(controller, ImagePoint(50, 20), Point(450, 350)) is None
    controller._measurement_frames.clear()
    assert _query(controller, ImagePoint(50, 20), Point(450, 350)).target.kind == EditTargetKind.LABEL
    controller.setLabelHitRegions([])
    assert _query(controller, ImagePoint(50, 20), Point(450, 350)) is None
    controller.setLabelHitRegions(_label_regions("line"))
    controller.clear_all()
    assert _query(controller, ImagePoint(50, 20), Point(450, 350)) is None


@pytest.mark.parametrize("kind", [MeasurementKind.RECT, MeasurementKind.ELLIPSE])
def test_click_in_unselected_roi_selects_and_hover_cursor_tracks_selection(kind):
    roi = _roi(kind)
    controller = _controller(roi)
    controller.update_hover(ImagePoint(50, 50), slice_index=0, endpoint_tolerance=1, line_tolerance=1)
    assert controller.hoverHit == {"measurementId": roi.measurement_id, "kind": "interior", "index": None}
    assert controller.hoverCursorKind == ""
    controller.tap_at(ImagePoint(50, 50), slice_index=0, endpoint_tolerance=1, line_tolerance=1)
    assert controller.selectedMeasurementId == roi.measurement_id
    assert controller.hoverCursorKind == "pan"
    controller.clear_selection()
    assert controller.hoverHit["kind"] == "interior"
    assert controller.hoverCursorKind == ""
    controller.clearHover()
    assert controller.hoverHit == {}


def test_adaptive_roi_tolerance_preserves_small_roi_interior_and_nearest_corner():
    small = replace(
        _roi(MeasurementKind.RECT),
        points=(ImagePoint(0, 0), ImagePoint(10, 10)),
    )
    standard = _controller(small)
    adaptive = MeasurementController(adaptive_roi_hit_tolerance=True)
    adaptive._measurements = {small.measurement_id: small}

    standard_center = standard.hit_test(
        ImagePoint(5, 5), slice_index=0,
        endpoint_tolerance=8, line_tolerance=6,
    )
    adaptive_center = adaptive.hit_test(
        ImagePoint(5, 5), slice_index=0,
        endpoint_tolerance=8, line_tolerance=6,
    )
    assert standard_center.target.kind == EditTargetKind.CONTROL_POINT
    assert adaptive_center.target.kind == EditTargetKind.INTERIOR

    corner = adaptive.hit_test(
        ImagePoint(9, 1), slice_index=0,
        endpoint_tolerance=8, line_tolerance=6,
    )
    assert corner.target == MeasurementEditTarget(EditTargetKind.CONTROL_POINT, 1)
    edge = adaptive.hit_test(
        ImagePoint(5, 1), slice_index=0,
        endpoint_tolerance=8, line_tolerance=6,
    )
    assert edge.target == MeasurementEditTarget(EditTargetKind.OUTLINE, 0)

    large = _roi(MeasurementKind.RECT)
    adaptive._measurements = {large.measurement_id: large}
    assert adaptive._hit_tolerances(large, 8, 6) == (8, 6)


def test_hover_distinguishes_outline_control_point_label_and_empty_canvas():
    controller = _controller(_line(), selected="line")
    before = controller.measurementItems
    for point, part, cursor in [
        (ImagePoint(50, 0), "outline", "pan"),
        (ImagePoint(0, 0), "controlPoint", ""),
        (ImagePoint(150, 50), None, ""),
    ]:
        controller.update_hover(point, slice_index=0, endpoint_tolerance=1, line_tolerance=1)
        assert controller.hoverHit.get("kind") == part
        assert controller.hoverCursorKind == cursor
    controller.setLabelHitRegions(_label_regions("line"))
    controller.update_hover(ImagePoint(150, 50), slice_index=0, endpoint_tolerance=1,
                            line_tolerance=1, viewport_point=Point(450, 350))
    assert controller.hoverHit["kind"] == "label"
    assert controller.hoverCursorKind == "pan"
    assert controller.measurementItems == before
    controller.delete_selected()
    assert controller.hoverHit == {}
    assert controller.hoverCursorKind == ""
