"""Capture real Cocoa UI documentation, with synthetic data and isolated settings.

Run from the repository on a native macOS desktop (requires loopback sockets)::

    QT_QPA_PLATFORM=cocoa QT_QUICK_BACKEND=software PYTHONPATH=src:tests \
      .venv/bin/python tests/manual/capture_documentation_20261028.py

The script runs each language in a fresh process, exercises real C-ECHO/FIND/MOVE,
checks saved settings and received pixels, and writes PNG posters plus GIFs.
Nothing is painted over the window captures. The three-instance peer has a
procedurally generated CT phantom; it is demonstration data, not a clinical scan.
"""
from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import numpy as np
from PIL import Image
import pydicom
from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from test_dimse import DimsePeer, SERIES, STUDY
from test_dimse_qml import reveal
from test_tag_qml import click, descendants, find, type_text

ROOT = Path(__file__).resolve().parents[2]


def phantom(peer):
    """Keep peer UIDs/counts while supplying recognizable synthetic CT pixels."""
    y, x = np.mgrid[:256, :256]
    radius = np.hypot(x - 127.5, y - 127.5)
    for index, ds in enumerate(peer.datasets):
        pixels = np.zeros((256, 256), dtype=np.uint16)
        pixels[radius < 108] = 1600
        interior = radius < 102
        pixels[interior] = (1024 + 4 * np.sin(x[interior] / 8) * np.cos(y[interior] / 9)).astype(np.uint16)
        for angle, value in zip(np.linspace(0, 2 * np.pi, 6, endpoint=False), [880, 980, 1040, 1100, 1180, 1400]):
            cx, cy = 127.5 + 65 * np.cos(angle), 127.5 + 65 * np.sin(angle)
            pixels[np.hypot(x - cx, y - cy) < 13 + index] = value
        pixels[np.hypot(x - 127.5, y - 127.5) < 4] = 1700
        ds.Rows = ds.Columns = 256
        ds.PixelSpacing = [1, 1]
        ds.RescaleSlope, ds.RescaleIntercept = 1, -1024
        ds.WindowWidth, ds.WindowCenter = 400, 40
        ds.PatientName, ds.SpecificCharacterSet = '测试^患者', 'ISO_IR 192'
        ds.PixelData = pixels.tobytes()


def capture_locale(output, locale):
    qt = QApplication.instance() or QApplication([])
    assert qt.platformName() == 'cocoa', 'Use a real native Cocoa desktop for documentation.'
    qt.setQuitOnLastWindowClosed(False)
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='voxenra-docs-') as temporary:
        folder = Path(temporary)
        peer = DimsePeer()
        phantom(peer)
        provider = DicomImageProvider()
        app = AppController(provider, settings_path=folder / 'settings.json',
                            pacs_config_path=folder / 'pacs.json', pacs_import_root=folder / 'imports')
        app.languageController.selectLanguage(locale)
        app.workspaceDocumentController.setAutomaticRecovery(False)
        engine = QQmlApplicationEngine()
        engine.addImageProvider('dicom', provider)
        engine.addImageProvider('navigation', SvgIconProvider())
        engine.rootContext().setContextProperty('appController', app)
        warnings = []
        engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
        engine.load(QUrl.fromLocalFile(str(ROOT / 'src/qt_dicom_viewer/qml/Main.qml')))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        window.resize(1280, 820)
        window.show()
        window.requestActivate()
        pacs, ws = app.pacsController, app.workspaceController

        def pump(ms=160):
            until = time.monotonic() + ms / 1000
            while time.monotonic() < until:
                qt.processEvents()
                time.sleep(.005)

        def wait(predicate):
            until = time.monotonic() + 30
            while not predicate() and time.monotonic() < until:
                pump(20)
            assert predicate(), 'Timed out awaiting verified UI/controller state'
            pump()

        def shot(move=True):
            if move:
                QTest.mouseMove(window, QPointF(600, 8).toPoint())
            pump(220)
            # Grab the live native QQuickWindow, preserving modal overlays and
            # drag ghosts; this is not a recreated UI or rendered HTML mockup.
            image = window.grabWindow()
            assert not image.isNull()
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            assert image.save(buffer, 'PNG')
            result = Image.open(BytesIO(bytes(buffer.data()))).convert('RGB')
            result = result.resize((1280, round(result.height * 1280 / result.width)), Image.Resampling.LANCZOS)
            assert np.asarray(result).std() > 10, 'Blank native window capture'
            return result

        def static(name):
            shot().save(output / (name + '.png'), optimize=True)

        def animation(name, frames, durations):
            assert len(frames) == len(durations)
            frames[0].save(output / (name + '.png'), optimize=True)
            # One shared palette keeps static UI colors stable between frames.
            atlas = Image.new('RGB', (frames[0].width, frames[0].height * len(frames)))
            for index, frame in enumerate(frames):
                atlas.paste(frame, (0, index * frame.height))
            palette = atlas.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
            encoded = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
            encoded[0].save(output / (name + '.gif'), save_all=True, append_images=encoded[1:],
                            duration=durations, loop=0, optimize=True, disposal=1)
            with Image.open(output / (name + '.gif')) as saved:
                assert saved.n_frames == len(frames)
            print(locale, name, len(frames), (output / (name + '.gif')).stat().st_size, flush=True)

        def press(name):
            click(window, find(window, name))

        def keys(items):
            return [item['toolType'] for item in items]

        try:
            pump(500)
            find(window, 'sidebarContainer').setProperty('expandedWidth', 215)
            # English preset names need more room to stay legible in the media.
            app.settingsController.setValue('layout', 'rightPanelWidth', 355 if locale == 'en-US' else 265)
            press('sidebarSettings')
            press('pacsAddProfile')
            type_text(window, find(window, 'pacsProfileName'), 'Local synthetic DIMSE')
            press('pacsProfileProtocol')
            QTest.keyClick(window, Qt.Key_Down)
            QTest.keyClick(window, Qt.Key_Return)
            pump()
            for suffix, value in [('Host', '127.0.0.1'), ('Port', str(peer.port)), ('CalledAe', 'LABPACS'),
                                  ('CallingAe', 'VOXENRA'), ('ListenHost', '127.0.0.1'),
                                  ('ListenPort', str(peer.destination))]:
                control = find(window, 'pacsProfile' + suffix)
                reveal(window, control)
                type_text(window, control, value)
            reveal(window, find(window, 'pacsProfileName'))
            press('pacsTestDraft')
            wait(lambda: not pacs.busy)
            assert 'C-ECHO' in pacs.message and not pacs.isError, pacs.message
            assert not pacs.profiles
            static('51-dimse-settings')
            press('pacsSaveProfile')
            wait(lambda: len(pacs.profiles) == 1)
            profile = pacs.profiles[0]
            assert profile['protocol'] == 'dimse' and profile['port'] == peer.port
            assert profile['listen_port'] == peer.destination
            assert 'LABPACS' in (folder / 'pacs.json').read_text()
            press('sidebarPacs')
            frames = [shot()]
            press('pacsQueryStudies')
            wait(lambda: not pacs.busy)
            assert not pacs.isError
            frames.append(shot())
            press('pacsStudy-' + STUDY)
            wait(lambda: not pacs.busy)
            press('pacsSeries-' + SERIES)
            assert pacs.selectedCount == 1
            frames.append(shot())
            # Delay the actual peer transfers so the live receive status is
            # readable. No controller progress/message is fabricated.
            peer.delay = .6
            press('pacsImportSelected')
            wait(lambda: pacs.busy and pacs.progress > 0)
            frames.append(shot())
            wait(lambda: not pacs.busy)
            assert not pacs.isError, pacs.message
            assert ws.activeTabType == '2d'
            wait(lambda: ws.activeLoadState.status == 'ready')
            record = app._series_catalog.get_series(SERIES)
            assert record.dicom_file_count == 3
            received = {str(ds.SOPInstanceUID): ds for ds in map(pydicom.dcmread, (folder / 'imports').rglob('*.dcm'))}
            assert len(received) == 3
            for source in peer.datasets:
                np.testing.assert_array_equal(received[str(source.SOPInstanceUID)].pixel_array, source.pixel_array)
            assert {str(query.QueryRetrieveLevel) for query in peer.requests} >= {'STUDY', 'SERIES', 'IMAGE'}
            pump(600)
            frames.append(shot())
            animation('52-dimse-import', frames, [1000, 1000, 1400, 1200, 2000])
            print(locale, 'C-ECHO/FIND/MOVE: three received instances and pixel identity verified', flush=True)

            view = ws.activeViewport
            before_window = (view.current_window.width, view.current_window.center)
            sidebar, right = find(window, 'sidebarContainer'), find(window, 'rightPanel')
            assert sidebar.isVisible() and right.isVisible()
            frames = [shot()]
            press('toggleViewportMaximize')
            wait(lambda: window.property('maximizedReadingArea'))
            assert not sidebar.isVisible() and not right.isVisible()
            assert ws.activeViewport is view
            frames.append(shot())
            press('toggleViewportMaximize')
            wait(lambda: not window.property('maximizedReadingArea'))
            assert sidebar.isVisible() and right.isVisible()
            assert (view.current_window.width, view.current_window.center) == before_window
            frames.append(shot())
            animation('54-focus-view', frames, [1400, 1900, 1400])

            press('primaryTool-window')
            press('windowFavorite-ct-lung')
            press('windowFavorite-ct-bone')
            favorites = app.settingsController.values['window']['favorites']
            assert favorites == ['ct-lung', 'ct-bone'], favorites
            assert (view.current_window.width, view.current_window.center) == before_window
            assert [preset['presetId'] for preset in app.settingsController.window_presets[:2]] == favorites
            assert SettingsController(path=folder / 'settings.json').values['window']['favorites'] == favorites
            assert find(window, 'windowFavorite-ct-lung').property('checked')
            assert find(window, 'windowFavorite-ct-bone').property('checked')
            assert find(window, 'windowPreset-ct-lung').mapToScene(QPointF()).y() < find(window, 'windowPreset-ct-brain').mapToScene(QPointF()).y()
            static('55-window-favorites')

            press('sidebarSettings')
            app.settingsController.selectCategory('toolbar')
            page = find(window, 'toolbarSettingsPage')
            editor = page.property('editor')
            assert editor.selectedProfile == '2d:ct'
            assert find(window, 'toolbarProfile').property('count') == 6
            frames = [shot()]
            press('toolbarProfile')
            frames.append(shot())
            QTest.keyClick(window, Qt.Key_Escape)
            press('toolbarDetails')
            assert find(window, 'toolbarMode').isVisible() and find(window, 'toolbarCapability').isVisible()
            frames.append(shot())
            source, target = find(window, 'toolbarTile-common-window'), find(window, 'toolbarTile-common-pan')
            start = source.mapToScene(QPointF(source.width() / 2, source.height() / 2)).toPoint()
            end = target.mapToScene(QPointF(target.width() * .8, target.height() / 2)).toPoint()
            QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
            for step in range(1, 13):
                QTest.mouseMove(window, start + (end - start) * step / 12, 15)
            assert find(window, 'toolbarDragPreview').isVisible()
            assert find(window, 'toolbarInsertion-common').isVisible()
            assert keys(editor.commonTools)[:3] == ['window', 'scroll', 'pan']
            frames.append(shot(move=False))
            QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
            pump()
            assert keys(editor.commonTools)[:3] == ['scroll', 'pan', 'window']
            assert editor.dirty
            assert app.settingsController.section('toolbar')['rightProfiles'] == {}
            frames.append(shot())
            press('toolbarSave')
            assert not editor.dirty
            saved = SettingsController(path=folder / 'settings.json').section('toolbar')['rightProfiles']['2d:ct']
            assert saved['common'][:3] == ['scroll', 'pan', 'window']
            frames.append(shot())
            animation('53-toolbar-customization', frames, [1000, 1600, 1400, 1800, 1100, 1500])
            assert not warnings, warnings
            print(locale, 'PASS: focus restore, favorites and toolbar persisted state; zero QML warnings', flush=True)
        finally:
            window.hide()
            app.shutdown()
            delete(engine)
            peer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--locale', choices=('zh-CN', 'en-US'))
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/screenshots')
    args = parser.parse_args()
    if args.locale:
        capture_locale(args.output / 'en' if args.locale == 'en-US' else args.output, args.locale)
    else:
        for language in ('zh-CN', 'en-US'):
            subprocess.run([sys.executable, __file__, '--locale', language, '--output', str(args.output)], check=True)
