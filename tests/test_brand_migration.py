"""The rename must preserve released user data without reviving deleted history."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QMimeData
from PySide6.QtGui import QGuiApplication
from voxplane.infrastructure import brand_settings
from test_dicom_tags import qt_app


@pytest.fixture
def identities(qt_app, tmp_path, monkeypatch):
    original = qt_app.organizationName(), qt_app.applicationName()
    def location(kind):
        return str(tmp_path / qt_app.applicationName() / str(kind))
    monkeypatch.setattr(brand_settings, 'QStandardPaths', SimpleNamespace(
        AppConfigLocation=0, AppLocalDataLocation=1, writableLocation=location))
    yield tmp_path
    qt_app.setOrganizationName(original[0])
    qt_app.setApplicationName(original[1])


def put(root, identity, kind, name, data):
    path = root / identity / str(kind) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_rename_preserves_preferences_recovery_recent_and_languages(identities):
    root = identities
    records = [(0, 'display-settings.json', b'{"appearance":{"theme":"graphite"}}'),
               (0, 'pacs.json', b'{"profiles":[]}'),
               (1, 'workspace-recovery.voxworkspace', b'old workspace bytes'),
               (1, 'recent-workspaces.json', b'["/original/file.voxworkspace"]'),
               (1, 'languages/custom.json', b'custom translation')]
    for kind, name, data in records:
        put(root, 'Voxenra', kind, name, data)
    brand_settings.configure_storage_identity()
    assert QCoreApplication.applicationName() == 'VoxPlane'
    assert QCoreApplication.organizationName() == 'VoxPlane'
    for kind, name, data in records:
        assert (root / 'VoxPlane' / str(kind) / name).read_bytes() == data
        assert (root / 'Voxenra' / str(kind) / name).read_bytes() == data


def test_current_preferences_win_and_deleted_recovery_is_not_reimported(identities):
    root = identities
    put(root, 'Voxenra', 0, 'display-settings.json', b'old')
    put(root, 'VoxPlane', 0, 'display-settings.json', b'new')
    put(root, 'Voxenra', 1, 'workspace-recovery.voxworkspace', b'old recovery')
    brand_settings.configure_storage_identity()
    assert (root / 'VoxPlane/0/display-settings.json').read_bytes() == b'new'
    recovery = root / 'VoxPlane/1/workspace-recovery.voxworkspace'
    assert recovery.read_bytes() == b'old recovery'
    recovery.unlink()
    brand_settings.configure_storage_identity()
    assert not recovery.exists(), 'A dismissed recovery must not return every launch'


def test_recent_brand_wins_over_original_qt_identity(identities):
    root = identities
    put(root, brand_settings.LEGACY_APPLICATION, 0, 'display-settings.json', b'ancient')
    put(root, 'Voxenra', 0, 'display-settings.json', b'recent')
    brand_settings.configure_storage_identity()
    assert (root / 'VoxPlane/0/display-settings.json').read_bytes() == b'recent'


def test_failed_copy_retries_without_overwriting_other_migrated_data(identities, monkeypatch):
    root = identities
    put(root, 'Voxenra', 0, 'display-settings.json', b'settings')
    put(root, 'Voxenra', 0, 'pacs.json', b'pacs')
    write = brand_settings._write_file
    with monkeypatch.context() as patch:
        patch.setattr(brand_settings, '_write_file',
                      lambda path, data: False if path.name == 'pacs.json' else write(path, data))
        brand_settings.configure_storage_identity()
    import json
    assert not json.loads((root / 'VoxPlane/0' / brand_settings.MIGRATION_MARKER).read_bytes())['complete']
    put(root, 'VoxPlane', 0, 'display-settings.json', b'user changed settings')
    brand_settings.configure_storage_identity()
    assert (root / 'VoxPlane/0/pacs.json').read_bytes() == b'pacs'
    assert (root / 'VoxPlane/0/display-settings.json').read_bytes() == b'user changed settings'
    assert (root / 'VoxPlane/0' / brand_settings.MIGRATION_MARKER).exists()


def test_unrelated_copy_failure_cannot_resurrect_dismissed_recovery(identities, monkeypatch):
    root = identities
    put(root, 'Voxenra', 0, 'pacs.json', b'recent pacs')
    put(root, 'Voxenra', 1, 'workspace-recovery.voxworkspace', b'recovery')
    write = brand_settings._write_file
    with monkeypatch.context() as patch:
        patch.setattr(brand_settings, '_write_file',
                      lambda path, data: False if path.name == 'pacs.json' else write(path, data))
        brand_settings.configure_storage_identity()
    recovery = root / 'VoxPlane/1/workspace-recovery.voxworkspace'
    assert recovery.read_bytes() == b'recovery'
    recovery.unlink()
    brand_settings.configure_storage_identity()
    assert not recovery.exists()
    assert (root / 'VoxPlane/0/pacs.json').read_bytes() == b'recent pacs'


def test_newer_source_failure_never_falls_back_to_ancient_file(identities, monkeypatch):
    root = identities
    put(root, 'Voxenra', 0, 'pacs.json', b'recent pacs')
    put(root, brand_settings.LEGACY_APPLICATION, 0, 'pacs.json', b'ancient pacs')
    copy = brand_settings._copy_file
    with monkeypatch.context() as patch:
        patch.setattr(brand_settings, '_copy_file',
                      lambda old, new: False if old.parts[-3] == 'Voxenra' else copy(old, new))
        brand_settings.configure_storage_identity()
    assert not (root / 'VoxPlane/0/pacs.json').exists()
    brand_settings.configure_storage_identity()
    assert (root / 'VoxPlane/0/pacs.json').read_bytes() == b'recent pacs'


def test_workspace_file_format_stays_compatible():
    from voxplane.core.workspace_document import validate_document, FORMAT
    document = {'format': 'VoxenraWorkspace', 'version': 2, 'series': [], 'tabs': []}
    assert FORMAT == 'VoxenraWorkspace'
    assert validate_document(document)['format'] == document['format']


def test_old_clipboard_payload_is_read_but_new_copy_uses_new_brand(qt_app):
    from voxplane.ui.annotation_clipboard import read_annotation, write_annotation
    import json
    payload = dict(version=1, kind='length', points=[[1, 2], [3, 4]])
    mime = QMimeData()
    mime.setData('application/x-voxenra-annotation+json', json.dumps(payload).encode())
    QGuiApplication.clipboard().setMimeData(mime)
    try:
        assert read_annotation() == payload
        write_annotation(payload)
        assert QGuiApplication.clipboard().mimeData().hasFormat('application/x-voxplane-annotation+json')
    finally:
        QGuiApplication.clipboard().clear()
