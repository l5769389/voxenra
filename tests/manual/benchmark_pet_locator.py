"""Compare locator feedback using real QML and representative decoded volumes.

PYTHONPATH=src python tests/manual/benchmark_pet_locator.py /tmp/pet-locator-after.json
Run the same script with PYTHONPATH pointing to a pre-change source snapshot for
the baseline. CT: 457 x 512 x 512; PET: 104 x 128 x 128, float32. First decode is
excluded: generated volume arrays are injected into the ordinary VolumeManager
cache. Its real fingerprint validation still visits all 561 instance records
(backed by the generated seed DICOM files). No patient data is used.
"""
from collections import Counter
from dataclasses import replace
from importlib.resources import files
import json
from pathlib import Path
import platform
import sys
from tempfile import TemporaryDirectory
import time

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

if __package__:
    from .smoke_pet_3d import make_pair
else:
    from smoke_pet_3d import make_pair
from voxplane.application.series_catalog import SeriesCatalog
from voxplane.core.volume_manager import VolumeManager, series_fingerprint
from voxplane.core.dicom_loader import DicomLoader
from voxplane.model import DicomFolderScanSnapshot, PixelSpacing
from voxplane.service.render_serivce import RenderService
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.svg_icon_provider import SvgIconProvider


def representative_pair(folder, manager):
    seeds = make_pair(folder)
    records = []
    for seed, shape, spacing in zip(seeds, [(457, 512, 512), (104, 128, 128)], [(1., 1.), (4., 456/103)]):
        base = manager.get_or_build(seed)
        depth, rows, columns = shape
        xy_spacing, z_spacing = spacing
        instances = tuple(replace(seed.instances[i % len(seed.instances)],
            sop_instance_uid=seed.series_instance_uid+f".{i+1}", rows=rows, columns=columns,
            pixel_spacing=PixelSpacing(xy_spacing, xy_spacing),
            image_position_patient=(0., 0., i*z_spacing)) for i in range(depth))
        record = replace(seed, instances=instances)
        y, x = np.mgrid[:rows, :columns].astype(np.float32)
        x, y = (x/(columns-1)-.5)*2, (y/(rows-1)-.5)*2
        pixels = np.empty(shape, np.float32)
        for z in range(depth):
            zz = (z/(depth-1)-.5)*2
            if seed.modality == "CT":
                pixels[z] = np.where(x*x+y*y+zz*zz*.3 < .6, 100+300*x+100*zz, -1000)
            else:
                pixels[z] = 8*np.exp(-((x-.2)**2+(y+.1)**2+(zz-.2)**2)/.08)
        geometry = replace(base.geometry, slice_count=depth, rows=rows, columns=columns,
            origin_patient=(0., 0., 0.), row_spacing=xy_spacing,
            column_spacing=xy_spacing, slice_spacing=z_spacing)
        volume = replace(base, modality_pixels=pixels, geometry=geometry,
            suv_pixels=pixels if seed.modality == "PT" else None,
            fingerprint=series_fingerprint(record))
        manager._volumes_by_series_uid[(seed.series_instance_uid, None)] = volume
        records.append(record)
    return records


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    output = Path(sys.argv[1])
    with TemporaryDirectory(prefix="pet-locator-benchmark-") as folder:
        folder = Path(folder)
        manager, catalog = VolumeManager(), SeriesCatalog()
        ct, pet = representative_pair(folder, manager)
        catalog.update(DicomFolderScanSnapshot(folder, 561, 561, 0, [ct, pet]))
        provider = DicomImageProvider()
        workspace = WorkspaceController(catalog, provider)
        service = RenderService(catalog, manager)
        workspace.renderRequested.connect(service.submit)
        service.rendered.connect(workspace.handleRenderResult)
        service.failed.connect(workspace.handleRenderFailure)
        failures = []
        service.failed.connect(failures.append)
        view = QQuickView()
        view.engine().addImageProvider("dicom", provider)
        view.engine().addImageProvider("navigation", SvgIconProvider())
        view.resize(1280, 900)
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        qml_dir = files("voxplane").joinpath("qml/sections/center/viewportArea")
        scene = folder / "Benchmark.qml"
        scene.write_text('''import QtQuick
import "'''+QUrl.fromLocalFile(str(qml_dir)).toString()+'''" as Views
Rectangle {
    required property var workspace
    color: "black"
    Views.ViewportLayout {
        anchors.fill: parent
        viewportController: workspace.activeViewport
        currentTabAllViewports: workspace.currentTabAllViewports
        tabType: "petctfusion"; hasTabs: true
    }
}''')
        warnings = []
        view.engine().warnings.connect(lambda es: warnings.extend(e.toString() for e in es))

        def pump():
            app.processEvents()
            time.sleep(.001)

        def until(predicate):
            deadline = time.monotonic()+30
            while not predicate() and time.monotonic() < deadline:
                pump()
            assert predicate(), "Timed out"

        def children(item):
            yield item
            for child in item.childItems():
                yield from children(child)

        try:
            workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
            tab = workspace.activeTab
            until(lambda: tab.ready)
            view.setInitialProperties({"workspace": workspace})
            view.setSource(QUrl.fromLocalFile(str(scene)))
            assert view.status() == QQuickView.Ready
            view.show()
            for _ in range(80): pump()
            markers = [x for x in children(view.rootObject()) if x.objectName() == "mprCrosshairLayer"]
            marker = markers[2]
            def position():
                return marker.mapToScene(QPointF(marker.property("centerX"), marker.property("centerY")))
            counts, delay = Counter(), [0.]
            request_times, render_ms, completion_ms = {}, [], []
            def count(obj, name, key):
                original = getattr(obj, name)
                def wrapped(*args, **kwargs):
                    counts[key] += 1
                    return original(*args, **kwargs)
                setattr(obj, name, wrapped)
            reconstructor = service._worker._pet_reconstructor
            count(reconstructor.reslicer, "_sample_plane", "sample_planes")
            count(reconstructor, "_full_mip", "mip_projections")
            count(manager, "get_or_build", "volume_validations")
            count(DicomLoader, "apply_window", "window_conversions")
            for v in tab.viewports_by_id.values():
                v.imageSourceChanged.connect(lambda: counts.update(["image_source_updates"]))
                count(v.measurementController, "refresh_roi_metrics", "roi_refreshes")
            set_array = provider.set_array
            def upload(viewport_id, *args):
                before = provider._images[viewport_id].cacheKey()
                set_array(viewport_id, *args)
                counts["image_copies"] += before != provider._images[viewport_id].cacheKey()
            provider.set_array = upload
            render = reconstructor.render
            def measured(request):
                counts["reconstructions"] += 1
                start = time.monotonic()
                time.sleep(delay[0])
                result = render(request)
                render_ms.append((time.monotonic()-start)*1000)
                return result
            reconstructor.render = measured
            def submitted(request):
                counts["submitted"] += 1
                request_times[request.request_id] = time.monotonic()
            workspace.renderRequested.connect(submitted)
            service.rendered.connect(lambda result: completion_ms.append(
                (time.monotonic()-request_times[result.response_id])*1000))
            def summary(values):
                return {"p50": round(float(np.percentile(values, 50)), 3),
                        "p95": round(float(np.percentile(values, 95)), 3),
                        "max": round(float(max(values)), 3)} if values else None
            report = {"platform": platform.platform(), "python": platform.python_version(),
                "source": str(files("voxplane")), "ct_shape": [457, 512, 512],
                "pet_shape": [104, 128, 128], "measurement": "QTest mouse event to actual QML locator position; excludes compositor/vsync", "scenarios": {}}
            for name, artificial_delay, continuous in [("in_plane", 0., False),
                    ("slow_backend", .120, False), ("continuous_slow_backend", .120, True)]:
                counts.clear(); render_ms.clear(); completion_ms.clear()
                delay[0] = artificial_delay
                latency, immediate = [], 0
                press = position().toPoint()+QPoint(12, 0)
                offset = QPointF(press)-position()
                QTest.mousePress(view, Qt.LeftButton, pos=press, delay=0)
                steps = 100 if continuous else 30
                for i in range(steps):
                    # Each target is separated by more than the match tolerance.
                    target = press + QPoint(20+(i*7)%42, 15+(i%5)*4)
                    expected = QPointF(target)-offset
                    start = time.monotonic()
                    QTest.mouseMove(view, target, delay=0)
                    matches = lambda: (position()-expected).manhattanLength() < 2
                    if matches(): immediate += 1
                    if continuous:
                        if matches(): latency.append((time.monotonic()-start)*1000)
                        until_time = start+.008
                        while time.monotonic() < until_time: pump()
                    else:
                        until(matches)
                        latency.append((time.monotonic()-start)*1000)
                QTest.mouseRelease(view, Qt.LeftButton, pos=target, delay=0)
                until(lambda: tab._requested == tab._committed_request)
                report["scenarios"][name] = {"events": steps, "artificial_delay_ms": artificial_delay*1000,
                    "immediate_feedback_events": immediate, "feedback_ms": summary(latency),
                    "render_ms": summary(render_ms), "request_to_presented_batch_ms": summary(completion_ms),
                    "counts": dict(counts)}
            counts.clear(); render_ms.clear(); completion_ms.clear(); delay[0] = 0
            plane_latencies = []
            for i in range(12):
                center = np.array(tab._target_mpr_state.frame.center_patient)
                start = time.monotonic()
                tab.move_center(tuple(center+[0, 0, .37]))
                until(lambda: tab._requested == tab._committed_request)
                plane_latencies.append((time.monotonic()-start)*1000)
            report["scenarios"]["subvoxel_plane_change"] = {
                "events": 12, "image_update_ms": summary(plane_latencies), "counts": dict(counts)}
            assert not warnings and not failures, (warnings, failures)
            output.write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2), flush=True)
        finally:
            service.shutdown()
            view.hide()
            delete(view)
            workspace.shutdown()


if __name__ == "__main__":
    main()
