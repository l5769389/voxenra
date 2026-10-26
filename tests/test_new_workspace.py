from threading import Event

import pytest
from PySide6.QtWidgets import QMessageBox

from qt_dicom_viewer.core.workspace_document import read_document
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app, draw_length


@pytest.fixture
def work(qt_app, tmp_path):
    app, record = populated_app(tmp_path, settings_path=tmp_path/'settings.json')
    app.workspaceDocumentController._autosave.stop()
    try:
        yield app, app.workspaceDocumentController, record
    finally:
        app.shutdown()


def test_new_discards_session_but_preserves_file_settings_and_recent(work, tmp_path, monkeypatch):
    app, doc, record = work
    path = tmp_path/'original.voxworkspace'
    assert doc.save_to(path)
    wait_until(lambda: not doc.busy)
    saved = path.read_bytes()
    draw_length(app.workspaceController.activeViewport)
    app.workspaceController.activeTab.historyController.capture()
    app.panelController._last_import_paths = ['old-archive.zip']
    app.panelController._last_import_snapshot = object()
    app.settingsController.setValue('appearance', 'theme', 'light')
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: QMessageBox.Discard)
    old_store = app.panelController._import_store
    assert doc.newWorkspace()
    assert doc.path == '' and not doc.dirty and not doc.hasContent
    assert not app.workspaceController._tab_dict
    assert not app.panelController.seriesItems and not app._series_catalog.snapshot()
    assert app.panelController._last_import_snapshot is None
    assert not app.panelController._last_import_paths
    assert app.panelController._import_store is not old_store
    assert app.settingsController.section('appearance')['theme'] == 'light'
    assert doc.recentWorkspaces[0]['path'] == str(path)
    assert path.read_bytes() == saved
    assert doc.restore_from(path)
    wait_until(lambda: not doc.busy)
    assert not doc.isError and app.workspaceController.activeViewport is not None


def test_cancel_new_preserves_all_current_content(work, monkeypatch):
    app, doc, _ = work
    tab = app.workspaceController.activeTab
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: QMessageBox.Cancel)
    assert not doc.newWorkspace()
    assert doc.hasContent and app.workspaceController.activeTab is tab and doc.dirty


def test_save_then_new_waits_for_success_and_preserves_measurements(work, tmp_path, monkeypatch):
    app, doc, _ = work
    draw_length(app.workspaceController.activeViewport)
    app.workspaceController.activeTab.historyController.capture()
    path = tmp_path/'saved-before-new.voxworkspace'
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: QMessageBox.Save)
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.workspace_document_controller.QFileDialog.getSaveFileName',
                        lambda *args: (str(path), ''))
    assert not doc.newWorkspace()
    assert doc.busy and doc.hasContent
    wait_until(lambda: not doc.busy)
    assert not doc.hasContent and not doc.path and not doc.dirty
    saved = read_document(path)
    assert any(v.get('measurements') for v in saved['tabs'][0]['edits']['views'].values())


@pytest.mark.parametrize('failure', ['cancel', 'write', 'new-edits'])
def test_failed_or_stale_save_does_not_create_new(work, tmp_path, monkeypatch, failure):
    from qt_dicom_viewer.ui.controller import workspace_document_controller as module
    app, doc, _ = work
    tab = app.workspaceController.activeTab
    entered, release = Event(), Event()
    original_write = module.atomic_write
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: QMessageBox.Save)
    if failure == 'cancel':
        monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: ('', ''))
    else:
        doc._path = str(tmp_path/'current.voxworkspace')
        def write(path, payload):
            if failure == 'write':
                raise OSError('disk full')
            entered.set()
            assert release.wait(5)
            original_write(path, payload)
        monkeypatch.setattr(module, 'atomic_write', write)
    try:
        assert not doc.newWorkspace()
        if failure == 'new-edits':
            assert entered.wait(2)
            doc.mark_dirty()
            release.set()
        wait_until(lambda: not doc.busy)
        assert doc.hasContent and doc.dirty and app.workspaceController.activeTab is tab
        assert not doc._new_after_save
        if failure == 'write':
            assert doc.isError and 'disk full' in doc.message
    finally:
        release.set()


@pytest.mark.parametrize('busy_source', ['document', 'import', 'pacs'])
def test_new_is_blocked_during_background_work(work, monkeypatch, busy_source):
    app, doc, _ = work
    owner, attr = {'document': (doc, '_busy'), 'import': (app.panelController, '_scanning'),
                   'pacs': (app.pacsController, '_busy')}[busy_source]
    monkeypatch.setattr(owner, attr, True)
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: pytest.fail('Busy workspace prompted'))
    assert not doc.canCreateNew and not doc.newWorkspace()
    assert doc.hasContent


def test_new_empty_workspace_needs_no_prompt(qt_app, monkeypatch):
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        doc = app.workspaceDocumentController
        app.workspaceController.openManual()
        monkeypatch.setattr(doc, '_ask_new_workspace', lambda: pytest.fail('Empty workspace prompted'))
        assert doc.newWorkspace()
        assert not doc.dirty and not app.workspaceController._tab_dict
    finally:
        app.shutdown()


@pytest.mark.parametrize('owned', [True, False])
def test_new_removes_only_current_sessions_recovery(work, monkeypatch, owned):
    app, doc, _ = work
    doc._recovery_path.write_text('recovery')
    doc._owns_recovery = owned
    doc._previous_recovery = not owned
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: QMessageBox.Discard)
    assert doc.newWorkspace()
    assert doc._recovery_path.exists() is not owned
    assert doc.recoveryAvailable is not owned


def test_recovery_cleanup_failure_preserves_current_session(work, monkeypatch):
    from pathlib import Path
    app, doc, _ = work
    tab = app.workspaceController.activeTab
    doc._owns_recovery = True
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: QMessageBox.Discard)
    original = Path.unlink
    def unlink(path, **kwargs):
        if path == doc._recovery_path:
            raise PermissionError('recovery is locked')
        return original(path, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', unlink)
        assert not doc.newWorkspace()
        assert doc.hasContent and doc.dirty and app.workspaceController.activeTab is tab
        assert doc.isError and 'recovery is locked' in doc.message


def test_new_saved_workspace_needs_no_prompt_and_clears_pending_restore(work, tmp_path, monkeypatch):
    from qt_dicom_viewer.core.local_import import LocalImportStore
    app, doc, _ = work
    assert doc.save_to(tmp_path/'saved.voxworkspace')
    wait_until(lambda: not doc.busy)
    store = LocalImportStore()
    cleaned = []
    monkeypatch.setattr(store, 'cleanup', lambda: cleaned.append(True))
    doc._pending = {'store': store, 'missing': ['missing-image']}
    doc._error = True
    monkeypatch.setattr(doc, '_ask_new_workspace', lambda: pytest.fail('Saved workspace prompted'))
    assert doc.newWorkspace()
    assert cleaned == [True] and doc._pending is None
    assert not doc.isError and not doc.hasMissingSources and not doc.path
