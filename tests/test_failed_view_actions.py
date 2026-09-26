"""Failed images remain inspectable tabs, with truthful export capabilities."""
import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from pydicom.uid import SecondaryCaptureImageStorage

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from test_dicom_tags import qt_app, wait_until
from test_enhanced_mr import enhanced_dataset
from test_mr import mr_dataset
from test_pacs_qml import scene
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants


@pytest.mark.parametrize("kind", ["incomplete_mr", "unsupported_color"])
def test_double_click_creates_error_tab_and_blocks_png(scene, tmp_path, monkeypatch, kind):
    window, app, warnings = scene
    if kind == "incomplete_mr":
        dataset = enhanced_dataset()
        del dataset.PerFrameFunctionalGroupsSequence[0].PlanePositionSequence
        reason = "Enhanced MR 帧信息不完整"
    else:
        dataset = mr_dataset()
        dataset.Modality = "OT"
        dataset.SOPClassUID = dataset.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
        dataset.PhotometricInterpretation = "HSV"
        dataset.SamplesPerPixel, dataset.PlanarConfiguration = 3, 0
        dataset.BitsAllocated = dataset.BitsStored = 8
        dataset.HighBit, dataset.PixelRepresentation = 7, 0
        dataset.PixelData = np.full((dataset.Rows, dataset.Columns, 3), 128, np.uint8).tobytes()
        reason = "暂不支持此彩色 DICOM 的颜色编码"
    path = tmp_path / (kind + ".dcm")
    dataset.save_as(path, enforce_file_format=True)
    scan = list(DicomFolderScanner().scan_files([path], folder=tmp_path))[-1]
    panel, workspace = app.panelController, app.workspaceController
    panel.update_series_session(scan)
    panel._update_series_record(scan)
    uid = scan.series[0].series_instance_uid
    QTest.qWait(80)
    row = find(window, "series-" + uid)
    point = row.mapToScene(QPointF(row.width() * .7, row.height() / 2)).toPoint()
    QTest.mouseDClick(window, Qt.LeftButton, pos=point)
    wait_until(lambda: workspace.activeLoadState is not None and workspace.activeLoadState.status == "error")
    tab = workspace.activeTab
    assert len(workspace.tabs) == 1
    assert workspace.tabs[0]["tabLabel"]
    assert reason in workspace.activeLoadState.errorMessage
    panel.openSeriesView(uid, "2d")
    assert workspace.activeTab is tab and len(workspace.tabs) == 1
    tab.toolController.activateTool("export")
    QTest.qWait(80)
    assert reason in find(window, "workspaceLoadingMessage").property("text")
    assert not any(i.objectName() == "retryWorkspaceLoad" for i in descendants(window.contentItem()))
    assert not find(window, "exportPng").isEnabled()
    assert find(window, "pngUnavailableReason").isVisible()
    assert not app.exportController.canExportPng
    def unexpected_dialog(*args):
        pytest.fail("A failed view must not offer a PNG save dialog")
    monkeypatch.setattr("qt_dicom_viewer.ui.controller.export_controller.QFileDialog.getSaveFileName", unexpected_dialog)
    app.exportController.exportPng(None, 1, False)
    assert app.exportController.isError and "无法导出" in app.exportController.message
    assert app.exportController.current_series()  # Source DICOM still exists.
    click(window, find(window, "cancelWorkspaceLoad"))
    assert not workspace.tabs and workspace.activeTab is None
    panel.openSeriesView(uid, "tag")
    wait_until(lambda: workspace.activeLoadState.status == "ready")
    assert workspace.activeTabType == "tag" and not app.exportController.canExportPng
    assert not warnings, warnings


def test_montage_png_tracks_visible_slice_failure_and_recovery(sidebar_scene, monkeypatch):
    window, app, records, warnings = sidebar_scene
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, "Montage", "montage")
    wait_until(lambda: app.exportController.canExportPng)
    view = workspace.activeViewport
    view._tool_controller.activateTool("export")
    QTest.qWait(50)
    button = find(window, "exportPng")
    assert button.isEnabled()
    index = next(iter(view._visible_indices))
    view._slice_model.update(index, load_state="error", error_text="Unreadable slice")
    assert not app.exportController.canExportPng
    QTest.qWait(10)
    assert not button.isEnabled()
    view._slice_model.update(index, load_state="ready", error_text="")
    QTest.qWait(10)
    assert app.exportController.canExportPng and button.isEnabled()
    assert not warnings, warnings


def test_later_slice_failure_offers_close_and_blocks_png(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    workspace = app.workspaceController
    workspace.createTab(records[0].series_instance_uid, "CT", "2d")
    wait_until(lambda: app.exportController.canExportPng)
    workspace.activeViewport._set_load_state("error", "Unreadable next slice")
    QTest.qWait(60)
    assert workspace.activeLoadState.status == "ready"  # Initial opening already finished.
    assert not app.exportController.canExportPng
    close = find(window, "closeFailedViewport")
    click(window, close)
    assert not workspace.tabs
    assert not warnings, warnings
