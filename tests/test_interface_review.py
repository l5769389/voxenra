"""真实 QML 界面：窄窗口文字、按钮与工具提示的布局契约。"""

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtTest import QTest
import pytest

from voxplane.model import TabType
from test_series_sidebar import sidebar_scene
from test_dicom_tags import qt_app, wait_until
from test_tag_qml import click, descendants, find
from test_service_panel_qml import service_panel, _find
from test_measurement_qml import _visual_children


@pytest.mark.parametrize("service_panel", [TabType.TWO_D, TabType.MPR, TabType.THREE_D, TabType.FOUR_D], indirect=True)
@pytest.mark.parametrize("show_labels", [False, True])
def test_toolbar_buttons_and_labels_fit_narrow_panels(service_panel, show_labels, tmp_path):
    view, controller, warnings = service_panel
    controller.settingsController.setValue("appearance", "toolLabels", show_labels)
    for width in [220, 250, 280]:
        view.resize(width, 580)
        QTest.qWait(80)
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
