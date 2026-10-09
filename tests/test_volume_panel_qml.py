"""QML menus can be verified without constructing a native VTK window."""
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl, Qt
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.core.volume_view import VolumeViewState
from test_measurement_qml import _visual_children, qt_app
from test_volume_display import loaded_tab, volume
from test_volume_edit import draw, wait_edit


@pytest.fixture
def panel(qt_app, loaded_tab, request):
    controller = loaded_tab.activeViewport
    if getattr(request, "param", "CT") == "MR":
        controller.viewport_config = replace(controller.viewport_config,
            series_meta=replace(controller.viewport_config.series_meta, modality="MR"))
        controller.reset_all_view_state()
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(250, 700)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setInitialProperties(dict(toolController=loaded_tab.toolController,
        viewportController=controller, toolVisible=True))
    path = Path(__file__).resolve().parents[1]/"src/qt_dicom_viewer/qml/sections/RightPanel.qml"
    view.setSource(QUrl.fromLocalFile(str(path)))
    assert view.status() == QQuickView.Ready, [e.toString() for e in view.errors()]
    view.show()
    QTest.qWait(60)
    try:
        yield view, controller, loaded_tab.toolController, warnings
    finally:
        view.hide()
        delete(view)


def find(view, name):
    from toolbar_navigation import reveal_primary_tool
    reveal_primary_tool(view.rootObject(), name)
    return next(item for item in _visual_children(view.rootObject())
                if item.objectName() == name and item.isVisible())


def click(view, name):
    item = find(view, name)
    if name.startswith("volumePreset-"):
        flickable = find(view, "toolDetailFlickable")
        local = item.mapToItem(flickable, QPointF(item.width()/2, item.height()/2))
        if local.y() < 0 or local.y() > flickable.height():
            maximum = max(0, flickable.property("contentHeight")-flickable.height())
            target = flickable.property("contentY")+local.y()-flickable.height()/2
            flickable.setProperty("contentY", min(maximum, max(0, target)))
            QTest.qWait(20)
    point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
    QTest.mouseClick(view, Qt.LeftButton, pos=point)
    QTest.qWait(20)


def test_direction_menu_clicks_and_rotation_update_one_badge(panel, tmp_path):
    view, controller, tools, warnings = panel
    assert find(view, "currentVolumeFace").property("text") == "A"
    click(view, "primaryTool-volume-direction")
    assert tools.activeInteraction == "volume:rotate"
    for face in "APLRSI":
        click(view, "volumeFace-"+face)
        assert controller.currentFace == face
        assert find(view, "currentVolumeFace").property("text") == face
        assert sum(find(view, "volumeFace-"+f).property("checked") for f in "APLRSI") == 1
    click(view, "volumeFace-A")
    controller.begin_drag((300, 300), (600, 600))
    controller.update_drag((550, 310))
    controller.end_drag()
    QTest.qWait(20)
    assert controller.currentFace != "A"
    assert find(view, "currentVolumeFace").property("text") == controller.currentFace
    assert find(view, "volumeFace-"+controller.currentFace).property("checked")
    click(view, "activeToolReset")
    assert controller.state == VolumeViewState()
    assert find(view, "currentVolumeFace").property("text") == "A"
    assert view.grabWindow().save(str(tmp_path/"volume-directions-panel.png"))
    assert not warnings, warnings


def test_grouped_templates_and_window_controls(panel, tmp_path):
    view, controller, tools, warnings = panel
    click(view, "primaryTool-volume-preset")
    assert tools.activeInteraction == "volume:rotate"
    labels = {item.property("text") for item in _visual_children(view.rootObject())
              if item.isVisible() and item.property("text")}
    assert {"General", "CT", "CTA"} <= labels
    for preset in (entry["presetId"] for entry in controller.volumePresets):
        click(view, "volumePreset-"+preset)
        assert controller.currentPresetId == preset
        assert find(view, "volumePreset-"+preset).property("checked")
    click(view, "volumePreset-bone")
    assert view.grabWindow().save(str(tmp_path/"volume-presets-panel.png"))
    click(view, "primaryTool-window")
    assert tools.activePanel == "window" and tools.activeInteraction == "window"
    help_buttons = [item for item in _visual_children(view.rootObject())
                    if item.isVisible() and item.property("explanation")]
    assert any("3D 调窗" in item.property("explanation") for item in help_buttons)
    assert not any(item.objectName().startswith("windowPreset-") and item.isVisible()
                   for item in _visual_children(view.rootObject()))
    assert not any(item.objectName() == "beginSaveWindowTemplate" and item.isVisible()
                   for item in _visual_children(view.rootObject()))
    assert not any(item.objectName() == "invertWindowButton" and item.isVisible()
                   for item in _visual_children(view.rootObject()))
    controller.applyWindowPreset(45, 300)
    assert (controller.windowCenter, controller.windowWidth) == (45, 300)
    click(view, "activeToolReset")
    assert not warnings, warnings


@pytest.mark.parametrize("panel", ["MR"], indirect=True)
def test_ct_templates_are_disabled_in_mr_panel(panel):
    view, controller, tools, warnings = panel
    click(view, "primaryTool-volume-preset")
    for preset in ("bone", "lung", "vessel"):
        assert not any(i.objectName() == "volumePreset-"+preset for i in _visual_children(view.rootObject()))
        controller.applyVolumePreset(preset)
        assert controller.currentPresetId == "mr-general"
    for preset in ("mr-mip", "mr-bright"):
        assert find(view, "volumePreset-"+preset).isEnabled()
        click(view, "volumePreset-"+preset)
        assert controller.currentPresetId == preset
    assert not warnings, warnings


def test_freehand_crop_actions_and_bottom_reset(panel, qt_app, tmp_path):
    view, controller, tools, warnings = panel
    click(view, "primaryTool-volume-crop")
    assert tools.activePanel == "volume-crop" and tools.activeInteraction == "volume:crop"
    assert "voi" not in {t["toolType"] for t in tools.tools}
    assert tools.activeToolLabel == "裁剪"
    button = find(view, "primaryTool-volume-crop")
    glyph = next(item for item in _visual_children(button) if item.objectName() == "toolbarGlyph")
    assert glyph.property("iconName") == "volume-crop"
    assert not any(x.objectName() == "volumeCrop-clear" for x in _visual_children(view.rootObject()))
    assert find(view, "volumeCrop-inside").isEnabled()
    assert find(view, "volumeCrop-outside").isEnabled()
    assert find(view, "volumeCrop-inside").property("checked")
    assert not find(view, "volumeCrop-outside").property("checked")
    click(view, "volumeCrop-outside")
    assert controller.cropMode == "outside"
    assert find(view, "volumeCrop-outside").property("checked")
    assert not find(view, "volumeCrop-inside").property("checked")
    assert not controller.hasCrop and not controller.editBusy
    draw(controller)
    assert not find(view, "volumeCrop-inside").isEnabled()
    assert not find(view, "volumeCrop-outside").isEnabled()
    wait_edit(qt_app, controller)
    assert view.grabWindow().save(str(tmp_path/"volume-crop-panel.png"))
    assert controller.hasCrop and not controller.selection_points
    click(view, "activeToolReset")
    assert not controller.hasCrop
    click(view, "primaryTool-pan")
    click(view, "primaryTool-volume-crop")
    assert controller.cropMode == "inside"
    draw(controller)
    wait_edit(qt_app, controller)
    assert controller.hasCrop and not controller.selection_points
    assert not warnings, warnings


@pytest.mark.parametrize("panel", ["MR"], indirect=True)
def test_bed_toggle_is_disabled_for_non_ct(panel):
    view, controller, tools, warnings = panel
    assert not find(view, "primaryTool-volume-bed").isEnabled()
    assert not warnings, warnings
