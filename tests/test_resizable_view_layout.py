"""Actual QML interactions for bounded resizing, compact overlays and PET 3D."""
import os
from pathlib import Path
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtQuick import QQuickView
from PySide6.QtCore import QUrl
import pytest
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_pacs_qml import scene
from test_pet_fusion import paired_series, qt_app
from test_tag_qml import find, click, descendants, type_text
from test_dicom_tags import wait_until


def drag(window, name, delta):
    handle = find(window, name)
    origin = handle.mapToScene(QPointF(handle.width() / 2, 170)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, origin)
    for step in range(1, 9):
        QTest.mouseMove(window, origin + QPoint(round(delta * step / 8), 0), 10)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, origin + QPoint(delta, 0))
    QTest.qWait(50)


def load_pet(scene, paired_series, tmp_path, kind="3d"):
    window, app, warnings = scene
    catalog, ct, pet = paired_series
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet]))
    app.workspaceController.createTab(pet.series_instance_uid, "PET", kind)
    wait_until(lambda: app.workspaceController.activeLoadState.status != "loading")
    assert app.workspaceController.activeLoadState.status == "ready", app.workspaceController.activeLoadState.errorMessage
    return app.workspaceController.activeViewport


def test_right_and_settings_widths_clamp_persist_and_restore(scene, paired_series, tmp_path):
    window, app, warnings = scene
    load_pet(scene, paired_series, tmp_path, "2d")
    right = find(window, "rightPanel")
    assert right.width() == 300
    drag(window, "rightPanelResizeHandle", -200)
    assert right.width() == 420
    window.resize(1000, 600)
    QTest.qWait(60)
    assert 240 <= right.width() < 420
    assert app.settingsController.values["layout"]["rightPanelWidth"] == 420
    window.resize(1440, 900)
    QTest.qWait(60)
    assert right.width() == 420
    drag(window, "rightPanelResizeHandle", 300)
    assert right.width() == 240
    app.workspaceController.openSettings()
    wait_until(lambda: any(i.objectName() == "settingsNavigation" for i in descendants(window.contentItem())))
    navigation = find(window, "settingsNavigation")
    assert navigation.width() == 180
    drag(window, "settingsNavigationResizeHandle", 150)
    assert navigation.width() == 300
    app.workspaceController.openManual("water-qa")
    app.workspaceController.openSettings()
    QTest.qWait(100)
    assert find(window, "settingsNavigation").width() == 300
    restored = SettingsController(path=tmp_path / "display-settings.json")
    assert restored.values["layout"] == {"rightPanelCollapsed": False, "rightPanelWidth": 240, "settingsNavigationWidth": 300, "manualNavigationWidth": 260,
                                         "rememberedMprLayout": "", "rememberedFourDLayout": "", "settingsCollapsedGroups": []}
    drag(window, "settingsNavigationResizeHandle", -250)
    assert find(window, "settingsNavigation").width() == 156
    assert not warnings, warnings


def test_pet_panel_and_narrow_corner_lines(scene, paired_series, tmp_path, monkeypatch):
    from qt_dicom_viewer.ui.controller.viewport.standalone_pet_volume_controller import StandalonePetVolumeController
    monkeypatch.setattr(StandalonePetVolumeController, "ensureNativeView", lambda self: None)
    window, app, warnings = scene
    view = load_pet(scene, paired_series, tmp_path)
    wait_until(lambda: find(window, "rightPanel").isEnabled())
    click(window, find(window, "primaryTool-volume-preset"))
    QTest.qWait(70)
    type_text(window, find(window, "pet3dUpper"), "0.179")
    QTest.keyClick(window, Qt.Key_Return)
    assert view.petUpper == pytest.approx(.179)
    drag(window, "rightPanelResizeHandle", 100)
    assert find(window, "pet3dUpper").width() > 100
    load_pet(scene, paired_series, tmp_path, "mpr")
    window.resize(1000, 600)
    QTest.qWait(150)
    wait_until(lambda: len([i for i in descendants(window.contentItem())
                          if i.objectName() == "viewportMetadataOverlay"]) == 3)
    corners = [i for i in descendants(window.contentItem()) if i.objectName() == "viewportMetadataOverlay"]
    assert len(corners) == 3 and all(i.property("fontScale") == .85 for i in corners)
    text_lines = [i for i in descendants(window.contentItem()) if i.objectName() == "cornerInformationLine"]
    assert text_lines
    for line in text_lines:
        assert line.property("maximumLineCount") == 1 and line.property("lineCount") == 1
        assert line.property("font").pixelSize() == 10
    for scale in [i for i in descendants(window.contentItem()) if i.objectName() == "imageScaleBar"]:
        assert scale.property("barPixels") <= min(160, scale.width() * .25) + .001
    corner = find(window, "overlay-topRight")
    corner.setProperty("text", "Patient: " + "测试很长的患者姓名" * 8 + "\nID: " + "ABC-1234567890-" * 12)
    QTest.qWait(60)
    long_lines = [i for i in descendants(corner) if i.objectName() == "cornerInformationLine"]
    assert len(long_lines) == 2 and all(i.property("truncated") for i in long_lines)
    assert window.grabWindow().save(str(tmp_path / "pet-mpr-compact.png"))
    assert not warnings, warnings


@pytest.mark.parametrize("spacing", [.0001, .5, 2, 50, 5000])
def test_scale_fits_screen_budget_without_losing_physical_calibration(qt_app, spacing):
    view = QQuickView()
    view.setInitialProperties({"pixelsPerMm": spacing, "calibrated": True,
                               "options": {"lengthMm": 100, "enabled": True}})
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/sections/center/viewportArea/ScaleBar.qml")))
    item = view.rootObject()
    try:
        for width in (90, 240, 900):
            item.setWidth(width)
            assert 0 < item.property("lengthMm") <= 100
            assert item.property("barPixels") <= min(160, width * .25, width-32) + 1e-6
            assert item.property("barPixels") == pytest.approx(item.property("lengthMm") * spacing)
        item.setProperty("calibrated", False)
        assert not item.isVisible()
    finally:
        from shiboken6 import delete
        delete(view)


@pytest.mark.skipif(os.environ.get("VOXENRA_NATIVE_QA") != "1", reason="Requires a native desktop OpenGL window")
@pytest.mark.parametrize("kind", ["ct", "pet", "fusion"])
def test_native_volume_sidebar_drag_and_png(scene, paired_series, tmp_path, kind, monkeypatch):
    window, app, warnings = scene
    catalog, ct, pet = paired_series
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet]))
    workspace = app.workspaceController
    if kind == "fusion":
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        wait_until(lambda: workspace.activeLoadState.status == "ready")
        workspace.activeTab.openVolumeView()
    else:
        record = pet if kind == "pet" else ct
        workspace.createTab(record.series_instance_uid, kind, "3d")
    wait_until(lambda: workspace.activeLoadState.status == "ready")
    view = workspace.activeViewport
    wait_until(lambda: view._host is not None and view._host.isVisible())
    from qt_dicom_viewer.ui.cursors import tool_cursor
    tools = workspace.activeTab.toolController
    available = {definition["toolType"] for definition in tools.tools}
    for tool, cursor_kind in (("pan", "pan"), ("zoom", "zoom"), ("volume-rotate", "rotate-3d"),
                              ("volume-crop", "volume-crop"), ("window", "window")):
        if tool not in available:
            continue
        tools.activateTool(tool)
        widget = view._host.vtk_widget
        expected = tool_cursor(cursor_kind, widget.devicePixelRatioF())
        for pressed in (False, True):
            if pressed:
                QTest.mousePress(widget, Qt.LeftButton, pos=QPoint(30, 30))
            actual = widget.cursor()
            assert actual.shape() == Qt.BitmapCursor
            assert actual.hotSpot() == QPoint(2, 2)
            assert actual.pixmap().toImage() == expected.pixmap().toImage()
        QTest.mouseRelease(widget, Qt.LeftButton, pos=QPoint(30, 30))
    if kind != "pet":
        tools.activateTool("window")
        assert not any(i.objectName() == "invertWindowButton" and i.isVisible()
                       for i in descendants(window.contentItem()))
    tools.activateTool("zoom")
    click(window, find(window, "zoomShortcut-5"))
    assert view.zoom == 5
    click(window, find(window, "zoomShortcut-1"))
    assert view.zoom == 1
    view.setViewFace("L")
    original = view.snapshot_image()
    backend = view._host.backend
    assert backend.marker.GetEnabled()
    actors = backend.renderer.GetViewProps()
    assert not any(actors.GetItemAsObject(i).IsA("vtkTextActor") for i in range(actors.GetNumberOfItems()))
    app.settingsController.setValue("corners", "enabled", False)
    assert original == view.snapshot_image()
    app.settingsController.setValue("corners", "enabled", True)
    assert original == view.snapshot_image()
    assert original.save(str(tmp_path / (kind + "-3d-no-corner-text.png")))
    from PySide6.QtGui import QImage
    target = tmp_path / (kind + "-3d-anonymous-export.png")
    monkeypatch.setattr("qt_dicom_viewer.ui.controller.export_controller.QFileDialog.getSaveFileName",
                        lambda *args: (str(target), "PNG"))
    app.exportController.exportPng(None, window.devicePixelRatio())
    wait_until(lambda: not app.exportController.busy)
    assert not app.exportController.isError, app.exportController.message
    exported = QImage(str(target))
    assert not exported.textKeys()
    assert exported.convertToFormat(QImage.Format_RGB888) == original.convertToFormat(QImage.Format_RGB888)
    view.setViewFace("A")
    tools.activateTool("volume-rotate")
    sidebar = find(window, "sidebarContainer")
    click(window, find(window, "sidebarToggle"))
    QTest.qWait(150)
    toggle = find(window, "sidebarToggle")
    assert sidebar.width() == 52
    button_right = toggle.mapToScene(QPointF(toggle.width(), 0)).x()
    container = next(i for i in descendants(window.contentItem()) if i.metaObject().className().startswith("QQuickWindowContainer"))
    assert button_right < container.mapToScene(QPointF()).x()
    # WindowContainer geometry is queued separately from the QML layout.
    # Wait for the actual native child to leave the button's hit area.
    button_global = window.mapToGlobal(toggle.mapToScene(QPointF(toggle.width(), 0)).toPoint())
    wait_until(lambda: view._host.mapToGlobal(QPoint()).x() > button_global.x())
    window.requestActivate()
    wait_until(window.isActive)
    click(window, toggle)
    assert sidebar.width() == 300
    drag(window, "rightPanelResizeHandle", -120)
    click(window, find(window, "sidebarToggle"))
    QTest.qWait(250)
    assert view.loadState == "ready", view.errorMessage
    # The menu must be a window above VTK, and the click must reach its action.
    from PySide6.QtGui import QGuiApplication
    from test_series_sidebar import right_click
    right_click(window, find(window, "compactSeries-" + ct.series_instance_uid))
    def visible_popup():
        return next((w for w in QGuiApplication.topLevelWindows()
                     if w.isVisible() and w.metaObject().className() == "QQuickPopupWindow"), None)
    wait_until(lambda: visible_popup() is not None)
    popup = visible_popup()
    action = find(popup, "seriesContextAction-remove")
    assert action.isVisible() and popup is not window
    click(popup, action)
    assert app.panelController.compactSidebarModel.rowCount() == 1
    assert view._host.isVisible() and view.loadState == "ready"
    assert ct.first_file.exists()
    if kind == "pet":
        before = view.snapshot_image()
        workspace.activeTab.toolController.activateTool("volume-crop")
        view.begin_drag((0, 0), (640, 480))
        for point in ((320, 0), (320, 480), (0, 480)):
            view.update_drag(point)
        view.end_drag()
        wait_until(lambda: not view.editBusy)
        assert view.hasCrop
        cropped = view.snapshot_image()
        assert before.bits().tobytes() != cropped.bits().tobytes()
        mask, state = view.visible_mask, view.state
        view.setPetUnit("kbqml")
        wait_until(lambda: workspace.activeLoadState.status == "ready")
        wait_until(lambda: view._host.isVisible())
        assert view.visible_mask is mask and view.state == state
        assert view.snapshot_image().save(str(tmp_path / "pet-cropped-unit.png"))
        assert view._host.backend.mapper.GetMaskInput() is not None
        view.reset_all_view_state()
        wait_until(lambda: workspace.activeLoadState.status == "ready")
        wait_until(lambda: view._host.isVisible())
        assert not view.hasCrop and view.petUnitId == "suvbw"
    assert view.snapshot_image().save(str(tmp_path / (kind + "-3d.png")))
    assert window.grabWindow().save(str(tmp_path / (kind + "-sidebar.png")))
    assert not warnings, warnings
