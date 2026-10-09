"""验证服务入口的真实 QML 点击、图片加载及与绘制交互的隔离。"""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl, Qt
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from test_measurement_qml import (
    _mouse_drag, _scene, _visual_children, qt_app, viewport,
)


@pytest.fixture
def service_panel(qt_app, request):
    controller = ToolController(tab_type=getattr(request, "param", TabType.TWO_D))
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(320, 640)
    warnings = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    view.setInitialProperties({
        "toolController": controller,
        "toolVisible": True,
        "viewportController": None,
    })
    source = Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/sections/RightPanel.qml"
    view.setSource(QUrl.fromLocalFile(str(source)))
    assert view.status() == QQuickView.Ready, [error.toString() for error in view.errors()]
    view.show()
    QTest.qWait(100)
    try:
        yield view, controller, warnings
    finally:
        view.hide()
        delete(view)


def _find(view, name):
    from toolbar_navigation import reveal_primary_tool
    reveal_primary_tool(view.rootObject(), name)
    return next(item for item in _visual_children(view.rootObject())
                if item.objectName() == name and item.isVisible())


def _click(view, item):
    center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, center)
    QTest.qWait(100)


def _assert_service_panel_has_only_top_aligned_buttons(view):
    panel = _find(view, "servicePanel")
    visible_texts = {item.property("text") for item in _visual_children(panel)
                     if item.isVisible() and item.property("text")}
    assert {"MTF", "FWHM"} <= visible_texts
    assert "QA" not in visible_texts
    assert _find(view, "serviceEntry-mtf").property("label") == "MTF"
    assert _find(view, "serviceEntry-qa").property("label") == "QA"
    assert not any("预留" in text or "待实现" in text or text == "服务" for text in visible_texts)
    assert not any(item.objectName() == "serviceEntryStatus"
                   for item in _visual_children(panel))
    first, second = _find(view, "serviceEntry-mtf"), _find(view, "serviceEntry-fwhm")
    assert first.mapToItem(panel, QPointF(0, 0)).y() == pytest.approx(0)
    assert second.mapToItem(panel, QPointF(0, 0)).y() == pytest.approx(0)
    assert first.width() == pytest.approx(second.width(), abs=1)
    assert second.mapToItem(panel, QPointF(0, 0)).x() == pytest.approx(first.width() + 8)


@pytest.mark.parametrize("service_panel", [None], indirect=True)
def test_expanded_tool_catalog_fits_toolbar_at_fractional_column_width(service_panel):
    view, controller, warnings = service_panel
    view.resize(264, 560)
    QTest.qWait(50)
    for button in _visual_children(view.rootObject()):
        if button.objectName().startswith("primaryTool-"):
            assert button.y()+button.height() <= button.parentItem().height()
    _click(view, _find(view, "primaryTool-service"))
    assert controller.activePanel == "service"
    assert _find(view, "serviceEntry-mtf").isEnabled()
    assert not warnings, warnings


def test_service_menu_has_no_title_or_explanation_and_only_selects_entries(service_panel, tmp_path):
    view, controller, warnings = service_panel
    commands = []
    controller.commandRequested.connect(commands.append)
    primary_service = _find(view, "primaryTool-service")
    tinted_service_icon = next(
        item for item in _visual_children(primary_service)
        if item.objectName() == "navigationSvgIcon" and item.isVisible()
    )
    assert tinted_service_icon.parentItem().property("iconColor").name() == "#b0bfcc"

    _click(view, primary_service)
    assert controller.activePanel == "service"
    # Selecting a secondary tool collapses More, so the hidden icon is no longer hovered.
    assert tinted_service_icon.parentItem().property("iconColor").name() == "#66d0ff"
    QTest.mouseMove(view, QPointF(2, view.height() - 2).toPoint())
    QTest.qWait(30)
    assert tinted_service_icon.parentItem().property("iconColor").name() == "#66d0ff"
    _assert_service_panel_has_only_top_aligned_buttons(view)

    for entry in ["mtf"]:
        button = _find(view, "serviceEntry-" + entry)
        _click(view, button)
        assert controller.activeService == "service:" + entry
        assert controller.activeInteraction == "service:" + entry
        assert button.property("checked")
        _assert_service_panel_has_only_top_aligned_buttons(view)
        other = _find(view, "serviceEntry-" + ("qa" if entry == "mtf" else "mtf"))
        assert not other.property("checked")

    qa = _find(view, "serviceEntry-qa")
    assert qa.isEnabled()
    _click(view, qa)
    assert controller.activeService == "service:qa"
    assert controller.activeInteraction == "service:qa"
    assert qa.property("checked")

    for button_name, icon_name in [("primaryTool-service", "service"),
                                    ("serviceEntry-qa", "qa")]:
        button = _find(view, button_name)
        images = [item for item in _visual_children(button)
                  if item.objectName() == "navigationSvgIcon" and item.isVisible()]
        assert len(images) == 1
        image = images[0]
        assert str(image.property("source")).find(icon_name) >= 0
        assert image.width() > 0
        assert image.parentItem().property("iconColor") == image.parentItem().property("iconColor")
    assert not warnings, warnings
    assert commands == []

    screenshot = view.grabWindow()
    assert not screenshot.isNull()
    output = tmp_path / "service-panel.png"
    assert screenshot.save(str(output))
    print(f"QML preview: {output}")


@pytest.mark.parametrize("service_panel", [TabType.MPR, TabType.THREE_D, TabType.FOUR_D, TabType.TAG], indirect=True)
def test_non_2d_toolbar_has_no_service_entry(service_panel):
    view, controller, warnings = service_panel
    assert not any(item.objectName() == "primaryTool-service"
                   for item in _visual_children(view.rootObject()))
    controller.selectService("service:mtf")
    QTest.qWait(20)
    assert not any(item.objectName() == "servicePanel"
                   for item in _visual_children(view.rootObject()))
    assert not warnings, warnings


@pytest.mark.parametrize("entry", ["qa"])
def test_automatic_qa_cancels_draft_and_does_not_draw_manual_measurements(viewport, entry):
    view, controller, pixel_layer, warnings = viewport
    tools = controller._tool_controller
    tools.activateTool("measure")
    tools.selectInteraction("measure:angle")
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, _scene(pixel_layer, 30, 30))
    assert controller.measurementController.has_active_transaction

    tools.selectService("service:" + entry)
    assert not controller.measurementController.has_active_transaction
    _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
    assert controller.measurementController.measurementItems == []
    assert not controller.measurementController.has_active_transaction
    assert tools.activeInteraction == "service:qa"
    assert not warnings, warnings

    # 切回普通测量后，原有矩形绘制功能仍可正常使用。
    tools.activateTool("measure")
    tools.selectInteraction("measure:rect")
    _mouse_drag(view, _scene(pixel_layer, 30, 35), _scene(pixel_layer, 95, 95))
    assert len(controller.measurementController.measurementItems) == 1
