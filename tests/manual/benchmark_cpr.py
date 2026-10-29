"""Reproduce the CPR core's synthetic timing/length evidence (no patient data).

Run: .venv/bin/python tests/manual/benchmark_cpr.py build/cpr-core-benchmark.json
This measures numerical sampling only, excluding decoding and any GUI work.
"""
import argparse
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_mpr_reslicer import _volume
from qt_dicom_viewer.model.cpr import CprPath, CprSettings
from qt_dicom_viewer.core.cpr_geometry import sample_centerline
from qt_dicom_viewer.core.cpr_reslicer import CprReslicer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    z, y, x = np.indices((160, 128, 128), dtype=np.float32)
    volume = _volume(2*x - 3*y + .5*z, slice_spacing=.8, row_spacing=.7, column_spacing=.7)
    path = CprPath("benchmark", "Benchmark", ((10, 30, 50), (35, 38, 65), (60, 30, 80), (75, 40, 90)))
    reslicer = CprReslicer()
    evidence = []
    for mode, thickness in (("thin", 0), ("mip", 5), ("mean", 5)):
        settings = CprSettings(step_mm=.25, width_mm=40, projection=mode, thickness_mm=thickness)
        durations = []
        for _ in range(5):
            started = time.perf_counter()
            result = reslicer.reslice(volume, path, settings)
            durations.append(time.perf_counter() - started)
        evidence.append(dict(mode=mode, thickness_mm=thickness, shape=list(result.modality_pixels.shape),
                             median_seconds=float(np.median(durations))))
    started = time.perf_counter()
    section = reslicer.cross_section(volume, result.centerline, 100, width_mm=40, step_mm=.25)
    evidence.append(dict(mode="cross_section", shape=list(section.modality_pixels.shape), seconds=time.perf_counter()-started))
    angles = np.linspace(0, 1.5*np.pi, 301)
    for pitch in (0., 3.):
        points = np.column_stack((10*np.cos(angles), 10*np.sin(angles), pitch*angles))
        line = sample_centerline(CprPath("q", "q", points), CprSettings(step_mm=.2))
        exact = float(np.hypot(10, pitch)*1.5*np.pi)
        evidence.append(dict(mode="circle" if pitch == 0 else "helix", length_mm=line.length_mm,
                             analytic_length_mm=exact, relative_error=abs(line.length_mm-exact)/exact))
    report = dict(platform=platform.platform(), python=platform.python_version(), numpy=np.__version__,
                  volume_shape=list(volume.modality_pixels.shape), scenarios=evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
