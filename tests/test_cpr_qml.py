from pathlib import Path
from contextlib import contextmanager

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_cpr_controller import cpr, qt_app, draw
from test_cpr_persistence import cpr_app
from test_dicom_tags import wait_until
from test_measurement_qml import _visual_children
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider


@pytest.mark.parametrize('completion', ['enter', 'double-click', 'double-click-existing-point'])
def test_four_views_accept_real_pointer_and_keyboard_path_drawing(cpr, completion):
    view = QQuickView()
    provider = DicomImageProvider()
    cpr.imageUpdateRequested.connect(provider.set_array)
    for viewport in cpr.viewports_by_id.values():
        viewport.refresh_window_image()
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.engine().addImageProvider("dicom", provider)
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 700)
    view.setInitialProperties(dict(controller=cpr))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        "src/qt_dicom_viewer/qml/sections/center/viewportArea/CprPage.qml")))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(80)
    try:
        target = next((item for item in _visual_children(view.rootObject())
                       if item.objectName() == "cprViewport-reference-a"), None)
        assert target is not None
        original_size = target.size()
        cpr.startPath()
        QTest.qWait(20)
        assert target.size() == original_size
        for x, y in ((.35, .35), (.5, .5)):
            point = target.mapToScene(QPointF(
                target.width()*x, target.height()*y))
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
            QTest.qWait(40)
        assert len(cpr.controlPoints) == 2
        point = target.mapToScene(QPointF(target.width()*.65, target.height()*.6))
        if completion == 'enter':
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
            QTest.keyClick(view, Qt.Key_Return)
        else:
            if completion == 'double-click-existing-point':
                QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
                point += QPointF(1, 1)
            # A realistic second press can drift by a pixel. It must confirm,
            # not add a tiny terminal segment that changes the section normal.
            end = (point + QPointF(1, 1)).toPoint()
            QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
        wait_until(lambda: cpr.ready)
        assert len(cpr.paths) == 1
        assert len(cpr.current_path.control_points) == 3
        assert target.size() == original_size
        assert not cpr.focusedViewportId
        view.rootObject().setProperty("controller", None)
        QCoreApplication.processEvents()
        assert not warnings, "\n".join(warnings)
    finally:
        view.hide()
        delete(view)


@pytest.fixture
def cpr_page(cpr):
    draw(cpr)
    with displayed_cpr_page(cpr) as page:
        yield page


@contextmanager
def displayed_cpr_page(cpr):
    window = QQuickView()
    provider = DicomImageProvider()
    cpr.imageUpdateRequested.connect(provider.set_array)
    for viewport in cpr.viewports_by_id.values():
        viewport.refresh_window_image()
    warnings = []
    window.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    window.engine().addImageProvider("dicom", provider)
    window.engine().addImageProvider("navigation", SvgIconProvider())
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.resize(1000, 700)
    window.setInitialProperties(dict(controller=cpr))
    window.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        "src/qt_dicom_viewer/qml/sections/center/viewportArea/CprPage.qml")))
    assert window.status() == QQuickView.Ready
    window.show()
    QTest.qWait(80)
    try:
        yield window, cpr
    finally:
        window.rootObject().setProperty("controller", None)
        QCoreApplication.processEvents()
        window.hide()
        delete(window)
        assert not warnings, "\n".join(warnings)


def named_item(root, name):
    return next(item for item in _visual_children(root) if item.objectName() == name)


def double_click(window, item):
    point = item.mapToScene(QPointF(item.width()*.7, item.height()*.45)).toPoint()
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(50)


@pytest.mark.parametrize("role", ["reference-a", "reference-b", "curved", "cross"])
def test_cpr_double_click_focus_restore_and_wheel_without_navigation_chrome(cpr_page, role):
    window, tab = cpr_page
    item = named_item(window.rootObject(), "cprViewport-" + role)
    controller = tab.viewForRole(role)
    original_size = item.size()
    names = [child.objectName() for child in _visual_children(window.rootObject())]
    assert "sliceControl" not in names and not any(name.startswith("cprFocus-") for name in names)
    double_click(window, item)
    assert tab.focusedViewportId == controller.viewportId
    assert tab.activeViewport is controller
    assert item.width() > original_size.width() * 1.9
    QTest.qWait(500)
    double_click(window, item)
    assert not tab.focusedViewportId
    assert item.size() == original_size
    wait_until(lambda: tab.ready and not tab.busy)
    index = controller.sliceIndex
    direction = 1 if index < controller.sliceCount - 1 else -1
    point = item.mapToScene(QPointF(item.width()*.5, item.height()*.5))
    event = QWheelEvent(point, QPointF(window.mapToGlobal(point.toPoint())), QPoint(), QPoint(0, -120 * direction),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(window, event)
    wait_until(lambda: tab.ready and not tab.busy)
    assert controller.sliceIndex == index + direction
    if role in ("curved", "cross"):
        assert tab.viewForRole("curved").sliceIndex == tab.viewForRole("cross").sliceIndex
    assert not tab.focusedViewportId


def test_cpr_overlay_uses_geometry_and_window_without_repeated_patient_or_acquisition_details(cpr_page):
    window, tab = cpr_page
    for role in ("reference-a", "reference-b", "curved", "cross"):
        item = named_item(window.rootObject(), "cprViewport-" + role)
        controller = tab.viewForRole(role)
        controller.cursorController.clearPosition()
        assert named_item(item, "overlay-topRight").property("text") == ""
        assert named_item(item, "overlay-bottomRight").property("text") == ""
        window_text = named_item(item, "overlay-bottomLeft").property("text")
        assert "WW:" in window_text and "WL:" in window_text
        assert "kV:" not in window_text and "thk:" not in window_text
        top = named_item(item, "overlay-topLeft").property("text")
        if role.startswith("reference"):
            assert "Slice:" in top
        else:
            assert "Slice:" not in top  # Samples along a path are not source slices.
        controller.cursorController.updatePosition(10, 10, 125.5)
        cursor = named_item(item, "overlay-bottomRight").property("text")
        assert "125.5" in cursor and "X:" not in cursor and "Rot:" not in cursor
    curved = named_item(window.rootObject(), "cprViewport-curved")
    assert "CPR · Thin" in named_item(curved, "overlay-topLeft").property("text")
    for index in (0, 1):
        selector = named_item(window.rootObject(), "cprPlane-" + str(index))
        reference = named_item(window.rootObject(), "cprViewport-reference-" + ("a" if index == 0 else "b"))
        assert selector not in list(_visual_children(reference))
        assert selector.property("mode") == tab.referencePlanes[index]


def test_cpr_inline_plane_selection_does_not_focus_or_modify_path(cpr_page):
    window, tab = cpr_page
    original = tab.current_path
    selector = named_item(window.rootObject(), "cprPlane-0")
    point = selector.mapToScene(QPointF(selector.width()/2, selector.height()/2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    wait_until(lambda: tab.ready and not tab.busy)
    assert list(tab.referencePlanes) == ["sagittal", "coronal"]
    assert not tab.focusedViewportId
    assert tab.current_path == original
    assert selector.property("mode") == "sagittal"
    window.rootObject().setProperty("anonymousExport", True)
    assert not selector.isVisible()
    window.rootObject().setProperty("anonymousExport", False)
    assert selector.isVisible()


def test_historical_reference_shows_stored_plane_and_explicit_history_status(cpr_app):
    from test_workspace_persistence import draw_length
    _, tab, _ = cpr_app
    reference = tab.viewForRole("reference-a")
    measurement = draw_length(reference)
    source = reference._measure_controller._sources[measurement]
    with displayed_cpr_page(tab) as (window, _):
        tab.setReferencePlane(0, "coronal")
        wait_until(lambda: tab.ready and not tab.busy)
        tab.navigate_measurement(reference, source)
        wait_until(lambda: reference.historicalPlane)
        selector = named_item(window.rootObject(), "cprPlane-0")
        viewport = named_item(window.rootObject(), "cprViewport-reference-a")
        assert reference.overlayInfo["viewPosition"].startswith("Axial")
        assert viewport.property("twoDViewMode") == ""
        assert not selector.isVisible()
        assert "Axial" in named_item(viewport, "overlay-topLeft").property("text")
        status = named_item(window.rootObject(), "cprStatus-reference-a")
        assert status.property("text") == reference.historicalDescription
        reference.setSliceIndex(reference.sliceIndex + 1)
        wait_until(lambda: not reference.historicalPlane and tab.ready)
        assert selector.isVisible() and selector.property("mode") == "coronal"


def test_path_panel_buttons_and_name_field_work_without_binding_errors(cpr):
    view = QQuickView()
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(280, 1050)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setInitialProperties(dict(controller=cpr))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        "src/qt_dicom_viewer/qml/sections/right/panels/CprPanel.qml")))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(40)
    def click(name):
        item = next(item for item in _visual_children(view.rootObject()) if item.objectName() == name)
        point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
        QTest.qWait(20)
    try:
        click("cprNewPath")
        assert cpr.drawing
        fields = {item.objectName(): item for item in _visual_children(view.rootObject())}
        assert not fields['cprFinishPath'].isEnabled()
        ref = cpr.viewForRole('reference-a')
        ref.cprTap(5, 10, .4)
        assert not fields['cprFinishPath'].isEnabled()
        ref.cprTap(15, 10, .4)
        assert fields['cprFinishPath'].isEnabled()
        click('cprFinishPath')
        wait_until(lambda: cpr.ready)
        assert not cpr.drawing and not cpr.pathEditing
        click('cprEditPath')
        assert cpr.pathEditing
        click('cprEditPath')
        assert not cpr.pathEditing
        click('cprNewPath')
        click("cprCancelPath")
        assert not cpr.drawing
        draw(cpr)
        click("cprDetails")
        click("cprPathName")
        QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
        QCoreApplication.sendEvent(view, QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, "Left artery"))
        QTest.keyClick(view, Qt.Key_Return)
        assert cpr.current_path.name == "Left artery"
        assert not warnings, "\n".join(warnings)
    finally:
        view.hide()
        delete(view)


def test_panel_syncs_saved_values_when_loader_assigns_controller_late(cpr):
    draw(cpr)
    cpr.renamePath("Saved vessel")
    cpr.setParameter("angle", 35)
    cpr.setParameter("thickness", 12)
    cpr.setParameter("step", .75)
    wait_until(lambda: cpr.ready and not cpr.busy)
    view = QQuickView()
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setInitialProperties(dict(controller=None))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        "src/qt_dicom_viewer/qml/sections/right/panels/CprPanel.qml")))
    assert view.status() == QQuickView.Ready
    try:
        # ToolDetailPanel assigns its controller after Loader.onLoaded. Returning
        # from Settings must not present defaults or overwrite saved parameters.
        view.rootObject().setProperty("controller", cpr)
        QCoreApplication.processEvents()
        fields = {item.objectName(): item for item in _visual_children(view.rootObject())}
        assert fields["cprPathName"].property("text") == "Saved vessel"
        assert fields["cprParameter-angle"].property("text") == "35.0"
        assert fields["cprParameter-thickness"].property("text") == "12.0"
        assert fields["cprParameter-step"].property("text") == "0.75"
    finally:
        delete(view)
