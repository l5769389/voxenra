"""Native 3D loading, idle redraw, tab switching and repeated-close probe.

QT_QPA_PLATFORM=cocoa PYTHONPATH=src:tests:tests/manual python \
    tests/manual/benchmark_volume_loading.py OUTPUT.json [DICOM_DIRECTORY]

Without a directory, use a synthetic 457 x 512 x 512 CT already decoded in the
normal volume cache. With a directory, scan first, then time actual decoding.
VTK imports and directory scanning are excluded from both measurements. No
patient identifiers, paths or screenshots are included in the JSON output.
"""
from importlib.resources import files
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from voxplane.application.series_catalog import SeriesCatalog
from voxplane.core.dicom_scanner import DicomFolderScanner
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import DicomFolderScanSnapshot
from voxplane.service.render_serivce import RenderService
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.svg_icon_provider import SvgIconProvider
from voxplane.ui.volume_render_backend import VolumeRenderBackend


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = Path(sys.argv[1])
    source = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    with TemporaryDirectory(prefix="volume-loading-") as folder:
        folder = Path(folder)
        manager, catalog = VolumeManager(), SeriesCatalog()
        if source is None:
            from benchmark_pet_locator import representative_pair
            series, _ = representative_pair(folder, manager)
            snapshot = DicomFolderScanSnapshot(folder, 457, 457, 0, [series])
        else:
            snapshot = None
            for snapshot in DicomFolderScanner().scan(source):
                pass
            assert snapshot and snapshot.series, "No series found"
            series = max(snapshot.series, key=lambda item: len(item.instances))
        catalog.update(snapshot)
        provider = DicomImageProvider()
        workspace = WorkspaceController(catalog, provider)
        service = RenderService(catalog, manager)
        workspace.renderRequested.connect(service.submit)
        workspace.renderCancelled.connect(service.cancel)
        service.rendered.connect(workspace.handleRenderResult)
        service.failed.connect(workspace.handleRenderFailure)
        errors, warnings, timings = [], [], []
        service.failed.connect(errors.append)
        view = QQuickView()
        view.engine().addImageProvider("dicom", provider)
        view.engine().addImageProvider("navigation", SvgIconProvider())
        view.engine().warnings.connect(lambda es: warnings.extend(e.toString() for e in es))
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        view.resize(1100, 800)
        qml_dir = files("voxplane").joinpath("qml/sections/center/viewportArea")
        scene = folder / "Loading.qml"
        scene.write_text('''import QtQuick
import "'''+QUrl.fromLocalFile(str(qml_dir)).toString()+'''" as Views
Rectangle {
    required property var workspace
    color: "black"
    Views.VolumeViewport {
        anchors.fill: parent
        viewportController: workspace.activeViewport
        visible: !!workspace.activeViewport
    }
}''')
        view.setInitialProperties({"workspace": workspace})
        view.setSource(QUrl.fromLocalFile(str(scene)))
        assert view.status() == QQuickView.Ready
        view.show()
        QTest.qWait(100)
        cycle = -1
        originals = {}
        for name in ("set_volume", "render"):
            original = getattr(VolumeRenderBackend, name)
            originals[name] = original
            def wrapped(self, *args, _original=original, _name=name, **kwargs):
                start = time.perf_counter()
                result = _original(self, *args, **kwargs)
                timings.append({"cycle": cycle, "step": _name,
                                "ms": round((time.perf_counter()-start)*1000, 3)})
                return result
            setattr(VolumeRenderBackend, name, wrapped)
        gaps = []
        last_tick = time.perf_counter()
        def tick():
            nonlocal last_tick
            now = time.perf_counter()
            gaps.append((now-last_tick)*1000)
            last_tick = now
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(tick)
        timer.start()
        def until(predicate):
            deadline = time.monotonic()+45
            while not predicate() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
                assert not errors, str(errors)
            assert predicate(), "Timed out waiting for native view"
        def frame_count():
            return sum(t["step"] == "render" for t in timings)
        cycles = []
        try:
            # Cancel a queued open before the GUI delivers its result.
            workspace.createTab(series.series_instance_uid, "loading probe", "3d")
            cancelled = workspace.activeViewport
            workspace.closeTab(workspace.activeTabId)
            assert cancelled._disposed and cancelled.volume is None
            for cycle in range(3):
                gaps.clear()
                last_tick = time.perf_counter()
                start = last_tick
                workspace.createTab(series.series_instance_uid, "loading probe", "3d")
                controller, tab_id = workspace.activeViewport, workspace.activeTabId
                until(lambda: controller._host is not None and controller._host.data_ready
                      and controller._host.backend._initialized)
                load_ms = (time.perf_counter()-start)*1000
                host = controller._host
                QTest.qWait(300)
                before = frame_count()
                QTest.qWait(300)
                idle_renders = frame_count()-before
                assert idle_renders == 0, "Idle window is repeatedly drawing"
                workspace.openManual()
                QTest.qWait(80)
                assert not host._active
                before = frame_count()
                workspace.activateTabId(tab_id)
                until(lambda: host._active and frame_count() > before)
                image = controller.snapshot_image()
                assert image is not None and not image.isNull()
                shape = list(controller.volume.modality_pixels.shape)
                workspace.closeTab(tab_id)
                QTest.qWait(80)
                assert host._disposed and not host._active
                cycles.append({"cycle": cycle, "ready_ms": round(load_ms, 2),
                               "max_gui_gap_ms": round(max(gaps, default=0), 2),
                               "idle_renders_300ms": idle_renders,
                               "switch_back_export_close": "passed"})
            until(lambda: not service._active)
            assert not errors and not warnings, (errors, warnings)
            report = {"source": "real DICOM" if source else "synthetic cached CT",
                      "shape": shape, "cancel_before_result": "passed", "cycles": cycles,
                      "timings": timings, "qml_warnings": len(warnings),
                      "render_errors": len(errors)}
            output.write_text(json.dumps(report, indent=2)+"\n")
            print(json.dumps(report, indent=2))
        finally:
            timer.stop()
            for name, original in originals.items():
                setattr(VolumeRenderBackend, name, original)
            workspace.shutdown()
            service.shutdown()
            view.close()
            delete(view)
            QTest.qWait(30)


if __name__ == "__main__":
    main()
