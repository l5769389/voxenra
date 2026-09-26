"""Capture actual Voxenra UI from local MR / 4D CT samples and a loopback PACS demo.

QT_QPA_PLATFORM=cocoa QT_QUICK_BACKEND=software PYTHONPATH=src:tests:tests/manual \
  python tests/manual/capture_readme.py --samples ~/Documents/Voxenra-MR-TestData \
  --output docs/screenshots

Original DICOM files are read only. Display records use anonymous demo labels;
settings and recovery files are isolated. Native VTK screenshots include the
actual child window. Each scene runs in a separate process for Qt/VTK cleanup.
"""
import argparse
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from PySide6.QtCore import QPointF, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import delete

from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from test_tag_qml import find

ROOT = Path(__file__).resolve().parents[2]
SCENES = ('01-2d-measurement', '02-mpr-segmentation', '04-volume-rendering',
          '07-mr-reading', '08-enhanced-mr-compare', '09-mpr-compare',
          '10-2d-layout', '11-mpr-3d-layout', '12-mr-montage',
          '13-detached-tabs', '14-oblique-mpr', '03-4d-mpr',
          '16-pacs-browser', '21-dicom-tags', '22-display-settings', '23-pacs-import',
          '24-compact-sidebars', '25-theme-dark', '26-theme-light',
          '27-thick-slab', '28-mtf-analysis', '29-volume-crop', '30-offline-manual')


def scan(path, label):
    result = list(DicomFolderScanner().scan(path))[-1] if path.is_dir() else list(
        DicomFolderScanner().scan_files([path], folder=path.parent))[-1]
    # Only the presentation records change; files, geometry and pixel values do not.
    return [replace(r, patient_name='MR Demo', patient_id='Anonymous',
                    study_description='Public MR sample', study_date='', study_time='',
                    series_description=label or r.series_description) for r in result.series]


def capture(samples, output, scene, ct_samples=None):
    qt = QApplication.instance() or QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    if scene == '28-mtf-analysis':
        records = []
    elif scene in ('01-2d-measurement', '02-mpr-segmentation', '04-volume-rendering', '03-4d-mpr'):
        assert ct_samples and ct_samples.is_dir(), 'Pass --ct-samples with a 4D CT folder'
        source = ct_samples if scene == '03-4d-mpr' else ct_samples / 'ph0'
        snapshot = list(DicomFolderScanner().scan_files(sorted(source.rglob('*.dcm')),
                        folder=ct_samples, can_publish=lambda: False))[-1]
        def clean_instance(i):
            return replace(i, patient_name='CT Demo', patient_id='Anonymous',
                           study_description='Respiratory CT', study_date='', study_time='',
                           acquisition_datetime='', patient_age='', patient_sex='')
        records = [replace(r, patient_name='CT Demo', patient_id='Anonymous',
                    study_description='Respiratory CT', study_date='', study_time='',
                    instances=tuple(clean_instance(i) for i in r.instances),
                    phases=tuple(replace(phase, instances=tuple(clean_instance(i) for i in phase.instances))
                                 for phase in r.phases)) for r in snapshot.series
                   if scene != '03-4d-mpr' or r.phase_count > 1]
        assert records
    elif scene == '08-enhanced-mr-compare':
        records = scan(samples / 'Enhanced-MR/In/Philips/IM_0035_fMRI.dcm', '')
        records.sort(key=lambda r: (r.instances[0].mr_parameters.temporal_position or 0,
                                    r.instances[0].mr_parameters.echo_time or 0))
        records = records[:4]
    elif scene == '09-mpr-compare':
        records = [*scan(samples / '01_T1_Brain_HFS', 'T1 · HFS'),
                   *scan(samples / '02_T1_Brain_HFDR', 'T1 · HFDR')]
    else:
        records = scan(samples / 'Thin-3D-T1/DICOM', '3D T1 · 1 mm')
    with TemporaryDirectory(prefix='voxenra-readme-') as tmp:
        folder = Path(tmp)
        if scene == '28-mtf-analysis':
            from io import BytesIO
            import numpy as np
            import pydicom
            from test_pacs import dicom_bytes
            from test_bead_mtf import gaussian
            ds = pydicom.dcmread(BytesIO(dicom_bytes(1)))
            ds.PatientName, ds.PatientID = 'Synthetic^MTF', 'MTF-DEMO'
            ds.SeriesDescription = 'Synthetic Gaussian point source'
            ds.Rows, ds.Columns = 128, 128
            ds.PixelSpacing = [.15, .1]
            ds.WindowCenter, ds.WindowWidth = 550, 1100
            # Keep the point-source tails and background annulus within the image.
            ds.PixelData = np.rint(gaussian(sigma_x=.25, sigma_y=.3)).astype('<u2').tobytes()
            path = folder / 'synthetic-mtf.dcm'
            ds.save_as(path, enforce_file_format=True)
            records = list(DicomFolderScanner().scan_files([path], folder=folder))[-1].series
        provider = DicomImageProvider()
        app = AppController(provider, settings_path=folder / 'settings.json',
                            pacs_config_path=folder / 'pacs.json', pacs_import_root=folder / 'imports')
        app.workspaceDocumentController.setAutomaticRecovery(False)
        app.languageController.selectLanguage('zh-CN')
        if scene == '26-theme-light':
            app.settingsController.setValue('appearance', 'theme', 'light')
        app.settingsController.setValue('layout', 'rightPanelWidth', 258)
        app.settingsController.setValue('corners', 'topLeft', ['viewPosition', 'seriesDescription', 'slice'])
        app.settingsController.setValue('corners', 'topRight', [])
        app.settingsController.setValue('corners', 'bottomRight', ['transform'])
        engine = QQmlApplicationEngine()
        engine.addImageProvider('dicom', provider)
        engine.addImageProvider('navigation', SvgIconProvider())
        engine.rootContext().setContextProperty('appController', app)
        warnings = []
        engine.warnings.connect(lambda items: warnings.extend(i.toString() for i in items))
        engine.load(QUrl.fromLocalFile(str(ROOT / 'src/qt_dicom_viewer/qml/Main.qml')))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        area = (QGuiApplication.screenAt(window.position()) or QGuiApplication.primaryScreen()).availableGeometry()
        window.resize(min(1440, area.width() - 40), min(900, area.height() - 60))
        window.setPosition(area.x() + 20, area.y() + 20)
        if QGuiApplication.platformName() == "offscreen":
            window.resize(1440, 900)
        window.requestActivate()
        ws = app.workspaceController
        backdrop = None
        detached_window = None
        pacs_server = None

        def pump(ms=150):
            end = time.monotonic() + ms / 1000
            while time.monotonic() < end:
                qt.processEvents()
                time.sleep(.005)

        def wait(predicate):
            end = time.monotonic() + 30
            while not predicate() and time.monotonic() < end:
                pump(25)
            assert predicate(), f'Timed out: {scene}'
            pump()

        def ready():
            wait(lambda: ws.activeTab is not None and all(getattr(v, 'loadState', 'ready') == 'ready'
                 for v in ws.activeTab.viewports_by_id.values()))

        try:
            count = sum(len(r.instances) for r in records)
            snapshot = DicomFolderScanSnapshot(samples, count, count, 0, records)
            app.panelController.update_series_session(snapshot)
            app.panelController._update_series_record(snapshot)
            wait(lambda: len(app.panelController._thumbnails) == len(records))
            find(window, 'sidebarContainer').setProperty('expandedWidth', 230)
            uid = records[0].series_instance_uid
            if scene in ('01-2d-measurement', '02-mpr-segmentation', '04-volume-rendering'):
                from capture_release_features import capture_feature
                capture_feature(app, window, uid, scene, output, folder, pump, wait, ready)
                assert not warnings, warnings
                return
            app.panelController.selectSeries(uid)
            if scene in ('16-pacs-browser', '23-pacs-import'):
                from test_pacs import FakePacs, STUDY, SERIES
                pacs_server = FakePacs()
                pacs = app.pacsController
                assert pacs.saveProfile({'name':'DICOMweb Demo', 'url':pacs_server.url, 'auth':'none'})
                ws.openPacs()
                pacs.queryStudies({}, 50)
                wait(lambda: not pacs.busy and bool(pacs.studies))
                pacs.selectStudy(STUDY)
                wait(lambda: not pacs.busy and bool(pacs.series))
                pacs.selectSeries(SERIES, True)
                if scene == '23-pacs-import':
                    imported = []
                    pacs.imported.connect(imported.append)
                    pacs.importSelected()
                    wait(lambda: not pacs.busy and bool(imported))
                    assert imported[0].dicom_file_count == 3
                    assert all(i.path.is_file() for r in imported[0].series for i in r.instances)
                    ready()
                    assert ws.activeTab.tab_config.series_metas[0].series_uid == SERIES
                    ws.openPacs()
                    find(window, 'series-' + SERIES)
                pump(500)
            elif scene == '30-offline-manual':
                app.languageController.selectLanguage('en-US')
                ws.openManual('measurement-edit')
                wait(lambda: ws.manualController is not None and ws.manualController.chapterId == 'measurement-edit')
                pump(500)
            elif scene == '28-mtf-analysis':
                ws.createTab(uid, 'CT · MTF', '2d')
                ready()
                tab, view = ws.activeTab, ws.activeViewport
                app.settingsController.setValue('layout', 'rightPanelWidth', 365)
                tab.toolController.selectService('service:mtf')
                view.beginInteraction(0, 0, 1, True, 20, 20, .1, .15)
                view.endInteraction(50, 50, True, 108, 108)
                wait(lambda: view.mtfController.status in ('ready', 'error'))
                assert view.mtfController.status == 'ready', view.mtfController._current_analysis().error
                assert view.mtfController.currentResult['x']['mtf50'] > 0
            elif scene == '29-volume-crop':
                ws.createTab(uid, 'MR · 3D Crop', '3d')
                ready()
                view, tab = ws.activeViewport, ws.activeTab
                wait(lambda: view._host is not None and view._host.backend._initialized)
                view.setViewFace('A')
                view.setZoom(1.0)
                pump(500)
                size = (view._host.width(), view._host.height())
                tab.toolController.activateTool('volume-crop')
                view.setCropMode('inside')
                view.begin_drag((size[0] * .5, size[1] * .2), size)
                for x, y in ((.85, .2), (.85, .6), (.5, .6)):
                    view.update_drag((size[0] * x, size[1] * y))
                view.end_drag()
                wait(lambda: not view.editBusy)
                assert view.hasCrop and view.crop_mask.any() and not view.crop_mask.all()
                original_crop = view.crop_mask.copy()
                tab.toolController.activateTool('volume-rotate')
                view.begin_drag((size[0] * .2, size[1] * .25), size)
                view.update_drag((size[0] * .35, size[1] * .32))
                view.end_drag()
                tab.toolController.activateTool('volume-crop')
                assert view.hasCrop and (view.crop_mask == original_crop).all()
                pump(900)
            elif scene == '21-dicom-tags':
                ws.createTab(uid, 'MR · DICOM Tags', 'tag')
                wait(lambda: ws.activeTab is not None and not ws.activeTab.tagController.loading)
                ws.activeTab.tagController.setSearchText('0028')
                pump(500)
            elif scene == '08-enhanced-mr-compare':
                ws.createMultiCompareTab([r.series_instance_uid for r in records])
                ready()
                ws.activeTab.toolController.activateTool('viewport-settings')
            elif scene == '09-mpr-compare':
                ws.createMprCompareTab(uid, records[1].series_instance_uid)
                ready()
                ws.activeViewport._tool_controller.activateTool('mpr-layout')
            elif scene == '03-4d-mpr':
                ws.createTab(uid, '4D CT · 10 phases', '4d')
                ready()
                tab = ws.activeTab
                tab.mprLayout.setLayout('left')
                tab.activeViewport.applyWindowPreset(-500, 1400)
                tab.toolController.activateTool('play')
            elif scene == '13-detached-tabs':
                ws.createTab(uid, 'MR · MPR', 'mpr')
                ready()
                main_tab = ws.activeTab
                main_tab.mprLayout.setLayout('left')
                ws.createTab(uid, 'MR · 原始 Stack', '2d')
                ready()
                moved = ws.activeTab
                moved.activeViewport.autoWindow()
                assert app.windowManager.detachTab(moved.tab_config.tab_id)
                wait(lambda: not app.windowManager._transfers)
                owner = app.windowManager.owner(moved.tab_config.tab_id)
                assert owner.detached and owner.activeTab is moved
                detached_window = app.windowManager.windows[owner.windowId]
                # An owned backdrop excludes other apps from the screenshot.
                backdrop = QWidget(None, Qt.Window | Qt.FramelessWindowHint)
                backdrop.setStyleSheet('background: #081015')
                backdrop.setGeometry(area.x()+10, area.y()+10, min(1460,area.width()-20), min(870,area.height()-30))
                backdrop.show()
                backdrop.raise_()
                pump(200)
                window.resize(1280, 760)
                window.setPosition(area.x()+25, area.y()+25)
                window.raise_()
                detached_window.resize(960, 720)
                detached_window.setPosition(area.x()+min(480,area.width()-980), area.y()+min(130,area.height()-750))
                detached_window.show()
                detached_window.raise_()
                detached_window.requestActivate()
                pump(600)
            else:
                kind = 'mpr' if scene in ('11-mpr-3d-layout','14-oblique-mpr','24-compact-sidebars','25-theme-dark','26-theme-light','27-thick-slab') else 'montage' if scene == '12-mr-montage' else '2d'
                ws.createTab(uid, 'MR · 3D T1', kind)
                ready()
                tab, view = ws.activeTab, ws.activeViewport
                if scene in ('24-compact-sidebars', '25-theme-dark', '26-theme-light'):
                    tab.mprLayout.setLayout('left')
                    tab.toolController.activateTool('mpr-layout')
                    if scene == '24-compact-sidebars':
                        find(window, 'sidebarContainer').setProperty('collapsed', True)
                        app.settingsController.setValue('layout', 'rightPanelCollapsed', True)
                        pump(500)
                        assert find(window, 'sidebarContainer').property('collapsed')
                        assert find(window, 'rightPanel').property('collapsed')
                elif scene == '27-thick-slab':
                    tab.mprLayout.setLayout('left')
                    tab.toolController.activateTool('mip')
                    tab.toolController.setMprProjectionEnabled(True)
                    tab.toolController.setMprProjectionMode('mip')
                    for plane in ('axial', 'coronal', 'sagittal'):
                        tab.toolController.setMprThickness(plane, 20)
                    wait(lambda: not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids)
                elif scene == '14-oblique-mpr':
                    from math import radians
                    from qt_dicom_viewer.model import MprPlane
                    tab.mprLayout.setLayout('left')
                    tab._handle_crosshair_rotation_requested(MprPlane.AXIAL, radians(23))
                    tab._handle_mpr_3d_rotation_requested((1., 0., 0.), radians(12))
                    wait(lambda: not tab._active_mpr_requests and not tab._dirty_mpr_viewport_ids)
                    tab.activeViewport._tool_controller.activateTool('mpr-rotate-3d')
                elif scene == '10-2d-layout':
                    layout = tab.twoDLayout
                    layout.setLayout('2x2')
                    for index, mode in enumerate(('stack', 'axial', 'coronal', 'sagittal')):
                        if index:
                            layout.loadSeries(index, uid)
                            ready()
                        layout.setMode(index, mode)
                        ready()
                    layout.activateCell(0)
                    tab.toolController.activateTool('mpr-layout')
                elif scene == '11-mpr-3d-layout':
                    tab.mprLayout.setLayout('quad')
                    reference = tab.mprLayout.volumeViewport
                    wait(lambda: reference._host is not None and reference._host.backend._initialized)
                    source_id = tab.activeViewport.viewportId
                    reference.setViewFace('A')
                    reference.setZoom(1.0)
                    size = (reference._host.width(), reference._host.height())
                    reference._tools.activateTool('volume-rotate')
                    reference.begin_drag((size[0] * .25, size[1] * .35), size)
                    reference.update_drag((size[0] * .40, size[1] * .43))
                    reference.end_drag()
                    tab.activateViewport(source_id)
                    tab.activeViewport._tool_controller.activateTool('mpr-layout')
                    pump(900)
                elif scene == '12-mr-montage':
                    view.setColumnCount(3)
                    view.toggleDetails()
                    view.applyWindowPreset(105, 210)
                    pump()
                    grid = find(window, 'montageGrid')
                    if grid:
                        grid.setProperty('contentY', 26 * grid.property('cellHeight'))
                    tab.toolController.activateTool('pseudocolor')
                    view.applyColorMap('blackbody')
                    pump(1500)
                else:
                    view.autoWindow()
                    tab.toolController.activateTool('window')
            ready()
            if scene == '22-display-settings':
                ws.openSettings()
                app.settingsController.selectCategory('corners')
            pump(500)
            # Keep tooltips and cursor badges away from image content.
            QTest.mouseMove(window, QPointF(700, 14).toPoint())
            pump(300)
            if scene == '13-detached-tabs':
                rect = backdrop.geometry()
                picture = (QGuiApplication.screenAt(window.position()) or QGuiApplication.primaryScreen()).grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
            else:
                picture = (QGuiApplication.screenAt(window.position()) or QGuiApplication.primaryScreen()).grabWindow(window.winId()) if scene in ('11-mpr-3d-layout','29-volume-crop') else window.grabWindow()
            assert not picture.isNull()
            output.mkdir(parents=True, exist_ok=True)
            assert picture.save(str(output / f'{scene}.png'), 'PNG', 0)
            print(scene, picture.width(), picture.height(), flush=True)
            if scene == '03-4d-mpr':
                from PIL import Image
                from PySide6.QtCore import QBuffer, QByteArray, QIODevice
                from io import BytesIO
                import numpy as np
                frames = []
                original = None
                changed = False
                for index in range(tab.phaseCount):
                    tab.setPhaseIndex(index)
                    wait(lambda: tab.currentPhaseIndex == index and not tab._active_mpr_requests
                         and not tab._dirty_mpr_viewport_ids and tab._rendering_phase_index is None)
                    pixels = tab.activeViewport._modality_pixel
                    if original is None: original = pixels.copy()
                    else: changed |= not np.array_equal(pixels,original,equal_nan=True)
                    pump(80)
                    shot = window.grabWindow()
                    data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.WriteOnly)
                    shot.save(buffer,'PNG')
                    image=Image.open(BytesIO(data.data())).convert('RGB')
                    image.thumbnail((1100,760),Image.Resampling.LANCZOS)
                    frames.append(image)
                assert changed, 'Animation must include actual image changes, not only phase labels'
                palette=frames[0].quantize(colors=192)
                indexed=[im.quantize(palette=palette,dither=Image.Dither.NONE) for im in frames]
                indexed[0].save(output/'03-4d-playback.gif',save_all=True,append_images=indexed[1:],
                                duration=240,loop=0,optimize=True,disposal=2)
                print('03-4d-playback.gif',len(frames),'phases',flush=True)
            elif scene == '11-mpr-3d-layout':
                from capture_release_features import capture_layout_animation
                capture_layout_animation(app, window, output, pump, wait)
            assert not warnings, warnings
        finally:
            if detached_window is not None: detached_window.hide()
            if backdrop is not None: backdrop.close()
            window.hide()
            app.shutdown()
            delete(engine)
            if pacs_server is not None: pacs_server.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scene', choices=SCENES)
    parser.add_argument('--ct-samples', type=Path)
    args = parser.parse_args()
    if args.scene:
        capture(args.samples.resolve(), args.output.resolve(), args.scene, args.ct_samples)
    else:
        for name in SCENES:
            if name == '03-4d-mpr' and args.ct_samples is None: continue
            subprocess.run([sys.executable, __file__, '--samples', str(args.samples),
                            '--output', str(args.output), '--scene', name,
                            *(['--ct-samples',str(args.ct_samples)] if args.ct_samples else [])], check=True)
