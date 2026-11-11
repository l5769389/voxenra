"""Chooser positions survive restart without changing workspace/save preferences."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6 import QtWidgets

from voxplane.i18n import message
from voxplane.i18n.widgets import QFileDialog
from voxplane.settings.dialog_locations import DialogLocations
from test_dicom_tags import qt_app


@pytest.fixture
def locations(qt_app, tmp_path):
    history = DialogLocations(tmp_path / 'settings' / 'dialog-locations.json')
    history.activate()
    try:
        yield history
    finally:
        history.deactivate()


def test_locations_survive_a_new_process_and_missing_folder(locations, tmp_path):
    expected = {}
    for key in ('images', 'workspace', 'attachments', 'export'):
        folder = tmp_path / key / '影像'
        folder.mkdir(parents=True)
        locations.remember(key, folder, directory=True)
        expected[key] = str(folder)
    script = '''import json, sys
from voxplane.settings.dialog_locations import DialogLocations
history = DialogLocations(sys.argv[1])
print(json.dumps({key: history.directory(key) for key in ('images', 'workspace', 'attachments', 'export')}))
'''
    result = subprocess.run([sys.executable, '-c', script, str(locations.path)],
                            capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(result.stdout) == expected
    Path(expected['images']).rmdir()
    assert locations.directory('images') == str(tmp_path / 'images')
    assert locations.directory('workspace') == expected['workspace']


def test_workspace_open_save_share_location_and_cancel_preserves_it(locations, tmp_path, monkeypatch):
    folder = tmp_path / 'workspaces'
    folder.mkdir()
    target = folder / 'review.voxworkspace'
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(target), ''))
    assert QFileDialog.getOpenFileName(None, message('text.0417'), '')[0] == str(target)
    observed = []
    def cancel(*args, **kwargs):
        observed.append(args[2] if len(args) > 2 else kwargs['dir'])
        return '', ''
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getSaveFileName', cancel)
    QFileDialog.getSaveFileName(None, message('text.0414'), 'new.voxworkspace')
    assert observed == [str(folder / 'new.voxworkspace')]
    assert locations.directory('workspace') == str(folder)
    assert 'new.voxworkspace' not in locations.path.read_text()


def test_export_folder_and_attachment_file_keep_distinct_locations(locations, tmp_path, monkeypatch):
    export, attachments = tmp_path / 'exports', tmp_path / 'seg'
    export.mkdir()
    attachments.mkdir()
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getExistingDirectory', lambda *a, **k: str(export))
    QFileDialog.getExistingDirectory(None, message('results.chooseDirectory'))
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(attachments / 'seg.dcm'), ''))
    QFileDialog.getOpenFileName(None, message('seg.chooseFile'), '')
    assert locations.directory('export') == str(export)
    assert locations.directory('attachments') == str(attachments)


@pytest.mark.parametrize('is_folder', [False, True])
def test_mixed_import_remembers_selected_folder_itself_or_file_parent(locations, tmp_path, monkeypatch, is_folder):
    from voxplane.ui.dialogs import local_import_dialog as module
    selected = tmp_path / 'dicom'
    selected.mkdir()
    if not is_folder:
        selected = selected / 'image.dcm'
        selected.touch()
    opened = []
    results = [[str(selected)], []]
    class Picker:
        def __init__(self, directory):
            opened.append(directory)
            self.paths = results.pop(0)
        def exec(self):
            return QtWidgets.QDialog.Accepted if self.paths else QtWidgets.QDialog.Rejected
        def deleteLater(self):
            pass
    monkeypatch.setattr(module, 'LocalImportDialog', Picker)
    monkeypatch.setattr(module.QGuiApplication, 'focusWindow', lambda: None)
    assert module.select_import_paths(str(tmp_path)) == [str(selected)]
    assert module.select_import_paths() == []
    assert opened == [str(tmp_path), str(selected if is_folder else selected.parent)]


def test_bad_history_and_memory_only_mode(tmp_path):
    file = tmp_path / 'locations.json'
    file.write_text('{broken')
    assert DialogLocations(file)._directories == {}
    file.write_text(json.dumps({'images': 12, 'workspace': 'relative', 'export': '\0bad', 'unknown': str(tmp_path)}))
    assert DialogLocations(file)._directories == {}
    history = DialogLocations(None)
    history.remember('workspace', tmp_path, directory=True)
    assert history.directory('workspace') == str(tmp_path)
