"""Regenerate real application screenshots with synthetic data and isolated settings.

QT_QPA_PLATFORM=cocoa QT_QUICK_BACKEND=software PYTHONPATH=src:tests \
  python tests/manual/capture_manual.py /tmp/manual-screenshots
Use a native desktop to include the VTK child in the 3D screenshot.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import subprocess
import time
import zipfile

from PySide6.QtCore import QObject, QPointF, QUrl, Qt, QItemSelectionModel
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from voxplane.model import DicomFolderScanSnapshot
from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.svg_icon_provider import SvgIconProvider
from voxplane.ui.dialogs.local_import_dialog import LocalImportDialog
from test_tag_qml import find, descendants, click
from test_measurement_qml import _scene, _mouse_drag
from test_mpr_voi_qml import _owner
from smoke_pet_3d import make_pair
from smoke_water_qa import make_water_series

ROOT = Path(__file__).resolve().parents[2]


def main(output, volume_only=False, locale="zh-CN", volume_kind="ct", check_switching=False):
    qt = QApplication.instance() or QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="voxplane-manual-") as temporary:
        folder = Path(temporary)
        pair_dir, water_dir = folder / 'CT-PET', folder / 'Water-QA'
        pair_dir.mkdir(); water_dir.mkdir()
        ct, pet = make_pair(pair_dir)
        water, _ = make_water_series(water_dir)
        records = [ct, pet, water]
        provider = DicomImageProvider()
        app = AppController(provider, settings_path=folder/'settings.json',
                            pacs_config_path=folder/'pacs.json', pacs_import_root=folder/'imports')
        app.languageController.selectLanguage(locale)
        app.workspaceDocumentController.setAutomaticRecovery(False)
        engine = QQmlApplicationEngine()
        engine.addImageProvider('dicom', provider)
        engine.addImageProvider('navigation', SvgIconProvider())
        engine.rootContext().setContextProperty('appController', app)
        warnings = []
        engine.warnings.connect(lambda entries: warnings.extend(e.toString() for e in entries))
        engine.load(QUrl.fromLocalFile(str(ROOT/'src/voxplane/qml/Main.qml')))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        window.resize(1440, 900)
        from qt_pointer import activate_window
        activate_window(window)
        ws = app.workspaceController

        def pump(ms=120):
            until = time.monotonic() + ms / 1000
            while time.monotonic() < until:
                qt.processEvents()
                time.sleep(.005)

        def wait(predicate):
            until = time.monotonic() + 20
            while not predicate() and time.monotonic() < until:
                pump(20)
            assert predicate(), 'Timed out generating manual screenshot'
            pump()

        def capture(name, target=None, native=False):
            # Move the pointer out of controls so tooltips cannot obscure content.
            QTest.mouseMove(window, window.contentItem().mapToScene(QPointF(600, 16)).toPoint())
            pump(160)
            target = target or window
            if native:
                picture = (QGuiApplication.screenAt(target.position()) or QGuiApplication.primaryScreen()).grabWindow(target.winId())
            else:
                picture = target.grabWindow() if hasattr(target, 'grabWindow') else target.grab()
            assert not picture.isNull(), name
            assert picture.save(str(output / (name + '.png')), 'PNG', 0)
            print(name, picture.width(), picture.height(), flush=True)

        def open_view(series, kind, title):
            if locale == 'en-US': title = {'合成 CT 3D':'Synthetic CT 3D', '合成水模 CT':'Synthetic Water CT', '序列平铺 · 合成 CT':'Tiles · Synthetic CT', '合成 CT MPR':'Synthetic CT MPR', '合成 PET MPR':'Synthetic PET MPR'}.get(title, title)
            ws.createTab(series.series_instance_uid, title, kind)
            wait(lambda: ws.activeLoadState.status == 'ready')
            return ws.activeTab, ws.activeViewport

        def layer_for(view):
            return next(i for i in descendants(window.contentItem())
                        if i.objectName() == 'dicomPixelLayer' and i.isVisible() and _owner(i) is view)

        try:
            count = sum(len(record.instances) for record in records)
            snapshot = DicomFolderScanSnapshot(folder, count, count, 0, records)
            app.panelController.update_series_session(snapshot)
            app.panelController._update_series_record(snapshot)
            wait(lambda: len(app.panelController._thumbnails) == 3)
            find(window, 'sidebarContainer').setProperty('expandedWidth', 220)
            app.settingsController.setValue('layout', 'rightPanelWidth', 260)
            if volume_only:
                if volume_kind == 'fusion':
                    ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
                    wait(lambda: ws.activeTab.ready)
                    ws.activeTab.openVolumeView()
                    volume, view = ws.activeTab, ws.activeViewport
                else:
                    title = ('Synthetic ' if locale == 'en-US' else '合成 ') + volume_kind.upper() + ' 3D'
                    volume, view = open_view(pet if volume_kind == 'pet' else ct, '3d', title)
                wait(lambda: view._host is not None and view._host.isVisible())
                wait(lambda: view._host.backend._initialized)
                volume.toolController.activateTool('volume-preset')
                pump(500)
                capture('volume', native=True)
                if check_switching:
                    from voxplane.ui.workspace_snapshot import tab_snapshot
                    from voxplane.core.workspace_state import dumps
                    if volume_kind != 'fusion':
                        volume.toolController.activateTool('volume-crop')
                        size = (view._host.width(), view._host.height())
                        view.begin_drag((0, 0), size)
                        for point in ((size[0]*.55, 0), (size[0]*.55, size[1]), (0, size[1])):
                            view.update_drag(point)
                        view.end_drag()
                        wait(lambda: not view.editBusy)
                        assert view.hasCrop
                    view.setZoom(1.5)
                    pump()
                    host, backend = view._host, view._host.backend
                    before = dumps(tab_snapshot(volume))
                    history = list(volume.historyController._undo)
                    app.workspaceDocumentController._dirty = False
                    for theme, lang in [('light','en-US'), ('dark','en-US'), ('light','zh-CN'), ('dark','zh-CN')]:
                        app.settingsController.setValue('appearance', 'theme', theme)
                        app.languageController.selectLanguage(lang)
                        pump(200)
                        assert view._host is host and host.backend is backend and host.isVisible()
                        assert dumps(tab_snapshot(volume)) == before
                        assert volume.historyController._undo == history
                        assert not app.workspaceDocumentController.dirty
                        capture(volume_kind+'-'+theme+'-'+lang, native=True)
                assert not warnings, warnings
                return
            tab, view = open_view(water, '2d', '合成水模 CT')
            capture('overview')
            layer = layer_for(view)
            for key in ('mean', 'std', 'minimum', 'maximum', 'count'):
                app.settingsController.setValue('roi', key, False)
            for kind, a, b in [('length', (100, 100), (230, 80)),
                               ('angle', (130, 290), (210, 290)),
                               ('ellipse', (305, 95), (360, 150)),
                               ('rect', (345, 240), (380, 275))]:
                tab.toolController.activateTool('measure')
                tab.toolController.selectInteraction('measure:' + kind)
                view.measurementController.clear_selection()
                pump()
                points = (a, b, (210, 340)) if kind == 'angle' else (a, b)
                for point in points:
                    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, _scene(layer, *point))
                print(kind, len(view.measurementController.measurementItems), flush=True)
            assert len(view.measurementController.measurementItems) == 4
            capture('measurement')
            view.measurementController.clear_all()
            for key in ('mean', 'std', 'minimum', 'maximum', 'count'):
                app.settingsController.setValue('roi', key, True)
            for point in ((250, 140), (310, 205)):
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, _scene(layer, *point))
            assert len(view.measurementController.measurementItems) == 1
            capture('roi')
            view.measurementController.clear_all()
            tab.toolController.activateTool('annotate')
            tab.toolController.selectInteraction('annotate:arrow')
            for point in ((100, 250), (160, 185)):
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, _scene(layer, *point))
            capture('annotation')
            tab.toolController.activateTool('export')
            capture('export')
            click(window, find(window, 'sidebarWorkspace'))
            dialog = window.findChild(QObject, 'workspaceDocumentDialog')
            wait(lambda: dialog.property('visible'))
            app.workspaceDocumentController.setAutomaticRecovery(True)
            app.workspaceDocumentController._autosave.stop()
            capture('workspace', dialog.findChild(QObject, 'workspaceDocumentMessage').window())
            dialog.findChild(QObject, 'workspaceDocumentMessage').window().close()
            app.workspaceDocumentController.setAutomaticRecovery(False)

            # The actual mixed picker, using only temporary synthetic source files.
            imports = folder / 'Import-Examples'
            imports.mkdir()
            (imports/'CT-series').mkdir()
            (imports/'single-image.dcm').write_bytes(water.instances[0].path.read_bytes())
            with zipfile.ZipFile(imports/'PET-series.zip', 'w') as archive:
                archive.write(pet.instances[0].path, 'PET/001.dcm')
            picker = LocalImportDialog(str(imports))
            picker.show()
            wait(lambda: picker.model.rowCount(picker.view.rootIndex()) == 3)
            picker.view.selectAll()
            capture('import', picker)
            picker.close(); delete(picker)

            assert app.pacsController.saveProfile({'name': 'DICOMweb Example' if locale == 'en-US' else 'DICOMweb 示例', 'url': 'http://127.0.0.1:8042/dicom-web', 'auth': 'none'})
            ws.openPacs(); pump()
            capture('pacs')
            ws.closeTab('workspace-pacs')
            ws.openSettings()
            for category, name in [('measurement', 'measurement-style'), ('corners', 'corners')]:
                app.settingsController.selectCategory(category)
                pump()
                capture(name)
            ws.closeTab('workspace-settings')
            montage, _ = open_view(ct, 'montage', '序列平铺 · 合成 CT')
            pump(500)
            capture('montage')
            pump(1200)
            ws.closeTab(ws.activeTabId)
            for series, suffix in [(ct, 'ct'), (pet, 'pt')]:
                mpr, view = open_view(series, 'mpr', '合成 CT MPR' if suffix == 'ct' else '合成 PET MPR')
                if suffix == 'ct': capture('mpr')
                else: capture('pet')
                view = next(v for v in mpr.viewports_by_id.values() if v.viewportType == 'axial')
                mpr.activateViewport(view.viewportId)
                for tool, start, end in [('segmentation', (22, 20), (44, 42)), ('voi', (32, 32), (43, 32))]:
                    mpr.toolController.activateTool(tool)
                    pump()
                    _mouse_drag(window, _scene(layer_for(view), *start), _scene(layer_for(view), *end))
                    wait(lambda: not mpr.voiController.busy)
                    assert not mpr.voiController.error and mpr.voiController.records
                    capture(tool + '-' + suffix)
                ws.closeTab(ws.activeTabId)
            ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
            wait(lambda: ws.activeTab.ready)
            capture('fusion')
            ws.activeTab.toolController.activateTool('registration')
            capture('registration')
            # Let the detail loader release the registration panel before closing its tab.
            ws.activeTab.toolController.activateTool('pan')
            pump()
            ws.closeTab(ws.activeTabId)
            ws.activateTabId(tab.tab_config.tab_id)
            view = tab.activeViewport
            view.measurementController.clear_all()
            tab.toolController.activateTool('service')
            tab.toolController.selectInteraction('service:qa')
            wait(lambda: view.qaController.status == 'ready')
            capture('water-qa')
            ws.openManual('measurement-edit')
            pump(300)
            capture('offline-manual')
            assert not warnings, warnings
        finally:
            window.hide()
            app.shutdown()
            delete(engine)


if __name__ == '__main__':
    volume_only = '--volume-only' in sys.argv
    locale = "en-US" if "--english" in sys.argv else "zh-CN"
    volume_kind = 'fusion' if '--fusion' in sys.argv else 'pet' if '--pet' in sys.argv else 'ct'
    main(Path(sys.argv[1]), volume_only, locale, volume_kind, '--check-switching' in sys.argv)
    # Isolate the native VTK lifecycle from the QML screenshot session.
    if not volume_only:
        subprocess.run([sys.executable, __file__, sys.argv[1], '--volume-only', *(['--english'] if locale == 'en-US' else [])], check=True)
