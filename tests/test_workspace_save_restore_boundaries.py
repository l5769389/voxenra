import pytest

from qt_dicom_viewer.core.dicom_scanner import _build_series_record, _read_instance
from qt_dicom_viewer.core.workspace_document import read_document
from qt_dicom_viewer.core.workspace_state import dumps
from qt_dicom_viewer.i18n.messages import builtin, localize
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import make_dicom, qt_app, wait_until
from test_workspace_persistence import populated_app


@pytest.mark.parametrize('recovery', [False, True])
def test_tab_limit_rejects_save_without_replacing_readable_document(qt_app, tmp_path, recovery):
    records = []
    for index in range(65):
        source = tmp_path / f'{index}.dcm'
        dataset = make_dicom(source, index + 1)
        dataset.SeriesInstanceUID = f'1.2.3.{index + 1}'
        dataset.save_as(source, enforce_file_format=True)
        records.append(_build_series_record([_read_instance(source)]))
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        workspace, manager = app.workspaceController, app.workspaceDocumentController
        snapshot = DicomFolderScanSnapshot(tmp_path, 65, 65, 0, records)
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        for record in records[:64]:
            workspace.createTab(record.series_instance_uid, 'Tags', 'tag')
        path = tmp_path / 'safe.voxworkspace'
        assert manager.save_to(path, recovery=recovery)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        saved = read_document(path)
        assert len(saved['tabs']) == 64
        previous = path.read_bytes()

        workspace.createTab(records[64].series_instance_uid, 'Tags', 'tag')
        manager._close_after_save = True
        assert manager.dirty
        assert manager.save_to(path, recovery=recovery)
        wait_until(lambda: not manager.busy)
        assert manager.isError, manager.message
        assert manager.dirty and manager._recovery_dirty
        assert not manager._close_after_save
        assert len(workspace._tab_dict) == 65
        assert path.read_bytes() == previous
        assert len(read_document(path)['tabs']) == 64
        for locale, action in [('zh-CN', '关闭'), ('en-US', 'Close')]:
            message = localize(manager._message, builtin(locale)['messages'])
            assert '64' in message and action in message

        # The reader applies the same limit to externally supplied documents.
        saved['tabs'].append(saved['tabs'][0])
        invalid_path = tmp_path / 'external.voxworkspace'
        invalid_path.write_bytes(dumps(saved))
        with pytest.raises(ValueError, match='64'):
            read_document(invalid_path)
    finally:
        app.shutdown()


@pytest.mark.parametrize('utility_tabs', [False, True])
def test_skip_all_missing_sources_finishes_restore_and_preserves_original(qt_app, tmp_path, monkeypatch, utility_tabs):
    from qt_dicom_viewer.ui.controller import workspace_document_controller as module

    app, record = populated_app(tmp_path)
    try:
        workspace, manager = app.workspaceController, app.workspaceDocumentController
        if utility_tabs:
            workspace.openSettings()
            workspace.openPacs()
            workspace.openManual()
        manager.setSidebarLayout(275, True)
        app.settingsController.setValue('layout', 'rightPanelWidth', 360)
        path = tmp_path / 'original.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        original = path.read_bytes()
        for instance in record.instances:
            instance.path.unlink()
        manager.setSidebarLayout(300, False)
        app.settingsController.setValue('layout', 'rightPanelWidth', 300)

        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy)
        assert manager.hasMissingSources and manager._pending['snapshot'] is None
        manager.skipMissing()
        wait_until(lambda: not manager.busy)
        assert manager._pending is None
        assert not manager.hasMissingSources and not manager.restoring
        assert [tab.tab_config.tab_type.value for tab in workspace._tab_dict.values()] == (
            ['settings', 'pacs', 'manual'] if utility_tabs else [])
        if utility_tabs:
            assert workspace.activeTab.tab_config.tab_type.value == 'manual'
        assert not app.panelController.hasSeries
        assert not app._series_catalog.snapshot()
        assert manager.sidebarLayout == {'width': 275, 'collapsed': True}
        assert app.settingsController.section('layout')['rightPanelWidth'] == 360
        assert manager.isError and manager.dirty
        assert '1' in manager.message and '另存' in manager.message
        assert manager.path == ''
        assert path.read_bytes() == original

        # Save routes through Save As after a partial restore, protecting the source.
        replacement = tmp_path / 'remaining.voxworkspace'
        monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: (str(replacement), ''))
        assert manager.save()
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        assert read_document(replacement)['series'] == []
        assert path.read_bytes() == original
    finally:
        app.shutdown()


@pytest.mark.parametrize('active', [[], {}, '0', None, True, -1, 1, 0.5])
def test_invalid_active_tab_is_rejected_before_restore(tmp_path, active):
    path = tmp_path / 'invalid.voxworkspace'
    path.write_bytes(dumps(dict(format='VoxenraWorkspace', version=1, series=[],
                               tabs=[dict(type='manual', label='Manual', series=[])], activeTab=active)))
    with pytest.raises(ValueError):
        read_document(path)


@pytest.mark.parametrize('tabs,active', [([], 0), ([], 'missing'),
    ([dict(type='manual', label='Manual', series=[])], 'missing'),
    ([dict(type='manual', label='Manual', series=[]), dict(type='settings', label='Settings', series=[])], 1)])
def test_valid_active_tab_and_legacy_default_remain_readable(tmp_path, tabs, active):
    document = dict(format='VoxenraWorkspace', version=1, series=[], tabs=tabs)
    if active != 'missing':
        document['activeTab'] = active
    path = tmp_path / 'valid.voxworkspace'
    path.write_bytes(dumps(document))
    assert read_document(path).get('activeTab', 0) == (0 if active == 'missing' else active)


def test_invalid_active_tab_preserves_current_workspace(qt_app, tmp_path):
    app, _ = populated_app(tmp_path)
    try:
        manager, workspace = app.workspaceDocumentController, app.workspaceController
        old_tab = workspace.activeTab
        old_tab.activeViewport.setZoom(3)
        path = tmp_path / 'invalid.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        document = read_document(path)
        old_tab.activeViewport.setZoom(4)
        document['activeTab'] = []
        path.write_bytes(dumps(document))
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy)
        assert manager.isError and not manager.restoring
        assert workspace.activeTab is old_tab
        assert old_tab.activeViewport.zoom == 4 and manager.dirty
        assert manager.save_to(tmp_path / 'still-saveable.voxworkspace')
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
    finally:
        app.shutdown()


@pytest.mark.parametrize('missing', [False, True])
def test_cancel_after_worker_completion_keeps_current_workspace(qt_app, tmp_path, monkeypatch, missing):
    from qt_dicom_viewer.ui.controller import workspace_document_controller as module

    app, record = populated_app(tmp_path)
    try:
        manager, workspace = app.workspaceDocumentController, app.workspaceController
        path = tmp_path / 'saved.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        old_tab = workspace.activeTab
        old_store = app.panelController._import_store
        old_tab.activeViewport.setZoom(3)
        if missing:
            for instance in record.instances:
                instance.path.unlink()
        resources = []
        store_type = module.LocalImportStore
        def make_store():
            store = store_type()
            resources.append(store.root)
            return store
        monkeypatch.setattr(module, 'LocalImportStore', make_store)
        assert manager.restore_from(path)
        # Complete the single-worker queue without delivering GUI signals.
        manager._executor.submit(lambda: None).result(timeout=10)
        manager.cancel()
        wait_until(lambda: not manager.busy)
        assert workspace.activeTab is old_tab
        assert old_tab.activeViewport.zoom == 3 and manager.dirty
        assert manager.path == str(path)
        assert app.panelController._import_store is old_store
        assert not manager.restoring and not manager.hasMissingSources
        assert manager._pending is None
        assert resources and all(not root.exists() for root in resources)
        assert '取消' in manager.message
    finally:
        app.shutdown()


def test_finish_restore_failure_unlocks_saving_and_reports_reason(qt_app, tmp_path, monkeypatch):
    app, _ = populated_app(tmp_path)
    try:
        manager = app.workspaceDocumentController
        path = tmp_path / 'saved.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        manager._pending = dict(document=read_document(path), path=str(path), missing=[])
        manager._restored_ids = {0: app.workspaceController.activeTabId}
        manager._busy = manager._restoring = True
        manager._restore_timer.start()
        def fail_activation(_):
            raise RuntimeError('tab activation failed')
        with monkeypatch.context() as patch:
            patch.setattr(app.workspaceController, 'activateTabId', fail_activation)
            manager._finish_restore('Restored')
        assert manager.isError and 'tab activation failed' in manager.message
        assert not manager.restoring and not manager._restore_timer.isActive()
        assert manager._pending is None and manager.path == '' and manager.dirty
        assert manager.save_to(tmp_path / 'recovered.voxworkspace')
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
    finally:
        app.shutdown()


def test_skip_missing_after_cancelled_location_retry_restores_available_tabs(qt_app, tmp_path, monkeypatch):
    from test_series_sidebar import phantom_series
    from qt_dicom_viewer.ui.dialogs import local_import_dialog
    app, available = populated_app(tmp_path)
    try:
        manager, workspace, panel = app.workspaceDocumentController, app.workspaceController, app.panelController
        missing = phantom_series(tmp_path, 2, 'SYNTHETIC-B', '1.2.3.2', '20261020')
        snapshot = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [available, missing])
        panel.update_series_session(snapshot)
        panel._update_series_record(snapshot)
        workspace.createTab(missing.series_instance_uid, 'Missing', 'tag')
        path = tmp_path / 'two-series.voxworkspace'
        assert manager.save_to(path)
        wait_until(lambda: not manager.busy)
        assert not manager.isError, manager.message
        original = path.read_bytes()
        for instance in missing.instances:
            instance.path.unlink()
        assert manager.restore_from(path)
        wait_until(lambda: not manager.busy)
        assert manager.hasMissingSources
        pending = manager._pending
        monkeypatch.setattr(local_import_dialog, 'select_import_paths', lambda: [str(available.instances[0].path)])
        manager.locateMissing()
        manager._executor.submit(lambda: None).result(timeout=10)
        manager.cancel()
        wait_until(lambda: not manager.busy)
        assert manager._pending is pending
        manager.skipMissing()
        wait_until(lambda: not manager.busy)
        assert len(workspace._tab_dict) == 1
        assert workspace.activeTabType == '2d'
        assert workspace.activeViewport.loadState == 'ready'
        assert manager._pending is None and not manager.restoring
        assert manager.isError and manager.dirty and not manager.path
        assert path.read_bytes() == original
    finally:
        app.shutdown()
