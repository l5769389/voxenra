"""Real native trackpad events: route zoom without mouse clicks or tool changes."""
from dataclasses import replace
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl, Qt, Property, Signal
from PySide6.QtGui import QCursor, QInputDevice, QNativeGestureEvent, QPointingDevice
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import delete

from test_measurement_qml import qt_app, viewport, _scene, _visual_children
from test_mpr_pointer_units_qml import mpr_scene
from test_mpr_voi_qml import _owner
from test_cpr_qml import cpr_page
from test_cpr_controller import cpr
from test_mpr_layout import loaded
from test_pet_fusion import paired_series
from test_compare_2d import comparison

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def trackpad(qt_app):
    return QPointingDevice("Test trackpad", 12345, QInputDevice.DeviceType.TouchPad,
        QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position,
        2, 0)


def gesture(target, device, position, deltas):
    position = QPointF(position)
    QCursor.setPos(target.mapToGlobal(position.toPoint()))
    QTest.mouseMove(target, position.toPoint())
    global_position = QPointF(target.mapToGlobal(position.toPoint()))
    for kind, value in [(Qt.BeginNativeGesture, 0), *[(Qt.ZoomNativeGesture, d) for d in deltas],
                        (Qt.EndNativeGesture, 0)]:
        fingers = 2 if kind == Qt.ZoomNativeGesture else 0
        event = QNativeGestureEvent(kind, device, fingers, position, position,
                                    global_position, value, QPointF())
        QApplication.sendEvent(target, event)
        QTest.qWait(5)


@pytest.mark.parametrize("tool", ["window", "pan", "measure:length", "measure:curve", "annotate:arrow"])
def test_native_pinch_updates_image_and_preserves_tool_and_geometry(viewport, trackpad, tool):
    view, controller, pixels, warnings = viewport
    controller._tool_controller.selectInteraction(tool)
    if tool.startswith("measure:"):
        QTest.mouseClick(view, Qt.LeftButton, pos=_scene(pixels, 50, 50))
    draft = controller.measurementController.activeTransaction.copy()
    before = controller._state
    scale = pixels.mapToScene(QPointF(100, 100)) - pixels.mapToScene(QPointF(0, 0))
    position = _scene(pixels, 120, 120)
    landmark = pixels.mapFromScene(QPointF(position))
    gesture(view, trackpad, position, [.25, .20])
    assert controller.zoom == pytest.approx(1.5)
    assert controller._state == replace(before, zoom=1.5, pan_x=controller.panX, pan_y=controller.panY)
    assert (pixels.mapToScene(landmark) - QPointF(position)).manhattanLength() < .01
    assert controller.activeInteraction == tool
    after_draft = controller.measurementController.activeTransaction
    # A live preview follows the cursor after the transform; confirmed points
    # and the number of committed measurements must not change.
    assert len(after_draft.get('points', [])) == len(draft.get('points', []))
    assert after_draft.get('points', [])[:1] == draft.get('points', [])[:1]
    assert after_draft.get('measurementId') == draft.get('measurementId')
    assert not controller.measurementController.measurementItems
    after = pixels.mapToScene(QPointF(100, 100)) - pixels.mapToScene(QPointF(0, 0))
    assert after.x() == pytest.approx(scale.x() * 1.5)
    assert not warnings


def test_pinch_limits_reverse_immediately_and_respect_external_reset(viewport, trackpad):
    view, controller, _, warnings = viewport
    p = QPointF(500, 360)
    controller.setZoom(19)
    gesture(view, trackpad, p, [1, -.1])
    assert controller.zoom == pytest.approx(18)
    controller.setZoom(.11)
    gesture(view, trackpad, p, [-.5, .5])
    assert controller.zoom == pytest.approx(.15)
    controller.setZoom(1)
    gesture(view, trackpad, p, [.2])
    assert controller.zoom == pytest.approx(1.2)
    assert not warnings


def test_pinch_targets_nonactive_mpr_view_without_changing_slice(mpr_scene, trackpad):
    view, axial, _, _ = mpr_scene
    tab = axial.workspaceTab
    target = next(v for v in tab.viewports_by_id.values() if v.viewportType == 'coronal')
    tab.activateViewport(axial.viewportId)
    pixels = next(x for x in _visual_children(view.rootObject())
                  if x.objectName() == 'dicomPixelLayer' and _owner(x) is target)
    before = {v.viewportId: v._state for v in tab.viewports_by_id.values()}
    gesture(view, trackpad, _scene(pixels, 30, 2), [.3])
    assert target.zoom == pytest.approx(1.3)
    assert tab.activeViewport is target
    for v in tab.viewports_by_id.values():
        expected = replace(before[v.viewportId], zoom=1.3, pan_x=v.panX, pan_y=v.panY) if v is target else before[v.viewportId]
        assert v._state == expected


@pytest.mark.parametrize('role', ['reference-a', 'reference-b', 'curved', 'cross'])
def test_all_cpr_views_pinch_without_moving_path_or_sampling_position(cpr_page, trackpad, role):
    view, tab = cpr_page
    target = tab.viewForRole(role)
    surface = next(x for x in _visual_children(view.rootObject())
                   if x.objectName() == 'cprViewport-' + role)
    before = {v.viewportId: v._state for v in tab.viewports_by_id.values()}
    path = tab.current_path
    gesture(view, trackpad, surface.mapToScene(QPointF(surface.width()/2, surface.height()/2)), [.4])
    assert target.zoom == pytest.approx(1.4)
    assert tab.activeViewport is target
    assert tab.current_path == path
    for v in tab.viewports_by_id.values():
        expected = replace(before[v.viewportId], zoom=1.4, pan_x=v.panX, pan_y=v.panY) if v is target else before[v.viewportId]
        assert v._state == expected


def test_montage_pinch_scales_images_without_scrolling_or_opening_slice(qt_app, trackpad):
    from test_montage_controller import _controller
    from voxplane.ui.svg_icon_provider import SvgIconProvider
    controller = _controller(100)
    opened = []
    controller.sliceOpenRequested.connect(lambda *args: opened.append(args))
    view = QQuickView()
    view.engine().addImageProvider('navigation', SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 720)
    warnings = []
    view.engine().warnings.connect(lambda es: warnings.extend(e.toString() for e in es))
    view.setInitialProperties(dict(viewportController=controller))
    view.setSource(QUrl.fromLocalFile(str(ROOT / 'src/voxplane/qml/sections/center/viewportArea/MontageViewport.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    QTest.qWait(80)
    try:
        grid = view.rootObject().findChild(QQuickItem, 'montageGrid')
        y = grid.property('contentY')
        tile_image = next(x for x in _visual_children(view.rootObject())
                          if x.objectName() == 'montageSliceImage-1')
        landmark = QPointF(tile_image.width()*.65,tile_image.height()*.4)
        anchor = tile_image.mapToScene(landmark).toPoint()
        landmark = tile_image.mapFromScene(QPointF(anchor))
        gesture(view, trackpad, anchor, [.5])
        assert controller.zoom == pytest.approx(1.5)
        assert (tile_image.mapToScene(landmark) - QPointF(anchor)).manhattanLength() < .01
        assert grid.property('contentY') == y
        assert not opened and not warnings
    finally:
        view.hide()
        delete(view)


def test_native_volume_widget_routes_pinch_and_keeps_camera_orientation(qt_app, trackpad):
    from test_volume_view import make_tab
    from voxplane.ui.volume_viewport_host import VolumeInteractor
    tab = make_tab()
    controller = tab.activeViewport
    controller._set_status('ready')
    class Host(QWidget):
        def request_render(self, *args, **kwargs): pass
        def _update_cursor(self): pass
    host = Host()
    host.controller = controller
    window = QQuickView()
    controller._native_owner = QQuickItem(window.contentItem())
    class EventOnlyInteractor(VolumeInteractor):
        def __init__(self, parent):
            # Exercise QWidget delivery and the production event handler without
            # creating a Cocoa VTK render window under the offscreen platform.
            self.host = parent
            self._drag_button = Qt.NoButton
            QWidget.__init__(self, parent)
    widget = EventOnlyInteractor(host)
    try:
        before = controller.state
        tool = controller.activeInteraction
        gesture(widget, trackpad, QPointF(150, 150), [.5, -.2])
        assert controller.state == replace(before, zoom=pytest.approx(1.2))
        assert controller.activeInteraction == tool
        window.setProperty('shortcutPopupOpen', True)
        gesture(widget, trackpad, QPointF(150, 150), [.5])
        assert controller.zoom == pytest.approx(1.2)
        window.setProperty('shortcutPopupOpen', False)
        gesture(widget, trackpad, QPointF(150, 150), [.5])
        assert controller.zoom == pytest.approx(1.8)
    finally:
        controller._native_owner = None
        delete(window)
        delete(widget)
        delete(host)
        controller.shutdown()


@pytest.mark.parametrize('factor', [0, -1, float('nan'), float('inf'), -float('inf')])
def test_invalid_pinch_is_ignored(viewport, factor):
    _, controller, _, _ = viewport
    before = controller._state
    controller.pinchZoom(factor)
    assert controller._state == before


def test_pinch_is_blocked_while_modal_is_open_and_recovers(viewport, trackpad, tmp_path):
    _, controller, _, _ = viewport
    class ModalView(QQuickView):
        popupChanged = Signal()
        _popup = False
        @Property(bool, notify=popupChanged)
        def shortcutPopupOpen(self): return self._popup
        @shortcutPopupOpen.setter
        def shortcutPopupOpen(self, value):
            self._popup = value
            self.popupChanged.emit()
    window = ModalView()
    source = tmp_path / 'Pinch.qml'
    directory = (ROOT / 'src/voxplane/qml/sections/center/viewportArea').as_uri()
    source.write_text(f'''import QtQuick
import "{directory}" as Views
Item {{
    Views.ViewportPinchHandler {{ viewportController: testController }}
}}''')
    window.engine().rootContext().setContextProperty('testController', controller)
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.resize(600, 400)
    window.setSource(QUrl.fromLocalFile(str(source)))
    assert window.status() == QQuickView.Ready, window.errors()
    window.show()
    QTest.qWait(40)
    try:
        window.setProperty('shortcutPopupOpen', True)
        gesture(window, trackpad, QPointF(300, 200), [.5])
        assert controller.zoom == 1
        window.setProperty('shortcutPopupOpen', False)
        gesture(window, trackpad, QPointF(300, 200), [.5])
        assert controller.zoom == pytest.approx(1.5)
    finally:
        window.hide()
        delete(window)


def test_ct_pet_reference_volume_pinch_activates_volume_without_reconstruction(loaded):
    _, tab, _, requests, failures = loaded
    tab.mprLayout.setLayout('quad')
    volume = tab.mprLayout.volumeViewport
    before = tab._target_mpr_state
    request_count = len(requests)
    tool = volume.activeInteraction
    volume.pinchZoom(1.3)
    assert tab.activeViewport is volume
    assert volume.zoom == pytest.approx(1.3)
    assert volume.activeInteraction == tool
    assert tab._target_mpr_state == before
    assert len(requests) == request_count and not failures


@pytest.mark.parametrize('linked', [False, True])
def test_compare_mpr_pinch_respects_explicit_zoom_link(comparison, linked):
    from test_compare_mpr import open_pair
    app, records = comparison
    tab = open_pair(app, records)
    first, second = [g.activeViewport for g in tab.groups]
    for v in (first, second):
        v.setViewportSize(600, 400)
    tab.setLink('zoom', linked)
    QTest.qWait(50)
    before = second.zoom
    first.pinchZoom(1.5)
    QTest.qWait(50)
    assert first.zoom == pytest.approx(1.5)
    assert second.zoom == pytest.approx(before * (1.5 if linked else 1))


@pytest.mark.skipif(os.environ.get('VOXPLANE_NATIVE_QA') != '1', reason='requires native desktop window')
def test_native_rendered_reference_and_slice_pinch(loaded, trackpad, tmp_path):
    from voxplane.ui.svg_icon_provider import SvgIconProvider
    workspace, tab, provider, requests, failures = loaded
    tab.mprLayout.setLayout('quad')
    view = QQuickView()
    view.engine().addImageProvider('navigation', SvgIconProvider())
    view.engine().addImageProvider('dicom', provider)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1200, 820)
    view.setInitialProperties(dict(workspace=workspace, tabController=tab, rightPanelWidth=250))
    view.setSource(QUrl.fromLocalFile(str(ROOT / 'tests/qml/MprVoiWorkspace.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    try:
        QTest.qWait(800)
        volume = tab.mprLayout.volumeViewport
        host = volume._host
        assert host and host.frame_ready and host.backend._initialized
        before = volume.snapshot_image()
        assert before.save(str(tmp_path / 'volume-before.png'))
        geometry = tab._target_mpr_state
        count = len(requests)
        renderer = host.backend.renderer
        ratio = host.vtk_widget.devicePixelRatioF()
        display_position = (100*ratio, (host.vtk_widget.height()-100)*ratio, .5)
        renderer.SetDisplayPoint(*display_position)
        renderer.DisplayToWorld()
        landmark = renderer.GetWorldPoint()
        gesture(host.vtk_widget, trackpad, QPointF(100, 100), [.5])
        QTest.qWait(250)
        assert volume.zoom == pytest.approx(1.5)
        assert tab.activeViewport is volume
        renderer.SetWorldPoint(*landmark)
        renderer.WorldToDisplay()
        assert renderer.GetDisplayPoint()[:2] == pytest.approx(display_position[:2], abs=.02)
        after = volume.snapshot_image()
        assert after != before
        assert after.save(str(tmp_path / 'volume-after.png'))
        target = next(v for v in tab.viewports_by_id.values() if v.viewportType == 'coronal')
        pixels = next(x for x in _visual_children(view.rootObject())
                      if x.objectName() == 'dicomPixelLayer' and _owner(x) is target)
        center = pixels.mapToScene(QPointF(pixels.width()/2, pixels.height()/2))
        gesture(view, trackpad, center, [.25, .2])
        QTest.qWait(100)
        assert target.zoom == pytest.approx(1.5)
        assert tab.activeViewport is target
        assert tab._target_mpr_state == geometry and len(requests) == count
        assert view.grabWindow().save(str(tmp_path / 'mpr-after.png'))
        assert not warnings and not failures
    finally:
        view.close()
        delete(view)
        QTest.qWait(40)
