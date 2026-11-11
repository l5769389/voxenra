"""Capture every CT preset for one local DICOM series using native Qt/OpenGL.

    PYTHONPATH=src python tests/manual/render_ct_presets.py DICOM_DIR OUTPUT_DIR

Choose a single series/phase. Output contains rendered anatomy, so keep it local.
No source DICOM tags, patient identifiers, or voxel arrays are exported.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from PySide6.QtWidgets import QApplication
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkIOImage import vtkPNGWriter
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter

from voxplane.core.dicom_scanner import _read_instance, _build_series_record
from voxplane.core.volume_manager import VolumeManager
from voxplane.core.volume_view import VolumeViewState
from voxplane.model.volume_models import VolumeDisplayState
from voxplane.ui.volume_render_backend import VolumeRenderBackend
from voxplane.volume_presets import VOLUME_PRESETS


class CaptureWidget(QVTKRenderWindowInteractor):
    def paintEvent(self, event):
        # Match the application's VolumeInteractor: Cocoa paint callbacks must
        # not re-enter VTK while a render is in progress.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dicom_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    paths = sorted(p for p in args.dicom_dir.rglob("*") if p.suffix.lower() == ".dcm")
    instances = [_read_instance(path) for path in paths]
    if len(instances) < 2 or any(i is None for i in instances):
        parser.error("Choose a folder containing at least two readable .dcm slices.")
    if len({i.series_instance_uid for i in instances}) != 1:
        parser.error("Choose one series/phase, not a folder containing multiple series.")
    series = _build_series_record(instances)
    if series.modality.strip().upper() != "CT":
        parser.error("This capture tool requires a CT series.")
    volume = VolumeManager().get_or_build(series)
    app = QApplication([])
    widget = CaptureWidget()
    widget.resize(850, 700)
    widget.show()
    app.processEvents()
    backend = VolumeRenderBackend(widget)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    try:
        backend.set_volume(volume)
        for preset in VOLUME_PRESETS:
            if preset.group == "MR":
                continue
            display = VolumeDisplayState(preset.preset_id, preset.default_window or volume.default_window)
            start = time.perf_counter()
            backend.render(VolumeViewState(), False, display)
            elapsed_ms = (time.perf_counter()-start)*1000
            app.processEvents()
            grab = vtkWindowToImageFilter()
            grab.SetInput(backend.window)
            grab.ReadFrontBufferOff()
            grab.Update()
            image = grab.GetOutput()
            width, height, _ = image.GetDimensions()
            pixels = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(height, width, 3)
            # Center region excludes the orientation marker and most background.
            roi = pixels[height//5:4*height//5, width//5:4*width//5]
            visible = roi.max(axis=-1) > 25
            stats = {
                "render_ms": round(elapsed_ms, 1),
                "visible_pixels": int(visible.sum()),
                "mean_rgb": float(roi[visible].mean()) if visible.any() else 0,
                "mean_channel_spread": float(np.ptp(roi.astype(float), axis=-1)[visible].mean()) if visible.any() else 0,
            }
            results[preset.preset_id] = stats
            writer = vtkPNGWriter()
            writer.SetFileName(str(args.output_dir/(preset.preset_id+".png")))
            writer.SetInputData(image)
            writer.Write()
            print(preset.preset_id, stats, flush=True)
    finally:
        backend.dispose()
        widget.close()
    (args.output_dir/"metrics.json").write_text(json.dumps(results, indent=2)+"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
