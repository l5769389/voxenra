from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.freehand_roi import simple_polygon
from qt_dicom_viewer.core.measurement_geometry import roi_metrics
from qt_dicom_viewer.core.measurement_hit_test import (
    hit_test_interior,
    hit_test_outline,
)
from qt_dicom_viewer.core.workspace_state import dumps, loads, encode, decode
from qt_dicom_viewer.model import ImagePoint, MeasurementKind
from qt_dicom_viewer.model.measure import RoiMeasurement
from qt_dicom_viewer.ui.controller.viewport.controller.measure.measure_controller import (
    MeasurementController,
)
from test_measurement_controller import _context, _position, _drag
from test_measurement_qml import (
    qt_app as qt_app,
    viewport as viewport,
    _scene,
    _visual_children,
)


def points(values):
    return tuple(ImagePoint(*p) for p in values)


def test_concave_polygon_area_perimeter_and_pixel_centers():
    p = points([(0, 0), (4, 0), (4, 4), (2, 2), (0, 4)])
    pixels = np.arange(25, dtype=float).reshape(5, 5)
    m = roi_metrics(
        p, MeasurementKind.FREEHAND, pixels, row_spacing=3, column_spacing=2, unit="HU"
    )
    assert m.area_mm2 == 72
    assert m.perimeter_mm == pytest.approx(8 + 24 + 2 * np.hypot(4, 6))
    expected = pixels[
        np.array(
            [
                [1, 1, 1, 1, 1],
                [1, 1, 1, 1, 1],
                [1, 1, 1, 1, 1],
                [1, 1, 0, 1, 1],
                [1, 0, 0, 0, 1],
            ],
            dtype=bool,
        )
    ]
    assert m.pixel_count == 21
    assert m.mean == pytest.approx(expected.mean()) and m.std == pytest.approx(
        expected.std()
    )
    assert simple_polygon(p)
    roi = RoiMeasurement("id", "s", "i", 0, MeasurementKind.FREEHAND, p, m)
    assert hit_test_interior(roi, ImagePoint(2, 3)) is None
    assert hit_test_interior(roi, ImagePoint(1, 1)) is not None
    assert hit_test_outline(roi, ImagePoint(0, 2), 0.1) is not None
    assert loads(dumps(roi)) == roi


def test_crossings_invalid_spacing_and_padding():
    assert not simple_polygon(points([(0, 0), (4, 4), (0, 4), (4, 0)]))
    p = points([(-2, -2), (3, -2), (3, 3), (-2, 3)])
    pixels = np.full((3, 3), 7.0)
    pixels[0, 0] = np.nan
    m = roi_metrics(
        p, MeasurementKind.FREEHAND, pixels, row_spacing=2, column_spacing=1
    )
    assert m.area_mm2 == 50 and m.pixel_count == 8 and m.mean == 7
    assert (
        roi_metrics(
            p, MeasurementKind.FREEHAND, pixels, row_spacing=0, column_spacing=1
        ).area_mm2
        is None
    )
    old = encode(m)
    del old["fields"]["perimeter_mm"]
    assert decode(old).perimeter_mm is None


def test_freehand_creation_translation_vertex_edit_cancel_and_copy():
    c = MeasurementController()
    context = replace(
        _context(),
        measurement_kind=MeasurementKind.FREEHAND,
        modality_pixels=np.ones((100, 100)),
        endpoint_tolerance=1,
        line_tolerance=0.5,
    )
    start = _position(10, 10)
    for x, y in [(10, 10), (30, 10), (30, 30), (20, 20), (10, 30), (10, 10)]:
        c.tap_at(ImagePoint(x, y), slice_index=0, endpoint_tolerance=1,
                 line_tolerance=0.5, context=context)
    original = c.committed_measurements[0]
    assert len(original.points) == 5 and original.smooth
    assert original.metrics.area_mm2 > 300
    assert c.selected_copy()["kind"] == "freehand"
    c.begin(_position(15, 15), context)
    c.update(_drag(_position(15, 15), _position(20, 15)))
    c.end(_position(20, 15))
    moved = c.committed_measurements[0]
    assert moved.points[0] == ImagePoint(15, 10) and moved.metrics.area_mm2 == pytest.approx(original.metrics.area_mm2)
    c.begin(_position(15, 10), context)
    c.update(_drag(_position(15, 10), _position(12, 8)))
    c.cancel_transaction()
    assert c.committed_measurements[0] == moved
    copy = c.paste_points(list(original.points), context)
    assert copy and copy != original.measurement_id
    assert len(c.committed_measurements) == 2


def test_real_pointer_freehand_outline_and_metrics(viewport):
    view, controller, layer, warnings = viewport
    controller._tool_controller.selectInteraction("measure:freehand")
    layer_item = next(
        x
        for x in _visual_children(view.rootObject())
        if x.objectName() == "viewportInteractionLayer"
    )
    assert layer_item.property("hoverCursorKind") == "measure-freehand"
    assert layer_item.property("immediateRoiDrag")
    path = [(30, 35), (95, 35), (110, 65), (80, 80), (95, 110), (30, 95), (30, 35)]
    for p in path[:-1]:
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(layer, *p))
        QTest.qWait(30)
        before = len(controller._measure_controller._active_transaction.draft.points)
        QTest.mouseMove(view, _scene(layer, p[0] + 2, p[1] + 2), 25)
        assert len(controller._measure_controller._active_transaction.draft.points) == before
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(layer, *path[-1]))
    QTest.qWait(50)
    item = controller._measure_controller.committed_measurements[0]
    assert item.kind == MeasurementKind.FREEHAND and item.smooth and item.metrics.perimeter_mm > 0
    assert len(controller._measure_controller.measurementItems[0]["renderPoints"]) > len(item.points)
    assert len(item.points) == len(path) - 1
    assert item.points[1].column == pytest.approx(path[1][0], abs=0.5)
    assert item.points[1].row == pytest.approx(path[1][1], abs=0.5)
    handles = [
        x
        for x in _visual_children(view.rootObject())
        if x.objectName() == "roiHandle" and x.isVisible()
    ]
    assert len(handles) == len(item.points)
    cards = [
        x
        for x in _visual_children(view.rootObject())
        if x.objectName() == "roiMetricCard" and x.isVisible()
    ]
    assert len(cards) == 1
    from PySide6.QtGui import QGuiApplication
    from qt_dicom_viewer.ui.annotation_clipboard import read_annotation
    try:
        assert controller.copySelectedAnnotation()
        assert read_annotation()["smooth"] is True
        assert controller.pasteAnnotation()
        copied = controller._measure_controller.committed_measurements[-1]
        assert copied.smooth and len(copied.points) == len(item.points)
        assert copied.metrics.area_mm2 == pytest.approx(item.metrics.area_mm2)
    finally:
        # Release Python-owned MIME data while the Qt application is still alive.
        QGuiApplication.clipboard().clear()
    QTest.qWait(50)
    assert not warnings


@pytest.mark.parametrize("kind", [MeasurementKind.FREEHAND, MeasurementKind.CURVE])
@pytest.mark.parametrize("smooth", [False, True])
def test_freehand_history_workspace_and_csv(qt_app, tmp_path, kind, smooth):
    import csv
    from test_workspace_persistence import populated_app
    from test_dicom_tags import wait_until

    app, _ = populated_app(tmp_path)
    try:
        view = app.workspaceController.activeViewport
        controller = view._measure_controller
        history = app.workspaceController.activeTab.historyController
        context = view._measurement_context(3, 2, kind=kind)
        path = points([(30, 30), (60, 30), (60, 60), (45, 45), (30, 60)])
        identifier = controller.paste_points(list(path), context, smooth=smooth)
        history.capture()
        original = controller._measurements[identifier]
        if kind == MeasurementKind.FREEHAND:
            if not smooth:
                assert original.metrics.area_mm2 == pytest.approx(675 * 0.7 * 0.8)
            assert original.smooth == smooth
            assert original.metrics.pixel_count > 0 and original.metrics.perimeter_mm > 0
        else:
            assert original.length_mm > 0
        history.undo()
        assert not controller.committed_measurements
        history.redo()
        assert controller._measurements[identifier] == original

        document = app.workspaceDocumentController
        filename = tmp_path / "freehand.voxworkspace"
        assert document.save_to(filename)
        wait_until(lambda: not document.busy)
        assert not document.isError, document.message
        assert document.restore_from(filename)
        wait_until(lambda: not document.busy)
        assert not document.isError, document.message
        restored = app.workspaceController.activeViewport._measure_controller
        assert restored._measurements[identifier] == original
        report = app.exportController.measurementReport
        csv_path = tmp_path / "freehand.csv"
        assert report.export_to(csv_path)
        wait_until(lambda: not report.busy)
        assert not report.isError, report.message
        with csv_path.open(encoding="utf-8-sig") as stream:
            rows = list(csv.reader(stream))
        if kind == MeasurementKind.FREEHAND:
            from qt_dicom_viewer.core.measurement_report import COLUMNS
            column = next(i for i, (key, _) in enumerate(COLUMNS) if key == "perimeter_mm")
            assert float(rows[-1][column]) == pytest.approx(original.metrics.perimeter_mm, abs=0.01)
        else:
            assert float(rows[-1][9]) == pytest.approx(original.length_mm, abs=0.01)
    finally:
        app.shutdown()


def test_projected_measurement_retains_frame_origin_after_projection_disabled(viewport):
    window, view, layer, _ = viewport
    controller = view._measure_controller
    frame = view._frame_meta
    uid = view.viewport_config.series_uid
    controller.set_frame(uid, frame, source_context=("projection", "mip", 20))
    context = view._measurement_context(3, 2, kind=MeasurementKind.FREEHAND)
    identifier = controller.paste_points(
        list(points([(20, 20), (40, 20), (30, 40)])), context
    )
    assert controller._measurement_frames[identifier][6] == ("projection", "mip", 20)
    controller.set_frame(uid, frame)
    assert controller.visible_measurements == ()
    assert controller.committed_measurements[0].measurement_id == identifier
    assert (
        loads(dumps(controller._measurement_frames))[identifier][6][0] == "projection"
    )


def test_smooth_boundary_area_statistics_picking_and_legacy_workspace():
    from qt_dicom_viewer.core.freehand_roi import roi_outline
    p = points([(5, 5), (15, 5), (15, 15), (5, 15)])
    pixels = np.zeros((21, 21))
    pixels[4, 10] = 100  # Inside the spline, outside the straight control polygon.
    m = roi_metrics(p, MeasurementKind.FREEHAND, pixels, row_spacing=2,
                    column_spacing=.5, smooth=True)
    # Exact integral of four periodic uniform Catmull-Rom spans: 41/30 times square area.
    assert m.area_mm2 == pytest.approx(100*41/30, abs=.015)
    assert m.width_mm == pytest.approx(12.5*.5)
    assert m.height_mm == pytest.approx(12.5*2)
    assert m.maximum == 100 and m.pixel_count > 121
    boundary = roi_outline(p, True)
    assert len(boundary) > len(p) and all(v in boundary for v in p)
    # Independent high-order quadrature of the analytic cubic derivative in mm.
    t, w = np.polynomial.legendre.leggauss(64)
    t = (t+1)/2
    perimeter = 0
    coords = np.array([(v.column, v.row) for v in p])
    for i in range(4):
        a,b,c,d = (coords[(i+j)%4] for j in (-1,0,1,2))
        derivative = .5*((-a+c) + 2*(2*a-5*b+4*c-d)*t[:,None]
                         + 3*(-a+3*b-3*c+d)*(t*t)[:,None])
        perimeter += np.dot(w/2, np.linalg.norm(derivative*[.5,2], axis=1))
    assert m.perimeter_mm == pytest.approx(perimeter, abs=.002)
    roi = RoiMeasurement('spline','s','i',0,MeasurementKind.FREEHAND,p,m,smooth=True)
    assert hit_test_interior(roi, ImagePoint(10,4))
    assert hit_test_outline(roi, ImagePoint(10,3.75), .001)
    assert loads(dumps(roi)) == roi
    old = replace(roi, smooth=False, metrics=roi_metrics(p,MeasurementKind.FREEHAND,
        pixels,row_spacing=2,column_spacing=.5))
    encoded = encode(old)
    del encoded['fields']['smooth']
    restored = decode(encoded)
    assert restored == old and restored.metrics.area_mm2 == 100
    assert hit_test_interior(restored, ImagePoint(10,4)) is None


def test_smoothing_tightens_overshoot_before_preview_and_commit():
    from qt_dicom_viewer.core.freehand_roi import roi_outline
    from qt_dicom_viewer.core.curve_geometry import sample_closed_curve
    p = points([(0,0),(10,0),(10,10),(9.9,.1),(0,10)])
    assert simple_polygon(p)  # The clicks alone are a valid polygon.
    assert not simple_polygon(sample_closed_curve(p))  # Previous interpolation crossed.
    boundary = roi_outline(p, True)
    assert simple_polygon(boundary) and len(boundary) > len(p)
    assert all(v in boundary for v in p)  # No control point is moved or reordered.
    c = MeasurementController()
    context = replace(_context(),measurement_kind=MeasurementKind.FREEHAND,
                      endpoint_tolerance=.01,line_tolerance=.01)
    for v in p:
        c.tap_at(v,slice_index=0,endpoint_tolerance=.01,line_tolerance=.01,context=context)
        displayed = points((v['column'], v['row']) for v in c.activeTransaction['renderPoints'])
        if len(displayed) >= 3:
            assert simple_polygon(displayed)
    assert c.finish_path()
    assert len(c.committed_measurements) == 1 and not c.has_active_transaction
    assert c.committed_measurements[0].points == p


def test_freehand_preview_click_and_drag_keep_the_last_valid_contour():
    from qt_dicom_viewer.core.freehand_roi import roi_outline
    c = MeasurementController()
    context = replace(_context(), measurement_kind=MeasurementKind.FREEHAND,
                      endpoint_tolerance=1, line_tolerance=.5)
    def click(x, y):
        c.tap_at(ImagePoint(x,y), slice_index=3, endpoint_tolerance=1,
                 line_tolerance=.5, context=context)
    click(10,10)
    click(30,10)
    c.preview_at(ImagePoint(30.1,10.1))
    assert len(c.activeTransaction['renderPoints']) == 2  # Snap near the last click.
    click(30,30)
    c.preview_at(ImagePoint(10,30))
    valid = c.activeTransaction['renderPoints']
    c.preview_at(ImagePoint(10,0))  # New segment would cross the first edge.
    assert c.activeTransaction['renderPoints'] == valid and c._path_invalid
    click(10,0)
    assert len(c._active_transaction.draft.points) == 3 and c._path_invalid
    click(10,30)
    assert not c._path_invalid
    assert c.finish_path()
    original = c.committed_measurements[0]
    c.begin(_position(30,10), context)
    c.update(_drag(_position(30,10),_position(35,10)))
    valid = c._active_transaction.draft
    c.update(_drag(_position(30,10),_position(5,25)))
    assert c._active_transaction.draft == valid  # No snap back to the starting contour.
    c.end(_position(5,25))
    edited = c.committed_measurements[0]
    assert edited.points[1] == ImagePoint(35,10)
    assert simple_polygon(roi_outline(edited.points, True))
    assert edited.metrics != original.metrics


@pytest.mark.parametrize('coords', [
    [(0,0),(100,0),(100.0001,.0001),(0,100)],  # Nearly coincident neighbors.
    [(0,0),(10,0),(10,10),(9.9,.1),(0,10)],  # Narrow concavity.
    [(368,410),(616,154),(385,155)],  # Two clicks and a triangular hover preview.
])
def test_safe_freehand_outline_with_uneven_control_spacing(coords):
    from qt_dicom_viewer.core.freehand_roi import roi_outline
    p = points(coords)
    boundary = roi_outline(p,True)
    assert simple_polygon(boundary)
    assert all(v in boundary for v in p)
    assert np.isfinite([(v.column,v.row) for v in boundary]).all()


def test_real_pointer_rejects_crossing_preview_and_click(viewport, tmp_path):
    view, controller, layer, warnings = viewport
    controller._tool_controller.selectInteraction('measure:freehand')
    for p in [(30,35),(95,35),(95,95)]:
        QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,*p))
        QTest.qWait(30)
    QTest.mouseMove(view,_scene(layer,30,95),30)
    QTest.qWait(30)
    measure = controller._measure_controller
    previous = measure.activeTransaction['renderPoints']
    QTest.mouseMove(view,_scene(layer,30,20),30)
    QTest.qWait(30)
    assert measure.activeTransaction['renderPoints'] == previous
    QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,30,20))
    QTest.qWait(30)
    assert len(measure._active_transaction.draft.points) == 3
    assert measure._path_invalid
    QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,30,95))
    QTest.keyClick(view,Qt.Key_Return)
    QTest.qWait(50)
    assert len(measure.committed_measurements) == 1
    assert len(measure.committed_measurements[0].points) == 4
    screenshot = view.grabWindow()
    if not screenshot.isNull():
        assert screenshot.save(str(tmp_path/'freehand-no-crossing.png'))
    assert not warnings


@pytest.mark.parametrize('coords, expected', [
    ([(0,0),(4,0),(4,4),(0,4)], True),
    ([(0,0),(4,0),(4,4),(2,2),(0,4)], True),
    ([(0,0),(4,4),(0,4),(4,0)], False),
    ([(0,0),(4,0),(4,4),(2,0),(0,4)], False),  # Nonadjacent edge touch.
    ([(0,0),(4,0),(2,0),(0,4)], False),  # Collinear overlapping edges.
    ([(0,0),(4,0),(2,0)], False),
])
def test_polygon_sweep_detects_crossings_touches_and_overlaps(coords, expected):
    assert simple_polygon(points(coords)) is expected
