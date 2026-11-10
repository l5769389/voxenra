from dataclasses import replace

import pytest
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.compare import relative_slice, supports_compare, SYNC_OPERATIONS
from qt_dicom_viewer.core.workspace_document import read_document
from qt_dicom_viewer.model import DicomFolderScanSnapshot, WindowLevel, WindowLevelChange
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import phantom_series
from test_workspace_persistence import draw_length
from test_pet_fusion import paired_series


@pytest.fixture
def comparison(qt_app, tmp_path):
    records = [phantom_series(tmp_path, i, "DEMO", f"1.2.3.{i}", "20260914") for i in (1, 2, 3)]
    records[1] = replace(records[1], instances=records[1].instances[:2])
    records[2] = replace(records[2], instances=records[2].instances[:1])
    app = AppController(DicomImageProvider(), settings_path=tmp_path / "settings.json")
    panel = app.panelController
    snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records)
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    try:
        yield app, records
    finally:
        app.shutdown()


def open_pair(app, records):
    app.workspaceController.createCompareTab(*(r.series_instance_uid for r in records[:2]))
    tab = app.workspaceController.activeTab
    wait_until(lambda: all(v.loadState == "ready" for v in tab.viewports_by_id.values()))
    return tab, list(tab.viewports_by_id.values())


def test_pair_picker_eligibility_selection_and_independent_views(comparison):
    app, records = comparison
    panel = app.panelController
    picker = panel.compareController
    first, second, third = [r.series_instance_uid for r in records]
    assert supports_compare(records[0])
    assert not supports_compare(replace(records[0], instances=()))
    assert not supports_compare(replace(records[0], instances=(replace(records[0].instances[0], rows=0),)))
    panel.selectSeries(first)
    picker.request(first)
    assert picker.dialogOpen and not picker.canConfirm
    assert {r['seriesUid'] for r in picker.candidates} == {second, third}
    picker.selectPartner(first)
    assert not picker.canConfirm
    picker.selectPartner(second)
    picker.confirm()
    assert not picker.dialogOpen
    registry = app.workspaceController
    tab = registry.activeTab
    assert registry.activeTabType == 'compare2d'
    panel.selectSeriesWithModifiers(second, True)
    picker.request(second)
    assert registry.activeTab is tab and len(registry.tabs) == 1
    # A different context series is the anchor, even while another pair is checked.
    picker.request(third)
    assert picker.dialogOpen and picker.anchor['seriesUid'] == third
    panel.removeSeries(third)
    assert not picker.dialogOpen


@pytest.mark.parametrize('counts, expected', [((1, 9), 0), ((9, 1), 0), ((3, 11), 5), ((5, 3), 1)])
def test_relative_slice_mapping(counts, expected):
    assert relative_slice(counts[0] // 2, *counts) == expected
    assert relative_slice(-20, *counts) == 0
    assert relative_slice(999, *counts) == (counts[1] - 1 if counts[0] > 1 else 0)


def test_shared_scroll_links_both_directions_and_can_unlink(comparison):
    app, records = comparison
    tab, (left, right) = open_pair(app, records)
    assert (left.sliceCount, right.sliceCount) == (3, 2)
    assert tab.sliceCount == 3
    tab.setSliceIndex(2)
    wait_until(lambda: (left.sliceIndex, right.sliceIndex) == (2, 1))
    right.setSliceIndex(0)
    wait_until(lambda: (left.sliceIndex, right.sliceIndex) == (0, 0))
    tab.setSyncOperation('scroll', False)
    tab.activateViewport(right.viewportId)
    assert tab.sliceCount == 2
    tab.setSliceIndex(1)
    wait_until(lambda: right.sliceIndex == 1)
    assert left.sliceIndex == 0
    tab.setSyncOperation('scroll', True)
    wait_until(lambda: left.sliceIndex == 2)
    assert tab.sliceCount == 3
    # Single-frame partner never attempts an out-of-range decode.
    tab, (left, right) = open_pair(app, [records[0], records[2]])
    tab.setSliceIndex(2)
    wait_until(lambda: left.sliceIndex == 2)
    assert right.sliceIndex == 0 and right.sliceCount == 1
    tab, (left, right) = open_pair(app, [records[2], records[1]])
    assert tab.sliceCount == 2  # Keep a useful shared slider when the left is a single image.
    tab.setSliceIndex(1)
    wait_until(lambda: right.sliceIndex == 1)
    assert left.sliceIndex == 0


def test_display_sync_options_reset_and_measurement_isolation(comparison):
    app, records = comparison
    tab, (left, right) = open_pair(app, records)
    assert tab.syncOperations == dict.fromkeys(SYNC_OPERATIONS, True)
    left.setViewportSize(400, 300)
    right.setViewportSize(200, 150)
    left.apply_pan(40, 30)
    assert (right.panX, right.panY) == (20, 15)
    left.setZoom(2)
    assert right.zoom == 2
    left.applyTransformAction('rotate:cw90')
    left.applyTransformAction('rotate:mirror-h')
    assert right.rotationDegrees == 90 and right.horizontalFlip
    right.applyTransformAction('rotate:mirror-v')
    assert left.verticalFlip
    left.apply_window_level(WindowLevelChange(WindowLevel(50, 500), True))
    wait_until(lambda: right.viewport_state.window == WindowLevel(50, 500) and right.inverted)
    left.applyColorMap('hot')
    assert right.viewport_state.display_style == left.viewport_state.display_style
    left.setViewportSetting('hide-sensitive-info', True)
    assert right.hideSensitiveInfo
    tab.setSyncOperation('zoom', False)
    left.setZoom(3)
    assert right.zoom == 2
    tab.activateViewport(right.viewportId)
    tab.setSyncOperation('zoom', True)
    assert left.zoom == 2
    tab.setSyncOperation('window', False)
    right.apply_window_level(WindowLevelChange(WindowLevel(90, 700), False))
    wait_until(lambda: right.viewport_state.window == WindowLevel(90, 700))
    assert left.viewport_state.window == WindowLevel(50, 500)
    assert not left.inverted  # Inversion has its own link.
    mid = draw_length(left)
    other_mid = draw_length(right)
    tab.historyController.capture()
    assert mid not in right._measure_controller._measurements
    assert other_mid not in left._measure_controller._measurements
    tab.historyController.undo()
    assert not left._measure_controller._measurements and not right._measure_controller._measurements
    tab.historyController.redo()
    assert mid in left._measure_controller._measurements
    from qt_dicom_viewer.ui.controller.measurement_report_controller import capture_results
    rows, _, _ = capture_results(app.workspaceController, app._series_catalog, anonymous=False)
    assert len(rows) == 2
    assert {row['series'] for row in rows} == {r.series_description for r in records[:2]}
    left.reset_all_view_state()
    assert right.zoom == 1 and right.rotationDegrees == 0
    assert other_mid in right._measure_controller._measurements


def test_compare_save_restore_both_sides_and_links(comparison, tmp_path):
    app, records = comparison
    tab, (left, right) = open_pair(app, records)
    tab.setSyncOperation('zoom', False)
    tab.setSyncOperation('scroll', False)
    left.setZoom(2)
    right.setZoom(5)
    right.setSliceIndex(1)
    wait_until(lambda: right._frame_meta.slice_index == 1)
    mid = draw_length(right)
    tab.activateViewport(right.viewportId)
    manager = app.workspaceDocumentController
    path = tmp_path / 'comparison.voxworkspace'
    assert manager.save_to(path)
    wait_until(lambda: not manager.busy)
    document = read_document(path)
    assert document['tabs'][0]['type'] == 'compare2d'
    assert len(document['tabs'][0]['views']) == 2
    assert manager.restore_from(path)
    wait_until(lambda: not manager.busy, timeout=20000)
    assert not manager.isError, manager.message
    restored = app.workspaceController.activeTab
    left, right = restored.viewports_by_id.values()
    assert (left.zoom, right.zoom) == (2, 5)
    assert (left.sliceIndex, right.sliceIndex) == (0, 1)
    assert restored.activeViewport is right
    assert mid in right._measure_controller._measurements
    assert restored.syncOperations['scroll'] is False
    assert restored.syncOperations['zoom'] is False
    manager._dirty = False
    restored.setSyncOperation('pan', False)
    assert manager.dirty


def test_mixed_pet_ct_compare_window_controls(comparison, paired_series):
    app, records = comparison
    _, ct, pet = paired_series
    app._series_catalog.update(DicomFolderScanSnapshot(records[0].instances[0].path.parent, 6, 6, 0, [ct, pet]))
    assert supports_compare(pet)
    tab, (left, right) = open_pair(app, [ct, pet])
    right.setPetDisplayUpper(7)
    wait_until(lambda: left.windowWidth == 7)
    tab.activateViewport(right.viewportId)
    assert not tab.toolController.windowPresets
    assert not any(tool['toolType'] == 'service' for tool in tab.toolController.tools)
    tab.setSyncOperation('window', False)
    left.applyWindowPreset(40, 400)
    wait_until(lambda: left.windowWidth == 400)
    assert right._pet_display.target.window.width == 7


@pytest.mark.parametrize('count', [3, 4])
def test_multi_compare_picker_retains_mpr_mode_and_workspace(comparison, tmp_path, count):
    app, records = comparison
    from test_mr import write_mr_series
    fourth = write_mr_series(tmp_path / "fourth-mr")
    records = [*records, fourth]
    snapshot = DicomFolderScanSnapshot(tmp_path, 10, 10, 0, records)
    panel, ws = app.panelController, app.workspaceController
    panel.update_series_session(snapshot)
    panel._update_series_record(snapshot)
    uids = [r.series_instance_uid for r in records]
    picker = panel.compareController
    panel.selectSeries(uids[0])
    picker.request(uids[0])
    for uid in uids[1:count]:
        picker.togglePartner(uid)
    assert picker.canConfirm and len(picker.partnerUids) == count - 1
    picker.confirm()
    tab = ws.activeTab
    wait_until(lambda: all(v.loadState == 'ready' for v in tab.viewports_by_id.values()))
    assert len(tab.viewports_by_id) == count
    manager = app.workspaceDocumentController
    path = tmp_path / 'multi-compare.voxworkspace'
    assert manager.save_to(path)
    wait_until(lambda: not manager.busy)
    assert manager.restore_from(path)
    wait_until(lambda: not manager.busy, timeout=20000)
    assert not manager.isError, manager.message
    restored = ws.activeTab
    wait_until(lambda: all(v.loadState == 'ready' for v in restored.viewports_by_id.values()))
    assert len(restored.viewports_by_id) == count
    # The same picker limits MPR to two groups and excludes single-slice records.
    panel.selectSeries(uids[0])
    picker.requestMpr(uids[0])
    assert picker.dialogOpen and picker.mode == 'mpr'
    picker.togglePartner(uids[1])
    picker.togglePartner(uids[3])
    assert picker.partnerUids == [uids[3]]
    assert uids[2] not in {r['seriesUid'] for r in picker.candidates}
    picker.confirm()
    assert ws.activeTabType == 'comparempr'
    wait_until(lambda: all(v.loadState == 'ready' for v in ws.activeTab.viewports_by_id.values()))
    assert len(ws.activeTab.viewports_by_id) == 6
