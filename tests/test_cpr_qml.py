from pathlib import Path

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QUrl, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_cpr_controller import cpr, qt_app, draw
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
        view.rootObject().setProperty("controller", None)
        QCoreApplication.processEvents()
        assert not warnings, "\n".join(warnings)
    finally:
        view.hide()
        delete(view)


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
