"""Shortcut commands, shared cursor policy and configurable transform information."""
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from qt_dicom_viewer.model import ToolType
from qt_dicom_viewer.settings.preferences import DEFAULTS, normalize_settings
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_display_tools_qml import display_panel, _find, _click
from test_measurement_qml import viewport, qt_app
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants
from test_dicom_tags import wait_until
from test_volume_panel_qml import panel, volume, loaded_tab, click as volume_click, find as volume_find


def test_scroll_shortcuts_exact_steps_and_clamped_boundaries(display_panel):
    view, controller, warnings = display_panel
    controller._state = replace(controller._state, slice_count=35, slice_index=0)
    controller.sliceChanged.emit()
    _click(view, _find(view.rootObject(), "primaryTool-scroll"))
    assert controller._tool_controller.activeInteraction == "scroll"
    for key, index in [("forward10", 10), ("forward10", 20), ("back10", 10), ("last", 34),
                       ("back10", 24), ("first", 0), ("last", 34)]:
        _click(view, _find(view.rootObject(), "scrollShortcut-" + key))
        assert controller.sliceIndex == index
    assert not _find(view.rootObject(), "scrollShortcut-forward10").isEnabled()
    assert not _find(view.rootObject(), "scrollShortcut-last").isEnabled()
    _click(view, _find(view.rootObject(), "scrollShortcut-first"))
    assert not _find(view.rootObject(), "scrollShortcut-back10").isEnabled()
    controller._state = replace(controller._state, slice_count=1, slice_index=0)
    controller.sliceChanged.emit()
    assert all(not _find(view.rootObject(), "scrollShortcut-" + key).isEnabled()
               for key in ("first", "last", "back10", "forward10"))
    assert not warnings, warnings


def test_zoom_buttons_set_absolute_fit_multiple_and_keep_transforms(display_panel, tmp_path):
    view, controller, warnings = display_panel
    controller.apply_pan(17, -12)
    controller.applyTransformAction("rotate:cw90")
    controller.applyTransformAction("rotate:mirror-h")
    _click(view, _find(view.rootObject(), "primaryTool-zoom"))
    assert controller._tool_controller.activeInteraction == "zoom"
    for factor in (2, 2, 5, 10, 1):
        button = _find(view.rootObject(), "zoomShortcut-" + str(factor))
        _click(view, button)
        assert controller.zoom == factor and button.property("checked")
        assert (controller.panX, controller.panY, controller.rotationDegrees, controller.horizontalFlip) == (17, -12, 90, True)
    controller.setZoom(float("nan"))
    assert controller.zoom == 1
    controller.apply_zoom(1.3)
    assert not _find(view.rootObject(), "zoomShortcut-1").property("checked")
    assert view.grabWindow().save(str(tmp_path / "zoom-shortcuts.png"))
    assert not warnings, warnings


@pytest.mark.parametrize("kind", ["2d", "mpr", "montage"])
def test_real_workspaces_use_shortcuts_and_preserve_other_tabs(sidebar_scene, kind):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, "Shortcuts", kind)
    wait_until(lambda: ws.activeLoadState.status in ("ready", "error"), timeout=15000)
    assert ws.activeLoadState.status == "ready", ws.activeLoadState.errorMessage
    current = ws.activeViewport
    click(window, find(window, "primaryTool-zoom"))
    click(window, find(window, "zoomShortcut-5"))
    assert current.zoom == 5
    if kind != "montage":
        click(window, find(window, "primaryTool-scroll"))
        click(window, find(window, "scrollShortcut-last"))
        # MPR publishes its displayed slice after the background reformat completes.
        wait_until(lambda: current.sliceIndex == current.sliceCount - 1)
        click(window, find(window, "scrollShortcut-first"))
        wait_until(lambda: current.sliceIndex == 0)
    else:
        current.applyTransformAction("rotate:mirror-v")
        QTest.qWait(30)
        labels = [i for i in descendants(window.contentItem()) if i.objectName() == "montageTransform-bottomRight"]
        assert not labels
        slices = [i for i in descendants(window.contentItem()) if i.objectName() == "montageSliceLabel"]
        assert slices and slices[0].property("text") == "1 / 3"
    ws.createTab(records[1].series_instance_uid, "Other", "2d")
    wait_until(lambda: ws.activeLoadState.status in ("ready", "error"), timeout=15000)
    assert ws.activeLoadState.status == "ready", ws.activeLoadState.errorMessage
    assert ws.activeViewport.zoom == 1 and current.zoom == 5
    assert not warnings, warnings


def test_volume_zoom_shortcuts_preserve_rotation_and_parameters(panel, tmp_path):
    view, controller, tools, warnings = panel
    controller.setViewFace("L")
    rotation, display = controller.state.rotation, controller.display_state
    volume_click(view, "primaryTool-zoom")
    for factor in (1, 2, 5, 10):
        volume_click(view, "zoomShortcut-" + str(factor))
        assert controller.zoom == factor
        assert controller.state.rotation == rotation and controller.display_state == display
        assert volume_find(view, "zoomShortcut-" + str(factor)).property("checked")
    controller.reset_tool_state(ToolType.ZOOM)
    assert controller.zoom == 1
    assert view.grabWindow().save(str(tmp_path / "volume-zoom.png"))
    assert not warnings, warnings


def test_transform_overlay_default_live_update_reset_and_config(viewport, tmp_path):
    view, controller, pixel_layer, warnings = viewport
    overlay = view.rootObject().findChild(QQuickItem, "overlay-bottomRight")
    assert "Rot: 0°" in overlay.property("text")
    controller.applyTransformAction("rotate:cw90")
    controller.applyTransformAction("rotate:mirror-h")
    controller.applyTransformAction("rotate:mirror-v")
    assert "Rot: 90° · Flip: HV" in overlay.property("text")
    controller.reset_tool_state(ToolType.ROTATE)
    assert "Rot: 0° · Flip: —" in overlay.property("text")
    settings = controller.settingsController
    settings.removeCornerField("bottomRight", 0)
    assert "Rot:" not in overlay.property("text")
    settings.addCornerField("topRight", "transform")
    top = view.rootObject().findChild(QQuickItem, "overlay-topRight")
    assert "Rot: 0°" in top.property("text")
    assert view.grabWindow().save(str(tmp_path / "transform-corner.png"))
    assert not warnings, warnings


def test_corner_default_migration_and_explicit_removal_survive_restart(qt_app, tmp_path):
    path = tmp_path / "display.json"
    old = deepcopy(DEFAULTS)
    old["corners"]["bottomRight"] = ["cursor"]
    path.write_text(json.dumps(old))
    settings = SettingsController(path=path)
    assert settings.values["corners"]["bottomRight"] == ["transform", "cursor"]
    assert settings.removeCornerField("bottomRight", 0)
    restored = SettingsController(path=path)
    assert restored.values["corners"]["bottomRight"] == ["cursor"]
    assert json.loads(path.read_text())["schemaVersion"] == 2
    old["corners"]["bottomRight"] = ["zoom", "cursor"]
    assert normalize_settings(old)["corners"]["bottomRight"] == ["zoom", "cursor"]


from test_pacs_qml import scene
from test_pet_fusion import paired_series
from qt_dicom_viewer.model import DicomFolderScanSnapshot


def test_pet_mpr_shortcuts_and_compact_transform_field(scene, paired_series, tmp_path):
    window, app, warnings = scene
    catalog, ct, pet = paired_series
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet]))
    ws = app.workspaceController
    ws.createTab(pet.series_instance_uid, "PET MPR", "mpr")
    wait_until(lambda: ws.activeLoadState.status in ("ready", "error"), timeout=15000)
    assert ws.activeLoadState.status == "ready", ws.activeLoadState.errorMessage
    current = ws.activeViewport
    click(window, find(window, "primaryTool-scroll"))
    click(window, find(window, "scrollShortcut-last"))
    wait_until(lambda: current.sliceIndex == current.sliceCount - 1)
    click(window, find(window, "scrollShortcut-first"))
    wait_until(lambda: current.sliceIndex == 0)
    click(window, find(window, "primaryTool-zoom"))
    click(window, find(window, "zoomShortcut-2"))
    assert current.zoom == 2
    current.applyTransformAction("rotate:mirror-h")
    QTest.qWait(50)
    texts = [i.property("text") for i in descendants(window.contentItem()) if i.objectName() == "overlay-bottomRight"]
    assert texts and any("Flip: H" in text for text in texts)
    assert not warnings, warnings


def test_four_d_shortcuts_keep_phase_and_use_active_plane(scene, tmp_path):
    from test_four_d import _cross_series_four_d
    window, app, warnings = scene
    records = _cross_series_four_d(tmp_path, phase_count=2)
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records))
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, "4D shortcuts", "4d")
    wait_until(lambda: ws.activeLoadState.status in ("ready", "error"), timeout=15000)
    assert ws.activeLoadState.status == "ready", ws.activeLoadState.errorMessage
    tab, current = ws.activeTab, ws.activeViewport
    phase = tab.currentPhaseIndex
    click(window, find(window, "primaryTool-scroll"))
    click(window, find(window, "scrollShortcut-last"))
    assert current.sliceIndex == current.sliceCount - 1 and tab.currentPhaseIndex == phase
    click(window, find(window, "primaryTool-zoom"))
    click(window, find(window, "zoomShortcut-10"))
    assert current.zoom == 10 and tab.currentPhaseIndex == phase
    assert not warnings, warnings
