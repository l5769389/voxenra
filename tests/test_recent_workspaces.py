import json

from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import populated_app


def test_recent_workspaces_success_only_and_restart(qt_app, tmp_path):
    settings = tmp_path / 'settings.json'
    app, _ = populated_app(tmp_path, settings_path=settings)
    doc = app.workspaceDocumentController
    first, second = tmp_path / 'First.voxworkspace', tmp_path / 'Second.voxworkspace'
    try:
        assert doc.recentWorkspaces == []
        for path in (first, second, first):
            assert doc.save_to(path)
            wait_until(lambda: not doc.busy)
            assert not doc.isError
        assert [r['path'] for r in doc.recentWorkspaces] == [str(first), str(second)]
        assert doc.save_to(doc.recoveryPath, recovery=True)
        wait_until(lambda: not doc.busy)
        assert len(doc.recentWorkspaces) == 2
        assert doc.restore_from(tmp_path / 'invalid.voxworkspace')
        wait_until(lambda: not doc.busy)
        assert doc.isError
        assert len(doc.recentWorkspaces) == 2
    finally:
        app.shutdown()
    restarted = AppController(DicomImageProvider(), settings_path=settings)
    try:
        doc = restarted.workspaceDocumentController
        assert [r['name'] for r in doc.recentWorkspaces] == ['First', 'Second']
        assert doc.openRecent(str(second))
        wait_until(lambda: not doc.busy)
        assert not doc.isError, doc.message
        assert doc.recentWorkspaces[0]['path'] == str(second)
        assert not doc.dirty
        second.unlink()
        assert not doc.openRecent(str(second))
        assert doc.isError and not doc.busy
        assert doc.recentWorkspaces[0]['missing']
        assert doc.removeRecent(str(second))
        assert doc.recentWorkspaces[0]['path'] == str(first)
        assert not doc.dirty
    finally:
        restarted.shutdown()


def test_recent_open_respects_cancel_and_busy(qt_app, tmp_path, monkeypatch):
    app, _ = populated_app(tmp_path)
    try:
        doc = app.workspaceDocumentController
        path = tmp_path / 'Saved.voxworkspace'
        doc.save_to(path)
        wait_until(lambda: not doc.busy)
        calls = []
        monkeypatch.setattr(doc, '_confirm_replace', lambda p: calls.append(p) or False)
        monkeypatch.setattr(doc, 'restore_from', lambda p: (_ for _ in ()).throw(AssertionError('must not load')))
        assert not doc.openRecent(str(path))
        assert calls == [str(path)]
        doc._busy = True
        assert not doc.openRecent(str(path))
        assert calls == [str(path)]
        doc._busy = False
        assert not doc.openRecent(str(tmp_path / 'not-in-history.voxworkspace'))
    finally:
        app.shutdown()


def test_history_is_bounded_and_defensive(tmp_path):
    from qt_dicom_viewer.infrastructure.recent_workspaces import RecentWorkspaces
    path = tmp_path / 'recent.json'
    path.write_text('{bad')
    history = RecentWorkspaces(path)
    assert history.items == []
    for i in range(9):
        history.remember(tmp_path / f'{i}.voxworkspace')
    assert len(history.items) == 5
    assert history.items[0]['name'] == '8'
    history.remember(tmp_path / '7.voxworkspace')
    assert [r['name'] for r in RecentWorkspaces(path).items] == ['7', '8', '6', '5', '4']
    path.write_text(json.dumps({'version': 1, 'items': [None, {}, {'path': 'relative', 'lastUsed': []}]}))
    assert RecentWorkspaces(path).items == []
