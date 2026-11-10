import os, sys, tempfile
from pathlib import Path
import pydicom
from PySide6.QtCore import Qt, QUrl, QPointF, QObject
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlApplicationEngine
from qt_dicom_viewer.app import configure_application_identity
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from test_dicom_tags import wait_until
from test_tag_qml import find
from test_series_sidebar import right_click
from qt_dicom_viewer import __version__

assert __version__ == '2.5.0'
data = Path('build/release-2.2.0/Cardiac CTA')
dicoms = [pydicom.dcmread(f, stop_before_pixels=True) for f in sorted(data.glob('*.dcm'))]
assert len(dicoms) == 91 and all(str(d.PatientName) == 'Demo' and d.PatientID == 'SAMPLE' for d in dicoms)
locale = sys.argv[1]
dest = Path('docs/screenshots') / ('en' if locale == 'en-US' else '')
app = QApplication([])
configure_application_identity(app)
base = Path(tempfile.mkdtemp(dir='build/release-2.5.0/media')).resolve()
provider = DicomImageProvider()
c = AppController(provider, settings_path=base/'settings.json', pacs_config_path=base/'pacs.json', pacs_import_root=base/'imports')
c.languageController.selectLanguage(locale)
c.workspaceDocumentController.setAutomaticRecovery(False)
c.settingsController.setValue('appearance', 'theme', 'dark')
engine = QQmlApplicationEngine()
engine.addImageProvider('dicom', provider)
engine.addImageProvider('navigation', SvgIconProvider())
engine.rootContext().setContextProperty('appController', c)
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
engine.load(QUrl.fromLocalFile(str(Path('src/qt_dicom_viewer/qml/Main.qml').resolve())))
w = engine.rootObjects()[0]
w.resize(1440, 900)
w.show()
w.requestActivate()
wait_until(w.isActive)
snapshot = list(DicomFolderScanner().scan(data))[-1]
c.panelController.acceptPacsImport(snapshot)
uid = dicoms[0].SeriesInstanceUID
c.panelController.selectSeries(uid)
wait_until(lambda: c.workspaceController.activeLoadState.status == 'ready', 15000)
tab = c.workspaceController.activeTab
view = tab.activeViewport
view.setSliceIndex(45)
wait_until(lambda: view.sliceIndex == 45 and not view.render_pending, 15000)
tab.toolController.activateTool('measure')
for kind, points in [('length', [(65,115),(128,115)]), ('ellipse',[(80,75),(118,108)]), ('angle',[(146,101),(157,124),(139,140)])]:
    tab.toolController.selectInteraction('measure:' + kind)
    for col, row in points:
        view.selectMeasurementAt(True, col, row, 1, 1, 200, 200)
assert len(view.measurementController.measurementItems) == 3
assert tab.toolController.activePanel == 'measure'

def shot(name):
    QTest.qWait(500)
    assert w.grabWindow().scaledToWidth(1440, Qt.SmoothTransformation).save(str(dest/name))

QTest.mouseMove(w, QPointF(700,16).toPoint())
shot('63-measurement-2.5.0.png')
tab.toolController.activateTool('window')
menu = w.findChild(QObject, 'seriesContextMenu')
menu.setProperty('popupType', 0)
right_click(w, find(w, 'series-' + uid))
wait_until(lambda: menu.property('opened'))
assert menu.findChild(QObject, 'seriesContextAction-2d').property('shortcutHint') == 'D'
assert menu.findChild(QObject, 'seriesContextAction-mpr').property('shortcutHint') == 'X'
shot('65-view-shortcuts-2.5.0.png')
menu.close()
dialog = w.findChild(QObject, 'workspaceDocumentDialog')
dialog.open()
wait_until(lambda: dialog.property('opened'))
QTest.qWait(250)
from PySide6.QtGui import QGuiApplication
popup_windows = QGuiApplication.topLevelWindows()
popup_window = next(item for item in popup_windows if item.isVisible() and item is not w and item.width() < 800)
assert popup_window.grabWindow().save(str(dest/'17-workspace-2.5.0.png'))
dialog.close()
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
sources = []
for title in ('CT-Phantom', 'MR-Demo', 'PET-CT-Demo'):
    folder = base / title
    folder.mkdir()
    sources.append(folder)
    c.panelController.favoriteDirectories.add(str(folder))
c.panelController.recentImagePaths.record([str(folder) for folder in sources],str(sources[0]))
picker=LocalImportDialog(str(sources[0]), favorites=c.panelController.favoriteDirectories, recent=c.panelController.recentImagePaths)
picker.show(); picker.activateWindow()
wait_until(lambda: not picker._loading)
QTest.qWait(200)
assert picker.recent_list.count()==3 and picker.recent_clear.isVisible()
assert picker.grab().save(str(dest/'66-image-sources-2.5.0.png'))
picker.close()
assert not warnings, warnings
print(locale, __version__, len(view.measurementController.measurementItems), flush=True)
w.hide()
c.shutdown()
os._exit(0)
