"""Desktop acceptance for moving CT, PET and fusion native 3D hosts.

Uses temporary synthetic data/settings only. Run on macOS and Windows separately:
PYTHONPATH=src:tests python tests/manual/smoke_tab_windows.py /tmp/tab-windows
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import time
import traceback

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl, QEvent, QObject
from PySide6.QtGui import QColor, QImage, QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete, isValid

from voxplane.model import DicomFolderScanSnapshot
from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.svg_icon_provider import SvgIconProvider
from smoke_pet_3d import make_pair


def main(output):
    qt = QApplication.instance() or QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    output.mkdir(parents=True, exist_ok=True)

    def pump(ms=100):
        until = time.monotonic() + ms / 1000
        while time.monotonic() < until:
            qt.processEvents()
            qt.sendPostedEvents(None, QEvent.DeferredDelete)
            time.sleep(.005)

    def wait(predicate):
        until = time.monotonic() + 20
        while not predicate() and time.monotonic() < until:
            pump(20)
        assert predicate(), 'Timed out during native tab migration'
        pump()

    with TemporaryDirectory(prefix='voxplane-tab-windows-') as folder:
        root = Path(folder)
        ct, pet = make_pair(root)
        provider = DicomImageProvider()
        app = AppController(provider, settings_path=root/'settings.json',
                            pacs_config_path=root/'pacs.json', pacs_import_root=root/'imports')
        app.workspaceDocumentController.setAutomaticRecovery(False)
        snapshot = DicomFolderScanSnapshot(root, 96, 96, 0, [ct, pet])
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        engine = QQmlApplicationEngine()
        engine.addImageProvider('dicom', provider)
        engine.addImageProvider('navigation', SvgIconProvider())
        engine.rootContext().setContextProperty('appController', app)
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[2]/'src/voxplane/qml/Main.qml')))
        window = engine.rootObjects()[0]
        ws, manager = app.workspaceController, app.windowManager
        callback_errors = []
        previous_hook = sys.excepthook
        sys.excepthook = lambda kind, error, trace: callback_errors.append(''.join(traceback.format_exception(kind, error, trace)))

        def attached(view, target):
            # Fetching QWindow.parent() in PySide can itself invalidate its wrapper
            # when the child closes. Check the actual container and global bounds.
            if not isValid(target) or view._host is None or not view._host.isVisible():
                return False
            container = target.findChild(QObject, 'volumeWindowContainer')
            native = view.nativeWindow
            return (container is not None and container.property('window') is native
                    and not native.isTopLevel()
                    and target.frameGeometry().contains(native.mapToGlobal(QPoint(native.width() // 2, native.height() // 2))))

        def open_tab(series, kind):
            ws.createTab(series.series_instance_uid, 'Synthetic ' + series.modality + ' ' + kind, kind)
            wait(lambda: ws.activeLoadState.status == 'ready')
            return ws.activeTab

        def capture(view, name, target=window):
            image = view.snapshot_image().convertToFormat(QImage.Format_RGB888)
            pixels = np.frombuffer(image.constBits(), np.uint8)
            assert pixels.std() > 3 and np.count_nonzero(pixels > 40) > 1000, 'Empty native render'
            assert image.save(str(output/(name+'.png')))
            # The selection frame must stay outside the native VTK child window.
            frame = target.findChild(QObject, 'volumeViewportFrame')
            assert frame is not None and frame.isVisible()
            chrome = target.grabWindow()
            for point in [QPointF(2, frame.height()/2), QPointF(frame.width()-3, frame.height()/2),
                          QPointF(frame.width()/2, 2), QPointF(frame.width()/2, frame.height()-3)]:
                point = frame.mapToScene(point)
                assert chrome.pixelColor(round(point.x()*chrome.width()/target.width()),
                                         round(point.y()*chrome.height()/target.height())) == QColor('#66d0ff')
            assert chrome.save(str(output/(name+'-window.png')))

        try:
            open_tab(ct, '2d')
            for kind in ('ct', 'pet', 'fusion'):
                if kind == 'fusion':
                    ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
                    wait(lambda: ws.activeLoadState.status == 'ready')
                    ws.createFusionVolumeTab(ws.activeTab)
                    tab = ws.activeTab
                else:
                    tab = open_tab(ct if kind == 'ct' else pet, '3d')
                view = tab.activeViewport
                wait(lambda: attached(view, window))
                view.wheel_zoom(120, 0)
                # A completed crop must survive reparenting and remain undoable.
                widget = view._host.vtk_widget
                if kind != 'fusion':
                    tab.toolController.activateTool('volume-crop')
                    view.setCropMode('outside')
                    points = [QPoint(int(x*widget.width()), int(y*widget.height()))
                              for x, y in ((.05, .05), (.18, .05), (.18, .18), (.05, .18))]
                    QTest.mousePress(widget, Qt.LeftButton, pos=points[0])
                    for point in points[1:]:
                        QTest.mouseMove(widget, point, 25)
                    QTest.mouseRelease(widget, Qt.LeftButton, pos=points[-1])
                    wait(lambda: not view.editBusy)
                    assert view.hasCrop, view.editMessage
                pump(200)
                tab.historyController.capture()
                state, display, host = view.state, view.display_state, view._host
                can_undo = tab.historyController.canUndo
                mask, volume = view.crop_mask.copy() if view.crop_mask is not None else None, view.volume
                capture(view, kind+'-before')
                assert manager.detachTab(tab.tab_config.tab_id)
                session = manager.owner(tab.tab_config.tab_id)
                other = manager.windows[session.windowId]
                wait(lambda: not manager._transfers and attached(view, other))
                assert view._host is host and view.volume is volume
                assert view.state == state and view.display_state == display
                assert np.array_equal(view.crop_mask, mask) and tab.historyController.canUndo == can_undo
                # A late callback from the source page must not hide the destination host.
                stale_owner = QObject()
                view.releaseNativeView(stale_owner)
                assert host.isVisible()
                for theme, locale in (('light', 'en-US'), ('dark', 'zh-CN')):
                    app.settingsController.setValue('appearance', 'theme', theme)
                    app.languageController.selectLanguage(locale)
                    pump(180)
                    assert view.state == state and view._host is host
                capture(view, kind+'-detached', other)
                other.showFullScreen(); pump(500)
                assert other.visibility() == QWindow.FullScreen
                other.showNormal(); pump(500)
                assert view._host is host and np.array_equal(view.crop_mask, mask)
                # Undo/redo must resolve to this window even when focus is in native VTK.
                if kind != 'fusion':
                    other.requestActivate()
                    widget.setFocus(Qt.MouseFocusReason)
                    pump(150)
                    QTest.keyClick(widget, Qt.Key_Z, Qt.ControlModifier)
                    wait(lambda: not view.hasCrop)
                    QTest.keyClick(widget, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
                    wait(lambda: view.hasCrop)
                assert np.array_equal(view.crop_mask, mask)
                manager.moveToMain(tab.tab_config.tab_id)
                wait(lambda: session.windowId not in manager.sessions and attached(view, window))
                assert view._host is host and view.volume is volume and view.state == state
                capture(view, kind+'-returned')
                print('PASS native', kind, 'state, host reuse, themes, fullscreen and return', flush=True)
                ws.closeTab(tab.tab_config.tab_id)
                pump()
            assert not warnings, warnings
            assert not callback_errors, callback_errors
            print('PASS all native tab window checks; no QML warnings', flush=True)
        finally:
            window.hide()
            app.shutdown()
            pump(50)
            delete(engine)
            sys.excepthook = previous_hook


if __name__ == '__main__':
    main(Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/voxplane-tab-windows'))
