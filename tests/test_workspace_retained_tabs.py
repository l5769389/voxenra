import pytest
from PySide6.QtWidgets import QMessageBox
from qt_dicom_viewer.core.workspace_document import read_document
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app, draw_length


@pytest.fixture
def edited(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Close)
    app, record = populated_app(tmp_path, settings_path=tmp_path/'settings.json')
    doc = app.workspaceDocumentController
    doc._autosave.stop()
    draw_length(app.workspaceController.activeViewport)
    try:
        yield app, record
    finally:
        app.shutdown()


def test_close_retains_results_without_prompt_and_reopen_restores(edited, monkeypatch):
    app, record = edited
    ws, doc = app.workspaceController, app.workspaceDocumentController
    key = ws.activeTabId
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: pytest.fail('Close prompted'))
    assert ws.closeTab(key)
    assert not ws.tabs and doc.closedTabCount == 1 and doc.hasContent
    app.panelController.openSeriesView(record.series_instance_uid, '2d')
    wait_until(lambda: ws.activeLoadState and ws.activeLoadState.status == 'ready')
    fresh = ws.activeTab
    assert not fresh.activeViewport._measure_controller._measurements
    assert doc.closedTabCount == 1 and doc.reopenLastClosed()
    wait_until(lambda: not doc.busy)
    assert ws.activeTab is not fresh and not doc.isError
    assert not fresh.activeViewport._measure_controller._measurements
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    assert doc.closedTabCount == 0


def test_closed_results_survive_file_recovery_and_require_exit_save(edited, tmp_path, monkeypatch):
    app, record = edited
    ws, doc = app.workspaceController, app.workspaceDocumentController
    assert ws.closeTab(ws.activeTabId)
    app.panelController.clearSeries()
    assert doc.hasContent
    monkeypatch.setattr(doc, '_ask_exit_behavior', lambda: ('cancel', False))
    assert not doc.requestClose()
    doc._save_recovery()
    wait_until(lambda: not doc.busy)
    recovery = read_document(doc._recovery_path)
    assert recovery['tabs'][0]['closedId']
    path = tmp_path/'closed.voxworkspace'
    assert doc.save_to(path)
    wait_until(lambda: not doc.busy)
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy)
    assert not doc.isError and not ws.tabs and doc.closedTabCount == 1
    assert doc.reopenLastClosed()
    wait_until(lambda: not doc.busy)
    assert len(ws.activeViewport._measure_controller._measurements) == 1
    assert doc.path == str(path) and doc.dirty


def test_failed_snapshot_preserves_all_tabs(edited, monkeypatch):
    import qt_dicom_viewer.ui.controller.workspace_controller as module
    app, _ = edited
    ws = app.workspaceController
    tab = ws.activeTab
    monkeypatch.setattr(module, 'dumps', lambda state: (_ for _ in ()).throw(MemoryError('full')))
    assert not ws.closeTab(ws.activeTabId)
    assert ws.activeTab is tab and app.workspaceDocumentController.isError


def test_new_discards_retained_results(edited, monkeypatch):
    app, _ = edited
    ws, doc = app.workspaceController, app.workspaceDocumentController
    assert ws.closeTab(ws.activeTabId)
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: QMessageBox.Discard)
    assert doc.newWorkspace()
    assert doc.closedTabCount == 0 and not doc.hasContent


from test_pet_fusion import paired_series


def test_reopen_fusion_volume_preserves_open_source(qt_app, tmp_path, paired_series):
    import numpy as np
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    _, ct, pet = paired_series
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet])
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        ws, doc = app.workspaceController, app.workspaceDocumentController
        ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        wait_until(lambda: ws.activeLoadState.status == 'ready', timeout=20000)
        source = ws.activeTab
        source_id = source.tab_config.tab_id
        ws.createFusionVolumeTab(source)
        volume = ws.activeViewport
        volume.crop_mask = np.ones_like(volume.volume.modality_pixels, dtype=bool)
        volume.crop_mask[0] = False
        volume._update_mask()
        mask = volume.crop_mask.copy()
        volume_id = ws.activeTabId
        assert ws.closeTab(volume_id)
        source.matrix[0,3] = 1.5
        source.request_render()
        wait_until(lambda: source._last_result.request.transform[3] == 1.5)
        assert doc.reopenLastClosed()
        wait_until(lambda: not doc.busy, timeout=20000)
        assert not doc.isError, doc.message
        assert ws._tab_dict[source_id] is source and source.matrix[0,3] == 1.5
        assert ws.activeTabId == volume_id and len(ws._tab_dict) == 2
        np.testing.assert_array_equal(ws.activeViewport.crop_mask, mask)
    finally:
        app.shutdown()


def test_reopen_snapshot_failure_keeps_retained_result(edited, monkeypatch):
    import qt_dicom_viewer.ui.controller.workspace_document_controller as module
    app, _ = edited
    ws, doc = app.workspaceController, app.workspaceDocumentController
    assert ws.closeTab(ws.activeTabId)
    monkeypatch.setattr(module, 'loads', lambda value: (_ for _ in ()).throw(MemoryError('full')))
    assert not doc.reopenLastClosed()
    assert doc.closedTabCount == 1 and doc.hasContent and doc.isError and not doc.busy


def test_unedited_image_tab_can_be_reopened_in_session(qt_app, tmp_path):
    app, record = populated_app(tmp_path, settings_path=False)
    ws, doc = app.workspaceController, app.workspaceDocumentController
    try:
        ws.activeViewport.apply_slice_index(1)
        wait_until(lambda: ws.activeViewport.sliceIndex == 1)
        assert ws.closeTab(ws.activeTabId) and doc.canReopenClosed
        path = tmp_path / 'browse.voxworkspace'
        assert doc.save_to(path)
        wait_until(lambda: not doc.busy)
        assert read_document(path)['tabs'] == []
        assert doc.reopenLastClosed()
        wait_until(lambda: not doc.busy)
        assert ws.activeViewport.sliceIndex == 1 and not doc.closedTabCount
    finally:
        app.shutdown()


def test_browsing_history_limit_preserves_edited_result(edited, tmp_path):
    app, record = edited
    ws, doc = app.workspaceController, app.workspaceDocumentController
    assert ws.closeTab(ws.activeTabId)
    for _ in range(21):
        ws.activeWorkspace(record.series_instance_uid, '2d')
        wait_until(lambda: ws.activeLoadState.status == 'ready')
        assert ws.closeTab(ws.activeTabId)
    assert doc.closedTabCount == 21
    path = tmp_path / 'retained.voxworkspace'
    assert doc.save_to(path)
    wait_until(lambda: not doc.busy)
    assert len(read_document(path)['tabs']) == 1
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy)
    assert doc.closedTabCount == 1 and doc.reopenLastClosed()
    wait_until(lambda: not doc.busy)
    assert len(ws.activeViewport._measure_controller._measurements) == 1


def test_unsuccessful_reopen_does_not_modify_another_open_tab(edited, monkeypatch):
    app, record = edited
    ws, doc = app.workspaceController, app.workspaceDocumentController
    assert ws.closeTab(ws.activeTabId)
    ws.activeWorkspace(record.series_instance_uid, '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    fresh = ws.activeTab
    monkeypatch.setattr(ws, 'createTab', lambda *args, **kwargs: None)
    assert doc.reopenLastClosed()
    wait_until(lambda: not doc.busy)
    assert doc.isError and doc.closedTabCount == 1
    assert ws.activeTab is fresh and not fresh.activeViewport._measure_controller._measurements
