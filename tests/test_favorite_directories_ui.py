"""Physical Qt clicks through favorites, with visible UI and resulting state checks."""
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.ui.controller.panel_controller import PanelController
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
from qt_dicom_viewer.ui.dialogs.favorite_directories_dialog import FavoriteDirectoriesDialog
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find, click


def shot(widget, name):
    import os
    directory = os.environ.get('FAVORITES_UI_SCREENSHOTS')
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        QTest.qWait(80)
        pixmap = widget.grabWindow() if hasattr(widget, 'grabWindow') else widget.grab()
        assert pixmap.save(str(target / (name + '.png')))


def drag_row(table, source, target, cancel=False):
    a = table.visualRect(table.model().index(source, 0)).center()
    rect = table.visualRect(table.model().index(target, 0))
    b = rect.center()
    b.setY(rect.bottom() - 2 if target > source else rect.top() + 2)
    QTest.mousePress(table.viewport(), Qt.LeftButton, Qt.NoModifier, a)
    for step in range(1, 11):
        QTest.mouseMove(table.viewport(), a + (b - a) * (step / 10), 20)
    if cancel:
        QTest.keyClick(table, Qt.Key_Escape)
    QTest.mouseRelease(table.viewport(), Qt.LeftButton, Qt.NoModifier, b)
    QTest.qWait(30)


def test_picker_and_manager_clicks_persist(qt_app, tmp_path, monkeypatch):
    from qt_dicom_viewer.ui.dialogs import favorite_directories_dialog as module
    from qt_dicom_viewer.i18n import localize, message
    directory = tmp_path / '影像目录'
    second, replacement = tmp_path / 'Second', tmp_path / 'Replacement'
    for path in (directory, second, replacement):
        path.mkdir()
    store = tmp_path / 'favorites.json'
    panel = PanelController(favorite_path=store)
    favorites = panel.favoriteDirectories
    picker = LocalImportDialog(str(directory), favorites=favorites)
    picker.show()
    try:
        button = picker.findChild(QObject, 'importFavoriteCurrent')
        wait_until(lambda: button.isEnabled())
        # Uncommitted address edits must not favorite the previous directory.
        picker.path_edit.setText(str(second))
        assert not button.isEnabled() and not favorites.items
        picker.path_edit.setText(str(directory))
        assert button.isEnabled()
        QTest.mouseClick(button, Qt.LeftButton)
        wait_until(lambda: not favorites.busy)
        assert favorites.items[0]['path'] == str(directory)
        assert not panel.scanning
        assert not button.isEnabled()
        assert button.text() == localize(message('favorites.saved'))
        shot(picker, 'picker-favorited')
    finally:
        picker.close()
        delete(picker)
    manager = FavoriteDirectoriesDialog(favorites)
    manager.show()
    try:
        monkeypatch.setattr(module.QFileDialog, 'getExistingDirectory', lambda *args: str(second))
        QTest.mouseClick(manager.add_button, Qt.LeftButton)
        wait_until(lambda: not favorites.busy)
        assert manager.table.rowCount() == 2
        manager.table.selectRow(0)
        manager.name.selectAll()
        QTest.keyClicks(manager.name, 'Reference scans')
        QTest.mouseClick(manager.rename_button, Qt.LeftButton)
        assert favorites.items[0]['name'] == 'Reference scans'
        drag_row(manager.table, 0, 1)
        assert favorites.items[1]['name'] == 'Reference scans'
        assert manager.table.currentRow() == 1
        before = favorites.items
        drag_row(manager.table, 1, 0, cancel=True)
        assert favorites.items == before
        assert manager.table.currentRow() == 1
        assert manager.table.selectionModel().selectedRows()[0].row() == 1
        assert manager.name.text() == favorites.items[1]["name"]
        shot(manager, 'manager-dark')
        monkeypatch.setattr(module.QFileDialog, 'getExistingDirectory', lambda *args: str(replacement))
        QTest.mouseClick(manager.replace_button, Qt.LeftButton)
        wait_until(lambda: not favorites.busy)
        assert favorites.items[1]['path'] == str(replacement)
        assert manager.path.text() == str(replacement)
        drag_row(manager.table, 1, 0)
        manager.table.selectRow(1)
        QTest.mouseClick(manager.remove_button, Qt.LeftButton)
        assert manager.table.rowCount() == 1
        reloaded_panel = PanelController(favorite_path=store)
        reloaded = FavoriteDirectoriesDialog(reloaded_panel.favoriteDirectories)
        reloaded.show()
        try:
            assert reloaded.table.item(0, 0).text() == 'Reference scans'
            assert reloaded.path.text() == str(replacement)
            shot(reloaded, 'manager-reloaded')
        finally:
            reloaded.close()
            delete(reloaded)
        assert not panel.scanning
    finally:
        manager.close()
        delete(manager)



def test_inline_favorites_navigation_and_import(scene, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from test_series_sidebar import phantom_series
    window, app, warnings = scene
    source = tmp_path / 'Synthetic CT'
    source.mkdir()
    record = phantom_series(source, 1, 'DEMO', '1.2.3.4', '20261029')
    offline = tmp_path / 'Offline'
    offline.mkdir()
    favorites = app.panelController.favoriteDirectories
    assert favorites.add(str(source)) and favorites.add(str(offline))
    offline.rmdir()
    app.panelController._last_import_directory = str(tmp_path)
    errors, opened = [], []
    def choose():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, LocalImportDialog)
            wait_until(lambda: not dialog._loading)
            listing = dialog.favorite_list
            assert listing.isVisible() and listing.count() == 2
            # Missing favorite keeps both saved entries and the last valid folder.
            QTest.mouseClick(listing.viewport(), Qt.LeftButton, Qt.NoModifier,
                            listing.visualItemRect(listing.item(1)).center())
            wait_until(lambda: not dialog._loading)
            assert dialog._directory == str(tmp_path)
            assert len(favorites.items) == 2
            assert dialog.selection_label.text()
            QTest.mouseClick(listing.viewport(), Qt.LeftButton, Qt.NoModifier,
                            listing.visualItemRect(listing.item(0)).center())
            wait_until(lambda: not dialog._loading and dialog._directory == str(source))
            assert dialog.model.rowCount() == 3
            shot(dialog, 'inline-favorites-dark')
            opened.append(True)
            QTest.mouseClick(dialog.open_button, Qt.LeftButton)
        except BaseException as error:
            errors.append(error)
            if dialog:
                dialog.reject()
    QTimer.singleShot(120, choose)
    click(window, find(window, 'homeOpenImport'))
    assert opened == [True] and not errors, errors
    wait_until(lambda: not app.panelController.scanning and bool(app.panelController.seriesItems), 15000)
    click(window, find(window, 'series-' + record.series_instance_uid))
    click(window, find(window, 'homeOpenSelected'))
    wait_until(lambda: app.workspaceController.activeViewport is not None
               and app.workspaceController.activeViewport.loadState == 'ready', 15000)
    assert not window.findChild(QObject, 'sidebarFavoriteDirectories')
    assert not window.findChild(QObject, 'compactSidebarFavoriteDirectories')
    shot(window, 'inline-favorite-imported')
    assert not warnings, warnings


def test_inline_favorites_many_resize_manage_and_reload(scene, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    window, app, warnings = scene
    favorites = app.panelController.favoriteDirectories
    for i in range(12):
        directory = tmp_path / ('Directory-' + str(i))
        directory.mkdir()
        assert favorites.add(str(directory))
    app.settingsController.setValue('appearance', 'theme', 'light')
    picker = LocalImportDialog(str(tmp_path), favorites=favorites)
    picker.show()
    try:
        wait_until(lambda: not picker._loading)
        for width in (880, 620):
            picker.resize(width, 560)
            QTest.qWait(60)
            listing = picker.favorite_list
            assert listing.height() <= 80
            assert listing.verticalScrollBar().maximum() > 0
            assert listing.horizontalScrollBar().maximum() == 0
            assert picker.view.height() >= 100
            shot(picker, 'inline-favorites-light-' + str(width))
        last = picker.favorite_list.item(11)
        picker.favorite_list.scrollToItem(last)
        QTest.qWait(30)
        QTest.mouseClick(picker.favorite_list.viewport(), Qt.LeftButton, Qt.NoModifier,
                        picker.favorite_list.visualItemRect(last).center())
        wait_until(lambda: not picker._loading and picker._directory == str(tmp_path / 'Directory-11'))
        assert picker.favorite_button.isEnabled() is False
        scroll = picker.favorite_list.verticalScrollBar().value()
        assert scroll > 0
        assert favorites.rename(favorites.items[11]['id'], 'Renamed last')
        QTest.qWait(20)
        assert picker.favorite_list.verticalScrollBar().value() == scroll
        errors, managed = [], []
        def manage():
            dialog = QApplication.activeModalWidget()
            try:
                assert isinstance(dialog, FavoriteDirectoriesDialog)
                dialog.name.setText('New favorite name')
                QTest.mouseClick(dialog.rename_button, Qt.LeftButton)
                managed.append(True)
            except BaseException as error:
                errors.append(error)
            finally:
                if dialog:
                    dialog.accept()
        QTimer.singleShot(100, manage)
        QTest.mouseClick(picker.manage_favorites, Qt.LeftButton)
        assert managed and not errors, errors
        assert picker.favorite_list.item(0).text() == 'New favorite name'
        panel = PanelController(favorite_path=favorites._store.path)
        restored = LocalImportDialog(str(tmp_path), favorites=panel.favoriteDirectories)
        restored.show()
        try:
            assert restored.favorite_list.count() == 12
            assert restored.favorite_list.item(0).text() == 'New favorite name'
        finally:
            restored.close()
            delete(restored)
    finally:
        picker.close()
        delete(picker)
    assert not warnings, warnings


def test_favorite_keyboard_stays_in_picker_and_preserves_selection(qt_app, tmp_path, monkeypatch):
    from PySide6.QtCore import QItemSelectionModel
    first, second = tmp_path / 'one' / 'CT', tmp_path / 'two' / 'CT'
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (second / 'image.dcm').write_bytes(b'test')
    panel = PanelController(favorite_path=tmp_path / 'favorites.json')
    favorites = panel.favoriteDirectories
    assert favorites.add(str(first)) and favorites.add(str(second))
    picker = LocalImportDialog(str(first), favorites=favorites)
    picker.show()
    try:
        wait_until(lambda: not picker._loading)
        listing = picker.favorite_list
        assert listing.item(0).text() != listing.item(1).text()
        listing.setCurrentRow(1)
        listing.setFocus()
        QTest.keyClick(listing, Qt.Key_Return)
        wait_until(lambda: not picker._loading and picker._directory == str(second))
        assert picker.isVisible() and not picker.paths
        index = picker.model.index(str(second / 'image.dcm'))
        picker.view.selectionModel().select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        before = picker._navigation_id
        QTest.mouseClick(listing.viewport(), Qt.LeftButton, Qt.NoModifier,
                        listing.visualItemRect(listing.item(1)).center())
        assert picker._navigation_id == before
        assert picker.selected_paths() == [str(second / 'image.dcm')]
        QTest.keyClick(listing, Qt.Key_Space)
        assert picker.isVisible() and picker._navigation_id == before
        close = picker.favorite_remove
        assert close.isVisible()
        assert listing.visualItemRect(listing.item(1)).contains(close.geometry())
        shot(picker, 'active-close')
        # Failed persistence retains the item and the current file selection.
        with monkeypatch.context() as patch:
            def fail_save(items):
                raise OSError('read only')
            patch.setattr(favorites._store, 'save', fail_save)
            QTest.mouseClick(close, Qt.LeftButton)
            assert len(favorites.items) == 2 and close.isVisible()
        QTest.mouseClick(close, Qt.LeftButton)
        assert [entry['path'] for entry in favorites.items] == [str(first)]
        restored = PanelController(favorite_path=tmp_path / 'favorites.json')
        assert restored.favoriteDirectories.items == favorites.items
        assert picker._navigation_id == before and picker._directory == str(second)
        assert picker.selected_paths() == [str(second / 'image.dcm')]
        assert (second / 'image.dcm').exists() and picker.isVisible()
        assert picker.favorite_button.isEnabled() and not close.isVisible()
        QTest.mouseClick(listing.viewport(), Qt.LeftButton, Qt.NoModifier,
                        listing.visualItemRect(listing.item(0)).center())
        wait_until(lambda: not picker._loading and picker._directory == str(first))
        QTest.mouseClick(close, Qt.LeftButton)
        assert not favorites.items and not listing.isVisible() and not close.isVisible()
        assert picker._directory == str(first) and picker.favorite_button.isEnabled()
    finally:
        picker.close()
        delete(picker)


def test_rename_only_enabled_for_changed_nonempty_name(qt_app, tmp_path):
    panel = PanelController()
    assert panel.favoriteDirectories.add(str(tmp_path))
    dialog = FavoriteDirectoriesDialog(panel.favoriteDirectories)
    dialog.show()
    try:
        assert not dialog.rename_button.isEnabled()
        dialog.name.setText('   ')
        assert not dialog.rename_button.isEnabled()
        dialog.name.setText('New name')
        assert dialog.rename_button.isEnabled()
        QTest.mouseClick(dialog.rename_button, Qt.LeftButton)
        assert panel.favoriteDirectories.items[0]['name'] == 'New name'
        assert not dialog.rename_button.isEnabled()
    finally:
        dialog.close()
        delete(dialog)
