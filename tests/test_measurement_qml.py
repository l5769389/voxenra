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

from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.model import EditTargetKind, ImagePoint, Point
from test_dicom_tags import wait_until
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
    from voxplane.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 720)
    provider = DicomImageProvider()
    provider.set_array(controller.viewport_config.viewport_id, result.image)
    view.engine().addImageProvider("dicom", provider)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    view.setInitialProperties({"viewportController": controller, "hasTabs": True})
    source = Path(__file__).resolve().parents[1] / "src/voxplane/qml/sections/center/viewportArea/Viewport.qml"
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


def _click_points(view, *points):
    for point in points:
        QTest.mouseClick(view, Qt.LeftButton, pos=point)
    QTest.qWait(40)


def test_roi_details_follow_selection_and_release_space_for_next_drawing(viewport):
    view, controller, pixels, warnings = viewport
    measure = controller.measurementController
    controller._tool_controller.selectInteraction('measure:rect')
    _click_points(view, _scene(pixels, 30, 35), _scene(pixels, 70, 75))
    first = measure.measurementItems[0]['measurementId']
    measure.clear_selection()
    controller._tool_controller.selectInteraction('measure:ellipse')
    _click_points(view, _scene(pixels, 90, 50), _scene(pixels, 130, 90))
    assert len(measure.measurementItems) == 2

    def visible(name):
        return [i for i in _visual_children(view.rootObject())
                if i.objectName() == name and i.isVisible()]

    assert len(visible('roiMetricCard')) == 1
    badges = visible('roiCompactLabel')
    assert len(badges) == 1
    assert 'ROI 1' in badges[0].property('text') and 'mm²' in badges[0].property('text')
    # Selecting the compact label expands its details without changing geometry.
    original = [i['points'] for i in measure.measurementItems]
    badge = badges[0]
    _click_points(view, badge.mapToScene(QPointF(badge.width()/2, badge.height()/2)).toPoint())
    assert measure.selectedMeasurementId == first
    assert len(visible('roiMetricCard')) == 1 and len(visible('roiCompactLabel')) == 1
    assert [i['points'] for i in measure.measurementItems] == original
    from PySide6.QtCore import QRectF
    card = visible('roiMetricCard')[0]
    card_bounds = QRectF(card.mapToScene(QPointF()), card.size())
    neighbor = QRectF(_scene(pixels, 90, 50), _scene(pixels, 130, 90))
    assert not card_bounds.intersects(neighbor)
    # Clear selection and place a point in space formerly occupied by the card.
    card = visible('roiMetricCard')[0]
    released_space = card.mapToScene(QPointF(card.width()/2, card.height()-15)).toPoint()
    measure.clear_selection()
    QTest.qWait(30)
    assert not visible('roiMetricCard') and len(visible('roiCompactLabel')) == 2
    _click_points(view, released_space)
    assert measure.activeTransaction.get('creating')
    assert len(measure.activeTransaction['points']) == 2
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["rect", "ellipse"])
def test_real_point_placement_renders_roi_metrics_and_keeps_card_upright(viewport, tmp_path, kind):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction(f"measure:{kind}")
    start, end = _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95)
    _click_points(view, start, end)
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
@pytest.mark.parametrize("font_size, precision", [(13, 2), (18, 3), (13, 0)])
def test_roi_card_width_and_columns_stay_stable_during_draw_and_resize(
        viewport, kind, font_size, precision):
    view, controller, pixel_layer, warnings = viewport
    controller.settingsController.setValue("measurement", "fontSize", font_size)
    assert controller.settingsController.setValue("measurement", "decimalPlaces", precision)
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

    _click_points(view, points[-1])
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
    wait_until(lambda: bool(controller.measurementController.measurementItems))
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
    wait_until(lambda: controller.measurementController.has_active_transaction)
    QTest.keyClick(view, Qt.Key_Escape)
    assert not controller.measurementController.has_active_transaction
    assert not warnings, warnings


def test_real_three_press_angle_and_vertex_drag_edit(viewport):
    view, controller, pixel_layer, warnings = viewport
    controller._tool_controller.selectInteraction("measure:angle")
    _click_points(view, _scene(pixel_layer, 30, 50), _scene(pixel_layer, 100, 50))
    assert controller.measurementController.measurementItems == []
    assert "终点" in controller.measurementController.instruction
    _click_points(view, _scene(pixel_layer, 100, 140))
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
    _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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
    _click_points(view, start, end)
    if kind == "angle":
        _click_points(view, _scene(pixel_layer, 30, 140))
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
        _click_points(view, start, vertex, end)
    else:
        _click_points(view, start, end)
    measurement_controller = controller.measurementController
    original = measurement_controller.measurementItems[0]
    measurement_controller.clear_selection()
    if transformed:
        controller.applyTransformAction("rotate:cw90")
        controller.applyTransformAction("rotate:mirror-h")
        controller.apply_zoom(1.1)
    QTest.qWait(40)
    label_name = "roiCompactLabel" if kind in ("rect", "ellipse") else "measurementLabel"
    labels = [item for item in _visual_children(view.rootObject())
              if item.objectName() == label_name and item.isVisible()]
    assert len(labels) == 1
    label = labels[0]
    label_center = label.mapToScene(QPointF(label.width() / 2, label.height() / 2)).toPoint()
    # Hit-test the badge before selection replaces it with a larger card that
    # may move to avoid the ROI or viewport metadata.
    image_position = pixel_layer.mapFromScene(QPointF(label_center))
    hit = measurement_controller.hit_test(
        ImagePoint(image_position.x() - .5, image_position.y() - .5),
        slice_index=0, endpoint_tolerance=1, line_tolerance=1,
        viewport_point=Point(label_center.x(), label_center.y()),
    )
    assert hit.target.kind == EditTargetKind.LABEL
    assert hit.target.index is None
    # 点击标签应选中所属测量，角度工具下也不能误建新的角度草稿。
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, label_center)
    wait_until(lambda: measurement_controller.selectedMeasurementId == original["measurementId"])
    assert not measurement_controller.has_active_transaction
    if kind in ("rect", "ellipse"):
        # Selection expands the compact badge. Drag the now-visible card.
        QTest.qWait(30)
        label_name = 'roiMetricCard'
        label = next(item for item in _visual_children(view.rootObject())
                     if item.objectName() == 'roiMetricCard' and item.isVisible())
        label_center = label.mapToScene(QPointF(label.width()/2, label.height()/2)).toPoint()
        image_position = pixel_layer.mapFromScene(QPointF(label_center))
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
    _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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
    _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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
    _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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
        _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 35), _scene(pixel_layer, 95, 95))
        hover_position = _scene(pixel_layer, 60, 35)
    elif kind == "length":
        _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 35))
        hover_position = _scene(pixel_layer, 45, 35)
    else:
        _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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
    _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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
def test_final_press_completes_and_selects_drawing_without_blocking_next(viewport, kind):
    view, controller, pixel_layer, warnings = viewport
    tools = controller._tool_controller
    tools.selectInteraction(("annotate:" if kind in ("arrow", "text") else "measure:") + kind)
    _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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
    _click_points(view, _scene(pixel_layer, 150, 160), _scene(pixel_layer, 200, 220))
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
        from voxplane.model import MeasurementKind
        context = controller._measurement_context(3, 2, kind=MeasurementKind.FREEHAND)
        controller.measurementController.paste_points([ImagePoint(30,35), ImagePoint(95,35),
                                                       ImagePoint(95,95), ImagePoint(30,95)], context)
        QTest.qWait(40)
    else:
        _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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
    _click_points(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
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


def test_double_click_cannot_cancel_the_committed_third_angle_point(viewport):
    view, controller, layer, warnings = viewport
    controller._tool_controller.selectInteraction("measure:angle")
    _click_points(view, _scene(layer, 30, 50), _scene(layer, 100, 50))
    QTest.mouseDClick(view, Qt.LeftButton, pos=_scene(layer, 100, 140))
    assert len(controller.measurementController.committed_measurements) == 1
    assert not controller.measurementController.has_active_transaction
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['length', 'rect', 'ellipse', 'angle'])
def test_point_measurement_shows_first_click_without_double_click_delay(viewport, kind):
    window, controller, layer, warnings = viewport
    controller._tool_controller.selectInteraction('measure:' + kind)
    measure = controller.measurementController
    QTest.mouseClick(window, Qt.LeftButton, pos=_scene(layer, 30, 40))
    assert measure.activeTransaction['points'][0] == pytest.approx({'column': 30, 'row': 40}, abs=.3)
    QTest.mouseMove(window, _scene(layer, 90, 100), 20)
    assert measure.activeTransaction['points'][1] == pytest.approx({'column': 90, 'row': 100}, abs=.3)
    QTest.keyClick(window, Qt.Key_Escape)
    assert not measure.has_active_transaction and not measure.committed_measurements
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['length', 'rect', 'ellipse', 'angle'])
def test_duplicate_press_keeps_draft_until_valid_fixed_point(viewport, kind):
    window, controller, layer, warnings = viewport
    controller._tool_controller.selectInteraction('measure:' + kind)
    measure = controller.measurementController
    start = _scene(layer, 30, 40)
    QTest.mouseDClick(window, Qt.LeftButton, pos=start)
    assert measure.has_active_transaction and not measure.committed_measurements
    _click_points(window, _scene(layer, 100, 110))
    if kind == 'angle':
        _click_points(window, _scene(layer, 100, 40))
    assert len(measure.committed_measurements) == 1 and not measure.has_active_transaction
    assert not warnings, warnings


@pytest.mark.parametrize("tool", ["pan", "measure:rect"])
def test_switch_tools_while_mouse_is_down_keeps_cursor_with_drag(viewport, tool):
    view, controller, layer, warnings = viewport
    tools = controller._tool_controller
    interaction = view.rootObject().findChild(QQuickItem, "viewportInteractionLayer")
    tools.selectInteraction(tool)
    start = _scene(layer, 64, 64)
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(view, start + QPoint(25, 18), 20)
    tools.selectInteraction("zoom")
    # Navigation completes on release. A measurement draft is cancelled by the switch.
    expected = "pan" if tool == "pan" else "zoom"
    try:
        assert interaction.property("effectiveCursorKind") == expected
        pan = controller.panX
        QTest.mouseMove(view, start + QPoint(45, 30), 20)
        assert (controller.panX != pan) == (tool == "pan")
    finally:
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, start + QPoint(45, 30))
    assert interaction.property("effectiveCursorKind") == "zoom"
    assert controller.zoom == 1 and not controller.measurementController.measurementItems
    assert not warnings, warnings


@pytest.mark.parametrize('tool', ['measure:length', 'measure:angle', 'measure:rect', 'measure:ellipse',
                                  'annotate:arrow', 'annotate:text'])
def test_fixed_points_confirm_on_press_and_complete_without_release(viewport, tmp_path, tool):
    window, controller, layer, warnings = viewport
    controller._tool_controller.selectInteraction(tool)
    measure = controller.measurementController
    text = controller.textAnnotationController
    coordinates = [(30, 40), (100, 40), (100, 110)] if tool == 'measure:angle' else [(30, 40), (100, 110)]
    for index, (x, y) in enumerate(coordinates):
        point = _scene(layer, x, y)
        QTest.mousePress(window, Qt.LeftButton, pos=point)
        try:
            final = index == len(coordinates) - 1
            if tool == 'annotate:text':
                assert bool(text._draft_id) is not final
                assert len(text.annotationItems) == 1
            else:
                assert measure.has_active_transaction is not final
                assert len(measure.committed_measurements) == int(final)
                if not final:
                    assert measure.activeTransaction['points'][index] == pytest.approx({'column': x, 'row': y}, abs=.3)
            # Neither moving while held nor releasing is allowed to confirm another point.
            QTest.mouseMove(window, point + QPoint(20, 25), 10)
        finally:
            QTest.mouseRelease(window, Qt.LeftButton, pos=point + QPoint(20, 25))
    if tool == 'annotate:text':
        item, = text.annotationItems
        assert [item['tailColumn'], item['tailRow'], item['headColumn'], item['headRow']] == pytest.approx([30, 40, 100, 110], abs=.3)
    else:
        result, = measure.committed_measurements
        np.testing.assert_allclose([(p.column, p.row) for p in result.points], coordinates, atol=.3)
    QTest.qWait(40)
    screenshot = window.grabWindow()
    if not screenshot.isNull():
        assert screenshot.save(str(tmp_path / (tool.replace(':', '-') + '-pressed.png')))
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['length','angle','rect','ellipse','curve','freehand','arrow'])
def test_completed_measurement_tracks_each_mirror_and_rotation(viewport,kind,tmp_path):
    from voxplane.model import MeasurementKind, ToolType
    view,controller,pixels,warnings=viewport
    controller._tool_controller.selectInteraction(('annotate:' if kind=='arrow' else 'measure:')+kind)
    if kind in ('curve','freehand'):
        context=controller._measurement_context(3,2,kind=MeasurementKind(kind))
        controller.measurementController.paste_points([ImagePoint(45,60),ImagePoint(105,90),ImagePoint(70,140)],context)
        QTest.qWait(40)
    else:
        _click_points(view,_scene(pixels,45,60),_scene(pixels,105,90))
        if kind=='angle': _click_points(view,_scene(pixels,150,140))
    original=controller.measurementController.measurementItems[0]
    item=next(i for i in _visual_children(view.rootObject()) if i.objectName()=='measurementItem' and not i.property('isDraft'))
    transforms=[('mirror-h',lambda:controller.applyTransformAction('rotate:mirror-h')),
                ('cw90',lambda:controller.applyTransformAction('rotate:cw90')),
                ('mirror-v',lambda:controller.applyTransformAction('rotate:mirror-v')),
                ('rotate37',lambda:controller.apply_rotation(37)),
                ('zoom',lambda:controller.apply_zoom(1.2)),
                ('pan',lambda:controller.apply_pan(20,-17)),
                ('reset-rotate',lambda:controller.reset_tool_state(ToolType.ROTATE)),
                ('mirror-again',lambda:controller.applyTransformAction('rotate:mirror-h')),
                ('reset-zoom',lambda:controller.reset_tool_state(ToolType.ZOOM)),
                ('reset-pan',lambda:controller.reset_tool_state(ToolType.PAN)),
                ('reset-transforms',lambda:controller.reset_tool_state(ToolType.ROTATE))]
    for action,apply in transforms:
        apply();QTest.qWait(40)
        item=next(i for i in _visual_children(view.rootObject()) if i.objectName()=='measurementItem' and not i.property('isDraft'))
        for prop,source in [('mappedPoints','points'),('renderPoints','renderPoints')]:
            points=item.property(prop).toVariant()
            source_points=original.get(source,original['points'])
            assert len(points)==len(source_points)
            for actual,p in zip(points,source_points):
                expected=pixels.mapToItem(item,QPointF(p['column']+.5,p['row']+.5))
                assert actual.x()==pytest.approx(expected.x(),abs=.01),(action,actual,expected)
                assert actual.y()==pytest.approx(expected.y(),abs=.01),(action,actual,expected)
        current=controller.measurementController.measurementItems[0]
        assert {k:v for k,v in current.items() if k not in ('selected','hovered')}=={k:v for k,v in original.items() if k not in ('selected','hovered')}
        label=item.property('labelItem')
        if label and label.isVisible():
            vector=label.mapToScene(QPointF(label.width(),0))-label.mapToScene(QPointF())
            assert vector==QPointF(label.width(),0)
        if action in ('mirror-h','reset-transforms'):
            assert view.grabWindow().save(str(tmp_path/f'{kind}-{action}.png'))
    # Editing after the reset must hit the displayed control point.
    before=controller.measurementController.measurementItems[0]['points']
    p=before[0]
    _mouse_drag(view,_scene(pixels,p['column'],p['row']),_scene(pixels,p['column']+8,p['row']+6))
    after=controller.measurementController.measurementItems[0]['points']
    assert any(a['column']==pytest.approx(p['column']+8,abs=.6) and a['row']==pytest.approx(p['row']+6,abs=.6) for a in after), after
    # The separate global reset intentionally clears drawing results.
    controller.reset_all_view_state(reset_slice=False);QTest.qWait(40)
    assert not controller.measurementController.measurementItems
    assert not any(i.objectName()=='measurementItem' and i.isVisible() for i in _visual_children(view.rootObject()))
    assert not warnings,warnings
