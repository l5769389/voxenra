"""Mixed file/folder picker and one-click QML integration."""

from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel, QTimer, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton
from shiboken6 import delete

from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
from test_dicom_tags import qt_app as qt_app, wait_until
from test_pacs_qml import scene as scene
from test_tag_qml import find, click, descendants


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
    if entry == "compactSidebarImport":
        click(window, find(window, "sidebarToggle"))
    target = None if entry == "shortcut" else find(window, entry)
    errors, opened = [], []

    def inspect():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, LocalImportDialog) and dialog.isVisible()
            opened.append(True)
            assert dialog.path_edit.text() == str(tmp_path)
        except BaseException as error:
            errors.append(error)
        finally:
            if dialog:
                dialog.reject()

    QTimer.singleShot(100, inspect)
    if entry == "shortcut":
        QTest.keySequence(window, QKeySequence(QKeySequence.StandardKey.Open))
    else:
        click(window, target)
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
        assert dialog.isVisible() and dialog.path_edit.text() == str(nested)
        QTest.mouseClick(dialog.open_button, Qt.LeftButton)
        assert dialog.paths == [str(nested)]
    finally:
        dialog.close()
        delete(dialog)
    dialog = LocalImportDialog(str(folder))
    dialog.reject()
    assert dialog.result() == QDialog.Rejected and not dialog.paths
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

    def choose():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, LocalImportDialog)
            wait_until(lambda: dialog.model.rowCount(dialog.view.rootIndex()) >= 4)
            for path in (folder, file, archive):
                dialog.view.selectionModel().select(
                    dialog.model.index(str(path)),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows,
                )
            QTest.mouseClick(dialog.open_button, Qt.LeftButton)
        except BaseException as error:
            errors.append(error)
            if dialog:
                dialog.reject()

    QTimer.singleShot(100, choose)
    click(window, find(window, "homeOpenImport"))
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
            assert confirm.geometry().bottom() == height - 17
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
    dialog=LocalImportDialog(str(folders[0]));dialog.show()
    try:
        for i in range(20):
            interface=QAccessible.queryAccessibleInterface(dialog.view)
            assert interface is not None
            for child in range(min(8, interface.childCount())):
                assert interface.child(child) is not None
            folder=folders[i%2]
            dialog.path_edit.setText(str(folder))
            QTest.keyClick(dialog.path_edit,Qt.Key_Return)
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
