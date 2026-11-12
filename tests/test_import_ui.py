"""Mixed file/folder picker and one-click QML integration."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QTimer, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton
from shiboken6 import delete

from voxplane.ui.dialogs.local_import_dialog import LocalImportDialog
from test_dicom_tags import qt_app as qt_app, wait_until
from test_pacs_qml import scene as scene
from test_tag_qml import find, click, descendants, settled_point


@pytest.mark.parametrize(
    "entry", ["homeOpenImport", "sidebarOpenFolder", "compactSidebarImport", "shortcut"]
)
def test_single_click_opens_mixed_picker(scene, entry, tmp_path):
    window, app, warnings = scene
    app.panelController._last_import_directory = str(tmp_path)
    # This checks each import action, not automatic screen adaptation (covered
    # by test_window_sizing). Native Windows may clamp resizes to a tiny desktop,
    # so explicitly select the sidebar presentation before clicking its action.
    sidebar = find(window, "sidebarContainer")
    sidebar.setProperty("compactRequired", False)
    sidebar.setProperty("collapsed", False)
    if entry == "sidebarOpenFolder":
        sidebar.setProperty("expandedWidth", sidebar.property("maximumExpandedWidth"))
    if entry == "compactSidebarImport":
        click(window, find(window, "sidebarToggle"))
    target = None if entry == "shortcut" else find(window, entry)
    if entry in ("sidebarOpenFolder", "compactSidebarImport"):
        # The requested sidebar width is applied during Qt Quick's layout pass.
        settled_point(target)
        native_key = QKeySequence(QKeySequence.StandardKey.Open).toString(QKeySequence.NativeText)
        assert target.parentItem().property("tooltipText").endswith(f"({native_key})")
        caption = next(item for item in descendants(target) if item.objectName() == "toolbarLabel")
        assert caption.isVisible() and not caption.property("truncated")
        title = target.parentItem().property("shortLabel")
        if entry == "sidebarOpenFolder":
            assert caption.property("text") == f"{title} ({native_key})", (sidebar.width(), caption.width())
        else:
            assert caption.property("text") == title
    errors, opened = [], []
    inspector = QTimer()
    inspector.setInterval(10)

    def inspect():
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            return
        inspector.stop()
        try:
            assert isinstance(dialog, LocalImportDialog) and dialog.isVisible()
            opened.append(True)
            assert dialog.path_edit.text() == str(tmp_path)
        except BaseException as error:
            errors.append(error)
        finally:
            if dialog:
                dialog.reject()

    if entry == "shortcut":
        window.requestActivate()
        QTest.qWaitForWindowActive(window)
    inspector.timeout.connect(inspect)
    inspector.start()
    try:
        if entry == "shortcut":
            QTest.keySequence(window, QKeySequence(QKeySequence.StandardKey.Open))
        else:
            click(window, target)
    finally:
        inspector.stop()
    assert opened == [True] and not errors, errors
    assert not app.panelController.scanning
    assert not any(
        i.objectName() in ("localImportBanner", "homeOpenFiles", "homeOpenFolder")
        for i in descendants(window.contentItem())
    )
    assert not warnings, warnings


def test_picker_mixed_selection_folders_files_and_archives(qt_app, tmp_path):
    folder = tmp_path / "影像目录"
    folder.mkdir()
    dicom = tmp_path / "slice.dcm"
    dicom.write_bytes(b"dicom")
    archive = tmp_path / "scans.rar"
    archive.write_bytes(b"archive")
    dialog = LocalImportDialog(str(tmp_path))
    dialog.show()
    try:
        wait_until(lambda: dialog.model.rowCount(dialog.view.rootIndex()) == 3)
        QTest.qWait(50)
        for number, path in enumerate((folder, dicom, archive)):
            index = dialog.model.index(str(path))
            pos = dialog.view.visualRect(index).center()
            QTest.mouseClick(
                dialog.view.viewport(),
                Qt.LeftButton,
                Qt.ControlModifier if number else Qt.NoModifier,
                pos,
            )
        assert {Path(p) for p in dialog.selected_paths()} == {folder, dicom, archive}
        assert dialog.grab().save(str(tmp_path / "mixed-picker.png"))
        QTest.mouseClick(dialog.open_button, Qt.LeftButton)
        assert dialog.result() == QDialog.Accepted
        assert {Path(p) for p in dialog.paths} == {folder, dicom, archive}
    finally:
        dialog.close()
        delete(dialog)


def test_picker_navigation_current_folder_and_cancel(qt_app, tmp_path):
    folder = tmp_path / "study"
    folder.mkdir()
    nested = folder / "series"
    nested.mkdir()
    dialog = LocalImportDialog(str(tmp_path))
    dialog.show()
    try:
        wait_until(lambda: dialog.model.rowCount(dialog.view.rootIndex()) > 0)
        QTest.qWait(50)
        index = dialog.model.index(str(folder))
        QTest.mouseClick(
            dialog.view.viewport(),
            Qt.LeftButton,
            pos=dialog.view.visualRect(index).center(),
        )
        QTest.mouseDClick(
            dialog.view.viewport(),
            Qt.LeftButton,
            pos=dialog.view.visualRect(index).center(),
        )
        QTest.qWait(50)
        assert dialog.isVisible() and dialog.path_edit.text() == str(folder)
        dialog.path_edit.setText(str(nested))
        QTest.keyClick(dialog.path_edit, Qt.Key_Return)
        wait_until(lambda: not dialog._loading)
        assert dialog.isVisible() and dialog.path_edit.text() == str(nested)
        QTest.keyClick(dialog.path_edit, Qt.Key_Return)
        assert dialog.paths == [str(nested)]
    finally:
        dialog.close()
        delete(dialog)
    dialog = LocalImportDialog(str(folder))
    dialog.reject()
    assert dialog.result() == QDialog.Rejected and not dialog.paths
    delete(dialog)


@pytest.mark.parametrize(("key", "modifier"), [
    (Qt.Key_Return, Qt.NoModifier),
    (Qt.Key_Enter, Qt.KeypadModifier),
    (Qt.Key_Escape, Qt.NoModifier),
])
def test_picker_file_list_keys_confirm_mixed_selection_or_cancel(qt_app, tmp_path, key, modifier):
    folder = tmp_path / "study"
    folder.mkdir()
    image = tmp_path / "slice.dcm"
    image.touch()
    dialog = LocalImportDialog(str(tmp_path))
    dialog.show()
    try:
        wait_until(lambda: not dialog._loading)
        for path, selection_modifier in ((folder, Qt.NoModifier), (image, Qt.ControlModifier)):
            rect = dialog.view.visualRect(dialog.model.index(str(path)))
            QTest.mouseClick(dialog.view.viewport(), Qt.LeftButton, selection_modifier, rect.center())
        dialog.view.setFocus()
        assert {Path(p) for p in dialog.selected_paths()} == {folder, image}
        assert dialog.open_button.isEnabled() and dialog.isVisible()
        assert dialog.open_button.text() == dialog.open_button.accessibleName() + " (Enter)"
        assert not dialog.open_button.toolTip() and dialog.open_button.accessibleDescription() == "Enter"
        QTest.keyClick(dialog.view, key, modifier)
        assert not dialog.isVisible()
        if key == Qt.Key_Escape:
            assert dialog.result() == QDialog.Rejected and not dialog.paths
        else:
            assert dialog.result() == QDialog.Accepted
            assert {Path(p) for p in dialog.paths} == {folder, image}
    finally:
        dialog.close()
        delete(dialog)


def test_picker_enter_activates_focused_cancel(qt_app, tmp_path):
    dialog = LocalImportDialog(str(tmp_path))
    dialog.show()
    try:
        wait_until(lambda: not dialog._loading)
        dialog.cancel_button.setFocus(Qt.TabFocusReason)
        QTest.keyClick(dialog.cancel_button, Qt.Key_Return)
        assert not dialog.isVisible()
        assert dialog.result() == QDialog.Rejected and not dialog.paths
    finally:
        dialog.close()
        delete(dialog)


def test_removed_status_does_not_render_or_change_layout(scene):
    window, app, warnings = scene
    sidebar = find(window, "sidebarContainer")
    footer = find(window, "sidebarSettingsFooter")
    geometry = (footer.y(), footer.height(), sidebar.width())
    for message, error in [("progress", False), ("success", False), ("failure", True)]:
        app.panelController._set_status(message, error)
        QTest.qWait(30)
        assert not any(
            i.objectName() == "localImportBanner"
            for i in descendants(window.contentItem())
        )
        assert (footer.y(), footer.height(), sidebar.width()) == geometry
    assert not warnings, warnings


def test_mixed_picker_imports_folder_file_and_rar_together(scene, tmp_path):
    from test_local_import import make_series
    from rar_fixture import stored_rar

    source = tmp_path / "source"
    source.mkdir()
    series = make_series(source, 3)
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "first.dcm").write_bytes(series.instances[0].path.read_bytes())
    file = tmp_path / "second.dcm"
    file.write_bytes(series.instances[1].path.read_bytes())
    archive = stored_rar(
        tmp_path / "third.rar",
        [("scan/third.dcm", series.instances[2].path.read_bytes())],
    )
    window, app, warnings = scene
    app.panelController._last_import_directory = str(tmp_path)
    errors = []
    chooser = QTimer()
    chooser.setInterval(10)

    def choose():
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            return
        chooser.stop()
        try:
            assert isinstance(dialog, LocalImportDialog)
            wait_until(lambda: dialog.model.rowCount(dialog.view.rootIndex()) >= 4)
            for path in (folder, file, archive):
                dialog.view.selectionModel().select(
                    dialog.model.index(str(path)),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows,
                )
            dialog.view.setFocus()
            QTest.keyClick(dialog.view, Qt.Key_Return)
        except BaseException as error:
            errors.append(error)
            if dialog:
                dialog.reject()

    target = find(window, "homeOpenImport")
    chooser.timeout.connect(choose)
    chooser.start()
    try:
        click(window, target)
    finally:
        chooser.stop()
    assert not errors, errors
    wait_until(lambda: not app.panelController.scanning)
    assert not app.panelController.importError
    assert (
        app._series_catalog.get_series(series.series_instance_uid).dicom_file_count == 3
    )
    assert all(i.path.exists() for i in series.instances)
    assert not warnings, warnings


def test_picker_uses_native_close_and_fixed_cancel_confirm_order(qt_app, tmp_path):
    dialog = LocalImportDialog(str(tmp_path))
    dialog.show()
    try:
        QTest.qWait(50)
        for width, height in ((620, 400), (880, 560)):
            dialog.resize(width, height)
            QTest.qWait(30)
            cancel, confirm = dialog.cancel_button, dialog.open_button
            assert dialog.findChild(QPushButton, "importDismiss") is None
            assert not dialog.windowFlags() & Qt.FramelessWindowHint
            assert dialog.windowFlags() & Qt.WindowCloseButtonHint
            assert cancel.geometry().right() < confirm.geometry().left()
            assert cancel.geometry().center().y() == confirm.geometry().center().y()
            assert confirm.geometry().right() == width - 17
            assert abs(confirm.geometry().bottom() - (height - 17)) <= 1
        assert dialog.grab().save(str(tmp_path / "picker-dialog-actions.png"))
        assert dialog.close()
        assert dialog.result() == QDialog.Rejected and not dialog.paths
    finally:
        dialog.close()
        delete(dialog)


def test_picker_accessible_cells_invalidated_on_navigation_and_selection_survives_sort(qt_app,tmp_path):
    from PySide6.QtGui import QAccessible
    folders=[tmp_path/'many',tmp_path/'few']
    for folder,count in zip(folders,(104,2)):
        folder.mkdir()
        for i in range(count): (folder/f'{i:03}.dcm').write_bytes(bytes(i+1))
    dialog=LocalImportDialog(str(folders[1]));dialog.show()
    try:
        wait_until(lambda: not dialog._loading)
        for i in range(20):
            interface=QAccessible.queryAccessibleInterface(dialog.view)
            assert interface is not None
            for child in range(min(8, interface.childCount())):
                assert interface.child(child) is not None
            folder=folders[i%2]
            dialog.path_edit.setText(str(folder))
            QTest.keyClick(dialog.path_edit,Qt.Key_Return)
            wait_until(lambda: not dialog._loading)
            assert dialog._directory == str(folder)
            assert dialog.model.rowCount() == (104 if i%2==0 else 2)
            assert not dialog.view.rootIndex().isValid()
        selected=folders[1]/'000.dcm'
        from PySide6.QtCore import QItemSelectionModel
        dialog.view.selectionModel().select(dialog.model.index(str(selected)),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        dialog.view.sortByColumn(1,Qt.DescendingOrder)
        assert dialog.selected_paths() == [str(selected)]
        assert dialog.model.filePath(dialog.model.index(0,0)).endswith('001.dcm')
    finally:
        dialog.close();delete(dialog)


def test_slow_directory_keeps_dialog_responsive_and_ignores_stale_result(qt_app, tmp_path, monkeypatch):
    import threading
    import voxplane.ui.dialogs.local_import_dialog as picker

    slow, fast = tmp_path / 'slow', tmp_path / 'fast'
    slow.mkdir(); fast.mkdir()
    (slow / 'old.dcm').write_bytes(b'old')
    (fast / 'new.dcm').write_bytes(b'new')
    entered, release = threading.Event(), threading.Event()
    original = picker.os.scandir

    def delayed(path):
        if Path(path) == slow:
            entered.set()
            release.wait(5)
        return original(path)

    monkeypatch.setattr(picker.os, 'scandir', delayed)
    dialog = LocalImportDialog(str(slow)); dialog.show()
    try:
        wait_until(entered.is_set)
        assert dialog.isVisible() and dialog._loading
        assert not dialog.open_button.isEnabled()
        QTest.qWait(60)
        assert dialog.selection_label.text() == ""
        wait_until(lambda: bool(dialog.selection_label.text()))
        dialog.navigate(str(fast))
        assert dialog.selection_label.text() == ""
        wait_until(lambda: not dialog._loading)
        assert dialog._directory == str(fast)
        assert dialog.model.index(str(fast / 'new.dcm')).isValid()
        release.set()
        wait_until(lambda: not dialog._directory_results.empty())
        dialog._finish_navigation()
        assert dialog._directory == str(fast)
        assert dialog.model.index(str(fast / 'new.dcm')).isValid()
        # Closing while another filesystem request is blocked must not wait on it.
        release.clear(); entered.clear()
        dialog.navigate(str(slow))
        wait_until(entered.is_set)
        dialog.reject()
        assert not dialog.isVisible()
    finally:
        delete(dialog)
        release.set()


def test_typed_file_is_selected_after_async_navigation(qt_app, tmp_path):
    file = tmp_path / 'image.dcm'; file.write_bytes(b'dicom')
    dialog = LocalImportDialog(str(tmp_path)); dialog.show()
    try:
        wait_until(lambda: not dialog._loading)
        dialog.path_edit.setText(str(file))
        QTest.keyClick(dialog.path_edit, Qt.Key_Return)
        wait_until(lambda: not dialog._loading)
        assert dialog.isVisible() and dialog.selected_paths() == [str(file)]
        qt_app.sendEvent(dialog.path_edit, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "", True))
        assert dialog.isVisible() and not dialog.paths
        QTest.keyClick(dialog.path_edit, Qt.Key_Enter, Qt.KeypadModifier)
        assert dialog.paths == [str(file)]
    finally:
        delete(dialog)


def test_pending_directory_result_preserves_new_address(qt_app, tmp_path):
    target = tmp_path / 'second'
    target.mkdir()
    dialog = LocalImportDialog(str(tmp_path))
    # Hold delivery until the address field has a newer edit.
    dialog._directory_timer.stop()
    dialog.show()
    try:
        dialog.path_edit.selectAll()
        QTest.keyClicks(dialog.path_edit, str(target))
        dialog._directory_timer.start()
        wait_until(lambda: not dialog._loading)
        assert dialog.isVisible() and dialog.path_edit.text() == str(target)
        QTest.keyClick(dialog.path_edit, Qt.Key_Return)
        wait_until(lambda: not dialog._loading)
        assert dialog._directory == str(target) and not dialog.paths
    finally:
        dialog.close()
        delete(dialog)


def test_invalid_address_enter_never_confirms_previous_selection(qt_app, tmp_path):
    image = tmp_path / 'previous.dcm'
    image.touch()
    invalid = str(tmp_path / 'missing')
    dialog = LocalImportDialog(str(tmp_path))
    dialog.show()
    try:
        wait_until(lambda: not dialog._loading)
        dialog.view.selectRow(dialog.model.index(str(image)).row())
        dialog.path_edit.setFocus()
        dialog.path_edit.setText(invalid)
        for _ in range(2):
            QTest.keyClick(dialog.path_edit, Qt.Key_Return)
            wait_until(lambda: not dialog._loading)
            assert dialog.isVisible() and not dialog.paths
            assert dialog.path_edit.text() == invalid and dialog.selection_label.text()
            # A directory watcher refresh while editing must preserve the failed address.
            dialog._refresh_directory()
            wait_until(lambda: not dialog._loading)
            assert dialog.path_edit.text() == invalid
        QTest.keyClick(dialog.path_edit, Qt.Key_Escape)
        assert not dialog.isVisible() and not dialog.paths
    finally:
        dialog.close()
        delete(dialog)


@pytest.mark.parametrize('kind', ['folder', 'file', 'missing'])
def test_confirm_commits_typed_path_instead_of_previous_selection(qt_app, tmp_path, kind):
    original = tmp_path / 'original'; original.mkdir()
    previous = original / 'previous.dcm'; previous.write_bytes(b'dicom')
    target = tmp_path / ('target.dcm' if kind == 'file' else 'target')
    if kind == 'folder': target.mkdir()
    elif kind == 'file': target.write_bytes(b'dicom')
    dialog = LocalImportDialog(str(original)); dialog.show()
    try:
        wait_until(lambda: not dialog._loading)
        dialog.view.selectionModel().select(dialog.model.index(str(previous)),
            QItemSelectionModel.Select | QItemSelectionModel.Rows)
        dialog.path_edit.setFocus()
        dialog.path_edit.selectAll()
        QTest.keyClicks(dialog.path_edit, str(target))
        QTest.mouseClick(dialog.open_button, Qt.LeftButton)
        wait_until(lambda: not dialog._loading)
        if kind == 'missing':
            assert dialog.isVisible() and not dialog.paths
            assert dialog.path_edit.text() == str(target)
            # A repeated click may retry, but must never fall back to the old selection.
            QTest.mouseClick(dialog.open_button, Qt.LeftButton)
            wait_until(lambda: not dialog._loading)
            assert dialog.isVisible() and not dialog.paths
        else:
            assert dialog.result() == QDialog.Accepted
            assert dialog.paths == [str(target)]
    finally:
        dialog.close(); delete(dialog)


def test_cancel_during_typed_path_check_never_accepts_late_result(qt_app, tmp_path, monkeypatch):
    from threading import Event
    import voxplane.ui.dialogs.local_import_dialog as picker
    original = tmp_path / 'original'; original.mkdir()
    target = tmp_path / 'target'; target.mkdir()
    entered, release = Event(), Event()
    scandir = picker.os.scandir
    def delayed(path):
        if Path(path) == target:
            entered.set()
            assert release.wait(5)
        return scandir(path)
    monkeypatch.setattr(picker.os, 'scandir', delayed)
    dialog = LocalImportDialog(str(original)); dialog.show()
    try:
        wait_until(lambda: not dialog._loading)
        dialog.path_edit.setText(str(target))
        QTest.mouseClick(dialog.open_button, Qt.LeftButton)
        wait_until(entered.is_set)
        QTest.mouseClick(dialog.cancel_button, Qt.LeftButton)
        release.set()
        wait_until(lambda: not dialog._loading)
        assert dialog.result() == QDialog.Rejected and not dialog.paths
    finally:
        release.set(); dialog.close(); delete(dialog)


@pytest.mark.parametrize('kind', ['hidden', 'directory-alias'])
def test_typed_file_never_falls_back_to_importing_parent(qt_app, tmp_path, kind):
    actual = tmp_path / 'actual'; actual.mkdir()
    target = actual / ('.scan.dcm' if kind == 'hidden' else 'scan.dcm')
    target.write_bytes(b'dicom')
    typed = target
    if kind == 'directory-alias':
        alias = tmp_path / 'alias'
        try: alias.symlink_to(actual, target_is_directory=True)
        except OSError: pytest.skip('Directory symlinks unavailable')
        typed = alias / target.name
    dialog = LocalImportDialog(str(tmp_path)); dialog.show()
    try:
        wait_until(lambda: not dialog._loading)
        dialog.path_edit.setText(str(typed))
        QTest.mouseClick(dialog.open_button, Qt.LeftButton)
        wait_until(lambda: not dialog._loading)
        assert dialog.result() == QDialog.Accepted
        assert len(dialog.paths) == 1 and Path(dialog.paths[0]).resolve() == target
        assert Path(dialog.paths[0]).is_file()
    finally:
        dialog.close(); delete(dialog)
