import time
from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from shiboken6 import delete
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_settings_redesign import open_page
from test_tag_qml import find
from qt_dicom_viewer.ui.controller.panel_controller import PanelController
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
from qt_dicom_viewer.ui.dialogs.favorite_directories_dialog import FavoriteDirectoriesDialog


def test_preview_reflects_style(scene, tmp_path):
    window, app, warnings = open_page(scene, 'corners')
    board = find(window, 'cornerEditorBoard')
    QTest.qWait(100)
    def shot():
        image = window.grabWindow()
        ratio = image.devicePixelRatio()
        p = board.mapToScene(QPointF())
        return image.copy(int(p.x()*ratio), int(p.y()*ratio), int(board.width()*ratio), int(board.height()*ratio))
    before = shot()
    for k,v in [('fontSize',20), ('lineHeight',1.8), ('colorMode','custom'), ('color','#00ff00')]:
        assert app.settingsController.setValue('corners',k,v)
    QTest.qWait(100)
    after = shot()
    assert before.save(str(tmp_path / 'corner-before.png'))
    assert after.save(str(tmp_path / 'corner-after.png'))
    from test_favorite_directories_ui import shot as save_ui
    save_ui(window, 'corner-styled')
    assert before != after
    # A taller styled row must still use the right insertion slot.
    from test_settings_redesign import drag_corner
    original = app.settingsController.values['corners']['topLeft'][:]
    drag_corner(window, 'topLeft', 0, 1)
    assert app.settingsController.values['corners']['topLeft'] == [original[1], original[0], *original[2:]]
    assert not warnings, warnings


def test_slow_favorite_add_keeps_ui_responsive(qt_app, tmp_path, monkeypatch):
    from qt_dicom_viewer.ui.controller import favorite_directories_controller as module
    panel = PanelController()
    picker = LocalImportDialog(str(tmp_path), favorites=panel.favoriteDirectories)
    picker.show()
    try:
        wait_until(lambda: not picker._loading)
        ticks=[]
        timer=QTimer(); timer.setInterval(10); timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        original = module.os.scandir
        def slow(path):
            time.sleep(.3)
            return original(path)
        monkeypatch.setattr(module.os,'scandir',slow)
        start=time.monotonic()
        QTest.mouseClick(picker.favorite_button,Qt.LeftButton)
        elapsed=time.monotonic()-start
        QTest.qWait(60)
        timer.stop()
        assert elapsed < .2 and ticks
        wait_until(lambda: len(panel.favoriteDirectories.items) == 1)
    finally:
        picker.close(); delete(picker)


def test_deactivate_during_favorite_drag(qt_app,tmp_path):
    panel=PanelController()
    for name in ['one','two','three']:
        p=tmp_path/name; p.mkdir(); panel.favoriteDirectories.add(str(p))
    dialog=FavoriteDirectoriesDialog(panel.favoriteDirectories); dialog.show(); dialog.activateWindow()
    QTest.qWaitForWindowActive(dialog)
    table=dialog.table
    a=table.visualRect(table.model().index(0,0)).center()
    b=table.visualRect(table.model().index(2,0)).center()
    QTest.mousePress(table.viewport(),Qt.LeftButton,Qt.NoModifier,a)
    QTest.mouseMove(table.viewport(),b,50)
    assert table._dragging
    other=QDialog(); other.show(); other.activateWindow()
    QTest.qWaitForWindowActive(other)
    assert not dialog.isActiveWindow()
    canceled = not table._dragging and not table._scroll.isActive()
    before=panel.favoriteDirectories.items
    QTest.mouseRelease(table.viewport(),Qt.LeftButton,Qt.NoModifier,b)
    unchanged = before == panel.favoriteDirectories.items
    other.close(); dialog.close(); delete(other); delete(dialog)
    assert canceled and unchanged


def test_destroyed_picker_callback(qt_app,tmp_path):
    panel=PanelController()
    panel.favoriteDirectories.add(str(tmp_path))
    picker=LocalImportDialog(str(tmp_path),favorites=panel.favoriteDirectories)
    picker.show()
    picker.resize(940,600)
    picker.close()
    delete(picker)
    QTest.qWait(40)


def test_closing_picker_discards_validation_and_late_result(qt_app, tmp_path, monkeypatch):
    from threading import Event
    gate = Event()
    entered = Event()
    panel = PanelController()
    favorites = panel.favoriteDirectories
    first = tmp_path / 'first'; first.mkdir()
    second = tmp_path / 'second'; second.mkdir()
    def check(path):
        if path == str(first):
            entered.set()
            gate.wait(3)
        return path
    monkeypatch.setattr(favorites, '_checked_directory', check)
    picker = LocalImportDialog(str(first), favorites=favorites)
    picker.show()
    try:
        wait_until(lambda: not picker._loading)
        QTest.mouseClick(picker.favorite_button, Qt.LeftButton)
        wait_until(entered.is_set)
        assert favorites.busy and not picker.favorite_button.isEnabled()
        assert not favorites.requestAdd(str(second))
        picker.close()
        assert not favorites.busy
        gate.set()
        wait_until(lambda: not favorites._validation_results.empty())
        assert favorites.requestAdd(str(second))
        wait_until(lambda: not favorites.busy)
        assert [item['path'] for item in favorites.items] == [str(second)]
    finally:
        gate.set(); picker.close(); delete(picker)


def test_async_validation_rechecks_target_and_duplicates(qt_app, tmp_path, monkeypatch):
    from threading import Event
    first = tmp_path / 'first'; first.mkdir()
    second = tmp_path / 'second'; second.mkdir()
    panel = PanelController(favorite_path=tmp_path / 'favorites.json')
    favorites = panel.favoriteDirectories
    assert favorites.add(str(first))
    identifier = favorites.items[0]['id']
    gate = Event()
    def check(path):
        gate.wait(3)
        return path
    monkeypatch.setattr(favorites, '_checked_directory', check)
    try:
        assert favorites.requestReplacement(identifier, str(second))
        assert favorites.remove(identifier)
        gate.set()
        wait_until(lambda: not favorites.busy)
        assert not favorites.items and favorites.isError
        gate.clear()
        assert favorites.requestAdd(str(second))
        # Another accepted change wins while the background check is pending.
        assert favorites._add_checked(str(second))
        gate.set()
        wait_until(lambda: not favorites.busy)
        assert len(favorites.items) == 1 and favorites.isError
        restored = PanelController(favorite_path=tmp_path / 'favorites.json')
        assert restored.favoriteDirectories.items == favorites.items
    finally:
        gate.set(); favorites.cancelValidation()


def test_async_validation_failure_preserves_saved_favorites(qt_app, tmp_path, monkeypatch):
    panel = PanelController(favorite_path=tmp_path / 'favorites.json')
    favorites = panel.favoriteDirectories
    assert favorites.add(str(tmp_path))
    original = favorites.items
    disk = (tmp_path / 'favorites.json').read_bytes()
    assert favorites.requestReplacement(original[0]['id'], str(tmp_path / 'missing'))
    wait_until(lambda: not favorites.busy)
    assert favorites.isError and favorites.items == original
    folder = tmp_path / 'new'; folder.mkdir()
    def fail_save(items):
        raise OSError('Read only')
    monkeypatch.setattr(favorites._store, 'save', fail_save)
    assert favorites.requestAdd(str(folder))
    wait_until(lambda: not favorites.busy)
    assert favorites.isError and favorites.items == original
    assert (tmp_path / 'favorites.json').read_bytes() == disk
