"""通过真实 QML 指针事件验证测量链路，不需要真实患者数据。"""

import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QUrl, Qt
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.model import EditTargetKind, ImagePoint, Point
from test_viewport_transform import _controller, _render_result


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    app = QApplication.instance() or QApplication([])
    from i18n_support import install_default_language
    install_default_language(app)
    yield app


@pytest.fixture
def viewport(qt_app):
    controller = _controller()
    original = _render_result(controller)
    pixels = np.add.outer(np.arange(256), np.arange(256)).astype(np.float32) - 100
    result = replace(original, image=np.clip(pixels + 70, 0, 255).astype(np.uint8),
                     modality_pixel=pixels, frame_meta=replace(original.frame_meta,
                     instance_meta=replace(original.frame_meta.instance_meta, rows=256, columns=256),
                     geometry=replace(original.frame_meta.geometry, rows=256, columns=256)))
    controller.handleRenderResult(result)
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 720)
    provider = DicomImageProvider()
    provider.set_array(controller.viewport_config.viewport_id, result.image)
    view.engine().addImageProvider("dicom", provider)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    view.setInitialProperties({"viewportController": controller, "hasTabs": True})
    source = Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/sections/center/viewportArea/Viewport.qml"
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, [error.toString() for error in view.errors()]
    view.show()
    view.requestActivate()
    assert QTest.qWaitForWindowActive(view)
    QTest.qWait(80)
    root = view.rootObject()
    pixel_layer = root.findChild(QQuickItem, "dicomPixelLayer")
    assert pixel_layer is not None
    try:
        yield view, controller, pixel_layer, warnings
    finally:
        controller.shutdown()
        view.hide()
        delete(view)  # 保持控制器活到 QML 销毁之后，避免退出时空绑定。


def _scene(pixel_layer, column, row):
    return pixel_layer.mapToScene(QPointF(column + .5, row + .5)).toPoint()


def _visual_children(item):
    # Repeater 委托的 QObject 所属关系与视觉父子关系不同。
    for child in item.childItems():
        yield child
        yield from _visual_children(child)


def _mouse_drag(view, start, end):
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(view, (start + end) / 2, 20)
    QTest.mouseMove(view, end, 20)
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(40)


@pytest.mark.parametrize("kind", ["rect", "ellipse"])
def test_real_drag_renders_roi_metrics_and_keeps_card_upright(viewport, tmp_path, kind):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    start, end = _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95)
    _mouse_drag(view, start, end)
    items = controller.measurementController.measurementItems
    assert len(items) == 1
    assert items[0]["type"] == kind
    assert items[0]["metrics"]["pixel_count"] > 0
    cards = [item for item in _visual_children(view.rootObject())
             if item.objectName() == "roiMetricCard" and item.isVisible()]
    assert len(cards) == 1
    card = cards[0]
    # Font metrics differ across native platforms; the card grows to fit them.
    card_width = card.width()
    assert card_width >= 238
    assert card.height() > 100
    before_width = card.mapToScene(QPointF(card.width(), 0)) - card.mapToScene(QPointF(0, 0))
    controller.applyTransformAction("rotate:cw90")
    controller.applyTransformAction("rotate:mirror-h")
    controller.apply_zoom(1.3)
    QTest.qWait(80)
    after_width = card.mapToScene(QPointF(card.width(), 0)) - card.mapToScene(QPointF(0, 0))
    assert before_width == after_width == QPointF(card_width, 0)
    assert not warnings, warnings
    screenshot = view.grabWindow()
    if not screenshot.isNull():
        output = tmp_path / f"{kind}-measurement.png"
        assert screenshot.save(str(output))
        print(f"QML preview: {output}")


@pytest.mark.parametrize("kind", ["rect", "ellipse"])
@pytest.mark.parametrize("font_size, precision", [(13, 2), (18, 4), (13, 0)])
def test_roi_card_width_and_columns_stay_stable_during_draw_and_resize(
        viewport, kind, font_size, precision):
    view, controller, pixel_layer, warnings = viewport
    controller.settingsController.setValue("measurement", "fontSize", font_size)
    controller.settingsController.setValue("measurement", "decimalPlaces", precision)
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    start = _scene(pixel_layer, 30, 35)

    def snapshot():
        card = next(item for item in _visual_children(view.rootObject())
                    if item.objectName() == "roiMetricCard" and item.isVisible())
        columns = [item for item in _visual_children(card)
                   if item.objectName().startswith("roiGeometry-")]
        return (card.width(), tuple((item.x(), item.width()) for item in columns),
                tuple(item.property("text") for item in columns))

    def drag_samples(origin, points):
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, origin)
        samples = []
        for point in points:
            QTest.mouseMove(view, point, 20)
            QTest.qWait(30)
            samples.append(snapshot())
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, points[-1])
        QTest.qWait(40)
        samples.append(snapshot())
        return samples

    # Cross integer digit boundaries in both directions, not just image transforms.
    points = [_scene(pixel_layer, column, row) for column, row in
              [(39, 44), (40, 45), (129, 100), (131, 140), (95, 95)]]
    samples = drag_samples(start, points)
    assert len({sample[2] for sample in samples}) > 2  # Metrics remain live.
    expected_width, expected_columns, _ = samples[0]
    for width, columns, _ in samples:
        assert width == pytest.approx(expected_width)
        assert np.array(columns) == pytest.approx(np.array(expected_columns))

    # Editing recreates the draft/card delegate; it must use the same reservation.
    samples = drag_samples(points[-1], [
        _scene(pixel_layer, 131, 140), _scene(pixel_layer, 40, 45),
        _scene(pixel_layer, 95, 95),
    ])
    for width, columns, _ in samples:
        assert width == pytest.approx(expected_width)
        assert np.array(columns) == pytest.approx(np.array(expected_columns))
    assert not warnings, warnings


def test_real_three_click_angle_and_keyboard_cancel_delete(viewport, tmp_path):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction("measure:angle")
    for column, row in [(30, 50), (100, 50), (100, 140)]:
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(pixel_layer, column, row))
        QTest.qWait(20)
    items = controller.measurementController.measurementItems
    assert len(items) == 1
    assert items[0]["label"] == "90.00°"
    screenshot = view.grabWindow()
    if not screenshot.isNull():
        output = tmp_path / "angle-measurement.png"
        assert screenshot.save(str(output))
        print(f"QML preview: {output}")
    QTest.keyClick(view, Qt.Key_Delete)
    assert controller.measurementController.measurementItems == []
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(pixel_layer, 150, 180))
    assert controller.measurementController.has_active_transaction
    QTest.keyClick(view, Qt.Key_Escape)
    assert not controller.measurementController.has_active_transaction
    assert not warnings, warnings


def test_real_two_drag_angle_and_vertex_edit(viewport):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction("measure:angle")
    _mouse_drag(view, _scene(pixel_layer, 30, 50), _scene(pixel_layer, 100, 50))
    assert controller.measurementController.measurementItems == []
    assert "终点" in controller.measurementController.instruction
    _mouse_drag(view, _scene(pixel_layer, 100, 50), _scene(pixel_layer, 100, 140))
    original = controller.measurementController.measurementItems[0]
    assert original["label"] == "90.00°"
    _mouse_drag(view, _scene(pixel_layer, 100, 50), _scene(pixel_layer, 125, 65))
    edited = controller.measurementController.measurementItems[0]
    assert edited["measurementId"] == original["measurementId"]
    assert edited["points"][0] == original["points"][0]
    assert edited["points"][2] == original["points"][2]
    assert edited["points"][1]["column"] == pytest.approx(125, abs=.5)
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["rect", "ellipse"])
@pytest.mark.parametrize("transformed", [False, True])
def test_real_roi_corner_resize_and_outline_move(viewport, kind, transformed):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    if transformed:
        controller.applyTransformAction("rotate:cw90")
        controller.applyTransformAction("rotate:mirror-h")
        controller.apply_zoom(1.1)
        QTest.qWait(40)
    _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
    original = controller.measurementController.measurementItems[0]
    _mouse_drag(view, _scene(pixel_layer, 95, 35), _scene(pixel_layer, 115, 25))
    resized = controller.measurementController.measurementItems[0]
    assert resized["measurementId"] == original["measurementId"]
    assert resized["metrics"]["width_mm"] == pytest.approx(85, abs=.5)
    assert resized["metrics"]["height_mm"] == pytest.approx(70, abs=.5)
    _mouse_drag(view, _scene(pixel_layer, 72.5, 95), _scene(pixel_layer, 87.5, 110))
    moved = controller.measurementController.measurementItems[0]
    assert moved["metrics"]["width_mm"] == pytest.approx(resized["metrics"]["width_mm"])
    assert moved["metrics"]["height_mm"] == pytest.approx(resized["metrics"]["height_mm"])
    assert min(p["column"] for p in moved["points"]) == pytest.approx(45, abs=.5)
    assert moved["metrics"]["mean"] > resized["metrics"]["mean"]
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["length", "angle", "rect", "ellipse"])
def test_measurement_can_start_in_canvas_outside_image(viewport, kind):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    start, end = _scene(pixel_layer, -25, 35), _scene(pixel_layer, 60, 95)
    _mouse_drag(view, start, end)
    if kind == "angle":
        _mouse_drag(view, end, _scene(pixel_layer, 30, 140))
    item = controller.measurementController.measurementItems[0]
    assert min(point["column"] for point in item["points"]) == pytest.approx(-25, abs=.5)
    if kind in ("rect", "ellipse"):
        assert item["metrics"]["pixel_count"] > 0
        assert item["metrics"]["width_mm"] == pytest.approx(85, abs=.5)
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["length", "angle", "rect", "ellipse"])
@pytest.mark.parametrize("transformed", [False, True])
def test_label_hit_moves_card_without_changing_measurement(viewport, kind, transformed):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    start = _scene(pixel_layer, 30, 35)
    end = _scene(pixel_layer, 95, 95)
    if kind == "angle":
        vertex = _scene(pixel_layer, 95, 35)
        _mouse_drag(view, start, vertex)
        _mouse_drag(view, vertex, end)
    else:
        _mouse_drag(view, start, end)
    measurement_controller = controller.measurementController
    original = measurement_controller.measurementItems[0]
    measurement_controller.clear_selection()
    if transformed:
        controller.applyTransformAction("rotate:cw90")
        controller.applyTransformAction("rotate:mirror-h")
        controller.apply_zoom(1.1)
    QTest.qWait(40)
    label_name = "roiMetricCard" if kind in ("rect", "ellipse") else "measurementLabel"
    labels = [item for item in _visual_children(view.rootObject())
              if item.objectName() == label_name and item.isVisible()]
    assert len(labels) == 1
    label = labels[0]
    label_center = label.mapToScene(QPointF(label.width() / 2, label.height() / 2)).toPoint()
    # 点击标签应选中所属测量，角度工具下也不能误建新的角度草稿。
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, label_center)
    assert measurement_controller.selectedMeasurementId == original["measurementId"]
    assert not measurement_controller.has_active_transaction
    image_position = pixel_layer.mapFromScene(QPointF(label_center))
    hit = measurement_controller.hit_test(
        ImagePoint(image_position.x() - .5, image_position.y() - .5),
        slice_index=0, endpoint_tolerance=1, line_tolerance=1,
        viewport_point=Point(label_center.x(), label_center.y()),
    )
    assert hit.target.kind == EditTargetKind.LABEL
    assert hit.target.index is None
    end = label_center + QPoint(24, 18)
    delta = pixel_layer.mapFromScene(QPointF(end)) - image_position
    targets = []
    measurement_controller.activeTransactionChanged.connect(
        lambda: targets.append(measurement_controller.activeTransaction.get("editTarget"))
    )
    _mouse_drag(view, label_center, end)
    moved = measurement_controller.measurementItems
    assert len(moved) == 1
    assert moved[0]["measurementId"] == original["measurementId"]
    assert not any(targets)  # No geometry transaction or statistical recalculation.
    assert moved[0]["points"] == original["points"]
    new_label = next(item for item in _visual_children(view.rootObject())
                     if item.objectName() == label_name and item.isVisible())
    new_center = new_label.mapToScene(QPointF(new_label.width()/2, new_label.height()/2))
    assert new_center.x() == pytest.approx(end.x(), abs=1)
    assert new_center.y() == pytest.approx(end.y(), abs=1)
    if kind in ("rect", "ellipse"):
        assert moved[0]["metrics"]["area_mm2"] == pytest.approx(original["metrics"]["area_mm2"])
    else:
        assert moved[0]["label"] == original["label"]
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["rect", "ellipse"])
def test_selected_roi_interior_drag_reports_interior_not_outline(viewport, kind):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
    measurement_controller = controller.measurementController
    original = measurement_controller.measurementItems[0]
    targets = []
    measurement_controller.activeTransactionChanged.connect(
        lambda: targets.append(measurement_controller.activeTransaction.get("editTarget"))
    )
    _mouse_drag(view, _scene(pixel_layer, 60, 65), _scene(pixel_layer, 75, 75))
    moved = measurement_controller.measurementItems
    assert len(moved) == 1
    assert moved[0]["measurementId"] == original["measurementId"]
    assert moved[0]["metrics"]["area_mm2"] == pytest.approx(original["metrics"]["area_mm2"])
    assert {target["kind"] for target in targets if target} == {"interior"}
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["rect", "ellipse"])
def test_roi_edit_updates_after_first_pixel_of_drag(viewport, kind):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
    measurement = controller.measurementController
    original = measurement.measurementItems[0]
    start = _scene(pixel_layer, 60, 65)

    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(view, start + QPoint(1, 0), 20)
    QTest.qWait(30)

    # 1 屏幕像素小于常见平台 startDragDistance；ROI 仍应立即进入编辑并刷新草稿。
    draft = measurement.activeTransaction
    assert draft["measurementId"] == original["measurementId"]
    assert draft["editTarget"]["kind"] == "interior"
    assert draft["points"] != original["points"]

    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, start + QPoint(1, 0))
    QTest.qWait(30)
    assert not measurement.has_active_transaction
    assert measurement.measurementItems[0]["points"] != original["points"]
    interaction = view.rootObject().findChild(QQuickItem, "viewportInteractionLayer")
    assert interaction.property("immediateRoiDrag") is True
    assert not warnings, warnings


def _move_pointer(view, position):
    # Qt caches the last synthetic position across recreated windows. Ensure
    # a real move is delivered even when consecutive cases use the same point.
    QTest.mouseMove(view, position + QPoint(1, 0), 1)
    QTest.mouseMove(view, position, 20)
    QTest.qWait(30)


def test_pan_and_zoom_share_pointer_tip_hotspot(viewport, tmp_path):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction("pan")
    _move_pointer(view, _scene(pixel_layer, 60, 65))
    root = view.rootObject()
    interaction = root.findChild(QQuickItem, "viewportInteractionLayer")
    assert interaction.property("customCursorActive")
    assert interaction.property("effectiveCursorShape") == Qt.BlankCursor.value
    assert view.cursor().shape() == Qt.BlankCursor
    pos = _scene(pixel_layer, 60, 65)
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(20)
    assert interaction.property("effectiveCursorShape") == Qt.BlankCursor.value
    assert view.cursor().shape() == Qt.BlankCursor
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, pos)
    assert root.findChild(QQuickItem, "viewportCursorPointer") is None
    assert view.grabWindow().save(str(tmp_path / "pan-cursor.png"))
    controller._tool_controller.selectInteraction("zoom")
    icon = root.findChild(QQuickItem, "viewportCursorOperationIcon")
    assert (icon.width(), icon.height()) == (40, 32)
    tip = icon.mapToScene(QPointF(2, 2))
    hotspot = interaction.mapToScene(interaction.property("cursorPosition"))
    assert tip == hotspot
    assert view.grabWindow().save(str(tmp_path / "cursor-preview.png"))
    assert not warnings, warnings


def test_unified_cursor_policy_has_vectors_for_every_operation_and_no_raster_badge(viewport):
    view, controller, pixel_layer, warnings = viewport
    _move_pointer(view, _scene(pixel_layer, 60, 65))
    interaction = view.rootObject().findChild(QQuickItem, "viewportInteractionLayer")
    glyph = view.rootObject().findChild(QQuickItem, "viewportCursorOperationIcon")
    # Component-level policy matrix, including targets that overlap each other.
    for tool, region, crosshair, measurement, expected in [
        ("window", "", "", "pan", "window"),
        ("zoom", "", "", "", "zoom"),
        ("scroll", "", "", "", "scroll"),
        ("pan", "", "", "", "pan"),
        ("mpr:rotate3d", "", "", "", "rotate-3d"),
        ("volume:crop", "", "", "", "volume-crop"),
        ("window", "", "center", "", "crosshair-move"),
        ("zoom", "", "verticalLine", "", "crosshair-rotate"),
        ("measure:rect", "", "", "pan", "pan"),
        ("measure:ellipse", "", "", "", "measure-ellipse"),
        ("measure:angle", "", "horizontalLine", "pan", "crosshair-rotate"),
        ("annotate:text", "", "center", "", "annotate-text"),
        ("mpr:voi", "voi", "center", "pan", "voi"),
        ("mpr:voi", "resize", "horizontalLine", "", "resize"),
        ("mpr:voi", "pan", "center", "", "pan"),
        ("mpr:segmentation", "segmentation", "verticalLine", "", "segmentation"),
        ("mpr:voi", "default", "center", "", "default"),
        ("service:mtf", "", "", "", "mtf"),
        ("service:qa", "", "", "", "window"),
        ("measure:length", "", "", "", "measure-line"),
        ("measure:angle", "", "", "", "measure-angle"),
        ("measure:rect", "", "", "", "measure-rect"),
        ("annotate:arrow", "", "", "", "annotate-arrow"),
    ]:
        interaction.setProperty("activeInteraction", tool)
        interaction.setProperty("regionCursorKind", region)
        interaction.setProperty("crosshairHoverTarget", crosshair)
        interaction.setProperty("measurementCursorKind", measurement)
        assert interaction.property("hoverCursorKind") == expected
        assert interaction.property("customCursorActive") == (expected not in ("", "default"))
        if expected not in ("", "default"):
            assert not glyph.property("sharedSource").isEmpty(), expected
    assert not any(x.objectName() in ("tintedRasterToolIcon", "rasterToolIcon") for x in _visual_children(glyph))
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["rect", "ellipse"])
@pytest.mark.parametrize("transformed", [False, True])
def test_click_unselected_roi_interior_shows_move_cursor_without_an_extra_move(viewport, kind, transformed):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
    measurement = controller.measurementController
    original = measurement.measurementItems[0]
    measurement.clear_selection()
    if transformed:
        controller.applyTransformAction("rotate:cw90")
        controller.applyTransformAction("rotate:mirror-h")
        controller.apply_zoom(1.1)
        QTest.qWait(30)
    interaction = view.rootObject().findChild(QQuickItem, "viewportInteractionLayer")
    center = _scene(pixel_layer, 60, 65)
    _move_pointer(view, center)
    assert measurement.hoverHit["kind"] == "interior"
    assert measurement.hoverCursorKind == ""
    assert interaction.property("hoverCursorKind") == "measure-" + kind
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, center)
    QTest.qWait(30)
    assert measurement.selectedMeasurementId == original["measurementId"]
    assert measurement.hoverCursorKind == "pan"
    assert interaction.property("hoverCursorKind") == "pan"
    assert interaction.property("customCursorActive") is True
    assert interaction.property("effectiveCursorShape") == Qt.BlankCursor.value
    assert view.cursor().shape() == Qt.BlankCursor
    assert measurement.measurementItems == [original]
    _move_pointer(view, _scene(pixel_layer, 30, 35))
    assert measurement.hoverHit["kind"] == "controlPoint"
    assert interaction.property("hoverCursorKind") == "measure-" + kind
    _move_pointer(view, _scene(pixel_layer, 60, 65))
    assert interaction.property("hoverCursorKind") == "pan"
    _move_pointer(view, QPoint(10, 10))
    assert measurement.hoverHit == {}
    assert interaction.property("hoverCursorKind") == "measure-" + kind
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["length", "angle", "rect", "ellipse"])
def test_selected_outline_has_move_cursor_and_crosshair_keeps_priority(viewport, kind):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    if kind == "angle":
        _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 35))
        _mouse_drag(view, _scene(pixel_layer, 95, 35), _scene(pixel_layer, 95, 95))
        hover_position = _scene(pixel_layer, 60, 35)
    elif kind == "length":
        _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 35))
        hover_position = _scene(pixel_layer, 45, 35)
    else:
        _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
        hover_position = _scene(pixel_layer, 30, 65)
    measurement = controller.measurementController
    interaction = view.rootObject().findChild(QQuickItem, "viewportInteractionLayer")
    _move_pointer(view, hover_position)
    assert measurement.hoverHit["kind"] == "outline"
    assert interaction.property("hoverCursorKind") == "pan"
    # 仅验证统一光标层的优先级，不修改实际 MPR 状态。
    interaction.setProperty("crosshairHoverTarget", "horizontalLine")
    assert interaction.property("hoverCursorKind") == "crosshair-rotate"
    interaction.setProperty("crosshairHoverTarget", "")
    measurement.clear_selection()
    assert interaction.property("hoverCursorKind") == "measure-" + ("line" if kind == "length" else kind)
    assert not warnings, warnings


def test_move_cursor_is_locked_during_drag_without_xy_sampling_and_cleared_on_tool_change(viewport):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction("measure:rect")
    _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
    interaction = view.rootObject().findChild(QQuickItem, "viewportInteractionLayer")
    start = _scene(pixel_layer, 60, 65)
    _move_pointer(view, start)
    assert interaction.property("hoverCursorKind") == "pan"
    sample_updates = []
    controller._cursor_controller.cursorInfoChanged.connect(lambda: sample_updates.append(True))
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(view, start + QPoint(40, 30), 20)
    QTest.qWait(30)
    assert interaction.property("effectiveCursorKind") == "pan"
    assert controller.measurementController.hoverHit == {}
    assert sample_updates == []
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, start + QPoint(40, 30))
    QTest.qWait(30)
    assert controller.measurementController.hoverHit["kind"] == "interior"
    assert interaction.property("hoverCursorKind") == "pan"
    controller._tool_controller.selectInteraction("window")
    assert controller.measurementController.hoverHit == {}
    assert interaction.property("hoverCursorKind") == "window"
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["length", "rect", "ellipse", "arrow", "text"])
def test_mouse_release_completes_and_selects_drawing_without_blocking_next(viewport, kind):
    view, controller, pixel_layer, warnings = viewport
    tools = controller._tool_controller
    tools.selectInteraction(("annotate:" if kind in ("arrow", "text") else "measure:") + kind)
    _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
    text = controller.textAnnotationController
    measure = controller.measurementController
    def items():
        return text.annotationItems if kind == "text" else measure.measurementItems
    assert len(items()) == 1
    assert (text.selectedAnnotationId if kind == "text" else measure.selectedMeasurementId)
    assert not text._draft_id and not measure.has_active_transaction
    first = items()[0]
    selected = text.selectedAnnotationId if kind == "text" else measure.selectedMeasurementId
    # Hover after release must not modify the completed result.
    _move_pointer(view, _scene(pixel_layer, 150, 160))
    assert items() == [first]
    _mouse_drag(view, _scene(pixel_layer, 150, 160), _scene(pixel_layer, 200, 220))
    assert len(items()) == 2
    assert {k: v for k, v in items()[0].items() if k != "selected"} == {k: v for k, v in first.items() if k != "selected"}
    assert (text.selectedAnnotationId if kind == "text" else measure.selectedMeasurementId) != selected
    assert not text._draft_id and not measure.has_active_transaction
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["voi", "segmentation"])
def test_region_creation_uses_same_composite_pointer(viewport, tmp_path, kind):
    view, controller, pixel_layer, warnings = viewport
    _move_pointer(view, _scene(pixel_layer, 60, 65))
    root = view.rootObject()
    interaction = root.findChild(QQuickItem, "viewportInteractionLayer")
    interaction.setProperty("activeInteraction", "mpr:" + kind)
    interaction.setProperty("regionCursorKind", kind)
    assert interaction.property("effectiveCursorShape") == Qt.BlankCursor.value
    assert view.cursor().shape() == Qt.BlankCursor
    icon = root.findChild(QQuickItem, "viewportCursorOperationIcon")
    assert icon.isVisible() and (icon.width(), icon.height()) == (40, 32)
    hotspot = interaction.mapToScene(interaction.property("cursorPosition"))
    assert icon.mapToScene(QPointF(2, 2)) == hotspot
    assert view.grabWindow().save(str(tmp_path / (kind + "-cursor.png")))
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['rect','ellipse','freehand'])
def test_card_has_no_shape_title_and_stays_put_when_roi_moves(viewport, kind, tmp_path):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction('measure:'+kind)
    if kind == 'freehand':
        from qt_dicom_viewer.model import MeasurementKind
        context = controller._measurement_context(3, 2, kind=MeasurementKind.FREEHAND)
        controller.measurementController.paste_points([ImagePoint(30,35), ImagePoint(95,35),
                                                       ImagePoint(95,95), ImagePoint(30,95)], context)
        QTest.qWait(40)
    else:
        _mouse_drag(view, _scene(pixel_layer, 30,35), _scene(pixel_layer,95,95))
    def card():
        return next(i for i in _visual_children(view.rootObject())
                    if i.objectName() == 'roiMetricCard' and i.isVisible())
    initial = controller.measurementController.measurementItems[0]
    assert not any(i.property('text') == initial['label'] for i in _visual_children(card()))
    position = card().mapToScene(QPointF())
    _mouse_drag(view, _scene(pixel_layer,60,65), _scene(pixel_layer,70,72))
    moved = controller.measurementController.measurementItems[0]
    assert moved['points'] != initial['points']
    assert moved['metrics']['mean'] != initial['metrics']['mean']
    current_position = card().mapToScene(QPointF())
    assert current_position.x() == pytest.approx(position.x(), abs=1)
    assert current_position.y() == pytest.approx(position.y(), abs=1)
    # Escape rolls back a card move without reverting or editing the ROI.
    before = dict(moved['labelPosition'])
    center = card().mapToScene(QPointF(card().width()/2,card().height()/2)).toPoint()
    QTest.mousePress(view,Qt.LeftButton,Qt.NoModifier,center)
    QTest.mouseMove(view,center+QPoint(-35,20),20)
    QTest.keyClick(view,Qt.Key_Escape)
    QTest.mouseRelease(view,Qt.LeftButton,Qt.NoModifier,center+QPoint(-35,20))
    assert controller.measurementController.measurementItems[0]['labelPosition'] == before
    assert controller.measurementController.measurementItems[0]['points'] == moved['points']
    assert view.grabWindow().save(str(tmp_path/f'{kind}-independent-card.png'))
    assert not warnings,warnings


@pytest.mark.parametrize('kind', ['length','rect','ellipse'])
def test_live_link_switch_moves_geometry_and_card_together_or_independently(viewport, kind):
    view, c, pixel_layer, warnings = viewport
    c._tool_controller.selectInteraction('measure:'+kind)
    _mouse_drag(view,_scene(pixel_layer,30,35),_scene(pixel_layer,95,95))
    measure = c.measurementController
    label_name = 'measurementLabel' if kind == 'length' else 'roiMetricCard'
    def label():
        return next(i for i in _visual_children(view.rootObject()) if i.objectName()==label_name and i.isVisible())
    def drag_card():
        target=label();start=target.mapToScene(QPointF(target.width()/2,target.height()/2)).toPoint()
        _mouse_drag(view,start,start+QPoint(-24,12))
    assert c.settingsController.setValue('measurement','linkLabelToShape',True)
    before=measure.measurementItems[0]
    position=label().mapToScene(QPointF())
    drag_card()
    after=measure.measurementItems[0]
    assert after['points'] != before['points']
    delta=[(b['column']-a['column'],b['row']-a['row']) for a,b in zip(before['points'],after['points'])]
    assert all(d==pytest.approx(delta[0]) for d in delta)
    assert label().mapToScene(QPointF()).x()==pytest.approx(position.x()-24,abs=1)
    assert label().mapToScene(QPointF()).y()==pytest.approx(position.y()+12,abs=1)
    assert c.settingsController.setValue('measurement','linkLabelToShape',False)
    drag_card()
    assert measure.measurementItems[0]['points']==after['points']
    if kind!='length':
        assert c.settingsController.setValue('measurement','fontSize',18)
        assert c.settingsController.setValue('measurement','cardTransparency',55)
        QTest.qWait(40)
        assert label().property('metricFontSize')==18
        assert label().property('color').alphaF()==pytest.approx(.45,abs=.005)
        assert label().opacity()==1
        geometry={str(i.objectName()):i for i in _visual_children(label()) if str(i.objectName()).startswith('roiGeometry-')}
        assert set(geometry)=={'roiGeometry-dimensions','roiGeometry-area'}
        size,area=geometry['roiGeometry-dimensions'],geometry['roiGeometry-area']
        # 尺寸行右侧堆叠：上为长宽、下为面积，两行共用右缘。
        assert area.y()>=size.y()+size.height()
        assert size.x()==pytest.approx(area.x(),abs=1)
    assert not warnings,warnings
