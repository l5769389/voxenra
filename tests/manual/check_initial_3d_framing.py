"""Native initial framing QA using synthetic DICOM, without writing preferences.

QT_QPA_PLATFORM=cocoa QT_QUICK_BACKEND=software .venv/bin/python \
    tests/manual/check_initial_3d_framing.py /tmp/initial-3d-framing
"""
import sys
import time
from importlib.resources import files
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from smoke_3d import make_series

from voxplane.app import bind_controller
from voxplane.model import DicomFolderScanSnapshot
from voxplane.ui.controller.settings_controller import SettingsController


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    original_init = SettingsController.__init__
    with patch.object(SettingsController, '__init__',
                      lambda self, parent=None, **kwargs: original_init(self, parent, path=False)):
        engine = bind_controller()
    controller = engine.app_controller
    warnings, errors = [], []
    engine.warnings.connect(lambda items: warnings.extend(i.toString() for i in items))
    engine.load(files('voxplane').joinpath('qml/Main.qml'))
    root = engine.rootObjects()[0]
    workspace = controller.workspaceController

    def pump(duration=.2):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)

    def check(view, name):
        deadline = time.monotonic() + 15
        while view.loadState != 'ready' and time.monotonic() < deadline:
            pump(.05)
        assert view.loadState == 'ready', view.errorMessage
        pump(.8)
        host = view._host
        assert host and host.isVisible() and host.backend._initialized
        renderer = host.backend.renderer
        width, height = host.backend.window.GetSize()
        g = view.volume.geometry
        projected = []
        for k, j, i in product((0, g.slice_count-1), (0, g.rows-1), (0, g.columns-1)):
            point = g.voxel_to_patient @ [k, j, i, 1]
            renderer.SetWorldPoint(*point)
            renderer.WorldToDisplay()
            x, y, _ = renderer.GetDisplayPoint()
            projected.extend((abs(2*x/width-1), abs(2*y/height-1)))
        assert .86 < max(projected) < .88, (name, max(projected))
        image = view.snapshot_image()
        assert not image.isNull() and image.save(str(output / (name + '.png')))
        print(f'{name}: {width}x{height}, limiting grid occupancy {max(projected):.3f}', flush=True)

    def exercise():
        try:
            with TemporaryDirectory(prefix='framing-qa-') as folder:
                series = make_series(Path(folder))
                controller._series_catalog.update(DicomFolderScanSnapshot(
                    Path(folder), 48, 48, 0, [series]))
                root.resize(1440, 900)
                workspace.createTab(series.series_instance_uid, 'Framing QA', '3d')
                check(workspace.activeViewport, 'standalone-3d')
                workspace.createTab(series.series_instance_uid, 'Framing QA MPR', 'mpr')
                tab = workspace.activeTab
                tab.mprLayout.setLayout('quad')
                check(tab.mprLayout.volumeViewport, 'quad-3d')
                root.resize(1280, 720)
                pump()
                check(tab.mprLayout.volumeViewport, 'quad-3d-minimum-window')
                assert not warnings, warnings
        except BaseException as error:  # noqa: BLE001 - report failures outside the Qt callback
            import traceback
            traceback.print_exc()
            errors.append(error)
        finally:
            controller.shutdown()
            root.close()
            app.quit()

    QTimer.singleShot(100, exercise)
    app.exec()
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
