"""Check visible completion styling and actual antialiased pixels in Qt Quick."""
from pathlib import Path
import tomllib

import pytest
from PySide6.QtCore import QObject, QPointF, QUrl, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView, QSGRendererInterface
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer import __version__
from test_measurement_qml import qt_app, viewport, _scene, _mouse_drag, _visual_children, _move_pointer
from test_pacs_qml import scene
from test_tag_qml import find
from test_dicom_tags import wait_until

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["MeasurementItem", "LengthMeasurementItem", "AngleMeasurementItem", "RoiMeasurementItem"])
def test_measurement_delegate_survives_invalidated_model(qt_app, name):
    """Tab/model teardown may invalidate inputs before destroying the visual delegate."""
    view = QQuickView()
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    properties = dict(measurement={"type": "length", "label": "12 mm"},
                      isDraft=False, isSelected=False)
    geometry = None
    if name == "MeasurementItem":
        properties.update(coordinateMapper=None, transformState=None)
    else:
        geometry = "corners" if name == "RoiMeasurementItem" else "mappedPoints"
        properties[geometry] = [QPointF(10, 20), QPointF(30, 40)]
    view.setInitialProperties(properties)
    view.setSource(QUrl.fromLocalFile(str(ROOT / "src/qt_dicom_viewer/qml/sections/center/viewportArea/measurementLayer" / (name + ".qml"))))
    try:
        assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
        root = view.rootObject()
        for invalid in ("undefined", "null"):
            expression = QQmlExpression(QQmlEngine.contextForObject(root), root,
                                       f"measurement = {invalid};" + (f" {geometry} = {invalid};" if geometry else ""))
            expression.evaluate()
            assert not expression.hasError(), expression.error().toString()
            QTest.qWait(10)
        root.setProperty("measurement", {"type": "length", "label": "24 mm"})
        if geometry:
            root.setProperty(geometry, [QPointF(50, 60), QPointF(70, 80)])
        QTest.qWait(10)
        if name == "LengthMeasurementItem":
            assert root.property("startX") == 50
            assert root.findChild(QObject, "measurementLabel").property("text") == "24 mm"
        assert not warnings, warnings
    finally:
        delete(view)


def rendered_geometry(view, kind):
    # Each MeasurementItem has all three delegates; only the active one is visible.
    for item in _visual_children(view.rootObject()):
        if not item.isVisible():
            continue
        if kind == "text" and item.objectName().startswith("annotationArrow-"):
            return item
        if kind != "text" and item.property("dashed") is not None and item.property("measurement"):
            return item
    raise AssertionError("No visible annotation geometry")


@pytest.mark.parametrize("kind", ["length", "rect", "ellipse", "arrow", "text", "angle"])
def test_release_uses_completed_style_while_remaining_selected(viewport, tmp_path, kind):
    view, c, image_layer, warnings = viewport
    settings = c.settingsController
    settings.setValue("measurement", "editingColor", "#00ffff")
    settings.setValue("measurement", "completedColor", "#ffff00")
    settings.setValue("measurement", "editingDash", True)
    settings.setValue("measurement", "completedDash", False)
    c._tool_controller.selectInteraction(("annotate:" if kind in ("arrow", "text") else "measure:") + kind)
    if kind == "angle":
        for p in [(35, 40), (70, 105), (155, 85)]:
            QTest.mouseClick(view, Qt.LeftButton, pos=_scene(image_layer, *p))
        wait_until(lambda: bool(c.measurementController.measurementItems))
    else:
        start, end = _scene(image_layer, 35, 40), _scene(image_layer, 140, 115)
        QTest.mousePress(view, Qt.LeftButton, pos=start)
        QTest.mouseMove(view, end, 30)
        QTest.qWait(40)
        geometry = rendered_geometry(view, kind)
        if kind != "text":
            assert geometry.property("dashed")
        else:
            assert geometry.property("draftStyle")
        QTest.mouseRelease(view, Qt.LeftButton, pos=end)
        QTest.qWait(40)
    measure = c.measurementController
    text = c.textAnnotationController
    assert not measure.has_active_transaction and not text._draft_id
    assert text.selectedAnnotationId if kind == "text" else measure.selectedMeasurementId
    geometry = rendered_geometry(view, kind)
    if kind == "text":
        assert not geometry.property("draftStyle")
        # Access the real ShapePath to distinguish selected from editing.
        stem = geometry.findChild(QObject, "annotationStem")
        assert QQmlExpression(QQmlEngine.contextForObject(stem), stem, "strokeStyle === ShapePath.SolidLine").evaluate()[0] is True
    else:
        assert not geometry.property("isDraft") and geometry.property("isSelected")
        assert not geometry.property("dashed")
        if kind != "arrow":
            assert geometry.property("lineColor" if kind != "length" else "measurementColor") == QColor("#ffff00")
    _move_pointer(view, _scene(image_layer, 200, 230))
    assert not measure.has_active_transaction and not text._draft_id
    if kind != "text":
        assert measure.selectedMeasurementState == "completed"
        original = measure.measurementItems
        # Clicking even the already-selected result changes styling, not its geometry.
        QTest.mouseClick(view, Qt.LeftButton, pos=_scene(image_layer, 35, 40))
        wait_until(lambda: measure.selectedMeasurementState == "draft")
        geometry = rendered_geometry(view, kind)
        assert measure.selectedMeasurementState == "draft"
        assert geometry.property("isSelected") and not geometry.property("isDraft")
        assert geometry.property("draftStyle") and geometry.property("dashed")
        assert not measure.has_active_transaction and measure.measurementItems == original
        if kind != "arrow":
            assert geometry.property("measurementColor" if kind == "length" else "lineColor") == QColor("#00ffff")
        assert view.grabWindow().save(str(tmp_path / (kind + "-clicked-selected-draft.png")))
    if kind not in ("text", "angle"):
        # Re-entering a real edit uses the editing style; release restores completion again.
        start, end = _scene(image_layer, 35, 40), _scene(image_layer, 45, 55)
        QTest.mousePress(view, Qt.LeftButton, pos=start)
        QTest.mouseMove(view, end, 30)
        QTest.qWait(40)
        assert rendered_geometry(view, kind).property("isDraft")
        assert rendered_geometry(view, kind).property("dashed")
        QTest.mouseRelease(view, Qt.LeftButton, pos=end)
        QTest.qWait(40)
        assert not rendered_geometry(view, kind).property("dashed")
    assert view.grabWindow().save(str(tmp_path / (kind + "-completed-selected.png")))
    QTest.keyClick(view, Qt.Key_Delete)
    assert not (text.annotationItems if kind == "text" else measure.measurementItems)
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["length", "arrow", "angle", "rect", "ellipse"])
def test_thin_diagonal_and_curved_geometry_has_antialiased_pixels(qt_app, tmp_path, kind):
    name = "LengthMeasurementItem" if kind in ("length", "arrow") else "AngleMeasurementItem" if kind == "angle" else "RoiMeasurementItem"
    properties = dict(preferences={"measurement": {"lineWidth": 1.0, "completedColor": "#ffffff", "annotationColor": "#ffffff"}},
                      measurement={"type": kind, "label": ""}, isDraft=False, isSelected=False)
    if kind in ("rect", "ellipse"):
        properties.update(showMetrics=False, corners=[QPointF(50.25, 40.75), QPointF(350.5, 100.35), QPointF(305.5, 252.65), QPointF(5.25, 193.05)])
    else:
        points = [QPointF(25.35, 40.25), QPointF(365.75, 175.65)]
        if kind == "angle":
            points.insert(1, QPointF(110.75, 230.5))
        properties["mappedPoints"] = points
    view = QQuickView()
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.setColor(QColor("#000000"))
    view.resize(400, 300)
    view.setInitialProperties(properties)
    view.setSource(QUrl.fromLocalFile(str(ROOT / "src/qt_dicom_viewer/qml/sections/center/viewportArea/measurementLayer" / (name + ".qml"))))
    try:
        assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
        view.show()
        QTest.qWait(120)
        frame = view.grabWindow()
        assert not frame.isNull()
        gray = [frame.pixelColor(x, y).red() for y in range(frame.height()) for x in range(frame.width())]
        # Without edge coverage these thin strokes have only black/white staircase pixels.
        assert sum(0 < v < 255 for v in gray) > 100, (kind, view.rendererInterface().graphicsApi())
        assert len(set(gray)) > 32
        assert frame.save(str(tmp_path / (kind + "-antialias.png")))
        print("Graphics API:", view.rendererInterface().graphicsApi(), "DPR:", view.devicePixelRatio())
        assert not warnings, warnings
    finally:
        view.hide()
        delete(view)


def test_version_matches_runtime_build_and_settings_header(scene, tmp_path):
    window, app, warnings = scene
    with (ROOT / "pyproject.toml").open("rb") as f:
        project = tomllib.load(f)["project"]
    with (ROOT / "uv.lock").open("rb") as f:
        locked = next(p for p in tomllib.load(f)["package"] if p["name"] == project["name"])
    assert __version__ == project["version"] == locked["version"]
    assert app.settingsController.applicationVersion == __version__
    app.workspaceController.openSettings()
    label = find(window, "settingsApplicationVersion")
    assert label.property("text") == f"版本 {__version__}"
    assert label.isVisible()
    app.settingsController.setValue("layout", "settingsNavigationWidth", 156)
    window.resize(1000, 600)
    QTest.qWait(80)
    assert window.grabWindow().save(str(tmp_path / "settings-version.png"))
    assert not label.property("truncated"), {
        key: label.property(key) for key in
        ("width", "height", "implicitWidth", "implicitHeight", "contentWidth", "contentHeight")
    }
    assert not warnings, warnings
