"""真实 QML 界面：占位不可执行、禁用提示可达、窄窗口文字与按钮不裁切。"""

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtTest import QTest
import pytest

from qt_dicom_viewer.model import TabType
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from test_series_sidebar import sidebar_scene
from test_dicom_tags import qt_app, wait_until
from test_tag_qml import click, descendants, find
from test_service_panel_qml import service_panel, _find, _click
from test_measurement_qml import _visual_children


@pytest.mark.parametrize("tab_type, expected", [
    (TabType.TWO_D, set()),
    (TabType.MPR, set()),
    (TabType.THREE_D, set()),
    (TabType.FOUR_D, set()),
])
def test_placeholder_catalog_is_view_specific(tab_type, expected):
    controller = ToolController(tab_type=tab_type)
    assert {item["toolType"] for item in controller.tools if not item["available"]} == expected
    assert controller.tools[-1]["toolType"] == "reset"
    state = (controller.activeTool, controller.activeInteraction, controller.activePanel)
    commands = []
    controller.commandRequested.connect(commands.append)
    for name in expected - {"annotate"}:
        controller.activateTool(name)
    assert (controller.activeTool, controller.activeInteraction, controller.activePanel) == state
    assert commands == []


@pytest.mark.parametrize("service_panel", [TabType.TWO_D, TabType.MPR, TabType.THREE_D, TabType.FOUR_D], indirect=True)
@pytest.mark.parametrize("show_labels", [False, True])
def test_toolbar_placeholders_hover_but_cannot_activate(service_panel, show_labels, tmp_path):
    view, controller, warnings = service_panel
    controller.settingsController.setValue("appearance", "toolLabels", show_labels)
    for width in [220, 250, 280]:
        view.resize(width, 580)
        QTest.qWait(80)
        state = (controller.activeTool, controller.activePanel, controller.activeInteraction)
        for definition in controller.tools:
            button = _find(view, "primaryTool-" + definition["toolType"])
            assert button.width() >= 36 and button.height() >= 36
            start = button.mapToScene(QPointF())
            end = button.mapToScene(QPointF(button.width(), button.height()))
            assert 0 <= start.x() < end.x() <= width
            assert 0 <= start.y() < end.y() <= view.height()
            label = next(item for item in _visual_children(button)
                         if item.objectName() == "toolbarLabel")
            assert label.isVisible() == show_labels, definition["toolType"]
            if show_labels:
                assert label.property("text")
                assert 0 <= label.mapToItem(button, QPointF()).y()
                assert label.mapToItem(button, QPointF(0, label.height())).y() <= button.height()
            assert button.parentItem().property("tooltipText")
            if not definition["available"]:
                assert not button.isEnabled()
                _click(view, button)
                assert (controller.activeTool, controller.activePanel, controller.activeInteraction) == state
                hover_point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
                QTest.mouseMove(view, hover_point)
                QTest.qWait(500)
                action = button.parentItem()
                assert action.property("tooltipVisible")
                assert "待实现" in action.property("tooltipText")
                QTest.mouseMove(view, QPoint(width - 2, view.height() - 2))
        assert view.grabWindow().save(str(tmp_path / f"toolbar-{controller._tab_type.value}-{width}.png"))
    assert not warnings, warnings


@pytest.mark.parametrize("tab_type", ["2d", "mpr", "tag"])
@pytest.mark.parametrize("show_labels", [False, True])
def test_full_workspace_readability(sidebar_scene, tab_type, show_labels, tmp_path):
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue("appearance", "sidebarLabels", show_labels)
    panel, workspace = app.panelController, app.workspaceController
    if tab_type == "2d":
        assert window.grabWindow().save(str(tmp_path / "workspace-empty.png"))
    click(window, find(window, "series-" + records[0].series_instance_uid))
    click(window, find(window, "openView-" + tab_type))
    wait_until(lambda: workspace.activeTabType == tab_type)
    if tab_type == "tag":
        wait_until(lambda: not workspace.activeTab.tagController.loading)
    for width, height, sidebar_width in [(1400, 760, 300), (1000, 600, 200)]:
        window.resize(width, height)
        find(window, "sidebarContainer").setProperty("expandedWidth", sidebar_width)
        QTest.mouseMove(window, QPoint(width // 2, height - 10))
        QTest.qWait(250)
        for name in ["sidebarOpenFolder", "openView-fusion", "openView-montage", "openView-3d"]:
            button = find(window, name)
            for label in descendants(button):
                if label.objectName() == "toolbarLabel":
                    assert label.isVisible() == show_labels
                    if show_labels:
                        assert label.property("text")
                        assert label.mapToItem(button, QPointF(0, label.height())).y() <= button.height()
                if label.objectName() == "toolbarGlyph":
                    assert label.width() > 0 and label.height() > 0
                    assert label.width() <= button.width()
            assert button.parentItem().property("tooltipText")
        assert find(window, "openView-fusion").isEnabled()
        assert find(window, "openView-montage").isEnabled()
        QTest.mouseMove(window, QPoint(width // 2, height - 10))
        QTest.qWait(80)
        assert window.grabWindow().save(str(tmp_path / f"workspace-{tab_type}-{width}.png"))
    assert not warnings, warnings
