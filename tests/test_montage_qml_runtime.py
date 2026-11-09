"""Exercise Montage scrolling through a real Qt wheel event."""

import os
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from qt_dicom_viewer.model import WindowLevel
from test_montage_controller import _controller


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    app = QApplication.instance() or QApplication([])
    from i18n_support import install_default_language
    install_default_language(app)
    yield app


def test_montage_grid_scrolls_on_wheel_event(qt_app, tmp_path) -> None:
    controller = _controller(320)
    controller._baseline_window = WindowLevel(center=40.0, width=400.0)
    controller._state = replace(
        controller.viewport_state,
        window=controller._baseline_window,
    )
    opened: list[tuple] = []
    controller.sliceOpenRequested.connect(
        lambda *args: opened.append(args)
    )
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 720)
    warnings: list[str] = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(
            error.toString() for error in errors
        )
    )
    view.setInitialProperties({"viewportController": controller})
    source = (
        Path(__file__).resolve().parents[1]
        / "src/qt_dicom_viewer/qml/sections/center/viewportArea/"
        / "MontageViewport.qml"
    )
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, [
        error.toString() for error in view.errors()
    ]
    view.show()
    QTest.qWait(100)

    try:
        root = view.rootObject()
        grid = root.findChild(QQuickItem, "montageGrid")
        assert grid is not None
        assert grid.property("contentHeight") > grid.height()

        first_tile_center = grid.mapToScene(
            QPointF(
                float(grid.property("cellWidth")) / 2,
                float(grid.property("cellHeight")) / 2,
            )
        )
        QTest.mouseClick(
            view,
            Qt.LeftButton,
            Qt.NoModifier,
            first_tile_center.toPoint(),
        )
        QTest.qWait(40)
        assert not opened  # Single clicks do not navigate away from the grid.
        QTest.qWait(qt_app.styleHints().mouseDoubleClickInterval() + 10)
        QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, first_tile_center.toPoint())
        QTest.qWait(40)
        assert len(opened) == 1 and opened[0][1] == 0

        before = float(grid.property("contentY"))

        local_position = grid.mapToScene(
            QPointF(grid.width() / 2, grid.height() / 2)
        )
        global_position = view.mapToGlobal(local_position.toPoint())
        event = QWheelEvent(
            local_position,
            QPointF(global_position),
            QPoint(),
            QPoint(0, -120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        QCoreApplication.sendEvent(view, event)
        QTest.qWait(80)

        assert float(grid.property("contentY")) > before
        scroll = float(grid.property("contentY"))
        header = root.findChild(QQuickItem, "montageHeader")
        height = header.height()
        controller.toggleDetails()
        QTest.qWait(60)
        assert header.height() < height
        assert abs(float(grid.property("contentY")) - scroll) <= 1
        controller.toggleDetails()
        QTest.qWait(60)
        assert abs(float(grid.property("contentY")) - scroll) <= 1
        view.resize(360, 600)
        QTest.qWait(60)
        toggle = root.findChild(QQuickItem, "montageDetailsToggle")
        assert toggle.mapToScene(QPointF(toggle.width(), 0)).x() <= 360
        assert header.height() < 240
        assert not warnings, warnings

        screenshot = view.grabWindow()
        if not screenshot.isNull():
            output = tmp_path / "montage-scroll.png"
            assert screenshot.save(str(output))
            print(f"QML preview: {output}")
    finally:
        view.hide()
        delete(view)


def test_first_tile_renders_when_bootstrap_finishes_before_grid(qt_app, tmp_path):
    from PySide6.QtCore import QTimer
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    from test_dicom_tags import wait_until
    from test_montage_controller import _result
    controller = _controller(24)
    provider = DicomImageProvider()
    requests = []
    controller.renderRequested.connect(requests.append)
    controller.imageRemovalRequested.connect(provider.remove_image)

    def deliver(request):
        result = _result(request)
        result.image.fill(180)
        if controller.accepts_result(result):
            provider.set_array(result.image_key, result.image)
            controller.handleRenderResult(result)

    controller.request_first_loader()
    deliver(requests.pop())  # Workspace loads this before QML incubation.
    assert controller._slice_model.item(0)["loadState"] == "empty"
    controller.renderRequested.connect(lambda req: QTimer.singleShot(0, lambda: deliver(req)))
    view = QQuickView()
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.engine().addImageProvider("dicom", provider)
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 720)
    view.setInitialProperties({"viewportController": controller})
    source = Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/sections/center/viewportArea/MontageViewport.qml"
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, view.errors()
    view.show()
    try:
        wait_until(lambda: controller._slice_model.item(0)["loadState"] == "ready")
        wait_until(lambda: controller._active_request is None)
        QTest.qWait(80)
        from test_tag_qml import descendants
        first = next((item for item in descendants(view.rootObject())
                      if item.objectName() == "montageSliceImage-0"), None)
        assert first is not None and first.isVisible()
        assert first.property("source").toString().startswith("image://dicom/")
        point = first.mapToScene(QPointF(first.width() / 2, first.height() / 2))
        screenshot = view.grabWindow()
        ratio = screenshot.devicePixelRatio()
        color = screenshot.pixelColor(round(point.x() * ratio), round(point.y() * ratio))
        assert color.red() == color.green() == color.blue() == 180
        assert screenshot.save(str(tmp_path / "montage-first-tile.png"))
        # A transformed image must not paint over the tile's hover frame.
        # Use real rendered pixels: hover properties alone miss this regression.
        from qt_pointer import move_pointer
        tile = first.parentItem().parentItem().parentItem()
        bounds = (tile.mapToScene(QPointF()), tile.size())
        move_pointer(view, tile.mapToScene(QPointF(tile.width() * .4, tile.height() * .4)).toPoint())

        def check_border(stage):
            QTest.qWait(40)
            image = view.grabWindow()
            assert image.save(str(tmp_path / f"montage-frame-{stage}.png"))
            sample = tile.mapToScene(QPointF(tile.width() * .65, tile.height() * .65))
            assert image.pixelColor(round(sample.x() * ratio), round(sample.y() * ratio)) == QColor(180, 180, 180)
            for fraction in (.2, .5, .8):
                edges = [QPointF(1, tile.height() * fraction),
                         QPointF(tile.width() - 2, tile.height() * fraction),
                         QPointF(tile.width() * fraction, 1),
                         QPointF(tile.width() * fraction, tile.height() - 2)]
                for local in edges:
                    p = tile.mapToScene(local)
                    x, y = round(p.x() * ratio), round(p.y() * ratio)
                    # Grid cells can have fractional heights; Qt snaps their
                    # one-pixel borders to the nearest device pixel.
                    colors = [image.pixelColor(x + dx, y + dy)
                              for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
                    assert QColor('#579fc6') in colors, (stage, local, [c.name() for c in colors])
            assert (tile.mapToScene(QPointF()), tile.size()) == bounds

        controller.setZoom(.5)
        check_border('fit')
        controller.setZoom(3)
        check_border('zoom')
        controller._tool_controller.selectInteraction('pan')
        start = tile.mapToScene(QPointF(tile.width() * .4, tile.height() * .4)).toPoint()
        end = start + QPoint(30, -20)
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
        move_pointer(view, start + QPoint(15, -10))
        QTest.qWait(20)
        move_pointer(view, end)
        QTest.qWait(20)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
        assert controller.panX != 0 and controller.panY != 0
        check_border('pan')
        controller.applyTransformAction('rotate:cw90')
        controller.applyTransformAction('rotate:mirror-h')
        check_border('rotate-flip')
        move_pointer(view, QPoint(2, 2))
        QTest.qWait(40)
        image = view.grabWindow()
        p = tile.mapToScene(QPointF(1, tile.height() / 2))
        x, y = round(p.x() * ratio), round(p.y() * ratio)
        assert all(image.pixelColor(x + dx, y + dy) != QColor('#579fc6')
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        assert not warnings, "\n".join(warnings)
    finally:
        controller.dispose()
        view.hide()
        delete(view)


@pytest.fixture
def cursor_scene(qt_app):
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    controller = _controller(320)
    controller._baseline_window = WindowLevel(center=40, width=400)
    controller._state = replace(controller.viewport_state, window=controller._baseline_window)
    view = QQuickView()
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1000, 720)
    view.setInitialProperties({"viewportController": controller})
    source = Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/sections/center/viewportArea/MontageViewport.qml"
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, view.errors()
    view.show()
    QTest.qWait(80)
    try:
        yield view, controller, warnings
    finally:
        controller.dispose()
        view.hide()
        delete(view)


@pytest.mark.parametrize("tool", ["window", "pan", "zoom"])
def test_montage_shows_one_cursor_and_restores_system_cursor_on_controls(cursor_scene, tool):
    from test_tag_qml import descendants
    view, controller, warnings = cursor_scene
    root = view.rootObject()
    grid = root.findChild(QQuickItem, "montageGrid")
    cell_width = float(grid.property("cellWidth"))
    cell_height = float(grid.property("cellHeight"))
    controller._tool_controller.selectInteraction(tool)

    def point(x, y):
        return grid.mapToScene(QPointF(x, y)).toPoint()

    def check_cursor(shape, expected_glyphs):
        QTest.qWait(25)
        glyphs = [item for item in descendants(root)
                  if item.objectName() == "montageToolCursor" and item.isVisible()]
        # Inspect the actual QWindow cursor, not just the handler's requested
        # shape: a higher MouseArea used to override BlankCursor with ArrowCursor.
        assert view.cursor().shape() == shape
        assert len(glyphs) == expected_glyphs
        if glyphs:
            assert glyphs[0].property("iconName") == tool
        return glyphs

    QTest.mouseMove(view, QPoint(2, 2))
    QTest.qWait(25)
    start = point(cell_width / 2, cell_height / 2)
    QTest.mouseMove(view, start)
    check_cursor(Qt.BlankCursor, 1)
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
    check_cursor(Qt.BlankCursor, 1)
    # Crossing into another delegate must keep one cursor, with the pointer tip
    # at the real mouse position and no clipping against an individual tile.
    end = point(cell_width * 1.5, cell_height / 2)
    QTest.mouseMove(view, end, 20)
    glyph = check_cursor(Qt.BlankCursor, 1)[0]
    assert glyph.mapToScene(QPointF(2, 2)).toPoint() == end
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
    check_cursor(Qt.BlankCursor, 1)
    for position in (point(cell_width - 4, cell_height / 2),  # Gutter
                     point(grid.width() - 5, cell_height / 2),  # Scrollbar
                     point(cell_width / 2, -25)):  # Header
        QTest.mouseMove(view, position)
        check_cursor(Qt.ArrowCursor, 0)

    controller._slice_model.update(0, load_state="error", error_text="Test load failure")
    QTest.qWait(25)
    retry = next(item for item in descendants(root) if item.objectName() == "montageClose-0")
    QTest.mouseMove(view, retry.mapToScene(QPointF(retry.width()/2, retry.height()/2)).toPoint())
    check_cursor(Qt.PointingHandCursor, 0)
    # Non-interactive panels leave the default left-window gesture available.
    QTest.mouseMove(view, point(25, 25))
    check_cursor(Qt.BlankCursor, 1)
    controller._tool_controller.activateTool("export")
    tool = "window"
    check_cursor(Qt.BlankCursor, 1)
    assert not warnings, "\n".join(warnings)
