from pathlib import Path

import pytest

from qt_dicom_viewer.ui.controller.panel_controller import PanelController


def panel(path=None):
    return PanelController(favorite_path=path)


def test_favorites_persist_alias_order_replacement_and_removal(tmp_path):
    paths = [tmp_path / name for name in ('one', 'two', 'replacement')]
    for path in paths:
        path.mkdir()
    store = tmp_path / 'favorites.json'
    p = panel(store)
    favorites = p.favoriteDirectories
    assert favorites.add(str(paths[0]))
    assert favorites.add(str(paths[1]))
    first, second = favorites.items
    assert favorites.rename(first['id'], 'Reference scans')
    assert favorites.move(second['id'], -1)
    assert favorites.replace(first['id'], str(paths[2]))
    again = panel(store).favoriteDirectories
    assert again.items == [second, dict(first, name='Reference scans', path=str(paths[2]))]
    assert again.remove(second['id'])
    assert len(panel(store).favoriteDirectories.items) == 1
    assert not p.scanning


def test_invalid_and_duplicate_directories_do_not_change_saved_items(tmp_path):
    p = panel()
    favorites = p.favoriteDirectories
    assert favorites.add(str(tmp_path))
    before = favorites.items
    assert not favorites.add(str(tmp_path / '.'))
    assert not favorites.add(str(tmp_path / 'missing'))
    assert not favorites.rename(before[0]['id'], '   ')
    assert favorites.items == before
    assert favorites.isError


def test_load_and_items_do_not_touch_favorite_directories(tmp_path, monkeypatch):
    store = tmp_path / 'favorites.json'
    p = panel(store)
    assert p.favoriteDirectories.add(str(tmp_path))
    original = Path.stat
    def guarded(path, *args, **kwargs):
        if path == tmp_path:
            raise AssertionError('favorites must not stat external paths while loading')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', guarded)
    assert panel(store).favoriteDirectories.items[0]['path'] == str(tmp_path)


def test_persistence_failure_does_not_commit_in_memory(tmp_path):
    invalid_parent = tmp_path / 'file'
    invalid_parent.write_text('occupied')
    p = panel(invalid_parent / 'favorites.json')
    assert not p.favoriteDirectories.add(str(tmp_path))
    assert p.favoriteDirectories.items == []
    assert p.favoriteDirectories.isError


@pytest.mark.parametrize('blocked', ['busy', 'restoring', 'disabled'])
def test_import_rejection_does_not_cancel_or_replace_current_task(tmp_path, monkeypatch, blocked):
    p = panel()
    favorites = p.favoriteDirectories
    assert favorites.add(str(tmp_path))
    p._last_import_paths = ['existing']
    p._import_progress = 0.4
    p._scanning = blocked == 'busy'
    monkeypatch.setattr(p, '_workspace_is_restoring', lambda: blocked == 'restoring')
    p._import_blocker = lambda: 'Local import disabled' if blocked == 'disabled' else ''
    def forbidden(*args):
        pytest.fail('blocked favorite must not cancel or start import')
    monkeypatch.setattr(p, 'cancelImport', forbidden)
    monkeypatch.setattr(p, '_start_import', forbidden)
    assert not favorites.importFavorite(favorites.items[0]['id'])
    assert p._last_import_paths == ['existing']
    assert p._import_progress == 0.4


def test_missing_favorite_is_retained_and_repairable(tmp_path):
    folder = tmp_path / 'images'
    folder.mkdir()
    p = panel()
    favorites = p.favoriteDirectories
    assert favorites.add(str(folder))
    item = favorites.items[0]
    folder.rmdir()
    assert not favorites.importFavorite(item['id'])
    assert favorites.items == [item]
    assert favorites.replace(item['id'], str(tmp_path))


def test_favorite_import_uses_existing_import_pipeline(tmp_path, monkeypatch):
    p = panel()
    favorites = p.favoriteDirectories
    assert favorites.add(str(tmp_path))
    received = []
    monkeypatch.setattr(p, '_start_import', lambda paths: received.append(paths) or True)
    assert favorites.importFavorite(favorites.items[0]['id'])
    assert received == [[str(tmp_path)]]


def test_app_rejects_local_import_when_local_source_is_disabled():
    from types import SimpleNamespace
    from qt_dicom_viewer.ui.app_controller import AppController
    app = SimpleNamespace(_pacs_controller=SimpleNamespace(localEnabled=False, busy=False))
    assert AppController._series_import_blocker(app, 'local')


def test_corrupt_or_mixed_settings_preserve_valid_entries_without_directory_checks(tmp_path):
    import json
    from qt_dicom_viewer.settings.favorite_directories import FavoriteDirectoriesStore
    store = tmp_path / 'favorites.json'
    store.write_text('{broken')
    assert FavoriteDirectoriesStore(store).items == []
    valid = dict(id='one', name='Disconnected', path=str(tmp_path / 'offline'))
    store.write_text(json.dumps(dict(version=1, items=[None, {}, valid, valid, dict(id='two', name='bad', path='relative')])))
    assert FavoriteDirectoriesStore(store).items == [valid]


def test_failed_write_preserves_existing_disk_and_memory(tmp_path, monkeypatch):
    from qt_dicom_viewer.settings import favorite_directories as module
    p = panel(tmp_path / 'favorites.json')
    favorites = p.favoriteDirectories
    assert favorites.add(str(tmp_path))
    before = favorites.items
    disk_before = (tmp_path / 'favorites.json').read_bytes()
    class FailedSave:
        def __init__(self, *args): pass
        def open(self, *args): return False
        def errorString(self): return 'Read-only filesystem'
    monkeypatch.setattr(module, 'QSaveFile', FailedSave)
    assert not favorites.rename(before[0]['id'], 'Changed')
    assert favorites.items == before
    assert (tmp_path / 'favorites.json').read_bytes() == disk_before


def test_directory_symlink_deduplication_and_item_copy(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    alias = tmp_path / 'alias'
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip('directory symlinks unavailable')
    p = panel()
    favorites = p.favoriteDirectories
    assert favorites.add(str(real))
    assert not favorites.add(str(alias))
    snapshot = favorites.items
    snapshot[0]['name'] = 'mutated'
    assert favorites.items[0]['name'] == 'real'


def test_favorite_limit_and_memory_only_settings(tmp_path):
    p = panel(False)
    favorites = p.favoriteDirectories
    for index in range(32):
        folder = tmp_path / str(index)
        folder.mkdir()
        assert favorites.add(str(folder))
    extra = tmp_path / 'extra'
    extra.mkdir()
    assert not favorites.add(str(extra))
    assert len(favorites.items) == 32
    assert panel(False).favoriteDirectories.items == []
    assert not (tmp_path / 'favorite-directories.json').exists()


def test_unreadable_directory_rejected(tmp_path, monkeypatch):
    import os
    p = panel()
    monkeypatch.setattr(os, 'access', lambda *args: False)
    assert not p.favoriteDirectories.add(str(tmp_path))
    assert p.favoriteDirectories.items == []
    assert p.importError
