"""Measure MPR rotation sampling and real QML mouse drags using synthetic CT.

PYTHONPATH=src python tests/manual/benchmark_mpr_rotation.py /tmp/mpr-after.json
For an A/B comparison add --reslicer-source /tmp/pre-change-mpr_reslicer.py.
The baseline changes only the reslicer; volume, grids, pointer path, render
scheduler, and QML remain identical. Run on a desktop with QT_QPA_PLATFORM=cocoa
(macOS) or windows. Decoding is excluded; the normal worker validates cached
volumes, resamples, windows, and uploads images. No patient data is used.
"""
import argparse
from importlib.resources import files
import importlib.util
import json
from math import cos, sin
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
import time
import tracemalloc

import numpy as np
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from benchmark_pet_locator import representative_pair
from voxplane.application.series_catalog import SeriesCatalog
from voxplane.core.mpr_reslicer import MprReslicer
from voxplane.core.mpr_rotation import rotate_crosshair_state, rotate_mpr_state_3d, resolve_sampling_basis
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import DicomFolderScanSnapshot, MprPlane, MprFrame, MprState, TabType
from voxplane.service.render_serivce import RenderService
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.svg_icon_provider import SvgIconProvider


def summary(values):
    return dict(median=float(np.median(values)), p95=float(np.percentile(values, 95))) if values else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--reslicer-source', type=Path)
    args = parser.parse_args()
    sampler = MprReslicer
    if args.reslicer_source:
        spec = importlib.util.spec_from_file_location('mpr_baseline', args.reslicer_source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sampler = module.MprReslicer
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = dict(platform=platform.platform(), qt_platform=app.platformName(),
                  numpy=np.__version__, reslicer=str(args.reslicer_source or 'working tree'),
                  scenarios={})
    with TemporaryDirectory(prefix='mpr-rotation-benchmark-') as temp:
        folder = Path(temp)
        manager, catalog = VolumeManager(), SeriesCatalog()
        ct, _ = representative_pair(folder, manager)
        catalog.update(DicomFolderScanSnapshot(folder, 457, 457, 0, [ct]))
        volume = manager.get_or_build(ct)
        reslicer = sampler()
        initial = MprState(MprFrame.standard_lps(volume.geometry.center_patient),
                           view_grids=reslicer.create_view_grids(volume))
        report['volume_shape'] = list(volume.modality_pixels.shape)
        report['grids'] = {p.value: [initial.view_grids.for_plane(p).rows,
                                    initial.view_grids.for_plane(p).columns] for p in MprPlane}
        for kind in ('crosshair', '3d'):
            timings = []
            state = initial
            for i in range(33):
                plane = list(MprPlane)[i % 3]
                normal = resolve_sampling_basis(state, plane).navigation_direction_patient
                state = (rotate_crosshair_state(state, plane, .04) if kind == 'crosshair'
                         else rotate_mpr_state_3d(state, normal, .04))
                planes = [p for p in MprPlane if p != plane or kind == '3d']
                start = time.perf_counter()
                for p in planes:
                    reslicer.reslice(volume, p, state.frame, state.view_rolls.for_plane(p),
                                     state.view_grids.for_plane(p))
                if i >= 3:
                    timings.append((time.perf_counter() - start) * 1000)
            tracemalloc.start()
            for p in planes:
                reslicer.reslice(volume, p, state.frame, state.view_rolls.for_plane(p),
                                 state.view_grids.for_plane(p))
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            report['scenarios'][kind + '_sampling'] = dict(batch_ms=summary(timings),
                                                          peak_temporary_mib=peak / 1024**2)

        provider = DicomImageProvider()
        workspace = WorkspaceController(catalog, provider)
        service = RenderService(catalog, manager)
        service._worker._mpr_reslicer = sampler()
        workspace.renderRequested.connect(service.submit)
        service.rendered.connect(workspace.handleRenderResult)
        service.failed.connect(workspace.handleRenderFailure)
        failures, warnings = [], []
        service.failed.connect(failures.append)
        view = QQuickView()
        view.engine().addImageProvider('dicom', provider)
        view.engine().addImageProvider('navigation', SvgIconProvider())
        view.engine().warnings.connect(lambda es: warnings.extend(e.toString() for e in es))
        view.resize(1280, 900)
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        qml_dir = files('voxplane').joinpath('qml/sections/center/viewportArea')
        scene = folder / 'Benchmark.qml'
        scene.write_text('''import QtQuick
import "''' + QUrl.fromLocalFile(str(qml_dir)).toString() + '''" as Views
Rectangle {
    required property var workspace
    color: "black"
    Views.ViewportLayout {
        anchors.fill: parent
        viewportController: workspace.activeViewport
        currentTabAllViewports: workspace.currentTabAllViewports
        tabType: "mpr"; hasTabs: true
    }
}''')

        def pump():
            app.processEvents()
            time.sleep(.001)

        def until(predicate):
            deadline = time.monotonic() + 30
            while not predicate() and time.monotonic() < deadline:
                pump()
            assert predicate(), 'Timed out'

        def children(item):
            yield item
            for child in item.childItems():
                yield from children(child)

        try:
            workspace.createTab(ct.series_instance_uid, 'Synthetic CT', TabType.MPR)
            tab = workspace.activeTab
            settled = lambda: (tab._target_mpr_state is not None and not tab._active_mpr_requests
                               and not tab._dirty_mpr_viewport_ids)
            until(settled)
            view.setInitialProperties({'workspace': workspace})
            view.setSource(QUrl.fromLocalFile(str(scene)))
            assert view.status() == QQuickView.Ready
            view.show()
            for _ in range(100):
                pump()
            markers = [x for x in children(view.rootObject()) if x.objectName() == 'mprCrosshairLayer']
            assert len(markers) == 3
            requests, completions, uploads, swaps = {}, [], [], []
            service.rendered.connect(lambda r: completions.append((time.perf_counter()-requests[r.response_id])*1000))
            workspace.renderRequested.connect(lambda r: requests.__setitem__(r.request_id, time.perf_counter()))
            for viewport in tab.viewports_by_id.values():
                viewport.imageSourceChanged.connect(lambda: uploads.append(time.perf_counter()))
            view.frameSwapped.connect(lambda: swaps.append(time.perf_counter()))
            for kind in ('crosshair', '3d'):
                for source_index, marker in enumerate(markers):
                    tab._handle_tool_command('viewport:reset')
                    until(settled)
                    for _ in range(30):
                        pump()
                    tab.toolController.activateTool('mpr-rotate-3d' if kind == '3d' else 'window')
                    center = marker.mapToScene(QPointF(marker.property('centerX'), marker.property('centerY')))
                    # Crosshair hit starts on a line; 3D starts away from both lines.
                    angle0 = .65 if kind == '3d' else 0.
                    radius = 80
                    point = lambda a: (center + QPointF(radius*cos(a), radius*sin(a))).toPoint()
                    press = point(angle0)
                    before = tab._target_mpr_state
                    completions.clear(); uploads.clear(); swaps.clear()
                    QTest.mousePress(view, Qt.LeftButton, pos=press, delay=0)
                    input_ms = []
                    start = time.perf_counter()
                    for i in range(1, 61):
                        t = time.perf_counter()
                        target = point(angle0 + .9*i/60)
                        QTest.mouseMove(view, target, delay=0)
                        input_ms.append((time.perf_counter()-t)*1000)
                        deadline = t + .008
                        while time.perf_counter() < deadline:
                            pump()
                    QTest.mouseRelease(view, Qt.LeftButton, pos=target, delay=0)
                    released = time.perf_counter()
                    until(settled)
                    final_ms = (time.perf_counter()-released)*1000
                    assert tab._target_mpr_state != before, (kind, source_index, 'drag did not rotate')
                    for viewport in tab.viewports_by_id.values():
                        expected = resolve_sampling_basis(tab._target_mpr_state, viewport.viewport_config.viewport_type)
                        geometry = viewport._plane_geometry
                        np.testing.assert_allclose(geometry.row_direction_patient, expected.row_direction_patient, atol=1e-7)
                        np.testing.assert_allclose(geometry.column_direction_patient, expected.column_direction_patient, atol=1e-7)
                    # A final frame must still paint after release.
                    n = len(swaps)
                    view.update()
                    until(lambda: len(swaps) > n)
                    report['scenarios'][f'{kind}_qml_view_{source_index}'] = dict(
                        events=60, input_ms=summary(input_ms), request_to_image_ms=summary(completions),
                        image_uploads=len(uploads), painted_frames=len(swaps),
                        final_settle_ms=final_ms, duration_ms=(time.perf_counter()-start)*1000)
            assert not failures and not warnings, (failures, warnings)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            view.grabWindow().save(str(args.output.with_suffix('.png')))
            args.output.write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2), flush=True)
        finally:
            service.shutdown()
            view.hide()
            delete(view)
            workspace.shutdown()


if __name__ == '__main__':
    main()
