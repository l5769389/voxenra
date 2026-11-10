from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from test_dicom_tags import qt_app, wait_until, make_dicom
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog

@pytest.mark.parametrize(('theme','locale','width','height'),[
    ('dark','zh-CN',1040,640), ('light','en-US',760,480), ('dark','zh-CN',620,400)])
def test_source_list_layout_and_actions(qt_app, tmp_path, theme, locale, width, height):
    app = AppController(DicomImageProvider(), settings_path=False)
    app.settingsController.setValue('appearance','theme',theme)
    app.languageController.selectLanguage(locale)
    c = app.panelController
    folders = [tmp_path/f'CT-Phantom-{i:02}' for i in range(1,13)]
    for i, folder in enumerate(folders):
        folder.mkdir()
        make_dicom(folder/'slice-01.dcm',i+1)
        assert c.favoriteDirectories.add(str(folder))
    c.recentImagePaths.record([str(f) for f in reversed(folders[:10])],str(folders[0]))
    picker = LocalImportDialog(str(folders[0]), favorites=c.favoriteDirectories,recent=c.recentImagePaths)
    picker.show(); picker.activateWindow(); picker.resize(width,height)
    out = Path('build/import-dialog-redesign-20261110/native'); out.mkdir(parents=True,exist_ok=True)
    try:
        wait_until(lambda: not picker._loading)
        QTest.qWait(100)
        listing = picker.recent_list
        assert listing.isVisible() and listing.count()==10
        assert picker.favorite_list.isVisible()
        assert picker.view.width()>=300
        assert picker.view.height()>=170
        assert picker.path_edit.width()>=130
        assert picker.grab().save(str(out/f'{theme}-{locale}-{width}x{height}.png'))
        assert picker.recent_clear.isVisible()
        assert listing.visualItemRect(listing.currentItem()).contains(picker.recent_clear.geometry())
        assert picker.favorite_list.geometry().bottom()<picker.recent_panel.geometry().bottom()
        assert picker.cancel_button.geometry().right()<picker.open_button.geometry().left()
        assert picker.open_button.geometry().bottom()<picker.height()
        assert picker.grab().save(str(out/f'{theme}-{locale}-{width}x{height}.png'))
        # Keyboard context menu only removes the target and never accepts the dialog.
        item = listing.item(1)
        point=listing.visualItemRect(item).center()
        qt_app.sendEvent(listing.viewport(), QContextMenuEvent(QContextMenuEvent.Mouse,point,listing.viewport().mapToGlobal(point)))
        QTest.qWait(80)
        assert picker.recent_menu.isVisible()
        assert picker.recent_menu.grab().save(str(out/f'menu-{locale}-{height}.png'))
        QTest.keyClick(picker.recent_menu,Qt.Key_Down)
        QTest.keyClick(picker.recent_menu,Qt.Key_Return)
        assert picker.isVisible() and not picker.paths
        assert len(c.recentImagePaths.items)==9 and str(folders[8]) not in c.recentImagePaths.items
        assert all(f.is_dir() for f in folders)
        listing.setCurrentRow(0)
        QTest.qWait(60)
        QTest.mouseClick(picker.recent_clear,Qt.LeftButton)
        assert picker.isVisible() and not picker.paths
        assert len(c.recentImagePaths.items)==8 and str(folders[9]) not in c.recentImagePaths.items
        QTest.mouseClick(picker.recent_clear_all,Qt.LeftButton)
        assert picker.isVisible() and not c.recentImagePaths.items
        assert picker.recent_empty.isVisible() and not picker.recent_clear_all.isEnabled()
        assert len(c.favoriteDirectories.items)==12
        QTest.qWait(80)
        assert picker.grab().save(str(out/f'empty-{theme}-{locale}-{width}x{height}.png'))
    finally:
        picker.close(); picker.deleteLater(); app.shutdown()
