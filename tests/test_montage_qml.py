from pathlib import Path

from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_montage_entry_and_center_loader_are_wired(sidebar_scene) -> None:
    window, app, records, warnings = sidebar_scene
    click(window, find(window, "series-" + records[0].series_instance_uid))
    button = find(window, "openView-montage")
    assert button.isEnabled()
    assert button.parentItem().property("tooltipText") == "平铺视图 (O)"
    click(window, button)
    assert app.workspaceController.activeTabType == "montage"
    assert find(window, "montageGrid").isVisible()
    assert not warnings, warnings


def test_montage_details_tooltip_handles_detached_anchor(sidebar_scene) -> None:
    window, app, records, warnings = sidebar_scene
    app.workspaceController.createTab(records[0].series_instance_uid, "Montage", "montage")
    button = find(window, "montageDetailsToggle")
    tooltip = next(child for child in button.children()
                   if child.inherits("QQuickToolTip") and child.objectName() != "montageDetailsToggle-hint")
    initial_text = tooltip.property("text")
    assert initial_text
    click(window, button)
    toggled_text = tooltip.property("text")
    assert toggled_text and toggled_text != initial_text

    # A Popup's visual anchor can disappear before the tooltip during a page
    # transfer. Exercise that lifecycle directly instead of relying on timing.
    detach = QQmlExpression(QQmlEngine.contextForObject(tooltip), tooltip, "parent = null")
    detach.evaluate()
    assert not detach.hasError(), detach.error().toString()
    assert tooltip.property("parent") is None
    click(window, button)
    QTest.qWait(50)
    assert not warnings, warnings
    assert not tooltip.property("visible")
    assert tooltip.property("text") == ""
    assert tooltip.setProperty("parent", button)
    assert tooltip.property("text") == initial_text
    click(window, button)
    assert tooltip.property("text") == toggled_text
    assert not warnings, warnings


def test_montage_qml_exposes_grid_controls_and_navigation() -> None:
    qml = _read(
        "src/qt_dicom_viewer/qml/sections/center/viewportArea/MontageViewport.qml"
    )

    assert "model: [2, 3, 4, 5, 6]" in qml
    assert "setVisibleRange(first, last)" in qml
    assert "openSlice(" in qml
    assert 'objectName: "montageWheelHandler"' in qml
    assert "onWheel: wheelEvent =>" in qml
    assert "montageGrid.contentY = Math.max" in qml
    assert 'tile.loadState === "error"' in qml
    for tag_label in (
        "患者姓名",
        "患者 ID / 性别 / 年龄",
        "检查 / 序列描述",
        "扫描参数",
        "采集日期 / 时间",
        "层厚",
    ):
        from qt_dicom_viewer.i18n.messages import builtin
        catalog = builtin()['messages']
        assert any(value == tag_label and f'qsTrId("{key}")' in qml for key, value in catalog.items())


def test_montage_tab_badge_is_responsive() -> None:
    tab_bar = _read(
        "src/qt_dicom_viewer/qml/sections/center/TabBarSection.qml"
    )

    assert "tabTypeLabel.implicitWidth + 12" in tab_bar
    # Pseudocolor is checked with rendered pixels in test_settings_redesign.py.


def test_montage_qml_is_in_the_compiled_resource_manifest() -> None:
    qrc = _read("Voxenra.qrc")
    assert (
        "src/qt_dicom_viewer/qml/sections/center/viewportArea/"
        "MontageViewport.qml"
    ) in qrc
