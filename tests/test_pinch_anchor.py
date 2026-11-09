"""Zoom keeps the anatomy under the cursor / touch centroid stationary."""
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QInputDevice
from PySide6.QtTest import QTest

from test_measurement_qml import qt_app, viewport
from test_pinch_zoom import trackpad, gesture
from test_volume_view import volume, make_tab
from test_compare_2d import comparison


def assert_point(actual, expected, tolerance=.01):
    assert actual.x() == pytest.approx(expected.x(), abs=tolerance)
    assert actual.y() == pytest.approx(expected.y(), abs=tolerance)


@pytest.mark.parametrize('rotation,flipped', [(0,False),(37,False),(90,True)])
def test_trackpad_keeps_cursor_anatomy_fixed_after_pan_and_rotation(viewport, trackpad, rotation, flipped):
    view, controller, pixels, warnings = viewport
    controller.apply_pan(35, -22)
    controller.apply_rotation(rotation)
    if flipped:
        controller.applyTransformAction('rotate:mirror-h')
    anchor = QPointF(640, 255)
    landmark = pixels.mapFromScene(anchor)
    before = controller._state
    gesture(view, trackpad, anchor, [.2, .25])
    assert controller.zoom == pytest.approx(before.zoom * 1.5)
    assert_point(pixels.mapToScene(landmark), anchor)
    assert replace(controller._state, zoom=before.zoom, pan_x=before.pan_x, pan_y=before.pan_y) == before
    assert not warnings


@pytest.mark.parametrize('device_type', [QInputDevice.DeviceType.TouchScreen, QInputDevice.DeviceType.TouchPad])
def test_touch_points_use_finger_centroid_only_on_touchscreen(viewport, device_type):
    view, controller, pixels, warnings = viewport
    QTest.mouseMove(view, QPoint(140, 140))
    QCursor.setPos(view.mapToGlobal(QPoint(140,140)))
    device = QTest.createTouchDevice(device_type)
    center = QPoint(650, 420)
    anchor = center if device_type == QInputDevice.DeviceType.TouchScreen else QPoint(140,140)
    landmark = pixels.mapFromScene(QPointF(anchor))
    sequence = QTest.touchEvent(view, device, False)
    sequence.press(0, center-QPoint(70,0), view).press(1,center+QPoint(70,0),view).commit()
    QTest.qWait(30)
    for distance in (90,110,130):
        sequence.move(0,center-QPoint(distance,0),view).move(1,center+QPoint(distance,0),view).commit()
        QTest.qWait(30)
    sequence.release(0,center-QPoint(130,0),view).release(1,center+QPoint(130,0),view).commit()
    QTest.qWait(30)
    assert controller.zoom > 1.2
    assert_point(pixels.mapToScene(landmark), QPointF(anchor))
    assert not warnings


@pytest.mark.parametrize('anchor', [(float('nan'), 100), (-1,20), (1200,800)])
def test_missing_or_outside_anchor_uses_viewport_center(viewport, anchor):
    view, controller, pixels, _ = viewport
    controller.apply_pan(35,-22)
    center=QPointF(view.width()/2,view.height()/2)
    landmark=pixels.mapFromScene(center)
    controller.pinchZoom(1.5,*anchor,view.width(),view.height())
    assert_point(pixels.mapToScene(landmark),center)


def test_pinch_limit_preserves_anchor_and_reverses_immediately(viewport,trackpad):
    view,controller,pixels,_=viewport
    controller.apply_pan(35,-22)
    controller.setZoom(19)
    anchor=QPointF(660,260)
    landmark=pixels.mapFromScene(anchor)
    gesture(view,trackpad,anchor,[1,-.1])
    assert controller.zoom == pytest.approx(18)
    assert_point(pixels.mapToScene(landmark),anchor)


def project_volume(geometry,state,size,point):
    from qt_dicom_viewer.core.volume_view import camera_parameters,view_basis
    camera=camera_parameters(geometry,state,size)
    delta=np.asarray(point)-camera['focal']
    basis=view_basis(state)
    scale=size[1]/(2*camera['scale'])
    return QPointF(size[0]/2+np.dot(delta,basis[:,0])*scale,
                   size[1]/2-np.dot(delta,basis[:,1])*scale)


def test_volume_zoom_keeps_offcenter_patient_point_fixed(qt_app,volume):
    from qt_dicom_viewer.core.volume_view import VolumeViewState,rotate_drag
    tab=make_tab();controller=tab.activeViewport
    controller._set_status('ready')
    controller.state=rotate_drag(VolumeViewState(pan=(.12,-.07)),(300,250),(330,290),(800,600))
    point=volume.geometry.center_patient+np.array([.6,.4,.5])
    position=project_volume(volume.geometry,controller.state,(800,600),point)
    controller.pinchZoom(1.5,position.x(),position.y(),800,600)
    assert_point(project_volume(volume.geometry,controller.state,(800,600),point),position)
    controller.shutdown()


@pytest.mark.parametrize('pan_link,zoom_link', [(True,True),(False,True),(True,False),(False,False)])
def test_compare_anchor_updates_respect_separate_pan_and_zoom_links(comparison,pan_link,zoom_link):
    from test_compare_2d import open_pair
    app,records=comparison
    tab,(first,second)=open_pair(app,records)
    first.setViewportSize(800,600)
    second.setViewportSize(400,300)
    first.apply_pan(30,-20)
    tab.setSyncOperation('pan',pan_link)
    tab.setSyncOperation('zoom',zoom_link)
    before=second._state
    changes=[]
    first.displayCommand.connect(changes.append)
    first.pinchZoom(1.5,620,250,800,600)
    assert len(changes)==1 and set(changes[0])=={'pan','zoom'}
    assert second.zoom==pytest.approx(1.5 if zoom_link else before.zoom)
    expected_pan=(first.panX/2,first.panY/2) if pan_link else (before.pan_x,before.pan_y)
    assert (second.panX,second.panY)==pytest.approx(expected_pan)
