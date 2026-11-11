"""Curve geometry and click-based paths share the displayed/exported physical arc."""
from test_dicom_tags import wait_until
from dataclasses import replace
import math
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from voxplane.core.curve_geometry import sample_curve, curve_length_mm
from voxplane.core.measurement_hit_test import hit_test_outline, hit_test_control_points
from voxplane.core.workspace_state import dumps, loads
from voxplane.model import ImagePoint, MeasurementKind
from voxplane.ui.controller.viewport.controller.measure.measure_controller import MeasurementController
from test_measurement_controller import _context, _position, _drag
from test_measurement_qml import qt_app, viewport, _scene, _visual_children


def click(c, p, context):
    c.tap_at(p, slice_index=0, endpoint_tolerance=1, line_tolerance=.5, context=context)


def test_curve_geometry_physical_spacing_endpoints_and_convergence():
    straight = [ImagePoint(0,0), ImagePoint(10,0), ImagePoint(20,0)]
    assert curve_length_mm(straight, 3, 2) == pytest.approx(40)
    assert curve_length_mm(straight, 0, 2) == 0
    controls = [ImagePoint(0,0), ImagePoint(10,20), ImagePoint(30,-5), ImagePoint(50,10)]
    path = sample_curve(controls)
    assert path[0] == controls[0] and path[-1] == controls[-1]
    assert [path[i*128] for i in range(len(controls))] == controls
    fine = sample_curve(controls, 2048)
    expected = sum(math.hypot((b.column-a.column)*.4, (b.row-a.row)*.9) for a,b in zip(fine,fine[1:]))
    assert curve_length_mm(controls,.9,.4) == pytest.approx(expected,abs=.002)
    assert curve_length_mm(controls,.9,.4) > sum(math.hypot((b.column-a.column)*.4,(b.row-a.row)*.9) for a,b in zip(controls,controls[1:]))


def test_curve_click_preview_edit_copy_and_workspace():
    c=MeasurementController()
    context=replace(_context(),measurement_kind=MeasurementKind.CURVE,endpoint_tolerance=1,line_tolerance=.5)
    controls=[ImagePoint(10,10),ImagePoint(30,40),ImagePoint(60,20)]
    for p in controls:
        click(c,p,context)
        c.preview_at(ImagePoint(p.column+5,p.row+6))
    assert c._active_transaction.draft.points==controls
    assert c.finish_path()
    original=c.committed_measurements[0]
    assert original.kind==MeasurementKind.CURVE and original.length_mm>0
    assert loads(dumps(original))==original
    sampled=sample_curve(original.points)
    assert hit_test_outline(original,sampled[30],.01)
    assert hit_test_control_points(original,sampled[30],.01) is None
    c.begin(_position(30,40),context)
    c.update(_drag(_position(30,40),_position(30,50)))
    c.end(_position(30,50))
    edited=c.committed_measurements[0]
    assert edited.points[1]==ImagePoint(30,50) and edited.length_mm>original.length_mm
    assert c.paste_points(list(edited.points),context)
    assert c.committed_measurements[1].length_mm==edited.length_mm


@pytest.mark.parametrize('kind',['curve','freehand'])
@pytest.mark.parametrize('finish',['enter','double'])
def test_real_click_paths_have_only_clicked_handles(viewport,kind,finish,tmp_path):
    view,controller,layer,warnings=viewport
    controller._tool_controller.selectInteraction('measure:'+kind)
    c=controller._measure_controller
    path=[(25,30),(100,35),(110,95),(35,85)]
    for p in path:
        QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,*p))
        QTest.qWait(30)
        QTest.mouseMove(view,_scene(layer,p[0]+5,p[1]+5),20)
    wait_until(lambda: len(c._active_transaction.draft.points)==4)
    controls = tuple(c._active_transaction.draft.points)
    if finish=='enter':
        QTest.keyClick(view,Qt.Key_Return)
    else:
        QTest.mouseDClick(view,Qt.LeftButton,Qt.NoModifier,_scene(layer, 20, 60))
    QTest.qWait(50)
    assert len(c.committed_measurements)==1
    item=c.committed_measurements[0]
    assert tuple(item.points)==controls
    assert not c.has_active_transaction
    if kind=='curve':
        assert item.length_mm>0
        handles=[x for x in _visual_children(view.rootObject()) if x.objectName()=='measurementControlPoint' and x.isVisible()]
        assert len(handles)==4
    assert view.grabWindow().save(str(tmp_path/f'{kind}-{finish}.png'))
    assert not warnings,warnings


def test_drag_does_not_sample_path_and_escape_discards_it(viewport):
    view,controller,layer,warnings=viewport
    controller._tool_controller.selectInteraction('measure:freehand')
    c=controller._measure_controller
    QTest.mousePress(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,20,20))
    for p in [(30,25),(40,35),(50,40)]:
        QTest.mouseMove(view,_scene(layer,*p),20)
    QTest.mouseRelease(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,50,40))
    assert len(c._active_transaction.draft.points)==1
    assert not c.committed_measurements
    QTest.keyClick(view,Qt.Key_Escape)
    assert not c.has_active_transaction and not c.committed_measurements
    assert not warnings,warnings


def test_curve_tightens_a_loop_without_moving_controls_and_uses_repaired_arc():
    from voxplane.core.curve_geometry import _sample_open_curve
    from voxplane.core.freehand_roi import simple_path
    controls = tuple(ImagePoint(*p) for p in [(0,0),(10,0),(10,10),(9.9,.1),(0,10)])
    old = _sample_open_curve(controls, 128, 1.0)
    assert simple_path(controls) and not simple_path(old)
    repaired = sample_curve(controls)
    assert simple_path(repaired) and len(repaired) > len(controls)
    assert repaired[0] == controls[0] and repaired[-1] == controls[-1]
    assert all(p in repaired for p in controls)
    expected = sum(math.hypot((b.column-a.column)*.4,(b.row-a.row)*.9)
                   for a,b in zip(repaired,repaired[1:]))
    assert curve_length_mm(controls,.9,.4) == pytest.approx(expected)
    assert curve_length_mm(controls,.9,.4) != pytest.approx(sum(
        math.hypot((b.column-a.column)*.4,(b.row-a.row)*.9) for a,b in zip(old,old[1:])))


@pytest.mark.parametrize('coords, valid', [
    ([(0,0),(10,0),(10,10),(0,10)], True),  # Open path has no closing segment.
    ([(0,0),(10,10),(0,10),(10,0)], False),  # First and last segments cross.
    ([(0,0),(10,0),(5,0)], False),  # Adjacent retracing also knots a curve.
    ([(0,0),(10,0),(10,0),(20,10)], False),
    ([(0,0),(10,0),(5,5),(5,0)], False),  # Nonadjacent touch.
    ([(0,0),(10,0),(10,10),(0,0)], False),  # Curve remains open.
    ([(0,0),(10,0),(20,0)], True),
])
def test_open_curve_rejects_crossing_retracing_and_duplicate_controls(coords, valid):
    from voxplane.core.freehand_roi import simple_path
    controls = tuple(ImagePoint(*p) for p in coords)
    assert simple_path(controls) is valid
    assert bool(sample_curve(controls)) is valid
    assert (curve_length_mm(controls,1,1)>0) is valid


def test_curve_invalid_preview_click_edit_and_paste_keep_valid_measurement():
    c = MeasurementController()
    context = replace(_context(),measurement_kind=MeasurementKind.CURVE,
                      endpoint_tolerance=1,line_tolerance=.5)
    for p in [(10,10),(30,10),(30,30)]:
        click(c,ImagePoint(*p),context)
    c.preview_at(ImagePoint(30.1,30.1))
    assert len(c._active_transaction.draft.points) == 3
    assert c.activeTransaction['renderPoints'][-1] == {'column':30, 'row':30}
    c.preview_at(ImagePoint(10,30))
    last = c.activeTransaction['renderPoints']
    c.preview_at(ImagePoint(10,0))
    assert c.activeTransaction['renderPoints'] == last and c._path_invalid
    click(c,ImagePoint(10,0),context)
    assert len(c._active_transaction.draft.points) == 3
    click(c,ImagePoint(10,30),context)
    assert not c._path_invalid and c.finish_path()
    c.begin(_position(30,10),context)
    c.update(_drag(_position(30,10),_position(35,10)))
    last = c._active_transaction.draft
    c.update(_drag(_position(30,10),_position(25,40)))
    assert c._active_transaction.draft == last
    c.end(_position(25,40))
    item = c.committed_measurements[0]
    assert item.points[1] == ImagePoint(35,10)
    assert item.length_mm == curve_length_mm(item.points,1,1)
    assert not c.paste_points([ImagePoint(*p) for p in [(0,0),(10,10),(0,10),(10,0)]],context)
    assert len(c.committed_measurements) == 1


def test_restored_curve_length_is_refreshed_from_the_safe_path(viewport):
    _,view,_,_ = viewport
    c = view._measure_controller
    context = view._measurement_context(1,.5,kind=MeasurementKind.CURVE)
    controls = [ImagePoint(*p) for p in [(20,20),(60,20),(60,60),(59.9,20.1),(20,60)]]
    uid = c.paste_points(controls,context)
    assert uid
    c._measurements[uid] = replace(c._measurements[uid],length_mm=9999)
    c.refresh_roi_metrics(view._modality_pixel, view._frame_meta)
    spacing = context.geometry.pixel_spacing
    assert c._measurements[uid].length_mm == curve_length_mm(controls,spacing.row,spacing.column)


def test_real_curve_crossing_preview_is_blocked_and_controls_can_continue(viewport,tmp_path):
    from voxplane.core.freehand_roi import simple_path
    view,controller,layer,warnings = viewport
    controller._tool_controller.selectInteraction('measure:curve')
    for p in [(30,35),(95,35),(95,95)]:
        QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,*p))
        QTest.qWait(30)
    c = controller._measure_controller
    wait_until(lambda: len(c._active_transaction.draft.points) == 3)
    QTest.mouseMove(view,_scene(layer,30,95),30)
    QTest.qWait(30)
    last = c.activeTransaction['renderPoints']
    QTest.mouseMove(view,_scene(layer,30,20),30)
    QTest.qWait(30)
    assert c.activeTransaction['renderPoints'] == last
    QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,30,20))
    assert len(c._active_transaction.draft.points) == 3
    QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,_scene(layer,30,95))
    QTest.keyClick(view,Qt.Key_Return)
    QTest.qWait(50)
    item = c.committed_measurements[0]
    assert len(item.points) == 4 and simple_path(sample_curve(item.points))
    assert view.grabWindow().save(str(tmp_path/'curve-no-crossing.png'))
    assert not warnings,warnings


@pytest.mark.parametrize("kind", ["curve", "freehand"])
def test_double_click_exits_too_short_path_without_creating_a_measurement(viewport, kind):
    view, controller, layer, warnings = viewport
    controller._tool_controller.selectInteraction("measure:" + kind)
    for xy in [(30, 35), (95, 35)]:
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(layer, *xy))
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, _scene(layer, 80, 90))
    assert not controller.measurementController.has_active_transaction
    assert not controller.measurementController.committed_measurements
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["curve", "freehand"])
def test_drag_places_one_path_point_at_release(viewport, kind):
    from PySide6.QtCore import QPoint
    window, controller, layer, warnings = viewport
    controller._tool_controller.selectInteraction('measure:' + kind)
    measure = controller.measurementController
    for i, (x, y) in enumerate(((50, 50), (90, 60), (70, 90))):
        end = _scene(layer, x, y)
        start = end - QPoint(19, 12)
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        marker = next(item for item in _visual_children(window.rootObject())
                      if item.objectName() == 'pathPointPlacementPreview')
        assert marker.isVisible()
        QTest.mouseMove(window, start + QPoint(11, 8), 20)
        QTest.mouseMove(window, end, 20)
        assert len(measure.activeTransaction.get('points', [])) == i
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
        assert not marker.isVisible()
        points = measure.activeTransaction['points']
        assert len(points) == i + 1
        assert (points[-1]['column'], points[-1]['row']) == pytest.approx((x, y), abs=.3)
    QTest.keyClick(window, Qt.Key_Return)
    assert len(measure.committed_measurements) == 1 and not warnings
