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
