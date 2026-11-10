"""Recent sources reflect completed local imports, never extracted/cache files."""
import json
from pathlib import Path
from threading import Event
import zipfile
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QObject
from PySide6.QtWidgets import QListWidget
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest

from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.ui.controller.panel_controller import PanelController
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
from test_dicom_tags import make_dicom, qt_app, wait_until


def panel(tmp_path):
    return PanelController(series_catalog=SeriesCatalog(), recent_path=tmp_path / 'recent.json')


def complete_import(controller, paths):
    assert controller._start_import([str(path) for path in paths])
    wait_until(lambda: not controller.scanning, 15000)


def test_successful_sources_persist_deduplicate_and_limit(qt_app, tmp_path):
    controller = panel(tmp_path)
    folder = tmp_path / 'images'
    folder.mkdir()
    files = [folder / f'{index:02d}.dcm' for index in range(12)]
    for index, path in enumerate(files):
        make_dicom(path, index + 1)
        complete_import(controller, [path])
    expected = [str(path) for path in reversed(files[2:])]
    assert controller.recentImagePaths.items == expected
    reloaded = panel(tmp_path)
    assert reloaded.recentImagePaths.items == expected
    assert reloaded.recentImagePaths.last_directory == str(folder)
    alias = tmp_path / 'alias.dcm'
    alias.symlink_to(files[2])
    complete_import(controller, [alias])
    assert controller.recentImagePaths.items == [str(files[2]), *expected[:-1]]
    assert len(controller.recentImagePaths.items) == 10


def test_mixed_selection_records_valid_files_directories_and_outer_archives(qt_app, tmp_path):
    controller = panel(tmp_path)
    folder = tmp_path / 'series'
    folder.mkdir()
    image = folder / 'image.dcm'
    make_dicom(image)
    archive = tmp_path / 'images.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.write(image, image.name)
    text = tmp_path / 'notes.txt'
    text.write_text('not an image')
    empty = tmp_path / 'empty'
    empty.mkdir()
    complete_import(controller, [folder, image, archive, empty, text])
    assert controller.recentImagePaths.items == [str(folder), str(image), str(archive)]
    assert controller.recentImagePaths.last_directory == str(folder)
    controller.cleanup_imports()
    assert archive.is_file() and image.is_file()


def test_failure_empty_and_cancelled_scans_leave_history_unchanged(qt_app, tmp_path, monkeypatch):
    controller = panel(tmp_path)
    image = tmp_path / 'image.dcm'
    make_dicom(image)
    complete_import(controller, [image])
    before = (tmp_path / 'recent.json').read_bytes()
    complete_import(controller, [tmp_path / 'missing'])
    empty = tmp_path / 'empty'
    empty.mkdir()
    complete_import(controller, [empty])
    entered, release = Event(), Event()
    original_prepare = controller._import_store.prepare
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_prepare(*args, **kwargs)
    monkeypatch.setattr(controller._import_store, 'prepare', delayed)
    assert controller._start_import([str(tmp_path)])
    try:
        wait_until(entered.is_set)
        controller.cancelImport()
    finally:
        release.set()
    wait_until(lambda: not controller.scanning)
    assert (tmp_path / 'recent.json').read_bytes() == before


def test_loading_missing_history_does_not_probe_saved_paths_and_clear_preserves_sources(qt_app, tmp_path, monkeypatch):
    controller = panel(tmp_path)
    image = tmp_path / 'image.dcm'
    make_dicom(image)
    complete_import(controller, [image])
    original = Path.stat
    def guarded(path, *args, **kwargs):
        if path in (image, tmp_path):
            raise AssertionError('Loading history must not probe saved sources')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'stat', guarded)
        restored = panel(tmp_path)
        assert restored.recentImagePaths.items == [str(image)]
    assert restored.recentImagePaths.clear()
    assert not panel(tmp_path).recentImagePaths.items
    assert image.is_file()
    assert restored.recentImagePaths.last_directory == ''


def test_picker_reopens_history_and_missing_entry_can_be_removed(qt_app, tmp_path):
    controller = panel(tmp_path)
    image = tmp_path / 'image.dcm'
    make_dicom(image)
    complete_import(controller, [image])
    picker = LocalImportDialog(str(tmp_path), recent=controller.recentImagePaths)
    picker.show()
    try:
        wait_until(lambda: not picker._loading)
        listing = picker.findChild(QListWidget, 'importRecentPaths')
        assert listing is not None and listing.isVisible()
        item = listing.item(0)
        assert item.data(Qt.UserRole) == str(image)
        QTest.mouseClick(listing.viewport(), Qt.LeftButton, pos=listing.visualItemRect(item).center())
        wait_until(lambda: not picker._loading and not picker.isVisible())
        assert picker.paths == [str(image)]
    finally:
        picker.close()
        picker.deleteLater()
    image.unlink()
    picker = LocalImportDialog(str(tmp_path), recent=controller.recentImagePaths)
    picker.show()
    try:
        wait_until(lambda: not picker._loading)
        listing = picker.findChild(QListWidget, 'importRecentPaths')
        item = listing.item(0)
        QTest.mouseClick(listing.viewport(), Qt.LeftButton, pos=listing.visualItemRect(item).center())
        wait_until(lambda: not picker._loading)
        assert picker.isVisible() and not picker.paths
        assert str(image) in picker.selection_label.text()
        assert controller.recentImagePaths.items == [str(image)]
        listing.setFocus()
        QTest.keyClick(listing, Qt.Key_Delete)
        assert not controller.recentImagePaths.items
        assert not listing.isVisible()
    finally:
        picker.close()
        picker.deleteLater()


def test_recent_malformed_history_and_failed_persistence_are_non_destructive(qt_app, tmp_path):
    history = tmp_path / 'recent.json'
    history.write_text('{broken')
    controller = panel(tmp_path)
    assert not controller.recentImagePaths.items
    history.write_text(json.dumps({'version': 1, 'items': [1, '', 'relative', '/a\u0000'], 'directory': 42}))
    assert not panel(tmp_path).recentImagePaths.items
    history.unlink()
    history.mkdir()
    image = tmp_path / 'image.dcm'
    make_dicom(image)
    complete_import(controller, [image])
    assert controller.hasSeries
    assert not controller.recentImagePaths.items
    assert controller.recentImagePaths.message
    assert controller.recentImagePaths.message in controller.statusMessage


def test_restart_reads_recent_sources_and_starting_directory_in_new_process(qt_app, tmp_path):
    controller = panel(tmp_path)
    folder = tmp_path / 'images'
    folder.mkdir()
    make_dicom(folder / 'image.dcm')
    complete_import(controller, [folder])
    script = '''import json, sys
from qt_dicom_viewer.settings.recent_image_paths import RecentImagePathsStore
history = RecentImagePathsStore(sys.argv[1])
print(json.dumps([history.items, history.directory]))
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'recent.json')],
                            check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(result.stdout) == [[str(folder)], str(folder)]


def test_cancel_after_partial_image_publication_does_not_record_source(qt_app, tmp_path, monkeypatch):
    from qt_dicom_viewer.core import dicom_scanner
    from qt_dicom_viewer.ui.workers.dicom_scan_worker import DicomScanWorker
    controller = panel(tmp_path)
    first, second = tmp_path / 'first.dcm', tmp_path / 'second.dcm'
    make_dicom(first, 1)
    make_dicom(second, 2)
    entered, release = Event(), Event()
    read_frames = dicom_scanner._read_frames
    def delayed(path):
        if path == second:
            entered.set()
            assert release.wait(5)
        return read_frames(path)
    monkeypatch.setattr(dicom_scanner, '_read_frames', delayed)
    monkeypatch.setattr(DicomScanWorker, 'process_report_interval', 0)
    assert controller._start_import([str(first), str(second)])
    try:
        wait_until(lambda: entered.is_set() and controller.hasSeries)
        controller.cancelImport()
    finally:
        release.set()
    wait_until(lambda: not controller.scanning)
    assert not controller.recentImagePaths.items
    assert not (tmp_path / 'recent.json').exists()


def test_busy_blocked_and_pacs_cache_imports_do_not_enter_history(qt_app, tmp_path):
    owner = QObject()
    cache = tmp_path / 'pacs-cache'
    cache.mkdir()
    image = cache / 'image.dcm'
    make_dicom(image)
    owner._pacs_controller = SimpleNamespace(_import_root=cache)
    controller = PanelController(owner, SeriesCatalog(), recent_path=tmp_path / 'recent.json')
    controller._scanning = True
    assert not controller._start_import([str(image)])
    controller._scanning = False
    controller._import_blocker = lambda: 'PACS transfer running'
    assert not controller._start_import([str(image)])
    controller._import_blocker = lambda: ''
    complete_import(controller, [image])
    assert controller.hasSeries and not controller.recentImagePaths.items


@pytest.mark.parametrize(('key', 'modifier'), [(Qt.Key_Return, Qt.NoModifier), (Qt.Key_Enter, Qt.KeypadModifier)])
def test_recent_list_keyboard_opens_selected_source(qt_app, tmp_path, key, modifier):
    controller = panel(tmp_path)
    first, second = tmp_path / 'first.dcm', tmp_path / 'second.dcm'
    make_dicom(first, 1)
    make_dicom(second, 2)
    complete_import(controller, [first, second])
    picker = LocalImportDialog(str(tmp_path), recent=controller.recentImagePaths)
    picker.show()
    picker.activateWindow()
    try:
        wait_until(lambda: not picker._loading)
        listing = picker.findChild(QListWidget, 'importRecentPaths')
        assert listing is not None
        listing.setCurrentRow(0)
        listing.setFocus(Qt.TabFocusReason)
        QTest.keyClick(listing, Qt.Key_Down)
        QTest.keyClick(listing, key, modifier)
        wait_until(lambda: not picker._loading and not picker.isVisible())
        assert picker.paths == [str(second)]
    finally:
        picker.close()
        picker.deleteLater()


@pytest.mark.parametrize('action', ['context', 'delete', 'backspace'])
def test_remove_recent_row_preserves_sources_favorites_and_other_records(qt_app, tmp_path, action):
    controller = panel(tmp_path)
    folder = tmp_path / 'images'
    folder.mkdir()
    files = [folder / 'first.dcm', folder / 'second.dcm']
    for i, path in enumerate(files): make_dicom(path, i+1)
    complete_import(controller, files)
    assert controller.favoriteDirectories.add(str(folder))
    picker = LocalImportDialog(str(tmp_path), favorites=controller.favoriteDirectories,
                               recent=controller.recentImagePaths)
    picker.show()
    picker.activateWindow()
    try:
        wait_until(lambda: not picker._loading)
        listing = picker.findChild(QListWidget, 'importRecentPaths')
        assert listing is not None
        listing.setCurrentRow(0)
        listing.setFocus(Qt.TabFocusReason)
        if action == 'context':
            # Context targeting must remove the right-clicked second row, not the old selection.
            point = listing.visualItemRect(listing.item(1)).center()
            event = QContextMenuEvent(QContextMenuEvent.Mouse, point, listing.viewport().mapToGlobal(point))
            qt_app.sendEvent(listing.viewport(), event)
            from PySide6.QtWidgets import QMenu
            menu = picker.findChild(QMenu, 'importRecentMenu')
            assert menu is not None and menu.isVisible()
            QTest.keyClick(menu, Qt.Key_Down)
            QTest.keyClick(menu, Qt.Key_Return)
            remaining = str(files[0])
        else:
            QTest.keyClick(listing, Qt.Key_Delete if action == 'delete' else Qt.Key_Backspace)
            remaining = str(files[1])
        assert picker.isVisible() and not picker.paths
        assert controller.recentImagePaths.items == [remaining]
        assert all(path.is_file() for path in files)
        assert controller.favoriteDirectories.items[0]['path'] == str(folder)
        assert picker.favorite_list.isVisible()
        assert panel(tmp_path).recentImagePaths.items == [remaining]
    finally:
        picker.close()
        picker.deleteLater()


@pytest.mark.parametrize('size', [(1040, 640), (620, 400)])
@pytest.mark.parametrize('keyboard', [False, True])
def test_active_recent_clear_removes_only_selected_row_without_opening(qt_app, tmp_path, keyboard, size):
    from PySide6.QtWidgets import QPushButton
    controller = panel(tmp_path)
    sources = [tmp_path / f'image-{i}.dcm' for i in range(8)]
    for i, source in enumerate(sources): make_dicom(source, i+1)
    complete_import(controller, sources)
    picker = LocalImportDialog(str(tmp_path), recent=controller.recentImagePaths)
    picker.show(); picker.activateWindow(); picker.resize(*size)
    try:
        wait_until(lambda: not picker._loading)
        listing = picker.recent_list
        listing.setCurrentRow(7)
        listing.scrollToItem(listing.currentItem())
        QTest.qWait(50)
        clear = picker.findChild(QPushButton, 'importRecentRowClear')
        assert clear is not None and clear.isVisible()
        assert listing.visualItemRect(listing.currentItem()).contains(clear.geometry())
        if keyboard:
            clear.setFocus(Qt.TabFocusReason)
            QTest.keyClick(clear, Qt.Key_Return)
        else:
            QTest.mouseClick(clear, Qt.LeftButton)
        assert picker.isVisible() and not picker.paths
        assert controller.recentImagePaths.items == [str(p) for p in sources[:7]]
        assert all(p.is_file() for p in sources)
        QTest.qWait(50)
        assert listing.visualItemRect(listing.currentItem()).contains(clear.geometry())
    finally:
        picker.close(); picker.deleteLater()


@pytest.mark.parametrize('keyboard', [False, True])
def test_recent_clear_all_keeps_favorites_source_files_and_current_directory(qt_app, tmp_path, keyboard):
    from PySide6.QtWidgets import QPushButton
    controller = panel(tmp_path)
    source = tmp_path / 'image.dcm'
    make_dicom(source)
    complete_import(controller, [source])
    assert controller.favoriteDirectories.add(str(tmp_path))
    picker = LocalImportDialog(str(tmp_path), favorites=controller.favoriteDirectories,
                               recent=controller.recentImagePaths)
    picker.show(); picker.activateWindow()
    try:
        wait_until(lambda: not picker._loading)
        clear = picker.findChild(QPushButton, 'importRecentClearAll')
        assert clear is not None and clear.isVisible() and clear.isEnabled()
        if keyboard:
            clear.setFocus(Qt.TabFocusReason)
            QTest.keyClick(clear, Qt.Key_Enter, Qt.KeypadModifier)
        else:
            QTest.mouseClick(clear, Qt.LeftButton)
        assert picker.isVisible() and not picker.paths
        assert not controller.recentImagePaths.items and not panel(tmp_path).recentImagePaths.items
        assert source.is_file() and len(controller.favoriteDirectories.items) == 1
        assert picker._directory == str(tmp_path)
        assert not clear.isEnabled()
        assert picker.open_button.isEnabled()
    finally:
        picker.close(); picker.deleteLater()
